import os
import sqlite3
import tempfile
from pathlib import Path

from services.hdpc_local_service import (
    create_local_record_with_metadata,
    find_hdpc_record_for_file,
    inspect_hdpc_project,
    read_hdpc_project_info,
    read_hdpc_project_stats,
    read_hdpc_published_records,
)
from services.hdpc_scan_service import create_and_scan_hdpc_project
from services.hdpc_schema_service import HDPC_SCHEMA_VERSION


def test_create_and_scan_hdpc_project_builds_nested_obj_bundle():
    with tempfile.TemporaryDirectory() as temp_dir:
        uploads = Path(temp_dir) / "uploads"
        outputs = Path(temp_dir) / "outputs"
        uploads.mkdir(parents=True, exist_ok=True)
        outputs.mkdir(parents=True, exist_ok=True)

        (uploads / "model.obj").write_text("mtllib model.mtl\nv 0 0 0\nf 1 1 1\n", encoding="utf-8")
        (uploads / "model.mtl").write_text("newmtl material0\nmap_Kd textures/albedo.jpg\n", encoding="utf-8")
        texture_dir = uploads / "textures"
        texture_dir.mkdir(parents=True, exist_ok=True)
        (texture_dir / "albedo.jpg").write_bytes(b"jpg")

        hdpc_path = Path(temp_dir) / "session.hdpc"
        result = create_and_scan_hdpc_project(
            hdpc_path=str(hdpc_path),
            data_in_path=str(uploads),
            data_out_path=str(outputs),
            project_name="OBJ Bundle",
            short_code="OBJB",
            modalities=["3d_model"],
            scan_options={
                "extensions": [".obj", ".mtl", ".jpg"],
                "primarysourceext": ".obj",
                "bundling": {"enabled": True, "strategy": "stem_match"},
                "batchEntity": "root",
                "obj_options": {"add_mtl": True, "add_textures": True, "archive_subdirectories": False},
            },
            batch_entity="root",
        )

        assert result["success"] is True
        assert hdpc_path.exists()

        inspect_data = inspect_hdpc_project(str(hdpc_path), show_files=True)
        assert inspect_data["project_info"]["project_name"] == "OBJ Bundle"
        assert inspect_data["configuration"]
        assert len(inspect_data["file_tree"]) == 1

        root = inspect_data["file_tree"][0]
        assert root["filename"] == "model.obj"
        assert root["file_type"] == "primary_source"
        assert root["is_primary_source"] is True
        assert len(root["children"]) == 1
        assert root["children"][0]["filename"] == "model.mtl"
        assert root["children"][0]["file_type"] == "primary"
        assert len(root["children"][0]["children"]) == 1
        assert root["children"][0]["children"][0]["filename"] == "albedo.jpg"
        assert root["children"][0]["children"][0]["file_type"] == "secondary"


def test_create_and_scan_hdpc_project_archives_subdirectory_textures():
    with tempfile.TemporaryDirectory() as temp_dir:
        uploads = Path(temp_dir) / "uploads"
        outputs = Path(temp_dir) / "outputs"
        uploads.mkdir(parents=True, exist_ok=True)
        outputs.mkdir(parents=True, exist_ok=True)

        (uploads / "artifact.obj").write_text("mtllib artifact.mtl\nv 0 0 0\nf 1 1 1\n", encoding="utf-8")
        (uploads / "artifact.mtl").write_text("newmtl material0\nmap_Kd textures/diffuse.jpg\n", encoding="utf-8")
        texture_dir = uploads / "textures"
        texture_dir.mkdir(parents=True, exist_ok=True)
        (texture_dir / "diffuse.jpg").write_bytes(b"jpg")

        hdpc_path = Path(temp_dir) / "session.hdpc"
        result = create_and_scan_hdpc_project(
            hdpc_path=str(hdpc_path),
            data_in_path=str(uploads),
            data_out_path=str(outputs),
            project_name="Archived Bundle",
            short_code="ARCH",
            modalities=["3d_model", "image"],
            scan_options={
                "extensions": [".obj", ".mtl", ".jpg"],
                "primarysourceext": ".obj",
                "bundling": {"enabled": True, "strategy": "stem_match"},
                "batchEntity": "root",
                "obj_options": {"add_mtl": True, "add_textures": True, "archive_subdirectories": True},
            },
            batch_entity="root",
        )

        assert result["success"] is True
        archive_path = outputs / "archives" / "artifact_textures.zip"
        assert archive_path.exists()

        inspect_data = inspect_hdpc_project(str(hdpc_path), show_files=True)
        root = inspect_data["file_tree"][0]
        mtl_node = root["children"][0]
        archive_nodes = [child for child in mtl_node["children"] if child["file_type"] == "archive"]
        assert len(archive_nodes) == 1
        assert archive_nodes[0]["filename"] == "artifact_textures.zip"
        assert archive_nodes[0]["children"][0]["file_type"] == "archived_file"

        conn = sqlite3.connect(hdpc_path)
        try:
            schema_version = conn.execute("SELECT hdpc_schema_version FROM project_info").fetchone()[0]
            assert schema_version == HDPC_SCHEMA_VERSION
            scan_settings = conn.execute(
                "SELECT modality, scan_options FROM file_scan_settings ORDER BY modality ASC"
            ).fetchall()
            assert [row[0] for row in scan_settings] == ["3d_model", "image"]
            assert all('"primarysourceext": ".obj"' in row[1] for row in scan_settings)
            count = conn.execute("SELECT COUNT(*) FROM source_files").fetchone()[0]
            assert count >= 4
        finally:
            conn.close()


def test_create_and_scan_hdpc_project_scans_preferred_primary_dependencies_in_hybrid_batch():
    with tempfile.TemporaryDirectory() as temp_dir:
        uploads = Path(temp_dir) / "uploads"
        outputs = Path(temp_dir) / "outputs"
        case_a = uploads / "cases" / "a"
        case_b = uploads / "cases" / "b"
        case_a.mkdir(parents=True, exist_ok=True)
        case_b.mkdir(parents=True, exist_ok=True)
        outputs.mkdir(parents=True, exist_ok=True)

        (case_a / "temple_column.obj").write_text("mtllib temple_column.mtl\nv 0 0 0\nf 1 1 1\n", encoding="utf-8")
        (case_a / "temple_column.mtl").write_text("newmtl material0\n", encoding="utf-8")
        (case_b / "detail.obj").write_text("mtllib detail.mtl\nv 0 0 0\nf 1 1 1\n", encoding="utf-8")
        (case_b / "detail.mtl").write_text("newmtl material0\n", encoding="utf-8")

        hdpc_path = Path(temp_dir) / "session.hdpc"
        result = create_and_scan_hdpc_project(
            hdpc_path=str(hdpc_path),
            data_in_path=str(uploads),
            data_out_path=str(outputs),
            project_name="Hybrid MSF Batch",
            short_code="HYBRID",
            modalities=["3d_model"],
            scan_options={
                "extensions": [".obj", ".mtl"],
                "primarysourceext": ".obj",
                "preferred_primary_files": ["temple_column.obj", "detail.obj"],
                "bundling": {"enabled": True, "strategy": "stem_match"},
                "batchEntity": "hybrid",
                "obj_options": {"add_mtl": True, "add_textures": True, "archive_subdirectories": True},
            },
            batch_entity="hybrid",
        )

        assert result["success"] is True

        conn = sqlite3.connect(hdpc_path)
        try:
            rows = conn.execute(
                "SELECT filename, file_type, status, parent_file_id FROM source_files ORDER BY file_id"
            ).fetchall()
        finally:
            conn.close()

        by_filename = {row[0]: row for row in rows}
        assert by_filename["temple_column.obj"][1] == "primary_source"
        assert by_filename["temple_column.obj"][2] == "Valid"
        assert by_filename["temple_column.mtl"][1] == "primary"
        assert by_filename["detail.obj"][2] == "Valid"
        assert by_filename["detail.obj"][1] == "primary_source"
        assert by_filename["detail.obj"][3] is None
        assert by_filename["temple_column.obj"][3] is None
        assert by_filename["detail.mtl"][1] == "primary"


def test_hdpc_local_queries_expose_records_stats_and_published_filter():
    with tempfile.TemporaryDirectory() as temp_dir:
        uploads = Path(temp_dir) / "uploads"
        outputs = Path(temp_dir) / "outputs"
        uploads.mkdir(parents=True, exist_ok=True)
        outputs.mkdir(parents=True, exist_ok=True)
        (uploads / "model.glb").write_bytes(b"glb")

        hdpc_path = Path(temp_dir) / "session.hdpc"
        create_and_scan_hdpc_project(
            hdpc_path=str(hdpc_path),
            data_in_path=str(uploads),
            data_out_path=str(outputs),
            project_name="Query Coverage",
            short_code="QUERY",
            modalities=["3d_model"],
            scan_options={
                "extensions": [".glb"],
                "primarysourceext": ".glb",
                "bundling": {"enabled": False},
                "batchEntity": "root",
                "obj_options": {"add_mtl": False, "add_textures": False, "archive_subdirectories": False},
            },
            batch_entity="root",
        )

        scanned = inspect_hdpc_project(str(hdpc_path), show_files=True)
        source_file_id = scanned["file_tree"][0]["file_id"]
        created = create_local_record_with_metadata(
            str(hdpc_path),
            file_id=source_file_id,
            metadata={
                "title": "Published model",
                "description": "Model description",
                "creators": [{"name": "Museum"}],
            },
            is_sandbox=True,
            access_token="sandbox-token",
        )
        local_record_id = created["local_record_db_id"]

        conn = sqlite3.connect(hdpc_path)
        try:
            conn.execute(
                """
                UPDATE zenodo_records
                SET record_status = 'published',
                    zenodo_record_id = '9001',
                    concept_rec_id = '7001',
                    zenodo_doi = '10.5072/zenodo.9001',
                    concept_doi = '10.5072/zenodo.7001'
                WHERE record_id = ?
                """,
                (local_record_id,),
            )
            conn.execute(
                """
                INSERT INTO zenodo_record_links (record_id, link_rel, link_url)
                VALUES (?, 'html', 'https://sandbox.zenodo.org/records/9001')
                """,
                (local_record_id,),
            )
            conn.commit()
        finally:
            conn.close()

        project_info = read_hdpc_project_info(str(hdpc_path))
        project_stats = read_hdpc_project_stats(str(hdpc_path))
        published_records = read_hdpc_published_records(str(hdpc_path))
        matched_record = find_hdpc_record_for_file(str(hdpc_path), source_file_id)
        inspect_data = inspect_hdpc_project(str(hdpc_path), show_files=False)

        assert project_info["project_name"] == "Query Coverage"
        assert project_stats["source_file_count"] == 1
        assert project_stats["published_record_count"] == 1
        assert project_stats["record_statuses"]["published"] == 1
        assert len(published_records) == 1
        assert published_records[0]["doi"] == "10.5072/zenodo.9001"
        assert published_records[0]["record_url"] == "https://sandbox.zenodo.org/records/9001"
        assert matched_record["record_id"] == local_record_id
        assert inspect_data["file_tree"] == []
        assert inspect_data["project_statistics"]["published_record_count"] == 1
        assert inspect_data["file_scan_settings"][0]["scan_options"]["primarysourceext"] == ".glb"
        assert inspect_data["zenodo_records"][0]["record_files"][0]["file_purpose"] == "main"
        assert inspect_data["published_records"][0]["record_id"] == local_record_id
