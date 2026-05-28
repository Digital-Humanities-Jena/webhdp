"""User-facing HPC resources request endpoints."""

from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from api_utils import APIResponse
from database.database import db
from database.models import User
from exceptions import ResourceNotFoundError
from services.hpc_resource_request_service import HpcResourceRequestService, HPC_USE_CASES

hpc_resource_request_bp = Blueprint("hpc_resource_request", __name__)
service = HpcResourceRequestService()


def _current_user() -> User:
    user = db.session.get(User, int(get_jwt_identity()))
    if user is None:
        raise ResourceNotFoundError("User not found")
    return user


@hpc_resource_request_bp.route("/me", methods=["GET"])
@jwt_required()
def get_my_hpc_resource_request_status():
    user = _current_user()
    return APIResponse.success(
        data={
            "profile_defaults": {
                "full_name": user.full_name or "",
                "affiliation": user.affiliation or "",
            },
            "hpc": service.access_summary_for_user(user),
            "use_cases": list(HPC_USE_CASES),
        }
    )


@hpc_resource_request_bp.route("", methods=["POST"])
@jwt_required()
def submit_hpc_resource_request():
    request_row = service.submit_request(user=_current_user(), payload=request.get_json() or {})
    return APIResponse.created(
        data={"request": service.serialize_request(request_row)},
        message="HPC resources request submitted",
    )
