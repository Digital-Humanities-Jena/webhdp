# routes/auth_routes.py
import hashlib
import hmac
import logging
import os
import secrets
import threading
import time
from datetime import datetime, timedelta

from flask import Blueprint, request, current_app
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required, get_jwt, verify_jwt_in_request
from flask_jwt_extended.exceptions import JWTExtendedException

from api_utils import APIResponse
from database.models import User, UserMfaChallenge, UserZenodoActiveCredential
from exceptions import ValidationError
from services.audit_service import record_audit_event
from services.institution_service import InstitutionService
from services.recovery_code_service import (
    find_valid_recovery_code,
    mark_recovery_code_used,
    recovery_code_status,
    regenerate_user_recovery_codes,
)
from services.hpc_resource_request_service import HpcResourceRequestService
from services.mfa_config_service import email_domain_matches_config, get_email_domain
from services.user_service import UserService
from services.zenodo_credential_service import ZenodoCredentialService
from database.database import db
from database.models import TokenBlocklist

logger = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__)
user_service = UserService()
institution_service = InstitutionService()
credential_service = ZenodoCredentialService()
hpc_request_service = HpcResourceRequestService()
_rate_limit_lock = threading.Lock()
_rate_limit_events: dict[str, list[float]] = {}
_rate_limit_lockouts: dict[str, float] = {}
_recovery_rate_limit_events: dict[str, list[float]] = {}
_recovery_rate_limit_lockouts: dict[str, float] = {}

PASSWORD_CHANGE_ALLOWED_PATHS = {
    "/api/v1/auth/me",
    "/api/v1/auth/me/password",
    "/api/v1/auth/logout",
}


@auth_bp.before_request
def enforce_auth_password_change_required():
    if request.method == "OPTIONS" or request.path in PASSWORD_CHANGE_ALLOWED_PATHS:
        return None
    if not request.headers.get("Authorization", "").startswith("Bearer "):
        return None
    try:
        verify_jwt_in_request(optional=True)
    except JWTExtendedException:
        return None
    user_id = get_jwt_identity()
    if not user_id:
        return None
    try:
        user = user_service.get_by_id(int(user_id))
    except (TypeError, ValueError):
        return None
    if user.force_password_change:
        return APIResponse.error(
            "PASSWORD_CHANGE_REQUIRED",
            "Password change required before continuing.",
            403,
            details={"action": "change_password"},
        )
    return None


def _remote_ip() -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip() or "unknown"
    return request.remote_addr or "unknown"


def _rate_limit_value(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _prune_rate_limit_state(now: float, window_seconds: int) -> None:
    for key, events in list(_rate_limit_events.items()):
        kept = [event for event in events if now - event <= window_seconds]
        if kept:
            _rate_limit_events[key] = kept
        else:
            _rate_limit_events.pop(key, None)
    for key, locked_until in list(_rate_limit_lockouts.items()):
        if locked_until <= now:
            _rate_limit_lockouts.pop(key, None)


def _rate_limit_keys(action: str, identifier: str | None = None) -> list[str]:
    keys = [f"{action}:ip:{_remote_ip()}"]
    normalized_identifier = str(identifier or "").strip().lower()
    if normalized_identifier:
        keys.append(f"{action}:id:{normalized_identifier}")
    return keys


def _check_rate_limit(action: str, identifier: str | None = None) -> None:
    window = _rate_limit_value("AUTH_RATE_LIMIT_WINDOW_SECONDS", 300)
    now = time.monotonic()
    keys = _rate_limit_keys(action, identifier)
    with _rate_limit_lock:
        _prune_rate_limit_state(now, window)
        active_lockouts = [
            _rate_limit_lockouts[key]
            for key in keys
            if key in _rate_limit_lockouts and _rate_limit_lockouts[key] > now
        ]
    if active_lockouts:
        retry_after = int(max(active_lockouts) - now) + 1
        return APIResponse.error(
            "RATE_LIMITED",
            "Too many authentication attempts. Try again later.",
            429,
            details={"retry_after_seconds": max(1, retry_after)},
        )
    return None


def _record_rate_limit_event(action: str, identifier: str | None = None, *, failed: bool = True) -> None:
    if not failed:
        return
    window = _rate_limit_value("AUTH_RATE_LIMIT_WINDOW_SECONDS", 300)
    lockout = _rate_limit_value("AUTH_RATE_LIMIT_LOCKOUT_SECONDS", 900)
    max_attempts = _rate_limit_value(
        "REGISTER_RATE_LIMIT_ATTEMPTS" if action == "register" else "LOGIN_RATE_LIMIT_ATTEMPTS",
        10 if action == "register" else 5,
    )
    now = time.monotonic()
    keys = _rate_limit_keys(action, identifier)
    with _rate_limit_lock:
        _prune_rate_limit_state(now, window)
        for key in keys:
            events = _rate_limit_events.get(key, [])
            events.append(now)
            _rate_limit_events[key] = events
            if len(events) >= max_attempts:
                _rate_limit_lockouts[key] = now + lockout
                _rate_limit_events.pop(key, None)


def _clear_rate_limit(action: str, identifier: str | None = None) -> None:
    keys = _rate_limit_keys(action, identifier)
    with _rate_limit_lock:
        for key in keys:
            _rate_limit_events.pop(key, None)
            _rate_limit_lockouts.pop(key, None)


def _recovery_rate_limit_value(name: str, default: int) -> int:
    try:
        return max(1, int(current_app.config.get(name, os.environ.get(name, default)) or default))
    except (TypeError, ValueError):
        return default


def _prune_recovery_rate_limit_state(now: float, window_seconds: int) -> None:
    for key, events in list(_recovery_rate_limit_events.items()):
        kept = [event for event in events if now - event <= window_seconds]
        if kept:
            _recovery_rate_limit_events[key] = kept
        else:
            _recovery_rate_limit_events.pop(key, None)
    for key, locked_until in list(_recovery_rate_limit_lockouts.items()):
        if locked_until <= now:
            _recovery_rate_limit_lockouts.pop(key, None)


def _check_recovery_rate_limit(identifier: str | None = None):
    window = _recovery_rate_limit_value("MFA_RECOVERY_RATE_LIMIT_WINDOW_SECONDS", 300)
    now = time.monotonic()
    keys = _rate_limit_keys("mfa_recovery", identifier)
    with _rate_limit_lock:
        _prune_recovery_rate_limit_state(now, window)
        active_lockouts = [
            _recovery_rate_limit_lockouts[key]
            for key in keys
            if key in _recovery_rate_limit_lockouts and _recovery_rate_limit_lockouts[key] > now
        ]
    if active_lockouts:
        retry_after = int(max(active_lockouts) - now) + 1
        return APIResponse.error(
            "MFA_RECOVERY_RATE_LIMITED",
            "Too many recovery code attempts. Try again later.",
            429,
            details={"retry_after_seconds": max(1, retry_after)},
        )
    return None


def _record_recovery_rate_limit_failure(identifier: str | None = None) -> None:
    window = _recovery_rate_limit_value("MFA_RECOVERY_RATE_LIMIT_WINDOW_SECONDS", 300)
    lockout = _recovery_rate_limit_value("MFA_RECOVERY_RATE_LIMIT_LOCKOUT_SECONDS", 900)
    max_attempts = _recovery_rate_limit_value("MFA_RECOVERY_RATE_LIMIT_ATTEMPTS", 5)
    now = time.monotonic()
    keys = _rate_limit_keys("mfa_recovery", identifier)
    with _rate_limit_lock:
        _prune_recovery_rate_limit_state(now, window)
        for key in keys:
            events = _recovery_rate_limit_events.get(key, [])
            events.append(now)
            _recovery_rate_limit_events[key] = events
            if len(events) >= max_attempts:
                _recovery_rate_limit_lockouts[key] = now + lockout
                _recovery_rate_limit_events.pop(key, None)


def _clear_recovery_rate_limit(identifier: str | None = None) -> None:
    keys = _rate_limit_keys("mfa_recovery", identifier)
    with _rate_limit_lock:
        for key in keys:
            _recovery_rate_limit_events.pop(key, None)
            _recovery_rate_limit_lockouts.pop(key, None)


def _serialize_membership(membership):
    payload = membership.to_dict()
    payload["institution"] = membership.institution.to_dict() if getattr(membership, "institution", None) else None
    return payload


def _serialize_user_context(user: User) -> dict:
    memberships = institution_service.list_for_user(user.id)
    institutions = []
    for membership in memberships:
        if not membership.institution:
            continue
        institution_payload = membership.institution.to_dict()
        institution_payload["role"] = membership.role.value if membership.role else "reader"
        institutions.append(institution_payload)

    return {
        **user.to_dict(),
        "memberships": [_serialize_membership(membership) for membership in memberships],
        "institutions": institutions,
        "default_institution": user.default_institution.to_dict() if getattr(user, "default_institution", None) else None,
        "zenodo_credentials_configured": UserZenodoActiveCredential.query.filter_by(user_id=user.id).count() > 0,
        "hpc": hpc_request_service.access_summary_for_user(user),
    }


def _create_access_token_for_user(user: User) -> str:
    return create_access_token(
        identity=str(user.id),
        additional_claims={
            "token_version": int(user.token_version or 0),
            "force_password_change": bool(user.force_password_change),
        },
    )


def _mfa_code_length() -> int:
    return max(4, min(10, int(current_app.config.get("MFA_EMAIL_CODE_LENGTH", 6) or 6)))


def _mfa_ttl_seconds() -> int:
    return max(60, int(current_app.config.get("MFA_EMAIL_CODE_TTL_SECONDS", 600) or 600))


def _mfa_max_attempts() -> int:
    return max(1, int(current_app.config.get("MFA_EMAIL_MAX_VERIFY_ATTEMPTS", 5) or 5))


def _mfa_resend_cooldown_seconds() -> int:
    return max(0, int(current_app.config.get("MFA_EMAIL_RESEND_COOLDOWN_SECONDS", 60) or 60))


def _hash_token(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _hash_mfa_code(code: str, token_hash: str) -> str:
    secret = str(current_app.config.get("SECRET_KEY") or current_app.config.get("JWT_SECRET_KEY") or "")
    payload = f"{token_hash}:{str(code).strip()}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _generate_mfa_code() -> str:
    length = _mfa_code_length()
    upper_bound = 10 ** length
    return str(secrets.randbelow(upper_bound)).zfill(length)


def _mask_email(email: str) -> str:
    local_part, separator, domain = str(email or "").partition("@")
    if not separator:
        return "***"
    if len(local_part) <= 2:
        masked_local = f"{local_part[:1]}***"
    else:
        masked_local = f"{local_part[:2]}***{local_part[-1:]}"
    return f"{masked_local}@{domain}"


def _send_login_mfa_code(user: User, code: str) -> bool:
    email_service = getattr(current_app, "email_service", None)
    if not email_service:
        logger.error("Email service is not available for mandatory login MFA")
        return False
    expires_minutes = max(1, int((_mfa_ttl_seconds() + 59) / 60))
    return bool(email_service.send_login_mfa_code_email(user.email, code, expires_minutes))


def _create_email_mfa_challenge(user: User) -> tuple[UserMfaChallenge, str, str]:
    now = datetime.utcnow()
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    code = _generate_mfa_code()
    UserMfaChallenge.query.filter(
        UserMfaChallenge.user_id == user.id,
        UserMfaChallenge.method == "email",
        UserMfaChallenge.consumed_at.is_(None),
    ).update({"consumed_at": now, "updated_at": now}, synchronize_session=False)
    challenge = UserMfaChallenge(
        user_id=user.id,
        method="email",
        token_hash=token_hash,
        code_hash=_hash_mfa_code(code, token_hash),
        expires_at=now + timedelta(seconds=_mfa_ttl_seconds()),
        attempts=0,
        last_sent_at=now,
        created_at=now,
        updated_at=now,
    )
    db.session.add(challenge)
    return challenge, token, code


def _mfa_response_payload(challenge: UserMfaChallenge, token: str, user: User) -> dict:
    expires_in_seconds = max(0, int((challenge.expires_at - datetime.utcnow()).total_seconds()))
    return {
        "mfa_required": True,
        "mfa_token": token,
        "method": challenge.method,
        "expires_in_seconds": expires_in_seconds,
        "masked_email": _mask_email(user.email),
    }


def _is_production_runtime() -> bool:
    return str(os.environ.get("FLASK_ENV") or "").strip().lower() == "production"


def _development_mfa_delivery_mode() -> str:
    mode = str(
        current_app.config.get("MFA_DEVELOPMENT_CODE_DELIVERY")
        or os.environ.get("MFA_DEVELOPMENT_CODE_DELIVERY")
        or ""
    ).strip().lower()
    if _is_production_runtime():
        return ""
    if mode in {"inline", "log"}:
        return mode
    return ""


def _deliver_login_mfa_code(user: User, code: str) -> tuple[bool, str]:
    mode = _development_mfa_delivery_mode()
    if mode:
        current_app.logger.warning("Development login MFA code for %s: %s", user.email, code)
        return True, mode
    return _send_login_mfa_code(user, code), "email"


def _attach_development_mfa_code(payload: dict, code: str, delivery_mode: str) -> dict:
    payload["delivery"] = "development_inline" if delivery_mode == "inline" else delivery_mode
    if delivery_mode == "inline":
        payload["development_mfa_code"] = code
    return payload


def _get_active_mfa_challenge(token: str) -> UserMfaChallenge | None:
    token_value = str(token or "").strip()
    if not token_value:
        return None
    return UserMfaChallenge.query.filter_by(token_hash=_hash_token(token_value), method="email").first()


def _validate_mfa_challenge(challenge: UserMfaChallenge | None) -> tuple[UserMfaChallenge | None, object | None]:
    now = datetime.utcnow()
    if not challenge or challenge.consumed_at is not None or challenge.expires_at <= now:
        return None, APIResponse.error("MFA_CHALLENGE_INVALID", "The verification code has expired. Please sign in again.", 400)
    if challenge.attempts >= _mfa_max_attempts():
        return None, APIResponse.error("MFA_CHALLENGE_LOCKED", "Too many verification attempts. Please sign in again.", 429)
    return challenge, None


@auth_bp.route("/register", methods=["POST"])
def register():
    """Register a new user"""
    data = request.get_json() or {}

    email = (data.get("email") or "").strip()
    password = data.get("password")
    limited_response = _check_rate_limit("register", email)
    if limited_response:
        return limited_response
    _record_rate_limit_event("register", email, failed=True)

    if not email or not password:
        raise ValidationError("Email and password are required")

    if len(password) < 8:
        raise ValidationError("Password must be at least 8 characters")

    user = user_service.create_user(email=email, password=password)

    # Send verification email
    if hasattr(current_app, "email_service"):
        current_app.email_service.send_verification_email(user.email, user.verification_token)

    return APIResponse.success(
        data={"user": _serialize_user_context(user)},
        message="User registered successfully. Please check your email for a verification link."
    )


@auth_bp.route("/verify-email/<token>", methods=["GET"])
def verify_email(token):
    """Verify user's email address"""
    user = user_service.verify_user(token)
    if not user:
        return APIResponse.error("Invalid or expired verification token", 400)

    return APIResponse.success(message="Email verified successfully. You can now log in.")


@auth_bp.route("/login", methods=["POST"])
def login():
    """Authenticate user credentials and start email MFA unless a provider bypass is configured."""
    data = request.get_json() or {}

    email = (data.get("email") or "").strip()
    password = data.get("password")
    limited_response = _check_rate_limit("login", email)
    if limited_response:
        return limited_response

    if not email or not password:
        raise ValidationError("Email and password are required")

    user = user_service.authenticate(email=email, password=password)
    if not user:
        _record_rate_limit_event("login", email, failed=True)
        raise ValidationError("Invalid email or password")

    if not user.is_verified:
        _record_rate_limit_event("login", email, failed=True)
        return APIResponse.error("EMAIL_NOT_VERIFIED", "Please verify your email address before logging in", 403)

    if email_domain_matches_config(user.email):
        record_audit_event(
            actor_user_id=user.id,
            event_type="auth.login_mfa_bypassed",
            entity_type="user",
            entity_id=user.id,
            details={"email_domain": get_email_domain(user.email)},
        )
        db.session.commit()
        _clear_rate_limit("login", email)
        access_token = _create_access_token_for_user(user)
        return APIResponse.success(
            data={"user": _serialize_user_context(user), "access_token": access_token, "mfa_bypassed": True},
            message="Login successful",
        )

    challenge, token, code = _create_email_mfa_challenge(user)
    delivered, delivery_mode = _deliver_login_mfa_code(user, code)
    if not delivered:
        db.session.rollback()
        return APIResponse.error("MFA_EMAIL_FAILED", "Unable to send the verification code email. Please try again later.", 500)
    db.session.commit()
    _clear_rate_limit("login", email)
    payload = _attach_development_mfa_code(_mfa_response_payload(challenge, token, user), code, delivery_mode)

    return APIResponse.success(
        data=payload,
        message="Verification code sent",
        status_code=202,
    )


@auth_bp.route("/login/verify-code", methods=["POST"])
def verify_login_code():
    """Complete login after verifying the emailed MFA code."""
    data = request.get_json() or {}
    token = data.get("mfa_token")
    code = str(data.get("code") or "").strip()

    if not token or not code:
        raise ValidationError("Verification token and code are required")

    challenge, error_response = _validate_mfa_challenge(_get_active_mfa_challenge(token))
    if error_response:
        return error_response

    token_hash = _hash_token(token)
    expected_code_hash = _hash_mfa_code(code, token_hash)
    if not hmac.compare_digest(challenge.code_hash, expected_code_hash):
        challenge.attempts += 1
        challenge.updated_at = datetime.utcnow()
        db.session.commit()
        if challenge.attempts >= _mfa_max_attempts():
            return APIResponse.error("MFA_CHALLENGE_LOCKED", "Too many verification attempts. Please sign in again.", 429)
        return APIResponse.error("MFA_CODE_INVALID", "Invalid verification code", 400)

    user = challenge.user
    if not user or not user.is_verified:
        return APIResponse.error("MFA_CHALLENGE_INVALID", "The verification code has expired. Please sign in again.", 400)

    now = datetime.utcnow()
    challenge.consumed_at = now
    challenge.updated_at = now
    db.session.commit()

    access_token = _create_access_token_for_user(user)
    return APIResponse.success(
        data={"user": _serialize_user_context(user), "access_token": access_token},
        message="Login successful",
    )


@auth_bp.route("/login/verify-recovery-code", methods=["POST"])
def verify_login_recovery_code():
    """Complete login after verifying an MFA recovery code."""
    data = request.get_json() or {}
    token = data.get("mfa_token")
    recovery_code = str(data.get("recovery_code") or "").strip()

    if not token or not recovery_code:
        raise ValidationError("Verification token and recovery code are required")

    challenge, error_response = _validate_mfa_challenge(_get_active_mfa_challenge(token))
    if error_response:
        return error_response

    user = challenge.user
    if not user or not user.is_verified:
        return APIResponse.error("MFA_CHALLENGE_INVALID", "The verification code has expired. Please sign in again.", 400)

    limited_response = _check_recovery_rate_limit(user.email)
    if limited_response:
        return limited_response

    recovery_row = find_valid_recovery_code(user, recovery_code)
    if not recovery_row:
        _record_recovery_rate_limit_failure(user.email)
        challenge.attempts += 1
        challenge.updated_at = datetime.utcnow()
        db.session.commit()
        if challenge.attempts >= _mfa_max_attempts():
            return APIResponse.error("MFA_CHALLENGE_LOCKED", "Too many verification attempts. Please sign in again.", 429)
        return APIResponse.error("MFA_RECOVERY_CODE_INVALID", "Invalid recovery code", 400)

    now = datetime.utcnow()
    mark_recovery_code_used(recovery_row)
    challenge.consumed_at = now
    challenge.updated_at = now
    _clear_recovery_rate_limit(user.email)
    record_audit_event(
        actor_user_id=user.id,
        event_type="auth.recovery_code_login",
        entity_type="user",
        entity_id=user.id,
        details={"source": recovery_row.source, "code_prefix": recovery_row.code_prefix},
    )
    db.session.commit()

    access_token = _create_access_token_for_user(user)
    return APIResponse.success(
        data={"user": _serialize_user_context(user), "access_token": access_token},
        message="Login successful",
    )


@auth_bp.route("/login/resend-code", methods=["POST"])
def resend_login_code():
    """Resend the email MFA code for an active login challenge."""
    data = request.get_json() or {}
    token = data.get("mfa_token")

    if not token:
        raise ValidationError("Verification token is required")

    challenge, error_response = _validate_mfa_challenge(_get_active_mfa_challenge(token))
    if error_response:
        return error_response
    if not challenge.user or not challenge.user.is_verified:
        return APIResponse.error("MFA_CHALLENGE_INVALID", "The verification code has expired. Please sign in again.", 400)

    now = datetime.utcnow()
    cooldown_seconds = _mfa_resend_cooldown_seconds()
    retry_after = cooldown_seconds - int((now - challenge.last_sent_at).total_seconds())
    if retry_after > 0:
        return APIResponse.error(
            "MFA_RESEND_COOLDOWN",
            "Please wait before requesting another verification code.",
            429,
            details={"retry_after_seconds": retry_after},
        )

    token_hash = _hash_token(token)
    code = _generate_mfa_code()
    next_code_hash = _hash_mfa_code(code, token_hash)
    while next_code_hash == challenge.code_hash:
        code = _generate_mfa_code()
        next_code_hash = _hash_mfa_code(code, token_hash)
    challenge.code_hash = next_code_hash
    challenge.expires_at = now + timedelta(seconds=_mfa_ttl_seconds())
    challenge.attempts = 0
    challenge.last_sent_at = now
    challenge.updated_at = now
    delivered, delivery_mode = _deliver_login_mfa_code(challenge.user, code)
    if not delivered:
        db.session.rollback()
        return APIResponse.error("MFA_EMAIL_FAILED", "Unable to send the verification code email. Please try again later.", 500)
    db.session.commit()
    payload = _attach_development_mfa_code(_mfa_response_payload(challenge, token, challenge.user), code, delivery_mode)

    return APIResponse.success(
        data=payload,
        message="Verification code sent",
    )


@auth_bp.route("/me/recovery-codes", methods=["GET"])
@jwt_required()
def get_recovery_codes():
    """Return recovery code status without exposing raw codes."""
    user_id = int(get_jwt_identity())
    user = user_service.get_by_id(user_id)
    if user.force_password_change:
        return APIResponse.error(
            "PASSWORD_CHANGE_REQUIRED",
            "Password change required before continuing.",
            403,
            details={"action": "change_password"},
        )
    return APIResponse.success(data={"recovery_codes": recovery_code_status(user)})


@auth_bp.route("/me/recovery-codes", methods=["POST"])
@jwt_required()
def regenerate_recovery_codes():
    """Regenerate recovery codes after validating the current password."""
    user_id = int(get_jwt_identity())
    user = user_service.get_by_id(user_id)
    if user.force_password_change:
        return APIResponse.error(
            "PASSWORD_CHANGE_REQUIRED",
            "Password change required before continuing.",
            403,
            details={"action": "change_password"},
        )
    data = request.get_json() or {}
    current_password = data.get("current_password")
    if not current_password:
        raise ValidationError("Current password is required")
    if not user.check_password(current_password):
        raise ValidationError("Current password is incorrect")

    codes, status = regenerate_user_recovery_codes(user)
    record_audit_event(
        actor_user_id=user.id,
        event_type="auth.recovery_codes_regenerated",
        entity_type="user",
        entity_id=user.id,
        details={"count": len(codes)},
    )
    db.session.commit()
    return APIResponse.success(
        data={"recovery_codes": status, "codes": codes},
        message="Recovery codes regenerated",
    )


@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def get_current_user():
    """Get current authenticated user"""
    user_id_str = get_jwt_identity()
    user_id = int(user_id_str)
    user = user_service.get_by_id(user_id)

    return APIResponse.success(data={"user": _serialize_user_context(user)})


@auth_bp.route("/me", methods=["PUT"])
@jwt_required()
def update_current_user():
    """Update current user's account details."""
    user_id_str = get_jwt_identity()
    user_id = int(user_id_str)
    user = user_service.get_by_id(user_id)

    data = request.get_json() or {}
    if not isinstance(data, dict):
        raise ValidationError("Invalid account update payload")

    updated_user = user_service.update_profile(user, data)
    return APIResponse.success(
        data={"user": _serialize_user_context(updated_user)},
        message="Account updated successfully",
    )


@auth_bp.route("/me/onboarding", methods=["PUT"])
@jwt_required()
def update_onboarding_state():
    user_id_str = get_jwt_identity()
    user = user_service.get_by_id(int(user_id_str))
    data = request.get_json() or {}
    action = str(data.get("action") or "").strip().lower()
    now = datetime.utcnow()
    if action == "complete":
        user.onboarding_required = False
        user.onboarding_completed_at = now
    elif action == "skip":
        user.onboarding_required = False
        user.onboarding_skipped_at = now
    else:
        raise ValidationError("action must be complete or skip")
    db.session.commit()
    return APIResponse.success(
        data={"user": _serialize_user_context(user)},
        message="Onboarding updated",
    )


@auth_bp.route("/me/password", methods=["PUT"])
@jwt_required()
def update_password():
    """Update current user's password."""
    user_id_str = get_jwt_identity()
    user_id = int(user_id_str)
    user = user_service.get_by_id(user_id)

    data = request.get_json() or {}
    current_password = data.get("current_password")
    new_password = data.get("new_password")
    confirm_new_password = data.get("confirm_new_password")

    if new_password != confirm_new_password:
        raise ValidationError("New password and confirmation do not match")

    updated_user = user_service.update_password(user, current_password, new_password)
    return APIResponse.success(
        data={
            "user": _serialize_user_context(updated_user),
            "access_token": _create_access_token_for_user(updated_user),
        },
        message="Password updated successfully",
    )


@auth_bp.route("/logout", methods=["POST"])
@jwt_required()
def logout():
    """Logout user (revoke token)"""
    jti = get_jwt()["jti"]
    db.session.add(TokenBlocklist(jti=jti))
    db.session.commit()
    return APIResponse.success(message="Logout successful")


@auth_bp.route("/me/zenodo-credentials/<environment>", methods=["GET"])
@jwt_required()
def get_personal_zenodo_credential(environment):
    user_id = int(get_jwt_identity())
    credential = credential_service.get_active_credential(user_id, environment) or credential_service.get_credential("user", user_id, environment)
    return APIResponse.success(data={"credential": credential_service.serialize_for_user(credential, user_id)})


@auth_bp.route("/me/zenodo-credentials", methods=["GET"])
@jwt_required()
def list_personal_zenodo_credentials():
    user_id = int(get_jwt_identity())
    environment = request.args.get("environment")
    return APIResponse.success(data=credential_service.list_available_credentials(user_id, environment))


@auth_bp.route("/me/zenodo-credentials", methods=["POST"])
@jwt_required()
def create_personal_zenodo_credential():
    user_id = int(get_jwt_identity())
    payload = request.get_json() or {}
    credential = credential_service.create_credential(
        user_id=user_id,
        environment=payload.get("environment"),
        token=payload.get("token"),
        name=payload.get("name"),
        actor_user_id=user_id,
    )
    return APIResponse.created(
        data={"credential": credential_service.serialize_for_user(credential, user_id)},
        message="Zenodo credential created successfully",
    )


@auth_bp.route("/me/zenodo-credentials/<environment>", methods=["PUT"])
@jwt_required()
def upsert_personal_zenodo_credential(environment):
    user_id = int(get_jwt_identity())
    payload = request.get_json() or {}
    token = payload.get("token")
    credential = credential_service.upsert_credential(
        owner_type="user",
        owner_id=user_id,
        environment=environment,
        token=token,
        name=payload.get("name"),
        actor_user_id=user_id,
    )
    return APIResponse.success(
        data={"credential": credential_service.serialize_for_user(credential, user_id)},
        message="Zenodo credential saved successfully",
    )


@auth_bp.route("/me/zenodo-credentials/<int:credential_id>", methods=["PATCH"])
@jwt_required()
def rename_personal_zenodo_credential(credential_id):
    user_id = int(get_jwt_identity())
    payload = request.get_json() or {}
    credential = credential_service.rename_credential(
        credential_id=credential_id,
        user_id=user_id,
        name=payload.get("name"),
    )
    return APIResponse.success(
        data={"credential": credential_service.serialize_for_user(credential, user_id)},
        message="Zenodo credential updated successfully",
    )


@auth_bp.route("/me/zenodo-credentials/<int:credential_id>", methods=["DELETE"])
@jwt_required()
def delete_personal_zenodo_credential_by_id(credential_id):
    user_id = int(get_jwt_identity())
    deleted = credential_service.delete_owned_credential_by_id(
        credential_id=credential_id,
        user_id=user_id,
        actor_user_id=user_id,
    )
    if not deleted:
        return APIResponse.not_found("Zenodo credential not found")
    return APIResponse.success(message="Zenodo credential deleted successfully")


@auth_bp.route("/me/zenodo-credentials/<environment>", methods=["DELETE"])
@jwt_required()
def delete_personal_zenodo_credential(environment):
    user_id = int(get_jwt_identity())
    deleted = credential_service.delete_credential(
        owner_type="user",
        owner_id=user_id,
        environment=environment,
        actor_user_id=user_id,
    )
    if not deleted:
        return APIResponse.not_found("Zenodo credential not found")
    return APIResponse.success(message="Zenodo credential deleted successfully")


@auth_bp.route("/me/zenodo-credentials/<environment>/validate", methods=["POST"])
@jwt_required()
def validate_personal_zenodo_credential(environment):
    user_id = int(get_jwt_identity())
    credential = credential_service.get_active_credential(user_id, environment) or credential_service.require_credential("user", user_id, environment)
    credential = credential_service.validate_accessible_credential(
        credential_id=credential.id,
        actor_user_id=user_id,
    )
    return APIResponse.success(
        data={"credential": credential_service.serialize_for_user(credential, user_id)},
        message="Zenodo credential validation completed",
    )


@auth_bp.route("/me/zenodo-credentials/<int:credential_id>/validate", methods=["POST"])
@jwt_required()
def validate_personal_zenodo_credential_by_id(credential_id):
    user_id = int(get_jwt_identity())
    credential = credential_service.validate_accessible_credential(
        credential_id=credential_id,
        actor_user_id=user_id,
    )
    return APIResponse.success(
        data={"credential": credential_service.serialize_for_user(credential, user_id)},
        message="Zenodo credential validation completed",
    )


@auth_bp.route("/me/zenodo-credentials/<int:credential_id>/share", methods=["POST"])
@jwt_required()
def share_personal_zenodo_credential(credential_id):
    user_id = int(get_jwt_identity())
    payload = request.get_json() or {}
    share = credential_service.share_credential(
        credential_id=credential_id,
        owner_user_id=user_id,
        recipient_email=payload.get("recipient_email") or payload.get("email"),
    )
    return APIResponse.created(
        data={"share": credential_service.serialize_share(share, viewer_user_id=user_id)},
        message="Zenodo credential share invitation created",
    )


@auth_bp.route("/me/zenodo-active-credentials/<environment>", methods=["PUT"])
@jwt_required()
def set_active_personal_zenodo_credential(environment):
    user_id = int(get_jwt_identity())
    payload = request.get_json() or {}
    credential = credential_service.set_active_credential(
        user_id=user_id,
        environment=environment,
        credential_id=payload.get("credential_id"),
    )
    return APIResponse.success(
        data={"credential": credential_service.serialize_for_user(credential, user_id)},
        message="Active Zenodo credential updated",
    )


@auth_bp.route("/me/zenodo-credential-shares/<int:share_id>/accept", methods=["POST"])
@jwt_required()
def accept_personal_zenodo_credential_share(share_id):
    user_id = int(get_jwt_identity())
    share = credential_service.respond_to_share(share_id=share_id, user_id=user_id, status="accepted")
    return APIResponse.success(
        data={"share": credential_service.serialize_share(share, viewer_user_id=user_id)},
        message="Zenodo credential share accepted",
    )


@auth_bp.route("/me/zenodo-credential-shares/<int:share_id>/decline", methods=["POST"])
@jwt_required()
def decline_personal_zenodo_credential_share(share_id):
    user_id = int(get_jwt_identity())
    share = credential_service.respond_to_share(share_id=share_id, user_id=user_id, status="declined")
    return APIResponse.success(
        data={"share": credential_service.serialize_share(share, viewer_user_id=user_id)},
        message="Zenodo credential share declined",
    )


@auth_bp.route("/me/zenodo-credential-shares/<int:share_id>", methods=["DELETE"])
@jwt_required()
def revoke_personal_zenodo_credential_share(share_id):
    user_id = int(get_jwt_identity())
    share = credential_service.revoke_share(share_id=share_id, owner_user_id=user_id)
    return APIResponse.success(
        data={"share": credential_service.serialize_share(share, viewer_user_id=user_id)},
        message="Zenodo credential share revoked",
    )
