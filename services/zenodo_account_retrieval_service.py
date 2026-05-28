from __future__ import annotations

import json
import logging
import os
import re
import time
import hashlib
import csv
import io
import shutil
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from flask import current_app

from database.database import db
from database.models import Session as DBSession, User, ZenodoCredential
from services.hdpc_schema_service import connect_hdpc, ensure_hdpc_schema
from services.notification_service import notify_user
from services.zenodo_account_retrieval_history_service import get_retrieval_entry, update_retrieval_entry

logger = logging.getLogger(__name__)

RETRIEVAL_RECORD_ORIGIN = "zenodo_retrieval"
RETRIEVAL_SESSION_ORIGIN = "zenodo_deep_retrieval"
DEFAULT_SHARD_RECORD_LIMIT = 5000
DEFAULT_PAGE_SIZE = 100
PRECHECK_PAGE = 100
MAX_RECORDS_CEILING = 1_000_000
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_REQUEST_RETRIES = 2
DEFAULT_INITIAL_WINDOW_DAYS = 31
MODEL_FILE_EXTENSIONS = {
    ".3ds",
    ".blend",
    ".dae",
    ".fbx",
    ".glb",
    ".gltf",
    ".obj",
    ".ply",
    ".stl",
    ".usd",
    ".usda",
    ".usdc",
    ".usdz",
    ".wrl",
    ".x3d",
}
DETECTOR_PRESETS = {
    "objaverse": {
        "id": "objaverse",
        "label": "Objaverse in description",
        "description": "Finds local shard records whose metadata mentions Objaverse.",
    },
    "3d_model_files": {
        "id": "3d_model_files",
        "label": "3D model files",
        "description": "Finds local shard records with common 3D model file extensions.",
    },
    "missing_target_community": {
        "id": "missing_target_community",
        "label": "Missing target community",
        "description": "Finds records not already assigned to the requested target community.",
    },
    "community_migration_candidates": {
        "id": "community_migration_candidates",
        "label": "Community migration candidates",
        "description": "Finds Objaverse or 3D model records missing the requested target community.",
    },
}
ZENODO_API_BASES = {
    "production": "https://zenodo.org/api",
    "sandbox": "https://sandbox.zenodo.org/api",
}


class ZenodoAccountRetrievalPaused(Exception):
    pass


class ZenodoAccountRetrievalCancelled(Exception):
    pass


class ZenodoRetrievalWindowTooDense(Exception):
    pass


class _SyntheticZenodoResponse:
    def __init__(self, *, status_code: int, text: str):
        self.status_code = status_code
        self.text = text
        self.headers: dict[str, str] = {}

    def json(self):
        return {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Zenodo request failed: {self.text}", response=self)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _parse_dt(value: Any, fallback: datetime | None = None) -> datetime:
    text = str(value or "").strip()
    if not text:
        return fallback or datetime(1970, 1, 1, tzinfo=timezone.utc)
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(f"{text[:10]}T00:00:00+00:00")
        except ValueError:
            return fallback or datetime(1970, 1, 1, tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _max_iso(left: Any, right: Any) -> str | None:
    left_dt = _parse_dt(left, None) if left else None
    right_dt = _parse_dt(right, None) if right else None
    if left_dt and right_dt:
        return _format_query_dt(max(left_dt, right_dt))
    if right_dt:
        return _format_query_dt(right_dt)
    if left_dt:
        return _format_query_dt(left_dt)
    return None


def _min_iso(left: Any, right: Any) -> str | None:
    left_dt = _parse_dt(left, None) if left else None
    right_dt = _parse_dt(right, None) if right else None
    if left_dt and right_dt:
        return _format_query_dt(min(left_dt, right_dt))
    if right_dt:
        return _format_query_dt(right_dt)
    if left_dt:
        return _format_query_dt(left_dt)
    return None


def _format_query_dt(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sanitize_url(value: str) -> str:
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if not parts.scheme or not parts.netloc:
        return value
    filtered = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True) if key.lower() != "access_token"]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(filtered, doseq=True), parts.fragment))


def sanitize_for_storage(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in {"access_token", "token"}:
                continue
            result[str(key)] = sanitize_for_storage(item)
        return result
    if isinstance(value, list):
        return [sanitize_for_storage(item) for item in value]
    if isinstance(value, str):
        return _sanitize_url(value)
    return value


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _extract_deposition_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("id") or payload.get("record_id") or payload.get("recid")
    return str(value).strip() if str(value or "").strip() else None


def _extract_record_status(deposition: dict[str, Any], requested_status: str) -> str:
    state = str(deposition.get("state") or deposition.get("submitted") or "").strip().lower()
    if requested_status == "draft":
        return "draft"
    if state in {"inprogress", "unsubmitted"}:
        return "draft"
    return "published"


def _extract_title(deposition: dict[str, Any]) -> str:
    metadata = deposition.get("metadata") if isinstance(deposition.get("metadata"), dict) else {}
    return _safe_text(metadata.get("title") or deposition.get("title"), "Untitled Zenodo record")


def _extract_doi(deposition: dict[str, Any]) -> str | None:
    metadata = deposition.get("metadata") if isinstance(deposition.get("metadata"), dict) else {}
    for key in ("doi", "prereserve_doi"):
        value = metadata.get(key)
        if isinstance(value, dict):
            value = value.get("doi")
        if str(value or "").strip():
            return str(value).strip()
    if str(deposition.get("doi") or "").strip():
        return str(deposition.get("doi")).strip()
    return None


def _extract_concept_doi(deposition: dict[str, Any]) -> str | None:
    metadata = deposition.get("metadata") if isinstance(deposition.get("metadata"), dict) else {}
    value = deposition.get("conceptdoi") or metadata.get("conceptdoi")
    return str(value).strip() if str(value or "").strip() else None


def _extract_deposition_owner_id(deposition: dict[str, Any]) -> str | None:
    owner = deposition.get("owner")
    if isinstance(owner, dict):
        for key in ("id", "user", "user_id"):
            if str(owner.get(key) or "").strip():
                return str(owner.get(key)).strip()
    for key in ("owner", "owner_id"):
        if str(deposition.get(key) or "").strip():
            return str(deposition.get(key)).strip()
    return None


def _links(deposition: dict[str, Any]) -> dict[str, Any]:
    return deposition.get("links") if isinstance(deposition.get("links"), dict) else {}


def _has_edit_rights(deposition: dict[str, Any], status: str) -> bool:
    links = _links(deposition)
    if status == "draft":
        return bool(links.get("self") or links.get("latest_draft"))
    return bool(links.get("edit"))


def _has_version_rights(deposition: dict[str, Any]) -> bool:
    links = _links(deposition)
    return bool(links.get("newversion") or links.get("latest_draft"))


def _file_name(file_obj: dict[str, Any], fallback_index: int) -> str:
    for key in ("filename", "key", "name"):
        if str(file_obj.get(key) or "").strip():
            return os.path.basename(str(file_obj.get(key)).strip()) or f"zenodo_file_{fallback_index}"
    return f"zenodo_file_{fallback_index}"


class RateLimitedZenodoClient:
    def __init__(
        self,
        *,
        token: str,
        environment: str,
        http: Any = requests,
        sleep_func: Any = time.sleep,
        min_interval_seconds: float = 2.05,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        request_retries: int = DEFAULT_REQUEST_RETRIES,
    ):
        self.token = token
        self.environment = "production" if environment == "production" else "sandbox"
        self.base_url = ZENODO_API_BASES[self.environment]
        self.http = http
        self.sleep_func = sleep_func
        self.min_interval_seconds = float(min_interval_seconds)
        self.request_timeout_seconds = max(1.0, float(request_timeout_seconds or DEFAULT_REQUEST_TIMEOUT_SECONDS))
        self.request_retries = max(0, int(request_retries or 0))
        self._last_request_at = 0.0
        self.rate_limited_waits = 0
        self.wait_seconds = 0.0

    def _wait(self, seconds: float) -> None:
        seconds = max(float(seconds or 0), 0)
        if seconds <= 0:
            return
        self.rate_limited_waits += 1
        self.wait_seconds += seconds
        self.sleep_func(seconds)

    def get_depositions(self, *, status: str, page: int, size: int, query: str | None = None):
        elapsed = time.monotonic() - self._last_request_at
        if self.min_interval_seconds > 0 and self._last_request_at and elapsed < self.min_interval_seconds:
            self._wait(self.min_interval_seconds - elapsed)
        params = {
            "status": status,
            "page": int(page),
            "size": int(size),
            "all_versions": "1",
            "sort": "mostrecent",
        }
        if query:
            params["q"] = query
        last_error = ""
        for attempt in range(self.request_retries + 1):
            try:
                response = self.http.get(
                    f"{self.base_url}/deposit/depositions",
                    headers={"Authorization": f"Bearer {self.token}"},
                    params=params,
                    timeout=self.request_timeout_seconds,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                self._last_request_at = time.monotonic()
                last_error = str(exc)
                if attempt < self.request_retries:
                    self._wait(min(10, 1 + attempt * 2))
                    continue
                return _SyntheticZenodoResponse(status_code=504, text=last_error or "Zenodo request timed out")

            self._last_request_at = time.monotonic()
            remaining = _to_int(response.headers.get("X-RateLimit-Remaining"), -1)
            reset = _to_int(response.headers.get("X-RateLimit-Reset"), 0)
            if response.status_code == 429:
                self._wait(_to_int(response.headers.get("Retry-After"), 60))
                continue
            if response.status_code >= 500 and attempt < self.request_retries:
                self._wait(min(10, 1 + attempt * 2))
                continue
            if remaining > -1 and remaining < 3 and reset:
                self._wait(max(reset - time.time(), 1))
            return response
        return _SyntheticZenodoResponse(status_code=504, text=last_error or "Zenodo request failed after retries")


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_max_records(value: Any) -> int | None:
    if value in (None, ""):
        return None
    normalized = int(value)
    if normalized < 1:
        raise ValueError("max_records must be at least 1")
    if normalized > MAX_RECORDS_CEILING:
        raise ValueError(f"max_records must be {MAX_RECORDS_CEILING} or lower")
    return normalized


def normalize_retrieval_datetime(value: Any, *, is_end: bool = False) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        suffix = "T23:59:59Z" if is_end else "T00:00:00Z"
        text = f"{text}{suffix}"
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("date window values must be ISO dates or datetimes")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return _format_query_dt(parsed)


def _window_query(window: dict[str, Any]) -> str:
    start = _format_query_dt(_parse_dt(window.get("start")))
    end = _format_query_dt(_parse_dt(window.get("end")))
    parts = [f"created:[{start} TO {end}]"]
    record_id = window.get("id") if isinstance(window.get("id"), dict) else None
    if record_id:
        parts.append(f"id:[{int(record_id.get('from', 0))} TO {int(record_id.get('to', 0))}]")
    else:
        recid = window.get("recid") if isinstance(window.get("recid"), dict) else None
        if recid:
            parts.append(f"recid:[{int(recid.get('from', 0))} TO {int(recid.get('to', 0))}]")
    return " AND ".join(parts)


def _window_without_cursor(window: dict[str, Any]) -> dict[str, Any]:
    result = dict(window)
    result.pop("next_page", None)
    result.pop("page", None)
    return result


def _window_page(window: dict[str, Any]) -> int:
    return max(1, _to_int(window.get("next_page") or window.get("page"), 1))


def _seed_windows(statuses: list[str], start: str, end: str, *, newest_first: bool = True, max_days: int = DEFAULT_INITIAL_WINDOW_DAYS) -> list[dict[str, Any]]:
    start_dt = _parse_dt(start)
    end_dt = _parse_dt(end)
    if start_dt > end_dt:
        raise ValueError("start_datetime must be before end_datetime")
    windows: list[dict[str, Any]] = []
    max_delta = timedelta(days=max(1, int(max_days or DEFAULT_INITIAL_WINDOW_DAYS)))
    for status in statuses:
        slices: list[dict[str, Any]] = []
        cursor = start_dt
        while cursor <= end_dt:
            slice_end = min(cursor + max_delta - timedelta(seconds=1), end_dt)
            slices.append({"status": status, "start": _format_query_dt(cursor), "end": _format_query_dt(slice_end), "next_page": 1})
            cursor = slice_end + timedelta(seconds=1)
        if newest_first:
            slices.reverse()
        windows.extend(slices)
    return windows


def _record_seen_key(deposition: dict[str, Any], status: str) -> str:
    deposition_id = _extract_deposition_id(deposition)
    if deposition_id:
        return f"{status}:{deposition_id}"
    fallback = {
        "status": status,
        "doi": _extract_doi(deposition),
        "concept": deposition.get("conceptrecid"),
        "created": deposition.get("created"),
        "modified": deposition.get("modified") or deposition.get("updated"),
        "title": _extract_title(deposition),
    }
    digest = hashlib.sha1(json.dumps(fallback, sort_keys=True).encode("utf-8")).hexdigest()
    return f"{status}:fallback:{digest}"


def _update_summary_temporal_bounds(summary: dict[str, Any], records: list[dict[str, Any]]) -> None:
    for deposition in records:
        created = deposition.get("created")
        modified = deposition.get("modified") or deposition.get("updated") or created
        summary["latest_created"] = _max_iso(summary.get("latest_created"), created)
        summary["latest_modified"] = _max_iso(summary.get("latest_modified"), modified)
        summary["earliest_created"] = _min_iso(summary.get("earliest_created"), created)


def _coverage_summary_from_entry_parts(summary: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    shards = [item for item in (manifest.get("shards") or []) if isinstance(item, dict)]
    compacted = [item for item in (manifest.get("compacted_shards") or []) if isinstance(item, dict)]
    return {
        "earliest_created": summary.get("earliest_created"),
        "latest_created": summary.get("latest_created"),
        "latest_modified": summary.get("latest_modified"),
        "record_count": int(summary.get("retrieved_records") or 0),
        "published_records": int(summary.get("published_records") or 0),
        "draft_records": int(summary.get("draft_records") or 0),
        "shard_count": len(shards),
        "compacted_shard_count": len(compacted),
        "duplicate_records_skipped": int(summary.get("duplicate_records_skipped") or 0),
        "split_windows": int(summary.get("split_windows") or 0),
        "rate_limited_waits": int(summary.get("rate_limited_waits") or 0),
    }


def _process_alive(pid: Any) -> bool | None:
    try:
        normalized = int(pid)
    except (TypeError, ValueError):
        return None
    if normalized <= 0:
        return None
    try:
        os.kill(normalized, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None


def _sanitize_log_line(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)(access_token|token)=([^&\s]+)", r"\1=[redacted]", text)
    text = re.sub(r"(?i)(bearer)\s+[A-Za-z0-9._~+/=-]+", r"\1 [redacted]", text)
    text = re.sub(r"(?i)(authorization:\s*)[^\s]+", r"\1[redacted]", text)
    return text[:1000]


def _can_split_time(window: dict[str, Any]) -> bool:
    return (_parse_dt(window.get("end")) - _parse_dt(window.get("start"))).total_seconds() > 1


def _split_window(window: dict[str, Any]) -> list[dict[str, Any]]:
    start = _parse_dt(window.get("start"))
    end = _parse_dt(window.get("end"))
    if (end - start).total_seconds() > 1:
        midpoint = start + (end - start) / 2
        left = {**window, "start": _format_query_dt(start), "end": _format_query_dt(midpoint)}
        right_start = midpoint + timedelta(seconds=1)
        if right_start > end:
            right_start = midpoint
        right = {**window, "start": _format_query_dt(right_start), "end": _format_query_dt(end)}
        return [left, right]
    record_id = window.get("id") if isinstance(window.get("id"), dict) else window.get("recid") if isinstance(window.get("recid"), dict) else {"from": 0, "to": 10_000_000_000}
    low = int(record_id.get("from", 0))
    high = int(record_id.get("to", 10_000_000_000))
    if high <= low:
        return [window]
    midpoint = low + ((high - low) // 2)
    base = {key: value for key, value in window.items() if key != "recid"}
    return [
        {**base, "id": {"from": low, "to": midpoint}},
        {**base, "id": {"from": midpoint + 1, "to": high}},
    ]


def _should_split_error(response, *, page: int | None = None) -> bool:
    text = str(getattr(response, "text", "") or "").lower()
    if response.status_code == 504 and page is not None and page > 1:
        return True
    if response.status_code in {400, 422} and page is not None and page >= PRECHECK_PAGE:
        return True
    return response.status_code in {400, 422} and bool(re.search(r"result window|too many|10000|max", text))


class ZenodoAccountRetrievalRunner:
    def __init__(
        self,
        *,
        retrieval_id: str,
        credential: ZenodoCredential,
        requester: User,
        http: Any = requests,
        sleep_func: Any = time.sleep,
        shard_record_limit: int = DEFAULT_SHARD_RECORD_LIMIT,
        min_interval_seconds: float = 2.05,
        max_records: int | None = None,
        initial_window_days: int = DEFAULT_INITIAL_WINDOW_DAYS,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        request_retries: int = DEFAULT_REQUEST_RETRIES,
    ):
        self.retrieval_id = retrieval_id
        self.credential = credential
        self.requester = requester
        self.environment = str(credential.environment or "production").strip().lower()
        self.http = http
        self.sleep_func = sleep_func
        self.shard_record_limit = max(100, int(shard_record_limit or DEFAULT_SHARD_RECORD_LIMIT))
        self.client: RateLimitedZenodoClient | None = None
        self.min_interval_seconds = min_interval_seconds
        self.max_records = normalize_max_records(max_records)
        self.initial_window_days = max(1, int(initial_window_days or DEFAULT_INITIAL_WINDOW_DAYS))
        self.request_timeout_seconds = request_timeout_seconds
        self.request_retries = request_retries
        self.current_shard_records: list[dict[str, Any]] = []
        self.current_shard_window: dict[str, Any] | None = None

    def _notify_final_state(self, *, status: str, title: str, body: str, severity: str, summary: dict[str, Any] | None = None) -> None:
        notify_user(
            recipient_user_id=self.requester.id,
            notification_type=f"zenodo.retrieval_{status}",
            category="zenodo",
            severity=severity,
            title=title,
            body=body,
            entity_type="zenodo_retrieval",
            entity_id=self.retrieval_id,
            action_url="/tools/zenodo-account-retrieval",
            payload={"summary": summary or {}, "environment": self.environment},
            dedupe_key=f"zenodo-retrieval:{self.retrieval_id}:{status}",
        )

    def run(self, *, token: str, task_self: Any = None) -> dict[str, Any]:
        update_retrieval_entry(
            self.retrieval_id,
            runtime={
                "process": {
                    "pid": os.getpid(),
                    "status": "running",
                    "started_at": _utc_now_iso(),
                }
            },
            heartbeat=True,
        )
        self.client = RateLimitedZenodoClient(
            token=token,
            environment=self.environment,
            http=self.http,
            sleep_func=self.sleep_func,
            min_interval_seconds=self.min_interval_seconds,
            request_timeout_seconds=self.request_timeout_seconds,
            request_retries=self.request_retries,
        )
        entry = get_retrieval_entry(self.retrieval_id) or {}
        options = entry.get("options") if isinstance(entry.get("options"), dict) else {}
        entry_max_records = options.get("max_records")
        if entry_max_records not in (None, ""):
            self.max_records = normalize_max_records(entry_max_records)
        checkpoint = entry.get("checkpoint") if isinstance(entry.get("checkpoint"), dict) else {}
        manifest = entry.get("manifest") if isinstance(entry.get("manifest"), dict) else {"retrieval_id": self.retrieval_id, "shards": []}
        manifest["max_records"] = self.max_records
        manifest["retrieval_mode"] = options.get("retrieval_mode") or manifest.get("retrieval_mode") or "full"
        manifest["sync_mode"] = options.get("sync_mode") or manifest.get("sync_mode") or "full"
        manifest["parent_retrieval_id"] = options.get("parent_retrieval_id") or manifest.get("parent_retrieval_id")
        manifest["incremental_since"] = options.get("incremental_since") or manifest.get("incremental_since")
        manifest["date_window"] = {
            "start": options.get("start_datetime"),
            "end": options.get("end_datetime"),
        }
        seen_keys = {str(item) for item in (checkpoint.get("seen_keys") or []) if str(item or "").strip()}
        windows = checkpoint.get("pending_windows") if isinstance(checkpoint.get("pending_windows"), list) else None
        active_from_checkpoint = checkpoint.get("active_window") if isinstance(checkpoint.get("active_window"), dict) else None
        if windows is None:
            start = options.get("start_datetime") or "1970-01-01T00:00:00Z"
            end = options.get("end_datetime") or _format_query_dt(_utc_now() + timedelta(days=1))
            windows = _seed_windows(["published", "draft"], start, end, newest_first=True, max_days=self.initial_window_days)
        else:
            windows = [dict(window) for window in windows if isinstance(window, dict)]
        if active_from_checkpoint:
            windows = [dict(active_from_checkpoint)] + windows
        summary = dict(entry.get("summary") or {})
        summary.setdefault("retrieved_records", 0)
        summary.setdefault("created_shards", len(manifest.get("shards") or []))
        summary.setdefault("published_records", 0)
        summary.setdefault("draft_records", 0)
        summary.setdefault("failed_windows", 0)
        summary.setdefault("rate_limited_waits", 0)
        summary.setdefault("duplicate_records_skipped", 0)
        summary.setdefault("split_windows", 0)
        summary.setdefault("pages_retrieved", 0)
        summary.setdefault("wait_seconds", 0)
        summary.setdefault("latest_created", None)
        summary.setdefault("latest_modified", None)
        summary.setdefault("earliest_created", None)
        summary["sync_mode"] = options.get("sync_mode") or summary.get("sync_mode") or "full"
        summary["retrieval_mode"] = options.get("retrieval_mode") or summary.get("retrieval_mode") or "full"
        summary["parent_retrieval_id"] = options.get("parent_retrieval_id") or summary.get("parent_retrieval_id")
        summary["seen_records"] = len(seen_keys)
        summary["max_records"] = self.max_records
        summary.setdefault("limit_reached", False)

        processed_windows = int((entry.get("progress") or {}).get("processed_windows") or 0)
        active_window: dict[str, Any] | None = None
        try:
            while windows:
                self._check_control()
                if self._limit_reached(summary):
                    summary["limit_reached"] = True
                    windows = []
                    break
                window = windows.pop(0)
                base_window = _window_without_cursor(window)
                page = _window_page(window)
                active_window = {**base_window, "next_page": page}
                response = self.client.get_depositions(status=base_window["status"], page=page, size=DEFAULT_PAGE_SIZE, query=_window_query(base_window))
                if _should_split_error(response, page=page):
                    split_windows = self._split_for_retry(base_window)
                    windows = split_windows + windows
                    active_window = None
                    summary["split_windows"] = int(summary.get("split_windows") or 0) + 1
                    summary["rate_limited_waits"] = self.client.rate_limited_waits
                    self._persist(
                        task_self,
                        windows,
                        manifest,
                        summary,
                        processed_windows,
                        "Split unstable Zenodo retrieval window",
                        None,
                        seen_keys=seen_keys,
                    )
                    continue

                if response.status_code in {502, 503, 504}:
                    retry_count = int(base_window.get("retry_count") or 0)
                    if retry_count < 5:
                        deferred_window = {**base_window, "next_page": page, "retry_count": retry_count + 1}
                        windows.append(deferred_window)
                        active_window = None
                        summary["deferred_windows"] = int(summary.get("deferred_windows") or 0) + 1
                        self._persist(
                            task_self,
                            windows,
                            manifest,
                            summary,
                            processed_windows,
                            "Deferred transient Zenodo retrieval window",
                            None,
                            seen_keys=seen_keys,
                        )
                        continue

                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list) or not payload:
                    processed_windows += 1
                    active_window = None
                    summary["rate_limited_waits"] = self.client.rate_limited_waits
                    summary["seen_records"] = len(seen_keys)
                    self._persist(task_self, windows, manifest, summary, processed_windows, "Completed Zenodo retrieval window", None, seen_keys=seen_keys)
                    continue

                fetched: list[dict[str, Any]] = []
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    sanitized = sanitize_for_storage(item)
                    key = _record_seen_key(sanitized, str(base_window.get("status") or "published"))
                    if key in seen_keys:
                        summary["duplicate_records_skipped"] = int(summary.get("duplicate_records_skipped") or 0) + 1
                        continue
                    if self._remaining_records(summary) is not None and self._remaining_records(summary) <= len(fetched):
                        break
                    seen_keys.add(key)
                    fetched.append(sanitized)

                if fetched:
                    _update_summary_temporal_bounds(summary, fetched)
                    if not self.current_shard_records:
                        self.current_shard_window = dict(base_window)
                    self.current_shard_records.extend(fetched)
                    summary["retrieved_records"] += len(fetched)
                    status_key = "published_records" if base_window.get("status") == "published" else "draft_records"
                    summary[status_key] = int(summary.get(status_key) or 0) + len(fetched)

                if self.current_shard_records:
                    shard_window = {
                        **(self.current_shard_window or base_window),
                        "page": page,
                        "artifact_granularity": "retrieval_page_checkpoint",
                    }
                    shard = self._flush_shard(manifest, shard_window)
                    if shard:
                        summary["created_shards"] = len(manifest.get("shards") or [])

                summary["pages_retrieved"] = int(summary.get("pages_retrieved") or 0) + 1
                summary["rate_limited_waits"] = self.client.rate_limited_waits
                summary["seen_records"] = len(seen_keys)
                if self._limit_reached(summary):
                    summary["limit_reached"] = True
                    windows = []
                    active_window = None
                    self._persist(task_self, windows, manifest, summary, processed_windows, "Harvesting Zenodo account records", None, seen_keys=seen_keys)
                    continue
                if len(payload) < DEFAULT_PAGE_SIZE:
                    processed_windows += 1
                    active_window = None
                else:
                    active_window = {**base_window, "next_page": page + 1}
                self._persist(task_self, windows, manifest, summary, processed_windows, "Harvesting Zenodo account records", active_window, seen_keys=seen_keys)
                if active_window:
                    windows = [active_window] + windows

            if self.current_shard_records:
                self._flush_shard(manifest, self.current_shard_window or {})
            summary["created_shards"] = len(manifest.get("shards") or [])
            summary["rate_limited_waits"] = self.client.rate_limited_waits
            summary["wait_seconds"] = round(float(self.client.wait_seconds), 3)
            summary["coverage_summary"] = _coverage_summary_from_entry_parts(summary, manifest)
            progress = self._progress(windows, summary, processed_windows, None)
            status = "completed: maximum record limit reached" if summary.get("limit_reached") else "completed"
            update_retrieval_entry(
                self.retrieval_id,
                state="SUCCESS",
                status=status,
                progress=progress,
                checkpoint={"pending_windows": [], "active_window": None, "seen_count": len(seen_keys)},
                manifest=manifest,
                summary=summary,
                error="",
                runtime={"process": {"pid": os.getpid(), "status": "exited", "exit_code": 0, "finished_at": _utc_now_iso()}},
                collection={"coverage_summary": summary["coverage_summary"]},
                heartbeat=True,
            )
            result = {"status": status, "retrieval_id": self.retrieval_id, "progress": progress, "summary": summary, "manifest": manifest}
            if task_self is not None:
                task_self.update_state(state="SUCCESS", meta={"status": "completed", "progress": progress, "result": result})
            self._notify_final_state(
                status="completed",
                title="Zenodo retrieval completed",
                body=f"Retrieved {int(summary.get('retrieved_records') or 0)} Zenodo records.",
                severity="success",
                summary=summary,
            )
            db.session.commit()
            return result
        except ZenodoAccountRetrievalPaused:
            if self.current_shard_records:
                self._flush_shard(manifest, self.current_shard_window or {})
            summary["created_shards"] = len(manifest.get("shards") or [])
            summary["rate_limited_waits"] = self.client.rate_limited_waits if self.client else summary.get("rate_limited_waits", 0)
            summary["wait_seconds"] = round(float(self.client.wait_seconds), 3) if self.client else summary.get("wait_seconds", 0)
            summary["coverage_summary"] = _coverage_summary_from_entry_parts(summary, manifest)
            progress = self._progress(windows, summary, processed_windows, None)
            update_retrieval_entry(
                self.retrieval_id,
                state="PAUSED",
                status="paused",
                progress=progress,
                checkpoint={"pending_windows": windows, "active_window": active_window, "seen_keys": sorted(seen_keys), "seen_count": len(seen_keys)},
                manifest=manifest,
                summary=summary,
                runtime={"process": {"pid": os.getpid(), "status": "paused", "updated_at": _utc_now_iso()}},
                heartbeat=True,
            )
            return {"status": "paused", "retrieval_id": self.retrieval_id, "progress": progress, "summary": summary, "manifest": manifest}
        except ZenodoAccountRetrievalCancelled:
            summary["coverage_summary"] = _coverage_summary_from_entry_parts(summary, manifest)
            update_retrieval_entry(self.retrieval_id, state="CANCELLED", status="cancelled", checkpoint={"pending_windows": windows, "active_window": active_window, "seen_keys": sorted(seen_keys), "seen_count": len(seen_keys)}, manifest=manifest, summary=summary, heartbeat=True)
            self._notify_final_state(
                status="cancelled",
                title="Zenodo retrieval cancelled",
                body="The Zenodo account retrieval was cancelled.",
                severity="warning",
                summary=summary,
            )
            db.session.commit()
            return {"status": "cancelled", "retrieval_id": self.retrieval_id, "summary": summary, "manifest": manifest}
        except Exception as exc:
            logger.error("Zenodo account retrieval %s failed: %s", self.retrieval_id, exc, exc_info=True)
            summary["coverage_summary"] = _coverage_summary_from_entry_parts(summary, manifest)
            update_retrieval_entry(self.retrieval_id, state="FAILURE", status=str(exc), checkpoint={"pending_windows": windows, "active_window": active_window, "seen_keys": sorted(seen_keys), "seen_count": len(seen_keys)}, manifest=manifest, summary=summary, error=str(exc), runtime={"process": {"pid": os.getpid(), "status": "exited", "exit_code": 1, "finished_at": _utc_now_iso()}}, heartbeat=True)
            self._notify_final_state(
                status="failed",
                title="Zenodo retrieval failed",
                body=str(exc),
                severity="error",
                summary=summary,
            )
            db.session.commit()
            raise

    def _check_control(self) -> None:
        entry = get_retrieval_entry(self.retrieval_id) or {}
        control = entry.get("control") if isinstance(entry.get("control"), dict) else {}
        if control.get("cancel_requested"):
            raise ZenodoAccountRetrievalCancelled()
        if control.get("pause_requested"):
            raise ZenodoAccountRetrievalPaused()

    def _window_is_dense(self, window: dict[str, Any]) -> bool:
        response = self.client.get_depositions(status=window["status"], page=PRECHECK_PAGE, size=DEFAULT_PAGE_SIZE, query=_window_query(window))
        if _should_split_error(response, page=PRECHECK_PAGE):
            return True
        response.raise_for_status()
        payload = response.json()
        return isinstance(payload, list) and len(payload) >= DEFAULT_PAGE_SIZE

    def _split_for_retry(self, window: dict[str, Any]) -> list[dict[str, Any]]:
        split_windows = _split_window(window)
        if len(split_windows) <= 1:
            raise ValueError("Zenodo retrieval window is still too dense after recid splitting")
        if self.max_records is not None:
            split_windows = list(reversed(split_windows))
        return [{**_window_without_cursor(item), "next_page": 1} for item in split_windows]

    def _remaining_records(self, summary: dict[str, Any]) -> int | None:
        if self.max_records is None:
            return None
        return max(int(self.max_records) - int(summary.get("retrieved_records") or 0), 0)

    def _limit_reached(self, summary: dict[str, Any]) -> bool:
        remaining = self._remaining_records(summary)
        return remaining is not None and remaining <= 0

    def _harvest_window(self, window: dict[str, Any], *, remaining_records: int | None = None) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if remaining_records is not None and remaining_records <= 0:
            return records
        page = 1
        while True:
            self._check_control()
            response = self.client.get_depositions(status=window["status"], page=page, size=DEFAULT_PAGE_SIZE, query=_window_query(window))
            if _should_split_error(response, page=page):
                raise ZenodoRetrievalWindowTooDense()
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or not payload:
                break
            for item in payload:
                if isinstance(item, dict):
                    records.append(sanitize_for_storage(item))
                    if remaining_records is not None and len(records) >= remaining_records:
                        break
            if remaining_records is not None and len(records) >= remaining_records:
                break
            if len(payload) < DEFAULT_PAGE_SIZE:
                break
            page += 1
        return records

    def _persist(
        self,
        task_self: Any,
        windows: list[dict[str, Any]],
        manifest: dict[str, Any],
        summary: dict[str, Any],
        processed_windows: int,
        status: str,
        current_window: dict[str, Any] | None,
        *,
        seen_keys: set[str] | None = None,
    ) -> None:
        seen_keys = seen_keys or set()
        if self.client:
            summary["wait_seconds"] = round(float(self.client.wait_seconds), 3)
        progress = self._progress(windows, summary, processed_windows, current_window)
        update_retrieval_entry(
            self.retrieval_id,
            state="PROGRESS",
            status=status,
            progress=progress,
            checkpoint={
                "pending_windows": windows,
                "active_window": current_window,
                "seen_keys": sorted(seen_keys),
                "seen_count": len(seen_keys),
            },
            manifest=manifest,
            summary=summary,
            heartbeat=True,
        )
        if task_self is not None:
            task_self.update_state(state="PROGRESS", meta={"status": status, "progress": progress})

    def _progress(self, windows: list[dict[str, Any]], summary: dict[str, Any], processed_windows: int, current_window: dict[str, Any] | None) -> dict[str, Any]:
        pending = len(windows)
        active = 1 if current_window else 0
        total_windows = processed_windows + pending + active
        entry = get_retrieval_entry(self.retrieval_id) or {}
        started_at = _parse_dt(entry.get("created_at"), _utc_now())
        elapsed_seconds = max((_utc_now() - started_at).total_seconds(), 1)
        records_per_hour = int((int(summary.get("retrieved_records") or 0) / elapsed_seconds) * 3600)
        pages_per_hour = int((int(summary.get("pages_retrieved") or 0) / elapsed_seconds) * 3600)
        eta_seconds = None
        if processed_windows > 0 and pending:
            eta_seconds = int((elapsed_seconds / max(processed_windows, 1)) * pending)
        return {
            "total_records": int(summary.get("retrieved_records") or 0),
            "retrieved_records": int(summary.get("retrieved_records") or 0),
            "processed_windows": processed_windows,
            "pending_windows": pending,
            "active_window": current_window,
            "current_page": _window_page(current_window or {}) if current_window else None,
            "created_shards": int(summary.get("created_shards") or 0),
            "rate_limited_waits": self.client.rate_limited_waits if self.client else int(summary.get("rate_limited_waits") or 0),
            "percent": 100 if total_windows == 0 else int(round((processed_windows / max(total_windows, 1)) * 100)),
            "current_window": current_window,
            "max_records": self.max_records,
            "limit_reached": bool(summary.get("limit_reached")),
            "seen_records": int(summary.get("seen_records") or 0),
            "pages_retrieved": int(summary.get("pages_retrieved") or 0),
            "duplicate_records_skipped": int(summary.get("duplicate_records_skipped") or 0),
            "split_windows": int(summary.get("split_windows") or 0),
            "deferred_windows": int(summary.get("deferred_windows") or 0),
            "wait_seconds": float(summary.get("wait_seconds") or 0),
            "records_per_hour": records_per_hour,
            "pages_per_hour": pages_per_hour,
            "eta_seconds": eta_seconds,
            "eta_basis": "processed_window_average" if eta_seconds is not None else "unavailable_until_windows_complete",
            "eta_confidence": "low" if int(summary.get("split_windows") or 0) or int(summary.get("deferred_windows") or 0) else "medium",
            "retrieval_mode": summary.get("retrieval_mode") or "full",
            "latest_created": summary.get("latest_created"),
            "latest_modified": summary.get("latest_modified"),
        }

    def _flush_shard(self, manifest: dict[str, Any], window: dict[str, Any]) -> dict[str, Any] | None:
        if not self.current_shard_records:
            return None
        shard_index = len(manifest.get("shards") or []) + 1
        records = list(self.current_shard_records)
        self.current_shard_records = []
        self.current_shard_window = None
        shard = write_retrieval_shard(
            retrieval_id=self.retrieval_id,
            shard_index=shard_index,
            records=records,
            environment=self.environment,
            requested_by=self.requester,
            credential=self.credential,
            window=window,
            manifest_summary={
                "retrieval_id": self.retrieval_id,
                "shard_index": shard_index,
                "record_count": len(records),
                "retrieval_mode": manifest.get("retrieval_mode") or "full",
                "sync_mode": manifest.get("sync_mode") or "full",
                "parent_retrieval_id": manifest.get("parent_retrieval_id"),
            },
        )
        manifest.setdefault("shards", []).append(shard)
        return shard


def write_retrieval_shard(
    *,
    retrieval_id: str,
    shard_index: int,
    records: list[dict[str, Any]],
    environment: str,
    requested_by: User,
    credential: ZenodoCredential,
    window: dict[str, Any],
    manifest_summary: dict[str, Any],
) -> dict[str, Any]:
    session_manager = getattr(current_app, "session_manager", None)
    if session_manager is None:
        raise ValueError("Session manager is not configured")
    hdpc_path, _, _, session_dir = session_manager.create_session_dirs()
    conn = connect_hdpc(hdpc_path, timeout=60)
    try:
        project_id = ensure_hdpc_schema(conn, hdpc_path)
        cursor = conn.cursor()
        now = _utc_now_iso()
        _upsert_project_config(cursor, project_id, "retrieval.kind", "zenodo_account_deep_retrieval")
        _upsert_project_config(cursor, project_id, "retrieval.id", retrieval_id)
        _upsert_project_config(cursor, project_id, "retrieval.shard_index", str(shard_index))
        _upsert_project_config(cursor, project_id, "retrieval.environment", environment)
        _upsert_project_config(cursor, project_id, "retrieval.window", json.dumps(window, sort_keys=True))
        _upsert_project_config(cursor, project_id, "retrieval.manifest", json.dumps(manifest_summary, sort_keys=True))
        _upsert_project_config(cursor, project_id, "retrieval.mode", str(manifest_summary.get("retrieval_mode") or "full"))
        _upsert_project_config(cursor, project_id, "retrieval.sync_mode", str(manifest_summary.get("sync_mode") or "full"))
        if manifest_summary.get("parent_retrieval_id"):
            _upsert_project_config(cursor, project_id, "retrieval.parent_retrieval_id", str(manifest_summary.get("parent_retrieval_id")))

        for record_index, raw_deposition in enumerate(records, start=1):
            deposition = sanitize_for_storage(raw_deposition)
            status = _extract_record_status(deposition, str(window.get("status") or "published"))
            links = _links(deposition)
            deposition_id = _extract_deposition_id(deposition)
            provenance = {
                "retrieval_id": retrieval_id,
                "retrieval_kind": "zenodo_account_deep_retrieval",
                "shard_index": shard_index,
                "source_status_query": str(window.get("status") or ""),
                "date_window": {"start": window.get("start"), "end": window.get("end")},
                "environment": environment,
                "requested_by": {
                    "user_id": int(requested_by.id),
                    "public_id": requested_by.public_id,
                    "email": requested_by.email,
                    "display_name": requested_by.display_name,
                },
                "credential": {
                    "credential_id": int(credential.id),
                    "owner_type": credential.owner_type,
                    "owner_id": int(credential.owner_id) if credential.owner_id is not None else None,
                    "relation": _credential_relation(credential, requested_by),
                },
                "deposition_owner_id": _extract_deposition_owner_id(deposition),
                "capabilities": {
                    "had_edit_rights": _has_edit_rights(deposition, status),
                    "had_version_rights": _has_version_rights(deposition),
                    "edit_link_present": bool(links.get("edit")),
                    "newversion_link_present": bool(links.get("newversion")),
                },
                "retrieved_at": now,
            }
            payload = dict(deposition)
            payload["webhdp_retrieval"] = provenance
            cursor.execute(
                """
                INSERT INTO zenodo_records (
                    project_id, source_file_id, record_title, record_status, record_metadata_json,
                    creation_api_response, last_publish_api_response, zenodo_record_id, concept_rec_id,
                    zenodo_doi, concept_doi, is_sandbox, created_timestamp, last_updated_timestamp,
                    version, version_rank, previous_record_id, record_origin, last_api_error
                ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL)
                """,
                (
                    project_id,
                    _extract_title(deposition),
                    status,
                    json.dumps(payload, sort_keys=True),
                    json.dumps({"retrieval_id": retrieval_id, "retrieved_at": now}, sort_keys=True),
                    json.dumps(deposition if status == "published" else {}, sort_keys=True),
                    deposition_id,
                    str(deposition.get("conceptrecid") or "").strip() or None,
                    _extract_doi(deposition),
                    _extract_concept_doi(deposition),
                    0 if environment == "production" else 1,
                    str(deposition.get("created") or now),
                    str(deposition.get("modified") or deposition.get("updated") or now),
                    str((deposition.get("metadata") or {}).get("version") or deposition.get("version") or ""),
                    record_index,
                    RETRIEVAL_RECORD_ORIGIN,
                ),
            )
            local_record_id = int(cursor.lastrowid)
            cursor.execute(
                """
                INSERT INTO zenodo_record_snapshots (record_id, snapshot_stage, http_status, payload_json, created_timestamp)
                VALUES (?, 'account_retrieval_deposition', 200, ?, ?)
                """,
                (local_record_id, json.dumps(payload, sort_keys=True), now),
            )
            for rel, url in links.items():
                if not rel or not url:
                    continue
                cursor.execute(
                    """
                    INSERT INTO zenodo_record_links (record_id, link_rel, link_url, created_timestamp, updated_timestamp)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(record_id, link_rel) DO UPDATE SET link_url = excluded.link_url, updated_timestamp = excluded.updated_timestamp
                    """,
                    (local_record_id, str(rel), str(url), now, now),
                )
            _write_retrieved_files(cursor, project_id, local_record_id, deposition, now)
        conn.commit()
    finally:
        conn.close()

    session = DBSession(
        user_id=int(requested_by.id),
        session_dir=session_dir,
        hdpc_path=hdpc_path,
        status="completed",
        sharing_scope="private",
        credential_preference="user",
        publishing_user_id=int(requested_by.id),
        default_zenodo_environment=environment,
        origin_type=RETRIEVAL_SESSION_ORIGIN,
        access_mode="explorer_only",
        origin_metadata_json=json.dumps(
            {
                "retrieval_id": retrieval_id,
                "shard_index": shard_index,
                "record_count": len(records),
                "environment": environment,
                "window": window,
                "artifact_kind": "zenodo_retrieval_shard",
                "sync_mode": manifest_summary.get("sync_mode") or "full",
                "parent_retrieval_id": manifest_summary.get("parent_retrieval_id"),
            },
            sort_keys=True,
        ),
        timings="{}",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.session.add(session)
    db.session.commit()
    return {
        "shard_index": shard_index,
        "session_id": int(session.id),
        "hdpc_path": hdpc_path,
        "record_count": len(records),
        "environment": environment,
        "window": window,
        "created_at": session.created_at.isoformat() if session.created_at else None,
    }


def _upsert_project_config(cursor, project_id: int, key: str, value: str) -> None:
    cursor.execute(
        """
        INSERT INTO project_configuration (project_id, config_key, config_value, description)
        VALUES (?, ?, ?, 'Zenodo account retrieval metadata')
        ON CONFLICT(project_id, config_key) DO UPDATE SET config_value = excluded.config_value
        """,
        (int(project_id), key, value),
    )


def _write_retrieved_files(cursor, project_id: int, local_record_id: int, deposition: dict[str, Any], now: str) -> None:
    files = deposition.get("files") if isinstance(deposition.get("files"), list) else []
    for index, file_obj in enumerate([item for item in files if isinstance(item, dict)], start=1):
        filename = _file_name(file_obj, index)
        size_value = file_obj.get("filesize") if file_obj.get("filesize") is not None else file_obj.get("size")
        links = file_obj.get("links") if isinstance(file_obj.get("links"), dict) else {}
        cursor.execute(
            """
            INSERT INTO source_files (
                project_id, absolute_path, relative_path, filename, size_bytes, sha256_hash,
                mime_type, file_type, status, added_timestamp, last_processed_timestamp,
                is_primary_source, pipeline_source, step_source
            ) VALUES (?, NULL, ?, ?, ?, ?, ?, 'retrieved_file', 'retrieved_metadata_only', ?, ?, 0, 'zenodo_retrieval', 'account_retrieval')
            """,
            (
                project_id,
                filename,
                filename,
                _to_int(size_value, 0),
                str(file_obj.get("checksum") or "").strip() or None,
                str(file_obj.get("type") or file_obj.get("mime_type") or "").strip() or None,
                now,
                now,
            ),
        )
        file_id = int(cursor.lastrowid)
        cursor.execute(
            """
            INSERT INTO record_files_map (
                record_id, file_id, file_path, file_purpose, zenodo_file_id, zenodo_file_key,
                zenodo_file_checksum, zenodo_file_size, zenodo_file_links_json,
                upload_status, upload_timestamp, upload_response_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'retrieved_metadata_only', ?, ?)
            """,
            (
                local_record_id,
                file_id,
                filename,
                "main" if index == 1 else "attached",
                str(file_obj.get("id") or "").strip() or None,
                filename,
                str(file_obj.get("checksum") or "").strip() or None,
                _to_int(size_value, 0),
                json.dumps(sanitize_for_storage(links), sort_keys=True),
                now,
                json.dumps(sanitize_for_storage(file_obj), sort_keys=True),
            ),
        )


def _credential_relation(credential: ZenodoCredential, requester: User) -> str:
    if credential.owner_type == "user" and int(credential.owner_id) == int(requester.id):
        return "owned_by_requesting_user"
    if credential.owner_type == "user":
        return "shared_to_requesting_user"
    return credential.owner_type or "unknown"


def delete_retrieval_shards(entry: dict[str, Any]) -> dict[str, Any]:
    manifest = entry.get("manifest") if isinstance(entry.get("manifest"), dict) else {}
    deleted_sessions = 0
    deleted_files = 0
    all_shards = list(manifest.get("shards") or []) + list(manifest.get("compacted_shards") or [])
    for shard in all_shards:
        if not isinstance(shard, dict):
            continue
        session_id = _to_int(shard.get("session_id"), 0)
        if not session_id:
            continue
        session = db.session.get(DBSession, session_id)
        if session is None:
            continue
        session_dir = Path(session.session_dir)
        db.session.delete(session)
        deleted_sessions += 1
        db.session.flush()
        if session_dir.is_dir():
            for child in session_dir.iterdir():
                if child.is_file() and child.name == "session.hdpc":
                    child.unlink(missing_ok=True)
                    deleted_files += 1
    db.session.commit()
    return {"deleted_sessions": deleted_sessions, "deleted_files": deleted_files}


def iter_retrieval_records(entry: dict[str, Any], *, include_compacted: bool = True):
    manifest = entry.get("manifest") if isinstance(entry.get("manifest"), dict) else {}
    shard_groups = list(manifest.get("shards") or [])
    if include_compacted:
        shard_groups.extend(manifest.get("compacted_shards") or [])
    for shard in shard_groups:
        if not isinstance(shard, dict):
            continue
        hdpc_path = shard.get("hdpc_path")
        if not hdpc_path or not os.path.exists(str(hdpc_path)):
            continue
        conn = connect_hdpc(str(hdpc_path), timeout=30)
        try:
            cursor = conn.cursor()
            rows = cursor.execute(
                """
                SELECT record_id, record_title, record_status, zenodo_record_id, zenodo_doi,
                       concept_rec_id, record_metadata_json, created_timestamp, last_updated_timestamp,
                       record_origin
                FROM zenodo_records
                ORDER BY record_id ASC
                """
            ).fetchall()
            for row in rows:
                metadata = {}
                try:
                    metadata = json.loads(row[6] or "{}")
                except json.JSONDecodeError:
                    metadata = {}
                retrieval_meta = metadata.get("webhdp_retrieval") if isinstance(metadata.get("webhdp_retrieval"), dict) else {}
                capabilities = retrieval_meta.get("capabilities") if isinstance(retrieval_meta.get("capabilities"), dict) else {}
                yield {
                    "local_record_id": row[0],
                    "title": row[1],
                    "status": row[2],
                    "zenodo_record_id": row[3],
                    "doi": row[4],
                    "concept_rec_id": row[5],
                    "created": row[7],
                    "modified": row[8],
                    "record_origin": row[9],
                    "retrieval": retrieval_meta,
                    "capabilities": capabilities,
                    "session_id": shard.get("session_id"),
                    "shard_index": shard.get("shard_index"),
                    "hdpc_path": str(hdpc_path),
                    "metadata": metadata,
                }
        finally:
            conn.close()


def search_retrieval_collection(
    entry: dict[str, Any],
    *,
    query: str | None = None,
    status: str | None = None,
    edit_capability: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    normalized_query = str(query or "").strip().lower()
    normalized_status = str(status or "").strip().lower()
    normalized_capability = str(edit_capability or "").strip().lower()
    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, int(offset or 0))
    total = 0
    records: list[dict[str, Any]] = []
    for record in iter_retrieval_records(entry, include_compacted=False):
        if normalized_status and str(record.get("status") or "").lower() != normalized_status:
            continue
        if normalized_capability == "editable" and not record.get("capabilities", {}).get("had_edit_rights"):
            continue
        if normalized_capability == "versionable" and not record.get("capabilities", {}).get("had_version_rights"):
            continue
        haystack = " ".join(
            str(record.get(key) or "")
            for key in ("title", "zenodo_record_id", "doi", "concept_rec_id", "created", "modified")
        ).lower()
        if normalized_query and normalized_query not in haystack:
            continue
        total += 1
        if total <= offset:
            continue
        if len(records) < limit:
            public_record = dict(record)
            public_record.pop("metadata", None)
            public_record.pop("hdpc_path", None)
            records.append(public_record)
    return {"records": records, "total": total, "limit": limit, "offset": offset}


def _record_metadata_text(metadata: dict[str, Any]) -> str:
    payload = dict(metadata or {})
    payload.pop("webhdp_retrieval", None)
    return json.dumps(payload, sort_keys=True).lower()


def _record_files(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    files = metadata.get("files") if isinstance(metadata.get("files"), list) else []
    return [item for item in files if isinstance(item, dict)]


def _file_match_names(metadata: dict[str, Any]) -> list[str]:
    matches: list[str] = []
    for file_obj in _record_files(metadata):
        name = _file_name(file_obj, len(matches) + 1)
        if Path(name).suffix.lower() in MODEL_FILE_EXTENSIONS:
            matches.append(name)
    return matches


def _community_identifiers(metadata: dict[str, Any]) -> list[str]:
    record_metadata = metadata.get("metadata") if isinstance(metadata.get("metadata"), dict) else {}
    communities = record_metadata.get("communities") or metadata.get("communities") or []
    identifiers: list[str] = []
    if isinstance(communities, list):
        for item in communities:
            if isinstance(item, dict):
                for key in ("identifier", "id", "slug"):
                    if str(item.get(key) or "").strip():
                        identifiers.append(str(item.get(key)).strip())
                        break
            elif str(item or "").strip():
                identifiers.append(str(item).strip())
    return identifiers


def _public_detector_record(record: dict[str, Any], *, reason: str, file_matches: list[str], communities: list[str]) -> dict[str, Any]:
    return {
        "session_id": record.get("session_id"),
        "shard_index": record.get("shard_index"),
        "local_record_id": record.get("local_record_id"),
        "zenodo_record_id": record.get("zenodo_record_id"),
        "title": record.get("title"),
        "status": record.get("status"),
        "doi": record.get("doi"),
        "concept_rec_id": record.get("concept_rec_id"),
        "created": record.get("created"),
        "modified": record.get("modified"),
        "had_edit_rights": bool(record.get("capabilities", {}).get("had_edit_rights")),
        "had_version_rights": bool(record.get("capabilities", {}).get("had_version_rights")),
        "reason": reason,
        "file_matches": file_matches,
        "communities": communities,
    }


def run_retrieval_detector(
    entry: dict[str, Any],
    *,
    detector_id: str,
    target_community: str | None = "3dbigdataspace",
    limit: int = 250,
    offset: int = 0,
) -> dict[str, Any]:
    normalized_detector = str(detector_id or "community_migration_candidates").strip().lower()
    if normalized_detector not in DETECTOR_PRESETS:
        raise ValueError("detector must be one of objaverse, 3d_model_files, missing_target_community, or community_migration_candidates")
    normalized_target = str(target_community or "").strip().lower()
    limit = max(1, min(int(limit or 250), 1000))
    offset = max(0, int(offset or 0))
    total = 0
    candidates: list[dict[str, Any]] = []

    for record in iter_retrieval_records(entry, include_compacted=False):
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        text = _record_metadata_text(metadata)
        file_matches = _file_match_names(metadata)
        communities = _community_identifiers(metadata)
        community_set = {item.lower() for item in communities}
        has_objaverse = "objaverse" in text
        has_model_file = bool(file_matches)
        missing_target = bool(normalized_target) and normalized_target not in community_set

        reason = ""
        if normalized_detector == "objaverse" and has_objaverse:
            reason = "Metadata mentions Objaverse."
        elif normalized_detector == "3d_model_files" and has_model_file:
            reason = "Record has 3D model file metadata."
        elif normalized_detector == "missing_target_community" and missing_target:
            reason = f"Record is missing target community {normalized_target}."
        elif normalized_detector == "community_migration_candidates" and missing_target and (has_objaverse or has_model_file):
            signals = []
            if has_objaverse:
                signals.append("Objaverse metadata")
            if has_model_file:
                signals.append("3D model files")
            reason = f"{' and '.join(signals)}; missing target community {normalized_target}."
        if not reason:
            continue

        total += 1
        if total <= offset:
            continue
        if len(candidates) < limit:
            candidates.append(_public_detector_record(record, reason=reason, file_matches=file_matches, communities=communities))

    return {
        "detector": DETECTOR_PRESETS[normalized_detector],
        "target_community": normalized_target or None,
        "candidates": candidates,
        "total": total,
        "limit": limit,
        "offset": offset,
        "source": "local_retrieval_shards",
    }


def export_detector_candidates_csv(entry: dict[str, Any], *, detector_id: str, target_community: str | None = "3dbigdataspace") -> str:
    result = run_retrieval_detector(entry, detector_id=detector_id, target_community=target_community, limit=1000)
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "retrieval_id",
            "detector",
            "target_community",
            "session_id",
            "shard_index",
            "zenodo_record_id",
            "title",
            "status",
            "doi",
            "concept_rec_id",
            "created",
            "modified",
            "had_edit_rights",
            "had_version_rights",
            "reason",
            "file_matches",
            "communities",
        ],
    )
    writer.writeheader()
    for record in result["candidates"]:
        writer.writerow(
            {
                "retrieval_id": entry.get("retrieval_id"),
                "detector": result["detector"]["id"],
                "target_community": result.get("target_community"),
                "session_id": record.get("session_id"),
                "shard_index": record.get("shard_index"),
                "zenodo_record_id": record.get("zenodo_record_id"),
                "title": record.get("title"),
                "status": record.get("status"),
                "doi": record.get("doi"),
                "concept_rec_id": record.get("concept_rec_id"),
                "created": record.get("created"),
                "modified": record.get("modified"),
                "had_edit_rights": record.get("had_edit_rights"),
                "had_version_rights": record.get("had_version_rights"),
                "reason": record.get("reason"),
                "file_matches": ";".join(record.get("file_matches") or []),
                "communities": ";".join(record.get("communities") or []),
            }
        )
    return output.getvalue()


def build_retrieval_diagnostics(entry: dict[str, Any]) -> dict[str, Any]:
    runtime = entry.get("runtime") if isinstance(entry.get("runtime"), dict) else {}
    process = runtime.get("process") if isinstance(runtime.get("process"), dict) else {}
    progress = entry.get("progress") if isinstance(entry.get("progress"), dict) else {}
    summary = entry.get("summary") if isinstance(entry.get("summary"), dict) else {}
    checkpoint = entry.get("checkpoint") if isinstance(entry.get("checkpoint"), dict) else {}
    heartbeat_at = _parse_dt(entry.get("heartbeat_at") or entry.get("updated_at"), None)
    heartbeat_age = int((_utc_now() - heartbeat_at).total_seconds()) if heartbeat_at else None
    alive = _process_alive(process.get("pid"))
    state = str(entry.get("state") or "").upper()
    if state in {"SUCCESS", "FAILURE", "CANCELLED"}:
        health = "exited"
    elif entry.get("stale"):
        health = "stale"
    elif alive is True:
        health = "alive"
    elif alive is False:
        health = "exited"
    else:
        health = "unknown"

    log_lines: list[str] = []
    log_path = runtime.get("log_path")
    if log_path and os.path.exists(str(log_path)):
        try:
            with open(str(log_path), "r", encoding="utf-8", errors="replace") as handle:
                log_lines = [_sanitize_log_line(line.rstrip("\n")) for line in handle.readlines()[-40:]]
        except OSError:
            log_lines = []
    if not log_lines:
        for value in (entry.get("status"), entry.get("error")):
            if value:
                log_lines.append(_sanitize_log_line(value))

    return {
        "retrieval_id": entry.get("retrieval_id"),
        "state": entry.get("state"),
        "status": entry.get("status"),
        "heartbeat_at": entry.get("heartbeat_at"),
        "heartbeat_age_seconds": heartbeat_age,
        "stale": bool(entry.get("stale")),
        "process_health": {
            "status": health,
            "pid": process.get("pid"),
            "task_id": entry.get("task_id"),
            "exit_code": process.get("exit_code"),
            "alive": alive,
        },
        "execution_target": runtime.get("execution_target") or "celery_local",
        "runtime": {
            "proxy_policy": runtime.get("proxy_policy"),
            "source_database": runtime.get("source_database"),
            "shard_root": runtime.get("shard_root"),
            "token_source": runtime.get("token_source"),
            "script_version": runtime.get("script_version"),
            "python_version": runtime.get("python_version"),
            "hostname": runtime.get("hostname"),
        },
        "window": {
            "current": progress.get("current_window") or progress.get("active_window") or checkpoint.get("active_window"),
            "page": progress.get("current_page"),
            "pending": progress.get("pending_windows") if progress.get("pending_windows") is not None else len(checkpoint.get("pending_windows") or []),
            "processed": progress.get("processed_windows"),
        },
        "counters": {
            "retrieved_records": progress.get("retrieved_records") or summary.get("retrieved_records") or 0,
            "pages_retrieved": progress.get("pages_retrieved") or summary.get("pages_retrieved") or 0,
            "created_shards": progress.get("created_shards") or summary.get("created_shards") or 0,
            "split_windows": progress.get("split_windows") or summary.get("split_windows") or 0,
            "deferred_windows": progress.get("deferred_windows") or summary.get("deferred_windows") or 0,
            "duplicate_records_skipped": progress.get("duplicate_records_skipped") or summary.get("duplicate_records_skipped") or 0,
            "rate_limited_waits": progress.get("rate_limited_waits") or summary.get("rate_limited_waits") or 0,
            "wait_seconds": progress.get("wait_seconds") or summary.get("wait_seconds") or 0,
            "records_per_hour": progress.get("records_per_hour") or 0,
            "pages_per_hour": progress.get("pages_per_hour") or 0,
            "eta_seconds": progress.get("eta_seconds"),
            "eta_confidence": progress.get("eta_confidence"),
        },
        "log_tail": log_lines,
    }


def compact_retrieval_shards(
    entry: dict[str, Any],
    *,
    target_records_per_shard: int = DEFAULT_SHARD_RECORD_LIMIT,
) -> dict[str, Any]:
    if str(entry.get("state") or "").upper() != "SUCCESS":
        raise ValueError("Only completed retrievals can be compacted")
    target_records_per_shard = max(100, min(int(target_records_per_shard or DEFAULT_SHARD_RECORD_LIMIT), DEFAULT_SHARD_RECORD_LIMIT))
    retrieval_id = str(entry.get("retrieval_id") or "")
    requested_by = entry.get("requested_by") if isinstance(entry.get("requested_by"), dict) else {}
    user = db.session.get(User, int(requested_by.get("user_id") or 0))
    credential = db.session.get(ZenodoCredential, int(entry.get("credential_id") or 0))
    if user is None or credential is None:
        raise ValueError("Cannot compact retrieval without user and credential context")

    manifest = dict(entry.get("manifest") or {})
    if manifest.get("compacted_shards"):
        return {"created_compacted_shards": 0, "compacted_shards": manifest.get("compacted_shards") or [], "already_compacted": True}

    batch: list[dict[str, Any]] = []
    compacted: list[dict[str, Any]] = []
    source_count = 0

    def flush() -> None:
        nonlocal batch
        if not batch:
            return
        shard_index = len(compacted) + 1
        shard = write_retrieval_shard(
            retrieval_id=retrieval_id,
            shard_index=shard_index,
            records=batch,
            environment=str(entry.get("environment") or "production"),
            requested_by=user,
            credential=credential,
            window={"status": "mixed", "start": None, "end": None, "artifact_granularity": "post_completion_compaction"},
            manifest_summary={
                "retrieval_id": retrieval_id,
                "shard_index": shard_index,
                "record_count": len(batch),
                "sync_mode": (entry.get("options") or {}).get("sync_mode") or "full",
                "parent_retrieval_id": (entry.get("options") or {}).get("parent_retrieval_id"),
                "derived_from": "post_completion_compaction",
            },
        )
        shard["artifact_kind"] = "zenodo_retrieval_compacted_shard"
        compacted.append(shard)
        batch = []

    for record in iter_retrieval_records(entry, include_compacted=False):
        metadata = dict(record.get("metadata") or {})
        metadata.pop("webhdp_retrieval", None)
        if str(record.get("status") or "").lower() == "draft":
            metadata.setdefault("state", "inprogress")
        else:
            metadata.setdefault("state", "done")
        batch.append(metadata)
        source_count += 1
        if len(batch) >= target_records_per_shard:
            flush()
    flush()

    manifest["compacted_shards"] = compacted
    manifest["compaction"] = {
        "created_at": _utc_now_iso(),
        "source_record_count": source_count,
        "target_records_per_shard": target_records_per_shard,
        "compacted_shard_count": len(compacted),
    }
    update_retrieval_entry(retrieval_id, manifest=manifest, status=str(entry.get("status") or "completed"))
    return {"created_compacted_shards": len(compacted), "compacted_shards": compacted, "source_record_count": source_count}


def export_retrieval_manifest(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "retrieval_id": entry.get("retrieval_id"),
        "state": entry.get("state"),
        "status": entry.get("status"),
        "environment": entry.get("environment"),
        "options": entry.get("options") or {},
        "summary": entry.get("summary") or {},
        "collection": entry.get("collection") or {},
        "manifest": entry.get("manifest") or {},
    }


def export_retrieval_records_csv(entry: dict[str, Any]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "retrieval_id",
            "session_id",
            "shard_index",
            "zenodo_record_id",
            "title",
            "status",
            "doi",
            "concept_rec_id",
            "created",
            "modified",
            "had_edit_rights",
            "had_version_rights",
        ],
    )
    writer.writeheader()
    for record in iter_retrieval_records(entry, include_compacted=False):
        writer.writerow(
            {
                "retrieval_id": entry.get("retrieval_id"),
                "session_id": record.get("session_id"),
                "shard_index": record.get("shard_index"),
                "zenodo_record_id": record.get("zenodo_record_id"),
                "title": record.get("title"),
                "status": record.get("status"),
                "doi": record.get("doi"),
                "concept_rec_id": record.get("concept_rec_id"),
                "created": record.get("created"),
                "modified": record.get("modified"),
                "had_edit_rights": bool(record.get("capabilities", {}).get("had_edit_rights")),
                "had_version_rights": bool(record.get("capabilities", {}).get("had_version_rights")),
            }
        )
    return output.getvalue()


def build_retrieval_shard_archive(entry: dict[str, Any], destination_path: str) -> dict[str, Any]:
    manifest = entry.get("manifest") if isinstance(entry.get("manifest"), dict) else {}
    shard_count = 0
    with zipfile.ZipFile(destination_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(export_retrieval_manifest(entry), indent=2, sort_keys=True))
        archive.writestr("records.csv", export_retrieval_records_csv(entry))
        for shard in manifest.get("shards") or []:
            if not isinstance(shard, dict) or not shard.get("hdpc_path"):
                continue
            hdpc_path = str(shard.get("hdpc_path"))
            if not os.path.exists(hdpc_path):
                continue
            shard_count += 1
            archive.write(hdpc_path, f"shards/shard_{int(shard.get('shard_index') or shard_count):05d}.hdpc")
    return {"archive_path": destination_path, "shard_count": shard_count}


def delete_compacted_retrieval_shards(entry: dict[str, Any]) -> dict[str, Any]:
    manifest = dict(entry.get("manifest") or {})
    deleted_sessions = 0
    deleted_files = 0
    for shard in manifest.get("compacted_shards") or []:
        if not isinstance(shard, dict):
            continue
        session = db.session.get(DBSession, _to_int(shard.get("session_id"), 0))
        if session is None:
            continue
        session_dir = Path(session.session_dir)
        db.session.delete(session)
        deleted_sessions += 1
        if session_dir.is_dir():
            shutil.rmtree(session_dir, ignore_errors=True)
            deleted_files += 1
    manifest["compacted_shards"] = []
    manifest.pop("compaction", None)
    update_retrieval_entry(str(entry.get("retrieval_id") or ""), manifest=manifest)
    db.session.commit()
    return {"deleted_compacted_sessions": deleted_sessions, "deleted_compacted_directories": deleted_files}
