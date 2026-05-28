import hashlib
import json
import logging
import os
import platform
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from database.database import db
from database.models import SystemConfig

logger = logging.getLogger(__name__)

_INDEX_KEY = "zoh_history"
_JOB_KEY_PREFIX = "zoh:"
_MAX_HISTORY_ENTRIES = 50
STALE_HEARTBEAT_SECONDS = 300


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat()


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _safe_env_value(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if any(marker in lowered for marker in ("password=", "token=", "access_token=", "@")):
        return "[redacted]"
    return text[:500]


def _is_stale(entry: dict[str, Any]) -> bool:
    state = str(entry.get("state") or "").upper()
    if state not in {"PENDING", "PROGRESS"}:
        return False
    heartbeat = _parse_iso(entry.get("heartbeat_at") or entry.get("updated_at"))
    if heartbeat is None:
        return False
    return datetime.utcnow() - heartbeat > timedelta(seconds=STALE_HEARTBEAT_SECONDS)


def _collection_from_entry(entry: dict[str, Any]) -> dict[str, Any]:
    manifest = entry.get("manifest") if isinstance(entry.get("manifest"), dict) else {}
    summary = entry.get("summary") if isinstance(entry.get("summary"), dict) else {}
    options = entry.get("options") if isinstance(entry.get("options"), dict) else {}
    runtime = entry.get("runtime") if isinstance(entry.get("runtime"), dict) else {}
    shards = [item for item in (manifest.get("shards") or []) if isinstance(item, dict)]
    collection = dict(entry.get("collection") or {})
    collection.update(
        {
            "collection_id": collection.get("collection_id") or entry.get("harvest_id"),
            "harvest_id": entry.get("harvest_id"),
            "base_url": options.get("base_url") or collection.get("base_url"),
            "set_spec": options.get("set_spec") or collection.get("set_spec"),
            "metadata_prefix": options.get("metadata_prefix") or collection.get("metadata_prefix"),
            "harvest_mode": options.get("harvest_mode") or collection.get("harvest_mode") or "full",
            "sync_mode": options.get("sync_mode") or collection.get("sync_mode") or "full",
            "parent_harvest_id": options.get("parent_harvest_id") or collection.get("parent_harvest_id"),
            "execution_target": runtime.get("execution_target") or collection.get("execution_target") or "celery_local",
            "record_count": int(summary.get("harvested_records") or collection.get("record_count") or 0),
            "shard_count": len(shards),
            "latest_datestamp": summary.get("latest_datestamp") or collection.get("latest_datestamp"),
            "earliest_datestamp": summary.get("earliest_datestamp") or collection.get("earliest_datestamp"),
            "created_at": entry.get("created_at"),
            "updated_at": entry.get("updated_at"),
            "status": entry.get("status"),
            "state": entry.get("state"),
        }
    )
    return collection


def publicize_harvest_entry(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return entry
    payload = dict(entry)
    checkpoint = payload.get("checkpoint") if isinstance(payload.get("checkpoint"), dict) else None
    if checkpoint is not None:
        public_checkpoint = dict(checkpoint)
        if "seen_keys" in public_checkpoint:
            public_checkpoint["seen_count"] = len(public_checkpoint.get("seen_keys") or [])
            public_checkpoint.pop("seen_keys", None)
        payload["checkpoint"] = public_checkpoint
    payload["collection"] = _collection_from_entry(payload)
    payload["stale"] = _is_stale(payload)
    payload["stale_after_seconds"] = STALE_HEARTBEAT_SECONDS
    return payload


def new_harvest_id() -> str:
    return str(uuid.uuid4())


def _job_storage_key(harvest_id: str) -> str:
    digest = hashlib.sha1(str(harvest_id or "").encode("utf-8")).hexdigest()
    return f"{_JOB_KEY_PREFIX}{digest[:40]}"


def _load_json_config(key: str, default: Any) -> Any:
    entry = db.session.get(SystemConfig, key)
    if entry is None or not entry.value:
        return default
    try:
        return json.loads(entry.value)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON in SystemConfig key %s", key)
        return default


def _save_json_config(key: str, value: Any) -> None:
    entry = db.session.get(SystemConfig, key)
    payload = json.dumps(value, sort_keys=True)
    if entry is None:
        db.session.add(SystemConfig(key=key, value=payload))
    else:
        entry.value = payload


def _update_history_index(harvest_id: str) -> None:
    harvest_id = str(harvest_id or "").strip()
    if not harvest_id:
        return
    index = _load_json_config(_INDEX_KEY, [])
    if not isinstance(index, list):
        index = []
    normalized = [str(item).strip() for item in index if str(item).strip() and str(item).strip() != harvest_id]
    normalized.insert(0, harvest_id)
    stale_ids = normalized[_MAX_HISTORY_ENTRIES:]
    normalized = normalized[:_MAX_HISTORY_ENTRIES]
    _save_json_config(_INDEX_KEY, normalized)
    for stale_id in stale_ids:
        stale_entry = db.session.get(SystemConfig, _job_storage_key(stale_id))
        if stale_entry is not None:
            db.session.delete(stale_entry)


def get_harvest_entry(harvest_id: str) -> dict[str, Any] | None:
    harvest_id = str(harvest_id or "").strip()
    if not harvest_id:
        return None
    payload = _load_json_config(_job_storage_key(harvest_id), None)
    return payload if isinstance(payload, dict) else None


def list_harvest_entries(limit: int = 20, *, user_id: int | None = None) -> list[dict[str, Any]]:
    index = _load_json_config(_INDEX_KEY, [])
    if not isinstance(index, list):
        return []
    entries: list[dict[str, Any]] = []
    for harvest_id in index:
        if len(entries) >= max(1, min(int(limit or 20), _MAX_HISTORY_ENTRIES)):
            break
        entry = get_harvest_entry(str(harvest_id))
        if not isinstance(entry, dict):
            continue
        if user_id is not None and int((entry.get("requested_by") or {}).get("user_id") or 0) != int(user_id):
            continue
        entries.append(entry)
    return entries


def find_latest_successful_harvest(
    *,
    base_url: str,
    set_spec: str,
    metadata_prefix: str,
    user_id: int,
    exclude_harvest_id: str | None = None,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for entry in list_harvest_entries(limit=_MAX_HISTORY_ENTRIES, user_id=user_id):
        if str(entry.get("harvest_id")) == str(exclude_harvest_id or ""):
            continue
        if str(entry.get("state") or "").upper() != "SUCCESS":
            continue
        options = entry.get("options") if isinstance(entry.get("options"), dict) else {}
        if str(options.get("base_url") or "").rstrip("/") != str(base_url or "").rstrip("/"):
            continue
        if str(options.get("set_spec") or "").lower() != str(set_spec or "").lower():
            continue
        if str(options.get("metadata_prefix") or "").lower() != str(metadata_prefix or "").lower():
            continue
        collection = _collection_from_entry(entry)
        latest = collection.get("latest_datestamp")
        if not latest:
            continue
        candidates.append({**entry, "collection": collection})
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: str((item.get("collection") or {}).get("latest_datestamp") or item.get("updated_at") or ""), reverse=True)[0]


def record_harvest_launch(
    *,
    harvest_id: str,
    task_id: str | None,
    requested_by_user_id: int,
    requested_by_email: str | None,
    base_url: str,
    set_spec: str,
    metadata_prefix: str,
    max_records: int | None = None,
    from_datetime: str | None = None,
    until_datetime: str | None = None,
    sync_mode: str = "full",
    parent_harvest_id: str | None = None,
    incremental_since: str | None = None,
    incremental_overlap_hours: int | None = None,
    harvest_mode: str = "full",
    execution_target: str = "celery_local",
    runtime_options: dict[str, Any] | None = None,
    preflight_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = _utc_now_iso()
    runtime_options = dict(runtime_options or {})
    preflight_report = dict(preflight_report or {})
    normalized_sync_mode = "incremental" if str(sync_mode or "").lower() == "incremental" else "full"
    normalized_harvest_mode = str(harvest_mode or normalized_sync_mode or "full").strip().lower()
    if normalized_harvest_mode not in {"full", "historical_backfill", "incremental"}:
        normalized_harvest_mode = "incremental" if normalized_sync_mode == "incremental" else "full"
    entry = {
        "harvest_id": harvest_id,
        "task_id": task_id,
        "requested_by": {
            "user_id": int(requested_by_user_id),
            "email": str(requested_by_email or "") or None,
        },
        "state": "PENDING",
        "status": "Queued Zenodo OAI harvest",
        "control": {
            "pause_requested": False,
            "cancel_requested": False,
        },
        "checkpoint": {},
        "options": {
            "base_url": str(base_url or "").rstrip("/"),
            "set_spec": str(set_spec or "").strip(),
            "metadata_prefix": str(metadata_prefix or "").strip(),
            "max_records": int(max_records) if max_records is not None else None,
            "from_datetime": from_datetime,
            "until_datetime": until_datetime,
            "harvest_mode": normalized_harvest_mode,
            "sync_mode": normalized_sync_mode,
            "parent_harvest_id": parent_harvest_id,
            "incremental_since": incremental_since,
            "incremental_overlap_hours": int(incremental_overlap_hours) if incremental_overlap_hours is not None else None,
            "request_retries": runtime_options.get("request_retries"),
            "request_timeout_seconds": runtime_options.get("request_timeout_seconds"),
        },
        "runtime": {
            "execution_target": execution_target,
            "source_database": _safe_env_value(os.environ.get("DATABASE_URL")),
            "shard_root": runtime_options.get("output_root") or _safe_env_value(os.environ.get("SHARED_SESSION_PATH") or os.environ.get("WEBHDP_SESSIONS_PATH")),
            "script_version": runtime_options.get("script_version")
            or os.environ.get("WEBHDP_GIT_SHA")
            or os.environ.get("GIT_COMMIT")
            or os.environ.get("SOURCE_VERSION")
            or "unknown",
            "python_version": platform.python_version(),
            "hostname": socket.gethostname(),
            "process": {"pid": os.getpid(), "status": "queued"},
            "created_at": now,
        },
        "preflight": preflight_report,
        "progress": {
            "total_records": 0,
            "harvested_records": 0,
            "pages_retrieved": 0,
            "created_shards": 0,
            "duplicate_records_skipped": 0,
            "rate_limited_waits": 0,
            "percent": 0,
            "current_resumption_token": None,
            "max_records": int(max_records) if max_records is not None else None,
            "limit_reached": False,
            "records_per_hour": 0,
            "pages_per_hour": 0,
            "eta_seconds": None,
        },
        "summary": {
            "harvested_records": 0,
            "created_shards": 0,
            "pages_retrieved": 0,
            "failed_pages": 0,
            "duplicate_records_skipped": 0,
            "rate_limited_waits": 0,
            "max_records": int(max_records) if max_records is not None else None,
            "limit_reached": False,
            "latest_datestamp": None,
            "earliest_datestamp": None,
            "wait_seconds": 0,
            "coverage_summary": {},
        },
        "manifest": {
            "harvest_id": harvest_id,
            "shards": [],
            "sync_mode": normalized_sync_mode,
            "parent_harvest_id": parent_harvest_id,
        },
        "collection": {
            "collection_id": harvest_id,
            "harvest_id": harvest_id,
            "sync_mode": normalized_sync_mode,
            "parent_harvest_id": parent_harvest_id,
            "record_count": 0,
            "shard_count": 0,
            "latest_datestamp": None,
            "earliest_datestamp": None,
        },
        "error": None,
        "created_at": now,
        "updated_at": now,
        "heartbeat_at": now,
    }
    _save_json_config(_job_storage_key(harvest_id), entry)
    _update_history_index(harvest_id)
    db.session.commit()
    return entry


def update_harvest_entry(
    harvest_id: str,
    *,
    task_id: str | None = None,
    state: str | None = None,
    status: str | None = None,
    progress: dict[str, Any] | None = None,
    checkpoint: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
    error: str | None = None,
    control: dict[str, Any] | None = None,
    heartbeat: bool = False,
    collection: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
    preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    harvest_id = str(harvest_id or "").strip()
    if not harvest_id:
        raise ValueError("harvest_id is required")
    existing = get_harvest_entry(harvest_id) or {"harvest_id": harvest_id, "created_at": _utc_now_iso()}
    existing["updated_at"] = _utc_now_iso()
    if heartbeat:
        existing["heartbeat_at"] = existing["updated_at"]
    if task_id is not None:
        existing["task_id"] = str(task_id)
    if state is not None:
        existing["state"] = str(state)
    if status is not None:
        existing["status"] = str(status)
    if progress is not None:
        existing["progress"] = dict(progress)
    if checkpoint is not None:
        existing["checkpoint"] = dict(checkpoint)
    if manifest is not None:
        existing["manifest"] = dict(manifest)
    if summary is not None:
        existing["summary"] = dict(summary)
    if error is not None:
        existing["error"] = str(error) if error else None
    if control is not None:
        merged_control = dict(existing.get("control") or {})
        merged_control.update(control)
        existing["control"] = merged_control
    if collection is not None:
        merged_collection = dict(existing.get("collection") or {})
        merged_collection.update(collection)
        existing["collection"] = merged_collection
    if runtime is not None:
        merged_runtime = dict(existing.get("runtime") or {})
        merged_runtime.update(runtime)
        existing["runtime"] = merged_runtime
    if preflight is not None:
        merged_preflight = dict(existing.get("preflight") or {})
        merged_preflight.update(preflight)
        existing["preflight"] = merged_preflight
    existing["collection"] = _collection_from_entry(existing)
    _save_json_config(_job_storage_key(harvest_id), existing)
    _update_history_index(harvest_id)
    db.session.commit()
    return existing


def request_pause(harvest_id: str) -> dict[str, Any]:
    return update_harvest_entry(harvest_id, control={"pause_requested": True})


def clear_pause(harvest_id: str) -> dict[str, Any]:
    return update_harvest_entry(harvest_id, control={"pause_requested": False})


def request_cancel(harvest_id: str) -> dict[str, Any]:
    return update_harvest_entry(harvest_id, control={"cancel_requested": True})


def delete_harvest_entry(harvest_id: str) -> None:
    harvest_id = str(harvest_id or "").strip()
    if not harvest_id:
        return
    entry = db.session.get(SystemConfig, _job_storage_key(harvest_id))
    if entry is not None:
        db.session.delete(entry)
    index = _load_json_config(_INDEX_KEY, [])
    if isinstance(index, list):
        _save_json_config(_INDEX_KEY, [item for item in index if str(item) != harvest_id])
    db.session.commit()
