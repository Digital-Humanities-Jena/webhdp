import importlib.util
from pathlib import Path

import pytest


def _load_crypto_module():
    pytest.importorskip("cryptography.fernet")
    module_path = Path(__file__).resolve().parents[1] / "services" / "credential_crypto.py"
    spec = importlib.util.spec_from_file_location("test_credential_crypto_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_credential_crypto_accepts_plaintext_explicit_secret(monkeypatch):
    crypto = _load_crypto_module()
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "plain-text-encryption-secret")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("FLASK_ENV", "development")

    encrypted = crypto.encrypt_secret("sandbox-token")
    assert crypto.decrypt_secret(encrypted) == "sandbox-token"


def test_credential_crypto_requires_secret_in_production(monkeypatch):
    crypto = _load_crypto_module()
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("FLASK_ENV", "production")

    with pytest.raises(RuntimeError):
        crypto.encrypt_secret("sandbox-token")


def test_credential_crypto_rejects_secret_key_fallback_in_production(monkeypatch):
    crypto = _load_crypto_module()
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("SECRET_KEY", "fallback-secret-key")
    monkeypatch.setenv("FLASK_ENV", "production")

    report = crypto.get_encryption_configuration_report()

    assert report["status"] == "invalid"
    assert report["mode"] == "missing"
    with pytest.raises(RuntimeError):
        crypto.validate_encryption_configuration()
