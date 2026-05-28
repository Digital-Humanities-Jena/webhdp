#!/usr/bin/env python3
"""Enable, disable, or inspect WebHDP maintenance mode."""

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

from services.maintenance_service import disable_maintenance, enable_maintenance, maintenance_status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    enable = subparsers.add_parser("enable")
    enable.add_argument("--reason", default="deployment update")
    subparsers.add_parser("disable")
    subparsers.add_parser("status")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "enable":
        result = enable_maintenance(args.reason, args.root)
    elif args.command == "disable":
        result = disable_maintenance(args.root)
    else:
        result = maintenance_status(args.root)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Maintenance enabled: {result.get('enabled')}")
        print(f"Path: {result.get('path') or result.get('flag_path')}")
        if result.get("reason"):
            print(f"Reason: {result.get('reason')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
