import json
from datetime import datetime
from typing import Any

import requests

from database.database import db
from database.models import User, UserZenodoActiveCredential, ZenodoCredential, ZenodoCredentialShare
from exceptions import ResourceNotFoundError, SecurityError, ValidationError
from services.audit_service import record_audit_event
from services.credential_crypto import decrypt_secret, encrypt_secret
from services.notification_service import notify_user


VALID_ENVIRONMENTS = {"sandbox", "production"}
VALID_OWNER_TYPES = {"user", "institution"}
VALID_SHARE_STATUSES = {"pending", "accepted", "declined", "revoked"}
VALIDATION_MODE = "live_write_cleanup"
RECOMMENDED_SCOPES = ["deposit:write", "deposit:actions"]
CAPABILITY_KEYS = (
    "authentication",
    "deposit_read",
    "draft_create",
    "draft_cleanup",
)


def normalize_environment(environment: str) -> str:
    value = str(environment or "").strip().lower()
    if value not in VALID_ENVIRONMENTS:
        raise ValidationError("environment must be 'sandbox' or 'production'")
    return value


def mask_secret(value: str) -> str:
    text = str(value or "").strip()
    if len(text) <= 8:
        return "*" * len(text or "********")
    return f"{text[:4]}...{text[-4:]}"


def _base_api_url(environment: str) -> str:
    return "https://sandbox.zenodo.org/api" if environment == "sandbox" else "https://zenodo.org/api"


def _safe_json(response) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_capability(status: str, message: str, *, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "status": status,
        "message": str(message or "").strip(),
    }
    if evidence:
        payload["evidence"] = evidence
    return payload


def _build_probe_evidence(
    environment: str,
    probe: str,
    *,
    status_code: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    evidence = {
        "probe": probe,
        "base_api_url": _base_api_url(environment),
    }
    if status_code is not None:
        evidence["status_code"] = int(status_code)
    if error:
        evidence["error"] = str(error)
    return evidence


def _build_validation_report(
    *,
    environment: str,
    aggregate_status: str,
    summary: str,
    capabilities: dict[str, Any],
) -> dict[str, Any]:
    normalized_capabilities = {key: capabilities.get(key) for key in CAPABILITY_KEYS}
    return {
        "mode": VALIDATION_MODE,
        "environment": environment,
        "aggregate_status": aggregate_status,
        "summary": summary,
        "recommended_scopes": list(RECOMMENDED_SCOPES),
        "capabilities": normalized_capabilities,
    }


def _derive_top_level_message(report: dict[str, Any]) -> str | None:
    summary = str((report or {}).get("summary") or "").strip()
    return summary or None


def _extract_response_message(response) -> str:
    payload = _safe_json(response)
    message = str(payload.get("message") or payload.get("error") or "").strip()
    if message:
        return message
    return str(getattr(response, "text", "") or "").strip()


def _failed_capabilities(status: str, message: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _build_capability(status, message, evidence=evidence)
        for key in CAPABILITY_KEYS
    }


def _default_credential_name(environment: str) -> str:
    return f"{str(environment or '').strip().capitalize() or 'Zenodo'} API key"


def _serialize_user_reference(user: User | None) -> dict[str, Any] | None:
    if not user:
        return None
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "full_name": user.full_name,
    }


class ZenodoCredentialService:
    def _normalize_owner_type(self, owner_type: str) -> str:
        normalized_owner_type = str(owner_type or "").strip().lower()
        if normalized_owner_type not in VALID_OWNER_TYPES:
            raise ValidationError("owner_type must be 'user' or 'institution'")
        return normalized_owner_type

    def _normalize_name(self, name: str | None, environment: str) -> str:
        normalized = str(name or "").strip()
        if not normalized:
            normalized = _default_credential_name(environment)
        if len(normalized) > 120:
            raise ValidationError("Zenodo credential name must be 120 characters or fewer")
        return normalized

    def get_credential(self, owner_type: str, owner_id: int, environment: str) -> ZenodoCredential | None:
        normalized_owner_type = self._normalize_owner_type(owner_type)
        normalized_environment = normalize_environment(environment)
        return ZenodoCredential.query.filter_by(
            owner_type=normalized_owner_type,
            owner_id=int(owner_id),
            environment=normalized_environment,
        ).order_by(ZenodoCredential.id.asc()).first()

    def get_credential_by_id(self, credential_id: int) -> ZenodoCredential | None:
        try:
            normalized_id = int(credential_id)
        except (TypeError, ValueError):
            raise ValidationError("credential_id must be an integer")
        return db.session.get(ZenodoCredential, normalized_id)

    def require_credential(self, owner_type: str, owner_id: int, environment: str) -> ZenodoCredential:
        credential = self.get_credential(owner_type, owner_id, environment)
        if not credential:
            raise ResourceNotFoundError("Zenodo credential not found")
        return credential

    def require_credential_by_id(self, credential_id: int) -> ZenodoCredential:
        credential = self.get_credential_by_id(credential_id)
        if not credential:
            raise ResourceNotFoundError("Zenodo credential not found")
        return credential

    def _accepted_share_for_user(self, credential_id: int, user_id: int) -> ZenodoCredentialShare | None:
        return ZenodoCredentialShare.query.filter_by(
            credential_id=int(credential_id),
            recipient_user_id=int(user_id),
            status="accepted",
        ).first()

    def _ensure_owned_by_user(self, credential: ZenodoCredential, user_id: int) -> None:
        if credential.owner_type != "user" or int(credential.owner_id) != int(user_id):
            raise SecurityError("Only the owner can manage this Zenodo credential")

    def _ensure_accessible_by_user(self, credential: ZenodoCredential, user_id: int) -> None:
        if credential.owner_type == "user" and int(credential.owner_id) == int(user_id):
            return
        if self._accepted_share_for_user(credential.id, user_id):
            return
        raise SecurityError("You do not have access to this Zenodo credential")

    def get_active_credential(self, user_id: int, environment: str) -> ZenodoCredential | None:
        normalized_environment = normalize_environment(environment)
        row = UserZenodoActiveCredential.query.filter_by(
            user_id=int(user_id),
            environment=normalized_environment,
        ).first()
        if row and row.credential and row.credential.environment == normalized_environment:
            try:
                self._ensure_accessible_by_user(row.credential, user_id)
            except SecurityError:
                db.session.delete(row)
                db.session.flush()
                return None
            return row.credential
        if row:
            db.session.delete(row)
            db.session.flush()
        return None

    def serialize_for_user(self, credential: ZenodoCredential | None, user_id: int | None = None) -> dict[str, Any] | None:
        if not credential:
            return None
        payload = credential.to_dict()
        payload["source"] = "owned"
        payload["active"] = False
        payload["owner"] = None
        payload["shared_by"] = None
        if credential.owner_type == "user":
            owner = db.session.get(User, int(credential.owner_id))
            payload["owner"] = _serialize_user_reference(owner)
            if user_id is not None and int(credential.owner_id) != int(user_id):
                share = self._accepted_share_for_user(credential.id, int(user_id))
                payload["source"] = "shared"
                payload["share_id"] = share.id if share else None
                payload["shared_by"] = _serialize_user_reference(share.shared_by if share else owner)
        elif credential.owner_type == "institution":
            payload["source"] = "institution"
        if user_id is not None:
            active = UserZenodoActiveCredential.query.filter_by(
                user_id=int(user_id),
                environment=credential.environment,
                credential_id=credential.id,
            ).first()
            payload["active"] = bool(active)
        return payload

    def decrypt_value(self, credential: ZenodoCredential) -> str:
        return decrypt_secret(credential.encrypted_value)

    def serialize(self, credential: ZenodoCredential | None) -> dict[str, Any] | None:
        return credential.to_dict() if credential else None

    def list_available_credentials(self, user_id: int, environment: str | None = None) -> dict[str, Any]:
        normalized_environment = normalize_environment(environment) if environment else None
        owned_query = ZenodoCredential.query.filter_by(owner_type="user", owner_id=int(user_id))
        if normalized_environment:
            owned_query = owned_query.filter(ZenodoCredential.environment == normalized_environment)
        owned_credentials = owned_query.order_by(ZenodoCredential.environment.asc(), ZenodoCredential.name.asc()).all()

        shared_query = (
            ZenodoCredentialShare.query.join(ZenodoCredential)
            .filter(
                ZenodoCredentialShare.recipient_user_id == int(user_id),
                ZenodoCredentialShare.status == "accepted",
            )
        )
        if normalized_environment:
            shared_query = shared_query.filter(ZenodoCredential.environment == normalized_environment)
        shared_credentials = [
            share.credential
            for share in shared_query.order_by(ZenodoCredentialShare.updated_at.desc()).all()
            if share.credential
        ]

        seen: set[int] = set()
        credentials = []
        for credential in [*owned_credentials, *shared_credentials]:
            if credential.id in seen:
                continue
            seen.add(credential.id)
            credentials.append(self.serialize_for_user(credential, user_id))

        active_rows = UserZenodoActiveCredential.query.filter_by(user_id=int(user_id)).all()
        active = {
            row.environment: self.serialize_for_user(row.credential, user_id) if row.credential else None
            for row in active_rows
            if row.environment in VALID_ENVIRONMENTS
        }
        for env_name in VALID_ENVIRONMENTS:
            active.setdefault(env_name, None)

        incoming_query = ZenodoCredentialShare.query.filter_by(recipient_user_id=int(user_id), status="pending")
        outgoing_query = ZenodoCredentialShare.query.join(ZenodoCredential).filter(
            ZenodoCredential.owner_type == "user",
            ZenodoCredential.owner_id == int(user_id),
            ZenodoCredentialShare.status.in_(["pending", "accepted"]),
        )
        if normalized_environment:
            incoming_query = incoming_query.join(ZenodoCredential, ZenodoCredentialShare.credential_id == ZenodoCredential.id).filter(
                ZenodoCredential.environment == normalized_environment
            )
            outgoing_query = outgoing_query.filter(ZenodoCredential.environment == normalized_environment)

        return {
            "credentials": credentials,
            "active": active,
            "incoming_shares": [self.serialize_share(row, viewer_user_id=user_id) for row in incoming_query.all()],
            "outgoing_shares": [self.serialize_share(row, viewer_user_id=user_id) for row in outgoing_query.all()],
        }

    def serialize_share(self, share: ZenodoCredentialShare, viewer_user_id: int | None = None) -> dict[str, Any]:
        payload = share.to_dict()
        payload["credential"] = self.serialize_for_user(share.credential, viewer_user_id) if share.credential else None
        payload["shared_by"] = _serialize_user_reference(share.shared_by)
        payload["recipient"] = _serialize_user_reference(share.recipient)
        return payload

    def upsert_credential(
        self,
        *,
        owner_type: str,
        owner_id: int,
        environment: str,
        token: str,
        actor_user_id: int | None,
        name: str | None = None,
        credential_id: int | None = None,
    ) -> ZenodoCredential:
        normalized_owner_type = self._normalize_owner_type(owner_type)
        normalized_environment = normalize_environment(environment)
        normalized_name = self._normalize_name(name, normalized_environment)
        normalized_token = str(token or "").strip()
        if not normalized_token:
            raise ValidationError("Zenodo token is required")

        credential = None
        if credential_id is not None:
            credential = self.require_credential_by_id(int(credential_id))
            if credential.owner_type != normalized_owner_type or int(credential.owner_id) != int(owner_id):
                raise SecurityError("Only the owner can update this Zenodo credential")
            if credential.environment != normalized_environment:
                raise ValidationError("Zenodo credential environment cannot be changed")
        else:
            credential = self.get_credential(normalized_owner_type, int(owner_id), normalized_environment)
        action = "updated" if credential else "created"
        if not credential:
            credential = ZenodoCredential(
                name=normalized_name,
                owner_type=normalized_owner_type,
                owner_id=int(owner_id),
                environment=normalized_environment,
                created_by_user_id=actor_user_id,
            )
            db.session.add(credential)
        else:
            credential.name = normalized_name

        credential.encrypted_value = encrypt_secret(normalized_token)
        credential.masked_preview = mask_secret(normalized_token)
        credential.validation_status = "unknown"
        credential.last_validation_error = None
        credential.last_validation_report = None
        credential.updated_at = datetime.utcnow()
        db.session.flush()
        record_audit_event(
            actor_user_id=actor_user_id,
            event_type=f"zenodo_credential_{action}",
            entity_type="zenodo_credential",
            entity_id=credential.id,
            institution_id=credential.owner_id if normalized_owner_type == "institution" else None,
            details={
                "owner_type": normalized_owner_type,
                "owner_id": int(owner_id),
                "environment": normalized_environment,
                "name": credential.name,
                "masked_preview": credential.masked_preview,
            },
        )
        if normalized_owner_type == "user":
            self._ensure_active_default(int(owner_id), credential)
        db.session.commit()
        return credential

    def create_credential(
        self,
        *,
        user_id: int,
        environment: str,
        token: str,
        name: str | None,
        actor_user_id: int | None,
    ) -> ZenodoCredential:
        normalized_environment = normalize_environment(environment)
        normalized_name = self._normalize_name(name, normalized_environment)
        normalized_token = str(token or "").strip()
        if not normalized_token:
            raise ValidationError("Zenodo token is required")
        credential = ZenodoCredential(
            name=normalized_name,
            owner_type="user",
            owner_id=int(user_id),
            environment=normalized_environment,
            encrypted_value=encrypt_secret(normalized_token),
            masked_preview=mask_secret(normalized_token),
            validation_status="unknown",
            created_by_user_id=actor_user_id,
        )
        db.session.add(credential)
        db.session.flush()
        record_audit_event(
            actor_user_id=actor_user_id,
            event_type="zenodo_credential_created",
            entity_type="zenodo_credential",
            entity_id=credential.id,
            details={
                "owner_type": "user",
                "owner_id": int(user_id),
                "environment": normalized_environment,
                "name": credential.name,
                "masked_preview": credential.masked_preview,
            },
        )
        self._ensure_active_default(int(user_id), credential)
        db.session.commit()
        return credential

    def rename_credential(self, *, credential_id: int, user_id: int, name: str) -> ZenodoCredential:
        credential = self.require_credential_by_id(credential_id)
        self._ensure_owned_by_user(credential, user_id)
        credential.name = self._normalize_name(name, credential.environment)
        credential.updated_at = datetime.utcnow()
        record_audit_event(
            actor_user_id=user_id,
            event_type="zenodo_credential_renamed",
            entity_type="zenodo_credential",
            entity_id=credential.id,
            details={"environment": credential.environment, "name": credential.name},
        )
        db.session.commit()
        return credential

    def _ensure_active_default(self, user_id: int, credential: ZenodoCredential) -> None:
        if credential.owner_type != "user" or int(credential.owner_id) != int(user_id):
            return
        existing = UserZenodoActiveCredential.query.filter_by(
            user_id=int(user_id),
            environment=credential.environment,
        ).first()
        if existing:
            return
        db.session.add(
            UserZenodoActiveCredential(
                user_id=int(user_id),
                environment=credential.environment,
                credential_id=credential.id,
            )
        )

    def set_active_credential(self, *, user_id: int, environment: str, credential_id: int) -> ZenodoCredential:
        credential = self.require_credential_by_id(credential_id)
        normalized_environment = normalize_environment(environment)
        if credential.environment != normalized_environment:
            raise ValidationError("Active Zenodo credential environment mismatch")
        if credential.owner_type != "user":
            raise ValidationError("Only personal or shared user Zenodo credentials can be activated")
        self._ensure_accessible_by_user(credential, user_id)
        row = UserZenodoActiveCredential.query.filter_by(
            user_id=int(user_id),
            environment=normalized_environment,
        ).first()
        if not row:
            row = UserZenodoActiveCredential(user_id=int(user_id), environment=normalized_environment)
            db.session.add(row)
        row.credential_id = credential.id
        row.updated_at = datetime.utcnow()
        record_audit_event(
            actor_user_id=user_id,
            event_type="zenodo_active_credential_set",
            entity_type="zenodo_credential",
            entity_id=credential.id,
            details={
                "environment": normalized_environment,
                "credential_id": credential.id,
                "source": "owned" if int(credential.owner_id) == int(user_id) else "shared",
            },
        )
        db.session.commit()
        return credential

    def delete_credential(
        self,
        *,
        owner_type: str,
        owner_id: int,
        environment: str,
        actor_user_id: int | None,
    ) -> bool:
        credential = self.get_credential(owner_type, owner_id, environment)
        if not credential:
            return False
        record_audit_event(
            actor_user_id=actor_user_id,
            event_type="zenodo_credential_deleted",
            entity_type="zenodo_credential",
            entity_id=credential.id,
            institution_id=credential.owner_id if credential.owner_type == "institution" else None,
            details={
                "owner_type": credential.owner_type,
                "owner_id": credential.owner_id,
                "environment": credential.environment,
                "name": credential.name,
                "masked_preview": credential.masked_preview,
            },
        )
        UserZenodoActiveCredential.query.filter_by(credential_id=credential.id).delete()
        db.session.delete(credential)
        db.session.commit()
        return True

    def delete_owned_credential_by_id(self, *, credential_id: int, user_id: int, actor_user_id: int | None) -> bool:
        credential = self.get_credential_by_id(credential_id)
        if not credential:
            return False
        self._ensure_owned_by_user(credential, user_id)
        record_audit_event(
            actor_user_id=actor_user_id,
            event_type="zenodo_credential_deleted",
            entity_type="zenodo_credential",
            entity_id=credential.id,
            details={
                "owner_type": credential.owner_type,
                "owner_id": credential.owner_id,
                "environment": credential.environment,
                "name": credential.name,
                "masked_preview": credential.masked_preview,
            },
        )
        UserZenodoActiveCredential.query.filter_by(credential_id=credential.id).delete()
        db.session.delete(credential)
        db.session.commit()
        return True

    def share_credential(self, *, credential_id: int, owner_user_id: int, recipient_email: str) -> ZenodoCredentialShare:
        credential = self.require_credential_by_id(credential_id)
        self._ensure_owned_by_user(credential, owner_user_id)
        email = str(recipient_email or "").strip().lower()
        if not email:
            raise ValidationError("Recipient email is required")
        recipient = User.query.filter(db.func.lower(User.email) == email).first()
        if not recipient:
            raise ResourceNotFoundError("Recipient user not found")
        if int(recipient.id) == int(owner_user_id):
            raise ValidationError("You cannot share a Zenodo credential with yourself")
        share = ZenodoCredentialShare.query.filter_by(
            credential_id=credential.id,
            recipient_user_id=recipient.id,
        ).first()
        if not share:
            share = ZenodoCredentialShare(
                credential_id=credential.id,
                shared_by_user_id=int(owner_user_id),
                recipient_user_id=recipient.id,
                status="pending",
            )
            db.session.add(share)
        else:
            share.status = "pending"
            share.shared_by_user_id = int(owner_user_id)
            share.responded_at = None
            share.updated_at = datetime.utcnow()
        db.session.flush()
        record_audit_event(
            actor_user_id=owner_user_id,
            event_type="zenodo_credential_share_invited",
            entity_type="zenodo_credential_share",
            entity_id=share.id,
            details={
                "credential_id": credential.id,
                "environment": credential.environment,
                "recipient_user_id": recipient.id,
                "recipient_email": recipient.email,
            },
        )
        notify_user(
            recipient_user_id=recipient.id,
            actor_user_id=owner_user_id,
            notification_type="credential.share_received",
            severity="info",
            title="Zenodo credential shared with you",
            body=f"{credential.name or credential.environment} is ready for your review.",
            entity_type="zenodo_credential_share",
            entity_id=share.id,
            action_url="/account/configuration",
            payload={"share_id": share.id, "credential_id": credential.id, "environment": credential.environment},
        )
        db.session.commit()
        return share

    def respond_to_share(self, *, share_id: int, user_id: int, status: str) -> ZenodoCredentialShare:
        normalized_status = str(status or "").strip().lower()
        if normalized_status not in {"accepted", "declined"}:
            raise ValidationError("Share response must be accepted or declined")
        share = db.session.get(ZenodoCredentialShare, int(share_id))
        if not share or int(share.recipient_user_id) != int(user_id):
            raise ResourceNotFoundError("Zenodo credential share not found")
        if share.status == "revoked":
            raise ValidationError("This Zenodo credential share has been revoked")
        share.status = normalized_status
        share.responded_at = datetime.utcnow()
        share.updated_at = datetime.utcnow()
        record_audit_event(
            actor_user_id=user_id,
            event_type=f"zenodo_credential_share_{normalized_status}",
            entity_type="zenodo_credential_share",
            entity_id=share.id,
            details={
                "credential_id": share.credential_id,
                "environment": share.credential.environment if share.credential else None,
                "shared_by_user_id": share.shared_by_user_id,
            },
        )
        notify_user(
            recipient_user_id=share.shared_by_user_id,
            actor_user_id=user_id,
            notification_type=f"credential.share_{normalized_status}",
            severity="success" if normalized_status == "accepted" else "info",
            title=f"Zenodo credential share {normalized_status}",
            body=f"{share.recipient.email if share.recipient else 'A recipient'} {normalized_status} your shared credential.",
            entity_type="zenodo_credential_share",
            entity_id=share.id,
            action_url="/account/configuration",
            payload={"share_id": share.id, "credential_id": share.credential_id, "status": normalized_status},
        )
        db.session.commit()
        return share

    def revoke_share(self, *, share_id: int, owner_user_id: int) -> ZenodoCredentialShare:
        share = db.session.get(ZenodoCredentialShare, int(share_id))
        if not share or not share.credential:
            raise ResourceNotFoundError("Zenodo credential share not found")
        self._ensure_owned_by_user(share.credential, owner_user_id)
        share.status = "revoked"
        share.updated_at = datetime.utcnow()
        UserZenodoActiveCredential.query.filter_by(
            credential_id=share.credential_id,
            user_id=share.recipient_user_id,
        ).delete()
        record_audit_event(
            actor_user_id=owner_user_id,
            event_type="zenodo_credential_share_revoked",
            entity_type="zenodo_credential_share",
            entity_id=share.id,
            details={
                "credential_id": share.credential_id,
                "environment": share.credential.environment,
                "recipient_user_id": share.recipient_user_id,
            },
        )
        notify_user(
            recipient_user_id=share.recipient_user_id,
            actor_user_id=owner_user_id,
            notification_type="credential.share_revoked",
            severity="warning",
            title="Zenodo credential share revoked",
            body=f"Access to {share.credential.name or share.credential.environment} was revoked.",
            entity_type="zenodo_credential_share",
            entity_id=share.id,
            action_url="/account/configuration",
            payload={"share_id": share.id, "credential_id": share.credential_id, "status": "revoked"},
        )
        db.session.commit()
        return share

    def validate_token(self, environment: str, token: str) -> dict[str, Any]:
        normalized_environment = normalize_environment(environment)
        headers = {"Authorization": f"Bearer {str(token or '').strip()}"}
        base_url = _base_api_url(normalized_environment)
        draft_id: int | str | None = None

        try:
            read_response = requests.get(
                f"{base_url}/deposit/depositions",
                headers=headers,
                params={"size": 1},
                timeout=10,
            )
        except Exception as exc:
            evidence = _build_probe_evidence(
                normalized_environment,
                "GET /api/deposit/depositions?size=1",
                error=str(exc),
            )
            return _build_validation_report(
                environment=normalized_environment,
                aggregate_status="unreachable",
                summary=f"Zenodo validation failed before the read probe received a response: {exc}",
                capabilities=_failed_capabilities(
                    "unreachable",
                    "Zenodo could not be reached for the live validation read probe.",
                    evidence,
                ),
            )

        read_evidence = _build_probe_evidence(
            normalized_environment,
            "GET /api/deposit/depositions?size=1",
            status_code=read_response.status_code,
        )
        if read_response.status_code in {401, 403}:
            message = _extract_response_message(read_response)
            if read_response.status_code == 403:
                summary = (
                    "Zenodo rejected deposit read access for this token. This usually means the token is missing "
                    "deposit:write and/or deposit:actions."
                )
                if message:
                    summary = f"{summary} Zenodo message: {message}"
                return _build_validation_report(
                    environment=normalized_environment,
                    aggregate_status="invalid",
                    summary=summary,
                    capabilities={
                        "authentication": _build_capability(
                            "verified",
                            "Zenodo recognized the token, but the deposit API denied access.",
                            evidence=read_evidence,
                        ),
                        "deposit_read": _build_capability(
                            "invalid",
                            "The deposit API list probe was forbidden for this token.",
                            evidence=read_evidence,
                        ),
                        "draft_create": _build_capability(
                            "invalid",
                            "WebHDP could not test draft creation because the token lacks deposit API access.",
                            evidence={"recommended_scopes": list(RECOMMENDED_SCOPES)},
                        ),
                        "draft_cleanup": _build_capability(
                            "unverified",
                            "No test draft was created, so cleanup was not needed.",
                        ),
                    },
                )
            summary = (
                f"Zenodo rejected the {normalized_environment} token. This usually means the token is invalid or "
                "belongs to the other Zenodo environment."
            )
            if message:
                summary = f"{summary} Zenodo message: {message}"
            return _build_validation_report(
                environment=normalized_environment,
                aggregate_status="invalid",
                summary=summary,
                capabilities=_failed_capabilities(
                    "invalid",
                    "Capability could not be validated because Zenodo rejected the token.",
                    read_evidence,
                ),
            )
        if read_response.status_code == 429:
            return _build_validation_report(
                environment=normalized_environment,
                aggregate_status="unreachable",
                summary="Zenodo rate-limited token validation. Retry later.",
                capabilities=_failed_capabilities(
                    "unreachable",
                    "Zenodo did not allow the live validation read probe to complete because of rate limiting.",
                    read_evidence,
                ),
            )
        if read_response.status_code != 200:
            return _build_validation_report(
                environment=normalized_environment,
                aggregate_status="unreachable",
                summary=f"Zenodo returned status {read_response.status_code} during the credential read probe.",
                capabilities=_failed_capabilities(
                    "unreachable",
                    "Zenodo did not return a usable validation response for the live read probe.",
                    read_evidence,
                ),
            )

        capabilities = {
            "authentication": _build_capability(
                "verified",
                f"Zenodo accepted the token for the {normalized_environment} environment.",
                evidence=read_evidence,
            ),
            "deposit_read": _build_capability(
                "verified",
                "The deposit API list probe succeeded.",
                evidence=read_evidence,
            ),
            "draft_create": _build_capability(
                "unverified",
                "Draft creation has not run yet.",
            ),
            "draft_cleanup": _build_capability(
                "unverified",
                "No test draft has been created yet.",
            ),
        }

        try:
            create_response = requests.post(
                f"{base_url}/deposit/depositions",
                headers={**headers, "Content-Type": "application/json"},
                json={},
                timeout=30,
            )
            create_evidence = _build_probe_evidence(
                normalized_environment,
                "POST /api/deposit/depositions",
                status_code=create_response.status_code,
            )
            if create_response.status_code in {401, 403}:
                message = _extract_response_message(create_response)
                summary = (
                    "Zenodo accepted the read probe but rejected test draft creation. This usually means the token "
                    "is missing deposit:write."
                )
                if message:
                    summary = f"{summary} Zenodo message: {message}"
                capabilities["draft_create"] = _build_capability(
                    "invalid",
                    "Zenodo rejected test draft creation for this token.",
                    evidence=create_evidence,
                )
                capabilities["draft_cleanup"] = _build_capability(
                    "unverified",
                    "No test draft was created, so cleanup was not needed.",
                )
                return _build_validation_report(
                    environment=normalized_environment,
                    aggregate_status="invalid",
                    summary=summary,
                    capabilities=capabilities,
                )
            if create_response.status_code == 429:
                capabilities["draft_create"] = _build_capability(
                    "unreachable",
                    "Zenodo rate-limited the test draft creation probe.",
                    evidence=create_evidence,
                )
                capabilities["draft_cleanup"] = _build_capability(
                    "unverified",
                    "No test draft was created, so cleanup was not needed.",
                )
                return _build_validation_report(
                    environment=normalized_environment,
                    aggregate_status="unreachable",
                    summary="Zenodo rate-limited test draft creation. Retry later.",
                    capabilities=capabilities,
                )
            if create_response.status_code not in {200, 201}:
                capabilities["draft_create"] = _build_capability(
                    "unreachable",
                    "Zenodo did not return a usable response for test draft creation.",
                    evidence=create_evidence,
                )
                capabilities["draft_cleanup"] = _build_capability(
                    "unverified",
                    "No test draft was created, so cleanup was not needed.",
                )
                return _build_validation_report(
                    environment=normalized_environment,
                    aggregate_status="unreachable",
                    summary=f"Zenodo returned status {create_response.status_code} during test draft creation.",
                    capabilities=capabilities,
                )

            create_payload = _safe_json(create_response)
            draft_id = create_payload.get("id")
            capabilities["draft_create"] = _build_capability(
                "verified",
                "Zenodo allowed WebHDP to create a temporary validation draft.",
                evidence=create_evidence,
            )
            if not draft_id:
                capabilities["draft_cleanup"] = _build_capability(
                    "warning",
                    "Zenodo created a draft response without an id, so WebHDP could not automatically delete it.",
                    evidence={**create_evidence, "draft_id_present": False},
                )
                return _build_validation_report(
                    environment=normalized_environment,
                    aggregate_status="warning",
                    summary=(
                        "Zenodo allowed test draft creation, but the response did not include a draft id for "
                        "automatic cleanup. Check your Zenodo draft list."
                    ),
                    capabilities=capabilities,
                )
        except Exception as exc:
            create_evidence = _build_probe_evidence(
                normalized_environment,
                "POST /api/deposit/depositions",
                error=str(exc),
            )
            capabilities["draft_create"] = _build_capability(
                "unreachable",
                "Zenodo could not be reached for test draft creation.",
                evidence=create_evidence,
            )
            capabilities["draft_cleanup"] = _build_capability(
                "unverified",
                "No test draft was created, so cleanup was not needed.",
            )
            return _build_validation_report(
                environment=normalized_environment,
                aggregate_status="unreachable",
                summary=f"Zenodo validation failed before test draft creation received a response: {exc}",
                capabilities=capabilities,
            )

        try:
            cleanup_response = requests.delete(
                f"{base_url}/deposit/depositions/{draft_id}",
                headers=headers,
                timeout=30,
            )
            cleanup_evidence = _build_probe_evidence(
                normalized_environment,
                "DELETE /api/deposit/depositions/:id",
                status_code=cleanup_response.status_code,
            )
            if cleanup_response.status_code in {200, 201, 202, 204}:
                capabilities["draft_cleanup"] = _build_capability(
                    "verified",
                    "WebHDP automatically deleted the temporary validation draft.",
                    evidence=cleanup_evidence,
                )
                return _build_validation_report(
                    environment=normalized_environment,
                    aggregate_status="valid",
                    summary=(
                        f"Zenodo accepted the {normalized_environment} token for read access, temporary draft "
                        "creation, and automatic draft cleanup."
                    ),
                    capabilities=capabilities,
                )
            capabilities["draft_cleanup"] = _build_capability(
                "warning",
                "Zenodo did not confirm deletion of the temporary validation draft.",
                evidence=cleanup_evidence,
            )
            return _build_validation_report(
                environment=normalized_environment,
                aggregate_status="warning",
                summary=(
                    "Zenodo allowed test draft creation, but WebHDP could not confirm automatic cleanup. "
                    "Check your Zenodo draft list for a temporary validation draft."
                ),
                capabilities=capabilities,
            )
        except Exception as exc:
            cleanup_evidence = _build_probe_evidence(
                normalized_environment,
                "DELETE /api/deposit/depositions/:id",
                error=str(exc),
            )
            capabilities["draft_cleanup"] = _build_capability(
                "warning",
                "WebHDP could not reach Zenodo to delete the temporary validation draft.",
                evidence=cleanup_evidence,
            )
            return _build_validation_report(
                environment=normalized_environment,
                aggregate_status="warning",
                summary=(
                    "Zenodo allowed test draft creation, but automatic cleanup failed before WebHDP received a "
                    "delete response. Check your Zenodo draft list for a temporary validation draft."
                ),
                capabilities=capabilities,
            )

    def validate_credential(
        self,
        *,
        owner_type: str,
        owner_id: int,
        environment: str,
        actor_user_id: int | None,
    ) -> ZenodoCredential:
        credential = self.require_credential(owner_type, owner_id, environment)
        report = self.validate_token(credential.environment, self.decrypt_value(credential))
        status = str(report.get("aggregate_status") or "unknown").strip().lower()
        error = _derive_top_level_message(report)
        credential.validation_status = status or "unknown"
        credential.last_validation_error = error
        credential.last_validation_report = json.dumps(report)
        credential.last_validated_at = datetime.utcnow()
        db.session.flush()
        record_audit_event(
            actor_user_id=actor_user_id,
            event_type="zenodo_credential_validated",
            entity_type="zenodo_credential",
            entity_id=credential.id,
            institution_id=credential.owner_id if credential.owner_type == "institution" else None,
            details={
                "owner_type": credential.owner_type,
                "owner_id": credential.owner_id,
                "environment": credential.environment,
                "validation_mode": VALIDATION_MODE,
                "validation_status": status,
                "validation_error": error,
                "validation_report": report,
            },
        )
        db.session.commit()
        return credential

    def validate_accessible_credential(
        self,
        *,
        credential_id: int,
        actor_user_id: int,
    ) -> ZenodoCredential:
        credential = self.require_credential_by_id(credential_id)
        self._ensure_accessible_by_user(credential, actor_user_id)
        report = self.validate_token(credential.environment, self.decrypt_value(credential))
        status = str(report.get("aggregate_status") or "unknown").strip().lower()
        error = _derive_top_level_message(report)
        credential.validation_status = status or "unknown"
        credential.last_validation_error = error
        credential.last_validation_report = json.dumps(report)
        credential.last_validated_at = datetime.utcnow()
        db.session.flush()
        record_audit_event(
            actor_user_id=actor_user_id,
            event_type="zenodo_credential_validated",
            entity_type="zenodo_credential",
            entity_id=credential.id,
            institution_id=credential.owner_id if credential.owner_type == "institution" else None,
            details={
                "owner_type": credential.owner_type,
                "owner_id": credential.owner_id,
                "environment": credential.environment,
                "validation_mode": VALIDATION_MODE,
                "validation_status": status,
                "validation_error": error,
                "validation_report": report,
                "access": "owned" if credential.owner_type == "user" and int(credential.owner_id) == int(actor_user_id) else "shared",
            },
        )
        db.session.commit()
        return credential
