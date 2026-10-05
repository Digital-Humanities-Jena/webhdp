import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import PipelineRun, PipelineRunStatus, Session, User, UserMetadata, UserRole
from exceptions import ValidationError
from middleware import setup_error_handlers
from routes.pipeline_v2_routes import pipeline_v2_bp
from services.hdpc_scan_service import create_and_scan_hdpc_project
from services.msf_service import MSFService
from services.native_pipeline_system import NativePipelineSystemService
from services.registry_lock import OperationConflict
from services.submission_pipeline_service import execute_submission_pipeline
from test_mesh_optimizer_component import glb

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def workspace(tmp_path):
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='readiness-test-key', JWT_SECRET_KEY='readiness-jwt-key',
                      SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False,
                      ENABLE_RENDERER=True, ENABLE_USDZ_CONVERSION=True)
    db.init_app(app)
    JWTManager(app)
    setup_error_handlers(app)
    app.register_blueprint(pipeline_v2_bp, url_prefix='/api/v2')
    app.native_pipeline_service = NativePipelineSystemService()
    app.project_service = Mock()
    app.msf_service = MSFService()
    with app.app_context():
        db.create_all()
        user = User(email='owner@example.com', role=UserRole.ADMIN, is_verified=True)
        user.set_password('test-password')
        db.session.add(user)
        db.session.commit()
        native = app.native_pipeline_service
        native.ensure_seeded()
        from database.lod_template_bootstrap import ensure_default_lod_templates
        ensure_default_lod_templates()
        uploads = tmp_path / 'uploads'
        uploads.mkdir()
        source = glb(uploads / 'model.glb', scenes=[{'nodes': [0]}], nodes=[{'mesh': 0}])
        hdpc = tmp_path / 'session.hdpc'
        assert create_and_scan_hdpc_project(hdpc_path=str(hdpc), data_in_path=str(uploads),
            data_out_path=str(tmp_path / 'outputs'), project_name='Readiness', short_code='READY',
            modalities=['3d_model', 'image', 'text'], scan_options={'extensions': ['.glb'], 'primarysourceext': '.glb'})['success']
        session = Session(user_id=user.id, session_dir=str(tmp_path), hdpc_path=str(hdpc), status='ready')
        db.session.add(session)
        db.session.commit()
        metadata = UserMetadata(session_id=session.id, field_name='zenodo_metadata_draft', field_value=json.dumps({
            'title': 'Museum model', 'description': 'Documented source model', 'creators': [{'name': 'Museum'}],
            'upload_type': 'dataset', 'publication_date': '2026-10-06', 'access_right': 'open', 'license': 'cc-by-4.0'}))
        db.session.add(metadata)
        db.session.commit()
        component = tmp_path / 'component'
        component.mkdir()
        manifest = (ROOT / 'external_code/geometric_lod_generator/component.yaml').read_text()
        (component / 'component.yaml').write_text(manifest.replace('webhdp-geometric-lod-generator:local', 'example/lod@sha256:' + 'a' * 64))
        native.import_component_from_path(str(component))
        config = {'name': 'Detail levels', 'steps': [{
            'id': 'detail', 'name': 'Detail levels', 'enabled': True, 'scope': 'record',
            'component_ref': 'geometric_lod_generator', 'execution_profile_ref': 'local_docker',
            'parameters': {'target_ratio': 0.5}, 'input_bindings': [{'kind': 'input', 'target': 'input_file', 'type': 'pipeline_source_file'}]}]}
        validation = native.validate_pipeline_config(config)
        assert validation['valid'], validation
        native.create_pipeline_version_from_config('guarded_lod', config)
        payload = {'session_id': session.id, 'local_file_paths': [str(source)], 'record_ids': [],
                   'execution_items': [], 'is_sandbox': True, 'abort_on_critical_error': False}
        headers = {'Authorization': 'Bearer ' + create_access_token(identity=str(user.id))}
        yield app, native, session, user, source, metadata, payload, headers
        db.session.remove()
        db.drop_all()


def check(workspace, identifier='guarded_lod', **changes):
    app, native, session, user, _, _, payload, _ = workspace
    return native.check_submission_readiness(identifier, session.id, {**payload, **changes}, user.id)


def test_readiness_is_read_only_and_never_contacts_compute_or_zenodo(workspace):
    app, native, session, _, source, _, _, headers = workspace
    before = {str(path): path.read_bytes() for path in source.parents[1].rglob('*') if path.is_file()}
    with patch('requests.sessions.Session.request', side_effect=AssertionError('No network')), patch('subprocess.run', side_effect=AssertionError('No subprocess')):
        response = app.test_client().post('/api/v2/pipelines/guarded_lod/readiness', json=workspace[6], headers=headers)
    assert response.status_code == 200
    report = response.json['data']
    assert report['ready'], report
    assert report['selected_count'] == 1 and report['readiness_token']
    assert report['unverified'] and all('_state' not in key for key in report)
    assert PipelineRun.query.count() == 0
    assert before == {str(path): path.read_bytes() for path in source.parents[1].rglob('*') if path.is_file()}
    app.project_service.assert_not_called()


@pytest.mark.parametrize('damage', ['truncated', 'animation', 'morph', 'extra_scene'])
def test_invalid_model_blocks_execution_before_drafts_or_dispatch(workspace, damage):
    app, _, _, _, source, _, payload, headers = workspace
    if damage == 'truncated':
        source.write_bytes(b'glTF')
    else:
        extras = {'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}]}
        if damage == 'animation':
            extras['animations'] = [{}]
        if damage == 'morph':
            extras['meshes'] = [{'primitives': [{'attributes': {'POSITION': 0}, 'targets': [{'POSITION': 0}]}]}]
        if damage == 'extra_scene':
            extras['scenes'].append({'nodes': []})
        glb(source, **extras)
    report = check(workspace)
    assert not report['ready'] and report['blockers'][0]['source'] == source.name
    with patch('routes.pipeline_v2_routes._enqueue_submission_pipeline_task') as enqueue, patch('services.hdpc_zenodo_service.create_api_draft') as draft:
        response = app.test_client().post('/api/v2/pipelines/guarded_lod/execute', json={**payload, 'async_execution': True}, headers=headers)
    assert response.status_code == 400
    assert PipelineRun.query.count() == 0
    enqueue.assert_not_called()
    draft.assert_not_called()


@pytest.mark.parametrize('change', ['source', 'metadata', 'template', 'pipeline', 'parameters'])
def test_stale_readiness_rejected_and_same_request_reconnects(workspace, change):
    _, native, session, user, source, metadata, payload, _ = workspace
    report = check(workspace)
    assert report['ready'], report
    request = {**payload, 'request_id': str(uuid4()), 'readiness_token': report['readiness_token']}
    if change == 'source':
        glb(source, scenes=[{'nodes': [0]}], nodes=[{'mesh': 0}], extras={'label': 'changed'})
    elif change == 'metadata':
        metadata.field_value = metadata.field_value.replace('Museum model', 'Revised title'); db.session.commit()
    elif change == 'template':
        from database.models import LodTemplate
        row = LodTemplate.query.filter_by(standard='iiif').first()
        row.content += ' '; db.session.commit()
    elif change == 'pipeline':
        config = native.get_pipeline('guarded_lod')['config']
        config['description'] = 'Revised definition'
        native.create_pipeline_version_from_config('guarded_lod', config)
    else:
        request['abort_on_critical_error'] = True
    with pytest.raises(OperationConflict, match='changed'):
        native.create_pending_run('guarded_lod', session_id=session.id, initiated_by_user_id=user.id, request_payload=request)
    assert PipelineRun.query.count() == 0
    fresh = check(workspace, abort_on_critical_error=request.get('abort_on_critical_error', False))
    request['readiness_token'] = fresh['readiness_token']
    accepted = native.create_pending_run('guarded_lod', session_id=session.id, initiated_by_user_id=user.id, request_payload=request)
    source.unlink()
    retry = native.create_pending_run('guarded_lod', session_id=session.id, initiated_by_user_id=user.id, request_payload=request)
    assert accepted['run_id'] == retry['run_id'] and retry['reused']
    assert '_readiness_state' not in native.get_pipeline_run(accepted['run_id'])['request']


def test_queued_source_changes_fail_before_record_registration(workspace):
    app, native, session, user, source, _, payload, _ = workspace
    queued = native.create_pending_run('guarded_lod', session_id=session.id, initiated_by_user_id=user.id, request_payload=payload)
    glb(source, scenes=[{'nodes': [0]}], nodes=[{'mesh': 0}], extras={'changed': True})
    with patch('services.submission_pipeline_service.create_local_record_with_metadata') as register, patch('services.submission_pipeline_service.create_source_bundle') as bundle:
        with pytest.raises(OperationConflict, match='changed'):
            execute_submission_pipeline(identifier='guarded_lod', local_file_paths=payload['local_file_paths'],
                db_session_id=session.id, precreated_run_public_id=queued['run_id'])
    register.assert_not_called()
    bundle.assert_not_called()
    app.project_service.resolve_token_for_session.assert_not_called()
    assert PipelineRun.query.one().status == PipelineRunStatus.FAILED
    retry = execute_submission_pipeline(identifier='guarded_lod', local_file_paths=payload['local_file_paths'],
        db_session_id=session.id, precreated_run_public_id=queued['run_id'])
    assert retry['reused'] and not retry['result']['success']


def test_metadata_and_spreadsheet_checks_cover_later_selected_records(workspace):
    _, native, session, _, source, metadata, payload, _ = workspace
    second = glb(source.with_name('second.glb'), scenes=[{'nodes': [0]}], nodes=[{'mesh': 0}])
    create_and_scan_hdpc_project(hdpc_path=session.hdpc_path, data_in_path=str(source.parent),
        data_out_path=str(source.parents[1] / 'outputs'), project_name='Readiness', short_code='READY', modalities=['3d_model'], scan_options={'extensions': ['.glb'], 'primarysourceext': '.glb'})
    msf = source.parent / 'metadata.csv'
    msf.write_text('filename,title\nmodel.glb,Mapped model\n')
    values = json.loads(metadata.field_value)
    values.update(msf_path=str(msf), lod_mapping={'zenodo': {'3d': {'title': {'source': 'msf', 'field': 'title'}}}})
    metadata.field_value = json.dumps(values); db.session.commit()
    report = check(workspace, local_file_paths=[str(source), str(second)])
    assert not report['ready']
    assert any(item.get('source') == 'second.glb' and 'metadata row' in item['message'] for item in report['blockers']), report


def test_unauthorized_and_symlink_sources_cannot_be_read(workspace):
    app, native, session, user, source, _, payload, headers = workspace
    other = User(email='other@example.com', role=UserRole.USER, is_verified=True)
    other.set_password('test-password')
    db.session.add(other); db.session.commit()
    other_headers = {'Authorization': 'Bearer ' + create_access_token(identity=str(other.id))}
    assert app.test_client().post('/api/v2/pipelines/guarded_lod/readiness', json=payload, headers=other_headers).status_code in {403, 404}
    outside = source.parents[2] / 'outside.glb'
    outside.write_text('private')
    source.unlink(); source.symlink_to(outside)
    report = check(workspace)
    assert not report['ready'] and str(outside) not in json.dumps(report)


def test_missing_metadata_is_a_local_zenodo_blocker(workspace):
    _, _, _, _, _, metadata, _, _ = workspace
    metadata.field_value = json.dumps({'title': 'Incomplete'}); db.session.commit()
    report = check(workspace, 'metadata_only')
    assert not report['ready']
    assert any('creators' in item['message'] for item in report['blockers']), report


def test_batch_shared_creators_are_checked_before_unknown_defaults(workspace):
    _, _, session, _, _, metadata, _, _ = workspace
    from database.models import BatchFileMetadata
    db.session.add(BatchFileMetadata(session_id=session.id, filename='model.glb',
        metadata_json=json.dumps({'title': 'Individual model', 'description': 'A documented source.'})))
    db.session.commit()
    report = check(workspace, 'metadata_only')
    assert report['ready'], report
    values = json.loads(metadata.field_value)
    values.pop('creators')
    metadata.field_value = json.dumps(values); db.session.commit()
    report = check(workspace, 'metadata_only')
    assert not report['ready'] and any('creators' in issue['message'] for issue in report['blockers']), report


@pytest.mark.parametrize('parameters', [{'target_ratio': 1}, {'target_ratio': '0.5'}, {'max_relative_error': True}, {'max_relative_error': float('nan')}])
def test_known_parameter_errors_block_before_execution(workspace, parameters):
    _, native, _, _, _, _, _, _ = workspace
    config = native.get_pipeline('guarded_lod')['config']
    config['steps'][0]['parameters'].update(parameters)
    native.create_pipeline_version_from_config('guarded_lod', config)
    report = check(workspace)
    assert not report['ready'] and report['blockers'][0]['route'] == '/workflow/pipeline', report


def test_skipped_steps_and_future_outputs_are_checked_without_false_blockers(workspace):
    _, native, _, _, _, _, _, _ = workspace
    config = native.get_pipeline('guarded_lod')['config']
    first = config['steps'][0]
    second = {**first, 'id': 'second', 'name': 'Second detail level', 'input_bindings': [{
        'kind': 'input', 'target': 'input_file', 'type': 'artifact_file', 'source_step': 'detail', 'source_output': 'lod_medium'}]}
    config['steps'].append(second)
    native.create_pipeline_version_from_config('guarded_lod', config)
    report = check(workspace)
    assert report['ready'], report
    assert any('earlier steps' in item['message'] for item in report['unverified'])
    first['triggers'] = {'default_behavior': 'skip', 'rules': []}
    native.create_pipeline_version_from_config('guarded_lod', config)
    report = check(workspace)
    assert not report['ready'] and any('skipped' in item['message'] for item in report['blockers'])


def test_skipped_zenodo_steps_do_not_require_publication_metadata(workspace):
    _, native, _, _, _, metadata, _, _ = workspace
    values = json.loads(metadata.field_value)
    values.pop('creators')
    metadata.field_value = json.dumps(values); db.session.commit()
    config = native.get_pipeline('guarded_lod')['config']
    draft = next(step for step in native.get_pipeline('metadata_only')['config']['steps'] if step['component_ref'] == 'zenodo_draft')
    draft['triggers'] = {'default_behavior': 'skip', 'rules': []}
    config['steps'].append(draft)
    native.create_pipeline_version_from_config('guarded_lod', config)
    report = check(workspace)
    assert report['ready'], report
    draft['triggers']['default_behavior'] = 'run'
    native.create_pipeline_version_from_config('guarded_lod', config)
    report = check(workspace)
    assert not report['ready'] and any('creators' in issue['message'] for issue in report['blockers'])


def test_missing_model_dependencies_block_before_drafts(workspace):
    app, _, session, _, source, _, _, _ = workspace
    model = source.with_suffix('.gltf')
    model.write_text(json.dumps({'asset': {'version': '2.0'}, 'buffers': [{'uri': 'missing.bin', 'byteLength': 12}]}))
    result = create_and_scan_hdpc_project(hdpc_path=session.hdpc_path, data_in_path=str(source.parent),
        data_out_path=str(source.parents[1] / 'outputs'), project_name='Readiness', short_code='READY',
        modalities=['3d_model'], scan_options={'extensions': ['.gltf'], 'primarysourceext': '.gltf'})
    assert result['success'], result
    with patch('services.hdpc_zenodo_service.create_api_draft') as draft:
        report = check(workspace, 'metadata_only', local_file_paths=[str(model)])
    assert not report['ready'] and any('resources are missing' in issue['message'] for issue in report['blockers']), report
    draft.assert_not_called()


def test_saved_batch_decisions_bind_the_source_and_skip_plan(workspace):
    _, _, session, _, source, _, _, _ = workspace
    from services.dataset_integrity_service import analyze_session_record_resolution
    candidate = analyze_session_record_resolution(session)['candidates'][0]
    item = {'decision_key': candidate['decision_key'], 'action': candidate['selected_action'],
            'source_file_path': str(source), 'target_session_id': None, 'target_local_record_id': None,
            'target_concept_rec_id': None, 'forced_override_reason': None}
    report = check(workspace, local_file_paths=[], execution_items=[item])
    assert report['ready'], report
    report = check(workspace, local_file_paths=[], execution_items=[{**item, 'source_file_path': str(source.with_name('wrong.glb'))}])
    assert not report['ready'] and any('saved session plan' in issue['message'] for issue in report['blockers']), report
    report = check(workspace, local_file_paths=[], execution_items=[{**item, 'action': 'skip'}])
    assert not report['ready'] and any('marked as skip' in issue['message'] for issue in report['blockers'])


def test_record_reruns_check_the_actual_record_metadata(workspace):
    _, native, session, _, source, metadata, _, _ = workspace
    from services.hdpc_local_service import create_local_record_with_metadata, get_hdpc_file_id_map
    file_id = get_hdpc_file_id_map(session.hdpc_path)['model.glb']
    created = create_local_record_with_metadata(session.hdpc_path, file_id=file_id,
        metadata=json.loads(metadata.field_value), is_sandbox=True)
    rid = created['local_record_db_id']
    report = check(workspace, 'metadata_only', local_file_paths=[], record_ids=[rid])
    assert report['ready'], report
    report = check(workspace, local_file_paths=[], record_ids=[rid + 999])
    assert not report['ready']


def test_invalid_template_is_a_local_blocker_and_invalid_tokens_require_recheck(workspace):
    _, native, session, user, _, _, payload, _ = workspace
    from database.models import LodTemplate
    report = check(workspace)
    with pytest.raises(OperationConflict, match='expired or is invalid'):
        native.create_pending_run('guarded_lod', session_id=session.id, initiated_by_user_id=user.id,
                                  request_payload={**payload, 'readiness_token': report['readiness_token'] + 'invalid'})
    assert PipelineRun.query.count() == 0
    template = LodTemplate.query.filter_by(standard='iiif').first()
    template.content = '{% if %}'
    db.session.commit()
    report = check(workspace, 'metadata_only')
    assert not report['ready'] and report['blockers'][0]['route'] == '/workflow/edm-selection'


def test_expired_token_cannot_start_a_new_run(workspace):
    _, native, session, user, _, _, payload, _ = workspace
    with patch('itsdangerous.timed.time.time', return_value=time.time() - 3601):
        report = check(workspace)
    with pytest.raises(OperationConflict, match='expired'):
        native.create_pending_run('guarded_lod', session_id=session.id, initiated_by_user_id=user.id,
                                  request_payload={**payload, 'readiness_token': report['readiness_token']})
    assert PipelineRun.query.count() == 0


def test_unused_templates_do_not_block_or_get_created(workspace):
    _, native, session, user, _, _, payload, _ = workspace
    from database.models import LodTemplate
    LodTemplate.query.delete(); db.session.commit()
    report = check(workspace)
    assert report['ready'], report
    native.create_pending_run('guarded_lod', session_id=session.id, initiated_by_user_id=user.id,
                             request_payload={**payload, 'readiness_token': report['readiness_token']})
    assert LodTemplate.query.count() == 0


def test_only_enabled_metadata_formats_require_templates(workspace):
    _, native, _, _, _, _, _, _ = workspace
    from database.models import LodTemplate
    LodTemplate.query.filter_by(standard='iiif').delete(); db.session.commit()
    assert not check(workspace, 'metadata_only')['ready']
    config = native.get_pipeline('metadata_only')['config']
    next(step for step in config['steps'] if step['component_ref'] == 'lod_generation')['parameters']['generate_iiif'] = False
    native.create_pipeline_version_from_config('metadata_only', config)
    report = check(workspace, 'metadata_only')
    assert report['ready'], report


def test_readiness_api_token_accepts_canonical_execution_and_retry(workspace):
    app, _, _, _, source, _, payload, headers = workspace
    client = app.test_client()
    report = client.post('/api/v2/pipelines/guarded_lod/readiness', json={
        'session_id': payload['session_id'], 'local_file_paths': payload['local_file_paths'],
    }, headers=headers).json['data']
    assert report['ready'], report
    request = {**payload, 'async_execution': True, 'expected_version': report['pipeline_version'],
               'readiness_token': report['readiness_token'], 'request_id': str(uuid4())}
    with patch('routes.pipeline_v2_routes._enqueue_submission_pipeline_task', return_value=SimpleNamespace(id='queued')) as enqueue:
        accepted = client.post('/api/v2/pipelines/guarded_lod/execute', json=request, headers=headers)
        assert accepted.status_code == 202, accepted.json
        source.unlink()
        retry = client.post('/api/v2/pipelines/guarded_lod/execute', json=request, headers=headers)
    assert retry.status_code == 202 and retry.json['data']['run_id'] == accepted.json['data']['run_id']
    assert PipelineRun.query.count() == 1
    enqueue.assert_called_once()
