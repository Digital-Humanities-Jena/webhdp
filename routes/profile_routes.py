import logging
import os

from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import or_

from api_utils import APIResponse
from database.database import db
from database.models import Institution, User, UserRole

logger = logging.getLogger(__name__)
profile_bp = Blueprint("profiles", __name__)


def _frontend_base_url() -> str:
    configured = os.environ.get("FRONTEND_URL") or os.environ.get("PUBLIC_BASE_URL") or request.host_url
    return str(configured or "").strip().rstrip("/")


def _profile_url(kind: str, slug_or_public_id: str | None) -> str | None:
    identifier = str(slug_or_public_id or "").strip()
    if not identifier:
        return None
    return f"{_frontend_base_url()}/profiles/{kind}/{identifier}"


def _is_internal_profile(profile_visibility: str | None) -> bool:
    normalized = str(profile_visibility or "private").strip().lower()
    return normalized in {"internal", "public"}


def _current_user_can_view_private_profiles() -> bool:
    try:
        current_user_id = int(get_jwt_identity() or 0)
    except (TypeError, ValueError):
        return False
    current_user = db.session.get(User, current_user_id)
    return bool(current_user and current_user.role in {UserRole.ADMIN, UserRole.MODERATOR})


def _serialize_internal_user(user: User, *, include_private_fields: bool = False) -> dict:
    display_name = user.display_name or user.full_name or None
    payload = {
        "public_id": user.public_id,
        "slug": user.slug,
        "profile_url": _profile_url("users", user.slug or user.public_id),
        "display_name": display_name,
        "full_name": user.full_name,
        "bio": user.bio,
        "website_url": user.website_url,
        "avatar_url": user.avatar_url,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }
    if include_private_fields or user.show_email:
        payload["email"] = user.email
    if include_private_fields or user.show_orcid:
        payload["orcid"] = user.orcid
    if include_private_fields or user.show_affiliation:
        payload["affiliation"] = user.affiliation
    return payload


def _serialize_internal_institution(institution: Institution) -> dict:
    return {
        "public_id": institution.public_id,
        "slug": institution.slug,
        "profile_url": _profile_url("institutions", institution.slug or institution.public_id),
        "name": institution.display_name or institution.name,
        "legal_name": institution.name,
        "description": institution.description,
        "website_url": institution.website_url,
        "logo_url": institution.logo_url,
        "created_at": institution.created_at.isoformat() if institution.created_at else None,
    }


@profile_bp.route("/users/<identifier>", methods=["GET"])
@jwt_required()
def get_user_profile(identifier):
    normalized = str(identifier or "").strip()
    if not normalized:
        return APIResponse.not_found("User profile was not found")
    user = User.query.filter(or_(User.public_id == normalized, User.slug == normalized)).first()
    can_view_private = _current_user_can_view_private_profiles()
    if not user or (not can_view_private and not _is_internal_profile(user.profile_visibility)):
        return APIResponse.not_found("User profile was not found")
    return APIResponse.success(data={"user": _serialize_internal_user(user, include_private_fields=can_view_private)})


@profile_bp.route("/institutions/<identifier>", methods=["GET"])
@jwt_required()
def get_institution_profile(identifier):
    normalized = str(identifier or "").strip()
    if not normalized:
        return APIResponse.not_found("Institution profile was not found")
    institution = Institution.query.filter(
        or_(Institution.public_id == normalized, Institution.slug == normalized)
    ).first()
    if not institution or not _is_internal_profile(institution.profile_visibility):
        return APIResponse.not_found("Institution profile was not found")
    return APIResponse.success(data={"institution": _serialize_internal_institution(institution)})
