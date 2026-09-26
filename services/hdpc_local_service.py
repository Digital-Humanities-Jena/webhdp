import hashlib
from services.pipeline_execution_lock import serialize_project_mutation

import json
import mimetypes
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.hdpc_schema_service import connect_hdpc, ensure_hdpc_schema, table_columns, table_exists

CANONICAL_RECORD_ORIGINS = frozenset({"submit_pipeline", "versioning", "zenodo_retrieval"})
DEFAULT_RECORD_ORIGIN = "submit_pipeline"
VERSIONING_RECORD_ORIGIN = "versioning"
ZENODO_RETRIEVAL_RECORD_ORIGIN = "zenodo_retrieval"
MANUAL_RECORD_ORIGIN = "manual_api"
LEGACY_PLACEHOLDER_RECORD_ORIGIN = "legacy_placeholder"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _guess_mime_type(path: str) -> str | None:
    guessed, _ = mimetypes.guess_type(path)
    return guessed or None


def _json_loads(raw_value: Any, fallback: Any) -> Any:
    if raw_value in (None, ""):
        return fallback
    if isinstance(raw_value, (dict, list)):
        return raw_value
    try:
        return json.loads(raw_value)
    except (TypeError, ValueError):
        return fallback


def _validation_error_message(validation_report: dict[str, Any] | None) -> str | None:
    if not isinstance(validation_report, dict):
        return None
    errors = validation_report.get("errors")
    if isinstance(errors, list) and errors:
        return "; ".join(str(item) for item in errors[:3] if str(item).strip()) or None
    if validation_report.get("valid") is False:
        return "Validation failed"
    return None


def _normalize_payload(metadata: dict[str, Any]) -> dict[str, Any]:
    if "metadata" in metadata and isinstance(metadata.get("metadata"), dict):
        return dict(metadata)
    return {"metadata": dict(metadata)}


def _table_exists(cursor: sqlite3.Cursor, table_name: str) -> bool:
    return table_exists(cursor, table_name)


def _table_columns(cursor: sqlite3.Cursor, table_name: str) -> set[str]:
    return table_columns(cursor, table_name)


def _ensure_local_project_schema(conn: sqlite3.Connection, hdpc_path: str) -> int:
    return ensure_hdpc_schema(conn, hdpc_path)


def normalize_hdpc_record_origin(value: Any) -> str | None:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return normalized or None


def is_canonical_hdpc_record(record_like: dict[str, Any] | None) -> bool:
    origin = normalize_hdpc_record_origin((record_like or {}).get("record_origin"))
    if not origin:
        return True
    return origin in CANONICAL_RECORD_ORIGINS


def _normalize_record_status_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_record_path_signature(value: Any) -> str | None:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return None
    return f"path:{text.lower()}"


def _normalize_record_name_signature(value: Any) -> str | None:
    text = os.path.basename(str(value or "").strip())
    if not text:
        return None
    return f"name:{text.lower()}"


def _record_identity_candidates(record: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: str | None) -> None:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        candidates.append(normalized)

    source_file_id = record.get("source_file_id")
    if source_file_id is not None and str(source_file_id).strip():
        add(f"source_id:{int(source_file_id)}")

    for key in (
        "_signature_group_key",
        "source_file_path",
        "source_relative_path",
        "relative_path",
        "absolute_path",
        "mapped_file_path",
    ):
        add(_normalize_record_path_signature(record.get(key)))

    for key in ("source_file_name", "filename", "name"):
        add(_normalize_record_name_signature(record.get(key)))

    file_items = record.get("record_files") or record.get("files") or []
    if isinstance(file_items, list):
        for item in file_items:
            if not isinstance(item, dict):
                continue
            add(_normalize_record_path_signature(item.get("absolute_path")))
            add(_normalize_record_path_signature(item.get("mapped_file_path")))
            add(_normalize_record_path_signature(item.get("relative_path")))
            add(_normalize_record_name_signature(item.get("filename")))

    return candidates


def _record_visibility_priority(record: dict[str, Any]) -> tuple[int, float, int]:
    status = _normalize_record_status_text(record.get("record_status"))
    status_priority = {
        "published": 500,
        "draft": 400,
        "prepared": 300,
        "preparation_failed": 200,
        "discarded": 100,
    }.get(status, 0)
    timestamp_value = (
        str(record.get("updated_at") or "").strip()
        or str(record.get("last_updated_timestamp") or "").strip()
        or str(record.get("created_at") or "").strip()
        or str(record.get("created_timestamp") or "").strip()
    )
    try:
        normalized_timestamp = datetime.fromisoformat(timestamp_value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        normalized_timestamp = 0.0
    record_id = int(record.get("local_record_id") or record.get("record_id") or 0)
    return status_priority, normalized_timestamp, record_id


def classify_hdpc_record_inventory(records: list[dict[str, Any]]) -> dict[str, Any]:
    visible_records: list[dict[str, Any]] = []
    hidden_records: list[dict[str, Any]] = []
    grouped_records: dict[str, list[dict[str, Any]]] = {}
    hidden_noncanonical_records = 0
    hidden_legacy_placeholder_records = 0

    for record in records or []:
        copied = dict(record)
        origin = normalize_hdpc_record_origin(copied.get("record_origin"))
        copied["record_origin"] = origin
        copied["canonical_submit_flow"] = is_canonical_hdpc_record({"record_origin": origin})
        if not copied["canonical_submit_flow"]:
            copied["legacy_cleanup_reason"] = "noncanonical_origin"
            hidden_records.append(copied)
            hidden_noncanonical_records += 1
            continue

        identity_candidates = _record_identity_candidates(copied)
        dedupe_key = (
            next((item for item in identity_candidates if item.startswith("source_id:")), None)
            or next((item for item in identity_candidates if item.startswith("path:")), None)
            or next((item for item in identity_candidates if item.startswith("name:")), None)
            or f"record:{int(copied.get('local_record_id') or copied.get('record_id') or 0)}"
        )
        grouped_records.setdefault(dedupe_key, []).append(copied)

    hidden_duplicate_records = 0
    for grouped_items in grouped_records.values():
        version_records = [
            record
            for record in grouped_items
            if _normalize_record_status_text(record.get("record_status")) in {"draft", "published"}
        ]
        if version_records:
            version_records.sort(key=_record_visibility_priority, reverse=True)
            visible_records.extend(version_records)
            for record in grouped_items:
                if record in version_records:
                    continue
                record["legacy_cleanup_reason"] = "superseded_placeholder"
                hidden_records.append(record)
                hidden_duplicate_records += 1
                if _normalize_record_status_text(record.get("record_status")) in {"prepared", "preparation_failed", "discarded"}:
                    hidden_legacy_placeholder_records += 1
            continue

        best_record = max(grouped_items, key=_record_visibility_priority)
        visible_records.append(best_record)
        for record in grouped_items:
            if record is best_record:
                continue
            record["legacy_cleanup_reason"] = "duplicate_placeholder"
            hidden_records.append(record)
            hidden_duplicate_records += 1
            if _normalize_record_status_text(record.get("record_status")) in {"prepared", "preparation_failed", "discarded"}:
                hidden_legacy_placeholder_records += 1

    visible_records.sort(
        key=lambda record: int(record.get("local_record_id") or record.get("record_id") or 0)
    )
    hidden_records.sort(
        key=lambda record: int(record.get("local_record_id") or record.get("record_id") or 0)
    )
    return {
        "visible_records": visible_records,
        "hidden_records": hidden_records,
        "summary": {
            "hidden_duplicate_records": hidden_duplicate_records,
            "hidden_noncanonical_records": hidden_noncanonical_records,
            "hidden_legacy_placeholder_records": hidden_legacy_placeholder_records,
        },
    }


def _upsert_project_config(
    cursor: sqlite3.Cursor,
    project_id: int,
    key: str,
    value: Any,
    description: str | None = None,
) -> None:
    serialized = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
    cursor.execute(
        """
        INSERT INTO project_configuration (project_id, config_key, config_value, description)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(project_id, config_key)
        DO UPDATE SET config_value = excluded.config_value, description = excluded.description
        """,
        (project_id, key, serialized, description),
    )


def _get_or_create_source_file(
    cursor: sqlite3.Cursor,
    *,
    project_id: int,
    absolute_path: str,
    pipeline_source: str | None = None,
    step_source: str | None = None,
    file_type: str = "source",
    status: str = "pending",
) -> int:
    normalized_path = os.path.normpath(absolute_path)
    row = cursor.execute(
        "SELECT file_id FROM source_files WHERE absolute_path = ? LIMIT 1",
        (normalized_path,),
    ).fetchone()
    if row:
        updates = []
        params: list[Any] = []
        if pipeline_source is not None and "pipeline_source" in _table_columns(cursor, "source_files"):
            updates.append("pipeline_source = ?")
            params.append(pipeline_source)
        if step_source is not None and "step_source" in _table_columns(cursor, "source_files"):
            updates.append("step_source = ?")
            params.append(step_source)
        if updates:
            params.append(int(row[0]))
            cursor.execute(f"UPDATE source_files SET {', '.join(updates)} WHERE file_id = ?", params)
        return int(row[0])

    file_path = Path(normalized_path)
    cursor.execute(
        """
        INSERT INTO source_files (
            project_id,
            absolute_path,
            relative_path,
            filename,
            size_bytes,
            sha256_hash,
            mime_type,
            file_type,
            status,
            added_timestamp,
            pipeline_source,
            step_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id,
            normalized_path,
            file_path.name,
            file_path.name,
            file_path.stat().st_size,
            _file_sha256(normalized_path),
            _guess_mime_type(normalized_path),
            file_type,
            status,
            _utc_now_iso(),
            pipeline_source,
            step_source,
        ),
    )
    return int(cursor.lastrowid)


def _infer_input_dir(source_rows: list[sqlite3.Row]) -> str | None:
    directories = [
        os.path.dirname(str(row["absolute_path"]).strip())
        for row in source_rows
        if str(row["absolute_path"] or "").strip()
    ]
    directories = [path for path in directories if path]
    if not directories:
        return None
    if len(directories) == 1:
        return directories[0]
    try:
        return os.path.commonpath(directories)
    except ValueError:
        return directories[0]


def _read_project_info(cursor: sqlite3.Cursor) -> dict[str, Any] | None:
    if not _table_exists(cursor, "project_info"):
        return None
    row = cursor.execute(
        """
        SELECT
            project_id,
            project_name,
            project_short_code,
            description,
            creation_timestamp,
            last_modified_timestamp,
            hdpc_schema_version
        FROM project_info
        ORDER BY project_id ASC
        LIMIT 1
        """
    ).fetchone()
    return dict(row) if row is not None else None


def _read_source_rows(cursor: sqlite3.Cursor) -> list[sqlite3.Row]:
    if not _table_exists(cursor, "source_files"):
        return []
    source_file_columns = _table_columns(cursor, "source_files")
    select_columns = ["file_id"]
    optional_columns = {
        "filename": "filename",
        "absolute_path": "absolute_path",
        "relative_path": "relative_path",
        "file_type": "file_type",
        "status": "status",
        "size_bytes": "size_bytes",
        "mime_type": "mime_type",
        "pipeline_source": "pipeline_source",
        "step_source": "step_source",
        "added_timestamp": "added_timestamp",
        "last_processed_timestamp": "last_processed_timestamp",
        "sha256_hash": "sha256_hash",
        "parent_file_id": "parent_file_id",
        "error_message": "error_message",
        "validation_report_json": "validation_report_json",
        "is_primary_source": "is_primary_source",
    }
    for alias, column_name in optional_columns.items():
        if column_name in source_file_columns:
            select_columns.append(column_name)
        elif alias == "is_primary_source":
            select_columns.append("0 AS is_primary_source")
        else:
            select_columns.append(f"NULL AS {alias}")
    return cursor.execute(
        f"SELECT {', '.join(select_columns)} FROM source_files ORDER BY file_id ASC"
    ).fetchall()


def _read_configuration(cursor: sqlite3.Cursor, source_rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    configuration: list[dict[str, Any]] = []
    if _table_exists(cursor, "project_configuration"):
        config_rows = cursor.execute(
            "SELECT config_key, config_value, description FROM project_configuration ORDER BY config_key ASC"
        ).fetchall()
        configuration = [dict(row) for row in config_rows]
    if _table_exists(cursor, "configuration"):
        config_rows = cursor.execute("SELECT config_key, config_value FROM configuration").fetchall()
        existing_keys = {str(item.get("config_key") or "").strip() for item in configuration}
        for row in config_rows:
            payload = dict(row)
            if str(payload.get("config_key") or "").strip() in existing_keys:
                continue
            configuration.append(payload)

    config_keys = {str(item.get("config_key") or "").strip() for item in configuration}
    inferred_input_dir = _infer_input_dir(source_rows)
    if inferred_input_dir and "paths.data_in" not in config_keys:
        configuration.append({"config_key": "paths.data_in", "config_value": inferred_input_dir})
    return configuration


def _read_file_scan_settings(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    if not _table_exists(cursor, "file_scan_settings"):
        return []
    rows = cursor.execute(
        """
        SELECT scan_settings_id, project_id, modality, scan_options
        FROM file_scan_settings
        ORDER BY modality ASC, scan_settings_id ASC
        """
    ).fetchall()
    settings: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        payload["scan_options"] = _json_loads(payload.get("scan_options"), {})
        settings.append(payload)
    return settings


def _build_file_tree(source_rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    file_tree: list[dict[str, Any]] = []
    nodes_by_id: dict[int, dict[str, Any]] = {}
    parent_by_id: dict[int, int | None] = {}
    for row in source_rows:
        file_id = int(row["file_id"])
        parent_id = int(row["parent_file_id"]) if row["parent_file_id"] is not None else None
        node = {
            "file_id": file_id,
            "filename": row["filename"],
            "relative_path": row["relative_path"],
            "absolute_path": row["absolute_path"],
            "file_type": row["file_type"],
            "status": row["status"],
            "size_bytes": row["size_bytes"],
            "mime_type": row["mime_type"],
            "parent_file_id": parent_id,
            "error_message": row["error_message"],
            "validation_report_json": _json_loads(row["validation_report_json"], {}),
            "is_primary_source": bool(row["is_primary_source"]) if "is_primary_source" in row.keys() else False,
            "pipeline_source": row["pipeline_source"],
            "step_source": row["step_source"],
            "added_timestamp": row["added_timestamp"],
            "last_processed_timestamp": row["last_processed_timestamp"],
            "sha256_hash": row["sha256_hash"],
            "children": [],
        }
        nodes_by_id[file_id] = node
        parent_by_id[file_id] = parent_id

    for file_id, node in nodes_by_id.items():
        parent_id = parent_by_id.get(file_id)
        if parent_id is not None and parent_id in nodes_by_id:
            nodes_by_id[parent_id]["children"].append(node)
        else:
            file_tree.append(node)

    for node in nodes_by_id.values():
        node["children"].sort(key=lambda item: (str(item.get("filename") or "").lower(), int(item.get("file_id") or 0)))
    file_tree.sort(key=lambda item: (str(item.get("filename") or "").lower(), int(item.get("file_id") or 0)))
    return file_tree


def _normalize_record_status(raw_status: Any, metadata_payload: dict[str, Any]) -> str:
    normalized = str(raw_status or "").strip().lower()
    if normalized in {"prepared", "draft", "published", "failed"}:
        return normalized
    links = metadata_payload.get("links") if isinstance(metadata_payload.get("links"), dict) else {}
    if metadata_payload.get("doi") and links.get("html"):
        return "published"
    if metadata_payload.get("id"):
        return "draft"
    return normalized or "unknown"


def _extract_record_doi(row_dict: dict[str, Any], metadata_payload: dict[str, Any]) -> str:
    metadata_core = metadata_payload.get("metadata") if isinstance(metadata_payload.get("metadata"), dict) else {}
    prereserve = metadata_core.get("prereserve_doi") if isinstance(metadata_core.get("prereserve_doi"), dict) else {}
    return str(
        row_dict.get("zenodo_doi")
        or metadata_payload.get("doi")
        or metadata_core.get("doi")
        or prereserve.get("doi")
        or ""
    ).strip()


def _normalize_record_version(row_dict: dict[str, Any], metadata_payload: dict[str, Any]) -> str | None:
    metadata_core = metadata_payload.get("metadata") if isinstance(metadata_payload.get("metadata"), dict) else {}
    candidate = row_dict.get("version")
    if candidate in (None, ""):
        candidate = metadata_core.get("version")
    text = str(candidate or "").strip()
    return text or None


def _normalize_version_rank_value(raw_value: Any, version_label: str | None) -> int:
    if raw_value not in (None, ""):
        try:
            normalized = int(raw_value)
            if normalized > 0:
                return normalized
        except (TypeError, ValueError):
            pass
    version_parts = _version_sort_key(version_label)
    if version_parts:
        return max(version_parts[-1], 1)
    return 1


def _read_record_links(cursor: sqlite3.Cursor) -> dict[int, dict[str, str]]:
    if not _table_exists(cursor, "zenodo_record_links"):
        return {}
    record_links: dict[int, dict[str, str]] = {}
    rows = cursor.execute(
        """
        SELECT record_id, link_rel, link_url
        FROM zenodo_record_links
        ORDER BY record_id ASC, link_rel ASC
        """
    ).fetchall()
    for row in rows:
        record_id = int(row["record_id"])
        rel = str(row["link_rel"] or "").strip()
        url = str(row["link_url"] or "").strip()
        if not rel or not url:
            continue
        record_links.setdefault(record_id, {})[rel] = url
    return record_links


def _read_record_file_maps(
    cursor: sqlite3.Cursor,
    *,
    source_rows_by_id: dict[int, dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    if not _table_exists(cursor, "record_files_map"):
        return {}
    rfm_columns = _table_columns(cursor, "record_files_map")
    select_columns = [
        "record_id",
        "file_id",
        "file_path",
        "file_purpose",
        "upload_status",
        "upload_timestamp",
    ]
    optional_columns = [
        "zenodo_file_id",
        "zenodo_file_key",
        "zenodo_file_checksum",
        "zenodo_file_size",
        "zenodo_file_links_json",
        "upload_error",
        "upload_response_json",
    ]
    for column_name in optional_columns:
        if column_name in rfm_columns:
            select_columns.append(column_name)
        else:
            select_columns.append(f"NULL AS {column_name}")

    files_by_record: dict[int, list[dict[str, Any]]] = {}
    order_field = "map_id" if "map_id" in rfm_columns else "file_id"
    rows = cursor.execute(
        f"SELECT {', '.join(select_columns)} FROM record_files_map WHERE upload_status != 'disabled' ORDER BY record_id ASC, {order_field} ASC"
    ).fetchall()
    for row in rows:
        payload = dict(row)
        file_id = int(payload["file_id"]) if payload.get("file_id") is not None else None
        source_file = source_rows_by_id.get(file_id or -1, {})
        payload["file_links"] = _json_loads(payload.get("zenodo_file_links_json"), {})
        payload["upload_response"] = _json_loads(payload.get("upload_response_json"), {})
        payload["source_file"] = source_file
        payload["filename"] = source_file.get("filename")
        payload["relative_path"] = source_file.get("relative_path")
        payload["absolute_path"] = source_file.get("absolute_path")
        files_by_record.setdefault(int(payload["record_id"]), []).append(payload)
    return files_by_record


def _read_zenodo_records(
    cursor: sqlite3.Cursor,
    source_rows: list[sqlite3.Row],
    *,
    canonical_only: bool = False,
) -> list[dict[str, Any]]:
    if not _table_exists(cursor, "zenodo_records"):
        return []
    source_rows_by_id = {int(row["file_id"]): dict(row) for row in source_rows}
    record_links = _read_record_links(cursor)
    record_files = _read_record_file_maps(cursor, source_rows_by_id=source_rows_by_id)

    rows = cursor.execute("SELECT * FROM zenodo_records ORDER BY record_id ASC").fetchall()
    records: list[dict[str, Any]] = []
    for row in rows:
        row_dict = dict(row)
        record_origin = normalize_hdpc_record_origin(row_dict.get("record_origin"))
        if canonical_only and not is_canonical_hdpc_record({"record_origin": record_origin}):
            continue
        metadata_payload = _json_loads(row_dict.get("record_metadata_json"), {})
        metadata_payload = metadata_payload if isinstance(metadata_payload, dict) else {}
        links = dict(record_links.get(int(row_dict["record_id"]), {}))
        metadata_links = metadata_payload.get("links") if isinstance(metadata_payload.get("links"), dict) else {}
        for rel, url in metadata_links.items():
            if rel and url and rel not in links:
                links[str(rel)] = str(url)
        source_file_id = row_dict.get("source_file_id")
        source_file = source_rows_by_id.get(int(source_file_id)) if source_file_id is not None else None
        status = _normalize_record_status(row_dict.get("record_status"), metadata_payload)
        file_items = record_files.get(int(row_dict["record_id"]), [])
        uploaded_file_count = sum(1 for item in file_items if str(item.get("upload_status") or "").lower() == "uploaded")
        doi = _extract_record_doi(row_dict, metadata_payload)
        version_label = _normalize_record_version(row_dict, metadata_payload)
        record = {
            "record_id": int(row_dict["record_id"]),
            "local_record_id": int(row_dict["record_id"]),
            "source_file_id": int(source_file_id) if source_file_id is not None else None,
            "record_title": row_dict.get("record_title"),
            "record_status": status,
            "record_metadata": metadata_payload,
            "metadata": metadata_payload,
            "creation_api_response": _json_loads(row_dict.get("creation_api_response"), {}),
            "last_publish_api_response": _json_loads(row_dict.get("last_publish_api_response"), {}),
            "zenodo_record_id": row_dict.get("zenodo_record_id") or metadata_payload.get("id"),
            "concept_rec_id": row_dict.get("concept_rec_id") or metadata_payload.get("conceptrecid"),
            "zenodo_doi": doi or None,
            "concept_doi": row_dict.get("concept_doi") or metadata_payload.get("conceptdoi"),
            "doi": doi or None,
            "is_sandbox": bool(row_dict.get("is_sandbox")) if row_dict.get("is_sandbox") is not None else False,
            "created_timestamp": row_dict.get("created_timestamp"),
            "last_updated_timestamp": row_dict.get("last_updated_timestamp"),
            "version": version_label,
            "version_rank": _normalize_version_rank_value(row_dict.get("version_rank"), version_label),
            "previous_record_id": (
                int(row_dict.get("previous_record_id"))
                if row_dict.get("previous_record_id") is not None
                else None
            ),
            "record_origin": record_origin,
            "canonical_submit_flow": is_canonical_hdpc_record({"record_origin": record_origin}),
            "last_api_error": row_dict.get("last_api_error"),
            "links": links,
            "record_url": links.get("html") or links.get("latest_html") or links.get("self"),
            "source_file_name": source_file.get("filename") if source_file else None,
            "source_file_path": source_file.get("absolute_path") if source_file else None,
            "source_relative_path": source_file.get("relative_path") if source_file else None,
            "record_files": file_items,
            "record_file_count": len(file_items),
            "uploaded_file_count": uploaded_file_count,
        }
        records.append(record)
    if canonical_only:
        return classify_hdpc_record_inventory(records).get("visible_records", [])
    return records


def _build_project_statistics(
    source_rows: list[sqlite3.Row],
    zenodo_records: list[dict[str, Any]],
) -> dict[str, Any]:
    file_type_counter = Counter(str(row["file_type"] or "unknown") for row in source_rows)
    file_status_counter = Counter(str(row["status"] or "unknown") for row in source_rows)
    record_status_counter = Counter(str(record.get("record_status") or "unknown") for record in zenodo_records)
    total_size_bytes = sum(int(row["size_bytes"] or 0) for row in source_rows if row["size_bytes"] is not None)
    return {
        "source_file_count": len(source_rows),
        "file_types": dict(file_type_counter),
        "file_statuses": dict(file_status_counter),
        "total_size_bytes": total_size_bytes,
        "record_count": len(zenodo_records),
        "record_statuses": dict(record_status_counter),
        "published_record_count": sum(1 for record in zenodo_records if record.get("record_status") == "published"),
        "draft_record_count": sum(1 for record in zenodo_records if record.get("record_status") == "draft"),
        "prepared_record_count": sum(1 for record in zenodo_records if record.get("record_status") == "prepared"),
    }


def _load_hdpc_snapshot(
    hdpc_path: str,
    *,
    include_configuration: bool = True,
    include_scan_settings: bool = True,
    include_file_tree: bool = False,
    canonical_records_only: bool = False,
) -> dict[str, Any]:
    conn = connect_hdpc(hdpc_path, readonly=True, timeout=30, row_factory=sqlite3.Row)
    try:
        cursor = conn.cursor()
        source_rows = _read_source_rows(cursor)
        records = _read_zenodo_records(cursor, source_rows, canonical_only=canonical_records_only)
        return {
            "project_info": _read_project_info(cursor),
            "configuration": _read_configuration(cursor, source_rows) if include_configuration else [],
            "file_scan_settings": _read_file_scan_settings(cursor) if include_scan_settings else [],
            "source_rows": source_rows,
            "source_rows_dicts": [dict(row) for row in source_rows],
            "source_rows_by_id": {int(row["file_id"]): dict(row) for row in source_rows},
            "zenodo_records": records,
            "published_records": [record for record in records if record.get("record_status") == "published"],
            "project_statistics": _build_project_statistics(source_rows, records),
            "file_tree": _build_file_tree(source_rows) if include_file_tree else [],
        }
    finally:
        conn.close()


def read_hdpc_project_info(hdpc_path: str) -> dict[str, Any] | None:
    return _load_hdpc_snapshot(
        hdpc_path,
        include_configuration=False,
        include_scan_settings=False,
    ).get("project_info")


def read_hdpc_project_stats(hdpc_path: str) -> dict[str, Any]:
    return _load_hdpc_snapshot(
        hdpc_path,
        include_configuration=False,
        include_scan_settings=False,
    )["project_statistics"]


def read_hdpc_zenodo_records(
    hdpc_path: str,
    *,
    statuses: set[str] | None = None,
    canonical_only: bool = False,
) -> list[dict[str, Any]]:
    records = _load_hdpc_snapshot(
        hdpc_path,
        include_configuration=False,
        include_scan_settings=False,
        canonical_records_only=canonical_only,
    )["zenodo_records"]
    if not statuses:
        return records
    normalized_statuses = {str(status).strip().lower() for status in statuses if str(status).strip()}
    return [record for record in records if str(record.get("record_status") or "").lower() in normalized_statuses]


def read_hdpc_published_records(hdpc_path: str, *, canonical_only: bool = False) -> list[dict[str, Any]]:
    return read_hdpc_zenodo_records(hdpc_path, statuses={"published"}, canonical_only=canonical_only)


def _is_recordable_source_row(row: dict[str, Any]) -> bool:
    if row.get("file_type") == "generated" or row.get("pipeline_source") == "lod_generation":
        return False
    if row.get("parent_file_id") is None:
        return True
    return bool(row.get("is_primary_source"))


def _upload_requires_retry(upload_status: Any) -> bool:
    normalized = str(upload_status or "").strip().lower()
    return normalized in {"pending", "pending_pipeline_upload", "removal_pending"} or "error" in normalized


def _version_sort_key(value: Any) -> tuple[int, ...]:
    text = str(value or "").strip()
    if not text:
        return tuple()
    parts: list[int] = []
    for raw_part in text.split("."):
        parts.append(int(raw_part) if raw_part.isdigit() else 0)
    return tuple(parts)


def _normalize_filter_timestamp(raw_value: str | None, *, end_of_day: bool = False) -> str | None:
    text = str(raw_value or "").strip()
    if not text:
        return None
    if "T" in text:
        return text
    return f"{text}T23:59:59.999Z" if end_of_day else f"{text}T00:00:00Z"


def _record_matches_filters(
    record: dict[str, Any],
    *,
    search_term: str | None = None,
    title_pattern: str | None = None,
    date_since: str | None = None,
    date_until: str | None = None,
) -> bool:
    normalized_search = str(search_term or "").strip().lower()
    if normalized_search:
        title = str(record.get("record_title") or "").lower()
        filename = str(record.get("source_file_name") or "").lower()
        if normalized_search not in title and normalized_search not in filename:
            return False

    normalized_pattern = str(title_pattern or "").strip()
    if normalized_pattern:
        regex_pattern = re.escape(normalized_pattern).replace(r"\*", ".*")
        if not re.fullmatch(regex_pattern, str(record.get("record_title") or "")):
            return False

    created_timestamp = str(record.get("created_timestamp") or "").strip()
    lower_bound = _normalize_filter_timestamp(date_since)
    if lower_bound and (not created_timestamp or created_timestamp < lower_bound):
        return False

    upper_bound = _normalize_filter_timestamp(date_until, end_of_day=True)
    if upper_bound and (not created_timestamp or created_timestamp > upper_bound):
        return False

    return True


def _bundle_size_by_file_id(source_rows: list[dict[str, Any]]) -> dict[int, int]:
    children_by_parent: dict[int, list[int]] = {}
    for row in source_rows:
        parent_file_id = row.get("parent_file_id")
        if parent_file_id is None:
            continue
        children_by_parent.setdefault(int(parent_file_id), []).append(int(row["file_id"]))

    cache: dict[int, int] = {}

    def _count(file_id: int) -> int:
        if file_id in cache:
            return cache[file_id]
        total = 1
        for child_id in children_by_parent.get(file_id, []):
            total += _count(child_id)
        cache[file_id] = total
        return total

    return {int(row["file_id"]): _count(int(row["file_id"])) for row in source_rows}


def _build_uploadable_files(
    source_rows: list[dict[str, Any]],
    records: list[dict[str, Any]],
    *,
    is_sandbox_for_drafts: bool,
) -> list[dict[str, Any]]:
    records_by_source_file_id: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        source_file_id = record.get("source_file_id")
        if source_file_id is None:
            continue
        records_by_source_file_id.setdefault(int(source_file_id), []).append(record)

    actionable: list[dict[str, Any]] = []
    metadata_ready_statuses = {"pending", "source_added", "metadata_error"}
    active_record_statuses = {"prepared", "draft", "published"}

    for row in source_rows:
        if not _is_recordable_source_row(row):
            continue
        file_status = str(row.get("status") or "").strip().lower()
        if file_status not in metadata_ready_statuses:
            continue
        related_records = records_by_source_file_id.get(int(row["file_id"]), [])
        if any(str(record.get("record_status") or "").lower() in active_record_statuses for record in related_records):
            continue
        actionable.append(
            {
                "source_file_db_id": int(row["file_id"]),
                "filename": row.get("filename"),
                "absolute_path": row.get("absolute_path"),
                "file_db_status": row.get("status"),
                "required_action": "action_prepare_metadata",
            }
        )

    for record in records:
        if str(record.get("record_status") or "").lower() != "prepared":
            continue
        if str(record.get("zenodo_record_id") or "").strip():
            continue
        actionable.append(
            {
                "source_file_db_id": record.get("source_file_id"),
                "filename": record.get("source_file_name"),
                "absolute_path": record.get("source_file_path"),
                "file_db_status": "metadata_ready",
                "local_record_db_id": record.get("record_id"),
                "record_title": record.get("record_title"),
                "is_sandbox": bool(record.get("is_sandbox")),
                "zenodo_record_db_status": record.get("record_status"),
                "required_action": "action_create_api_draft",
            }
        )

    for record in records:
        if str(record.get("record_status") or "").lower() != "draft":
            continue
        if not str(record.get("zenodo_record_id") or "").strip():
            continue
        if bool(record.get("is_sandbox")) is not bool(is_sandbox_for_drafts):
            continue
        for file_item in record.get("record_files") or []:
            if not _upload_requires_retry(file_item.get("upload_status")):
                continue
            actionable.append(
                {
                    "source_file_db_id": file_item.get("file_id"),
                    "filename": file_item.get("filename"),
                    "absolute_path": file_item.get("absolute_path"),
                    "file_db_status": (file_item.get("source_file") or {}).get("status"),
                    "local_record_db_id": record.get("record_id"),
                    "zenodo_api_deposition_id": record.get("zenodo_record_id"),
                    "record_title": record.get("record_title"),
                    "zenodo_record_db_status": record.get("record_status"),
                    "is_sandbox": bool(record.get("is_sandbox")),
                    "file_upload_on_zenodo_status": file_item.get("upload_status"),
                    "required_action": "action_upload_file",
                }
            )
    return actionable


def read_hdpc_uploadable_files(
    hdpc_path: str,
    *,
    is_sandbox_for_drafts: bool = True,
    _snapshot: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    snapshot = _snapshot or _load_hdpc_snapshot(
        hdpc_path,
        include_configuration=False,
        include_scan_settings=False,
        canonical_records_only=True,
    )
    items = _build_uploadable_files(
        snapshot["source_rows_dicts"],
        snapshot["zenodo_records"],
        is_sandbox_for_drafts=is_sandbox_for_drafts,
    )
    from services.lod_artifact_service import record_lod_readiness
    readiness = {}
    eligible = []
    for item in items:
        if item.get('required_action') == 'action_upload_file':
            record_id = item['local_record_db_id']
            if record_id not in readiness:
                readiness[record_id] = record_lod_readiness(hdpc_path, record_id)['ready']
            if not readiness[record_id]:
                continue
        eligible.append(item)
    return eligible


def read_hdpc_uploads_by_tab(
    hdpc_path: str,
    *,
    tab_id: str = "pending_preparation",
    is_sandbox: bool = True,
    search_term: str | None = None,
    title_pattern: str | None = None,
    date_since: str | None = None,
    date_until: str | None = None,
    _snapshot: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    normalized_tab = str(tab_id or "pending_preparation").strip().lower() or "pending_preparation"
    if normalized_tab == "versioning":
        return []
    if normalized_tab not in {"pending_preparation", "pending_operations", "drafts", "published"}:
        raise ValueError("Invalid tab_id")
    snapshot = _snapshot or _load_hdpc_snapshot(
        hdpc_path,
        include_configuration=False,
        include_scan_settings=False,
        canonical_records_only=True,
    )
    source_rows = snapshot["source_rows_dicts"]
    records = snapshot["zenodo_records"]
    records_by_source_file_id: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        source_file_id = record.get("source_file_id")
        if source_file_id is None:
            continue
        records_by_source_file_id.setdefault(int(source_file_id), []).append(record)

    if normalized_tab == "pending_preparation":
        restartable_statuses = {"preparation_failed", "discarded"}
        pending_statuses = {
            "pending",
            "source_added",
            "metadata_error",
            "verified",
            "valid",
            "invalid",
            "problems",
            "mtl missing",
            "textures missing",
            "file conflict",
        }
        bundle_sizes = _bundle_size_by_file_id(source_rows)
        items: list[dict[str, Any]] = []
        for row in source_rows:
            if not _is_recordable_source_row(row):
                continue
            file_status = str(row.get("status") or "").strip().lower()
            if file_status not in pending_statuses:
                continue
            related_records = records_by_source_file_id.get(int(row["file_id"]), [])
            if any(
                str(record.get("record_status") or "").lower() not in restartable_statuses
                for record in related_records
            ):
                continue
            items.append(
                {
                    "source_file_db_id": int(row["file_id"]),
                    "filename": row.get("filename"),
                    "absolute_path": row.get("absolute_path"),
                    "file_db_status": row.get("status"),
                    "required_action": "action_prepare_metadata",
                    "total_bundle_files": bundle_sizes.get(int(row["file_id"]), 1),
                }
            )
        items.sort(key=lambda item: str(item.get("filename") or "").lower())
        return items

    filtered_records = [
        record
        for record in records
        if bool(record.get("is_sandbox")) is bool(is_sandbox)
        and _record_matches_filters(
            record,
            search_term=search_term,
            title_pattern=title_pattern,
            date_since=date_since,
            date_until=date_until,
        )
    ]

    if normalized_tab == "pending_operations":
        items = [
            {
                "local_record_db_id": record.get("record_id"),
                "record_title": record.get("record_title"),
                "zenodo_record_db_status": record.get("record_status"),
                "is_sandbox": bool(record.get("is_sandbox")),
                "filename": record.get("source_file_name"),
                "record_created_date": record.get("created_timestamp"),
            }
            for record in filtered_records
            if str(record.get("record_status") or "").lower() == "prepared"
            and not str(record.get("zenodo_record_id") or "").strip()
        ]
        items.sort(
            key=lambda item: (
                str(item.get("record_created_date") or ""),
                int(item.get("local_record_db_id") or 0),
            ),
            reverse=True,
        )
        return items

    if normalized_tab == "drafts":
        items = []
        for record in filtered_records:
            if str(record.get("record_status") or "").lower() != "draft":
                continue
            if not str(record.get("zenodo_record_id") or "").strip():
                continue
            items.append(
                {
                    "local_record_db_id": record.get("record_id"),
                    "record_title": record.get("record_title"),
                    "zenodo_record_db_status": record.get("record_status"),
                    "is_sandbox": bool(record.get("is_sandbox")),
                    "zenodo_api_deposition_id": record.get("zenodo_record_id"),
                    "filename": record.get("source_file_name"),
                    "total_files_in_record": len(record.get("record_files") or []),
                    "uploaded_files_in_record": sum(
                        1
                        for file_item in record.get("record_files") or []
                        if str(file_item.get("upload_status") or "").strip().lower() == "uploaded"
                    ),
                    "discard_link": str((record.get("links") or {}).get("discard") or "").strip() or None,
                }
            )
        items.sort(
            key=lambda item: (
                str(
                    next(
                        (
                            record.get("last_updated_timestamp")
                            for record in filtered_records
                            if record.get("record_id") == item.get("local_record_db_id")
                        ),
                        "",
                    )
                ),
                int(item.get("local_record_db_id") or 0),
            ),
            reverse=True,
        )
        return items

    items = [
        {
            "local_record_db_id": record.get("record_id"),
            "record_title": record.get("record_title"),
            "zenodo_doi": record.get("zenodo_doi"),
            "concept_rec_id": record.get("concept_rec_id"),
            "version": record.get("version"),
            "version_rank": record.get("version_rank"),
            "filename": record.get("source_file_name"),
            "zenodo_api_deposition_id": record.get("zenodo_record_id"),
        }
        for record in filtered_records
        if str(record.get("record_status") or "").lower() == "published"
    ]
    items.sort(
        key=lambda item: (
            str(item.get("concept_rec_id") or ""),
            int(item.get("version_rank") or 0),
            _version_sort_key(item.get("version")),
            int(item.get("local_record_db_id") or 0),
        ),
        reverse=True,
    )
    return items


def read_hdpc_source_files(
    hdpc_path: str,
    *,
    page: int = 1,
    limit: int = 25,
    search: str | None = None,
) -> dict[str, Any]:
    conn = connect_hdpc(hdpc_path, readonly=True, timeout=30, row_factory=sqlite3.Row)
    try:
        cursor = conn.cursor()
        safe_limit = max(1, min(int(limit or 25), 500))
        safe_page = max(1, int(page or 1))
        source_file_columns = _table_columns(cursor, "source_files")
        if not source_file_columns:
            return {"items": [], "totalItems": 0, "page": safe_page, "totalPages": 1}

        select_columns = ["file_id"]
        optional_columns = {
            "filename": "filename",
            "relative_path": "relative_path",
            "absolute_path": "absolute_path",
            "size_bytes": "size_bytes",
            "mime_type": "mime_type",
            "file_type": "file_type",
            "status": "status",
            "parent_file_id": "parent_file_id",
            "is_primary_source": "is_primary_source",
            "pipeline_source": "pipeline_source",
            "step_source": "step_source",
            "sha256_hash": "sha256_hash",
            "error_message": "error_message",
            "validation_report_json": "validation_report_json",
        }
        for alias, column_name in optional_columns.items():
            if column_name in source_file_columns:
                select_columns.append(column_name)
            elif alias == "is_primary_source":
                select_columns.append("0 AS is_primary_source")
            else:
                select_columns.append(f"NULL AS {alias}")

        filters: list[str] = []
        params: list[Any] = []
        normalized_search = str(search or "").strip().lower()
        filename_expression = "LOWER(COALESCE(filename, ''))" if "filename" in source_file_columns else "CAST(file_id AS TEXT)"
        if normalized_search:
            filters.append(f"{filename_expression} LIKE ?")
            params.append(f"%{normalized_search}%")

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        total_items = int(
            cursor.execute(
                f"SELECT COUNT(*) FROM source_files {where_clause}",
                tuple(params),
            ).fetchone()[0]
        )
        total_pages = max(1, (total_items + safe_limit - 1) // safe_limit) if total_items else 1
        offset = (safe_page - 1) * safe_limit
        rows = [
            dict(row)
            for row in cursor.execute(
                f"""
                SELECT {', '.join(select_columns)}
                FROM source_files
                {where_clause}
                ORDER BY {filename_expression} ASC, file_id ASC
                LIMIT ? OFFSET ?
                """,
                (*params, safe_limit, offset),
            ).fetchall()
        ]

        items = [
            {
                "file_id": int(row["file_id"]),
                "filename": row.get("filename"),
                "relative_path": row.get("relative_path"),
                "absolute_path": row.get("absolute_path"),
                "size_bytes": row.get("size_bytes"),
                "mime_type": row.get("mime_type"),
                "file_type": row.get("file_type"),
                "status": row.get("status"),
                "parent_file_id": row.get("parent_file_id"),
                "is_primary_source": bool(row.get("is_primary_source")),
                "pipeline_source": row.get("pipeline_source"),
                "step_source": row.get("step_source"),
                "sha256_hash": row.get("sha256_hash"),
                "error_message": row.get("error_message"),
                "validation_report_json": _json_loads(row.get("validation_report_json"), {}),
            }
            for row in rows
        ]
        return {
            "items": items,
            "totalItems": total_items,
            "page": safe_page,
            "totalPages": total_pages,
        }
    finally:
        conn.close()


def read_hdpc_file_hierarchy(hdpc_path: str, file_id: int) -> dict[str, Any] | None:
    file_tree = _load_hdpc_snapshot(
        hdpc_path,
        include_configuration=False,
        include_scan_settings=False,
        include_file_tree=True,
    )["file_tree"]

    def _find_node(nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
        for node in nodes:
            if int(node.get("file_id") or 0) == int(file_id):
                return node
            found = _find_node(node.get("children") or [])
            if found is not None:
                return found
        return None

    return _find_node(file_tree)


def read_hdpc_record_inputs(hdpc_path: str, record_id: int) -> list[dict[str, Any]]:
    """Include unpacked descendants of upload archives needed by processors."""
    conn = connect_hdpc(hdpc_path, readonly=True, timeout=30, row_factory=sqlite3.Row)
    try:
        return [dict(row) for row in conn.execute(
            """WITH RECURSIVE inputs(file_id) AS (
                SELECT file_id FROM record_files_map WHERE record_id = ?
                UNION
                SELECT sf.file_id FROM source_files sf
                JOIN inputs ON sf.parent_file_id = inputs.file_id
            )
            SELECT sf.* FROM source_files sf JOIN inputs ON inputs.file_id = sf.file_id
            WHERE sf.pipeline_source IN ('scan', 'ingestion')""",
            (int(record_id),),
        ).fetchall()]
    finally:
        conn.close()


def read_hdpc_record_files(hdpc_path: str, record_id: int) -> list[dict[str, Any]]:
    snapshot = _load_hdpc_snapshot(
        hdpc_path,
        include_configuration=False,
        include_scan_settings=False,
        canonical_records_only=True,
    )
    record = next(
        (item for item in snapshot["zenodo_records"] if int(item.get("record_id") or 0) == int(record_id)),
        None,
    )
    return _normalize_hdpc_record_files((record or {}).get("record_files") or [])


def _normalize_hdpc_record_files(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items:
        normalized.append(
            {
                "file_id": item.get("file_id"),
                "filename": item.get("filename"),
                "absolute_path": item.get("absolute_path"),
                "relative_path": item.get("relative_path"),
                "file_type": (item.get("source_file") or {}).get("file_type"),
                "status": (item.get("source_file") or {}).get("status"),
                "sha256_hash": (item.get("source_file") or {}).get("sha256_hash"),
                "size_bytes": (item.get("source_file") or {}).get("size_bytes"),
                "mime_type": (item.get("source_file") or {}).get("mime_type"),
                "pipeline_source": (item.get("source_file") or {}).get("pipeline_source"),
                "step_source": (item.get("source_file") or {}).get("step_source"),
                "validation_report_json": _json_loads((item.get("source_file") or {}).get("validation_report_json"), {}),
                "file_purpose": item.get("file_purpose"),
                "upload_status": item.get("upload_status"),
                "upload_timestamp": item.get("upload_timestamp"),
                "upload_error": item.get("upload_error"),
                "zenodo_file_id": item.get("zenodo_file_id"),
                "zenodo_file_key": item.get("zenodo_file_key"),
                "zenodo_file_checksum": item.get("zenodo_file_checksum"),
                "zenodo_file_size": item.get("zenodo_file_size"),
                "zenodo_file_links": item.get("file_links") or {},
                "upload_response": item.get("upload_response") or {},
                "mapped_file_path": item.get("file_path"),
            }
        )
    normalized.sort(
        key=lambda item: (
            0 if str(item.get("file_purpose") or "").lower() == "main" else 1,
            str(item.get("filename") or "").lower(),
        )
    )
    return normalized


def _find_file_tree_node(nodes: list[dict[str, Any]], file_id: int) -> dict[str, Any] | None:
    for node in nodes:
        if int(node.get("file_id") or 0) == int(file_id):
            return node
        found = _find_file_tree_node(node.get("children") or [], file_id)
        if found is not None:
            return found
    return None


def _latest_same_concept_record_payload(records: list[dict[str, Any]], current_record: dict[str, Any]) -> dict[str, Any] | None:
    concept_rec_id = str(current_record.get("concept_rec_id") or "").strip()
    if not concept_rec_id:
        return None
    related = [
        record
        for record in records
        if record.get("record_status") == "published"
        and bool(record.get("is_sandbox")) is bool(current_record.get("is_sandbox"))
        and str(record.get("concept_rec_id") or "").strip() == concept_rec_id
    ]
    if not related:
        return None
    related.sort(
        key=lambda item: (
            int(item.get("version_rank") or 0),
            _version_sort_key(item.get("version")),
            str(item.get("last_updated_timestamp") or ""),
            int(item.get("record_id") or 0),
        ),
        reverse=True,
    )
    latest = related[0]
    metadata_files = latest.get("record_metadata", {}).get("files")
    files = metadata_files if isinstance(metadata_files, list) and metadata_files else [
        {
            "filename": item.get("filename"),
            "key": item.get("zenodo_file_key") or item.get("filename"),
            "checksum": item.get("zenodo_file_checksum"),
            "filesize": item.get("zenodo_file_size"),
            "links": item.get("file_links") or {},
        }
        for item in latest.get("record_files") or []
    ]
    return {
        "record_id": latest.get("record_id"),
        "concept_rec_id": latest.get("concept_rec_id"),
        "zenodo_record_id": latest.get("zenodo_record_id"),
        "version": latest.get("version"),
        "version_rank": latest.get("version_rank"),
        "files": files,
    }


def read_hdpc_record_context(hdpc_path: str, record_id: int) -> dict[str, Any] | None:
    conn = connect_hdpc(hdpc_path, readonly=True, timeout=30, row_factory=sqlite3.Row)
    try:
        cursor = conn.cursor()
        source_rows = _read_source_rows(cursor)
        source_rows_by_id = {int(row["file_id"]): dict(row) for row in source_rows}
        records = _read_zenodo_records(cursor, source_rows, canonical_only=True)
        record = next((item for item in records if int(item.get("record_id") or 0) == int(record_id)), None)
        if record is None:
            return None

        source_file = source_rows_by_id.get(int(record.get("source_file_id") or 0), {})
        normalized_files = _normalize_hdpc_record_files(record.get("record_files") or [])
        snapshots: list[dict[str, Any]] = []
        if _table_exists(cursor, "zenodo_record_snapshots"):
            snapshot_rows = cursor.execute(
                """
                SELECT snapshot_id, snapshot_stage, http_status, payload_json, created_timestamp
                FROM zenodo_record_snapshots
                WHERE record_id = ? AND snapshot_stage != 'lod_generation'
                ORDER BY snapshot_id ASC
                """,
                (int(record_id),),
            ).fetchall()
            snapshots = [
                {
                    "snapshot_id": int(row["snapshot_id"]),
                    "snapshot_stage": row["snapshot_stage"],
                    "http_status": row["http_status"],
                    "payload": _json_loads(row["payload_json"], {}),
                    "created_timestamp": row["created_timestamp"],
                }
                for row in snapshot_rows
            ]

        links = [
            {"link_rel": rel, "link_url": url}
            for rel, url in sorted((record.get("links") or {}).items())
            if rel and url
        ]
        traceability = {
            "record": {
                "record_id": record.get("record_id"),
                "record_status": record.get("record_status"),
                "record_title": record.get("record_title"),
                "zenodo_record_id": record.get("zenodo_record_id"),
                "zenodo_doi": record.get("zenodo_doi"),
                "concept_doi": record.get("concept_doi"),
                "concept_rec_id": record.get("concept_rec_id"),
                "is_sandbox": record.get("is_sandbox"),
                "created_timestamp": record.get("created_timestamp"),
                "last_updated_timestamp": record.get("last_updated_timestamp"),
                "version": record.get("version"),
                "version_rank": record.get("version_rank"),
                "previous_record_id": record.get("previous_record_id"),
                "last_api_error": record.get("last_api_error"),
                "record_metadata": record.get("record_metadata"),
            },
            "source_file": {
                "file_id": source_file.get("file_id"),
                "filename": source_file.get("filename"),
                "absolute_path": source_file.get("absolute_path"),
                "relative_path": source_file.get("relative_path"),
                "sha256_hash": source_file.get("sha256_hash"),
                "size_bytes": source_file.get("size_bytes"),
                "mime_type": source_file.get("mime_type"),
                "file_type": source_file.get("file_type"),
                "status": source_file.get("status"),
                "pipeline_source": source_file.get("pipeline_source"),
                "step_source": source_file.get("step_source"),
                "validation_report_json": _json_loads(source_file.get("validation_report_json"), {}),
            },
            "links": links,
            "files": normalized_files,
            "snapshots": snapshots,
            "summary": {
                "file_count": len(normalized_files),
                "uploaded_file_count": sum(
                    1 for item in normalized_files if str(item.get("upload_status") or "").lower() == "uploaded"
                ),
                "snapshot_count": len(snapshots),
                "has_links": bool(links),
            },
        }

        file_tree = _build_file_tree(source_rows)
        source_hierarchy = (
            _find_file_tree_node(file_tree, int(source_file["file_id"]))
            if source_file.get("file_id") is not None
            else None
        )
        previous_record = None
        previous_record_id = record.get("previous_record_id")
        if previous_record_id is not None:
            previous_record = next(
                (
                    {
                        "record_id": item.get("record_id"),
                        "record_title": item.get("record_title"),
                        "record_status": item.get("record_status"),
                        "version": item.get("version"),
                        "version_rank": item.get("version_rank"),
                        "zenodo_record_id": item.get("zenodo_record_id"),
                    }
                    for item in records
                    if int(item.get("record_id") or 0) == int(previous_record_id)
                ),
                None,
            )
        next_versions = [
            {
                "record_id": item.get("record_id"),
                "record_title": item.get("record_title"),
                "record_status": item.get("record_status"),
                "version": item.get("version"),
                "version_rank": item.get("version_rank"),
                "zenodo_record_id": item.get("zenodo_record_id"),
            }
            for item in records
            if int(item.get("previous_record_id") or 0) == int(record_id)
        ]
        next_versions.sort(
            key=lambda item: (
                int(item.get("version_rank") or 0),
                _version_sort_key(item.get("version")),
                int(item.get("record_id") or 0),
            )
        )
        latest_same_concept = _latest_same_concept_record_payload(records, record)
        lineage = {
            "traceability": traceability,
            "source_hierarchy": source_hierarchy,
            "latest_same_concept": latest_same_concept,
            "previous_record": previous_record,
            "next_versions": next_versions,
            "summary": {
                "has_source_hierarchy": source_hierarchy is not None,
                "has_latest_same_concept": latest_same_concept is not None,
                "has_previous_record": previous_record is not None,
                "next_version_count": len(next_versions),
                "snapshot_count": int((traceability.get("summary") or {}).get("snapshot_count") or 0),
                "uploaded_file_count": int((traceability.get("summary") or {}).get("uploaded_file_count") or 0),
            },
        }

        upload_status_counts = Counter(str(item.get("upload_status") or "unknown").strip().lower() for item in normalized_files)
        communities = (
            ((record.get("record_metadata") or {}).get("metadata") or {}).get("communities")
            if isinstance(record.get("record_metadata"), dict)
            else None
        )
        latest_snapshot_payload = next(
            (
                item.get("payload")
                for item in reversed(snapshots)
                if isinstance(item.get("payload"), dict)
            ),
            {},
        )
        link_map = {item.get("link_rel"): item.get("link_url") for item in links if item.get("link_rel")}
        from services.lod_artifact_service import record_lod_readiness
        lod_readiness = record_lod_readiness(hdpc_path, record_id)
        zenodo_status = {
            "lod_readiness": lod_readiness,
            "record": traceability["record"],
            "links": link_map,
            "upload_status_counts": dict(upload_status_counts),
            "communities": communities if isinstance(communities, list) else [],
            "actions": {
                "can_create_draft": str(record.get("record_status") or "").lower() == "prepared" and not str(record.get("zenodo_record_id") or "").strip(),
                "can_discard_draft": str(record.get("record_status") or "").lower() == "draft",
                "can_upload_files": lod_readiness["ready"] and str(record.get("record_status") or "").lower() == "draft" and any(
                    _upload_requires_retry(item.get("upload_status")) for item in normalized_files
                ),
                "can_publish": lod_readiness["ready"] and str(record.get("record_status") or "").lower() == "draft" and all(
                    not _upload_requires_retry(item.get("upload_status")) for item in normalized_files
                ),
            },
            "summary": {
                "file_count": len(normalized_files),
                "uploaded_file_count": int((traceability.get("summary") or {}).get("uploaded_file_count") or 0),
                "has_doi": bool(record.get("zenodo_doi")),
                "has_html_link": bool(link_map.get("html")),
                "last_api_error": record.get("last_api_error"),
                "latest_snapshot_stage": snapshots[-1].get("snapshot_stage") if snapshots else None,
                "latest_payload": latest_snapshot_payload,
            },
        }

        return {
            "traceability": traceability,
            "lineage": lineage,
            "zenodo_status": zenodo_status,
        }
    finally:
        conn.close()


def read_hdpc_record_traceability(hdpc_path: str, record_id: int) -> dict[str, Any] | None:
    context = read_hdpc_record_context(hdpc_path, record_id)
    return context.get("traceability") if context else None


def read_hdpc_latest_published_record_files(
    hdpc_path: str,
    *,
    concept_rec_id: str,
    is_sandbox: bool = True,
) -> dict[str, Any] | None:
    normalized_concept = str(concept_rec_id or "").strip()
    if not normalized_concept:
        return None

    records = [
        record
        for record in read_hdpc_published_records(hdpc_path, canonical_only=True)
        if str(record.get("concept_rec_id") or "").strip() == normalized_concept
        and bool(record.get("is_sandbox")) is bool(is_sandbox)
    ]
    if not records:
        return None

    records.sort(
        key=lambda item: (
            int(item.get("version_rank") or 0),
            _version_sort_key(item.get("version")),
            str(item.get("last_updated_timestamp") or ""),
            int(item.get("record_id") or 0),
        ),
        reverse=True,
    )
    latest = records[0]
    metadata_files = latest.get("record_metadata", {}).get("files")
    if isinstance(metadata_files, list) and metadata_files:
        files = metadata_files
    else:
        files = []
        for item in latest.get("record_files") or []:
            files.append(
                {
                    "filename": item.get("filename"),
                    "key": item.get("zenodo_file_key") or item.get("filename"),
                    "checksum": item.get("zenodo_file_checksum"),
                    "filesize": item.get("zenodo_file_size"),
                    "links": item.get("file_links") or {},
                }
            )
    return {
        "record_id": latest.get("record_id"),
        "concept_rec_id": latest.get("concept_rec_id"),
        "zenodo_record_id": latest.get("zenodo_record_id"),
        "version": latest.get("version"),
        "version_rank": latest.get("version_rank"),
        "files": files,
    }


def match_hdpc_files_for_versioning(
    hdpc_path: str,
    *,
    directory_path: str,
    match_method: str = "filename",
) -> list[dict[str, Any]]:
    normalized_directory = str(directory_path or "").strip()
    if not normalized_directory:
        raise ValueError("directory_path is required")
    target_dir = Path(normalized_directory)
    if not target_dir.is_dir():
        raise FileNotFoundError(normalized_directory)

    conn = connect_hdpc(hdpc_path, readonly=True, timeout=30, row_factory=sqlite3.Row)
    try:
        cursor = conn.cursor()
        source_rows = _read_source_rows(cursor)
        source_rows_by_id = {int(row["file_id"]): dict(row) for row in source_rows}
        published_records = [
            record
            for record in _read_zenodo_records(cursor, source_rows, canonical_only=True)
            if record.get("record_status") == "published" and record.get("concept_rec_id")
        ]
        matches: list[dict[str, Any]] = []
        files_in_dir = [path for path in target_dir.iterdir() if path.is_file()]
        for file_path in files_in_dir:
            current_hash: str | None = None
            for record in published_records:
                source_file = source_rows_by_id.get(int(record.get("source_file_id") or 0), {})
                is_match = False
                if match_method == "hashcode":
                    if current_hash is None:
                        current_hash = _file_sha256(str(file_path))
                    is_match = bool(current_hash and current_hash == str(source_file.get("sha256_hash") or ""))
                else:
                    is_match = file_path.name == str(source_file.get("filename") or "")
                if not is_match:
                    continue
                matches.append(
                    {
                        "concept_rec_id": record.get("concept_rec_id"),
                        "record_title": record.get("record_title"),
                        "matched_file_path": str(file_path.resolve()),
                        "matched_file_name": file_path.name,
                        "match_method": match_method,
                        "source_file_id": record.get("source_file_id"),
                        "local_record_id": record.get("record_id"),
                    }
                )
                break
        return matches
    finally:
        conn.close()


def read_hdpc_operations_summary(
    hdpc_path: str,
    *,
    is_sandbox: bool = True,
    _snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = _snapshot or _load_hdpc_snapshot(
        hdpc_path,
        include_configuration=False,
        include_scan_settings=False,
        canonical_records_only=True,
    )
    records = snapshot["zenodo_records"]
    uploadable_files = read_hdpc_uploadable_files(
        hdpc_path,
        is_sandbox_for_drafts=is_sandbox,
        _snapshot=snapshot,
    )
    pending_preparation = read_hdpc_uploads_by_tab(
        hdpc_path,
        tab_id="pending_preparation",
        is_sandbox=is_sandbox,
        _snapshot=snapshot,
    )
    pending_operations = read_hdpc_uploads_by_tab(
        hdpc_path,
        tab_id="pending_operations",
        is_sandbox=is_sandbox,
        _snapshot=snapshot,
    )
    drafts = read_hdpc_uploads_by_tab(
        hdpc_path,
        tab_id="drafts",
        is_sandbox=is_sandbox,
        _snapshot=snapshot,
    )
    published = read_hdpc_uploads_by_tab(
        hdpc_path,
        tab_id="published",
        is_sandbox=is_sandbox,
        _snapshot=snapshot,
    )
    upload_record_items: list[dict[str, Any]] = []
    publish_record_items: list[dict[str, Any]] = []
    from services.lod_artifact_service import record_lod_readiness
    for item in drafts:
        record_id = int(item.get("local_record_db_id") or 0)
        if not record_id:
            continue
        if not record_lod_readiness(hdpc_path, record_id)['ready']:
            continue
        uploaded = int(item.get("uploaded_files_in_record") or 0)
        total = int(item.get("total_files_in_record") or 0)
        if uploaded < total:
            upload_record_items.append(
                {
                    "local_record_id": record_id,
                    "record_title": item.get("record_title"),
                    "zenodo_record_id": item.get("zenodo_api_deposition_id"),
                    "uploaded_files_in_record": uploaded,
                    "total_files_in_record": total,
                    "result_code": "pending_uploads",
                }
            )
        elif total > 0:
            publish_record_items.append(
                {
                    "local_record_id": record_id,
                    "record_title": item.get("record_title"),
                    "zenodo_record_id": item.get("zenodo_api_deposition_id"),
                    "uploaded_files_in_record": uploaded,
                    "total_files_in_record": total,
                    "result_code": "ready_to_publish",
                }
            )

    return {
        "environment": "sandbox" if is_sandbox else "production",
        "tabs": {
            "pending_preparation": {"count": len(pending_preparation), "items": pending_preparation},
            "pending_operations": {"count": len(pending_operations), "items": pending_operations},
            "drafts": {"count": len(drafts), "items": drafts},
            "published": {"count": len(published), "items": published},
        },
        "actionable_operations": {
            "create_drafts": {
                "count": len(pending_operations),
                "target_kind": "record",
                "target_ids": [int(item["local_record_db_id"]) for item in pending_operations if item.get("local_record_db_id")],
                "items": pending_operations,
            },
            "discard_drafts": {
                "count": len(drafts),
                "target_kind": "record",
                "target_ids": [int(item["local_record_db_id"]) for item in drafts if item.get("local_record_db_id")],
                "items": drafts,
            },
            "upload_files": {
                "count": len(upload_record_items),
                "target_kind": "record",
                "target_ids": [int(item["local_record_id"]) for item in upload_record_items],
                "items": upload_record_items,
            },
            "publish_records": {
                "count": len(publish_record_items),
                "target_kind": "record",
                "target_ids": [int(item["local_record_id"]) for item in publish_record_items],
                "items": publish_record_items,
            },
            "remove_files": {
                "count": len(pending_preparation),
                "target_kind": "file",
                "target_ids": [int(item["source_file_db_id"]) for item in pending_preparation if item.get("source_file_db_id")],
                "items": pending_preparation,
            },
        },
        "summary": {
            "uploadable_item_count": len(uploadable_files),
            "draft_record_count": len(drafts),
            "published_record_count": len(published),
        },
    }


def read_hdpc_workspace_summary(hdpc_path: str, *, is_sandbox: bool = True) -> dict[str, Any]:
    inspect_data = _load_hdpc_snapshot(
        hdpc_path,
        include_configuration=True,
        include_scan_settings=True,
        canonical_records_only=True,
    )
    operations = read_hdpc_operations_summary(hdpc_path, is_sandbox=is_sandbox, _snapshot=inspect_data)
    configuration_items = inspect_data.get("configuration") or []
    config_map = {
        str(item.get("config_key") or ""): item.get("config_value")
        for item in configuration_items
        if item.get("config_key")
    }
    published_records = inspect_data.get("published_records") or []
    latest_published = max(
        published_records,
        key=lambda item: (
            int(item.get("version_rank") or 0),
            _version_sort_key(item.get("version")),
            str(item.get("last_updated_timestamp") or ""),
            int(item.get("record_id") or 0),
        ),
        default=None,
    )
    return {
        "project_info": inspect_data.get("project_info") or {},
        "project_statistics": inspect_data.get("project_statistics") or {},
        "file_scan_settings": inspect_data.get("file_scan_settings") or [],
        "configuration": configuration_items,
        "configuration_hints": {
            "batch_entity": config_map.get("core.batch_entity"),
            "use_sandbox": config_map.get("main.use_sandbox") or config_map.get("core.use_sandbox"),
            "pipeline_defaults": {
                key: value
                for key, value in config_map.items()
                if str(key).startswith("pipelines.")
            },
        },
        "record_summary": {
            "published_count": len(published_records),
            "draft_count": int((inspect_data.get("project_statistics") or {}).get("draft_record_count") or 0),
            "prepared_count": int((inspect_data.get("project_statistics") or {}).get("prepared_record_count") or 0),
            "record_count": int((inspect_data.get("project_statistics") or {}).get("record_count") or 0),
        },
        "upload_summary": operations.get("summary") or {},
        "versioning_summary": {
            "latest_published_record": {
                "local_record_id": latest_published.get("record_id"),
                "record_title": latest_published.get("record_title"),
                "concept_rec_id": latest_published.get("concept_rec_id"),
                "version": latest_published.get("version"),
                "version_rank": latest_published.get("version_rank"),
                "zenodo_record_id": latest_published.get("zenodo_record_id"),
            } if latest_published else None,
            "published_records": [
                {
                    "local_record_id": item.get("record_id"),
                    "record_title": item.get("record_title"),
                    "concept_rec_id": item.get("concept_rec_id"),
                    "version": item.get("version"),
                    "version_rank": item.get("version_rank"),
                    "zenodo_record_id": item.get("zenodo_record_id"),
                }
                for item in published_records[:10]
            ],
        },
        "operations": operations,
    }


def read_hdpc_record_lineage(hdpc_path: str, record_id: int) -> dict[str, Any] | None:
    context = read_hdpc_record_context(hdpc_path, record_id)
    return context.get("lineage") if context else None


def read_hdpc_record_zenodo_status(hdpc_path: str, record_id: int) -> dict[str, Any] | None:
    context = read_hdpc_record_context(hdpc_path, record_id)
    return context.get("zenodo_status") if context else None


@serialize_project_mutation
def remove_local_source_files(
    hdpc_path: str,
    *,
    file_ids: list[int],
) -> dict[str, Any]:
    normalized_ids = sorted({int(file_id) for file_id in file_ids if str(file_id).isdigit()})
    if not normalized_ids:
        return {
            "success": True,
            "removed_count": 0,
            "results": [],
        }

    conn = connect_hdpc(hdpc_path, timeout=30, row_factory=sqlite3.Row)
    try:
        cursor = conn.cursor()
        source_rows = [dict(row) for row in _read_source_rows(cursor)]
        children_by_parent: dict[int, list[int]] = {}
        for row in source_rows:
            parent_id = row.get("parent_file_id")
            if parent_id is None:
                continue
            children_by_parent.setdefault(int(parent_id), []).append(int(row["file_id"]))

        def _collect_descendants(root_id: int) -> list[int]:
            ordered: list[int] = []
            stack = [root_id]
            seen: set[int] = set()
            while stack:
                current = stack.pop()
                if current in seen:
                    continue
                seen.add(current)
                ordered.append(current)
                stack.extend(children_by_parent.get(current, []))
            return ordered

        results: list[dict[str, Any]] = []
        for file_id in normalized_ids:
            target_ids = _collect_descendants(file_id)
            active_links = cursor.execute(
                """
                SELECT zr.record_id, zr.record_status
                FROM zenodo_records zr
                WHERE zr.source_file_id IN ({placeholders})
                """.format(placeholders=",".join("?" for _ in target_ids)),
                tuple(target_ids),
            ).fetchall() if _table_exists(cursor, "zenodo_records") else []

            active_record = next(
                (
                    dict(row)
                    for row in active_links
                    if str(row["record_status"] or "").strip().lower() in {"prepared", "draft", "published"}
                ),
                None,
            )
            if active_record is not None:
                results.append(
                    {
                        "target_id": file_id,
                        "status": "skipped",
                        "result_code": "skipped_linked_active_record",
                        "record_id": active_record.get("record_id"),
                    }
                )
                continue

            if _table_exists(cursor, "record_files_map"):
                cursor.execute(
                    "DELETE FROM record_files_map WHERE file_id IN ({})".format(",".join("?" for _ in target_ids)),
                    tuple(target_ids),
                )
            if _table_exists(cursor, "zenodo_record_links") and _table_exists(cursor, "zenodo_records"):
                stale_record_rows = cursor.execute(
                    "SELECT record_id FROM zenodo_records WHERE source_file_id IN ({})".format(",".join("?" for _ in target_ids)),
                    tuple(target_ids),
                ).fetchall()
                stale_record_ids = [int(row["record_id"]) for row in stale_record_rows]
                if stale_record_ids:
                    cursor.execute(
                        "DELETE FROM zenodo_record_links WHERE record_id IN ({})".format(",".join("?" for _ in stale_record_ids)),
                        tuple(stale_record_ids),
                    )
                    if _table_exists(cursor, "zenodo_record_snapshots"):
                        cursor.execute(
                            "DELETE FROM zenodo_record_snapshots WHERE record_id IN ({})".format(",".join("?" for _ in stale_record_ids)),
                            tuple(stale_record_ids),
                        )
                    cursor.execute(
                        "DELETE FROM zenodo_records WHERE record_id IN ({})".format(",".join("?" for _ in stale_record_ids)),
                        tuple(stale_record_ids),
                    )
            cursor.execute(
                "DELETE FROM source_files WHERE file_id IN ({})".format(",".join("?" for _ in target_ids)),
                tuple(target_ids),
            )
            results.append(
                {
                    "target_id": file_id,
                    "status": "completed",
                    "result_code": "completed",
                    "removed_file_ids": target_ids,
                }
            )

        conn.commit()
        return {
            "success": True,
            "removed_count": sum(1 for item in results if item.get("status") == "completed"),
            "results": results,
        }
    finally:
        conn.close()


def find_hdpc_record_for_file(hdpc_path: str, file_id: str | int) -> dict[str, Any] | None:
    normalized_file_id = str(file_id).strip()
    if not normalized_file_id:
        return None
    records = read_hdpc_zenodo_records(hdpc_path, canonical_only=True)
    if not records:
        records = read_hdpc_zenodo_records(hdpc_path, canonical_only=False)
    for record in records:
        if str(record.get("source_file_id") or "").strip() == normalized_file_id:
            return record
    return None


def inspect_hdpc_project(hdpc_path: str, *, show_files: bool = True) -> dict[str, Any]:
    snapshot = _load_hdpc_snapshot(
        hdpc_path,
        include_configuration=True,
        include_scan_settings=True,
        include_file_tree=show_files,
    )
    return {
        "project_info": snapshot["project_info"],
        "configuration": snapshot["configuration"],
        "file_scan_settings": snapshot["file_scan_settings"],
        "file_tree": snapshot["file_tree"],
        "zenodo_records": snapshot["zenodo_records"],
        "published_records": snapshot["published_records"],
        "project_statistics": snapshot["project_statistics"],
    }


def get_hdpc_file_id_map(hdpc_path: str) -> dict[str, str]:
    conn = connect_hdpc(hdpc_path, readonly=True, timeout=30, row_factory=sqlite3.Row)
    try:
        cursor = conn.cursor()
        if not _table_exists(cursor, "source_files"):
            return {}
        rows = cursor.execute(
            "SELECT file_id, relative_path FROM source_files WHERE relative_path IS NOT NULL"
        ).fetchall()
        return {
            str(row["relative_path"]): str(row["file_id"])
            for row in rows
            if str(row["relative_path"] or "").strip()
        }
    finally:
        conn.close()


@serialize_project_mutation
def create_local_record_with_metadata(
    hdpc_path: str,
    *,
    file_id: str | int,
    metadata: dict[str, Any],
    is_sandbox: bool = True,
    access_token: str | None = None,
    persist_access_token: bool = False,
    record_origin: str | None = DEFAULT_RECORD_ORIGIN,
) -> dict[str, Any]:
    conn = connect_hdpc(hdpc_path, timeout=30, row_factory=sqlite3.Row)
    try:
        project_id = _ensure_local_project_schema(conn, hdpc_path)
        cursor = conn.cursor()
        payload = _normalize_payload(metadata)
        title = (
            str(payload.get("metadata", {}).get("title") or "").strip()
            or f"Record for file {file_id}"
        )

        if access_token and persist_access_token:
            token_key = "preferences.zenodo_sandbox_api_key" if is_sandbox else "preferences.zenodo_api_key"
            _upsert_project_config(cursor, project_id, token_key, access_token, "Zenodo API Key")
        sandbox_value = 1 if is_sandbox else 0
        _upsert_project_config(cursor, project_id, "main.use_sandbox", sandbox_value, "Use Zenodo Sandbox")
        _upsert_project_config(cursor, project_id, "core.use_sandbox", sandbox_value, "Use Zenodo Sandbox")

        now_iso = _utc_now_iso()
        insert_columns = [
            "project_id",
            "source_file_id",
            "record_title",
            "record_status",
            "record_metadata_json",
            "is_sandbox",
            "created_timestamp",
            "last_updated_timestamp",
            "version",
            "version_rank",
            "last_api_error",
        ]
        insert_values: list[Any] = [
            project_id,
            int(file_id),
            title,
            "prepared",
            json.dumps(payload),
            sandbox_value,
            now_iso,
            now_iso,
            "1.0.0",
            1,
            None,
        ]
        if "record_origin" in _table_columns(cursor, "zenodo_records"):
            insert_columns.append("record_origin")
            insert_values.append(normalize_hdpc_record_origin(record_origin) or DEFAULT_RECORD_ORIGIN)

        cursor.execute(
            f"""
            INSERT INTO zenodo_records (
                {", ".join(insert_columns)}
            ) VALUES ({", ".join("?" for _ in insert_columns)})
            """,
            tuple(insert_values),
        )
        local_record_id = int(cursor.lastrowid)
        cursor.execute(
            """
            INSERT INTO record_files_map (record_id, file_id, file_path, file_purpose, upload_status, upload_timestamp)
            SELECT ?, file_id, COALESCE(relative_path, filename, absolute_path), 'main', 'pending', ?
            FROM source_files
            WHERE file_id = ?
            ON CONFLICT(record_id, file_id) DO NOTHING
            """,
            (local_record_id, now_iso, int(file_id)),
        )
        cursor.execute(
            """
            UPDATE source_files
            SET status = 'metadata_ready',
                error_message = NULL,
                last_processed_timestamp = ?
            WHERE file_id = ?
            """,
            (now_iso, int(file_id)),
        )
        conn.commit()
        return {
            "success": True,
            "local_record_db_id": local_record_id,
            "message": "Record created successfully",
        }
    finally:
        conn.close()


@serialize_project_mutation
def add_local_source_files(
    hdpc_path: str,
    *,
    absolute_file_paths: list[str],
    record_id_to_associate: int | None = None,
    pipeline_name: str | None = None,
    step_name: str | None = None,
    validation_reports: dict[str, Any] | None = None,
) -> dict[str, Any]:
    conn = connect_hdpc(hdpc_path, timeout=30, row_factory=sqlite3.Row)
    try:
        project_id = _ensure_local_project_schema(conn, hdpc_path)
        cursor = conn.cursor()
        added_count = 0
        skipped_existing_path = 0
        errors_count = 0
        errors: list[str] = []
        associated_source_file_id = None
        if record_id_to_associate is not None:
            row = cursor.execute(
                "SELECT source_file_id FROM zenodo_records WHERE record_id = ?",
                (int(record_id_to_associate),),
            ).fetchone()
            associated_source_file_id = int(row[0]) if row and row[0] is not None else None

        for raw_path in absolute_file_paths or []:
            if not isinstance(raw_path, str) or not raw_path.strip():
                continue
            normalized_path = os.path.normpath(raw_path.strip())
            if not os.path.isfile(normalized_path):
                errors.append(f"Path is not a file: {raw_path}")
                errors_count += 1
                continue

            existing = cursor.execute(
                "SELECT file_id, sha256_hash FROM source_files WHERE absolute_path = ? LIMIT 1",
                (normalized_path,),
            ).fetchone()
            if existing:
                file_id = int(existing[0])
                skipped_existing_path += 1
                current_hash = _file_sha256(normalized_path)
                if str(existing[1] or "") != current_hash:
                    cursor.execute(
                        "UPDATE source_files SET sha256_hash = ?, size_bytes = ? WHERE file_id = ?",
                        (current_hash, os.path.getsize(normalized_path), file_id),
                    )
                    cursor.execute(
                        "UPDATE record_files_map SET upload_status = 'pending', upload_timestamp = NULL WHERE file_id = ? AND upload_status NOT IN ('disabled', 'removal_pending')",
                        (file_id,),
                    )
            else:
                file_type = "source" if pipeline_name in (None, "", "ingestion") else "generated"
                file_id = _get_or_create_source_file(
                    cursor,
                    project_id=project_id,
                    absolute_path=normalized_path,
                    pipeline_source=pipeline_name,
                    step_source=step_name,
                    file_type=file_type,
                    status="pending",
                )
                added_count += 1

            validation_report = None
            if isinstance(validation_reports, dict):
                validation_report = (
                    validation_reports.get(normalized_path)
                    or validation_reports.get(raw_path)
                    or validation_reports.get(os.path.basename(normalized_path))
                )
            if validation_report is not None and "validation_report_json" in _table_columns(cursor, "source_files"):
                cursor.execute(
                    """
                    UPDATE source_files
                    SET validation_report_json = ?, error_message = ?
                    WHERE file_id = ?
                    """,
                    (
                        json.dumps(validation_report, sort_keys=True),
                        _validation_error_message(validation_report),
                        file_id,
                    ),
                )

            if record_id_to_associate is not None:
                file_purpose = "main" if associated_source_file_id == file_id else "generated"
                relative_row = cursor.execute(
                    "SELECT relative_path, filename FROM source_files WHERE file_id = ?",
                    (file_id,),
                ).fetchone()
                safe_file_path = (
                    str(relative_row[0] or relative_row[1] or os.path.basename(normalized_path)).strip()
                    if relative_row
                    else os.path.basename(normalized_path)
                )
                cursor.execute(
                    """
                    INSERT INTO record_files_map (
                        record_id,
                        file_id,
                        file_path,
                        file_purpose,
                        upload_status,
                        upload_timestamp
                    ) VALUES (?, ?, ?, ?, 'pending', ?)
                    ON CONFLICT(record_id, file_id)
                    DO UPDATE SET
                        file_path = excluded.file_path,
                        file_purpose = excluded.file_purpose,
                        upload_status = CASE
                            WHEN record_files_map.upload_status = 'validation_pending_uploaded' THEN 'uploaded'
                            WHEN record_files_map.upload_status IN ('validation_pending', 'disabled', 'removal_pending') THEN 'pending'
                            ELSE record_files_map.upload_status END
                    """,
                    (
                        int(record_id_to_associate),
                        file_id,
                        safe_file_path,
                        file_purpose,
                        _utc_now_iso(),
                    ),
                )
        conn.commit()
        return {
            "success": errors_count == 0,
            "message": "File addition process completed.",
            "added_count": added_count,
            "skipped_existing_path": skipped_existing_path,
            "errors_count": errors_count,
            "errors": errors,
        }
    finally:
        conn.close()
