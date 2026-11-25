import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask_jwt_extended import JWTManager, create_access_token

from test_lod_reliability import services_app, specification
from test_hdpc_zenodo_service import _create_hdpc_with_source, _DummyZenodoHttp
from services.hdpc_local_service import create_local_record_with_metadata, read_hdpc_record_context
from services.hdpc_schema_service import connect_hdpc
from services.hdpc_zenodo_service import create_api_draft
from services.lod_artifact_service import generate_artifacts, record_lod_readiness


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    from routes.session_routes import session_bp
    app = services_app()
    app.config['JWT_SECRET_KEY'] = 'a-test-secret-key-that-is-at-least-32-bytes'
    JWTManager(app)
    app.register_blueprint(session_bp, url_prefix='/sessions')
    hdpc = str(tmp_path / 'project.hdpc')
    _create_hdpc_with_source(hdpc, str(tmp_path))
    create_local_record_with_metadata(hdpc, file_id=101, metadata={'title': 'Museum object', 'creators': [{'name': 'Museum'}]}, is_sandbox=True, access_token='test-token')
    create_api_draft(hdpc, 1, http=_DummyZenodoHttp())
    session = SimpleNamespace(hdpc_path=hdpc, session_dir=str(tmp_path), id=42)
    permission = Mock(return_value=(session, None, None))
    monkeypatch.setattr('routes.access_helpers.get_session_with_permission', permission)
    output = tmp_path / 'outputs' / 'record-1' / 'model'
    with app.app_context():
        from services.lod_artifact_service import current_record_context
        generate_artifacts(str(output), {**specification(), 'record': current_record_context(hdpc, 1)}, Mock())
        token = create_access_token(identity='1')
    return app, permission, {'Authorization': f'Bearer {token}'}, hdpc


def test_recovery_returns_safe_report_and_only_retries_local_generation(recovery):
    app, permission, headers, _ = recovery
    client = app.test_client()
    response = client.get('/sessions/42/records/1/lod', headers=headers)
    assert response.status_code == 200
    assert response.json['data']['formats']['edm']['success'] is False
    assert 'request' not in response.json['data']
    assert 'path' not in response.json['data']['formats']['jsonld']
    app.edm_service.validate_edm_document.return_value = {'valid': True}
    response = client.post('/sessions/42/records/1/lod', headers=headers)
    assert response.status_code == 200, response.json
    assert all(result['success'] for result in response.json['data']['formats'].values())
    assert app.iiif_service.generate_iiif_manifest_with_report.call_count == 1
    permission.assert_called_with(42, permission='edit', require_mutable=True)


def test_recovery_rejects_published_records_and_unauthorized_access(recovery):
    import sqlite3
    app, permission, headers, hdpc = recovery
    with sqlite3.connect(hdpc) as conn:
        conn.execute("UPDATE zenodo_records SET record_status='published' WHERE record_id=1")
    response = app.test_client().post('/sessions/42/records/1/lod', headers=headers)
    assert response.status_code == 400
    assert app.edm_service.generate_edm_xml_with_report.call_count == 1
    permission.return_value = (None, None, ({'success': False}, 404))
    assert app.test_client().get('/sessions/42/records/1/lod', headers=headers).status_code == 404
    assert app.test_client().post('/sessions/42/records/1/lod', headers=headers).status_code == 404
    assert app.test_client().get('/sessions/42/records/1/lod').status_code == 401


@pytest.mark.parametrize('record_status', ['published', 'done', 'submitted', 'completed'])
def test_finalized_record_uses_saved_validation_and_checks_integrity(recovery, record_status):
    app, _, headers, hdpc = recovery
    client = app.test_client()
    url = '/sessions/42/records/1/lod'
    app.edm_service.validate_edm_document.return_value = {'valid': True}
    assert client.post(url, headers=headers).status_code == 200
    with connect_hdpc(hdpc) as conn:
        conn.execute('UPDATE zenodo_records SET record_status = ? WHERE record_id = 1', (record_status,))
    app.config.update(LOCAL_EDM_VALIDATOR_REQUIRED=True, LOCAL_EDM_VALIDATOR_URL='http://new-validator')

    report = client.get(url, headers=headers).json['data']
    assert report['formats']['edm']['status'] == 'generated'
    assert report['formats']['edm']['validation']['valid'] is True
    assert report['readiness']['ready'] and not report['readiness']['revalidation_required']
    with app.app_context():
        assert read_hdpc_record_context(hdpc, 1)['zenodo_status']['lod_readiness']['ready']
        assert not record_lod_readiness(hdpc, 1)['ready']
    assert client.get(f'{url}?format=edm', headers=headers).data == b'<rdf/>'
    assert client.post(url, headers=headers).status_code == 400
    assert app.edm_service.generate_edm_xml_with_report.call_count == 2

    path = Path(hdpc).parent / 'outputs/record-1/model/edm.xml'
    path.write_text('tampered')
    assert client.get(f'{url}?format=edm', headers=headers).status_code == 400
    assert client.get(url, headers=headers).json['data']['formats']['edm']['status'] == 'failed'
    path.write_text('<rdf/>')
    with connect_hdpc(hdpc) as conn:
        conn.execute("UPDATE zenodo_records SET zenodo_record_id = '9102' WHERE record_id = 1")
    assert client.get(f'{url}?format=edm', headers=headers).status_code == 400
    assert client.get(url, headers=headers).json['data']['readiness']['record_changed']


def test_draft_validator_policy_change_keeps_unrelated_downloads(recovery):
    app, _, headers, _ = recovery
    client = app.test_client()
    url = '/sessions/42/records/1/lod'
    app.edm_service.validate_edm_document.return_value = {'valid': True}
    assert client.post(url, headers=headers).status_code == 200
    app.config.update(ENABLE_LOCAL_EDM_VALIDATION=True, LOCAL_EDM_VALIDATOR_REQUIRED=True,
                      LOCAL_EDM_VALIDATOR_URL='http://new-validator')

    report = client.get(url, headers=headers).json['data']
    assert report['readiness']['blocked_formats'] == ['edm']
    assert report['formats']['edm']['status'] == 'revalidation_required'
    assert client.get(f'{url}?format=edm', headers=headers).status_code == 400
    for standard in ('iiif', 'mets', 'cidoc_crm', 'jsonld'):
        assert report['formats'][standard]['status'] == 'generated'
        assert client.get(f'{url}?format={standard}', headers=headers).status_code == 200
    assert client.get(f'{url}?format=iiif', headers=headers).mimetype == 'application/ld+json'


def test_legacy_fingerprint_without_captured_policy_still_marks_all_drift(recovery):
    app, _, headers, hdpc = recovery
    client = app.test_client()
    url = '/sessions/42/records/1/lod'
    path = Path(hdpc).parent / 'outputs/record-1/model/lod-generation.json'
    manifest = json.loads(path.read_text())
    del manifest['validation_policy']
    path.write_text(json.dumps(manifest))

    assert client.get(f'{url}?format=iiif', headers=headers).status_code == 200
    app.config['LOCAL_EDM_VALIDATOR_URL'] = 'http://new-validator'
    assert client.get(f'{url}?format=iiif', headers=headers).status_code == 400
    report = client.get(url, headers=headers).json['data']
    assert set(report['readiness']['blocked_formats']) == set(manifest['formats'])


def test_download_checks_validation_and_file_integrity(recovery):
    from pathlib import Path
    app, _, headers, hdpc = recovery
    client = app.test_client()
    assert client.get('/sessions/42/records/1/lod?format=edm', headers=headers).status_code == 400
    response = client.get('/sessions/42/records/1/lod?format=jsonld', headers=headers)
    assert response.status_code == 200
    assert 'metadata.jsonld' in response.headers['Content-Disposition']
    assert '@context' in response.text
    path = Path(hdpc).parent / 'outputs/record-1/model/metadata.jsonld'
    path.write_text('tampered')
    assert client.get('/sessions/42/records/1/lod?format=jsonld', headers=headers).status_code == 400
    assert client.get('/sessions/42/records/1/lod?format=../../secret', headers=headers).status_code == 400


def test_legacy_interrupted_report_exposes_unattempted_formats(recovery):
    from pathlib import Path
    app, _, headers, hdpc = recovery
    path = Path(hdpc).parent / 'outputs/record-1/model/lod-generation.json'
    report = json.loads(path.read_text())
    report['formats'] = {}
    path.write_text(json.dumps(report))
    response = app.test_client().get('/sessions/42/records/1/lod', headers=headers)
    assert response.status_code == 200
    assert len(response.json['data']['formats']) == 5
    assert all(value['status'] == 'pending' for value in response.json['data']['formats'].values())
    assert response.json['data']['readiness']['state'] == 'blocked'


def test_recreated_draft_invalidates_exports_and_retry_updates_public_identity(recovery):
    from services.hdpc_schema_service import connect_hdpc
    app, _, headers, hdpc = recovery
    client = app.test_client()
    app.edm_service.validate_edm_document.return_value = {'valid': True}
    assert client.post('/sessions/42/records/1/lod', headers=headers).status_code == 200
    with connect_hdpc(hdpc) as conn:
        conn.execute("UPDATE zenodo_records SET zenodo_record_id = '9102', record_metadata_json = ? WHERE record_id = 1",
                     (json.dumps({'id': 9102, 'metadata': {'prereserve_doi': {'doi': '10.5072/zenodo.9102'}}}),))
    report = client.get('/sessions/42/records/1/lod', headers=headers).json['data']
    assert report['readiness']['record_changed']
    assert not report['readiness']['ready']
    assert report['formats']['jsonld']['status'] == 'regeneration_required'
    assert client.get('/sessions/42/records/1/lod?format=jsonld', headers=headers).status_code == 400
    report = client.post('/sessions/42/records/1/lod', headers=headers).json['data']
    assert report['readiness']['ready']
    output = client.get('/sessions/42/records/1/lod?format=jsonld', headers=headers)
    assert output.status_code == 200
    assert '9102' in output.text and '9001' not in output.text
    assert app.iiif_service.generate_iiif_manifest_with_report.call_count == 2


def test_lost_output_directory_can_be_rebuilt_from_project_recovery_state(recovery):
    import shutil
    from pathlib import Path
    app, _, headers, hdpc = recovery
    client = app.test_client()
    app.edm_service.validate_edm_document.return_value = {'valid': True}
    assert client.post('/sessions/42/records/1/lod', headers=headers).status_code == 200
    output = Path(hdpc).parent / 'outputs/record-1/model'
    (output / 'lod-generation.json').unlink()
    assert client.get('/sessions/42/records/1/lod', headers=headers).json['data']['readiness']['ready']
    shutil.rmtree(output)
    report = client.get('/sessions/42/records/1/lod', headers=headers).json['data']
    assert report['available'] and not report['readiness']['ready']
    regenerated = client.post('/sessions/42/records/1/lod', headers=headers)
    assert regenerated.status_code == 200
    assert regenerated.json['data']['readiness']['ready']
    assert (output / 'metadata.jsonld').is_file()


@pytest.mark.parametrize('corrupt', ['{truncated', '[]', '{"request": {}, "formats": {"edm": null}}'])
def test_corrupt_report_has_actionable_error_instead_of_server_error(recovery, corrupt):
    from pathlib import Path
    app, _, headers, hdpc = recovery
    (Path(hdpc).parent / 'outputs/record-1/model/lod-generation.json').write_text(corrupt)
    for method in (app.test_client().get, app.test_client().post):
        result = method('/sessions/42/records/1/lod', headers=headers)
        assert result.status_code == 400
        assert 'new pipeline run' in result.text


def test_project_backup_repairs_a_structurally_corrupt_output_report(recovery):
    from pathlib import Path
    app, _, headers, hdpc = recovery
    client = app.test_client()
    app.edm_service.validate_edm_document.return_value = {'valid': True}
    assert client.post('/sessions/42/records/1/lod', headers=headers).status_code == 200
    (Path(hdpc).parent / 'outputs/record-1/model/lod-generation.json').write_text('[]')
    response = client.post('/sessions/42/records/1/lod', headers=headers)
    assert response.status_code == 200
    assert response.json['data']['readiness']['ready']


def test_sparse_remote_response_does_not_forget_the_saved_doi(recovery):
    from services.hdpc_schema_service import connect_hdpc
    app, _, headers, hdpc = recovery
    client = app.test_client()
    app.edm_service.validate_edm_document.return_value = {'valid': True}
    assert client.post('/sessions/42/records/1/lod', headers=headers).status_code == 200
    with connect_hdpc(hdpc) as conn:
        conn.execute('UPDATE zenodo_records SET record_metadata_json = ? WHERE record_id = 1', (json.dumps({'id': 9001}),))
    assert client.get('/sessions/42/records/1/lod', headers=headers).json['data']['readiness']['ready']
