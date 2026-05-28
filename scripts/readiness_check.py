#!/usr/bin/env python3
"""Run deployment readiness checks without starting the web server."""

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

from services.readiness_service import build_readiness_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict-backups", action="store_true", help="Fail when no fresh backup is present")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_readiness_report(strict_backups=args.strict_backups)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Ready: {report['ready']}")
        if report["blockers"]:
            print("Blockers:")
            for blocker in report["blockers"]:
                print(f"- {blocker}: {report['checks'][blocker]}")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
