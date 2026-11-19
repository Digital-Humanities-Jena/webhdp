import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import Session as DBSession, User, UserRole
from routes.session_routes import session_bp


class _DummyResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _build_hdpc_zenodo_utility_fixture(path: str, root_dir: str) -> None:
    uploads_dir = os.path.join(root_dir, "uploads")
    os.makedirs(uploads_dir, exist_ok=True)

    file_paths = {}
    for filename, content in (
        ("pending.glb", "pending"),
        ("prepared.glb", "prepared"),
        ("draft.glb", "draft"),
        ("draft-preview.png", "preview"),
        ("published.glb", "published"),
    ):
        file_path = os.path.join(uploads_dir, filename)
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write(content)
        file_paths[filename] = file_path

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
            last_api_error TEXT,
            creation_api_response TEXT,
            last_publish_api_response TEXT
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
            "Session Zenodo Fixture",
            "ZENODO",
            "Fixture project",
            "2026-03-29T09:00:00Z",
            "2026-03-29T09:05:00Z",
            "1.2.0",
        ),
    )

    cursor.executemany(
        """
        INSERT INTO source_files (
            file_id, project_id, absolute_path, relative_path, filename, size_bytes,
            sha256_hash, mime_type, file_type, parent_file_id, status, added_timestamp,
            last_processed_timestamp, error_message, is_primary_source, pipeline_source, step_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                101,
                1,
                file_paths["pending.glb"],
                "pending.glb",
                "pending.glb",
                100,
                "hash-pending",
                "model/gltf-binary",
                "primary_source",
                None,
                "pending",
                "2026-03-29T09:00:00Z",
                "2026-03-29T09:00:00Z",
                None,
                1,
                "scan",
                "bootstrap_scan",
            ),
            (
                201,
                1,
                file_paths["prepared.glb"],
                "prepared.glb",
                "prepared.glb",
                110,
                "hash-prepared",
                "model/gltf-binary",
                "primary_source",
                None,
                "metadata_ready",
                "2026-03-29T09:01:00Z",
                "2026-03-29T09:01:00Z",
                None,
                1,
                "scan",
                "bootstrap_scan",
            ),
            (
                301,
                1,
                file_paths["draft.glb"],
                "draft.glb",
                "draft.glb",
                120,
                "hash-draft",
                "model/gltf-binary",
                "primary_source",
                None,
                "metadata_ready",
                "2026-03-29T09:02:00Z",
                "2026-03-29T09:02:00Z",
                None,
                1,
                "scan",
                "bootstrap_scan",
            ),
            (
                302,
                1,
                file_paths["draft-preview.png"],
                "draft-preview.png",
                "draft-preview.png",
                25,
                "hash-preview",
                "image/png",
                "secondary",
                301,
                "uploaded",
                "2026-03-29T09:02:30Z",
                "2026-03-29T09:02:30Z",
                None,
                0,
                "render",
                "thumbnail",
            ),
            (
                401,
                1,
                file_paths["published.glb"],
                "published.glb",
                "published.glb",
                130,
                "hash-published",
                "model/gltf-binary",
                "primary_source",
                None,
                "metadata_ready",
                "2026-03-29T09:03:00Z",
                "2026-03-29T09:03:00Z",
                None,
                1,
                "scan",
                "bootstrap_scan",
            ),
        ],
    )

    prepared_payload = {
        "metadata": {
            "title": "Prepared dataset",
            "creators": [{"name": "Museum"}],
        }
    }
    draft_payload = {
        "id": 9301,
        "conceptrecid": "8301",
        "links": {
            "self": "https://sandbox.zenodo.org/api/deposit/depositions/9301",
            "discard": "https://sandbox.zenodo.org/api/deposit/depositions/9301/actions/discard",
            "publish": "https://sandbox.zenodo.org/api/deposit/depositions/9301/actions/publish",
            "bucket": "https://sandbox.zenodo.org/api/files/bucket-9301",
            "html": "https://sandbox.zenodo.org/deposit/9301",
        },
        "metadata": {
            "title": "Draft dataset",
            "creators": [{"name": "Museum"}],
        },
    }
    published_payload = {
        "id": 9401,
        "doi": "10.5072/zenodo.9401",
        "conceptrecid": "8401",
        "conceptdoi": "10.5072/zenodo.8401",
        "links": {
            "html": "https://sandbox.zenodo.org/records/9401",
        },
        "metadata": {
            "title": "Published dataset",
        },
    }

    cursor.executemany(
        """
        INSERT INTO zenodo_records (
            record_id, project_id, source_file_id, record_title, record_status,
            record_metadata_json, zenodo_record_id, concept_rec_id, zenodo_doi, concept_doi,
            is_sandbox, created_timestamp, last_updated_timestamp, version, last_api_error,
            creation_api_response, last_publish_api_response
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                1,
                1,
                201,
                "Prepared dataset",
                "prepared",
                json.dumps(prepared_payload),
                None,
                None,
                None,
                None,
                1,
                "2026-03-29T09:10:00Z",
                "2026-03-29T09:10:00Z",
                "1.0.0",
                None,
                None,
                None,
            ),
            (
                2,
                1,
                301,
                "Draft dataset",
                "draft",
                json.dumps(draft_payload),
                "9301",
                "8301",
                None,
                None,
                1,
                "2026-03-29T09:11:00Z",
                "2026-03-29T09:12:00Z",
                "1.0.0",
                None,
                json.dumps(draft_payload),
                None,
            ),
            (
                3,
                1,
                401,
                "Published dataset",
                "published",
                json.dumps(published_payload),
                "9401",
                "8401",
                "10.5072/zenodo.9401",
                "10.5072/zenodo.8401",
                1,
                "2026-03-29T09:13:00Z",
                "2026-03-29T09:14:00Z",
                "1.0.1",
                None,
                None,
                json.dumps(published_payload),
            ),
        ],
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
            (1, 1, 201, file_paths["prepared.glb"], "main", None, None, None, None, None, "pending", None, None, None),
            (
                2,
                2,
                301,
                file_paths["draft.glb"],
                "main",
                None,
                None,
                None,
                None,
                None,
                "pending",
                None,
                None,
                None,
            ),
            (
                3,
                2,
                302,
                file_paths["draft-preview.png"],
                "generated",
                "zf-302",
                "draft-preview.png",
                "md5:preview",
                25,
                json.dumps({"self": "https://sandbox.zenodo.org/api/files/draft-preview.png"}),
                "uploaded",
                "2026-03-29T09:12:00Z",
                None,
                json.dumps({"status": "ok"}),
            ),
            (
                4,
                3,
                401,
                file_paths["published.glb"],
                "main",
                "zf-401",
                "published.glb",
                "md5:published",
                130,
                json.dumps({"self": "https://sandbox.zenodo.org/api/files/published.glb"}),
                "uploaded",
                "2026-03-29T09:14:00Z",
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
            (
                1,
                2,
                "discard",
                "https://sandbox.zenodo.org/api/deposit/depositions/9301/actions/discard",
                "2026-03-29T09:11:00Z",
                "2026-03-29T09:12:00Z",
            ),
            (
                2,
                3,
                "html",
                "https://sandbox.zenodo.org/records/9401",
                "2026-03-29T09:13:00Z",
                "2026-03-29T09:14:00Z",
            ),
        ],
    )
    cursor.executemany(
        """
        INSERT INTO zenodo_record_snapshots (
            snapshot_id, record_id, snapshot_stage, http_status, payload_json, created_timestamp
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                1,
                2,
                "prepared_before_draft",
                None,
                json.dumps({"metadata": {"title": "Draft dataset", "creators": [{"name": "Museum"}]}}),
                "2026-03-29T09:10:30Z",
            ),
            (
                2,
                2,
                "draft_created",
                201,
                json.dumps(draft_payload),
                "2026-03-29T09:11:00Z",
            ),
        ],
    )
    conn.commit()
    conn.close()


class TestSessionZenodoUtilityRoutes(unittest.TestCase):
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
            user = User(email="session-zenodo@example.com", role=UserRole.USER, is_verified=True)
            user.set_password("password123")
            db.session.add(user)
            db.session.commit()
            self.user_id = user.id
            self.token = create_access_token(identity=str(self.user_id))

            hdpc_path = os.path.join(self.temp_dir.name, "session.hdpc")
            _build_hdpc_zenodo_utility_fixture(hdpc_path, self.temp_dir.name)
            session_row = DBSession(
                user_id=self.user_id,
                session_dir=self.temp_dir.name,
                hdpc_path=hdpc_path,
                status="completed",
            )
            db.session.add(session_row)
            db.session.commit()
            self.session_id = session_row.id
            self.hdpc_path = hdpc_path

        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        self.temp_dir.cleanup()

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def test_uploadable_files_and_uploads_by_tab_routes(self):
        uploadable = self.client.get(
            f"/api/v1/sessions/{self.session_id}/zenodo/uploadable-files",
            headers=self._auth_headers(),
        )
        self.assertEqual(uploadable.status_code, 200)
        items = uploadable.get_json()["data"]["items"]
        self.assertEqual({item["required_action"] for item in items}, {
            "action_prepare_metadata",
            "action_create_api_draft",
            "action_upload_file",
        })

        pending_preparation = self.client.get(
            f"/api/v1/sessions/{self.session_id}/zenodo/uploads-by-tab?tab_id=pending_preparation",
            headers=self._auth_headers(),
        )
        self.assertEqual(pending_preparation.status_code, 200)
        pending_items = pending_preparation.get_json()["data"]["items"]
        self.assertEqual(len(pending_items), 1)
        self.assertEqual(pending_items[0]["filename"], "pending.glb")
        self.assertEqual(pending_items[0]["total_bundle_files"], 1)

        pending_operations = self.client.get(
            f"/api/v1/sessions/{self.session_id}/zenodo/uploads-by-tab?tab_id=pending_operations&search=prepared",
            headers=self._auth_headers(),
        )
        self.assertEqual(pending_operations.status_code, 200)
        operations_items = pending_operations.get_json()["data"]["items"]
        self.assertEqual(len(operations_items), 1)
        self.assertEqual(operations_items[0]["record_title"], "Prepared dataset")

        drafts = self.client.get(
            f"/api/v1/sessions/{self.session_id}/zenodo/uploads-by-tab?tab_id=drafts",
            headers=self._auth_headers(),
        )
        self.assertEqual(drafts.status_code, 200)
        draft_items = drafts.get_json()["data"]["items"]
        self.assertEqual(len(draft_items), 1)
        self.assertEqual(draft_items[0]["discard_link"], "https://sandbox.zenodo.org/api/deposit/depositions/9301/actions/discard")
        self.assertEqual(draft_items[0]["total_files_in_record"], 2)
        self.assertEqual(draft_items[0]["uploaded_files_in_record"], 1)

        published = self.client.get(
            f"/api/v1/sessions/{self.session_id}/zenodo/uploads-by-tab?tab_id=published",
            headers=self._auth_headers(),
        )
        self.assertEqual(published.status_code, 200)
        published_items = published.get_json()["data"]["items"]
        self.assertEqual(len(published_items), 1)
        self.assertEqual(published_items[0]["zenodo_doi"], "10.5072/zenodo.9401")

    def test_discard_draft_route_restores_local_state(self):
        from services.zenodo_credential_service import ZenodoCredentialService

        with self.app.app_context():
            ZenodoCredentialService().upsert_credential(
                owner_type="user", owner_id=self.user_id, environment="sandbox",
                token="test-sandbox-token", actor_user_id=self.user_id,
            )
        with patch(
            "services.hdpc_zenodo_service.requests.post",
            return_value=_DummyResponse(204, {}),
        ):
            response = self.client.post(
                f"/api/v1/sessions/{self.session_id}/records/2/discard-draft",
                headers=self._auth_headers(),
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]
        self.assertEqual(payload["restored_status"], "prepared")
        self.assertTrue(payload["remote_discard"]["success"])

        conn = sqlite3.connect(self.hdpc_path)
        conn.row_factory = sqlite3.Row
        try:
            record = conn.execute("SELECT * FROM zenodo_records WHERE record_id = 2").fetchone()
            self.assertEqual(record["record_status"], "prepared")
            self.assertIsNone(record["zenodo_record_id"])
            restored_payload = json.loads(record["record_metadata_json"])
            self.assertEqual(
                restored_payload,
                {"metadata": {"title": "Draft dataset", "creators": [{"name": "Museum"}]}},
            )
            file_rows = conn.execute(
                "SELECT upload_status, zenodo_file_id FROM record_files_map WHERE record_id = 2 ORDER BY map_id ASC"
            ).fetchall()
            self.assertEqual([row["upload_status"] for row in file_rows], ["pending", "pending"])
            self.assertTrue(all(row["zenodo_file_id"] is None for row in file_rows))
            link_count = conn.execute("SELECT COUNT(*) FROM zenodo_record_links WHERE record_id = 2").fetchone()[0]
            self.assertEqual(link_count, 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
