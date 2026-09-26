import json
import os
import sqlite3
import sys
import tempfile
import types
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import File, Session as DBSession, User, UserMetadata, UserRole
from routes.session_routes import session_bp
from services.hdpc_local_service import create_local_record_with_metadata
from services.native_pipeline_system import NativePipelineSystemService
from services.submission_pipeline_service import execute_submission_pipeline
import services.submission_pipeline_service as submission_pipeline_service


sys.modules["celery_app"] = types.SimpleNamespace(
    celery=types.SimpleNamespace(task=lambda *args, **kwargs: (lambda fn: fn))
)
sys.modules.pop("tasks", None)
import tasks  # noqa: E402


pytestmark = pytest.mark.batch0_regression


def test_async_pipeline_conflict_preserves_active_session_state():
    from services.pipeline_execution_lock import PipelineAlreadyRunning

    with _submission_test_context() as context:
        with patch("services.submission_pipeline_service.execute_submission_pipeline", side_effect=PipelineAlreadyRunning()), patch(
            "tasks.notify_user"
        ) as notify:
            with pytest.raises(PipelineAlreadyRunning):
                tasks.execute_submission_pipeline_task(
                    MagicMock(), None, "render", [context["source_path"]], context["session_id"]
                )
        assert db.session.get(DBSession, context["session_id"]).status == "processing"
        notify.assert_not_called()


def test_queued_run_retries_lock_contention_without_failing_the_session():
    from services.pipeline_execution_lock import PipelineAlreadyRunning
    from celery.exceptions import Retry
    task = MagicMock()
    task.retry.side_effect = Retry("Waiting for session")
    with _submission_test_context() as context:
        with patch("services.submission_pipeline_service.execute_submission_pipeline", side_effect=PipelineAlreadyRunning()), patch("tasks.notify_user") as notify:
            with pytest.raises(Retry):
                tasks.execute_submission_pipeline_task(task, None, "render", [context["source_path"]], context["session_id"], precreated_run_public_id="queued-run")
        task.retry.assert_called_once()
        assert task.retry.call_args.kwargs["countdown"] == 30
        assert task.retry.call_args.kwargs["max_retries"] is None
        assert db.session.get(DBSession, context["session_id"]).status == "processing"
        notify.assert_not_called()


def test_untracked_redelivery_does_not_repeat_remote_work():
    from exceptions import FileProcessingError
    task = MagicMock()
    task.request.delivery_info = {"redelivered": True}
    with _submission_test_context() as context:
        with patch("services.submission_pipeline_service.execute_submission_pipeline") as execute, patch("tasks.notify_user"):
            with pytest.raises(FileProcessingError, match="interrupted"):
                tasks.execute_submission_pipeline_task(task, None, "render", [context["source_path"]], context["session_id"])
        execute.assert_not_called()
        assert db.session.get(DBSession, context["session_id"]).status == "failed"


def _create_submission_hdpc(path: str, root_dir: str, *, filename: str = "model.glb") -> str:
    uploads_dir = os.path.join(root_dir, "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    source_path = os.path.join(uploads_dir, filename)
    with open(source_path, "w", encoding="utf-8") as handle:
        handle.write("glb")

    conn = sqlite3.connect(path)
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
                101,
                filename,
                source_path,
                filename,
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
    return source_path


@contextmanager
def _submission_test_context():
    temp_dir = tempfile.TemporaryDirectory()
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "batch0-secret"
    app.config["JWT_SECRET_KEY"] = "batch0-jwt"
    app.config["ENABLE_RENDERER"] = True
    app.config["ENABLE_USDZ_CONVERSION"] = True

    db.init_app(app)
    app.project_service = MagicMock()
    app.pipeline_service = MagicMock()
    app.native_pipeline_service = MagicMock()
    app.msf_service = MagicMock()

    with app.app_context():
        db.create_all()
        user = User(email="batch0-submission@example.com", role=UserRole.USER, is_verified=True)
        user.set_password("password")
        db.session.add(user)
        db.session.commit()

        hdpc_path = os.path.join(temp_dir.name, "session.hdpc")
        source_path = _create_submission_hdpc(hdpc_path, temp_dir.name)

        session_row = DBSession(
            user_id=user.id,
            session_dir=temp_dir.name,
            hdpc_path=hdpc_path,
            status="processing",
        )
        db.session.add(session_row)
        db.session.commit()

        try:
            yield {
                "app": app,
                "user_id": user.id,
                "session_id": session_row.id,
                "hdpc_path": hdpc_path,
                "source_path": source_path,
                "temp_dir": temp_dir.name,
            }
        finally:
            db.session.remove()
            db.drop_all()
    temp_dir.cleanup()


@contextmanager
def _native_pipeline_test_context():
    temp_dir = tempfile.TemporaryDirectory()
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "batch0-native-secret"
    app.config["JWT_SECRET_KEY"] = "batch0-native-jwt"
    app.config["ENABLE_RENDERER"] = True
    app.config["ENABLE_USDZ_CONVERSION"] = True
    app.config["ENABLE_METIS_VALIDATION"] = False

    db.init_app(app)
    native_service = NativePipelineSystemService()
    app.native_pipeline_service = native_service
    app.project_service = MagicMock()
    app.fast_renderer_service = MagicMock()
    app.any_to_usdz_service = MagicMock()
    app.edm_service = MagicMock()
    app.iiif_service = MagicMock()
    app.mets_service = MagicMock()
    app.msf_service = MagicMock()

    with app.app_context():
        db.create_all()
        user = User(email="batch0-native@example.com", role=UserRole.ADMIN, is_verified=True)
        user.set_password("password")
        db.session.add(user)
        db.session.commit()

        native_service.ensure_seeded()

        session_dir = Path(temp_dir.name)
        hdpc_path = session_dir / "session.hdpc"
        source_path = _create_submission_hdpc(str(hdpc_path), temp_dir.name)
        created = create_local_record_with_metadata(
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
        record_id = int(created["local_record_db_id"])

        session_row = DBSession(
            user_id=user.id,
            session_dir=temp_dir.name,
            hdpc_path=str(hdpc_path),
            status="processing",
        )
        db.session.add(session_row)
        db.session.commit()

        try:
            yield {
                "app": app,
                "native_service": native_service,
                "session_id": session_row.id,
                "session_row": session_row,
                "source_path": source_path,
                "hdpc_path": str(hdpc_path),
                "record_id": record_id,
                "outputs_dir": str(session_dir / "outputs"),
            }
        finally:
            db.session.remove()
            db.drop_all()
    temp_dir.cleanup()


def _build_native_execution_context(context: dict, *, access_token: str | None = None) -> dict:
    outputs_dir = Path(context["outputs_dir"])
    outputs_dir.mkdir(parents=True, exist_ok=True)

    pipeline = context["native_service"].get_pipeline("render")
    steps_map = {}
    for step in deepcopy(pipeline["config"]["steps"]):
        normalized_step = dict(step)
        normalized_step["parameters"] = dict(step.get("parameters") or {})
        steps_map[normalized_step["id"]] = normalized_step

    return {
        "identifier": "render",
        "canonical_identifier": "render",
        "local_file_paths": [context["source_path"]],
        "record_ids": [context["record_id"]],
        "db_session_id": context["session_id"],
        "db_session": context["session_row"],
        "hdpc_path": context["hdpc_path"],
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
                context["record_id"],
                context["source_path"],
                {
                    "title": "Model title",
                    "description": "Model description",
                    "creators": [{"name": "Museum"}],
                },
            )
        ],
        "skipped_files": [],
        "outputs_dir": context["outputs_dir"],
        "batch_metadata_map": {},
        "shared_zenodo_metadata": {},
        "batch_shared_zenodo_metadata": {},
        "batch_item_defaults": {},
        "lod_mapping_config": None,
        "resolved_lod_msf_path": None,
        "msf_rows_by_filename": {},
        "normalized_file_id_map": {"model.glb": "101"},
        "file_id_to_relative_path": {"101": "model.glb"},
        "bundle_file_paths_by_relative": {},
        "basename_to_relative_paths": {"model.glb": ["model.glb"]},
        "relative_to_absolute_path": {"model.glb": context["source_path"]},
        "absolute_to_relative_path": {os.path.normpath(context["source_path"]): "model.glb"},
        "steps_map": steps_map,
        "access_token": access_token,
    }


def test_upload_coordinator_does_not_create_local_records_during_upload(monkeypatch, tmp_path):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "batch0-upload-secret"
    app.config["JWT_SECRET_KEY"] = "batch0-upload-jwt"
    db.init_app(app)

    session_dir = tmp_path / "session"
    uploads_dir = session_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "artifact.glb").write_text("glb", encoding="utf-8")
    msf_path = input_dir / "upload.msf.csv"
    msf_path.write_text("filename\na rtifact.glb\n".replace(" ", ""), encoding="utf-8")

    app.project_service = MagicMock()
    app.project_service.create_and_scan.return_value = {"success": True}
    app.project_service.get_file_id_map.return_value = {"artifact.glb": "101"}
    app.project_service.find_record_for_file.return_value = None

    class _FakeMSFService:
        def parse_msf_file_with_profile(self, file_path, parse_options=None):
            return pd.DataFrame([{"filename": "artifact.glb"}]), {"file_path": file_path}

        def validate_msf_against_directory(self, df, directory_files, directory_root=None):
            return SimpleNamespace(
                is_valid=True,
                matched_files=["artifact.glb"],
                implicitly_included_files=[],
                filename_column="filename",
                errors=[],
            )

        def detect_filename_column(self, df, directory_files):
            return "filename", 1.0

        def suggest_sample_row_index(self, df, filename_column):
            return 0

        def get_all_file_metadata(self, df, matched_files, filename_column):
            return {"artifact.glb": {"title": "Artifact"}}

    class _DummyTaskSelf:
        def __init__(self):
            self.states = []

        def update_state(self, state=None, meta=None):
            self.states.append({"state": state, "meta": meta})

    monkeypatch.setattr(tasks, "MSFService", _FakeMSFService)
    create_record_mock = MagicMock(side_effect=AssertionError("Upload must not create local Zenodo records"))
    monkeypatch.setattr(tasks, "create_local_record_with_metadata", create_record_mock, raising=False)

    with app.app_context():
        db.create_all()
        user = User(email="upload-coordinator@example.com", role=UserRole.USER, is_verified=True)
        user.set_password("password")
        db.session.add(user)
        db.session.flush()
        session_row = DBSession(
            user_id=user.id,
            session_dir=str(session_dir),
            hdpc_path=str(session_dir / "session.hdpc"),
            status="pending",
        )
        db.session.add(session_row)
        db.session.commit()

        result = tasks.start_upload_coordinator(
            _DummyTaskSelf(),
            session_row.id,
            None,
            str(msf_path),
            tasks.STORAGE_MODE_LOCAL,
            input_directory_path=str(input_dir),
        )

        assert result["status"] == "coordinator_completed"
        assert result["worker_group_id"] is None
        create_record_mock.assert_not_called()


def test_resume_route_does_not_requeue_placeholder_file_workers(tmp_path):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "batch0-resume-secret"
    app.config["JWT_SECRET_KEY"] = "batch0-resume-jwt"
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(session_bp, url_prefix="/api/v1/sessions")

    with app.app_context():
        db.create_all()
        user = User(email="resume@example.com", role=UserRole.USER, is_verified=True)
        user.set_password("password123")
        db.session.add(user)
        db.session.flush()

        session_row = DBSession(
            user_id=user.id,
            session_dir=str(tmp_path),
            hdpc_path=str(tmp_path / "session.hdpc"),
            status="processing",
        )
        db.session.add(session_row)
        db.session.flush()
        db.session.add_all(
            [
                File(
                    session_id=session_row.id,
                    filename="retry_failed.glb",
                    path=str(tmp_path / "retry_failed.glb"),
                    status="failed",
                ),
                File(
                    session_id=session_row.id,
                    filename="retry_pending.glb",
                    path=str(tmp_path / "retry_pending.glb"),
                    status="pending",
                ),
            ]
        )
        db.session.commit()
        session_id = session_row.id
        token = create_access_token(identity=str(user.id))

    client = app.test_client()
    response = client.post(
        f"/api/v1/sessions/{session_id}/resume",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["count"] == 2
    assert payload["data"]["worker_group_id"] is None

    with app.app_context():
        statuses = {
            row.filename: row.status
            for row in File.query.filter(File.session_id == session_id).all()
        }
        assert statuses == {
            "retry_failed.glb": "failed",
            "retry_pending.glb": "failed",
        }
        db.session.remove()
        db.drop_all()


def test_record_rerun_prefers_existing_record_ids_over_local_file_paths(monkeypatch):
    with _submission_test_context() as context:
        app = context["app"]
        app.native_pipeline_service.get_pipeline.return_value = {"config": {"steps": []}}
        app.native_pipeline_service.resolve_pipeline_identifier.return_value = "render"
        app.native_pipeline_service.execute_registered_submission.return_value = {
            "success": True,
            "summary": {"successful_count": 1, "failed_count": 0, "processed_count": 1},
            "details": [{"record_id": 1}],
            "run_id": "run-native-rerun",
        }

        with app.app_context():
            created = create_local_record_with_metadata(
                context["hdpc_path"],
                file_id=101,
                metadata={
                    "title": "Existing record",
                    "description": "Existing record description",
                    "creators": [{"name": "Museum"}],
                },
                is_sandbox=True,
                access_token="sandbox-token",
            )

            create_record_mock = MagicMock(side_effect=AssertionError("Reruns must not recreate local records"))
            monkeypatch.setattr(submission_pipeline_service, "create_local_record_with_metadata", create_record_mock)
            monkeypatch.setattr(
                submission_pipeline_service,
                "ensure_fresh_record_creation_allowed",
                lambda *args, **kwargs: None,
            )

            result = execute_submission_pipeline(
                identifier="render",
                local_file_paths=[context["source_path"]],
                db_session_id=context["session_id"],
                is_sandbox=True,
                record_ids=[created["local_record_db_id"]],
            )

            assert result["result"]["success"] is True
            create_record_mock.assert_not_called()
            execution_context = app.native_pipeline_service.execute_registered_submission.call_args.args[1]
            assert execution_context["record_ids"] == [created["local_record_db_id"]]


def _run_lod_msf_resolution_case(extension: str) -> tuple[list[str], str]:
    with _submission_test_context() as context:
        app = context["app"]
        parsed_paths = []
        candidate_path = os.path.join(context["temp_dir"], "uploads", f"upload.msf{extension}")
        with open(candidate_path, "w", encoding="utf-8") as handle:
            handle.write("filename,title\nmodel.glb,Mapped title\n")

        app.native_pipeline_service.get_pipeline.return_value = {"config": {"steps": []}}
        app.native_pipeline_service.resolve_pipeline_identifier.return_value = "render"
        app.native_pipeline_service.execute_registered_submission.return_value = {
            "success": True,
            "summary": {"successful_count": 1, "failed_count": 0, "processed_count": 1},
            "details": [{"record_id": 1}],
            "run_id": f"run-lod-{extension}",
        }

        def _parse_msf_file(path, parse_options=None):
            parsed_paths.append(path)
            return pd.DataFrame([{"filename": "model.glb", "title": "Mapped title"}]), {}

        app.msf_service.parse_msf_file.side_effect = _parse_msf_file
        app.msf_service.detect_filename_column.return_value = ("filename", 1.0)

        with app.app_context():
            db.session.add(
                UserMetadata(
                    session_id=context["session_id"],
                    field_name="zenodo_metadata_draft",
                    field_value=json.dumps(
                        {
                            "title": "Shared title",
                            "description": "Shared description",
                            "creators": [{"name": "Museum"}],
                            "lod_mapping": {
                                "zenodo": {
                                    "3d": {
                                        "title": {"source": "column", "column": "title"}
                                    }
                                }
                            },
                        }
                    ),
                )
            )
            db.session.commit()

            with patch.object(submission_pipeline_service, "ensure_fresh_record_creation_allowed", return_value=None):
                execute_submission_pipeline(
                    identifier="render",
                    local_file_paths=[context["source_path"]],
                    db_session_id=context["session_id"],
                    is_sandbox=True,
                )

        return parsed_paths, candidate_path


def test_submission_pipeline_resolves_lod_msf_candidates_for_all_supported_upload_extensions():
    for extension in (".xlsx", ".xls", ".csv"):
        parsed_paths, candidate_path = _run_lod_msf_resolution_case(extension)
        assert parsed_paths == [candidate_path]


def test_required_lod_failure_blocks_zenodo_upload():
    with _native_pipeline_test_context() as context:
        app = context["app"]
        execution_context = _build_native_execution_context(context)
        execution_context["steps_map"]["fast_renderer"]["enabled"] = False
        execution_context["steps_map"]["any_to_usdz"]["enabled"] = False
        execution_context["steps_map"]["lod_generation"]["enabled"] = True
        execution_context["steps_map"]["lod_generation"]["parameters"] = {
            "generate_edm": True,
            "generate_iiif": False,
            "generate_mets": False,
            "lod_policy": "required",
        }
        execution_context["steps_map"]["zenodo_upload"]["enabled"] = True
        execution_context["steps_map"]["zenodo_upload"]["parameters"] = {"publish": False}

        app.edm_service.generate_edm_xml_with_report.side_effect = RuntimeError("LOD generation exploded")

        with app.app_context():
            with patch("services.dataset_integrity_service.ensure_record_operation_allowed", return_value=None), patch(
                "services.native_pipeline_system.create_local_zenodo_draft",
                return_value={"success": True, "zenodo_response": {"id": 12345}},
            ), patch(
                "services.native_pipeline_system.upload_local_zenodo_files",
                return_value={"success": True},
            ) as upload_mock:
                result = context["native_service"].execute_registered_submission("render", execution_context)

        upload_mock.assert_not_called()
        assert result["summary"]["failed_count"] == 1


def test_required_lod_validation_failure_blocks_zenodo_upload():
    with _native_pipeline_test_context() as context:
        app = context["app"]
        execution_context = _build_native_execution_context(context)
        execution_context["steps_map"]["fast_renderer"]["enabled"] = False
        execution_context["steps_map"]["any_to_usdz"]["enabled"] = False
        execution_context["steps_map"]["lod_generation"]["enabled"] = True
        execution_context["steps_map"]["lod_generation"]["parameters"] = {
            "generate_edm": True,
            "generate_iiif": False,
            "generate_mets": False,
            "lod_policy": "required",
        }
        execution_context["steps_map"]["zenodo_upload"]["enabled"] = True
        execution_context["steps_map"]["zenodo_upload"]["parameters"] = {"publish": False}

        app.edm_service.generate_edm_xml_with_report.return_value = {
            "content": "<rdf:RDF />",
            "minimum_viable_applied": False,
        }
        app.edm_service.validate_edm_document.return_value = {
            "valid": False,
            "errors": ["[Local EDM Validator] missing edm:rights"],
            "warnings": [],
        }

        with app.app_context():
            with patch("services.dataset_integrity_service.ensure_record_operation_allowed", return_value=None), patch(
                "services.native_pipeline_system.create_local_zenodo_draft",
                return_value={"success": True, "zenodo_response": {"id": 12345}},
            ), patch(
                "services.native_pipeline_system.upload_local_zenodo_files",
                return_value={"success": True},
            ) as upload_mock:
                result = context["native_service"].execute_registered_submission("render", execution_context)

        upload_mock.assert_not_called()
        assert result["summary"]["failed_count"] == 1
        assert result["details"][0]["edm"]["status"] == "failed_required"
        assert "EDM validation failed" in result["details"][0]["error"]


def test_native_zenodo_helpers_receive_resolved_access_token():
    with _native_pipeline_test_context() as context:
        execution_context = _build_native_execution_context(context, access_token="resolved-session-token")
        execution_context["steps_map"]["fast_renderer"]["enabled"] = False
        execution_context["steps_map"]["any_to_usdz"]["enabled"] = False
        execution_context["steps_map"]["lod_generation"]["enabled"] = False
        execution_context["steps_map"]["zenodo_upload"]["enabled"] = True
        execution_context["steps_map"]["zenodo_upload"]["parameters"] = {"publish": False}

        with context["app"].app_context():
            with patch("services.dataset_integrity_service.ensure_record_operation_allowed", return_value=None), patch(
                "services.native_pipeline_system.create_local_zenodo_draft",
                return_value={"success": True, "zenodo_response": {"id": 12345}},
            ) as draft_mock, patch(
                "services.native_pipeline_system.upload_local_zenodo_files",
                return_value={"success": True},
            ) as upload_mock:
                result = context["native_service"].execute_registered_submission("render", execution_context)

        assert result["success"] is True
        draft_mock.assert_called_once_with(
            context["hdpc_path"],
            context["record_id"],
            access_token="resolved-session-token",
        )
        upload_mock.assert_called_once_with(
            context["hdpc_path"],
            context["record_id"],
            publish=False,
            prune_inherited_files=False,
            access_token="resolved-session-token",
        )
