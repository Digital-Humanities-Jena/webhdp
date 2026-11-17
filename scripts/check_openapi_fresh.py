#!/usr/bin/env python3
"""Fail when either WebHDP OpenAPI contract is missing or stale."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_openapi import contracts


def main() -> int:
    success = True
    for path, spec in contracts().items():
        expected = json.dumps(spec, indent=2, sort_keys=True) + "\n"
        if not path.exists() or path.read_text(encoding="utf-8") != expected:
            print(f"{path.relative_to(ROOT)} needs regeneration. Run `make api-contract`.", file=sys.stderr)
            success = False
        else:
            print(f"{path.relative_to(ROOT)} is up to date.")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
