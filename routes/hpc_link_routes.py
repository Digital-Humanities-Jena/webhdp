"""WebHDP-facing HPC-Link allocation endpoints."""

from __future__ import annotations

import re
from flask import Blueprint, current_app, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from api_utils import APIResponse
from database.database import db
from database.models import CloudMirrorObject, Session, User, UserRole
from exceptions import APIConnectionError, APITimeoutError, SecurityError, ValidationError
from services.cloud_upload_service import read_stream_receipt
from services.hdp_component_policy import (
    component_runtime_report,
    webhdp_deployment_class,
    webhdp_deployment_label,
)
from services.hpc_reservation_service import HpcReservationService
from services.hpc_allocation_service import MAX_SESSION_ID, parse_allocation_integer, validate_allocation_purpose
from services.session_access_service import can_view_session

hpc_link_bp = Blueprint("hpc_link", __name__)

USER_ALLOCATION_FIELDS = (
    "allocation_id", "reservation_id", "session_id", "purpose", "status", "can_release", "requested_partition", "requested_gpu_type",
    "requested_gpu_count", "requested_duration_minutes", "node_name", "scheduler_state", "requested_at", "allocated_at",
    "expires_at", "released_at", "awaiting_confirmation",
)
SCHEDULER_REASONS = {"Resources", "Priority", "ReqNodeNotAvail", "QOSMaxGRESPerUser", "AssocMaxJobsLimit"}
COMPONENT_TOKEN = re.compile(r"[A-Za-z0-9_.-]{1,120}")


def _visible_allocation(data, user):
    if user.role == UserRole.ADMIN:
        return data
    visible = {key: data.get(key) for key in USER_ALLOCATION_FIELDS}
    if data.get("scheduler_reason") in SCHEDULER_REASONS:
        visible["scheduler_reason"] = data["scheduler_reason"]
    if data.get("last_error"):
        visible["last_error"] = {
            "allocating": "Waiting for HPC-Link to confirm this allocation.",
            "failed": "HPC-Link could not complete this request.",
            "cancelled": "The HPC request was cancelled.",
            "expired": "The HPC request has expired.",
        }.get(data.get("status"), "HPC-Link could not confirm the latest update.")
    return visible


def _object_payload():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValidationError("Expected a JSON object for this HPC operation.")
    return payload


def visible_cloud_staging(result, user):
    if user.role == UserRole.ADMIN:
        return result
    return {"staged_files": [{key: row[key] for key in ("name", "size_bytes") if key in row}
                             for row in result.get("staged_files", [])]}


@hpc_link_bp.after_request
def _keep_allocation_status_private(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


@hpc_link_bp.errorhandler(APIConnectionError)
@hpc_link_bp.errorhandler(APITimeoutError)
def _public_gateway_failure(error):
    actor = _current_user()
    if actor.role == UserRole.ADMIN:
        return APIResponse.error(error.error_code, error.message, error.status_code, error.details)
    return APIResponse.error(error.error_code, "HPC-Link could not complete this operation. Try again shortly.", error.status_code)


def _current_user() -> User:
    user = db.session.get(User, int(get_jwt_identity()))
    if user is None:
        from exceptions import ResourceNotFoundError

        raise ResourceNotFoundError("User not found")
    return user


@hpc_link_bp.route("/status", methods=["GET"])
@jwt_required()
def get_hpc_link_status():
    service = current_app.hpc_allocation_service
    user = _current_user()
    config = service.get_or_create_config()
    purpose = validate_allocation_purpose(str(request.args.get("purpose") or "workflow").strip().lower())
    session_id = request.args.get("session_id")
    allocation_state = {"active_hpc_allocation": False, "active_hpc_gpu_count": None, "gpu_allocation_status": None,
                        "gpu_allocation_id": None, "gpu_allocation_gpu_count": None,
                        "gpu_allocation_scheduler_reason": None}
    if session_id not in (None, ""):
        try:
            session = db.session.get(Session, parse_allocation_integer(session_id, name="Session ID", minimum=1, maximum=MAX_SESSION_ID))
            if session and can_view_session(session, user):
                allocation_state = service.session_allocation_status(session.id, user, purpose)
        except ValidationError:
            pass
    available = bool(config.enabled and config.base_url)
    can_allocate = service.user_can_allocate(user, purpose=purpose)
    config_summary = service.serialize_config(config) if user.role == UserRole.ADMIN else {
        "default_gpu_count": config.default_gpu_count,
        "default_duration_minutes": config.default_duration_minutes,
    }
    if user.role != UserRole.ADMIN and allocation_state["gpu_allocation_scheduler_reason"] not in SCHEDULER_REASONS:
        allocation_state["gpu_allocation_scheduler_reason"] = None
    payload = {
        "configured": bool(config.base_url),
        "enabled": bool(config.enabled),
        "available": available,
        "require_for_components": bool(config.require_for_components),
        "can_allocate": can_allocate,
        **allocation_state,
        "permission_reason": None,
        "config": config_summary,
        "quota": service.allocation_quota(user, config),
        "deployment_class": webhdp_deployment_class(current_app),
        "deployment_label": webhdp_deployment_label(current_app),
        "component_runtime": component_runtime_report(
            current_app,
            active_hpc_allocation=allocation_state["active_hpc_allocation"],
            hpc_link_available=available,
            can_allocate_hpc=can_allocate,
        ),
    }
    if not payload["can_allocate"]:
        payload["permission_reason"] = (
            "Verified account and hpc_link_access capability required"
            if user.role.value != "admin"
            else None
        )
    return APIResponse.success(data=payload)


@hpc_link_bp.route("/reservations", methods=["GET"])
@jwt_required()
def list_gpu_reservations():
    purpose = request.args.get("purpose", "workflow")
    if purpose not in ("workflow", "playground"):
        raise ValidationError("Select workflow or playground as the reservation purpose")
    user = _current_user()
    service = HpcReservationService(current_app.hpc_allocation_service)
    rows = service.list(user=user)
    for row in rows:
        if row.get("allocation"):
            row["allocation"] = _visible_allocation(row["allocation"], user)
    return APIResponse.success(data={"reservations": rows})


@hpc_link_bp.route("/reservations/<reservation_id>/claim", methods=["POST"])
@jwt_required()
def claim_gpu_reservation(reservation_id):
    payload = _object_payload()
    user = _current_user()
    service = HpcReservationService(current_app.hpc_allocation_service)
    return APIResponse.success(data={"allocation": _visible_allocation(service.claim(reservation_id, user, payload), user)})


@hpc_link_bp.route("/allocations", methods=["GET"])
@jwt_required()
def list_my_hpc_allocations():
    """List this account's current requests without polling or starting new work."""
    user = _current_user()
    service = current_app.hpc_allocation_service
    return APIResponse.success(data={
        "allocations": [_visible_allocation(row, user) for row in service.list_user_allocations(user)],
    })


@hpc_link_bp.route("/allocations", methods=["POST"])
@jwt_required()
def request_hpc_allocation():
    data = _object_payload()
    user = _current_user()
    purpose = validate_allocation_purpose(str(data.get("purpose", "workflow")).strip().lower())
    session_id = data.get("session_id")
    allocation = current_app.hpc_allocation_service.request_allocation(
        user=user,
        session_id=parse_allocation_integer(session_id, name="Session ID", minimum=1, maximum=MAX_SESSION_ID) if session_id not in (None, "") else None,
        purpose=purpose,
        payload=data,
    )
    return APIResponse.accepted(data={"allocation": _visible_allocation(allocation, user)}, message="HPC-Link allocation requested")


@hpc_link_bp.route("/allocations/<allocation_id>", methods=["GET"])
@jwt_required()
def get_hpc_allocation(allocation_id):
    service = current_app.hpc_allocation_service
    user = _current_user()
    allocation = service.get_allocation(allocation_id, user)
    payload = service.poll_allocation(allocation)
    return APIResponse.success(data={"allocation": _visible_allocation(payload, user)})


@hpc_link_bp.route("/allocations/<allocation_id>/preflight", methods=["POST"])
@jwt_required()
def preflight_hpc_allocation(allocation_id):
    service = current_app.hpc_allocation_service
    user = _current_user()
    allocation = service.get_allocation_for_compute(allocation_id, user)
    data = _object_payload()
    components = data.get("components", [])
    if (not isinstance(components, list) or len(components) > 50 or any(
            not isinstance(key, str) or not COMPONENT_TOKEN.fullmatch(key) for key in components)):
        raise ValidationError("Provide at most 50 valid component names for preflight.")
    result = service.preflight(allocation, list(dict.fromkeys(components)))
    if user.role != UserRole.ADMIN:
        checks = result.get("checks") or {}
        result = {"success": result.get("success") is True,
                  "checks": {key: {"success": bool(check.get("success"))} for key, check in checks.items()}}
    return APIResponse.success(data={"allocation": _visible_allocation(service.serialize_allocation(allocation), user), "preflight": result})


@hpc_link_bp.route("/allocations/<allocation_id>/stage/cloud", methods=["POST"])
@jwt_required()
def stage_hpc_cloud_files(allocation_id):
    service = current_app.hpc_allocation_service
    user = _current_user()
    if user.role != UserRole.ADMIN:
        raise SecurityError("Stage cloud files using a receipt from your own WebHDP upload.")
    allocation = service.get_allocation_for_compute(allocation_id, user)
    data = request.get_json() or {}
    files = data.get("files") if isinstance(data.get("files"), list) else []
    result = service.stage_cloud_files(allocation, files)
    return APIResponse.success(data={"allocation": service.serialize_allocation(allocation), "staging": result})


@hpc_link_bp.route("/allocations/<allocation_id>/stage/cloud-references", methods=["POST"])
@jwt_required()
def stage_hpc_cloud_references(allocation_id):
    service = current_app.hpc_allocation_service
    user = _current_user()
    allocation = service.get_allocation_for_compute(allocation_id, user)
    data = _object_payload()
    files = data.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= 100:
        raise ValidationError("Provide between 1 and 100 cloud upload receipts.")
    authorized = []
    for item in files:
        if not isinstance(item, dict):
            raise ValidationError('Each cloud reference must be an object')
        if item.get('cloud_upload_receipt'):
            reference = read_stream_receipt(item['cloud_upload_receipt'], user.id)
            path, provider, name = reference['path'], reference['provider'], reference['name']
        elif user.role == UserRole.ADMIN and allocation.session_id:
            path = str(item.get('cloud_path') or item.get('cloud_path_or_id') or item.get('file_id') or item.get('remote_path') or '').strip()
            provider = str(item.get('storage_type') or item.get('provider') or '').strip().lower()
            mirror = CloudMirrorObject.query.filter_by(session_id=allocation.session_id, cloud_path=path,
                                                        storage_provider=provider, status='available').first()
            if not mirror or not path or path.startswith(('http:', 'https:')):
                raise SecurityError('This cloud object is not recorded for the allocation upload session')
            name = mirror.original_filename
        else:
            raise SecurityError('A cloud upload receipt from your account is required')
        authorized.append({'cloud_path': path, 'storage_type': provider, 'name': name,
                           'relative_dir': item.get('relative_dir')})
    result = service.stage_cloud_references(allocation, authorized)
    return APIResponse.success(data={"allocation": _visible_allocation(service.serialize_allocation(allocation), user),
                                     "staging": visible_cloud_staging(result, user)})


@hpc_link_bp.route("/allocations/<allocation_id>/zenodo/upload-draft", methods=["POST"])
@jwt_required()
def upload_hpc_zenodo_draft(allocation_id):
    service = current_app.hpc_allocation_service
    user = _current_user()
    if user.role != UserRole.ADMIN:
        raise SecurityError("Use the WebHDP publishing workflow to prepare a Zenodo draft.")
    allocation = service.get_allocation_for_compute(allocation_id, user)
    data = request.get_json() or {}
    result = service.upload_zenodo_draft(allocation, data)
    return APIResponse.accepted(data={"allocation": service.serialize_allocation(allocation), "zenodo": result})


@hpc_link_bp.route("/allocations/<allocation_id>/release", methods=["POST"])
@jwt_required()
def release_hpc_allocation(allocation_id):
    service = current_app.hpc_allocation_service
    user = _current_user()
    allocation = service.get_allocation(allocation_id, user)
    result = service.release(allocation, protect_running=user.role != UserRole.ADMIN)
    result["allocation"] = _visible_allocation(result["allocation"], user)
    if user.role != UserRole.ADMIN:
        result["remote"] = {key: result["remote"][key] for key in ("cancelled", "detached") if key in result["remote"]}
    return APIResponse.success(data=result, message="HPC-Link allocation released")
