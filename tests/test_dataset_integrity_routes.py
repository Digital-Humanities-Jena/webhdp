import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import (
    Institution,
    InstitutionMembership,
    InstitutionRole,
    Session as DBSession,
    User,
    UserMetadata,
    UserRole,
)
from routes.dataset_routes import dataset_bp
from routes.session_routes import session_bp


def _create_hdpc(path: str, records: list[dict]) -> None:
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
            last_updated_timestamp TEXT,
            version INTEGER,
            last_api_error TEXT
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
            added_timestamp TEXT,
            sha256_hash TEXT
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

    for record in records:
        source_path = record["source_path"]
        os.makedirs(os.path.dirname(source_path), exist_ok=True)
        with open(source_path, "w", encoding="utf-8") as handle:
          handle.write("glb")

        cursor.execute(
            """
            INSERT INTO source_files (
                file_id, filename, absolute_path, relative_path, file_type, status, size_bytes,
                mime_type, pipeline_source, step_source, added_timestamp, sha256_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["file_id"],
                os.path.basename(source_path),
                source_path,
                os.path.basename(source_path),
                "primary_source",
                "Valid",
                100,
                "model/gltf-binary",
                "ingestion",
                "scan",
                "2026-03-10T10:00:00Z",
                record.get("sha256_hash", f"hash-{record['file_id']}"),
            ),
        )

        metadata = record.get("metadata") or {
            "metadata": {"title": record["title"]},
            "files": [{"filename": os.path.basename(source_path)}],
            "links": {"html": f"https://zenodo.org/records/{record.get('zenodo_record_id') or (9000 + record['record_id'])}"},
        }
        cursor.execute(
            """
            INSERT INTO zenodo_records (
                record_id, source_file_id, record_title, record_status, record_metadata_json,
                zenodo_record_id, concept_rec_id, zenodo_doi, is_sandbox, created_timestamp,
                last_updated_timestamp, version, last_api_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["record_id"],
                record["file_id"],
                record["title"],
                record["status"],
                json.dumps(metadata),
                str(record.get("zenodo_record_id") or "") or None,
                record.get("concept_rec_id"),
                record.get("zenodo_doi"),
                1 if record.get("is_sandbox") else 0,
                "2026-03-10T10:00:00Z",
                "2026-03-10T10:05:00Z",
                1,
                None,
            ),
        )
        cursor.execute(
            """
            INSERT INTO record_files_map (
                record_id, file_id, file_purpose, upload_status, upload_timestamp, file_path
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                record["record_id"],
                record["file_id"],
                "main",
                record.get("upload_status", "uploaded"),
                "2026-03-10T10:05:00Z",
                source_path,
            ),
        )

    conn.commit()
    conn.close()


class DummyProjectService:
    def _translate_path(self, path, to_container=False):
        return path

    def create_new_version_with_files(self, **kwargs):
        return {"success": True, "new_local_record_id": 999}


class TestDatasetIntegrityRoutes(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="dataset-integrity-test-")
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        self.app.config["SECRET_KEY"] = "test-secret"
        self.app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
        self.app.project_service = DummyProjectService()

        db.init_app(self.app)
        JWTManager(self.app)
        self.app.register_blueprint(dataset_bp, url_prefix="/api/v1/datasets")
        self.app.register_blueprint(session_bp, url_prefix="/api/v1/sessions")

        with self.app.app_context():
            db.create_all()
            admin = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
            admin.set_password("password123")
            db.session.add(admin)
            regular_user = User(email="user@example.com", role=UserRole.USER, is_verified=True)
            regular_user.set_password("password123")
            db.session.add(regular_user)
            db.session.commit()
            self.user_id = admin.id
            self.token = create_access_token(identity=str(self.user_id))
            self.regular_user_id = regular_user.id
            self.regular_token = create_access_token(identity=str(self.regular_user_id))

            institution = Institution(
                name="Shared Museum",
                slug="shared-museum",
                created_by_user_id=admin.id,
            )
            db.session.add(institution)
            db.session.flush()
            db.session.add_all(
                [
                    InstitutionMembership(
                        institution_id=institution.id,
                        user_id=admin.id,
                        role=InstitutionRole.OWNER,
                    ),
                    InstitutionMembership(
                        institution_id=institution.id,
                        user_id=regular_user.id,
                        role=InstitutionRole.READER,
                    ),
                ]
            )
            db.session.commit()
            self.institution_id = institution.id

            dataset_root = os.path.join(self.temp_dir, "local_input", "Turin_Dataset")
            os.makedirs(dataset_root, exist_ok=True)

            hdpc_path_one = os.path.join(self.temp_dir, "session1.hdpc")
            _create_hdpc(
                hdpc_path_one,
                [
                    {
                        "record_id": 1,
                        "file_id": 101,
                        "title": "Model A",
                        "status": "published",
                        "source_path": os.path.join(dataset_root, "model_a.glb"),
                        "concept_rec_id": "1001",
                        "zenodo_record_id": "190001",
                        "zenodo_doi": "10.5281/zenodo.190001",
                    },
                    {
                        "record_id": 2,
                        "file_id": 102,
                        "title": "Model B",
                        "status": "published",
                        "source_path": os.path.join(dataset_root, "model_b.glb"),
                        "concept_rec_id": "1002",
                        "zenodo_record_id": "190002",
                        "zenodo_doi": "10.5281/zenodo.190002",
                    },
                ],
            )
            session_one = DBSession(user_id=self.user_id, session_dir=self.temp_dir, hdpc_path=hdpc_path_one, status="completed")
            db.session.add(session_one)
            db.session.commit()
            self.session_one_id = session_one.id

            hdpc_path_two = os.path.join(self.temp_dir, "session2.hdpc")
            _create_hdpc(
                hdpc_path_two,
                [
                    {
                        "record_id": 10,
                        "file_id": 201,
                        "title": "Duplicate Model A",
                        "status": "published",
                        "source_path": os.path.join(dataset_root, "model_a.glb"),
                        "concept_rec_id": "2001",
                        "zenodo_record_id": "190010",
                        "zenodo_doi": "10.5281/zenodo.190010",
                    },
                    {
                        "record_id": 11,
                        "file_id": 202,
                        "title": "Prepared Model C",
                        "status": "prepared",
                        "source_path": os.path.join(dataset_root, "model_c.glb"),
                        "concept_rec_id": "",
                        "zenodo_record_id": None,
                        "zenodo_doi": "",
                        "upload_status": "pending",
                        "metadata": {"metadata": {"title": "Prepared Model C"}},
                    },
                    {
                        "record_id": 12,
                        "file_id": 203,
                        "title": "Sandbox Model S",
                        "status": "published",
                        "source_path": os.path.join(dataset_root, "model_s.glb"),
                        "concept_rec_id": "3001",
                        "zenodo_record_id": "290012",
                        "zenodo_doi": "10.5072/zenodo.290012",
                        "is_sandbox": True,
                    },
                ],
            )
            session_two = DBSession(user_id=self.user_id, session_dir=self.temp_dir, hdpc_path=hdpc_path_two, status="completed")
            db.session.add(session_two)
            db.session.commit()
            self.session_two_id = session_two.id

            shared_dataset_root = os.path.join(self.temp_dir, "shared_input", "Shared_Dataset")
            os.makedirs(shared_dataset_root, exist_ok=True)
            hdpc_path_shared = os.path.join(self.temp_dir, "shared_session.hdpc")
            _create_hdpc(
                hdpc_path_shared,
                [
                    {
                        "record_id": 30,
                        "file_id": 301,
                        "title": "Shared Model",
                        "status": "published",
                        "source_path": os.path.join(shared_dataset_root, "shared_model.glb"),
                        "concept_rec_id": "4001",
                        "zenodo_record_id": "390030",
                        "zenodo_doi": "10.5281/zenodo.390030",
                    }
                ],
            )
            shared_session = DBSession(
                user_id=self.user_id,
                institution_id=self.institution_id,
                session_dir=self.temp_dir,
                hdpc_path=hdpc_path_shared,
                status="completed",
                sharing_scope="institution",
            )
            db.session.add(shared_session)
            db.session.commit()
            self.shared_session_id = shared_session.id

            prepared_dataset_root = os.path.join(self.temp_dir, "prepared", "Turin_Dataset")
            os.makedirs(prepared_dataset_root, exist_ok=True)
            self.prepared_blocker_path = os.path.join(prepared_dataset_root, "model_a.glb")
            self.prepared_clean_path = os.path.join(prepared_dataset_root, "model_d.glb")
            for target in [self.prepared_blocker_path, self.prepared_clean_path]:
                with open(target, "w", encoding="utf-8") as handle:
                    handle.write("glb")

            hdpc_path_three = os.path.join(self.temp_dir, "session3.hdpc")
            sqlite3.connect(hdpc_path_three).close()
            session_three = DBSession(user_id=self.user_id, session_dir=self.temp_dir, hdpc_path=hdpc_path_three, status="pending")
            db.session.add(session_three)
            db.session.commit()
            self.session_three_id = session_three.id
            db.session.add(
                UserMetadata(
                    session_id=self.session_three_id,
                    field_name="msf_profile",
                    field_value=json.dumps(
                        {
                            "file_path": os.path.join(self.temp_dir, "prepared", "Turin_Dataset", "turin_metadata.xlsx"),
                            "source_file_path": os.path.join(self.temp_dir, "prepared", "Turin_Dataset", "turin_metadata.xlsx"),
                            "directory_root": prepared_dataset_root,
                            "directory_recursive": True,
                        }
                    ),
                )
            )
            db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def _regular_headers(self):
        return {"Authorization": f"Bearer {self.regular_token}"}

    def _add_dataset_session(self, name, records, *, dataset_key=None, shared=False):
        with self.app.app_context():
            session_dir = os.path.join(self.temp_dir, name)
            os.makedirs(session_dir, exist_ok=True)
            hdpc_path = os.path.join(session_dir, "session.hdpc")
            _create_hdpc(hdpc_path, records)
            session_row = DBSession(
                user_id=self.user_id,
                session_dir=session_dir,
                hdpc_path=hdpc_path,
                status="pending" if not records else "completed",
                default_zenodo_environment="sandbox",
                institution_id=self.institution_id if shared else None,
                sharing_scope="institution" if shared else "private",
            )
            db.session.add(session_row)
            db.session.flush()
            if dataset_key:
                root = os.path.join(session_dir, dataset_key)
                os.makedirs(root, exist_ok=True)
                db.session.add(UserMetadata(
                    session_id=session_row.id,
                    field_name="msf_profile",
                    field_value=json.dumps({"source_file_path": os.path.join(root, "metadata.xlsx"), "directory_root": root}),
                ))
            db.session.commit()
            return session_row.id

    def test_direct_sandbox_dataset_has_empty_production_scope_and_usable_sandbox_scope(self):
        session_id = self._add_dataset_session("direct_upload", [{
            "record_id": 1, "file_id": 1, "title": "Terrain", "status": "draft", "is_sandbox": True,
            "source_path": os.path.join(self.temp_dir, "direct_upload", "uploads", "terrain.glb"),
            "zenodo_record_id": "619251",
        }])
        dataset_key = f"session_{session_id}_dataset"
        base = f"/api/v1/datasets/{dataset_key}"
        response = self.client.get(f"{base}/summary", headers=self._headers())
        self.assertEqual(response.status_code, 200)
        summary = response.get_json()["data"]
        self.assertEqual(summary["environment"], "production")
        self.assertEqual(summary["available_environments"], ["sandbox"])
        self.assertEqual(summary["empty_reason"], "no_records_in_environment")
        self.assertEqual(summary["record_count"], 0)
        self.assertEqual(summary["sessions"], [])
        response = self.client.get(f"{base}/summary?environment=sandbox", headers=self._headers())
        self.assertEqual(response.status_code, 200)
        summary = response.get_json()["data"]
        self.assertEqual(summary["record_count"], 1)
        self.assertEqual(summary["sessions"][0]["session_id"], session_id)
        self.assertIsNone(summary["empty_reason"])
        duplicates = self.client.get(f"{base}/duplicates", headers=self._headers())
        self.assertEqual(duplicates.status_code, 200)
        self.assertEqual(duplicates.get_json()["data"]["groups"], [])
        self.assertEqual(duplicates.get_json()["data"]["available_environments"], ["sandbox"])
        empty_export = self.client.post(f"{base}/export", headers=self._headers(), json={"format": "bundle"})
        self.assertEqual(empty_export.status_code, 200)
        self.assertEqual(empty_export.get_json()["data"]["secondary_record_count"], 0)
        draft_export = self.client.post(f"{base}/export", headers=self._headers(), json={"format": "bundle", "environment": "sandbox"})
        self.assertEqual(draft_export.status_code, 200)
        self.assertEqual(draft_export.get_json()["data"]["secondary_record_count"], 1)

    def test_prepared_batch_and_empty_direct_sessions_have_workspaces_and_catalog_entries(self):
        batch_id = self._add_dataset_session("prepared_batch", [], dataset_key="Prepared_Dataset")
        direct_id = self._add_dataset_session("empty_upload", [])
        catalog_response = self.client.get("/api/v1/datasets?environment=sandbox", headers=self._headers())
        self.assertEqual(catalog_response.status_code, 200)
        catalog = {item["dataset_key"]: item for item in catalog_response.get_json()["data"]["datasets"]}
        for dataset_key, session_id in [("Prepared_Dataset", batch_id), (f"session_{direct_id}_dataset", direct_id)]:
            self.assertIn(dataset_key, catalog)
            self.assertEqual(catalog[dataset_key]["session_count"], 1)
            response = self.client.get(f"/api/v1/datasets/{dataset_key}/summary?environment=sandbox", headers=self._headers())
            self.assertEqual(response.status_code, 200)
            summary = response.get_json()["data"]
            self.assertEqual(summary["record_count"], 0)
            self.assertEqual(summary["empty_reason"], "no_records")
            self.assertEqual(summary["available_environments"], ["sandbox"])
            self.assertEqual(summary["sessions"][0]["session_id"], session_id)
            duplicates = self.client.get(f"/api/v1/datasets/{dataset_key}/duplicates?environment=sandbox", headers=self._headers())
            self.assertEqual(duplicates.status_code, 200)
            self.assertEqual(duplicates.get_json()["data"]["group_count"], 0)
            exported = self.client.post(f"/api/v1/datasets/{dataset_key}/export", headers=self._headers(), json={"format": "bundle", "environment": "sandbox"})
            self.assertEqual(exported.status_code, 200)
            self.assertEqual(exported.get_json()["data"]["primary_record_count"], 0)
            self.assertEqual(exported.get_json()["data"]["secondary_record_count"], 0)
        production_catalog = self.client.get("/api/v1/datasets?environment=production", headers=self._headers()).get_json()["data"]["datasets"]
        self.assertNotIn("Prepared_Dataset", {item["dataset_key"] for item in production_catalog})

    def test_empty_workspaces_preserve_private_session_access_and_unknown_key_404(self):
        private_id = self._add_dataset_session("private_empty_upload", [])
        self._add_dataset_session("shared_empty_batch", [], dataset_key="Shared_Empty_Dataset", shared=True)
        self._add_dataset_session("private_production", [{
            "record_id": 1, "file_id": 1, "title": "Private Production", "status": "draft",
            "source_path": os.path.join(self.temp_dir, "private_production", "Shared_Empty_Dataset", "private.glb"),
        }])
        for dataset_key in [f"session_{private_id}_dataset", "Missing_Dataset"]:
            for endpoint in ["summary", "duplicates"]:
                response = self.client.get(f"/api/v1/datasets/{dataset_key}/{endpoint}?environment=all", headers=self._regular_headers())
                self.assertEqual(response.status_code, 404)
            response = self.client.post(f"/api/v1/datasets/{dataset_key}/export", headers=self._regular_headers(), json={"environment": "all"})
            self.assertEqual(response.status_code, 404)
        response = self.client.get("/api/v1/datasets/Shared_Empty_Dataset/summary?environment=sandbox", headers=self._regular_headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["available_environments"], ["sandbox"])
        admin_response = self.client.get("/api/v1/datasets/Shared_Empty_Dataset/summary?environment=all", headers=self._headers())
        self.assertEqual(admin_response.get_json()["data"]["available_environments"], ["production", "sandbox"])
        missing_response = self.client.get("/api/v1/datasets/Missing_Dataset/summary?environment=all", headers=self._headers())
        self.assertEqual(missing_response.status_code, 404)
        catalog = self.client.get("/api/v1/datasets?environment=all", headers=self._regular_headers()).get_json()["data"]["datasets"]
        self.assertNotIn(f"session_{private_id}_dataset", {item["dataset_key"] for item in catalog})

    def test_all_environment_conflicts_keep_sandbox_and_production_separate(self):
        source_path = os.path.join(self.temp_dir, "mixed", "Mixed_Dataset", "model.glb")
        self._add_dataset_session("mixed_environment", [
            {"record_id": 1, "file_id": 1, "title": "Production", "status": "published", "source_path": source_path, "zenodo_record_id": "11"},
            {"record_id": 2, "file_id": 2, "title": "Sandbox", "status": "published", "source_path": source_path, "zenodo_record_id": "22", "is_sandbox": True},
        ])
        summary = self.client.get("/api/v1/datasets/Mixed_Dataset/summary?environment=all", headers=self._headers()).get_json()["data"]
        self.assertEqual(summary["available_environments"], ["production", "sandbox"])
        self.assertEqual(summary["duplicate_published_source_path_count"], 0)
        response = self.client.get("/api/v1/datasets/Mixed_Dataset/duplicates?environment=all", headers=self._headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["groups"], [])

    def test_dataset_routes_summarize_and_export_records(self):
        list_response = self.client.get("/api/v1/datasets", headers=self._headers())
        self.assertEqual(list_response.status_code, 200)
        datasets = list_response.get_json()["data"]["datasets"]
        dataset_keys = {item["dataset_key"] for item in datasets}
        self.assertIn("Turin_Dataset", dataset_keys)

        summary_response = self.client.get("/api/v1/datasets/Turin_Dataset/summary", headers=self._headers())
        self.assertEqual(summary_response.status_code, 200)
        summary = summary_response.get_json()["data"]
        self.assertEqual(summary["authoritative_session_id"], self.session_one_id)
        self.assertEqual(summary["source_path_count"], 3)
        self.assertEqual(summary["duplicate_published_source_path_count"], 1)
        self.assertEqual(summary["sessions"][0]["published_source_path_count"], 2)
        self.assertIn("production", summary["environment_breakdown"])

        duplicates_response = self.client.get("/api/v1/datasets/Turin_Dataset/duplicates", headers=self._headers())
        self.assertEqual(duplicates_response.status_code, 200)
        groups = duplicates_response.get_json()["data"]["groups"]
        self.assertEqual(len(groups), 1)
        self.assertIn("model_a.glb", groups[0]["normalized_source_file_path"])
        self.assertEqual(groups[0]["conflict_class"], "published_duplicate")

        filtered_duplicates_response = self.client.get(
            "/api/v1/datasets/Turin_Dataset/duplicates?path=Turin_Dataset/model_a.glb",
            headers=self._headers(),
        )
        self.assertEqual(filtered_duplicates_response.status_code, 200)
        filtered_duplicates_payload = filtered_duplicates_response.get_json()["data"]
        self.assertEqual(filtered_duplicates_payload["group_count"], 1)
        self.assertIn("model_a.glb", filtered_duplicates_payload["path_filter"])

        export_response = self.client.post(
            "/api/v1/datasets/Turin_Dataset/export",
            headers=self._headers(),
            json={"format": "bundle"},
        )
        self.assertEqual(export_response.status_code, 200)
        export_payload = export_response.get_json()["data"]
        self.assertEqual(export_payload["authoritative_session_id"], self.session_one_id)
        self.assertEqual(export_payload["primary_record_count"], 2)
        self.assertEqual(export_payload["secondary_record_count"], 2)
        self.assertIn("model_a.glb", export_payload["primary_csv"])
        self.assertEqual(
            export_payload["csv_columns"],
            [
                "original_filename",
                "zenodo_doi",
                "glb_direct_link",
                "record_link",
                "zenodo_record_id",
                "record_status",
                "session_id",
                "local_record_id",
            ],
        )

        production_summary_response = self.client.get(
            "/api/v1/datasets/Turin_Dataset/summary?environment=production",
            headers=self._headers(),
        )
        self.assertEqual(production_summary_response.status_code, 200)
        production_summary = production_summary_response.get_json()["data"]
        self.assertEqual(production_summary["environment"], "production")
        self.assertEqual(production_summary["published_source_path_count"], 2)

        sandbox_summary_response = self.client.get(
            "/api/v1/datasets/Turin_Dataset/summary?environment=sandbox",
            headers=self._headers(),
        )
        self.assertEqual(sandbox_summary_response.status_code, 200)
        sandbox_summary = sandbox_summary_response.get_json()["data"]
        self.assertEqual(sandbox_summary["environment"], "sandbox")
        self.assertEqual(sandbox_summary["published_source_path_count"], 1)

    def test_duplicate_check_from_prepared_session_detects_blockers(self):
        response = self.client.post(
            "/api/v1/datasets/duplicate-check",
            headers=self._headers(),
            json={"session_id": self.session_three_id, "is_sandbox": False},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]
        self.assertEqual(payload["dataset_key"], "Turin_Dataset")
        self.assertEqual(payload["summary"]["blocker"], 1)
        self.assertEqual(payload["summary"]["clean"], 1)
        blocker = next(item for item in payload["results"] if item["candidate_filename"] == "model_a.glb")
        clean = next(item for item in payload["results"] if item["candidate_filename"] == "model_d.glb")
        self.assertEqual(blocker["classification"], "blocker")
        self.assertEqual(clean["classification"], "clean")

    def test_duplicate_check_allows_same_lineage_versioning(self):
        response = self.client.post(
            "/api/v1/datasets/duplicate-check",
            headers=self._headers(),
            json={
                "dataset_key": "Turin_Dataset",
                "is_sandbox": False,
                "candidate_files": [
                    {
                        "source_file_path": os.path.join(self.temp_dir, "repair", "Turin_Dataset", "model_b.glb"),
                        "source_file_name": "model_b.glb",
                        "concept_rec_id": "1002",
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]
        self.assertEqual(payload["summary"]["allowed_versioning"], 1)
        result = payload["results"][0]
        self.assertEqual(result["classification"], "allowed_versioning")
        self.assertIn("versioning path", result["recommended_action"])

    def test_duplicate_check_redacts_foreign_matches_for_non_privileged_user(self):
        response = self.client.post(
            "/api/v1/datasets/duplicate-check",
            headers=self._regular_headers(),
            json={
                "dataset_key": "Turin_Dataset",
                "environment": "production",
                "candidate_files": [
                    {
                        "source_file_path": os.path.join(self.temp_dir, "foreign", "Turin_Dataset", "model_a.glb"),
                        "source_file_name": "model_a.glb",
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]
        self.assertEqual(payload["summary"]["blocker"], 1)
        result = payload["results"][0]
        self.assertEqual(result["classification"], "blocker")
        self.assertEqual(result["visible_matched_record_count"], 0)
        self.assertGreaterEqual(result["hidden_matched_record_count"], 1)
        self.assertEqual(result["matched_records"], [])
        self.assertIn("outside your visible scope", result["recommended_action"])

    def test_regular_user_can_see_shared_institution_dataset(self):
        list_response = self.client.get("/api/v1/datasets", headers=self._regular_headers())
        self.assertEqual(list_response.status_code, 200)
        datasets = list_response.get_json()["data"]["datasets"]
        dataset_keys = {item["dataset_key"] for item in datasets}
        self.assertIn("Shared_Dataset", dataset_keys)

        summary_response = self.client.get(
            "/api/v1/datasets/Shared_Dataset/summary",
            headers=self._regular_headers(),
        )
        self.assertEqual(summary_response.status_code, 200)
        summary = summary_response.get_json()["data"]
        self.assertEqual(summary["authoritative_session_id"], self.shared_session_id)
        self.assertEqual(summary["published_source_path_count"], 1)

    def test_conflict_review_requires_privileged_user_and_returns_queue(self):
        unauthorized = self.client.get(
            "/api/v1/datasets/conflict-review",
            headers=self._regular_headers(),
        )
        self.assertEqual(unauthorized.status_code, 403)

        response = self.client.get(
            "/api/v1/datasets/conflict-review?environment=production",
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["data"]
        self.assertEqual(payload["dataset_count"], 1)
        self.assertEqual(payload["duplicate_group_count"], 1)
        dataset_item = payload["datasets"][0]
        self.assertEqual(dataset_item["dataset_key"], "Turin_Dataset")
        self.assertEqual(dataset_item["duplicate_group_count"], 1)
        self.assertEqual(dataset_item["affected_user_count"], 1)
        self.assertEqual(dataset_item["affected_users"][0]["email"], "admin@example.com")
        self.assertEqual(dataset_item["groups_preview"][0]["affected_user_count"], 1)
        self.assertEqual(dataset_item["groups_preview"][0]["records"][0]["session_owner_email"], "admin@example.com")

    def test_session_records_include_dataset_key_and_version_route_blocks_duplicate_lineage(self):
        records_response = self.client.get(
            f"/api/v1/sessions/{self.session_one_id}/records",
            headers=self._headers(),
        )
        self.assertEqual(records_response.status_code, 200)
        payload = records_response.get_json()["data"]
        self.assertEqual(payload["provenance"]["dataset_key"], "Turin_Dataset")
        self.assertEqual(payload["records"][0]["dataset_key"], "Turin_Dataset")

        version_response = self.client.post(
            f"/api/v1/sessions/{self.session_one_id}/records/1/create-version",
            headers=self._headers(),
            json={"publish": False},
        )
        self.assertEqual(version_response.status_code, 400)
        version_payload = version_response.get_json()
        self.assertEqual(version_payload["error"]["code"], "VALIDATION_ERROR")
        self.assertIn("Duplicate dataset source detected", version_payload["error"]["message"])


if __name__ == "__main__":
    unittest.main()
