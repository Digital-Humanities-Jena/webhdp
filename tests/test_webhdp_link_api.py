"""Executable HTTP security and interoperability contract for WebHDP-Link."""
import base64
from datetime import timedelta
import hashlib
import io
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token
import pytest

from database.database import db
from database.models import User, UserRole
from database.webhdp_link_models import LinkArtifact, LinkCode, LinkRun, LinkToken, LinkUpload
from routes.webhdp_link_routes import webhdp_link_bp
from services.native_pipeline_system import NativePipelineSystemService
from services import webhdp_link_service as link
from services import webhdp_link_worker as worker

BASE = '/api/v1/link'
ORIGIN = 'http://127.0.0.1:5191'
REDIRECT = ORIGIN + '/callback'
FRONTEND = 'http://127.0.0.1:5173'


@pytest.fixture
def api(tmp_path):
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='link-http-tests-not-a-production-secret',
                      JWT_SECRET_KEY='link-http-tests-not-a-production-secret',
                      SQLALCHEMY_DATABASE_URI='sqlite:///' + str(tmp_path / 'test.db'), SQLALCHEMY_TRACK_MODIFICATIONS=False,
                      WEBHDP_LINK_STORAGE_PATH=str(tmp_path / 'storage'), WEBHDP_LINK_PUBLIC_BASE_URL='http://127.0.0.1:5100',
                      FRONTEND_URL=FRONTEND, ENABLE_RENDERER=False, ENABLE_USDZ_CONVERSION=False,
                      WEBHDP_DEPLOYMENT_MODE='local', WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=True)
    db.init_app(app)
    JWTManager(app)
    CORS(app, resources={r'/api/(?!v1/link(?:/|$)).*': {'origins': '*'}}, supports_credentials=True)
    app.register_blueprint(webhdp_link_bp, url_prefix=BASE)
    native = NativePipelineSystemService()
    app.native_pipeline_service = native
    with app.app_context():
        db.create_all()
        admin = User(email='admin@example.test', password_hash='unused', role=UserRole.ADMIN, is_verified=True)
        other = User(email='other@example.test', password_hash='unused', role=UserRole.USER, is_verified=True)
        db.session.add_all([admin, other]); db.session.commit()
        script = tmp_path / 'processor.py'
        script.write_text("import argparse,json\nfrom pathlib import Path\np=argparse.ArgumentParser();p.add_argument('--input-file');p.add_argument('--factor',type=int,default=2);a=p.parse_args()\nPath('answer.json').write_text(json.dumps({'value':int(Path(a.input_file).read_text())*a.factor}))\n")
        native.import_component_from_manifest({'metadata': {'name': 'link_api_processor', 'version': '1.0.0'},
            'inputs': [{'name': 'input_file', 'type': 'file_path', 'required': True}],
            'outputs': [{'name': 'answer', 'type': 'file_path', 'required': True}],
            'parameter_groups': [{'title': 'Options', 'parameters': [{'name': 'factor', 'type': 'integer', 'default': 2, 'minimum': 1, 'maximum': 10}]}],
            'execution': {'profiles': [{'id': 'local', 'adapter': 'local_cli', 'entrypoint': [sys.executable, str(script)], 'output_collection': [{'name': 'answer', 'path': 'answer.json'}]}]}})
        native.create_pipeline_version_from_config('link_api_pipeline', {'identifier': 'link_api_pipeline', 'name': 'HTTP test pipeline', 'version': '1.0.0',
            'steps': [{'id': 'process', 'name': 'Multiply', 'scope': 'record', 'component_ref': 'link_api_processor', 'execution_profile_ref': 'local', 'parameters': {'factor': 2},
                       'input_bindings': [{'kind': 'input', 'target': 'input_file', 'type': 'pipeline_source_file'}]}]}, activate=True)
        publication = {'id': 'arithmetic', 'name': 'Arithmetic', 'pipeline_identifier': 'link_api_pipeline', 'pipeline_version': '1.0.0',
                       'input': {'min_files': 1, 'max_files': 3, 'extensions': ['.txt']},
                       'parameters': {'factor': {'step_id': 'process', 'parameter': 'factor', 'type': 'integer', 'minimum': 1, 'maximum': 10, 'default': 2}}}
        link.save_publication(publication)
        link.save_publication({**publication, 'id': 'second'})
        client = link.save_client({'id': 'browser-app', 'name': 'Browser app', 'origins': [ORIGIN], 'redirect_uris': [REDIRECT], 'pipeline_ids': ['arithmetic', 'second']})
        client2 = link.save_client({'id': 'other-app', 'name': 'Other app', 'origins': ['http://127.0.0.1:5192'], 'redirect_uris': ['http://127.0.0.1:5192/callback'], 'pipeline_ids': ['arithmetic']})
        with app.test_request_context('/'):
            token = link.issue_token(client, admin, origin=ORIGIN)
            token2 = link.issue_token(client2, admin, service=True)
            other_token = link.issue_token(client, other, origin=ORIGIN)
        result = {'app': app, 'http': app.test_client(), 'admin': admin, 'other': other, 'client': client, 'client2': client2,
                  'token': token, 'token2': token2, 'other_token': other_token, 'root': tmp_path,
                  'jwt': create_access_token(identity=str(admin.id)), 'other_jwt': create_access_token(identity=str(other.id))}
        yield result
        db.session.remove(); db.drop_all()


def headers(api, token=None, origin=ORIGIN):
    result = {'Authorization': 'Bearer ' + (token or api['token'])['access_token']}
    if origin:
        result['Origin'] = origin
    return result


def jwt_headers(api, *, other=False):
    return {'Authorization': 'Bearer ' + api['other_jwt' if other else 'jwt'], 'Origin': FRONTEND}


def upload(api, content=b'21', name='input.txt', token=None, origin=ORIGIN):
    return api['http'].post(BASE + '/uploads', headers=headers(api, token, origin), data={'file': (io.BytesIO(content), name)})


def submit(api, upload_id, *, key=None, parameters=None, token=None, pipeline='arithmetic', origin=ORIGIN):
    return api['http'].post(BASE + '/runs', headers={**headers(api, token, origin), 'Idempotency-Key': key or str(uuid4())},
                            json={'pipeline_id': pipeline, 'inputs': [upload_id], 'parameters': parameters or {}})


def oauth(api, **overrides):
    verifier = 'a' * 43
    query = {'client_id': 'browser-app', 'redirect_uri': REDIRECT, 'response_type': 'code', 'code_challenge_method': 'S256',
             'code_challenge': base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='), 'state': 'unpredictable-state-123456789', 'scope': link.DEFAULT_SCOPE}
    query.update(overrides)
    return query, verifier


def test_discovery_openapi_and_origin_policy(api):
    response = api['http'].get(BASE + '/discovery', headers={'Origin': ORIGIN})
    assert response.status_code == 200
    data = response.json
    assert data['issuer'] == 'http://127.0.0.1:5100/api/v1/link'
    assert data['authorization_endpoint'] == FRONTEND + '/link/authorize'
    assert response.headers['Access-Control-Allow-Origin'] == ORIGIN
    assert 'Access-Control-Allow-Credentials' not in response.headers
    schema = api['http'].get(BASE + '/openapi.json').json
    assert schema['openapi'] == '3.1.0' and '/runs' in schema['paths']
    denied = api['http'].get(BASE + '/discovery', headers={'Origin': 'https://evil.example'})
    assert denied.status_code == 403 and denied.mimetype == 'application/problem+json'
    assert 'Access-Control-Allow-Origin' not in denied.headers
    assert api['http'].options(BASE + '/runs', headers={'Origin': ORIGIN, 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'Authorization,Idempotency-Key'}).status_code == 204
    assert api['http'].options(BASE + '/runs', headers={'Origin': ORIGIN, 'Access-Control-Request-Headers': 'X-HPC-Credential'}).status_code == 403


def test_pkce_code_flow_is_one_use_and_hashes_secrets(api):
    query, verifier = oauth(api)
    details = api['http'].get(BASE + '/oauth/request', query_string=query, headers={'Origin': FRONTEND})
    assert details.status_code == 200 and details.json['client']['id'] == 'browser-app'
    approved = api['http'].post(BASE + '/oauth/authorize', json={**query, 'approve': True}, headers=jwt_headers(api))
    assert approved.status_code == 200
    redirect = parse_qs(urlsplit(approved.json['redirect_uri']).query)
    assert redirect['state'][0] == query['state'] and redirect['iss'][0] == 'http://127.0.0.1:5100/api/v1/link'
    code = redirect['code'][0]
    assert db.session.get(LinkCode, code) is None
    assert db.session.get(LinkCode, link.digest(code)) is not None
    form = {'grant_type': 'authorization_code', 'client_id': 'browser-app', 'redirect_uri': REDIRECT, 'code': code, 'code_verifier': verifier}
    wrong = api['http'].post(BASE + '/oauth/token', data={**form, 'code_verifier': 'b' * 43}, headers={'Origin': ORIGIN})
    assert wrong.status_code == 400 and wrong.json['error'] == 'invalid_grant'
    response = api['http'].post(BASE + '/oauth/token', data=form, headers={'Origin': ORIGIN})
    assert response.status_code == 200 and response.json['token_type'] == 'Bearer'
    assert LinkToken.query.filter_by(token_hash=link.digest(response.json['access_token'])).one()
    assert api['http'].post(BASE + '/oauth/token', data=form, headers={'Origin': ORIGIN}).status_code == 400
    assert response.headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('overrides', [{'redirect_uri': REDIRECT + '/else'}, {'code_challenge_method': 'plain'}, {'state': ''}, {'scope': 'admin:all'}, {'response_type': 'token'}])
def test_invalid_oauth_request_never_returns_redirect(api, overrides):
    query, _ = oauth(api, **overrides)
    response = api['http'].post(BASE + '/oauth/authorize', json={**query, 'approve': True}, headers=jwt_headers(api))
    assert response.status_code == 400 and 'redirect_uri' not in response.json


def test_consent_denial_and_cross_origin_jwt_denied(api):
    query, _ = oauth(api)
    denied = api['http'].post(BASE + '/oauth/authorize', json={**query, 'approve': False}, headers=jwt_headers(api))
    assert parse_qs(urlsplit(denied.json['redirect_uri']).query)['error'] == ['access_denied']
    assert LinkCode.query.count() == 0
    attack = api['http'].post(BASE + '/oauth/authorize', json={**query, 'approve': True}, headers={'Authorization': 'Bearer ' + api['jwt'], 'Origin': ORIGIN})
    assert attack.status_code == 403


def test_token_expiry_revocation_account_and_origin_binding(api):
    row = db.session.get(LinkToken, api['token']['token_id'])
    assert api['http'].get(BASE + '/pipelines', headers=headers(api, origin='http://127.0.0.1:5192')).status_code == 403
    row.expires_at = link.now() - timedelta(seconds=1); db.session.commit()
    assert api['http'].get(BASE + '/pipelines', headers=headers(api)).status_code == 401
    row.expires_at = link.now() + timedelta(hours=1); row.revoked = True; db.session.commit()
    assert api['http'].get(BASE + '/pipelines', headers=headers(api)).status_code == 401
    row.revoked = False; api['admin'].token_version += 1; db.session.commit()
    assert api['http'].get(BASE + '/pipelines', headers=headers(api)).status_code == 401


def test_service_tokens_rejected_in_browsers_and_scopes_enforced(api):
    assert api['http'].get(BASE + '/pipelines', headers=headers(api, api['token2'], 'http://127.0.0.1:5192')).status_code == 403
    assert api['http'].get(BASE + '/pipelines', headers=headers(api, api['token2'], None)).status_code == 200
    row = db.session.get(LinkToken, api['token']['token_id']); row.scope = 'pipelines:read'; db.session.commit()
    assert upload(api).status_code == 403
    assert api['http'].get(BASE + '/admin/clients', headers=headers(api)).status_code == 403


def test_uploads_are_bounded_and_no_paths_or_cross_principal_inputs(api):
    assert upload(api, name='../escape.txt').status_code == 400
    config = link.client_config(api['client']); config['max_upload_bytes'] = 3
    api['client'].config_json = link.dumps(config); db.session.commit()
    assert upload(api, b'too large').status_code == 413
    assert LinkUpload.query.count() == 0
    good = upload(api).json
    assert good['sha256'] == hashlib.sha256(b'21').hexdigest()
    assert 'path' not in good
    assert submit(api, good['id'], token=api['other_token']).status_code == 404
    assert submit(api, good['id'], token=api['token2'], origin=None).status_code == 404


@pytest.mark.parametrize('parameters', [{'factor': 0}, {'factor': 100}, {'factor': True}, {'factor': '3'}, {'command': 'whoami'}])
def test_parameter_contract_rejects_unsafe_or_wrong_values(api, parameters):
    uploaded = upload(api).json
    response = submit(api, uploaded['id'], parameters=parameters)
    assert response.status_code == 400 and LinkRun.query.count() == 0


def test_idempotency_queue_quota_and_cancel(api):
    uploaded = upload(api).json
    key = str(uuid4())
    first = submit(api, uploaded['id'], key=key)
    again = submit(api, uploaded['id'], key=key)
    assert first.status_code == again.status_code == 202 and first.json['id'] == again.json['id']
    assert again.json['reused'] is True and LinkRun.query.count() == 1
    assert submit(api, uploaded['id'], key=key, parameters={'factor': 3}).status_code == 409
    config = link.client_config(api['client']); config['max_queued_runs'] = 1
    api['client'].config_json = link.dumps(config); db.session.commit()
    assert submit(api, uploaded['id']).status_code == 429
    run_id = first.json['id']
    assert api['http'].delete(BASE + '/uploads/' + uploaded['id'], headers=headers(api)).status_code == 409
    assert api['http'].post(BASE + '/runs/' + run_id + '/cancel', headers=headers(api)).json['status'] == 'cancelled'
    assert worker.process_next() is False
    assert api['http'].delete(BASE + '/uploads/' + uploaded['id'], headers=headers(api)).status_code == 204


def test_per_account_link_quotas_leave_capacity_for_a_second_account(api):
    other_token = api['other_token']
    client = link.save_client({'max_queued_runs': 3, 'max_queued_runs_per_user': 1,
                               'max_storage_bytes': 100, 'max_storage_bytes_per_user': 10}, existing=api['client'])
    assert link.serialize_client(client)['account_limits'] == {'max_queued_runs': 1, 'max_storage_bytes': 10}

    first_file = upload(api, b'21', token=other_token).json
    assert submit(api, first_file['id'], token=other_token).status_code == 202
    queued = submit(api, first_file['id'], token=other_token)
    assert queued.status_code == 429 and queued.json['code'] == 'account_queue_quota_exceeded'
    over_storage = upload(api, b'0123456', token=other_token)
    assert over_storage.status_code == 413 and over_storage.json['code'] == 'account_storage_quota_exceeded'
    assert link.storage_used(client.id, api['other'].id) == 4

    second_file = upload(api, b'12').json
    assert submit(api, second_file['id']).status_code == 202
    assert link.storage_used(client.id) == 8


def test_link_dispatch_gives_an_idle_account_a_worker_before_a_second_job(api):
    api['app'].config['WEBHDP_LINK_MAX_CONCURRENT_RUNS'] = 2
    link.save_client({'max_concurrent_runs': 2}, existing=api['client'])
    first_file = upload(api).json
    first = submit(api, first_file['id']).json['id']
    second = submit(api, first_file['id']).json['id']
    other_file = upload(api, token=api['other_token']).json
    third = submit(api, other_file['id'], token=api['other_token']).json['id']
    assert worker.claim_next() == first
    assert worker.claim_next() == third
    assert db.session.get(LinkRun, second).status == 'queued'


def test_demo_accounts_cannot_receive_or_keep_link_authorization(api):
    api['other'].set_capabilities(['model_publication_demo'])
    db.session.commit()
    with pytest.raises(link.LinkError, match='not eligible'):
        link.issue_token(api['client'], api['other'], service=True)
    assert api['http'].get(BASE + '/pipelines', headers=headers(api, api['other_token'])).status_code == 403


def test_pipeline_grants_limit_history_and_idempotent_reuse(api):
    uploaded = upload(api).json
    key = str(uuid4())
    created = submit(api, uploaded['id'], key=key, pipeline='second').json
    token = db.session.get(LinkToken, api['token']['token_id']); token.pipeline_ids_json = '["arithmetic"]'; db.session.commit()
    assert api['http'].get(BASE + '/runs/' + created['id'], headers=headers(api)).status_code == 404
    assert api['http'].get(BASE + '/runs', headers=headers(api)).json['runs'] == []
    assert submit(api, uploaded['id'], key=key, pipeline='second').status_code == 404


def test_real_http_job_download_hosted_progress_and_isolation(api):
    uploaded = upload(api).json
    response = submit(api, uploaded['id'], parameters={'factor': 3})
    run_id = response.json['id']
    assert response.json['progress_url'] == FRONTEND + '/link/jobs/' + run_id
    assert worker.process_next() is True
    result = api['http'].get(BASE + '/runs/' + run_id, headers=headers(api)).json
    assert result['status'] == 'succeeded', result
    assert result['progress'] == {'completed': 1, 'total': 1, 'phase': 'completed'}
    assert len(result['artifacts']) == 1
    assert str(api['root']) not in json.dumps(result)
    artifact = result['artifacts'][0]
    downloaded = api['http'].get(artifact['download_url'], headers=headers(api))
    assert downloaded.status_code == 200 and json.loads(downloaded.data)['value'] == 63
    assert hashlib.sha256(downloaded.data).hexdigest() == artifact['sha256']
    assert 'attachment' in downloaded.headers['Content-Disposition']
    assert api['http'].get(artifact['download_url'], headers=headers(api, api['other_token'])).status_code == 404
    assert api['http'].get(artifact['download_url'], headers=headers(api, api['token2'], None)).status_code == 404
    assert api['http'].get(BASE + '/jobs/' + run_id, headers=jwt_headers(api)).status_code == 200
    assert api['http'].get(BASE + '/jobs/' + run_id, headers=jwt_headers(api, other=True)).status_code == 404
    assert api['http'].get(BASE + '/jobs/' + run_id + '/artifacts/' + artifact['id'], headers=jwt_headers(api)).data == downloaded.data
    assert api['http'].get(BASE + '/jobs', headers=jwt_headers(api)).json['jobs'][0]['client_name'] == 'Browser app'
    path = link.artifact_path(db.session.get(LinkRun, run_id), db.session.get(LinkArtifact, artifact['id']))
    path.unlink(); path.symlink_to(Path(__file__))
    assert api['http'].get(artifact['download_url'], headers=headers(api)).status_code == 404


def test_progress_phase_distinguishes_worker_claim_resource_wait_and_result_finalization(api):
    from database.models import HpcAllocation, PipelineRun, PipelineRunStatus, PipelineVersion, Session
    created = submit(api, upload(api).json['id']).json
    run = db.session.get(LinkRun, created['id'])
    assert created['progress']['phase'] == 'queued'
    run.status = 'running'; run.started_at = link.now()
    db.session.commit()
    # Local preparation is processing; claiming a worker does not by itself
    # mean an HPC-backed pipeline has resources or has started a component.
    assert link.serialize_run(run)['progress']['phase'] == 'processing'
    saved = link.loads(run.request_json)
    saved['publication']['hpc'] = {'enabled': True}
    run.request_json = link.dumps(saved); db.session.commit()
    assert link.serialize_run(run)['progress']['phase'] == 'waiting_for_resources'
    session = Session(user_id=run.user_id, session_dir=str(api['root'] / 'private-job'), origin_type='webhdp_link')
    db.session.add(session); db.session.flush()
    version = db.session.get(PipelineVersion, run.pipeline_version_id)
    native = PipelineRun(pipeline_definition_id=version.pipeline_definition_id, pipeline_version_id=version.id,
        session_id=session.id, initiated_by_user_id=run.user_id, status=PipelineRunStatus.PENDING)
    allocation = HpcAllocation(user_id=run.user_id, session_id=session.id, purpose='workflow', status='allocating',
        requested_partition='private-partition', requested_gpu_type='private-gpu-model', requested_gpu_count=1,
        requested_duration_minutes=720, remote_job_id='PRIVATE-SCHEDULER-ID', node_name='private-compute-node',
        remote_session_dir='/private/cluster/workspace')
    db.session.add_all([native, allocation]); db.session.flush()
    run.session_id, run.native_run_id = session.id, native.id
    saved['_hpc_allocation_id'] = allocation.public_id
    run.request_json = link.dumps(saved); db.session.commit()
    for allocation_state in ('queued', 'allocating'):
        allocation.status = allocation_state; db.session.commit()
        response = api['http'].get(BASE + '/runs/' + run.id, headers=headers(api))
        assert response.status_code == 200
        assert response.json['status'] == 'running'
        assert response.json['progress'] == {'completed': 0, 'total': 1, 'phase': 'waiting_for_resources'}
        public_json = json.dumps(response.json)
        assert all(value not in public_json for value in ('PRIVATE-SCHEDULER-ID', 'private-compute-node',
            '/private/cluster', 'private-partition', 'private-gpu-model', allocation.public_id))
        assert api['http'].get(BASE + '/jobs/' + run.id, headers=jwt_headers(api)).json['progress'] == response.json['progress']
    allocation.status = 'running'; db.session.commit()
    assert link.serialize_run(run)['progress']['phase'] == 'processing'
    # An allocation belonging to another principal cannot influence this job's
    # public phase even if a stale internal reference points to it.
    allocation.user_id = api['other'].id; db.session.commit()
    assert link.serialize_run(run)['progress']['phase'] == 'waiting_for_resources'
    allocation.user_id = run.user_id
    allocation.status = 'failed'; db.session.commit()
    assert link.serialize_run(run)['progress']['phase'] == 'finalizing'
    native.status = PipelineRunStatus.RUNNING; db.session.commit()
    assert link.serialize_run(run)['progress']['phase'] == 'processing'
    for native_status in (PipelineRunStatus.COMPLETED, PipelineRunStatus.FAILED):
        native.status = native_status; db.session.commit()
        assert link.serialize_run(run)['progress']['phase'] == 'finalizing'


@pytest.mark.parametrize('status', ['succeeded', 'failed', 'cancelled'])
def test_terminal_progress_phase_preserves_success_failure_and_cancellation(api, status):
    created = submit(api, upload(api).json['id']).json
    run = db.session.get(LinkRun, created['id'])
    run.status = status
    run.error_code = 'execution_failed' if status == 'failed' else None
    db.session.commit()
    result = api['http'].get(BASE + '/runs/' + run.id, headers=headers(api)).json
    assert result['status'] == status and result['progress']['phase'] == 'completed'
    assert bool(result['error']) is (status == 'failed')
    schema = api['http'].get(BASE + '/openapi.json').json['components']['schemas']['Progress']
    assert result['progress']['phase'] in schema['properties']['phase']['enum']
    assert 'phase' not in schema['required']  # Older servers remain compatible.


def test_publication_immutable_admin_and_user_grant_revocation(api):
    assert api['http'].get(BASE + '/admin/clients', headers=jwt_headers(api, other=True)).status_code == 403
    assert api['http'].patch(BASE + '/admin/publications/arithmetic', headers=jwt_headers(api), json={'pipeline_version': '2.0.0'}).status_code == 409
    assert api['http'].patch(BASE + '/admin/publications/arithmetic', headers=jwt_headers(api), json={'enabled': False}).status_code == 200
    assert [x['id'] for x in api['http'].get(BASE + '/pipelines', headers=headers(api)).json['pipelines']] == ['second']
    token_id = api['token']['token_id']
    assert api['http'].delete(BASE + '/grants/' + token_id, headers=jwt_headers(api, other=True)).status_code == 404
    assert api['http'].delete(BASE + '/grants/' + token_id, headers=jwt_headers(api)).status_code == 204
    assert api['http'].get(BASE + '/pipelines', headers=headers(api)).status_code == 401
    grants = api['http'].get(BASE + '/grants', headers=jwt_headers(api)).json['grants']
    assert all('access_token' not in x and 'token_hash' not in x for x in grants)


def test_client_disabled_blocks_existing_tokens_and_jobs(api):
    uploaded = upload(api).json
    created = submit(api, uploaded['id']).json
    api['client'].enabled = False; db.session.commit()
    assert api['http'].get(BASE + '/pipelines', headers=headers(api, origin=None)).status_code == 401
    assert worker.process_next() is False
    row = db.session.get(LinkRun, created['id'])
    assert row.status == 'failed' and row.error_code == 'authorization_revoked'



def test_request_size_limits_apply_before_multipart_spooling(api, monkeypatch):
    config = link.client_config(api['client']); config['max_upload_bytes'] = 16
    api['client'].config_json = link.dumps(config); db.session.commit()
    assert upload(api, b'1234567890').status_code == 201
    called = []
    monkeypatch.setattr(link, 'accept_upload', lambda *a: called.append(True))
    response = upload(api, b'x' * 20000)
    assert response.status_code == 413 and not called
    large_json = api['http'].post(BASE + '/runs', headers=headers(api), json={'unknown': 'x' * 70000})
    assert large_json.status_code == 413



def test_cancelling_an_unstarted_run_releases_its_storage_reservation(api):
    config = link.client_config(api['client']); config['max_storage_bytes'] = 4
    api['client'].config_json = link.dumps(config); db.session.commit()
    uploaded = upload(api).json
    created = submit(api, uploaded['id'])
    assert created.status_code == 202 and link.storage_used(api['client'].id) == 4
    assert submit(api, uploaded['id']).status_code == 413
    assert api['http'].post(BASE + '/runs/' + created.json['id'] + '/cancel', headers=headers(api)).status_code == 200
    assert link.storage_used(api['client'].id) == 2
    assert submit(api, uploaded['id']).status_code == 202
