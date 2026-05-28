from __future__ import annotations

from typing import Iterable


CANONICAL_SESSION_STATES = ("queued", "scanned", "submitting", "completed", "failed")
CANONICAL_SOURCE_FILE_STATES = ("queued", "registered", "missing", "selected", "processed", "failed")
DOWNLOADABLE_SESSION_STATES = {"scanned", "submitting", "completed"}
TERMINAL_SESSION_STATES = {"completed", "failed"}
SUBMISSION_WORKFLOW_PHASES = {"submit", "processing"}
RUNNING_UPLOAD_STAGES = {
    "queued",
    "initializing",
    "preparing_files",
    "analyzing_msf",
    "initializing_project",
    "registering_files",
    "coordinator",
    "processing",
    "processing_files",
    "uploading",
}

_SESSION_STATE_ALIASES = {
    "pending": "queued",
    "queued": "queued",
    "ready": "scanned",
    "active": "scanned",
    "scanned": "scanned",
    "submitting": "submitting",
    "processing": "queued",
    "completed": "completed",
    "failed": "failed",
}

_SOURCE_UPLOAD_STATE_ALIASES = {
    "pending": "queued",
    "queued": "queued",
    "processing": "queued",
    "uploaded": "registered",
    "ready": "registered",
    "registered": "registered",
    "selected": "selected",
    "processed": "processed",
    "completed": "processed",
    "failed": "missing",
    "missing": "missing",
}

_SOURCE_VALIDATION_STATE_ALIASES = {
    "pending": "queued",
    "queued": "queued",
    "processing": "queued",
    "scanned": "registered",
    "uploaded": "registered",
    "ready": "registered",
    "registered": "registered",
    "selected": "selected",
    "processed": "processed",
    "completed": "processed",
    "error": "failed",
    "invalid": "failed",
    "failed": "failed",
    "missing": "failed",
    "problems": "failed",
    "conflict": "failed",
}


def _normalize_text(value) -> str:
    return str(value or "").strip().lower()


def normalize_session_state(
    raw_status,
    *,
    workflow_phase=None,
    upload_stage=None,
) -> str:
    status = _normalize_text(raw_status)
    phase = _normalize_text(workflow_phase)
    stage = _normalize_text(upload_stage)

    if phase == "failed" or stage == "failed" or status == "failed":
        return "failed"
    if phase == "completed" or status == "completed":
        return "completed"
    if phase in SUBMISSION_WORKFLOW_PHASES or status == "submitting":
        return "submitting"
    if stage == "completed":
        return "scanned"
    if status in {"ready", "active", "scanned"}:
        return "scanned"
    if status in {"pending", "queued"}:
        return "queued"
    if status == "processing":
        return "queued"
    if stage in RUNNING_UPLOAD_STAGES or stage == "awaiting_scan_start":
        return "queued"
    return _SESSION_STATE_ALIASES.get(status, "queued")


def normalize_source_upload_state(raw_status) -> str:
    status = _normalize_text(raw_status)
    return _SOURCE_UPLOAD_STATE_ALIASES.get(status, "queued" if not status else status)


def normalize_source_validation_state(raw_status) -> str:
    status = _normalize_text(raw_status)
    return _SOURCE_VALIDATION_STATE_ALIASES.get(status, "queued" if not status else status)


def is_downloadable_session_state(value, *, workflow_phase=None, upload_stage=None) -> bool:
    state = normalize_session_state(value, workflow_phase=workflow_phase, upload_stage=upload_stage)
    return state in DOWNLOADABLE_SESSION_STATES


def normalize_upload_file_counts(raw_counts: dict[str, int] | None) -> dict[str, int]:
    counts = raw_counts or {}
    normalized = {state: 0 for state in ("queued", "registered", "missing")}
    for raw_status, raw_count in counts.items():
        state = normalize_source_upload_state(raw_status)
        if state == "selected":
            state = "registered"
        elif state == "processed":
            state = "registered"
        elif state == "failed":
            state = "missing"
        if state not in normalized:
            continue
        normalized[state] += int(raw_count or 0)
    normalized["total"] = normalized["queued"] + normalized["registered"] + normalized["missing"]
    return normalized


def any_session_state(values: Iterable[str | None]) -> str | None:
    for value in values:
        state = _normalize_text(value)
        if state:
            return state
    return None
