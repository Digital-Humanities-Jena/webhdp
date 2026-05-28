import io
import os
import secrets
import shutil
import sqlite3
import tempfile
import unittest

import pytest
pytest.importorskip("flask_jwt_extended")
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import Session as DBSession
from database.models import User, UserRole
from middleware import setup_error_handlers
from routes.admin_routes import admin_bp
from routes.session_routes import session_bp


class DummySessionManager:
    def __init__(self, base_path: str):
        self.base_path = base_path

    def create_session_dirs(self):
        session_dir = os.path.join(self.base_path, f"hdp_session_{secrets.token_hex(4)}")
        os.makedirs(session_dir, exist_ok=True)

        hdpc_path = os.path.join(session_dir, "session.hdpc")
        data_out_path = os.path.join(session_dir, "outputs")
        uploads_path = os.path.join(session_dir, "uploads")
        os.makedirs(data_out_path, exist_ok=True)
        os.makedirs(uploads_path, exist_ok=True)
        return hdpc_path, data_out_path, uploads_path, session_dir


def _build_hdpc_bytes(record_count: int = 2, *, include_provenance: bool = False) -> bytes:
    fd, temp_path = tempfile.mkstemp(suffix=".hdpc")
    os.close(fd)

    conn = sqlite3.connect(temp_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE zenodo_records (
            record_id INTEGER PRIMARY KEY,
            source_file_id INTEGER,
            record_title TEXT,
            record_status TEXT,
            record_metadata_json TEXT,
            zenodo_record_id TEXT,
            concept_rec_id TEXT,
            zenodo_doi TEXT,
            is_sandbox INTEGER,
            created_timestamp TEXT,
            last_updated_timestamp TEXT
        )
        """
    )
    for idx in range(1, record_count + 1):
        metadata = (
            '{"metadata":{"title":"Imported Record %d"},'
            '"links":{"html":"https://sandbox.zenodo.org/records/%d"}}'
        ) % (idx, 1000 + idx)
        cursor.execute(
            """
            INSERT INTO zenodo_records (
                record_id,
                source_file_id,
                record_title,
                record_status,
                record_metadata_json,
                zenodo_record_id,
                concept_rec_id,
                zenodo_doi,
                is_sandbox,
                created_timestamp,
                last_updated_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                idx,
                None,
                f"Imported Record {idx}",
                "draft",
                metadata,
                str(1000 + idx),
                str(5000 + idx),
                f"10.1234/imported.{idx}",
                1,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )
    if include_provenance:
        cursor.execute(
            """
            CREATE TABLE hdpc_provenance (
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
        )
        cursor.execute(
            """
            INSERT INTO hdpc_provenance (
                provenance_id, creator_user_public_id, creator_display_name, creator_orcid,
                creator_profile_url, institution_public_id, institution_name, institution_slug,
                institution_profile_url, source_session_id, created_at, updated_at
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "source-user-public-id",
                "Ada Source",
                "0000-0000-0000-0001",
                "https://webhdp.example/profiles/users/ada-source",
                "source-institution-public-id",
                "Source Museum",
                "source-museum",
                "https://webhdp.example/profiles/institutions/source-museum",
                99,
                "2026-04-29T12:00:00+00:00",
                "2026-04-29T12:00:00+00:00",
            ),
        )
    conn.commit()
    conn.close()

    with open(temp_path, "rb") as file_obj:
        data = file_obj.read()
    os.remove(temp_path)
    return data


class TestHdpcImportRoutes(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp(prefix="hdpc-import-test-")

        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        self.app.config["SECRET_KEY"] = "test-secret"
        self.app.config["JWT_SECRET_KEY"] = "test-jwt-secret"

        db.init_app(self.app)
        JWTManager(self.app)
        setup_error_handlers(self.app)

        self.app.session_manager = DummySessionManager(self.temp_root)
        self.app.register_blueprint(session_bp, url_prefix="/api/v1/sessions")
        self.app.register_blueprint(admin_bp, url_prefix="/api/v1/admin")

        with self.app.app_context():
            db.create_all()

            self.user = User(email="user@example.com", role=UserRole.USER, is_verified=True)
            self.user.set_password("password123")
            self.admin = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
            self.admin.set_password("password123")
            db.session.add(self.user)
            db.session.add(self.admin)
            db.session.commit()

            self.user_id = self.user.id
            self.admin_id = self.admin.id
            self.user_token = create_access_token(identity=str(self.user_id))
            self.admin_token = create_access_token(identity=str(self.admin_id))

        self.client = self.app.test_client()
        self.hdpc_bytes = _build_hdpc_bytes(record_count=2)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _auth_headers(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    def test_user_can_import_hdpc_and_view_records(self):
        response = self.client.post(
            "/api/v1/sessions/import-hdpc",
            headers=self._auth_headers(self.user_token),
            data={"hdpc_file": (io.BytesIO(self.hdpc_bytes), "records.hdpc")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201)
        payload = response.get_json()

        session_id = payload["data"]["session"]["id"]
        self.assertIsNotNone(session_id)
        self.assertEqual(payload["data"]["import_summary"]["record_count"], 2)
        self.assertEqual(payload["data"]["import_summary"]["artifact_kind"], "legacy_raw")
        self.assertEqual(payload["data"]["session"]["origin_type"], "hdpc_import")
        self.assertEqual(payload["data"]["session"]["access_mode"], "full")

        with self.app.app_context():
            imported_session = db.session.get(DBSession, session_id)
            self.assertIsNotNone(imported_session)
            self.assertEqual(imported_session.user_id, self.user_id)
            self.assertEqual(imported_session.status, "completed")
            self.assertEqual(imported_session.origin_type, "hdpc_import")
            self.assertEqual(imported_session.access_mode, "full")
            self.assertTrue(os.path.exists(imported_session.hdpc_path))

        records_response = self.client.get(
            f"/api/v1/sessions/{session_id}/records",
            headers=self._auth_headers(self.user_token),
        )
        self.assertEqual(records_response.status_code, 200)
        records_payload = records_response.get_json()
        self.assertEqual(records_payload["data"]["summary"]["total_records"], 2)

    def test_import_preserves_hdpc_provenance_in_session_origin_metadata(self):
        response = self.client.post(
            "/api/v1/sessions/import-hdpc",
            headers=self._auth_headers(self.user_token),
            data={"hdpc_file": (io.BytesIO(_build_hdpc_bytes(record_count=1, include_provenance=True)), "records.hdpc")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201)
        session_id = response.get_json()["data"]["session"]["id"]

        with self.app.app_context():
            imported_session = db.session.get(DBSession, session_id)
            origin_metadata = imported_session.origin_metadata
            provenance = origin_metadata["hdpc_provenance"]
            self.assertEqual(provenance["creator_user_public_id"], "source-user-public-id")
            self.assertEqual(provenance["creator_display_name"], "Ada Source")
            self.assertEqual(provenance["institution_public_id"], "source-institution-public-id")

    def test_admin_can_import_hdpc_for_other_user(self):
        response = self.client.post(
            f"/api/v1/admin/users/{self.user_id}/hdpc/import",
            headers=self._auth_headers(self.admin_token),
            data={"hdpc_file": (io.BytesIO(self.hdpc_bytes), "admin-import.hdpc")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201)
        payload = response.get_json()

        self.assertEqual(payload["data"]["user"]["id"], self.user_id)
        self.assertEqual(payload["data"]["import_summary"]["record_count"], 2)
        session_id = payload["data"]["session"]["id"]

        with self.app.app_context():
            imported_session = db.session.get(DBSession, session_id)
            self.assertIsNotNone(imported_session)
            self.assertEqual(imported_session.user_id, self.user_id)

    def test_non_admin_cannot_import_hdpc_for_other_user(self):
        response = self.client.post(
            f"/api/v1/admin/users/{self.admin_id}/hdpc/import",
            headers=self._auth_headers(self.user_token),
            data={"hdpc_file": (io.BytesIO(self.hdpc_bytes), "forbidden.hdpc")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
