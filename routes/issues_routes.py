import logging

from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from api_utils import APIResponse
from routes.access_helpers import get_current_user_from_jwt
from services.issue_service import (
    INTERNAL_PRIORITY_CHOICES,
    ISSUE_TYPE_CHOICES,
    REPORTER_IMPACT_CHOICES,
    STATUS_CHOICES,
    add_issue_comment,
    create_issue,
    get_application_version_info,
    get_issue_or_404,
    list_assignable_issue_users,
    list_issues,
    list_registry_pages,
    refresh_issue_references,
    serialize_issue,
    serialize_issue_comment,
    update_issue,
)

logger = logging.getLogger(__name__)
issues_bp = Blueprint("issues", __name__)


def _require_current_user():
    user = get_current_user_from_jwt()
    if not user:
        return None, APIResponse.unauthorized()
    return user, None


@issues_bp.route("/registry", methods=["GET"])
@jwt_required()
def get_issue_registry():
    user, error_response = _require_current_user()
    if error_response:
        return error_response
    return APIResponse.success(
        data={
            "pages": list_registry_pages(),
            "assignable_users": list_assignable_issue_users(user),
            "issue_types": list(ISSUE_TYPE_CHOICES),
            "reporter_impacts": list(REPORTER_IMPACT_CHOICES),
            "internal_priorities": list(INTERNAL_PRIORITY_CHOICES),
            "statuses": list(STATUS_CHOICES),
            "app_version": get_application_version_info(),
            "viewer": {
                "id": user.id,
                "role": user.role.value if user.role else "user",
                "groups": list(user.groups or []),
                "capabilities": list(user.capabilities or []),
            },
        }
    )


@issues_bp.route("", methods=["GET", "POST"], strict_slashes=False)
@jwt_required()
def issues_collection():
    user, error_response = _require_current_user()
    if error_response:
        return error_response

    if request.method == "POST":
        payload = request.get_json() or {}
        issue = create_issue(user, payload)
        return APIResponse.created(
            data={"issue": serialize_issue(issue, user, include_comments=True)},
            message="Issue reported successfully",
        )

    payload = list_issues(
        user,
        scope=request.args.get("scope"),
        status=request.args.get("status"),
        page_key=request.args.get("page_key"),
    )
    return APIResponse.success(data=payload)


@issues_bp.route("/<int:issue_id>", methods=["GET", "PATCH"])
@jwt_required()
def issue_detail(issue_id):
    user, error_response = _require_current_user()
    if error_response:
        return error_response

    issue = get_issue_or_404(issue_id, user)

    if request.method == "PATCH":
        payload = request.get_json() or {}
        issue = update_issue(issue, user, payload)
        return APIResponse.success(data={"issue": serialize_issue(issue, user, include_comments=True)}, message="Issue updated")

    return APIResponse.success(data={"issue": serialize_issue(issue, user, include_comments=True)})


@issues_bp.route("/<int:issue_id>/comments", methods=["POST"])
@jwt_required()
def issue_comments(issue_id):
    user, error_response = _require_current_user()
    if error_response:
        return error_response

    issue = get_issue_or_404(issue_id, user)
    payload = request.get_json() or {}
    comment = add_issue_comment(
        issue,
        user,
        body=payload.get("body"),
        is_internal=payload.get("is_internal"),
    )
    return APIResponse.created(
        data={
            "comment": serialize_issue_comment(comment),
            "issue": serialize_issue(issue, user, include_comments=True),
        },
        message="Issue comment added",
    )


@issues_bp.route("/<int:issue_id>/refresh-code-references", methods=["POST"])
@jwt_required()
def refresh_issue_code_references(issue_id):
    user, error_response = _require_current_user()
    if error_response:
        return error_response

    issue = get_issue_or_404(issue_id, user)
    issue = refresh_issue_references(issue, user)
    return APIResponse.success(
        data={"issue": serialize_issue(issue, user, include_comments=True)},
        message="Code references refreshed",
    )
