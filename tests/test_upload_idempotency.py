import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import File
from database.models import Session as DBSession
from database.models import SystemConfig, User, UserMetadata, UserRole
from routes.session_routes import (
    UPLOAD_SUBMIT_TOKEN_FIELD,
    UPLOAD_TASK_ID_FIELD,
    UPLOAD_WORKER_GROUP_ID_FIELD,
    WORKFLOW_STATE_FIELD,
    session_bp,
)


class _DummyProjectService:
    def _translate_path(self, path, to_container=True):
        return path


class TestUploadIdempotency(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        self.app.config["SECRET_KEY"] = "test-secret"
        self.app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
        self.app.config["LOCAL_INPUT_PATH"] = self._temp_dir.name
        self.app.project_service = _DummyProjectService()

        db.init_app(self.app)
        JWTManager(self.app)
        self.app.register_blueprint(session_bp, url_prefix="/api/v1/sessions")

        with self.app.app_context():
            db.create_all()
            user = User(email="idempotency@example.com", role=UserRole.USER, is_verified=True)
            user.set_password("password123")
            db.session.add(user)
            db.session.add(
                SystemConfig(
                    key="storage_config",
                    value=json.dumps(
                        {
                            "primary_storage": "dropbox",
                            "secondary_storage": "gdrive",
                            "allow_server_fallback": False,
                            "storage_mode": "local",
                        }
                    ),
                )
            )
            db.session.commit()
            self.user_id = user.id
            self.token = create_access_token(identity=str(self.user_id))

            session_row = DBSession(
                user_id=self.user_id,
                session_dir="/tmp/hdp_session_test",
                hdpc_path="/tmp/hdp_session_test/session.hdpc",
                status="processing",
            )
            db.session.add(session_row)
            db.session.commit()
            self.session_id = session_row.id

            db.session.add(
                UserMetadata(
                    session_id=self.session_id,
                    field_name=UPLOAD_SUBMIT_TOKEN_FIELD,
                    field_value="upl_test_token_1",
                )
            )
            db.session.add(
                UserMetadata(
                    session_id=self.session_id,
                    field_name=UPLOAD_TASK_ID_FIELD,
                    field_value="task-abc-123",
                )
            )
            db.session.add_all(
                [
                    File(
                        session_id=self.session_id,
                        filename="retry_failed.glb",
                        path=os.path.join(self._temp_dir.name, "retry_failed.glb"),
                        status="failed",
                    ),
                    File(
                        session_id=self.session_id,
                        filename="retry_pending.glb",
                        path=os.path.join(self._temp_dir.name, "retry_pending.glb"),
                        status="pending",
                    ),
                ]
            )
            with open(os.path.join(self._temp_dir.name, "retry_pending.glb"), "wb") as handle:
                handle.write(b"glb")
            db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        self._temp_dir.cleanup()

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def test_directory_submit_reuses_existing_token_context(self):
        response = self.client.post(
            "/api/v1/sessions/directory",
            headers=self._auth_headers(),
            data={"submit_token": "upl_test_token_1"},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 202)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertTrue(payload["data"]["reused"])
        self.assertEqual(payload["data"]["session_id"], self.session_id)
        self.assertEqual(payload["data"]["task_id"], "task-abc-123")

    def test_directory_preflight_accepts_windows_archive_separators(self):
        import io
        import zipfile

        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("nested\\model.obj", "v 0 0 0\n")
        archive_bytes.seek(0)
        with patch("services.cloud_upload_service.CloudUploadService.get_storage_mode", return_value="server_only"), patch(
            "services.cloud_upload_service.CloudUploadService.get_available_storage", return_value=("server", "Ready")
        ):
            response = self.client.post(
                "/api/v1/sessions/directory?validate_only=true",
                headers=self._auth_headers(),
                data={"zip_file": (archive_bytes, "windows.zip"),
                      "msf_file": (io.BytesIO(b"filename,title\nmodel.obj,Model\n"), "metadata.csv")},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()["data"]["msf_validation"]["is_valid"])

    def test_recover_endpoint_returns_existing_context(self):
        response = self.client.post(
            "/api/v1/sessions/directory/recover",
            headers=self._auth_headers(),
            json={"submit_token": "upl_test_token_1"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertTrue(payload["data"]["reused"])
        self.assertEqual(payload["data"]["session_id"], self.session_id)
        self.assertEqual(payload["data"]["task_id"], "task-abc-123")
        self.assertIn("task_state", payload["data"])

    def test_recover_rejects_invalid_submit_token(self):
        response = self.client.post(
            "/api/v1/sessions/directory/recover",
            headers=self._auth_headers(),
            json={"submit_token": "not allowed !"},
        )
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["success"])

    def test_recover_returns_not_found_for_unknown_token(self):
        response = self.client.post(
            "/api/v1/sessions/directory/recover",
            headers=self._auth_headers(),
            json={"submit_token": "upl_unknown_token"},
        )
        self.assertEqual(response.status_code, 404)
        payload = response.get_json()
        self.assertFalse(payload["success"])

    def test_list_sessions_includes_msf_repair_hint(self):
        with self.app.app_context():
            db.session.get(User, self.user_id).set_capabilities(["mounted_input_access"])
            repair_session = DBSession(
                user_id=self.user_id,
                session_dir="/tmp/hdp_session_repair",
                hdpc_path="/tmp/hdp_session_repair/session.hdpc",
                status="pending",
            )
            db.session.add(repair_session)
            db.session.commit()
            repair_session_id = repair_session.id
            db.session.add(
                UserMetadata(
                    session_id=repair_session_id,
                    field_name="msf_profile",
                    field_value=json.dumps(
                        {
                            "storage_mode": "local",
                            "file_path": "/tmp/msf.csv",
                            "source_file_path": "/tmp/msf.csv",
                            "directory_root": "/tmp/local_input",
                            "scan_started": False,
                        }
                    ),
                )
            )
            db.session.commit()

        response = self.client.get("/api/v1/sessions", headers=self._auth_headers())
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        sessions = payload["data"]["sessions"]
        current = next(item for item in sessions if item["id"] == repair_session_id)
        self.assertEqual(current["status"], "queued")
        self.assertTrue(current["workflow_hint"]["requires_msf_repair"])
        self.assertEqual(current["workflow_hint"]["storage_mode"], "local")

    def test_local_msf_lists_nested_subdirectories(self):
        with self.app.app_context():
            db.session.get(User, self.user_id).set_capabilities(["mounted_input_access"])
            db.session.commit()
            local_input = self.app.config.get("LOCAL_INPUT_PATH")
            self.assertIsNotNone(local_input)

        import os
        os.makedirs(os.path.join(local_input, "fr_bench_7068946"), exist_ok=True)
        os.makedirs(os.path.join(local_input, "rcin"), exist_ok=True)
        with open(os.path.join(local_input, "fr_bench_7068946", "model_a.glb"), "wb") as handle:
            handle.write(b"glb")
        with open(os.path.join(local_input, "rcin", "model_b.glb"), "wb") as handle:
            handle.write(b"glb")
        with open(os.path.join(local_input, "rcin_dataset.xlsx"), "wb") as handle:
            handle.write(b"msf")

        with patch("services.cloud_upload_service.CloudUploadService.get_storage_mode", return_value="local"):
            response = self.client.get("/api/v1/sessions/local-msf", headers=self._auth_headers())
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        subdirectories = payload["data"]["subdirectories"]
        relative_paths = {item["relative_path"] for item in subdirectories}
        self.assertIn("fr_bench_7068946", relative_paths)
        self.assertIn("rcin", relative_paths)
        self.assertGreaterEqual(len(subdirectories), 2)

    def test_session_nodes_reads_local_hdpc_without_external_project_load(self):
        session_dir = os.path.join(self._temp_dir.name, "session_nodes")
        os.makedirs(session_dir, exist_ok=True)
        hdpc_path = os.path.join(session_dir, "session.hdpc")
        source_path = os.path.join(session_dir, "valid.glb")
        excluded_path = os.path.join(session_dir, "__MACOSX", "ignored.glb")
        os.makedirs(os.path.dirname(excluded_path), exist_ok=True)
        with open(source_path, "wb") as handle:
            handle.write(b"glb")
        with open(excluded_path, "wb") as handle:
            handle.write(b"glb")

        conn = sqlite3.connect(hdpc_path)
        try:
            conn.execute(
                """
                CREATE TABLE source_files (
                    file_id INTEGER PRIMARY KEY,
                    filename TEXT,
                    absolute_path TEXT,
                    relative_path TEXT,
                    file_type TEXT,
                    status TEXT,
                    size_bytes INTEGER,
                    mime_type TEXT,
                    pipeline_source TEXT,
                    step_source TEXT,
                    added_timestamp TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO source_files (
                    file_id, filename, absolute_path, relative_path, file_type, status,
                    size_bytes, mime_type, pipeline_source, step_source, added_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    "valid.glb",
                    source_path,
                    "valid.glb",
                    "primary_source",
                    "ready",
                    100,
                    "model/gltf-binary",
                    "ingestion",
                    "scan",
                    "2026-03-10T10:00:00Z",
                ),
            )
            conn.execute(
                """
                INSERT INTO source_files (
                    file_id, filename, absolute_path, relative_path, file_type, status,
                    size_bytes, mime_type, pipeline_source, step_source, added_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    2,
                    "ignored.glb",
                    excluded_path,
                    "__MACOSX/ignored.glb",
                    "primary_source",
                    "ready",
                    100,
                    "model/gltf-binary",
                    "ingestion",
                    "scan",
                    "2026-03-10T10:00:00Z",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        with self.app.app_context():
            session_row = db.session.get(DBSession, self.session_id)
            session_row.session_dir = session_dir
            session_row.hdpc_path = hdpc_path
            db.session.add(
                File(
                    session_id=self.session_id,
                    filename="valid.glb",
                    path=source_path,
                    status="uploaded",
                )
            )
            db.session.commit()

        response = self.client.get(
            f"/api/v1/sessions/{self.session_id}/nodes",
            headers=self._auth_headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        nodes = payload["data"]["nodes"]
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["filename"], "valid.glb")
        self.assertEqual(nodes[0]["validation_status"], "registered")
        self.assertEqual(nodes[0]["upload_status"], "registered")
        self.assertEqual(nodes[0]["status"], "registered")
        self.assertEqual(nodes[0]["legacy_validation_status"], "ready")
        self.assertEqual(nodes[0]["legacy_upload_status"], "uploaded")
        self.assertEqual(nodes[0]["absolute_path"], source_path)

    def test_workflow_state_routes_and_resume_hint(self):
        with self.app.app_context():
            db.session.add(
                UserMetadata(
                    session_id=self.session_id,
                    field_name=WORKFLOW_STATE_FIELD,
                    field_value=json.dumps(
                        {
                            "phase": "pipeline",
                            "current_step": 6,
                            "is_batch_mode": True,
                            "selected_file_keys": ["/tmp/hdp_session_test/uploads/model_a.glb"],
                            "selected_pipeline": {"identifier": "render", "name": "render"},
                        }
                    ),
                )
            )
            db.session.commit()

        get_response = self.client.get(
            f"/api/v1/sessions/{self.session_id}/workflow-state",
            headers=self._auth_headers(),
        )
        self.assertEqual(get_response.status_code, 200)
        get_payload = get_response.get_json()
        self.assertTrue(get_payload["success"])
        self.assertEqual(get_payload["data"]["state"]["phase"], "pipeline")
        self.assertTrue(get_payload["data"]["state"]["is_batch_mode"])

        put_response = self.client.put(
            f"/api/v1/sessions/{self.session_id}/workflow-state",
            headers=self._auth_headers(),
            json={
                "phase": "processing",
                "submission_id": 42,
                "pipeline_run_id": "run-native-123",
                "selected_pipeline": {"identifier": "metadata_only"},
            },
        )
        self.assertEqual(put_response.status_code, 200)
        put_payload = put_response.get_json()
        self.assertTrue(put_payload["success"])
        self.assertEqual(put_payload["data"]["state"]["phase"], "processing")
        self.assertEqual(put_payload["data"]["state"]["submission_id"], 42)
        self.assertEqual(put_payload["data"]["state"]["pipeline_run_id"], "run-native-123")
        self.assertEqual(put_payload["data"]["state"]["current_step"], 7)

        list_response = self.client.get("/api/v1/sessions", headers=self._auth_headers())
        self.assertEqual(list_response.status_code, 200)
        list_payload = list_response.get_json()
        current = next(item for item in list_payload["data"]["sessions"] if item["id"] == self.session_id)
        self.assertEqual(current["status"], "submitting")
        self.assertTrue(current["workflow_hint"]["can_resume_workflow"])
        self.assertEqual(current["workflow_hint"]["resume_phase"], "processing")
        self.assertEqual(current["workflow_hint"]["resume_route"], "/workflow/submit")
        self.assertEqual(current["workflow_hint"]["submission_id"], 42)
        self.assertEqual(current["workflow_hint"]["pipeline_run_id"], "run-native-123")
        self.assertEqual(current["workflow_hint"]["session_status"], "submitting")

    def test_resume_revalidates_files_without_worker_group(self):
        response = self.client.post(
            f"/api/v1/sessions/{self.session_id}/resume",
            headers=self._auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["count"], 2)
        self.assertEqual(payload["data"]["resumed_count"], 1)
        self.assertEqual(payload["data"]["failed_count"], 1)
        self.assertIsNone(payload["data"]["worker_group_id"])

        with self.app.app_context():
            session_row = db.session.get(DBSession, self.session_id)
            self.assertEqual(session_row.status, "scanned")
            statuses = {
                row.filename: row.status
                for row in File.query.filter(File.session_id == self.session_id).all()
            }
            self.assertEqual(statuses["retry_failed.glb"], "failed")
            self.assertEqual(statuses["retry_pending.glb"], "uploaded")
            worker_group_rows = UserMetadata.query.filter_by(
                session_id=self.session_id,
                field_name=UPLOAD_WORKER_GROUP_ID_FIELD,
            ).all()
            self.assertEqual(worker_group_rows, [])


if __name__ == "__main__":
    unittest.main()
