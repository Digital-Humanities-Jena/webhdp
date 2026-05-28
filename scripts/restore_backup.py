#!/usr/bin/env python3
"""Restore a WebHDP operational backup archive."""

from __future__ import annotations

import argparse
import json
import sys
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
    parser.add_argument("--target-root", default=str(ROOT), help="WebHDP root to restore into")
    parser.add_argument("--force", action="store_true", help="Actually replace local data")
    parser.add_argument("--encryption-key", help="Backup encryption key; defaults to BACKUP_ENCRYPTION_KEY")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = BackupService.restore_backup(
            archive_path=args.archive,
            target_root=args.target_root,
            encryption_key=args.encryption_key,
            force=args.force,
        )
    except BackupError as exc:
        BackupService.record_status(
            operation="restore",
            success=False,
            root=args.target_root,
            error=str(exc),
        )
        print(f"Restore failed: {exc}", file=sys.stderr)
        return 1

    if not result.get("dry_run"):
        BackupService.record_status(
            operation="restore",
            success=True,
            root=args.target_root,
            details=result,
        )

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result.get("dry_run"):
        print(result["message"])
        print(f"Archive: {result['archive_path']}")
        print(f"Target root: {result['target_root']}")
    else:
        print(f"Restore completed into: {result['target_root']}")
        for path in result.get("restored_paths", []):
            print(f"Restored: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
