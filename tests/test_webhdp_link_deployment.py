"""Offline deployment contract checks; never starts containers or contacts HPC."""
from copy import deepcopy
import hashlib
import json
import os
import shutil
import subprocess
import sys

import pytest

from scripts import validate_webhdp_link_deployment as preflight


@pytest.fixture
def deployment(tmp_path):
    publication = {'id': 'reviewed-pipeline', 'name': 'Reviewed pipeline', 'enabled': False,
                   'pipeline_identifier': 'native-reviewed', 'pipeline_version': '1.0.0',
                   'input': {'min_files': 1, 'max_files': 2, 'extensions': ['.jpg']},
                   'parameters': {}, 'execution_mode': 'record', 'step_timeout_seconds': 60,
                   'hpc': {'enabled': True, 'partition': 'approved', 'gpu_count': 1, 'gpu_type': 'reviewed',
                           'walltime_hours': 1, 'retain_allocation': False, 'reuse_retained_allocation': False}}
    inventory = {'pipeline_identifier': 'native-reviewed', 'pipeline_version': '1.0.0',
                 'steps': [{'id': 'process', 'component': 'reviewed', 'version': '1.0.0',
                            'manifest_sha256': 'a' * 64, 'adapter': 'hpc_link'}]}
    entry = {}
    for value, key, hashkey in ((publication, 'request_file', 'sha256'), (inventory, 'native_inventory_file', 'native_inventory_sha256')):
        filename = key + '.json'
        raw = json.dumps(value).encode()
        (tmp_path / filename).write_bytes(raw)
        entry[key], entry[hashkey] = filename, hashlib.sha256(raw).hexdigest()
    plan = {'schema_version': 1,
            'deployment': {'public_base_url': 'https://portal.test', 'frontend_url': 'https://portal.test',
                           'backend_image': 'webhdp-backend@sha256:' + 'a' * 64, 'frontend_image': 'webhdp-frontend@sha256:' + 'b' * 64},
            'worker': {'replicas': 1, 'global_concurrency': 1, 'hpc_wait_seconds': 900, 'partition_attempt_timeout_seconds': 600, 'stop_grace_seconds': 1320},
            'storage': {'link_path': '/app/instance/webhdp-link', 'quota_enforcement': 'filesystem', 'quota_reference': 'ticket-11',
                        'backup_restore_reference': 'restore-drill-5', 'retention_mode': 'manual_review', 'review_after_days': 30, 'retention_owner': 'Operations'},
            'secret_references': {'signing': 'env:SECRET_KEY', 'credential_encryption': 'env:CREDENTIAL_ENCRYPTION_KEY',
                                  'hpc_username': 'env:HPC_LINK_USERNAME', 'hpc_password': 'env:HPC_LINK_PASSWORD'},
            'hpc_authority': {'allowed_partitions': ['approved'], 'allowed_gpu_types': ['reviewed'], 'max_gpus': 1, 'max_walltime_hours': 1, 'policy_reference': 'principal-review-2'},
            'publications': [entry],
            'clients': [{'allow_loopback': False, 'registration': {'id': 'reviewed-client', 'name': 'Reviewed client', 'enabled': False,
                         'origins': ['https://app.test'], 'redirect_uris': ['https://app.test/callback'], 'pipeline_ids': ['reviewed-pipeline'],
                         'max_upload_bytes': 1024, 'max_storage_bytes': 4096, 'max_queued_runs': 2, 'max_concurrent_runs': 1}}]}
    env = {'WEBHDP_LINK_PUBLIC_BASE_URL': 'https://portal.test', 'FRONTEND_URL': 'https://portal.test', 'WEBHDP_LINK_STORAGE_PATH': '/app/instance/webhdp-link',
           'WEBHDP_LINK_MAX_CONCURRENT_RUNS': '1', 'WEBHDP_LINK_HPC_WAIT_SECONDS': '900', 'HPC_LINK_PARTITION_ATTEMPT_TIMEOUT_SECONDS': '600',
           'RUN_DB_BOOTSTRAP': '0', 'SKIP_DB_CREATE_ALL': '1', 'DATABASE_URL': 'sqlite:////app/instance/hdp_web.db',
           'SHARED_SESSION_PATH': '/shared/sessions', 'WEBHDP_SESSIONS_PATH': '/shared/sessions',
           'SECRET_KEY': 'private-signing-value', 'CREDENTIAL_ENCRYPTION_KEY': 'private-encryption-value',
           'HPC_LINK_USERNAME': 'private-user-value', 'HPC_LINK_PASSWORD': 'private-password-value'}
    volumes = [{'type': 'bind', 'source': '/srv/instance', 'target': '/app/instance'}, {'type': 'bind', 'source': '/srv/sessions', 'target': '/shared/sessions'}]
    log = {'driver': 'local', 'options': {'max-size': '10m', 'max-file': '5'}}
    common = {'environment': env, 'volumes': volumes, 'image': plan['deployment']['backend_image'], 'logging': log}
    compose = {'services': {'backend': {**deepcopy(common), 'command': ['gunicorn', '--access-logformat', '%(h)s %(m)s %(U)s %(s)s %(L)s', 'app:app']},
                           'frontend': {'image': plan['deployment']['frontend_image'], 'logging': deepcopy(log)},
                           'link-worker': {**deepcopy(common), 'command': ['python', 'scripts/webhdp_link_worker.py', '--poll-seconds', '2'],
                                           'restart': 'unless-stopped', 'init': True, 'stop_signal': 'SIGTERM', 'stop_grace_period': '22m0s', 'deploy': {'replicas': 1}}}}
    return plan, compose, tmp_path


def codes(result):
    return {error['code'] for error in result['errors']}


def update_publication(plan, directory, change, *, inventory=False):
    entry = plan['publications'][0]
    filekey, hashkey = ('native_inventory_file', 'native_inventory_sha256') if inventory else ('request_file', 'sha256')
    path = directory / entry[filekey]
    value = json.loads(path.read_text())
    change(value)
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    entry[hashkey] = hashlib.sha256(raw).hexdigest()


def test_valid_plan_is_only_static_proof(deployment):
    result = preflight.validate(*deployment)
    assert result['ok'], result
    assert result['minimum_stop_grace_seconds'] == 1320  # 900 queue + 2 records * 60 + 300 settle.
    assert not result['deployment_authorized']
    assert result['live_checks_performed'] == result['mutations_performed'] == []


def test_proxy_log_validation_rejects_a_raw_request_uri_or_unredacted_verification_path(deployment):
    plan, compose, directory = deployment
    frontend = directory / 'frontend'
    frontend.mkdir()
    for template in ('nginx.conf', 'nginx.hpc.singularity.conf.template'):
        shutil.copyfile(preflight.ROOT / 'frontend' / template, frontend / template)
    target = frontend / 'nginx.conf'
    original = target.read_text()
    for unsafe in (
        original.replace('map $uri $webhdp_logged_uri', 'map $request_uri $webhdp_logged_uri'),
        original.replace('/api/v1/auth/verify-email/[redacted];', '$uri;'),
    ):
        target.write_text(unsafe)
        result = preflight.validate(plan, compose, directory, repository=directory)
        assert 'query_free_access_logs_required' in codes(result)


@pytest.mark.parametrize('origin,callback', [
    ('https://*.test', 'https://app.test/callback'),
    ('https://app.test/', 'https://app.test/callback'),
    ('http://app.test', 'http://app.test/callback'),
    ('https://app.test', 'https://app.test/callback?code=predefined'),
    ('https://app.test', 'https://app.test/callback?iss='),
    ('https://app.test', 'https://app.test/callback#fragment'),
    ('https://app.test', 'https://other.test/callback'),
    ('https://@app.test', 'https://@app.test/callback'),
    ('https://app.test?', 'https://app.test/callback'),
    ('http://localhost:5195', 'http://localhost:5195/callback'),
])
def test_exact_browser_authority(deployment, origin, callback):
    plan, compose, directory = deployment
    plan['clients'][0]['registration'].update(origins=[origin], redirect_uris=[callback])
    assert not preflight.validate(plan, compose, directory)['ok']


def test_explicit_loopback_callback_with_non_oauth_query(deployment):
    plan, compose, directory = deployment
    client = plan['clients'][0]
    client.update(allow_loopback=True, loopback_reason='Reviewed local bridge bound to localhost only')
    client['registration'].update(origins=['http://localhost:5194'], redirect_uris=['http://localhost:5194/?webhdp=1'])
    assert preflight.validate(plan, compose, directory)['ok']
    client.pop('loopback_reason')
    assert 'operator_reference_required' in codes(preflight.validate(plan, compose, directory))


@pytest.mark.parametrize('field,value,code', [
    ('DATABASE_URL', 'sqlite:////tmp/other.db', 'identical_database_url_required'),
    ('SECRET_KEY', 'different-private-key', 'shared_secret_reference_unresolved'),
    ('WEBHDP_LINK_STORAGE_PATH', '/tmp/link', 'runtime_environment_mismatch'),
    ('RUN_DB_BOOTSTRAP', '1', 'runtime_environment_mismatch'),
])
def test_worker_must_share_api_authority(deployment, field, value, code):
    plan, compose, directory = deployment
    compose['services']['link-worker']['environment'][field] = value
    result = preflight.validate(plan, compose, directory)
    assert code in codes(result)
    if field == 'SECRET_KEY':
        assert value not in json.dumps(result)


def test_nested_worker_mount_cannot_shadow_shared_link_data(deployment):
    plan, compose, directory = deployment
    compose['services']['link-worker']['volumes'].append({'type': 'bind', 'source': '/other', 'target': '/app/instance/webhdp-link'})
    assert 'shared_writable_persistence_required' in codes(preflight.validate(plan, compose, directory))


@pytest.mark.parametrize('mount', [{'type': 'tmpfs', 'target': '/app/instance/webhdp-link'},
                                 {'type': 'bind', 'source': '/srv/instance', 'target': '/app/instance', 'read_only': True}])
def test_nonpersistent_or_readonly_mount_is_not_hidden_by_parent(deployment, mount):
    plan, compose, directory = deployment
    runner = compose['services']['link-worker']
    runner['volumes'] = [item for item in runner['volumes'] if item['target'] != mount['target']] + [mount]
    assert 'shared_writable_persistence_required' in codes(preflight.validate(plan, compose, directory))


def test_hpc_policy_must_fit_actual_operator_review(deployment):
    plan, compose, directory = deployment
    update_publication(plan, directory, lambda pub: pub['hpc'].update(partition='unapproved', gpu_type='unapproved', gpu_count=2, walltime_hours=12, reuse_retained_allocation=True))
    result = codes(preflight.validate(plan, compose, directory))
    assert {'partition_outside_central_authority', 'gpu_type_outside_central_authority', 'gpu_count_exceeds_authority', 'walltime_exceeds_authority', 'reuse_requires_retention'} <= result


def test_shutdown_grace_covers_all_steps_and_records_not_just_step(deployment):
    plan, compose, directory = deployment
    update_publication(plan, directory, lambda inventory: inventory['steps'].append({**inventory['steps'][0], 'id': 'second'}), inventory=True)
    result = preflight.validate(plan, compose, directory)
    assert result['minimum_stop_grace_seconds'] == 1440
    assert 'grace_shorter_than_whole_job_bound' in codes(result)


def test_changed_review_file_and_unpinned_manifest_rejected(deployment):
    plan, compose, directory = deployment
    (directory / plan['publications'][0]['request_file']).write_text('{}')
    update_publication(plan, directory, lambda inventory: inventory['steps'][0].update(manifest_sha256='unversioned'), inventory=True)
    result = codes(preflight.validate(plan, compose, directory))
    assert {'reviewed_file_hash_mismatch', 'manifest_digest_required'} <= result


def test_unknown_client_grant_and_eager_enable_rejected(deployment):
    plan, compose, directory = deployment
    plan['clients'][0]['registration'].update(enabled=True, pipeline_ids=['other'])
    assert {'stage_clients_disabled', 'publication_grant_outside_reviewed_set'} <= codes(preflight.validate(plan, compose, directory))


def test_no_credentials_in_diagnostics_or_cli(deployment):
    plan, compose, directory = deployment
    secret = 'DO-NOT-PRINT-PRIVATE-SECRET'
    plan['clients'][0]['registration']['access_token'] = secret
    plan['secret_references']['signing'] = secret
    compose['services']['link-worker']['environment']['SECRET_KEY'] = secret
    path = directory / 'plan.json'; path.write_text(json.dumps(plan))
    result = subprocess.run([sys.executable, str(preflight.ROOT / 'scripts/validate_webhdp_link_deployment.py'), '--plan', str(path)],
                            input=json.dumps(compose), text=True, capture_output=True)
    assert result.returncode == 1
    assert secret not in result.stdout + result.stderr
    assert 'inline_secret_field_forbidden' in result.stdout
    assert 'secret_value_or_invalid_reference_forbidden' in result.stdout


def test_incomplete_template_cannot_pass(deployment):
    _, compose, directory = deployment
    plan = json.loads((preflight.ROOT / 'deploy/webhdp-link.production.example.json').read_text())
    assert not preflight.validate(plan, compose, directory)['ok']


def test_render_actual_compose_overlay_offline(deployment):
    if not shutil.which('docker'):
        pytest.skip('Docker Compose CLI unavailable; no Docker daemon is needed')
    version = subprocess.run(['docker', 'compose', 'version'], capture_output=True)
    if version.returncode:
        pytest.skip('Docker Compose plugin unavailable')
    plan, _, directory = deployment
    for filename in ('docker-compose.prod.yml', 'docker-compose.webhdp-link.yml'):
        shutil.copyfile(preflight.ROOT / filename, directory / filename)
    env = {'WEBHDP_BACKEND_IMAGE': plan['deployment']['backend_image'], 'WEBHDP_FRONTEND_IMAGE': plan['deployment']['frontend_image'],
           'WEBHDP_LINK_PUBLIC_BASE_URL': 'https://portal.test', 'FRONTEND_URL': 'https://portal.test', 'WEBHDP_LINK_HPC_WAIT_SECONDS': '900',
           'HPC_LINK_PARTITION_ATTEMPT_TIMEOUT_SECONDS': '600', 'WEBHDP_LINK_STOP_GRACE_SECONDS': '1320', 'SECRET_KEY': 'test-signing-private',
           'CREDENTIAL_ENCRYPTION_KEY': 'test-encryption-private', 'HPC_LINK_USERNAME': 'test-principal', 'HPC_LINK_PASSWORD': 'test-password-private'}
    (directory / '.env').write_text('\n'.join(f'{key}={value}' for key, value in env.items()))
    # Completely isolated environment: a developer's exported credentials/config
    # cannot override this synthetic render or appear in captured diagnostics.
    child_env = {key: os.environ[key] for key in ('PATH', 'HOME', 'DOCKER_CONFIG') if key in os.environ}
    result = subprocess.run(['docker', 'compose', '-f', 'docker-compose.prod.yml', '-f', 'docker-compose.webhdp-link.yml', 'config', '--format', 'json'],
                            cwd=directory, env=child_env, capture_output=True, text=True)
    assert result.returncode == 0, 'Synthetic compose render failed'
    rendered = json.loads(result.stdout)
    checked = preflight.validate(plan, rendered, directory)
    assert checked['ok'], checked
    assert rendered['services']['link-worker']['depends_on']['backend']['condition'] == 'service_healthy'
    assert 'SECRET_KEY' not in json.dumps(checked)


def test_singularity_wrapper_only_foreground_exec_and_no_env_sourcing():
    wrapper = preflight.ROOT / 'scripts/hpc_singularity/remote/run_link_worker.sh'
    assert subprocess.run(['bash', '-n', str(wrapper)], capture_output=True).returncode == 0
    text = wrapper.read_text()
    assert 'exec singularity exec --cleanenv --env-file "$ENV_FILE"' in text
    assert 'source "$ENV_FILE"' not in text
    assert not any(command in text for command in ('sbatch ', 'scancel ', 'kill ', 'flask db ', 'nohup '))
    assert 'RUN_DB_BOOTSTRAP=0' in text and 'SKIP_DB_CREATE_ALL=1' in text


def test_singularity_wrapper_preserves_boundaries_and_never_sources_secrets(tmp_path):
    root = tmp_path / 'service with spaces'
    for name in ('instance', 'logs', 'hdp-shared/sessions', 'data/local_input', 'data/local_output', 'images/sif'):
        (root / name).mkdir(parents=True)
    (root / 'images/sif/backend.sif').touch()
    marker = tmp_path / 'must-not-exist'
    env_file = root / 'private.env'
    env_file.write_text(f'SECRET_KEY=private-secret\nEXECUTED=$(touch "{marker}")\n')
    # Record the wrapper's final command inside an isolated Bash process.
    # This exercises shell expansion without executing a runtime or a PATH stub.
    wrapper = preflight.ROOT / 'scripts/hpc_singularity/remote/run_link_worker.sh'
    environment = {'PATH': '/usr/bin:/bin', 'ROOT': str(root), 'ENV_FILE': str(env_file)}
    result = subprocess.run(
        ['bash', '-c', 'exec() { printf "%s\\n" "$@"; }; source "$1"', 'bash', str(wrapper)],
        env=environment, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    arguments = result.stdout.splitlines()
    assert arguments[:7] == ['singularity', 'exec', '--cleanenv', '--env-file', str(env_file), '--pwd', '/app']
    assert f'{root}/instance:/app/instance' in arguments
    assert f'{root}/hdp-shared/sessions:/shared/sessions' in arguments
    assert arguments[-4:] == ['python', '/app/scripts/webhdp_link_worker.py', '--poll-seconds', '2']
    assert 'private-secret' not in result.stdout + result.stderr
    assert not marker.exists()
