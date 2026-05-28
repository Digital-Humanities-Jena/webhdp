from __future__ import annotations

from typing import Literal

from flask_jwt_extended import get_jwt_identity

from api_utils import APIResponse
from database.database import db
from database.models import File, Session as DBSession, User
from services.session_access_service import (
    can_edit_session,
    can_manage_session,
    can_view_session,
    is_session_mutable,
)

SessionPermission = Literal["view", "edit", "manage"]


def get_current_user_from_jwt() -> User | None:
    raw_user_id = get_jwt_identity()
    if raw_user_id in (None, ""):
        return None
    try:
        user_id = int(raw_user_id)
    except (TypeError, ValueError):
        return None
    return db.session.get(User, user_id)


def _permission_allowed(session_row: DBSession, user: User | None, permission: SessionPermission) -> bool:
    if permission == "view":
        return can_view_session(session_row, user)
    if permission == "edit":
        return can_edit_session(session_row, user)
    if permission == "manage":
        return can_manage_session(session_row, user)
    return False


def get_session_with_permission(
    session_id: int,
    *,
    permission: SessionPermission = "view",
    require_mutable: bool = False,
) -> tuple[DBSession | None, User | None, tuple | None]:
    user = get_current_user_from_jwt()
    if not user:
        return None, None, APIResponse.unauthorized()

    session_row = db.session.get(DBSession, int(session_id))
    if not session_row:
        return None, user, APIResponse.not_found("Session not found")

    if not _permission_allowed(session_row, user, permission):
        return None, user, APIResponse.not_found("Session not found")

    if require_mutable and not is_session_mutable(session_row):
        return (
            None,
            user,
            APIResponse.error(
                "SESSION_READ_ONLY",
                "This session was imported as an explorer-only shared export and cannot be modified.",
                409,
                details={"session_id": int(session_row.id), "access_mode": getattr(session_row, "access_mode", None)},
            ),
        )

    return session_row, user, None


def get_file_with_session_permission(
    file_id: int,
    *,
    permission: SessionPermission = "view",
    require_mutable: bool = False,
) -> tuple[File | None, DBSession | None, User | None, tuple | None]:
    user = get_current_user_from_jwt()
    if not user:
        return None, None, None, APIResponse.unauthorized()

    file_row = db.session.get(File, int(file_id))
    if not file_row:
        return None, None, user, APIResponse.not_found("File not found")

    session_row = db.session.get(DBSession, int(file_row.session_id))
    if not session_row or not _permission_allowed(session_row, user, permission):
        return None, None, user, APIResponse.not_found("File not found")

    if require_mutable and not is_session_mutable(session_row):
        return (
            None,
            None,
            user,
            APIResponse.error(
                "SESSION_READ_ONLY",
                "This session was imported as an explorer-only shared export and cannot be modified.",
                409,
                details={"session_id": int(session_row.id), "access_mode": getattr(session_row, "access_mode", None)},
            ),
        )

    return file_row, session_row, user, None
