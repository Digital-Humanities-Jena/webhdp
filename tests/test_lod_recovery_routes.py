import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask_jwt_extended import JWTManager, create_access_token

from test_lod_reliability import services_app, specification
from test_hdpc_zenodo_service import _create_hdpc_with_source, _DummyZenodoHttp
from services.hdpc_local_service import create_local_record_with_metadata
from services.hdpc_zenodo_service import create_api_draft
from services.lod_artifact_service import generate_artifacts


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
        generate_artifacts(str(output), specification(), Mock())
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
