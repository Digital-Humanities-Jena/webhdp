"""Operational backup and restore helpers for WebHDP deployments.

The service intentionally stays independent from session cloud mirroring:
mirrors are user-facing source-artifact copies, while these backups are
operator-facing disaster-recovery archives.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy.engine.url import make_url

from services.cloud_upload_service import CloudUploadService, STORAGE_DROPBOX


BACKUP_FORMAT_VERSION = 1
ENCRYPTION_MAGIC = b"WEBHDPBKP1\0"
KDF_ITERATIONS = 390_000
SALT_SIZE = 16
NONCE_SIZE = 16
HMAC_SIZE = 32
CHUNK_SIZE = 1024 * 1024


class BackupError(RuntimeError):
    """Raised when a backup or restore operation cannot complete safely."""


@dataclasses.dataclass(frozen=True)
class BackupPaths:
    """Resolved local paths used by the backup service."""

    root: Path
    database: Path
    sessions: Path
    local_input: Path
    local_output: Path
    credentials: Path


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _derive_crypto_keys(secret: str, salt: bytes) -> tuple[bytes, bytes]:
    if not secret or not secret.strip():
        raise BackupError("BACKUP_ENCRYPTION_KEY is required for encrypted backups")

    key_material = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=64,
        salt=salt,
        iterations=KDF_ITERATIONS,
    ).derive(secret.encode("utf-8"))
    return key_material[:32], key_material[32:]


def encrypt_file(source: Path, target: Path, secret: str) -> None:
    """Encrypt a file with streaming AES-CTR plus HMAC-SHA256 authentication."""

    salt = os.urandom(SALT_SIZE)
    nonce = os.urandom(NONCE_SIZE)
    encryption_key, mac_key = _derive_crypto_keys(secret, salt)
    cipher = Cipher(algorithms.AES(encryption_key), modes.CTR(nonce)).encryptor()
    mac = hmac.new(mac_key, digestmod=hashlib.sha256)
    header = ENCRYPTION_MAGIC + salt + nonce
    mac.update(header)

    with source.open("rb") as src, target.open("wb") as dst:
        dst.write(header)
        for chunk in iter(lambda: src.read(CHUNK_SIZE), b""):
            encrypted = cipher.update(chunk)
            mac.update(encrypted)
            dst.write(encrypted)
        encrypted = cipher.finalize()
        if encrypted:
            mac.update(encrypted)
            dst.write(encrypted)
        dst.write(mac.digest())


def decrypt_file(source: Path, target: Path, secret: str) -> None:
    """Decrypt and authenticate a backup archive produced by :func:`encrypt_file`."""

    size = source.stat().st_size
    header_size = len(ENCRYPTION_MAGIC) + SALT_SIZE + NONCE_SIZE
    if size < header_size + HMAC_SIZE:
        raise BackupError("Encrypted backup is too small or truncated")

    with source.open("rb") as src:
        header = src.read(header_size)
        if not header.startswith(ENCRYPTION_MAGIC):
            raise BackupError("Encrypted backup header is not recognized")
        salt = header[len(ENCRYPTION_MAGIC): len(ENCRYPTION_MAGIC) + SALT_SIZE]
        nonce = header[-NONCE_SIZE:]
        encryption_key, mac_key = _derive_crypto_keys(secret, salt)
        mac = hmac.new(mac_key, digestmod=hashlib.sha256)
        mac.update(header)

        remaining_ciphertext = size - header_size - HMAC_SIZE
        with tempfile.NamedTemporaryFile(delete=False) as temp:
            temp_path = Path(temp.name)
            while remaining_ciphertext > 0:
                chunk = src.read(min(CHUNK_SIZE, remaining_ciphertext))
                if not chunk:
                    raise BackupError("Encrypted backup ended before the authentication tag")
                remaining_ciphertext -= len(chunk)
                mac.update(chunk)
                temp.write(chunk)
            expected_tag = src.read(HMAC_SIZE)

    try:
        if not hmac.compare_digest(mac.digest(), expected_tag):
            raise BackupError("Encrypted backup authentication failed")

        cipher = Cipher(algorithms.AES(encryption_key), modes.CTR(nonce)).decryptor()
        with temp_path.open("rb") as encrypted, target.open("wb") as plain:
            for chunk in iter(lambda: encrypted.read(CHUNK_SIZE), b""):
                plain.write(cipher.update(chunk))
            plain.write(cipher.finalize())
    finally:
        temp_path.unlink(missing_ok=True)


class BackupService:
    """Create, upload, list, and restore WebHDP operational backups."""

    @staticmethod
    def _resolve_root_path(root_path: Path, value: str | Path | None, default: Path) -> Path:
        raw = Path(value) if value else default
        if not raw.is_absolute():
            raw = root_path / raw
        return raw.resolve()

    @staticmethod
    def resolve_paths(root: str | Path | None = None, database_url: str | None = None) -> BackupPaths:
        root_path = Path(root or os.getcwd()).resolve()
        database = BackupService.sqlite_path_from_url(
            database_url or os.environ.get("DATABASE_URL") or f"sqlite:///{root_path / 'instance' / 'hdp_web.db'}",
            root_path=root_path,
        )
        return BackupPaths(
            root=root_path,
            database=database,
            sessions=BackupService._resolve_root_path(
                root_path,
                os.environ.get("WEBHDP_SESSIONS_PATH"),
                root_path / "hdp-shared" / "sessions",
            ),
            local_input=BackupService._resolve_root_path(
                root_path,
                os.environ.get("LOCAL_INPUT_HOST_PATH"),
                root_path / "local_input",
            ),
            local_output=BackupService._resolve_root_path(
                root_path,
                os.environ.get("LOCAL_OUTPUT_HOST_PATH"),
                root_path / "local_output",
            ),
            credentials=BackupService._resolve_root_path(
                root_path,
                os.environ.get("CREDENTIALS_HOST_PATH"),
                root_path / "credentials",
            ),
        )

    @staticmethod
    def sqlite_path_from_url(database_url: str, root_path: str | Path | None = None) -> Path:
        try:
            url = make_url(database_url)
        except Exception as exc:
            raise BackupError(f"Could not parse DATABASE_URL for backup: {exc}") from exc
        if url.drivername not in {"sqlite", "sqlite+pysqlite"}:
            raise BackupError("BackupService currently supports SQLite DATABASE_URL values only")
        if not url.database or url.database == ":memory:":
            raise BackupError("BackupService requires a file-backed SQLite database")
        database = Path(url.database)
        if not database.is_absolute() and root_path is not None:
            database = Path(root_path).resolve() / database
        return database.resolve()

    @staticmethod
    def validate_paths(paths: BackupPaths, include_credentials: bool) -> None:
        required = {
            "database": paths.database,
            "sessions": paths.sessions,
            "local_input": paths.local_input,
            "local_output": paths.local_output,
        }
        missing = [f"{name}={path}" for name, path in required.items() if not path.exists()]
        if include_credentials and not paths.credentials.exists():
            missing.append(f"credentials={paths.credentials}")
        if missing:
            raise BackupError("Backup required path(s) are missing: " + "; ".join(missing))
        if not paths.database.is_file():
            raise BackupError(f"SQLite database path is not a file: {paths.database}")

    @staticmethod
    def _archive_entries(paths: BackupPaths, include_credentials: bool) -> list[tuple[Path, str]]:
        BackupService.validate_paths(paths, include_credentials)
        entries = [(paths.database, "instance/hdp_web.db")]
        for path, arcname in (
            (paths.sessions, "hdp-shared/sessions"),
            (paths.local_input, "local_input"),
            (paths.local_output, "local_output"),
        ):
            entries.append((path, arcname))
        if include_credentials and paths.credentials.exists():
            entries.append((paths.credentials, "credentials"))
        return entries

    @staticmethod
    def _copy_sqlite_database(source: Path, target: Path) -> None:
        if not source.exists():
            raise BackupError(f"SQLite database not found: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        source_conn = sqlite3.connect(str(source))
        try:
            target_conn = sqlite3.connect(str(target))
            try:
                source_conn.backup(target_conn)
            finally:
                target_conn.close()
        finally:
            source_conn.close()

    @staticmethod
    def _iter_files_for_manifest(entries: Iterable[tuple[Path, str]]) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        for path, arcname in entries:
            if path.is_file():
                files.append({
                    "path": arcname,
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                })
                continue
            if path.is_dir():
                for child in sorted(p for p in path.rglob("*") if p.is_file()):
                    relative = PurePosixPath(arcname) / child.relative_to(path).as_posix()
                    files.append({
                        "path": str(relative),
                        "size": child.stat().st_size,
                        "sha256": sha256_file(child),
                    })
        return files

    @staticmethod
    def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @staticmethod
    def _status_path(output_dir: str | Path | None = None, root: str | Path | None = None) -> Path:
        root_path = Path(root or os.getcwd()).resolve()
        directory = Path(output_dir or os.environ.get("BACKUP_LOCAL_DIR") or root_path / "backups").resolve()
        return directory / "backup_status.json"

    @staticmethod
    def record_status(
        *,
        operation: str,
        success: bool,
        output_dir: str | Path | None = None,
        root: str | Path | None = None,
        details: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        status_path = BackupService._status_path(output_dir, root)
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status = {}
        if status_path.exists():
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                status = {}
        key = f"last_{operation}_{'success' if success else 'failure'}"
        status[key] = {
            "at": datetime.now(timezone.utc).isoformat(),
            "details": details or {},
            "error": error,
        }
        status["last_operation"] = {
            "operation": operation,
            "success": bool(success),
            "at": status[key]["at"],
        }
        status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return status

    @staticmethod
    def _parse_created_at(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def create_backup(
        cls,
        *,
        root: str | Path | None = None,
        output_dir: str | Path | None = None,
        backup_type: str = "manual",
        include_credentials: bool | None = None,
        encrypt: bool | None = None,
        upload_provider: str | None = None,
        remote_prefix: str | None = None,
        instance_id: str | None = None,
    ) -> dict[str, Any]:
        paths = cls.resolve_paths(root)
        output = Path(output_dir or os.environ.get("BACKUP_LOCAL_DIR") or paths.root / "backups").resolve()
        output.mkdir(parents=True, exist_ok=True)
        timestamp = utc_timestamp()
        instance = instance_id or os.environ.get("WEBHDP_INSTANCE_ID") or paths.root.name or "webhdp"
        include_creds = (
            include_credentials
            if include_credentials is not None
            else str(os.environ.get("BACKUP_INCLUDE_CREDENTIALS", "true")).lower() in {"1", "true", "yes", "on"}
        )
        encryption_key = os.environ.get("BACKUP_ENCRYPTION_KEY", "")
        should_encrypt = encrypt if encrypt is not None else bool(encryption_key)
        provider = (upload_provider or os.environ.get("BACKUP_PROVIDER") or "local").strip().lower()
        if provider != "local" and not should_encrypt:
            raise BackupError("Cloud backups must be encrypted. Set BACKUP_ENCRYPTION_KEY.")
        if should_encrypt and not encryption_key:
            raise BackupError("BACKUP_ENCRYPTION_KEY is required when encryption is enabled")
        if include_creds and not should_encrypt:
            raise BackupError("Credential backups require encryption. Set BACKUP_ENCRYPTION_KEY or disable credentials.")

        archive_stem = f"webhdp-{instance}-{backup_type}-{timestamp}"
        plain_archive = output / f"{archive_stem}.tar.gz"
        manifest_path = output / f"{archive_stem}.manifest.json"
        final_archive = output / f"{archive_stem}.tar.gz.enc" if should_encrypt else plain_archive

        with tempfile.TemporaryDirectory(prefix="webhdp-backup-") as temp_dir:
            temp_root = Path(temp_dir)
            db_copy = temp_root / "instance" / "hdp_web.db"
            cls._copy_sqlite_database(paths.database, db_copy)
            entries = cls._archive_entries(
                dataclasses.replace(paths, database=db_copy),
                include_credentials=include_creds,
            )
            manifest = {
                "format_version": BACKUP_FORMAT_VERSION,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "backup_type": backup_type,
                "instance_id": instance,
                "database_url_type": "sqlite",
                "database_source": str(paths.database),
                "encrypted": bool(should_encrypt),
                "include_credentials": bool(include_creds),
                "source_paths": {
                    "root": str(paths.root),
                    "database": str(paths.database),
                    "sessions": str(paths.sessions),
                    "local_input": str(paths.local_input),
                    "local_output": str(paths.local_output),
                    "credentials": str(paths.credentials) if include_creds else None,
                },
                "paths": [arcname for _, arcname in entries],
                "files": cls._iter_files_for_manifest(entries),
            }
            manifest_temp = temp_root / "manifest.json"
            cls._write_manifest(manifest_temp, manifest)

            with tarfile.open(plain_archive, "w:gz") as archive:
                archive.add(manifest_temp, arcname="manifest.json")
                for source, arcname in entries:
                    archive.add(source, arcname=arcname)

        if should_encrypt:
            encrypt_file(plain_archive, final_archive, encryption_key)
            plain_archive.unlink(missing_ok=True)

        manifest_sidecar = {
            **manifest,
            "archive_filename": final_archive.name,
            "archive_size": final_archive.stat().st_size,
            "archive_sha256": sha256_file(final_archive),
            "upload": None,
        }

        if provider == STORAGE_DROPBOX:
            prefix = (remote_prefix or os.environ.get("BACKUP_REMOTE_PREFIX") or "/WebHDP/backups").rstrip("/")
            remote_base = f"{prefix}/{instance}/{timestamp}"
            archive_upload = CloudUploadService.upload_to_dropbox(str(final_archive), f"{remote_base}/{final_archive.name}")
            cls._write_manifest(manifest_path, manifest_sidecar)
            manifest_upload = CloudUploadService.upload_to_dropbox(str(manifest_path), f"{remote_base}/{manifest_path.name}")
            manifest_sidecar["upload"] = {
                "provider": STORAGE_DROPBOX,
                "archive": archive_upload,
                "manifest": manifest_upload,
                "remote_prefix": remote_base,
            }
        elif provider not in {"", "local"}:
            raise BackupError(f"Unsupported backup provider: {provider}")

        cls._write_manifest(manifest_path, manifest_sidecar)
        cls.record_status(
            operation="backup",
            success=True,
            output_dir=output,
            root=paths.root,
            details={
                "archive_path": str(final_archive),
                "manifest_path": str(manifest_path),
                "backup_type": backup_type,
                "provider": provider,
                "archive_size": manifest_sidecar["archive_size"],
                "archive_sha256": manifest_sidecar["archive_sha256"],
            },
        )
        return {
            "success": True,
            "archive_path": str(final_archive),
            "manifest_path": str(manifest_path),
            "manifest": manifest_sidecar,
        }

    @staticmethod
    def _validate_tar_member(member: tarfile.TarInfo) -> None:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise BackupError(f"Unsafe path in backup archive: {member.name}")

    @classmethod
    def restore_backup(
        cls,
        *,
        archive_path: str | Path,
        target_root: str | Path | None = None,
        encryption_key: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        archive = Path(archive_path).resolve()
        root = Path(target_root or os.getcwd()).resolve()
        if not archive.exists():
            raise BackupError(f"Backup archive not found: {archive}")

        if not force:
            return {
                "success": False,
                "dry_run": True,
                "message": "Restore dry run only. Re-run with --force to replace local data.",
                "archive_path": str(archive),
                "target_root": str(root),
            }

        with tempfile.TemporaryDirectory(prefix="webhdp-restore-") as temp_dir:
            temp_root = Path(temp_dir)
            tar_path = archive
            if archive.suffix == ".enc":
                secret = encryption_key or os.environ.get("BACKUP_ENCRYPTION_KEY", "")
                tar_path = temp_root / archive.name.removesuffix(".enc")
                decrypt_file(archive, tar_path, secret)

            extract_root = temp_root / "extract"
            extract_root.mkdir()
            with tarfile.open(tar_path, "r:gz") as tar:
                for member in tar.getmembers():
                    cls._validate_tar_member(member)
                tar.extractall(extract_root)

            manifest_file = extract_root / "manifest.json"
            if not manifest_file.exists():
                raise BackupError("Backup archive does not contain manifest.json")
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

            restore_backup_dir = root / f"pre_restore_backup_{utc_timestamp()}"
            restored_paths: list[str] = []
            for relative in manifest.get("paths", []):
                source = extract_root / relative
                target = root / relative
                if not source.exists():
                    continue
                if target.exists():
                    safety_copy = restore_backup_dir / relative
                    safety_copy.parent.mkdir(parents=True, exist_ok=True)
                    if target.is_dir():
                        shutil.copytree(target, safety_copy, dirs_exist_ok=True)
                        shutil.rmtree(target)
                    else:
                        shutil.copy2(target, safety_copy)
                        target.unlink()
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(source, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(source, target)
                restored_paths.append(relative)

            verification = cls.verify_restored_manifest(root, manifest)

        return {
            "success": True,
            "archive_path": str(archive),
            "target_root": str(root),
            "restored_paths": restored_paths,
            "verification": verification,
        }

    @staticmethod
    def verify_restored_manifest(root: str | Path, manifest: dict[str, Any]) -> dict[str, Any]:
        root_path = Path(root).resolve()
        missing_paths = []
        mismatched_files = []
        verified_files = 0

        for relative in manifest.get("paths", []):
            if not (root_path / relative).exists():
                missing_paths.append(str(relative))

        for file_entry in manifest.get("files", []):
            relative = str(file_entry.get("path") or "")
            if not relative:
                continue
            target = root_path / relative
            if not target.is_file():
                mismatched_files.append({"path": relative, "error": "missing"})
                continue
            expected_sha = str(file_entry.get("sha256") or "")
            actual_sha = sha256_file(target)
            if expected_sha and actual_sha != expected_sha:
                mismatched_files.append({"path": relative, "error": "sha256 mismatch"})
                continue
            verified_files += 1

        ok = not missing_paths and not mismatched_files
        if not ok:
            raise BackupError(
                "Restored backup verification failed: "
                f"missing_paths={missing_paths}, mismatched_files={mismatched_files}"
            )
        return {
            "ok": True,
            "verified_files": verified_files,
            "verified_paths": len(manifest.get("paths", [])),
        }

    @staticmethod
    def list_local_backups(output_dir: str | Path | None = None, root: str | Path | None = None) -> list[dict[str, Any]]:
        root_path = Path(root or os.getcwd()).resolve()
        directory = Path(output_dir or os.environ.get("BACKUP_LOCAL_DIR") or root_path / "backups").resolve()
        if not directory.exists():
            return []
        backups = []
        for manifest_path in sorted(directory.glob("*.manifest.json")):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                payload["manifest_path"] = str(manifest_path)
                archive_filename = payload.get("archive_filename")
                if archive_filename:
                    archive_path = directory / str(archive_filename)
                    payload["archive_path"] = str(archive_path)
                    payload["archive_exists"] = archive_path.exists()
                backups.append(payload)
            except json.JSONDecodeError:
                backups.append({"manifest_path": str(manifest_path), "error": "invalid manifest json"})
        return backups

    @staticmethod
    def get_backup_status(output_dir: str | Path | None = None, root: str | Path | None = None) -> dict[str, Any]:
        backups = BackupService.list_local_backups(output_dir, root)
        latest = None
        for backup in backups:
            created_at = BackupService._parse_created_at(backup.get("created_at"))
            if created_at is None:
                continue
            if latest is None or created_at > latest[0]:
                latest = (created_at, backup)

        status_path = BackupService._status_path(output_dir, root)
        persisted_status = {}
        if status_path.exists():
            try:
                persisted_status = json.loads(status_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                persisted_status = {"error": "invalid status json"}

        latest_backup = latest[1] if latest else None
        latest_age_seconds = None
        if latest:
            latest_age_seconds = int((datetime.now(timezone.utc) - latest[0]).total_seconds())

        return {
            "backup_count": len(backups),
            "latest_backup": latest_backup,
            "latest_backup_age_seconds": latest_age_seconds,
            "status_path": str(status_path),
            "status": persisted_status,
        }

    @staticmethod
    def prune_local_backups(
        *,
        output_dir: str | Path | None = None,
        root: str | Path | None = None,
        retention_days: int | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        root_path = Path(root or os.getcwd()).resolve()
        directory = Path(output_dir or os.environ.get("BACKUP_LOCAL_DIR") or root_path / "backups").resolve()
        days = int(retention_days if retention_days is not None else os.environ.get("BACKUP_RETENTION_DAYS", 30))
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        deleted: list[str] = []
        kept: list[str] = []
        errors: list[dict[str, str]] = []

        for backup in BackupService.list_local_backups(directory, root_path):
            created_at = BackupService._parse_created_at(backup.get("created_at"))
            manifest_path = Path(str(backup.get("manifest_path") or ""))
            archive_path = Path(str(backup.get("archive_path") or ""))
            if created_at is None or created_at >= cutoff:
                kept.append(str(manifest_path))
                continue
            for candidate in (archive_path, manifest_path):
                if not str(candidate) or not candidate.exists():
                    continue
                if dry_run:
                    deleted.append(str(candidate))
                    continue
                try:
                    candidate.unlink()
                    deleted.append(str(candidate))
                except OSError as exc:
                    errors.append({"path": str(candidate), "error": str(exc)})

        result = {
            "success": not errors,
            "dry_run": bool(dry_run),
            "retention_days": days,
            "deleted": deleted,
            "kept": kept,
            "errors": errors,
        }
        BackupService.record_status(
            operation="prune",
            success=not errors,
            output_dir=directory,
            root=root_path,
            details=result,
            error=None if not errors else "One or more backup files could not be pruned.",
        )
        return result

    @staticmethod
    def list_dropbox_backups(remote_prefix: str | None = None) -> list[dict[str, Any]]:
        import dropbox

        app_key = os.getenv("DROPBOX_APP_KEY")
        app_secret = os.getenv("DROPBOX_APP_SECRET")
        refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN")
        if not all([app_key, app_secret, refresh_token]):
            raise BackupError("Dropbox backup listing requires DROPBOX_APP_KEY, DROPBOX_APP_SECRET, and DROPBOX_REFRESH_TOKEN")

        dbx = dropbox.Dropbox(app_key=app_key, app_secret=app_secret, oauth2_refresh_token=refresh_token)
        prefix = remote_prefix or os.environ.get("BACKUP_REMOTE_PREFIX") or "/WebHDP/backups"
        result = dbx.files_list_folder(prefix, recursive=True)
        entries = list(result.entries)
        while result.has_more:
            result = dbx.files_list_folder_continue(result.cursor)
            entries.extend(result.entries)
        return [
            {
                "name": getattr(entry, "name", ""),
                "path": getattr(entry, "path_display", ""),
                "size": getattr(entry, "size", None),
            }
            for entry in entries
            if getattr(entry, "name", "").endswith((".tar.gz.enc", ".manifest.json"))
        ]

    @staticmethod
    def prune_dropbox_backups(
        *,
        remote_prefix: str | None = None,
        retention_days: int | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        import dropbox

        app_key = os.getenv("DROPBOX_APP_KEY")
        app_secret = os.getenv("DROPBOX_APP_SECRET")
        refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN")
        if not all([app_key, app_secret, refresh_token]):
            raise BackupError("Dropbox backup pruning requires DROPBOX_APP_KEY, DROPBOX_APP_SECRET, and DROPBOX_REFRESH_TOKEN")

        dbx = dropbox.Dropbox(app_key=app_key, app_secret=app_secret, oauth2_refresh_token=refresh_token)
        days = int(retention_days if retention_days is not None else os.environ.get("BACKUP_RETENTION_DAYS", 30))
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        entries = BackupService.list_dropbox_backups(remote_prefix)
        deleted: list[str] = []
        kept: list[str] = []
        errors: list[dict[str, str]] = []

        for entry in entries:
            path = str(entry.get("path") or "")
            if not path:
                continue
            try:
                metadata = dbx.files_get_metadata(path)
                modified = getattr(metadata, "server_modified", None) or getattr(metadata, "client_modified", None)
                if modified and modified.tzinfo is None:
                    modified = modified.replace(tzinfo=timezone.utc)
            except Exception as exc:
                errors.append({"path": path, "error": str(exc)})
                continue
            if not modified or modified.astimezone(timezone.utc) >= cutoff:
                kept.append(path)
                continue
            if dry_run:
                deleted.append(path)
                continue
            try:
                dbx.files_delete_v2(path)
                deleted.append(path)
            except Exception as exc:
                errors.append({"path": path, "error": str(exc)})

        return {
            "success": not errors,
            "dry_run": bool(dry_run),
            "retention_days": days,
            "deleted": deleted,
            "kept": kept,
            "errors": errors,
        }
