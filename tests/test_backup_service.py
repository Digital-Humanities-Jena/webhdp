import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from services.backup_service import BackupError, BackupService


def _create_sqlite_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO sample (value) VALUES ('kept')")
        conn.commit()
    finally:
        conn.close()


def test_backup_create_encrypt_and_restore_roundtrip(tmp_path, monkeypatch):
    root = tmp_path / "source"
    db_path = root / "instance" / "hdp_web.db"
    _create_sqlite_db(db_path)
    (root / "hdp-shared" / "sessions").mkdir(parents=True)
    (root / "hdp-shared" / "sessions" / "session.txt").write_text("session", encoding="utf-8")
    (root / "local_input").mkdir()
    (root / "local_input" / "input.txt").write_text("input", encoding="utf-8")
    (root / "local_output").mkdir()
    (root / "local_output" / "output.txt").write_text("output", encoding="utf-8")
    (root / "credentials").mkdir()
    (root / "credentials" / "note.txt").write_text("secret-ish", encoding="utf-8")

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", "backup-secret-" + "x" * 32)

    result = BackupService.create_backup(
        root=root,
        output_dir=tmp_path / "backups",
        backup_type="test",
        include_credentials=True,
    )

    archive = Path(result["archive_path"])
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert archive.name.endswith(".tar.gz.enc")
    assert manifest["encrypted"] is True
    assert "credentials" in manifest["paths"]
    assert manifest["archive_sha256"]

    target = tmp_path / "restore"
    restored = BackupService.restore_backup(archive_path=archive, target_root=target, force=True)
    assert restored["success"] is True
    assert (target / "local_input" / "input.txt").read_text(encoding="utf-8") == "input"
    assert (target / "local_output" / "output.txt").read_text(encoding="utf-8") == "output"

    conn = sqlite3.connect(target / "instance" / "hdp_web.db")
    try:
        assert conn.execute("SELECT value FROM sample").fetchone()[0] == "kept"
    finally:
        conn.close()


def test_cloud_backup_requires_encryption(tmp_path, monkeypatch):
    root = tmp_path / "source"
    db_path = root / "instance" / "hdp_web.db"
    _create_sqlite_db(db_path)
    (root / "hdp-shared" / "sessions").mkdir(parents=True)
    (root / "local_input").mkdir()
    (root / "local_output").mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.delenv("BACKUP_ENCRYPTION_KEY", raising=False)

    with pytest.raises(BackupError, match="Cloud backups must be encrypted"):
        BackupService.create_backup(
            root=root,
            output_dir=tmp_path / "backups",
            include_credentials=False,
            upload_provider="dropbox",
        )


def test_dropbox_backup_uploads_archive_and_manifest(tmp_path, monkeypatch):
    root = tmp_path / "source"
    db_path = root / "instance" / "hdp_web.db"
    _create_sqlite_db(db_path)
    (root / "hdp-shared" / "sessions").mkdir(parents=True)
    (root / "local_input").mkdir()
    (root / "local_output").mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", "backup-secret-" + "y" * 32)

    uploads = []

    def fake_upload(local_path, remote_path):
        uploads.append((os.path.basename(local_path), remote_path))
        return {"success": True, "storage_type": "dropbox", "remote_path": remote_path}

    monkeypatch.setattr("services.backup_service.CloudUploadService.upload_to_dropbox", fake_upload)

    result = BackupService.create_backup(
        root=root,
        output_dir=tmp_path / "backups",
        include_credentials=False,
        upload_provider="dropbox",
        remote_prefix="/WebHDP/backups-test",
        instance_id="unit",
    )

    assert result["manifest"]["upload"]["provider"] == "dropbox"
    assert len(uploads) == 2
    assert uploads[0][1].startswith("/WebHDP/backups-test/unit/")
    assert uploads[0][1].endswith(".tar.gz.enc")
    assert uploads[1][1].endswith(".manifest.json")


def test_backup_fails_when_required_data_paths_are_missing(tmp_path, monkeypatch):
    root = tmp_path / "source"
    db_path = root / "instance" / "hdp_web.db"
    _create_sqlite_db(db_path)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", "backup-secret-" + "m" * 32)

    with pytest.raises(BackupError, match="Backup required path"):
        BackupService.create_backup(
            root=root,
            output_dir=tmp_path / "backups",
            include_credentials=False,
        )


def test_prune_local_backups_respects_retention(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    old_archive = backup_dir / "old.tar.gz.enc"
    old_manifest = backup_dir / "old.manifest.json"
    new_archive = backup_dir / "new.tar.gz.enc"
    new_manifest = backup_dir / "new.manifest.json"
    old_archive.write_text("old", encoding="utf-8")
    new_archive.write_text("new", encoding="utf-8")
    old_manifest.write_text(
        json.dumps(
            {
                "created_at": (datetime.now(timezone.utc) - timedelta(days=40)).isoformat(),
                "archive_filename": old_archive.name,
            }
        ),
        encoding="utf-8",
    )
    new_manifest.write_text(
        json.dumps(
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "archive_filename": new_archive.name,
            }
        ),
        encoding="utf-8",
    )

    dry_run = BackupService.prune_local_backups(output_dir=backup_dir, retention_days=30, dry_run=True)
    assert dry_run["dry_run"] is True
    assert str(old_archive) in dry_run["deleted"]
    assert old_archive.exists()

    applied = BackupService.prune_local_backups(output_dir=backup_dir, retention_days=30, dry_run=False)
    assert applied["success"] is True
    assert not old_archive.exists()
    assert not old_manifest.exists()
    assert new_archive.exists()
    assert new_manifest.exists()


def test_backup_status_reports_latest_backup(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    manifest = backup_dir / "latest.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "archive_filename": "latest.tar.gz.enc",
            }
        ),
        encoding="utf-8",
    )
    (backup_dir / "latest.tar.gz.enc").write_text("archive", encoding="utf-8")

    status = BackupService.get_backup_status(output_dir=backup_dir, root=tmp_path)

    assert status["backup_count"] == 1
    assert status["latest_backup"]["archive_filename"] == "latest.tar.gz.enc"
    assert status["latest_backup_age_seconds"] is not None
