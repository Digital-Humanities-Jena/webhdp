#!/usr/bin/env python3
"""Offline Link deployment preflight. Never imports app, contacts services or mutates state.

Read an operator-reviewed JSON plan and `docker compose config --format json`
from stdin. Output contains field paths/error codes only, never configuration
values or rendered secrets. A pass verifies static consistency, not live readiness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.webhdp_link_openapi import document

LIMIT = 4 * 1024 * 1024
PIN = re.compile(r"^[^\s]+@sha256:[a-f0-9]{64}$")
DIGEST = re.compile(r"^[a-f0-9]{64}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
SECRET_KEYS = {"password", "token", "access_token", "refresh_token", "api_key", "secret_key", "credential_encryption_key"}


def read_json(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('document_too_large')
    return json.loads(raw), raw


def mapping(value):
    return value if isinstance(value, dict) else {}


def sequence(value):
    return value if isinstance(value, list) else []


def populated(value):
    return isinstance(value, str) and bool(value.strip()) and not any(
        part in value.lower() for part in ('replace_me', 'changeme', '<', '>', '@service_', '@webhdp_', 'example.org', 'example.com'))


def safe_url(value, *, origin=False, allow_loopback=False):
    if not populated(value) or any(c.isspace() for c in value) or '*' in value or '\\' in value:
        return False
    try:
        parts = urlsplit(value)
        parts.port  # Also reject malformed or out-of-range ports.
    except ValueError:
        return False
    if not parts.hostname or parts.username is not None or parts.password is not None or '#' in value:
        return False
    if parts.hostname in LOOPBACK:
        if not allow_loopback or parts.scheme not in {'http', 'https'}:
            return False
    elif parts.scheme != 'https':
        return False
    if origin:
        return value == f'{parts.scheme}://{parts.netloc}'
    return not any(key in {'code', 'state', 'error', 'iss'} for key, _ in parse_qsl(parts.query, keep_blank_values=True))


def origin_of(value):
    try:
        parts = urlsplit(value)
        return f'{parts.scheme}://{parts.netloc}'
    except (ValueError, TypeError):
        return None


def contract_errors(value, schema, spec):
    """Check the structural subset used by Link's request schemas, offline.

    This is not a general JSON Schema implementation. The API remains the
    authority for native bindings and scalar parameter semantics. Reject newly
    introduced validation keywords rather than silently ignoring them.
    """
    if '$ref' in schema:
        schema = spec['components']['schemas'][schema['$ref'].rsplit('/', 1)[-1]]
    supported = {'type', 'properties', 'additionalProperties', 'required', 'items', 'minItems', 'maxItems', 'uniqueItems',
                 'minProperties', 'maxProperties', 'minimum', 'maximum', 'minLength', 'maxLength', 'pattern', 'enum',
                 'const', 'description', 'title', 'default', 'format'}
    if set(schema) - supported:
        yield 'unsupported_contract_keyword'
    types = {'object': dict, 'array': list, 'string': str, 'integer': int, 'number': (int, float), 'boolean': bool}
    typ = schema.get('type')
    if typ and (not isinstance(value, types.get(typ, ())) or (typ in {'number', 'integer'} and type(value) is bool)):
        yield 'type'
        return
    if 'enum' in schema and value not in schema['enum']:
        yield 'enum'
    if 'const' in schema and value != schema['const']:
        yield 'const'
    if isinstance(value, dict):
        properties = schema.get('properties', {})
        if any(key not in value for key in schema.get('required', [])):
            yield 'required'
        if schema.get('additionalProperties') is False and set(value) - set(properties):
            yield 'additionalProperties'
        for key, item in value.items():
            child = properties.get(key, schema.get('additionalProperties', {}))
            if isinstance(child, dict):
                yield from contract_errors(item, child, spec)
    elif isinstance(value, list):
        if schema.get('uniqueItems') and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            yield 'uniqueItems'
        for item in value:
            yield from contract_errors(item, schema.get('items', {}), spec)
    elif isinstance(value, str) and 'pattern' in schema and not re.search(schema['pattern'], value):
        yield 'pattern'
    for low, high, count in (('minItems', 'maxItems', len(value) if isinstance(value, list) else None),
                             ('minProperties', 'maxProperties', len(value) if isinstance(value, dict) else None),
                             ('minLength', 'maxLength', len(value) if isinstance(value, str) else None),
                             ('minimum', 'maximum', value if type(value) in (int, float) else None)):
        if count is not None:
            if low in schema and count < schema[low]:
                yield low
            if high in schema and count > schema[high]:
                yield high


def validate(plan, compose, directory, *, repository=ROOT):
    """Return sanitized findings. All input, including malformed nested fields, is untrusted."""
    errors = []
    warnings = []

    def require(condition, path, code):
        if not condition:
            errors.append({'path': path, 'code': code})
        return bool(condition)

    def number(value, path, lo, hi):
        if require(type(value) is int and lo <= value <= hi, path, 'integer_out_of_range'):
            return value
        return lo

    def reference(value, path):
        return require(populated(value), path, 'operator_reference_required')

    def schema(value, name, path):
        spec = document('')
        for code in contract_errors(value, spec['components']['schemas'][name], spec):
            errors.append({'path': path, 'code': 'api_schema_' + code})

    def no_secrets(value, path):
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in SECRET_KEYS:
                    errors.append({'path': path, 'code': 'inline_secret_field_forbidden'})
                else:
                    no_secrets(item, path)
        elif isinstance(value, list):
            for item in value:
                no_secrets(item, path)

    def hashed_file(entry, file_key, hash_key, path):
        filename = entry.get(file_key)
        digest = entry.get(hash_key)
        if not require(populated(filename) and isinstance(digest, str) and bool(DIGEST.fullmatch(digest)), path, 'reviewed_file_and_sha256_required'):
            return {}
        try:
            content, raw = read_json(Path(directory) / filename)
        except (OSError, ValueError, TypeError):
            require(False, path, 'reviewed_file_unreadable')
            return {}
        require(hashlib.sha256(raw).hexdigest() == digest, path, 'reviewed_file_hash_mismatch')
        no_secrets(content, path)
        require(isinstance(content, dict), path, 'object_required')
        return mapping(content)

    require(isinstance(plan, dict), '/', 'object_required')
    plan = mapping(plan)
    no_secrets(plan, '/')
    require(plan.get('schema_version') == 1, '/schema_version', 'unsupported_schema')
    deployment = mapping(plan.get('deployment'))
    for field in ('public_base_url', 'frontend_url'):
        require(safe_url(deployment.get(field), origin=True), '/deployment/' + field, 'exact_https_origin_required')
    # Shipped production nginx CSP uses connect-src self; split-origin frontend
    # requires a separate reviewed CSP/build configuration, not this overlay.
    require(deployment.get('public_base_url') == deployment.get('frontend_url'), '/deployment', 'shipped_frontend_requires_same_origin')
    for field in ('backend_image', 'frontend_image'):
        require(isinstance(deployment.get(field), str) and bool(PIN.fullmatch(deployment[field])), '/deployment/' + field, 'immutable_image_digest_required')

    worker = mapping(plan.get('worker'))
    replicas = number(worker.get('replicas'), '/worker/replicas', 1, 64)
    concurrency = number(worker.get('global_concurrency'), '/worker/global_concurrency', 1, 64)
    require(replicas <= concurrency, '/worker/replicas', 'replicas_exceed_global_limit')
    hpc_wait = number(worker.get('hpc_wait_seconds'), '/worker/hpc_wait_seconds', 1, 604800)
    partition_wait = number(worker.get('partition_attempt_timeout_seconds'), '/worker/partition_attempt_timeout_seconds', 1, 604800)
    require(hpc_wait >= partition_wait, '/worker/hpc_wait_seconds', 'link_wait_shorter_than_partition_wait')
    grace = number(worker.get('stop_grace_seconds'), '/worker/stop_grace_seconds', 1, 31536000)

    storage = mapping(plan.get('storage'))
    require(storage.get('link_path') == '/app/instance/webhdp-link', '/storage/link_path', 'overlay_storage_path_mismatch')
    require(storage.get('quota_enforcement') in {'filesystem', 'container_volume'}, '/storage/quota_enforcement', 'hard_runtime_quota_plan_required')
    for field in ('quota_reference', 'backup_restore_reference', 'retention_owner'):
        reference(storage.get(field), '/storage/' + field)
    require(storage.get('retention_mode') == 'manual_review', '/storage/retention_mode', 'automatic_link_purge_not_implemented')
    number(storage.get('review_after_days'), '/storage/review_after_days', 1, 3650)
    warnings.append({'path': '/storage', 'code': 'verify_hard_quota_backup_restore_and_manual_retention_on_target'})

    authority = mapping(plan.get('hpc_authority'))
    publications = sequence(plan.get('publications'))
    require(bool(publications), '/publications', 'reviewed_publication_required')
    ids = set()
    uses_hpc = False
    max_runtime = 0
    for index, value in enumerate(publications):
        path = f'/publications/{index}'
        entry = mapping(value)
        publication = hashed_file(entry, 'request_file', 'sha256', path)
        inventory = hashed_file(entry, 'native_inventory_file', 'native_inventory_sha256', path + '/native_inventory')
        schema(publication, 'PublicationCreate', path)
        pid = publication.get('id')
        require(isinstance(pid, str) and pid not in ids, path, 'unique_publication_id_required')
        if isinstance(pid, str):
            ids.add(pid)
        require(publication.get('enabled') is False, path, 'stage_publications_disabled')
        for field in ('pipeline_identifier', 'pipeline_version'):
            require(populated(publication.get(field)) and inventory.get(field) == publication.get(field), path + '/' + field, 'native_inventory_mismatch')
        steps = sequence(inventory.get('steps'))
        require(bool(steps), path + '/native_inventory/steps', 'pinned_native_steps_required')
        step_ids = set()
        needs_hpc = False
        for step_index, raw_step in enumerate(steps):
            step = mapping(raw_step)
            spath = path + f'/native_inventory/steps/{step_index}'
            for key in ('id', 'component', 'version'):
                require(populated(step.get(key)), spath, 'pinned_step_identity_required')
            require(isinstance(step.get('manifest_sha256'), str) and bool(DIGEST.fullmatch(step['manifest_sha256'])), spath, 'manifest_digest_required')
            require(step.get('adapter') in {'local_cli', 'container_cli', 'hpc_link'}, spath, 'unsupported_adapter')
            needs_hpc |= step.get('adapter') == 'hpc_link'
            sid = step.get('id')
            require(isinstance(sid, str) and sid not in step_ids, spath, 'duplicate_step_id')
            if isinstance(sid, str):
                step_ids.add(sid)
        inp = mapping(publication.get('input'))
        count = number(inp.get('max_files'), path + '/input/max_files', 1, 1000)
        minimum = number(inp.get('min_files'), path + '/input/min_files', 1, 1000)
        require(minimum <= count, path + '/input', 'file_count_order')
        timeout = number(publication.get('step_timeout_seconds'), path + '/step_timeout_seconds', 1, 43200)
        runtime = timeout * len(steps) * (count if publication.get('execution_mode') == 'record' else 1)
        hpc = mapping(publication.get('hpc'))
        require(not needs_hpc or hpc.get('enabled') is True, path + '/hpc', 'hpc_policy_required')
        if hpc.get('enabled') is True:
            uses_hpc = True
            walltime = number(hpc.get('walltime_hours'), path + '/hpc/walltime_hours', 1, 168)
            gpu_count = number(hpc.get('gpu_count'), path + '/hpc/gpu_count', 0, 8)
            require(hpc.get('partition') in sequence(authority.get('allowed_partitions')), path + '/hpc/partition', 'partition_outside_central_authority')
            require(gpu_count == 0 or hpc.get('gpu_type') in sequence(authority.get('allowed_gpu_types')), path + '/hpc/gpu_type', 'gpu_type_outside_central_authority')
            require(gpu_count <= number(authority.get('max_gpus'), '/hpc_authority/max_gpus', 0, 8), path + '/hpc/gpu_count', 'gpu_count_exceeds_authority')
            require(walltime <= number(authority.get('max_walltime_hours'), '/hpc_authority/max_walltime_hours', 1, 168), path + '/hpc/walltime_hours', 'walltime_exceeds_authority')
            require(runtime + 300 <= walltime * 3600, path + '/hpc/walltime_hours', 'walltime_shorter_than_pipeline_bound')
            require(not hpc.get('reuse_retained_allocation') or hpc.get('retain_allocation') is True, path + '/hpc', 'reuse_requires_retention')
            if hpc.get('retain_allocation'):
                reference(entry.get('retained_allocation_owner'), path + '/retained_allocation_owner')
            runtime += hpc_wait
        max_runtime = max(max_runtime, runtime + 300)
    require(grace >= max_runtime, '/worker/stop_grace_seconds', 'grace_shorter_than_whole_job_bound')
    if uses_hpc:
        reference(authority.get('policy_reference'), '/hpc_authority/policy_reference')
        warnings.append({'path': '/hpc_authority', 'code': 'verify_principal_permissions_runtime_pins_and_scheduler_limits_on_target'})

    clients = sequence(plan.get('clients'))
    require(bool(clients), '/clients', 'client_required')
    client_ids = set()
    for index, raw_client in enumerate(clients):
        path = f'/clients/{index}'
        client = mapping(raw_client)
        reg = mapping(client.get('registration'))
        schema(reg, 'ClientCreate', path + '/registration')
        cid = reg.get('id')
        require(isinstance(cid, str) and bool(IDENTIFIER.fullmatch(cid)) and cid not in client_ids, path, 'unique_client_id_required')
        if isinstance(cid, str):
            client_ids.add(cid)
        require(reg.get('enabled') is False, path, 'stage_clients_disabled')
        allow_local = client.get('allow_loopback') is True
        if allow_local:
            reference(client.get('loopback_reason'), path + '/loopback_reason')
            warnings.append({'path': path, 'code': 'explicit_loopback_exception_requires_desktop_or_local_app_review'})
        origins = sequence(reg.get('origins'))
        callbacks = sequence(reg.get('redirect_uris'))
        require(bool(origins) and bool(callbacks), path, 'browser_origin_and_callback_required')
        for origin in origins:
            require(safe_url(origin, origin=True, allow_loopback=allow_local), path + '/origins', 'invalid_exact_origin')
        for callback in callbacks:
            require(safe_url(callback, allow_loopback=allow_local) and origin_of(callback) in origins, path + '/redirect_uris', 'invalid_exact_callback')
        grants = sequence(reg.get('pipeline_ids'))
        require(bool(grants) and all(isinstance(pid, str) and pid in ids for pid in grants), path + '/pipeline_ids', 'publication_grant_outside_reviewed_set')
        upload = number(reg.get('max_upload_bytes'), path + '/max_upload_bytes', 1, 20 * 1024**3)
        quota = number(reg.get('max_storage_bytes'), path + '/max_storage_bytes', 1, 1024**4)
        require(quota >= 2 * upload, path + '/max_storage_bytes', 'quota_cannot_hold_upload_and_private_copy')
        number(reg.get('max_queued_runs'), path + '/max_queued_runs', 1, 10000)
        slots = number(reg.get('max_concurrent_runs'), path + '/max_concurrent_runs', 1, 64)
        require(slots <= concurrency, path + '/max_concurrent_runs', 'client_limit_exceeds_global_limit')

    services = mapping(mapping(compose).get('services'))
    backend = mapping(services.get('backend'))
    runner = mapping(services.get('link-worker'))
    frontend = mapping(services.get('frontend'))
    for name, service in (('backend', backend), ('link-worker', runner), ('frontend', frontend)):
        require(bool(service), '/compose/' + name, 'required_service_missing')
        expected = deployment.get('frontend_image' if name == 'frontend' else 'backend_image')
        require(service.get('image') == expected, '/compose/' + name + '/image', 'image_mismatch')
        logging = mapping(service.get('logging'))
        options = mapping(logging.get('options'))
        require(logging.get('driver') == 'local' and options.get('max-size') == '10m' and str(options.get('max-file')) == '5', '/compose/' + name + '/logging', 'bounded_logging_required')
    envs = [mapping(service.get('environment')) for service in (backend, runner)]
    expected_env = {'WEBHDP_LINK_PUBLIC_BASE_URL': deployment.get('public_base_url'), 'FRONTEND_URL': deployment.get('frontend_url'),
                    'WEBHDP_LINK_STORAGE_PATH': storage.get('link_path'), 'WEBHDP_LINK_MAX_CONCURRENT_RUNS': str(concurrency),
                    'WEBHDP_LINK_HPC_WAIT_SECONDS': str(hpc_wait), 'HPC_LINK_PARTITION_ATTEMPT_TIMEOUT_SECONDS': str(partition_wait),
                    'RUN_DB_BOOTSTRAP': '0', 'SKIP_DB_CREATE_ALL': '1'}
    for name, env in zip(('backend', 'link-worker'), envs):
        for key, value in expected_env.items():
            require(str(env.get(key)) == str(value), '/compose/' + name + '/environment/' + key, 'runtime_environment_mismatch')
    require(populated(envs[0].get('DATABASE_URL')) and envs[0].get('DATABASE_URL') == envs[1].get('DATABASE_URL'), '/compose/database', 'identical_database_url_required')
    for key in ('SHARED_SESSION_PATH', 'WEBHDP_SESSIONS_PATH'):
        require(envs[0].get(key) == '/shared/sessions' and envs[1].get(key) == '/shared/sessions', '/compose/environment/' + key, 'shared_session_path_mismatch')

    def mount_identity(service, target):
        matches = []
        for mount in sequence(service.get('volumes')):
            mount = mapping(mount)
            try:
                relative = PurePosixPath(target).relative_to(mount.get('target', ''))
            except (ValueError, TypeError):
                continue
            matches.append((len(str(mount.get('target'))), mount, relative))
        if not matches:
            return None
        _, mount, relative = max(matches, key=lambda item: item[0])
        if mount.get('type') not in {'bind', 'volume'} or not mount.get('source') or mount.get('read_only'):
            return None
        return mount['type'], mount['source'], str(relative)

    for target in ('/app/instance', '/app/instance/webhdp-link', '/shared/sessions'):
        identity = mount_identity(backend, target)
        require(identity is not None and identity == mount_identity(runner, target), '/compose/volumes', 'shared_writable_persistence_required')
    database = envs[0].get('DATABASE_URL', '')
    if isinstance(database, str) and database.startswith('sqlite:'):
        require(database.startswith('sqlite:////app/instance/') and '?' not in database and database.endswith(('.db', '.sqlite', '.sqlite3')), '/compose/database', 'sqlite_must_use_shared_instance_directory')
        warnings.append({'path': '/compose/database', 'code': 'sqlite_requires_one_host_local_filesystem_and_working_flock'})
    elif isinstance(database, str):
        require(database.startswith(('postgresql:', 'postgresql+', 'mysql:', 'mysql+', 'mariadb:', 'mariadb+')), '/compose/database', 'unsupported_database_lock_dialect')

    refs = mapping(plan.get('secret_references'))
    required_refs = {'signing': 'SECRET_KEY', 'credential_encryption': 'CREDENTIAL_ENCRYPTION_KEY'}
    if uses_hpc:
        required_refs.update(hpc_username='HPC_LINK_USERNAME', hpc_password='HPC_LINK_PASSWORD')
    for key, variable in required_refs.items():
        require(refs.get(key) == 'env:' + variable, '/secret_references/' + key, 'explicit_environment_reference_required')
    for reference_value in refs.values():
        if not require(isinstance(reference_value, str) and bool(re.fullmatch(r'env:[A-Z][A-Z0-9_]*', reference_value)), '/secret_references', 'secret_value_or_invalid_reference_forbidden'):
            continue
        key = reference_value[4:]
        require(isinstance(envs[0].get(key), str) and bool(envs[0][key].strip()) and envs[0].get(key) == envs[1].get(key), '/compose/secrets', 'shared_secret_reference_unresolved')
    require(runner.get('command') == ['python', 'scripts/webhdp_link_worker.py', '--poll-seconds', '2'], '/compose/link-worker/command', 'dedicated_worker_command_required')
    require(runner.get('restart') == 'unless-stopped' and runner.get('init') is True and runner.get('stop_signal') == 'SIGTERM', '/compose/link-worker', 'supervised_graceful_worker_required')
    require(not runner.get('ports'), '/compose/link-worker/ports', 'worker_must_not_publish_ports')
    require(mapping(runner.get('deploy')).get('replicas') == replicas, '/compose/link-worker/replicas', 'replica_mismatch')
    duration = str(runner.get('stop_grace_period', ''))
    try:
        duration_parts = re.findall(r'(\d+(?:\.\d+)?)(h|m|s)', duration)
        seconds = sum(float(value) * {'h': 3600, 'm': 60, 's': 1}[unit] for value, unit in duration_parts)
        valid_duration = ''.join(value + unit for value, unit in duration_parts) == duration
    except ValueError:
        seconds, valid_duration = 0, False
    require(valid_duration and seconds == grace, '/compose/link-worker/stop_grace_period', 'stop_grace_mismatch')
    command = sequence(backend.get('command'))
    require('--access-logformat' in command and '%(h)s %(m)s %(U)s %(s)s %(L)s' in command, '/compose/backend/command', 'path_only_access_logs_required')

    for template in ('nginx.conf', 'nginx.hpc.singularity.conf.template'):
        try:
            source = (Path(repository) / 'frontend' / template).read_text()
        except OSError:
            source = ''
        marker = 'location ^~ /api/v1/link/ {'
        location = source.split(marker, 1)[-1].split('\n    }', 1)[0] if marker in source else ''
        require(all(text in location for text in ('proxy_http_version 1.1;', 'proxy_set_header Origin $http_origin;', 'proxy_request_buffering off;')) and 'Access-Control-Allow-Origin' not in location and 'return 204' not in location, '/proxy/' + template, 'link_proxy_contract_missing')
        require("frame-ancestors 'none'" in source, '/proxy/' + template, 'consent_frame_protection_missing')
        require("log_format webhdp_safe '$remote_addr $request_method $uri $status $body_bytes_sent $request_time';" in source and 'access_log /var/log/nginx/access.log webhdp_safe;' in source, '/proxy/' + template, 'query_free_access_logs_required')
    warnings.append({'path': '/proxy', 'code': 'verify_tls_headers_authenticated_upload_and_download_through_actual_proxy'})
    return {'ok': not errors, 'scope': 'offline_configuration_only', 'errors': errors, 'warnings': warnings,
            'minimum_stop_grace_seconds': max_runtime, 'live_checks_performed': [],
            'mutations_performed': [], 'deployment_authorized': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--compose', default='-', help='Rendered Compose JSON file, or stdin (default); may contain secrets, never logged.')
    args = parser.parse_args(argv)
    try:
        plan, _ = read_json(args.plan)
        if args.compose == '-':
            raw = sys.stdin.buffer.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise ValueError('document_too_large')
            compose = json.loads(raw)
        else:
            compose, _ = read_json(args.compose)
        result = validate(plan, compose, args.plan.resolve().parent)
    except (OSError, ValueError, TypeError, KeyError):
        result = {'ok': False, 'scope': 'offline_configuration_only', 'errors': [{'path': '/', 'code': 'invalid_or_unreadable_input'}],
                  'live_checks_performed': [], 'mutations_performed': [], 'deployment_authorized': False}
    print(json.dumps(result, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
