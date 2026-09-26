"""Native Zenodo lifecycle helpers backed directly by a local .hdpc project."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable
from urllib.parse import quote

import requests

from services.hdpc_local_service import (
    VERSIONING_RECORD_ORIGIN,
    _file_sha256,
    _guess_mime_type,
    normalize_hdpc_record_origin,
)
from services.hdpc_schema_service import connect_hdpc, ensure_hdpc_schema


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base_url(is_sandbox: bool) -> str:
    return "https://sandbox.zenodo.org" if is_sandbox else "https://zenodo.org"


def _token_from_db_or_env(cursor: sqlite3.Cursor, project_id: int, is_sandbox: bool) -> str:
    config_key = "preferences.zenodo_sandbox_api_key" if is_sandbox else "preferences.zenodo_api_key"
    row = cursor.execute(
        "SELECT config_value FROM project_configuration WHERE project_id = ? AND config_key = ? LIMIT 1",
        (project_id, config_key),
    ).fetchone()
    if row and str(row[0] or "").strip():
        return str(row[0]).strip()
    env_key = "ZENODO_SANDBOX_API_KEY" if is_sandbox else "ZENODO_API_KEY"
    token = str(os.environ.get(env_key) or "").strip()
    if token:
        return token
    raise RuntimeError(f"{env_key} is not configured")


def _resolved_access_token(
    cursor: sqlite3.Cursor,
    project_id: int,
    is_sandbox: bool,
    access_token: str | None = None,
) -> str:
    token = str(access_token or "").strip()
    if token:
        return token
    return _token_from_db_or_env(cursor, project_id, is_sandbox)


def _metadata_payload_for_draft(stored_payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(stored_payload.get("metadata"), dict):
        return {"metadata": dict(stored_payload["metadata"])}
    return {"metadata": dict(stored_payload)}


def _json_loads(raw_value: Any, fallback: Any) -> Any:
    if raw_value in (None, ""):
        return fallback
    if isinstance(raw_value, (dict, list)):
        return raw_value
    try:
        return json.loads(raw_value)
    except (TypeError, ValueError):
        return fallback


def _safe_file_path_value(relative_path: str | None, absolute_path: str | None, filename: str | None) -> str | None:
    candidate = str(relative_path or "").strip()
    if not candidate:
        candidate = str(filename or "").strip()
    if not candidate:
        candidate = str(absolute_path or "").strip()
    if not candidate:
        return None
    if os.path.isabs(candidate):
        candidate = os.path.basename(candidate)
    normalized = os.path.normpath(candidate).replace("\\", "/").lstrip("/")
    return normalized or None


def _upsert_links(cursor: sqlite3.Cursor, record_id: int, links: dict[str, Any]) -> None:
    if not isinstance(links, dict):
        return
    now_iso = _utc_now_iso()
    for rel, url in links.items():
        if not url:
            continue
        cursor.execute(
            """
            INSERT INTO zenodo_record_links (record_id, link_rel, link_url, created_timestamp, updated_timestamp)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(record_id, link_rel)
            DO UPDATE SET link_url = excluded.link_url, updated_timestamp = excluded.updated_timestamp
            """,
            (record_id, str(rel), str(url), now_iso, now_iso),
        )


def _store_snapshot(
    cursor: sqlite3.Cursor,
    record_id: int,
    stage: str,
    payload: Any,
    *,
    http_status: int | None = None,
) -> None:
    if payload is None:
        return
    cursor.execute(
        """
        INSERT INTO zenodo_record_snapshots (record_id, snapshot_stage, http_status, payload_json, created_timestamp)
        VALUES (?, ?, ?, ?, ?)
        """,
        (record_id, stage, http_status, json.dumps(payload), _utc_now_iso()),
    )


def _sync_uploaded_files(cursor: sqlite3.Cursor, record_id: int, payload: dict[str, Any]) -> None:
    files = payload.get("files")
    if not isinstance(files, list):
        return
    linked_rows = cursor.execute(
        """
        SELECT rfm.file_id, sf.filename
        FROM record_files_map rfm
        JOIN source_files sf ON sf.file_id = rfm.file_id
        WHERE rfm.record_id = ? AND rfm.upload_status = 'uploaded'
        """,
        (record_id,),
    ).fetchall()
    filename_to_file_id = {
        str(row[1]).strip().lower(): int(row[0])
        for row in linked_rows
        if str(row[1] or "").strip()
    }
    for item in files:
        if not isinstance(item, dict):
            continue
        filename = str(item.get("filename") or item.get("key") or "").strip().lower()
        if not filename:
            continue
        file_id = filename_to_file_id.get(filename)
        if not file_id:
            continue
        cursor.execute(
            """
            UPDATE record_files_map
            SET upload_status = 'uploaded',
                zenodo_file_id = COALESCE(?, zenodo_file_id),
                zenodo_file_key = COALESCE(?, zenodo_file_key),
                zenodo_file_checksum = COALESCE(?, zenodo_file_checksum),
                zenodo_file_size = COALESCE(?, zenodo_file_size),
                zenodo_file_links_json = COALESCE(?, zenodo_file_links_json),
                upload_timestamp = COALESCE(upload_timestamp, ?)
            WHERE record_id = ? AND file_id = ?
            """,
            (
                str(item.get("id") or "") or None,
                str(item.get("key") or item.get("filename") or "") or None,
                str(item.get("checksum") or "") or None,
                item.get("filesize") if item.get("filesize") is not None else None,
                json.dumps(item.get("links")) if isinstance(item.get("links"), dict) else None,
                _utc_now_iso(),
                record_id,
                file_id,
            ),
        )


def _communities_from_metadata(payload: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    communities = metadata.get("communities")
    if not isinstance(communities, list):
        return []
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in communities:
        if isinstance(item, dict):
            identifier = str(item.get("identifier") or "").strip()
            if not identifier:
                continue
            lowered = identifier.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            normalized.append({"identifier": identifier})
        elif isinstance(item, str):
            identifier = item.strip()
            if not identifier:
                continue
            lowered = identifier.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            normalized.append({"identifier": identifier})
    return normalized


def _community_identifiers(payload: dict[str, Any]) -> list[str]:
    return [str(item.get("identifier") or "").strip() for item in _communities_from_metadata(payload)]


def _metadata_with_communities(payload: dict[str, Any], community_identifiers: list[str]) -> dict[str, Any]:
    metadata_payload = _metadata_payload_for_draft(payload)
    metadata = metadata_payload.setdefault("metadata", {})
    metadata["communities"] = [{"identifier": identifier} for identifier in community_identifiers if identifier]
    return metadata_payload


def _response_payload(response: Any) -> dict[str, Any]:
    payload = _json_loads(getattr(response, "text", None), {})
    if hasattr(response, "json"):
        try:
            payload = response.json()
        except ValueError:
            pass
    return payload if isinstance(payload, dict) else {}


def _store_record_payload(
    cursor: sqlite3.Cursor,
    record_id: int,
    *,
    payload: dict[str, Any],
    record_status: str,
) -> None:
    now_iso = _utc_now_iso()
    cursor.execute(
        """
        UPDATE zenodo_records
        SET record_status = ?,
            zenodo_record_id = ?,
            zenodo_doi = ?,
            concept_rec_id = ?,
            concept_doi = ?,
            record_metadata_json = ?,
            last_api_error = NULL,
            last_updated_timestamp = ?
        WHERE record_id = ?
        """,
        (
            record_status,
            str(payload.get("id") or "") or None,
            str(payload.get("doi") or "") or None,
            str(payload.get("conceptrecid") or "") or None,
            str(payload.get("conceptdoi") or "") or None,
            json.dumps(payload),
            now_iso,
            int(record_id),
        ),
    )
    _upsert_links(cursor, int(record_id), payload.get("links", {}))


def _store_api_error(cursor: sqlite3.Cursor, record_id: int, payload: dict[str, Any], fallback_message: str) -> None:
    cursor.execute(
        "UPDATE zenodo_records SET last_api_error = ?, last_updated_timestamp = ? WHERE record_id = ?",
        (json.dumps(payload or {"error": fallback_message}), _utc_now_iso(), int(record_id)),
    )


def _prepared_payload_from_snapshot_or_draft(
    cursor: sqlite3.Cursor,
    record_id: int,
    current_payload: dict[str, Any],
) -> dict[str, Any]:
    backup_row = cursor.execute(
        """
        SELECT payload_json
        FROM zenodo_record_snapshots
        WHERE record_id = ? AND snapshot_stage = 'prepared_before_draft'
        ORDER BY snapshot_id DESC
        LIMIT 1
        """,
        (int(record_id),),
    ).fetchone()
    if backup_row:
        backup_payload = _json_loads(backup_row[0], {})
        if isinstance(backup_payload, dict) and backup_payload:
            return _metadata_payload_for_draft(backup_payload)
    return _metadata_payload_for_draft(current_payload if isinstance(current_payload, dict) else {})


def _increment_version(value: str) -> str:
    parts = str(value or "0.0.0").split(".")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    if value.startswith("v") and value[1:].isdigit():
        return f"v{int(value[1:]) + 1}"
    return f"{value}-new"


def _delete_inherited_files(
    draft_payload: dict[str, Any],
    token: str,
    *,
    http=requests,
    retain_filenames: set[str] | None = None,
) -> list[str]:
    deleted: list[str] = []
    retained = {str(item or "").strip().lower() for item in (retain_filenames or set()) if str(item or "").strip()}
    for file_obj in draft_payload.get("files", []) if isinstance(draft_payload, dict) else []:
        if not isinstance(file_obj, dict):
            continue
        delete_url = str(((file_obj.get("links") or {}).get("self")) or "").strip()
        filename = str(file_obj.get("filename") or file_obj.get("key") or "unknown")
        if filename.strip().lower() in retained:
            continue
        if not delete_url:
            continue
        response = http.delete(delete_url, params={"access_token": token}, timeout=60)
        if response.status_code not in {200, 204}:
            raise RuntimeError(f"Failed to delete inherited file '{filename}' from Zenodo draft")
        deleted.append(filename)
    return deleted


def _refresh_deposition_payload(
    cursor: sqlite3.Cursor,
    record_id: int,
    *,
    refresh_url: str,
    token: str,
    record_status: str,
    snapshot_stage: str,
    http=requests,
) -> dict[str, Any] | None:
    if not refresh_url:
        return None
    refreshed = http.get(refresh_url, params={"access_token": token}, timeout=30)
    if refreshed.status_code != 200:
        return None
    refreshed_payload = _response_payload(refreshed)
    _store_record_payload(cursor, int(record_id), payload=refreshed_payload, record_status=record_status)
    _store_snapshot(cursor, int(record_id), snapshot_stage, refreshed_payload, http_status=refreshed.status_code)
    _sync_uploaded_files(cursor, int(record_id), refreshed_payload)
    return refreshed_payload


def _register_file_set_for_version(
    cursor: sqlite3.Cursor,
    new_local_record_id: int,
    source_file_path: str,
    absolute_file_paths: list[str],
    *,
    remote_files: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    source_path = str(Path(source_file_path).resolve())
    normalized_paths: list[str] = []
    seen: set[str] = set()
    seen_upload_names: dict[str, str] = {}
    for raw_path in absolute_file_paths or []:
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        resolved = str(Path(raw_path).resolve())
        if resolved in seen or not Path(resolved).is_file():
            continue
        upload_name = Path(resolved).name.strip().lower()
        existing_path = seen_upload_names.get(upload_name)
        if upload_name and existing_path and existing_path != resolved:
            raise RuntimeError(f"Duplicate Zenodo upload filename detected: {Path(resolved).name}")
        if upload_name:
            seen_upload_names[upload_name] = resolved
        seen.add(resolved)
        normalized_paths.append(resolved)

    if source_path not in seen:
        if not Path(source_path).is_file():
            raise FileNotFoundError(f"Source file not found: {source_path}")
        upload_name = Path(source_path).name.strip().lower()
        existing_path = seen_upload_names.get(upload_name)
        if upload_name and existing_path and existing_path != source_path:
            raise RuntimeError(f"Duplicate Zenodo upload filename detected: {Path(source_path).name}")
        if upload_name:
            seen_upload_names[upload_name] = source_path
        normalized_paths.insert(0, source_path)
        seen.add(source_path)

    project_row = cursor.execute("SELECT project_id FROM project_info ORDER BY project_id ASC LIMIT 1").fetchone()
    if not project_row:
        raise RuntimeError("Project ID is not available in the .hdpc project")
    project_id = int(project_row[0])

    remote_files_by_name = {
        str(item.get("filename") or item.get("key") or "").strip().lower(): item
        for item in (remote_files or [])
        if isinstance(item, dict) and str(item.get("filename") or item.get("key") or "").strip()
    }
    existing_rows = cursor.execute(
        """
        SELECT
            rfm.file_id,
            rfm.upload_status,
            rfm.upload_timestamp,
            rfm.upload_response_json,
            rfm.zenodo_file_id,
            rfm.zenodo_file_key,
            rfm.zenodo_file_checksum,
            rfm.zenodo_file_size,
            rfm.zenodo_file_links_json,
            sf.absolute_path,
            sf.relative_path,
            sf.filename,
            sf.sha256_hash
        FROM record_files_map rfm
        JOIN source_files sf ON sf.file_id = rfm.file_id
        WHERE rfm.record_id = ?
        """,
        (int(new_local_record_id),),
    ).fetchall()
    existing_by_file_id = {int(row["file_id"]): dict(row) for row in existing_rows}

    source_file_id = None
    desired_file_ids: list[int] = []
    pending_file_count = 0
    preserved_file_count = 0
    preserved_filenames: set[str] = set()
    for file_path_str in normalized_paths:
        file_path = Path(file_path_str)
        current_size = file_path.stat().st_size
        current_hash = _file_sha256(str(file_path))
        current_mime_type = _guess_mime_type(str(file_path))
        row = cursor.execute(
            "SELECT file_id, relative_path, filename, sha256_hash FROM source_files WHERE absolute_path = ? LIMIT 1",
            (str(file_path),),
        ).fetchone()
        if row:
            file_id = int(row[0])
            safe_file_path = _safe_file_path_value(row[1], str(file_path), row[2])
            stored_hash = str(row[3] or "").strip()
            cursor.execute(
                """
                UPDATE source_files
                SET relative_path = ?,
                    filename = ?,
                    size_bytes = ?,
                    sha256_hash = ?,
                    mime_type = ?,
                    file_type = ?,
                    status = COALESCE(status, 'pending')
                WHERE file_id = ?
                """,
                (
                    file_path.name,
                    file_path.name,
                    current_size,
                    current_hash,
                    current_mime_type,
                    "source" if str(file_path) == source_path else "derived",
                    file_id,
                ),
            )
        else:
            cursor.execute(
                """
                INSERT INTO source_files (
                    project_id, absolute_path, relative_path, filename, size_bytes, sha256_hash,
                    mime_type, file_type, status, added_timestamp, pipeline_source, step_source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    str(file_path),
                    file_path.name,
                    file_path.name,
                    current_size,
                    current_hash,
                    current_mime_type,
                    "source" if str(file_path) == source_path else "derived",
                    "pending",
                    _utc_now_iso(),
                    "versioning",
                    "new_version_sync",
                ),
            )
            file_id = int(cursor.lastrowid)
            safe_file_path = file_path.name
            stored_hash = current_hash

        file_purpose = "main" if str(file_path) == source_path else "derived"
        desired_file_ids.append(file_id)
        existing_mapping = existing_by_file_id.get(file_id) or {}
        remote_filename_key = file_path.name.strip().lower()
        remote_file = remote_files_by_name.get(remote_filename_key)
        preserve_uploaded_file = bool(
            existing_mapping
            and str(existing_mapping.get("upload_status") or "").strip().lower() == "uploaded"
            and remote_file
            and str(stored_hash or "").strip()
            and str(stored_hash or "").strip() == str(current_hash or "").strip()
        )
        if preserve_uploaded_file:
            preserved_file_count += 1
            preserved_filenames.add(remote_filename_key)
            cursor.execute(
                """
                UPDATE record_files_map
                SET file_path = ?,
                    file_purpose = ?,
                    upload_status = 'uploaded',
                    upload_error = NULL,
                    zenodo_file_id = COALESCE(?, zenodo_file_id),
                    zenodo_file_key = COALESCE(?, zenodo_file_key),
                    zenodo_file_checksum = COALESCE(?, zenodo_file_checksum),
                    zenodo_file_size = COALESCE(?, zenodo_file_size),
                    zenodo_file_links_json = COALESCE(?, zenodo_file_links_json)
                WHERE record_id = ? AND file_id = ?
                """,
                (
                    safe_file_path,
                    file_purpose,
                    str(remote_file.get("id") or "") or None,
                    str(remote_file.get("key") or remote_file.get("filename") or "") or None,
                    str(remote_file.get("checksum") or "") or None,
                    remote_file.get("filesize") if remote_file.get("filesize") is not None else None,
                    json.dumps(remote_file.get("links")) if isinstance(remote_file.get("links"), dict) else None,
                    int(new_local_record_id),
                    file_id,
                ),
            )
        else:
            pending_file_count += 1
            cursor.execute(
                """
                INSERT INTO record_files_map (
                    record_id, file_id, file_path, file_purpose, upload_status, upload_timestamp,
                    upload_error, upload_response_json, zenodo_file_id, zenodo_file_key,
                    zenodo_file_checksum, zenodo_file_size, zenodo_file_links_json
                ) VALUES (?, ?, ?, ?, 'pending', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
                ON CONFLICT(record_id, file_id)
                DO UPDATE SET
                    file_path = excluded.file_path,
                    file_purpose = excluded.file_purpose,
                    upload_status = 'pending',
                    upload_timestamp = NULL,
                    upload_error = NULL,
                    upload_response_json = NULL,
                    zenodo_file_id = NULL,
                    zenodo_file_key = NULL,
                    zenodo_file_checksum = NULL,
                    zenodo_file_size = NULL,
                    zenodo_file_links_json = NULL
                """,
                (int(new_local_record_id), file_id, safe_file_path, file_purpose),
            )
        if str(file_path) == source_path:
            source_file_id = file_id

    if source_file_id is None:
        raise RuntimeError("Could not determine the source file entry for the new version")

    if desired_file_ids:
        placeholders = ", ".join("?" for _ in desired_file_ids)
        cursor.execute(
            f"DELETE FROM record_files_map WHERE record_id = ? AND file_id NOT IN ({placeholders})",
            (int(new_local_record_id), *desired_file_ids),
        )
    else:
        cursor.execute("DELETE FROM record_files_map WHERE record_id = ?", (int(new_local_record_id),))

    cursor.execute(
        "UPDATE zenodo_records SET source_file_id = ?, last_updated_timestamp = ? WHERE record_id = ?",
        (source_file_id, _utc_now_iso(), int(new_local_record_id)),
    )

    return {
        "source_file_id": source_file_id,
        "registered_file_count": len(normalized_paths),
        "absolute_file_paths": normalized_paths,
        "pending_file_count": pending_file_count,
        "preserved_file_count": preserved_file_count,
        "preserved_filenames": sorted(preserved_filenames),
    }


def prepare_new_version_draft(
    hdpc_path: str,
    *,
    concept_rec_id: str,
    is_sandbox: bool,
    source_file_path: str,
    absolute_file_paths: list[str],
    access_token: str | None = None,
    reference_record: dict[str, Any] | None = None,
    http=requests,
) -> Dict[str, Any]:
    conn = connect_hdpc(hdpc_path, timeout=30, row_factory=sqlite3.Row)
    try:
        project_id = ensure_hdpc_schema(conn, hdpc_path)
        cursor = conn.cursor()
        token = _resolved_access_token(cursor, project_id, is_sandbox, access_token)

        existing_draft = cursor.execute(
            """
            SELECT record_id, record_metadata_json
            FROM zenodo_records
            WHERE concept_rec_id = ? AND record_status = 'draft' AND is_sandbox = ?
            ORDER BY record_id DESC
            LIMIT 1
            """,
            (str(concept_rec_id), 1 if is_sandbox else 0),
        ).fetchone()

        if existing_draft:
            new_local_record_id = int(existing_draft["record_id"])
            draft_payload = _json_loads(existing_draft["record_metadata_json"], {})
            refresh_url = str(
                ((draft_payload.get("links") or {}).get("self"))
                or ((draft_payload.get("links") or {}).get("latest_draft"))
                or ""
            ).strip()
            refreshed_payload = (
                _refresh_deposition_payload(
                    cursor,
                    new_local_record_id,
                    refresh_url=refresh_url,
                    token=token,
                    record_status="draft",
                    snapshot_stage="existing_version_draft_refreshed",
                    http=http,
                )
                if refresh_url
                else None
            )
            if refreshed_payload:
                draft_payload = refreshed_payload
        else:
            latest_published = cursor.execute(
                """
                SELECT *
                FROM zenodo_records
                WHERE concept_rec_id = ? AND record_status = 'published' AND is_sandbox = ?
                ORDER BY COALESCE(last_updated_timestamp, created_timestamp) DESC, record_id DESC
                LIMIT 1
                """,
                (str(concept_rec_id), 1 if is_sandbox else 0),
            ).fetchone()

            reference_payload = {}
            reference_version_rank = 0
            reference_title = ""
            previous_record_id = None
            if latest_published is not None:
                reference_payload = _json_loads(latest_published["record_metadata_json"], {})
                reference_version_rank = int(latest_published["version_rank"] or 0)
                reference_title = str(latest_published["record_title"] or "").strip()
                previous_record_id = int(latest_published["record_id"])
            elif isinstance(reference_record, dict):
                reference_payload = (
                    reference_record.get("record_metadata")
                    if isinstance(reference_record.get("record_metadata"), dict)
                    else {}
                )
                reference_version_rank = int(reference_record.get("version_rank") or 0)
                reference_title = str(reference_record.get("record_title") or "").strip()
            else:
                return {"success": False, "error": f"No published record found for concept ID {concept_rec_id}."}

            new_version_url = str(((reference_payload.get("links") or {}).get("newversion")) or "").strip()
            if not new_version_url:
                return {"success": False, "error": f"Could not find 'newversion' link for concept ID {concept_rec_id}."}

            response = http.post(new_version_url, params={"access_token": token}, json={}, timeout=60)
            new_version_payload = _response_payload(response)
            if response.status_code not in {200, 201, 202}:
                return {
                    "success": False,
                    "error": str(
                        new_version_payload.get("message")
                        or getattr(response, "text", "")
                        or "Zenodo new version draft failed"
                    ),
                }

            latest_draft_url = str(((new_version_payload.get("links") or {}).get("latest_draft")) or "").strip()
            if latest_draft_url:
                draft_response = http.get(latest_draft_url, params={"access_token": token}, timeout=60)
                draft_payload = _response_payload(draft_response)
                if draft_response.status_code not in {200, 201}:
                    return {
                        "success": False,
                        "error": str(
                            draft_payload.get("message")
                            or getattr(draft_response, "text", "")
                            or "Zenodo latest_draft fetch failed"
                        ),
                    }
            else:
                draft_payload = new_version_payload

            update_url = str(
                ((draft_payload.get("links") or {}).get("self"))
                or ((draft_payload.get("links") or {}).get("latest_draft"))
                or ""
            ).strip()
            if not update_url:
                return {"success": False, "error": "New version draft is missing the update link."}

            metadata = dict(draft_payload.get("metadata") or {})
            metadata["version"] = _increment_version(str((reference_payload.get("metadata") or {}).get("version") or "0.0.0"))
            update_response = http.put(
                update_url,
                params={"access_token": token},
                json={"metadata": metadata},
                timeout=60,
            )
            draft_payload = _response_payload(update_response)
            if update_response.status_code not in {200, 201}:
                return {
                    "success": False,
                    "error": str(
                        draft_payload.get("message")
                        or getattr(update_response, "text", "")
                        or "Zenodo draft version update failed"
                    ),
                }

            now_iso = _utc_now_iso()
            insert_columns = [
                "project_id",
                "source_file_id",
                "record_status",
                "is_sandbox",
                "zenodo_record_id",
                "zenodo_doi",
                "concept_rec_id",
                "concept_doi",
                "version",
                "version_rank",
                "previous_record_id",
                "record_title",
                "record_metadata_json",
                "created_timestamp",
                "last_updated_timestamp",
                "creation_api_response",
                "last_api_error",
            ]
            insert_values: list[Any] = [
                project_id,
                None,
                "draft",
                1 if is_sandbox else 0,
                str(draft_payload.get("id") or "") or None,
                str(draft_payload.get("doi") or "") or None,
                str(draft_payload.get("conceptrecid") or concept_rec_id),
                str(draft_payload.get("conceptdoi") or "") or None,
                str((draft_payload.get("metadata") or {}).get("version") or ""),
                max(reference_version_rank, 1) + 1,
                previous_record_id,
                str((draft_payload.get("metadata") or {}).get("title") or reference_title or ""),
                json.dumps(draft_payload),
                now_iso,
                now_iso,
                json.dumps(draft_payload),
                None,
            ]
            if "record_origin" in {str(item[1]) for item in cursor.execute("PRAGMA table_info(zenodo_records)").fetchall()}:
                insert_columns.append("record_origin")
                insert_values.append(normalize_hdpc_record_origin(VERSIONING_RECORD_ORIGIN) or VERSIONING_RECORD_ORIGIN)
            cursor.execute(
                f"""
                INSERT INTO zenodo_records (
                    {", ".join(insert_columns)}
                ) VALUES ({", ".join("?" for _ in insert_columns)})
                """,
                tuple(insert_values),
            )
            new_local_record_id = int(cursor.lastrowid)
            _upsert_links(cursor, new_local_record_id, draft_payload.get("links", {}))
            _store_snapshot(
                cursor,
                new_local_record_id,
                "new_version_draft_created",
                draft_payload,
                http_status=update_response.status_code,
            )
            conn.commit()

        registration = _register_file_set_for_version(
            cursor,
            new_local_record_id,
            source_file_path,
            absolute_file_paths,
            remote_files=draft_payload.get("files") if isinstance(draft_payload, dict) else None,
        )
        conn.commit()

        refreshed = cursor.execute(
            """
            SELECT record_metadata_json, record_status, zenodo_record_id, zenodo_doi, version
            FROM zenodo_records
            WHERE record_id = ?
            """,
            (new_local_record_id,),
        ).fetchone()
        refreshed_payload = _json_loads(refreshed["record_metadata_json"], {}) if refreshed else {}
        return {
            "success": True,
            "new_local_record_id": new_local_record_id,
            "local_record_db_id": new_local_record_id,
            "registered_file_count": registration["registered_file_count"],
            "pending_file_count": int(registration.get("pending_file_count") or 0),
            "preserved_file_count": int(registration.get("preserved_file_count") or 0),
            "record_status": refreshed["record_status"] if refreshed else None,
            "zenodo_record_id": refreshed["zenodo_record_id"] if refreshed else None,
            "zenodo_doi": refreshed["zenodo_doi"] if refreshed else None,
            "version": refreshed["version"] if refreshed else None,
            "zenodo_response": refreshed_payload,
            "message": "Zenodo version draft prepared successfully.",
        }
    finally:
        conn.close()


def create_api_draft(
    hdpc_path: str,
    local_record_id: int,
    *,
    access_token: str | None = None,
    http=requests,
) -> Dict[str, Any]:
    conn = connect_hdpc(hdpc_path, timeout=30, row_factory=sqlite3.Row)
    try:
        project_id = ensure_hdpc_schema(conn, hdpc_path)
        cursor = conn.cursor()
        row = cursor.execute(
            """
            SELECT zr.record_id, zr.is_sandbox, zr.record_metadata_json,
                   zr.record_status, zr.zenodo_record_id
            FROM zenodo_records zr
            WHERE zr.record_id = ?
            """,
            (int(local_record_id),),
        ).fetchone()
        if not row:
            return {"success": False, "error": f"Record {local_record_id} not found"}

        is_sandbox = bool(row["is_sandbox"])
        token = _resolved_access_token(cursor, project_id, is_sandbox, access_token)
        stored_payload = _json_loads(row["record_metadata_json"], {})
        existing_id = str(row["zenodo_record_id"] or "").strip()
        if existing_id:
            if row["record_status"] != "draft":
                return {"success": False, "error": "An existing record must be edited through its draft or version workflow."}
            response = http.get(
                f"{_base_url(is_sandbox)}/api/deposit/depositions/{existing_id}",
                params={"access_token": token}, timeout=120,
            )
            if response.status_code != 200:
                return {"success": False, "error": "The existing Zenodo draft could not be retrieved. Retry after checking its availability."}
            payload = response.json()
            if payload.get("submitted") or payload.get("state") == "done":
                return {"success": False, "error": "The Zenodo record is already submitted; create a new version to change its files."}
            remote_names = {
                str(item.get("filename") or item.get("key") or "")
                for item in payload.get("files", [])
            }
            for mapped in cursor.execute(
                """SELECT rfm.file_id, sf.filename FROM record_files_map rfm
                   JOIN source_files sf ON sf.file_id = rfm.file_id
                   WHERE rfm.record_id = ? AND rfm.upload_status = 'uploaded'""",
                (int(local_record_id),),
            ).fetchall():
                if mapped["filename"] not in remote_names:
                    cursor.execute(
                        """UPDATE record_files_map SET upload_status = 'pending', upload_timestamp = NULL
                           WHERE record_id = ? AND file_id = ?""",
                        (int(local_record_id), mapped["file_id"]),
                    )
            _store_record_payload(cursor, int(local_record_id), payload=payload, record_status="draft")
            _store_snapshot(cursor, int(local_record_id), "draft_reused", payload, http_status=200)
            conn.commit()
            return {"success": True, "message": "Existing Zenodo draft reused.",
                    "local_record_db_id": int(local_record_id), "zenodo_response": payload}
        _store_snapshot(cursor, int(local_record_id), "prepared_before_draft", stored_payload)
        response = http.post(
            f"{_base_url(is_sandbox)}/api/deposit/depositions",
            params={"access_token": token},
            json=_metadata_payload_for_draft(stored_payload),
            timeout=120,
        )
        response_payload = _json_loads(getattr(response, "text", None), {})
        if hasattr(response, "json"):
            try:
                response_payload = response.json()
            except ValueError:
                pass

        if response.status_code not in {200, 201}:
            cursor.execute(
                "UPDATE zenodo_records SET last_api_error = ?, last_updated_timestamp = ? WHERE record_id = ?",
                (json.dumps(response_payload or {"error": getattr(response, "text", "")}), _utc_now_iso(), int(local_record_id)),
            )
            conn.commit()
            return {
                "success": False,
                "error": str((response_payload or {}).get("message") or getattr(response, "text", "") or "Zenodo draft creation failed"),
                "zenodo_response": response_payload,
            }

        now_iso = _utc_now_iso()
        cursor.execute(
            """
            UPDATE zenodo_records
            SET record_status = 'draft',
                zenodo_record_id = ?,
                zenodo_doi = ?,
                concept_rec_id = ?,
                concept_doi = ?,
                record_metadata_json = ?,
                creation_api_response = ?,
                last_api_error = NULL,
                last_updated_timestamp = ?
            WHERE record_id = ?
            """,
            (
                str(response_payload.get("id") or "") or None,
                str(response_payload.get("doi") or "") or None,
                str(response_payload.get("conceptrecid") or "") or None,
                str(response_payload.get("conceptdoi") or "") or None,
                json.dumps(response_payload),
                json.dumps(response_payload),
                now_iso,
                int(local_record_id),
            ),
        )
        _upsert_links(cursor, int(local_record_id), response_payload.get("links", {}))
        _store_snapshot(cursor, int(local_record_id), "draft_created", response_payload, http_status=response.status_code)
        cursor.execute(
            "UPDATE record_files_map SET upload_status = 'pending', upload_timestamp = NULL WHERE record_id = ?",
            (int(local_record_id),),
        )
        conn.commit()
        return {
            "success": True,
            "message": "Zenodo draft record created successfully.",
            "local_record_db_id": int(local_record_id),
            "zenodo_response": response_payload,
        }
    finally:
        conn.close()


def discard_draft(
    hdpc_path: str,
    local_record_id: int,
    *,
    access_token: str | None = None,
    http=requests,
) -> Dict[str, Any]:
    conn = connect_hdpc(hdpc_path, timeout=30, row_factory=sqlite3.Row)
    try:
        project_id = ensure_hdpc_schema(conn, hdpc_path)
        cursor = conn.cursor()
        row = cursor.execute(
            """
            SELECT record_id, is_sandbox, record_status, record_title, version, record_metadata_json
            FROM zenodo_records
            WHERE record_id = ?
            """,
            (int(local_record_id),),
        ).fetchone()
        if not row:
            return {"success": False, "error": f"Record {local_record_id} not found", "error_code": "not_found"}

        status = str(row["record_status"] or "").strip().lower()
        if status != "draft":
            return {
                "success": False,
                "error": f"Record {local_record_id} is not an active draft",
                "error_code": "invalid_state",
            }

        current_payload = _json_loads(row["record_metadata_json"], {})
        prepared_payload = _prepared_payload_from_snapshot_or_draft(cursor, int(local_record_id), current_payload)
        prepared_metadata = (
            prepared_payload.get("metadata")
            if isinstance(prepared_payload.get("metadata"), dict)
            else {}
        )
        restored_title = str(prepared_metadata.get("title") or row["record_title"] or "").strip() or f"Record {local_record_id}"
        restored_version = str(prepared_metadata.get("version") or row["version"] or "1.0.0").strip() or "1.0.0"

        remote_discard = {
            "attempted": False,
            "success": False,
            "status_code": None,
            "message": "",
        }
        discard_url = ""
        if isinstance(current_payload, dict):
            discard_url = str(((current_payload.get("links") or {}).get("discard")) or "").strip()

        if discard_url:
            remote_discard["attempted"] = True
            try:
                token = _resolved_access_token(cursor, project_id, bool(row["is_sandbox"]), access_token)
                response = http.post(discard_url, params={"access_token": token}, timeout=120)
                remote_discard["status_code"] = int(getattr(response, "status_code", 0) or 0) or None
                response_payload = _response_payload(response)
                _store_snapshot(
                    cursor,
                    int(local_record_id),
                    "draft_discard_remote",
                    response_payload or {"status_code": remote_discard["status_code"]},
                    http_status=remote_discard["status_code"],
                )
                if remote_discard["status_code"] in {200, 201, 202, 204}:
                    remote_discard["success"] = True
                else:
                    remote_discard["message"] = str(
                        response_payload.get("message")
                        or getattr(response, "text", "")
                        or "Zenodo draft discard failed"
                    )
            except Exception as exc:
                remote_discard["message"] = str(exc)
        else:
            remote_discard["message"] = "Draft payload has no discard link; applying local rollback only."

        now_iso = _utc_now_iso()
        cursor.execute(
            """
            UPDATE zenodo_records
            SET record_status = 'prepared',
                record_title = ?,
                version = ?,
                record_metadata_json = ?,
                zenodo_record_id = NULL,
                zenodo_doi = NULL,
                concept_rec_id = NULL,
                concept_doi = NULL,
                creation_api_response = NULL,
                last_api_error = NULL,
                last_updated_timestamp = ?
            WHERE record_id = ?
            """,
            (
                restored_title,
                restored_version,
                json.dumps(prepared_payload),
                now_iso,
                int(local_record_id),
            ),
        )
        cursor.execute("DELETE FROM zenodo_record_links WHERE record_id = ?", (int(local_record_id),))
        cursor.execute(
            """
            UPDATE record_files_map
            SET upload_status = 'pending',
                upload_timestamp = NULL,
                upload_error = NULL,
                upload_response_json = NULL,
                zenodo_file_id = NULL,
                zenodo_file_key = NULL,
                zenodo_file_checksum = NULL,
                zenodo_file_size = NULL,
                zenodo_file_links_json = NULL
            WHERE record_id = ?
            """,
            (int(local_record_id),),
        )
        _store_snapshot(
            cursor,
            int(local_record_id),
            "draft_discarded_local_restore",
            {
                "restored_payload": prepared_payload,
                "remote_discard": remote_discard,
            },
        )
        conn.commit()
        return {
            "success": True,
            "message": "Draft discarded and local metadata restored.",
            "record_id": int(local_record_id),
            "restored_status": "prepared",
            "remote_discard": remote_discard,
        }
    finally:
        conn.close()


def publish_record(
    hdpc_path: str,
    local_record_id: int,
    *,
    access_token: str | None = None,
    http=requests,
) -> Dict[str, Any]:
    if os.environ.get("ZENODO_PUBLISH_ENABLED", "true").lower() not in {"true", "1", "yes", "on"}:
        return {"success": False, "error": "Zenodo publication is disabled by this deployment"}
    conn = connect_hdpc(hdpc_path, timeout=30, row_factory=sqlite3.Row)
    try:
        project_id = ensure_hdpc_schema(conn, hdpc_path)
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT is_sandbox, record_metadata_json FROM zenodo_records WHERE record_id = ?",
            (int(local_record_id),),
        ).fetchone()
        if not row:
            return {"success": False, "error": f"Record {local_record_id} not found"}
        is_sandbox = bool(row["is_sandbox"])
        token = _resolved_access_token(cursor, project_id, is_sandbox, access_token)
        payload = _json_loads(row["record_metadata_json"], {})
        publish_url = ((payload.get("links") or {}).get("publish") if isinstance(payload, dict) else None) or ""
        deposition_id = str(payload.get("id") or payload.get("record_id") or "").strip()
        if not publish_url:
            return {"success": False, "error": "Publish link missing in stored Zenodo draft"}

        response = http.post(publish_url, params={"access_token": token}, timeout=120)
        response_payload = _json_loads(getattr(response, "text", None), {})
        if hasattr(response, "json"):
            try:
                response_payload = response.json()
            except ValueError:
                pass

        if response.status_code == 500 and deposition_id:
            recheck = http.get(
                f"{_base_url(is_sandbox)}/api/records/{deposition_id}",
                params={"access_token": token},
                timeout=30,
            )
            if recheck.status_code == 200:
                try:
                    response_payload = recheck.json()
                except ValueError:
                    response_payload = {}
                response = recheck

        if response.status_code not in {200, 202}:
            cursor.execute(
                "UPDATE zenodo_records SET last_api_error = ?, last_updated_timestamp = ? WHERE record_id = ?",
                (json.dumps(response_payload or {"error": getattr(response, "text", "")}), _utc_now_iso(), int(local_record_id)),
            )
            conn.commit()
            return {
                "success": False,
                "error": str((response_payload or {}).get("message") or getattr(response, "text", "") or "Zenodo publish failed"),
                "zenodo_response": response_payload,
            }

        now_iso = _utc_now_iso()
        cursor.execute(
            """
            UPDATE zenodo_records
            SET record_status = 'published',
                zenodo_record_id = ?,
                zenodo_doi = ?,
                concept_rec_id = ?,
                concept_doi = ?,
                record_metadata_json = ?,
                last_publish_api_response = ?,
                last_api_error = NULL,
                last_updated_timestamp = ?
            WHERE record_id = ?
            """,
            (
                str(response_payload.get("id") or "") or None,
                str(response_payload.get("doi") or "") or None,
                str(response_payload.get("conceptrecid") or "") or None,
                str(response_payload.get("conceptdoi") or "") or None,
                json.dumps(response_payload),
                json.dumps(response_payload),
                now_iso,
                int(local_record_id),
            ),
        )
        _upsert_links(cursor, int(local_record_id), response_payload.get("links", {}))
        _store_snapshot(cursor, int(local_record_id), "publish_completed", response_payload, http_status=response.status_code)
        _sync_uploaded_files(cursor, int(local_record_id), response_payload if isinstance(response_payload, dict) else {})
        conn.commit()
        return {
            "success": True,
            "message": "Zenodo record published successfully.",
            "local_record_db_id": int(local_record_id),
            "zenodo_response": response_payload,
        }
    finally:
        conn.close()


def upload_files_for_deposition(
    hdpc_path: str,
    local_record_id: int,
    *,
    publish: bool = False,
    refresh_remote_state: bool = False,
    prune_inherited_files: bool = False,
    access_token: str | None = None,
    http=requests,
) -> Dict[str, Any]:
    conn = connect_hdpc(hdpc_path, timeout=30, row_factory=sqlite3.Row)
    try:
        project_id = ensure_hdpc_schema(conn, hdpc_path)
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT is_sandbox, record_metadata_json FROM zenodo_records WHERE record_id = ?",
            (int(local_record_id),),
        ).fetchone()
        if not row:
            return {"success": False, "error": f"Record {local_record_id} not found"}
        is_sandbox = bool(row["is_sandbox"])
        token = _resolved_access_token(cursor, project_id, is_sandbox, access_token)
        payload = _json_loads(row["record_metadata_json"], {})
        links = payload.get("links") if isinstance(payload, dict) else {}
        bucket_url = str((links or {}).get("bucket") or "").strip()
        refresh_url = str((links or {}).get("self") or "").strip()
        if not bucket_url:
            return {"success": False, "error": "Bucket URL not found in stored Zenodo draft"}

        deleted_inherited_files: list[str] = []
        if prune_inherited_files:
            retain_rows = cursor.execute(
                """
                SELECT COALESCE(sf.filename, rfm.file_path) AS filename
                FROM record_files_map rfm
                LEFT JOIN source_files sf ON sf.file_id = rfm.file_id
                WHERE rfm.record_id = ?
                """,
                (int(local_record_id),),
            ).fetchall()
            retain_filenames = {
                os.path.basename(str(row["filename"] or "")).strip()
                for row in retain_rows
                if str(row["filename"] or "").strip()
            }
            deleted_inherited_files = _delete_inherited_files(
                payload,
                token,
                http=http,
                retain_filenames=retain_filenames,
            )
            refresh_remote_state = refresh_remote_state or bool(deleted_inherited_files)

        pending_rows = cursor.execute(
            """
            SELECT rfm.file_id, sf.absolute_path, sf.filename, sf.pipeline_source, sf.validation_report_json
            FROM record_files_map rfm
            JOIN source_files sf ON sf.file_id = rfm.file_id
            WHERE rfm.record_id = ? AND rfm.upload_status IN ('pending', 'upload_error')
            ORDER BY rfm.map_id ASC
            """,
            (int(local_record_id),),
        ).fetchall()
        if not pending_rows:
            refreshed_payload = None
            if refresh_remote_state and refresh_url:
                refreshed_payload = _refresh_deposition_payload(
                    cursor,
                    int(local_record_id),
                    refresh_url=refresh_url,
                    token=token,
                    record_status="draft",
                    snapshot_stage="upload_refreshed",
                    http=http,
                )
                conn.commit()
            return {
                "success": True,
                "message": "No pending files to upload." if refreshed_payload is None else "No pending files to upload. Draft state refreshed.",
                "log": [],
                "uploaded_file_count": 0,
                "failed_upload_count": 0,
                "deleted_inherited_files": deleted_inherited_files,
            }

        log_messages: list[str] = []
        success_count = 0
        error_count = 0
        for file_row in pending_rows:
            file_path = Path(str(file_row["absolute_path"]))
            try:
                with open(file_path, "rb") as handle:
                    if file_row["pipeline_source"] == "lod_generation":
                        from services.lod_reliability import digest
                        report = _json_loads(file_row["validation_report_json"], {})
                        if report.get("valid") is not True or report.get("sha256") != digest(handle.read()):
                            raise ValueError("Metadata upload blocked: validation is missing, failed, or the file changed. Regenerate this format.")
                        from flask import current_app, has_app_context
                        if has_app_context() and current_app.config.get("LOCAL_EDM_VALIDATOR_REQUIRED") and (report.get("standard") == "edm" or file_path.name == "edm.xml"):
                            if ((report.get("details") or {}).get("remote") or {}).get("valid") is not True:
                                raise ValueError("Metadata upload blocked: required Local EDM Validator checks are missing. Retry generation.")
                        handle.seek(0)
                    response = http.put(
                        f"{bucket_url}/{quote(file_path.name, safe='')}",
                        params={"access_token": token},
                        data=handle,
                        timeout=300,
                    )
                response_payload = _json_loads(getattr(response, "text", None), {})
                if hasattr(response, "json"):
                    try:
                        response_payload = response.json()
                    except ValueError:
                        pass
                if response.status_code not in {200, 201}:
                    error_count += 1
                    log_messages.append(f"ERROR uploading '{file_path.name}'")
                    cursor.execute(
                        """
                        UPDATE record_files_map
                        SET upload_status = 'upload_error',
                            upload_error = ?,
                            upload_response_json = ?
                        WHERE record_id = ? AND file_id = ?
                        """,
                        (
                            str(getattr(response, "text", "") or response_payload),
                            json.dumps(response_payload),
                            int(local_record_id),
                            int(file_row["file_id"]),
                        ),
                    )
                    continue
                success_count += 1
                log_messages.append(f"Uploaded '{file_path.name}'")
                cursor.execute(
                    """
                    UPDATE record_files_map
                    SET upload_status = 'uploaded',
                        upload_timestamp = ?,
                        upload_error = NULL,
                        upload_response_json = ?,
                        zenodo_file_id = COALESCE(?, zenodo_file_id),
                        zenodo_file_key = COALESCE(?, zenodo_file_key),
                        zenodo_file_checksum = COALESCE(?, zenodo_file_checksum),
                        zenodo_file_size = COALESCE(?, zenodo_file_size),
                        zenodo_file_links_json = COALESCE(?, zenodo_file_links_json)
                    WHERE record_id = ? AND file_id = ?
                    """,
                    (
                        _utc_now_iso(),
                        json.dumps(response_payload),
                        str(response_payload.get("id") or "") or None,
                        str(response_payload.get("key") or file_path.name) or None,
                        str(response_payload.get("checksum") or "") or None,
                        response_payload.get("filesize") if response_payload.get("filesize") is not None else None,
                        json.dumps(response_payload.get("links")) if isinstance(response_payload.get("links"), dict) else None,
                        int(local_record_id),
                        int(file_row["file_id"]),
                    ),
                )
            except Exception as exc:
                error_count += 1
                log_messages.append(f"EXCEPTION during upload of '{file_path.name}': {exc}")
                cursor.execute(
                    """
                    UPDATE record_files_map
                    SET upload_status = 'upload_error',
                        upload_error = ?,
                        upload_response_json = ?
                    WHERE record_id = ? AND file_id = ?
                    """,
                    (str(exc), json.dumps({"error": str(exc)}), int(local_record_id), int(file_row["file_id"])),
                )

        if refresh_url and (success_count or refresh_remote_state):
            _refresh_deposition_payload(
                cursor,
                int(local_record_id),
                refresh_url=refresh_url,
                token=token,
                record_status="draft",
                snapshot_stage="upload_refreshed",
                http=http,
            )

        conn.commit()
        result = {
            "success": error_count == 0,
            "message": f"Upload process finished. {success_count} succeeded, {error_count} failed.",
            "log": log_messages,
            "uploaded_file_count": success_count,
            "failed_upload_count": error_count,
            "deleted_inherited_files": deleted_inherited_files,
        }
        if publish and error_count == 0:
            publication = publish_record(hdpc_path, int(local_record_id), access_token=access_token, http=http)
            result["publication"] = publication
            result["published"] = publication.get("success", False)
            if not publication.get("success", False):
                result["success"] = False
        return result
    finally:
        conn.close()


def append_community_to_record(
    hdpc_path: str,
    local_record_id: int,
    community_identifier: str,
    *,
    access_token: str | None = None,
    http=requests,
) -> Dict[str, Any]:
    identifier = str(community_identifier or "").strip()
    if not identifier:
        return {
            "success": False,
            "result": {
                "status": "failed",
                "message": "community_identifier is required",
                "communities_after": None,
                "rate_limited_waits": 0,
            },
        }

    conn = connect_hdpc(hdpc_path, timeout=30, row_factory=sqlite3.Row)
    try:
        project_id = ensure_hdpc_schema(conn, hdpc_path)
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT record_status, is_sandbox, record_metadata_json FROM zenodo_records WHERE record_id = ?",
            (int(local_record_id),),
        ).fetchone()
        if not row:
            return {
                "success": False,
                "result": {
                    "status": "failed",
                    "message": f"Record {local_record_id} not found",
                    "communities_after": None,
                    "rate_limited_waits": 0,
                },
            }

        payload = _json_loads(row["record_metadata_json"], {})
        before = _community_identifiers(payload)
        if identifier.lower() in {item.lower() for item in before}:
            return {
                "success": True,
                "result": {
                    "status": "unchanged",
                    "message": f"Community '{identifier}' already linked to record.",
                    "communities_before": before,
                    "communities_after": before,
                    "rate_limited_waits": 0,
                    "zenodo_response": payload,
                },
            }

        after = before + [identifier]
        return _update_record_communities(
            cursor,
            project_id,
            int(local_record_id),
            str(row["record_status"] or "").strip().lower(),
            bool(row["is_sandbox"]),
            payload,
            communities_before=before,
            communities_after=after,
            access_token=access_token,
            http=http,
        )
    finally:
        conn.close()


def remove_community_from_record(
    hdpc_path: str,
    local_record_id: int,
    community_identifier: str | None = None,
    *,
    remove_all: bool = False,
    access_token: str | None = None,
    http=requests,
) -> Dict[str, Any]:
    conn = connect_hdpc(hdpc_path, timeout=30, row_factory=sqlite3.Row)
    try:
        project_id = ensure_hdpc_schema(conn, hdpc_path)
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT record_status, is_sandbox, record_metadata_json FROM zenodo_records WHERE record_id = ?",
            (int(local_record_id),),
        ).fetchone()
        if not row:
            return {
                "success": False,
                "result": {
                    "status": "failed",
                    "message": f"Record {local_record_id} not found",
                    "communities_after": None,
                    "rate_limited_waits": 0,
                },
            }

        payload = _json_loads(row["record_metadata_json"], {})
        before = _community_identifiers(payload)
        if remove_all:
            after: list[str] = []
            if not before:
                return {
                    "success": True,
                    "result": {
                        "status": "unchanged",
                        "message": "Record has no communities to remove.",
                        "communities_before": before,
                        "communities_after": before,
                        "rate_limited_waits": 0,
                        "zenodo_response": payload,
                    },
                }
        else:
            identifier = str(community_identifier or "").strip()
            if not identifier:
                return {
                    "success": False,
                    "result": {
                        "status": "failed",
                        "message": "community_identifier is required",
                        "communities_after": None,
                        "rate_limited_waits": 0,
                    },
                }
            after = [item for item in before if item.lower() != identifier.lower()]
            if len(after) == len(before):
                return {
                    "success": True,
                    "result": {
                        "status": "unchanged",
                        "message": f"Community '{identifier}' was not linked to record.",
                        "communities_before": before,
                        "communities_after": before,
                        "rate_limited_waits": 0,
                        "zenodo_response": payload,
                    },
                }

        return _update_record_communities(
            cursor,
            project_id,
            int(local_record_id),
            str(row["record_status"] or "").strip().lower(),
            bool(row["is_sandbox"]),
            payload,
            communities_before=before,
            communities_after=after,
            access_token=access_token,
            http=http,
        )
    finally:
        conn.close()


def _update_record_communities(
    cursor: sqlite3.Cursor,
    project_id: int,
    local_record_id: int,
    record_status: str,
    is_sandbox: bool,
    payload: dict[str, Any],
    *,
    communities_before: list[str],
    communities_after: list[str],
    access_token: str | None = None,
    http=requests,
) -> Dict[str, Any]:
    token = _resolved_access_token(cursor, project_id, is_sandbox, access_token)
    metadata_update = _metadata_with_communities(payload, communities_after)
    effective_payload = payload
    http_statuses: list[int] = []

    if record_status == "draft":
        update_url = str(((payload.get("links") or {}).get("self")) or ((payload.get("links") or {}).get("latest_draft")) or "").strip()
        if not update_url:
            return {
                "success": False,
                "result": {
                    "status": "failed_capability_check",
                    "message": "Draft record is missing an editable deposition link.",
                    "communities_before": communities_before,
                    "communities_after": communities_before,
                    "rate_limited_waits": 0,
                },
            }
        update_response = http.put(
            update_url,
            params={"access_token": token},
            json=metadata_update,
            timeout=120,
        )
        http_statuses.append(update_response.status_code)
        updated_payload = _response_payload(update_response)
        if update_response.status_code not in {200, 201}:
            _store_api_error(cursor, local_record_id, updated_payload, "Zenodo metadata update failed")
            cursor.connection.commit()
            return {
                "success": False,
                "result": {
                    "status": "failed",
                    "message": str(updated_payload.get("message") or getattr(update_response, "text", "") or "Zenodo metadata update failed"),
                    "communities_before": communities_before,
                    "communities_after": communities_before,
                    "rate_limited_waits": 0,
                    "zenodo_response": updated_payload,
                },
            }
        effective_payload = updated_payload
        if not isinstance(effective_payload.get("metadata"), dict):
            effective_payload["metadata"] = {}
        effective_payload["metadata"]["communities"] = metadata_update["metadata"]["communities"]
        _store_record_payload(cursor, local_record_id, payload=effective_payload, record_status="draft")
        _store_snapshot(cursor, local_record_id, "community_metadata_updated", effective_payload, http_status=update_response.status_code)
        cursor.connection.commit()
        return {
            "success": True,
            "result": {
                "status": "succeeded",
                "message": "Record communities updated successfully.",
                "communities_before": communities_before,
                "communities_after": communities_after,
                "rate_limited_waits": 0,
                "zenodo_response": effective_payload,
            },
        }

    if record_status == "published":
        edit_url = str(((payload.get("links") or {}).get("edit")) or "").strip()
        if not edit_url:
            return {
                "success": False,
                "result": {
                    "status": "failed_capability_check",
                    "message": "Published record does not expose a no-version edit action.",
                    "communities_before": communities_before,
                    "communities_after": communities_before,
                    "rate_limited_waits": 0,
                },
            }
        edit_response = http.post(edit_url, params={"access_token": token}, timeout=120)
        http_statuses.append(edit_response.status_code)
        draft_payload = _response_payload(edit_response)
        if edit_response.status_code not in {200, 201}:
            _store_api_error(cursor, local_record_id, draft_payload, "Zenodo edit action failed")
            cursor.connection.commit()
            return {
                "success": False,
                "result": {
                    "status": "failed",
                    "message": str(draft_payload.get("message") or getattr(edit_response, "text", "") or "Zenodo edit action failed"),
                    "communities_before": communities_before,
                    "communities_after": communities_before,
                    "rate_limited_waits": 0,
                    "zenodo_response": draft_payload,
                },
            }

        update_url = str(((draft_payload.get("links") or {}).get("latest_draft")) or ((draft_payload.get("links") or {}).get("self")) or "").strip()
        if not update_url:
            return {
                "success": False,
                "result": {
                    "status": "failed",
                    "message": "Zenodo edit response did not include an editable draft link.",
                    "communities_before": communities_before,
                    "communities_after": communities_before,
                    "rate_limited_waits": 0,
                    "zenodo_response": draft_payload,
                },
            }

        update_response = http.put(
            update_url,
            params={"access_token": token},
            json=metadata_update,
            timeout=120,
        )
        http_statuses.append(update_response.status_code)
        updated_payload = _response_payload(update_response)
        if update_response.status_code not in {200, 201}:
            _store_api_error(cursor, local_record_id, updated_payload, "Zenodo metadata update failed")
            cursor.connection.commit()
            return {
                "success": False,
                "result": {
                    "status": "failed",
                    "message": str(updated_payload.get("message") or getattr(update_response, "text", "") or "Zenodo metadata update failed"),
                    "communities_before": communities_before,
                    "communities_after": communities_before,
                    "rate_limited_waits": 0,
                    "zenodo_response": updated_payload,
                },
            }

        publish_url = str(((updated_payload.get("links") or {}).get("publish")) or "").strip()
        if not publish_url:
            return {
                "success": False,
                "result": {
                    "status": "failed",
                    "message": "Zenodo draft is missing a publish link after metadata update.",
                    "communities_before": communities_before,
                    "communities_after": communities_before,
                    "rate_limited_waits": 0,
                    "zenodo_response": updated_payload,
                },
            }

        if os.environ.get("ZENODO_PUBLISH_ENABLED", "true").lower() not in {"true", "1", "yes", "on"}:
            return {"success": False, "error": "Zenodo publication is disabled by this deployment"}
        publish_response = http.post(publish_url, params={"access_token": token}, timeout=120)
        http_statuses.append(publish_response.status_code)
        published_payload = _response_payload(publish_response)
        if publish_response.status_code not in {200, 202}:
            _store_api_error(cursor, local_record_id, published_payload, "Zenodo publish failed")
            cursor.connection.commit()
            return {
                "success": False,
                "result": {
                    "status": "failed",
                    "message": str(published_payload.get("message") or getattr(publish_response, "text", "") or "Zenodo publish failed"),
                    "communities_before": communities_before,
                    "communities_after": communities_before,
                    "rate_limited_waits": 0,
                    "zenodo_response": published_payload,
                },
            }

        effective_payload = published_payload
        if not isinstance(effective_payload.get("metadata"), dict):
            effective_payload["metadata"] = {}
        effective_payload["metadata"]["communities"] = metadata_update["metadata"]["communities"]
        _store_record_payload(cursor, local_record_id, payload=effective_payload, record_status="published")
        _store_snapshot(cursor, local_record_id, "community_metadata_updated", effective_payload, http_status=http_statuses[-1] if http_statuses else None)
        _sync_uploaded_files(cursor, local_record_id, effective_payload)
        cursor.connection.commit()
        return {
            "success": True,
            "result": {
                "status": "succeeded",
                "message": "Record communities updated successfully.",
                "communities_before": communities_before,
                "communities_after": communities_after,
                "rate_limited_waits": 0,
                "zenodo_response": effective_payload,
            },
        }

    return {
        "success": False,
        "result": {
            "status": "failed_capability_check",
            "message": f"Record status '{record_status or 'unknown'}' is not editable for community operations.",
            "communities_before": communities_before,
            "communities_after": communities_before,
            "rate_limited_waits": 0,
        },
    }


def create_new_version_with_files(
    hdpc_path: str,
    *,
    concept_rec_id: str,
    is_sandbox: bool,
    source_file_path: str,
    absolute_file_paths: list[str],
    publish: bool = False,
    access_token: str | None = None,
    http=requests,
) -> Dict[str, Any]:
    prepared_version = prepare_new_version_draft(
        hdpc_path,
        concept_rec_id=concept_rec_id,
        is_sandbox=is_sandbox,
        source_file_path=source_file_path,
        absolute_file_paths=absolute_file_paths,
        access_token=access_token,
        http=http,
    )
    if not prepared_version.get("success"):
        return prepared_version

    new_local_record_id = int(
        prepared_version.get("new_local_record_id") or prepared_version.get("local_record_db_id") or 0
    )
    upload_result = upload_files_for_deposition(
        hdpc_path,
        new_local_record_id,
        publish=publish,
        prune_inherited_files=True,
        access_token=access_token,
        http=http,
    )
    conn = connect_hdpc(hdpc_path, timeout=30, row_factory=sqlite3.Row)
    try:
        cursor = conn.cursor()
        refreshed = cursor.execute(
            """
            SELECT record_metadata_json, record_status, zenodo_record_id, zenodo_doi, version
            FROM zenodo_records
            WHERE record_id = ?
            """,
            (new_local_record_id,),
        ).fetchone()
        refreshed_payload = _json_loads(refreshed["record_metadata_json"], {}) if refreshed else {}
        return {
            "success": bool(upload_result.get("success")),
            "new_local_record_id": new_local_record_id,
            "deleted_inherited_files": upload_result.get("deleted_inherited_files") or [],
            "registered_file_count": int(prepared_version.get("registered_file_count") or 0),
            "uploaded_file_count": int(upload_result.get("uploaded_file_count") or 0),
            "preserved_file_count": int(prepared_version.get("preserved_file_count") or 0),
            "publish_requested": bool(publish),
            "publish_result": upload_result.get("publication"),
            "record_status": refreshed["record_status"] if refreshed else None,
            "zenodo_record_id": refreshed["zenodo_record_id"] if refreshed else None,
            "zenodo_doi": refreshed["zenodo_doi"] if refreshed else None,
            "version": refreshed["version"] if refreshed else None,
            "zenodo_response": refreshed_payload,
            "message": upload_result.get("message"),
            "log": upload_result.get("log"),
        }
    finally:
        conn.close()
