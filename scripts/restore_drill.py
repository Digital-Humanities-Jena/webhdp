#!/usr/bin/env python3
"""Restore a backup into an isolated directory and verify its contents."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from services.backup_service import BackupError, BackupService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", help="Local .tar.gz or .tar.gz.enc backup archive")
    parser.add_argument("--target-root", help="Restore target. Defaults to a temporary drill directory")
    parser.add_argument("--keep-target", action="store_true", help="Do not delete the temporary restore target")
    parser.add_argument("--encryption-key", help="Backup encryption key; defaults to BACKUP_ENCRYPTION_KEY")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    return parser.parse_args()


def sqlite_integrity_check(database_path: Path) -> str:
    if not database_path.is_file():
        raise BackupError(f"Restored SQLite database not found: {database_path}")
    connection = sqlite3.connect(str(database_path))
    try:
        row = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()
    result = str(row[0] if row else "")
    if result.lower() != "ok":
        raise BackupError(f"Restored SQLite integrity check failed: {result}")
    return result


def main() -> int:
    args = parse_args()
    temp_dir = None
    target_root = Path(args.target_root).resolve() if args.target_root else None
    if target_root is None:
        temp_dir = tempfile.mkdtemp(prefix="webhdp-restore-drill-")
        target_root = Path(temp_dir).resolve()

    try:
        restored = BackupService.restore_backup(
            archive_path=args.archive,
            target_root=target_root,
            encryption_key=args.encryption_key,
            force=True,
        )
        integrity = sqlite_integrity_check(target_root / "instance" / "hdp_web.db")
        result = {
            "success": True,
            "target_root": str(target_root),
            "archive_path": str(Path(args.archive).resolve()),
            "sqlite_integrity_check": integrity,
            "restored_paths": restored.get("restored_paths", []),
            "verification": restored.get("verification", {}),
        }
    except BackupError as exc:
        result = {
            "success": False,
            "target_root": str(target_root),
            "archive_path": str(Path(args.archive).resolve()),
            "error": str(exc),
        }
        BackupService.record_status(operation="restore_drill", success=False, root=ROOT, error=str(exc))
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"Restore drill failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if temp_dir and not args.keep_target:
            shutil.rmtree(temp_dir, ignore_errors=True)

    BackupService.record_status(operation="restore_drill", success=True, root=ROOT, details=result)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Restore drill passed for: {result['archive_path']}")
        print(f"SQLite integrity check: {integrity}")
        print(f"Verified files: {result['verification'].get('verified_files', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
