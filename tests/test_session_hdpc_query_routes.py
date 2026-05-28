import json
import os
import sqlite3
import tempfile
import unittest

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import Session as DBSession, User, UserRole
from routes.session_routes import session_bp


def _build_hdpc_query_fixture(path: str, root_dir: str) -> dict[str, str]:
    uploads_dir = os.path.join(root_dir, "uploads")
    versioning_dir = os.path.join(root_dir, "versioning")
    os.makedirs(uploads_dir, exist_ok=True)
    os.makedirs(versioning_dir, exist_ok=True)

    source_path = os.path.join(uploads_dir, "model.glb")
    child_path = os.path.join(uploads_dir, "preview.png")
    latest_render_path = os.path.join(uploads_dir, "render.png")
    version_match_path = os.path.join(versioning_dir, "model.glb")
    for file_path, content in (
        (source_path, "glb"),
        (child_path, "png"),
        (latest_render_path, "render"),
        (version_match_path, "glb"),
    ):
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write(content)

    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE project_info (
            project_id INTEGER PRIMARY KEY,
            project_name TEXT,
            project_short_code TEXT,
            description TEXT,
            creation_timestamp TEXT,
            last_modified_timestamp TEXT,
            hdpc_schema_version TEXT
        )
        """
    )
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
            project_id INTEGER,
            absolute_path TEXT,
            relative_path TEXT,
            filename TEXT,
            size_bytes INTEGER,
            sha256_hash TEXT,
            mime_type TEXT,
            file_type TEXT,
            parent_file_id INTEGER,
            status TEXT,
            added_timestamp TEXT,
            last_processed_timestamp TEXT,
            error_message TEXT,
            is_primary_source INTEGER,
            pipeline_source TEXT,
            step_source TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE zenodo_records (
            record_id INTEGER PRIMARY KEY,
            project_id INTEGER,
            source_file_id INTEGER,
            record_title TEXT,
            record_status TEXT,
            record_metadata_json TEXT,
            zenodo_record_id TEXT,
            concept_rec_id TEXT,
            zenodo_doi TEXT,
            concept_doi TEXT,
            is_sandbox INTEGER,
            created_timestamp TEXT,
            last_updated_timestamp TEXT,
            version TEXT,
            last_api_error TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE record_files_map (
            map_id INTEGER PRIMARY KEY,
            record_id INTEGER,
            file_id INTEGER,
            file_path TEXT,
            file_purpose TEXT,
            zenodo_file_id TEXT,
            zenodo_file_key TEXT,
            zenodo_file_checksum TEXT,
            zenodo_file_size INTEGER,
            zenodo_file_links_json TEXT,
            upload_status TEXT,
            upload_timestamp TEXT,
            upload_error TEXT,
            upload_response_json TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE zenodo_record_links (
            link_id INTEGER PRIMARY KEY,
            record_id INTEGER,
            link_rel TEXT,
            link_url TEXT,
            created_timestamp TEXT,
            updated_timestamp TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE zenodo_record_snapshots (
            snapshot_id INTEGER PRIMARY KEY,
            record_id INTEGER,
            snapshot_stage TEXT,
            http_status INTEGER,
            payload_json TEXT,
            created_timestamp TEXT
        )
        """
    )

    cursor.execute(
        """
        INSERT INTO project_info (
            project_id, project_name, project_short_code, description,
            creation_timestamp, last_modified_timestamp, hdpc_schema_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            "Session Query Fixture",
            "QUERY",
            "Fixture project",
            "2026-03-29T09:00:00Z",
            "2026-03-29T09:05:00Z",
            "1.2.0",
        ),
    )
    cursor.execute(
        """
        INSERT INTO file_scan_settings (scan_settings_id, project_id, modality, scan_options)
        VALUES (?, ?, ?, ?)
        """,
        (
            1,
            1,
            "3d_model",
            json.dumps({"extensions": [".glb", ".png"], "primarysourceext": ".glb"}),
        ),
    )

    source_rows = [
        (
            101,
            1,
            source_path,
            "model.glb",
            "model.glb",
            100,
            "hash-model",
            "model/gltf-binary",
            "primary_source",
            None,
            "ready",
            "2026-03-29T09:00:00Z",
            "2026-03-29T09:05:00Z",
            None,
            1,
            "scan",
            "bootstrap_scan",
        ),
        (
            102,
            1,
            child_path,
            "preview.png",
            "preview.png",
            20,
            "hash-preview",
            "image/png",
            "secondary",
            101,
            "uploaded",
            "2026-03-29T09:01:00Z",
            "2026-03-29T09:06:00Z",
            None,
            0,
            "render",
            "thumbnail",
        ),
        (
            103,
            1,
            latest_render_path,
            "render.png",
            "render.png",
            30,
            "hash-render",
            "image/png",
            "generated",
            None,
            "uploaded",
            "2026-03-29T09:02:00Z",
            "2026-03-29T09:07:00Z",
            None,
            0,
            "lod_generation",
            "xml_generator",
        ),
    ]
    cursor.executemany(
        """
        INSERT INTO source_files (
            file_id, project_id, absolute_path, relative_path, filename, size_bytes,
            sha256_hash, mime_type, file_type, parent_file_id, status, added_timestamp,
            last_processed_timestamp, error_message, is_primary_source, pipeline_source, step_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        source_rows,
    )

    metadata_payload = {
        "id": 9001,
        "doi": "10.5072/zenodo.9001",
        "conceptrecid": "7001",
        "conceptdoi": "10.5072/zenodo.7001",
        "files": [
            {"filename": "model.glb", "key": "model.glb", "checksum": "md5:model", "filesize": 100},
            {"filename": "render.png", "key": "render.png", "checksum": "md5:render", "filesize": 30},
        ],
        "links": {
            "html": "https://sandbox.zenodo.org/records/9001",
            "self": "https://sandbox.zenodo.org/api/deposit/depositions/9001",
        },
        "metadata": {
            "title": "Published model",
        },
    }
    cursor.execute(
        """
        INSERT INTO zenodo_records (
            record_id, project_id, source_file_id, record_title, record_status,
            record_metadata_json, zenodo_record_id, concept_rec_id, zenodo_doi, concept_doi,
            is_sandbox, created_timestamp, last_updated_timestamp, version, last_api_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            1,
            101,
            "Published model",
            "published",
            json.dumps(metadata_payload),
            "9001",
            "7001",
            "10.5072/zenodo.9001",
            "10.5072/zenodo.7001",
            1,
            "2026-03-29T09:10:00Z",
            "2026-03-29T09:12:00Z",
            "1.0.0",
            None,
        ),
    )
    cursor.executemany(
        """
        INSERT INTO record_files_map (
            map_id, record_id, file_id, file_path, file_purpose, zenodo_file_id, zenodo_file_key,
            zenodo_file_checksum, zenodo_file_size, zenodo_file_links_json, upload_status,
            upload_timestamp, upload_error, upload_response_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                1,
                1,
                101,
                source_path,
                "main",
                "zf-1",
                "model.glb",
                "md5:model",
                100,
                json.dumps({"self": "https://sandbox.zenodo.org/api/files/model.glb"}),
                "uploaded",
                "2026-03-29T09:12:00Z",
                None,
                json.dumps({"status": "ok"}),
            ),
            (
                2,
                1,
                103,
                latest_render_path,
                "generated",
                "zf-2",
                "render.png",
                "md5:render",
                30,
                json.dumps({"self": "https://sandbox.zenodo.org/api/files/render.png"}),
                "uploaded",
                "2026-03-29T09:12:30Z",
                None,
                json.dumps({"status": "ok"}),
            ),
        ],
    )
    cursor.executemany(
        """
        INSERT INTO zenodo_record_links (
            link_id, record_id, link_rel, link_url, created_timestamp, updated_timestamp
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (1, 1, "html", "https://sandbox.zenodo.org/records/9001", "2026-03-29T09:10:00Z", "2026-03-29T09:12:00Z"),
            (2, 1, "self", "https://sandbox.zenodo.org/api/deposit/depositions/9001", "2026-03-29T09:10:00Z", "2026-03-29T09:12:00Z"),
        ],
    )
    cursor.execute(
        """
        INSERT INTO zenodo_record_snapshots (
            snapshot_id, record_id, snapshot_stage, http_status, payload_json, created_timestamp
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            1,
            "draft_created",
            201,
            json.dumps({"id": 9001}),
            "2026-03-29T09:11:00Z",
        ),
    )

    conn.commit()
    conn.close()
    return {
        "versioning_dir": versioning_dir,
        "source_path": source_path,
        "child_path": child_path,
        "latest_render_path": latest_render_path,
    }


class TestSessionHdpcQueryRoutes(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        self.app.config["SECRET_KEY"] = "test-secret"
        self.app.config["JWT_SECRET_KEY"] = "test-jwt-secret"

        db.init_app(self.app)
        JWTManager(self.app)
        self.app.register_blueprint(session_bp, url_prefix="/api/v1/sessions")

        with self.app.app_context():
            db.create_all()
            user = User(email="session-query@example.com", role=UserRole.USER, is_verified=True)
            user.set_password("password123")
            db.session.add(user)
            db.session.commit()
            self.user_id = user.id
            self.token = create_access_token(identity=str(self.user_id))

            hdpc_path = os.path.join(self.temp_dir.name, "session.hdpc")
            self.fixture = _build_hdpc_query_fixture(hdpc_path, self.temp_dir.name)
            session_row = DBSession(
                user_id=self.user_id,
                session_dir=self.temp_dir.name,
                hdpc_path=hdpc_path,
                status="completed",
            )
            db.session.add(session_row)
            db.session.commit()
            self.session_id = session_row.id

        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        self.temp_dir.cleanup()

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def test_project_summary_and_published_records_routes(self):
        response = self.client.get(
            f"/api/v1/sessions/{self.session_id}/project-summary",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]
        self.assertEqual(payload["project_info"]["project_name"], "Session Query Fixture")
        self.assertEqual(payload["project_statistics"]["published_record_count"], 1)
        self.assertEqual(payload["file_scan_settings"][0]["modality"], "3d_model")

        published = self.client.get(
            f"/api/v1/sessions/{self.session_id}/published-records",
            headers=self._auth_headers(),
        )
        self.assertEqual(published.status_code, 200)
        published_payload = published.get_json()["data"]["records"]
        self.assertEqual(len(published_payload), 1)
        self.assertEqual(published_payload[0]["doi"], "10.5072/zenodo.9001")

    def test_source_files_and_hierarchy_routes(self):
        response = self.client.get(
            f"/api/v1/sessions/{self.session_id}/files?search=model",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]
        self.assertEqual(payload["totalItems"], 1)
        self.assertEqual(payload["items"][0]["filename"], "model.glb")

        hierarchy = self.client.get(
            f"/api/v1/sessions/{self.session_id}/files/101/hierarchy",
            headers=self._auth_headers(),
        )
        self.assertEqual(hierarchy.status_code, 200)
        hierarchy_payload = hierarchy.get_json()["data"]["hierarchy"]
        self.assertEqual(hierarchy_payload["filename"], "model.glb")
        self.assertEqual(len(hierarchy_payload["children"]), 1)
        self.assertEqual(hierarchy_payload["children"][0]["filename"], "preview.png")

    def test_record_files_and_traceability_routes(self):
        files_response = self.client.get(
            f"/api/v1/sessions/{self.session_id}/records/1/files",
            headers=self._auth_headers(),
        )
        self.assertEqual(files_response.status_code, 200)
        files_payload = files_response.get_json()["data"]["files"]
        self.assertEqual(len(files_payload), 2)
        self.assertEqual(files_payload[0]["file_purpose"], "main")

        traceability = self.client.get(
            f"/api/v1/sessions/{self.session_id}/records/1/traceability",
            headers=self._auth_headers(),
        )
        self.assertEqual(traceability.status_code, 200)
        trace_payload = traceability.get_json()["data"]
        self.assertEqual(trace_payload["record"]["record_status"], "published")
        self.assertEqual(trace_payload["source_file"]["sha256_hash"], "hash-model")
        self.assertEqual(trace_payload["summary"]["snapshot_count"], 1)
        self.assertEqual(trace_payload["links"][0]["link_rel"], "html")

    def test_versioning_match_and_latest_files_routes(self):
        match_response = self.client.post(
            f"/api/v1/sessions/{self.session_id}/versioning/match-files",
            headers=self._auth_headers(),
            json={
                "directory_path": self.fixture["versioning_dir"],
                "match_method": "filename",
            },
        )
        self.assertEqual(match_response.status_code, 200)
        matches = match_response.get_json()["data"]["matches"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["concept_rec_id"], "7001")

        latest_response = self.client.get(
            f"/api/v1/sessions/{self.session_id}/concepts/7001/latest-files?is_sandbox=true",
            headers=self._auth_headers(),
        )
        self.assertEqual(latest_response.status_code, 200)
        latest_payload = latest_response.get_json()["data"]
        self.assertEqual(latest_payload["record_id"], 1)
        self.assertEqual(len(latest_payload["files"]), 2)
        self.assertEqual(latest_payload["files"][0]["filename"], "model.glb")

    def test_workspace_summary_lineage_and_zenodo_status_routes(self):
        summary_response = self.client.get(
            f"/api/v1/sessions/{self.session_id}/workspace-summary",
            headers=self._auth_headers(),
        )
        self.assertEqual(summary_response.status_code, 200)
        summary_payload = summary_response.get_json()["data"]
        self.assertEqual(summary_payload["project_info"]["project_name"], "Session Query Fixture")
        self.assertEqual(summary_payload["record_summary"]["published_count"], 1)
        self.assertEqual(summary_payload["operations"]["tabs"]["published"]["count"], 1)

        lineage_response = self.client.get(
            f"/api/v1/sessions/{self.session_id}/records/1/lineage",
            headers=self._auth_headers(),
        )
        self.assertEqual(lineage_response.status_code, 200)
        lineage_payload = lineage_response.get_json()["data"]["lineage"]
        self.assertEqual(lineage_payload["traceability"]["record"]["record_id"], 1)
        self.assertEqual(lineage_payload["source_hierarchy"]["filename"], "model.glb")
        self.assertEqual(lineage_payload["latest_same_concept"]["concept_rec_id"], "7001")

        zenodo_status_response = self.client.get(
            f"/api/v1/sessions/{self.session_id}/records/1/zenodo-status",
            headers=self._auth_headers(),
        )
        self.assertEqual(zenodo_status_response.status_code, 200)
        zenodo_payload = zenodo_status_response.get_json()["data"]["zenodo_status"]
        self.assertTrue(zenodo_payload["summary"]["has_html_link"])
        self.assertEqual(zenodo_payload["upload_status_counts"]["uploaded"], 2)

        detail_response = self.client.get(
            f"/api/v1/sessions/{self.session_id}/records/1",
            headers=self._auth_headers(),
        )
        self.assertEqual(detail_response.status_code, 200)
        detail_payload = detail_response.get_json()["data"]
        self.assertEqual(detail_payload["record"]["local_record_id"], 1)
        self.assertEqual(detail_payload["lineage"]["traceability"]["record"]["record_id"], 1)
        self.assertTrue(detail_payload["zenodo_status"]["summary"]["has_html_link"])

        operations_response = self.client.get(
            f"/api/v1/sessions/{self.session_id}/operations/summary",
            headers=self._auth_headers(),
        )
        self.assertEqual(operations_response.status_code, 200)
        operations_payload = operations_response.get_json()["data"]
        self.assertEqual(operations_payload["tabs"]["published"]["count"], 1)
        self.assertEqual(operations_payload["actionable_operations"]["publish_records"]["count"], 0)


if __name__ == "__main__":
    unittest.main()
