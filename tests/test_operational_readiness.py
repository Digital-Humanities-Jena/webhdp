import os
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

from services.maintenance_service import disable_maintenance, enable_maintenance, maintenance_status
from services.readiness_service import build_readiness_report
from session_manager import SessionManager


def _create_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version (version_num) VALUES ('testrev')")
        conn.commit()
    finally:
        conn.close()


def test_readiness_passes_for_local_inline_sqlite_deployment(tmp_path, monkeypatch):
    db_path = tmp_path / "instance" / "hdp_web.db"
    _create_db(db_path)
    (tmp_path / "hdp-shared" / "sessions").mkdir(parents=True)
    (tmp_path / "local_input").mkdir()
    (tmp_path / "local_output").mkdir()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("WEBHDP_INLINE_TASKS", "true")
    monkeypatch.delenv("BACKUP_ENABLED", raising=False)

    report = build_readiness_report()

    assert report["ready"] is True
    assert report["checks"]["database"]["integrity_check"] == "ok"
    assert report["checks"]["redis"]["skipped"] is True


def test_readiness_blocks_when_sqlite_revision_is_behind_head(tmp_path, monkeypatch):
    db_path = tmp_path / "instance" / "hdp_web.db"
    _create_db(db_path)
    (tmp_path / "hdp-shared" / "sessions").mkdir(parents=True)
    (tmp_path / "local_input").mkdir()
    (tmp_path / "local_output").mkdir()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("WEBHDP_INLINE_TASKS", "true")
    monkeypatch.setattr("services.readiness_service._alembic_head", lambda root: "headrev")

    report = build_readiness_report()

    assert report["ready"] is False
    assert report["blockers"] == ["database"]
    assert report["checks"]["database"]["alembic_revision"] == "testrev"
    assert report["checks"]["database"]["expected_alembic_revision"] == "headrev"
    assert report["checks"]["database"]["error"] == "database migration revision is not at Alembic head"


def test_running_app_readiness_checks_required_validator_only(tmp_path, monkeypatch):
    db = tmp_path / "instance" / "hdp_web.db"
    _create_db(db)
    for directory in ("hdp-shared/sessions", "local_input", "local_output"):
        (tmp_path / directory).mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.delenv("BACKUP_ENABLED", raising=False)
    monkeypatch.setenv("WEBHDP_INLINE_TASKS", "true")
    from services.readiness_service import LocalEdmValidatorClient

    health = {"ok": False, "status": "DOWN"}
    calls = []

    def health_check(client):
        calls.append(client.base_url)
        return health

    monkeypatch.setattr(LocalEdmValidatorClient, "check_health", health_check)
    app = SimpleNamespace(config={
        "LOCAL_EDM_VALIDATOR_URL": "http://validator-in-docker:8080",
        "ENABLE_LOCAL_EDM_VALIDATION": True,
        "LOCAL_EDM_VALIDATOR_REQUIRED": False,
    })
    optional = build_readiness_report(app)
    assert optional["ready"] and optional["checks"]["local_edm_validator"]["skipped"]
    assert calls == []

    app.config.update(ENABLE_LOCAL_EDM_VALIDATION=False, LOCAL_EDM_VALIDATOR_REQUIRED=True)
    unavailable = build_readiness_report(app)
    assert unavailable["blockers"] == ["local_edm_validator"]
    assert calls == ["http://validator-in-docker:8080"]

    health.update(ok=True, status="UP")
    assert build_readiness_report(app)["ready"] is True
    app.config["LOCAL_EDM_VALIDATOR_EXPECTED_METIS_SCHEMA_VERSION"] = "15"
    info = {"ok": True, "summary": {"metis_schema_version": "14"}}
    monkeypatch.setattr(LocalEdmValidatorClient, "get_info", lambda self: info)
    mismatch = build_readiness_report(app)
    assert mismatch["blockers"] == ["local_edm_validator"]
    assert "expected 15, reported 14" in mismatch["checks"]["local_edm_validator"]["error"]
    info["summary"]["metis_schema_version"] = "15"
    assert build_readiness_report(app)["ready"] is True


def test_readiness_blocks_when_sqlite_schema_is_stamped_but_incomplete(tmp_path, monkeypatch):
    db_path = tmp_path / "instance" / "hdp_web.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version (version_num) VALUES ('headrev')")
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255) NOT NULL)")
        conn.commit()
    finally:
        conn.close()
    (tmp_path / "hdp-shared" / "sessions").mkdir(parents=True)
    (tmp_path / "local_input").mkdir()
    (tmp_path / "local_output").mkdir()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("WEBHDP_INLINE_TASKS", "true")
    monkeypatch.setattr("services.readiness_service._alembic_head", lambda root: "headrev")

    report = build_readiness_report()

    assert report["ready"] is False
    assert report["blockers"] == ["database"]
    assert report["checks"]["database"]["error"] == "database schema does not match application models"
    assert report["checks"]["database"]["schema_error_count"] > 0
    assert any("users" in error for error in report["checks"]["database"]["schema_errors"])


def test_maintenance_flag_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("MAINTENANCE_FLAG_PATH", str(tmp_path / "maintenance.json"))

    enabled = enable_maintenance("unit test", tmp_path)
    assert enabled["enabled"] is True
    assert maintenance_status(tmp_path)["enabled"] is True

    disabled = disable_maintenance(tmp_path)
    assert disabled["enabled"] is False
    assert maintenance_status(tmp_path)["enabled"] is False


def test_session_artifact_cleanup_is_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("SHARED_SESSION_PATH", str(tmp_path))
    session_dir = tmp_path / "hdp_session_old"
    uploads = session_dir / "uploads"
    uploads.mkdir(parents=True)
    (session_dir / "session.hdpc").write_text("db", encoding="utf-8")
    (uploads / "model.glb").write_text("payload", encoding="utf-8")
    old_time = time.time() - 3600
    os.utime(session_dir, (old_time, old_time))

    manager = SessionManager(
        session_timeout=1,
        artifact_cleanup_enabled=False,
        artifact_retention_seconds=1,
        cleanup_interval=3600,
    )
    manager._cleanup_expired_sessions()
    assert (uploads / "model.glb").exists()

    manager.artifact_cleanup_enabled = True
    manager._cleanup_expired_sessions()
    assert (session_dir / "session.hdpc").exists()
    assert not uploads.exists()
