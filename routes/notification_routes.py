from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from api_utils import APIResponse
from routes.access_helpers import get_current_user_from_jwt
from services.notification_service import (
    get_preferences,
    list_notifications,
    mark_all_read,
    mark_read,
    notification_runtime_config,
    serialize_notification,
    unread_count,
    update_preferences,
)


notifications_bp = Blueprint("notifications", __name__)


def _require_current_user():
    user = get_current_user_from_jwt()
    if not user:
        return None, APIResponse.unauthorized()
    return user, None


@notifications_bp.route("", methods=["GET"], strict_slashes=False)
@jwt_required()
def notifications_collection():
    user, error_response = _require_current_user()
    if error_response:
        return error_response
    return APIResponse.success(
        data=list_notifications(
            user_id=user.id,
            state=request.args.get("state") or "all",
            limit=request.args.get("limit") or 20,
            category=request.args.get("category"),
        )
    )


@notifications_bp.route("/unread-count", methods=["GET"])
@jwt_required()
def get_unread_count():
    user, error_response = _require_current_user()
    if error_response:
        return error_response
    return APIResponse.success(data={"unread_count": unread_count(user_id=user.id)})


@notifications_bp.route("/client-config", methods=["GET"])
@jwt_required()
def get_notification_client_config():
    user, error_response = _require_current_user()
    if error_response:
        return error_response
    return APIResponse.success(data=notification_runtime_config())


@notifications_bp.route("/preferences", methods=["GET"])
@jwt_required()
def get_notification_preferences():
    user, error_response = _require_current_user()
    if error_response:
        return error_response
    return APIResponse.success(data=get_preferences(user_id=user.id))


@notifications_bp.route("/preferences", methods=["PUT"])
@jwt_required()
def update_notification_preferences():
    user, error_response = _require_current_user()
    if error_response:
        return error_response
    payload = request.get_json() or {}
    return APIResponse.success(data=update_preferences(user_id=user.id, preferences=payload.get("preferences") or []))


@notifications_bp.route("/<int:notification_id>", methods=["PATCH"])
@jwt_required()
def update_notification(notification_id):
    user, error_response = _require_current_user()
    if error_response:
        return error_response
    payload = request.get_json() or {}
    notification = mark_read(
        notification_id=notification_id,
        user_id=user.id,
        read=payload.get("read") if "read" in payload else None,
        archived=payload.get("archived") if "archived" in payload else None,
    )
    return APIResponse.success(data={"notification": serialize_notification(notification)})


@notifications_bp.route("/read-all", methods=["POST"])
@jwt_required()
def read_all_notifications():
    user, error_response = _require_current_user()
    if error_response:
        return error_response
    updated_count = mark_all_read(user_id=user.id)
    return APIResponse.success(data={"updated_count": updated_count, "unread_count": unread_count(user_id=user.id)})
