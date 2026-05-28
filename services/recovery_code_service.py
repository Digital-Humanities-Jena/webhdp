import hashlib
import hmac
import secrets
import string
from datetime import datetime, timedelta

from flask import current_app

from database.database import db
from database.models import User, UserRecoveryCode


USER_GENERATED = "user_generated"
ADMIN_ISSUED = "admin_issued"
_ALPHABET = string.ascii_uppercase + string.digits


def _config_int(name: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    try:
        value = int(current_app.config.get(name, default) or default)
    except (TypeError, ValueError):
        value = default
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def recovery_code_count() -> int:
    return _config_int("MFA_RECOVERY_CODE_COUNT", 10, minimum=1, maximum=50)


def recovery_code_length() -> int:
    return _config_int("MFA_RECOVERY_CODE_LENGTH", 12, minimum=8, maximum=32)


def admin_recovery_code_ttl_seconds() -> int:
    return _config_int("MFA_ADMIN_RECOVERY_CODE_TTL_SECONDS", 24 * 60 * 60, minimum=300)


def normalize_recovery_code(code: str) -> str:
    return "".join(ch for ch in str(code or "").upper() if ch.isalnum())


def format_recovery_code(raw_code: str) -> str:
    normalized = normalize_recovery_code(raw_code)
    return "-".join(normalized[index:index + 4] for index in range(0, len(normalized), 4))


def hash_recovery_code(code: str) -> str:
    secret = str(current_app.config.get("SECRET_KEY") or current_app.config.get("JWT_SECRET_KEY") or "")
    normalized = normalize_recovery_code(code)
    return hmac.new(secret.encode("utf-8"), normalized.encode("utf-8"), hashlib.sha256).hexdigest()


def generate_recovery_code() -> str:
    raw_code = "".join(secrets.choice(_ALPHABET) for _ in range(recovery_code_length()))
    return format_recovery_code(raw_code)


def _build_code(user_id: int, *, source: str, expires_at: datetime | None = None) -> tuple[UserRecoveryCode, str]:
    while True:
        code = generate_recovery_code()
        code_hash = hash_recovery_code(code)
        if not UserRecoveryCode.query.filter_by(code_hash=code_hash).first():
            break
    row = UserRecoveryCode(
        user_id=user_id,
        source=source,
        code_hash=code_hash,
        code_prefix=normalize_recovery_code(code)[:4],
        expires_at=expires_at,
    )
    return row, code


def recovery_code_status(user: User) -> dict:
    rows = UserRecoveryCode.query.filter_by(user_id=user.id, source=USER_GENERATED).all()
    now = datetime.utcnow()
    active_rows = [
        row
        for row in rows
        if row.used_at is None
        and row.invalidated_at is None
        and (row.expires_at is None or row.expires_at > now)
    ]
    used_rows = [row for row in rows if row.used_at is not None]
    return {
        "configured": bool(active_rows),
        "remaining_count": len(active_rows),
        "used_count": len(used_rows),
        "total_count": len(rows),
    }


def regenerate_user_recovery_codes(user: User) -> tuple[list[str], dict]:
    now = datetime.utcnow()
    UserRecoveryCode.query.filter(
        UserRecoveryCode.user_id == user.id,
        UserRecoveryCode.source == USER_GENERATED,
        UserRecoveryCode.used_at.is_(None),
        UserRecoveryCode.invalidated_at.is_(None),
    ).update({"invalidated_at": now, "updated_at": now}, synchronize_session=False)

    codes = []
    for _ in range(recovery_code_count()):
        row, code = _build_code(user.id, source=USER_GENERATED)
        db.session.add(row)
        codes.append(code)
    return codes, recovery_code_status(user)


def create_admin_recovery_code(user: User) -> tuple[str, UserRecoveryCode]:
    expires_at = datetime.utcnow() + timedelta(seconds=admin_recovery_code_ttl_seconds())
    row, code = _build_code(user.id, source=ADMIN_ISSUED, expires_at=expires_at)
    db.session.add(row)
    return code, row


def find_valid_recovery_code(user: User, code: str) -> UserRecoveryCode | None:
    normalized = normalize_recovery_code(code)
    if not normalized:
        return None
    now = datetime.utcnow()
    code_hash = hash_recovery_code(normalized)
    row = UserRecoveryCode.query.filter_by(user_id=user.id, code_hash=code_hash).first()
    if not row:
        return None
    if row.used_at is not None or row.invalidated_at is not None:
        return None
    if row.expires_at is not None and row.expires_at <= now:
        return None
    return row


def mark_recovery_code_used(row: UserRecoveryCode) -> None:
    now = datetime.utcnow()
    row.used_at = now
    row.updated_at = now


def generate_temporary_password() -> str:
    while True:
        password = secrets.token_urlsafe(18)
        if len(password) >= 16 and any(ch.isdigit() for ch in password):
            return password
