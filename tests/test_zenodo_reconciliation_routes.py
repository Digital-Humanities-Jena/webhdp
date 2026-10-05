import json
from unittest.mock import Mock

import requests

from database.database import db
from routes.session_routes import session_bp
from services import hdpc_zenodo_service as zenodo
from services.hdpc_local_service import create_local_record_with_metadata
from test_hdpc_zenodo_service import _create_hdpc_with_source, _DummyResponse
from test_playground_reliability import playground


def test_reconciliation_requires_edit_permission_and_uses_record_environment(playground, monkeypatch):
    p = playground
    p.app.register_blueprint(session_bp, url_prefix='/api/v1/sessions')
    _create_hdpc_with_source(p.session.hdpc_path, str(p.root))
    create_local_record_with_metadata(p.session.hdpc_path, file_id=101, metadata={'title': 'Object'}, is_sandbox=True, access_token='test-token')
    p.session.default_zenodo_environment = 'production'
    db.session.commit()
    http = Mock()
    http.post.side_effect = requests.Timeout('acknowledgement lost')
    assert zenodo.create_api_draft(p.session.hdpc_path, 1, http=http)['reconciliation_required']
    import sqlite3
    with sqlite3.connect(p.session.hdpc_path) as conn:
        original = json.loads(conn.execute('SELECT request_json FROM zenodo_remote_operations').fetchone()[0])
    http.get.return_value = _DummyResponse(200, {'id': 9001, 'metadata': original['metadata'], 'state': 'inprogress', 'submitted': False})
    token_lookup = Mock(return_value={'token': 'test-token'})
    monkeypatch.setattr('routes.session_routes.publishing_context_service.resolve_token_for_session', token_lookup)
    monkeypatch.setattr('routes.session_routes.reconcile_remote_operation', lambda *args, **kwargs: zenodo.reconcile_remote_operation(*args, **kwargs, http=http))
    url = f'/api/v1/sessions/{p.session.id}/records/1/reconcile'
    assert p.client.post(url, json={'deposition_id': '9001'}, headers=p.headers[1]).status_code == 404
    token_lookup.assert_not_called()
    result = p.client.post(url, json={'deposition_id': '9001', 'is_sandbox': False}, headers=p.headers[0])
    assert result.status_code == 200
    assert result.get_json()['data']['success']
    assert token_lookup.call_args.args[1] == 'sandbox'
    assert http.get.call_args.args[0].startswith('https://sandbox.zenodo.org/')
    p.session.access_mode = 'explorer_only'
    db.session.commit()
    assert p.client.post(url, json={}, headers=p.headers[0]).status_code == 409
