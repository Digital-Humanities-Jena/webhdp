"""Deployment readiness checks for the single-node SQLite deployment."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import redis
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory

from services.backup_service import BackupError, BackupService
from services.local_edm_validator_client import (
    LocalEdmValidatorClient,
    expected_validator_identity,
    validator_identity_mismatches,
)
from services.maintenance_service import maintenance_status


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _alembic_head(root: Path) -> str | None:
    ini_path = root / "migrations" / "alembic.ini"
    versions_path = root / "migrations"
    if not ini_path.exists() or not versions_path.exists():
        return None
    config = AlembicConfig(str(ini_path))
    config.set_main_option("script_location", str(versions_path))
    heads = ScriptDirectory.from_config(config).get_heads()
    return heads[0] if len(heads) == 1 else None


def _schema_drift_errors(connection: sqlite3.Connection, *, max_errors: int = 20) -> tuple[list[str], int]:
    from database.database import db
    import database.models  # noqa: F401 - populate SQLAlchemy metadata for comparison

    existing_tables = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    errors: list[str] = []
    total = 0
    for table in db.metadata.tables.values():
        table_name = str(table.name)
        if table_name not in existing_tables:
            total += 1
            if len(errors) < max_errors:
                errors.append(f"missing table {table_name}")
            continue
        existing_columns = {
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info({table_name!r})").fetchall()
        }
        for column in table.columns:
            column_name = str(column.name)
            if column_name not in existing_columns:
                total += 1
                if len(errors) < max_errors:
                    errors.append(f"table {table_name} missing column {column_name}")
    return errors, total


def _check_sqlite(database_url: str, *, expected_alembic_revision: str | None = None) -> dict[str, Any]:
    try:
        path = BackupService.sqlite_path_from_url(database_url)
    except BackupError as exc:
        return {"ok": False, "error": str(exc)}
    if not path.is_file():
        return {"ok": False, "path": str(path), "error": "database file missing"}
    connection = sqlite3.connect(str(path))
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        revision_row = None
        try:
            revision_row = connection.execute("SELECT version_num FROM alembic_version LIMIT 1").fetchone()
        except sqlite3.Error:
            revision_row = None
        actual_revision = revision_row[0] if revision_row else None
        revision_ok = expected_alembic_revision is None or actual_revision == expected_alembic_revision
        schema_errors: list[str] = []
        schema_error_count = 0
        if integrity.lower() == "ok" and revision_ok and expected_alembic_revision is not None:
            schema_errors, schema_error_count = _schema_drift_errors(connection)
    finally:
        connection.close()
    schema_ok = not schema_errors and schema_error_count == 0
    result = {
        "ok": integrity.lower() == "ok" and revision_ok and schema_ok,
        "path": str(path),
        "integrity_check": integrity,
        "alembic_revision": actual_revision,
        "expected_alembic_revision": expected_alembic_revision,
    }
    if integrity.lower() != "ok":
        result["error"] = "sqlite integrity check failed"
    elif not revision_ok:
        result["error"] = "database migration revision is not at Alembic head"
    elif not schema_ok:
        result["error"] = "database schema does not match application models"
        result["schema_errors"] = schema_errors
        result["schema_error_count"] = schema_error_count
    return result


def _check_path(path: str | Path, *, writable: bool = True, min_free_bytes: int = 0) -> dict[str, Any]:
    target = Path(path).resolve()
    if not target.exists():
        return {"ok": False, "path": str(target), "error": "path missing"}
    if writable and not os.access(target, os.W_OK):
        return {"ok": False, "path": str(target), "error": "path is not writable"}
    usage = None
    try:
        disk = os.statvfs(str(target))
        free = disk.f_bavail * disk.f_frsize
        usage = {"free_bytes": free, "min_free_bytes": min_free_bytes}
        if min_free_bytes and free < min_free_bytes:
            return {"ok": False, "path": str(target), "disk": usage, "error": "insufficient free space"}
    except OSError as exc:
        return {"ok": False, "path": str(target), "error": str(exc)}
    return {"ok": True, "path": str(target), "disk": usage}


def _check_redis(url: str) -> dict[str, Any]:
    if _truthy(os.environ.get("WEBHDP_INLINE_TASKS")):
        return {"ok": True, "skipped": True, "reason": "WEBHDP_INLINE_TASKS is enabled"}
    if not url:
        return {"ok": False, "error": "redis url is not configured"}
    parsed = urlparse(url)
    if not parsed.scheme.startswith("redis"):
        return {"ok": True, "skipped": True, "reason": f"unsupported broker scheme {parsed.scheme}"}
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        pong = client.ping()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": bool(pong)}


def _check_backup(root: Path, backup_dir: str | None, max_age_seconds: int, required: bool) -> dict[str, Any]:
    status = BackupService.get_backup_status(output_dir=backup_dir, root=root)
    latest_age = status.get("latest_backup_age_seconds")
    latest = status.get("latest_backup")
    ok = bool(latest) and (latest_age is None or latest_age <= max_age_seconds)
    if not required and not latest:
        ok = True
    return {
        "ok": ok,
        "required": required,
        "latest_backup_age_seconds": latest_age,
        "max_age_seconds": max_age_seconds,
        "latest_archive": (latest or {}).get("archive_filename"),
        "backup_count": status.get("backup_count", 0),
    }


def _check_edm_validator(config) -> dict[str, Any]:
    if not _truthy(config.get("LOCAL_EDM_VALIDATOR_REQUIRED")):
        return {"ok": True, "skipped": True, "required": False}
    client = LocalEdmValidatorClient(config=config)
    health = client.check_health()
    result = {"ok": health["ok"], "required": True, "status": health.get("status")}
    if not health["ok"]:
        result["error"] = "Required local EDM validator did not report healthy"
        return result

    expected = expected_validator_identity(config)
    if expected:
        info = client.get_info()
        identity = dict(info.get("summary") or {}) if info.get("ok") else {}
        identity["source_ref"] = identity.get("git_commit") or identity.get("source_ref")
        differences = validator_identity_mismatches(expected, identity, allow_short_source_ref=True)
        if differences:
            result.update(ok=False, error="Required local EDM validator identity differs: " + ", ".join(differences))
    return result


def build_readiness_report(app=None, *, strict_backups: bool = False) -> dict[str, Any]:
    root = Path(os.getcwd()).resolve()
    config = app.config if app is not None else {}
    database_url = (
        os.environ.get("DATABASE_URL")
        or config.get("SQLALCHEMY_DATABASE_URI")
        or f"sqlite:///{root / 'instance' / 'hdp_web.db'}"
    )
    min_free_bytes = int(config.get("MIN_UPLOAD_FREE_BYTES") or os.environ.get("MIN_UPLOAD_FREE_BYTES") or 0)
    backup_required = strict_backups or _truthy(os.environ.get("BACKUP_ENABLED"))
    backup_dir = os.environ.get("BACKUP_LOCAL_DIR") or config.get("BACKUP_LOCAL_DIR")
    max_backup_age = int(config.get("BACKUP_MAX_AGE_SECONDS") or os.environ.get("BACKUP_MAX_AGE_SECONDS") or 26 * 60 * 60)

    checks = {
        "database": _check_sqlite(database_url, expected_alembic_revision=_alembic_head(root)),
        "sessions_path": _check_path(os.environ.get("WEBHDP_SESSIONS_PATH") or root / "hdp-shared" / "sessions", min_free_bytes=min_free_bytes),
        "local_input": _check_path(os.environ.get("LOCAL_INPUT_HOST_PATH") or root / "local_input", min_free_bytes=min_free_bytes),
        "local_output": _check_path(os.environ.get("LOCAL_OUTPUT_HOST_PATH") or root / "local_output", min_free_bytes=min_free_bytes),
        "backup": _check_backup(root, backup_dir, max_backup_age, backup_required),
        "redis": _check_redis(os.environ.get("CELERY_BROKER_URL") or config.get("CELERY_BROKER_URL") or ""),
        # The host-side maintenance CLI may run outside the application's Docker network.
        "local_edm_validator": _check_edm_validator(config) if app is not None else {
            "ok": True, "skipped": True, "reason": "checked by the running application's readiness endpoint",
        },
        "maintenance": maintenance_status(root),
    }
    blockers = [name for name, check in checks.items() if name != "maintenance" and not check.get("ok")]
    return {
        "ready": not blockers,
        "blockers": blockers,
        "checks": checks,
    }
