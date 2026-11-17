"""HPC orchestration policy checks with a mocked central allocation service.

No SSH, scheduler, remote deployment or live GPU is used. These tests establish
the Link-to-central-service contract, not remote execution correctness.
"""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from flask import Flask
import pytest

from database.database import db
from database.models import HpcAllocation, PipelineDefinition, PipelineVersion, Session, User, UserRole
from database.webhdp_link_models import LinkClient, LinkPublication, LinkRun, LinkToken
from exceptions import FileProcessingError
from services.hpc_allocation_service import HpcAllocationService
from services.native_pipeline_system import NativePipelineSystemService
from services import webhdp_link_service as link
from services import webhdp_link_worker as worker


@pytest.fixture
def hpc(tmp_path):
    app = Flask(__name__)
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path}/hpc-policy.sqlite",
        SQLALCHEMY_TRACK_MODIFICATIONS=False, WEBHDP_LINK_STORAGE_PATH=str(tmp_path / "storage"),
        WEBHDP_LINK_HPC_WAIT_SECONDS=0)
    db.init_app(app)
    native = NativePipelineSystemService()
    app.native_pipeline_service = native
    central = MagicMock(spec=HpcAllocationService)
    app.hpc_allocation_service = central
    with app.app_context():
        db.create_all()
        native.ensure_seeded()
        definition = PipelineDefinition.query.filter_by(identifier="metadata_only").one()
        version = PipelineVersion.query.filter_by(pipeline_definition_id=definition.id).first()
        user = User(email="hpc-policy@example.test", password_hash="not-a-login", role=UserRole.USER,
                    is_verified=True, token_version=0)
        db.session.add(user); db.session.commit()
        session = Session(user_id=user.id, status="submitting", session_dir=str(tmp_path / "run"))
        db.session.add(session); db.session.commit()
        policy = {"enabled": True, "partition": "operator-gpu", "gpu_type": "test-gpu", "gpu_count": 1, "walltime_hours": 12}
        config = {"hpc": policy, "structure": [{"id": "first", "component": "first_processor"}, {"id": "second", "component": "second_processor"}]}
        publication = LinkPublication(id="hpc-policy", name="HPC policy", pipeline_version_id=version.id, enabled=True, config_json=link.dumps(config))
        client = LinkClient(id="hpc-client", name="HPC client", enabled=True, config_json=link.dumps({"pipeline_ids": [publication.id], "max_concurrent_runs": 1}))
        db.session.add_all([publication, client]); db.session.commit()
        token = LinkToken(token_hash="1" * 64, client_id=client.id, user_id=user.id, user_token_version=0,
            scope=link.DEFAULT_SCOPE, pipeline_ids_json=link.dumps([publication.id]), expires_at=link.now() + timedelta(hours=1))
        db.session.add(token); db.session.commit()
        run = LinkRun(client_id=client.id, user_id=user.id, token_id=token.id, publication_id=publication.id,
            pipeline_version_id=version.id, session_id=session.id, idempotency_key="hpc-policy-test-key", fingerprint="2" * 64,
            status="running", request_json=link.dumps({"publication": config, "parameters": {"partition": "untrusted", "walltime_hours": 99}}))
        db.session.add(run); db.session.commit()
        allocation = SimpleNamespace(public_id="owned-allocation", user_id=user.id, session_id=session.id, status="running")
        central.request_allocation.return_value = {"allocation_id": allocation.public_id}
        central.get_allocation.return_value = allocation
        central.get_active_for_session.return_value = allocation
        central.preflight.return_value = {"success": True}
        def release(item):
            item.status = "released"
            return {"allocation": {"status": "released"}}
        central.release.side_effect = release
        yield {"app": app, "run": run, "user": user, "session": session, "publication": publication,
               "config": config, "central": central, "allocation": allocation, "release": release}
        db.session.remove(); db.drop_all()


def prepare(hpc):
    snapshot = link.loads(hpc["run"].request_json)["publication"]
    worker._prepare_hpc(hpc["run"], snapshot)
    return snapshot


def test_hpc_dispatch_uses_owned_session_and_frozen_operator_policy(hpc):
    # A later publication edit and external parameter names cannot replace the
    # resource policy already frozen into this accepted run.
    changed = deepcopy(hpc["config"])
    changed["hpc"]["partition"] = "later-publication-partition"
    hpc["publication"].config_json = link.dumps(changed); db.session.commit()
    snapshot = prepare(hpc)
    hpc["central"].request_allocation.assert_called_once_with(user=hpc["user"], session_id=hpc["session"].id,
        purpose="workflow", payload={"partition": "operator-gpu", "gpu_type": "test-gpu", "gpu_count": 1, "duration_minutes": 720})
    hpc["central"].get_allocation.assert_called_once_with("owned-allocation", user=hpc["user"])
    hpc["central"].preflight.assert_called_once_with(hpc["allocation"], components=["first_processor", "second_processor"])
    saved = link.loads(hpc["run"].request_json)
    assert saved["publication"] == snapshot
    assert saved["_hpc_allocation_id"] == "owned-allocation" and saved["_hpc_cleanup_pending"] is True


def test_omitted_walltime_keeps_central_default_and_disabled_policy_does_not_allocate(hpc):
    config = deepcopy(hpc["config"])
    config["hpc"].pop("walltime_hours")
    worker._prepare_hpc(hpc["run"], config)
    assert "duration_minutes" not in hpc["central"].request_allocation.call_args.kwargs["payload"]
    hpc["central"].reset_mock()
    worker._prepare_hpc(hpc["run"], {"hpc": {"enabled": False}})
    hpc["central"].request_allocation.assert_not_called()


@pytest.mark.parametrize("terminal", ["succeeded", "failed", "cancelled"])
def test_default_policy_releases_owned_running_allocation_after_each_outcome(hpc, terminal):
    prepare(hpc)
    hpc["run"].status = terminal; db.session.commit()
    worker.cleanup_allocations()
    hpc["central"].release.assert_called_once_with(hpc["allocation"])
    saved = link.loads(hpc["run"].request_json)
    assert saved["_hpc_cleanup_pending"] is False and saved["_hpc_retained"] is False


@pytest.mark.parametrize("retain", [False, True])
def test_queue_timeout_releases_pending_allocation_even_when_retention_requested(hpc, retain):
    saved = link.loads(hpc["run"].request_json)
    saved["publication"]["hpc"]["retain_allocation"] = retain
    hpc["run"].request_json = link.dumps(saved); db.session.commit()
    hpc["central"].get_active_for_session.return_value = None
    hpc["allocation"].status = "queued"
    with pytest.raises(FileProcessingError, match="queue deadline"):
        prepare(hpc)
    hpc["central"].preflight.assert_not_called()
    hpc["run"].status = "failed"; db.session.commit()
    worker.cleanup_allocations()
    hpc["central"].release.assert_called_once_with(hpc["allocation"])
    assert link.loads(hpc["run"].request_json)["_hpc_retained"] is False


@pytest.mark.parametrize("state", ["running", "queued", "failed", "expired"])
def test_explicit_retention_keeps_only_a_running_allocation(hpc, state):
    prepare(hpc)
    saved = link.loads(hpc["run"].request_json)
    saved["publication"]["hpc"]["retain_allocation"] = True
    hpc["run"].request_json = link.dumps(saved); hpc["run"].status = "succeeded"; db.session.commit()
    hpc["allocation"].status = state
    worker.cleanup_allocations()
    if state == "running":
        hpc["central"].release.assert_not_called()
    else:
        hpc["central"].release.assert_called_once_with(hpc["allocation"])
    saved = link.loads(hpc["run"].request_json)
    assert saved["_hpc_retained"] is (state == "running")
    assert saved["_hpc_cleanup_pending"] is False


@pytest.mark.parametrize("different_owner", ["session_id", "user_id"])
def test_cleanup_refuses_allocation_owned_by_another_session_or_user(hpc, different_owner):
    prepare(hpc)
    setattr(hpc["allocation"], different_owner, getattr(hpc["allocation"], different_owner) + 10)
    worker.release_owned_allocation(hpc["run"])
    hpc["central"].release.assert_not_called()
    assert link.loads(hpc["run"].request_json)["_hpc_cleanup_pending"] is True


def test_preflight_failure_does_not_lose_cleanup_obligation(hpc):
    hpc["central"].preflight.return_value = {"success": False, "error": "component unavailable"}
    with pytest.raises(FileProcessingError, match="preflight failed"):
        prepare(hpc)
    assert link.loads(hpc["run"].request_json)["_hpc_cleanup_pending"] is True
    hpc["run"].status = "failed"; db.session.commit()
    worker.cleanup_allocations()
    hpc["central"].release.assert_called_once_with(hpc["allocation"])


def test_failed_release_remains_pending_until_a_successful_retry(hpc):
    prepare(hpc)
    hpc["run"].status = "cancelled"; db.session.commit()
    hpc["central"].release.side_effect = RuntimeError("central service temporarily unavailable")
    worker.cleanup_allocations()
    db.session.expire_all()
    run = db.session.get(LinkRun, hpc["run"].id)
    assert link.loads(run.request_json)["_hpc_cleanup_pending"] is True
    hpc["central"].release.side_effect = hpc["release"]
    worker.cleanup_allocations()
    db.session.refresh(run)
    assert link.loads(run.request_json)["_hpc_cleanup_pending"] is False
    assert hpc["central"].release.call_count == 2
    worker.cleanup_allocations()
    assert hpc["central"].release.call_count == 2


def retained_candidate(hpc):
    current = hpc['run']
    saved = link.loads(current.request_json)
    saved['publication']['hpc'].update(retain_allocation=True, reuse_retained_allocation=True)
    current.request_json = link.dumps(saved)
    previous_session = Session(user_id=current.user_id, status='completed', origin_type='webhdp_link', session_dir='/private/previous')
    db.session.add(previous_session); db.session.flush()
    allocation = HpcAllocation(user_id=current.user_id, session_id=previous_session.id, status='running',
        requested_partition='operator-gpu', requested_gpu_count=1, requested_duration_minutes=720,
        expires_at=link.now() + timedelta(hours=12))
    db.session.add(allocation); db.session.flush()
    previous = LinkRun(client_id=current.client_id, user_id=current.user_id, token_id=current.token_id,
        publication_id=current.publication_id, pipeline_version_id=current.pipeline_version_id,
        session_id=previous_session.id, idempotency_key='previous-hpc-request', fingerprint='3'*64,
        status='succeeded', completed_at=link.now(), request_json=link.dumps({
            'publication':saved['publication'], '_hpc_retained':True, '_hpc_cleanup_pending':False,
            '_hpc_allocation_id':allocation.public_id}))
    db.session.add(previous); db.session.commit()
    return previous, allocation, saved['publication']['hpc']


def test_reuses_only_idle_owned_retained_allocation_without_resetting_expiry(hpc):
    previous, allocation, policy = retained_candidate(hpc)
    original_expiry = allocation.expires_at
    result = worker._reuse_retained_allocation(hpc['run'], policy, hpc['central'], hpc['user'])
    assert result is allocation and allocation.session_id == hpc['run'].session_id
    assert allocation.expires_at == original_expiry and allocation.requested_duration_minutes == 720
    hpc['central'].require_allocation_access.assert_called_once_with(hpc['user'], purpose='workflow')
    hpc['central'].request_allocation.assert_not_called()
    hpc['central'].release.assert_not_called()
    assert link.loads(previous.request_json)['_hpc_retained'] is False
    assert link.loads(hpc['run'].request_json)['_hpc_reused_from'] == previous.id
    assert worker._reuse_retained_allocation(hpc['run'], policy, hpc['central'], hpc['user']) is None


@pytest.mark.parametrize('reason', ['foreign_user', 'active_run', 'resource_change', 'pending_cleanup', 'normal_workflow', 'expired'])
def test_retained_reuse_rejects_incompatible_or_active_reservations(hpc, reason):
    previous, allocation, policy = retained_candidate(hpc)
    saved = link.loads(previous.request_json)
    if reason == 'foreign_user':
        allocation.user_id += 100
    elif reason == 'active_run':
        previous.status = 'running'
    elif reason == 'resource_change':
        policy = {**policy, 'partition':'different'}
    elif reason == 'pending_cleanup':
        saved['_hpc_cleanup_pending'] = True
    elif reason == 'normal_workflow':
        db.session.get(Session, previous.session_id).origin_type = 'native'
    else:
        allocation.status = 'expired'
    previous.request_json = link.dumps(saved); db.session.commit()
    assert worker._reuse_retained_allocation(hpc['run'], policy, hpc['central'], hpc['user']) is None
    assert allocation.session_id == previous.session_id
    hpc['central'].release.assert_not_called()


def test_allocating_slurm_job_is_polled_before_preflight(hpc, monkeypatch):
    hpc['allocation'].status = 'allocating'
    hpc['app'].config['WEBHDP_LINK_HPC_WAIT_SECONDS'] = 20
    hpc['central'].poll_allocation.side_effect = lambda row: setattr(row, 'status', 'running')
    monkeypatch.setattr(worker.time, 'sleep', lambda seconds: None)
    prepare(hpc)
    hpc['central'].poll_allocation.assert_called_once()
    hpc['central'].preflight.assert_called_once()


def test_operator_queue_wait_environment_is_respected_before_worker_start(hpc, monkeypatch):
    hpc['app'].config.pop('WEBHDP_LINK_HPC_WAIT_SECONDS')
    monkeypatch.setenv('WEBHDP_LINK_HPC_WAIT_SECONDS', '14400')
    hpc['allocation'].status = 'allocating'
    ticks = iter([0, 1000])
    monkeypatch.setattr(worker.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(worker.time, 'sleep', lambda seconds: None)
    hpc['central'].poll_allocation.side_effect = lambda row: setattr(row, 'status', 'running')
    prepare(hpc)
    hpc['central'].poll_allocation.assert_called_once()
    hpc['central'].preflight.assert_called_once()


def test_reuse_queue_serializes_same_user_even_when_client_concurrency_allows_two(hpc):
    previous, allocation, policy = retained_candidate(hpc)
    previous.status = 'queued'
    previous.heartbeat_at = None
    current = hpc['run']; current.heartbeat_at = link.now()
    client = db.session.get(LinkClient, current.client_id)
    client.config_json = link.dumps({**link.loads(client.config_json), 'max_concurrent_runs':5})
    db.session.commit()
    assert worker.claim_next() is None
    current.status = 'succeeded'; db.session.commit()
    assert worker.claim_next() == previous.id
