#!/usr/bin/env python3
"""List local or Dropbox WebHDP operational backups."""

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
    parser.add_argument("--root", default=str(ROOT), help="WebHDP root used to resolve the default local backup dir")
    parser.add_argument("--output-dir", help="Local backup directory")
    parser.add_argument("--provider", choices=["local", "dropbox"], default="local")
    parser.add_argument("--remote-prefix", help="Dropbox backup prefix")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.provider == "dropbox":
            backups = BackupService.list_dropbox_backups(args.remote_prefix)
        else:
            backups = BackupService.list_local_backups(args.output_dir, args.root)
    except BackupError as exc:
        print(f"Could not list backups: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(backups, indent=2, sort_keys=True))
    else:
        if not backups:
            print("No backups found.")
        for backup in backups:
            name = backup.get("archive_filename") or backup.get("name") or backup.get("archive_path")
            created = backup.get("created_at") or ""
            size = backup.get("archive_size") or backup.get("size") or ""
            print(f"{created} {name} {size}".strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
