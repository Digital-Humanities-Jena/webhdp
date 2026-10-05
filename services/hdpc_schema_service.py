from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HDPC_SCHEMA_VERSION = "webhdp-local-2"
HDPC_SCHEMA_META_TABLE = "hdpc_schema_meta"
CORE_TABLES = (
    "project_info",
    "project_configuration",
    "file_scan_settings",
    "source_files",
    "zenodo_records",
    "record_files_map",
    "zenodo_record_links",
    "zenodo_record_snapshots",
    "zenodo_remote_operations",
    "hdpc_provenance",
    "shared_export_manifest",
)
LEGACY_PASS_THROUGH_TABLES = (
    "batches",
    "metadata_mapping_files",
    "metadata_values",
    "project_pipelines",
    "api_log",
    "api_credentials",
    "metadata_backups",
    "component_configurations",
)

_CORE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_source_files_absolute_path ON source_files (absolute_path)",
    "CREATE INDEX IF NOT EXISTS idx_source_files_parent_file_id ON source_files (parent_file_id)",
    "CREATE INDEX IF NOT EXISTS idx_source_files_status ON source_files (status)",
    "CREATE INDEX IF NOT EXISTS idx_source_files_file_type ON source_files (file_type)",
    "CREATE INDEX IF NOT EXISTS idx_source_files_sha256_hash ON source_files (sha256_hash)",
    "CREATE INDEX IF NOT EXISTS idx_source_files_filename_file_id ON source_files (filename, file_id)",
    "CREATE INDEX IF NOT EXISTS idx_zenodo_records_status_sandbox ON zenodo_records (record_status, is_sandbox)",
    "CREATE INDEX IF NOT EXISTS idx_zenodo_records_source_file_id ON zenodo_records (source_file_id)",
    "CREATE INDEX IF NOT EXISTS idx_zenodo_records_concept_status_sandbox ON zenodo_records (concept_rec_id, record_status, is_sandbox)",
    "CREATE INDEX IF NOT EXISTS idx_zenodo_records_previous_record_id ON zenodo_records (previous_record_id)",
    "CREATE INDEX IF NOT EXISTS idx_zenodo_records_zenodo_record_id ON zenodo_records (zenodo_record_id)",
    "CREATE INDEX IF NOT EXISTS idx_record_files_map_record_id ON record_files_map (record_id)",
    "CREATE INDEX IF NOT EXISTS idx_record_files_map_file_id ON record_files_map (file_id)",
    "CREATE INDEX IF NOT EXISTS idx_record_files_map_upload_status ON record_files_map (upload_status)",
    "CREATE INDEX IF NOT EXISTS idx_record_files_map_zenodo_file_key ON record_files_map (zenodo_file_key)",
    "CREATE INDEX IF NOT EXISTS idx_zenodo_record_snapshots_record_id ON zenodo_record_snapshots (record_id)",
    "CREATE INDEX IF NOT EXISTS idx_zenodo_record_snapshots_stage ON zenodo_record_snapshots (snapshot_stage)",
)

_CANONICAL_TABLE_COLUMNS = {
    "zenodo_remote_operations": (
        "operation_id", "record_id", "operation_type", "state", "request_json",
        "remote_id", "response_json", "error", "created_at", "updated_at",
    ),
    "project_configuration": (
        "config_id",
        "project_id",
        "config_key",
        "config_value",
        "description",
    ),
    "file_scan_settings": (
        "scan_settings_id",
        "project_id",
        "modality",
        "scan_options",
    ),
    "source_files": (
        "file_id",
        "project_id",
        "absolute_path",
        "relative_path",
        "filename",
        "size_bytes",
        "sha256_hash",
        "mime_type",
        "file_type",
        "parent_file_id",
        "status",
        "added_timestamp",
        "last_processed_timestamp",
        "error_message",
        "validation_report_json",
        "is_primary_source",
        "pipeline_source",
        "step_source",
    ),
    "zenodo_records": (
        "record_id",
        "project_id",
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
    ),
    "record_files_map": (
        "map_id",
        "record_id",
        "file_id",
        "file_path",
        "file_purpose",
        "zenodo_file_id",
        "zenodo_file_key",
        "zenodo_file_checksum",
        "zenodo_file_size",
        "zenodo_file_links_json",
        "upload_status",
        "upload_timestamp",
        "upload_error",
        "upload_response_json",
    ),
    "zenodo_record_links": (
        "link_id",
        "record_id",
        "link_rel",
        "link_url",
        "created_timestamp",
        "updated_timestamp",
    ),
    "zenodo_record_snapshots": (
        "snapshot_id",
        "record_id",
        "snapshot_stage",
        "http_status",
        "payload_json",
        "created_timestamp",
    ),
    "hdpc_provenance": (
        "provenance_id",
        "creator_user_public_id",
        "creator_display_name",
        "creator_orcid",
        "creator_profile_url",
        "institution_public_id",
        "institution_name",
        "institution_slug",
        "institution_profile_url",
        "source_session_id",
        "created_at",
        "updated_at",
    ),
}

_REPAIRABLE_CORE_COLUMNS = {
    "project_configuration": {
        "project_id": "INTEGER",
        "config_key": "TEXT",
        "config_value": "TEXT",
        "description": "TEXT",
    },
    "file_scan_settings": {
        "project_id": "INTEGER",
        "modality": "TEXT",
        "scan_options": "TEXT",
    },
    "source_files": {
        "project_id": "INTEGER",
        "absolute_path": "TEXT",
        "relative_path": "TEXT",
        "filename": "TEXT",
        "size_bytes": "INTEGER",
        "sha256_hash": "TEXT",
        "mime_type": "TEXT",
        "file_type": "TEXT",
        "parent_file_id": "INTEGER",
        "status": "TEXT",
        "added_timestamp": "TEXT",
        "last_processed_timestamp": "TEXT",
        "error_message": "TEXT",
        "validation_report_json": "TEXT",
        "is_primary_source": "INTEGER DEFAULT 0",
        "pipeline_source": "TEXT",
        "step_source": "TEXT",
    },
    "zenodo_records": {
        "project_id": "INTEGER",
        "source_file_id": "INTEGER",
        "record_title": "TEXT",
        "record_status": "TEXT DEFAULT 'prepared'",
        "record_metadata_json": "TEXT",
        "creation_api_response": "TEXT",
        "last_publish_api_response": "TEXT",
        "zenodo_record_id": "TEXT",
        "concept_rec_id": "TEXT",
        "zenodo_doi": "TEXT",
        "concept_doi": "TEXT",
        "is_sandbox": "INTEGER DEFAULT 1",
        "created_timestamp": "TEXT",
        "last_updated_timestamp": "TEXT",
        "version": "TEXT",
        "version_rank": "INTEGER DEFAULT 1",
        "previous_record_id": "INTEGER",
        "record_origin": "TEXT DEFAULT 'submit_pipeline'",
        "last_api_error": "TEXT",
    },
    "record_files_map": {
        "record_id": "INTEGER",
        "file_id": "INTEGER",
        "file_path": "TEXT",
        "file_purpose": "TEXT DEFAULT 'main'",
        "zenodo_file_id": "TEXT",
        "zenodo_file_key": "TEXT",
        "zenodo_file_checksum": "TEXT",
        "zenodo_file_size": "INTEGER",
        "zenodo_file_links_json": "TEXT",
        "upload_status": "TEXT DEFAULT 'pending'",
        "upload_timestamp": "TEXT",
        "upload_error": "TEXT",
        "upload_response_json": "TEXT",
    },
    "zenodo_record_links": {
        "record_id": "INTEGER",
        "link_rel": "TEXT",
        "link_url": "TEXT",
        "created_timestamp": "TEXT",
        "updated_timestamp": "TEXT",
    },
    "zenodo_record_snapshots": {
        "record_id": "INTEGER",
        "snapshot_stage": "TEXT",
        "http_status": "INTEGER",
        "payload_json": "TEXT",
        "created_timestamp": "TEXT",
    },
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_hdpc(
    hdpc_path: str,
    *,
    readonly: bool = False,
    timeout: int = 30,
    row_factory: Any | None = None,
) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"file:{hdpc_path}?mode=ro", uri=True, timeout=timeout)
    else:
        conn = sqlite3.connect(hdpc_path, timeout=timeout)
        conn.execute("PRAGMA foreign_keys = ON")
    if row_factory is not None:
        conn.row_factory = row_factory
    return conn


def table_exists(cursor: sqlite3.Cursor, table_name: str) -> bool:
    row = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def table_columns(cursor: sqlite3.Cursor, table_name: str) -> set[str]:
    if not table_exists(cursor, table_name):
        return set()
    rows = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def ensure_column(cursor: sqlite3.Cursor, table_name: str, column_name: str, column_sql: str) -> None:
    if column_name in table_columns(cursor, table_name):
        return
    cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")


def _foreign_key_count(cursor: sqlite3.Cursor, table_name: str) -> int:
    if not table_exists(cursor, table_name):
        return 0
    rows = cursor.execute(f"PRAGMA foreign_key_list({table_name})").fetchall()
    return len(rows)


def _normalize_relative_path(value: str | None, *, fallback: str | None = None) -> str | None:
    candidate = str(value or "").strip() or str(fallback or "").strip()
    if not candidate:
        return None
    if os.path.isabs(candidate):
        candidate = os.path.basename(candidate)
    normalized = os.path.normpath(candidate).replace("\\", "/").lstrip("/")
    return normalized or None


def _schema_meta_sql(table_name: str = HDPC_SCHEMA_META_TABLE) -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            meta_id INTEGER PRIMARY KEY CHECK (meta_id = 1),
            hdpc_schema_version TEXT NOT NULL,
            updated_timestamp TEXT NOT NULL
        )
    """


def _project_info_sql(table_name: str = "project_info") -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            project_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT NOT NULL,
            project_short_code TEXT NOT NULL UNIQUE,
            description TEXT,
            creation_timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_modified_timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            hdpc_schema_version TEXT NOT NULL
        )
    """


def _project_configuration_sql(table_name: str = "project_configuration") -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            config_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            config_key TEXT NOT NULL,
            config_value TEXT,
            description TEXT,
            FOREIGN KEY (project_id) REFERENCES project_info(project_id) ON DELETE CASCADE,
            UNIQUE (project_id, config_key)
        )
    """


def _file_scan_settings_sql(table_name: str = "file_scan_settings") -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            scan_settings_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            modality TEXT NOT NULL,
            scan_options TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES project_info(project_id) ON DELETE CASCADE,
            UNIQUE (project_id, modality)
        )
    """


def _source_files_sql(table_name: str = "source_files") -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            file_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            absolute_path TEXT,
            relative_path TEXT,
            filename TEXT NOT NULL,
            size_bytes INTEGER,
            sha256_hash TEXT,
            mime_type TEXT,
            file_type TEXT NOT NULL DEFAULT 'source',
            parent_file_id INTEGER,
            status TEXT NOT NULL DEFAULT 'pending',
            added_timestamp TEXT,
            last_processed_timestamp TEXT,
            error_message TEXT,
            validation_report_json TEXT,
            is_primary_source INTEGER NOT NULL DEFAULT 0,
            pipeline_source TEXT,
            step_source TEXT,
            FOREIGN KEY (project_id) REFERENCES project_info(project_id) ON DELETE CASCADE,
            FOREIGN KEY (parent_file_id) REFERENCES {table_name}(file_id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
        )
    """


def _zenodo_records_sql(table_name: str = "zenodo_records") -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            source_file_id INTEGER,
            record_title TEXT,
            record_status TEXT NOT NULL DEFAULT 'prepared',
            record_metadata_json TEXT,
            creation_api_response TEXT,
            last_publish_api_response TEXT,
            zenodo_record_id TEXT,
            concept_rec_id TEXT,
            zenodo_doi TEXT,
            concept_doi TEXT,
            is_sandbox INTEGER NOT NULL DEFAULT 1,
            created_timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_updated_timestamp TEXT,
            version TEXT,
            version_rank INTEGER NOT NULL DEFAULT 1,
            previous_record_id INTEGER,
            record_origin TEXT NOT NULL DEFAULT 'submit_pipeline',
            last_api_error TEXT,
            FOREIGN KEY (project_id) REFERENCES project_info(project_id) ON DELETE CASCADE,
            FOREIGN KEY (source_file_id) REFERENCES source_files(file_id) ON DELETE SET NULL,
            FOREIGN KEY (previous_record_id) REFERENCES {table_name}(record_id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED
        )
    """


def _record_files_map_sql(table_name: str = "record_files_map") -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            map_id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL,
            file_id INTEGER NOT NULL,
            file_path TEXT,
            file_purpose TEXT NOT NULL DEFAULT 'main',
            zenodo_file_id TEXT,
            zenodo_file_key TEXT,
            zenodo_file_checksum TEXT,
            zenodo_file_size INTEGER,
            zenodo_file_links_json TEXT,
            upload_status TEXT NOT NULL DEFAULT 'pending',
            upload_timestamp TEXT,
            upload_error TEXT,
            upload_response_json TEXT,
            FOREIGN KEY (record_id) REFERENCES zenodo_records(record_id) ON DELETE CASCADE,
            FOREIGN KEY (file_id) REFERENCES source_files(file_id) ON DELETE CASCADE,
            UNIQUE (record_id, file_id)
        )
    """


def _zenodo_record_links_sql(table_name: str = "zenodo_record_links") -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            link_id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL,
            link_rel TEXT NOT NULL,
            link_url TEXT NOT NULL,
            created_timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_timestamp TEXT,
            FOREIGN KEY (record_id) REFERENCES zenodo_records(record_id) ON DELETE CASCADE,
            UNIQUE (record_id, link_rel)
        )
    """


def _zenodo_record_snapshots_sql(table_name: str = "zenodo_record_snapshots") -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL,
            snapshot_stage TEXT NOT NULL,
            http_status INTEGER,
            payload_json TEXT NOT NULL,
            created_timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (record_id) REFERENCES zenodo_records(record_id) ON DELETE CASCADE
        )
    """


def _zenodo_remote_operations_sql(table_name: str = "zenodo_remote_operations") -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            operation_id TEXT PRIMARY KEY,
            record_id INTEGER NOT NULL,
            operation_type TEXT NOT NULL,
            state TEXT NOT NULL,
            request_json TEXT NOT NULL,
            remote_id TEXT,
            response_json TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (record_id) REFERENCES zenodo_records(record_id) ON DELETE CASCADE
        )
    """


def _hdpc_provenance_sql(table_name: str = "hdpc_provenance") -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            provenance_id INTEGER PRIMARY KEY CHECK (provenance_id = 1),
            creator_user_public_id TEXT,
            creator_display_name TEXT,
            creator_orcid TEXT,
            creator_profile_url TEXT,
            institution_public_id TEXT,
            institution_name TEXT,
            institution_slug TEXT,
            institution_profile_url TEXT,
            source_session_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """


_CANONICAL_CREATE_SQL = {
    "project_info": _project_info_sql,
    "project_configuration": _project_configuration_sql,
    "file_scan_settings": _file_scan_settings_sql,
    "source_files": _source_files_sql,
    "zenodo_records": _zenodo_records_sql,
    "record_files_map": _record_files_map_sql,
    "zenodo_record_links": _zenodo_record_links_sql,
    "zenodo_record_snapshots": _zenodo_record_snapshots_sql,
    "zenodo_remote_operations": _zenodo_remote_operations_sql,
    "hdpc_provenance": _hdpc_provenance_sql,
}


def _default_project_values(hdpc_path: str) -> tuple[str, str, str]:
    stem = Path(hdpc_path).stem or "webhdp_project"
    project_name = stem.replace("_", " ").strip() or "WebHDP Project"
    short_code = "WEBHDP"
    description = "Locally managed WebHDP project context"
    return project_name, short_code, description


def _ensure_project_info(cursor: sqlite3.Cursor, hdpc_path: str) -> int:
    cursor.execute(_project_info_sql())
    row = cursor.execute("SELECT project_id FROM project_info ORDER BY project_id ASC LIMIT 1").fetchone()
    if row:
        return int(row[0])

    project_name, short_code, description = _default_project_values(hdpc_path)
    existing_short_code = cursor.execute(
        "SELECT project_id FROM project_info WHERE project_short_code = ?",
        (short_code,),
    ).fetchone()
    if existing_short_code:
        short_code = f"WEBHDP_{Path(hdpc_path).stem[:24].upper()}"
    now_iso = _utc_now_iso()
    cursor.execute(
        """
        INSERT INTO project_info (
            project_name,
            project_short_code,
            description,
            creation_timestamp,
            last_modified_timestamp,
            hdpc_schema_version
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            project_name,
            short_code,
            description,
            now_iso,
            now_iso,
            HDPC_SCHEMA_VERSION,
        ),
    )
    return int(cursor.lastrowid)


def _ensure_repairable_core_columns(cursor: sqlite3.Cursor) -> None:
    for table_name, column_defs in _REPAIRABLE_CORE_COLUMNS.items():
        if not table_exists(cursor, table_name):
            continue
        for column_name, column_sql in column_defs.items():
            ensure_column(cursor, table_name, column_name, column_sql)


def _repair_project_ids(cursor: sqlite3.Cursor, project_id: int) -> None:
    for table_name in ("project_configuration", "file_scan_settings", "source_files", "zenodo_records"):
        columns = table_columns(cursor, table_name)
        if "project_id" not in columns:
            continue
        cursor.execute(
            f"UPDATE {table_name} SET project_id = ? WHERE project_id IS NULL",
            (project_id,),
        )


def _fill_required_core_defaults(cursor: sqlite3.Cursor, project_id: int) -> None:
    now_iso = _utc_now_iso()

    source_columns = table_columns(cursor, "source_files")
    if source_columns:
        if "project_id" in source_columns:
            cursor.execute(
                "UPDATE source_files SET project_id = ? WHERE project_id IS NULL",
                (project_id,),
            )
        if "file_type" in source_columns:
            cursor.execute(
                """
                UPDATE source_files
                SET file_type = 'source'
                WHERE file_type IS NULL OR TRIM(file_type) = ''
                """
            )
        if "status" in source_columns:
            cursor.execute(
                """
                UPDATE source_files
                SET status = 'pending'
                WHERE status IS NULL OR TRIM(status) = ''
                """
            )
        if "is_primary_source" in source_columns:
            cursor.execute(
                "UPDATE source_files SET is_primary_source = 0 WHERE is_primary_source IS NULL"
            )
        if {"file_id", "filename"}.issubset(source_columns):
            select_columns = ["file_id", "filename"]
            if "relative_path" in source_columns:
                select_columns.append("relative_path")
            else:
                select_columns.append("NULL AS relative_path")
            if "absolute_path" in source_columns:
                select_columns.append("absolute_path")
            else:
                select_columns.append("NULL AS absolute_path")
            rows = cursor.execute(
                f"SELECT {', '.join(select_columns)} FROM source_files ORDER BY file_id ASC"
            ).fetchall()
            for row in rows:
                filename = str(row[1] or "").strip()
                if filename:
                    continue
                fallback = _normalize_relative_path(row[2], fallback=row[3])
                derived_filename = os.path.basename(fallback) if fallback else f"file-{int(row[0])}"
                cursor.execute(
                    "UPDATE source_files SET filename = ? WHERE file_id = ?",
                    (derived_filename, int(row[0])),
                )

    record_columns = table_columns(cursor, "zenodo_records")
    if record_columns:
        if "project_id" in record_columns:
            cursor.execute(
                "UPDATE zenodo_records SET project_id = ? WHERE project_id IS NULL",
                (project_id,),
            )
        if "record_status" in record_columns:
            cursor.execute(
                """
                UPDATE zenodo_records
                SET record_status = 'prepared'
                WHERE record_status IS NULL OR TRIM(record_status) = ''
                """
            )
        if "is_sandbox" in record_columns:
            cursor.execute(
                "UPDATE zenodo_records SET is_sandbox = 1 WHERE is_sandbox IS NULL"
            )
        if "created_timestamp" in record_columns:
            if "last_updated_timestamp" in record_columns:
                cursor.execute(
                    """
                    UPDATE zenodo_records
                    SET created_timestamp = COALESCE(last_updated_timestamp, ?)
                    WHERE created_timestamp IS NULL OR TRIM(created_timestamp) = ''
                    """,
                    (now_iso,),
                )
            else:
                cursor.execute(
                    """
                    UPDATE zenodo_records
                    SET created_timestamp = ?
                    WHERE created_timestamp IS NULL OR TRIM(created_timestamp) = ''
                    """,
                    (now_iso,),
                )
        if "version_rank" in record_columns:
            cursor.execute(
                "UPDATE zenodo_records SET version_rank = 1 WHERE version_rank IS NULL"
            )

    mapping_columns = table_columns(cursor, "record_files_map")
    if mapping_columns:
        if "file_purpose" in mapping_columns:
            cursor.execute(
                """
                UPDATE record_files_map
                SET file_purpose = 'main'
                WHERE file_purpose IS NULL OR TRIM(file_purpose) = ''
                """
            )
        if "upload_status" in mapping_columns:
            cursor.execute(
                """
                UPDATE record_files_map
                SET upload_status = 'pending'
                WHERE upload_status IS NULL OR TRIM(upload_status) = ''
                """
            )


def _extract_error_message_from_report(parsed: Any) -> str | None:
    if isinstance(parsed, dict):
        errors = parsed.get("errors")
        if isinstance(errors, list) and errors:
            text = str(errors[0] or "").strip()
            return text or None
    if isinstance(parsed, list) and parsed:
        text = str(parsed[0] or "").strip()
        return text or None
    return None


def _repair_validation_reports(cursor: sqlite3.Cursor) -> None:
    columns = table_columns(cursor, "source_files")
    if "file_id" not in columns:
        return
    has_validation = "validation_report_json" in columns
    has_error = "error_message" in columns
    if not has_error:
        return
    select_columns = ["file_id", "error_message"]
    if has_validation:
        select_columns.append("validation_report_json")
    else:
        select_columns.append("NULL AS validation_report_json")
    rows = cursor.execute(
        f"SELECT {', '.join(select_columns)} FROM source_files ORDER BY file_id ASC"
    ).fetchall()
    for row in rows:
        file_id = int(row[0])
        error_message = row[1]
        validation_report_json = row[2]
        if str(validation_report_json or "").strip():
            continue
        text = str(error_message or "").strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        cursor.execute(
            """
            UPDATE source_files
            SET validation_report_json = ?, error_message = ?
            WHERE file_id = ?
            """,
            (
                json.dumps(parsed, sort_keys=True),
                _extract_error_message_from_report(parsed),
                file_id,
            ),
        )


def _expanded_modalities(raw_value: Any) -> list[str]:
    if isinstance(raw_value, list):
        return [str(item).strip() for item in raw_value if str(item).strip()]
    text = str(raw_value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = None
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [text]


def _normalize_file_scan_settings(cursor: sqlite3.Cursor, project_id: int) -> None:
    columns = table_columns(cursor, "file_scan_settings")
    if not {"scan_settings_id", "project_id", "modality", "scan_options"}.issubset(columns):
        return
    rows = cursor.execute(
        """
        SELECT scan_settings_id, project_id, modality, scan_options
        FROM file_scan_settings
        ORDER BY scan_settings_id ASC
        """
    ).fetchall()
    normalized_rows: dict[tuple[int, str], str] = {}
    for row in rows:
        row_project_id = int(row[1]) if row[1] is not None else int(project_id)
        modalities = _expanded_modalities(row[2]) or ["unknown"]
        for modality in modalities:
            normalized_rows[(row_project_id, modality)] = str(row[3] or "{}")
    cursor.execute("DELETE FROM file_scan_settings")
    for (row_project_id, modality), scan_options in sorted(normalized_rows.items()):
        cursor.execute(
            """
            INSERT INTO file_scan_settings (project_id, modality, scan_options)
            VALUES (?, ?, ?)
            """,
            (row_project_id, modality, scan_options),
        )


def _repair_source_file_references(cursor: sqlite3.Cursor) -> None:
    source_columns = table_columns(cursor, "source_files")
    if "parent_file_id" in source_columns:
        cursor.execute(
            """
            UPDATE source_files
            SET parent_file_id = NULL
            WHERE parent_file_id IS NOT NULL
              AND parent_file_id NOT IN (SELECT file_id FROM source_files)
            """
        )


def _normalize_record_file_paths(cursor: sqlite3.Cursor) -> None:
    if not table_exists(cursor, "record_files_map"):
        return
    source_columns = table_columns(cursor, "source_files")
    rfm_columns = table_columns(cursor, "record_files_map")
    if not {"record_id", "file_id", "file_path"}.issubset(rfm_columns):
        return
    has_relative = "relative_path" in source_columns
    has_filename = "filename" in source_columns
    query = """
        SELECT rfm.record_id, rfm.file_id, rfm.file_path, sf.relative_path, sf.filename
        FROM record_files_map rfm
        LEFT JOIN source_files sf ON sf.file_id = rfm.file_id
        ORDER BY rfm.map_id ASC, rfm.record_id ASC
    """
    rows = cursor.execute(query).fetchall()
    for row in rows:
        relative_path = row[3] if has_relative else None
        filename = row[4] if has_filename else None
        safe_path = _normalize_relative_path(relative_path, fallback=filename or row[2])
        cursor.execute(
            """
            UPDATE record_files_map
            SET file_path = ?
            WHERE record_id = ? AND file_id = ?
            """,
            (safe_path, row[0], row[1]),
        )


def _repair_record_file_maps(cursor: sqlite3.Cursor) -> None:
    if not table_exists(cursor, "zenodo_records"):
        return
    if table_exists(cursor, "record_files_map"):
        cursor.execute(
            """
            DELETE FROM record_files_map
            WHERE record_id NOT IN (SELECT record_id FROM zenodo_records)
               OR file_id NOT IN (SELECT file_id FROM source_files)
            """
        )
    if not table_exists(cursor, "record_files_map"):
        return
    rows = cursor.execute(
        """
        SELECT zr.record_id, zr.source_file_id, sf.relative_path, sf.filename
        FROM zenodo_records zr
        LEFT JOIN source_files sf ON sf.file_id = zr.source_file_id
        WHERE zr.source_file_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM record_files_map rfm
              WHERE rfm.record_id = zr.record_id
                AND rfm.file_id = zr.source_file_id
          )
        ORDER BY zr.record_id ASC
        """
    ).fetchall()
    for row in rows:
        safe_path = _normalize_relative_path(row[2], fallback=row[3])
        cursor.execute(
            """
            INSERT INTO record_files_map (
                record_id,
                file_id,
                file_path,
                file_purpose,
                upload_status,
                upload_timestamp
            ) VALUES (?, ?, ?, 'main', 'pending', NULL)
            ON CONFLICT(record_id, file_id) DO NOTHING
            """,
            (int(row[0]), int(row[1]), safe_path),
        )


def _repair_record_references(cursor: sqlite3.Cursor) -> None:
    record_columns = table_columns(cursor, "zenodo_records")
    if "source_file_id" in record_columns:
        cursor.execute(
            """
            UPDATE zenodo_records
            SET source_file_id = NULL
            WHERE source_file_id IS NOT NULL
              AND source_file_id NOT IN (SELECT file_id FROM source_files)
            """
        )
    if "previous_record_id" in record_columns:
        cursor.execute(
            """
            UPDATE zenodo_records
            SET previous_record_id = NULL
            WHERE previous_record_id IS NOT NULL
              AND previous_record_id NOT IN (SELECT record_id FROM zenodo_records)
            """
        )
    if table_exists(cursor, "zenodo_record_links"):
        cursor.execute(
            """
            DELETE FROM zenodo_record_links
            WHERE record_id NOT IN (SELECT record_id FROM zenodo_records)
            """
        )
    if table_exists(cursor, "zenodo_record_snapshots"):
        cursor.execute(
            """
            DELETE FROM zenodo_record_snapshots
            WHERE record_id NOT IN (SELECT record_id FROM zenodo_records)
            """
        )
    if table_exists(cursor, "zenodo_remote_operations"):
        cursor.execute("DELETE FROM zenodo_remote_operations WHERE record_id NOT IN (SELECT record_id FROM zenodo_records)")


def _parse_version_rank(version_value: Any) -> int | None:
    text = str(version_value or "").strip()
    if not text:
        return None
    if text.isdigit():
        return max(1, int(text))
    parts = text.split(".")
    if parts and all(part.isdigit() for part in parts):
        return max(1, int(parts[-1]))
    return None


def _backfill_version_rank(cursor: sqlite3.Cursor) -> None:
    columns = table_columns(cursor, "zenodo_records")
    if not {"record_id", "version_rank", "created_timestamp", "last_updated_timestamp", "version"}.issubset(columns):
        return
    rows = cursor.execute(
        """
        SELECT record_id, concept_rec_id, is_sandbox, version, version_rank, created_timestamp, last_updated_timestamp
        FROM zenodo_records
        ORDER BY record_id ASC
        """
    ).fetchall()
    grouped: dict[tuple[str, int], list[sqlite3.Row]] = {}
    standalone: list[sqlite3.Row] = []
    for row in rows:
        concept_rec_id = str(row[1] or "").strip()
        if concept_rec_id:
            grouped.setdefault((concept_rec_id, int(row[2] or 0)), []).append(row)
        else:
            standalone.append(row)
    for row in standalone:
        rank = _parse_version_rank(row[3]) or int(row[4] or 0) or 1
        cursor.execute(
            "UPDATE zenodo_records SET version_rank = ? WHERE record_id = ?",
            (rank, int(row[0])),
        )
    for items in grouped.values():
        sorted_rows = sorted(
            items,
            key=lambda item: (
                _parse_version_rank(item[3]) or 0,
                str(item[6] or item[5] or ""),
                int(item[0]),
            ),
        )
        for index, row in enumerate(sorted_rows, start=1):
            cursor.execute(
                "UPDATE zenodo_records SET version_rank = ? WHERE record_id = ?",
                (index, int(row[0])),
            )


def _maybe_rebuild_table(cursor: sqlite3.Cursor, table_name: str) -> None:
    if table_name not in _CANONICAL_TABLE_COLUMNS or not table_exists(cursor, table_name):
        return
    if _foreign_key_count(cursor, table_name) > 0:
        return
    existing_columns = table_columns(cursor, table_name)
    canonical_columns = set(_CANONICAL_TABLE_COLUMNS[table_name])
    unexpected_columns = existing_columns - canonical_columns
    if unexpected_columns:
        return
    temp_table = f"__tmp_{table_name}_rebuild"
    cursor.execute(f"DROP TABLE IF EXISTS {temp_table}")
    cursor.execute(_CANONICAL_CREATE_SQL[table_name](temp_table))
    copy_columns = [column for column in _CANONICAL_TABLE_COLUMNS[table_name] if column in existing_columns]
    if copy_columns:
        joined_columns = ", ".join(copy_columns)
        cursor.execute(
            f"""
            INSERT INTO {temp_table} ({joined_columns})
            SELECT {joined_columns}
            FROM {table_name}
            """
        )
    cursor.execute(f"DROP TABLE {table_name}")
    cursor.execute(f"ALTER TABLE {temp_table} RENAME TO {table_name}")


def _rebuild_core_tables(cursor: sqlite3.Cursor) -> None:
    rebuild_order = (
        "project_configuration",
        "file_scan_settings",
        "source_files",
        "zenodo_records",
        "record_files_map",
        "zenodo_record_links",
        "zenodo_record_snapshots",
        "zenodo_remote_operations",
        "hdpc_provenance",
    )
    cursor.execute("PRAGMA foreign_keys = OFF")
    try:
        for table_name in rebuild_order:
            _maybe_rebuild_table(cursor, table_name)
    finally:
        cursor.execute("PRAGMA foreign_keys = ON")


def _write_schema_meta(cursor: sqlite3.Cursor) -> None:
    cursor.execute(_schema_meta_sql())
    cursor.execute(
        f"""
        INSERT INTO {HDPC_SCHEMA_META_TABLE} (meta_id, hdpc_schema_version, updated_timestamp)
        VALUES (1, ?, ?)
        ON CONFLICT(meta_id) DO UPDATE SET
            hdpc_schema_version = excluded.hdpc_schema_version,
            updated_timestamp = excluded.updated_timestamp
        """,
        (HDPC_SCHEMA_VERSION, _utc_now_iso()),
    )


def _sync_project_schema_version(cursor: sqlite3.Cursor) -> None:
    if not table_exists(cursor, "project_info"):
        return
    cursor.execute(
        """
        UPDATE project_info
        SET hdpc_schema_version = ?
        WHERE project_id = (SELECT project_id FROM project_info ORDER BY project_id ASC LIMIT 1)
        """,
        (HDPC_SCHEMA_VERSION,),
    )


def ensure_hdpc_schema(conn: sqlite3.Connection, hdpc_path: str) -> int:
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    cursor.execute(_project_info_sql())
    project_id = _ensure_project_info(cursor, hdpc_path)
    cursor.execute(_project_configuration_sql())
    cursor.execute(_file_scan_settings_sql())
    cursor.execute(_source_files_sql())
    cursor.execute(_zenodo_records_sql())
    cursor.execute(_record_files_map_sql())
    cursor.execute(_zenodo_record_links_sql())
    cursor.execute(_zenodo_record_snapshots_sql())
    cursor.execute(_zenodo_remote_operations_sql())
    cursor.execute(_hdpc_provenance_sql())

    _ensure_repairable_core_columns(cursor)
    ensure_column(cursor, "source_files", "validation_report_json", "TEXT")
    ensure_column(cursor, "zenodo_records", "version_rank", "INTEGER NOT NULL DEFAULT 1")
    ensure_column(cursor, "zenodo_records", "previous_record_id", "INTEGER")
    ensure_column(cursor, "zenodo_records", "record_origin", "TEXT NOT NULL DEFAULT 'submit_pipeline'")
    ensure_column(cursor, "project_info", "hdpc_schema_version", "TEXT NOT NULL DEFAULT 'webhdp-local-2'")

    _repair_project_ids(cursor, project_id)
    _fill_required_core_defaults(cursor, project_id)
    _repair_validation_reports(cursor)
    _normalize_file_scan_settings(cursor, project_id)
    _repair_source_file_references(cursor)
    _repair_record_references(cursor)
    _repair_record_file_maps(cursor)
    _normalize_record_file_paths(cursor)
    _backfill_version_rank(cursor)
    _rebuild_core_tables(cursor)
    _repair_record_references(cursor)
    _repair_record_file_maps(cursor)
    _normalize_record_file_paths(cursor)
    _backfill_version_rank(cursor)
    _write_schema_meta(cursor)
    _sync_project_schema_version(cursor)

    for index_sql in _CORE_INDEXES:
        cursor.execute(index_sql)
    cursor.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_zenodo_uncertain_operation
        ON zenodo_remote_operations (record_id, operation_type) WHERE state = 'uncertain'""")

    return project_id


def write_hdpc_provenance(conn: sqlite3.Connection, provenance: dict[str, Any] | None) -> None:
    if not provenance:
        return
    cursor = conn.cursor()
    cursor.execute(_hdpc_provenance_sql())
    now_iso = _utc_now_iso()
    created_at = str(provenance.get("created_at") or now_iso)
    cursor.execute(
        """
        INSERT INTO hdpc_provenance (
            provenance_id,
            creator_user_public_id,
            creator_display_name,
            creator_orcid,
            creator_profile_url,
            institution_public_id,
            institution_name,
            institution_slug,
            institution_profile_url,
            source_session_id,
            created_at,
            updated_at
        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(provenance_id) DO UPDATE SET
            creator_user_public_id = excluded.creator_user_public_id,
            creator_display_name = excluded.creator_display_name,
            creator_orcid = excluded.creator_orcid,
            creator_profile_url = excluded.creator_profile_url,
            institution_public_id = excluded.institution_public_id,
            institution_name = excluded.institution_name,
            institution_slug = excluded.institution_slug,
            institution_profile_url = excluded.institution_profile_url,
            source_session_id = excluded.source_session_id,
            updated_at = excluded.updated_at
        """,
        (
            provenance.get("creator_user_public_id"),
            provenance.get("creator_display_name"),
            provenance.get("creator_orcid"),
            provenance.get("creator_profile_url"),
            provenance.get("institution_public_id"),
            provenance.get("institution_name"),
            provenance.get("institution_slug"),
            provenance.get("institution_profile_url"),
            int(provenance["source_session_id"]) if provenance.get("source_session_id") not in (None, "") else None,
            created_at,
            now_iso,
        ),
    )


def read_hdpc_provenance(hdpc_path: str) -> dict[str, Any] | None:
    conn = connect_hdpc(hdpc_path, readonly=True, timeout=10)
    try:
        cursor = conn.cursor()
        if not table_exists(cursor, "hdpc_provenance"):
            return None
        row = cursor.execute(
            """
            SELECT
                creator_user_public_id,
                creator_display_name,
                creator_orcid,
                creator_profile_url,
                institution_public_id,
                institution_name,
                institution_slug,
                institution_profile_url,
                source_session_id,
                created_at,
                updated_at
            FROM hdpc_provenance
            WHERE provenance_id = 1
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        return {
            "creator_user_public_id": row[0],
            "creator_display_name": row[1],
            "creator_orcid": row[2],
            "creator_profile_url": row[3],
            "institution_public_id": row[4],
            "institution_name": row[5],
            "institution_slug": row[6],
            "institution_profile_url": row[7],
            "source_session_id": int(row[8]) if row[8] is not None else None,
            "created_at": row[9],
            "updated_at": row[10],
        }
    finally:
        conn.close()
