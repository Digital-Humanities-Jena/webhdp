import json
from unittest.mock import patch

import pytest
from flask_jwt_extended import create_access_token

from database.database import db
from database.models import Session, User
from browser_api import FixtureAdapter
from services.pipeline_checkpoints import journal
from test_pipeline_checkpoints import execute
from test_submission_readiness import workspace


@pytest.fixture
def reviewed(workspace):
    app, native, session, user, source, _, payload, headers = workspace
    adapter = FixtureAdapter()
    adapter.failures[session.id] = False
    native._adapter_registry['container_cli'] = adapter
    context = app, native, session, user, payload, headers, adapter
    with patch('services.submission_pipeline_service.publishing_context_service.resolve_token_for_session', return_value={'environment': 'sandbox', 'source': 'user', 'token': None}):
        run, result = execute(context, payload)
    assert result['result']['success'], result
    rid = result['result']['details'][0]['record_id']
    return app.test_client(), session, headers, run, rid, source


def endpoint(session, rid):
    return f'/api/v2/sessions/{session.id}/records/{rid}/derivatives'


def test_review_uses_verified_report_and_streams_each_level(reviewed):
    client, session, headers, run, rid, source = reviewed
    response = client.get(endpoint(session, rid), headers=headers)
    assert response.status_code == 200
    detail = response.json['data']['sets'][0]
    assert [model['level'] for model in detail['models']] == ['source', 'high', 'medium', 'low']
    assert all(model['repaired_tangents'] == 0 for model in detail['models'][1:])
    for model in detail['models']:
        response = client.get(f"{endpoint(session, rid)}/{detail['step_run_id']}/{model['level']}", headers=headers)
        assert response.status_code == 200
        assert response.data == source.read_bytes()
        assert response.headers['X-Content-SHA256'] == model['sha256']
        assert response.headers['Cache-Control'] == 'no-store'
    assert '_checkpoints' not in json.dumps(client.get(f'/api/v2/runs/{run.public_id}', headers=headers).json['data'])


@pytest.mark.parametrize('damage', ['report', 'model', 'source', 'escape', 'missing_journal'])
def test_review_rejects_changed_or_unverifiable_content(reviewed, tmp_path, damage):
    from pathlib import Path
    client, session, headers, run, rid, source = reviewed
    detail = client.get(endpoint(session, rid), headers=headers).json['data']['sets'][0]
    saved = journal(run)[str(rid)]['steps']['detail']
    if damage == 'missing_journal':
        payload = json.loads(run.request_json)
        payload.pop('_checkpoints')
        run.request_json = json.dumps(payload)
        db.session.commit()
    elif damage == 'escape':
        output = Path(saved['outputs']['lod_medium'])
        outside = tmp_path / 'outside.glb'
        outside.write_bytes(output.read_bytes())
        output.unlink()
        output.symlink_to(outside)
        # Put the target outside the session root, not merely its output folder.
        session.session_dir = str(source.parent)
        db.session.commit()
    else:
        target = source if damage == 'source' else Path(saved['outputs']['analysis_report' if damage == 'report' else 'lod_medium'])
        target.write_bytes(target.read_bytes() + b'changed')
    level = 'source' if damage == 'source' else 'medium'
    response = client.get(f"{endpoint(session, rid)}/{detail['step_run_id']}/{level}", headers=headers)
    assert response.status_code == 409


def test_review_cannot_cross_session_or_record_boundaries(reviewed):
    client, session, headers, _, rid, _ = reviewed
    detail = client.get(endpoint(session, rid), headers=headers).json['data']['sets'][0]
    other = User(email='foreign@example.com', password_hash='test-only-hash')
    db.session.add(other)
    db.session.commit()
    foreign = {'Authorization': 'Bearer ' + create_access_token(identity=str(other.id))}
    assert client.get(endpoint(session, rid), headers=foreign).status_code in {403, 404}
    assert client.get(f"{endpoint(session, rid + 1)}/{detail['step_run_id']}/medium", headers=headers).status_code == 404
    assert client.get(f"{endpoint(session, rid)}/{detail['step_run_id']}/unknown", headers=headers).status_code == 404
