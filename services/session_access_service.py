from typing import Iterable

from sqlalchemy import and_, func, or_

from constants import UPLOAD_STORAGE_MODE_FIELD, UPLOAD_TASK_ID_FIELD
from database.database import db
from database.models import InstitutionRole, Session as DBSession, User, UserMetadata, UserRole
from services.institution_service import InstitutionService


_ROLE_LEVELS = {
    InstitutionRole.READER.value: 1,
    InstitutionRole.CURATOR.value: 2,
    InstitutionRole.MANAGER.value: 3,
    InstitutionRole.OWNER.value: 4,
}
MOUNTED_INPUT_CAPABILITY = "mounted_input_access"
MOUNTED_INPUT_ORIGIN = "mounted_input"


def can_use_mounted_inputs(user: User | None) -> bool:
    return bool(user and user.is_verified and not user.force_password_change and user.has_capability(MOUNTED_INPUT_CAPABILITY))


def mounted_input_session_filter():
    legacy_local_scans = db.session.query(UserMetadata.session_id).filter(UserMetadata.field_name == UPLOAD_TASK_ID_FIELD)
    return or_(DBSession.origin_type == MOUNTED_INPUT_ORIGIN, DBSession.id.in_(
        db.session.query(UserMetadata.session_id).filter(or_(
            and_(UserMetadata.field_name == UPLOAD_STORAGE_MODE_FIELD, UserMetadata.field_value == "local",
                 UserMetadata.session_id.in_(legacy_local_scans)),
            and_(UserMetadata.field_name == "msf_profile",
                 func.replace(UserMetadata.field_value, " ", "").contains('"storage_mode":"local"')),
        )),
    ))


def _can_access_session_source(session_row: DBSession, user: User) -> bool:
    if can_use_mounted_inputs(user):
        return True
    if session_row.origin_type == MOUNTED_INPUT_ORIGIN:
        return False
    return not db.session.query(DBSession.id).filter(
        DBSession.id == session_row.id, mounted_input_session_filter(),
    ).scalar()


def _shared_with_institution(session_row: DBSession) -> bool:
    return str(getattr(session_row, "sharing_scope", None) or "private").strip().lower() == "institution"


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
    if not session_row or not user or not _can_access_session_source(session_row, user):
        return False
    if session_row.user_id == user.id:
        return True
    if is_platform_moderator_or_admin(user):
        return True
    if not _shared_with_institution(session_row):
        return False
    return _membership_level(session_row, user.id) >= _ROLE_LEVELS[InstitutionRole.READER.value]


def can_edit_session(session_row: DBSession, user: User | None) -> bool:
    if not session_row or not user or not _can_access_session_source(session_row, user):
        return False
    if session_row.user_id == user.id:
        return True
    if is_platform_moderator_or_admin(user):
        return True
    if not _shared_with_institution(session_row):
        return False
    return _membership_level(session_row, user.id) >= _ROLE_LEVELS[InstitutionRole.CURATOR.value]


def can_manage_session(session_row: DBSession, user: User | None) -> bool:
    if not session_row or not user or not _can_access_session_source(session_row, user):
        return False
    if session_row.user_id == user.id:
        return True
    if is_platform_moderator_or_admin(user):
        return True
    if not _shared_with_institution(session_row):
        return False
    return _membership_level(session_row, user.id) >= _ROLE_LEVELS[InstitutionRole.MANAGER.value]


def is_session_owner(session_row: DBSession, user: User | None) -> bool:
    return bool(session_row and user and int(session_row.user_id) == int(user.id))


def can_change_session_visibility(session_row: DBSession, user: User | None) -> bool:
    return bool(session_row and (is_session_owner(session_row, user) or is_platform_moderator_or_admin(user)))


def is_institution_shared_session(session_row: DBSession | None) -> bool:
    if not session_row or not getattr(session_row, "institution_id", None):
        return False
    return _shared_with_institution(session_row)


def is_session_mutable(session_row: DBSession | None) -> bool:
    if not session_row:
        return False
    return str(getattr(session_row, "access_mode", None) or "full").strip().lower() != "explorer_only"


def can_download_hdpc(session_row: DBSession, user: User | None) -> bool:
    return is_session_owner(session_row, user) and _can_access_session_source(session_row, user)


def can_download_shared_hdpc(session_row: DBSession, user: User | None) -> bool:
    if not user or not is_institution_shared_session(session_row):
        return False
    return can_view_session(session_row, user)


def build_session_permissions(session_row: DBSession, user: User | None) -> dict[str, bool]:
    return {
        "is_owner": is_session_owner(session_row, user),
        "can_edit": is_session_mutable(session_row) and can_edit_session(session_row, user),
        "can_manage": can_manage_session(session_row, user),
        "can_change_visibility": can_change_session_visibility(session_row, user),
        "can_download_hdpc": can_download_hdpc(session_row, user),
        "can_download_shared_hdpc": can_download_shared_hdpc(session_row, user),
    }


def get_accessible_sessions(user: User | None, *, scope: str = "all") -> Iterable[DBSession]:
    normalized_scope = str(scope or "all").strip().lower()
    query = DBSession.query
    if not user:
        return []
    if not can_use_mounted_inputs(user):
        query = query.filter(~mounted_input_session_filter())
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
                & (func.lower(func.trim(DBSession.sharing_scope)) == "institution")
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
                    & (func.lower(func.trim(DBSession.sharing_scope)) == "institution")
                )
            )
        else:
            query = query.filter(DBSession.user_id == user.id)
    return query.order_by(DBSession.created_at.desc()).all()
