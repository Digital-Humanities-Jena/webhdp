import os
import sqlite3
import time
from pathlib import Path

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
