from typing import Iterable

from database.database import db
from database.models import InstitutionRole, Session as DBSession, User, UserRole
from services.institution_service import InstitutionService


_ROLE_LEVELS = {
    InstitutionRole.READER.value: 1,
    InstitutionRole.CURATOR.value: 2,
    InstitutionRole.MANAGER.value: 3,
    InstitutionRole.OWNER.value: 4,
}


def get_user(user_id: int | None) -> User | None:
    if user_id is None:
        return None
    return db.session.get(User, int(user_id))


def is_platform_moderator_or_admin(user: User | None) -> bool:
    if not user or not user.role:
        return False
    return user.role in {UserRole.MODERATOR, UserRole.ADMIN}


def is_platform_admin(user: User | None) -> bool:
    return bool(user and user.role == UserRole.ADMIN)


def _membership_level(session_row: DBSession, user_id: int) -> int:
    if not session_row.institution_id:
        return 0
    membership = InstitutionService().get_membership(session_row.institution_id, int(user_id))
    if not membership:
        return 0
    return _ROLE_LEVELS.get(membership.role.value if membership.role else InstitutionRole.READER.value, 0)


def can_view_session(session_row: DBSession, user: User | None) -> bool:
    if not session_row or not user:
        return False
    if session_row.user_id == user.id:
        return True
    if is_platform_moderator_or_admin(user):
        return True
    if str(getattr(session_row, "sharing_scope", None) or "private").strip().lower() == "private":
        return False
    return _membership_level(session_row, user.id) >= _ROLE_LEVELS[InstitutionRole.READER.value]


def can_edit_session(session_row: DBSession, user: User | None) -> bool:
    if not session_row or not user:
        return False
    if session_row.user_id == user.id:
        return True
    if is_platform_moderator_or_admin(user):
        return True
    if str(getattr(session_row, "sharing_scope", None) or "private").strip().lower() == "private":
        return False
    return _membership_level(session_row, user.id) >= _ROLE_LEVELS[InstitutionRole.CURATOR.value]


def can_manage_session(session_row: DBSession, user: User | None) -> bool:
    if not session_row or not user:
        return False
    if session_row.user_id == user.id:
        return True
    if is_platform_moderator_or_admin(user):
        return True
    return _membership_level(session_row, user.id) >= _ROLE_LEVELS[InstitutionRole.MANAGER.value]


def is_session_owner(session_row: DBSession, user: User | None) -> bool:
    return bool(session_row and user and int(session_row.user_id) == int(user.id))


def is_institution_shared_session(session_row: DBSession | None) -> bool:
    if not session_row or not getattr(session_row, "institution_id", None):
        return False
    return str(getattr(session_row, "sharing_scope", None) or "private").strip().lower() != "private"


def is_session_mutable(session_row: DBSession | None) -> bool:
    if not session_row:
        return False
    return str(getattr(session_row, "access_mode", None) or "full").strip().lower() != "explorer_only"


def can_download_hdpc(session_row: DBSession, user: User | None) -> bool:
    return is_session_owner(session_row, user)


def can_download_shared_hdpc(session_row: DBSession, user: User | None) -> bool:
    if not user or not is_institution_shared_session(session_row):
        return False
    if is_session_owner(session_row, user):
        return True
    if is_platform_moderator_or_admin(user):
        return True
    return can_view_session(session_row, user)


def build_session_permissions(session_row: DBSession, user: User | None) -> dict[str, bool]:
    return {
        "is_owner": is_session_owner(session_row, user),
        "can_edit": can_edit_session(session_row, user),
        "can_manage": can_manage_session(session_row, user),
        "can_download_hdpc": can_download_hdpc(session_row, user),
        "can_download_shared_hdpc": can_download_shared_hdpc(session_row, user),
    }


def get_accessible_sessions(user: User | None, *, scope: str = "all") -> Iterable[DBSession]:
    normalized_scope = str(scope or "all").strip().lower()
    query = DBSession.query
    if not user:
        return []
    if is_platform_moderator_or_admin(user):
        if normalized_scope == "personal":
            query = query.filter(DBSession.institution_id.is_(None))
        elif normalized_scope == "institution":
            query = query.filter(DBSession.institution_id.isnot(None))
        return query.order_by(DBSession.created_at.desc()).all()

    if normalized_scope == "personal":
        query = query.filter(DBSession.user_id == user.id, DBSession.institution_id.is_(None))
    elif normalized_scope == "institution":
        membership_rows = InstitutionService().list_for_user(user.id)
        institution_ids = [row.institution_id for row in membership_rows]
        if not institution_ids:
            return query.filter(
                DBSession.user_id == user.id,
                DBSession.institution_id.isnot(None),
            ).order_by(DBSession.created_at.desc()).all()
        query = query.filter(
            ((DBSession.user_id == user.id) & DBSession.institution_id.isnot(None))
            | (
                (DBSession.institution_id.in_(institution_ids))
                & (DBSession.sharing_scope != "private")
            )
        )
    else:
        membership_rows = InstitutionService().list_for_user(user.id)
        institution_ids = [row.institution_id for row in membership_rows]
        if institution_ids:
            query = query.filter(
                (DBSession.user_id == user.id)
                | (
                    (DBSession.institution_id.in_(institution_ids))
                    & (DBSession.sharing_scope != "private")
                )
            )
        else:
            query = query.filter(DBSession.user_id == user.id)
    return query.order_by(DBSession.created_at.desc()).all()
