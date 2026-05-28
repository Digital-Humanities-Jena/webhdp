"""HPC resources request and approval workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from database.database import db
from database.models import HpcResourceRequest, User, UserRole
from exceptions import ResourceNotFoundError, SecurityError, ValidationError
from services.audit_service import record_audit_event
from services.notification_service import notify_admins, notify_user


HPC_ACCESS_CAPABILITY = "hpc_link_access"
HPC_USE_CASES = ("3D Models", "Photographies", "Historical Data", "Documents", "Other")


def _utc_now() -> datetime:
    return datetime.utcnow()


def _serialize_user(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role.value if user.role else "user",
        "display_name": user.display_name,
        "full_name": user.full_name,
        "affiliation": user.affiliation,
        "capabilities": user.capabilities,
        "hpc_access": user.role == UserRole.ADMIN or user.has_capability(HPC_ACCESS_CAPABILITY),
        "hpc_access_source": "implicit_admin" if user.role == UserRole.ADMIN else ("explicit" if user.has_capability(HPC_ACCESS_CAPABILITY) else None),
    }


class HpcResourceRequestService:
    def _normalize_use_cases(self, values: Any) -> list[str]:
        if not isinstance(values, list):
            raise ValidationError("use_cases must be an array")
        allowed = {item.lower(): item for item in HPC_USE_CASES}
        normalized = []
        seen = set()
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            canonical = allowed.get(text.lower())
            if not canonical:
                raise ValidationError(f"Unsupported HPC use case: {text}")
            marker = canonical.lower()
            if marker in seen:
                continue
            seen.add(marker)
            normalized.append(canonical)
        if not normalized:
            raise ValidationError("At least one use case is required")
        return normalized

    def latest_for_user(self, user_id: int) -> HpcResourceRequest | None:
        return (
            HpcResourceRequest.query.filter_by(user_id=int(user_id))
            .order_by(HpcResourceRequest.submitted_at.desc(), HpcResourceRequest.id.desc())
            .first()
        )

    def pending_for_user(self, user_id: int) -> HpcResourceRequest | None:
        return HpcResourceRequest.query.filter_by(user_id=int(user_id), status=HpcResourceRequest.STATUS_PENDING).first()

    def access_summary_for_user(self, user: User) -> dict[str, Any]:
        request_row = self.latest_for_user(user.id)
        return {
            "has_access": user.role == UserRole.ADMIN or user.has_capability(HPC_ACCESS_CAPABILITY),
            "access_source": "implicit_admin" if user.role == UserRole.ADMIN else ("explicit" if user.has_capability(HPC_ACCESS_CAPABILITY) else None),
            "latest_request": request_row.to_dict() if request_row else None,
            "pending_request": request_row.to_dict() if request_row and request_row.status == HpcResourceRequest.STATUS_PENDING else None,
            "use_cases": list(HPC_USE_CASES),
        }

    def submit_request(self, *, user: User, payload: dict[str, Any]) -> HpcResourceRequest:
        if self.pending_for_user(user.id):
            raise ValidationError("You already have a pending HPC resources request")

        full_name = str(payload.get("full_name") or "").strip()
        affiliation = str(payload.get("affiliation") or "").strip()
        if not full_name:
            raise ValidationError("Full name is required")
        if not affiliation:
            raise ValidationError("Institutional affiliation is required")
        use_cases = self._normalize_use_cases(payload.get("use_cases"))
        notes = str(payload.get("notes") or "").strip() or None

        request_row = HpcResourceRequest(
            user_id=user.id,
            full_name=full_name,
            affiliation=affiliation,
            notes=notes,
            status=HpcResourceRequest.STATUS_PENDING,
        )
        request_row.set_use_cases(use_cases)

        if not user.full_name:
            user.full_name = full_name
        if not user.affiliation:
            user.affiliation = affiliation

        db.session.add(request_row)
        db.session.flush()
        record_audit_event(
            actor_user_id=user.id,
            event_type="hpc_resource_request.submitted",
            entity_type="hpc_resource_request",
            entity_id=request_row.public_id,
            details={"use_cases": use_cases},
        )
        notify_admins(
            exclude_user_id=user.id,
            actor_user_id=user.id,
            notification_type="hpc.request_submitted",
            category="hpc",
            severity="info",
            title="HPC access requested",
            body=f"{user.email} requested access to HPC resources.",
            entity_type="hpc_resource_request",
            entity_id=request_row.public_id,
            action_url="/admin/hpc-access",
            payload={
                "request_id": request_row.id,
                "request_public_id": request_row.public_id,
                "user_id": user.id,
                "email": user.email,
                "use_cases": use_cases,
            },
            dedupe_key=f"hpc-request:{request_row.public_id}:submitted",
        )
        db.session.commit()
        return request_row

    def list_requests(self, *, status: str | None = None) -> list[dict[str, Any]]:
        query = HpcResourceRequest.query
        normalized_status = str(status or "").strip().lower()
        if normalized_status and normalized_status != "all":
            if normalized_status not in HpcResourceRequest.VALID_STATUSES:
                raise ValidationError("Invalid request status")
            query = query.filter(HpcResourceRequest.status == normalized_status)
        rows = query.order_by(HpcResourceRequest.submitted_at.desc(), HpcResourceRequest.id.desc()).all()
        return [self.serialize_request(row, include_user=True) for row in rows]

    def serialize_request(self, request_row: HpcResourceRequest, *, include_user: bool = False) -> dict[str, Any]:
        payload = request_row.to_dict()
        if include_user:
            payload["user"] = _serialize_user(request_row.user)
        return payload

    def get_request(self, request_id: int) -> HpcResourceRequest:
        request_row = db.session.get(HpcResourceRequest, int(request_id))
        if request_row is None:
            raise ResourceNotFoundError("HPC resources request not found")
        return request_row

    def approve_request(self, *, request_id: int, admin_user: User, comment: str | None = None) -> HpcResourceRequest:
        request_row = self.get_request(request_id)
        if request_row.status != HpcResourceRequest.STATUS_PENDING:
            raise ValidationError("Only pending HPC resources requests can be approved")
        target_user = request_row.user
        capabilities = target_user.capabilities
        if HPC_ACCESS_CAPABILITY.lower() not in {item.lower() for item in capabilities}:
            target_user.set_capabilities([*capabilities, HPC_ACCESS_CAPABILITY])

        now = _utc_now()
        request_row.status = HpcResourceRequest.STATUS_APPROVED
        request_row.reviewer_user_id = admin_user.id
        request_row.review_comment = str(comment or "").strip() or None
        request_row.reviewed_at = now
        request_row.updated_at = now
        notify_user(
            recipient_user_id=target_user.id,
            actor_user_id=admin_user.id,
            notification_type="hpc.request_approved",
            category="hpc",
            severity="success",
            title="HPC access approved",
            body="Your request for HPC resources has been approved.",
            entity_type="hpc_resource_request",
            entity_id=request_row.public_id,
            action_url="/hpc-resources",
            dedupe_key=f"hpc-request:{request_row.public_id}:approved",
        )
        notify_admins(
            actor_user_id=admin_user.id,
            notification_type="hpc.access_granted",
            category="hpc",
            severity="success",
            title="HPC access granted",
            body=f"{target_user.email} was approved for HPC resource access.",
            entity_type="hpc_resource_request",
            entity_id=request_row.public_id,
            action_url="/admin/hpc-access",
            payload={
                "request_id": request_row.id,
                "request_public_id": request_row.public_id,
                "user_id": target_user.id,
                "email": target_user.email,
                "approved_by_user_id": admin_user.id,
            },
            dedupe_key=f"hpc-request:{request_row.public_id}:access-granted",
        )
        record_audit_event(
            actor_user_id=admin_user.id,
            event_type="hpc_resource_request.approved",
            entity_type="hpc_resource_request",
            entity_id=request_row.public_id,
            details={"user_id": target_user.id, "comment": request_row.review_comment},
        )
        db.session.commit()
        return request_row

    def reject_request(self, *, request_id: int, admin_user: User, comment: str | None = None) -> HpcResourceRequest:
        request_row = self.get_request(request_id)
        if request_row.status != HpcResourceRequest.STATUS_PENDING:
            raise ValidationError("Only pending HPC resources requests can be rejected")
        now = _utc_now()
        request_row.status = HpcResourceRequest.STATUS_REJECTED
        request_row.reviewer_user_id = admin_user.id
        request_row.review_comment = str(comment or "").strip() or None
        request_row.reviewed_at = now
        request_row.updated_at = now
        notify_user(
            recipient_user_id=request_row.user_id,
            actor_user_id=admin_user.id,
            notification_type="hpc.request_rejected",
            category="hpc",
            severity="warning",
            title="HPC access request reviewed",
            body=request_row.review_comment or "Your request for HPC resources was not approved.",
            entity_type="hpc_resource_request",
            entity_id=request_row.public_id,
            action_url="/hpc-resources",
            dedupe_key=f"hpc-request:{request_row.public_id}:rejected",
        )
        record_audit_event(
            actor_user_id=admin_user.id,
            event_type="hpc_resource_request.rejected",
            entity_type="hpc_resource_request",
            entity_id=request_row.public_id,
            details={"user_id": request_row.user_id, "comment": request_row.review_comment},
        )
        db.session.commit()
        return request_row

    def list_hpc_access_users(self) -> list[dict[str, Any]]:
        users = User.query.order_by(User.email.asc()).all()
        return [
            _serialize_user(user)
            for user in users
            if user.role == UserRole.ADMIN or user.has_capability(HPC_ACCESS_CAPABILITY)
        ]

    def revoke_access(self, *, user_id: int, admin_user: User) -> User:
        user = db.session.get(User, int(user_id))
        if user is None:
            raise ResourceNotFoundError("User not found")
        if user.role == UserRole.ADMIN:
            raise SecurityError("Admin implicit HPC access cannot be revoked")
        next_capabilities = [item for item in user.capabilities if item.lower() != HPC_ACCESS_CAPABILITY.lower()]
        user.set_capabilities(next_capabilities)
        notify_user(
            recipient_user_id=user.id,
            actor_user_id=admin_user.id,
            notification_type="hpc.access_revoked",
            category="hpc",
            severity="warning",
            title="HPC access revoked",
            body="An administrator revoked HPC access for your account.",
            entity_type="user",
            entity_id=user.id,
            action_url="/hpc-resources",
            dedupe_key=f"hpc-access:{user.id}:revoked:{int(_utc_now().timestamp())}",
        )
        record_audit_event(
            actor_user_id=admin_user.id,
            event_type="hpc_access.revoked",
            entity_type="user",
            entity_id=user.id,
            details={"capability": HPC_ACCESS_CAPABILITY},
        )
        db.session.commit()
        return user
