"""Issue, revoke, and accept email-bound institutional invitations."""

import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from math import ceil

from database.database import db
from database.models import AuditEvent, InstitutionInvitation, InstitutionRole, User, UserRole
from exceptions import AppException, ResourceNotFoundError, SecurityError, ValidationError
from services.audit_service import record_audit_event
from services.email_identity import email_for_delivery, normalize_email
from services.institution_service import InstitutionService, institution_membership_lock
from services.model_publication_accounts import is_demo
from services.user_service import UserService


INVITATION_LIFETIME = timedelta(days=7)
RESEND_COOLDOWN = timedelta(minutes=1)
DELIVERY_WINDOW = timedelta(hours=1)
INSTITUTION_DELIVERY_LIMIT = 60
DELIVERY_REQUESTED = "institution_invitation_delivery_requested"
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")
logger = logging.getLogger(__name__)


class InvalidInvitation(ResourceNotFoundError):
    error_code = "INVITATION_INVALID"
    user_message = "This invitation is no longer available. Ask your institution for a new invitation."


class InvitationEmailMismatch(SecurityError):
    error_code = "INVITATION_EMAIL_MISMATCH"
    user_message = "Sign in with the verified email address that received the invitation."


class InvitationAccountAmbiguous(AppException):
    status_code = 409
    error_code = "EMAIL_IDENTITY_AMBIGUOUS"
    user_message = "More than one account matches this address. Contact account support."


class InvitationAlreadyAccepted(AppException):
    status_code = 409
    error_code = "INVITATION_ALREADY_ACCEPTED"
    user_message = "This invitation was accepted. Manage access from the membership list."


class InvitationRateLimited(AppException):
    status_code = 429
    error_code = "INVITATION_RATE_LIMITED"
    user_message = "An invitation can be sent again after the waiting period."

    def __init__(self, wait):
        self.retry_after = max(1, ceil(wait.total_seconds()))
        super().__init__(details={"retry_after_seconds": self.retry_after})


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _timestamp(value):
    return (value.isoformat(timespec="seconds") + "Z") if value else None


def _digest(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _token_digest(token):
    if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token):
        raise InvalidInvitation()
    return _digest(token)


def _status(invitation, now):
    if invitation.accepted_at:
        return "accepted"
    if invitation.revoked_at:
        return "revoked"
    if invitation.expires_at <= now:
        return "expired"
    return "pending"


def _invitation_data(invitation, now):
    return {
        "id": invitation.id,
        "email": invitation.delivery_email,
        "role": invitation.role,
        "status": _status(invitation, now),
        "delivery": invitation.delivery_status,
        "created_at": _timestamp(invitation.created_at),
        "expires_at": _timestamp(invitation.expires_at),
        "last_sent_at": _timestamp(invitation.delivery_attempted_at) if invitation.delivery_status == "sent" else None,
    }


def _institution_data(institution):
    return {"id": institution.id, "name": institution.display_name or institution.name, "slug": institution.slug}


def _audit(invitation, actor, event_type, **details):
    record_audit_event(
        actor_user_id=actor.id,
        institution_id=invitation.institution_id,
        event_type=event_type,
        entity_type="institution_invitation",
        entity_id=invitation.id,
        details={"role": invitation.role, **details},
    )


class InstitutionInvitationService:
    def __init__(self):
        self.institutions = InstitutionService()
        self.users = UserService()

    @staticmethod
    def _verified_account(user):
        if not user or not user.is_verified or user.force_password_change or is_demo(user):
            raise SecurityError("A verified WebHDP account is required.")

    def _manager(self, institution_id, actor):
        self._verified_account(actor)
        institution = self.institutions.get_by_id(institution_id)
        self.institutions.require_membership_manager(institution_id, actor)
        return institution

    def _manages_owners(self, institution_id, actor):
        return actor.role == UserRole.ADMIN or self.institutions.has_role(
            self.institutions.get_membership(institution_id, actor.id), "owner"
        )

    def list(self, institution_id, actor, *, limit, offset):
        self._manager(institution_id, actor)
        query = InstitutionInvitation.query.filter_by(institution_id=institution_id)
        if not self._manages_owners(institution_id, actor):
            query = query.filter(InstitutionInvitation.role != InstitutionRole.OWNER.value)
        now = _now()
        rows = query.order_by(InstitutionInvitation.created_at.desc(), InstitutionInvitation.id.desc())
        return {"invitations": [_invitation_data(row, now) for row in rows.offset(offset).limit(limit)], "total": query.count()}

    @staticmethod
    def _check_delivery_limit(institution_id, now):
        recent = AuditEvent.query.filter(
            AuditEvent.institution_id == institution_id,
            AuditEvent.event_type == DELIVERY_REQUESTED,
            AuditEvent.created_at > now - DELIVERY_WINDOW,
        )
        if recent.count() >= INSTITUTION_DELIVERY_LIMIT:
            first = recent.order_by(AuditEvent.created_at.asc()).first()
            raise InvitationRateLimited(first.created_at + DELIVERY_WINDOW - now)

    def issue(self, institution_id, actor, *, email, role, delivery):
        recipient = normalize_email(email)
        address = email_for_delivery(email)
        try:
            requested_role = InstitutionRole(role)
        except (TypeError, ValueError):
            raise ValidationError("Choose a valid institution role.") from None
        now = _now()
        with institution_membership_lock(institution_id):
            institution = self._manager(institution_id, actor)
            invited_role = self.institutions.validate_membership_role(institution_id, requested_role, actor=actor)
            self._check_delivery_limit(institution_id, now)
            invitation = InstitutionInvitation.query.filter_by(
                institution_id=institution_id, recipient_email=recipient, accepted_at=None, revoked_at=None
            ).filter(InstitutionInvitation.expires_at > now).order_by(InstitutionInvitation.created_at.desc()).first()
            if invitation is not None:
                self.institutions.validate_membership_role(institution_id, invitation.role, actor=actor)
                if invitation.delivery_attempted_at + RESEND_COOLDOWN > now:
                    raise InvitationRateLimited(invitation.delivery_attempted_at + RESEND_COOLDOWN - now)
            else:
                invitation = InstitutionInvitation(
                    institution_id=institution_id, recipient_email=recipient, created_at=now,
                    delivery_email=address, role=invited_role.value, issued_by_user_id=actor.id,
                    expires_at=now + INVITATION_LIFETIME,
                )
                db.session.add(invitation)

            token = secrets.token_urlsafe(32)
            issuer_id = actor.id
            invitation.delivery_attempted_at = now
            invitation.delivery_status = "sending"
            db.session.flush()
            _audit(invitation, actor, DELIVERY_REQUESTED, role=invited_role.value)
            invitation_id = invitation.id
            institution_name = institution.display_name or institution.name
            db.session.commit()

        try:
            sent = delivery(address, token, institution_name, invited_role.value)
        except Exception as error:
            logger.warning("Institution invitation delivery failed (%s)", type(error).__name__)
            sent = False
        status = "sent" if sent else "failed"
        outcome = {"delivery_status": status}
        if sent:
            outcome.update(
                token_hash=_digest(token), delivery_email=address, role=invited_role.value,
                issued_by_user_id=issuer_id, expires_at=now + INVITATION_LIFETIME,
            )
        # Keep an existing link usable during delivery failures. A later resend,
        # revocation or acceptance wins over a delayed mail response.
        InstitutionInvitation.query.filter_by(
            id=invitation_id, delivery_attempted_at=now, accepted_at=None, revoked_at=None,
        ).update(outcome, synchronize_session=False)
        db.session.commit()
        invitation = db.session.get(InstitutionInvitation, invitation_id, populate_existing=True)
        return {"invitation": _invitation_data(invitation, _now()), "delivery": status}

    def revoke(self, institution_id, invitation_id, actor):
        with institution_membership_lock(institution_id):
            self._manager(institution_id, actor)
            invitation = InstitutionInvitation.query.filter_by(institution_id=institution_id, id=invitation_id).first()
            if invitation is None:
                raise ResourceNotFoundError("Invitation not found.")
            if invitation.role == InstitutionRole.OWNER.value and not self._manages_owners(institution_id, actor):
                raise ResourceNotFoundError("Invitation not found.")
            if invitation.accepted_at:
                raise InvitationAlreadyAccepted()
            now = _now()
            if invitation.revoked_at is None:
                invitation.revoked_at = now
                invitation.token_hash = None
                _audit(invitation, actor, "institution_invitation_revoked")
                db.session.commit()
            return _invitation_data(invitation, now)

    def _validate_invitation(self, invitation, actor, now):
        self._verified_account(actor)
        if invitation is None or _status(invitation, now) != "pending":
            raise InvalidInvitation()
        try:
            recipient = normalize_email(actor.email)
        except ValidationError:
            raise InvitationEmailMismatch() from None
        if recipient != invitation.recipient_email:
            raise InvitationEmailMismatch()
        accounts = self.users.find_accounts_for_email(recipient)
        if len(accounts) != 1 or accounts[0].id != actor.id:
            raise InvitationAccountAmbiguous()

        issuer = db.session.get(User, invitation.issued_by_user_id) if invitation.issued_by_user_id is not None else None
        try:
            institution = self._manager(invitation.institution_id, issuer)
            self.institutions.validate_membership_role(institution.id, invitation.role, actor=issuer)
        except (ResourceNotFoundError, SecurityError, ValidationError):
            raise InvalidInvitation() from None
        return institution, issuer

    def preview(self, token, actor):
        self._verified_account(actor)
        invitation = InstitutionInvitation.query.filter_by(token_hash=_token_digest(token)).first()
        institution, _ = self._validate_invitation(invitation, actor, _now())
        membership = self.institutions.get_membership(institution.id, actor.id)
        return {
            "institution": _institution_data(institution),
            "role": invitation.role,
            "expires_at": _timestamp(invitation.expires_at),
            "current_role": membership.role.value if membership else None,
        }

    def accept(self, token, actor):
        self._verified_account(actor)
        digest = _token_digest(token)
        identity = db.session.query(InstitutionInvitation.id, InstitutionInvitation.institution_id).filter_by(
            token_hash=digest
        ).first()
        if identity is None:
            raise InvalidInvitation()
        with institution_membership_lock(identity.institution_id):
            db.session.refresh(actor)
            invitation = db.session.get(InstitutionInvitation, identity.id, populate_existing=True)
            if invitation is None or invitation.token_hash != digest:
                raise InvalidInvitation()
            now = _now()
            institution, issuer = self._validate_invitation(invitation, actor, now)
            membership = self.institutions.get_membership(institution.id, actor.id)
            already_member = membership is not None
            if membership is None:
                membership = self.institutions.upsert_membership(
                    institution.id, actor.id, invitation.role, actor=issuer, commit=False, notify_change=False
                )
            invitation.accepted_at = now
            invitation.accepted_by_user_id = actor.id
            invitation.token_hash = None
            _audit(invitation, actor, "institution_invitation_accepted", membership_id=membership.id)
            db.session.commit()
            return {
                "institution": _institution_data(institution),
                "membership": {"id": membership.id, "role": membership.role.value, "institution_id": institution.id},
                "already_member": already_member,
            }
