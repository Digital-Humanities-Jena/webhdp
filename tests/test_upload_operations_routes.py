import json
import unittest

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from constants import (
    UPLOAD_PROGRESS_FIELD,
    UPLOAD_STORAGE_MODE_FIELD,
    UPLOAD_SUBMIT_TOKEN_FIELD,
    UPLOAD_TASK_ID_FIELD,
    UPLOAD_WORKER_GROUP_ID_FIELD,
)
from database.database import db
from database.models import File, Session as DBSession, User, UserMetadata, UserRole
from middleware import setup_error_handlers
from routes.admin_routes import admin_bp
from routes.session_routes import session_bp


class _DummyProjectService:
    def _translate_path(self, path, to_container=True):
        return path


class TestUploadOperationRoutes(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        self.app.config["SECRET_KEY"] = "test-secret"
        self.app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
        self.app.project_service = _DummyProjectService()

        db.init_app(self.app)
        JWTManager(self.app)
        setup_error_handlers(self.app)
        self.app.register_blueprint(session_bp, url_prefix="/api/v1/sessions")
        self.app.register_blueprint(admin_bp, url_prefix="/api/v1/admin")

        with self.app.app_context():
            db.create_all()

            self.user = User(email="uploader@example.com", role=UserRole.USER, is_verified=True)
            self.user.set_password("password123")
            self.user.set_capabilities(["mounted_input_access"])
            self.other_user = User(email="other@example.com", role=UserRole.USER, is_verified=True)
            self.other_user.set_password("password123")
            self.admin = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
            self.admin.set_password("password123")
            db.session.add_all([self.user, self.other_user, self.admin])
            db.session.commit()

            self.user_token = create_access_token(identity=str(self.user.id))
            self.other_user_token = create_access_token(identity=str(self.other_user.id))
            self.admin_token = create_access_token(identity=str(self.admin.id))

            self.session = DBSession(
                user_id=self.user.id,
                session_dir="/tmp/upload-session-1",
                hdpc_path="/tmp/upload-session-1/session.hdpc",
                status="processing",
            )
            self.completed_session = DBSession(
                user_id=self.user.id,
                session_dir="/tmp/upload-session-2",
                hdpc_path="/tmp/upload-session-2/session.hdpc",
                status="ready",
            )
            self.local_preflight_session = DBSession(
                user_id=self.user.id,
                session_dir="/tmp/upload-session-3",
                hdpc_path="/tmp/upload-session-3/session.hdpc",
                status="pending",
            )
            db.session.add_all([self.session, self.completed_session, self.local_preflight_session])
            db.session.commit()
            self.session_id = self.session.id
            self.completed_session_id = self.completed_session.id
            self.local_preflight_session_id = self.local_preflight_session.id

            db.session.add_all(
                [
                    File(session_id=self.session_id, filename="a.glb", path="/tmp/a.glb", status="uploaded"),
                    File(session_id=self.session_id, filename="b.glb", path="/tmp/b.glb", status="pending"),
                    File(session_id=self.session_id, filename="c.glb", path="/tmp/c.glb", status="failed"),
                    File(session_id=self.completed_session_id, filename="done.glb", path="/tmp/done.glb", status="uploaded"),
                ]
            )

            db.session.add_all(
                [
                    UserMetadata(session_id=self.session_id, field_name=UPLOAD_SUBMIT_TOKEN_FIELD, field_value="token-1"),
                    UserMetadata(session_id=self.session_id, field_name=UPLOAD_TASK_ID_FIELD, field_value="task-1"),
                    UserMetadata(session_id=self.session_id, field_name=UPLOAD_WORKER_GROUP_ID_FIELD, field_value="group-1"),
                    UserMetadata(session_id=self.session_id, field_name=UPLOAD_STORAGE_MODE_FIELD, field_value="cloud_backup"),
                    UserMetadata(
                        session_id=self.session_id,
                        field_name=UPLOAD_PROGRESS_FIELD,
                        field_value=json.dumps(
                            {
                                "current_stage": "processing_files",
                                "status_message": "Processing files...",
                                "total_files": 3,
                                "processed_count": 2,
                                "failed_count": 1,
                                "percent": 66.7,
                            }
                        ),
                    ),
                    UserMetadata(session_id=self.completed_session_id, field_name=UPLOAD_SUBMIT_TOKEN_FIELD, field_value="token-2"),
                    UserMetadata(session_id=self.completed_session_id, field_name=UPLOAD_STORAGE_MODE_FIELD, field_value="local"),
                    UserMetadata(
                        session_id=self.completed_session_id,
                        field_name=UPLOAD_PROGRESS_FIELD,
                        field_value=json.dumps(
                            {
                                "current_stage": "completed",
                                "status_message": "Upload completed.",
                                "total_files": 1,
                                "processed_count": 1,
                                "failed_count": 0,
                                "percent": 100,
                            }
                        ),
                    ),
                    UserMetadata(
                        session_id=self.local_preflight_session_id,
                        field_name="msf_profile",
                        field_value=json.dumps(
                            {
                                "storage_mode": "local",
                                "scan_started": False,
                                "file_path": "/tmp/local-input/upload.csv",
                                "source_file_path": "/tmp/local-input/upload.csv",
                                "directory_root": "/tmp/local-input/models",
                            }
                        ),
                    ),
                ]
            )
            db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _auth_headers(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_user_can_list_upload_operations(self):
        response = self.client.get(
            "/api/v1/sessions/upload-operations",
            headers=self._auth_headers(self.user_token),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(len(payload["data"]["operations"]), 3)
        operations = {
            item["session_id"]: item
            for item in payload["data"]["operations"]
        }
        first = next(iter(operations.values()))
        self.assertIn("progress", first)
        self.assertIn("file_counts", first)
        self.assertIn("workflow_hint", first)
        self.assertEqual(operations[self.session_id]["status"], "queued")
        self.assertEqual(operations[self.completed_session_id]["status"], "scanned")
        self.assertEqual(operations[self.local_preflight_session_id]["status"], "queued")

    def test_upload_operation_detail_enforces_ownership(self):
        response = self.client.get(
            f"/api/v1/sessions/upload-operations/{self.session_id}",
            headers=self._auth_headers(self.other_user_token),
        )
        self.assertEqual(response.status_code, 404)

    def test_session_progress_includes_upload_progress(self):
        response = self.client.get(
            f"/api/v1/sessions/{self.session_id}/progress",
            headers=self._auth_headers(self.user_token),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["data"]["upload_progress"]["current_stage"], "processing_files")
        self.assertEqual(payload["data"]["upload_progress"]["failed_count"], 1)
        self.assertEqual(payload["data"]["upload_progress"]["session_status"], "queued")
        self.assertEqual(payload["data"]["workflow_file_counts"]["registered"], 1)
        self.assertEqual(payload["data"]["workflow_file_counts"]["missing"], 1)
        self.assertEqual(payload["data"]["workflow_file_counts"]["queued"], 1)

    def test_admin_can_list_running_upload_operations(self):
        response = self.client.get(
            "/api/v1/admin/upload-operations?status=running",
            headers=self._auth_headers(self.admin_token),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        operations = payload["data"]["operations"]
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0]["session_id"], self.session_id)
        self.assertEqual(operations[0]["user_email"], "uploader@example.com")

    def test_local_preflight_session_has_persistent_monitor_detail(self):
        response = self.client.get(
            f"/api/v1/sessions/upload-operations/{self.local_preflight_session_id}",
            headers=self._auth_headers(self.user_token),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        operation = payload["data"]["operation"]
        self.assertEqual(operation["status"], "queued")
        self.assertEqual(operation["progress"]["current_stage"], "awaiting_scan_start")
        self.assertEqual(operation["storage_mode"], "local")
        self.assertTrue(operation["workflow_hint"]["can_resume_workflow"])
        self.assertEqual(operation["workflow_hint"]["resume_route"], "/workflow/msf-analysis")


if __name__ == "__main__":
    unittest.main()
