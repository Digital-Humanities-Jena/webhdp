# routes/auth_routes.py
import hashlib
import hmac
import logging
import os
import secrets
import time
from datetime import datetime, timedelta

from flask import Blueprint, request, current_app, json
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required, get_jwt, verify_jwt_in_request
from flask_jwt_extended.exceptions import JWTExtendedException
from sqlalchemy.exc import IntegrityError

from api_utils import APIResponse
from database.models import User, UserMfaChallenge, UserZenodoActiveCredential
from exceptions import AppException, ValidationError
from services.audit_service import record_audit_event
from services.auth_throttle import check_auth_limit, clear_account_auth_limit, record_auth_attempt
from services.email_identity import normalize_email
from services.institution_service import InstitutionService
from services.model_publication_accounts import (
    DEMO_CLAIM, DEMO_USERNAME, demo_expiry, demo_sign_in_allowed, demo_username_email, is_demo,
    is_generated_demo_email,
)
from services.recovery_code_service import (
    find_valid_recovery_code,
    mark_recovery_code_used,
    recovery_code_status,
    regenerate_user_recovery_codes,
)
from services.hpc_resource_request_service import HpcResourceRequestService
from services.registration_service import confirm_signup, send_signup_link
from services.registry_lock import OperationConflict
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


def _auth_limit_response(retry_after, *, recovery=False):
    if not retry_after:
        return None
    code, message = (
        ("MFA_RECOVERY_RATE_LIMITED", "Too many recovery code attempts. Try again later.")
        if recovery else ("RATE_LIMITED", "Too many authentication attempts. Try again later.")
    )
    response, status = APIResponse.error(code, message, 429, details={"retry_after_seconds": retry_after})
    response.headers["Retry-After"] = str(retry_after)
    return response, status


def _check_rate_limit(action, identifier=None):
    return _auth_limit_response(check_auth_limit(action, identifier))


def _consume_rate_limit(action, identifier=None):
    return _auth_limit_response(record_auth_attempt(action, identifier, consume=True))


def _record_rate_limit_event(action, identifier=None, *, failed=True):
    if failed:
        record_auth_attempt(action, identifier)


def _clear_rate_limit(action, identifier=None):
    clear_account_auth_limit(action, identifier)


def _check_recovery_rate_limit(identifier=None):
    return _auth_limit_response(check_auth_limit("mfa_recovery", identifier), recovery=True)


def _record_recovery_rate_limit_failure(identifier=None):
    record_auth_attempt("mfa_recovery", identifier)


def _clear_recovery_rate_limit(identifier=None):
    clear_account_auth_limit("mfa_recovery", identifier)


def _serialize_membership(membership):
    payload = membership.to_dict()
    payload["institution"] = membership.institution.to_dict() if getattr(membership, "institution", None) else None
    return payload


def _serialize_user_context(user: User) -> dict:
    if is_demo(user):
        return {
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role.value,
            "model_publication_only": True,
            "model_publication_expires_at": demo_expiry(user.id),
        }
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
        "model_publication_only": False,
        "memberships": [_serialize_membership(membership) for membership in memberships],
        "institutions": institutions,
        "default_institution": user.default_institution.to_dict() if getattr(user, "default_institution", None) else None,
        "zenodo_credentials_configured": UserZenodoActiveCredential.query.filter_by(user_id=user.id).count() > 0,
        "hpc": hpc_request_service.access_summary_for_user(user),
    }


def _create_access_token_for_user(user: User) -> str:
    demo = is_demo(user)
    return create_access_token(
        identity=str(user.id),
        expires_delta=timedelta(seconds=max(1, demo_expiry(user.id) - time.time())) if demo else None,
        additional_claims={
            "token_version": int(user.token_version or 0),
            "force_password_change": bool(user.force_password_change),
            **({DEMO_CLAIM: True} if demo else {}),
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
        logger.error("Email service is not available for email login MFA")
        return False
    expires_minutes = max(1, int((_mfa_ttl_seconds() + 59) / 60))
    return bool(email_service.send_login_mfa_code_email(user.email, code, expires_minutes))


def _create_email_mfa_challenge(user: User, method: str = "email") -> tuple[UserMfaChallenge, str, str]:
    now = datetime.utcnow()
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    code = _generate_mfa_code()
    UserMfaChallenge.query.filter(
        UserMfaChallenge.user_id == user.id,
        UserMfaChallenge.method == method,
        UserMfaChallenge.consumed_at.is_(None),
    ).update({"consumed_at": now, "updated_at": now}, synchronize_session=False)
    challenge = UserMfaChallenge(
        user_id=user.id,
        method=method,
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
    if challenge.user and is_demo(challenge.user) and not demo_sign_in_allowed(challenge.user):
        return None, APIResponse.error("DEMO_CLOSED", "The live demonstration is currently closed.", 403)
    if challenge.attempts >= _mfa_max_attempts():
        return None, APIResponse.error("MFA_CHALLENGE_LOCKED", "Too many verification attempts. Please sign in again.", 429)
    return challenge, None


class IdentityPayloadTooLarge(AppException):
    status_code = 413
    error_code = "AUTH_PAYLOAD_TOO_LARGE"
    user_message = "Authentication requests must be 16 KiB or smaller."


def _identity_payload():
    if not request.is_json:
        raise ValidationError("Provide a JSON object.")
    maximum_bytes = 16 * 1024
    body = request.stream.read(maximum_bytes + 1)
    if len(body) > maximum_bytes:
        raise IdentityPayloadTooLarge()
    try:
        data = json.loads(body)
    except (ValueError, RecursionError) as exc:
        raise ValidationError("Provide a valid JSON object.") from exc
    if not isinstance(data, dict):
        raise ValidationError("Provide a JSON object.")
    return data


def _registration_busy():
    return APIResponse.error(
        "REGISTRATION_BUSY", "This request is already being processed. Try again in a moment.",
        429, details={"retry_after_seconds": 3},
    )


def _request_signup_link():
    email = _identity_payload().get("email")
    key = normalize_email(email)
    limited_response = _consume_rate_limit("register", key)
    if limited_response:
        return limited_response
    try:
        delivered = send_signup_link(email)
    except OperationConflict:
        return _registration_busy()
    if not delivered:
        return APIResponse.error(
            "VERIFICATION_EMAIL_UNAVAILABLE",
            "WebHDP could not send the verification email. Try requesting a new link later.",
            503,
        )
    return APIResponse.accepted(
        data={"accepted": True},
        message="If you can register with this address, you’ll receive an email with a link to continue.",
    )


@auth_bp.post("/register")
def register():
    """Start registration for a WebHDP account."""
    return _request_signup_link()


@auth_bp.post("/resend-verification")
def resend_verification():
    """Request another registration verification link."""
    return _request_signup_link()


@auth_bp.post("/verify-email")
def verify_email():
    """Confirm email ownership and set the new account's password."""
    limited_response = _consume_rate_limit("verify_email")
    if limited_response:
        return limited_response
    data = _identity_payload()
    try:
        user = confirm_signup(data.get("token"), data.get("password"))
    except (OperationConflict, IntegrityError):
        return _registration_busy()
    if not user:
        return APIResponse.error(
            "INVALID_EMAIL_VERIFICATION_LINK",
            "This verification link is invalid, expired or already used. Request a new link to continue.",
            400,
        )

    return APIResponse.success(message="Email verified successfully. You can now log in.")


@auth_bp.get("/verify-email/<token>")
def legacy_email_verification(token):
    """Retire historical verification links without activating an account."""
    return APIResponse.error(
        "INVALID_EMAIL_VERIFICATION_LINK",
        "This verification link has been retired. Request a new link to continue.",
        410,
    )


@auth_bp.route("/login", methods=["POST"])
def login():
    """Authenticate with a password, followed by email verification when enabled by the user."""
    data = _identity_payload()

    raw_identifier = data.get("email")
    password = data.get("password")
    if not isinstance(raw_identifier, str) or not isinstance(password, str):
        raise ValidationError("Email and password are required")
    identifier = raw_identifier.strip()
    uses_demo_username = identifier.casefold() == DEMO_USERNAME
    action = "demo_login" if uses_demo_username or is_generated_demo_email(identifier) else "login"
    try:
        account_limit_key = normalize_email(identifier) if action == "login" else None
    except ValidationError:
        # Keep sign-in available to legacy accounts with a nonstandard stored address.
        account_limit_key = identifier
    limited_response = _check_rate_limit(action, account_limit_key)
    if limited_response:
        return limited_response

    if not identifier or not password:
        raise ValidationError("Email and password are required")
    try:
        password.encode("utf-8")
    except UnicodeError as exc:
        raise ValidationError("Invalid email or password") from exc

    email = demo_username_email() if uses_demo_username else identifier
    user = user_service.authenticate(email=email, password=password) if email else None
    if not user:
        _record_rate_limit_event(action, account_limit_key, failed=True)
        raise ValidationError("Invalid email or password")

    if is_demo(user) and not demo_sign_in_allowed(user):
        return APIResponse.error("DEMO_CLOSED", "The live demonstration is currently closed.", 403)

    if not user.is_verified:
        _record_rate_limit_event(action, account_limit_key, failed=True)
        return APIResponse.error("EMAIL_NOT_VERIFIED", "Please verify your email address before logging in", 403)

    if not user.mfa_enabled:
        _clear_rate_limit(action, account_limit_key)
        return APIResponse.success(
            data={"user": _serialize_user_context(user), "access_token": _create_access_token_for_user(user)},
            message="Login successful",
        )

    challenge, token, code = _create_email_mfa_challenge(user)
    delivered, delivery_mode = _deliver_login_mfa_code(user, code)
    if not delivered:
        db.session.rollback()
        return APIResponse.error("MFA_EMAIL_FAILED", "Unable to send the verification code email. Please try again later.", 500)
    db.session.commit()
    _clear_rate_limit(action, account_limit_key)
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


@auth_bp.route("/me/mfa", methods=["POST"])
@jwt_required()
def configure_mfa():
    """Start email enrollment or disable optional two-factor authentication."""
    user = user_service.get_by_id(int(get_jwt_identity()))
    data = request.get_json() or {}
    limited = _check_rate_limit("mfa_settings", str(user.id))
    if limited:
        return limited
    if not user.check_password(str(data.get("current_password") or "")):
        _record_rate_limit_event("mfa_settings", str(user.id), failed=True)
        raise ValidationError("Current password is incorrect")
    if not isinstance(data.get("enabled"), bool):
        raise ValidationError("enabled must be a boolean")
    if not data["enabled"]:
        user.mfa_enabled = False
        UserMfaChallenge.query.filter_by(user_id=user.id, consumed_at=None).update(
            {"consumed_at": datetime.utcnow()}, synchronize_session=False
        )
        record_audit_event(actor_user_id=user.id, event_type="auth.mfa_disabled", entity_type="user", entity_id=user.id)
        db.session.commit()
        return APIResponse.success(data={"user": _serialize_user_context(user)}, message="Two-factor authentication disabled")
    limited = _check_rate_limit("mfa_enrollment", user.email)
    if limited:
        return limited
    _record_rate_limit_event("mfa_enrollment", user.email, failed=True)
    challenge, token, code = _create_email_mfa_challenge(user, method="email_setup")
    delivered, delivery = _deliver_login_mfa_code(user, code)
    if not delivered:
        db.session.rollback()
        return APIResponse.error("MFA_EMAIL_FAILED", "Unable to send a verification email. Two-factor authentication has not been changed.", 503)
    db.session.commit()
    return APIResponse.success(data=_attach_development_mfa_code(_mfa_response_payload(challenge, token, user), code, delivery), status_code=202)


@auth_bp.route("/me/mfa/verify", methods=["POST"])
@jwt_required()
def verify_mfa_enrollment():
    """Enable two-factor authentication only after proving email access."""
    user = user_service.get_by_id(int(get_jwt_identity()))
    data = request.get_json() or {}
    challenge = UserMfaChallenge.query.filter_by(
        token_hash=_hash_token(str(data.get("mfa_token") or "")), user_id=user.id, method="email_setup"
    ).first()
    challenge, error = _validate_mfa_challenge(challenge)
    if error:
        return error
    code = str(data.get("code") or "").strip()
    if not hmac.compare_digest(challenge.code_hash, _hash_mfa_code(code, challenge.token_hash)):
        challenge.attempts += 1
        db.session.commit()
        return APIResponse.error("MFA_CODE_INVALID", "Invalid verification code", 400)
    challenge.consumed_at = datetime.utcnow()
    user.mfa_enabled = True
    record_audit_event(actor_user_id=user.id, event_type="auth.mfa_enabled", entity_type="user", entity_id=user.id)
    db.session.commit()
    return APIResponse.success(data={"user": _serialize_user_context(user)}, message="Two-factor authentication enabled")


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
