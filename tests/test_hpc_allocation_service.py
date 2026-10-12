from datetime import datetime, timedelta
import os
import pytest

from database.models import HpcAllocation, HpcLinkConfig, User, UserRole
from services.hpc_allocation_service import HpcAllocationService, mask_secret
from exceptions import ValidationError


def test_component_execution_sends_pinned_identity_without_executable_settings(monkeypatch):
    from unittest.mock import Mock
    service = HpcAllocationService()
    client = Mock()
    monkeypatch.setattr(service, 'client', lambda: client)
    profile = {'version': '1.0.0', 'sif_sha256': 'a' * 64, 'image': '/work/component.sif',
               'entrypoint': ['python3', 'runner.py'], 'environment': {'SETTING': 'value'}}
    request = {'component_key': 'mesh_optimizer', 'profile': profile, 'inputs': {'input_file': 'model.glb'}}
    service.execute_component(HpcAllocation(remote_session_id='allocation-1'), request)
    sent = client.post.call_args.args[1]
    assert sent['profile'] == {'version': '1.0.0', 'sif_sha256': 'a' * 64}
    assert sent['component_version'] == '1.0.0'
    assert sent['inputs'] == request['inputs']
    assert request['profile'] is profile and 'entrypoint' in profile


def test_hpc_link_permission_requires_verified_capability_for_users():
    service = HpcAllocationService()
    user = User(email="user@example.com", role=UserRole.USER, is_verified=True)
    user.set_capabilities(["hpc_link_access"])

    assert service.user_can_allocate(user, purpose="workflow") is True


def test_hpc_link_permission_denies_unverified_user_even_with_capability():
    service = HpcAllocationService()
    user = User(email="user@example.com", role=UserRole.USER, is_verified=False)
    user.set_capabilities(["hpc_link_access"])

    assert service.user_can_allocate(user, purpose="workflow") is False


def test_hpc_link_permission_allows_admin_and_playground_moderator():
    service = HpcAllocationService()
    admin = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=False)
    moderator = User(email="mod@example.com", role=UserRole.MODERATOR, is_verified=False)

    assert service.user_can_allocate(admin, purpose="workflow") is True
    assert service.user_can_allocate(moderator, purpose="playground") is True
    assert service.user_can_allocate(moderator, purpose="workflow") is False


def test_mask_secret_redacts_token_preview():
    assert mask_secret("abcdef123456") == "abcd...3456"
    assert mask_secret("abcd") == "ab***cd"
    assert mask_secret("") == ""


def test_partition_sequence_parsing_preserves_order_and_deduplicates():
    service = HpcAllocationService()

    assert service.parse_partition_sequence(" partition-a,partition-b, partition-a ,,partition-c ") == [
        "partition-a",
        "partition-b",
        "partition-c",
    ]


def test_partition_sequence_rejects_invalid_tokens():
    service = HpcAllocationService()

    try:
        service.parse_partition_sequence("partition-a,bad token")
    except ValidationError as exc:
        assert "Invalid HPC partition token" in str(exc)
    else:
        raise AssertionError("Expected invalid partition token to be rejected")


def test_env_partition_sequence_overrides_default_partition(monkeypatch):
    service = HpcAllocationService()
    config = HpcLinkConfig(default_partition="partition-z")
    monkeypatch.setenv("HPC_LINK_PARTITION_SEQUENCE", "partition-a,partition-b")

    assert service._partition_sequence_for_request(config, {"partition": "partition-c"}) == [
        "partition-a",
        "partition-b",
    ]


def test_partition_attempt_timeout_advances_to_next_partition(monkeypatch):
    service = HpcAllocationService()
    allocation = HpcAllocation(
        user_id=1,
        purpose="workflow",
        status="allocating",
        requested_partition="partition-a",
        requested_gpu_count=0,
        requested_duration_minutes=30,
        partition_sequence_json='["partition-a", "partition-b"]',
        partition_attempt_index=0,
        partition_attempt_started_at=datetime.utcnow() - timedelta(seconds=301),
        remote_session_id="remote-a",
        remote_job_id="job-a",
    )
    calls = []

    class FakeClient:
        def delete(self, path, timeout):
            calls.append(("delete", path, timeout))
            return {"cancelled": True}

        def post(self, path, payload, timeout):
            calls.append(("post", path, payload, timeout))
            return {
                "session_id": "remote-b",
                "job_id": "job-b",
                "status": "queued",
                "scheduler_state": "PENDING",
            }

    monkeypatch.setenv("HPC_LINK_PARTITION_ATTEMPT_TIMEOUT_SECONDS", "300")
    monkeypatch.setattr(service, "client", lambda *args, **kwargs: FakeClient())
    monkeypatch.setattr(service, "_notify_allocation", lambda *args, **kwargs: None)
    monkeypatch.setattr("services.hpc_allocation_service.db.session.commit", lambda: None)

    advanced = service._advance_partition_attempt(allocation, HpcLinkConfig(enabled=True, base_url="http://hpc-link"))

    assert advanced is True
    assert allocation.requested_partition == "partition-b"
    assert allocation.partition_attempt_index == 1
    assert allocation.remote_session_id == "remote-b"
    assert allocation.remote_job_id == "job-b"
    assert allocation.status == "allocating"
    assert calls[0][0] == "delete"
    assert calls[1][0] == "post"
    assert calls[1][2]["partition"] == "partition-b"
    history = service._allocation_attempt_history(allocation)
    assert history[0]["partition"] == "partition-a"
    assert history[0]["status"] == "timed_out"
    assert history[0]["remote_cancelled"] is True


def test_partition_attempt_timeout_fails_after_sequence_exhausted(monkeypatch):
    service = HpcAllocationService()
    allocation = HpcAllocation(
        user_id=1,
        purpose="workflow",
        status="allocating",
        requested_partition="partition-a",
        requested_gpu_count=0,
        requested_duration_minutes=30,
        partition_sequence_json='["partition-a"]',
        partition_attempt_index=0,
        partition_attempt_started_at=datetime.utcnow() - timedelta(seconds=301),
        remote_session_id="remote-a",
    )

    class FakeClient:
        def delete(self, path, timeout):
            return {"cancelled": True}

    monkeypatch.setattr(service, "client", lambda *args, **kwargs: FakeClient())
    monkeypatch.setattr(service, "_notify_allocation", lambda *args, **kwargs: None)
    monkeypatch.setattr("services.hpc_allocation_service.db.session.commit", lambda: None)

    advanced = service._advance_partition_attempt(allocation, HpcLinkConfig(enabled=True, base_url="http://hpc-link"))

    assert advanced is False
    assert allocation.status == "failed"
    assert "all configured partitions" in allocation.last_error


def test_stage_cloud_references_resolves_scoped_urls(monkeypatch):
    service = HpcAllocationService()
    allocation = type("Allocation", (), {"remote_session_id": "remote-1"})()
    staged_payload = {}

    monkeypatch.setattr(
        "services.hpc_allocation_service.CloudUploadService.get_file_download_url",
        lambda cloud_path, storage_type: f"https://example.invalid/download/{cloud_path}?sig=short",
    )

    def fake_stage_cloud_files(target_allocation, files):
        staged_payload["allocation"] = target_allocation
        staged_payload["files"] = files
        return {"staged_files": files}

    monkeypatch.setattr(service, "stage_cloud_files", fake_stage_cloud_files)

    result = service.stage_cloud_references(
        allocation,
        [
            {
                "cloud_path": "/hdp_uploads/test_models.zip",
                "storage_type": "dropbox",
                "name": "test_models.zip",
                "relative_dir": "batch-a",
            }
        ],
    )

    assert result["staged_files"][0]["name"] == "test_models.zip"
    assert result["staged_files"][0]["relative_dir"] == "batch-a"
    assert staged_payload["files"][0]["url"].startswith("https://example.invalid/download/")


def test_stage_cloud_references_rejects_server_storage():
    service = HpcAllocationService()
    allocation = type("Allocation", (), {"remote_session_id": "remote-1"})()

    try:
        service.stage_cloud_references(allocation, [{"cloud_path": "/tmp/file.zip", "storage_type": "server"}])
    except ValidationError as exc:
        assert "Server-only storage" in str(exc)
    else:
        raise AssertionError("Expected server storage to be rejected")


def test_upload_zenodo_draft_rejects_publish_flag():
    service = HpcAllocationService()
    allocation = type("Allocation", (), {"remote_session_id": "remote-1"})()

    try:
        service.upload_zenodo_draft(
            allocation,
            {"access_token": "secret", "publish": True, "files": [{"remote_path": "/work/out.png"}]},
        )
    except ValidationError as exc:
        assert "Publishing through HPC-Link is disabled" in str(exc)
    else:
        raise AssertionError("Expected publish=True to be rejected")


def test_upload_zenodo_draft_posts_draft_payload(monkeypatch):
    service = HpcAllocationService()
    allocation = type("Allocation", (), {"remote_session_id": "remote-1", "last_health_json": None})()
    captured = {}

    class FakeClient:
        def post(self, path, payload, timeout):
            captured["path"] = path
            captured["payload"] = payload
            captured["timeout"] = timeout
            return {"success": True, "environment": "sandbox", "uploaded_files": []}

    monkeypatch.setattr(service, "client", lambda: FakeClient())
    monkeypatch.setattr("services.hpc_allocation_service.db.session.commit", lambda: None)

    result = service.upload_zenodo_draft(
        allocation,
        {
            "environment": "sandbox",
            "access_token": "secret-token",
            "files": [{"remote_path": "/work/session/outputs/render.png", "name": "render.png"}],
        },
    )

    assert result["success"] is True
    assert captured["path"] == "/api/apps/webhdp/sessions/remote-1/zenodo/upload-draft"
    assert captured["payload"]["publish"] is False
    assert captured["payload"]["access_token"] == "secret-token"


def test_serialize_config_preserves_zero_gpu_default():
    service = HpcAllocationService()
    config = type(
        "Config",
        (),
        {
            "enabled": True,
            "require_for_components": False,
            "base_url": "http://hpc-link",
            "encrypted_token": None,
            "masked_token_preview": "",
            "default_partition": "partition-a",
            "default_gpu_type": None,
            "default_gpu_count": 0,
            "default_duration_minutes": 30,
            "max_active_allocations": 1,
            "max_active_allocations_per_user": 1,
            "remote_data_root": "",
            "remote_apps_root": "",
            "last_validation_status": None,
            "last_validation_error": None,
            "last_validated_at": None,
        },
    )()

    assert service.serialize_config(config)["default_gpu_count"] == 0


def test_local_staging_streams_dependency_tree_without_basename_collisions(tmp_path, monkeypatch):
    from urllib.parse import unquote
    service = HpcAllocationService()
    allocation = type('Allocation', (), {'remote_session_id':'s1', 'remote_input_dir':'/remote/inputs', 'last_health_json':None})()
    files = []
    for folder in ['first', '模型']:
        path = tmp_path / folder / 'buffer.bin'
        path.parent.mkdir()
        path.write_bytes(folder.encode())
        files.append(str(path))
    class Client:
        def upload_file(self, path, local):
            assert '/stage/file?path=' in path
            relative = unquote(path.split('?path=')[1])
            return {'name':'buffer.bin', 'remote_path':'/remote/inputs/'+relative, 'size_bytes':os.path.getsize(local)}
    monkeypatch.setattr(service, 'client', lambda: Client())
    monkeypatch.setattr('services.hpc_allocation_service.db.session.commit', lambda: None)
    result = service.stage_local_files(allocation, files)['staged_files']
    assert [r['remote_path'] for r in result] == ['/remote/inputs/first/buffer.bin', '/remote/inputs/模型/buffer.bin']
    assert [r['local_path'] for r in result] == files


def test_request_replaces_expired_running_allocation(monkeypatch):
    from flask import Flask
    from database.database import db
    from database.models import Session
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    with app.app_context():
        db.create_all()
        user = User(email='operator@example.com', role=UserRole.ADMIN)
        user.set_password('test-allocation-password')
        db.session.add(user)
        db.session.flush()
        session = Session(user_id=user.id, session_dir='/tmp/workflow')
        db.session.add(session)
        db.session.flush()
        previous = HpcAllocation(user_id=user.id, session_id=session.id, purpose='workflow', status='running', requested_partition='partition-a', remote_session_id='expired-job')
        db.session.add_all([previous, HpcLinkConfig(enabled=True, default_partition='partition-a')])
        db.session.commit()
        service = HpcAllocationService()
        monkeypatch.setattr(service, '_notify_allocation', lambda *args, **kwargs: None)
        def refresh(allocation):
            allocation.status = 'expired'
            db.session.commit()
        monkeypatch.setattr(service, 'refresh_allocation', refresh)
        def start(allocation, config):
            allocation.status = 'allocating'
            db.session.commit()
        monkeypatch.setattr(service, '_start_allocation', start)
        result = service.request_allocation(user=user, session_id=session.id, purpose='workflow', payload={})
        assert previous.status == 'expired'
        assert result['allocation_id'] != previous.public_id
        assert result['status'] == 'allocating'
        assert HpcAllocation.query.count() == 2


@pytest.fixture
def queue_workspace(tmp_path, monkeypatch):
    from flask import Flask
    from flask_jwt_extended import JWTManager
    from database.database import db
    from routes.hpc_link_routes import hpc_link_bp
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI=f'sqlite:///{tmp_path / "queue.db"}',
        SQLALCHEMY_TRACK_MODIFICATIONS=False, JWT_SECRET_KEY='allocation-test-key')
    db.init_app(app)
    JWTManager(app)
    service = app.hpc_allocation_service = HpcAllocationService()
    app.register_blueprint(hpc_link_bp, url_prefix='/api/v1/hpc-link')
    with app.app_context():
        db.create_all()
        users = [User(email=f'operator-{index}@example.com', role=UserRole.ADMIN) for index in (1, 2)]
        for user in users:
            user.set_password('allocation-test-password')
        config = HpcLinkConfig(enabled=True, default_partition='partition-a',
            max_active_allocations=2, max_active_allocations_per_user=1)
        db.session.add_all([*users, config])
        db.session.commit()
        monkeypatch.setattr(service, '_notify_allocation', lambda *args, **kwargs: None)
        try:
            yield app, service, users
        finally:
            db.session.remove()
            db.drop_all()


def test_waiting_allocation_poll_advances_after_remote_job_ends(queue_workspace, monkeypatch):
    from database.database import db
    from flask_jwt_extended import create_access_token
    from unittest.mock import Mock
    app, service, users = queue_workspace
    active = HpcAllocation(user_id=users[0].id, purpose='workflow', status='running',
        requested_partition='partition-a', remote_session_id='ended-job')
    waiting = HpcAllocation(user_id=users[0].id, purpose='workflow', status='queued',
        requested_partition='partition-a')
    db.session.add_all([active, waiting]); db.session.commit()
    client = Mock()
    client.get.side_effect = lambda path, **kwargs: {
        'status': 'finished' if path.endswith('ended-job') else 'running'}
    client.post.return_value = {'session_id': 'next-job', 'job_id': 'next-slurm-job', 'status': 'queued'}
    monkeypatch.setattr(service, 'client', lambda *args, **kwargs: client)
    headers = {'Authorization': 'Bearer ' + create_access_token(identity=str(users[0].id))}
    response = app.test_client().get(f'/api/v1/hpc-link/allocations/{waiting.public_id}', headers=headers)
    assert response.status_code == 200
    assert response.json['data']['allocation']['status'] == 'running'
    assert response.json['data']['allocation']['remote_job_id'] == 'next-slurm-job'
    assert active.status == 'expired'
    client.post.assert_called_once()


def test_user_at_allocation_limit_does_not_block_other_users(queue_workspace, monkeypatch):
    from database.database import db
    from unittest.mock import Mock
    _, service, users = queue_workspace
    active = HpcAllocation(user_id=users[0].id, purpose='workflow', status='running',
        requested_partition='partition-a', remote_session_id='active-job')
    first = HpcAllocation(user_id=users[0].id, purpose='workflow', status='queued',
        requested_partition='partition-a', requested_at=datetime.utcnow() - timedelta(seconds=10))
    second = HpcAllocation(user_id=users[1].id, purpose='workflow', status='queued',
        requested_partition='partition-a')
    db.session.add_all([active, first, second]); db.session.commit()
    client = Mock()
    client.get.return_value = {'status': 'running'}
    client.post.return_value = {'session_id': 'second-user-job', 'status': 'queued'}
    monkeypatch.setattr(service, 'client', lambda *args, **kwargs: client)
    service.process_queue()
    assert first.status == 'queued'
    assert second.status == 'allocating'
    assert second.remote_session_id == 'second-user-job'
    client.post.assert_called_once()


def test_poll_returns_saved_status_while_another_request_advances_queue(queue_workspace, monkeypatch):
    from contextlib import contextmanager
    from database.database import db
    from unittest.mock import Mock
    from services.registry_lock import OperationConflict
    _, service, users = queue_workspace
    waiting = HpcAllocation(user_id=users[0].id, purpose='workflow', status='queued',
        requested_partition='partition-a')
    db.session.add(waiting); db.session.commit()
    client = Mock()
    monkeypatch.setattr(service, 'client', lambda *args, **kwargs: client)
    @contextmanager
    def busy_lock(name):
        raise OperationConflict('Queue processing is already in progress.')
        yield
    monkeypatch.setattr('services.hpc_allocation_service.registry_lock', busy_lock)
    assert service.poll_allocation(waiting)['status'] == 'queued'
    service.process_queue()
    client.post.assert_not_called()
    client.get.assert_not_called()
