from flask import Blueprint, current_app, request
from flask_jwt_extended import jwt_required

from api_utils import APIResponse
from exceptions import ValidationError
from routes.access_helpers import get_current_user_from_jwt
from services.institution_invitation_service import InstitutionInvitationService, InvitationRateLimited


institution_invitation_bp = Blueprint("institution_invitations", __name__)
invitation_service = InstitutionInvitationService()


def _payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("Provide a JSON object.")
    return data


@institution_invitation_bp.after_request
def keep_invitation_responses_private(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


@institution_invitation_bp.errorhandler(InvitationRateLimited)
def handle_invitation_rate_limit(error):
    response, status = APIResponse.error(error.error_code, error.message, error.status_code, error.details)
    response.headers["Retry-After"] = str(error.retry_after)
    return response, status


@institution_invitation_bp.get("/<int:institution_id>/invitations")
@jwt_required()
def list_institution_invitations(institution_id):
    try:
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        raise ValidationError("Invitation limits and offsets must be integers.") from None
    if not 1 <= limit <= 100 or not 0 <= offset <= 2_147_483_647:
        raise ValidationError("Provide a limit between 1 and 100 and a non-negative offset.")
    data = invitation_service.list(institution_id, get_current_user_from_jwt(), limit=limit, offset=offset)
    return APIResponse.success(data=data)


@institution_invitation_bp.post("/<int:institution_id>/invitations")
@jwt_required()
def issue_institution_invitation(institution_id):
    data = _payload()
    email_service = getattr(current_app, "email_service", None)
    delivery = getattr(email_service, "send_institution_invitation", None)
    result = invitation_service.issue(
        institution_id,
        get_current_user_from_jwt(),
        email=data.get("email"),
        role=data.get("role"),
        delivery=delivery or (lambda *_: False),
    )
    if result["delivery"] == "failed":
        return APIResponse.success(data=result, message="The invitation was saved. Email delivery failed and can be retried.")
    return APIResponse.success(data=result, message="Invitation emailed.")


@institution_invitation_bp.delete("/<int:institution_id>/invitations/<uuid:invitation_id>")
@jwt_required()
def revoke_institution_invitation(institution_id, invitation_id):
    result = invitation_service.revoke(institution_id, str(invitation_id), get_current_user_from_jwt())
    return APIResponse.success(data={"invitation": result}, message="Invitation revoked.")


@institution_invitation_bp.post("/invitations/preview")
@jwt_required()
def preview_institution_invitation():
    result = invitation_service.preview(_payload().get("token"), get_current_user_from_jwt())
    return APIResponse.success(data=result)


@institution_invitation_bp.post("/invitations/accept")
@jwt_required()
def accept_institution_invitation():
    result = invitation_service.accept(_payload().get("token"), get_current_user_from_jwt())
    return APIResponse.success(data=result, message="Institution invitation accepted.")
