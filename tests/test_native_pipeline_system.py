import os
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import subprocess

from flask import Flask
import yaml

from constants import HMSM_PIPELINE_DEFINITIONS, OPTIONAL_3D_PIPELINE_DEFINITIONS, PIPELINE_DEFINITION
from database.database import db
from database.models import (
    ComponentDefinition,
    ExecutionArtifact,
    PipelineRun,
    PipelineVersion,
    Session as DBSession,
    StepRun,
    User,
    UserRole,
)
from exceptions import FileProcessingError, ResourceNotFoundError, ValidationError
from services.native_pipeline_adapters import AdapterExecutionRequest
from services.native_pipeline_system import NativePipelineSystemService


class NativePipelineSystemTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="native-pipeline-test-")
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        self.app.config["SECRET_KEY"] = "test-secret"
        self.app.config["JWT_SECRET_KEY"] = "test-jwt"
        self.app.config["ENABLE_RENDERER"] = True
        self.app.config["ENABLE_USDZ_CONVERSION"] = True
        self.app.config["ENABLE_METIS_VALIDATION"] = False
        self.app.config["WEBHDP_DEPLOYMENT_MODE"] = "local"
        self.app.config["WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS"] = True

        db.init_app(self.app)
        self.native_service = NativePipelineSystemService()
        self.app.native_pipeline_service = self.native_service

        self.app.project_service = MagicMock()
        self.app.fast_renderer_service = MagicMock()
        self.app.any_to_usdz_service = MagicMock()
        self.app.fast_renderer_service.check_health.return_value = True
        self.app.any_to_usdz_service.check_health.return_value = True
        self.app.edm_service = MagicMock()
        self.app.iiif_service = MagicMock()
        self.app.mets_service = MagicMock()
        self.app.msf_service = MagicMock()

        with self.app.app_context():
            db.create_all()
            self.user = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
            self.user.set_password("password")
            db.session.add(self.user)
            self.other_user = User(email="user@example.com", role=UserRole.USER, is_verified=True)
            self.other_user.set_password("password")
            db.session.add(self.other_user)
            db.session.commit()
            self.user_id = self.user.id
            self.other_user_id = self.other_user.id
            self.native_service.ensure_seeded()

    def _reserve_run(self, *args, **kwargs):
        # Reservation lifecycle fixtures isolate readiness, which has integration coverage.
        with patch.object(self.native_service, 'require_submission_readiness', return_value={'_state': None}):
            return self.native_service.create_pending_run(*args, **kwargs)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_core_profile_lists_and_accepts_only_validated_pipelines(self):
        with patch.dict(os.environ, {"WEBHDP_CORE_ONLY": "true"}), self.app.app_context():
            identifiers = {item["identifier"] for item in self.native_service.list_pipelines(include_hidden=True)}
            self.assertEqual(identifiers, {"render", "metadata_only"})
            self.assertEqual(self.native_service.get_pipeline("render")["identifier"], "render")
            with self.assertRaises(ValidationError):
                self.native_service.get_pipeline(next(iter(OPTIONAL_3D_PIPELINE_DEFINITIONS)))

    def test_server_deployment_blocks_local_renderer_without_hpc_allocation(self):
        self.app.config["WEBHDP_DEPLOYMENT_MODE"] = "server"
        self.app.config["WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS"] = False
        with self.app.app_context():
            with self.assertRaises(FileProcessingError) as exc:
                self.native_service._ensure_component_runtime_available(
                    "fast_renderer",
                    {"db_session_id": 123},
                )
        self.assertIn("must run through an active HPC-Link allocation", str(exc.exception))
        self.app.fast_renderer_service.check_health.assert_not_called()

    def test_local_deployment_allows_local_renderer_when_opted_in(self):
        self.app.config["WEBHDP_DEPLOYMENT_MODE"] = "local"
        self.app.config["WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS"] = True
        with self.app.app_context():
            self.native_service._ensure_component_runtime_available(
                "fast_renderer",
                {"db_session_id": 123},
            )
        self.app.fast_renderer_service.check_health.assert_called()

    def test_local_deployment_reports_unavailable_renderer_when_service_down(self):
        self.app.config["WEBHDP_DEPLOYMENT_MODE"] = "local"
        self.app.config["WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS"] = True
        self.app.fast_renderer_service.check_health.return_value = False

        with self.app.app_context():
            with self.assertRaises(FileProcessingError) as exc:
                self.native_service._ensure_component_runtime_available(
                    "fast_renderer",
                    {"db_session_id": 123},
                )

        self.assertIn("configured for local workstation execution", str(exc.exception))
        self.assertIn("local service is not reachable", str(exc.exception))

    def test_hpc_only_component_requires_active_hpc_allocation(self):
        self.app.config["WEBHDP_DEPLOYMENT_MODE"] = "local"
        self.app.config["WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS"] = True

        with self.app.app_context():
            with self.assertRaises(FileProcessingError) as exc:
                self.native_service._ensure_component_runtime_available(
                    "gltf_validator",
                    {"db_session_id": 123},
                    hpc_only=True,
                )

        self.assertIn("HPC-only", str(exc.exception))
        self.assertIn("Request an active HPC-Link allocation", str(exc.exception))

    def _build_generic_execution_context(self, session_dir: Path, source_file: Path, session_row: DBSession, pipeline_steps):
        outputs_dir = session_dir / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)
        return {
            "identifier": "generic_pipeline",
            "canonical_identifier": "generic_pipeline",
            "local_file_paths": [str(source_file)],
            "db_session_id": session_row.id,
            "db_session": session_row,
            "hdpc_path": str(session_dir / "session.hdpc"),
            "is_sandbox": True,
            "abort_on_critical_error": False,
            "progress_callback": None,
            "pipeline_timings": {
                "project_loading": 0,
                "record_registration": 0,
                "batch_render": 0,
                "record_processing": [],
                "total_execution": 0,
            },
            "record_info_list": [
                (
                    77,
                    str(source_file),
                    {
                        "title": "Model title",
                        "description": "Model description",
                    },
                )
            ],
            "skipped_files": [],
            "outputs_dir": str(outputs_dir),
            "batch_metadata_map": {},
            "shared_zenodo_metadata": {},
            "batch_shared_zenodo_metadata": {},
            "batch_item_defaults": {},
            "lod_mapping_config": None,
            "resolved_lod_msf_path": None,
            "msf_rows_by_filename": {},
            "normalized_file_id_map": {},
            "file_id_to_relative_path": {},
            "bundle_file_paths_by_relative": {},
            "basename_to_relative_paths": {},
            "relative_to_absolute_path": {},
            "absolute_to_relative_path": {},
            "steps_map": {step["id"]: step for step in pipeline_steps},
        }

    def _prepare_generic_pipeline_session(self, name: str, filename: str = "model.glb"):
        session_dir = Path(self.temp_dir) / name
        uploads_dir = session_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        source_file = uploads_dir / filename
        source_file.write_text("glb-data", encoding="utf-8")
        hdpc_path = session_dir / "session.hdpc"
        self._create_hdpc_source_file(hdpc_path, source_file, file_id=101)

        session_row = DBSession(
            user_id=self.user_id,
            session_dir=str(session_dir),
            hdpc_path=str(hdpc_path),
            status="processing",
        )
        db.session.add(session_row)
        db.session.commit()
        return session_dir, source_file, session_row

    def _create_hdpc_source_file(self, hdpc_path: Path, source_file: Path, file_id: int = 101) -> None:
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
                    file_id,
                    source_file.name,
                    str(source_file),
                    source_file.name,
                    "primary_source",
                    "ready",
                    source_file.stat().st_size,
                    "model/gltf-binary",
                    "ingestion",
                    "scan",
                    "2026-03-10T10:00:00Z",
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _write_batch_directory_component(self, component_dir: Path, name: str = "batch_directory_consumer") -> None:
        component_dir.mkdir(parents=True, exist_ok=True)
        (component_dir / "component.yaml").write_text(
            "\n".join(
                [
                    "metadata:",
                    f"  name: {name}",
                    '  version: "0.1.0"',
                    "  description: Batch component requiring both file and directory context",
                    "inputs:",
                    "  - name: input_files",
                    "    type: file_list",
                    "    required: true",
                    "  - name: input_dir",
                    "    type: dir_path",
                    "    required: true",
                    "outputs: []",
                    "parameter_groups: []",
                    "execution:",
                    "  profiles:",
                    "    - id: local_default",
                    "      adapter: local_cli",
                    "      entrypoint: [\"batch-dir-tool\", \"run\"]",
                    "compatibility: {}",
                ]
            ),
            encoding="utf-8",
        )

    def test_manifest_validation_infers_legacy_execution(self):
        component_dir = Path(self.temp_dir) / "legacy_component"
        component_dir.mkdir(parents=True, exist_ok=True)
        (component_dir / "main.py").write_text("print('hello')\n", encoding="utf-8")
        (component_dir / "component.yaml").write_text(
            "\n".join(
                [
                    "metadata:",
                    "  name: legacy_component",
                    '  version: "0.1.0"',
                    "inputs: []",
                    "outputs: []",
                    "parameter_groups: []",
                ]
            ),
            encoding="utf-8",
        )

        with self.app.app_context():
            validation = self.native_service.validate_component_manifest_path(str(component_dir))

        manifest = validation["manifest"]
        self.assertEqual(manifest["execution"]["profiles"][0]["adapter"], "legacy_hdp_python")
        self.assertTrue(manifest["compatibility"]["legacy_inferred_execution"])
        self.assertEqual(manifest["compatibility"]["playground"], {"enabled": True, "reason": None})

    def test_list_components_filters_to_playground_enabled_components_only(self):
        component_dir = Path(self.temp_dir) / "playground_enabled_component"
        component_dir.mkdir(parents=True, exist_ok=True)
        (component_dir / "component.yaml").write_text(
            "\n".join(
                [
                    "metadata:",
                    "  name: playground_enabled_component",
                    '  version: "0.1.0"',
                    "inputs: []",
                    "outputs: []",
                    "parameter_groups: []",
                    "execution:",
                    "  profiles:",
                    "    - id: local_default",
                    "      adapter: local_cli",
                    "      entrypoint: [\"component-cli\"]",
                    "compatibility: {}",
                ]
            ),
            encoding="utf-8",
        )

        with self.app.app_context():
            self.native_service.import_component_from_path(str(component_dir))
            components = self.native_service.list_components(playground_only=True)

        components_by_key = {component["key"]: component for component in components}
        self.assertIn("playground_enabled_component", components_by_key)
        self.assertIn("fast_renderer", components_by_key)
        self.assertIn("any_to_usdz", components_by_key)
        self.assertEqual(components_by_key["fast_renderer"]["name"], "Fast 3D Model Renderer")
        self.assertEqual(components_by_key["any_to_usdz"]["name"], "USDZ Converter")
        self.assertEqual(
            components_by_key["fast_renderer"]["playground_schema"]["metadata"]["category"],
            "3D Processing",
        )

    def test_builtin_playground_components_load_from_physical_manifests(self):
        with self.app.app_context():
            components = {
                component["key"]: component
                for component in self.native_service.list_components(playground_only=True)
            }

        fast_renderer = components["fast_renderer"]
        any_to_usdz = components["any_to_usdz"]
        self.assertEqual(
            fast_renderer["manifest"]["compatibility"]["manifest_source"],
            str((Path(__file__).resolve().parents[1] / "external_code" / "fast_renderer" / "component.yaml").resolve()),
        )
        self.assertEqual(
            any_to_usdz["manifest"]["compatibility"]["manifest_source"],
            str((Path(__file__).resolve().parents[1] / "external_code" / "any_to_usdz" / "component.yaml").resolve()),
        )
        self.assertEqual(
            fast_renderer["playground_schema"]["result"]["artifact_views"][0]["widget"],
            "image_gallery",
        )
        self.assertEqual(any_to_usdz["playground_schema"]["inputs"][0]["widget"], "model_input")

    def test_manifest_validation_rejects_array_default_on_string_field(self):
        component_dir = Path(self.temp_dir) / "invalid_default_component"
        component_dir.mkdir(parents=True, exist_ok=True)
        (component_dir / "component.yaml").write_text(
            "\n".join(
                [
                    "metadata:",
                    "  name: invalid_default_component",
                    '  version: "0.1.0"',
                    "inputs:",
                    "  - name: formats",
                    "    type: string",
                    "    default: [\".glb\"]",
                    "outputs: []",
                    "parameter_groups: []",
                    "execution:",
                    "  profiles:",
                    "    - id: local_default",
                    "      adapter: local_cli",
                    "      entrypoint: [\"component-cli\"]",
                ]
            ),
            encoding="utf-8",
        )

        with self.app.app_context():
            with self.assertRaises(ValidationError):
                self.native_service.validate_component_manifest_path(str(component_dir))

    def test_manifest_validation_returns_normalized_playground_schema(self):
        component_dir = Path(self.temp_dir) / "ui_component"
        component_dir.mkdir(parents=True, exist_ok=True)
        (component_dir / "component.yaml").write_text(
            "\n".join(
                [
                    "metadata:",
                    "  name: ui_component",
                    '  version: "0.1.0"',
                    "inputs:",
                    "  - name: source_image",
                    "    type: file_path",
                    "    required: true",
                    "outputs: []",
                    "parameter_groups:",
                    "  - title: General",
                    "    parameters:",
                    "      - name: resize_width",
                    "        type: integer",
                    "      - name: lock_ratio",
                    "        type: boolean",
                    "ui:",
                    "  playground:",
                    "    fields:",
                    "      source_image:",
                    "        widget: image_input",
                    "        accept_extensions: [\".png\", \".jpg\"]",
                    "      resize_width:",
                    "        widget: number_input",
                    "        mutex_with: [\"lock_ratio\"]",
                    "      lock_ratio:",
                    "        widget: checkbox",
                    "        visible_if:",
                    "          field: source_image",
                    "          truthy: true",
                    "execution:",
                    "  profiles:",
                    "    - id: local_default",
                    "      adapter: local_cli",
                    "      entrypoint: [\"component-cli\"]",
                ]
            ),
            encoding="utf-8",
        )

        with self.app.app_context():
            validation = self.native_service.validate_component_manifest_path(str(component_dir))

        playground_schema = validation["playground_schema"]
        self.assertEqual(playground_schema["inputs"][0]["widget"], "image_input")
        self.assertEqual(playground_schema["inputs"][0]["accept_extensions"], [".png", ".jpg"])
        parameter_fields = {
            field["name"]: field
            for group in playground_schema["parameter_groups"]
            for field in group["fields"]
        }
        self.assertEqual(parameter_fields["resize_width"]["constraints"]["mutex_with"], ["lock_ratio"])
        self.assertEqual(parameter_fields["lock_ratio"]["constraints"]["visible_if"]["field"], "source_image")

    def test_pipeline_updates_create_new_immutable_versions(self):
        updated = {
            **PIPELINE_DEFINITION,
            "steps": [
                {**step, "enabled": False} if step["id"] == "any_to_usdz" else dict(step)
                for step in PIPELINE_DEFINITION["steps"]
            ],
        }

        with self.app.app_context():
            original_count = PipelineVersion.query.count()
            self.native_service.create_pipeline_version_from_config(
                "render",
                updated,
                activate=True,
                created_by_user_id=self.user_id,
                mirror_legacy_config=True,
            )
            new_count = PipelineVersion.query.count()
            render_definition = self.native_service.get_pipeline("render")

        self.assertGreater(new_count, original_count)
        self.assertEqual(render_definition["config"]["steps"][1]["id"], "any_to_usdz")
        self.assertFalse(render_definition["config"]["steps"][1]["enabled"])

    def test_optional_3d_pipelines_are_skipped_until_components_are_registered(self):
        with self.app.app_context():
            pipeline_ids = {pipeline["identifier"] for pipeline in self.native_service.list_pipelines()}

        for identifier in OPTIONAL_3D_PIPELINE_DEFINITIONS:
            self.assertNotIn(identifier, pipeline_ids)

    def test_optional_3d_pipelines_seed_validate_and_remain_idempotent_after_component_import(self):
        repo_root = Path(__file__).resolve().parents[1]
        component_dirs = [
            repo_root / "external_code" / component_name
            for component_name in [
                "model_profiler",
                "geometry_qa_gate",
                "texture_dependency_auditor",
                "canonical_glb_normalizer",
                "geometric_lod_generator",
                "point_cloud_analyzer",
                "scale_orientation_centering_normalizer",
                "model_repair_component",
                "model_fingerprint_deduplication",
                "viewer_readiness_analyzer",
            ]
        ]

        with self.app.app_context():
            import yaml
            for component_dir in component_dirs:
                manifest = yaml.safe_load((component_dir / "component.yaml").read_text())
                for profile in manifest.get("execution", {}).get("profiles", []):
                    if profile.get("runtime") == "docker":
                        profile["image"] = "sha256:" + "a" * 64
                self.native_service.import_component_from_manifest(manifest, source_path=str(component_dir))
            self.native_service._seed_state = "idle"
            self.native_service.ensure_seeded()

            for identifier, definition in OPTIONAL_3D_PIPELINE_DEFINITIONS.items():
                validation = self.native_service.validate_pipeline_config(definition)
                pipeline = self.native_service.get_pipeline(identifier)
                self.assertTrue(validation["valid"], identifier)
                self.assertEqual(pipeline["active_version"], pipeline["config"]["version"])
                self.assertEqual(pipeline["active_version"], "1.0.0")
                self.assertEqual(len(pipeline["config"]["steps"]), len(definition["steps"]))
                output_action_targets = {
                    action.get("target_field")
                    for step in pipeline["config"]["steps"]
                    for action in step.get("output_actions", [])
                }
                if identifier in {"3d_prepublication_analysis", "3d_point_cloud_readiness"}:
                    self.assertIn("model_type", output_action_targets)
                    self.assertIn("point_count", output_action_targets)

            version_count = PipelineVersion.query.count()
            self.native_service._seed_state = "idle"
            self.native_service.ensure_seeded()
            self.assertEqual(PipelineVersion.query.count(), version_count)

    def _import_hmsm_component(self, component_key, *, pin_image=True, version=None):
        path = Path(__file__).resolve().parents[1] / "external_code" / component_key / "component.yaml"
        manifest = yaml.safe_load(path.read_text())
        if pin_image:
            manifest["execution"]["profiles"][0]["image"] = "sha256:" + "a" * 64
        if version:
            manifest["metadata"]["version"] = version
        return self.native_service.import_component_from_manifest(manifest)

    def test_hmsm_templates_require_pinned_profiles_and_preserve_saved_versions(self):
        with self.app.app_context():
            self._import_hmsm_component("hmsm_midi_reconstruction", pin_image=False)
            self._import_hmsm_component("hmsm_scan_digitizer")
            registered = {row["identifier"] for row in self.native_service.list_pipelines()}
            self.assertEqual(registered.intersection(HMSM_PIPELINE_DEFINITIONS), {"hmsm_scan_digitization"})

            self._import_hmsm_component("hmsm_midi_interpretation")
            identifier = "hmsm_digitize_and_interpret"
            config = self.native_service.get_pipeline(identifier)["config"]
            self.assertTrue(self.native_service.validate_pipeline_config(config)["valid"])
            updated = self.native_service.create_pipeline_version_from_config(identifier, {**config, "name": "My digitization"})
            self._import_hmsm_component("hmsm_midi_interpretation")
            upgraded = self._import_hmsm_component("hmsm_midi_interpretation", version="1.1.0")
            self._import_hmsm_component("hmsm_midi_reconstruction", version="1.1.0")
            version_count = PipelineVersion.query.count()
            self.native_service._seed_state = "idle"
            self.native_service.ensure_seeded()

            pipeline = self.native_service.get_pipeline(identifier)
            self.assertEqual(pipeline["active_version"], updated["active_version"])
            self.assertEqual(pipeline["name"], "My digitization")
            self.assertEqual(pipeline["config"]["steps"][1]["component_version"], config["steps"][1]["component_version"])
            self.assertEqual(PipelineVersion.query.count(), version_count)
            registered = {row["identifier"] for row in self.native_service.list_pipelines()}
            self.assertTrue(HMSM_PIPELINE_DEFINITIONS.keys() <= registered)

            updated_config = pipeline["config"]
            updated_config["steps"][1].pop("component_manifest_hash")
            updated_config["steps"][1]["component_version"] = upgraded["version"]
            upgraded_pipeline = self.native_service.create_pipeline_version_from_config(identifier, updated_config)
            self.assertNotEqual(upgraded_pipeline["active_version"], updated["active_version"])
            self.assertEqual(upgraded_pipeline["config"]["steps"][1]["component_version"], "1.1.0")

    def test_hmsm_preflight_checks_selected_file_types_and_resolves_manifest_defaults(self):
        with self.app.app_context():
            for key in ("hmsm_scan_digitizer", "hmsm_midi_interpretation", "hmsm_midi_reconstruction"):
                self._import_hmsm_component(key)
            _, scan, session = self._prepare_generic_pipeline_session("hmsm_preflight", "scan.png")
            midi = scan.with_name("source.MIDI")
            midi.write_bytes(b"synthetic MIDI")
            for identifier, valid_source, invalid_source in (
                ("hmsm_scan_digitization", scan, midi),
                ("hmsm_digitize_and_interpret", scan, midi),
                ("hmsm_midi_interpretation", midi, scan),
                ("hmsm_midi_reconstruction", midi, scan),
            ):
                with self.subTest(identifier=identifier):
                    config = self.native_service.get_pipeline(identifier)["config"]
                    request = {"pipeline_definition": config, "session_id": session.id}
                    valid = self.native_service.preflight_pipeline_constructor({**request, "local_file_paths": [str(valid_source)]}, self.user_id)
                    self.assertTrue(valid["valid"], valid["validation"])
                    self.assertTrue(valid["preflight_token"])
                    first = valid["steps"][0]["records"][0]
                    self.assertEqual(first["resolved_inputs"], {"input_file": str(valid_source.resolve())})
                    if identifier == "hmsm_midi_reconstruction":
                        self.assertEqual(first["effective_parameters"], {
                            "model_id": "generic_65_no_dynamics", "title": "Untitled reconstruction study", "roll_speed": 6, "revolution": 60,
                        })
                    if identifier == "hmsm_digitize_and_interpret":
                        self.assertEqual(valid["steps"][1]["records"][0]["resolved_inputs"], {"input_file": None})
                    invalid = self.native_service.preflight_pipeline_constructor({**request, "local_file_paths": [str(invalid_source)]}, self.user_id)
                    self.assertFalse(invalid["valid"])
                    self.assertIsNone(invalid["preflight_token"])
                    self.assertIn(invalid_source.name, invalid["validation"]["errors"][0])
                    self.assertNotIn(str(invalid_source.parent), invalid["validation"]["errors"][0])

            config = self.native_service.get_pipeline("hmsm_midi_interpretation")["config"]
            config["steps"][0]["triggers"] = {"default_behavior": "skip", "rules": [{
                "id": "only_midi", "action": "run",
                "conditions": [{"source_type": "file_fact", "field": "extension", "operator": "in", "values": [".mid", ".midi"]}],
            }]}
            mixed = self.native_service.preflight_pipeline_constructor({
                "pipeline_definition": config, "session_id": session.id, "local_file_paths": [str(scan), str(midi)],
            }, self.user_id)
            self.assertTrue(mixed["valid"], mixed["validation"])
            self.assertEqual([row["action"] for row in mixed["steps"][0]["records"]], ["skip", "run"])

    def test_hmsm_pipeline_definition_rejects_incompatible_bindings_and_parameters(self):
        with self.app.app_context():
            self._import_hmsm_component("hmsm_scan_digitizer")
            self._import_hmsm_component("hmsm_midi_interpretation")
            self._import_hmsm_component("hmsm_midi_reconstruction")
            chain = self.native_service.get_pipeline("hmsm_digitize_and_interpret")["config"]
            digitize, interpret = chain["steps"]
            binding = interpret["input_bindings"][0]
            options_binding = {**binding, "target": "options_file", "source_output": "result_file"}
            reconstruction = self.native_service.get_pipeline("hmsm_midi_reconstruction")["config"]
            for config, expected in (
                ({**chain, "steps": [interpret, digitize]}, "earlier step"),
                ({**chain, "steps": [digitize, {**interpret, "input_bindings": [{**binding, "source_output": "result_file"}]}]}, "requires .mid, .midi"),
                ({**chain, "steps": [{**digitize, "execution_profile_ref": "unknown"}, interpret]}, "requires a WebHDP Docker contract"),
                ({**chain, "steps": [{**digitize, "scope": "pipeline"}, interpret]}, "requires record scope"),
                ({**chain, "steps": [digitize, {**interpret, "parameters": {"options_json": "[]"}}]}, "must contain a JSON object"),
                ({**chain, "steps": [digitize, {**interpret, "parameters": {"options_json": "{}"},
                                                "input_bindings": [binding, options_binding]}]}, "cannot be used with input 'options_file'"),
                ({**chain, "steps": [digitize, {**interpret, "parameters": {"undeclared": 1}}]}, "is not declared"),
                ({**reconstruction, "steps": [{**reconstruction["steps"][0], "parameters": {"roll_speed": "fast"}}]}, "must be a finite number"),
            ):
                with self.subTest(expected=expected):
                    validation = self.native_service.validate_pipeline_config(config)
                    self.assertFalse(validation["valid"])
                    self.assertTrue(any(expected in message for message in validation["errors"]), validation["errors"])

    def test_hmsm_pipeline_passes_midi_and_preserves_identically_named_artifacts(self):
        identifier = "hmsm_digitize_and_interpret"
        midi_data = b"MThd synthetic MIDI from step one"

        def run_container(command, *, workdir, **_options):
            workdir = Path(workdir)
            request = json.loads((workdir / "request/request.json").read_text())
            self.assertEqual(set(request["inputs"]), {"input_file"})
            input_file = workdir / "inputs" / request["inputs"]["input_file"]
            output_dir = workdir / "outputs"
            if request["component_key"] == "hmsm_scan_digitizer":
                self.assertEqual(input_file.name, "scan.png")
                self.assertEqual(request["parameters"], {"model_id": "generic_65_no_dynamics"})
                (output_dir / "digitized.mid").write_bytes(midi_data)
                filenames = {"midi_file": "digitized.mid"}
            else:
                self.assertEqual(request["component_key"], "hmsm_midi_interpretation")
                self.assertEqual(input_file.read_bytes(), midi_data)
                filenames = {}
            filenames["runtime_manifest"] = "hmsm-source.json"
            for field in manifests[request["component_key"]]["outputs"]:
                if field.get("required"):
                    filenames.setdefault(field["name"], field["name"] + field["extensions"][0])
            for filename in filenames.values():
                if not (output_dir / filename).exists():
                    (output_dir / filename).write_bytes(b"synthetic contract output")
            (output_dir / "hmsm-source.json").write_text(request["component_key"])
            (workdir / "response/response.json").write_text(json.dumps({
                "success": True,
                "outputs": {key: f"/outputs/{filename}" for key, filename in filenames.items()},
                "artifacts": [{"name": "hmsm-source.json", "path": "/outputs/hmsm-source.json"}],
            }))
            return {"success": True, "command": command, "logs": {}}

        with self.app.app_context():
            manifests = {
                key: self._import_hmsm_component(key)["manifest"]
                for key in ("hmsm_scan_digitizer", "hmsm_midi_interpretation")
            }
            session_dir, source_file, session_row = self._prepare_generic_pipeline_session("hmsm", "scan.png")
            context = self._build_generic_execution_context(session_dir, source_file, session_row, [])
            adapter = self.native_service._adapter_registry["container_cli"]
            with patch.object(adapter, "_run_command", side_effect=run_container) as run:
                result = self.native_service.execute_registered_submission(identifier, context)
            self.assertTrue(result["success"], result["details"])
            self.assertEqual(run.call_count, 2)
            artifacts = ExecutionArtifact.query.filter_by(name="hmsm-source.json").order_by(ExecutionArtifact.id).all()
            self.assertEqual([Path(item.path).read_text() for item in artifacts], ["hmsm_scan_digitizer", "hmsm_midi_interpretation"])
            self.assertTrue(all(Path(item.path).is_relative_to(session_dir.resolve()) for item in artifacts))

    def test_failed_optimizer_does_not_render_original_as_fallback(self):
        import yaml
        from constants import MESH_OPTIMIZATION_PIPELINE_DEFINITION
        with self.app.app_context():
            session_dir, source_file, session_row = self._prepare_generic_pipeline_session("optimizer_failure")
            manifest = yaml.safe_load((Path(__file__).resolve().parents[1] / "external_code/mesh_optimizer/component.yaml").read_text())
            manifest["execution"]["profiles"][0]["sif_sha256"] = "a" * 64
            self.native_service.import_component_from_manifest(manifest)
            self.native_service.create_pipeline_version_from_config("mesh_optimization", MESH_OPTIMIZATION_PIPELINE_DEFINITION, activate=True)
            self.app.hpc_allocation_service = MagicMock()
            adapter = MagicMock()
            adapter.execute.return_value = {"success": False, "status": "failed", "error": "Baking failed", "outputs": {}}
            self.native_service._adapter_registry["hpc_link"] = adapter
            context = self._build_generic_execution_context(session_dir, source_file, session_row, MESH_OPTIMIZATION_PIPELINE_DEFINITION["steps"])
            result = self.native_service.execute_registered_submission("mesh_optimization", context)
            self.assertFalse(result["success"])
            self.assertEqual(adapter.execute.call_count, 1)
            self.assertEqual([row.status for row in StepRun.query.order_by(StepRun.id)], ["failed", "failed"])
            self.assertIn("did not produce", result["details"][0]["step_results"]["fast_renderer"]["error"])

    def test_publication_retry_does_not_reactivate_an_older_version(self):
        from uuid import uuid4
        from services.registry_lock import OperationConflict
        with self.app.app_context():
            config = self.native_service.get_pipeline("render")["config"]
            request_id = str(uuid4())
            first = self.native_service.create_pipeline_version_from_config("render", config, request_id=request_id, created_by_user_id=self.user_id)
            newer = self.native_service.create_pipeline_version_from_config("render", {**config, "name": "Newer revision"})
            count = PipelineVersion.query.count()
            retry = self.native_service.create_pipeline_version_from_config("render", config, request_id=request_id, created_by_user_id=self.user_id)
            self.assertTrue(retry["reused"])
            self.assertEqual(retry["publication_version"], first["publication_version"])
            self.assertEqual(retry["active_version"], newer["active_version"])
            self.assertEqual(PipelineVersion.query.count(), count)
            with self.assertRaises(OperationConflict):
                self.native_service.create_pipeline_version_from_config("render", {**config, "name": "Different request"}, request_id=request_id, created_by_user_id=self.user_id)

    def test_queued_run_keeps_version_and_retries_reuse_it(self):
        from uuid import uuid4
        from services.registry_lock import OperationConflict
        with self.app.app_context():
            _, _, session = self._prepare_generic_pipeline_session("queued_version")
            original = self.native_service.get_pipeline("render")
            payload = {"request_id": str(uuid4()), "session_id": session.id, "local_file_paths": ["sample.glb"], "expected_version": original["active_version"]}
            pending = self._reserve_run("render", session_id=session.id, initiated_by_user_id=self.user_id, request_payload=payload)
            updated = {**original["config"], "name": "New renderer revision"}
            self.native_service.create_pipeline_version_from_config("render", updated)
            retry = self._reserve_run("render", session_id=session.id, initiated_by_user_id=self.user_id, request_payload=payload)
            self.assertEqual(pending["run_id"], retry["run_id"])
            self.assertTrue(retry["reused"])
            with self.assertRaises(OperationConflict):
                self._reserve_run("render", session_id=session.id, initiated_by_user_id=self.user_id, request_payload={**payload, "local_file_paths": ["other.glb"]})
            with patch.object(self.native_service, "_run_native_pipeline", return_value={"success": True}) as execute:
                result = self.native_service.execute_registered_submission("render", {"db_session_id": session.id}, existing_run_public_id=pending["run_id"])
            self.assertEqual(result["pipeline_version"], original["active_version"])
            self.assertEqual(execute.call_args.args[0]["name"], original["config"]["name"])
            with patch.object(self.native_service, "_run_native_pipeline") as duplicate:
                self.native_service.execute_registered_submission("render", {"db_session_id": session.id}, existing_run_public_id=pending["run_id"])
            duplicate.assert_not_called()
            before = self.native_service.get_pipeline_run(pending["run_id"])
            self.native_service.update_run_progress(pending["run_id"], {"status_message": "Late callback"})
            self.assertEqual(self.native_service.get_pipeline_run(pending["run_id"])["result"], before["result"])

    def test_abrupt_exit_reconciles_without_replaying_remote_work(self):
        from uuid import uuid4
        with self.app.app_context():
            _, _, session = self._prepare_generic_pipeline_session("interrupted")
            payload = {"request_id": str(uuid4()), "session_id": session.id}
            queued = self._reserve_run("render", session_id=session.id, initiated_by_user_id=self.user_id, request_payload=payload)
            with patch.object(self.native_service, "_run_native_pipeline", side_effect=SystemExit("worker terminated")) as execute:
                with self.assertRaises(SystemExit):
                    self.native_service.execute_registered_submission("render", {"db_session_id": session.id}, existing_run_public_id=queued["run_id"])
                redelivery = self.native_service.execute_registered_submission("render", {"db_session_id": session.id}, existing_run_public_id=queued["run_id"])
                self.assertFalse(redelivery["success"])
                recovered = self.native_service.get_pipeline_run(queued["run_id"], self.user_id)
                self.assertEqual(recovered["status"], "failed")
                self.assertTrue(recovered["result"]["interrupted"])
                self.assertNotIn("_dispatch", recovered["request"])
                retry = self._reserve_run("render", session_id=session.id, initiated_by_user_id=self.user_id, request_payload=payload)
                self.assertTrue(retry["reused"])
                result = self.native_service.execute_registered_submission("render", {"db_session_id": session.id}, existing_run_public_id=queued["run_id"])
                self.assertFalse(result["success"])
                execute.assert_called_once()
            new = self._reserve_run("render", session_id=session.id, initiated_by_user_id=self.user_id, request_payload={"request_id": str(uuid4()), "session_id": session.id})
            self.assertNotEqual(new["run_id"], queued["run_id"])

    def test_live_worker_lock_prevents_false_interruption(self):
        from test_workflow_transition_reliability import locked_by_other_process
        from database.models import PipelineRunStatus
        with self.app.app_context():
            _, _, session = self._prepare_generic_pipeline_session("live_worker")
            queued = self._reserve_run("render", session_id=session.id, initiated_by_user_id=self.user_id, request_payload={})
            row = PipelineRun.query.filter_by(public_id=queued["run_id"]).one()
            row.status = PipelineRunStatus.RUNNING
            db.session.commit()
            with locked_by_other_process(session.hdpc_path):
                self.assertEqual(self.native_service.get_pipeline_run(row.public_id)["status"], "running")
            self.assertEqual(self.native_service.get_pipeline_run(row.public_id)["status"], "failed")

    def test_interruption_before_dispatch_can_be_recovered(self):
        with self.app.app_context():
            _, _, session = self._prepare_generic_pipeline_session("interrupted_dispatch")
            queued = self._reserve_run("render", session_id=session.id, initiated_by_user_id=self.user_id, request_payload={})
            with patch("services.pipeline_run_recovery.owner_alive", return_value=False):
                self.assertEqual(self.native_service.get_pipeline_run(queued["run_id"])["status"], "failed")

    def test_unknown_task_monitor_does_not_fail_queued_run(self):
        with self.app.app_context():
            _, _, session = self._prepare_generic_pipeline_session("unknown_dispatch")
            queued = self._reserve_run("render", session_id=session.id, initiated_by_user_id=self.user_id, request_payload={})
            self.assertEqual(self.native_service.get_pipeline_run(queued["run_id"])["status"], "pending")

    def test_queued_run_reserves_session_against_synchronous_execution(self):
        from services.pipeline_execution_lock import PipelineAlreadyRunning
        from services.submission_pipeline_service import execute_submission_pipeline
        with self.app.app_context():
            _, _, session = self._prepare_generic_pipeline_session('reserved_session')
            queued = self._reserve_run('render', session_id=session.id, initiated_by_user_id=self.user_id, request_payload={})
            with patch.object(self.native_service, '_run_native_pipeline') as execute:
                with self.assertRaises(PipelineAlreadyRunning):
                    self.native_service.execute_registered_submission('render', {'db_session_id': session.id})
                with self.assertRaises(PipelineAlreadyRunning):
                    execute_submission_pipeline('render', [], session.id)
                execute.assert_not_called()
            self.assertEqual(self.native_service.get_pipeline_run(queued['run_id'])['status'], 'pending')

    def test_duplicate_request_reconnects_while_worker_holds_the_session_lock(self):
        from uuid import uuid4
        from test_workflow_transition_reliability import locked_by_other_process
        with self.app.app_context():
            _, _, session = self._prepare_generic_pipeline_session('active_retry')
            payload = {'request_id': str(uuid4())}
            queued = self._reserve_run('render', session_id=session.id, initiated_by_user_id=self.user_id, request_payload=payload)
            with locked_by_other_process(session.hdpc_path):
                reused = self._reserve_run('render', session_id=session.id, initiated_by_user_id=self.user_id, request_payload=payload)
                self.assertTrue(reused['reused'])
                self.assertEqual(reused['run_id'], queued['run_id'])

    def test_uncertain_dispatch_cancels_unstarted_run_and_ignores_late_delivery(self):
        from services.pipeline_run_recovery import resolve_dispatch_failure
        from routes.pipeline_v2_routes import _enqueue_submission_pipeline_task
        import sys
        from types import SimpleNamespace
        with self.app.app_context():
            _, _, session = self._prepare_generic_pipeline_session('uncertain_dispatch')
            queued = self._reserve_run('render', session_id=session.id, initiated_by_user_id=self.user_id, request_payload={})
            def accepted_but_response_lost(**kwargs):
                row = PipelineRun.query.filter_by(public_id=queued['run_id']).one()
                self.assertEqual(json.loads(row.request_json)['_dispatch']['task_id'], kwargs['task_id'])
                raise ConnectionError('response lost')
            task = SimpleNamespace(apply_async=accepted_but_response_lost)
            with patch.dict(sys.modules, {'tasks': SimpleNamespace(execute_submission_pipeline_task=task)}):
                with self.assertRaises(ConnectionError):
                    _enqueue_submission_pipeline_task(None, 'render', [], session.id, True, False, [], [], queued['run_id'])
            resolve_dispatch_failure(queued['run_id'])
            with patch.object(self.native_service, '_run_native_pipeline') as execute:
                result = self.native_service.execute_registered_submission('render', {'db_session_id': session.id}, existing_run_public_id=queued['run_id'])
                self.assertFalse(result['success'])
                execute.assert_not_called()

    def test_dispatch_error_preserves_running_worker_and_completed_result(self):
        from services.pipeline_run_recovery import resolve_dispatch_failure
        from database.models import PipelineRunStatus
        from test_workflow_transition_reliability import locked_by_other_process
        with self.app.app_context():
            _, _, session = self._prepare_generic_pipeline_session('accepted_dispatch')
            queued = self._reserve_run('render', session_id=session.id, initiated_by_user_id=self.user_id, request_payload={})
            run = PipelineRun.query.filter_by(public_id=queued['run_id']).one()
            run.status = PipelineRunStatus.RUNNING
            db.session.commit()
            with locked_by_other_process(session.hdpc_path):
                resolve_dispatch_failure(run.public_id)
                self.assertEqual(run.status, PipelineRunStatus.RUNNING)
            run.status = PipelineRunStatus.COMPLETED
            run.result_json = json.dumps({'success': True, 'saved': 'result'})
            db.session.commit()
            resolve_dispatch_failure(run.public_id)
            self.assertEqual(run.status, PipelineRunStatus.COMPLETED)
            self.assertEqual(json.loads(run.result_json)['saved'], 'result')

    def test_retired_hostname_preparation_expires_and_frees_session(self):
        from datetime import datetime, timedelta
        from database.models import PipelineRunStatus
        with self.app.app_context():
            _, _, session = self._prepare_generic_pipeline_session('retired_hostname')
            queued = self._reserve_run('render', session_id=session.id, initiated_by_user_id=self.user_id, request_payload={})
            run = PipelineRun.query.filter_by(public_id=queued['run_id']).one()
            payload = json.loads(run.request_json)
            payload['_dispatch']['owner']['host'] = 'previous-container'
            run.request_json = json.dumps(payload)
            run.started_at = datetime.utcnow() - timedelta(minutes=3)
            db.session.commit()
            self.assertEqual(self.native_service.get_pipeline_run(run.public_id)['status'], 'failed')
            self.assertEqual(run.status, PipelineRunStatus.FAILED)
            self.assertEqual(session.status, 'failed')
            replacement = self._reserve_run('render', session_id=session.id, initiated_by_user_id=self.user_id, request_payload={})
            self.assertNotEqual(replacement['run_id'], run.public_id)

    def test_cancelled_pipeline_reservation_is_not_replayed(self):
        from services.pipeline_run_recovery import cancel_pending_run
        with self.app.app_context():
            _, _, session = self._prepare_generic_pipeline_session('cancelled_reservation')
            queued = self._reserve_run('render', session_id=session.id, initiated_by_user_id=self.user_id, request_payload={})
            run = PipelineRun.query.filter_by(public_id=queued['run_id']).one()
            cancel_pending_run(run)
            self.assertTrue(self.native_service.get_pipeline_run(run.public_id)['result']['cancelled'])
            with patch.object(self.native_service, '_run_native_pipeline') as execute:
                result = self.native_service.execute_registered_submission('render', {'db_session_id': session.id}, existing_run_public_id=run.public_id)
                self.assertFalse(result['success'])
                execute.assert_not_called()

    def test_preflight_token_binds_definition_user_and_file_selection(self):
        from services.registry_lock import OperationConflict
        with self.app.app_context():
            directory, source, session = self._prepare_generic_pipeline_session("preflight_contract")
            config = {"identifier": "checked", "name": "Checked", "version": "1.0.0", "steps": [{"id": "classify", "name": "Classify", "component_ref": "input_file_classification"}]}
            saved = self.native_service.create_pipeline_version_from_config("checked", config)
            request = {"pipeline_definition": saved["config"], "session_id": session.id, "local_file_paths": [str(source)]}
            checked = self.native_service.preflight_pipeline_constructor(request, self.user_id)
            payload = {"preflight_token": checked["preflight_token"], "session_id": session.id, "local_file_paths": [str(source)]}
            self.native_service._verify_preflight(payload, saved["config"], self.user_id)
            for changed, user in [({**payload, "local_file_paths": ["different.glb"]}, self.user_id), (payload, self.other_user_id), ({**payload, "preflight_token": "invalid"}, self.user_id)]:
                with self.assertRaises(OperationConflict):
                    self.native_service._verify_preflight(changed, saved["config"], user)
            with self.assertRaises(OperationConflict):
                self.native_service._verify_preflight(payload, {**saved["config"], "name": "Changed"}, self.user_id)

    def test_preflight_rejects_changed_metadata_settings(self):
        from database.models import UserMetadata
        from services.registry_lock import OperationConflict
        with self.app.app_context():
            directory, source, session = self._prepare_generic_pipeline_session("preflight_metadata")
            saved = self.native_service.create_pipeline_version_from_config("metadata_checked", {"identifier": "metadata_checked", "name": "Metadata checked", "version": "1.0.0", "steps": [{"id": "classify", "name": "Classify", "component_ref": "input_file_classification"}]})
            checked = self.native_service.preflight_pipeline_constructor({"pipeline_definition": saved["config"], "session_id": session.id, "local_file_paths": [str(source)]}, self.user_id)
            db.session.add(UserMetadata(session_id=session.id, field_name="zenodo_metadata_draft", field_value='{"title":"Changed title"}'))
            db.session.commit()
            with self.assertRaises(OperationConflict):
                self._reserve_run("metadata_checked", session_id=session.id, initiated_by_user_id=self.user_id, request_payload={"preflight_token": checked["preflight_token"], "session_id": session.id, "local_file_paths": [str(source)]})

    def test_publication_rejects_unpinned_container_artifacts(self):
        with self.app.app_context():
            for runtime, image in [("docker", "example/component:latest"), ("singularity", "/work/component.sif")]:
                key = f"unpinned_{runtime}"
                self.native_service.import_component_from_manifest({"metadata": {"name": key, "version": "1.0.0"}, "execution": {"profiles": [{"id": "container", "adapter": "container_cli", "runtime": runtime, "image": image, "entrypoint": ["run"]}]}})
                config = {"name": key, "steps": [{"id": "process", "name": "Process", "component_ref": key, "execution_profile_ref": "container"}]}
                with self.assertRaises(ValidationError) as caught:
                    self.native_service.create_pipeline_version_from_config(key, config)
                self.assertIn("HDP Components", str(caught.exception.details))

    def test_run_details_require_access_to_its_session(self):
        with self.app.app_context():
            _, _, session = self._prepare_generic_pipeline_session("private_run")
            queued = self._reserve_run("render", session_id=session.id, initiated_by_user_id=self.user_id, request_payload={})
            self.assertEqual(self.native_service.get_pipeline_run(queued["run_id"], self.user_id)["run_id"], queued["run_id"])
            with self.assertRaises(ResourceNotFoundError):
                self.native_service.get_pipeline_run(queued["run_id"], self.other_user_id)

    def test_pipeline_component_version_does_not_follow_new_imports(self):
        with self.app.app_context():
            manifest = {"metadata": {"name": "stable_component", "version": "1.0.0"}, "execution": {"profiles": [{"id": "local", "adapter": "local_cli", "entrypoint": ["old-command"]}]},
                        "inputs": [{"name": "input_file", "type": "file_path"}],
                        "ui": {"playground": {"fields": {"input_file": {"accept_extensions": [".glb"]}}}}}
            self.native_service.import_component_from_manifest(manifest)
            saved = self.native_service.create_pipeline_version_from_config("stable", {"identifier": "stable", "name": "Stable", "version": "1.0.0", "steps": [{"id": "stable", "name": "Stable", "component_ref": "stable_component", "execution_profile_ref": "local"}]})
            manifest["metadata"]["version"] = "2.0.0"
            manifest["execution"]["profiles"][0]["entrypoint"] = ["new-command"]
            manifest["ui"]["playground"]["fields"]["input_file"]["accept_extensions"] = [".obj"]
            self.native_service.import_component_from_manifest(manifest)
            step = saved["config"]["steps"][0]
            selected = self.native_service._step_component_version(step)
            self.assertEqual(selected.version, "1.0.0")
            self.assertIn("old-command", selected.manifest_json)
            self.assertEqual(self.native_service.get_pipeline("stable")["components"][0]["version"], "1.0.0")
            self.assertEqual(self.native_service.get_pipeline("stable")["guidance"]["source_extensions"], [".glb"])

    def test_repeated_original_version_chooses_next_unused_version(self):
        with self.app.app_context():
            original = self.native_service.get_pipeline("render")["config"]
            versions = []
            for count in range(3):
                config = {**original, "name": f"Renderer revision {count}"}
                saved = self.native_service.create_pipeline_version_from_config("render", config)
                versions.append(saved["active_version"])
                self.assertEqual(saved["active_version"], saved["config"]["version"])
            self.assertEqual(len(set(versions)), 3)

    def test_enabled_input_binding_rejects_disabled_source(self):
        config = {
            "identifier": "disabled_source", "name": "Disabled source", "version": "1.0.0",
            "steps": [
                {"id": "convert", "component_ref": "any_to_usdz", "name": "Convert", "enabled": False},
                {"id": "render", "component_ref": "fast_renderer", "name": "Render", "scope": "batch",
                 "input_bindings": [{"kind": "input", "target": "input_files", "type": "artifact_file", "source_step": "convert", "source_output": "output_path"}]},
            ],
        }
        with self.app.app_context():
            result = self.native_service.validate_pipeline_config(config)
        self.assertFalse(result["valid"])
        self.assertTrue(any("disabled source step 'convert'" in message for message in result["errors"]))

    def test_enabled_trigger_rejects_disabled_classifier(self):
        config = {
            "identifier": "disabled_classifier", "name": "Disabled classifier", "version": "1.0.0",
            "steps": [
                {"id": "classify", "component_ref": "input_file_classification", "name": "Classify", "enabled": False},
                {"id": "render", "component_ref": "fast_renderer", "name": "Render", "scope": "batch",
                 "triggers": {"rules": [{"id": "mesh", "action": "run", "conditions": [
                     {"source_type": "classifier_output", "source_step": "classify", "source_output": "classification_json", "field": "$.asset.model_kind", "operator": "eq", "value": "mesh"}
                 ]}]}},
            ],
        }
        with self.app.app_context():
            result = self.native_service.validate_pipeline_config(config)
        self.assertFalse(result["valid"])
        self.assertTrue(any("disabled classifier step 'classify'" in message for message in result["errors"]))

    def test_pipeline_version_row_and_config_version_stay_aligned_when_version_is_incremented(self):
        updated = {
            **PIPELINE_DEFINITION,
            "steps": [
                {**step, "enabled": False} if step["id"] == "any_to_usdz" else dict(step)
                for step in PIPELINE_DEFINITION["steps"]
            ],
        }

        with self.app.app_context():
            current = self.native_service.get_pipeline("render")
            major, minor, patch = [int(part) for part in current["active_version"].split(".")]
            expected_version = f"{major}.{minor}.{patch + 1}"
            pipeline = self.native_service.create_pipeline_version_from_config(
                "render",
                updated,
                activate=True,
                created_by_user_id=self.user_id,
            )
            version_count = PipelineVersion.query.count()
            repeated = self.native_service.create_pipeline_version_from_config(
                "render",
                updated,
                activate=True,
                created_by_user_id=self.user_id,
            )
            repeated_version_count = PipelineVersion.query.count()

        self.assertEqual(pipeline["active_version"], pipeline["config"]["version"])
        self.assertEqual(pipeline["active_version"], expected_version)
        self.assertEqual(repeated["active_version"], expected_version)
        self.assertEqual(repeated["config"]["version"], expected_version)
        self.assertEqual(repeated_version_count, version_count)

    def test_output_actions_map_json_outputs_into_zenodo_metadata(self):
        json_output_path = Path(self.temp_dir) / "metadata.json"
        json_output_path.write_text(
            '{"mapped":{"title":"Mapped title","keywords":["scan","mesh"]}}',
            encoding="utf-8",
        )
        record_context = {
            "file_zenodo_metadata": {"description": "Original description"},
            "record_status": {"warnings": []},
            "step_outputs": {"extract_metadata": {"metadata_json": str(json_output_path)}},
        }
        binding = {
            "type": "artifact_json_value",
            "source_step": "extract_metadata",
            "source_output": "metadata_json",
            "selector": "$.mapped.keywords",
        }
        step = {
            "id": "extract_metadata",
            "output_actions": [
                {
                    "action_type": "zenodo_metadata_field",
                    "source_output": "metadata_json",
                    "selector": "$.mapped.title",
                    "target_field": "title",
                },
                {
                    "action_type": "zenodo_metadata_field",
                    "source_output": "metadata_json",
                    "selector": "$.mapped.keywords",
                    "target_field": "keywords",
                    "transform": "join",
                    "config": {"separator": " | "},
                },
            ],
        }
        result = {"outputs": {"metadata_json": str(json_output_path)}}

        with self.app.app_context():
            resolved_keywords = self.native_service._resolve_binding_value(binding, record_context, {})
            applied_actions = self.native_service._apply_output_actions(step, record_context, result)

        self.assertEqual(resolved_keywords, ["scan", "mesh"])
        self.assertEqual(record_context["file_zenodo_metadata"]["title"], "Mapped title")
        self.assertEqual(record_context["file_zenodo_metadata"]["keywords"], "scan | mesh")
        self.assertEqual(len(applied_actions), 2)

    def test_output_actions_map_3d_analysis_outputs_into_edm_metadata(self):
        json_output_path = Path(self.temp_dir) / "model_profile.json"
        json_output_path.write_text(
            '{"facts":{"model_type":"point_cloud","point_count":12345,"polygon_count":0},"qa":{"recommendation":"pass"}}',
            encoding="utf-8",
        )
        record_context = {
            "file_zenodo_metadata": {},
            "record_status": {"warnings": []},
            "step_outputs": {},
        }
        step = {
            "id": "profile_model",
            "output_actions": [
                {
                    "action_type": "edm_metadata_field",
                    "source_output": "analysis_report",
                    "selector": "$.facts.model_type",
                    "target_field": "model_type",
                },
                {
                    "action_type": "edm_metadata_field",
                    "source_output": "analysis_report",
                    "selector": "$.facts.point_count",
                    "target_field": "point_count",
                },
                {
                    "action_type": "record_status_field",
                    "source_output": "analysis_report",
                    "selector": "$.qa.recommendation",
                    "target_field": "details.qa_recommendation",
                },
            ],
        }
        result = {"outputs": {"analysis_report": str(json_output_path)}}

        with self.app.app_context():
            applied_actions = self.native_service._apply_output_actions(step, record_context, result)

        self.assertEqual(record_context["file_zenodo_metadata"]["model_type"], "point_cloud")
        self.assertEqual(record_context["file_zenodo_metadata"]["point_count"], 12345)
        self.assertEqual(record_context["record_status"]["details"]["qa_recommendation"], "pass")
        self.assertEqual(
            [action["action_type"] for action in applied_actions],
            ["edm_metadata_field", "edm_metadata_field", "record_status_field"],
        )

    def test_output_actions_support_record_targets_nested_fields_and_deduping(self):
        json_output_path = Path(self.temp_dir) / "metadata_extended.json"
        json_output_path.write_text(
            '{"mapped":{"keywords":["scan","mesh","scan"],"quality":"  Preview  "}}',
            encoding="utf-8",
        )
        record_context = {
            "file_zenodo_metadata": {"keywords": ["existing"]},
            "record_status": {"warnings": ["Existing warning"]},
            "step_outputs": {},
        }
        step = {
            "id": "extract_metadata",
            "output_actions": [
                {
                    "action_type": "record_metadata_field",
                    "source_output": "metadata_json",
                    "selector": "$.mapped.keywords",
                    "target_field": "keywords",
                    "transform": "dedupe_list",
                    "overwrite_policy": "append_unique",
                },
                {
                    "action_type": "record_status_field",
                    "source_output": "metadata_json",
                    "selector": "$.mapped.quality",
                    "target_field": "details.quality_label",
                    "transform": "trim",
                },
                {
                    "action_type": "record_warning",
                    "source_output": "warning_text",
                    "transform": "trim",
                    "overwrite_policy": "append_unique",
                },
            ],
        }
        result = {
            "outputs": {
                "metadata_json": str(json_output_path),
                "warning_text": "  Missing normal map  ",
            }
        }

        with self.app.app_context():
            applied_actions = self.native_service._apply_output_actions(step, record_context, result)

        self.assertEqual(record_context["file_zenodo_metadata"]["keywords"], ["existing", "scan", "mesh"])
        self.assertEqual(record_context["record_status"]["details"]["quality_label"], "Preview")
        self.assertEqual(
            record_context["record_status"]["warnings"],
            ["Existing warning", "Missing normal map"],
        )
        self.assertEqual(len(applied_actions), 3)

    def test_output_actions_support_collection_target_paths(self):
        json_output_path = Path(self.temp_dir) / "metadata_collection.json"
        json_output_path.write_text(
            '{"mapped":{"creators":["Alice","Bob"],"communities":["3d-big-data-space"]}}',
            encoding="utf-8",
        )
        record_context = {
            "file_zenodo_metadata": {},
            "record_status": {"warnings": []},
            "step_outputs": {},
        }
        step = {
            "id": "extract_metadata",
            "output_actions": [
                {
                    "action_type": "zenodo_metadata_field",
                    "source_output": "metadata_json",
                    "selector": "$.mapped.creators",
                    "target_field": "creators[].name",
                    "overwrite_policy": "overwrite",
                },
                {
                    "action_type": "zenodo_metadata_field",
                    "source_output": "metadata_json",
                    "selector": "$.mapped.communities",
                    "target_field": "communities[].identifier",
                    "overwrite_policy": "overwrite",
                },
            ],
        }
        result = {
            "outputs": {
                "metadata_json": str(json_output_path),
            }
        }

        with self.app.app_context():
            self.native_service._apply_output_actions(step, record_context, result)

        self.assertEqual(
            record_context["file_zenodo_metadata"]["creators"],
            [{"name": "Alice"}, {"name": "Bob"}],
        )
        self.assertEqual(
            record_context["file_zenodo_metadata"]["communities"],
            [{"identifier": "3d-big-data-space"}],
        )

    def test_pipeline_validation_accepts_expanded_output_actions_without_runtime_warnings(self):
        config = {
            "identifier": "extended_actions",
            "name": "Extended Actions",
            "version": "1.0.0",
            "steps": [
                {
                    "id": "extract_metadata",
                    "name": "Extract Metadata",
                    "component_ref": "lod_generation",
                    "execution_profile_ref": "builtin_default",
                    "scope": "record",
                    "output_actions": [
                        {
                            "action_type": "record_metadata_field",
                            "source_output": "metadata_json",
                            "selector": "$.mapped.keywords",
                            "target_field": "keywords",
                            "transform": "dedupe_list",
                            "overwrite_policy": "append_unique",
                        },
                        {
                            "action_type": "record_status_field",
                            "source_output": "metadata_json",
                            "selector": "$.mapped.quality",
                            "target_field": "details.quality_label",
                            "transform": "trim",
                        },
                        {
                            "action_type": "record_warning",
                            "source_output": "warning_text",
                            "transform": "coerce_string",
                        },
                    ],
                }
            ],
        }

        with self.app.app_context():
            validation = self.native_service.validate_pipeline_config(config)

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["warnings"], [])

    def test_constructor_support_exposes_edm_metadata_targets(self):
        with self.app.app_context():
            support = self.native_service.get_pipeline_constructor_support()

        edm_paths = {entry["path"]: entry for entry in support["edm_metadata_target_paths"]}
        combined_paths = {entry["path"]: entry for entry in support["metadata_target_paths"]}
        self.assertEqual(edm_paths["point_count"]["action_type"], "edm_metadata_field")
        self.assertEqual(edm_paths["model_type"]["action_type"], "edm_metadata_field")
        self.assertEqual(combined_paths["title"]["action_type"], "zenodo_metadata_field")
        self.assertEqual(combined_paths["point_count"]["action_type"], "edm_metadata_field")

    def test_pipeline_validation_rejects_non_classifier_trigger_sources(self):
        config = {
            "identifier": "invalid_trigger_source",
            "name": "Invalid Trigger Source",
            "version": "1.0.0",
            "steps": [
                {
                    "id": "convert",
                    "name": "Convert",
                    "component_ref": "any_to_usdz",
                    "execution_profile_ref": "builtin_default",
                    "scope": "record",
                },
                {
                    "id": "render",
                    "name": "Render",
                    "component_ref": "fast_renderer",
                    "execution_profile_ref": "builtin_default",
                    "scope": "batch",
                    "triggers": {
                        "default_behavior": "run",
                        "rules": [
                            {
                                "id": "bad_rule",
                                "conditions": [
                                    {
                                        "source_type": "classifier_output",
                                        "source_step": "convert",
                                        "source_output": "output_path",
                                        "field": "$.asset.model_kind",
                                        "operator": "eq",
                                        "value": "mesh",
                                    }
                                ],
                                "action": "run",
                                "parameter_overrides": {"resolution": 1024},
                            }
                        ],
                    },
                },
            ],
        }

        with self.app.app_context():
            validation = self.native_service.validate_pipeline_config(config)

        self.assertFalse(validation["valid"])
        self.assertTrue(any("input_file_classification" in message for message in validation["errors"]))

    def test_constructor_preflight_groups_fast_renderer_records_into_trigger_buckets(self):
        session_dir = Path(self.temp_dir) / "constructor_preflight_session"
        uploads_dir = session_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        mesh_file = uploads_dir / "mesh.glb"
        mesh_file.write_text("glb-data", encoding="utf-8")
        point_cloud_file = uploads_dir / "cloud.ply"
        point_cloud_file.write_text(
            "\n".join(
                [
                    "ply",
                    "format ascii 1.0",
                    "element vertex 2",
                    "property float x",
                    "property float y",
                    "property float z",
                    "end_header",
                    "0 0 0",
                    "1 1 1",
                ]
            ),
            encoding="utf-8",
        )

        with self.app.app_context():
            session_row = DBSession(
                user_id=self.user_id,
                session_dir=str(session_dir),
                hdpc_path=str(session_dir / "session.hdpc"),
                status="ready",
            )
            db.session.add(session_row)
            db.session.commit()

            payload = {
                "pipeline_definition": {
                    "identifier": "constructor_preflight",
                    "name": "Constructor Preflight",
                    "version": "1.0.0",
                    "steps": [
                        {
                            "id": "classify",
                            "name": "Classify",
                            "component_ref": "input_file_classification",
                            "execution_profile_ref": "builtin_default",
                            "scope": "record",
                        },
                        {
                            "id": "render",
                            "name": "Render",
                            "component_ref": "fast_renderer",
                            "execution_profile_ref": "builtin_default",
                            "scope": "batch",
                            "parameters": {"resolution": 512},
                            "triggers": {
                                "default_behavior": "run",
                                "rules": [
                                    {
                                        "id": "point_cloud_rule",
                                        "conditions": [
                                            {
                                                "source_type": "classifier_output",
                                                "source_step": "classify",
                                                "source_output": "classification_json",
                                                "field": "$.asset.model_kind",
                                                "operator": "eq",
                                                "value": "point_cloud",
                                            }
                                        ],
                                        "action": "run",
                                        "parameter_overrides": {"resolution": 2048},
                                    }
                                ],
                            },
                        },
                    ],
                },
                "session_id": session_row.id,
                "local_file_paths": [str(mesh_file), str(point_cloud_file)],
            }

            preflight = self.native_service.preflight_pipeline_constructor(payload, user_id=self.user_id)

        render_step = next(step for step in preflight["steps"] if step["step_id"] == "render")
        self.assertEqual(len(render_step["buckets"]), 2)

    def test_constructor_preflight_merges_fast_renderer_batch_records_when_input_files_default_is_used(self):
        session_dir = Path(self.temp_dir) / "constructor_preflight_merged_batch"
        first_dir = session_dir / "uploads" / "set_a"
        second_dir = session_dir / "uploads" / "set_b"
        first_dir.mkdir(parents=True, exist_ok=True)
        second_dir.mkdir(parents=True, exist_ok=True)
        first_file = first_dir / "mesh_a.glb"
        second_file = second_dir / "mesh_b.glb"
        first_file.write_text("glb-a", encoding="utf-8")
        second_file.write_text("glb-b", encoding="utf-8")

        with self.app.app_context():
            session_row = DBSession(
                user_id=self.user_id,
                session_dir=str(session_dir),
                hdpc_path=str(session_dir / "session.hdpc"),
                status="ready",
            )
            db.session.add(session_row)
            db.session.commit()

            payload = {
                "pipeline_definition": {
                    "identifier": "constructor_preflight_merged_batch",
                    "name": "Constructor Preflight Merged Batch",
                    "version": "1.0.0",
                    "steps": [
                        {
                            "id": "render",
                            "name": "Render",
                            "component_ref": "fast_renderer",
                            "execution_profile_ref": "builtin_default",
                            "scope": "batch",
                            "parameters": {"formats": [".glb"]},
                        },
                    ],
                },
                "session_id": session_row.id,
                "local_file_paths": [str(first_file), str(second_file)],
            }

            preflight = self.native_service.preflight_pipeline_constructor(payload, user_id=self.user_id)

        render_step = next(step for step in preflight["steps"] if step["step_id"] == "render")
        self.assertEqual(len(render_step["buckets"]), 1)
        self.assertEqual(
            set(render_step["buckets"][0]["record_paths"]),
            {str(first_file.resolve()), str(second_file.resolve())},
        )
        for record in render_step["records"]:
            self.assertEqual(record["resolved_inputs"]["input_files"], [record["record_path"]])
            self.assertNotIn("input-dir", record["resolved_inputs"])

    def test_constructor_preflight_rejects_access_to_another_users_session(self):
        session_dir = Path(self.temp_dir) / "foreign_session"
        uploads_dir = session_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        source_file = uploads_dir / "model.glb"
        source_file.write_text("glb-data", encoding="utf-8")

        with self.app.app_context():
            session_row = DBSession(
                user_id=self.user_id,
                session_dir=str(session_dir),
                hdpc_path=str(session_dir / "session.hdpc"),
                status="ready",
            )
            db.session.add(session_row)
            db.session.commit()

            payload = {
                "pipeline_definition": {
                    "identifier": "constructor_preflight",
                    "name": "Constructor Preflight",
                    "version": "1.0.0",
                    "steps": [],
                },
                "session_id": session_row.id,
                "local_file_paths": [str(source_file)],
            }

            with self.assertRaises(ResourceNotFoundError):
                self.native_service.preflight_pipeline_constructor(payload, user_id=self.other_user_id)

    def test_constructor_preflight_rejects_paths_outside_session_scope(self):
        session_dir = Path(self.temp_dir) / "scoped_session"
        uploads_dir = session_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        outside_dir = Path(self.temp_dir) / "outside"
        outside_dir.mkdir(parents=True, exist_ok=True)
        outside_file = outside_dir / "model.glb"
        outside_file.write_text("glb-data", encoding="utf-8")

        with self.app.app_context():
            session_row = DBSession(
                user_id=self.user_id,
                session_dir=str(session_dir),
                hdpc_path=str(session_dir / "session.hdpc"),
                status="ready",
            )
            db.session.add(session_row)
            db.session.commit()

            payload = {
                "pipeline_definition": {
                    "identifier": "constructor_preflight",
                    "name": "Constructor Preflight",
                    "version": "1.0.0",
                    "steps": [],
                },
                "session_id": session_row.id,
                "local_file_paths": [str(outside_file)],
            }

            with self.assertRaises(ValidationError):
                self.native_service.preflight_pipeline_constructor(payload, user_id=self.user_id)

    def test_pipeline_validation_rejects_duplicate_step_ids(self):
        config = {
            "identifier": "duplicate_steps",
            "name": "Duplicate Steps",
            "version": "1.0.0",
            "steps": [
                {
                    "id": "render",
                    "name": "Render A",
                    "component_ref": "fast_renderer",
                    "execution_profile_ref": "builtin_default",
                    "scope": "batch",
                },
                {
                    "id": "render",
                    "name": "Render B",
                    "component_ref": "fast_renderer",
                    "execution_profile_ref": "builtin_default",
                    "scope": "batch",
                },
            ],
        }

        with self.app.app_context():
            validation = self.native_service.validate_pipeline_config(config)

        self.assertFalse(validation["valid"])
        self.assertTrue(any("Duplicate step id detected" in message for message in validation["errors"]))

    def test_pipeline_validation_rejects_batch_scope_without_batch_compatible_inputs(self):
        config = {
            "identifier": "invalid_batch_scope",
            "name": "Invalid Batch Scope",
            "version": "1.0.0",
            "steps": [
                {
                    "id": "convert",
                    "name": "Convert",
                    "component_ref": "any_to_usdz",
                    "execution_profile_ref": "builtin_default",
                    "scope": "batch",
                }
            ],
        }

        with self.app.app_context():
            validation = self.native_service.validate_pipeline_config(config)

        self.assertFalse(validation["valid"])
        self.assertTrue(any("batch-compatible 'file_list' or 'dir_path' input" in message for message in validation["errors"]))

    def test_pipeline_validation_warns_when_batch_dir_path_is_implicitly_derived(self):
        component_dir = Path(self.temp_dir) / "batch_directory_component"
        self._write_batch_directory_component(component_dir)

        with self.app.app_context():
            imported = self.native_service.import_component_from_path(str(component_dir))
            validation = self.native_service.validate_pipeline_config(
                {
                    "identifier": "batch_directory_warning",
                    "name": "Batch Directory Warning",
                    "version": "1.0.0",
                    "steps": [
                        {
                            "id": "consume",
                            "name": "Consume",
                            "component_ref": imported["key"],
                            "execution_profile_ref": "local_default",
                            "scope": "batch",
                        }
                    ],
                }
            )

        self.assertTrue(validation["valid"])
        self.assertTrue(
            any("leaves directory input 'input_dir' without an explicit binding" in message for message in validation["warnings"])
        )

    @patch("subprocess.run")
    def test_imported_local_cli_component_executes_through_native_pipeline_and_persists_artifacts(self, mock_run):
        component_dir = Path(self.temp_dir) / "local_cli_component"
        component_dir.mkdir(parents=True, exist_ok=True)
        (component_dir / "component.yaml").write_text(
            "\n".join(
                [
                    "metadata:",
                    "  name: local_cli_component",
                    '  version: "0.1.0"',
                    "  description: Local CLI integration component",
                    "inputs:",
                    "  - name: input_file",
                    "    type: file_path",
                    "outputs:",
                    "  - name: rendered_image",
                    "    type: file_path",
                    "execution:",
                    "  profiles:",
                    "    - id: local_default",
                    "      adapter: local_cli",
                    "      entrypoint: [\"local-tool\", \"run\"]",
                    "      working_directory: \".\"",
                    "      output_collection:",
                    "        - name: rendered_image",
                    "          path: generated/render.png",
                    "          artifact_kind: file",
                    "        - name: metadata_json",
                    "          path: generated/metadata.json",
                    "          artifact_kind: file",
                    "compatibility: {}",
                ]
            ),
            encoding="utf-8",
        )

        def local_side_effect(*args, **kwargs):
            cwd = Path(kwargs["cwd"])
            generated_dir = cwd / "generated"
            generated_dir.mkdir(parents=True, exist_ok=True)
            (generated_dir / "render.png").write_text("png", encoding="utf-8")
            (generated_dir / "metadata.json").write_text('{"quality":"preview"}', encoding="utf-8")
            return subprocess.CompletedProcess(args=kwargs.get("args") or args[0], returncode=0, stdout="ok", stderr="")

        mock_run.side_effect = local_side_effect

        with self.app.app_context():
            session_dir, source_file, session_row = self._prepare_generic_pipeline_session("session_local_cli")
            imported = self.native_service.import_component_from_path(str(component_dir))
            pipeline_config = {
                "identifier": "generic_pipeline",
                "name": "Generic Pipeline",
                "version": "1.0.0",
                "steps": [
                    {
                        "id": "local_step",
                        "name": "Local Step",
                        "component_ref": imported["key"],
                        "execution_profile_ref": "local_default",
                        "scope": "record",
                    }
                ],
            }
            self.native_service.create_pipeline_version_from_config(
                "generic_pipeline",
                pipeline_config,
                activate=True,
                created_by_user_id=self.user_id,
            )
            execution_context = self._build_generic_execution_context(session_dir, source_file, session_row, pipeline_config["steps"])

            result = self.native_service.execute_registered_submission("generic_pipeline", execution_context)
            pipeline_runs = PipelineRun.query.all()
            self.assertEqual(json.loads(pipeline_runs[0].result_json)["effective_steps"], result["effective_steps"])
            self.assertEqual(
                {step["id"]: step["enabled"] for step in result["effective_steps"]},
                {step["id"]: step.get("enabled", True) for step in execution_context["steps_map"].values()},
            )
            step_runs = StepRun.query.all()
            artifacts = ExecutionArtifact.query.order_by(ExecutionArtifact.name.asc()).all()

        self.assertTrue(result["success"])
        self.assertEqual(result["summary"]["successful_count"], 1)
        self.assertEqual(result["details"][0]["step_results"]["local_step"]["success"], True)
        self.assertEqual(len(pipeline_runs), 1)
        self.assertEqual(len(step_runs), 1)
        self.assertEqual([artifact.name for artifact in artifacts], ["metadata_json", "rendered_image"])

    @patch("subprocess.run")
    def test_imported_legacy_python_component_executes_through_native_pipeline(self, mock_run):
        component_dir = Path(self.temp_dir) / "legacy_python_component"
        component_dir.mkdir(parents=True, exist_ok=True)
        (component_dir / "main.py").write_text("print('legacy')\n", encoding="utf-8")
        (component_dir / "component.yaml").write_text(
            "\n".join(
                [
                    "metadata:",
                    "  name: legacy_python_component",
                    '  version: "0.1.0"',
                    "  description: Legacy python integration component",
                    "inputs:",
                    "  - name: input_file",
                    "    type: file_path",
                    "outputs:",
                    "  - name: report_file",
                    "    type: file_path",
                    "parameter_groups: []",
                    "execution:",
                    "  profiles:",
                    "    - id: legacy_default",
                    "      adapter: legacy_hdp_python",
                    "      entrypoint: [\"python\", \"main.py\"]",
                    "      working_directory: \".\"",
                    "      output_collection:",
                    "        - name: report_file",
                    "          path: legacy/report.txt",
                    "          artifact_kind: file",
                    "compatibility: {}",
                ]
            ),
            encoding="utf-8",
        )

        def legacy_side_effect(*args, **kwargs):
            cwd = Path(kwargs["cwd"])
            output_dir = cwd / "legacy"
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "report.txt").write_text("legacy-ok", encoding="utf-8")
            return subprocess.CompletedProcess(args=kwargs.get("args") or args[0], returncode=0, stdout="ok", stderr="")

        mock_run.side_effect = legacy_side_effect

        with self.app.app_context():
            session_dir, source_file, session_row = self._prepare_generic_pipeline_session("session_legacy_python")
            imported = self.native_service.import_component_from_path(str(component_dir))
            pipeline_config = {
                "identifier": "generic_pipeline",
                "name": "Generic Pipeline",
                "version": "1.0.0",
                "steps": [
                    {
                        "id": "legacy_step",
                        "name": "Legacy Step",
                        "component_ref": imported["key"],
                        "execution_profile_ref": "legacy_default",
                        "scope": "record",
                    }
                ],
            }
            self.native_service.create_pipeline_version_from_config(
                "generic_pipeline",
                pipeline_config,
                activate=True,
                created_by_user_id=self.user_id,
            )
            execution_context = self._build_generic_execution_context(session_dir, source_file, session_row, pipeline_config["steps"])

            result = self.native_service.execute_registered_submission("generic_pipeline", execution_context)
            artifacts = ExecutionArtifact.query.all()

        self.assertTrue(result["success"])
        self.assertEqual(result["summary"]["successful_count"], 1)
        self.assertEqual(result["details"][0]["step_results"]["legacy_step"]["status"], "completed")
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].name, "report_file")

    @patch("subprocess.run")
    def test_imported_container_component_executes_through_native_pipeline_and_collects_outputs(self, mock_run):
        component_dir = Path(self.temp_dir) / "container_component"
        component_dir.mkdir(parents=True, exist_ok=True)
        (component_dir / "component.yaml").write_text(
            "\n".join(
                [
                    "metadata:",
                    "  name: container_component",
                    '  version: "0.1.0"',
                    "  description: Container integration component",
                    "inputs:",
                    "  - name: input_file",
                    "    type: file_path",
                    "outputs:",
                    "  - name: packaged_output",
                    "    type: file_path",
                    "parameter_groups: []",
                    "execution:",
                    "  profiles:",
                    "    - id: container_default",
                    "      adapter: container_cli",
                    "      runtime: docker",
                    "      image: example/component@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "      entrypoint: [\"python\", \"/app/main.py\"]",
                    "      output_collection:",
                    "        - name: packaged_output",
                    "          path: container/result.bin",
                    "          artifact_kind: file",
                    "compatibility: {}",
                ]
            ),
            encoding="utf-8",
        )

        def container_side_effect(*args, **kwargs):
            cwd = Path(kwargs["cwd"])
            output_dir = cwd / "container"
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "result.bin").write_text("container-ok", encoding="utf-8")
            return subprocess.CompletedProcess(args=kwargs.get("args") or args[0], returncode=0, stdout="ok", stderr="")

        mock_run.side_effect = container_side_effect

        with self.app.app_context():
            session_dir, source_file, session_row = self._prepare_generic_pipeline_session("session_container")
            imported = self.native_service.import_component_from_path(str(component_dir))
            pipeline_config = {
                "identifier": "generic_pipeline",
                "name": "Generic Pipeline",
                "version": "1.0.0",
                "steps": [
                    {
                        "id": "container_step",
                        "name": "Container Step",
                        "component_ref": imported["key"],
                        "execution_profile_ref": "container_default",
                        "scope": "record",
                    }
                ],
            }
            self.native_service.create_pipeline_version_from_config(
                "generic_pipeline",
                pipeline_config,
                activate=True,
                created_by_user_id=self.user_id,
            )
            execution_context = self._build_generic_execution_context(session_dir, source_file, session_row, pipeline_config["steps"])

            result = self.native_service.execute_registered_submission("generic_pipeline", execution_context)
            step_run = StepRun.query.one()
            artifacts = ExecutionArtifact.query.all()

        self.assertTrue(result["success"])
        self.assertEqual(result["summary"]["successful_count"], 1)
        self.assertEqual(result["details"][0]["step_results"]["container_step"]["success"], True)
        self.assertEqual(len(artifacts), 1)
        self.assertIn("docker", step_run.command_json)

    @patch("subprocess.run")
    def test_playground_executes_imported_local_cli_component(self, mock_run):
        component_dir = Path(self.temp_dir) / "playground_component"
        component_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = component_dir / "component.yaml"
        manifest_path.write_text(
            "\n".join(
                [
                    "metadata:",
                    "  name: playground_component",
                    '  version: "0.1.0"',
                    "  description: Playground test component",
                    "inputs:",
                    "  - name: input_files",
                    "    type: file_list",
                    "outputs: []",
                    "parameter_groups:",
                    "  - title: General",
                    "    parameters:",
                    "      - name: quality",
                    "        type: string",
                    "execution:",
                    "  profiles:",
                    "    - id: local_default",
                    "      adapter: local_cli",
                    "      entrypoint: [\"component-cli\"]",
                    "      working_directory: \".\"",
                    "compatibility: {}",
                ]
            ),
            encoding="utf-8",
        )
        mock_run.return_value = subprocess.CompletedProcess(
            args=["component-cli", "--input-files", '["/tmp/example.glb"]', "--quality", "preview"],
            returncode=0,
            stdout="playground ok",
            stderr="",
        )

        with self.app.app_context():
            session_dir = Path(self.temp_dir) / "session_playground"
            session_dir.mkdir(parents=True, exist_ok=True)
            session_row = DBSession(
                user_id=self.user_id,
                session_dir=str(session_dir),
                hdpc_path=str(session_dir / "session.hdpc"),
                status="ready",
            )
            db.session.add(session_row)
            db.session.commit()

            source = session_dir / "example.glb"
            source.write_bytes(b"model")
            imported = self.native_service.import_component_from_path(str(component_dir))
            result = self.native_service.execute_playground(
                {
                    "component_key": imported["key"],
                    "session_id": session_row.id,
                    "inputs": {"input_files": [str(source)]},
                    "parameters": {"quality": "preview"},
                    "profile_id": "local_default",
                },
                self.user_id,
            )
            stored_runs = PipelineRun.query.count()

        self.assertEqual(imported["key"], "playground_component")
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["result"]["success"])
        self.assertEqual(stored_runs, 0)
        command = mock_run.call_args.kwargs["args"] if "args" in mock_run.call_args.kwargs else mock_run.call_args.args[0]
        self.assertEqual(command[:2], ["component-cli", "--input-files"])
        self.assertIn("--quality", command)

    @patch("subprocess.run")
    def test_playground_legacy_input_files_alias_still_maps_to_inputs(self, mock_run):
        component_dir = Path(self.temp_dir) / "playground_alias_component"
        component_dir.mkdir(parents=True, exist_ok=True)
        (component_dir / "component.yaml").write_text(
            "\n".join(
                [
                    "metadata:",
                    "  name: playground_alias_component",
                    '  version: "0.1.0"',
                    "inputs:",
                    "  - name: input_files",
                    "    type: file_list",
                    "    required: true",
                    "outputs: []",
                    "parameter_groups: []",
                    "execution:",
                    "  profiles:",
                    "    - id: local_default",
                    "      adapter: local_cli",
                    "      entrypoint: [\"component-cli\"]",
                    "compatibility: {}",
                ]
            ),
            encoding="utf-8",
        )
        mock_run.return_value = subprocess.CompletedProcess(
            args=["component-cli", "--input-files", '["/tmp/example.glb"]'],
            returncode=0,
            stdout="playground ok",
            stderr="",
        )

        with self.app.app_context():
            session_dir = Path(self.temp_dir) / "session_playground_alias"
            session_dir.mkdir(parents=True, exist_ok=True)
            session_row = DBSession(
                user_id=self.user_id,
                session_dir=str(session_dir),
                hdpc_path=str(session_dir / "session.hdpc"),
                status="ready",
            )
            db.session.add(session_row)
            db.session.commit()

            source = session_dir / "example.glb"
            source.write_bytes(b"model")
            imported = self.native_service.import_component_from_path(str(component_dir))
            result = self.native_service.execute_playground(
                {
                    "component_key": imported["key"],
                    "session_id": session_row.id,
                    "input_files": [str(source)],
                    "profile_id": "local_default",
                },
                self.user_id,
            )

        self.assertEqual(result["status"], "completed")
        command = mock_run.call_args.kwargs["args"] if "args" in mock_run.call_args.kwargs else mock_run.call_args.args[0]
        self.assertEqual(command[:2], ["component-cli", "--input-files"])

    def test_playground_executes_builtin_usdz_converter_component(self):
        with self.app.app_context():
            session_dir = Path(self.temp_dir) / "session_playground_usdz"
            uploads_dir = session_dir / "uploads"
            uploads_dir.mkdir(parents=True, exist_ok=True)
            source_file = uploads_dir / "model.glb"
            source_file.write_text("glb-data", encoding="utf-8")
            session_row = DBSession(
                user_id=self.user_id,
                session_dir=str(session_dir),
                hdpc_path=str(session_dir / "session.hdpc"),
                status="ready",
            )
            db.session.add(session_row)
            db.session.commit()

            output_path = session_dir / "playground" / "result" / "model.usdz"
            self.app.any_to_usdz_service.convert.return_value = {
                "success": True,
                "output_path": str(output_path),
            }

            result = self.native_service.execute_playground(
                {
                    "component_key": "any_to_usdz",
                    "session_id": session_row.id,
                    "inputs": {"input_file": str(source_file)},
                    "parameters": {"scale": 1.5, "apply_modifiers": True},
                    "profile_id": "builtin_default",
                },
                self.user_id,
            )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["result"]["success"])
        self.app.any_to_usdz_service.convert.assert_called_once()
        self.assertEqual(
            Path(self.app.any_to_usdz_service.convert.call_args.args[0]).resolve(),
            source_file.resolve(),
        )

    def test_playground_usdz_converter_resolves_relative_session_input(self):
        with self.app.app_context():
            session_dir = Path(self.temp_dir) / "session_playground_usdz_relative"
            uploads_dir = session_dir / "uploads"
            uploads_dir.mkdir(parents=True, exist_ok=True)
            source_file = uploads_dir / "model.glb"
            source_file.write_text("glb-data", encoding="utf-8")
            session_row = DBSession(
                user_id=self.user_id,
                session_dir=str(session_dir),
                hdpc_path=str(session_dir / "session.hdpc"),
                status="ready",
            )
            db.session.add(session_row)
            db.session.commit()

            output_path = session_dir / "playground" / "result" / "model.usdz"
            self.app.any_to_usdz_service.convert.return_value = {
                "success": True,
                "output_path": str(output_path),
            }

            result = self.native_service.execute_playground(
                {
                    "component_key": "any_to_usdz",
                    "session_id": session_row.id,
                    "inputs": {"input_file": "uploads/model.glb"},
                    "profile_id": "builtin_default",
                },
                self.user_id,
            )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["result"]["success"])
        self.assertEqual(self.app.any_to_usdz_service.convert.call_args.args[0], str(source_file.resolve()))

    def test_playground_executes_builtin_fast_renderer_component(self):
        with self.app.app_context():
            session_dir = Path(self.temp_dir) / "session_playground_renderer"
            input_dir = session_dir / "uploads"
            input_dir.mkdir(parents=True, exist_ok=True)
            source_file = input_dir / "model.glb"
            source_file.write_text("glb-data", encoding="utf-8")
            session_row = DBSession(
                user_id=self.user_id,
                session_dir=str(session_dir),
                hdpc_path=str(session_dir / "session.hdpc"),
                status="ready",
            )
            db.session.add(session_row)
            db.session.commit()

            def render_batch_side_effect(input_paths, output_dir, options=None):
                render_dir = Path(output_dir) / "model"
                render_dir.mkdir(parents=True, exist_ok=True)
                thumbnail = render_dir / "model_r000.png"
                thumbnail.write_text("png", encoding="utf-8")
                translated = self.app.fast_renderer_service._translate_to_container_path(input_paths[0])
                return {
                    "results": {
                        translated: {
                            "success": True,
                            "status": "completed",
                        }
                    }
                }

            self.app.fast_renderer_service.render_batch.side_effect = render_batch_side_effect
            self.app.fast_renderer_service._translate_to_container_path.side_effect = lambda value: value

            result = self.native_service.execute_playground(
                {
                    "component_key": "fast_renderer",
                    "session_id": session_row.id,
                    "inputs": {"input-dir": str(input_dir)},
                    "parameters": {"formats": [".glb"]},
                    "profile_id": "builtin_default",
                },
                self.user_id,
            )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["result"]["success"])
        self.app.fast_renderer_service.render_batch.assert_called_once()

    def test_playground_fast_renderer_resolves_relative_session_inputs(self):
        with self.app.app_context():
            session_dir = Path(self.temp_dir) / "session_playground_renderer_relative"
            input_dir = session_dir / "uploads"
            input_dir.mkdir(parents=True, exist_ok=True)
            source_file = input_dir / "model.glb"
            source_file.write_text("glb-data", encoding="utf-8")
            session_row = DBSession(
                user_id=self.user_id,
                session_dir=str(session_dir),
                hdpc_path=str(session_dir / "session.hdpc"),
                status="ready",
            )
            db.session.add(session_row)
            db.session.commit()

            def render_batch_side_effect(input_paths, output_dir, options=None):
                render_dir = Path(output_dir) / "model"
                render_dir.mkdir(parents=True, exist_ok=True)
                thumbnail = render_dir / "model_r000.png"
                thumbnail.write_text("png", encoding="utf-8")
                return {
                    "results": {
                        input_paths[0]: {
                            "success": True,
                            "status": "completed",
                        }
                    }
                }

            self.app.fast_renderer_service.render_batch.side_effect = render_batch_side_effect
            self.app.fast_renderer_service._translate_to_container_path.side_effect = lambda value: value

            result = self.native_service.execute_playground(
                {
                    "component_key": "fast_renderer",
                    "session_id": session_row.id,
                    "inputs": {"input_files": ["uploads/model.glb"]},
                    "parameters": {"formats": [".glb"], "angles": [0]},
                    "profile_id": "builtin_default",
                },
                self.user_id,
            )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["result"]["success"])
        self.assertEqual(self.app.fast_renderer_service.render_batch.call_args.args[0], [str(source_file.resolve())])

    def test_playground_session_file_accepts_relative_session_paths(self):
        with self.app.app_context():
            session_dir = Path(self.temp_dir) / "session_playground_file_preview"
            uploads_dir = session_dir / "uploads"
            uploads_dir.mkdir(parents=True, exist_ok=True)
            source_file = uploads_dir / "model.glb"
            source_file.write_text("glb-data", encoding="utf-8")
            session_row = DBSession(
                user_id=self.user_id,
                session_dir=str(session_dir),
                hdpc_path=str(session_dir / "session.hdpc"),
                status="ready",
            )
            db.session.add(session_row)
            db.session.commit()

            result = self.native_service.get_playground_session_file(
                session_row.id,
                "uploads/model.glb",
                self.user_id,
            )

        self.assertEqual(result["path"], str(source_file.resolve()))
        self.assertEqual(result["download_name"], "model.glb")

    def test_playground_validates_required_and_unknown_fields(self):
        component_dir = Path(self.temp_dir) / "playground_validation_component"
        component_dir.mkdir(parents=True, exist_ok=True)
        (component_dir / "component.yaml").write_text(
            "\n".join(
                [
                    "metadata:",
                    "  name: playground_validation_component",
                    '  version: "0.1.0"',
                    "inputs:",
                    "  - name: source_path",
                    "    type: file_path",
                    "    required: true",
                    "outputs: []",
                    "parameter_groups:",
                    "  - title: General",
                    "    parameters:",
                    "      - name: count",
                    "        type: integer",
                    "execution:",
                    "  profiles:",
                    "    - id: local_default",
                    "      adapter: local_cli",
                    "      entrypoint: [\"component-cli\"]",
                    "compatibility: {}",
                ]
            ),
            encoding="utf-8",
        )

        with self.app.app_context():
            session_dir = Path(self.temp_dir) / "session_playground_validation"
            session_dir.mkdir(parents=True, exist_ok=True)
            session_row = DBSession(
                user_id=self.user_id,
                session_dir=str(session_dir),
                hdpc_path=str(session_dir / "session.hdpc"),
                status="ready",
            )
            db.session.add(session_row)
            db.session.commit()

            imported = self.native_service.import_component_from_path(str(component_dir))

            with self.assertRaises(ValidationError):
                self.native_service.execute_playground(
                    {
                        "component_key": imported["key"],
                        "session_id": session_row.id,
                        "inputs": {},
                        "profile_id": "local_default",
                    },
                    self.user_id,
                )

            with self.assertRaises(ValidationError):
                self.native_service.execute_playground(
                    {
                        "component_key": imported["key"],
                        "session_id": session_row.id,
                        "inputs": {"source_path": "/tmp/example.glb", "extra": "value"},
                        "profile_id": "local_default",
                    },
                    self.user_id,
                )

    def test_render_pipeline_executes_through_native_engine_and_persists_runs(self):
        session_dir = Path(self.temp_dir) / "session_1"
        uploads_dir = session_dir / "uploads"
        outputs_dir = session_dir / "outputs"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        outputs_dir.mkdir(parents=True, exist_ok=True)
        source_file = uploads_dir / "model.glb"
        source_file.write_text("glb-data", encoding="utf-8")
        hdpc_path = session_dir / "session.hdpc"
        self._create_hdpc_source_file(hdpc_path, source_file, file_id=101)

        def render_batch_side_effect(input_paths, output_dir, options=None):
            render_dir = Path(output_dir) / "model"
            render_dir.mkdir(parents=True, exist_ok=True)
            (render_dir / "model_r000.png").write_text("png", encoding="utf-8")
            return {
                "results": {
                    input_paths[0]: {
                        "success": True,
                        "status": "completed",
                        "duration": 0.5,
                        "subprocess_timings": {"total": 0.5},
                    }
                }
            }

        def convert_side_effect(file_path, output_root):
            usdz_path = Path(output_root) / "model.usdz"
            usdz_path.write_text("usdz", encoding="utf-8")
            return {"success": True, "status": "completed", "output_path": str(usdz_path), "timings": {"total": 0.2}}

        self.app.fast_renderer_service.render_batch.side_effect = render_batch_side_effect
        self.app.fast_renderer_service._translate_to_container_path.side_effect = lambda value: value
        self.app.any_to_usdz_service.convert.side_effect = convert_side_effect
        self.app.project_service.create_api_draft.return_value = {"success": True, "zenodo_response": {"id": 12345}}
        self.app.project_service.upload_files_for_deposition.return_value = {"success": True, "id": 12345}
        self.app.project_service.add_source_files.return_value = {"success": True}
        self.app.edm_service.generate_edm_xml_with_report.return_value = {
            "content": "<edm />",
            "minimum_viable_applied": False,
        }
        self.app.edm_service.validate_edm_document.return_value = {"valid": True, "warnings": []}
        self.app.iiif_service.generate_iiif_manifest_with_report.return_value = {
            "content": "{}",
            "validation": {"valid": True, "warnings": []},
            "minimum_viable_applied": False,
        }
        self.app.iiif_service.validate_iiif_manifest.return_value = {"valid": True, "warnings": []}
        self.app.mets_service.generate_mets_xml_with_report.return_value = {
            "content": "<mets />",
            "validation": {"valid": True, "warnings": []},
            "minimum_viable_applied": False,
        }
        self.app.mets_service.validate_mets_xml.return_value = {"valid": True, "warnings": []}

        with self.app.app_context():
            from services.hdpc_local_service import create_local_record_with_metadata

            create_local_record_with_metadata(
                str(hdpc_path),
                file_id=101,
                metadata={
                    "title": "Model title",
                    "description": "Model description",
                    "creators": [{"name": "Museum"}],
                },
                is_sandbox=True,
                access_token="sandbox-token",
            )

            session_row = DBSession(
                user_id=self.user_id,
                session_dir=str(session_dir),
                hdpc_path=str(hdpc_path),
                status="processing",
            )
            db.session.add(session_row)
            db.session.commit()

            pipeline = self.native_service.get_pipeline("render")
            execution_context = {
                "identifier": "render",
                "canonical_identifier": "render",
                "local_file_paths": [str(source_file)],
                "db_session_id": session_row.id,
                "db_session": session_row,
                "hdpc_path": str(hdpc_path),
                "is_sandbox": True,
                "abort_on_critical_error": False,
                "progress_callback": None,
                "pipeline_timings": {
                    "project_loading": 0,
                    "record_registration": 0,
                    "batch_render": 0,
                    "record_processing": [],
                    "total_execution": 0,
                },
                "record_info_list": [
                    (
                        1,
                        str(source_file),
                        {
                            "title": "Model title",
                            "description": "Model description",
                            "creators": [{"name": "Museum"}],
                        },
                    )
                ],
                "skipped_files": [],
                "outputs_dir": str(outputs_dir),
                "batch_metadata_map": {},
                "shared_zenodo_metadata": {},
                "batch_shared_zenodo_metadata": {},
                "batch_item_defaults": {},
                "lod_mapping_config": None,
                "resolved_lod_msf_path": None,
                "msf_rows_by_filename": {},
                "normalized_file_id_map": {},
                "file_id_to_relative_path": {},
                "bundle_file_paths_by_relative": {},
                "basename_to_relative_paths": {},
                "relative_to_absolute_path": {},
                "absolute_to_relative_path": {},
                "steps_map": {step["id"]: step for step in pipeline["config"]["steps"]},
            }

            with patch("services.dataset_integrity_service.ensure_record_operation_allowed", return_value=None), patch(
                "services.native_pipeline_system.create_local_zenodo_draft",
                return_value={"success": True, "zenodo_response": {"id": 12345}},
            ), patch(
                "services.native_pipeline_system.upload_local_zenodo_files",
                return_value={"success": True, "id": 12345},
            ):
                result = self.native_service.execute_registered_submission("render", execution_context)

            pipeline_runs = PipelineRun.query.all()
            step_runs = StepRun.query.all()
            artifacts = ExecutionArtifact.query.all()

        self.assertTrue(result["success"])
        self.assertEqual(result["summary"]["successful_count"], 1)
        self.assertEqual(result["details"][0]["render"]["success"], True)
        self.assertEqual(result["details"][0]["usdz"]["success"], True)
        self.assertEqual(result["details"][0]["edm"]["success"], True)
        self.assertEqual(result["details"][0]["iiif"]["success"], True)
        self.assertEqual(result["details"][0]["mets"]["success"], True)
        self.assertEqual(len(pipeline_runs), 1)
        self.assertGreaterEqual(len(step_runs), 5)
        self.assertGreaterEqual(len(artifacts), 4)
        self.assertFalse(self.app.project_service.add_source_files.called)
        self.assertFalse(self.app.project_service.create_api_draft.called)
        self.assertFalse(self.app.project_service.upload_files_for_deposition.called)
        self.assertTrue(result.get("run_id"))

    def test_batch_step_derives_directory_input_from_mapped_file_outputs(self):
        session_dir = Path(self.temp_dir) / "session_batch_directory_derivation"
        uploads_dir = session_dir / "uploads"
        outputs_dir = session_dir / "outputs"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        outputs_dir.mkdir(parents=True, exist_ok=True)
        source_file = uploads_dir / "model.glb"
        source_file.write_text("glb-data", encoding="utf-8")
        hdpc_path = session_dir / "session.hdpc"
        self._create_hdpc_source_file(hdpc_path, source_file, file_id=101)

        component_dir = Path(self.temp_dir) / "runtime_batch_directory_component"
        self._write_batch_directory_component(component_dir, name="runtime_batch_directory_consumer")

        with self.app.app_context():
            imported = self.native_service.import_component_from_path(str(component_dir))

            pipeline_config = {
                "identifier": "batch_directory_derivation",
                "name": "Batch Directory Derivation",
                "version": "1.0.0",
                "status": "active",
                "modality": "3D Model",
                "processingMode": "root",
                "steps": [
                    {
                        "id": "convert",
                        "name": "Convert",
                        "component_ref": "any_to_usdz",
                        "execution_profile_ref": "builtin_default",
                        "scope": "record",
                    },
                    {
                        "id": "consume",
                        "name": "Consume",
                        "component_ref": imported["key"],
                        "execution_profile_ref": "local_default",
                        "scope": "batch",
                        "input_bindings": [
                            {
                                "kind": "input",
                                "target": "input_files",
                                "type": "artifact_file",
                                "source_step": "convert",
                                "source_output": "output_path",
                            }
                        ],
                    },
                ],
            }
            self.native_service.create_pipeline_version_from_config(
                pipeline_config["identifier"],
                pipeline_config,
                activate=True,
                created_by_user_id=self.user_id,
            )

            session_row = DBSession(
                user_id=self.user_id,
                session_dir=str(session_dir),
                hdpc_path=str(hdpc_path),
                status="processing",
            )
            db.session.add(session_row)
            db.session.commit()

            converted_dir = outputs_dir / "converted"
            converted_output = converted_dir / "model.usdz"

            def convert_side_effect(file_path, output_root):
                converted_dir.mkdir(parents=True, exist_ok=True)
                converted_output.write_text("usdz", encoding="utf-8")
                return {"success": True, "status": "completed", "output_path": str(converted_output), "timings": {"total": 0.2}}

            self.app.any_to_usdz_service.convert.side_effect = convert_side_effect

            captured_requests = []
            local_adapter = self.native_service._adapter_registry["local_cli"]
            original_execute = local_adapter.execute

            def local_execute_side_effect(request):
                captured_requests.append(request)
                return {"success": True, "status": "completed", "outputs": {}, "artifacts": []}

            local_adapter.execute = MagicMock(side_effect=local_execute_side_effect)

            execution_context = {
                "identifier": pipeline_config["identifier"],
                "canonical_identifier": pipeline_config["identifier"],
                "local_file_paths": [str(source_file)],
                "db_session_id": session_row.id,
                "db_session": session_row,
                "hdpc_path": str(hdpc_path),
                "is_sandbox": True,
                "abort_on_critical_error": False,
                "progress_callback": None,
                "pipeline_timings": {
                    "project_loading": 0,
                    "record_registration": 0,
                    "batch_render": 0,
                    "record_processing": [],
                    "total_execution": 0,
                },
                "record_info_list": [
                    (
                        1,
                        str(source_file),
                        {
                            "title": "Model title",
                            "description": "Model description",
                        },
                    )
                ],
                "skipped_files": [],
                "outputs_dir": str(outputs_dir),
                "batch_metadata_map": {},
                "shared_zenodo_metadata": {},
                "batch_shared_zenodo_metadata": {},
                "batch_item_defaults": {},
                "lod_mapping_config": None,
                "resolved_lod_msf_path": None,
                "msf_rows_by_filename": {},
                "normalized_file_id_map": {},
                "file_id_to_relative_path": {},
                "bundle_file_paths_by_relative": {},
                "basename_to_relative_paths": {},
                "relative_to_absolute_path": {},
                "absolute_to_relative_path": {},
                "steps_map": {step["id"]: step for step in pipeline_config["steps"]},
            }

            with patch.object(self.native_service, "_register_record_files", return_value=None):
                try:
                    result = self.native_service.execute_registered_submission(pipeline_config["identifier"], execution_context)
                finally:
                    local_adapter.execute = original_execute

        self.assertTrue(result["success"])
        self.assertEqual(len(captured_requests), 1)
        self.assertEqual(captured_requests[0].inputs["input_files"], [str(converted_output)])
        self.assertEqual(captured_requests[0].inputs["input_dir"], str(converted_dir))
        self.assertNotEqual(captured_requests[0].inputs["input_dir"], str(uploads_dir))

    def test_render_pipeline_prefers_local_zenodo_and_hdpc_registration_when_available(self):
        session_dir = Path(self.temp_dir) / "session_local_native"
        uploads_dir = session_dir / "uploads"
        outputs_dir = session_dir / "outputs"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        outputs_dir.mkdir(parents=True, exist_ok=True)
        source_file = uploads_dir / "model.glb"
        source_file.write_text("glb-data", encoding="utf-8")
        hdpc_path = session_dir / "session.hdpc"
        self._create_hdpc_source_file(hdpc_path, source_file, file_id=101)

        def render_batch_side_effect(input_paths, output_dir, options=None):
            render_dir = Path(output_dir) / "model"
            render_dir.mkdir(parents=True, exist_ok=True)
            (render_dir / "model_r000.png").write_text("png", encoding="utf-8")
            return {
                "results": {
                    input_paths[0]: {
                        "success": True,
                        "status": "completed",
                        "duration": 0.5,
                        "subprocess_timings": {"total": 0.5},
                    }
                }
            }

        def convert_side_effect(file_path, output_root):
            usdz_path = Path(output_root) / "model.usdz"
            usdz_path.write_text("usdz", encoding="utf-8")
            return {"success": True, "status": "completed", "output_path": str(usdz_path), "timings": {"total": 0.2}}

        self.app.fast_renderer_service.render_batch.side_effect = render_batch_side_effect
        self.app.fast_renderer_service._translate_to_container_path.side_effect = lambda value: value
        self.app.any_to_usdz_service.convert.side_effect = convert_side_effect
        self.app.edm_service.generate_edm_xml_with_report.return_value = {
            "content": "<edm />",
            "minimum_viable_applied": False,
        }
        self.app.edm_service.validate_edm_document.return_value = {"valid": True, "warnings": []}
        self.app.iiif_service.generate_iiif_manifest_with_report.return_value = {
            "content": "{}",
            "validation": {"valid": True, "warnings": []},
            "minimum_viable_applied": False,
        }
        self.app.iiif_service.validate_iiif_manifest.return_value = {"valid": True, "warnings": []}
        self.app.mets_service.generate_mets_xml_with_report.return_value = {
            "content": "<mets />",
            "validation": {"valid": True, "warnings": []},
            "minimum_viable_applied": False,
        }
        self.app.mets_service.validate_mets_xml.return_value = {"valid": True, "warnings": []}

        with self.app.app_context():
            from services.hdpc_local_service import create_local_record_with_metadata

            create_local_record_with_metadata(
                str(hdpc_path),
                file_id=101,
                metadata={
                    "title": "Model title",
                    "description": "Model description",
                    "creators": [{"name": "Museum"}],
                },
                is_sandbox=True,
                access_token="sandbox-token",
            )

            session_row = DBSession(
                user_id=self.user_id,
                session_dir=str(session_dir),
                hdpc_path=str(hdpc_path),
                status="processing",
            )
            db.session.add(session_row)
            db.session.commit()

            pipeline = self.native_service.get_pipeline("render")
            execution_context = {
                "identifier": "render",
                "canonical_identifier": "render",
                "local_file_paths": [str(source_file)],
                "db_session_id": session_row.id,
                "db_session": session_row,
                "hdpc_path": str(hdpc_path),
                "is_sandbox": True,
                "abort_on_critical_error": False,
                "progress_callback": None,
                "pipeline_timings": {
                    "project_loading": 0,
                    "record_registration": 0,
                    "batch_render": 0,
                    "record_processing": [],
                    "total_execution": 0,
                },
                "record_info_list": [
                    (
                        1,
                        str(source_file),
                        {
                            "title": "Model title",
                            "description": "Model description",
                            "creators": [{"name": "Museum"}],
                        },
                    )
                ],
                "skipped_files": [],
                "outputs_dir": str(outputs_dir),
                "batch_metadata_map": {},
                "shared_zenodo_metadata": {},
                "batch_shared_zenodo_metadata": {},
                "batch_item_defaults": {},
                "lod_mapping_config": None,
                "resolved_lod_msf_path": None,
                "msf_rows_by_filename": {},
                "normalized_file_id_map": {},
                "file_id_to_relative_path": {},
                "bundle_file_paths_by_relative": {},
                "basename_to_relative_paths": {},
                "relative_to_absolute_path": {},
                "absolute_to_relative_path": {},
                "steps_map": {step["id"]: step for step in pipeline["config"]["steps"]},
            }

            with patch("services.dataset_integrity_service.ensure_record_operation_allowed", return_value=None), patch(
                "services.native_pipeline_system.create_local_zenodo_draft",
                return_value={"success": True, "zenodo_response": {"id": 12345}},
            ) as local_draft, patch(
                "services.native_pipeline_system.upload_local_zenodo_files",
                return_value={"success": True, "published": True, "publication": {"success": True}},
            ) as local_upload:
                result = self.native_service.execute_registered_submission("render", execution_context)

        self.assertTrue(local_draft.called)
        self.assertTrue(local_upload.called)
        self.app.project_service.create_api_draft.assert_not_called()
        self.app.project_service.upload_files_for_deposition.assert_not_called()
        self.app.project_service.add_source_files.assert_not_called()

    def test_force_create_fresh_bypasses_duplicate_guard_during_local_zenodo_steps(self):
        with self.app.app_context():
            draft_request = AdapterExecutionRequest(
                step_id="zenodo_draft",
                profile={},
                workdir=self.temp_dir,
                metadata={
                    "execution_context": {
                        "db_session": MagicMock(),
                        "hdpc_path": "/tmp/test.hdpc",
                        "steps_map": {"zenodo_draft": {"enabled": True}},
                        "progress_callback": None,
                    },
                    "record_context": {
                        "record_id": 1,
                        "filename": "model.glb",
                        "index": 1,
                        "total_records": 1,
                        "record_timings": {"steps": {}, "subprocesses": {}},
                        "record_status": {
                            "zenodo": {"draft_success": False, "upload_success": False},
                            "warnings": [],
                            "step_results": {},
                        },
                        "record_resolution": {"action": "force_create_fresh"},
                    },
                },
            )
            upload_request = AdapterExecutionRequest(
                step_id="zenodo_upload",
                profile={},
                workdir=self.temp_dir,
                metadata={
                    "execution_context": {
                        "db_session": MagicMock(),
                        "hdpc_path": "/tmp/test.hdpc",
                        "steps_map": {"zenodo_upload": {"enabled": True, "parameters": {"publish": False}}},
                        "progress_callback": None,
                    },
                    "record_context": {
                        "record_id": 1,
                        "filename": "model.glb",
                        "index": 1,
                        "total_records": 1,
                        "current_zenodo_draft_record_id": 12345,
                        "record_timings": {"steps": {}, "subprocesses": {}},
                        "record_status": {
                            "error": None,
                            "zenodo": {"draft_success": True, "upload_success": False},
                            "warnings": [],
                            "step_results": {},
                        },
                        "record_resolution": {"action": "force_create_fresh"},
                    },
                },
            )
            with patch(
                "services.dataset_integrity_service.ensure_record_operation_allowed",
                side_effect=AssertionError("force_create_fresh should bypass duplicate guards during native draft/upload"),
            ), patch(
                "services.native_pipeline_system.create_local_zenodo_draft",
                return_value={"success": True, "zenodo_response": {"id": 12345}},
            ) as local_draft, patch(
                "services.native_pipeline_system.upload_local_zenodo_files",
                return_value={"success": True, "published": False},
            ) as local_upload:
                draft_result = self.native_service._builtin_zenodo_draft_handler(draft_request)
                upload_result = self.native_service._builtin_zenodo_upload_handler(upload_request)

        self.assertTrue(draft_result["success"])
        self.assertTrue(upload_result["success"])
        self.assertTrue(local_draft.called)
        self.assertTrue(local_upload.called)

    def _execute_required_lod_generation(self, session_name, lod_parameters):
        session_dir = Path(self.temp_dir) / session_name
        uploads_dir = session_dir / "uploads"
        outputs_dir = session_dir / "outputs"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        outputs_dir.mkdir(parents=True, exist_ok=True)
        source_file = uploads_dir / "model.glb"
        source_file.write_text("glb-data", encoding="utf-8")
        hdpc_path = session_dir / "session.hdpc"
        self._create_hdpc_source_file(hdpc_path, source_file, file_id=101)

        with self.app.app_context():
            from services.hdpc_local_service import create_local_record_with_metadata

            create_local_record_with_metadata(
                str(hdpc_path),
                file_id=101,
                metadata={
                    "title": "Model title",
                    "description": "Model description",
                    "creators": [{"name": "Museum"}],
                },
                is_sandbox=True,
                access_token="sandbox-token",
            )

            session_row = DBSession(
                user_id=self.user_id,
                session_dir=str(session_dir),
                hdpc_path=str(hdpc_path),
                status="processing",
            )
            db.session.add(session_row)
            db.session.commit()

            pipeline = self.native_service.get_pipeline("render")
            execution_context = {
                "identifier": "render",
                "canonical_identifier": "render",
                "local_file_paths": [str(source_file)],
                "db_session_id": session_row.id,
                "db_session": session_row,
                "hdpc_path": str(hdpc_path),
                "is_sandbox": True,
                "abort_on_critical_error": False,
                "progress_callback": None,
                "pipeline_timings": {
                    "project_loading": 0,
                    "record_registration": 0,
                    "batch_render": 0,
                    "record_processing": [],
                    "total_execution": 0,
                },
                "record_info_list": [
                    (
                        1,
                        str(source_file),
                        {
                            "title": "Model title",
                            "description": "Model description",
                            "creators": [{"name": "Museum"}],
                        },
                    )
                ],
                "skipped_files": [],
                "outputs_dir": str(outputs_dir),
                "batch_metadata_map": {},
                "shared_zenodo_metadata": {},
                "batch_shared_zenodo_metadata": {},
                "batch_item_defaults": {},
                "lod_mapping_config": None,
                "resolved_lod_msf_path": None,
                "msf_rows_by_filename": {},
                "normalized_file_id_map": {},
                "file_id_to_relative_path": {},
                "bundle_file_paths_by_relative": {},
                "basename_to_relative_paths": {},
                "relative_to_absolute_path": {},
                "absolute_to_relative_path": {},
                "steps_map": {step["id"]: step for step in pipeline["config"]["steps"]},
            }
            execution_context["steps_map"]["fast_renderer"]["enabled"] = False
            execution_context["steps_map"]["any_to_usdz"]["enabled"] = False
            execution_context["steps_map"]["lod_generation"]["enabled"] = True
            execution_context["steps_map"]["lod_generation"]["parameters"] = lod_parameters
            execution_context["steps_map"]["zenodo_upload"]["enabled"] = True
            execution_context["steps_map"]["zenodo_upload"]["parameters"] = {"publish": False}

            with patch("services.dataset_integrity_service.ensure_record_operation_allowed", return_value=None), patch(
                "services.native_pipeline_system.create_local_zenodo_draft",
                return_value={"success": True, "zenodo_response": {"id": 12345}},
            ), patch(
                "services.native_pipeline_system.upload_local_zenodo_files",
                return_value={"success": True},
            ) as upload_mock:
                result = self.native_service.execute_registered_submission("render", execution_context)
                upload_called = upload_mock.called

        return result, upload_called

    def test_required_lod_failure_blocks_native_zenodo_upload(self):
        self.app.edm_service.generate_edm_xml_with_report.side_effect = RuntimeError("LOD generation exploded")

        result, upload_called = self._execute_required_lod_generation(
            "session_lod_required_failure",
            {
                "generate_edm": True,
                "generate_iiif": False,
                "generate_mets": False,
                "lod_policy": "required",
            },
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["summary"]["failed_count"], 1)
        self.assertEqual(result["details"][0]["edm"]["status"], "failed_required")
        self.assertIn("LOD generation failed", result["details"][0]["error"])
        self.assertFalse(upload_called)

    def test_required_iiif_validation_failure_blocks_native_zenodo_upload(self):
        self.app.iiif_service.generate_iiif_manifest_with_report.return_value = {
            "content": "{}",
            "validation": {"valid": False, "errors": ["legacy v4 Scene manifest"]},
            "minimum_viable_applied": False,
        }

        result, upload_called = self._execute_required_lod_generation(
            "session_iiif_required_validation_failure",
            {
                "generate_edm": False,
                "generate_iiif": True,
                "generate_mets": False,
                "lod_policy": "required",
            },
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["details"][0]["iiif"]["status"], "failed_required")
        self.assertIn("IIIF validation failed", result["details"][0]["error"])
        self.assertFalse(upload_called)

    def test_required_mets_validation_failure_blocks_native_zenodo_upload(self):
        self.app.mets_service.generate_mets_xml_with_report.return_value = {
            "content": "<mets />",
            "validation": {"valid": False, "errors": ["METS XSD: invalid CHECKSUMTYPE"]},
            "minimum_viable_applied": False,
        }

        result, upload_called = self._execute_required_lod_generation(
            "session_mets_required_validation_failure",
            {
                "generate_edm": False,
                "generate_iiif": False,
                "generate_mets": True,
                "lod_policy": "required",
            },
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["details"][0]["mets"]["status"], "failed_required")
        self.assertIn("METS/MODS validation failed", result["details"][0]["error"])
        self.assertFalse(upload_called)


if __name__ == "__main__":
    unittest.main()
