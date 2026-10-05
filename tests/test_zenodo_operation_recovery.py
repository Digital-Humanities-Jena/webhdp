import json
import sqlite3
from unittest.mock import Mock

import pytest
import requests

from services.hdpc_local_service import create_local_record_with_metadata, read_hdpc_record_context, read_hdpc_operations_summary
from services.hdpc_zenodo_service import create_api_draft, discard_draft, publish_record, reconcile_remote_operation, upload_files_for_deposition
from test_hdpc_zenodo_service import _create_hdpc_with_source, _DummyResponse


@pytest.fixture
def remote_record(tmp_path):
    path = str(tmp_path / 'project.hdpc')
    _create_hdpc_with_source(path, str(tmp_path))
    metadata = {'title': 'Museum object', 'description': 'A description', 'creators': [{'name': 'Museum'}]}
    create_local_record_with_metadata(path, file_id=101, metadata=metadata, access_token='test-only-token')
    payload = {'id': 9001, 'metadata': metadata, 'submitted': False, 'state': 'inprogress',
               'links': {'publish': 'https://sandbox.zenodo.org/api/deposit/depositions/9001/actions/publish'}}
    return path, payload


def journal(path):
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute('SELECT * FROM zenodo_remote_operations')]


def test_lost_draft_response_blocks_duplicate_creation_and_exposes_recovery(remote_record):
    path, payload = remote_record
    http = Mock()
    http.post.side_effect = requests.ConnectionError('lost response?access_token=test-only-token')
    assert create_api_draft(path, 1, http=http)['reconciliation_required']
    assert create_api_draft(path, 1, http=http)['error_code'] == 'REMOTE_OUTCOME_UNCERTAIN'
    http.post.assert_called_once()
    context = read_hdpc_record_context(path, 1)
    assert not any(context['zenodo_status']['actions'].values())
    summary = context['zenodo_status']['unresolved_operations'][0]
    assert 'request_json' not in summary
    assert 'test-only-token' not in json.dumps(journal(path))
    assert read_hdpc_operations_summary(path)['actionable_operations']['create_drafts']['count'] == 0
    http.get.return_value = _DummyResponse(200, {**payload, 'metadata': {**payload['metadata'], 'creators': [{'name': 'Museum', 'affiliation': ''}]}})
    assert reconcile_remote_operation(path, 1, deposition_id='9001', http=http)['success']
    assert journal(path)[0]['state'] == 'completed'
    http.post.assert_called_once()
    assert read_hdpc_record_context(path, 1)['traceability']['record']['record_status'] == 'draft'


def test_reconnection_rejects_wrong_identity_and_requires_explicit_absence_confirmation(remote_record):
    path, payload = remote_record
    http = Mock()
    http.post.side_effect = requests.Timeout('response missing')
    create_api_draft(path, 1, http=http)
    http.get.return_value = _DummyResponse(200, {**payload, 'metadata': {'title': 'Another object'}})
    assert not reconcile_remote_operation(path, 1, deposition_id='9001', http=http)['success']
    assert journal(path)[0]['state'] == 'uncertain'
    assert reconcile_remote_operation(path, 1, confirmed_not_created=True, http=http)['success']
    assert journal(path)[0]['state'] == 'confirmed_not_created'
    http.post.side_effect = None
    http.post.return_value = _DummyResponse(201, payload)
    assert create_api_draft(path, 1, http=http)['success']
    assert http.post.call_count == 2


def test_successful_remote_response_survives_local_commit_failure(remote_record, monkeypatch):
    from services import hdpc_zenodo_service as service
    path, payload = remote_record
    http = Mock()
    http.post.return_value = _DummyResponse(201, payload)
    store = service._save_operation_record
    monkeypatch.setattr(service, '_save_operation_record', Mock(side_effect=sqlite3.OperationalError('disk unavailable')))
    with pytest.raises(sqlite3.OperationalError):
        create_api_draft(path, 1, http=http)
    assert journal(path)[0]['remote_id'] == '9001'
    monkeypatch.setattr(service, '_save_operation_record', store)
    assert create_api_draft(path, 1, http=http)['success']
    http.post.assert_called_once()
    http.get.assert_not_called()


def prepare_published_request(path, payload, monkeypatch):
    http = Mock()
    http.post.return_value = _DummyResponse(201, payload)
    assert create_api_draft(path, 1, http=http)['success']
    monkeypatch.setattr('services.lod_artifact_service.record_lod_readiness', lambda *args: {'ready': True, 'pending_upload_count': 0})
    return http


def test_lost_publication_response_reconciles_without_another_post(remote_record, monkeypatch):
    path, payload = remote_record
    http = prepare_published_request(path, payload, monkeypatch)
    http.post.side_effect = requests.ConnectionError('publish reply lost')
    published = {**payload, 'submitted': True, 'state': 'done', 'doi': '10.5072/zenodo.9001'}
    http.get.side_effect = requests.Timeout('status unavailable')
    assert publish_record(path, 1, http=http)['reconciliation_required']
    for operation in (create_api_draft, discard_draft, upload_files_for_deposition):
        assert operation(path, 1, http=http)['reconciliation_required']
    monkeypatch.setenv('ZENODO_PUBLISH_ENABLED', 'false')
    monkeypatch.setattr('services.lod_artifact_service.record_lod_readiness', lambda *args: {'ready': False})
    http.get.side_effect = None
    http.get.return_value = _DummyResponse(200, published)
    assert publish_record(path, 1, http=http)['success']
    assert publish_record(path, 1, http=http)['success']
    assert http.post.call_count == 2  # One creation and one publication attempt.
    assert journal(path)[-1]['state'] == 'completed'
    assert read_hdpc_record_context(path, 1)['traceability']['record']['record_status'] == 'published'


def test_accepted_but_unfinished_publication_stays_uncertain(remote_record, monkeypatch):
    path, payload = remote_record
    http = prepare_published_request(path, payload, monkeypatch)
    http.post.return_value = _DummyResponse(202, payload)
    http.get.side_effect = [_DummyResponse(200, payload), _DummyResponse(404, {})]
    assert not publish_record(path, 1, http=http)['success']
    assert journal(path)[-1]['state'] == 'uncertain'
    assert read_hdpc_record_context(path, 1)['traceability']['record']['record_status'] == 'draft'


def test_definite_rejection_can_be_retried(remote_record):
    path, payload = remote_record
    http = Mock()
    http.post.return_value = _DummyResponse(400, {'message': 'Invalid metadata'})
    assert not create_api_draft(path, 1, http=http)['success']
    assert journal(path)[0]['state'] == 'rejected'
    http.post.return_value = _DummyResponse(201, payload)
    assert create_api_draft(path, 1, http=http)['success']


def test_unpublished_confirmation_requires_authenticated_draft_and_missing_public_record(remote_record, monkeypatch):
    path, payload = remote_record
    http = prepare_published_request(path, payload, monkeypatch)
    http.post.side_effect = requests.Timeout('publication reply missing')
    http.get.side_effect = requests.Timeout('status unavailable')
    publish_record(path, 1, http=http)
    http.get.side_effect = [_DummyResponse(200, payload), _DummyResponse(503, {})]
    assert not reconcile_remote_operation(path, 1, confirmed_not_published=True, http=http)['success']
    http.get.side_effect = [_DummyResponse(200, payload), _DummyResponse(404, {})]
    assert reconcile_remote_operation(path, 1, confirmed_not_published=True, http=http)['success']
    assert journal(path)[-1]['state'] == 'confirmed_not_published'
    http.post.side_effect = None
    http.post.return_value = _DummyResponse(202, {**payload, 'submitted': True, 'state': 'done'})
    assert publish_record(path, 1, http=http)['success']
    assert http.post.call_count == 3
