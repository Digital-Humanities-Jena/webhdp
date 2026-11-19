"""Email ownership challenges for ordinary WebHDP registration."""

from datetime import datetime, timedelta
import hashlib
import os
import re
import secrets

from flask import current_app
from sqlalchemy.exc import IntegrityError

from database.database import db
from database.models import UserEmailVerification, UserRole
from services.email_identity import email_for_delivery, normalize_email
from services.model_publication_accounts import is_demo, is_generated_demo_email
from services.registry_lock import registry_lock
from services.user_service import UserService, validate_new_password


_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
_USERS = UserService()


def _hash(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _identity_lock(key):
    # A fixed number of shared locks bounds filesystem entries for public requests.
    return registry_lock(f"registration:{_hash(key)[:3]}")


def _eligible_pending_account(accounts):
    return len(accounts) == 1 and accounts[0].role == UserRole.USER and not accounts[0].is_verified and not is_demo(accounts[0])


def _configured_seconds(name, default, minimum, maximum):
    value = current_app.config.get(name, os.environ.get(name, default))
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def send_signup_link(email):
    """Issue a new link following cooldown. A known send failure keeps any previous link."""
    delivery_email = email_for_delivery(email)
    key = normalize_email(delivery_email)
    if is_generated_demo_email(key):
        return True

    cooldown = _configured_seconds("REGISTRATION_EMAIL_RESEND_SECONDS", 60, 0, 600)
    ttl = _configured_seconds("REGISTRATION_EMAIL_TTL_SECONDS", 86400, 60, 172800)

    with _identity_lock(key):
        accounts = _USERS.find_accounts_for_email(key)
        if accounts and not _eligible_pending_account(accounts):
            return True
        if accounts:
            delivery_email = email_for_delivery(accounts[0].email)
        now = datetime.utcnow()
        challenges = UserEmailVerification.query.filter_by(canonical_email=key)
        if challenges.filter(UserEmailVerification.created_at > now - timedelta(seconds=cooldown)).first():
            return True

        token = secrets.token_urlsafe(32)
        challenge = UserEmailVerification(
            canonical_email=key, delivery_email=delivery_email, token_hash=_hash(token),
            created_at=now, expires_at=now + timedelta(seconds=ttl),
        )
        UserEmailVerification.query.filter(UserEmailVerification.expires_at <= now).delete(synchronize_session=False)
        db.session.add(challenge)
        db.session.commit()
        challenge_id = challenge.id
        email_service = getattr(current_app, "email_service", None)
        try:
            delivered = email_service is not None and email_service.send_verification_email(delivery_email, token) is True
        except Exception as exc:
            current_app.logger.warning("Registration email delivery failed (%s).", type(exc).__name__)
            delivered = False
        if delivered:
            challenges.filter(UserEmailVerification.id != challenge_id).delete(synchronize_session=False)
        else:
            db.session.delete(challenge)
        db.session.commit()
        return delivered


def confirm_signup(token, password):
    """Set the password through a verified email challenge, consuming it atomically."""
    validate_new_password(password)
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        return None

    token_hash = _hash(token)
    identity = db.session.query(UserEmailVerification.canonical_email).filter_by(token_hash=token_hash).scalar()
    db.session.rollback()
    if not identity:
        return None

    with _identity_lock(identity):
        pending = UserEmailVerification.query.filter(
            UserEmailVerification.token_hash == token_hash,
            UserEmailVerification.expires_at > datetime.utcnow(),
        ).first()
        if not pending:
            return None
        accounts = _USERS.find_accounts_for_email(identity)
        if accounts and not _eligible_pending_account(accounts):
            return None
        try:
            if accounts:
                user = accounts[0]
                user.is_verified = True
                user.canonical_email = identity
                user.legacy_canonical_email = None
                user.verification_token = None
                user.set_password(password)
                user.token_version = int(user.token_version or 0) + 1
                user.force_password_change = False
                user.onboarding_required = not (user.onboarding_completed_at or user.onboarding_skipped_at)
                _USERS.invalidate_pending_mfa(user)
            else:
                user = _USERS.add_user(pending.delivery_email, password, verified=True)
            UserEmailVerification.query.filter_by(canonical_email=identity).delete(synchronize_session=False)
            db.session.commit()
        except IntegrityError:
            # An intervening account or slug creation can win the unique constraint.
            # Roll back both changes so an eligible address can try again.
            db.session.rollback()
            raise
    _USERS.notify_registration(user)
    return user
