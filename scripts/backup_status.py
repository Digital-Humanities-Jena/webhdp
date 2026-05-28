#!/usr/bin/env python3
"""Show WebHDP operational backup status."""

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

from services.backup_service import BackupService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT), help="WebHDP root used to resolve the default local backup dir")
    parser.add_argument("--output-dir", help="Local backup directory")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    status = BackupService.get_backup_status(args.output_dir, args.root)
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        latest = status.get("latest_backup") or {}
        print(f"Backup count: {status.get('backup_count', 0)}")
        print(f"Latest archive: {latest.get('archive_filename') or 'none'}")
        print(f"Latest age seconds: {status.get('latest_backup_age_seconds')}")
        last_operation = (status.get("status") or {}).get("last_operation") or {}
        if last_operation:
            print(
                "Last operation: "
                f"{last_operation.get('operation')} "
                f"success={last_operation.get('success')} "
                f"at={last_operation.get('at')}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
