"""WebHDP access grants and exclusive leases for operator-held Slurm jobs."""

import json
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath

from sqlalchemy import func

from database.database import db
from database.models import (
    HpcAllocation, HpcReservation, HpcReservationGrant, PipelineRun, PipelineRunStatus,
    PlaygroundRun, Session, User,
)
from exceptions import APIConnectionError, APITimeoutError, ResourceNotFoundError, SecurityError, ValidationError
from services.hpc_allocation_service import ACTIVE_ALLOCATION_STATES, _parse_datetime, _utc_now_naive
from services.registry_lock import OperationConflict, serialize_registry
from services.session_access_service import is_session_mutable


GATEWAY_RESERVATIONS = "/api/apps/webhdp/reservations"
OPAQUE_ID = re.compile(r"[a-zA-Z0-9_-]{1,128}")
SCHEDULER_FIELDS = ("job_id", "partition", "gpu_type", "gpu_count", "cpus", "memory_mb", "node_name", "started_at")


def _iso(value: datetime) -> str:
    return value.replace(tzinfo=timezone.utc).isoformat()


class HpcReservationService:
    def __init__(self, allocations):
        self.allocations = allocations

    @staticmethod
    def _get(public_id):
        reservation = HpcReservation.query.filter_by(public_id=public_id).first()
        if reservation is None:
            raise ResourceNotFoundError("GPU reservation not found")
        return reservation

    @staticmethod
    def active_claim(reservation):
        return HpcAllocation.query.filter(
            HpcAllocation.reservation_id == reservation.id,
            HpcAllocation.status.in_(ACTIVE_ALLOCATION_STATES),
        ).one_or_none()

    def can_use(self, reservation, user):
        return bool(user and user.is_verified and self.allocations.user_can_allocate(user)
                    and db.session.get(HpcReservationGrant, (reservation.id, user.id)))

    @staticmethod
    def _label(value):
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 120:
            raise ValidationError("Enter a reservation label of 1 to 120 characters")
        return value.strip()

    def _set_grants(self, reservation, emails):
        if not isinstance(emails, list) or len(emails) > 50 or any(
            not isinstance(email, str) or not email.strip() or len(email) > 254 for email in emails
        ):
            raise ValidationError("Provide up to 50 existing account email addresses")
        addresses = {email.strip().lower() for email in emails}
        users = User.query.filter(func.lower(User.email).in_(addresses)).all() if addresses else []
        if len(users) != len(addresses) or any(not user.is_verified or not self.allocations.user_can_allocate(user) for user in users):
            raise ValidationError("Each email must belong to a verified account with HPC access")
        ids = {user.id for user in users}
        active = self.active_claim(reservation) if reservation.id is not None else None
        if active and active.user_id not in ids:
            raise OperationConflict("Release the active claim before removing its access grant")
        existing = {grant.user_id for grant in reservation.grants}
        reservation.grants[:] = [grant for grant in reservation.grants if grant.user_id in ids]
        reservation.grants.extend(HpcReservationGrant(user_id=user_id) for user_id in ids - existing)

    def client_for(self, reservation):
        config = self.allocations.get_or_create_config()
        if not config.enabled or str(config.base_url or "").rstrip("/") != reservation.gateway_url:
            raise ValidationError("The HPC-Link connection for this reservation is unavailable")
        return self.allocations.client(config)

    @staticmethod
    def _facts(payload, gateway_id):
        expires_at = _parse_datetime(payload.get("expires_at"))
        started_at = _parse_datetime(payload.get("started_at"))
        if (payload.get("reservation_id") != gateway_id or not expires_at or not started_at
                or started_at >= expires_at or not str(payload.get("job_id", "")).isdecimal()
                or not payload.get("partition") or not payload.get("node_name")
                or any(type(payload.get(key)) is not int or payload[key] < 1 for key in ("gpu_count", "cpus", "memory_mb"))):
            raise ValidationError("HPC-Link did not return valid GPU reservation metadata")
        facts = {key: payload.get(key) for key in SCHEDULER_FIELDS}
        facts["job_id"] = str(facts["job_id"])
        return facts, expires_at

    def _observe(self, reservation):
        if reservation.expires_at <= _utc_now_naive():
            return "expired"
        try:
            payload = self.client_for(reservation).get(f"{GATEWAY_RESERVATIONS}/{reservation.gateway_reservation_id}", timeout=5)
            facts, expires_at = self._facts(payload, reservation.gateway_reservation_id)
            original = json.loads(reservation.scheduler_json)
            if any(facts[key] != original[key] for key in ("job_id", "partition", "node_name", "started_at")):
                return "unavailable"
            if expires_at <= _utc_now_naive() or payload.get("status") == "expired":
                return "expired"
            reservation.scheduler_json = json.dumps(facts)
            reservation.expires_at = expires_at
            return payload["status"] if payload.get("status") in {"available", "in_use"} else "unavailable"
        except (APIConnectionError, APITimeoutError, ValidationError):
            return "unavailable"

    def _serialize(self, reservation, *, user=None, admin=False):
        active = self.active_claim(reservation)
        health = self._observe(reservation) if reservation.enabled else "disabled"
        status = "in_use" if health == "available" and active else health
        result = {
            "reservation_id": reservation.public_id, "label": reservation.label, "enabled": reservation.enabled,
            **json.loads(reservation.scheduler_json), "expires_at": _iso(reservation.expires_at), "status": status,
            "can_claim": status == "available" and self.can_use(reservation, user),
        }
        if active and user and active.user_id == user.id:
            result["allocation"] = self.allocations.serialize_allocation(active)
        if admin:
            result["gateway_reservation_id"] = reservation.gateway_reservation_id
            result["allowed_emails"] = sorted(grant.user.email for grant in reservation.grants)
            result["has_active_claim"] = bool(active)
        return result

    def list(self, *, user=None, admin=False):
        query = HpcReservation.query
        if not admin:
            if not user or not user.is_verified or not self.allocations.user_can_allocate(user):
                return []
            query = query.join(HpcReservationGrant).filter(HpcReservationGrant.user_id == user.id)
        rows = [self._serialize(row, user=user, admin=admin)
                for row in query.order_by(HpcReservation.created_at.desc()).all()]
        db.session.commit()
        return rows

    @serialize_registry("hpc-allocation-queue")
    def register(self, actor, payload):
        gateway_id = payload.get("gateway_reservation_id")
        if not isinstance(gateway_id, str) or not OPAQUE_ID.fullmatch(gateway_id):
            raise ValidationError("Enter the HPC-Link reservation ID issued by the operator")
        label = self._label(payload.get("label"))
        if HpcReservation.query.filter_by(gateway_reservation_id=gateway_id).first():
            raise OperationConflict("This GPU reservation is already registered")
        config = self.allocations.get_or_create_config()
        gateway_url = str(config.base_url or "").rstrip("/")
        response = self.allocations.client(config).get(f"{GATEWAY_RESERVATIONS}/{gateway_id}", timeout=10)
        facts, expires_at = self._facts(response, gateway_id)
        if response.get("status") != "available" or expires_at <= _utc_now_naive():
            raise ValidationError("HPC-Link must report an available running GPU reservation")
        row = HpcReservation(gateway_reservation_id=gateway_id, gateway_url=gateway_url, label=label,
                             scheduler_json=json.dumps(facts), expires_at=expires_at, created_by_id=actor.id)
        self._set_grants(row, payload.get("allowed_emails"))
        db.session.add(row)
        db.session.commit()
        return self._serialize(row, admin=True)

    @serialize_registry("hpc-allocation-queue")
    def edit(self, public_id, payload):
        row = self._get(public_id)
        if "label" in payload:
            row.label = self._label(payload["label"])
        if "enabled" in payload:
            if type(payload["enabled"]) is not bool:
                raise ValidationError("enabled must be a boolean")
            row.enabled = payload["enabled"]
        if "allowed_emails" in payload:
            self._set_grants(row, payload["allowed_emails"])
        db.session.commit()
        return self._serialize(row, admin=True)

    @serialize_registry("hpc-allocation-queue")
    def claim(self, public_id, user, payload):
        reservation = self._get(public_id)
        purpose = payload.get("purpose", "workflow")
        if purpose not in ("workflow", "playground"):
            raise ValidationError("Select workflow or playground as the reservation purpose")
        if not self.can_use(reservation, user):
            raise ResourceNotFoundError("GPU reservation not found")
        session_id = payload.get("session_id")
        if type(session_id) is not int or session_id < 1:
            raise ValidationError("Select an upload session for this GPU claim")
        session = db.session.get(Session, session_id)
        if session is None or session.user_id != user.id:
            raise SecurityError("Choose an upload session that belongs to your account")
        if not is_session_mutable(session):
            raise SecurityError("This read-only session cannot claim an HPC allocation")
        existing = self.active_claim(reservation)
        if existing and existing.expires_at and existing.expires_at <= _utc_now_naive():
            self.allocations.refresh_allocation(existing)
            existing = None
        if existing:
            if existing.user_id != user.id or existing.session_id != session.id:
                raise OperationConflict("This GPU reservation already has an active claim")
            if existing.status == "allocating":
                self.complete_claim(existing)
            return self.allocations.serialize_allocation(existing)
        if not reservation.enabled or self._observe(reservation) != "available":
            raise OperationConflict("This GPU reservation is not currently available")
        if HpcAllocation.query.filter(HpcAllocation.session_id == session_id,
                                      HpcAllocation.status.in_({"queued", *ACTIVE_ALLOCATION_STATES})).first():
            raise OperationConflict("Release the upload session's current HPC allocation first")
        config = self.allocations.get_or_create_config()
        if (self.allocations._active_count() >= config.max_active_allocations
                or self.allocations._active_count(user_id=user.id) >= config.max_active_allocations_per_user):
            raise OperationConflict("The active HPC allocation limit has been reached")
        facts = json.loads(reservation.scheduler_json)
        row = HpcAllocation(user_id=user.id, session_id=session.id, reservation=reservation, purpose=purpose,
                            status="allocating", requested_partition=facts["partition"], requested_gpu_type=facts["gpu_type"],
                            requested_gpu_count=facts["gpu_count"], remote_job_id=facts["job_id"], node_name=facts["node_name"],
                            expires_at=reservation.expires_at,
                            requested_duration_minutes=max(1, int((reservation.expires_at - _utc_now_naive()).total_seconds() / 60)))
        db.session.add(row)
        db.session.commit()  # Persist the idempotency key before the remote call.
        self.complete_claim(row)
        return self.allocations.serialize_allocation(row)

    def complete_claim(self, allocation):
        reservation = allocation.reservation
        if allocation.expires_at <= _utc_now_naive():
            allocation.status = "expired"
            db.session.commit()
            return
        if not reservation.enabled or not self.can_use(reservation, allocation.user):
            allocation.last_error = "Access to this GPU claim is no longer enabled"
            db.session.commit()
            return
        payload = {"reservation_id": reservation.gateway_reservation_id, "claim_id": allocation.public_id}
        try:
            response = self.client_for(reservation).post("/api/apps/webhdp/sessions/adopt", payload, timeout=15)
            session_id = response.get("session_id", "")
            root = PurePosixPath(response.get("remote_session_dir") or "")
            input_dir = response.get("input_dir")
            output_dir = response.get("output_dir")
            expires_at = _parse_datetime(response.get("expires_at"))
            if (response.get("externally_managed") is not True or response.get("reservation_id") != reservation.gateway_reservation_id
                    or str(response.get("job_id")) != allocation.remote_job_id or not isinstance(session_id, str)
                    or not OPAQUE_ID.fullmatch(session_id) or not root.is_absolute() or ".." in root.parts
                    or input_dir != str(root / "inputs") or output_dir != str(root / "outputs") or not expires_at):
                raise ValidationError("HPC-Link did not confirm the reserved GPU claim")
            allocation.remote_session_id = session_id
            allocation.remote_session_dir = str(root)
            allocation.remote_input_dir, allocation.remote_output_dir = input_dir, output_dir
            allocation.expires_at = expires_at
            allocation.allocated_at = _utc_now_naive()
            allocation.scheduler_state = "RUNNING"
            allocation.status = "running"
            allocation.last_error = None
        except (APIConnectionError, APITimeoutError, ValidationError):
            # A timed-out response may have created the lease. Retry with the same ID.
            allocation.last_error = "HPC-Link has not confirmed this GPU claim. Refresh to retry or release access."
        db.session.commit()

    def detach(self, allocation):
        if allocation.status == "released":
            return {"cancelled": False, "detached": True}
        for model in (PipelineRun, PlaygroundRun):
            if model.query.filter(model.session_id == allocation.session_id,
                                  model.status.in_({PipelineRunStatus.PENDING, PipelineRunStatus.RUNNING})).first():
                raise OperationConflict("Wait for the upload session's run to finish before releasing GPU access")
        reservation = allocation.reservation
        path = f"{GATEWAY_RESERVATIONS}/{reservation.gateway_reservation_id}/claims/{allocation.public_id}"
        try:
            response = self.client_for(reservation).delete(path, timeout=20)
        except APIConnectionError as exc:
            if exc.details.get("http_status") == 409:
                raise OperationConflict("HPC-Link is still running work for this GPU claim") from exc
            raise
        if response.get("detached") is not True or response.get("cancelled") is not False:
            raise ValidationError("HPC-Link did not confirm that access was released")
        return response
