import json
from collections import Counter
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from database.database import db
from database.models import PipelineRun, PipelineRunStatus, PipelineVersion, StepRun
from services.hdpc_scan_service import create_and_scan_hdpc_project
from services.pipeline_checkpoints import journal, recovery_plan
from services.submission_pipeline_service import execute_submission_pipeline
from test_mesh_optimizer_component import glb
from test_submission_readiness import workspace


class LadderAdapter:
    def __init__(self):
        self.calls = Counter()
        self.fail = True
        self.crash = False
        self.metadata = {}

    def execute(self, execution):
        record = execution.metadata['record_context']
        self.calls[(record['record_id'], execution.step_id)] += 1
        self.metadata[(record['record_id'], execution.step_id)] = record['file_zenodo_metadata']
        if execution.step_id == 'finish' and self.crash:
            raise KeyboardInterrupt('worker stopped')
        if execution.step_id == 'finish' and self.fail and record['filename'] == 'model.glb':
            return {'success': False, 'error': 'The derivative needs correction.', 'outputs': {}}
        output = Path(execution.workdir) / (execution.step_id + '.glb')
        output.write_bytes(Path(execution.inputs['input_file']).read_bytes())
        return {'success': True, 'outputs': {'lod_medium': str(output)},
                'artifacts': [{'name': output.name, 'path': str(output), 'artifact_kind': 'model'}]}


@pytest.fixture
def continuation(workspace):
    app, native, session, user, source, _, payload, headers = workspace
    other = glb(source.with_name('other.glb'), scenes=[{'nodes': [0]}], nodes=[{'mesh': 0}])
    create_and_scan_hdpc_project(hdpc_path=session.hdpc_path, data_in_path=str(source.parent),
        data_out_path=str(source.parents[1] / 'outputs'), project_name='Continuation', short_code='CONT',
        modalities=['3d_model'], scan_options={'extensions': ['.glb'], 'primarysourceext': '.glb'})
    config = native.get_pipeline('guarded_lod')['config']
    first = {**config['steps'][0], 'id': 'prepare', 'name': 'Prepare derivative'}
    second = {**first, 'id': 'finish', 'name': 'Finish derivative', 'input_bindings': [
        {'kind': 'input', 'target': 'input_file', 'type': 'artifact_file', 'source_step': 'prepare', 'source_output': 'lod_medium'}]}
    config['steps'] = [first, second]
    native.create_pipeline_version_from_config('guarded_lod', config)
    adapter = LadderAdapter()
    native._adapter_registry['container_cli'] = adapter
    payload = {**payload, 'local_file_paths': [str(source), str(other)]}
    with patch('services.submission_pipeline_service.publishing_context_service.resolve_token_for_session', return_value={'environment': 'sandbox', 'source': 'user', 'token': None}):
        yield app, native, session, user, payload, headers, adapter


def execute(context, payload):
    _, native, session, user, _, _, _ = context
    payload = {**payload, 'request_id': str(uuid4())}
    accepted = native.create_pending_run('guarded_lod', session_id=session.id,
        initiated_by_user_id=user.id, request_payload=payload)
    result = execute_submission_pipeline(identifier='guarded_lod', local_file_paths=payload.get('local_file_paths', []),
        record_ids=payload.get('record_ids', []), db_session_id=session.id, precreated_run_public_id=accepted['run_id'])
    return PipelineRun.query.filter_by(public_id=accepted['run_id']).one(), result


def retry_payload(context, run):
    _, native, _, user, _, _, _ = context
    plan = recovery_plan(native, run.public_id, user.id)
    return {'session_id': plan['session_id'], 'record_ids': plan['record_ids'], 'local_file_paths': [],
            'execution_items': [], 'is_sandbox': plan['is_sandbox'], 'resume_from_run_id': run.public_id,
            'expected_version': plan['pipeline_version']}


def test_partial_retry_reuses_verified_work_and_original_version(continuation):
    _, native, _, user, payload, _, adapter = continuation
    run, result = execute(continuation, payload)
    assert not result['result']['success']
    retry = retry_payload(continuation, run)
    assert len(retry['record_ids']) == 1
    config = native.get_pipeline('guarded_lod')['config']
    config['steps'][0]['parameters']['target_ratio'] = 0.3
    native.create_pipeline_version_from_config('guarded_lod', config)
    adapter.fail = False
    rid = retry['record_ids'][0]
    retried, result = execute(continuation, retry)
    assert result['result']['success'], result
    assert adapter.calls[(rid, 'prepare')] == 1
    assert adapter.calls[(rid, 'finish')] == 2
    assert retried.pipeline_version_id == run.pipeline_version_id
    assert native.get_pipeline_run(retried.public_id, user.id)['outcomes']['summary']['completed'] == 1
    assert result['result']['details'][0]['step_results']['prepare']['reused']
    assert all(adapter.calls[key] == 1 for key in adapter.calls if key[0] != rid)


@pytest.mark.parametrize('damage', ['changed', 'deleted', 'source'])
def test_damaged_output_or_changed_input_invalidates_dependents(continuation, damage):
    _, _, _, _, payload, _, adapter = continuation
    run, _ = execute(continuation, payload)
    retry = retry_payload(continuation, run)
    rid = retry['record_ids'][0]
    saved = journal(run)[str(rid)]
    output = Path(saved['steps']['prepare']['outputs']['lod_medium'])
    if damage == 'deleted':
        output.unlink()
    elif damage == 'changed':
        glb(output, scenes=[{'nodes': [0]}], nodes=[{'mesh': 0}], extras={'changed': True})
    else:
        glb(Path(saved['state']['file_path']), scenes=[{'nodes': [0]}], nodes=[{'mesh': 0}], extras={'changed': True})
    adapter.fail = False
    _, result = execute(continuation, retry)
    assert result['result']['success'], result
    assert adapter.calls[(rid, 'prepare')] == 2 and adapter.calls[(rid, 'finish')] == 2


def test_worker_interruption_keeps_committed_step_and_record_checkpoints(continuation):
    app, native, session, user, payload, _, adapter = continuation
    adapter.crash = True
    with pytest.raises(KeyboardInterrupt):
        execute(continuation, payload)
    db.session.rollback()
    run = PipelineRun.query.one()
    assert run.status == PipelineRunStatus.RUNNING
    assert sum(step.status == 'completed' for step in StepRun.query.all()) == 2
    saved = journal(run)
    assert len(saved) == 2 and all(row['steps']['prepare']['success'] for row in saved.values())
    adapter.crash = False
    adapter.fail = False
    retry = retry_payload(continuation, run)
    assert run.status == PipelineRunStatus.FAILED
    _, result = execute(continuation, retry)
    assert result['result']['success'], result
    assert all(count == 1 for (rid, step), count in adapter.calls.items() if step == 'prepare')


def test_uncertain_remote_operation_blocks_retry_and_foreign_access(continuation):
    app, native, session, user, payload, headers, _ = continuation
    run, _ = execute(continuation, payload)
    retry = retry_payload(continuation, run)
    from services.hdpc_schema_service import connect_hdpc
    from services.zenodo_operation_service import begin_operation
    with connect_hdpc(session.hdpc_path) as connection:
        begin_operation(connection, retry['record_ids'][0], 'create_draft', {})
    response = app.test_client().get(f'/api/v2/runs/{run.public_id}/recovery', headers=headers)
    assert response.status_code == 200
    assert not response.json['data']['record_ids']
    assert 'uncertain' in response.json['data']['records'][0]['reason']
    rejected = app.test_client().post('/api/v2/pipelines/guarded_lod/execute', json={**retry, 'async_execution': True}, headers=headers)
    assert rejected.status_code == 409
    from database.models import User
    from flask_jwt_extended import create_access_token
    other = User(email='other@example.com', password_hash='test-only-hash')
    db.session.add(other)
    db.session.commit()
    foreign = {'Authorization': 'Bearer ' + create_access_token(identity=str(other.id))}
    assert app.test_client().get(f'/api/v2/runs/{run.public_id}/recovery', headers=foreign).status_code in {403, 404}


def test_reuse_preserves_metadata_corrected_after_the_failed_run(continuation):
    _, _, session, _, payload, _, adapter = continuation
    run, _ = execute(continuation, payload)
    retry = retry_payload(continuation, run)
    rid = retry['record_ids'][0]
    from services.hdpc_schema_service import connect_hdpc
    with connect_hdpc(session.hdpc_path) as connection:
        metadata = json.loads(connection.execute('SELECT record_metadata_json FROM zenodo_records WHERE record_id=?', (rid,)).fetchone()[0])
        metadata['metadata']['description'] = 'Corrected curator description'
        connection.execute('UPDATE zenodo_records SET record_metadata_json=? WHERE record_id=?', (json.dumps(metadata), rid))
        connection.commit()
    adapter.fail = False
    _, result = execute(continuation, retry)
    assert result['result']['success'], result
    assert adapter.calls[(rid, 'prepare')] == 1
    assert adapter.metadata[(rid, 'finish')]['description'] == 'Corrected curator description'


@pytest.mark.parametrize('selection', ['paths', 'records'])
def test_incomplete_registration_blocks_original_batch_continuation(continuation, selection):
    _, native, _, user, payload, _, _ = continuation
    run, _ = execute(continuation, payload)
    request = json.loads(run.request_json)
    if selection == 'records':
        request['record_ids'] = [int(rid) for rid in request['_checkpoints']['records']]
        request['local_file_paths'] = []
    request['_checkpoints']['records'].pop(next(iter(request['_checkpoints']['records'])))
    run.request_json = json.dumps(request)
    # Model an arbitrary batch component in the pinned definition: unlike the
    # renderer, its outputs can depend on every member of the original group.
    version = db.session.get(PipelineVersion, run.pipeline_version_id)
    config = json.loads(version.config_json)
    config['steps'][0]['scope'] = 'batch'
    version.config_json = json.dumps(config)
    db.session.commit()
    plan = recovery_plan(native, run.public_id, user.id)
    assert plan['whole_batch']
    assert len(plan['unregistered_sources'] if selection == 'paths' else plan['unregistered_record_ids']) == 1
    assert not plan['record_ids']
    assert all('original batch' in record['reason'] for record in plan['records'])
    from services.pipeline_checkpoints import validate_recovery
    from services.registry_lock import OperationConflict
    with pytest.raises(OperationConflict):
        validate_recovery(native, {**payload, 'local_file_paths': [],
            'record_ids': [plan['records'][0]['record_id']], 'resume_from_run_id': run.public_id}, user.id)


def test_registration_keeps_original_selection_when_metadata_resolves_another_asset(continuation):
    _, native, _, user, payload, _, _ = continuation
    run, _ = execute(continuation, payload)
    saved = journal(run)
    rid, record = next(iter(saved.items()))
    selected = Path(record['state']['file_path']).with_suffix('.xml')
    selected.write_text('<record/>')
    request = json.loads(run.request_json)
    request['local_file_paths'] = [str(selected), *request['local_file_paths'][1:]]
    run.request_json = json.dumps(request)
    from services.pipeline_checkpoints import persist_registration, persist
    persist_registration(run, rid, record['state']['file_path'], {}, source_file_path=str(selected))
    # Later step checkpoints update state but retain the original selection.
    persist(run, [record['state']])
    assert not recovery_plan(native, run.public_id, user.id)['unregistered_sources']


@pytest.mark.parametrize('blocker', ['published', 'active_allocation'])
def test_recovery_requires_mutable_records_and_released_interrupted_compute(continuation, blocker):
    _, native, session, user, payload, _, _ = continuation
    run, _ = execute(continuation, payload)
    rid = retry_payload(continuation, run)['record_ids'][0]
    if blocker == 'published':
        from services.hdpc_schema_service import connect_hdpc
        with connect_hdpc(session.hdpc_path) as connection:
            connection.execute("UPDATE zenodo_records SET record_status='published' WHERE record_id=?", (rid,))
            connection.commit()
    else:
        from database.models import HpcAllocation
        run.result_json = json.dumps({**json.loads(run.result_json), 'interrupted': True})
        allocation = HpcAllocation(user_id=user.id, session_id=session.id,
            requested_partition='offline-test', remote_session_id='saved-session', status='active')
        db.session.add(allocation)
        db.session.commit()
    with patch('requests.sessions.Session.request', side_effect=AssertionError('No cluster contact')):
        plan = recovery_plan(native, run.public_id, user.id)
    assert not plan['record_ids']
    assert ('published' if blocker == 'published' else 'allocation') in plan['records'][0]['reason']
    if blocker == 'active_allocation':
        allocation.status = 'released'
        db.session.commit()
        assert recovery_plan(native, run.public_id, user.id)['record_ids'] == [rid]


def test_registration_interruption_keeps_record_ids_and_identifies_remaining_sources(continuation):
    _, native, _, user, payload, _, adapter = continuation
    from services import submission_pipeline_service as submission
    original = submission.create_local_record_with_metadata
    count = 0
    def create(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise KeyboardInterrupt('registration worker stopped')
        return original(*args, **kwargs)
    with patch.object(submission, 'create_local_record_with_metadata', side_effect=create), pytest.raises(KeyboardInterrupt):
        execute(continuation, payload)
    db.session.rollback()
    run = PipelineRun.query.one()
    plan = recovery_plan(native, run.public_id, user.id)
    assert len(plan['record_ids']) == 1
    assert len(plan['unregistered_sources']) == 1
    assert not adapter.calls
    adapter.fail = False
    _, result = execute(continuation, retry_payload(continuation, run))
    assert result['result']['success'], result
