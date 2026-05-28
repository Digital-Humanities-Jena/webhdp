import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, List

from database.database import db
from database.models import SystemConfig

logger = logging.getLogger(__name__)

_INDEX_KEY = "zbt_history"
_TASK_KEY_PREFIX = "zbt:"
_MAX_HISTORY_ENTRIES = 50


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat()


def _task_storage_key(task_id: str) -> str:
    digest = hashlib.sha1(str(task_id or "").encode("utf-8")).hexdigest()
    return f"{_TASK_KEY_PREFIX}{digest[:40]}"


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
    payload = json.dumps(value)
    if entry is None:
        entry = SystemConfig(key=key, value=payload)
        db.session.add(entry)
    else:
        entry.value = payload


def _update_history_index(task_id: str) -> None:
    task_id = str(task_id or "").strip()
    if not task_id:
        return

    index = _load_json_config(_INDEX_KEY, [])
    if not isinstance(index, list):
        index = []

    normalized = [str(item).strip() for item in index if str(item).strip() and str(item).strip() != task_id]
    normalized.insert(0, task_id)
    stale_ids = normalized[_MAX_HISTORY_ENTRIES:]
    normalized = normalized[:_MAX_HISTORY_ENTRIES]

    _save_json_config(_INDEX_KEY, normalized)
    for stale_id in stale_ids:
        stale_entry = db.session.get(SystemConfig, _task_storage_key(stale_id))
        if stale_entry is not None:
            db.session.delete(stale_entry)


def get_task_entry(task_id: str) -> Dict[str, Any] | None:
    task_id = str(task_id or "").strip()
    if not task_id:
        return None

    payload = _load_json_config(_task_storage_key(task_id), None)
    return payload if isinstance(payload, dict) else None


def list_task_entries(limit: int = 20) -> List[Dict[str, Any]]:
    index = _load_json_config(_INDEX_KEY, [])
    if not isinstance(index, list):
        return []

    entries: List[Dict[str, Any]] = []
    for task_id in index[: max(1, min(int(limit or 20), _MAX_HISTORY_ENTRIES))]:
        entry = get_task_entry(str(task_id))
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def record_task_launch(
    *,
    task_id: str,
    operation: str,
    remove_mode: str | None,
    community_identifier: str | None,
    selected_count: int,
    eligible_count: int,
    ineligible_count: int,
    requested_by_user_id: int | None,
    requested_by_email: str | None,
) -> Dict[str, Any]:
    now = _utc_now_iso()
    entry = {
        "task_id": str(task_id),
        "operation": str(operation),
        "remove_mode": str(remove_mode) if remove_mode else None,
        "community_identifier": str(community_identifier) if community_identifier else None,
        "selected_count": int(selected_count or 0),
        "eligible_count": int(eligible_count or 0),
        "ineligible_count": int(ineligible_count or 0),
        "requested_by": {
            "user_id": int(requested_by_user_id) if requested_by_user_id is not None else None,
            "email": str(requested_by_email) if requested_by_email else None,
        },
        "state": "PENDING",
        "status": "Queued Zenodo community operation",
        "progress": {
            "total_records": int(selected_count or 0),
            "processed": 0,
            "succeeded": 0,
            "unchanged": 0,
            "ineligible": 0,
            "failed": 0,
            "rate_limited_waits": 0,
            "percent": 0,
            "current_record": None,
        },
        "summary": {
            "total_records": int(selected_count or 0),
            "processed": 0,
            "succeeded": 0,
            "unchanged": 0,
            "ineligible": 0,
            "failed": 0,
            "rate_limited_waits": 0,
        },
        "result": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
    }

    _save_json_config(_task_storage_key(task_id), entry)
    _update_history_index(task_id)
    db.session.commit()
    return entry


def update_task_entry(
    task_id: str,
    *,
    state: str | None = None,
    status: str | None = None,
    progress: Dict[str, Any] | None = None,
    result: Dict[str, Any] | None = None,
    error: str | None = None,
) -> Dict[str, Any]:
    task_id = str(task_id or "").strip()
    if not task_id:
        raise ValueError("task_id is required")

    existing = get_task_entry(task_id) or {
        "task_id": task_id,
        "created_at": _utc_now_iso(),
    }
    existing["updated_at"] = _utc_now_iso()

    if state is not None:
        existing["state"] = str(state)
    if status is not None:
        existing["status"] = str(status)
    if progress is not None:
        existing["progress"] = dict(progress)
    if result is not None:
        existing["result"] = dict(result)
        summary = result.get("summary") if isinstance(result, dict) else None
        progress_from_result = result.get("progress") if isinstance(result, dict) else None
        if isinstance(summary, dict):
            existing["summary"] = dict(summary)
        if isinstance(progress_from_result, dict):
            existing["progress"] = dict(progress_from_result)
        if status is None and isinstance(result, dict) and result.get("status") is not None:
            existing["status"] = str(result.get("status"))
    if error is not None:
        existing["error"] = str(error)

    _save_json_config(_task_storage_key(task_id), existing)
    _update_history_index(task_id)
    db.session.commit()
    return existing
