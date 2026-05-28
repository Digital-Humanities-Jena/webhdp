#!/usr/bin/env python3
"""Fail when docs/api/openapi.json is stale."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_openapi import OUTPUT_PATH, _build_spec


def main() -> int:
    expected = json.dumps(_build_spec(), indent=2, sort_keys=True) + "\n"
    if not OUTPUT_PATH.exists():
        print(f"{OUTPUT_PATH.relative_to(ROOT)} is missing. Run `make api-contract`.", file=sys.stderr)
        return 1

    current = OUTPUT_PATH.read_text(encoding="utf-8")
    if current != expected:
        print(
            f"{OUTPUT_PATH.relative_to(ROOT)} is stale. Run `make api-contract` and commit the result.",
            file=sys.stderr,
        )
        return 1

    print(f"{OUTPUT_PATH.relative_to(ROOT)} is up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
