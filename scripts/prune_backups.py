#!/usr/bin/env python3
"""Prune local or Dropbox WebHDP operational backups by retention policy."""

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
    parser.add_argument("--retention-days", type=int, help="Retention window in days")
    parser.add_argument("--apply", action="store_true", help="Delete old backups. Default is dry run.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.provider == "dropbox":
            result = BackupService.prune_dropbox_backups(
                remote_prefix=args.remote_prefix,
                retention_days=args.retention_days,
                dry_run=not args.apply,
            )
        else:
            result = BackupService.prune_local_backups(
                output_dir=args.output_dir,
                root=args.root,
                retention_days=args.retention_days,
                dry_run=not args.apply,
            )
    except BackupError as exc:
        print(f"Could not prune backups: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        mode = "dry run" if result.get("dry_run") else "applied"
        print(f"Prune {mode}: {len(result.get('deleted', []))} old files matched")
        for path in result.get("deleted", []):
            print(f"delete: {path}")
        for item in result.get("errors", []):
            print(f"error: {item['path']}: {item['error']}", file=sys.stderr)
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
