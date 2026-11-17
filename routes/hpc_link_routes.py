"""WebHDP-facing HPC-Link allocation endpoints."""

from __future__ import annotations

from flask import Blueprint, current_app, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from api_utils import APIResponse
from database.database import db
from database.models import Session, User
from exceptions import ValidationError
from services.hdp_component_policy import (
    component_runtime_report,
    webhdp_deployment_class,
    webhdp_deployment_label,
)
from services.hpc_reservation_service import HpcReservationService
from services.session_access_service import can_view_session

hpc_link_bp = Blueprint("hpc_link", __name__)


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
    purpose = str(request.args.get("purpose") or "workflow").strip().lower()
    session_id = request.args.get("session_id")
    active_hpc_allocation = False
    if session_id not in (None, ""):
        try:
            session = db.session.get(Session, int(session_id))
            active_hpc_allocation = bool(session and can_view_session(session, user)
                                         and service.get_active_for_session(session.id, user_id=user.id))
        except (TypeError, ValueError):
            active_hpc_allocation = False
    available = bool(config.enabled and config.base_url)
    can_allocate = service.user_can_allocate(user, purpose=purpose)
    payload = {
        "configured": bool(config.base_url),
        "enabled": bool(config.enabled),
        "available": available,
        "require_for_components": bool(config.require_for_components),
        "can_allocate": can_allocate,
        "active_hpc_allocation": active_hpc_allocation,
        "permission_reason": None,
        "config": service.serialize_config(config),
        "deployment_class": webhdp_deployment_class(current_app),
        "deployment_label": webhdp_deployment_label(current_app),
        "component_runtime": component_runtime_report(
            current_app,
            active_hpc_allocation=active_hpc_allocation,
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
    service = HpcReservationService(current_app.hpc_allocation_service)
    return APIResponse.success(data={"reservations": service.list(user=_current_user())})


@hpc_link_bp.route("/reservations/<reservation_id>/claim", methods=["POST"])
@jwt_required()
def claim_gpu_reservation(reservation_id):
    payload = request.get_json()
    if not isinstance(payload, dict):
        raise ValidationError("Expected a GPU claim object")
    service = HpcReservationService(current_app.hpc_allocation_service)
    return APIResponse.success(data={"allocation": service.claim(reservation_id, _current_user(), payload)})


@hpc_link_bp.route("/allocations", methods=["POST"])
@jwt_required()
def request_hpc_allocation():
    data = request.get_json() or {}
    user = _current_user()
    purpose = str(data.get("purpose") or "workflow").strip().lower()
    session_id = data.get("session_id")
    allocation = current_app.hpc_allocation_service.request_allocation(
        user=user,
        session_id=int(session_id) if session_id not in (None, "") else None,
        purpose=purpose,
        payload=data,
    )
    return APIResponse.accepted(data={"allocation": allocation}, message="HPC-Link allocation requested")


@hpc_link_bp.route("/allocations/<allocation_id>", methods=["GET"])
@jwt_required()
def get_hpc_allocation(allocation_id):
    service = current_app.hpc_allocation_service
    allocation = service.get_allocation(allocation_id, _current_user())
    payload = service.poll_allocation(allocation)
    return APIResponse.success(data={"allocation": payload})


@hpc_link_bp.route("/allocations/<allocation_id>/preflight", methods=["POST"])
@jwt_required()
def preflight_hpc_allocation(allocation_id):
    service = current_app.hpc_allocation_service
    allocation = service.get_allocation(allocation_id, _current_user())
    data = request.get_json() or {}
    result = service.preflight(allocation, data.get("components") if isinstance(data.get("components"), list) else None)
    return APIResponse.success(data={"allocation": service.serialize_allocation(allocation), "preflight": result})


@hpc_link_bp.route("/allocations/<allocation_id>/stage/cloud", methods=["POST"])
@jwt_required()
def stage_hpc_cloud_files(allocation_id):
    service = current_app.hpc_allocation_service
    allocation = service.get_allocation(allocation_id, _current_user())
    data = request.get_json() or {}
    files = data.get("files") if isinstance(data.get("files"), list) else []
    result = service.stage_cloud_files(allocation, files)
    return APIResponse.success(data={"allocation": service.serialize_allocation(allocation), "staging": result})


@hpc_link_bp.route("/allocations/<allocation_id>/stage/cloud-references", methods=["POST"])
@jwt_required()
def stage_hpc_cloud_references(allocation_id):
    service = current_app.hpc_allocation_service
    allocation = service.get_allocation(allocation_id, _current_user())
    data = request.get_json() or {}
    files = data.get("files") if isinstance(data.get("files"), list) else []
    result = service.stage_cloud_references(allocation, files)
    return APIResponse.success(data={"allocation": service.serialize_allocation(allocation), "staging": result})


@hpc_link_bp.route("/allocations/<allocation_id>/zenodo/upload-draft", methods=["POST"])
@jwt_required()
def upload_hpc_zenodo_draft(allocation_id):
    service = current_app.hpc_allocation_service
    allocation = service.get_allocation(allocation_id, _current_user())
    data = request.get_json() or {}
    result = service.upload_zenodo_draft(allocation, data)
    return APIResponse.accepted(data={"allocation": service.serialize_allocation(allocation), "zenodo": result})


@hpc_link_bp.route("/allocations/<allocation_id>/release", methods=["POST"])
@jwt_required()
def release_hpc_allocation(allocation_id):
    service = current_app.hpc_allocation_service
    allocation = service.get_allocation(allocation_id, _current_user())
    result = service.release(allocation)
    return APIResponse.success(data=result, message="HPC-Link allocation released")
