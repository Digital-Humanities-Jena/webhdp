import json
import sqlite3

from services.hdpc_schema_service import (
    HDPC_SCHEMA_VERSION,
    connect_hdpc,
    ensure_hdpc_schema,
    read_hdpc_provenance,
    write_hdpc_provenance,
)


def _build_sparse_legacy_hdpc(path: str) -> None:
    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE file_scan_settings (
            scan_settings_id INTEGER PRIMARY KEY,
            project_id INTEGER,
            modality TEXT,
            scan_options TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE source_files (
            file_id INTEGER PRIMARY KEY,
            filename TEXT,
            absolute_path TEXT,
            relative_path TEXT,
            file_type TEXT,
            status TEXT,
            error_message TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE zenodo_records (
            record_id INTEGER PRIMARY KEY,
            source_file_id INTEGER,
            record_title TEXT,
            record_status TEXT,
            record_metadata_json TEXT,
            concept_rec_id TEXT,
            is_sandbox INTEGER,
            created_timestamp TEXT,
            version TEXT
        )
        """
    )
    cursor.execute(
        """
        INSERT INTO file_scan_settings (scan_settings_id, project_id, modality, scan_options)
        VALUES (1, NULL, '["3d_model", "image"]', '{"recursive": true}')
        """
    )
    cursor.execute(
        """
        INSERT INTO source_files (
            file_id, filename, absolute_path, relative_path, file_type, status, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            None,
            "/tmp/uploads/artifact.glb",
            "uploads/artifact.glb",
            "primary_source",
            "ready",
            json.dumps({"errors": ["Missing preview"]}),
        ),
    )
    cursor.executemany(
        """
        INSERT INTO zenodo_records (
            record_id, source_file_id, record_title, record_status, record_metadata_json,
            concept_rec_id, is_sandbox, created_timestamp, version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                1,
                1,
                "Artifact v1",
                "published",
                json.dumps({"metadata": {"title": "Artifact", "version": "0.0.1"}}),
                "7001",
                1,
                "2026-03-29T00:00:00Z",
                "0.0.1",
            ),
            (
                2,
                1,
                "Artifact v2",
                "published",
                json.dumps({"metadata": {"title": "Artifact", "version": "2"}}),
                "7001",
                1,
                "2026-03-30T00:00:00Z",
                "2",
            ),
        ],
    )
    conn.commit()
    conn.close()


def test_ensure_hdpc_schema_repairs_sparse_legacy_core_tables(tmp_path):
    hdpc_path = tmp_path / "legacy.hdpc"
    _build_sparse_legacy_hdpc(str(hdpc_path))

    conn = connect_hdpc(str(hdpc_path))
    try:
        project_id = ensure_hdpc_schema(conn, str(hdpc_path))
        conn.commit()
        cursor = conn.cursor()

        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert cursor.execute(
            "SELECT hdpc_schema_version FROM hdpc_schema_meta WHERE meta_id = 1"
        ).fetchone()[0] == HDPC_SCHEMA_VERSION
        assert cursor.execute(
            "SELECT hdpc_schema_version FROM project_info WHERE project_id = ?",
            (project_id,),
        ).fetchone()[0] == HDPC_SCHEMA_VERSION

        scan_rows = cursor.execute(
            "SELECT project_id, modality FROM file_scan_settings ORDER BY modality ASC"
        ).fetchall()
        assert scan_rows == [(project_id, "3d_model"), (project_id, "image")]

        source_row = cursor.execute(
            """
            SELECT project_id, filename, error_message, validation_report_json
            FROM source_files
            WHERE file_id = 1
            """
        ).fetchone()
        assert source_row[0] == project_id
        assert source_row[1] == "artifact.glb"
        assert source_row[2] == "Missing preview"
        assert json.loads(source_row[3])["errors"] == ["Missing preview"]

        record_rows = cursor.execute(
            "SELECT record_id, version, version_rank FROM zenodo_records ORDER BY record_id ASC"
        ).fetchall()
        assert record_rows == [(1, "0.0.1", 1), (2, "2", 2)]

        file_map_rows = cursor.execute(
            """
            SELECT record_id, file_id, file_path, file_purpose, upload_status
            FROM record_files_map
            ORDER BY record_id ASC
            """
        ).fetchall()
        assert file_map_rows == [
            (1, 1, "uploads/artifact.glb", "main", "pending"),
            (2, 1, "uploads/artifact.glb", "main", "pending"),
        ]

        assert cursor.execute("PRAGMA foreign_key_list(source_files)").fetchall()
        assert cursor.execute("PRAGMA foreign_key_list(zenodo_records)").fetchall()
    finally:
        conn.close()


def test_hdpc_schema_writes_and_reads_portable_creator_provenance(tmp_path):
    hdpc_path = tmp_path / "provenance.hdpc"
    conn = connect_hdpc(str(hdpc_path))
    try:
        ensure_hdpc_schema(conn, str(hdpc_path))
        write_hdpc_provenance(
            conn,
            {
                "creator_user_public_id": "user-public-id",
                "creator_display_name": "Ada Curator",
                "creator_orcid": "0000-0000-0000-0001",
                "creator_profile_url": "https://webhdp.example/profiles/users/ada-curator",
                "institution_public_id": "institution-public-id",
                "institution_name": "Museum Network",
                "institution_slug": "museum-network",
                "institution_profile_url": "https://webhdp.example/profiles/institutions/museum-network",
                "source_session_id": 42,
                "created_at": "2026-04-29T12:00:00+00:00",
            },
        )
        conn.commit()
    finally:
        conn.close()

    provenance = read_hdpc_provenance(str(hdpc_path))
    assert provenance["creator_user_public_id"] == "user-public-id"
    assert provenance["creator_display_name"] == "Ada Curator"
    assert provenance["creator_orcid"] == "0000-0000-0000-0001"
    assert provenance["institution_public_id"] == "institution-public-id"
    assert provenance["source_session_id"] == 42


def test_ensure_hdpc_schema_creates_hot_path_indexes_used_by_query_plans(tmp_path):
    hdpc_path = tmp_path / "indexed.hdpc"
    conn = connect_hdpc(str(hdpc_path))
    try:
        project_id = ensure_hdpc_schema(conn, str(hdpc_path))
        cursor = conn.cursor()

        source_rows = []
        record_rows = []
        snapshot_rows = []
        for index in range(1, 401):
            status = "error" if index % 40 == 0 else "ready"
            absolute_path = f"/tmp/uploads/model-{index}.glb"
            relative_path = f"uploads/model-{index}.glb"
            source_rows.append(
                (
                    project_id,
                    absolute_path,
                    relative_path,
                    f"model-{index}.glb",
                    100 + index,
                    "hash-" + str(index),
                    "model/gltf-binary",
                    "primary_source",
                    status,
                    "2026-03-30T00:00:00Z",
                    1 if index == 1 else 0,
                )
            )
            record_rows.append(
                (
                    project_id,
                    index,
                    f"Record {index}",
                    "published" if index % 3 == 0 else "draft",
                    json.dumps({"metadata": {"title": f"Record {index}"}}),
                    "7001" if index % 2 == 0 else "7002",
                    1,
                    "2026-03-30T00:00:00Z",
                    "2026-03-30T00:00:00Z",
                    f"0.0.{index}",
                    index,
                )
            )
            snapshot_rows.append(
                (
                    index,
                    "published_payload" if index % 2 == 0 else "draft_payload",
                    200,
                    json.dumps({"id": index}),
                    "2026-03-30T00:00:00Z",
                )
            )

        cursor.executemany(
            """
            INSERT INTO source_files (
                project_id, absolute_path, relative_path, filename, size_bytes, sha256_hash,
                mime_type, file_type, status, added_timestamp, is_primary_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            source_rows,
        )
        cursor.executemany(
            """
            INSERT INTO zenodo_records (
                project_id, source_file_id, record_title, record_status, record_metadata_json,
                concept_rec_id, is_sandbox, created_timestamp, last_updated_timestamp, version, version_rank
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            record_rows,
        )
        cursor.executemany(
            """
            INSERT INTO zenodo_record_snapshots (
                record_id, snapshot_stage, http_status, payload_json, created_timestamp
            ) VALUES (?, ?, ?, ?, ?)
            """,
            snapshot_rows,
        )
        conn.commit()
        cursor.execute("ANALYZE")

        source_index_names = {
            row[1]
            for row in cursor.execute("PRAGMA index_list(source_files)").fetchall()
        }
        assert {
            "idx_source_files_absolute_path",
            "idx_source_files_status",
        }.issubset(source_index_names)

        record_index_names = {
            row[1]
            for row in cursor.execute("PRAGMA index_list(zenodo_records)").fetchall()
        }
        assert {
            "idx_zenodo_records_source_file_id",
            "idx_zenodo_records_status_sandbox",
        }.issubset(record_index_names)

        snapshot_index_names = {
            row[1]
            for row in cursor.execute("PRAGMA index_list(zenodo_record_snapshots)").fetchall()
        }
        assert {
            "idx_zenodo_record_snapshots_record_id",
            "idx_zenodo_record_snapshots_stage",
        }.issubset(snapshot_index_names)

        def _plan_details(sql: str, params: tuple[object, ...]) -> str:
            return " | ".join(
                str(row[3])
                for row in cursor.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
            )

        assert "idx_source_files_absolute_path" in _plan_details(
            "SELECT * FROM source_files WHERE absolute_path = ?",
            ("/tmp/uploads/model-400.glb",),
        )
        assert "idx_source_files_status" in _plan_details(
            "SELECT * FROM source_files WHERE status = ?",
            ("error",),
        )
        assert "idx_zenodo_records_source_file_id" in _plan_details(
            "SELECT * FROM zenodo_records WHERE source_file_id = ?",
            (400,),
        )
        assert "idx_zenodo_records_status_sandbox" in _plan_details(
            "SELECT * FROM zenodo_records WHERE record_status = ? AND is_sandbox = ?",
            ("published", 1),
        )
        assert "idx_zenodo_record_snapshots_record_id" in _plan_details(
            "SELECT * FROM zenodo_record_snapshots WHERE record_id = ?",
            (400,),
        )
    finally:
        conn.close()
