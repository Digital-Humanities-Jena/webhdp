#!/usr/bin/env python3
"""Create a WebHDP operational backup archive."""

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
    parser.add_argument("--root", default=str(ROOT), help="WebHDP project/deployment root")
    parser.add_argument("--output-dir", help="Local backup output directory")
    parser.add_argument("--type", default="manual", dest="backup_type", help="Backup type label")
    parser.add_argument("--provider", default=None, help="Upload provider: local or dropbox")
    parser.add_argument("--remote-prefix", help="Remote backup prefix, e.g. /WebHDP/backups")
    parser.add_argument("--instance-id", help="Stable deployment identifier for backup paths")
    parser.add_argument("--no-credentials", action="store_true", help="Exclude credentials/ from the archive")
    parser.add_argument("--encrypt", action="store_true", help="Require encryption even for local-only backups")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = BackupService.create_backup(
            root=args.root,
            output_dir=args.output_dir,
            backup_type=args.backup_type,
            include_credentials=not args.no_credentials,
            encrypt=True if args.encrypt else None,
            upload_provider=args.provider,
            remote_prefix=args.remote_prefix,
            instance_id=args.instance_id,
        )
    except BackupError as exc:
        BackupService.record_status(
            operation="backup",
            success=False,
            output_dir=args.output_dir,
            root=args.root,
            error=str(exc),
        )
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Backup created: {result['archive_path']}")
        print(f"Manifest: {result['manifest_path']}")
        upload = result["manifest"].get("upload")
        if upload:
            print(f"Uploaded to {upload['provider']}: {upload['remote_prefix']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
