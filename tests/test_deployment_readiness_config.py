import importlib.util
import uuid
from pathlib import Path

import pytest
from flask import Flask

from database.database import db, init_db


def _load_config_module():
    module_path = Path(__file__).resolve().parents[1] / "config.py"
    spec = importlib.util.spec_from_file_location(f"test_config_{uuid.uuid4().hex}", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_production_config_rejects_placeholder_secrets(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "your-secret-key-here")
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "")
    monkeypatch.delenv("SETUP_BOOTSTRAP_TOKEN", raising=False)
    monkeypatch.delenv("DEFAULT_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("DEFAULT_ADMIN_PASSWORD", raising=False)

    with pytest.raises(ValueError, match="SECRET_KEY|Production configuration"):
        _load_config_module()


def test_production_config_accepts_real_secret_and_bootstrap_values(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "prod-secret-" + "a" * 32)
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "credential-secret-" + "b" * 32)
    monkeypatch.setenv("SETUP_BOOTSTRAP_TOKEN", "setup-token-" + "c" * 32)
    monkeypatch.delenv("DEFAULT_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("DEFAULT_ADMIN_PASSWORD", raising=False)

    module = _load_config_module()

    assert module.ProductionConfig.SECRET_KEY.startswith("prod-secret-")
    assert module.ProductionConfig.CREDENTIAL_ENCRYPTION_KEY.startswith("credential-secret-")


def test_production_config_rejects_short_jwt_signing_key(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "synthetic-short-key")
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "credential-secret-" + "b" * 32)
    monkeypatch.setenv("SETUP_BOOTSTRAP_TOKEN", "setup-token-" + "c" * 32)

    with pytest.raises(ValueError, match="at least 32 bytes"):
        _load_config_module()


def test_storage_mode_defaults_to_pure_cloud(monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.delenv("STORAGE_MODE", raising=False)
    monkeypatch.setenv("FLASK_ENV", "development")

    module = _load_config_module()

    assert module.Config.STORAGE_MODE == "pure_cloud"


def test_file_backed_sqlite_uses_deployment_pragmas(tmp_path):
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'webhdp.db'}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    init_db(app)

    with app.app_context():
        raw_connection = db.engine.raw_connection()
        try:
            cursor = raw_connection.cursor()
            cursor.execute("PRAGMA foreign_keys")
            assert cursor.fetchone()[0] == 1
            cursor.execute("PRAGMA busy_timeout")
            assert cursor.fetchone()[0] == 30000
            cursor.execute("PRAGMA journal_mode")
            assert cursor.fetchone()[0].lower() == "wal"
        finally:
            raw_connection.close()
            db.session.remove()
            db.engine.dispose()
