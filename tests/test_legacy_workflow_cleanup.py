import os
import sqlite3
import tempfile
import unittest

from flask import Flask

from constants import WORKFLOW_STATE_FIELD
from database.database import db
from database.models import Session as DBSession, User, UserMetadata, UserRole
from scripts import cleanup_legacy_workflow_state as cleanup_script
from services.dataset_integrity_service import read_session_records
from services.hdpc_schema_service import connect_hdpc, ensure_hdpc_schema


def _create_duplicate_record_hdpc(hdpc_path: str, session_root: str) -> None:
    uploads_dir = os.path.join(session_root, "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    source_path = os.path.join(uploads_dir, "model.glb")
    with open(source_path, "w", encoding="utf-8") as handle:
        handle.write("glb")

    conn = connect_hdpc(hdpc_path, timeout=30, row_factory=sqlite3.Row)
    try:
        project_id = ensure_hdpc_schema(conn, hdpc_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO source_files (
                project_id, absolute_path, relative_path, filename, size_bytes, mime_type,
                file_type, status, added_timestamp, is_primary_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                source_path,
                "model.glb",
                "model.glb",
                3,
                "model/gltf-binary",
                "primary_source",
                "ready",
                "2026-03-31T10:00:00Z",
                1,
            ),
        )
        source_file_id = int(cursor.lastrowid)

        cursor.execute(
            """
            INSERT INTO zenodo_records (
                record_id, project_id, source_file_id, record_title, record_status,
                record_metadata_json, is_sandbox, created_timestamp, last_updated_timestamp, record_origin
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                project_id,
                source_file_id,
                "Prepared placeholder",
                "prepared",
                '{"metadata":{"title":"Prepared placeholder"}}',
                1,
                "2026-03-31T10:05:00Z",
                "2026-03-31T10:05:00Z",
                "submit_pipeline",
            ),
        )
        cursor.execute(
            """
            INSERT INTO zenodo_records (
                record_id, project_id, source_file_id, record_title, record_status,
                record_metadata_json, zenodo_record_id, is_sandbox, created_timestamp,
                last_updated_timestamp, record_origin
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                2,
                project_id,
                source_file_id,
                "Draft canonical record",
                "draft",
                '{"metadata":{"title":"Draft canonical record"},"links":{"html":"https://sandbox.zenodo.org/records/9002"}}',
                "9002",
                1,
                "2026-03-31T10:10:00Z",
                "2026-03-31T10:10:00Z",
                "submit_pipeline",
            ),
        )
        cursor.execute(
            """
            INSERT INTO record_files_map (
                record_id, file_id, file_path, file_purpose, upload_status
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (1, source_file_id, source_path, "main", "pending"),
        )
        cursor.execute(
            """
            INSERT INTO record_files_map (
                record_id, file_id, file_path, file_purpose, upload_status
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (2, source_file_id, source_path, "main", "uploaded"),
        )
        conn.commit()
    finally:
        conn.close()


class TestLegacyWorkflowCleanup(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        self.app.config["SECRET_KEY"] = "test-secret"
        self.app.config["JWT_SECRET_KEY"] = "test-jwt"

        db.init_app(self.app)

        with self.app.app_context():
            db.create_all()
            user = User(email="cleanup@example.com", role=UserRole.USER, is_verified=True)
            user.set_password("password")
            db.session.add(user)
            db.session.commit()
            self.user_id = user.id

            self.hdpc_path = os.path.join(self.temp_dir.name, "session.hdpc")
            _create_duplicate_record_hdpc(self.hdpc_path, self.temp_dir.name)

            session_row = DBSession(
                user_id=self.user_id,
                session_dir=self.temp_dir.name,
                hdpc_path=self.hdpc_path,
                status="ready",
            )
            db.session.add(session_row)
            db.session.flush()
            db.session.add(
                UserMetadata(
                    session_id=session_row.id,
                    field_name=WORKFLOW_STATE_FIELD,
                    field_value='{"phase":"files","current_step":3}',
                )
            )
            db.session.commit()
            self.session_id = session_row.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        self.temp_dir.cleanup()

    def test_read_session_records_hides_legacy_placeholder_duplicates(self):
        with self.app.app_context():
            session_row = db.session.get(DBSession, self.session_id)
            records = read_session_records(session_row)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["local_record_id"], 2)
        self.assertEqual(records[0]["record_status"], "draft")

    def test_cleanup_script_reports_and_applies_placeholder_cleanup(self):
        with self.app.app_context():
            dry_run = cleanup_script.run_cleanup(apply_changes=False, session_ids=[self.session_id])
            self.assertEqual(dry_run["session_count"], 1)
            self.assertEqual(dry_run["status_updates"], 0)
            self.assertEqual(dry_run["hidden_legacy_placeholder_records"], 1)
            self.assertEqual(dry_run["sessions"][0]["normalized_status"], "scanned")
            self.assertEqual(dry_run["sessions"][0]["placeholder_record_ids"], [1])

            applied = cleanup_script.run_cleanup(apply_changes=True, session_ids=[self.session_id])
            self.assertEqual(applied["status_updates"], 1)
            self.assertEqual(applied["placeholder_origin_updates"], 1)

            session_row = db.session.get(DBSession, self.session_id)
            self.assertEqual(session_row.status, "scanned")

        with sqlite3.connect(self.hdpc_path) as conn:
            row = conn.execute("SELECT record_origin FROM zenodo_records WHERE record_id = 1").fetchone()
        self.assertEqual(row[0], "legacy_placeholder")


if __name__ == "__main__":
    unittest.main()
