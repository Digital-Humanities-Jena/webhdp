#!/usr/bin/env python3
"""Wait until the Celery queue has no queued, reserved, or active work."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def _queue_depth_from_redis(broker_url: str, queue_name: str) -> dict[str, int]:
    import redis

    client = redis.Redis.from_url(broker_url, socket_connect_timeout=2, socket_timeout=2)
    return {
        "queued": int(client.llen(queue_name)),
        "unacked": int(client.hlen("unacked")),
    }


def _worker_depth_from_celery() -> dict[str, int]:
    from celery_app import celery

    inspector = celery.control.inspect(timeout=2)
    active = inspector.active() or {}
    reserved = inspector.reserved() or {}
    scheduled = inspector.scheduled() or {}
    return {
        "active": sum(len(items or []) for items in active.values()),
        "reserved": sum(len(items or []) for items in reserved.values()),
        "scheduled": sum(len(items or []) for items in scheduled.values()),
    }


def current_depth(queue_name: str) -> dict[str, int]:
    broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
    depth = _queue_depth_from_redis(broker_url, queue_name)
    try:
        depth.update(_worker_depth_from_celery())
    except Exception as exc:
        depth["inspect_error"] = 1
        depth["inspect_error_message"] = str(exc)
    depth["total"] = sum(value for key, value in depth.items() if key in {"queued", "unacked", "active", "reserved", "scheduled"})
    return depth


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", default=os.environ.get("CELERY_QUEUE_NAME", "celery"))
    parser.add_argument("--timeout-seconds", type=int, default=int(os.environ.get("UPDATE_DRAIN_TIMEOUT_SECONDS", "900")))
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--allow-unavailable", action="store_true", help="Return success if Redis/Celery cannot be inspected")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    deadline = time.time() + args.timeout_seconds
    last_depth = {}
    while time.time() <= deadline:
        try:
            last_depth = current_depth(args.queue)
        except Exception as exc:
            if args.allow_unavailable:
                result = {"drained": True, "warning": str(exc)}
                print(json.dumps(result, indent=2, sort_keys=True) if args.json else f"Drain check skipped: {exc}")
                return 0
            print(f"Could not inspect Celery drain state: {exc}", file=sys.stderr)
            return 1
        if int(last_depth.get("total", 0)) == 0:
            result = {"drained": True, "depth": last_depth}
            print(json.dumps(result, indent=2, sort_keys=True) if args.json else "Celery queue drained.")
            return 0
        if not args.json:
            print(f"Waiting for Celery drain: {last_depth}")
        time.sleep(args.poll_seconds)

    result = {"drained": False, "depth": last_depth, "timeout_seconds": args.timeout_seconds}
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else f"Celery drain timed out: {last_depth}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
