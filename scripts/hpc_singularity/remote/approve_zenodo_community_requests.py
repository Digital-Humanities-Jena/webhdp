#!/usr/bin/env python3
"""Approve submitted Zenodo community requests with durable progress logging.

This operator script is intentionally standalone so it can run inside tmux on
the HPC login node using the WebHDP production environment file. It does not
print tokens or write secrets to logs.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


ZENODO_BASE_URL = "https://zenodo.org"


class SafetyStop(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_env_file(path: Path) -> None:
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")


def write_state(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def request_with_retries(
    session: requests.Session,
    method: str,
    url: str,
    *,
    audit_path: Path,
    max_retries: int,
    **kwargs: Any,
) -> requests.Response:
    retry = 0
    while True:
        try:
            response = session.request(method, url, timeout=kwargs.pop("timeout", 60), **kwargs)
        except requests.RequestException as exc:
            if retry >= max_retries:
                raise
            wait_seconds = min(300, 2**retry)
            append_jsonl(
                audit_path,
                {
                    "event": "network_retry",
                    "time": utc_now(),
                    "method": method,
                    "url": url,
                    "retry": retry + 1,
                    "wait_seconds": wait_seconds,
                    "error": str(exc),
                },
            )
            time.sleep(wait_seconds)
            retry += 1
            continue

        remaining = int(response.headers.get("X-RateLimit-Remaining", "-1"))
        reset = int(response.headers.get("X-RateLimit-Reset", "0") or 0)
        if remaining > -1 and remaining < 3:
            wait_seconds = max(1, reset - int(time.time()) + 1)
            append_jsonl(
                audit_path,
                {
                    "event": "rate_limit_low_remaining",
                    "time": utc_now(),
                    "method": method,
                    "url": url,
                    "remaining": remaining,
                    "wait_seconds": wait_seconds,
                },
            )
            time.sleep(wait_seconds)

        if response.status_code == 429:
            if retry >= max_retries:
                response.raise_for_status()
            wait_seconds = int(response.headers.get("Retry-After", "60") or 60)
            append_jsonl(
                audit_path,
                {
                    "event": "rate_limit_retry",
                    "time": utc_now(),
                    "method": method,
                    "url": url,
                    "retry": retry + 1,
                    "wait_seconds": wait_seconds,
                },
            )
            time.sleep(wait_seconds)
            retry += 1
            continue

        if 500 <= response.status_code < 600:
            if retry >= max_retries:
                response.raise_for_status()
            wait_seconds = min(300, 2**retry)
            append_jsonl(
                audit_path,
                {
                    "event": "server_retry",
                    "time": utc_now(),
                    "method": method,
                    "url": url,
                    "status_code": response.status_code,
                    "retry": retry + 1,
                    "wait_seconds": wait_seconds,
                },
            )
            time.sleep(wait_seconds)
            retry += 1
            continue

        response.raise_for_status()
        return response


def normalize_request(item: dict[str, Any]) -> dict[str, Any]:
    links = item.get("links") if isinstance(item.get("links"), dict) else {}
    actions = links.get("actions") if isinstance(links.get("actions"), dict) else {}
    topic = item.get("topic") if isinstance(item.get("topic"), dict) else {}
    record = topic.get("record")
    return {
        "request_id": str(item.get("id") or "").strip(),
        "number": item.get("number"),
        "title": item.get("title"),
        "type": item.get("type"),
        "status": item.get("status"),
        "is_open": bool(item.get("is_open")),
        "record": record.get("id") if isinstance(record, dict) else record,
        "accept_url": actions.get("accept"),
    }


def fetch_submitted_page(
    session: requests.Session,
    requests_url: str,
    *,
    token: str,
    page_size: int,
    audit_path: Path,
    max_retries: int,
) -> tuple[int, list[dict[str, Any]]]:
    response = request_with_retries(
        session,
        "GET",
        requests_url,
        audit_path=audit_path,
        max_retries=max_retries,
        params={
            "access_token": token,
            "status": "submitted",
            "page": 1,
            "size": page_size,
        },
    )
    payload = response.json()
    hits = payload.get("hits", {}) if isinstance(payload, dict) else {}
    return int(hits.get("total") or 0), [item for item in (hits.get("hits") or []) if isinstance(item, dict)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--community", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-retries", type=int, default=8)
    parser.add_argument("--max-consecutive-failures", type=int, default=25)
    parser.add_argument("--sleep-between-actions", type=float, default=0.0)
    args = parser.parse_args()

    args.work_dir.mkdir(parents=True, exist_ok=True)
    audit_path = args.work_dir / f"{args.community}_approval_audit.jsonl"
    state_path = args.work_dir / f"{args.community}_approval_state.json"
    lock_path = args.work_dir / f"{args.community}_approval.lock"

    load_env_file(args.env_file)
    token = str(os.environ.get("ZENODO_API_KEY") or "").strip()
    if not token:
        raise SafetyStop("ZENODO_API_KEY is missing from the WebHDP production environment")

    lock_handle = lock_path.open("w", encoding="utf-8")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise SafetyStop(f"another approval process is already holding {lock_path}") from exc

    stop_requested = {"value": False}

    def _handle_signal(signum: int, _frame: Any) -> None:
        stop_requested["value"] = True
        append_jsonl(audit_path, {"event": "signal_received", "time": utc_now(), "signal": signum})

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    session = requests.Session()
    started_at = utc_now()
    state: dict[str, Any] = {
        "community": args.community,
        "started_at": started_at,
        "updated_at": started_at,
        "status": "starting",
        "submitted_remaining": None,
        "accepted": 0,
        "failed": 0,
        "skipped": 0,
        "batches": 0,
        "last_error": None,
    }
    append_jsonl(audit_path, {"event": "run_started", "time": started_at, "community": args.community})
    write_state(state_path, state)

    community_response = request_with_retries(
        session,
        "GET",
        f"{ZENODO_BASE_URL}/api/communities/{args.community}",
        audit_path=audit_path,
        max_retries=args.max_retries,
        params={"access_token": token},
    )
    community_payload = community_response.json()
    requests_url = str((community_payload.get("links") or {}).get("requests") or "").strip()
    if not requests_url:
        raise SafetyStop("Zenodo community does not expose a requests endpoint")

    consecutive_failures = 0
    while not stop_requested["value"]:
        submitted_total, page_items = fetch_submitted_page(
            session,
            requests_url,
            token=token,
            page_size=args.page_size,
            audit_path=audit_path,
            max_retries=args.max_retries,
        )
        state.update(
            {
                "status": "running" if submitted_total else "completed",
                "updated_at": utc_now(),
                "submitted_remaining": submitted_total,
            }
        )
        write_state(state_path, state)

        print(
            f"{utc_now()} submitted_remaining={submitted_total} "
            f"accepted={state['accepted']} failed={state['failed']} skipped={state['skipped']}",
            flush=True,
        )

        if submitted_total == 0:
            break
        if not page_items:
            raise SafetyStop(f"submitted_total={submitted_total}, but Zenodo returned an empty page")

        actionable = [normalize_request(item) for item in page_items]
        actionable = [
            item
            for item in actionable
            if item["request_id"] and item["status"] == "submitted" and item["is_open"] and item["accept_url"]
        ]
        if not actionable:
            raise SafetyStop("submitted page contains no actionable accept requests; stopping to avoid a spin loop")

        state["batches"] += 1
        for item in actionable:
            if stop_requested["value"]:
                break
            result = {
                "event": "accept_attempt",
                "time": utc_now(),
                "community": args.community,
                **{key: item.get(key) for key in ("request_id", "number", "title", "type", "record")},
            }
            try:
                response = request_with_retries(
                    session,
                    "POST",
                    f"{ZENODO_BASE_URL}/api/requests/{item['request_id']}/actions/accept",
                    audit_path=audit_path,
                    max_retries=args.max_retries,
                    params={"access_token": token},
                )
                updated = normalize_request(response.json())
                result.update(
                    {
                        "event": "accepted",
                        "accepted_status": updated.get("status"),
                        "accepted_is_open": updated.get("is_open"),
                    }
                )
                state["accepted"] += 1
                consecutive_failures = 0
            except Exception as exc:
                state["failed"] += 1
                consecutive_failures += 1
                result.update({"event": "accept_failed", "error": str(exc)})
                state["last_error"] = str(exc)
                if consecutive_failures >= args.max_consecutive_failures:
                    append_jsonl(audit_path, result)
                    raise SafetyStop(f"{consecutive_failures} consecutive accept failures")
            append_jsonl(audit_path, result)
            state["updated_at"] = utc_now()
            write_state(state_path, state)
            if args.sleep_between_actions > 0:
                time.sleep(args.sleep_between_actions)

    if stop_requested["value"]:
        state["status"] = "stopped"
    else:
        state["status"] = "completed"
    state["updated_at"] = utc_now()
    write_state(state_path, state)
    append_jsonl(audit_path, {"event": "run_finished", "time": state["updated_at"], **state})
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SafetyStop as exc:
        print(f"SAFETY_STOP: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(2)
