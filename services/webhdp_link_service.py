"""WebHDP-Link v1 boundary: explicit publication, scoped authority and opaque data IDs.

The integration API never accepts a command, filesystem path, execution profile,
HPC credential, callback URL, or pipeline graph from an external application.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from flask import current_app, request
from sqlalchemy import func
from werkzeug.utils import secure_filename

from database.database import db
from database.models import ComponentVersion, PipelineDefinition, PipelineVersion, PipelineVersionStatus, User
from database.webhdp_link_models import LinkArtifact, LinkClient, LinkCode, LinkPublication, LinkRun, LinkToken, LinkUpload
from services.registry_lock import registry_lock

SCOPES = ('pipelines:read', 'uploads:write', 'runs:write', 'runs:read', 'artifacts:read')
DEFAULT_SCOPE = ' '.join(SCOPES)
TERMINAL = {'succeeded', 'failed', 'cancelled'}
ID_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$')
PKCE_PATTERN = re.compile(r'^[A-Za-z0-9._~-]{43,128}$')
SAFE_BINDINGS = {'pipeline_source_file', 'pipeline_source_files', 'pipeline_source_directory', 'artifact_file', 'artifact_directory', 'artifact_json_value', 'literal'}
SCHEMA_KEYS = {'type', 'title', 'description', 'default', 'enum', 'minimum', 'maximum', 'minLength', 'maxLength'}


class LinkError(Exception):
    def __init__(self, code, detail, status=400):
        self.code, self.detail, self.status = code, detail, status
        super().__init__(detail)


def now():
    return datetime.utcnow()


def iso(value):
    return value.isoformat(timespec='seconds') + 'Z' if value else None


def loads(value, fallback=None):
    return json.loads(value) if value else ({} if fallback is None else fallback)


def dumps(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fail(condition, code, message, status=400):
    if condition:
        raise LinkError(code, message, status)


def object_payload(data, allowed):
    fail(not isinstance(data, dict), 'invalid_request', 'Expected a JSON object.')
    fail(bool(set(data) - set(allowed)), 'invalid_request', 'The request contains unsupported fields.')
    return data


def bounded_int(value, name, minimum, maximum):
    fail(type(value) is not int or not minimum <= value <= maximum, 'invalid_request', f'{name} must be an integer between {minimum} and {maximum}.')
    return value


def identifier(value, name='id'):
    fail(not isinstance(value, str) or not ID_PATTERN.fullmatch(value), 'invalid_request', f'{name} must be a short identifier containing letters, digits, dots, underscores or hyphens.')
    return value


def text_field(value, name, maximum=160, minimum=1):
    fail(not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum, 'invalid_request', f'{name} must contain {minimum} to {maximum} characters.')
    return value.strip()


def origin_of(url):
    p = urlsplit(url)
    return f'{p.scheme}://{p.netloc}'


def validate_url(value, *, origin=False):
    fail(not isinstance(value, str) or len(value) > 1024, 'invalid_request', 'A valid HTTPS URL is required.')
    try:
        p = urlsplit(value)
        _ = p.port
    except ValueError:
        raise LinkError('invalid_request', 'A valid HTTPS URL is required.')
    local = p.hostname in {'localhost', '127.0.0.1', '::1'}
    fail(not p.hostname or p.username is not None or p.password is not None or p.fragment or '\\' in value or any(ord(c) < 33 for c in value), 'invalid_request', 'URLs must be absolute and contain no credentials, fragment or whitespace.')
    fail(p.scheme != 'https' and not (local and p.scheme == 'http'), 'invalid_request', 'HTTPS is required except for loopback development URLs.')
    if origin:
        fail(value != origin_of(value), 'invalid_request', 'Origins must contain exactly scheme, host and optional port.')
    else:
        fail(any(k in {'code', 'state', 'error', 'iss'} for k, _ in parse_qsl(p.query)), 'invalid_request', 'Redirect URLs cannot predefine OAuth response parameters.')
    return value


def public_base():
    configured = current_app.config.get('WEBHDP_LINK_PUBLIC_BASE_URL') or os.environ.get('WEBHDP_LINK_PUBLIC_BASE_URL')
    return str(configured or request.url_root).rstrip('/')


def issuer():
    return public_base() + '/api/v1/link'


def storage_root():
    path = Path(current_app.config.get('WEBHDP_LINK_STORAGE_PATH') or os.environ.get('WEBHDP_LINK_STORAGE_PATH') or Path(current_app.instance_path) / 'webhdp-link').expanduser().resolve()
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    return path


def scopes(value=None):
    value = DEFAULT_SCOPE if value is None else value
    fail(not isinstance(value, str) or len(value) > 300, 'invalid_scope', 'scope must be a space-separated string.')
    selected = value.split()
    fail(not selected or bool(set(selected) - set(SCOPES)), 'invalid_scope', 'An unknown or empty scope was requested.')
    return ' '.join(scope for scope in SCOPES if scope in selected)


def require_user(user):
    fail(user is None or not user.is_verified or user.force_password_change, 'access_denied', 'This WebHDP account is not eligible to authorize an application.', 403)


def client_config(client):
    return loads(client.config_json)


def serialize_client(client):
    return {'id': client.id, 'name': client.name, 'enabled': client.enabled, **client_config(client), 'created_at': iso(client.created_at)}


def save_client(data, existing=None):
    allowed = {'id', 'name', 'enabled', 'origins', 'redirect_uris', 'pipeline_ids', 'max_queued_runs', 'max_concurrent_runs', 'max_upload_bytes', 'max_storage_bytes'}
    object_payload(data, allowed)
    old = serialize_client(existing) if existing else {}
    merged = {**old, **data}
    cid = identifier(merged.get('id') or str(uuid4()))
    fail(existing is not None and cid != existing.id, 'invalid_request', 'Client identifiers cannot be changed.')
    fail(existing is None and db.session.get(LinkClient, cid) is not None, 'conflict', 'A client with this identifier exists.', 409)
    origins = merged.get('origins', [])
    redirects = merged.get('redirect_uris', [])
    pids = merged.get('pipeline_ids', [])
    for value, label in ((origins, 'origins'), (redirects, 'redirect_uris'), (pids, 'pipeline_ids')):
        fail(not isinstance(value, list) or len(value) > 50 or any(not isinstance(v, str) for v in value), 'invalid_request', f'{label} must be a list of at most 50 strings.')
    origins = list(dict.fromkeys(validate_url(x, origin=True) for x in origins))
    redirects = list(dict.fromkeys(validate_url(x) for x in redirects))
    fail(any(origin_of(x) not in origins for x in redirects), 'invalid_request', 'Every redirect URI must belong to a registered origin.')
    for pid in pids:
        fail(db.session.get(LinkPublication, identifier(pid, 'pipeline_id')) is None, 'invalid_request', 'A selected publication does not exist.')
    config = {'origins': origins, 'redirect_uris': redirects, 'pipeline_ids': list(dict.fromkeys(pids))}
    for key, default, lo, hi in (
        ('max_queued_runs', 20, 1, 10000), ('max_concurrent_runs', 1, 1, 64),
        ('max_upload_bytes', 100 * 1024**2, 1, 20 * 1024**3), ('max_storage_bytes', 1024**3, 1, 1024**4),
    ):
        config[key] = bounded_int(merged.get(key, default), key, lo, hi)
    fail(type(merged.get('enabled', True)) is not bool, 'invalid_request', 'enabled must be a boolean.')
    row = existing or LinkClient(id=cid)
    row.name = text_field(merged.get('name'), 'name')
    row.enabled = merged.get('enabled', True)
    row.config_json = dumps(config)
    db.session.add(row)
    db.session.commit()
    return row


def _native_parameter(field):
    typ = {'string_dropdown': 'string', 'text': 'string'}.get(field.get('type'), field.get('type'))
    if typ not in {'string', 'number', 'integer', 'boolean'}:
        return None
    result = {'name': field['name'], 'type': typ, 'label': field.get('label') or field['name']}
    for key in ('default', 'minimum', 'maximum', 'minLength', 'maxLength', 'description'):
        if field.get(key) is not None:
            result[key] = field[key]
    options = field.get('enum') or field.get('options')
    if options:
        result['enum'] = [x.get('value') if isinstance(x, dict) else x for x in options]
    return result


def version_steps(version):
    rows = {step.step_key: step for step in version.steps}
    result = []
    for step in loads(version.config_json).get('steps', []):
        if not step.get('enabled', True):
            continue
        persisted = rows.get(step['id'])
        component = db.session.get(ComponentVersion, persisted.component_version_id) if persisted else None
        if component is None:
            raise LinkError('invalid_pipeline', 'Every step must pin an installed component version.')
        manifest = loads(component.manifest_json)
        parameters = [_native_parameter(field) for group in manifest.get('parameter_groups', []) for field in group.get('parameters', [])]
        result.append({'id': step['id'], 'name': step.get('name') or step['id'], 'component': component.component_definition.key,
                       'version': component.version, 'parameters': [x for x in parameters if x is not None]})
    return result


def pipeline_options():
    current_app.native_pipeline_service.ensure_seeded()
    result = []
    for definition in PipelineDefinition.query.filter_by(is_active=True).order_by(PipelineDefinition.name).all():
        versions = []
        for version in definition.versions:
            if version.status == PipelineVersionStatus.PUBLISHED:
                try:
                    versions.append({'version': version.version, 'steps': version_steps(version)})
                except LinkError:
                    pass
        result.append({'identifier': definition.identifier, 'name': definition.name, 'versions': versions})
    return result


def validate_schema(schema, *, value_marker=False, value=None):
    fail(not isinstance(schema, dict) or bool(set(schema) - SCHEMA_KEYS), 'invalid_request', 'Only the documented scalar JSON Schema keywords are supported.')
    typ = schema.get('type')
    fail(typ not in {'string', 'number', 'integer', 'boolean'}, 'invalid_request', 'Exposed parameters must be string, number, integer or boolean.')
    for key in ('minimum', 'maximum'):
        if key in schema:
            fail(type(schema[key]) not in (int, float) or not math.isfinite(schema[key]), 'invalid_request', f'{key} must be finite.')
    fail('minimum' in schema and 'maximum' in schema and schema['minimum'] > schema['maximum'], 'invalid_request', 'minimum exceeds maximum.')
    for key in ('minLength', 'maxLength'):
        if key in schema:
            bounded_int(schema[key], key, 0, 10000)
    if 'enum' in schema:
        fail(not isinstance(schema['enum'], list) or not 1 <= len(schema['enum']) <= 100, 'invalid_request', 'enum must contain 1 to 100 scalar values.')
        for entry in schema['enum']:
            validate_schema({k: v for k, v in schema.items() if k not in {'enum', 'default'}}, value_marker=True, value=entry)
    if value_marker:
        valid = ((typ == 'string' and isinstance(value, str)) or (typ == 'boolean' and type(value) is bool)
                 or (typ == 'integer' and type(value) is int) or (typ == 'number' and type(value) in (int, float) and math.isfinite(value)))
        fail(not valid, 'invalid_parameter', 'A parameter does not match its declared type.')
        if typ in {'integer', 'number'}:
            fail(value < schema.get('minimum', -math.inf) or value > schema.get('maximum', math.inf), 'invalid_parameter', 'A numeric parameter is outside its allowed range.')
        if typ == 'string':
            fail(not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', 10000), 'invalid_parameter', 'A string parameter has an invalid length.')
            fail('\x00' in value, 'invalid_parameter', 'A string parameter contains a forbidden character.')
        if 'enum' in schema:
            fail(not any(type(value) is type(x) and value == x for x in schema['enum']), 'invalid_parameter', 'A parameter is not an allowed option.')
    elif 'default' in schema:
        validate_schema(schema, value_marker=True, value=schema['default'])


def save_publication(data, existing=None):
    object_payload(data, {'id', 'name', 'description', 'pipeline_identifier', 'pipeline_version', 'enabled', 'input', 'parameters', 'execution_mode', 'step_timeout_seconds', 'hpc'})
    if existing is not None:
        fail(bool(set(data) - {'enabled', 'name', 'description'}), 'immutable_publication', 'Publish a new identifier to change the pipeline version, input contract, parameters or execution policy.', 409)
        if 'enabled' in data:
            fail(type(data['enabled']) is not bool, 'invalid_request', 'enabled must be a boolean.')
            existing.enabled = data['enabled']
        if 'name' in data:
            existing.name = text_field(data['name'], 'name')
        if 'description' in data:
            existing.description = text_field(data['description'], 'description', 5000, 0)
        db.session.commit()
        return existing
    old = serialize_publication(existing, admin=True) if existing else {}
    merged = {**old, **data}
    pid = identifier(merged.get('id'))
    fail(existing is not None and pid != existing.id, 'invalid_request', 'Publication identifiers cannot be changed.')
    fail(existing is None and db.session.get(LinkPublication, pid) is not None, 'conflict', 'A publication with this identifier exists.', 409)
    definition = PipelineDefinition.query.filter_by(identifier=merged.get('pipeline_identifier'), is_active=True).first()
    version = PipelineVersion.query.filter_by(pipeline_definition_id=definition.id, version=merged.get('pipeline_version'), status=PipelineVersionStatus.PUBLISHED).first() if definition else None
    fail(version is None, 'invalid_pipeline', 'Select a published native pipeline version.')
    details = version_steps(version)
    fail(not details, 'invalid_pipeline', 'A publication must contain an enabled step.')
    config = loads(version.config_json)
    step_rows = {step.step_key: step for step in version.steps}
    fields_by_step = {step['id']: {x['name']: x for x in step['parameters']} for step in details}
    seen = set()
    needs_hpc = False
    bound_parameters = set()
    for step in config.get('steps', []):
        if not step.get('enabled', True):
            continue
        fail(step.get('scope', 'record') != 'record' or bool(step.get('output_actions')), 'unsupported_pipeline', 'Link v1 supports record steps without submission metadata output actions.')
        component = db.session.get(ComponentVersion, step_rows[step['id']].component_version_id)
        profile = current_app.native_pipeline_service._get_profile_row(component, step.get('execution_profile_ref'))
        profile_data = current_app.native_pipeline_service._profile_payload(profile)
        working_directory = Path(str(profile_data.get('working_directory') or '.'))
        fail(working_directory.is_absolute() or '..' in working_directory.parts, 'unsupported_pipeline', 'Link components must use a working directory inside their private invocation directory.')
        if profile.adapter in {'local_cli', 'container_cli'}:
            for output in profile_data.get('output_collection') or []:
                declared = Path(str(output.get('path') or output.get('relative_path') or output.get('glob') or '.'))
                fail(declared.is_absolute() or '..' in declared.parts, 'unsupported_pipeline', 'Link CLI output declarations must remain inside their private invocation directory.')
        needs_hpc = needs_hpc or profile.adapter == 'hpc_link'
        bound_parameters.update((step['id'], b['target']) for b in step.get('parameter_bindings', []))
        fail(profile.adapter not in {'local_cli', 'container_cli', 'hpc_link'}, 'unsupported_pipeline', 'Link publications require a CLI, container or HPC-Link component profile.')
        for binding in step.get('input_bindings', []) + step.get('parameter_bindings', []):
            fail(binding.get('type') not in SAFE_BINDINGS, 'unsupported_pipeline', 'This pipeline uses a binding that requires submission-specific authority.')
            if str(binding.get('type')).startswith('artifact_'):
                fail(binding.get('source_step') not in seen, 'invalid_pipeline', 'Artifact bindings must reference an earlier enabled step.')
            if binding.get('kind') == 'input' and binding.get('type') == 'literal':
                fail(True, 'unsupported_pipeline', 'File inputs must derive from uploaded data or previous artifacts.')
        # Trigger overrides can obscure the external parameter contract; expose
        # only explicit fixed graphs until a trigger schema is standardized.
        fail(bool((step.get('triggers') or {}).get('rules')), 'unsupported_pipeline', 'Conditional trigger rules are not supported in Link v1 publications.')
        seen.add(step['id'])
    inp = merged.get('input') or {}
    object_payload(inp, {'min_files', 'max_files', 'extensions'})
    inp = {'min_files': bounded_int(inp.get('min_files', 1), 'min_files', 1, 1000),
           'max_files': bounded_int(inp.get('max_files', 1), 'max_files', 1, 1000), 'extensions': inp.get('extensions', [])}
    fail(inp['min_files'] > inp['max_files'], 'invalid_request', 'min_files exceeds max_files.')
    fail(not isinstance(inp['extensions'], list) or not 1 <= len(inp['extensions']) <= 100 or any(not isinstance(x, str) or not re.fullmatch(r'\.[a-z0-9]{1,12}', x) for x in inp['extensions']), 'invalid_request', 'Declare a nonempty list of lowercase file extensions.')
    params = merged.get('parameters') or {}
    fail(not isinstance(params, dict) or len(params) > 64, 'invalid_request', 'parameters must be a mapping of at most 64 exposed parameters.')
    normalized = {}
    targets = set()
    for name, param in params.items():
        identifier(name, 'parameter name')
        object_payload(param, SCHEMA_KEYS | {'step_id', 'parameter', 'label'})
        field = fields_by_step.get(param.get('step_id'), {}).get(param.get('parameter'))
        fail(field is None, 'invalid_parameter', 'An exposed parameter must name a scalar component parameter.')
        target = (param['step_id'], param['parameter'])
        fail(target in targets, 'invalid_parameter', 'Each component parameter can be exposed only once.')
        fail(target in bound_parameters, 'invalid_parameter', 'Externally set parameters cannot also have a native parameter binding.')
        targets.add(target)
        schema = {k: v for k, v in param.items() if k in SCHEMA_KEYS}
        schema.setdefault('type', field['type'])
        fail(schema['type'] != field['type'], 'invalid_parameter', 'Exposed parameter types must match the component manifest.')
        for key in ('default', 'enum', 'minimum', 'maximum', 'minLength', 'maxLength'):
            if key not in schema and key in field:
                schema[key] = field[key]
        if 'enum' in field:
            fail(any(x not in field['enum'] for x in schema.get('enum', [])), 'invalid_parameter', 'The public enum cannot broaden the component options.')
        for key in ('minimum', 'minLength'):
            fail(key in field and schema.get(key, field[key]) < field[key], 'invalid_parameter', 'The public bounds cannot broaden component bounds.')
        for key in ('maximum', 'maxLength'):
            fail(key in field and schema.get(key, field[key]) > field[key], 'invalid_parameter', 'The public bounds cannot broaden component bounds.')
        if param.get('label'):
            schema['title'] = text_field(param['label'], 'label')
        validate_schema(schema)
        normalized[name] = {**schema, 'step_id': target[0], 'parameter': target[1]}
    mode = merged.get('execution_mode', 'record')
    fail(mode not in {'record', 'bundle'}, 'invalid_request', 'execution_mode must be record or bundle.')
    hpc = merged.get('hpc') or {}
    object_payload(hpc, {'enabled', 'walltime_hours', 'partition', 'gpu_count', 'gpu_type', 'retain_allocation', 'reuse_retained_allocation'})
    fail(type(hpc.get('enabled', False)) is not bool, 'invalid_request', 'hpc.enabled must be a boolean.')
    fail(needs_hpc and not hpc.get('enabled'), 'invalid_pipeline', 'HPC component profiles require an administrator-defined HPC allocation policy.')
    if hpc.get('enabled'):
        if 'walltime_hours' in hpc:
            hpc['walltime_hours'] = bounded_int(hpc['walltime_hours'], 'walltime_hours', 1, 168)
        fail(type(hpc.get('retain_allocation', False)) is not bool, 'invalid_request', 'hpc.retain_allocation must be a boolean.')
        hpc['retain_allocation'] = hpc.get('retain_allocation', False)
        fail(type(hpc.get('reuse_retained_allocation', False)) is not bool, 'invalid_request', 'hpc.reuse_retained_allocation must be a boolean.')
        hpc['reuse_retained_allocation'] = hpc.get('reuse_retained_allocation', False)
        fail(hpc['reuse_retained_allocation'] and not hpc['retain_allocation'], 'invalid_request', 'HPC reuse requires explicit allocation retention.')
        hpc['gpu_count'] = bounded_int(hpc.get('gpu_count', 1), 'gpu_count', 0, 8)
        for key in ('partition', 'gpu_type'):
            if key in hpc:
                identifier(hpc[key], key)
    fail(type(merged.get('enabled', True)) is not bool, 'invalid_request', 'enabled must be a boolean.')
    row = existing or LinkPublication(id=pid)
    row.pipeline_version_id = version.id
    row.name = text_field(merged.get('name'), 'name')
    row.description = text_field(merged.get('description', ''), 'description', 5000, 0)
    row.enabled = merged.get('enabled', True)
    row.config_json = dumps({'input': inp, 'parameters': normalized, 'execution_mode': mode, 'structure': details,
                             'step_timeout_seconds': bounded_int(merged.get('step_timeout_seconds', 3600), 'step_timeout_seconds', 1, 43200), 'hpc': hpc})
    db.session.add(row)
    db.session.commit()
    return row


def serialize_publication(row, *, admin=False):
    config = loads(row.config_json)
    version = db.session.get(PipelineVersion, row.pipeline_version_id)
    definition = db.session.get(PipelineDefinition, version.pipeline_definition_id)
    properties = {name: {k: v for k, v in field.items() if k in SCHEMA_KEYS} for name, field in config['parameters'].items()}
    data = {'id': row.id, 'name': row.name, 'description': row.description, 'enabled': row.enabled,
            'pipeline_identifier': definition.identifier, 'pipeline_version': version.version,
            'input': config['input'], 'execution_mode': config['execution_mode'],
            'parameter_schema': {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'type': 'object', 'properties': properties, 'additionalProperties': False},
            'structure': [{k: v for k, v in step.items() if k != 'parameters'} for step in config['structure']]}
    if admin:
        data.update(parameters=config['parameters'], step_timeout_seconds=config['step_timeout_seconds'], hpc=config.get('hpc', {}))
    return data


def available_publications(client, token=None):
    allowed = set(client_config(client)['pipeline_ids'])
    if token:
        allowed &= set(loads(token.pipeline_ids_json, []))
    return [row for row in LinkPublication.query.filter(LinkPublication.id.in_(allowed), LinkPublication.enabled.is_(True)).order_by(LinkPublication.name).all()]


def authorization_request(data):
    identifier(data.get('client_id'), 'client_id')
    client = db.session.get(LinkClient, data.get('client_id'))
    fail(client is None or not client.enabled, 'invalid_client', 'This application is not registered or is disabled.')
    config = client_config(client)
    fail(data.get('redirect_uri') not in config['redirect_uris'], 'invalid_redirect_uri', 'The redirect URI must exactly match a registered URI.')
    fail(data.get('response_type') != 'code', 'unsupported_response_type', 'Only the authorization code flow is supported.')
    challenge = data.get('code_challenge')
    fail(data.get('code_challenge_method') != 'S256' or not isinstance(challenge, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', challenge), 'invalid_request', 'S256 PKCE with a valid SHA-256 challenge is required.')
    state = data.get('state')
    fail(not isinstance(state, str) or not 16 <= len(state) <= 512 or any(ord(x) < 32 for x in state), 'invalid_request', 'An unpredictable state value of 16 to 512 characters is required.')
    return client, {'redirect_uri': data['redirect_uri'], 'code_challenge': challenge, 'state': state, 'scope': scopes(data.get('scope'))}


def authorize(data, user):
    require_user(user)
    client, details = authorization_request(data)
    fail(type(data.get('approve')) is not bool, 'invalid_request', 'approve must be a boolean.')
    response = {'state': details['state'], 'iss': issuer()}
    if data['approve']:
        raw = secrets.token_urlsafe(32)
        db.session.add(LinkCode(id=digest(raw), client_id=client.id, user_id=user.id,
                              expires_at=now() + timedelta(minutes=5),
                              config_json=dumps({**details, 'user_token_version': user.token_version or 0,
                                                 'pipeline_ids': [row.id for row in available_publications(client)]})))
        db.session.commit()
        response['code'] = raw
    else:
        response['error'] = 'access_denied'
    p = urlsplit(details['redirect_uri'])
    return {'redirect_uri': urlunsplit((p.scheme, p.netloc, p.path, urlencode(parse_qsl(p.query, keep_blank_values=True) + list(response.items())), ''))}


def issue_token(client, user, *, scope=None, expires_in=3600, service=False, origin=None, pipeline_ids=None):
    require_user(user)
    fail(not client.enabled, 'invalid_client', 'The application is disabled.')
    lifetime = bounded_int(expires_in, 'expires_in', 60, 30 * 86400 if service else 3600)
    raw = 'whl_' + secrets.token_urlsafe(32)
    row = LinkToken(token_hash=digest(raw), client_id=client.id, user_id=user.id,
                    user_token_version=user.token_version or 0, scope=scopes(scope),
                    pipeline_ids_json=dumps(pipeline_ids if pipeline_ids is not None else [p.id for p in available_publications(client)]),
                    service=service, origin=origin, expires_at=now() + timedelta(seconds=lifetime))
    db.session.add(row)
    db.session.commit()
    return {'access_token': raw, 'token_type': 'Bearer', 'expires_in': lifetime, 'scope': row.scope, 'token_id': row.id, 'issuer': issuer()}


def exchange_code(data):
    fail(data.get('grant_type') != 'authorization_code', 'unsupported_grant_type', 'Only authorization_code is supported.')
    code = data.get('code', '')
    verifier = data.get('code_verifier', '')
    fail(not isinstance(code, str) or not 20 <= len(code) <= 200 or not isinstance(verifier, str) or not PKCE_PATTERN.fullmatch(verifier), 'invalid_grant', 'The authorization code or verifier is invalid.')
    with registry_lock('link-code:' + digest(code)):
        row = db.session.get(LinkCode, digest(code))
        fail(row is None or row.used_at is not None or row.expires_at <= now(), 'invalid_grant', 'The authorization code is invalid, expired or already used.')
        config = loads(row.config_json)
        client = db.session.get(LinkClient, row.client_id)
        user = db.session.get(User, row.user_id)
        fail(client is None or not client.enabled or row.client_id != data.get('client_id') or config['redirect_uri'] != data.get('redirect_uri'), 'invalid_grant', 'The authorization code does not match this application and redirect URI.')
        fail(config['redirect_uri'] not in client_config(client)['redirect_uris'], 'invalid_grant', 'This redirect URI is no longer registered.')
        origin = request.headers.get('Origin')
        fail(origin is not None and origin != origin_of(config['redirect_uri']), 'invalid_grant', 'The exchange origin does not match the authorized redirect URI.')
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        fail(not hmac.compare_digest(expected, config['code_challenge']), 'invalid_grant', 'The PKCE verifier does not match.')
        require_user(user)
        fail((user.token_version or 0) != config['user_token_version'], 'invalid_grant', 'The WebHDP account authorization has changed.')
        row.used_at = now()
        # The code consumption and token insertion commit together.
        return issue_token(client, user, scope=config['scope'], origin=origin_of(config['redirect_uri']), pipeline_ids=config['pipeline_ids'])


def authenticate(required=None):
    header = request.headers.get('Authorization', '')
    fail(not header.startswith('Bearer whl_') or len(header) > 300, 'invalid_token', 'A WebHDP-Link bearer token is required.', 401)
    token = LinkToken.query.filter_by(token_hash=digest(header[7:])).first()
    fail(token is None or token.revoked or token.expires_at <= now(), 'invalid_token', 'The bearer token is invalid, expired or revoked.', 401)
    client = db.session.get(LinkClient, token.client_id)
    user = db.session.get(User, token.user_id)
    fail(client is None or not client.enabled or user is None or not user.is_verified or user.force_password_change or (user.token_version or 0) != token.user_token_version, 'invalid_token', 'This application authorization is no longer valid.', 401)
    origin = request.headers.get('Origin')
    if origin is not None:
        fail(token.service or origin not in client_config(client)['origins'] or (token.origin is not None and token.origin != origin), 'origin_denied', 'This bearer token cannot be used by this origin.', 403)
    fail(required is not None and required not in token.scope.split(), 'insufficient_scope', 'The bearer token does not grant the required scope.', 403)
    return token, client, user


def serialize_token(row):
    return {'id': row.id, 'client_id': row.client_id, 'user_id': row.user_id, 'scope': row.scope, 'service': row.service,
            'created_at': iso(row.created_at), 'expires_at': iso(row.expires_at), 'revoked': row.revoked}


def upload_path(row):
    return storage_root() / 'uploads' / row.id / row.name


def tree_bytes(root):
    total = 0
    if root.is_dir():
        for directory, _, names in os.walk(root, followlinks=False):
            for name in names:
                try:
                    total += (Path(directory) / name).lstat().st_size
                except FileNotFoundError:
                    pass
    return total


def storage_used(client_id):
    uploaded = db.session.query(func.coalesce(func.sum(LinkUpload.size), 0)).filter(LinkUpload.client_id == client_id).scalar()
    retained = 0
    for row in LinkRun.query.filter_by(client_id=client_id).all():
        payload = loads(row.request_json)
        reserved = payload.get('input_bytes', 0) if row.status in {'queued', 'running'} and not payload.get('data_purged') else 0
        retained += max(reserved, tree_bytes(storage_root() / 'runs' / row.id))
    return int(uploaded or 0) + retained


def serialize_upload(row):
    return {'id': row.id, 'name': row.name, 'size': row.size, 'sha256': row.sha256, 'media_type': row.media_type, 'created_at': iso(row.created_at)}


def accept_upload(file, token, client):
    fail(file is None, 'invalid_upload', 'A multipart file field named file is required.')
    original = file.filename or ''
    fail('/' in original or '\\' in original or '\x00' in original or len(original) > 255, 'invalid_upload', 'File names cannot contain paths.')
    name = secure_filename(original)
    fail(not name or len(name) > 255, 'invalid_upload', 'A usable file name is required.')
    config = client_config(client)
    with registry_lock('link-storage:' + client.id):
        available = config['max_storage_bytes'] - storage_used(client.id)
        fail(available <= 0, 'storage_quota_exceeded', 'The application storage quota is exhausted.', 413)
        row = LinkUpload(id=str(uuid4()), client_id=client.id, user_id=token.user_id, name=name,
                         media_type=mimetypes.guess_type(name)[0] or 'application/octet-stream')
        path = upload_path(row)
        path.parent.mkdir(parents=True, mode=0o700)
        size, checksum = 0, hashlib.sha256()
        try:
            with path.open('xb') as handle:
                os.chmod(path, 0o600)
                while chunk := file.stream.read(1024**2):
                    size += len(chunk)
                    fail(size > min(config['max_upload_bytes'], available), 'upload_too_large', 'The upload exceeds the file or storage quota.', 413)
                    checksum.update(chunk)
                    handle.write(chunk)
            fail(size == 0, 'invalid_upload', 'Empty uploads cannot be processed.')
            row.size, row.sha256 = size, checksum.hexdigest()
            db.session.add(row)
            db.session.commit()
        except Exception:
            db.session.rollback()
            shutil.rmtree(path.parent, ignore_errors=True)
            raise
        return row


def submit_run(data, token, client, key):
    object_payload(data, {'pipeline_id', 'inputs', 'parameters'})
    fail(not isinstance(key, str) or not 16 <= len(key) <= 80 or not re.fullmatch(r'[A-Za-z0-9_.:-]+', key), 'invalid_idempotency_key', 'Provide an unpredictable Idempotency-Key of 16 to 80 URL-safe characters.')
    fingerprint = digest(dumps(data))
    with registry_lock('link-submit:' + client.id), registry_lock('link-storage:' + client.id):
        existing = LinkRun.query.filter_by(client_id=client.id, user_id=token.user_id, idempotency_key=key).first()
        if existing:
            fail(existing.publication_id not in loads(token.pipeline_ids_json, []) or existing.publication_id not in client_config(client)['pipeline_ids'], 'run_not_found', 'The run is unavailable to this authorization.', 404)
            fail(existing.fingerprint != fingerprint, 'idempotency_conflict', 'This idempotency key was already used with another request.', 409)
            return existing, True
        publication = next((x for x in available_publications(client, token) if x.id == data.get('pipeline_id')), None)
        fail(publication is None, 'pipeline_not_found', 'The pipeline is unavailable to this authorization.', 404)
        config = loads(publication.config_json)
        inputs = data.get('inputs')
        fail(not isinstance(inputs, list) or not config['input']['min_files'] <= len(inputs) <= config['input']['max_files'] or any(not isinstance(x, str) for x in inputs) or len(set(inputs)) != len(inputs), 'invalid_inputs', 'Provide the permitted number of distinct upload IDs.')
        uploads = []
        for uid in inputs:
            row = LinkUpload.query.filter_by(id=uid, client_id=client.id, user_id=token.user_id).first()
            fail(row is None, 'upload_not_found', 'An input upload is unavailable to this authorization.', 404)
            fail(Path(row.name).suffix.lower() not in config['input']['extensions'], 'invalid_inputs', 'An input file extension is not accepted by this pipeline.')
            uploads.append(row)
        parameters = data.get('parameters', {})
        fail(not isinstance(parameters, dict) or bool(set(parameters) - set(config['parameters'])), 'invalid_parameter', 'Only explicitly exposed parameters may be supplied.')
        normalized = {}
        for name, field in config['parameters'].items():
            if name not in parameters and 'default' not in field:
                continue
            value = parameters.get(name, field.get('default'))
            validate_schema({k: v for k, v in field.items() if k in SCHEMA_KEYS}, value_marker=True, value=value)
            normalized[name] = value
        quota = client_config(client)
        queued = LinkRun.query.filter_by(client_id=client.id, status='queued').count()
        fail(queued >= quota['max_queued_runs'], 'queue_quota_exceeded', 'The application queue is full. Retry after jobs finish.', 429)
        input_bytes = sum(x.size for x in uploads)
        fail(storage_used(client.id) + input_bytes > quota['max_storage_bytes'], 'storage_quota_exceeded', 'There is insufficient application storage for this run.', 413)
        row = LinkRun(id=str(uuid4()), client_id=client.id, user_id=token.user_id, token_id=token.id,
                      publication_id=publication.id, pipeline_version_id=publication.pipeline_version_id,
                      idempotency_key=key, fingerprint=fingerprint,
                      request_json=dumps({'inputs': inputs, 'parameters': normalized, 'input_bytes': input_bytes, 'publication': config}))
        db.session.add(row)
        db.session.commit()
        return row, False


def require_run(run_id, token):
    row = LinkRun.query.filter_by(id=run_id, client_id=token.client_id, user_id=token.user_id).first()
    client = db.session.get(LinkClient, token.client_id)
    fail(row is None or row.publication_id not in loads(token.pipeline_ids_json, []) or row.publication_id not in client_config(client)['pipeline_ids'], 'run_not_found', 'The run is unavailable to this authorization.', 404)
    return row


def cancel_run(row):
    with registry_lock('link-queue'):
        db.session.refresh(row)
        if row.status not in TERMINAL:
            row.cancel_requested = True
            if row.status == 'queued':
                row.status, row.completed_at = 'cancelled', now()
            db.session.commit()
    return row


def artifact_path(run, artifact):
    root = (storage_root() / 'runs' / run.id).resolve()
    relative = Path(artifact.relative_path)
    fail(relative.is_absolute() or '..' in relative.parts, 'artifact_not_found', 'The artifact is unavailable.', 404)
    path = root / relative
    try:
        fail(path.resolve(strict=True) != path or not path.is_file(), 'artifact_not_found', 'The artifact is unavailable.', 404)
    except (OSError, RuntimeError):
        raise LinkError('artifact_not_found', 'The artifact is unavailable.', 404)
    return path


def _progress_phase(row, snapshot, native, native_steps):
    """Describe persisted execution state without probing or exposing the HPC.

    A worker claim is not evidence that a scientific component has started.
    Terminal Link status remains authoritative for success versus failure.
    """
    from database.models import HpcAllocation, PipelineRunStatus
    if row.status in TERMINAL:
        return 'completed'
    if row.status == 'queued':
        return 'queued'
    if native and native.status in {PipelineRunStatus.COMPLETED, PipelineRunStatus.FAILED}:
        return 'finalizing'
    native_started = bool(native and native.status == PipelineRunStatus.RUNNING) or any(
        step.status in {'running', 'completed', 'failed', 'skipped'} for step in native_steps)
    if snapshot['publication'].get('hpc', {}).get('enabled') and not native_started:
        allocation = None
        if row.session_id:
            candidates = HpcAllocation.query.filter_by(user_id=row.user_id, session_id=row.session_id, purpose='workflow')
            allocation_id = snapshot.get('_hpc_allocation_id')
            if allocation_id:
                candidates = candidates.filter_by(public_id=allocation_id)
            allocation = candidates.order_by(HpcAllocation.requested_at.desc()).first()
        if allocation is None or allocation.status in {'queued', 'allocating'}:
            return 'waiting_for_resources'
        if allocation.status in {'failed', 'released', 'expired', 'cancelled'}:
            return 'finalizing'
    return 'processing'


def serialize_run(row, *, admin=False):
    from database.models import PipelineRun
    version = db.session.get(PipelineVersion, row.pipeline_version_id)
    snapshot = loads(row.request_json)
    config = snapshot['publication']
    native = db.session.get(PipelineRun, row.native_run_id) if row.native_run_id else None
    native_steps = native.step_runs if native else []
    expected = len(config['structure']) * (1 if config['execution_mode'] == 'bundle' else len(snapshot['inputs']))
    complete = sum(s.status in {'completed', 'failed'} for s in native_steps)
    errors = {'execution_failed': 'A pipeline component failed. The WebHDP maintainer can inspect the private execution details.',
              'interrupted': 'The worker stopped before confirming completion. The job was not automatically replayed.',
              'authorization_revoked': 'The application authorization or publication was withdrawn before execution.',
              'storage_quota_exceeded': 'The output exceeded the application storage quota.'}
    data = {'id': row.id, 'pipeline_id': row.publication_id, 'pipeline_name': db.session.get(LinkPublication, row.publication_id).name, 'pipeline_version': version.version, 'status': row.status,
            'progress_url': str(current_app.config.get('FRONTEND_URL') or '').rstrip('/') + '/link/jobs/' + row.id,
            'cancel_requested': row.cancel_requested, 'progress': {'completed': complete, 'total': expected,
                'phase': _progress_phase(row, snapshot, native, native_steps)},
            'steps': [{'id': str(s.id), 'name': next((x['name'] for x in config['structure'] if x['id'] == _step_key(s)), _step_key(s)), 'status': s.status} for s in native_steps],
            'artifacts': [{'id': a.id, 'name': a.name, 'size': a.size, 'sha256': a.sha256, 'media_type': a.media_type,
                           'download_url': f'/api/v1/link/runs/{row.id}/artifacts/{a.id}'} for a in LinkArtifact.query.filter_by(run_id=row.id).order_by(LinkArtifact.name).all()],
            'error': {'code': row.error_code, 'detail': errors.get(row.error_code, errors['execution_failed'])} if row.error_code else None,
            'created_at': iso(row.created_at), 'started_at': iso(row.started_at), 'completed_at': iso(row.completed_at)}
    if admin:
        data.update(client_id=row.client_id, user_id=row.user_id, hpc_cleanup_pending=bool(loads(row.request_json).get('_hpc_cleanup_pending')))
    return data


def _step_key(step):
    from database.models import PipelineStep
    row = db.session.get(PipelineStep, step.pipeline_step_id)
    return row.step_key if row else 'step'


def process_next():
    """Convenience entrypoint for operator launchers; no HTTP request executes jobs."""
    from services.webhdp_link_worker import process_next as process
    return process()
