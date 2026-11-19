import os
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

from exceptions import FileProcessingError
from services.submission_pipeline_service import (
    _collect_generated_output_files,
    _build_bundle_file_paths_by_relative,
    _derive_batch_fallback_creators,
    _derive_batch_fallback_title,
    _extract_standard_mapping,
    _has_excluded_segment,
    _merge_non_empty_metadata,
    _resolve_metadata_linked_asset,
    _split_batch_shared_zenodo_metadata,
    execute_submission_pipeline,
)
from database.database import db
from database.models import Session as DBSession, User, UserMetadata, UserRole
from services.hdpc_local_service import get_hdpc_file_id_map, inspect_hdpc_project
from services.hdpc_local_service import add_local_source_files, create_local_record_with_metadata


def test_merge_non_empty_metadata_preserves_existing_values_on_empty_overrides():
    base = {
        "title": "Original title",
        "description": "Original description",
        "creators": [{"name": "Original Creator"}],
    }
    overrides = {
        "title": "Updated title",
        "description": "",
        "creators": [],
        "keywords": ["lod", "mapping"],
    }

    merged = _merge_non_empty_metadata(base, overrides)

    assert merged["title"] == "Updated title"
    assert merged["description"] == "Original description"
    assert merged["creators"] == [{"name": "Original Creator"}]
    assert merged["keywords"] == ["lod", "mapping"]


def test_split_batch_shared_zenodo_metadata_excludes_item_specific_defaults():
    shared = {
        "title": "Collection title",
        "description": "Collection description",
        "creators": [{"name": "Museum"}],
        "license": "cc-by-4.0",
        "access_right": "open",
    }

    batch_shared, item_defaults = _split_batch_shared_zenodo_metadata(shared)

    assert batch_shared == {
        "license": "cc-by-4.0",
        "access_right": "open",
    }
    assert item_defaults == {
        "title": "Collection title",
        "description": "Collection description",
        "creators": [{"name": "Museum"}],
    }


def test_derive_batch_fallback_title_prefers_identifier_over_filename():
    metadata = {"_external_identifier": "Gr.149"}

    assert _derive_batch_fallback_title(metadata, "Gr_149_Naczynie_1.glb") == "Gr.149"


def test_derive_batch_fallback_creators_uses_affiliation_then_shared_defaults():
    assert _derive_batch_fallback_creators({"_affiliations_raw": "RCIN / IAE PAN"}) == [
        {"name": "RCIN / IAE PAN"}
    ]
    assert _derive_batch_fallback_creators(
        {"creators": [{"name": "Unknown"}]},
        {"creators": [{"name": "Polish Academy of Sciences"}]},
    ) == [{"name": "Polish Academy of Sciences"}]
    assert _derive_batch_fallback_creators(
        {},
        {"creators": [{"name": "Polish Academy of Sciences"}]},
    ) == [{"name": "Polish Academy of Sciences"}]


def test_has_excluded_segment_detects_internal_dirs():
    assert _has_excluded_segment("__MACOSX/model/test_model.glb")
    assert _has_excluded_segment("assets/__pycache__/preview.png")
    assert not _has_excluded_segment("assets/model/test_model.glb")


def test_resolve_metadata_linked_asset_prefers_glb_when_selected_obj():
    resolved_file_id, resolved_path, resolved_metadata = _resolve_metadata_linked_asset(
        selected_file_path="/shared/sessions/s1/uploads/model_one/test_model.obj",
        selected_file_id=5,
        batch_metadata_map={
            "test_model.glb": {"title": "MSF GLB Title"},
        },
        basename_to_relative_paths={
            "test_model.glb": ["model_one/test_model.glb"],
            "test_model.obj": ["model_one/test_model.obj"],
        },
        normalized_file_id_map={
            "model_one/test_model.glb": 16,
            "model_one/test_model.obj": 5,
        },
        relative_to_absolute_path={
            "model_one/test_model.glb": "/shared/sessions/s1/uploads/model_one/test_model.glb",
            "model_one/test_model.obj": "/shared/sessions/s1/uploads/model_one/test_model.obj",
        },
    )

    assert resolved_file_id == 16
    assert resolved_path.endswith("/model_one/test_model.glb")
    assert resolved_metadata == {"title": "MSF GLB Title"}


def test_build_bundle_file_paths_maps_children_to_full_bundle():
    tree = [
        {
            "relative_path": "model_one/test_model.glb",
            "absolute_path": "/shared/sessions/s1/uploads/model_one/test_model.glb",
            "children": [
                {
                    "relative_path": "model_one/test_model.obj",
                    "absolute_path": "/shared/sessions/s1/uploads/model_one/test_model.obj",
                    "children": [
                        {
                            "relative_path": "model_one/test_model.mtl",
                            "absolute_path": "/shared/sessions/s1/uploads/model_one/test_model.mtl",
                            "children": [
                                {
                                    "relative_path": "model_one/textures/albedo.jpg",
                                    "absolute_path": "/shared/sessions/s1/uploads/model_one/textures/albedo.jpg",
                                    "children": [],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ]

    bundle_map = _build_bundle_file_paths_by_relative(tree)
    expected_bundle = [
        "/shared/sessions/s1/uploads/model_one/test_model.glb",
        "/shared/sessions/s1/uploads/model_one/test_model.obj",
        "/shared/sessions/s1/uploads/model_one/test_model.mtl",
        "/shared/sessions/s1/uploads/model_one/textures/albedo.jpg",
    ]

    assert bundle_map["model_one/test_model.glb"] == expected_bundle
    assert bundle_map["model_one/test_model.obj"] == expected_bundle
    assert bundle_map["model_one/test_model.mtl"] == expected_bundle
    assert bundle_map["model_one/textures/albedo.jpg"] == expected_bundle


def test_build_bundle_file_paths_excludes_archived_members_and_keeps_archive():
    tree = [
        {
            "relative_path": "model_one/test_model.glb",
            "absolute_path": "/shared/sessions/s1/uploads/model_one/test_model.glb",
            "file_type": "primary_source",
            "children": [
                {
                    "relative_path": "model_one/test_model.obj",
                    "absolute_path": "/shared/sessions/s1/uploads/model_one/test_model.obj",
                    "file_type": "source",
                    "children": [
                        {
                            "relative_path": "archives/model_one_textures.zip",
                            "absolute_path": "/shared/sessions/s1/archives/model_one_textures.zip",
                            "file_type": "archive",
                            "children": [
                                {
                                    "relative_path": "model_one/textures/albedo.jpg",
                                    "absolute_path": "/shared/sessions/s1/uploads/model_one/textures/albedo.jpg",
                                    "file_type": "archived_file",
                                    "children": [],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ]

    bundle_map = _build_bundle_file_paths_by_relative(tree)
    mapped = bundle_map["model_one/test_model.glb"]

    assert "/shared/sessions/s1/archives/model_one_textures.zip" in mapped
    assert "/shared/sessions/s1/uploads/model_one/textures/albedo.jpg" not in mapped


def test_extract_standard_mapping_accepts_legacy_3d_model_alias():
    mapping = {
        "edm": {
            "3d_model": {
                "dc:title": {"source": "static", "value": "Legacy 3D title"}
            }
        }
    }

    extracted = _extract_standard_mapping(mapping, "edm", "3d")
    assert extracted == mapping["edm"]["3d_model"]


def test_extract_standard_mapping_accepts_audio_alias_for_sound():
    mapping = {
        "iiif": {
            "audio": {
                "label": {"source": "static", "value": "Audio record"}
            }
        }
    }

    extracted = _extract_standard_mapping(mapping, "iiif", "sound")
    assert extracted == mapping["iiif"]["audio"]


def test_collect_generated_output_files_reads_existing_render_outputs_from_disk():
    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = os.path.join(temp_dir, "model_one")
        os.makedirs(output_dir, exist_ok=True)

        expected = [
            os.path.join(output_dir, "edm.xml"),
            os.path.join(output_dir, "model_one_r000.png"),
            os.path.join(output_dir, "model_one_r090.png"),
        ]
        for path in expected:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("data")

        os.makedirs(os.path.join(output_dir, "nested"), exist_ok=True)
        with open(os.path.join(output_dir, "nested", "ignored.txt"), "w", encoding="utf-8") as handle:
            handle.write("nested")

        assert _collect_generated_output_files(output_dir) == sorted(expected)


def _create_submission_hdpc(path: str, root_dir: str) -> dict[str, str]:
    uploads_dir = os.path.join(root_dir, "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    source_path = os.path.join(uploads_dir, "model.glb")
    with open(source_path, "w", encoding="utf-8") as handle:
        handle.write("glb")

    conn = sqlite3.connect(path)
    cursor = conn.cursor()
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
        INSERT INTO source_files (
            file_id, filename, absolute_path, relative_path, file_type, status,
            size_bytes, mime_type, pipeline_source, step_source, added_timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            101,
            "model.glb",
            source_path,
            "model.glb",
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
    conn.close()
    return {"source_path": source_path}


class TestSubmissionPipelineNativeHdpcContext(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        self.app.config["SECRET_KEY"] = "test-secret"
        self.app.config["JWT_SECRET_KEY"] = "test-jwt"
        self.app.config["ENABLE_RENDERER"] = True
        self.app.config["ENABLE_USDZ_CONVERSION"] = True

        db.init_app(self.app)
        self.app.project_service = MagicMock()
        self.app.pipeline_service = MagicMock()
        self.app.native_pipeline_service = MagicMock()
        self.app.msf_service = MagicMock()

        with self.app.app_context():
            db.create_all()
            user = User(email="native@example.com", role=UserRole.USER, is_verified=True)
            user.set_password("password")
            db.session.add(user)
            db.session.commit()
            self.user_id = user.id

            hdpc_path = os.path.join(self.temp_dir.name, "session.hdpc")
            fixture = _create_submission_hdpc(hdpc_path, self.temp_dir.name)
            self.source_path = fixture["source_path"]

            session_row = DBSession(
                user_id=self.user_id,
                session_dir=self.temp_dir.name,
                hdpc_path=hdpc_path,
                status="processing",
            )
            db.session.add(session_row)
            db.session.flush()
            db.session.add(
                UserMetadata(
                    session_id=session_row.id,
                    field_name="zenodo_metadata_draft",
                    field_value=json.dumps(
                        {
                            "title": "Model title",
                            "description": "Model description",
                            "creators": [{"name": "Museum"}],
                        }
                    ),
                )
            )
            db.session.commit()
            self.session_id = session_row.id

    def tearDown(self):
        self.temp_dir.cleanup()
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_hdpc_local_service_reads_file_map_and_infers_input_dir(self):
        hdpc_path = os.path.join(self.temp_dir.name, "session.hdpc")

        inspect_data = inspect_hdpc_project(hdpc_path, show_files=True)
        file_id_map = get_hdpc_file_id_map(hdpc_path)

        assert file_id_map == {"model.glb": "101"}
        assert inspect_data["file_tree"][0]["absolute_path"] == self.source_path
        assert any(
            item.get("config_key") == "paths.data_in" and item.get("config_value") == os.path.dirname(self.source_path)
            for item in inspect_data["configuration"]
        )

    def test_hdpc_local_mutation_service_creates_records_and_registers_generated_files(self):
        hdpc_path = os.path.join(self.temp_dir.name, "session.hdpc")
        preview_path = os.path.join(self.temp_dir.name, "outputs", "preview.png")
        os.makedirs(os.path.dirname(preview_path), exist_ok=True)
        with open(preview_path, "w", encoding="utf-8") as handle:
            handle.write("preview")

        created = create_local_record_with_metadata(
            hdpc_path,
            file_id=101,
            metadata={
                "title": "Local title",
                "description": "Local description",
                "creators": [{"name": "Museum"}],
            },
            is_sandbox=True,
            access_token="sandbox-token",
        )
        added = add_local_source_files(
            hdpc_path,
            absolute_file_paths=[preview_path],
            record_id_to_associate=created["local_record_db_id"],
            pipeline_name="render",
            step_name="fast_renderer",
        )

        self.assertTrue(created["success"])
        self.assertEqual(added["added_count"], 1)

        conn = sqlite3.connect(hdpc_path)
        conn.row_factory = sqlite3.Row
        try:
            record = conn.execute("SELECT * FROM zenodo_records WHERE record_id = ?", (created["local_record_db_id"],)).fetchone()
            self.assertIsNotNone(record)
            self.assertEqual(record["source_file_id"], 101)
            self.assertEqual(record["record_status"], "prepared")
            self.assertEqual(record["record_origin"], "submit_pipeline")
            payload = json.loads(record["record_metadata_json"])
            self.assertEqual(payload["metadata"]["title"], "Local title")

            configs = {
                row["config_key"]: row["config_value"]
                for row in conn.execute("SELECT config_key, config_value FROM project_configuration").fetchall()
            }
            self.assertEqual(configs["main.use_sandbox"], "1")
            self.assertEqual(configs["core.use_sandbox"], "1")
            self.assertNotIn("preferences.zenodo_sandbox_api_key", configs)

            mapped = conn.execute(
                "SELECT file_purpose FROM record_files_map WHERE record_id = ? ORDER BY map_id ASC",
                (created["local_record_db_id"],),
            ).fetchall()
            self.assertEqual([row["file_purpose"] for row in mapped], ["main", "generated"])
        finally:
            conn.close()

    def test_hdpc_local_mutation_service_persists_access_token_only_when_requested(self):
        hdpc_path = os.path.join(self.temp_dir.name, "session.hdpc")

        created = create_local_record_with_metadata(
            hdpc_path,
            file_id=101,
            metadata={
                "title": "Persisted token title",
                "description": "Persisted token description",
                "creators": [{"name": "Museum"}],
            },
            is_sandbox=True,
            access_token="sandbox-token",
            persist_access_token=True,
        )

        self.assertTrue(created["success"])

        conn = sqlite3.connect(hdpc_path)
        conn.row_factory = sqlite3.Row
        try:
            configs = {
                row["config_key"]: row["config_value"]
                for row in conn.execute("SELECT config_key, config_value FROM project_configuration").fetchall()
            }
            self.assertEqual(configs["preferences.zenodo_sandbox_api_key"], "sandbox-token")
        finally:
            conn.close()

    @patch("services.submission_pipeline_service.ensure_fresh_record_creation_allowed", return_value=None)
    def test_execute_submission_pipeline_prefers_existing_record_ids_over_local_file_paths(self, _guard):
        self.app.native_pipeline_service.get_pipeline.return_value = {"config": {"steps": []}}
        self.app.native_pipeline_service.resolve_pipeline_identifier.return_value = "render"
        self.app.native_pipeline_service.execute_registered_submission.return_value = {
            "success": True,
            "summary": {"successful_count": 1, "failed_count": 0, "processed_count": 1},
            "details": [{"record_id": 1}],
            "run_id": "run-native-rerun",
        }

        with self.app.app_context():
            created = create_local_record_with_metadata(
                os.path.join(self.temp_dir.name, "session.hdpc"),
                file_id=101,
                metadata={
                    "title": "Existing record",
                    "description": "Existing record description",
                    "creators": [{"name": "Museum"}],
                },
                is_sandbox=True,
                access_token="sandbox-token",
            )

            with patch(
                "services.submission_pipeline_service.create_local_record_with_metadata",
                side_effect=AssertionError("Reruns must not recreate records"),
            ) as create_record_mock:
                result = execute_submission_pipeline(
                    identifier="render",
                    local_file_paths=[self.source_path],
                    db_session_id=self.session_id,
                    is_sandbox=True,
                    record_ids=[created["local_record_db_id"]],
                )

        assert result["result"]["success"] is True
        create_record_mock.assert_not_called()
        execution_context = self.app.native_pipeline_service.execute_registered_submission.call_args.args[1]
        assert execution_context["record_ids"] == [created["local_record_db_id"]]
        assert execution_context["local_file_paths"] == []

    @patch(
        "services.submission_pipeline_service.publishing_context_service.describe_session",
        return_value={
            "workspace_type": "institution",
            "credential_preference": "institution",
            "effective_credential_source": "institution",
            "institution_id": 77,
            "publishing_user_id": 11,
            "default_communities": ["museum-a"],
            "primary_submission_community": "museum-a",
            "moderation_default_communities": [],
            "use_institution_default_communities": True,
        },
    )
    @patch(
        "services.submission_pipeline_service.publishing_context_service.resolve_token_for_session",
        return_value={
            "environment": "sandbox",
            "source": "institution",
            "owner_type": "institution",
            "owner_id": 77,
            "credential_id": 12,
            "token": "resolved-session-token",
            "masked_preview": "reso...oken",
        },
    )
    @patch("services.submission_pipeline_service.ensure_fresh_record_creation_allowed", return_value=None)
    def test_execute_submission_pipeline_carries_safe_publishing_context_into_native_execution(
        self,
        _guard,
        _resolve_token,
        _describe_session,
    ):
        self.app.native_pipeline_service.get_pipeline.return_value = {"config": {"steps": [{"id": "zenodo_draft"}]}}
        self.app.native_pipeline_service.resolve_pipeline_identifier.return_value = "render"
        self.app.native_pipeline_service.execute_registered_submission.return_value = {
            "success": True,
            "summary": {"successful_count": 1, "failed_count": 0, "processed_count": 1},
            "details": [{"record_id": 1}],
            "run_id": "run-native-token-context",
        }

        with self.app.app_context():
            result = execute_submission_pipeline(
                identifier="render",
                local_file_paths=[self.source_path],
                db_session_id=self.session_id,
                is_sandbox=True,
            )

        assert result["result"]["success"] is True
        execution_context = self.app.native_pipeline_service.execute_registered_submission.call_args.args[1]
        assert execution_context["access_token"] == "resolved-session-token"
        assert execution_context["zenodo_environment"] == "sandbox"
        assert execution_context["credential_source"] == "institution"
        assert execution_context["publishing_context"] == {
            "environment": "sandbox",
            "credential_source": "institution",
            "owner_type": "institution",
            "owner_id": 77,
            "credential_id": 12,
            "masked_preview": "reso...oken",
            "workspace_type": "institution",
            "credential_preference": "institution",
            "institution_id": 77,
            "publishing_user_id": 11,
            "community_policy": {
                "default_communities": ["museum-a"],
                "primary_submission_community": "museum-a",
                "moderation_default_communities": [],
                "use_institution_default_communities": True,
            },
        }

    @patch("services.submission_pipeline_service.ensure_fresh_record_creation_allowed", return_value=None)
    def test_execute_submission_pipeline_uses_local_hdpc_context_before_external_project_inspection(self, _guard):
        self.app.project_service.add_source_files.return_value = {"success": True}
        self.app.native_pipeline_service.get_pipeline.return_value = {"config": {"steps": []}}
        self.app.native_pipeline_service.resolve_pipeline_identifier.return_value = "render"
        self.app.native_pipeline_service.execute_registered_submission.return_value = {
            "success": True,
            "summary": {"successful_count": 1, "failed_count": 0, "processed_count": 1},
            "details": [{"record_id": 1}],
            "run_id": "run-native-1",
        }

        with self.app.app_context():
            result = execute_submission_pipeline(
                identifier="render",
                local_file_paths=[self.source_path],
                db_session_id=self.session_id,
                is_sandbox=True,
            )

        assert result["result"]["success"] is True
        self.app.project_service.load.assert_not_called()
        self.app.project_service.inspect.assert_not_called()
        self.app.project_service.get_file_id_map.assert_not_called()
        self.app.project_service.create_record_with_metadata.assert_not_called()
        self.app.project_service.add_source_files.assert_not_called()
        self.app.native_pipeline_service.execute_registered_submission.assert_called_once()
        execution_context = self.app.native_pipeline_service.execute_registered_submission.call_args.args[1]
        assert execution_context["record_ids"] == [1]
        assert execution_context["record_info_list"][0][1] == self.source_path
        assert execution_context["normalized_file_id_map"] == {"model.glb": "101"}

        hdpc_path = os.path.join(self.temp_dir.name, "session.hdpc")
        conn = sqlite3.connect(hdpc_path)
        conn.row_factory = sqlite3.Row
        try:
            created_record = conn.execute("SELECT * FROM zenodo_records WHERE record_id = 1").fetchone()
            assert created_record is not None
            linked = conn.execute(
                "SELECT COUNT(*) FROM record_files_map WHERE record_id = ?",
                (1,),
            ).fetchone()[0]
            assert linked == 1
        finally:
            conn.close()

    @patch("services.submission_pipeline_service.ensure_fresh_record_creation_allowed", return_value=None)
    def test_execute_submission_pipeline_resolves_upload_msf_csv_for_lod_mapping(self, _guard):
        candidate_path = os.path.join(self.temp_dir.name, "uploads", "upload.msf.csv")
        with open(candidate_path, "w", encoding="utf-8") as handle:
            handle.write("filename,title\nmodel.glb,Mapped title\n")

        self.app.native_pipeline_service.get_pipeline.return_value = {"config": {"steps": []}}
        self.app.native_pipeline_service.resolve_pipeline_identifier.return_value = "render"
        self.app.native_pipeline_service.execute_registered_submission.return_value = {
            "success": True,
            "summary": {"successful_count": 1, "failed_count": 0, "processed_count": 1},
            "details": [{"record_id": 1}],
            "run_id": "run-native-msf-csv",
        }
        self.app.msf_service.parse_msf_file.return_value = (MagicMock(iterrows=lambda: iter([(0, {"filename": "model.glb"})])), {})
        self.app.msf_service.detect_filename_column.return_value = ("filename", 1.0)

        with self.app.app_context():
            db.session.add(
                UserMetadata(
                    session_id=self.session_id,
                    field_name="zenodo_metadata_draft",
                    field_value=json.dumps(
                        {
                            "title": "Model title",
                            "description": "Model description",
                            "creators": [{"name": "Museum"}],
                            "lod_mapping": {"zenodo": {"3d": {"title": {"source": "column", "column": "title"}}}},
                        }
                    ),
                )
            )
            db.session.commit()

            execute_submission_pipeline(
                identifier="render",
                local_file_paths=[self.source_path],
                db_session_id=self.session_id,
                is_sandbox=True,
            )

        self.app.msf_service.parse_msf_file.assert_called_once_with(candidate_path, parse_options={})

    def test_execute_submission_pipeline_requires_resolvable_msf_when_lod_mapping_is_configured(self):
        self.app.native_pipeline_service.get_pipeline.return_value = {"config": {"steps": []}}
        self.app.native_pipeline_service.resolve_pipeline_identifier.return_value = "render"
        self.app.native_pipeline_service.execute_registered_submission.return_value = {
            "success": True,
            "summary": {"successful_count": 1, "failed_count": 0, "processed_count": 1},
            "details": [{"record_id": 1}],
            "run_id": "run-native-msf-missing",
        }

        with self.app.app_context():
            db.session.add(
                UserMetadata(
                    session_id=self.session_id,
                    field_name="zenodo_metadata_draft",
                    field_value=json.dumps(
                        {
                            "title": "Model title",
                            "description": "Model description",
                            "creators": [{"name": "Museum"}],
                            "lod_mapping": {"zenodo": {"3d": {"title": {"source": "column", "column": "title"}}}},
                        }
                    ),
                )
            )
            db.session.commit()

            with self.assertRaises(FileProcessingError) as ctx:
                execute_submission_pipeline(
                    identifier="render",
                    local_file_paths=[self.source_path],
                    db_session_id=self.session_id,
                    is_sandbox=True,
                )

        self.assertIn("LOD mapping is configured but no MSF source was found", str(ctx.exception))

    @patch("services.submission_pipeline_service.ensure_fresh_record_creation_allowed", return_value=None)
    @patch("services.submission_pipeline_service.get_hdpc_file_id_map", return_value={})
    @patch("services.submission_pipeline_service.inspect_hdpc_project", return_value={"configuration": [], "file_tree": []})
    def test_execute_submission_pipeline_requires_local_hdpc_queries(
        self,
        _inspect_hdpc_project,
        _get_hdpc_file_id_map,
        _guard,
    ):
        self.app.native_pipeline_service.get_pipeline.return_value = {"config": {"steps": []}}
        self.app.native_pipeline_service.resolve_pipeline_identifier.return_value = "render"
        self.app.native_pipeline_service.execute_registered_submission.return_value = {
            "success": True,
            "summary": {"successful_count": 1, "failed_count": 0, "processed_count": 1},
            "details": [{"record_id": 1}],
            "run_id": "run-native-fallback",
        }

        with self.app.app_context():
            with self.assertRaises(FileProcessingError):
                execute_submission_pipeline(
                    identifier="render",
                    local_file_paths=[self.source_path],
                    db_session_id=self.session_id,
                    is_sandbox=True,
                )

        self.app.project_service.load.assert_not_called()
        self.app.project_service.inspect.assert_not_called()
        self.app.project_service.get_file_id_map.assert_not_called()

    @patch("services.submission_pipeline_service.publishing_context_service.resolve_token_for_session",
           return_value={"token": "fixture-token"})
    @patch("services.submission_pipeline_service.create_local_record_with_metadata")
    @patch("services.submission_pipeline_service._resolve_version_target_record")
    @patch("services.submission_pipeline_service.analyze_session_record_resolution")
    def test_execute_submission_pipeline_uses_saved_create_version_execution_items(
        self,
        analyze_resolution,
        resolve_target_record,
        create_record_mock,
        _resolve_token,
    ):
        self.app.native_pipeline_service.get_pipeline.return_value = {"config": {"steps": []}}
        self.app.native_pipeline_service.resolve_pipeline_identifier.return_value = "render"
        self.app.native_pipeline_service.execute_registered_submission.return_value = {
            "success": True,
            "summary": {"successful_count": 1, "failed_count": 0, "processed_count": 1},
            "details": [{"record_id": 9}],
            "run_id": "run-native-version-plan",
        }
        self.app.project_service.prepare_new_version_draft.return_value = {
            "success": True,
            "new_local_record_id": 9,
            "local_record_db_id": 9,
        }
        create_record_mock.side_effect = AssertionError("Create-version execution must not create a fresh local record")
        analyze_resolution.return_value = {
            "candidates": [
                {
                    "decision_key": "dataset::model",
                    "selected_action": "create_version",
                    "severity": "version",
                    "resolved": True,
                    "selected_target": {
                        "session_id": 77,
                        "local_record_id": 88,
                        "concept_rec_id": "7001",
                    },
                }
            ]
        }
        resolve_target_record.return_value = {
            "local_record_id": 88,
            "concept_rec_id": "7001",
            "record_status": "published",
        }

        with self.app.app_context():
            result = execute_submission_pipeline(
                identifier="render",
                local_file_paths=[],
                db_session_id=self.session_id,
                is_sandbox=True,
                execution_items=[
                    {
                        "decision_key": "dataset::model",
                        "action": "create_version",
                        "source_file_path": self.source_path,
                        "source_file_name": "model.glb",
                        "target_session_id": 77,
                        "target_local_record_id": 88,
                        "target_concept_rec_id": "7001",
                    }
                ],
            )

        assert result["result"]["success"] is True
        self.app.project_service.prepare_new_version_draft.assert_called_once()
        create_record_mock.assert_not_called()
        execution_context = self.app.native_pipeline_service.execute_registered_submission.call_args.args[1]
        assert execution_context["record_ids"] == [9]
        assert execution_context["record_resolution_by_record_id"][9]["action"] == "create_version"

    @patch("services.submission_pipeline_service.record_audit_event")
    @patch("services.submission_pipeline_service.ensure_fresh_record_creation_allowed")
    @patch("services.submission_pipeline_service.analyze_session_record_resolution")
    def test_execute_submission_pipeline_honors_skip_and_force_create_execution_items(
        self,
        analyze_resolution,
        ensure_fresh_guard,
        audit_event,
    ):
        second_path = os.path.join(self.temp_dir.name, "uploads", "model-two.glb")
        with open(second_path, "w", encoding="utf-8") as handle:
            handle.write("glb-2")

        hdpc_path = os.path.join(self.temp_dir.name, "session.hdpc")
        conn = sqlite3.connect(hdpc_path)
        try:
            conn.execute(
                """
                INSERT INTO source_files (
                    file_id, filename, absolute_path, relative_path, file_type, status,
                    size_bytes, mime_type, pipeline_source, step_source, added_timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    102,
                    "model-two.glb",
                    second_path,
                    "model-two.glb",
                    "primary_source",
                    "ready",
                    120,
                    "model/gltf-binary",
                    "ingestion",
                    "scan",
                    "2026-03-11T10:00:00Z",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        self.app.native_pipeline_service.get_pipeline.return_value = {"config": {"steps": []}}
        self.app.native_pipeline_service.resolve_pipeline_identifier.return_value = "render"
        self.app.native_pipeline_service.execute_registered_submission.return_value = {
            "success": True,
            "summary": {"successful_count": 1, "failed_count": 0, "processed_count": 1},
            "details": [{"record_id": 1}],
            "run_id": "run-native-force-create",
        }
        analyze_resolution.return_value = {
            "candidates": [
                {
                    "decision_key": "dataset::model-one",
                    "selected_action": "skip",
                    "severity": "warning",
                    "resolved": True,
                },
                {
                    "decision_key": "dataset::model-two",
                    "selected_action": "force_create_fresh",
                    "severity": "blocker",
                    "resolved": True,
                    "forced_override_reason": "Curator approved duplicate exception",
                },
            ]
        }
        ensure_fresh_guard.side_effect = AssertionError("force_create_fresh must bypass the normal fresh-record guard")

        with self.app.app_context():
            result = execute_submission_pipeline(
                identifier="render",
                local_file_paths=[],
                db_session_id=self.session_id,
                is_sandbox=True,
                execution_items=[
                    {
                        "decision_key": "dataset::model-one",
                        "action": "skip",
                        "source_file_path": self.source_path,
                        "source_file_name": "model.glb",
                    },
                    {
                        "decision_key": "dataset::model-two",
                        "action": "force_create_fresh",
                        "source_file_path": second_path,
                        "source_file_name": "model-two.glb",
                        "forced_override_reason": "Curator approved duplicate exception",
                    },
                ],
            )

        assert result["result"]["success"] is True
        audit_event.assert_called_once()
        audit_details = audit_event.call_args.kwargs["details"]
        assert audit_details["decision_key"] == "dataset::model-two"
        assert audit_details["reason"] == "Curator approved duplicate exception"
        execution_context = self.app.native_pipeline_service.execute_registered_submission.call_args.args[1]
        assert execution_context["skipped_files"] == [self.source_path]
        assert len(execution_context["record_ids"]) == 1

    def test_execute_submission_pipeline_rejects_execution_plan_environment_mismatch(self):
        with self.app.app_context():
            with self.assertRaises(FileProcessingError) as ctx:
                execute_submission_pipeline(
                    identifier="render",
                    local_file_paths=[],
                    db_session_id=self.session_id,
                    is_sandbox=False,
                    execution_items=[
                        {
                            "decision_key": "dataset::model",
                            "action": "create_fresh_record",
                            "source_file_path": self.source_path,
                            "source_file_name": "model.glb",
                        }
                    ],
                )

        self.assertIn("default Zenodo environment", str(ctx.exception))
        self.app.native_pipeline_service.execute_registered_submission.assert_not_called()
