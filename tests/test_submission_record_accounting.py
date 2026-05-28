import json
import os
import sqlite3
import tempfile
import unittest

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import File, Session as DBSession, Submission, User, UserMetadata, UserRole
from routes.session_routes import WORKFLOW_STATE_FIELD, session_bp
from routes.submission_routes import submission_bp


def _build_hdpc_fixture(path: str, root_dir: str) -> dict[str, object]:
    input_dir = os.path.join(root_dir, "local_input", "rcin")
    os.makedirs(input_dir, exist_ok=True)
    output_dir = os.path.join(root_dir, "outputs", "model_a")
    os.makedirs(output_dir, exist_ok=True)

    source_paths = {
        "model_a.glb": os.path.join(input_dir, "model_a.glb"),
        "model_b.glb": os.path.join(input_dir, "model_b.glb"),
        "model_c.glb": os.path.join(input_dir, "model_c.glb"),
    }
    for source_path in source_paths.values():
        with open(source_path, "w", encoding="utf-8") as handle:
            handle.write("glb")

    rendered_paths = [
        os.path.join(output_dir, "model_a_r000.png"),
        os.path.join(output_dir, "model_a_r090.png"),
    ]
    for rendered_path in rendered_paths:
        with open(rendered_path, "w", encoding="utf-8") as handle:
            handle.write("png")

    conn = sqlite3.connect(path)
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
    cursor.execute(
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
    cursor.execute(
        """
        CREATE TABLE record_files_map (
            record_id INTEGER,
            file_id INTEGER,
            file_purpose TEXT,
            upload_status TEXT,
            upload_timestamp TEXT,
            file_path TEXT
        )
        """
    )

    source_rows = [
        (101, "model_a.glb", source_paths["model_a.glb"], "rcin/model_a.glb", "model", "ready"),
        (102, "model_b.glb", source_paths["model_b.glb"], "rcin/model_b.glb", "model", "ready"),
        (103, "model_c.glb", source_paths["model_c.glb"], "rcin/model_c.glb", "model", "ready"),
    ]
    for file_id, filename, absolute_path, relative_path, file_type, status in source_rows:
        cursor.execute(
            """
            INSERT INTO source_files (
                file_id, filename, absolute_path, relative_path, file_type, status,
                size_bytes, mime_type, pipeline_source, step_source, added_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_id,
                filename,
                absolute_path,
                relative_path,
                file_type,
                status,
                100,
                "model/gltf-binary",
                "render",
                "scan",
                "2026-03-10T10:00:00Z",
            ),
        )

    zenodo_rows = [
        (
            1,
            101,
            "Prepared A",
            "prepared",
            '{"metadata":{"title":"Prepared A"},"links":{"html":"https://sandbox.zenodo.org/records/9001"}}',
        ),
        (
            2,
            102,
            "Prepared B",
            "prepared",
            '{"metadata":{"title":"Prepared B"},"links":{"html":"https://sandbox.zenodo.org/records/9002"}}',
        ),
        (
            3,
            103,
            "Prepared C",
            "prepared",
            '{"metadata":{"title":"Prepared C"},"links":{"html":"https://sandbox.zenodo.org/records/9003"}}',
        ),
        (
            4,
            101,
            "Processed A",
            "published",
            '{"metadata":{"title":"Processed A"},"files":[{"filename":"model_a.glb"},{"filename":"model_a.usdz"}],"links":{"html":"https://sandbox.zenodo.org/records/9004"}}',
        ),
    ]
    for record_id, source_file_id, title, status, metadata_json in zenodo_rows:
        cursor.execute(
            """
            INSERT INTO zenodo_records (
                record_id, source_file_id, record_title, record_status,
                record_metadata_json, zenodo_record_id, concept_rec_id, zenodo_doi,
                is_sandbox, created_timestamp, last_updated_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                source_file_id,
                title,
                status,
                metadata_json,
                str(9000 + record_id),
                str(8000 + record_id),
                f"10.5072/example.{record_id}",
                1,
                "2026-03-10T10:00:00Z",
                "2026-03-10T10:05:00Z",
            ),
        )

    for record_id, file_id in [(1, 101), (2, 102), (3, 103), (4, 101)]:
        cursor.execute(
            """
            INSERT INTO record_files_map (
                record_id, file_id, file_purpose, upload_status, upload_timestamp, file_path
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                file_id,
                "main",
                "uploaded",
                "2026-03-10T10:05:00Z",
                source_paths[f"model_{chr(96 + (file_id - 100))}.glb"],
            ),
        )

    conn.commit()
    conn.close()
    return {
        "source_paths": source_paths,
        "rendered_paths": rendered_paths,
    }


class TestSubmissionRecordAccounting(unittest.TestCase):
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
        self.app.register_blueprint(submission_bp, url_prefix="/api/v1/submissions")

        with self.app.app_context():
            db.create_all()
            user = User(email="records@example.com", role=UserRole.USER, is_verified=True)
            user.set_password("password123")
            db.session.add(user)
            db.session.commit()
            self.user_id = user.id
            self.token = create_access_token(identity=str(self.user_id))

            hdpc_path = os.path.join(self.temp_dir.name, "session.hdpc")
            self.fixture_paths = _build_hdpc_fixture(hdpc_path, self.temp_dir.name)

            session_row = DBSession(
                user_id=self.user_id,
                session_dir=self.temp_dir.name,
                hdpc_path=hdpc_path,
                status="completed",
            )
            db.session.add(session_row)
            db.session.commit()
            self.session_id = session_row.id

            file_rows = [
                File(session_id=self.session_id, filename="model_a.glb", path=self.fixture_paths["source_paths"]["model_a.glb"], size=100, status="ready"),
                File(session_id=self.session_id, filename="model_b.glb", path=self.fixture_paths["source_paths"]["model_b.glb"], size=100, status="ready"),
                File(session_id=self.session_id, filename="model_c.glb", path=self.fixture_paths["source_paths"]["model_c.glb"], size=100, status="ready"),
            ]
            db.session.add_all(file_rows)
            db.session.flush()

            db.session.add(
                UserMetadata(
                    session_id=self.session_id,
                    field_name=WORKFLOW_STATE_FIELD,
                    field_value=json.dumps(
                        {
                            "phase": "processing",
                            "current_step": 7,
                            "is_batch_mode": True,
                            "selected_file_keys": [str(file_rows[0].id)],
                        }
                    ),
                )
            )

            submission = Submission(
                session_id=self.session_id,
                pipeline_id="render",
                status="completed",
                result=json.dumps(
                    {
                        "success": True,
                        "details": [
                            {
                                "record_id": 4,
                                "file_path": self.fixture_paths["source_paths"]["model_a.glb"],
                                "render": {"status": "completed", "success": True},
                            }
                        ],
                    }
                ),
            )
            db.session.add(submission)
            db.session.commit()
            self.submission_id = submission.id

        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        self.temp_dir.cleanup()

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def test_session_records_deduplicate_processed_and_prepared_entries(self):
        response = self.client.get(f"/api/v1/sessions/{self.session_id}/records", headers=self._headers())
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]
        self.assertEqual(payload["summary"]["total_records"], 3)
        self.assertEqual(payload["summary"]["processed_records"], 1)
        self.assertEqual(payload["summary"]["available_not_selected_records"], 2)
        self.assertEqual(payload["summary"]["hidden_duplicate_records"], 1)
        self.assertEqual(payload["summary"]["hidden_legacy_placeholder_records"], 1)

        processed = [record for record in payload["records"] if record["processed_in_latest_submission"]]
        available = [record for record in payload["records"] if record["available_not_selected"]]
        self.assertEqual(len(processed), 1)
        self.assertEqual(len(available), 2)
        self.assertEqual(processed[0]["source_file_name"], "model_a.glb")

    def test_session_records_keep_published_and_draft_versions_visible(self):
        with sqlite3.connect(os.path.join(self.temp_dir.name, "session.hdpc")) as conn:
            conn.execute(
                """
                INSERT INTO zenodo_records (
                    record_id, source_file_id, record_title, record_status,
                    record_metadata_json, zenodo_record_id, concept_rec_id, zenodo_doi,
                    is_sandbox, created_timestamp, last_updated_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    5,
                    101,
                    "Draft A v2",
                    "draft",
                    '{"metadata":{"title":"Draft A v2","version":"0.0.2"},"links":{"html":"https://sandbox.zenodo.org/deposit/9005","self":"https://sandbox.zenodo.org/api/deposit/depositions/9005"}}',
                    "9005",
                    "8004",
                    None,
                    1,
                    "2026-03-10T10:06:00Z",
                    "2026-03-10T10:06:00Z",
                ),
            )
            conn.execute(
                """
                INSERT INTO record_files_map (
                    record_id, file_id, file_purpose, upload_status, upload_timestamp, file_path
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    5,
                    101,
                    "main",
                    "pending",
                    None,
                    self.fixture_paths["source_paths"]["model_a.glb"],
                ),
            )
            conn.commit()

        response = self.client.get(f"/api/v1/sessions/{self.session_id}/records", headers=self._headers())
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]

        self.assertEqual(payload["summary"]["total_records"], 4)
        self.assertEqual(payload["summary"]["published_records"], 1)
        self.assertEqual(payload["summary"]["draft_records"], 1)
        self.assertEqual(payload["summary"]["hidden_duplicate_records"], 1)
        self.assertEqual(payload["summary"]["hidden_legacy_placeholder_records"], 1)

        model_a_versions = [record for record in payload["records"] if record["source_file_name"] == "model_a.glb"]
        self.assertEqual(len(model_a_versions), 2)
        self.assertEqual({record["record_status"] for record in model_a_versions}, {"published", "draft"})

    def test_session_records_hide_noncanonical_manual_rows(self):
        with sqlite3.connect(os.path.join(self.temp_dir.name, "session.hdpc")) as conn:
            conn.execute("ALTER TABLE zenodo_records ADD COLUMN record_origin TEXT")
            conn.execute("UPDATE zenodo_records SET record_origin = 'submit_pipeline'")
            conn.execute(
                """
                INSERT INTO zenodo_records (
                    record_id, source_file_id, record_title, record_status,
                    record_metadata_json, zenodo_record_id, concept_rec_id, zenodo_doi,
                    is_sandbox, created_timestamp, last_updated_timestamp, record_origin
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    6,
                    102,
                    "Manual Draft",
                    "draft",
                    '{"metadata":{"title":"Manual Draft"},"links":{"html":"https://sandbox.zenodo.org/records/9006"}}',
                    "9006",
                    "8006",
                    None,
                    1,
                    "2026-03-10T10:07:00Z",
                    "2026-03-10T10:07:00Z",
                    "manual_api",
                ),
            )
            conn.commit()

        response = self.client.get(f"/api/v1/sessions/{self.session_id}/records", headers=self._headers())
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]

        self.assertEqual(payload["summary"]["total_records"], 3)
        self.assertNotIn(6, [record["local_record_id"] for record in payload["records"]])

    def test_submission_detail_reports_processed_and_available_files_separately(self):
        response = self.client.get(f"/api/v1/submissions/{self.submission_id}", headers=self._headers())
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]
        self.assertEqual(len(payload["files"]), 1)
        self.assertEqual(payload["files"][0]["filename"], "model_a.glb")
        self.assertEqual(len(payload["available_files"]), 2)
        self.assertEqual(payload["file_summary"]["processed_file_count"], 1)
        self.assertEqual(payload["file_summary"]["available_not_processed_count"], 2)

    def test_session_records_flag_missing_uploaded_thumbnails_for_3d_records(self):
        response = self.client.get(f"/api/v1/sessions/{self.session_id}/records", headers=self._headers())
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]
        self.assertEqual(payload["summary"]["records_missing_uploaded_thumbnails"], 1)
        self.assertEqual(payload["summary"]["repairable_thumbnail_records"], 1)

        processed_record = next(record for record in payload["records"] if record["local_record_id"] == 4)
        thumbnail_health = processed_record["thumbnail_health"]
        self.assertTrue(thumbnail_health["is_3d_record"])
        self.assertTrue(thumbnail_health["missing_uploaded_thumbnails"])
        self.assertEqual(thumbnail_health["local_rendered_thumbnail_count"], 2)
        self.assertEqual(thumbnail_health["uploaded_thumbnail_count"], 0)

    def test_session_record_detail_includes_zenodo_model_preview_payload(self):
        response = self.client.get(f"/api/v1/sessions/{self.session_id}/records/4", headers=self._headers())
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]

        preview = payload["record"]["model_preview"]
        self.assertTrue(preview["is_3d_record"])
        self.assertTrue(preview["can_inline_preview"])
        self.assertEqual(preview["filename"], "model_a.glb")
        self.assertEqual(preview["format"], "glb")
        self.assertEqual(preview["source"], "zenodo_direct_file")
        self.assertEqual(preview["reason"], None)
        self.assertEqual(
            preview["url"],
            "https://sandbox.zenodo.org/api/records/9004/files/model_a.glb/content",
        )

    def test_create_version_uses_complete_local_file_set(self):
        class StubProjectService:
            def __init__(self):
                self.calls = []

            def create_new_version_with_files(self, **kwargs):
                self.calls.append(kwargs)
                return {"success": True, "new_local_record_id": 44}

        stub_service = StubProjectService()
        self.app.project_service = stub_service

        response = self.client.post(
            f"/api/v1/sessions/{self.session_id}/records/4/create-version",
            headers=self._headers(),
            json={"publish": False},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]
        self.assertEqual(payload["new_version"]["new_local_record_id"], 44)
        self.assertEqual(len(stub_service.calls), 1)

        call = stub_service.calls[0]
        self.assertEqual(call["concept_rec_id"], "8004")
        self.assertEqual(call["source_file_path"], self.fixture_paths["source_paths"]["model_a.glb"])
        self.assertEqual(call["hdpc_path"], os.path.join(self.temp_dir.name, "session.hdpc"))
        self.assertIn(self.fixture_paths["source_paths"]["model_a.glb"], call["absolute_file_paths"])
        self.assertIn(self.fixture_paths["rendered_paths"][0], call["absolute_file_paths"])
        self.assertIn(self.fixture_paths["rendered_paths"][1], call["absolute_file_paths"])


if __name__ == "__main__":
    unittest.main()
