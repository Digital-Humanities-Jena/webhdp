import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, List

from database.database import db
from database.models import SystemConfig
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


logger = logging.getLogger(__name__)

_TASK_KEY_PREFIX = "session_batch_task:"
_SESSION_INDEX_PREFIX = "session_batch_history:"
_GLOBAL_INDEX_KEY = "session_batch_history_global"
_MAX_HISTORY_ENTRIES = 100


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat()


def _task_storage_key(task_id: str) -> str:
    digest = hashlib.sha1(str(task_id or "").encode("utf-8")).hexdigest()
    return f"{_TASK_KEY_PREFIX}{digest[:40]}"


def _session_index_key(session_id: int) -> str:
    return f"{_SESSION_INDEX_PREFIX}{int(session_id)}"


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
    payload = json.dumps(value)
    bind = db.session.get_bind()
    if bind is not None and bind.dialect.name == "sqlite":
        statement = sqlite_insert(SystemConfig).values(key=key, value=payload)
        db.session.execute(
            statement.on_conflict_do_update(
                index_elements=[SystemConfig.key],
                set_={"value": payload},
            )
        )
        return

    entry = db.session.get(SystemConfig, key)
    if entry is None:
        db.session.merge(SystemConfig(key=key, value=payload))
        return
    entry.value = payload


def _update_index(key: str, task_id: str) -> None:
    task_id = str(task_id or "").strip()
    if not task_id:
        return
    index = _load_json_config(key, [])
    if not isinstance(index, list):
        index = []
    normalized = [str(item).strip() for item in index if str(item).strip() and str(item).strip() != task_id]
    normalized.insert(0, task_id)
    normalized = normalized[:_MAX_HISTORY_ENTRIES]
    _save_json_config(key, normalized)


def get_task_entry(task_id: str) -> Dict[str, Any] | None:
    payload = _load_json_config(_task_storage_key(str(task_id or "").strip()), None)
    return payload if isinstance(payload, dict) else None


def list_task_entries(*, session_id: int | None = None, limit: int = 20) -> List[Dict[str, Any]]:
    key = _session_index_key(session_id) if session_id is not None else _GLOBAL_INDEX_KEY
    index = _load_json_config(key, [])
    if not isinstance(index, list):
        return []
    items: List[Dict[str, Any]] = []
    for task_id in index[: max(1, min(int(limit or 20), _MAX_HISTORY_ENTRIES))]:
        entry = get_task_entry(task_id)
        if isinstance(entry, dict):
            items.append(entry)
    return items


def record_task_launch(
    *,
    task_id: str,
    session_id: int,
    operation_type: str,
    target_ids: List[int],
    options: Dict[str, Any] | None,
    requested_by_user_id: int | None,
    requested_by_email: str | None,
) -> Dict[str, Any]:
    now = _utc_now_iso()
    entry = {
        "task_id": str(task_id),
        "session_id": int(session_id),
        "operation_type": str(operation_type),
        "target_ids": [int(item) for item in target_ids if str(item).isdigit()],
        "options": dict(options or {}),
        "requested_by": {
            "user_id": int(requested_by_user_id) if requested_by_user_id is not None else None,
            "email": str(requested_by_email) if requested_by_email else None,
        },
        "state": "PENDING",
        "status": "Queued session batch operation",
        "progress": {
            "total_items": len(target_ids or []),
            "processed": 0,
            "completed": 0,
            "skipped": 0,
            "failed": 0,
            "percent": 0,
            "current_target_id": None,
        },
        "summary": {
            "total_items": len(target_ids or []),
            "completed": 0,
            "skipped": 0,
            "failed": 0,
        },
        "result": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
    }
    _save_json_config(_task_storage_key(task_id), entry)
    _update_index(_GLOBAL_INDEX_KEY, task_id)
    _update_index(_session_index_key(session_id), task_id)
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

    existing = get_task_entry(task_id) or {"task_id": task_id, "created_at": _utc_now_iso()}
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
    session_id = existing.get("session_id")
    if str(session_id or "").isdigit():
        _update_index(_session_index_key(int(session_id)), task_id)
    _update_index(_GLOBAL_INDEX_KEY, task_id)
    db.session.commit()
    return existing
