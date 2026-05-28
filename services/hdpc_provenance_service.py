from __future__ import annotations

import os
from typing import Any

from database.models import Institution, Session as DBSession, User


def public_base_url() -> str:
    return str(os.environ.get("PUBLIC_BASE_URL") or os.environ.get("FRONTEND_URL") or "").strip().rstrip("/")


def _profile_url(kind: str, identifier: str | None, *, base_url: str | None = None) -> str | None:
    clean_identifier = str(identifier or "").strip()
    clean_base_url = str(base_url if base_url is not None else public_base_url()).strip().rstrip("/")
    if not clean_identifier or not clean_base_url:
        return None
    return f"{clean_base_url}/profiles/{kind}/{clean_identifier}"


def build_hdpc_provenance(
    *,
    user: User | None,
    session: DBSession | None = None,
    institution: Institution | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    creator_identifier = user.slug or user.public_id if user else None
    institution_identifier = institution.slug or institution.public_id if institution else None
    return {
        "creator_user_public_id": user.public_id if user else None,
        "creator_display_name": (user.display_name or user.full_name) if user else None,
        "creator_orcid": user.orcid if user and user.show_orcid else None,
        "creator_profile_url": _profile_url("users", creator_identifier, base_url=base_url),
        "institution_public_id": institution.public_id if institution else None,
        "institution_name": (institution.display_name or institution.name) if institution else None,
        "institution_slug": institution.slug if institution else None,
        "institution_profile_url": _profile_url("institutions", institution_identifier, base_url=base_url),
        "source_session_id": session.id if session else None,
    }
