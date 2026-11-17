from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from flask import Flask

from database.database import db
from database.models import HpcAllocation, HpcLinkConfig, Session, User, UserRole
from exceptions import APITimeoutError, ResourceNotFoundError, SecurityError, ValidationError
from services.hpc_allocation_service import HpcAllocationService
from services.hpc_reservation_service import HpcReservationService
from services.registry_lock import OperationConflict


class Gateway:
    def __init__(self):
        now = datetime.now(timezone.utc)
        self.facts = {"reservation_id": str(uuid4()), "job_id": "765", "partition": "gpu", "gpu_type": "a100",
                      "gpu_count": 1, "cpus": 8, "memory_mb": 65536, "node_name": "gpu017",
                      "started_at": now.isoformat(), "expires_at": (now + timedelta(hours=4)).isoformat(),
                      "status": "available"}
        self.claim_ids = []
        self.detached = []
        self.timeout = False

    def get(self, path, *, timeout):
        assert path == f"/api/apps/webhdp/reservations/{self.facts['reservation_id']}"
        return dict(self.facts)

    def post(self, path, payload, *, timeout):
        assert path == "/api/apps/webhdp/sessions/adopt"
        assert payload["reservation_id"] == self.facts["reservation_id"]
        claim = payload["claim_id"]
        self.claim_ids.append(claim)
        self.facts["status"] = "in_use"
        if self.timeout:
            raise APITimeoutError("simulated lost response after gateway stored the claim")
        root = f"/work/test/{claim}"
        return {**self.facts, "externally_managed": True, "session_id": claim, "remote_session_dir": root,
                "input_dir": root + "/inputs", "output_dir": root + "/outputs"}

    def delete(self, path, *, timeout):
        prefix = f"/api/apps/webhdp/reservations/{self.facts['reservation_id']}/claims/"
        assert path.startswith(prefix)  # Must never call a scheduler-owned session stop route.
        self.detached.append(path.removeprefix(prefix))
        self.facts["status"] = "available"
        return {"cancelled": False, "detached": True}


@pytest.fixture
def reservations(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'test.sqlite'}", SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    with app.app_context():
        db.create_all()
        admin = User(email="admin@example.org", role=UserRole.ADMIN, is_verified=True, password_hash="unused-in-unit-test")
        users = [User(email=f"guest{i}@example.org", role=UserRole.USER, is_verified=True, password_hash="unused-in-unit-test")
                 for i in range(3)]
        for user in users:
            user.set_capabilities(["hpc_link_access"])
        db.session.add_all([admin, *users, HpcLinkConfig(enabled=True, base_url="https://gateway.invalid")])
        db.session.flush()
        sessions = [Session(user_id=user.id, session_dir=str(tmp_path / str(user.id))) for user in users]
        db.session.add_all(sessions)
        db.session.commit()
        gateway = Gateway()
        allocation_service = HpcAllocationService()
        monkeypatch.setattr(allocation_service, "client", lambda config=None: gateway)
        service = HpcReservationService(allocation_service)
        row = service.register(admin, {"gateway_reservation_id": gateway.facts["reservation_id"], "label": "Demo GPU",
                                       "allowed_emails": [user.email for user in users[:2]]})
        yield service, gateway, users, sessions, row["reservation_id"]


def test_only_named_account_sees_reservation_and_can_claim_owned_session(reservations):
    service, gateway, users, sessions, identifier = reservations
    visible = service.list(user=users[0])[0]
    assert visible["can_claim"] is True and visible["job_id"] == "765"
    assert "gateway_reservation_id" not in visible and "allowed_emails" not in visible
    assert service.list(user=users[2]) == []
    with pytest.raises(ResourceNotFoundError):
        service.claim(identifier, users[2], {"session_id": sessions[2].id})
    with pytest.raises(SecurityError):
        service.claim(identifier, users[0], {"session_id": sessions[1].id})
    assert gateway.claim_ids == []


def test_exclusive_lease_uses_request_actor_and_reclaims_in_fresh_workspace(reservations):
    service, gateway, users, sessions, identifier = reservations
    first = service.claim(identifier, users[0], {"session_id": sessions[0].id})
    assert first["status"] == "running" and first["reservation_id"] == identifier
    assert service.claim(identifier, users[0], {"session_id": sessions[0].id})["allocation_id"] == first["allocation_id"]
    assert len(gateway.claim_ids) == 1
    assert service.list(user=users[0])[0]["allocation"]["allocation_id"] == first["allocation_id"]
    assert "allocation" not in service.list(user=users[1])[0]
    with pytest.raises(OperationConflict):
        service.claim(identifier, users[1], {"session_id": sessions[1].id})
    central = service.allocations
    assert central.get_active_for_session(sessions[0].id) is None
    assert central.get_active_for_session(sessions[0].id, user_id=users[1].id) is None
    lease = central.get_active_for_session(sessions[0].id, user_id=users[0].id)
    assert lease.public_id == first["allocation_id"]
    assert central.release(lease)["remote"] == {"cancelled": False, "detached": True}
    second = service.claim(identifier, users[1], {"session_id": sessions[1].id})
    assert second["remote_job_id"] == first["remote_job_id"]
    assert second["remote_input_dir"] != first["remote_input_dir"]


def test_claim_retries_same_gateway_key_after_lost_response(reservations):
    service, gateway, users, sessions, identifier = reservations
    gateway.timeout = True
    starting = service.claim(identifier, users[0], {"session_id": sessions[0].id})
    assert starting["status"] == "allocating"
    gateway.timeout = False
    recovered = service.claim(identifier, users[0], {"session_id": sessions[0].id})
    assert recovered["status"] == "running"
    assert gateway.claim_ids == [starting["allocation_id"]] * 2


def test_release_unconfirmed_claim_does_not_create_another_remote_session(reservations):
    service, gateway, users, sessions, identifier = reservations
    gateway.timeout = True
    starting = service.claim(identifier, users[0], {"session_id": sessions[0].id})
    row = HpcAllocation.query.filter_by(public_id=starting["allocation_id"]).one()
    assert row.remote_session_id is None
    service.allocations.release(row)
    assert gateway.detached == gateway.claim_ids == [starting["allocation_id"]]


def test_revoked_capability_and_changed_gateway_block_reserved_compute(reservations):
    service, gateway, users, sessions, identifier = reservations
    claim = service.claim(identifier, users[0], {"session_id": sessions[0].id})
    row = HpcAllocation.query.filter_by(public_id=claim["allocation_id"]).one()
    users[0].set_capabilities([])
    db.session.commit()
    assert service.allocations.get_active_for_session(sessions[0].id, user_id=users[0].id) is None
    with pytest.raises(SecurityError):
        service.allocations.execute_component(row, {})
    config = service.allocations.get_or_create_config()
    config.base_url = "https://other-gateway.invalid"
    db.session.commit()
    with pytest.raises(ValidationError, match="connection"):
        service.allocations.release(row)
    assert gateway.detached == []


def test_different_scheduler_generation_and_disabled_reservation_refuse_claims(reservations):
    service, gateway, users, sessions, identifier = reservations
    started_at = gateway.facts["started_at"]
    gateway.facts["started_at"] = (datetime.fromisoformat(started_at) + timedelta(seconds=1)).isoformat()
    assert service.list(user=users[0])[0]["status"] == "unavailable"
    with pytest.raises(OperationConflict):
        service.claim(identifier, users[0], {"session_id": sessions[0].id})
    gateway.facts["started_at"] = started_at
    service.edit(identifier, {"enabled": False})
    assert not service.list(user=users[0])[0]["can_claim"]
    with pytest.raises(OperationConflict):
        service.claim(identifier, users[0], {"session_id": sessions[0].id})
    assert gateway.claim_ids == []
