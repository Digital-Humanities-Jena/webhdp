import logging

from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from api_utils import APIResponse
from database.database import db
from database.models import Institution, InstitutionZenodoCommunity, User, UserRole
from exceptions import ResourceNotFoundError, ValidationError
from routes.access_helpers import get_current_user_from_jwt
from services.audit_service import list_audit_events, record_audit_event
from services.institution_service import InstitutionService
from services.zenodo_credential_service import ZenodoCredentialService

logger = logging.getLogger(__name__)
institution_bp = Blueprint("institutions", __name__)
institution_service = InstitutionService()
credential_service = ZenodoCredentialService()


def _serialize_membership(membership):
    payload = membership.to_dict()
    payload["institution"] = membership.institution.to_dict() if getattr(membership, "institution", None) else None
    return payload


def _serialize_institution_summary(
    institution: Institution,
    *,
    membership=None,
    member_count: int | None = None,
) -> dict:
    payload = institution.to_dict()
    payload["member_count"] = int(member_count or 0)
    payload["role"] = membership.role.value if membership and membership.role else None
    return payload


def _parse_positive_int_arg(name: str, default: int) -> int:
    raw_value = request.args.get(name, default)
    try:
        normalized_value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be an integer") from exc
    if normalized_value < 1:
        raise ValidationError(f"{name} must be greater than 0")
    return normalized_value


def _parse_int_value(value, *, field_name: str, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name} must be an integer") from exc


def _can_manage_institution(user: User | None, institution: Institution) -> bool:
    if not user:
        return False
    if user.role == UserRole.ADMIN:
        return True
    membership = institution_service.get_membership(institution.id, user.id)
    return institution_service.has_role(membership, "manager")


def _serialize_institution(
    institution: Institution,
    *,
    include_members=False,
    include_communities=False,
    include_credentials=False,
    memberships=None,
    member_count: int | None = None,
    communities=None,
    community_policy=None,
):
    payload = institution.to_dict()
    membership_rows = memberships
    if include_members and membership_rows is None:
        membership_rows = institution_service.list_members(institution.id)
    payload["memberships"] = [_serialize_membership(row) for row in membership_rows] if include_members and membership_rows else ([] if include_members else None)
    if member_count is not None:
        payload["member_count"] = int(member_count)
    elif membership_rows is not None:
        payload["member_count"] = len(membership_rows)
    else:
        payload["member_count"] = institution_service.list_member_counts([institution.id]).get(institution.id, 0)
    if include_communities:
        community_rows = communities if communities is not None else institution_service.list_communities(institution.id)
        payload["communities"] = [row.to_dict() for row in community_rows]
        payload["community_policy"] = (
            community_policy if community_policy is not None else institution_service.build_community_policy(institution.id)
        )
    if include_credentials:
        payload["zenodo_credentials"] = {
            environment: credential_service.serialize(
                credential_service.get_credential("institution", institution.id, environment)
            )
            for environment in ("sandbox", "production")
        }
    return payload


def _require_admin_user():
    user = get_current_user_from_jwt()
    if not user:
        return None, APIResponse.unauthorized()
    if user.role != UserRole.ADMIN:
        return None, APIResponse.forbidden("Admin access required")
    return user, None


def _require_institution_access(institution_id: int, *, required_role: str = "reader"):
    user = get_current_user_from_jwt()
    if not user:
        return None, None, APIResponse.unauthorized()

    institution = db.session.get(Institution, int(institution_id))
    if not institution:
        return None, user, APIResponse.not_found("Institution not found")

    if user.role == UserRole.ADMIN:
        return institution, user, None

    membership = institution_service.get_membership(institution.id, user.id)
    if not institution_service.has_role(membership, required_role):
        return None, user, APIResponse.not_found("Institution not found")
    return institution, user, None


@institution_bp.route("", methods=["GET"])
@jwt_required()
def list_institutions():
    user = get_current_user_from_jwt()
    if not user:
        return APIResponse.unauthorized()

    include_all = str(request.args.get("all") or "").strip().lower() in {"1", "true", "yes", "on"}
    if user.role in {UserRole.ADMIN, UserRole.MODERATOR} and include_all:
        institutions = Institution.query.order_by(Institution.name.asc()).all()
        institution_ids = [institution.id for institution in institutions]
        member_counts = institution_service.list_member_counts(institution_ids)
        membership_map = institution_service.get_membership_map(user.id, institution_ids)
        payload = [
            _serialize_institution_summary(
                institution,
                membership=membership_map.get(institution.id),
                member_count=member_counts.get(institution.id, 0),
            )
            for institution in institutions
        ]
    else:
        payload = [
            {
                **membership.institution.to_dict(),
                "role": membership.role.value if membership.role else "reader",
            }
            for membership in institution_service.list_for_user(user.id)
            if membership.institution
        ]
    return APIResponse.success(data={"institutions": payload})


@institution_bp.route("/suggestions", methods=["GET"])
@jwt_required()
def suggest_institutions():
    user = get_current_user_from_jwt()
    if not user:
        return APIResponse.unauthorized()
    query = request.args.get("q") or request.args.get("query") or ""
    limit = _parse_positive_int_arg("limit", 8)
    return APIResponse.success(data={"institutions": institution_service.suggest_institutions(query, limit=limit)})


@institution_bp.route("/affiliation", methods=["POST"])
@jwt_required()
def configure_affiliation():
    user = get_current_user_from_jwt()
    if not user:
        return APIResponse.unauthorized()

    payload = request.get_json() or {}
    result = institution_service.configure_user_affiliation(
        user=user,
        institution_id=payload.get("institution_id"),
        name=payload.get("name"),
        confirm_create=payload.get("confirm_create") is True,
    )
    similar = result.get("similar") or []
    if result.get("institution") is None and similar:
        return APIResponse.error(
            "SIMILAR_INSTITUTION_EXISTS",
            "A very similar institution already exists.",
            409,
            details={"similar": similar},
        )

    memberships = institution_service.list_for_user(user.id)
    return APIResponse.success(
        data={
            "institution": result["institution"].to_dict(),
            "membership": _serialize_membership(result["membership"]) if result.get("membership") else None,
            "memberships": [_serialize_membership(membership) for membership in memberships],
            "institutions": [
                {
                    **membership.institution.to_dict(),
                    "role": membership.role.value if membership.role else "reader",
                }
                for membership in memberships
                if membership.institution
            ],
            "user": user.to_dict(),
            "created": bool(result.get("created")),
            "similar": similar,
        },
        message="Institutional affiliation updated",
        status_code=201 if result.get("created") else 200,
    )


@institution_bp.route("", methods=["POST"])
@jwt_required()
def create_institution():
    admin_user, error_response = _require_admin_user()
    if error_response:
        return error_response

    payload = request.get_json() or {}
    institution = institution_service.create_institution(
        name=payload.get("name"),
        description=payload.get("description"),
        display_name=payload.get("display_name"),
        website_url=payload.get("website_url"),
        logo_url=payload.get("logo_url"),
        profile_visibility=payload.get("profile_visibility"),
        created_by_user_id=admin_user.id,
    )
    record_audit_event(
        actor_user_id=admin_user.id,
        institution_id=institution.id,
        event_type="institution_created",
        entity_type="institution",
        entity_id=institution.id,
        details={"name": institution.name, "slug": institution.slug},
    )
    db.session.commit()
    return APIResponse.created(
        data={"institution": _serialize_institution(institution, include_members=True)},
        message="Institution created successfully",
    )


@institution_bp.route("/<int:institution_id>", methods=["GET"])
@jwt_required()
def get_institution(institution_id):
    institution, user, error_response = _require_institution_access(institution_id, required_role="reader")
    if error_response:
        return error_response
    return APIResponse.success(
        data={
            "institution": _serialize_institution(
                institution,
                include_members=True,
                include_communities=True,
                include_credentials=_can_manage_institution(user, institution),
            )
        }
    )


@institution_bp.route("/<int:institution_id>", methods=["PUT"])
@jwt_required()
def update_institution(institution_id):
    institution, user, error_response = _require_institution_access(institution_id, required_role="manager")
    if error_response:
        return error_response

    payload = request.get_json() or {}
    updated = institution_service.update_institution(
        institution,
        name=payload.get("name") if "name" in payload else None,
        description=payload.get("description") if "description" in payload else None,
        display_name=payload.get("display_name") if "display_name" in payload else None,
        website_url=payload.get("website_url") if "website_url" in payload else None,
        logo_url=payload.get("logo_url") if "logo_url" in payload else None,
        profile_visibility=payload.get("profile_visibility") if "profile_visibility" in payload else None,
    )
    record_audit_event(
        actor_user_id=user.id,
        institution_id=updated.id,
        event_type="institution_updated",
        entity_type="institution",
        entity_id=updated.id,
        details={"name": updated.name, "description": updated.description},
    )
    db.session.commit()
    return APIResponse.success(
        data={"institution": _serialize_institution(updated, include_members=True, include_communities=True)},
        message="Institution updated successfully",
    )


@institution_bp.route("/<int:institution_id>/memberships", methods=["GET"])
@jwt_required()
def list_institution_memberships(institution_id):
    institution, _, error_response = _require_institution_access(institution_id, required_role="reader")
    if error_response:
        return error_response
    memberships = institution_service.list_members(institution.id)
    return APIResponse.success(data={"memberships": [_serialize_membership(row) for row in memberships]})


@institution_bp.route("/<int:institution_id>/audit-events", methods=["GET"])
@jwt_required()
def list_institution_audit_events(institution_id):
    institution, _, error_response = _require_institution_access(institution_id, required_role="manager")
    if error_response:
        return error_response

    page = _parse_positive_int_arg("page", 1)
    per_page = _parse_positive_int_arg("per_page", 25)
    payload = list_audit_events(
        institution_id=institution.id,
        event_type=request.args.get("event_type"),
        entity_type=request.args.get("entity_type"),
        page=page,
        per_page=per_page,
    )
    return APIResponse.success(data=payload)


@institution_bp.route("/<int:institution_id>/memberships", methods=["POST"])
@jwt_required()
def create_institution_membership(institution_id):
    institution, user, error_response = _require_institution_access(institution_id, required_role="manager")
    if error_response:
        return error_response

    payload = request.get_json() or {}
    target_user = None
    if payload.get("user_id") is not None:
        try:
            target_user = db.session.get(User, int(payload.get("user_id")))
        except (TypeError, ValueError) as exc:
            raise ValidationError("user_id must be an integer") from exc
    elif payload.get("email"):
        target_user = User.query.filter_by(email=str(payload.get("email")).strip()).first()

    if not target_user:
        raise ResourceNotFoundError("Target user not found")

    membership = institution_service.upsert_membership(institution.id, target_user.id, payload.get("role"))
    record_audit_event(
        actor_user_id=user.id,
        institution_id=institution.id,
        event_type="institution_membership_upserted",
        entity_type="institution_membership",
        entity_id=membership.id,
        details={"user_id": target_user.id, "role": membership.role.value if membership.role else None},
    )
    db.session.commit()
    return APIResponse.success(
        data={"membership": _serialize_membership(membership)},
        message="Institution membership saved successfully",
    )


@institution_bp.route("/<int:institution_id>/memberships/<int:member_user_id>", methods=["PUT"])
@jwt_required()
def update_institution_membership(institution_id, member_user_id):
    institution, user, error_response = _require_institution_access(institution_id, required_role="manager")
    if error_response:
        return error_response

    target_user = db.session.get(User, int(member_user_id))
    if not target_user:
        return APIResponse.not_found("Target user not found")

    payload = request.get_json() or {}
    membership = institution_service.upsert_membership(institution.id, target_user.id, payload.get("role"))
    record_audit_event(
        actor_user_id=user.id,
        institution_id=institution.id,
        event_type="institution_membership_upserted",
        entity_type="institution_membership",
        entity_id=membership.id,
        details={"user_id": target_user.id, "role": membership.role.value if membership.role else None},
    )
    db.session.commit()
    return APIResponse.success(
        data={"membership": _serialize_membership(membership)},
        message="Institution membership updated successfully",
    )


@institution_bp.route("/<int:institution_id>/memberships/<int:member_user_id>", methods=["DELETE"])
@jwt_required()
def delete_institution_membership(institution_id, member_user_id):
    institution, user, error_response = _require_institution_access(institution_id, required_role="manager")
    if error_response:
        return error_response

    removed = institution_service.remove_membership(institution.id, int(member_user_id))
    if not removed:
        return APIResponse.not_found("Membership not found")

    record_audit_event(
        actor_user_id=user.id,
        institution_id=institution.id,
        event_type="institution_membership_removed",
        entity_type="institution_membership",
        entity_id=member_user_id,
        details={"user_id": member_user_id},
    )
    db.session.commit()
    return APIResponse.success(message="Institution membership removed successfully")


@institution_bp.route("/<int:institution_id>/communities", methods=["GET"])
@jwt_required()
def list_institution_communities(institution_id):
    institution, _, error_response = _require_institution_access(institution_id, required_role="reader")
    if error_response:
        return error_response

    communities = institution_service.list_communities(institution.id)
    return APIResponse.success(
        data={
            "communities": [row.to_dict() for row in communities],
            "community_policy": institution_service.build_community_policy(institution.id),
        }
    )


@institution_bp.route("/<int:institution_id>/communities", methods=["POST"])
@jwt_required()
def create_institution_community(institution_id):
    institution, user, error_response = _require_institution_access(institution_id, required_role="manager")
    if error_response:
        return error_response

    payload = request.get_json() or {}
    identifier = institution_service.validate_community_identifier(institution.id, payload.get("identifier"))

    community = InstitutionZenodoCommunity(
        institution_id=institution.id,
        identifier=identifier,
        is_primary_submission=bool(payload.get("is_primary_submission", False)),
        is_moderation_default=bool(payload.get("is_moderation_default", False)),
        enabled=bool(payload.get("enabled", True)),
        sort_order=_parse_int_value(payload.get("sort_order"), field_name="sort_order", default=0),
    )
    db.session.add(community)
    db.session.flush()
    if community.is_primary_submission:
        institution_service.apply_primary_submission_selection(institution.id, community.id)
    record_audit_event(
        actor_user_id=user.id,
        institution_id=institution.id,
        event_type="institution_community_created",
        entity_type="institution_community",
        entity_id=community.id,
        details=community.to_dict(),
    )
    db.session.commit()
    return APIResponse.created(
        data={"community": community.to_dict()},
        message="Institution community created successfully",
    )


@institution_bp.route("/<int:institution_id>/communities/<int:community_id>", methods=["PUT"])
@jwt_required()
def update_institution_community(institution_id, community_id):
    institution, user, error_response = _require_institution_access(institution_id, required_role="manager")
    if error_response:
        return error_response

    community = db.session.get(InstitutionZenodoCommunity, int(community_id))
    if not community or community.institution_id != institution.id:
        return APIResponse.not_found("Institution community not found")

    payload = request.get_json() or {}
    if "identifier" in payload:
        community.identifier = institution_service.validate_community_identifier(
            institution.id,
            payload.get("identifier"),
            exclude_community_id=community.id,
        )
    if "is_primary_submission" in payload:
        community.is_primary_submission = bool(payload.get("is_primary_submission"))
    if "is_moderation_default" in payload:
        community.is_moderation_default = bool(payload.get("is_moderation_default"))
    if "enabled" in payload:
        community.enabled = bool(payload.get("enabled"))
    if "sort_order" in payload:
        community.sort_order = _parse_int_value(payload.get("sort_order"), field_name="sort_order", default=0)
    db.session.flush()
    if community.is_primary_submission:
        institution_service.apply_primary_submission_selection(institution.id, community.id)

    record_audit_event(
        actor_user_id=user.id,
        institution_id=institution.id,
        event_type="institution_community_updated",
        entity_type="institution_community",
        entity_id=community.id,
        details=community.to_dict(),
    )
    db.session.commit()
    return APIResponse.success(
        data={"community": community.to_dict()},
        message="Institution community updated successfully",
    )


@institution_bp.route("/<int:institution_id>/communities/<int:community_id>", methods=["DELETE"])
@jwt_required()
def delete_institution_community(institution_id, community_id):
    institution, user, error_response = _require_institution_access(institution_id, required_role="manager")
    if error_response:
        return error_response

    community = db.session.get(InstitutionZenodoCommunity, int(community_id))
    if not community or community.institution_id != institution.id:
        return APIResponse.not_found("Institution community not found")

    record_audit_event(
        actor_user_id=user.id,
        institution_id=institution.id,
        event_type="institution_community_deleted",
        entity_type="institution_community",
        entity_id=community.id,
        details=community.to_dict(),
    )
    db.session.delete(community)
    db.session.commit()
    return APIResponse.success(message="Institution community deleted successfully")


@institution_bp.route("/<int:institution_id>/zenodo-credentials/<environment>", methods=["GET"])
@jwt_required()
def get_institution_credential(institution_id, environment):
    institution, _, error_response = _require_institution_access(institution_id, required_role="manager")
    if error_response:
        return error_response
    credential = credential_service.get_credential("institution", institution.id, environment)
    return APIResponse.success(data={"credential": credential_service.serialize(credential)})


@institution_bp.route("/<int:institution_id>/zenodo-credentials/<environment>", methods=["PUT"])
@jwt_required()
def upsert_institution_credential(institution_id, environment):
    institution, user, error_response = _require_institution_access(institution_id, required_role="manager")
    if error_response:
        return error_response

    payload = request.get_json() or {}
    credential = credential_service.upsert_credential(
        owner_type="institution",
        owner_id=institution.id,
        environment=environment,
        token=payload.get("token"),
        actor_user_id=user.id,
    )
    return APIResponse.success(
        data={"credential": credential_service.serialize(credential)},
        message="Institution Zenodo credential saved successfully",
    )


@institution_bp.route("/<int:institution_id>/zenodo-credentials/<environment>", methods=["DELETE"])
@jwt_required()
def delete_institution_credential(institution_id, environment):
    institution, user, error_response = _require_institution_access(institution_id, required_role="manager")
    if error_response:
        return error_response

    deleted = credential_service.delete_credential(
        owner_type="institution",
        owner_id=institution.id,
        environment=environment,
        actor_user_id=user.id,
    )
    if not deleted:
        return APIResponse.not_found("Zenodo credential not found")
    return APIResponse.success(message="Institution Zenodo credential deleted successfully")


@institution_bp.route("/<int:institution_id>/zenodo-credentials/<environment>/validate", methods=["POST"])
@jwt_required()
def validate_institution_credential(institution_id, environment):
    institution, user, error_response = _require_institution_access(institution_id, required_role="manager")
    if error_response:
        return error_response

    credential = credential_service.validate_credential(
        owner_type="institution",
        owner_id=institution.id,
        environment=environment,
        actor_user_id=user.id,
    )
    return APIResponse.success(
        data={"credential": credential_service.serialize(credential)},
        message="Institution Zenodo credential validation completed",
    )
