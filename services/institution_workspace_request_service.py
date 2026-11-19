"""Review institutional workspace applications without exposing private workspaces."""

import logging
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy.orm import selectinload

from database.database import db
from database.models import InstitutionWorkspaceRequest, User, UserRole
from exceptions import ResourceNotFoundError, SecurityError, ValidationError
from services.audit_service import record_audit_event
from services.institution_service import InstitutionService, institution_directory_lock, normalize_institution_name, validate_institution_name
from services.model_publication_accounts import is_demo
from services.notification_service import notify_admins, notify_user
from services.registry_lock import OperationConflict, registry_lock

logger = logging.getLogger(__name__)


def _optional_note(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value.strip()) > 2000:
        raise ValidationError("Notes must contain at most 2,000 characters")
    return value.strip() or None


def _require_account(actor, *, admin=False):
    if not actor.is_verified or actor.force_password_change or is_demo(actor):
        raise SecurityError("A verified, active account is required")
    if admin and actor.role != UserRole.ADMIN:
        raise SecurityError("Site administration is required to review workspace requests")


@contextmanager
def _workspace_request_lock(name):
    with registry_lock(name):
        try:
            yield
        except Exception:
            db.session.rollback()
            raise


def serialize_workspace_request(row, *, include_requester=False):
    payload = {
        "id": row.id,
        "name": row.name,
        "reason": row.reason,
        "status": row.status,
        "institution_id": row.institution_id,
        "created_at": row.created_at.isoformat(),
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "review_note": row.review_note,
    }
    if include_requester:
        requester = row.requester
        payload["requester"] = {
            "id": row.requester_user_id,
            "email": requester.email if requester else None,
            "display_name": requester.display_name if requester else None,
        }
    return payload


class InstitutionWorkspaceRequestService:
    def list(self, actor: User, *, include_all=False, status=None, page=1, per_page=25):
        _require_account(actor, admin=include_all)
        query = InstitutionWorkspaceRequest.query
        if include_all:
            query = query.options(selectinload(InstitutionWorkspaceRequest.requester))
        else:
            query = query.filter_by(requester_user_id=actor.id)
        if status:
            if status not in {"pending", "approved", "rejected"}:
                raise ValidationError("Choose pending, approved or rejected for the request status")
            query = query.filter_by(status=status)
        result = query.order_by(InstitutionWorkspaceRequest.created_at.desc(), InstitutionWorkspaceRequest.id.desc()).paginate(
            page=page, per_page=per_page, max_per_page=100, error_out=False
        )
        return {
            "requests": [serialize_workspace_request(row, include_requester=include_all) for row in result.items],
            "pagination": {"page": result.page, "per_page": result.per_page, "pages": result.pages, "total": result.total},
        }

    def submit(self, actor: User, *, name, reason=None):
        name = validate_institution_name(name)
        normalized = normalize_institution_name(name)
        reason = _optional_note(reason)
        with _workspace_request_lock(f"institution-workspace-requests:{actor.id}"):
            db.session.refresh(actor)
            _require_account(actor)
            existing = InstitutionWorkspaceRequest.query.filter_by(
                requester_user_id=actor.id, normalized_name=normalized, status="pending"
            ).first()
            if existing:
                raise OperationConflict("You already have a pending workspace request with this name")
            pending_count = InstitutionWorkspaceRequest.query.filter_by(requester_user_id=actor.id, status="pending").count()
            if pending_count >= 5:
                raise OperationConflict("Review your pending workspace requests before submitting another")
            row = InstitutionWorkspaceRequest(requester_user_id=actor.id, name=name, normalized_name=normalized, reason=reason)
            db.session.add(row)
            db.session.flush()
            record_audit_event(
                actor_user_id=actor.id,
                event_type="institution_workspace_requested",
                entity_type="institution_workspace_request",
                entity_id=row.id,
            )
            db.session.commit()
        self._notify_admins(row)
        return row

    def _notify_admins(self, row):
        try:
            notify_admins(
                exclude_user_id=row.requester_user_id,
                notification_type="institution.workspace_requested",
                title="Institution workspace request received",
                body=f"Review the workspace request for {row.name}.",
                entity_type="institution_workspace_request",
                entity_id=row.id,
                action_url="/account/institutions",
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("Unable to notify administrators of a workspace request")

    def decide(self, actor: User, request_id: int, *, decision, note=None):
        if decision not in ("approve", "reject"):
            raise ValidationError("A decision must approve or reject the workspace request")
        note = _optional_note(note)
        with _workspace_request_lock(f"institution-workspace-review:{request_id}"), institution_directory_lock():
            db.session.refresh(actor)
            _require_account(actor, admin=True)
            row = db.session.get(InstitutionWorkspaceRequest, request_id, populate_existing=True)
            if row is None:
                raise ResourceNotFoundError("Workspace request not found")
            if row.status != "pending":
                raise OperationConflict("This workspace request has already been reviewed")
            if decision == "approve":
                if row.requester is None:
                    raise ValidationError("The requesting account is no longer available")
                institution = InstitutionService().create_institution(
                    name=row.name, description=None, actor=actor, owner=row.requester, profile_visibility="private", commit=False,
                )
                row.institution_id = institution.id
            row.status = "approved" if decision == "approve" else "rejected"
            row.reviewed_by_user_id = actor.id
            row.reviewed_at = datetime.utcnow()
            row.review_note = note
            record_audit_event(
                actor_user_id=actor.id,
                institution_id=row.institution_id,
                event_type=f"institution_workspace_request_{row.status}",
                entity_type="institution_workspace_request",
                entity_id=row.id,
                details={"requester_user_id": row.requester_user_id},
            )
            db.session.commit()
        self._notify_decision(row)
        return row

    def _notify_decision(self, row):
        try:
            notify_user(
                recipient_user_id=row.requester_user_id,
                notification_type=f"institution.workspace_request_{row.status}",
                title=f"Workspace request {row.status}",
                body=f"Your request for {row.name} was {row.status}.",
                institution_id=row.institution_id,
                entity_type="institution_workspace_request",
                entity_id=row.id,
                action_url="/account/institutions",
                dedupe_key=f"institution:workspace-request:{row.id}:{row.status}",
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("Unable to record the workspace decision notification")
