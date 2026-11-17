"""Verify that GPU reservation ownership and private claim lifecycles are enforced."""

import asyncio
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
import pytest

from app.auth_store import AuthenticatedUser
from app.main import app
from app.schemas.apps import WebHdpReservationInspectRequest, WebHdpReservationRegisterRequest, WebHdpSessionAdoptRequest
from app.security import get_api_key
from app.services import apps_gateway as gateway


def actor(username, *, admin=False):
    return AuthenticatedUser(user_id=1, username=username, is_admin=admin, invited=True, is_active=True,
                             allowed_partitions=[], allowed_gpu_types=[], max_duration_minutes=30, max_gpu_count=1)


@pytest.fixture
def cluster(monkeypatch, tmp_path):
    now = int(datetime.now(timezone.utc).timestamp())
    job = {"job_id": 9319538, "user_name": "cluster-owner", "user_id": 1042, "job_state": "RUNNING",
           "partition": "gpu", "nodes": "gpu017", "submit_time": now - 120, "start_time": now - 60,
           "end_time": now + 2400, "tres_alloc_str": "cpu=8,mem=64G,node=1,gres/gpu=1,gres/gpu:a100=1"}
    commands = []
    state = {"step": None, "block_execution": None, "remote_guard_busy": False}

    async def command(text, *, timeout):
        commands.append(text)
        if text == "scontrol --json show job 9319538":
            return json.dumps({"jobs": [job], "errors": []}), "", 0
        if text.startswith("umask 077; mkdir -p "):
            return "", "", 0
        if text.startswith("squeue --steps --jobs=9319538 "):
            return f"9319538.2|{state['step']}\n" if state["step"] else "", "", 0
        if text.startswith("flock -n -E 75 ") and "exec srun --jobid=9319538 " in text:
            if state["block_execution"]:
                await state["block_execution"].wait()
            return "success", "", 0
        if text.startswith("flock -n -E 75 ") and "touch " in text:
            return "", "", 75 if state["remote_guard_busy"] else 0
        raise AssertionError(f"Unexpected command: {text}")

    original_settings = gateway.get_settings()
    monkeypatch.setattr(gateway, "get_settings", lambda: original_settings.model_copy(update={
        "hpc_apps_root": "/work/private", "hpc_user": "cluster-owner",
        "webhdp_sessions_registry_path": str(tmp_path / "registry.json"),
    }))
    monkeypatch.setattr(gateway.ssh_manager, "run_command", AsyncMock(side_effect=command))
    monkeypatch.setattr(gateway.auth_store, "get_user_by_username",
                        lambda username: actor("webhdp-service") if username == "webhdp-service" else None)
    return SimpleNamespace(job=job, service=gateway.HpcApplicationGatewayService(), commands=commands,
                           state=state, admin=actor("operator", admin=True), owner=actor("webhdp-service"),
                           other=actor("other-user"), registry=tmp_path / "registry.json")


async def register(cluster):
    return await cluster.service.register_webhdp_reservation(
        WebHdpReservationRegisterRequest(job_id="9319538", owner_username=cluster.owner.username), cluster.admin,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("change,status", [
    ({"user_name": "someone-else"}, 403),
    ({"job_state": "PENDING"}, 409),
    ({"tres_alloc_str": "cpu=8,mem=64G,node=1"}, 409),
    ({"nodes": "gpu[017-018]"}, 409),
    ({"end_time": 1}, 409),
])
async def test_inspection_only_accepts_owned_running_single_node_gpu_jobs(cluster, change, status):
    cluster.job.update(change)
    request = WebHdpReservationInspectRequest(job_id="9319538")
    with pytest.raises(HTTPException) as denied:
        await cluster.service.inspect_webhdp_reservation(request, cluster.owner)
    assert denied.value.status_code == 403
    assert cluster.commands == []
    with pytest.raises(HTTPException) as invalid:
        await cluster.service.inspect_webhdp_reservation(request, cluster.admin)
    assert invalid.value.status_code == status


@pytest.mark.asyncio
async def test_claims_are_scoped_exclusive_and_private_across_restart(cluster):
    reservation = await register(cluster)
    assert (await register(cluster)).reservation_id == reservation.reservation_id
    assert reservation.status == "available" and reservation.memory_mb == 65536
    assert reservation.started_at.timestamp() == cluster.job["start_time"]
    assert "remote_session_dir" not in reservation.model_dump()
    first = WebHdpSessionAdoptRequest(reservation_id=reservation.reservation_id, claim_id=uuid4())
    second = WebHdpSessionAdoptRequest(reservation_id=reservation.reservation_id, claim_id=uuid4())
    with pytest.raises(HTTPException) as denied:
        await cluster.service.adopt_webhdp_session(first, cluster.other)
    assert denied.value.status_code == 403

    responses = await asyncio.gather(
        cluster.service.adopt_webhdp_session(first, cluster.owner),
        cluster.service.adopt_webhdp_session(second, cluster.owner), return_exceptions=True,
    )
    opened, conflict = responses
    assert opened.externally_managed and opened.reservation_id == reservation.reservation_id
    assert opened.input_dir == opened.remote_session_dir + "/inputs"
    assert opened.output_dir == opened.remote_session_dir + "/outputs"
    assert conflict.status_code == 409
    assert sum(command.startswith("umask 077") for command in cluster.commands) == 1

    restarted = gateway.HpcApplicationGatewayService()
    restored = await restarted.adopt_webhdp_session(first, cluster.owner)
    assert restored.session_id == opened.session_id
    assert (await restarted.get_webhdp_reservation(reservation.reservation_id, cluster.owner)).status == "in_use"
    assert (await restarted.get_webhdp_session_status(opened.session_id, cluster.owner)).scheduler_state == "RUNNING"
    detached = await restarted.detach_webhdp_claim(reservation.reservation_id, str(first.claim_id), cluster.owner)
    assert detached.detached and not detached.cancelled
    assert await restarted.stop_webhdp_session(opened.session_id, cluster.owner) == detached
    with pytest.raises(HTTPException) as old_claim:
        await restarted.adopt_webhdp_session(first, cluster.owner)
    assert old_claim.value.status_code == 409
    fresh = await restarted.adopt_webhdp_session(second, cluster.owner)
    assert fresh.session_id != opened.session_id and fresh.input_dir != opened.input_dir
    assert all("scancel" not in text and "sbatch" not in text for text in cluster.commands)


@pytest.mark.asyncio
async def test_active_gateway_or_scheduler_step_blocks_detach(cluster):
    reservation = await register(cluster)
    claim = WebHdpSessionAdoptRequest(reservation_id=reservation.reservation_id, claim_id=uuid4())
    adopted = await cluster.service.adopt_webhdp_session(claim, cluster.owner)
    session = cluster.service._webhdp_sessions[adopted.session_id]
    cluster.state["block_execution"] = asyncio.Event()
    execution = asyncio.create_task(cluster.service._run_in_webhdp_allocation(session, "true", timeout=30))
    try:
        await asyncio.sleep(0)
        with pytest.raises(HTTPException) as busy:
            await cluster.service.stop_webhdp_session(adopted.session_id, cluster.owner)
        assert busy.value.status_code == 409
    finally:
        cluster.state["block_execution"].set()
        await execution

    cluster.state["step"] = f"webhdp-{adopted.session_id}"
    restarted = gateway.HpcApplicationGatewayService()
    with pytest.raises(HTTPException) as busy_after_restart:
        await restarted.stop_webhdp_session(adopted.session_id, cluster.owner)
    assert busy_after_restart.value.status_code == 409
    cluster.state["step"] = None
    cluster.state["remote_guard_busy"] = True
    with pytest.raises(HTTPException, match="launching"):
        await restarted.stop_webhdp_session(adopted.session_id, cluster.owner)
    cluster.state["remote_guard_busy"] = False
    assert (await restarted.stop_webhdp_session(adopted.session_id, cluster.owner)).detached
    assert all("scancel" not in text for text in cluster.commands)


@pytest.mark.asyncio
async def test_scheduler_identity_drift_blocks_execution_and_pending_claim_can_be_closed(cluster):
    reservation = await register(cluster)
    claim = WebHdpSessionAdoptRequest(reservation_id=reservation.reservation_id, claim_id=uuid4())
    closed = await cluster.service.detach_webhdp_claim(reservation.reservation_id, str(claim.claim_id), cluster.owner)
    assert closed.detached and not closed.session_id
    with pytest.raises(HTTPException, match="already detached"):
        await cluster.service.adopt_webhdp_session(claim, cluster.owner)

    valid = WebHdpSessionAdoptRequest(reservation_id=reservation.reservation_id, claim_id=uuid4())
    adopted = await cluster.service.adopt_webhdp_session(valid, cluster.owner)
    cluster.job["submit_time"] += 1
    facts = await cluster.service.get_webhdp_reservation(reservation.reservation_id, cluster.owner)
    assert facts.status == "unavailable"
    status = await cluster.service.get_webhdp_session_status(adopted.session_id, cluster.owner)
    assert status.scheduler_state != "RUNNING"
    with pytest.raises(HTTPException, match="has changed"):
        await cluster.service._run_in_webhdp_allocation(
            cluster.service._webhdp_sessions[adopted.session_id], "true", timeout=30,
        )
    assert (await cluster.service.stop_webhdp_session(adopted.session_id, cluster.owner)).detached
    await cluster.service.revoke_webhdp_reservation(reservation.reservation_id, cluster.admin)
    assert (await cluster.service.detach_webhdp_claim(reservation.reservation_id, str(valid.claim_id), cluster.owner)).detached
    assert not any("srun --jobid" in text or "scancel" in text for text in cluster.commands)


def test_routes_require_admin_registration_but_service_user_can_claim(cluster, monkeypatch):
    selected = {"actor": cluster.owner}

    async def authenticate(request: Request):
        request.state.current_user = selected["actor"]
        return "test-auth"

    monkeypatch.setitem(app.dependency_overrides, get_api_key, authenticate)
    monkeypatch.setattr("app.routers.apps.hpc_application_service", cluster.service)
    client = TestClient(app)
    base = "/api/apps/webhdp"
    body = {"job_id": "9319538", "owner_username": cluster.owner.username}
    assert client.post(f"{base}/reservations", json=body).status_code == 403
    selected["actor"] = cluster.admin
    assert client.post(f"{base}/reservations/inspect", json={"job_id": "9319538", "node": "gpu017"}).status_code == 422
    response = client.post(f"{base}/reservations", json=body)
    assert response.status_code == 200
    reservation_id = response.json()["reservation_id"]
    selected["actor"] = cluster.owner
    claim_id = str(uuid4())
    held = client.post(f"{base}/sessions/adopt", json={"reservation_id": reservation_id, "claim_id": claim_id})
    assert held.status_code == 200 and held.json()["externally_managed"]
    selected["actor"] = cluster.other
    assert client.get(f"{base}/reservations/{reservation_id}").status_code == 403
    assert client.delete(f"{base}/reservations/{reservation_id}/claims/{claim_id}").status_code == 403
    selected["actor"] = cluster.owner
    result = client.delete(f"{base}/reservations/{reservation_id}/claims/{claim_id}")
    assert result.status_code == 200 and result.json()["detached"] and not result.json()["cancelled"]
    selected["actor"] = cluster.admin
    assert client.delete(f"{base}/reservations/{reservation_id}").status_code == 204
