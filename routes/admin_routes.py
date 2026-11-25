from database.models import UserRole, SubmissionReview, SystemConfig
import logging
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from flask import Blueprint, current_app, g, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from database.models import AuditEvent, HpcAllocation, User, UserMfaChallenge, UserRecoveryCode, Session as DBSession, Submission, UserMetadata
from database.database import db
from api_utils import APIResponse
from constants import (
    UPLOAD_PROGRESS_FIELD,
    UPLOAD_STORAGE_MODE_FIELD,
    UPLOAD_SUBMIT_TOKEN_FIELD,
    UPLOAD_TASK_ID_FIELD,
    UPLOAD_WORKER_GROUP_ID_FIELD,
)
from exceptions import SecurityError, ResourceNotFoundError, ValidationError, AppException
from routes.session_routes import (
    _build_upload_operation_payload,
    _get_session_metadata_map,
    _get_upload_file_counts,
)
from services.hdpc_import_service import import_hdpc_for_user
from services.hpc_resource_request_service import HpcResourceRequestService
from services.hpc_allocation_service import QUEUEABLE_ALLOCATION_STATES, TERMINAL_ALLOCATION_STATES
from services.admin_observability_service import AdminObservabilityService
from services.audit_service import record_audit_event
from services.backup_service import BackupError, BackupService
from services.notification_service import cleanup_notifications, list_notification_deliveries, notify_admins, send_notification_digests
from services.recovery_code_service import create_admin_recovery_code, generate_temporary_password, recovery_code_status
from services.version_detection_policy_service import VersionDetectionPolicyService
from services.zenodo_config_service import ZenodoConfigService
from services.local_edm_validator_client import LocalEdmValidatorClient
from services.mfa_config_service import get_mfa_provider_bypass_config, save_mfa_provider_bypass_config
from security import path_is_within

logger = logging.getLogger(__name__)
admin_bp = Blueprint("admin", __name__)
hpc_request_service = HpcResourceRequestService()
ACTIVE_SESSION_STATUSES = {"queued", "scanned", "submitting", "processing", "pending", "active", "running", "ready"}
TERMINAL_SESSION_STATUSES = {"completed", "failed", "cancelled", "deleted"}


def require_admin(func):
    """Decorator to require admin role"""

    def wrapper(*args, **kwargs):
        from services.user_service import UserService

        user_service = UserService()
        user_id = get_jwt_identity()
        user = user_service.get_by_id(user_id)

        if user.role != UserRole.ADMIN:
            raise SecurityError("Admin access required")

        return func(*args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


def require_moderator_or_admin(func):
    """Decorator to require moderator or admin role"""

    def wrapper(*args, **kwargs):
        from services.user_service import UserService

        user_service = UserService()
        user_id = get_jwt_identity()
        user = user_service.get_by_id(user_id)

        if user.role.value not in ("moderator", "admin"):
            raise SecurityError("Moderator or admin access required")

        g.current_user = user  # Store user for convenience
        return func(*args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


def _serialize_admin_user(user):
    payload = user.to_dict()
    payload["recovery_codes"] = recovery_code_status(user)
    now = datetime.utcnow()
    admin_recovery_remaining = UserRecoveryCode.query.filter(
        UserRecoveryCode.user_id == user.id,
        UserRecoveryCode.source == "admin_issued",
        UserRecoveryCode.used_at.is_(None),
        UserRecoveryCode.invalidated_at.is_(None),
        (UserRecoveryCode.expires_at.is_(None)) | (UserRecoveryCode.expires_at > now),
    ).count()
    payload["admin_recovery_codes"] = {
        "remaining_count": admin_recovery_remaining,
    }
    payload["last_recovery_reset_at"] = None
    last_reset = (
        AuditEvent.query.filter_by(
            event_type="admin.user_recovery_reset",
            entity_type="user",
            entity_id=str(user.id),
        )
        .order_by(AuditEvent.created_at.desc())
        .first()
    )
    if last_reset:
        payload["last_recovery_reset_at"] = last_reset.created_at.isoformat()
    return payload


def _serialize_session_monitor_row(session_row):
    owner = getattr(session_row, "user", None)
    return {
        "id": session_row.id,
        "status": session_row.status,
        "origin_type": getattr(session_row, "origin_type", None) or "workflow",
        "access_mode": getattr(session_row, "access_mode", None) or "full",
        "sharing_scope": getattr(session_row, "sharing_scope", None) or "private",
        "institution_id": session_row.institution_id,
        "session_dir": session_row.session_dir,
        "created_at": session_row.created_at.isoformat() if session_row.created_at else None,
        "updated_at": session_row.updated_at.isoformat() if session_row.updated_at else None,
        "user": {
            "id": owner.id,
            "email": owner.email,
            "display_name": owner.display_name,
            "full_name": owner.full_name,
            "slug": owner.slug,
        }
        if owner
        else None,
        "file_count": len(getattr(session_row, "files", []) or []),
    }


def _serialize_admin_allocation(allocation, service):
    payload = service.serialize_allocation(allocation)
    owner = getattr(allocation, "user", None)
    session_row = getattr(allocation, "session", None)
    payload["user"] = {
        "id": owner.id,
        "email": owner.email,
        "display_name": owner.display_name,
        "full_name": owner.full_name,
        "slug": owner.slug,
    } if owner else None
    payload["session"] = _serialize_session_monitor_row(session_row) if session_row else None
    return payload


@admin_bp.route("/submissions", methods=["GET"])
@jwt_required()
@require_moderator_or_admin
def list_all_submissions():
    """List all submissions (admin only)"""
    submissions = (
        db.session.query(Submission, User.email.label("user_email"))
        .join(DBSession, Submission.session_id == DBSession.id)
        .join(User, DBSession.user_id == User.id)
        .order_by(Submission.created_at.desc())
        .all()
    )

    submission_list = [
        {
            "id": sub.Submission.id,
            "session_id": sub.Submission.session_id,
            "pipeline_id": sub.Submission.pipeline_id,
            "status": sub.Submission.status,
            "created_at": sub.Submission.created_at.isoformat(),
            "user_email": sub.user_email,
        }
        for sub in submissions
    ]

    return APIResponse.success(data={"submissions": submission_list})


@admin_bp.route("/upload-operations", methods=["GET"])
@jwt_required()
@require_moderator_or_admin
def list_upload_operations():
    status_filter = (request.args.get("status") or "all").strip().lower()

    upload_session_ids = [
        row[0]
        for row in (
            db.session.query(UserMetadata.session_id)
            .filter(
                UserMetadata.field_name.in_(
                    [
                        UPLOAD_SUBMIT_TOKEN_FIELD,
                        UPLOAD_TASK_ID_FIELD,
                        UPLOAD_PROGRESS_FIELD,
                    ]
                )
            )
            .distinct()
            .all()
        )
    ]
    if not upload_session_ids:
        return APIResponse.success(data={"operations": []})

    rows = (
        db.session.query(DBSession, User.email.label("user_email"))
        .join(User, DBSession.user_id == User.id)
        .filter(DBSession.id.in_(upload_session_ids))
        .order_by(DBSession.created_at.desc())
        .all()
    )

    session_ids = [row[0].id for row in rows]
    metadata_map = _get_session_metadata_map(
        session_ids,
        {
            UPLOAD_SUBMIT_TOKEN_FIELD,
            UPLOAD_TASK_ID_FIELD,
            UPLOAD_STORAGE_MODE_FIELD,
            UPLOAD_PROGRESS_FIELD,
            UPLOAD_WORKER_GROUP_ID_FIELD,
        },
    )
    file_counts = _get_upload_file_counts(session_ids)

    operations = [
        _build_upload_operation_payload(
            row[0],
            metadata_fields=metadata_map.get(row[0].id, {}),
            file_counts=file_counts.get(row[0].id, {}),
            user_email=row.user_email,
        )
        for row in rows
    ]

    if status_filter == "running":
        operations = [operation for operation in operations if operation.get("is_running")]
    elif status_filter == "completed":
        operations = [operation for operation in operations if operation.get("progress", {}).get("current_stage") == "completed"]
    elif status_filter == "failed":
        operations = [operation for operation in operations if operation.get("status") == "failed"]

    return APIResponse.success(data={"operations": operations})


@admin_bp.route("/submissions/<int:submission_id>", methods=["GET"])
@jwt_required()
@require_moderator_or_admin
def get_submission_detail(submission_id):
    """Get detailed submission info (moderator/admin only)"""
    submission = db.session.get(Submission, submission_id)
    if not submission:
        raise ResourceNotFoundError("Submission not found", details={"submission_id": submission_id})

    session = db.session.get(DBSession, submission.session_id)
    if not session:
        # This points to a data integrity issue if submission exists but session missing
        raise ResourceNotFoundError("Associated session not found", details={"session_id": submission.session_id})

    user = db.session.get(User, session.user_id)
    if not user:
         raise ResourceNotFoundError("Associated user not found", details={"user_id": session.user_id})

    # --- Fetch review history ---
    submission_reviews = (
        db.session.query(SubmissionReview, User.email.label("moderator_email"))
        .join(User, SubmissionReview.moderator_id == User.id)
        .filter(SubmissionReview.submission_id == submission_id)
        .order_by(SubmissionReview.created_at.desc())
        .all()
    )

    review_history = [
        {
            "id": review.SubmissionReview.id,
            "action": review.SubmissionReview.action,
            "comment": review.SubmissionReview.comment,
            "new_status": review.SubmissionReview.new_status,
            "previous_status": review.SubmissionReview.previous_status,
            "created_at": review.SubmissionReview.created_at.isoformat(),
            "moderator_email": review.moderator_email,
        }
        for review in submission_reviews
    ]

    parsed_timings = None
    if submission.timings:
        try:
            parsed_timings = json.loads(submission.timings)
        except (TypeError, json.JSONDecodeError):
            parsed_timings = None

    return APIResponse.success(
        data={
            "submission": {
                "id": submission.id,
                "pipeline_id": submission.pipeline_id,
                "status": submission.status,
                "result": submission.result,
                "timings": parsed_timings,
                "created_at": submission.created_at.isoformat(),
                "completed_at": submission.completed_at.isoformat() if submission.completed_at else None,
            },
            "session": {"id": session.id, "file_count": len(session.files)},
            "user": {"email": user.email, "id": user.id},
            "review_history": review_history,
        }
    )


@admin_bp.route("/stats", methods=["GET"])
@jwt_required()
@require_admin
def get_admin_stats():
    """Get admin statistics"""
    total_users = User.query.count()
    total_sessions = DBSession.query.count()
    total_submissions = Submission.query.count()
    pending = Submission.query.filter_by(status="pending").count()
    completed = Submission.query.filter_by(status="completed").count()

    return APIResponse.success(
        data={
            "total_users": total_users,
            "total_sessions": total_sessions,
            "total_submissions": total_submissions,
            "pending_submissions": pending,
            "completed_submissions": completed,
        }
    )


@admin_bp.route("/setup-guidance", methods=["GET"])
@jwt_required()
@require_admin
def get_admin_setup_guidance():
    """Return mode-aware administrator setup guidance without active HPC calls."""
    from services.setup_guidance_service import build_admin_setup_guidance

    return APIResponse.success(data=build_admin_setup_guidance(current_app))


@admin_bp.route("/observability/credentials-status", methods=["GET"])
@jwt_required()
@require_admin
def get_credentials_status():
    return APIResponse.success(data=AdminObservabilityService.get_credentials_status())


@admin_bp.route("/observability/api-activity", methods=["GET"])
@jwt_required()
@require_admin
def get_api_activity():
    route_family = request.args.get("route_family")
    service = request.args.get("service")
    status_class = request.args.get("status_class")
    hours = request.args.get("hours", type=int)
    limit = request.args.get("limit", default=50, type=int)
    payload = AdminObservabilityService.get_api_activity(
        route_family=route_family,
        service=service,
        status_class=status_class,
        hours=hours,
        limit=limit,
    )
    return APIResponse.success(data=payload)


@admin_bp.route("/observability/checks/<check_id>", methods=["POST"])
@jwt_required()
@require_admin
def run_observability_check(check_id):
    try:
        result = AdminObservabilityService.run_check(check_id, app=current_app)
    except ValueError as exc:
        return APIResponse.validation_error(str(exc))
    return APIResponse.success(data=result, message="Observability check completed")


@admin_bp.route("/observability/notification-deliveries", methods=["GET"])
@jwt_required()
@require_admin
def get_notification_deliveries():
    recipient_user_id = request.args.get("recipient_user_id", type=int)
    payload = list_notification_deliveries(
        channel=request.args.get("channel"),
        status=request.args.get("status"),
        recipient_user_id=recipient_user_id,
        limit=request.args.get("limit", default=100, type=int),
        start_at=request.args.get("start_at"),
        end_at=request.args.get("end_at"),
    )
    return APIResponse.success(data=payload)


@admin_bp.route("/observability/notification-digest/run", methods=["POST"])
@jwt_required()
@require_admin
def run_notification_digest():
    payload = request.get_json(silent=True) or {}
    result = send_notification_digests(
        user_id=payload.get("user_id"),
        max_per_user=payload.get("max_per_user"),
        user_batch_size=payload.get("user_batch_size"),
    )
    return APIResponse.success(data=result, message="Notification digest run completed")


@admin_bp.route("/observability/notifications/cleanup", methods=["POST"])
@jwt_required()
@require_admin
def run_notification_cleanup():
    payload = request.get_json(silent=True) or {}
    result = cleanup_notifications(batch_size=payload.get("batch_size") or 1000)
    return APIResponse.success(data=result, message="Notification cleanup completed")


@admin_bp.route("/backups/status", methods=["GET"])
@jwt_required()
@require_admin
def get_backup_status():
    output_dir = request.args.get("output_dir") or current_app.config.get("BACKUP_LOCAL_DIR")
    payload = BackupService.get_backup_status(output_dir=output_dir, root=os.getcwd())
    return APIResponse.success(data=payload)


@admin_bp.route("/backups", methods=["GET"])
@jwt_required()
@require_admin
def list_backups():
    provider = (request.args.get("provider") or "local").strip().lower()
    try:
        if provider == "dropbox":
            backups = BackupService.list_dropbox_backups(request.args.get("remote_prefix"))
        elif provider == "local":
            backups = BackupService.list_local_backups(
                output_dir=request.args.get("output_dir") or current_app.config.get("BACKUP_LOCAL_DIR"),
                root=os.getcwd(),
            )
        else:
            return APIResponse.validation_error("provider must be local or dropbox")
    except BackupError as exc:
        return APIResponse.validation_error(str(exc))
    return APIResponse.success(data={"provider": provider, "backups": backups})


@admin_bp.route("/backups", methods=["POST"])
@jwt_required()
@require_admin
def create_backup():
    payload = request.get_json(silent=True) or {}
    try:
        result = BackupService.create_backup(
            root=os.getcwd(),
            output_dir=payload.get("output_dir") or current_app.config.get("BACKUP_LOCAL_DIR"),
            backup_type=payload.get("backup_type") or "manual",
            include_credentials=payload.get("include_credentials"),
            encrypt=payload.get("encrypt"),
            upload_provider=payload.get("provider"),
            remote_prefix=payload.get("remote_prefix"),
            instance_id=payload.get("instance_id"),
        )
    except BackupError as exc:
        BackupService.record_status(
            operation="backup",
            success=False,
            output_dir=payload.get("output_dir") or current_app.config.get("BACKUP_LOCAL_DIR"),
            root=os.getcwd(),
            error=str(exc),
        )
        return APIResponse.validation_error(str(exc))
    return APIResponse.created(data=result, message="Backup created")


@admin_bp.route("/backups/prune", methods=["POST"])
@jwt_required()
@require_admin
def prune_backups():
    payload = request.get_json(silent=True) or {}
    provider = (payload.get("provider") or "local").strip().lower()
    dry_run = bool(payload.get("dry_run", True))
    try:
        if provider == "dropbox":
            result = BackupService.prune_dropbox_backups(
                remote_prefix=payload.get("remote_prefix"),
                retention_days=payload.get("retention_days"),
                dry_run=dry_run,
            )
        elif provider == "local":
            result = BackupService.prune_local_backups(
                output_dir=payload.get("output_dir") or current_app.config.get("BACKUP_LOCAL_DIR"),
                root=os.getcwd(),
                retention_days=payload.get("retention_days"),
                dry_run=dry_run,
            )
        else:
            return APIResponse.validation_error("provider must be local or dropbox")
    except BackupError as exc:
        return APIResponse.validation_error(str(exc))
    return APIResponse.success(data=result, message="Backup retention evaluated")


@admin_bp.route("/submissions/<int:submission_id>", methods=["DELETE"])
@jwt_required()
@require_admin
def delete_submission(submission_id):
    """Delete a submission (admin only)"""
    submission = db.session.get(Submission, submission_id)
    if not submission:
        raise ResourceNotFoundError("Submission not found")

    db.session.delete(submission)
    db.session.commit()

    logger.info(f"Admin deleted submission {submission_id}")
    return APIResponse.success(message="Submission deleted successfully")


@admin_bp.route("/users", methods=["GET"])
@jwt_required()
@require_admin
def list_all_users():
    users = User.query.all()
    user_list = [_serialize_admin_user(user) for user in users]
    return APIResponse.success(data={"users": user_list})


@admin_bp.route("/users/<int:user_id>/role", methods=["PUT"])
@jwt_required()
@require_admin
def update_user_role(user_id):
    data = request.get_json()
    new_role_str = data.get("role")

    try:
        # Validate and convert string to Enum
        new_role_enum = UserRole(new_role_str)
    except ValueError:
        return APIResponse.validation_error(f"Invalid role: {new_role_str}")

    user_to_update = db.session.get(User, user_id)
    if not user_to_update:
        raise ResourceNotFoundError("User not found")

    user_to_update.role = new_role_enum
    db.session.commit()

    logger.info(f"Admin {get_jwt_identity()} changed user {user_id} role to {new_role_str}")
    return APIResponse.success(data=user_to_update.to_dict())


@admin_bp.route("/users/<int:user_id>/capabilities", methods=["PUT"])
@jwt_required()
@require_admin
def update_user_capabilities(user_id):
    data = request.get_json() or {}
    capabilities = data.get("capabilities")
    if not isinstance(capabilities, list):
        return APIResponse.validation_error("capabilities must be an array")

    user_to_update = db.session.get(User, user_id)
    if not user_to_update:
        raise ResourceNotFoundError("User not found")
    previous_capabilities = {item.lower() for item in user_to_update.capabilities}

    from services.user_service import UserService

    updated = UserService().update_capabilities(user_to_update, [str(item) for item in capabilities])
    next_capabilities = {item.lower() for item in updated.capabilities}
    admin_user_id = int(get_jwt_identity())
    if "hpc_link_access" not in previous_capabilities and "hpc_link_access" in next_capabilities:
        notify_admins(
            actor_user_id=admin_user_id,
            notification_type="hpc.access_granted",
            category="hpc",
            severity="success",
            title="HPC access granted",
            body=f"{updated.email} was granted HPC resource access.",
            entity_type="user",
            entity_id=updated.id,
            action_url="/admin/hpc-access",
            payload={"user_id": updated.id, "email": updated.email, "granted_by_user_id": admin_user_id},
            dedupe_key=f"hpc-access:{updated.id}:granted:{int(datetime.utcnow().timestamp())}",
        )
        db.session.commit()
    logger.info("Admin %s changed user %s capabilities", get_jwt_identity(), user_id)
    return APIResponse.success(data=updated.to_dict())


@admin_bp.route("/hpc-resource-requests", methods=["GET"])
@jwt_required()
@require_admin
def list_hpc_resource_requests():
    status = request.args.get("status")
    return APIResponse.success(data={"requests": hpc_request_service.list_requests(status=status)})


@admin_bp.route("/hpc-resource-requests/<int:request_id>/approve", methods=["POST"])
@jwt_required()
@require_admin
def approve_hpc_resource_request(request_id):
    admin_user = db.session.get(User, int(get_jwt_identity()))
    data = request.get_json() or {}
    request_row = hpc_request_service.approve_request(
        request_id=request_id,
        admin_user=admin_user,
        comment=data.get("comment"),
    )
    return APIResponse.success(
        data={"request": hpc_request_service.serialize_request(request_row, include_user=True)},
        message="HPC resources request approved",
    )


@admin_bp.route("/hpc-resource-requests/<int:request_id>/reject", methods=["POST"])
@jwt_required()
@require_admin
def reject_hpc_resource_request(request_id):
    admin_user = db.session.get(User, int(get_jwt_identity()))
    data = request.get_json() or {}
    request_row = hpc_request_service.reject_request(
        request_id=request_id,
        admin_user=admin_user,
        comment=data.get("comment"),
    )
    return APIResponse.success(
        data={"request": hpc_request_service.serialize_request(request_row, include_user=True)},
        message="HPC resources request rejected",
    )


@admin_bp.route("/hpc-access-users", methods=["GET"])
@jwt_required()
@require_admin
def list_hpc_access_users():
    return APIResponse.success(data={"users": hpc_request_service.list_hpc_access_users()})


@admin_bp.route("/hpc-access-users/<int:user_id>/revoke", methods=["POST"])
@jwt_required()
@require_admin
def revoke_hpc_access(user_id):
    admin_user = db.session.get(User, int(get_jwt_identity()))
    user = hpc_request_service.revoke_access(user_id=user_id, admin_user=admin_user)
    return APIResponse.success(data={"user": _serialize_admin_user(user)}, message="HPC access revoked")


@admin_bp.route("/session-monitoring", methods=["GET"])
@jwt_required()
@require_admin
def get_session_monitoring():
    status_filter = str(request.args.get("status") or "active").strip().lower()
    try:
        limit = max(1, min(int(request.args.get("limit") or 100), 250))
    except (TypeError, ValueError):
        return APIResponse.validation_error("limit must be an integer")

    session_query = DBSession.query.join(User, DBSession.user_id == User.id)
    if status_filter == "all":
        pass
    elif status_filter in ACTIVE_SESSION_STATUSES and status_filter != "active":
        session_query = session_query.filter(DBSession.status == status_filter)
    else:
        session_query = session_query.filter(~DBSession.status.in_(list(TERMINAL_SESSION_STATUSES)))
    sessions = session_query.order_by(DBSession.updated_at.desc(), DBSession.id.desc()).limit(limit).all()

    service = current_app.hpc_allocation_service
    allocation_rows = (
        HpcAllocation.query.filter(HpcAllocation.status.in_(list(QUEUEABLE_ALLOCATION_STATES)))
        .order_by(HpcAllocation.requested_at.desc(), HpcAllocation.id.desc())
        .limit(limit)
        .all()
    )
    config = service.get_or_create_config()
    return APIResponse.success(
        data={
            "sessions": [_serialize_session_monitor_row(row) for row in sessions],
            "allocations": [_serialize_admin_allocation(row, service) for row in allocation_rows],
            "summary": {
                "running_sessions": DBSession.query.filter(~DBSession.status.in_(list(TERMINAL_SESSION_STATUSES))).count(),
                "active_hpc_allocations": HpcAllocation.query.filter(HpcAllocation.status.in_(list(QUEUEABLE_ALLOCATION_STATES))).count(),
                "global_hpc_limit": int(config.max_active_allocations or 3),
                "max_active_allocations_per_user": int(config.max_active_allocations_per_user or 1),
            },
            "filters": {"status": status_filter, "limit": limit},
        }
    )


@admin_bp.route("/session-monitoring/sessions/<int:session_id>/terminate", methods=["POST"])
@jwt_required()
@require_admin
def terminate_monitored_session(session_id):
    admin_user = db.session.get(User, int(get_jwt_identity()))
    session_row = db.session.get(DBSession, int(session_id))
    if not session_row:
        raise ResourceNotFoundError("Session not found")

    service = current_app.hpc_allocation_service
    allocations = HpcAllocation.query.filter(
        HpcAllocation.session_id == int(session_id),
        ~HpcAllocation.status.in_(list(TERMINAL_ALLOCATION_STATES)),
    ).all()
    released = []
    for allocation in allocations:
        released.append(service.release(allocation).get("allocation"))

    previous_status = session_row.status
    session_row.status = "cancelled"
    session_row.updated_at = datetime.utcnow()
    record_audit_event(
        actor_user_id=admin_user.id,
        session_id=session_row.id,
        event_type="admin.session_terminated",
        entity_type="session",
        entity_id=session_row.id,
        details={"previous_status": previous_status, "released_allocations": [item.get("allocation_id") for item in released if item]},
    )
    db.session.commit()
    return APIResponse.success(
        data={"session": _serialize_session_monitor_row(session_row), "released_allocations": released},
        message="Session terminated",
    )


@admin_bp.route("/session-monitoring/allocations/<allocation_id>/terminate", methods=["POST"])
@jwt_required()
@require_admin
def terminate_monitored_allocation(allocation_id):
    admin_user = db.session.get(User, int(get_jwt_identity()))
    service = current_app.hpc_allocation_service
    allocation = service.get_allocation(allocation_id, admin_user)
    previous_status = allocation.status
    result = service.release(allocation)
    record_audit_event(
        actor_user_id=admin_user.id,
        session_id=allocation.session_id,
        event_type="admin.hpc_allocation_terminated",
        entity_type="hpc_allocation",
        entity_id=allocation.public_id,
        details={"previous_status": previous_status, "user_id": allocation.user_id},
    )
    db.session.commit()
    return APIResponse.success(data=result, message="HPC allocation terminated")


@admin_bp.route("/users/<int:user_id>/recovery-reset", methods=["POST"])
@jwt_required()
@require_admin
def reset_user_recovery(user_id):
    actor_user_id = int(get_jwt_identity())
    if user_id == actor_user_id:
        return APIResponse.validation_error("Admins cannot reset their own account recovery")

    target_user = db.session.get(User, user_id)
    if not target_user:
        raise ResourceNotFoundError("User not found")

    data = request.get_json() or {}
    temporary_password = str(data.get("temporary_password") or "").strip()
    generated_password = False
    if not temporary_password:
        temporary_password = generate_temporary_password()
        generated_password = True
    if len(temporary_password) < 8:
        raise ValidationError("Temporary password must be at least 8 characters")

    now = datetime.utcnow()
    target_user.set_password(temporary_password)
    target_user.force_password_change = True
    target_user.token_version = int(target_user.token_version or 0) + 1
    UserMfaChallenge.query.filter(
        UserMfaChallenge.user_id == target_user.id,
        UserMfaChallenge.consumed_at.is_(None),
    ).update({"consumed_at": now, "updated_at": now}, synchronize_session=False)
    recovery_code, recovery_row = create_admin_recovery_code(target_user)
    record_audit_event(
        actor_user_id=actor_user_id,
        event_type="admin.user_recovery_reset",
        entity_type="user",
        entity_id=target_user.id,
        details={
            "generated_password": generated_password,
            "recovery_code_expires_at": recovery_row.expires_at.isoformat() if recovery_row.expires_at else None,
        },
    )
    db.session.flush()
    user_payload = _serialize_admin_user(target_user)
    db.session.commit()

    logger.info("Admin %s created account recovery reset for user %s", actor_user_id, target_user.id)
    return APIResponse.success(
        data={
            "user": user_payload,
            "temporary_password": temporary_password,
            "generated_password": generated_password,
            "recovery_code": recovery_code,
            "recovery_code_expires_at": recovery_row.expires_at.isoformat() if recovery_row.expires_at else None,
        },
        message="Account recovery reset created",
    )


@admin_bp.route("/hpc-link-config", methods=["GET"])
@jwt_required()
@require_admin
def get_hpc_link_config():
    return APIResponse.success(data={"config": current_app.hpc_allocation_service.serialize_config()})


@admin_bp.route("/hpc-link-config", methods=["PUT"])
@jwt_required()
@require_admin
def update_hpc_link_config():
    data = request.get_json() or {}
    config = current_app.hpc_allocation_service.update_config(data)
    return APIResponse.success(data={"config": config}, message="HPC-Link configuration saved")


@admin_bp.route("/hpc-link-config/validate", methods=["POST"])
@jwt_required()
@require_admin
def validate_hpc_link_config():
    config = current_app.hpc_allocation_service.validate_config()
    if config.get("last_validation_status") != "valid":
        return APIResponse.error(
            "HPC_LINK_VALIDATION_FAILED",
            config.get("last_validation_error") or "HPC-Link validation failed",
            400,
            details={"config": config},
        )
    return APIResponse.success(data={"config": config}, message="HPC-Link configuration validation completed")


@admin_bp.route("/hpc-reservations", methods=["GET", "POST"])
@jwt_required()
@require_admin
def hpc_reservations():
    from services.hpc_reservation_service import HpcReservationService

    service = HpcReservationService(current_app.hpc_allocation_service)
    if request.method == "GET":
        return APIResponse.success(data={"reservations": service.list(admin=True)})
    payload = request.get_json()
    if not isinstance(payload, dict):
        raise ValidationError("Expected a GPU reservation object")
    actor = db.session.get(User, int(get_jwt_identity()))
    return APIResponse.success(data={"reservation": service.register(actor, payload)}, status_code=201)


@admin_bp.route("/hpc-reservations/<reservation_id>", methods=["PATCH"])
@jwt_required()
@require_admin
def edit_hpc_reservation(reservation_id):
    from services.hpc_reservation_service import HpcReservationService

    payload = request.get_json()
    if not isinstance(payload, dict):
        raise ValidationError("Expected a GPU reservation object")
    service = HpcReservationService(current_app.hpc_allocation_service)
    return APIResponse.success(data={"reservation": service.edit(reservation_id, payload)})


@admin_bp.route("/users/<int:user_id>/hdpc/import", methods=["POST"])
@jwt_required()
@require_admin
def import_hdpc_for_target_user(user_id):
    """Import a .hdpc file and attach it to a new session for any target user."""
    target_user = db.session.get(User, user_id)
    if not target_user:
        raise ResourceNotFoundError("User not found")

    uploaded_file = request.files.get("hdpc_file")
    try:
        actor_user_id = int(get_jwt_identity())
        result = import_hdpc_for_user(user_id=user_id, uploaded_file=uploaded_file, actor_user_id=actor_user_id)
        result["user"] = {"id": target_user.id, "email": target_user.email}
        return APIResponse.created(
            data=result,
            message=f"HDPC file imported for user {target_user.email}",
        )
    except ValidationError as exc:
        return APIResponse.validation_error(str(exc))


@admin_bp.route("/submissions/<int:submission_id>/review", methods=["POST"])
@jwt_required()
@require_moderator_or_admin
def add_submission_review(submission_id):
    data = request.get_json()
    comment = data.get("comment")
    new_status = data.get("new_status")
    moderator_user = g.current_user

    if not comment and not new_status:
        return APIResponse.validation_error("Comment or new status is required")

    submission = db.session.get(Submission, submission_id)
    if not submission:
        raise ResourceNotFoundError("Submission not found")

    # Create the review record for provenance
    review = SubmissionReview(
        submission_id=submission_id,
        moderator_id=moderator_user.id,
        action="status_change" if new_status else "comment",
        comment=comment,
        previous_status=submission.status,
        new_status=new_status,
    )

    # If a new status was provided, update the submission itself
    if new_status:
        submission.status = new_status

    db.session.add(review)
    db.session.commit()

    logger.info(f"User {moderator_user.id} reviewed submission {submission_id}")
    return APIResponse.created(message="Review added successfully")


@admin_bp.route("/zenodo-community-config", methods=["GET"])
@jwt_required()
@require_admin
def get_zenodo_community_config():
    """Get global Zenodo community override configuration."""
    config = ZenodoConfigService.get_community_override_config()
    return APIResponse.success(data={"config": config})


@admin_bp.route("/zenodo-community-config", methods=["POST"])
@jwt_required()
@require_admin
def update_zenodo_community_config():
    """Update global Zenodo community override configuration."""
    data = request.get_json() or {}
    if not isinstance(data, dict):
        return APIResponse.validation_error("No JSON data provided")

    community = str(data.get("community", "")).strip()
    if not community:
        return APIResponse.validation_error("community must be a non-empty string")

    enabled = bool(data.get("enabled", True))
    config = ZenodoConfigService.save_community_override_config(
        {
            "enabled": enabled,
            "community": community,
        }
    )
    logger.info("Admin updated Zenodo community override config")
    return APIResponse.success(message="Zenodo community override updated", data={"config": config})


@admin_bp.route("/version-detection-config", methods=["GET"])
@jwt_required()
@require_admin
def get_version_detection_config():
    config = VersionDetectionPolicyService.get_config()
    return APIResponse.success(data={"config": config})


@admin_bp.route("/version-detection-config", methods=["POST"])
@jwt_required()
@require_admin
def update_version_detection_config():
    data = request.get_json() or {}
    if not isinstance(data, dict):
        return APIResponse.validation_error("No JSON data provided")

    config = VersionDetectionPolicyService.save_config(data)
    logger.info("Admin updated version detection policy config")
    return APIResponse.success(message="Version detection policy updated", data={"config": config})


@admin_bp.route("/pipelines/<pipeline_id>/config", methods=["GET"])
@jwt_required()
@require_admin
def get_pipeline_config(pipeline_id):
    """Get configuration for a specific pipeline (admin only)"""
    pipeline = current_app.native_pipeline_service.get_pipeline(pipeline_id)
    config_data = pipeline.get("config", {})
    return APIResponse.success(data={"config": config_data})


@admin_bp.route("/pipelines/<pipeline_id>/config", methods=["POST"])
@jwt_required()
@require_admin
def update_pipeline_config(pipeline_id):
    """Update configuration for a specific pipeline (admin only)"""
    data = request.get_json()
    if data is None:
        return APIResponse.validation_error("No JSON data provided")

    # Normalize renderer engine for environments that use Blender < 4.x.
    if isinstance(data, dict):
        steps = data.get("steps")
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, dict) or step.get("id") != "fast_renderer":
                    continue
                params = step.get("parameters")
                if not isinstance(params, dict):
                    continue
                engine = params.get("engine")
                if isinstance(engine, str) and engine.strip().upper() == "BLENDER_EEVEE_NEXT":
                    params["engine"] = "CYCLES"
                    logger.info("Normalized fast_renderer engine BLENDER_EEVEE_NEXT -> CYCLES")

    user_id = get_jwt_identity()
    current_app.native_pipeline_service.create_pipeline_version_from_config(
        pipeline_id,
        data,
        activate=True,
        created_by_user_id=int(user_id) if user_id else None,
        mirror_legacy_config=True,
    )
    logger.info(f"Admin updated config for pipeline {pipeline_id}")
    return APIResponse.success(message="Configuration updated successfully", data={"config": data})


@admin_bp.route("/pipelines/render/status", methods=["GET"])
@jwt_required()
@require_admin
def get_renderer_status():
    """Check status of the Fast Renderer service (admin only)"""
    from flask import current_app
    from services.hdp_component_policy import hpc_required_message, local_hdp_component_execution_allowed

    disabled_by_config = not current_app.config.get("ENABLE_RENDERER", True)
    if not local_hdp_component_execution_allowed(current_app):
        return APIResponse.success(data={
            "reachable": False,
            "service_url": None,
            "disabled_by_config": disabled_by_config,
            "hpc_required": True,
            "local_execution_allowed": False,
            "message": hpc_required_message("fast_renderer"),
        })

    fast_renderer = current_app.fast_renderer_service
    is_reachable = fast_renderer.check_health()

    # Check if disabled by config
    return APIResponse.success(data={
        "reachable": is_reachable,
        "service_url": fast_renderer.service_url,
        "disabled_by_config": disabled_by_config,
        "hpc_required": False,
        "local_execution_allowed": True,
    })


@admin_bp.route("/pipelines/render/test", methods=["POST"])
@jwt_required()
@require_admin
def test_renderer():
    """Trigger a test render via Admin API (admin only)"""
    # Reuse the logic from setup_routes but secured for admin context
    # We call the same internal logic or just reuse the code pattern
    from flask import current_app
    import shutil
    import os
    from services.hdp_component_policy import hpc_required_message, local_hdp_component_execution_allowed

    if not local_hdp_component_execution_allowed(current_app):
        return APIResponse.validation_error(
            hpc_required_message("fast_renderer"),
            details={"hpc_required": True, "local_execution_allowed": False},
        )

    fast_renderer = current_app.fast_renderer_service
    session_manager = current_app.session_manager

    # 1. Create temp session
    # Use session manager to get valid paths
    hdpc_path, data_out_path, uploads_path, session_dir = session_manager.create_session_dirs()

    # 2. Locate test model
    app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    source_model_path = os.path.join(app_root, "test_model.glb")

    if not os.path.exists(source_model_path):
            # Try alternate location if app_root varies
            source_model_path = "/app/test_model.glb" # Docker fallback
            if not os.path.exists(source_model_path):
                return APIResponse.server_error("Test model not found on server")

    # 3. Copy
    target_model_path = os.path.join(uploads_path, "test_model.glb")
    shutil.copy(source_model_path, target_model_path)

    # 4. Render
    from constants import PIPELINE_DEFINITION
    step_config = next((s for s in PIPELINE_DEFINITION["steps"] if s["id"] == "fast_renderer"), {})
    options = step_config.get("parameters", {}).copy()
    options["resolution"] = 256 # Low res for speed

    result = fast_renderer.render(target_model_path, data_out_path, options=options)

    if not result.get("success") or result.get("success_count", 0) == 0:
        error_msg = result.get("error") or "No models were successfully rendered."
        return APIResponse.server_error(f"Render failed: {error_msg}", details=result)

    return APIResponse.success(message="Test render successful", data=result)


@admin_bp.route("/pipelines/converter/test", methods=["POST"])
@jwt_required()
@require_admin
def test_converter():
    """Trigger a test conversion via Admin API (admin only)"""
    from flask import current_app
    import shutil
    import os
    from services.hdp_component_policy import hpc_required_message, local_hdp_component_execution_allowed

    if not local_hdp_component_execution_allowed(current_app):
        return APIResponse.validation_error(
            hpc_required_message("any_to_usdz"),
            details={"hpc_required": True, "local_execution_allowed": False},
        )

    any_to_usdz_service = current_app.any_to_usdz_service
    session_manager = current_app.session_manager

    # 1. Create temp session
    # Use session manager to get valid paths
    hdpc_path, data_out_path, uploads_path, session_dir = session_manager.create_session_dirs()

    # 2. Identify source model
    # Support selecting a specific file type or test set
    options = request.get_json() or {}
    test_file = options.get("test_file", "test_model.glb") # Default to GLB

    app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Check standard location first, then model_one if requested
    source_path = None

    copied_assets = []

    # If testing OBJ/model_one explicitly
    if "model_one" in test_file or test_file.endswith(".obj"):
            # Look for model_one directory in project root
            possible_model_one = os.path.join(app_root, "model_one")
            if os.path.exists(possible_model_one) and os.path.isdir(possible_model_one):
                # Copy the entire directory content to uploads
                # We want the files directly in uploads, or in a subfolder?
                # Pipeline usually expects files in uploads path.
                # Let's copy the contents of model_one to uploads_path
                for item in os.listdir(possible_model_one):
                    s = os.path.join(possible_model_one, item)
                    d = os.path.join(uploads_path, item)
                    if os.path.isdir(s):
                        shutil.copytree(s, d, dirs_exist_ok=True)
                    else:
                        shutil.copy2(s, d)
                    copied_assets.append(item)

                # Set the target model path (OBJ file)
                target_model_path = os.path.join(uploads_path, "test_model.obj")
                if not os.path.exists(target_model_path):
                    return APIResponse.server_error(f"test_model.obj not found in model_one")
            else:
                # Fallback/Error if model_one not found
                return APIResponse.server_error("model_one directory not found on server")

    else:
        # Default single GLB file logic
        source_model_path = os.path.join(app_root, test_file)
        if not os.path.exists(source_model_path):
                # Try docker fallback
                source_model_path = f"/app/{test_file}"
                if not os.path.exists(source_model_path):
                    return APIResponse.server_error(f"Test model {test_file} not found")

        # Copy the primary test file and likely sidecar files (textures, .mtl, .bin).
        source_dir = os.path.dirname(source_model_path)
        source_stem = os.path.splitext(os.path.basename(source_model_path))[0]
        source_name = os.path.basename(source_model_path)
        sidecar_exts = {
            ".mtl",
            ".bin",
            ".png",
            ".jpg",
            ".jpeg",
            ".tga",
            ".bmp",
            ".webp",
            ".ktx2",
            ".dds",
            ".tif",
            ".tiff",
            ".exr",
        }
        for item in os.listdir(source_dir):
            item_path = os.path.join(source_dir, item)
            if not os.path.isfile(item_path):
                continue
            item_stem, item_ext = os.path.splitext(item)
            if item == source_name or item_stem == source_stem or item_ext.lower() in sidecar_exts:
                shutil.copy2(item_path, os.path.join(uploads_path, item))
                copied_assets.append(item)

        target_model_path = os.path.join(uploads_path, source_name)

    # 4. Convert
    # Options are passed through
    result = any_to_usdz_service.convert(target_model_path, data_out_path, options=options)

    if not result.get("success"):
        logger.error("Converter test failed for %s: %s", test_file, result)
        return APIResponse.server_error(
            f"Conversion failed: {result.get('error')}",
            details={"result": result, "copied_assets": copied_assets},
        )

    result["copied_assets"] = copied_assets
    return APIResponse.success(message=f"Test conversion successful for {test_file}", data=result)

@admin_bp.route("/edm-config", methods=["GET"])
@jwt_required()
@require_admin
def get_edm_config():
    """Get EDM mapping configuration (admin only)"""
    from flask import current_app
    config = current_app.edm_service.get_full_configuration()
    return APIResponse.success(data={"config": config})


@admin_bp.route("/edm-validator/status", methods=["GET"])
@jwt_required()
@require_admin
def get_edm_validator_status():
    """Return local EDM validator configuration and reachability."""
    enabled = current_app.config.get(
        "ENABLE_LOCAL_EDM_VALIDATION",
        current_app.config.get("ENABLE_METIS_VALIDATION", True),
    )
    client = LocalEdmValidatorClient()
    required = bool(current_app.config.get("LOCAL_EDM_VALIDATOR_REQUIRED", True))
    health = client.check_health()
    info = client.get_info()
    return APIResponse.success(
        data={
            "enabled": bool(enabled),
            "required": required,
            "active": bool(enabled or required),
            "url": client.base_url,
            "continue_on_error": bool(current_app.config.get("LOCAL_EDM_VALIDATOR_CONTINUE_ON_ERROR", True)),
            "health": health,
            "info": info,
        }
    )


@admin_bp.route("/edm-config", methods=["POST"])
@jwt_required()
@require_admin
def update_edm_config():
    """Update EDM mapping configuration (admin only)"""
    from flask import current_app
    data = request.get_json()
    if data is None:
        return APIResponse.validation_error("No JSON data provided")

    # Expecting 'types' and 'licenses' keys, but we just save what we get generally
    # Maybe some validation?

    current_app.edm_service.save_configuration(data)
    logger.info(f"Admin updated EDM config")
    return APIResponse.success(message="EDM configuration updated successfully", data={"config": data})


@admin_bp.route("/storage-config", methods=["GET"])
@jwt_required()
@require_admin
def get_storage_config():
    """Get cloud storage configuration (admin only)"""
    from services.cloud_upload_service import CloudUploadService

    config = CloudUploadService.get_storage_config()
    return APIResponse.success(data={"config": config})


@admin_bp.route("/storage-config", methods=["POST"])
@jwt_required()
@require_admin
def update_storage_config():
    """Update cloud storage configuration (admin only)"""
    from services.cloud_upload_service import (
        CloudUploadService,
        STORAGE_DROPBOX,
        STORAGE_GDRIVE,
        STORAGE_MODE_LOCAL,
        STORAGE_MODE_PURE_CLOUD,
        STORAGE_MODE_CLOUD_BACKUP,
        STORAGE_MODE_SERVER_ONLY
    )
    from services.hdp_component_policy import (
        DEPLOYMENT_CLASS_WORKSTATION_LOCAL,
        webhdp_deployment_class,
    )

    data = request.get_json()
    if data is None:
        return APIResponse.validation_error("No JSON data provided")

    # Validate storage types
    valid_storages = {STORAGE_DROPBOX, STORAGE_GDRIVE}
    valid_modes = {STORAGE_MODE_PURE_CLOUD, STORAGE_MODE_CLOUD_BACKUP, STORAGE_MODE_SERVER_ONLY}
    if webhdp_deployment_class(current_app) == DEPLOYMENT_CLASS_WORKSTATION_LOCAL:
        valid_modes.add(STORAGE_MODE_LOCAL)

    primary = data.get("primary_storage")
    secondary = data.get("secondary_storage")
    storage_mode = data.get("storage_mode")

    if primary and primary not in valid_storages:
        return APIResponse.validation_error(f"Invalid primary_storage: {primary}")
    if secondary and secondary not in valid_storages:
        return APIResponse.validation_error(f"Invalid secondary_storage: {secondary}")
    if storage_mode and storage_mode not in valid_modes:
        return APIResponse.validation_error(f"Invalid storage_mode: {storage_mode}. Valid modes: {list(valid_modes)}")

    # Build config with defaults for missing fields
    current_config = CloudUploadService.get_storage_config()
    new_config = {
        "primary_storage": data.get("primary_storage", current_config.get("primary_storage")),
        "secondary_storage": data.get("secondary_storage", current_config.get("secondary_storage")),
        "allow_server_fallback": data.get("allow_server_fallback", current_config.get("allow_server_fallback", False)),
        "storage_mode": data.get("storage_mode", current_config.get("storage_mode", STORAGE_MODE_PURE_CLOUD))
    }

    CloudUploadService.save_storage_config(new_config)
    logger.info(f"Admin updated storage config: {new_config}")
    return APIResponse.success(message="Storage configuration updated successfully", data={"config": new_config})


@admin_bp.route("/mfa-config", methods=["GET"])
@jwt_required()
@require_admin
def get_mfa_config():
    """Get login MFA provider bypass configuration (admin only)"""
    return APIResponse.success(data={"config": get_mfa_provider_bypass_config()})


@admin_bp.route("/mfa-config", methods=["POST"])
@jwt_required()
@require_admin
def update_mfa_config():
    """Update login MFA provider bypass configuration (admin only)"""
    data = request.get_json()
    if data is None:
        return APIResponse.validation_error("No JSON data provided")

    current_config = get_mfa_provider_bypass_config()
    enabled = data.get("enabled", current_config.get("enabled", False))
    if not isinstance(enabled, bool):
        return APIResponse.validation_error("enabled must be true or false")

    try:
        new_config = save_mfa_provider_bypass_config(
            {
                "enabled": enabled,
                "domains": data.get("domains", current_config.get("domains", [])),
            }
        )
    except ValueError as exc:
        return APIResponse.validation_error(str(exc))

    actor_user_id = int(get_jwt_identity())
    record_audit_event(
        actor_user_id=actor_user_id,
        event_type="admin.mfa_provider_bypass_updated",
        entity_type="system_config",
        entity_id="mfa_provider_bypass",
        details={"enabled": new_config["enabled"], "domains": new_config["domains"]},
    )
    db.session.commit()
    logger.info("Admin updated login MFA provider bypass config: %s", new_config)
    return APIResponse.success(message="MFA configuration updated successfully", data={"config": new_config})


@admin_bp.route("/modality-config", methods=["GET"])
@jwt_required()
@require_admin
def get_modality_config():
    """Get modality detection configuration (admin only)"""
    from flask import current_app
    config = current_app.edm_service.get_full_modality_configuration()
    return APIResponse.success(data={"config": config})


@admin_bp.route("/modality-config", methods=["POST"])
@jwt_required()
@require_admin
def update_modality_config():
    """Update modality detection configuration (admin only)"""
    from flask import current_app
    data = request.get_json()
    if data is None:
        return APIResponse.validation_error("No JSON data provided")

    current_app.edm_service.save_modality_configuration(data)
    logger.info(f"Admin updated modality detection config")
    return APIResponse.success(message="Modality configuration updated successfully", data={"config": data})
@admin_bp.route("/modality-config", methods=["DELETE"])
@jwt_required()
@require_admin
def reset_modality_config():
    """Reset modality detection configuration to defaults (admin only)"""
    from flask import current_app
    current_app.edm_service.reset_modality_configuration()
    logger.info(f"Admin reset modality detection config to defaults")
    return APIResponse.success(message="Modality configuration reset to defaults")


@admin_bp.route("/storage-status", methods=["GET"])
@jwt_required()
def get_storage_status():
    """Get current cloud storage availability status for authenticated users."""
    from routes.access_helpers import get_current_user_from_jwt
    from services.cloud_upload_service import CloudUploadService, STORAGE_MODE_LOCAL, STORAGE_MODE_SERVER_ONLY, STORAGE_SERVER
    from services.session_access_service import can_use_mounted_inputs

    dropbox_available, dropbox_msg = CloudUploadService.check_dropbox_available()
    gdrive_available, gdrive_msg = CloudUploadService.check_gdrive_available()
    active_storage, active_msg = CloudUploadService.get_available_storage()
    config = CloudUploadService.get_storage_config()

    # Ensure the reported mode reflects environment overrides
    config["storage_mode"] = CloudUploadService.get_storage_mode()
    if config["storage_mode"] == STORAGE_MODE_LOCAL and not can_use_mounted_inputs(get_current_user_from_jwt()):
        config["storage_mode"] = STORAGE_MODE_SERVER_ONLY
        active_storage, active_msg = STORAGE_SERVER, "Server storage is available"

    return APIResponse.success(data={
        "config": config,
        "active_storage": active_storage,
        "active_message": active_msg,
        "services": {
            "dropbox": {
                "available": dropbox_available,
                "message": dropbox_msg
            },
            "gdrive": {
                "available": gdrive_available,
                "message": gdrive_msg
            }
        }
    })


@admin_bp.route("/projects/media", methods=["GET"])
@jwt_required()
@require_admin
def get_media():
    """Serve a media file by path (admin only, for previews)"""
    path = request.args.get("path")
    if not path:
        return APIResponse.validation_error("No path provided")

    logger.info(f"Admin media request for path: {path}")

    resolved_path = Path(path).expanduser().resolve(strict=False)
    allowed_roots = [
        os.environ.get("SHARED_SESSION_PATH"),
        os.environ.get("WEBHDP_SESSIONS_PATH"),
        current_app.config.get("UPLOAD_FOLDER"),
        tempfile.gettempdir(),
    ]
    allowed_roots = [Path(root).expanduser().resolve(strict=False) for root in allowed_roots if root]
    if not any(path_is_within(root, resolved_path) for root in allowed_roots):
        return APIResponse.forbidden("Media path is outside allowed preview directories")

    if not resolved_path.exists() or not resolved_path.is_file():
        logger.warning(f"Media file not found at: {path}")
        return APIResponse.error("File not found", 404)

    try:
        from flask import send_file
        return send_file(resolved_path)
    except Exception as e:
        logger.error(f"Failed to serve media {path}: {e}")
        raise AppException(f"Failed to serve media: {str(e)}")


@admin_bp.route("/version", methods=["GET"])
@jwt_required()
@require_admin
def get_version():
    """Get the current application version and timestamp (admin only)"""
    version_file = Path(__file__).resolve().parent.parent / "version.json"

    if not version_file.exists():
        return APIResponse.success(data={"version": "unknown", "timestamp": "unknown"})

    try:
        with open(version_file, "r") as f:
            version_data = json.load(f)
        return APIResponse.success(data=version_data)
    except Exception as e:
        logger.error(f"Error reading version file: {e}")
        return APIResponse.success(data={"version": "error", "timestamp": "error"})
