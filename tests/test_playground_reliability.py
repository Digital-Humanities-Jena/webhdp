import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import (
    ComponentDefinition, ComponentProfile, ComponentVersion, PlaygroundRun,
    Session, User,
)
from middleware import setup_error_handlers
from routes.pipeline_v2_routes import pipeline_v2_bp
from services.native_pipeline_system import NativePipelineSystemService
from services.hpc_allocation_service import HpcAllocationService


@pytest.fixture
def playground(tmp_path):
    app = Flask(__name__)
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
                      SQLALCHEMY_TRACK_MODIFICATIONS=False,
                      JWT_SECRET_KEY='playground-test-secret-at-least-32')
    db.init_app(app)
    JWTManager(app)
    setup_error_handlers(app)
    app.register_blueprint(pipeline_v2_bp, url_prefix='/api/v2')
    service = NativePipelineSystemService()
    service.ensure_seeded = Mock()
    service._should_route_component_to_hpc_link = Mock(return_value=False)
    adapter = Mock()
    adapter.execute.return_value = {'success': True, 'logs': {'stdout': 'Session result'}}
    service._adapter_registry['local_cli'] = adapter
    app.native_pipeline_service = service
    with app.app_context():
        db.create_all()
        users = [User(email=f'{name}@example.com', password_hash='test-only-hash')
                 for name in ('owner', 'other')]
        db.session.add_all(users)
        db.session.flush()
        session = Session(user_id=users[0].id, session_dir=str(tmp_path),
                          hdpc_path=str(tmp_path / 'project.hdpc'))
        component = ComponentDefinition(key='test_component', name='Test component', source_type='local')
        db.session.add_all([session, component])
        db.session.flush()
        manifest = {
            'metadata': {'name': component.key, 'version': '1.0.0'},
            'inputs': [{'name': 'files', 'type': 'file_list'}],
            'outputs': [],
            'parameter_groups': [{'title': 'Paths', 'parameters': [{'name': 'directory', 'type': 'dir_path'}]}],
            'execution': {'profiles': [{'id': 'local', 'adapter': 'local_cli', 'entrypoint': ['test-component']}]},
            'compatibility': {},
        }
        version = ComponentVersion(component_definition_id=component.id, version='1.0.0',
                                   manifest_json=json.dumps(manifest), manifest_hash='test')
        db.session.add(version)
        db.session.flush()
        db.session.add(ComponentProfile(component_version_id=version.id, profile_id='local',
                                        adapter='local_cli', entrypoint_json='["test-component"]'))
        db.session.commit()
        source = tmp_path / 'model.glb'
        source.write_bytes(b'model')
        headers = [{'Authorization': f'Bearer {create_access_token(identity=str(user.id))}'} for user in users]
        payload = {'component_key': component.key, 'profile_id': 'local', 'session_id': session.id,
                   'inputs': {'files': [source.name]}, 'parameters': {'directory': '.'}}
        yield SimpleNamespace(app=app, client=app.test_client(), service=service, adapter=adapter,
                              session=session, users=users, headers=headers, payload=payload, root=tmp_path)
        db.session.remove()
        db.drop_all()


def _hpc_artifact_fixture(p, path_field="path", remote_path=None):
    from database.models import HpcAllocation
    from pathlib import Path

    allocation = HpcAllocation(user_id=p.users[0].id, session_id=p.session.id, purpose="playground",
                               status="running", requested_partition="vis", remote_session_id="owned-test-session",
                               remote_session_dir="/remote/owned-test-session")
    db.session.add(allocation)
    profile = ComponentProfile.query.one()
    profile.adapter = "hpc_link"
    db.session.commit()
    gateway = HpcAllocationService()
    client = Mock()
    client.download_to_file.side_effect = lambda url, destination, **kwargs: Path(destination).write_bytes(b"generated artifact bytes")
    gateway.client = Mock(return_value=client)
    p.app.hpc_allocation_service = gateway
    p.service._ensure_component_runtime_available = Mock()
    p.service._adapter_registry["hpc_link"] = p.adapter
    remote_path = remote_path or "/remote/owned-test-session/outputs/invocation/model.zip"
    p.adapter.execute.return_value = {
        "success": True, "status": "completed", "outputs": {"dataset": remote_path},
        "artifacts": [{"name": "model.zip", "artifact_kind": "file", path_field: remote_path}],
    }
    return gateway, client, remote_path


@pytest.mark.parametrize("path_field", ["path", "remote_path"])
def test_hpc_playground_materializes_portable_artifacts_for_authenticated_download(playground, path_field):
    from pathlib import Path
    from database.models import HpcArtifact

    p = playground
    gateway, client, remote = _hpc_artifact_fixture(p, path_field)
    response = p.client.post("/api/v2/playground/execute", json=p.payload, headers=p.headers[0])
    assert response.status_code == 201
    run = response.get_json()["data"]["playground_run"]
    assert run["status"] == "completed"
    artifact = run["result"]["artifacts"][0]
    assert artifact["remote_path"] == remote
    assert Path(artifact["path"]).is_relative_to(p.root / "playground" / run["run_id"])
    assert run["result"]["outputs"]["dataset"] == artifact["path"]
    downloaded = p.client.get(f"/api/v2/playground/runs/{run['run_id']}/artifacts/0", headers=p.headers[0])
    assert downloaded.status_code == 200 and downloaded.data == b"generated artifact bytes"
    assert p.client.get(f"/api/v2/playground/runs/{run['run_id']}/artifacts/0", headers=p.headers[1]).status_code == 404
    stored = HpcArtifact.query.one()
    assert stored.remote_path == remote and stored.playground_run_id == PlaygroundRun.query.one().id
    assert stored.pipeline_run_id is None and stored.step_run_id is None
    client.download_to_file.assert_called_once()


def test_hpc_playground_rejects_artifact_outside_owned_remote_session(playground):
    from database.models import HpcArtifact

    p = playground
    gateway, client, _ = _hpc_artifact_fixture(p, remote_path="/remote/another-session/private.zip")
    result = p.service.execute_playground(p.payload, p.users[0].id)
    assert result["status"] == "failed"
    assert "outside the active HPC allocation directory" in result["error"]
    client.download_to_file.assert_not_called()
    assert HpcArtifact.query.count() == 0


def test_native_hpc_portable_path_contract_becomes_local_downstream_binding(playground):
    from pathlib import Path
    from services.pipeline_artifacts import pipeline_artifact_location

    p = playground
    gateway, client, remote = _hpc_artifact_fixture(p)
    gateway.register_remote_artifacts = Mock()
    result = p.adapter.execute.return_value
    paths = p.service._materialize_hpc_artifacts(
        {"db_session_id": p.session.id}, {"specific_output_dir": str(p.root / "outputs/record-7/source"), "record_id": 7},
        SimpleNamespace(id=11), SimpleNamespace(id=12), "historic_prepare", result,
    )
    assert paths == [str(p.root / "outputs/record-7/source/step-12/outputs/model.zip")]
    assert Path(paths[0]).read_bytes() == b"generated artifact bytes"
    assert result["outputs"]["dataset"] == result["artifacts"][0]["path"] == paths[0]
    assert result["artifacts"][0]["remote_path"] == remote
    kwargs = gateway.register_remote_artifacts.call_args.kwargs
    assert kwargs["pipeline_run_id"] == 11 and kwargs["step_run_id"] == 12 and kwargs["record_id"] == 7
    # A successfully downloaded HPC artifact must also satisfy the native
    # authenticated download resolver, not merely exist on the host.
    artifact = SimpleNamespace(path=paths[0], pipeline_run_id=11, step_run_id=12, record_id=7)
    step = SimpleNamespace(id=12, pipeline_run_id=11, record_id=7, record_path="/uploads/source.zip")
    assert pipeline_artifact_location(SimpleNamespace(session_dir=str(p.root)), step, artifact) == Path(paths[0])


def test_playground_execution_and_results_require_session_permission(playground):
    p = playground
    rejected = p.client.post('/api/v2/playground/execute', json=p.payload, headers=p.headers[1])
    assert rejected.status_code == 404
    p.adapter.execute.assert_not_called()
    accepted = p.client.post('/api/v2/playground/execute', json=p.payload, headers=p.headers[0])
    assert accepted.status_code == 201
    run_id = accepted.get_json()['data']['playground_run']['run_id']
    assert p.client.get(f'/api/v2/playground/runs/{run_id}', headers=p.headers[1]).status_code == 404
    assert p.client.get(f'/api/v2/playground/runs/{run_id}', headers=p.headers[0]).status_code == 200


def test_explorer_only_sessions_cannot_execute(playground):
    p = playground
    p.session.access_mode = 'explorer_only'
    db.session.commit()
    assert p.client.post('/api/v2/playground/execute', json=p.payload, headers=p.headers[0]).status_code == 409
    p.adapter.execute.assert_not_called()
    assert PlaygroundRun.query.count() == 0


@pytest.mark.parametrize('target', ['input', 'parameter', 'symlink'])
def test_playground_rejects_paths_outside_session_before_running(playground, tmp_path, target):
    p = playground
    outside = tmp_path.parent / f'{tmp_path.name}-outside.glb'
    outside.write_bytes(b'outside')
    try:
        if target == 'parameter':
            p.payload['parameters']['directory'] = str(tmp_path.parent)
        else:
            path = outside
            if target == 'symlink':
                path = tmp_path / 'escape.glb'
                path.symlink_to(outside)
            p.payload['inputs']['files'] = [str(path)]
        assert p.client.post('/api/v2/playground/execute', json=p.payload, headers=p.headers[0]).status_code == 400
        p.adapter.execute.assert_not_called()
        assert PlaygroundRun.query.count() == 0
    finally:
        outside.unlink()


def test_playground_resolves_relative_inputs_for_every_adapter(playground):
    p = playground
    result = p.service.execute_playground(p.payload, p.users[0].id)
    assert result['status'] == 'completed'
    request = p.adapter.execute.call_args.args[0]
    assert request.inputs['files'] == [str(p.root / 'model.glb')]
    assert request.parameters['directory'] == str(p.root)


def test_async_request_retries_return_one_pinned_run(playground, monkeypatch):
    import sys
    from uuid import uuid4
    p = playground
    task = Mock()
    task.apply_async.side_effect = lambda **kwargs: SimpleNamespace(id=kwargs['task_id'])
    monkeypatch.setitem(sys.modules, 'tasks', SimpleNamespace(execute_playground_task=task))
    payload = {**p.payload, 'async_execution': True, 'request_id': str(uuid4())}
    first = p.client.post('/api/v2/playground/execute', json=payload, headers=p.headers[0])
    assert first.status_code == 202
    run = PlaygroundRun.query.one()
    assert json.loads(run.request_json)['_dispatch']['state'] == 'queued'
    assert task.apply_async.call_args.kwargs == {'args': [run.public_id], 'task_id': run.public_id}
    second = p.client.post('/api/v2/playground/execute', json=payload, headers=p.headers[0])
    assert second.status_code == 202
    assert second.get_json()['data']['playground_run']['reused']
    assert PlaygroundRun.query.count() == 1
    task.apply_async.assert_called_once()
    p.adapter.execute.assert_not_called()
    original = db.session.get(ComponentVersion, run.component_version_id)
    original.is_active = False
    newer_manifest = json.loads(original.manifest_json)
    newer_manifest['inputs'] = [{'name': 'different_files', 'type': 'file_list'}]
    db.session.add(ComponentVersion(component_definition_id=original.component_definition_id,
                    version='2.0.0', manifest_json=json.dumps(newer_manifest), manifest_hash='new'))
    db.session.commit()
    result = p.service.execute_playground_run(run.public_id)
    assert result['status'] == 'completed'
    assert '_dispatch' not in result['request']
    assert p.adapter.execute.call_args.args[0].inputs['files'] == [str(p.root / 'model.glb')]
    p.service.execute_playground_run(run.public_id)
    p.adapter.execute.assert_called_once()


def test_same_request_id_cannot_change_inputs(playground):
    from uuid import uuid4
    from services.registry_lock import OperationConflict
    p = playground
    payload = {**p.payload, 'request_id': str(uuid4())}
    p.service.create_pending_playground_run(payload, p.users[0].id)
    with pytest.raises(OperationConflict):
        p.service.create_pending_playground_run({**payload, 'parameters': {}}, p.users[0].id)
    assert PlaygroundRun.query.count() == 1


def test_unconfirmed_dispatch_is_cancelled_and_late_delivery_is_safe(playground, monkeypatch):
    import sys
    from uuid import uuid4
    p = playground
    task = Mock()
    task.apply_async.side_effect = ConnectionError('Broker acknowledgement was lost')
    monkeypatch.setitem(sys.modules, 'tasks', SimpleNamespace(execute_playground_task=task))
    payload = {**p.payload, 'async_execution': True, 'request_id': str(uuid4())}
    response = p.client.post('/api/v2/playground/execute', json=payload, headers=p.headers[0])
    assert response.status_code == 202
    run = response.get_json()['data']['playground_run']
    assert run['status'] == 'failed'
    assert p.service.execute_playground_run(run['run_id'])['status'] == 'failed'
    repeated = p.client.post('/api/v2/playground/execute', json=payload, headers=p.headers[0])
    assert repeated.get_json()['data']['playground_run']['reused']
    task.apply_async.assert_called_once()
    p.adapter.execute.assert_not_called()
    assert p.service.execute_playground(p.payload, p.users[0].id)['status'] == 'completed'


def test_queued_cancellation_blocks_late_worker_delivery(playground):
    p = playground
    pending = p.service.create_pending_playground_run(p.payload, p.users[0].id)
    run_id = pending['run_id']
    assert p.client.post(f'/api/v2/playground/runs/{run_id}/cancel', headers=p.headers[1]).status_code == 404
    cancelled = p.client.post(f'/api/v2/playground/runs/{run_id}/cancel', headers=p.headers[0])
    assert cancelled.status_code == 200
    assert cancelled.get_json()['data']['playground_run']['result']['cancelled']
    assert p.service.execute_playground_run(run_id)['status'] == 'failed'
    p.adapter.execute.assert_not_called()


def test_adapter_exception_is_durable_and_never_replayed(playground):
    p = playground
    p.adapter.execute.side_effect = RuntimeError('Component executable is unavailable')
    pending = p.service.create_pending_playground_run(p.payload, p.users[0].id)
    result = p.service.execute_playground_run(pending['run_id'])
    assert result['status'] == 'failed'
    assert result['completed_at']
    assert result['error'] == 'Component executable is unavailable'
    assert p.client.get(f"/api/v2/playground/runs/{pending['run_id']}", headers=p.headers[0]).get_json()['data']['playground_run']['status'] == 'failed'
    p.service.execute_playground_run(pending['run_id'])
    p.adapter.execute.assert_called_once()


@pytest.mark.parametrize('change', ['permission', 'path'])
def test_worker_rechecks_permission_and_files_after_queueing(playground, change):
    p = playground
    pending = p.service.create_pending_playground_run(p.payload, p.users[0].id)
    if change == 'permission':
        p.session.user_id = p.users[1].id
        db.session.commit()
    else:
        (p.root / 'model.glb').unlink()
    assert p.service.execute_playground_run(pending['run_id'])['status'] == 'failed'
    p.adapter.execute.assert_not_called()


def test_institution_reader_can_read_results_and_curator_can_execute(playground):
    from database.models import Institution, InstitutionMembership, InstitutionRole
    p = playground
    institution = Institution(name='Museum', slug='museum')
    db.session.add(institution)
    db.session.flush()
    membership = InstitutionMembership(institution_id=institution.id, user_id=p.users[1].id, role=InstitutionRole.READER)
    db.session.add(membership)
    p.session.institution_id = institution.id
    p.session.sharing_scope = 'institution'
    db.session.commit()
    result = p.service.execute_playground(p.payload, p.users[0].id)
    run_url = f"/api/v2/playground/runs/{result['run_id']}"
    assert p.client.get(run_url, headers=p.headers[1]).status_code == 200
    assert p.client.get(f'/api/v2/playground/sessions/{p.session.id}/file?path=model.glb', headers=p.headers[1]).status_code == 200
    assert p.client.post('/api/v2/playground/execute', json=p.payload, headers=p.headers[1]).status_code == 404
    membership.role = InstitutionRole.CURATOR
    db.session.commit()
    assert p.client.post('/api/v2/playground/execute', json=p.payload, headers=p.headers[1]).status_code == 201
    p.session.sharing_scope = 'private'
    db.session.commit()
    assert p.client.get(run_url, headers=p.headers[1]).status_code == 404


def test_old_hostname_preparing_reservation_expires_without_replaying(playground):
    from datetime import datetime, timedelta
    p = playground
    pending = p.service.create_pending_playground_run(p.payload, p.users[0].id)
    run = PlaygroundRun.query.one()
    request = json.loads(run.request_json)
    request['_dispatch']['owner']['host'] = 'retired-container'
    run.request_json = json.dumps(request)
    db.session.commit()
    assert p.service.get_playground_run(run.public_id, p.users[0].id)['status'] == 'pending'
    run.started_at = datetime.utcnow() - timedelta(minutes=3)
    db.session.commit()
    assert p.service.get_playground_run(run.public_id, p.users[0].id)['status'] == 'failed'
    assert p.service.execute_playground_run(pending['run_id'])['status'] == 'failed'
    p.adapter.execute.assert_not_called()
    assert p.service.create_pending_playground_run(p.payload, p.users[0].id)['run_id'] != pending['run_id']


def test_old_running_job_with_worker_lock_stays_running(playground):
    from datetime import datetime, timedelta
    from database.models import PipelineRunStatus
    from test_workflow_transition_reliability import locked_by_other_process
    p = playground
    p.service.create_pending_playground_run(p.payload, p.users[0].id)
    run = PlaygroundRun.query.one()
    run.status = PipelineRunStatus.RUNNING
    run.started_at = datetime.utcnow() - timedelta(days=1)
    db.session.commit()
    with locked_by_other_process(p.session.hdpc_path):
        assert p.service.get_playground_run(run.public_id, p.users[0].id)['status'] == 'running'
    assert p.service.get_playground_run(run.public_id, p.users[0].id)['status'] == 'failed'


def test_expired_reservation_does_not_cancel_an_active_dispatcher(playground):
    import subprocess
    import sys
    from datetime import datetime, timedelta
    p = playground
    p.service.create_pending_playground_run(p.payload, p.users[0].id)
    run = PlaygroundRun.query.one()
    run.started_at = datetime.utcnow() - timedelta(minutes=3)
    db.session.commit()
    lock_name = f'run-dispatch:{run.__tablename__}:{run.public_id}'
    process = subprocess.Popen([sys.executable, '-c',
        'import sys\nfrom flask import Flask\nfrom database.database import db\n'
        'from services.registry_lock import registry_lock\napp=Flask(__name__)\n'
        'app.config["SQLALCHEMY_DATABASE_URI"]="sqlite:///:memory:"\ndb.init_app(app)\n'
        'with app.app_context(), registry_lock(sys.argv[1]):\n print("locked",flush=True)\n sys.stdin.read()', lock_name],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == 'locked'
        assert p.service.get_playground_run(run.public_id, p.users[0].id)['status'] == 'pending'
    finally:
        process.communicate('', timeout=10)
        assert process.returncode == 0
    assert p.service.get_playground_run(run.public_id, p.users[0].id)['status'] == 'failed'


def test_playground_reservation_also_blocks_queued_pipeline_creation(playground):
    from services.registry_lock import OperationConflict
    p = playground
    p.service.create_pending_playground_run(p.payload, p.users[0].id)
    with pytest.raises(OperationConflict) as conflict:
        p.service.create_pending_run('render', session_id=p.session.id, initiated_by_user_id=p.users[0].id, request_payload={})
    assert conflict.value.details['run_kind'] == 'playground'


def test_pipeline_cancellation_requires_session_permission_and_preserves_later_run(playground, monkeypatch):
    from database.models import PipelineDefinition, PipelineVersion, PipelineRun, PipelineRunStatus
    from services.pipeline_execution_lock import PipelineAlreadyRunning
    p = playground
    definition = PipelineDefinition(identifier='test_pipeline', name='Test pipeline')
    db.session.add(definition)
    db.session.flush()
    version = PipelineVersion(pipeline_definition_id=definition.id, version='1.0.0', config_json='{}', config_hash='test')
    db.session.add(version)
    db.session.flush()
    run = PipelineRun(pipeline_definition_id=definition.id, pipeline_version_id=version.id, session_id=p.session.id,
                      initiated_by_user_id=p.users[0].id, status=PipelineRunStatus.PENDING)
    db.session.add(run)
    p.session.status = 'processing'
    db.session.commit()
    with pytest.raises(PipelineAlreadyRunning):
        p.service.create_pending_playground_run(p.payload, p.users[0].id)
    url = f'/api/v2/runs/{run.public_id}/cancel'
    assert p.client.post(url, headers=p.headers[1]).status_code == 404
    assert p.client.post(url, headers=p.headers[0]).status_code == 200
    assert p.session.status == 'failed'
    old_id = run.public_id
    new = PipelineRun(pipeline_definition_id=definition.id, pipeline_version_id=version.id, session_id=p.session.id,
                      initiated_by_user_id=p.users[0].id, status=PipelineRunStatus.PENDING)
    db.session.add(new)
    p.session.status = 'submitting'
    db.session.commit()
    import tasks
    task = tasks.execute_submission_pipeline_task
    notify = Mock()
    monkeypatch.setattr(tasks, 'notify_user', notify)
    arguments = (None, 'test_pipeline', [], p.session.id, True, False, [], [], old_id)
    if hasattr(task, 'func'):
        result = task.func(task, *arguments)
    elif hasattr(task, 'run'):
        result = task.run(*arguments)
    else:
        result = task(SimpleNamespace(request=SimpleNamespace(delivery_info={})), *arguments)
    assert result['status'] == 'failed'
    assert p.session.status == 'submitting'
    assert new.status == PipelineRunStatus.PENDING
    notify.assert_not_called()
