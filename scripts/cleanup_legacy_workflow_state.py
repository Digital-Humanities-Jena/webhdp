#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from constants import UPLOAD_PROGRESS_FIELD, WORKFLOW_STATE_FIELD
from database.database import db
from database.models import Session as DBSession, UserMetadata
from services.hdpc_local_service import (
    DEFAULT_RECORD_ORIGIN,
    LEGACY_PLACEHOLDER_RECORD_ORIGIN,
    classify_hdpc_record_inventory,
    inspect_hdpc_project,
)
from services.hdpc_schema_service import connect_hdpc, ensure_hdpc_schema, table_columns
from workflow_status import normalize_session_state


@dataclass
class SessionCleanupPlan:
    session_id: int
    original_status: str
    normalized_status: str
    status_changed: bool
    hdpc_path: str | None
    hidden_duplicate_records: int
    hidden_legacy_placeholder_records: int
    placeholder_record_ids: list[int]


def _parse_json(raw_value: Any, fallback: Any) -> Any:
    if raw_value in (None, ""):
        return fallback
    if isinstance(raw_value, (dict, list)):
        return raw_value
    try:
        return json.loads(raw_value)
    except (TypeError, ValueError):
        return fallback


def build_session_metadata_map(session_ids: list[int]) -> dict[int, dict[str, str]]:
    if not session_ids:
        return {}
    rows = (
        db.session.query(UserMetadata)
        .filter(UserMetadata.session_id.in_(session_ids))
        .filter(UserMetadata.field_name.in_([WORKFLOW_STATE_FIELD, UPLOAD_PROGRESS_FIELD]))
        .all()
    )
    metadata_map: dict[int, dict[str, str]] = {}
    for row in rows:
        metadata_map.setdefault(int(row.session_id), {})[str(row.field_name)] = row.field_value or ""
    return metadata_map


def plan_session_status_update(session_row: DBSession, metadata_fields: dict[str, str]) -> tuple[str, bool]:
    workflow_state = _parse_json(metadata_fields.get(WORKFLOW_STATE_FIELD), {})
    upload_progress = _parse_json(metadata_fields.get(UPLOAD_PROGRESS_FIELD), {})
    normalized_status = normalize_session_state(
        getattr(session_row, "status", None),
        workflow_phase=workflow_state.get("phase") if isinstance(workflow_state, dict) else None,
        upload_stage=upload_progress.get("current_stage") if isinstance(upload_progress, dict) else None,
    )
    original_status = str(getattr(session_row, "status", "") or "").strip()
    return normalized_status, normalized_status != original_status


def inspect_hidden_placeholder_records(hdpc_path: str | None) -> dict[str, Any]:
    candidate_path = str(hdpc_path or "").strip()
    if not candidate_path or not Path(candidate_path).exists():
        return {
            "hidden_duplicate_records": 0,
            "hidden_legacy_placeholder_records": 0,
            "placeholder_record_ids": [],
        }

    inspect_data = inspect_hdpc_project(candidate_path, show_files=False)
    inventory = classify_hdpc_record_inventory(inspect_data.get("zenodo_records") or [])
    hidden_records = inventory.get("hidden_records") or []
    placeholder_record_ids = sorted(
        {
            int(record.get("local_record_id") or record.get("record_id") or 0)
            for record in hidden_records
            if str(record.get("legacy_cleanup_reason") or "").strip().lower() in {"superseded_placeholder", "duplicate_placeholder"}
            and int(record.get("local_record_id") or record.get("record_id") or 0) > 0
        }
    )
    summary = inventory.get("summary") or {}
    return {
        "hidden_duplicate_records": int(summary.get("hidden_duplicate_records") or 0),
        "hidden_legacy_placeholder_records": int(summary.get("hidden_legacy_placeholder_records") or 0),
        "placeholder_record_ids": placeholder_record_ids,
    }


def apply_hdpc_placeholder_cleanup(hdpc_path: str, placeholder_record_ids: list[int]) -> int:
    normalized_ids = sorted({int(record_id) for record_id in placeholder_record_ids if int(record_id) > 0})
    if not normalized_ids:
        return 0

    conn = connect_hdpc(hdpc_path, timeout=30)
    try:
        ensure_hdpc_schema(conn, hdpc_path)
        cursor = conn.cursor()
        columns = table_columns(cursor, "zenodo_records")
        if "record_origin" not in columns:
            return 0
        cursor.execute(
            "UPDATE zenodo_records SET record_origin = ? WHERE record_origin IS NULL OR TRIM(record_origin) = ''",
            (DEFAULT_RECORD_ORIGIN,),
        )
        cursor.execute(
            "UPDATE zenodo_records SET record_origin = ? WHERE record_id IN ({placeholders})".format(
                placeholders=",".join("?" for _ in normalized_ids)
            ),
            (LEGACY_PLACEHOLDER_RECORD_ORIGIN, *normalized_ids),
        )
        conn.commit()
        return int(cursor.rowcount or 0)
    finally:
        conn.close()


def build_cleanup_plan(session_rows: list[DBSession]) -> list[SessionCleanupPlan]:
    metadata_map = build_session_metadata_map([int(session.id) for session in session_rows])
    plans: list[SessionCleanupPlan] = []
    for session_row in session_rows:
        metadata_fields = metadata_map.get(int(session_row.id), {})
        normalized_status, status_changed = plan_session_status_update(session_row, metadata_fields)
        cleanup = inspect_hidden_placeholder_records(getattr(session_row, "hdpc_path", None))
        plans.append(
            SessionCleanupPlan(
                session_id=int(session_row.id),
                original_status=str(getattr(session_row, "status", "") or ""),
                normalized_status=normalized_status,
                status_changed=status_changed,
                hdpc_path=getattr(session_row, "hdpc_path", None),
                hidden_duplicate_records=int(cleanup["hidden_duplicate_records"]),
                hidden_legacy_placeholder_records=int(cleanup["hidden_legacy_placeholder_records"]),
                placeholder_record_ids=list(cleanup["placeholder_record_ids"]),
            )
        )
    return plans


def run_cleanup(*, apply_changes: bool = False, session_ids: list[int] | None = None) -> dict[str, Any]:
    query = db.session.query(DBSession).order_by(DBSession.id.asc())
    if session_ids:
        query = query.filter(DBSession.id.in_(session_ids))
    sessions = query.all()
    plans = build_cleanup_plan(sessions)

    status_updates = 0
    placeholder_origin_updates = 0
    if apply_changes:
        for session_row, plan in zip(sessions, plans, strict=False):
            if plan.status_changed:
                session_row.status = plan.normalized_status
                status_updates += 1
            if plan.placeholder_record_ids and plan.hdpc_path:
                placeholder_origin_updates += apply_hdpc_placeholder_cleanup(plan.hdpc_path, plan.placeholder_record_ids)
        db.session.commit()

    return {
        "apply_changes": bool(apply_changes),
        "session_count": len(plans),
        "status_updates": status_updates,
        "placeholder_origin_updates": placeholder_origin_updates,
        "hidden_duplicate_records": sum(plan.hidden_duplicate_records for plan in plans),
        "hidden_legacy_placeholder_records": sum(plan.hidden_legacy_placeholder_records for plan in plans),
        "sessions": [asdict(plan) for plan in plans],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize legacy workflow session state and hide legacy placeholder records.")
    parser.add_argument("--apply", action="store_true", help="Apply the proposed cleanup instead of printing a dry-run report.")
    parser.add_argument("--session-id", action="append", type=int, dest="session_ids", help="Limit cleanup to one or more session IDs.")
    return parser.parse_args()


def _load_app():
    from app import app

    return app


def main() -> int:
    args = parse_args()
    app = _load_app()
    with app.app_context():
        payload = run_cleanup(apply_changes=bool(args.apply), session_ids=args.session_ids or None)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
