#!/usr/bin/env python3
"""Check that a SQLite deployment still contains its existing accounts."""

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys


def read_accounts(database: Path) -> dict:
    uri = database.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=10)) as connection:
        rows = connection.execute("SELECT id, email, created_at, role, is_verified FROM users").fetchall()

    if not rows:
        raise ValueError("the database has no existing WebHDP accounts")

    accounts = {}
    for user_id, email, created_at, role, is_verified in rows:
        # Keep account names and credentials out of the operator snapshot.
        identity = json.dumps([user_id, email, created_at]).encode("utf-8")
        accounts[hashlib.sha256(identity).hexdigest()] = {"role": role, "verified": bool(is_verified)}
    return accounts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capture", "verify"))
    parser.add_argument("--database", required=True, type=Path, help="Path to the SQLite file used by WebHDP")
    parser.add_argument("--snapshot", required=True, type=Path, help="Path for the private pre-update snapshot")
    args = parser.parse_args(argv)

    try:
        current = read_accounts(args.database)
        if args.action == "capture":
            descriptor = os.open(args.snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(current, stream)
            print(f"Captured {len(current)} existing WebHDP accounts.")
        else:
            baseline = json.loads(args.snapshot.read_text(encoding="utf-8"))
            if not isinstance(baseline, dict) or not baseline:
                raise ValueError("the pre-update account snapshot is invalid")
            missing = baseline.keys() - current.keys()
            changed = sum(
                previous["role"] != current[account]["role"]
                or (previous["verified"] and not current[account]["verified"])
                for account, previous in baseline.items()
                if account in current
            )
            if missing or changed:
                raise ValueError(f"{len(missing)} accounts missing and {changed} with changed roles or lost verification")
            print(f"Verified that all {len(baseline)} pre-update accounts remain present.")
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
        print(f"Account continuity check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
