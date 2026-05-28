from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from typing import Any

from services.hdpc_local_service import DEFAULT_RECORD_ORIGIN, normalize_hdpc_record_origin
from services.hdpc_schema_service import connect_hdpc, ensure_hdpc_schema, table_columns, table_exists


SHARED_EXPORT_ARTIFACT_KIND = "sanitized_shared"
SHARED_EXPORT_FORMAT_VERSION = 1
SHARED_EXPORT_IMPORT_MODE = "explorer_only"
SAFE_PROJECT_CONFIGURATION_KEYS = {"main.use_sandbox", "core.use_sandbox"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table_exists(cursor: sqlite3.Cursor, table_name: str) -> bool:
    return table_exists(cursor, table_name)


def _table_columns(cursor: sqlite3.Cursor, table_name: str) -> set[str]:
    return table_columns(cursor, table_name)


def _is_absolute_path(value: str | None) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return os.path.isabs(text) or bool(re.match(r"^[A-Za-z]:[\\/]", text))


def _normalize_relative_path(relative_path: str | None, *, fallback: str | None = None) -> str | None:
    candidate = str(relative_path or "").strip()
    if not candidate:
        candidate = str(fallback or "").strip()
    if not candidate:
        return None
    if _is_absolute_path(candidate):
        candidate = os.path.basename(candidate)
    normalized = os.path.normpath(candidate).replace("\\", "/").lstrip("/")
    return normalized or None


def _path_aliases(value: str | None) -> set[str]:
    text = str(value or "").strip()
    if not text:
        return set()
    aliases = {text}
    try:
        aliases.add(os.path.normpath(text))
    except Exception:
        pass
    aliases.add(text.replace("\\", "/"))
    aliases.add(text.replace("/", "\\"))
    return {alias for alias in aliases if str(alias or "").strip()}


def _replace_scrubbed_path_values(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _replace_scrubbed_path_values(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_scrubbed_path_values(item, replacements) for item in value]
    if isinstance(value, str):
        return replacements.get(value, value)
    return value


def _sanitize_json_text(raw_value: str | None, replacements: dict[str, str]) -> str | None:
    text = str(raw_value or "").strip()
    if not text:
        return raw_value
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return raw_value
    sanitized = _replace_scrubbed_path_values(parsed, replacements)
    return json.dumps(sanitized, sort_keys=True)


def _sanitize_project_configuration(cursor: sqlite3.Cursor) -> None:
    if _table_exists(cursor, "project_configuration"):
        project_id_row = cursor.execute(
            "SELECT project_id FROM project_configuration ORDER BY project_id ASC LIMIT 1"
        ).fetchone()
        if project_id_row is None and _table_exists(cursor, "project_info"):
            project_id_row = cursor.execute(
                "SELECT project_id FROM project_info ORDER BY project_id ASC LIMIT 1"
            ).fetchone()
        safe_rows = cursor.execute(
            """
            SELECT project_id, config_key, config_value, description
            FROM project_configuration
            WHERE config_key IN (?, ?)
            ORDER BY config_key ASC
            """,
            tuple(SAFE_PROJECT_CONFIGURATION_KEYS),
        ).fetchall()
        cursor.execute("DELETE FROM project_configuration")
        for row in safe_rows:
            cursor.execute(
                """
                INSERT INTO project_configuration (project_id, config_key, config_value, description)
                VALUES (?, ?, ?, ?)
                """,
                (row[0], row[1], row[2], row[3]),
            )
        project_id = safe_rows[0][0] if safe_rows else (project_id_row[0] if project_id_row else None)
        if project_id is not None:
            cursor.executemany(
                """
                INSERT INTO project_configuration (project_id, config_key, config_value, description)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        project_id,
                        "shared_export.artifact_kind",
                        SHARED_EXPORT_ARTIFACT_KIND,
                        "Sanitized shared export artifact kind",
                    ),
                    (
                        project_id,
                        "shared_export.import_mode",
                        SHARED_EXPORT_IMPORT_MODE,
                        "Shared export import mode",
                    ),
                    (
                        project_id,
                        "shared_export.format_version",
                        str(SHARED_EXPORT_FORMAT_VERSION),
                        "Shared export format version",
                    ),
                ],
            )

    if _table_exists(cursor, "configuration"):
        configuration_columns = _table_columns(cursor, "configuration")
        if {"config_key", "config_value"}.issubset(configuration_columns):
            safe_rows = cursor.execute(
                """
                SELECT config_key, config_value
                FROM configuration
                WHERE config_key IN (?, ?)
                ORDER BY config_key ASC
                """,
                tuple(SAFE_PROJECT_CONFIGURATION_KEYS),
            ).fetchall()
            cursor.execute("DELETE FROM configuration")
            for row in safe_rows:
                cursor.execute(
                    "INSERT INTO configuration (config_key, config_value) VALUES (?, ?)",
                    (row[0], row[1]),
                )


def _sanitize_source_and_record_paths(cursor: sqlite3.Cursor) -> dict[str, str]:
    replacements: dict[str, str] = {}
    source_file_safe_paths: dict[int, str | None] = {}

    if _table_exists(cursor, "source_files"):
        source_rows = cursor.execute(
            "SELECT file_id, absolute_path, relative_path, filename FROM source_files ORDER BY file_id ASC"
        ).fetchall()
        for row in source_rows:
            file_id = int(row[0])
            absolute_path = row[1]
            relative_path = row[2]
            filename = row[3]
            safe_relative_path = _normalize_relative_path(relative_path, fallback=filename or absolute_path)
            source_file_safe_paths[file_id] = safe_relative_path
            if absolute_path:
                for alias in _path_aliases(str(absolute_path)):
                    replacements[alias] = safe_relative_path or os.path.basename(str(alias))
            cursor.execute(
                """
                UPDATE source_files
                SET absolute_path = NULL,
                    relative_path = ?,
                    error_message = NULL
                WHERE file_id = ?
                """,
                (safe_relative_path, file_id),
            )

    if _table_exists(cursor, "record_files_map"):
        rfm_columns = _table_columns(cursor, "record_files_map")
        select_columns = ["record_id", "file_id", "file_path"]
        rows = cursor.execute(
            f"SELECT {', '.join(select_columns)} FROM record_files_map ORDER BY record_id ASC"
        ).fetchall()
        for row in rows:
            file_id = int(row[1]) if row[1] is not None else None
            file_path = row[2]
            safe_relative_path = source_file_safe_paths.get(file_id) or _normalize_relative_path(file_path)
            if file_path:
                for alias in _path_aliases(str(file_path)):
                    replacements.setdefault(alias, safe_relative_path or os.path.basename(str(alias)))
            if "file_path" in rfm_columns:
                cursor.execute(
                    "UPDATE record_files_map SET file_path = ? WHERE record_id = ? AND file_id = ?",
                    (safe_relative_path, row[0], row[1]),
                )
            if "upload_error" in rfm_columns:
                cursor.execute(
                    "UPDATE record_files_map SET upload_error = NULL WHERE record_id = ? AND file_id = ?",
                    (row[0], row[1]),
                )

    return replacements


def _sanitize_json_payload_columns(cursor: sqlite3.Cursor, replacements: dict[str, str]) -> None:
    table_column_map = {
        "zenodo_records": ["record_metadata_json", "creation_api_response", "last_publish_api_response"],
        "record_files_map": ["zenodo_file_links_json", "upload_response_json"],
    }
    for table_name, candidate_columns in table_column_map.items():
        if not _table_exists(cursor, table_name):
            continue
        columns = _table_columns(cursor, table_name)
        available_columns = [column_name for column_name in candidate_columns if column_name in columns]
        if not available_columns:
            continue
        primary_key = "record_id" if "record_id" in columns else "map_id"
        select_columns = [primary_key, *available_columns]
        rows = cursor.execute(
            f"SELECT {', '.join(select_columns)} FROM {table_name} ORDER BY {primary_key} ASC"
        ).fetchall()
        for row in rows:
            row_key = row[0]
            for offset, column_name in enumerate(available_columns, start=1):
                sanitized_value = _sanitize_json_text(row[offset], replacements)
                cursor.execute(
                    f"UPDATE {table_name} SET {column_name} = ? WHERE {primary_key} = ?",
                    (sanitized_value, row_key),
                )


def _safe_project_configuration_rows(source_cursor: sqlite3.Cursor, target_project_id: int) -> list[tuple[int, str, str | None, str | None]]:
    rows: list[tuple[int, str, str | None, str | None]] = []
    if _table_exists(source_cursor, "project_configuration"):
        for row in source_cursor.execute(
            """
            SELECT config_key, config_value, description
            FROM project_configuration
            WHERE config_key IN (?, ?)
            ORDER BY config_key ASC
            """,
            tuple(SAFE_PROJECT_CONFIGURATION_KEYS),
        ).fetchall():
            rows.append((target_project_id, str(row[0]), row[1], row[2]))
    elif _table_exists(source_cursor, "configuration"):
        for row in source_cursor.execute(
            """
            SELECT config_key, config_value
            FROM configuration
            WHERE config_key IN (?, ?)
            ORDER BY config_key ASC
            """,
            tuple(SAFE_PROJECT_CONFIGURATION_KEYS),
        ).fetchall():
            rows.append((target_project_id, str(row[0]), row[1], None))
    rows.extend(
        [
            (
                target_project_id,
                "shared_export.artifact_kind",
                SHARED_EXPORT_ARTIFACT_KIND,
                "Sanitized shared export artifact kind",
            ),
            (
                target_project_id,
                "shared_export.import_mode",
                SHARED_EXPORT_IMPORT_MODE,
                "Shared export import mode",
            ),
            (
                target_project_id,
                "shared_export.format_version",
                str(SHARED_EXPORT_FORMAT_VERSION),
                "Shared export format version",
            ),
        ]
    )
    return rows


def _copy_project_info(source_cursor: sqlite3.Cursor, target_cursor: sqlite3.Cursor, project_id: int) -> None:
    if not _table_exists(source_cursor, "project_info"):
        return
    row = source_cursor.execute(
        """
        SELECT project_name, project_short_code, description, creation_timestamp, last_modified_timestamp
        FROM project_info
        ORDER BY project_id ASC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        return
    target_cursor.execute(
        """
        UPDATE project_info
        SET project_name = ?, project_short_code = ?, description = ?, creation_timestamp = ?, last_modified_timestamp = ?
        WHERE project_id = ?
        """,
        (
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            int(project_id),
        ),
    )


def _copy_source_files(
    source_cursor: sqlite3.Cursor,
    target_cursor: sqlite3.Cursor,
    project_id: int,
) -> dict[str, str]:
    replacements: dict[str, str] = {}
    if not _table_exists(source_cursor, "source_files"):
        return replacements

    source_columns = _table_columns(source_cursor, "source_files")
    select_columns = ["file_id", "absolute_path", "relative_path", "filename"]
    extra_columns = [
        "size_bytes",
        "sha256_hash",
        "mime_type",
        "file_type",
        "parent_file_id",
        "status",
        "added_timestamp",
        "last_processed_timestamp",
        "validation_report_json",
        "is_primary_source",
        "pipeline_source",
        "step_source",
    ]
    for column_name in extra_columns:
        if column_name in source_columns:
            select_columns.append(column_name)
        else:
            select_columns.append(f"NULL AS {column_name}")

    rows = source_cursor.execute(
        f"SELECT {', '.join(select_columns)} FROM source_files ORDER BY file_id ASC"
    ).fetchall()
    for row in rows:
        absolute_path = row[1]
        relative_path = row[2]
        filename = row[3]
        safe_relative_path = _normalize_relative_path(relative_path, fallback=filename or absolute_path)
        if absolute_path:
            for alias in _path_aliases(str(absolute_path)):
                replacements[alias] = safe_relative_path or os.path.basename(str(alias))
        validation_report_json = _sanitize_json_text(row[12], replacements)
        target_cursor.execute(
            """
            INSERT INTO source_files (
                file_id,
                project_id,
                absolute_path,
                relative_path,
                filename,
                size_bytes,
                sha256_hash,
                mime_type,
                file_type,
                parent_file_id,
                status,
                added_timestamp,
                last_processed_timestamp,
                error_message,
                validation_report_json,
                is_primary_source,
                pipeline_source,
                step_source
            ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
            """,
            (
                int(row[0]),
                int(project_id),
                safe_relative_path,
                filename or (safe_relative_path or f"file_{row[0]}"),
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
                row[9],
                row[10],
                row[11] if len(row) > 11 else None,
                validation_report_json,
                int(row[13] or 0) if len(row) > 13 and row[13] is not None else 0,
                row[14] if len(row) > 14 else None,
                row[15] if len(row) > 15 else None,
            ),
        )
    return replacements


def _copy_zenodo_records(
    source_cursor: sqlite3.Cursor,
    target_cursor: sqlite3.Cursor,
    project_id: int,
    replacements: dict[str, str],
) -> None:
    if not _table_exists(source_cursor, "zenodo_records"):
        return
    source_columns = _table_columns(source_cursor, "zenodo_records")
    select_columns = [
        "record_id",
        "source_file_id",
        "record_title",
        "record_status",
        "record_metadata_json",
        "creation_api_response",
        "last_publish_api_response",
        "zenodo_record_id",
        "concept_rec_id",
        "zenodo_doi",
        "concept_doi",
        "is_sandbox",
        "created_timestamp",
        "last_updated_timestamp",
        "version",
        "version_rank",
        "previous_record_id",
        "record_origin",
        "last_api_error",
    ]
    translated_columns: list[str] = []
    for column_name in select_columns:
        if column_name in source_columns:
            translated_columns.append(column_name)
        elif column_name == "previous_record_id" and "previous_version_id" in source_columns:
            translated_columns.append("previous_version_id AS previous_record_id")
        else:
            translated_columns.append(f"NULL AS {column_name}")
    rows = source_cursor.execute(
        f"SELECT {', '.join(translated_columns)} FROM zenodo_records ORDER BY record_id ASC"
    ).fetchall()
    for row in rows:
        version_label = str(row[14] or "").strip() or None
        version_rank = row[15]
        record_origin = normalize_hdpc_record_origin(row[17]) or DEFAULT_RECORD_ORIGIN
        if version_rank in (None, ""):
            parts = [int(part) for part in str(version_label or "").split(".") if part.isdigit()]
            version_rank = parts[-1] if parts else 1
        target_cursor.execute(
            """
            INSERT INTO zenodo_records (
                record_id,
                project_id,
                source_file_id,
                record_title,
                record_status,
                record_metadata_json,
                creation_api_response,
                last_publish_api_response,
                zenodo_record_id,
                concept_rec_id,
                zenodo_doi,
                concept_doi,
                is_sandbox,
                created_timestamp,
                last_updated_timestamp,
                version,
                version_rank,
                previous_record_id,
                record_origin,
                last_api_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(row[0]),
                int(project_id),
                row[1],
                row[2],
                row[3],
                _sanitize_json_text(row[4], replacements),
                _sanitize_json_text(row[5], replacements),
                _sanitize_json_text(row[6], replacements),
                row[7],
                row[8],
                row[9],
                row[10],
                row[11],
                row[12],
                row[13],
                version_label,
                int(version_rank or 1),
                row[16],
                record_origin,
                row[18],
            ),
        )


def _copy_record_files_map(
    source_cursor: sqlite3.Cursor,
    target_cursor: sqlite3.Cursor,
    replacements: dict[str, str],
) -> None:
    if not _table_exists(source_cursor, "record_files_map"):
        return
    rows = source_cursor.execute(
        """
        SELECT
            map_id,
            record_id,
            file_id,
            file_path,
            file_purpose,
            zenodo_file_id,
            zenodo_file_key,
            zenodo_file_checksum,
            zenodo_file_size,
            zenodo_file_links_json,
            upload_status,
            upload_timestamp,
            upload_response_json
        FROM record_files_map
        ORDER BY map_id ASC
        """
    ).fetchall()
    for row in rows:
        safe_file_path = replacements.get(str(row[3]), _normalize_relative_path(row[3]))
        target_cursor.execute(
            """
            INSERT INTO record_files_map (
                map_id,
                record_id,
                file_id,
                file_path,
                file_purpose,
                zenodo_file_id,
                zenodo_file_key,
                zenodo_file_checksum,
                zenodo_file_size,
                zenodo_file_links_json,
                upload_status,
                upload_timestamp,
                upload_error,
                upload_response_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                int(row[0]),
                int(row[1]),
                int(row[2]),
                safe_file_path,
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
                _sanitize_json_text(row[9], replacements),
                row[10],
                row[11],
                _sanitize_json_text(row[12], replacements),
            ),
        )


def _copy_simple_record_table(
    source_cursor: sqlite3.Cursor,
    target_cursor: sqlite3.Cursor,
    *,
    table_name: str,
    select_columns: str,
    insert_columns: str,
) -> None:
    if not _table_exists(source_cursor, table_name):
        return
    rows = source_cursor.execute(f"SELECT {select_columns} FROM {table_name} ORDER BY 1 ASC").fetchall()
    if not rows:
        return
    placeholders = ", ".join("?" for _ in range(len(rows[0])))
    target_cursor.executemany(
        f"INSERT INTO {table_name} ({insert_columns}) VALUES ({placeholders})",
        rows,
    )


def _write_manifest(
    cursor: sqlite3.Cursor,
    *,
    source_session_id: int,
    source_institution_id: int,
    source_owner_user_id: int,
    source_owner_user_public_id: str | None = None,
    source_owner_profile_url: str | None = None,
    source_institution_public_id: str | None = None,
    source_institution_profile_url: str | None = None,
) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS shared_export_manifest (
            artifact_kind TEXT NOT NULL,
            format_version INTEGER NOT NULL,
            import_mode TEXT NOT NULL,
            source_session_id INTEGER,
            source_institution_id INTEGER,
            source_owner_user_id INTEGER,
            source_owner_user_public_id TEXT,
            source_owner_profile_url TEXT,
            source_institution_public_id TEXT,
            source_institution_profile_url TEXT,
            exported_at TEXT NOT NULL
        )
        """
    )
    for column_name in (
        "source_owner_user_public_id",
        "source_owner_profile_url",
        "source_institution_public_id",
        "source_institution_profile_url",
    ):
        if column_name not in _table_columns(cursor, "shared_export_manifest"):
            cursor.execute(f"ALTER TABLE shared_export_manifest ADD COLUMN {column_name} TEXT")
    cursor.execute("DELETE FROM shared_export_manifest")
    cursor.execute(
        """
        INSERT INTO shared_export_manifest (
            artifact_kind,
            format_version,
            import_mode,
            source_session_id,
            source_institution_id,
            source_owner_user_id,
            source_owner_user_public_id,
            source_owner_profile_url,
            source_institution_public_id,
            source_institution_profile_url,
            exported_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            SHARED_EXPORT_ARTIFACT_KIND,
            SHARED_EXPORT_FORMAT_VERSION,
            SHARED_EXPORT_IMPORT_MODE,
            int(source_session_id),
            int(source_institution_id),
            int(source_owner_user_id),
            source_owner_user_public_id,
            source_owner_profile_url,
            source_institution_public_id,
            source_institution_profile_url,
            _utc_now_iso(),
        ),
    )


def _source_provenance_manifest_fields(cursor: sqlite3.Cursor) -> dict[str, str | None]:
    if not _table_exists(cursor, "hdpc_provenance"):
        return {}
    row = cursor.execute(
        """
        SELECT creator_user_public_id, creator_profile_url, institution_public_id, institution_profile_url
        FROM hdpc_provenance
        WHERE provenance_id = 1
        LIMIT 1
        """
    ).fetchone()
    if not row:
        return {}
    return {
        "source_owner_user_public_id": row[0],
        "source_owner_profile_url": row[1],
        "source_institution_public_id": row[2],
        "source_institution_profile_url": row[3],
    }


def create_sanitized_shared_export(
    source_hdpc_path: str,
    *,
    source_session_id: int,
    source_institution_id: int,
    source_owner_user_id: int,
    source_owner_user_public_id: str | None = None,
    source_owner_profile_url: str | None = None,
    source_institution_public_id: str | None = None,
    source_institution_profile_url: str | None = None,
) -> str:
    temp_file = tempfile.NamedTemporaryFile(prefix="webhdp-shared-export-", suffix=".hdpc", delete=False)
    temp_path = temp_file.name
    temp_file.close()

    source_conn = None
    target_conn = None
    try:
        source_conn = connect_hdpc(source_hdpc_path, readonly=True, timeout=30, row_factory=sqlite3.Row)
        target_conn = connect_hdpc(temp_path, timeout=30, row_factory=sqlite3.Row)
        target_project_id = ensure_hdpc_schema(target_conn, temp_path)
        source_cursor = source_conn.cursor()
        target_conn.row_factory = sqlite3.Row
        target_cursor = target_conn.cursor()

        _copy_project_info(source_cursor, target_cursor, target_project_id)
        replacements = _copy_source_files(source_cursor, target_cursor, target_project_id)
        _copy_zenodo_records(source_cursor, target_cursor, target_project_id, replacements)
        _copy_record_files_map(source_cursor, target_cursor, replacements)
        _copy_simple_record_table(
            source_cursor,
            target_cursor,
            table_name="zenodo_record_links",
            select_columns="link_id, record_id, link_rel, link_url, created_timestamp, updated_timestamp",
            insert_columns="link_id, record_id, link_rel, link_url, created_timestamp, updated_timestamp",
        )
        _copy_simple_record_table(
            source_cursor,
            target_cursor,
            table_name="zenodo_record_snapshots",
            select_columns="snapshot_id, record_id, snapshot_stage, http_status, payload_json, created_timestamp",
            insert_columns="snapshot_id, record_id, snapshot_stage, http_status, payload_json, created_timestamp",
        )
        _copy_simple_record_table(
            source_cursor,
            target_cursor,
            table_name="hdpc_provenance",
            select_columns="""
                provenance_id, creator_user_public_id, creator_display_name, creator_orcid,
                creator_profile_url, institution_public_id, institution_name, institution_slug,
                institution_profile_url, source_session_id, created_at, updated_at
            """,
            insert_columns="""
                provenance_id, creator_user_public_id, creator_display_name, creator_orcid,
                creator_profile_url, institution_public_id, institution_name, institution_slug,
                institution_profile_url, source_session_id, created_at, updated_at
            """,
        )
        for config_row in _safe_project_configuration_rows(source_cursor, target_project_id):
            target_cursor.execute(
                """
                INSERT INTO project_configuration (project_id, config_key, config_value, description)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(project_id, config_key)
                DO UPDATE SET config_value = excluded.config_value, description = excluded.description
                """,
                config_row,
            )
        ensure_hdpc_schema(target_conn, temp_path)
        provenance_manifest = _source_provenance_manifest_fields(source_cursor)
        _write_manifest(
            target_cursor,
            source_session_id=source_session_id,
            source_institution_id=source_institution_id,
            source_owner_user_id=source_owner_user_id,
            source_owner_user_public_id=source_owner_user_public_id
            or provenance_manifest.get("source_owner_user_public_id"),
            source_owner_profile_url=source_owner_profile_url or provenance_manifest.get("source_owner_profile_url"),
            source_institution_public_id=source_institution_public_id
            or provenance_manifest.get("source_institution_public_id"),
            source_institution_profile_url=source_institution_profile_url
            or provenance_manifest.get("source_institution_profile_url"),
        )

        target_conn.commit()
        return temp_path
    except Exception:
        try:
            if target_conn is not None:
                target_conn.close()
        finally:
            if source_conn is not None:
                source_conn.close()
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise
    finally:
        if target_conn is not None:
            target_conn.close()
        if source_conn is not None:
            source_conn.close()


def read_shared_export_manifest(hdpc_path: str) -> dict[str, Any] | None:
    conn = connect_hdpc(hdpc_path, readonly=True, timeout=10)
    try:
        cursor = conn.cursor()
        if not _table_exists(cursor, "shared_export_manifest"):
            return None
        row = cursor.execute(
            """
            SELECT artifact_kind, format_version, import_mode, source_session_id,
                   source_institution_id, source_owner_user_id, exported_at
            FROM shared_export_manifest
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        manifest = {
            "artifact_kind": row[0],
            "format_version": int(row[1]) if row[1] is not None else None,
            "import_mode": row[2],
            "source_session_id": int(row[3]) if row[3] is not None else None,
            "source_institution_id": int(row[4]) if row[4] is not None else None,
            "source_owner_user_id": int(row[5]) if row[5] is not None else None,
            "exported_at": row[6],
        }
        columns = _table_columns(cursor, "shared_export_manifest")
        if {
            "source_owner_user_public_id",
            "source_owner_profile_url",
            "source_institution_public_id",
            "source_institution_profile_url",
        }.issubset(columns):
            public_row = cursor.execute(
                """
                SELECT source_owner_user_public_id, source_owner_profile_url,
                       source_institution_public_id, source_institution_profile_url
                FROM shared_export_manifest
                LIMIT 1
                """
            ).fetchone()
            if public_row:
                manifest.update(
                    {
                        "source_owner_user_public_id": public_row[0],
                        "source_owner_profile_url": public_row[1],
                        "source_institution_public_id": public_row[2],
                        "source_institution_profile_url": public_row[3],
                    }
                )
        return manifest
    finally:
        conn.close()
