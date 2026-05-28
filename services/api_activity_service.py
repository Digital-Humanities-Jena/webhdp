import json
import logging
import os
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List


logger = logging.getLogger(__name__)

_DEFAULT_LOG_DIR = "logs"
_ACTIVITY_FILENAME = "api_activity.jsonl"
_MAX_ENTRIES = 2000


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _activity_log_path() -> str:
    log_dir = os.path.abspath(os.path.join(os.getcwd(), _DEFAULT_LOG_DIR))
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, _ACTIVITY_FILENAME)


def _normalize_path(path: str | None) -> str:
    text = str(path or "").strip()
    return text if text.startswith("/api/") else ""


def _classify_route_family(path: str) -> str:
    normalized = _normalize_path(path)
    if not normalized:
        return "other"
    parts = [part for part in normalized.split("/") if part]
    if len(parts) < 3:
        return "other"
    if parts[0] != "api":
        return "other"
    if parts[2].isdigit():
        return "sessions"
    return parts[2]


def _classify_service(path: str) -> str:
    normalized = _normalize_path(path)
    if "/community-moderation" in normalized or "/zenodo" in normalized:
        return "zenodo"
    if "/admin/cloud/" in normalized:
        return "cloud_storage"
    if "/pipelines" in normalized or "/playground" in normalized:
        return "pipeline"
    if "/setup/" in normalized or "/hpc-diagnostics" in normalized:
        return "system"
    return "webhdp"


def _status_class(status_code: int | None) -> str:
    code = int(status_code or 0)
    if 200 <= code < 300:
        return "success"
    if 300 <= code < 400:
        return "redirect"
    if 400 <= code < 500:
        return "client_error"
    if code >= 500:
        return "server_error"
    return "unknown"


def _parse_iso(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _within_time_window(timestamp: str | None, *, hours: int | None = None) -> bool:
    if hours is None:
        return True
    dt = _parse_iso(timestamp)
    if dt is None:
        return False
    now = datetime.now(timezone.utc)
    return dt >= now - timedelta(hours=max(1, int(hours)))


def record_api_activity(entry: Dict[str, Any]) -> None:
    path = _normalize_path(entry.get("path"))
    if not path:
        return

    payload = {
        "timestamp": str(entry.get("timestamp") or _utc_now_iso()),
        "method": str(entry.get("method") or "GET").upper(),
        "path": path,
        "route_family": str(entry.get("route_family") or _classify_route_family(path)),
        "service": str(entry.get("service") or _classify_service(path)),
        "status_code": int(entry.get("status_code") or 0),
        "status_class": str(entry.get("status_class") or _status_class(entry.get("status_code"))),
        "duration_ms": int(entry.get("duration_ms") or 0),
        "user_id": int(entry.get("user_id")) if str(entry.get("user_id") or "").isdigit() else None,
        "request_id": str(entry.get("request_id") or "").strip() or None,
    }

    target_path = _activity_log_path()
    fd, tmp_path = tempfile.mkstemp(prefix="api-activity-", suffix=".jsonl", dir=os.path.dirname(target_path))
    os.close(fd)

    kept_lines: List[str] = []
    try:
        if os.path.exists(target_path):
            with open(target_path, "r", encoding="utf-8") as handle:
                kept_lines = handle.readlines()[-(_MAX_ENTRIES - 1):]

        with open(tmp_path, "w", encoding="utf-8") as handle:
            handle.writelines(kept_lines)
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
        os.replace(tmp_path, target_path)
    except Exception:
        logger.warning("Failed to record API activity entry", exc_info=True)
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def list_api_activity(
    *,
    limit: int = 50,
    route_family: str | None = None,
    service: str | None = None,
    status_class: str | None = None,
    hours: int | None = None,
) -> List[Dict[str, Any]]:
    target_path = _activity_log_path()
    if not os.path.exists(target_path):
        return []

    normalized_route_family = str(route_family or "").strip().lower() or None
    normalized_service = str(service or "").strip().lower() or None
    normalized_status_class = str(status_class or "").strip().lower() or None
    safe_limit = max(1, min(int(limit or 50), _MAX_ENTRIES))

    items: List[Dict[str, Any]] = []
    with open(target_path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if normalized_route_family and str(payload.get("route_family") or "").lower() != normalized_route_family:
                continue
            if normalized_service and str(payload.get("service") or "").lower() != normalized_service:
                continue
            if normalized_status_class and str(payload.get("status_class") or "").lower() != normalized_status_class:
                continue
            if not _within_time_window(payload.get("timestamp"), hours=hours):
                continue
            items.append(payload)

    items.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    return items[:safe_limit]


def summarize_api_activity(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    route_counts = Counter(str(item.get("route_family") or "other") for item in entries)
    service_counts = Counter(str(item.get("service") or "webhdp") for item in entries)
    status_counts = Counter(str(item.get("status_class") or "unknown") for item in entries)

    durations = [int(item.get("duration_ms") or 0) for item in entries if int(item.get("duration_ms") or 0) >= 0]
    avg_duration = round(sum(durations) / len(durations), 1) if durations else 0.0

    return {
        "total_entries": len(entries),
        "average_duration_ms": avg_duration,
        "route_families": dict(route_counts),
        "services": dict(service_counts),
        "status_classes": dict(status_counts),
    }
