import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import Session as DBSession, User, UserRole
from exceptions import ResourceNotFoundError
from middleware import setup_error_handlers
from routes.pipeline_routes import pipeline_bp
from routes.pipeline_v2_routes import pipeline_v2_bp
from routes.tools_routes import tools_bp


class TestNativePipelineRoutes(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="native-pipeline-routes-")
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        self.app.config["SECRET_KEY"] = "test-secret"
        self.app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
        self.app.config["ENABLE_RENDERER"] = True
        self.app.config["ENABLE_USDZ_CONVERSION"] = True

        db.init_app(self.app)
        JWTManager(self.app)
        setup_error_handlers(self.app)

        self.app.native_pipeline_service = MagicMock()
        self.app.native_pipeline_service.create_pending_run.return_value = {"run_id": "run-123"}
        self.app.component_installer_service = MagicMock()
        self.app.register_blueprint(pipeline_bp, url_prefix="/api/v1/pipelines")
        self.app.register_blueprint(pipeline_v2_bp, url_prefix="/api/v2")
        self.app.register_blueprint(tools_bp, url_prefix="/api/v1/tools")

        with self.app.app_context():
            db.create_all()
            self.user = User(email="user@example.com", role=UserRole.USER, is_verified=True)
            self.user.set_password("password123")
            self.user.set_capabilities([])
            self.admin_user = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
            self.admin_user.set_password("password123")
            self.admin_user.set_capabilities([])
            self.author_user = User(email="author@example.com", role=UserRole.USER, is_verified=True)
            self.author_user.set_password("password123")
            self.author_user.set_capabilities(["native_pipeline_author"])
            db.session.add(self.user)
            db.session.add(self.admin_user)
            db.session.add(self.author_user)
            db.session.commit()
            self.token = create_access_token(identity=str(self.user.id))
            self.admin_token = create_access_token(identity=str(self.admin_user.id))
            self.author_token = create_access_token(identity=str(self.author_user.id))
            self.user_id = self.user.id
            self.admin_user_id = self.admin_user.id
            self.author_user_id = self.author_user.id

            self.session = DBSession(
                user_id=self.user.id,
                session_dir="/tmp/session-routes",
                hdpc_path="/tmp/session-routes/session.hdpc",
                status="ready",
            )
            self.author_session = DBSession(
                user_id=self.author_user.id,
                session_dir="/tmp/session-routes-author",
                hdpc_path="/tmp/session-routes-author/session.hdpc",
                status="ready",
            )
            db.session.add(self.session)
            db.session.add(self.author_session)
            db.session.commit()
            self.session_id = self.session.id
            self.author_session_id = self.author_session.id

        self.client = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def _admin_headers(self):
        return {"Authorization": f"Bearer {self.admin_token}"}

    def _author_headers(self):
        return {"Authorization": f"Bearer {self.author_token}"}

    @patch("routes.tools_routes.CloudUploadService.get_storage_mode", return_value="cloud_backup")
    @patch.dict("os.environ", {"WEBHDP_CORE_ONLY": "true", "WEBHDP_ENABLE_NATIVE_TOOLS": "false"})
    def test_native_tools_opt_in_preserves_profile_and_account_guards(self, _storage_mode):
        tools = "/api/v1/tools"
        constructor = "/api/v2/pipelines?scope=constructor"
        installer = f"{tools}/hdp-components/catalog"
        admin = self._admin_headers()

        def features(headers):
            context = self.client.get(f"{tools}/context", headers=headers).get_json()["data"]
            self.assertTrue(context["core_only"])
            return {name for name, feature in context["features"].items() if feature["enabled"]}

        self.assertEqual(features(admin), {"hpc_diagnostics"})
        self.assertEqual(self.client.get(constructor, headers=admin).status_code, 403)
        self.assertEqual(self.client.get(installer, headers=admin).status_code, 403)

        self.app.native_pipeline_service.list_pipelines.return_value = []
        self.app.component_installer_service.list_available_catalog.return_value = {}
        with patch.dict("os.environ", {"WEBHDP_ENABLE_NATIVE_TOOLS": "true"}):
            self.assertEqual(features(admin), {
                "hpc_diagnostics", "native_playground", "pipeline_constructor", "hdp_component_installer",
            })
            self.assertEqual(features(self._headers()), {"native_playground"})
            self.assertEqual(features(self._author_headers()), {"native_playground", "pipeline_constructor"})
            self.assertEqual(self.client.get(constructor, headers=self._headers()).status_code, 403)
            self.assertEqual(self.client.get(constructor, headers=self._author_headers()).status_code, 200)
            self.app.native_pipeline_service.list_pipelines.assert_called_once_with(status=None, authoring=True)
            self.assertEqual(self.client.get(installer).status_code, 401)
            self.assertEqual(self.client.get(installer, headers=self._headers()).status_code, 403)
            self.assertEqual(self.client.get(installer, headers=admin).status_code, 200)
            self.assertEqual(self.client.post(f"{tools}/pipeline-preflight/local", headers=admin, json={}).status_code, 403)
            self.assertEqual(self.client.get(f"{tools}/community-migrations/context", headers=admin).status_code, 403)

    def test_v1_pipeline_list_and_detail_use_native_service(self):
        self.app.native_pipeline_service.list_pipelines.return_value = [
            {"identifier": "render", "name": "render", "description": "Render pipeline"}
        ]
        self.app.native_pipeline_service.get_pipeline.return_value = {
            "identifier": "render",
            "name": "render",
            "description": "Render pipeline",
            "config": {"steps": [{"id": "fast_renderer", "enabled": True}]},
        }

        list_response = self.client.get("/api/v1/pipelines", headers=self._headers())
        detail_response = self.client.get("/api/v1/pipelines/render", headers=self._headers())

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        self.app.native_pipeline_service.list_pipelines.assert_called_once()
        self.app.native_pipeline_service.get_pipeline.assert_called_with("render")

    def test_v1_execution_status_route_uses_native_run_lookup_only(self):
        self.app.native_pipeline_service.get_pipeline_run.return_value = {
            "run_id": "run-123",
            "status": "completed",
            "steps": [],
            "artifacts": [],
        }

        response = self.client.get("/api/v1/pipelines/executions/run-123/status", headers=self._headers())

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["data"]["run_id"], "run-123")
        self.app.native_pipeline_service.get_pipeline_run.assert_called_once_with("run-123", self.user_id)

    def test_v1_execution_status_route_returns_404_for_unknown_native_run(self):
        self.app.native_pipeline_service.get_pipeline_run.side_effect = ResourceNotFoundError("missing")

        response = self.client.get("/api/v1/pipelines/executions/missing/status", headers=self._headers())

        self.assertEqual(response.status_code, 404)

    @patch("services.submission_pipeline_service.execute_submission_pipeline")
    def test_v1_execute_route_preserves_compatibility_shape(self, execute_submission_pipeline):
        execute_submission_pipeline.return_value = {
            "result": {
                "success": True,
                "run_id": "run-123",
                "pipeline_identifier": "render",
                "pipeline_version": "1.1.0",
                "details": [],
            },
            "timings": {"total_execution": 1.2},
            "progress_summary": {"processed_count": 1, "failed_count": 0, "successful_count": 1},
        }

        response = self.client.post(
            "/api/v1/pipelines/render/execute_on_local_files",
            json={
                "session_id": self.session_id,
                "local_file_paths": ["/tmp/session-routes/uploads/model.glb"],
                "is_sandbox": True,
            },
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["result"]["run_id"], "run-123")
        self.assertEqual(payload["data"]["result"]["pipeline_version"], "1.1.0")
        self.assertEqual(execute_submission_pipeline.call_args.kwargs['precreated_run_public_id'], 'run-123')

    def test_v1_and_v2_reject_account_processing_quota_before_dispatch(self):
        from database.models import Submission
        from services.native_run_quota import NativeRunQuotaExceeded

        self.app.native_pipeline_service.create_pending_run.side_effect = NativeRunQuotaExceeded(details={'active': 3, 'active_limit': 3})
        body = {'session_id': self.session_id, 'local_file_paths': ['/tmp/session-routes/uploads/model.glb'], 'async_execution': True}
        for endpoint in ('/api/v1/pipelines/render/execute_on_local_files', '/api/v2/pipelines/render/execute'):
            response = self.client.post(endpoint, json=body, headers=self._headers())
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.get_json()['error']['code'], 'NATIVE_PROCESSING_QUOTA')
        with self.app.app_context():
            self.assertEqual(Submission.query.count(), 0)

    @patch("services.submission_pipeline_service.execute_submission_pipeline")
    def test_v1_concurrent_execution_returns_conflict_without_failing_active_session(self, execute):
        from services.pipeline_execution_lock import PipelineAlreadyRunning
        from database.models import Submission

        execute.side_effect = PipelineAlreadyRunning()
        response = self.client.post(
            "/api/v1/pipelines/render/execute_on_local_files",
            json={"session_id": self.session_id,
                  "local_file_paths": ["/tmp/session-routes/uploads/model.glb"],
                  "is_sandbox": True},
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("already being processed", response.get_json()["error"]["message"])
        with self.app.app_context():
            self.assertNotEqual(db.session.get(DBSession, self.session_id).status, "failed")
            self.assertEqual(Submission.query.filter_by(session_id=self.session_id).count(), 0)

    @patch("routes.pipeline_v2_routes.execute_submission_pipeline")
    def test_v2_execute_and_run_routes_use_native_backend(self, execute_submission_pipeline):
        self.app.native_pipeline_service.list_pipelines.return_value = [
            {"identifier": "render", "name": "render", "description": "Render pipeline"}
        ]
        self.app.native_pipeline_service.get_pipeline.return_value = {
            "identifier": "render",
            "name": "render",
            "description": "Render pipeline",
            "config": {"steps": [{"id": "fast_renderer", "enabled": True}]},
        }
        self.app.native_pipeline_service.get_pipeline_run.return_value = {
            "run_id": "run-123",
            "status": "completed",
            "steps": [],
            "artifacts": [],
        }
        execute_submission_pipeline.return_value = {
            "result": {
                "success": True,
                "run_id": "run-123",
                "pipeline_identifier": "render",
                "pipeline_version": "1.1.0",
                "details": [],
            },
            "timings": {"total_execution": 1.2},
            "progress_summary": {"processed_count": 1, "failed_count": 0, "successful_count": 1},
        }

        execute_response = self.client.post(
            "/api/v2/pipelines/render/execute",
            json={
                "session_id": self.session_id,
                "local_file_paths": ["/tmp/session-routes/uploads/model.glb"],
                "is_sandbox": True,
            },
            headers=self._headers(),
        )
        run_response = self.client.get("/api/v2/runs/run-123", headers=self._headers())

        self.assertEqual(execute_response.status_code, 200)
        self.assertEqual(run_response.status_code, 200)
        execute_payload = execute_response.get_json()
        run_payload = run_response.get_json()
        self.assertEqual(execute_payload["data"]["run_id"], "run-123")
        self.assertEqual(run_payload["data"]["run"]["status"], "completed")

    @patch("routes.pipeline_v2_routes.execute_submission_pipeline")
    def test_v2_sync_execution_accepts_record_ids(self, execute_submission_pipeline):
        with self.app.app_context():
            db.session.get(DBSession, self.session_id).status = "failed"
            db.session.commit()
        execute_submission_pipeline.return_value = {
            "result": {
                "success": True,
                "run_id": "run-records",
                "pipeline_identifier": "render",
                "pipeline_version": "1.1.0",
                "details": [],
            },
            "timings": {"total_execution": 0.4},
            "progress_summary": {"processed_count": 2, "failed_count": 0, "successful_count": 2},
        }

        response = self.client.post(
            "/api/v2/pipelines/render/execute",
            json={
                "session_id": self.session_id,
                "record_ids": [21, 22],
                "is_sandbox": True,
            },
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["data"]["run_id"], "run-records")
        self.assertEqual(execute_submission_pipeline.call_args.kwargs["db_session_id"], self.session_id)
        self.assertEqual(execute_submission_pipeline.call_args.kwargs["local_file_paths"], [])
        self.assertEqual(execute_submission_pipeline.call_args.kwargs["record_ids"], [21, 22])
        with self.app.app_context():
            self.assertEqual(db.session.get(DBSession, self.session_id).status, "completed")

        execute_submission_pipeline.return_value["result"]["success"] = False
        response = self.client.post(
            "/api/v2/pipelines/render/execute",
            json={"session_id": self.session_id, "record_ids": [21], "is_sandbox": True},
            headers=self._headers(),
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(db.session.get(DBSession, self.session_id).status, "failed")

    @patch("routes.pipeline_v2_routes._enqueue_submission_pipeline_task")
    def test_v2_async_execution_precreates_native_run_and_accepts_record_ids(self, mock_enqueue):
        mock_enqueue.return_value = MagicMock(id="task-123")
        self.app.native_pipeline_service.create_pending_run.return_value = {
            "run_id": "run-async",
            "pipeline_identifier": "render",
            "pipeline_version": "1.1.0",
            "status": "pending",
        }

        response = self.client.post(
            "/api/v2/pipelines/render/execute",
            json={
                "session_id": self.session_id,
                "record_ids": [11, 12],
                "async_execution": True,
                "is_sandbox": True,
            },
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 202)
        payload = response.get_json()
        self.assertEqual(payload["data"]["run_id"], "run-async")
        self.assertEqual(payload["data"]["task_id"], "task-123")
        self.app.native_pipeline_service.create_pending_run.assert_called_once()
        args = mock_enqueue.call_args.args
        self.assertEqual(args[0], None)
        self.assertEqual(args[1], "render")
        self.assertEqual(args[2], [])
        self.assertEqual(args[3], self.session_id)
        self.assertEqual(args[6], [11, 12])
        self.assertEqual(args[7], [])
        self.assertEqual(args[8], "run-async")

    def test_v2_playground_routes_use_native_backend(self):
        self.app.native_pipeline_service.execute_playground.return_value = {
            "run_id": "play-123",
            "status": "completed",
            "result": {"success": True},
        }
        self.app.native_pipeline_service.get_playground_run.return_value = {
            "run_id": "play-123",
            "status": "completed",
            "result": {"success": True},
        }

        execute_response = self.client.post(
            "/api/v2/playground/execute",
            json={
                "component_key": "demo_component",
                "session_id": self.session_id,
                "inputs": {"input_files": ["/tmp/example.glb"]},
                "parameters": {"quality": "preview"},
            },
            headers=self._headers(),
        )
        run_response = self.client.get("/api/v2/playground/runs/play-123", headers=self._headers())

        self.assertEqual(execute_response.status_code, 201)
        self.assertEqual(run_response.status_code, 200)
        self.assertEqual(execute_response.get_json()["data"]["playground_run"]["run_id"], "play-123")
        self.assertEqual(run_response.get_json()["data"]["playground_run"]["status"], "completed")

    def test_v2_components_route_supports_playground_only_filter(self):
        self.app.native_pipeline_service.list_components.return_value = [
            {"key": "playground_component", "playground": {"enabled": True, "reason": None}}
        ]

        response = self.client.get("/api/v2/components?playground_only=true", headers=self._headers())

        self.assertEqual(response.status_code, 200)
        self.app.native_pipeline_service.list_components.assert_called_once_with(playground_only=True)
        self.assertEqual(response.get_json()["data"]["components"][0]["key"], "playground_component")

    def test_v2_component_validate_and_import_routes_use_native_backend(self):
        component_dir = Path(self.temp_dir) / "route_component"
        component_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = component_dir / "component.yaml"
        manifest_path.write_text(
            "\n".join(
                [
                    "metadata:",
                    "  name: route_component",
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
        self.app.native_pipeline_service.validate_component_manifest_path.return_value = {
            "component_path": str(component_dir),
            "manifest_path": str(manifest_path),
            "manifest": {"metadata": {"name": "route_component", "version": "0.1.0"}},
            "playground_schema": {"title": "Route Component"},
        }
        self.app.native_pipeline_service.import_component_from_path.return_value = {
            "key": "route_component",
            "name": "route_component",
            "version": "0.1.0",
        }

        validate_response = self.client.post(
            "/api/v2/components/validate",
            json={"component_path": str(component_dir)},
            headers=self._admin_headers(),
        )
        import_response = self.client.post(
            "/api/v2/components/import",
            json={"component_path": str(component_dir)},
            headers=self._admin_headers(),
        )

        self.assertEqual(validate_response.status_code, 200)
        self.assertEqual(import_response.status_code, 201)
        self.app.native_pipeline_service.validate_component_manifest_path.assert_called_once_with(str(component_dir))
        self.app.native_pipeline_service.import_component_from_path.assert_called_once_with(str(component_dir))
        self.assertEqual(validate_response.get_json()["data"]["manifest"]["metadata"]["name"], "route_component")
        self.assertEqual(validate_response.get_json()["data"]["playground_schema"]["title"], "Route Component")
        self.assertEqual(import_response.get_json()["data"]["component"]["key"], "route_component")

    def test_pipeline_author_can_access_constructor_routes(self):
        self.app.native_pipeline_service.validate_pipeline_config.return_value = {
            "valid": True,
            "normalized": {"identifier": "authoring"},
            "warnings": [],
            "errors": [],
        }
        self.app.native_pipeline_service.get_pipeline_constructor_support.return_value = {
            "trigger_operators": [{"id": "eq"}],
            "zenodo_target_paths": [{"path": "title"}],
        }
        self.app.native_pipeline_service.preflight_pipeline_constructor.return_value = {
            "valid": True,
            "steps": [],
        }

        validate_response = self.client.post(
            "/api/v2/pipelines/validate",
            json={"identifier": "authoring", "name": "Authoring", "version": "1.0.0", "steps": []},
            headers=self._author_headers(),
        )
        support_response = self.client.get("/api/v2/pipelines/constructor-support", headers=self._author_headers())
        preflight_response = self.client.post(
            "/api/v2/pipelines/constructor/preflight",
            json={
                "pipeline_definition": {"identifier": "authoring", "name": "Authoring", "version": "1.0.0", "steps": []},
                "session_id": self.author_session_id,
                "local_file_paths": ["/tmp/session-routes-author/uploads/model.glb"],
            },
            headers=self._author_headers(),
        )

        self.assertEqual(validate_response.status_code, 200)
        self.assertEqual(support_response.status_code, 200)
        self.assertEqual(preflight_response.status_code, 200)
        self.app.native_pipeline_service.preflight_pipeline_constructor.assert_called_once_with(
            {
                "pipeline_definition": {"identifier": "authoring", "name": "Authoring", "version": "1.0.0", "steps": []},
                "session_id": self.author_session_id,
                "local_file_paths": ["/tmp/session-routes-author/uploads/model.glb"],
            },
            user_id=self.author_user_id,
        )

    def test_regular_user_cannot_access_constructor_routes(self):
        response = self.client.get("/api/v2/pipelines/constructor-support", headers=self._headers())
        self.assertEqual(response.status_code, 403)

    def test_v2_pipeline_artifact_download_requires_matching_run_and_isolated_file(self):
        from database.models import ExecutionArtifact, PipelineDefinition, PipelineRun, PipelineStep, PipelineVersion, StepRun

        session_dir = Path(self.temp_dir).resolve()
        with self.app.app_context():
            session = db.session.get(DBSession, self.session_id)
            session.session_dir = str(session_dir)
            definition = PipelineDefinition(identifier="fixture", name="Artifact fixture")
            db.session.add(definition)
            db.session.flush()
            version = PipelineVersion(pipeline_definition_id=definition.id, version="1", config_json="{}", config_hash="fixture")
            db.session.add(version)
            db.session.flush()
            runs = [PipelineRun(pipeline_definition_id=definition.id, pipeline_version_id=version.id, session_id=session.id) for _ in range(2)]
            step = PipelineStep(pipeline_version_id=version.id, step_key="scan", component_key="scan", name="Scan", order_index=1)
            db.session.add_all([*runs, step])
            db.session.flush()
            step_run = StepRun(pipeline_run_id=runs[0].id, pipeline_step_id=step.id, record_id=7, record_path="/uploads/example.png")
            db.session.add(step_run)
            db.session.flush()
            record_dir = session_dir / "outputs" / "record-7" / "example"
            output_dir = record_dir / f"step-{step_run.id}" / "outputs"
            output_dir.mkdir(parents=True)
            result_path = output_dir / "result.mid"
            result_path.write_bytes(b"test midi")
            legacy_path = record_dir / "unscoped.txt"
            legacy_path.write_bytes(b"unscoped")
            linked_path = output_dir / "linked.mid"
            linked_path.symlink_to(result_path)
            linked_dir = output_dir / "linked-directory"
            linked_dir.symlink_to(output_dir, target_is_directory=True)
            artifacts = [
                ExecutionArtifact(pipeline_run_id=runs[0].id, step_run_id=step_run.id, record_id=7,
                                  artifact_kind="file", name=path.name, path=str(path))
                for path in (result_path, legacy_path, linked_path, linked_dir / result_path.name,
                             output_dir / ".." / "outputs" / result_path.name, output_dir / "missing.mid")
            ]
            db.session.add_all(artifacts)
            db.session.commit()
            run_urls = [f"/api/v2/runs/{run.public_id}/artifacts" for run in runs]
            artifact_ids = [artifact.id for artifact in artifacts]

        url = f"{run_urls[0]}/{artifact_ids[0]}"
        response = self.client.get(url, headers=self._headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"test midi")
        self.assertIn("attachment; filename=result.mid", response.headers["Content-Disposition"])
        self.assertIn("no-store", response.headers["Cache-Control"])
        response.close()
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.get(url, headers=self._author_headers()).status_code, 404)
        self.assertEqual(self.client.get(f"{run_urls[1]}/{artifact_ids[0]}", headers=self._headers()).status_code, 404)
        for artifact_id in artifact_ids[1:]:
            with self.subTest(artifact_id=artifact_id):
                response = self.client.get(f"{run_urls[0]}/{artifact_id}", headers=self._headers())
                self.assertEqual(response.status_code, 404)

    def test_v2_playground_artifact_download_route_uses_native_backend(self):
        artifact_path = Path(self.temp_dir) / "artifact.png"
        artifact_path.write_bytes(b"png-data")
        self.app.native_pipeline_service.get_playground_run_artifact.return_value = {
            "path": str(artifact_path),
            "download_name": "artifact.png",
            "mimetype": "image/png",
        }

        response = self.client.get("/api/v2/playground/runs/play-123/artifacts/0", headers=self._headers())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"png-data")
        self.app.native_pipeline_service.get_playground_run_artifact.assert_called_once_with("play-123", 0, self.user_id)

    def test_v2_playground_session_file_route_uses_native_backend(self):
        session_file = Path(self.temp_dir) / "session_preview.png"
        session_file.write_bytes(b"preview-data")
        self.app.native_pipeline_service.get_playground_session_file.return_value = {
            "path": str(session_file),
            "download_name": "session_preview.png",
            "mimetype": "image/png",
        }

        response = self.client.get(
            f"/api/v2/playground/sessions/{self.session_id}/file",
            query_string={"path": str(session_file)},
            headers=self._headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"preview-data")
        self.app.native_pipeline_service.get_playground_session_file.assert_called_once_with(self.session_id, str(session_file), self.user_id)

    def test_v2_platform_support_route_exposes_native_contract(self):
        response = self.client.get("/api/v2/platform-support", headers=self._headers())

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["official_platform_id"], "webhdp_native_pipeline_platform")
        self.assertTrue(payload["data"]["decision"]["retire_legacy_component_manager_api"])
        self.assertTrue(payload["data"]["decision"]["retire_legacy_pipeline_manager_api"])
        self.assertEqual(payload["data"]["supported_surfaces"]["components_import"], "/api/v2/components/import")
        retired_ids = {item["id"] for item in payload["data"]["retired_surfaces"]}
        self.assertIn("legacy_component_manager_api", retired_ids)
        self.assertIn("legacy_pipeline_manager_api", retired_ids)


if __name__ == "__main__":
    unittest.main()
