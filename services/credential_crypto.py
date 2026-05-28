import base64
import hashlib
import os

from cryptography.fernet import Fernet
from flask import current_app, has_app_context


_DEVELOPMENT_FALLBACK_SECRET = "dev-credential-encryption-key"
_PLACEHOLDER_SECRET_VALUES = {
    "",
    "change-me",
    "change-this-in-production",
    "dev-secret-key-replace-in-prod",
    "your-secret-key-here",
}


def _get_config_value(name: str) -> str:
    if has_app_context():
        value = current_app.config.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return str(os.environ.get(name) or "").strip()


def _is_production_environment() -> bool:
    if has_app_context():
        if current_app.config.get("TESTING"):
            return False
        env = str(current_app.config.get("ENV") or current_app.config.get("FLASK_ENV") or "").strip().lower()
        if env == "production":
            return True
        if current_app.debug:
            return False
    return str(os.environ.get("FLASK_ENV") or "").strip().lower() == "production"


def _hash_secret_material(value: str) -> bytes:
    digest = hashlib.sha256(str(value or "").encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _is_placeholder_secret(value: str) -> bool:
    return str(value or "").strip().lower() in _PLACEHOLDER_SECRET_VALUES


def _explicit_fernet_key(value: str) -> bytes | None:
    candidate = str(value or "").strip().encode("utf-8")
    if not candidate:
        return None
    try:
        Fernet(candidate)
    except Exception:
        return None
    return candidate


def _derive_key() -> bytes:
    explicit = _get_config_value("CREDENTIAL_ENCRYPTION_KEY")
    if explicit and not _is_placeholder_secret(explicit):
        explicit_key = _explicit_fernet_key(explicit)
        if explicit_key:
            return explicit_key
        return _hash_secret_material(explicit)

    if _is_production_environment():
        raise RuntimeError("Credential encryption requires CREDENTIAL_ENCRYPTION_KEY in production")

    secret = _get_config_value("SECRET_KEY")
    if secret and not _is_placeholder_secret(secret):
        return _hash_secret_material(secret)

    return _hash_secret_material(_DEVELOPMENT_FALLBACK_SECRET)


def get_encryption_configuration_report() -> dict:
    explicit = _get_config_value("CREDENTIAL_ENCRYPTION_KEY")
    secret = _get_config_value("SECRET_KEY")
    is_production = _is_production_environment()

    if explicit and not _is_placeholder_secret(explicit):
        return {
            "event": "credential_encryption_configuration",
            "status": "configured",
            "mode": "explicit_key",
            "production": bool(is_production),
            "message": "Credential encryption is configured with CREDENTIAL_ENCRYPTION_KEY.",
        }

    if is_production:
        return {
            "event": "credential_encryption_configuration",
            "status": "invalid",
            "mode": "missing",
            "production": True,
            "message": "Credential encryption requires CREDENTIAL_ENCRYPTION_KEY in production.",
        }

    if secret and not _is_placeholder_secret(secret):
        return {
            "event": "credential_encryption_configuration",
            "status": "configured",
            "mode": "secret_key_fallback",
            "production": False,
            "message": (
                "Credential encryption is using SECRET_KEY fallback. Configure CREDENTIAL_ENCRYPTION_KEY for an explicit "
                "credential-encryption secret."
            ),
        }

    return {
        "event": "credential_encryption_configuration",
        "status": "development_fallback",
        "mode": "development_fallback",
        "production": False,
        "message": "Credential encryption is using the development fallback secret.",
    }


def validate_encryption_configuration() -> dict:
    report = get_encryption_configuration_report()
    if report["status"] == "invalid":
        raise RuntimeError(report["message"])
    return report


def get_fernet() -> Fernet:
    return Fernet(_derive_key())


def encrypt_secret(value: str) -> str:
    return get_fernet().encrypt(str(value or "").encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    return get_fernet().decrypt(str(value or "").encode("utf-8")).decode("utf-8")
