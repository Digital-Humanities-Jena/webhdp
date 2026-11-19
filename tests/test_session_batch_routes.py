import json
import os
import sqlite3
import sys
import tempfile
import types

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import Session as DBSession, User, UserRole
from middleware import setup_error_handlers
from routes.session_routes import session_bp
from services.session_batch_history_service import get_task_entry
from services.zenodo_credential_service import ZenodoCredentialService


def _build_batch_hdpc(path: str, root_dir: str) -> None:
    uploads_dir = os.path.join(root_dir, "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    prepared_path = os.path.join(uploads_dir, "prepared.glb")
    draft_path = os.path.join(uploads_dir, "draft.glb")
    for file_path in (prepared_path, draft_path):
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write("glb")

    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE project_info (
            project_id INTEGER PRIMARY KEY,
            project_name TEXT,
            project_short_code TEXT,
            description TEXT,
            creation_timestamp TEXT,
            last_modified_timestamp TEXT,
            hdpc_schema_version TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE source_files (
            file_id INTEGER PRIMARY KEY,
            project_id INTEGER,
            absolute_path TEXT,
            relative_path TEXT,
            filename TEXT,
            size_bytes INTEGER,
            sha256_hash TEXT,
            mime_type TEXT,
            file_type TEXT,
            parent_file_id INTEGER,
            status TEXT,
            added_timestamp TEXT,
            last_processed_timestamp TEXT,
            error_message TEXT,
            is_primary_source INTEGER,
            pipeline_source TEXT,
            step_source TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE zenodo_records (
            record_id INTEGER PRIMARY KEY,
            project_id INTEGER,
            source_file_id INTEGER,
            record_title TEXT,
            record_status TEXT,
            record_metadata_json TEXT,
            zenodo_record_id TEXT,
            concept_rec_id TEXT,
            zenodo_doi TEXT,
            concept_doi TEXT,
            is_sandbox INTEGER,
            created_timestamp TEXT,
            last_updated_timestamp TEXT,
            version TEXT,
            last_api_error TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE record_files_map (
            map_id INTEGER PRIMARY KEY,
            record_id INTEGER,
            file_id INTEGER,
            file_path TEXT,
            file_purpose TEXT,
            zenodo_file_id TEXT,
            zenodo_file_key TEXT,
            zenodo_file_checksum TEXT,
            zenodo_file_size INTEGER,
            zenodo_file_links_json TEXT,
            upload_status TEXT,
            upload_timestamp TEXT,
            upload_error TEXT,
            upload_response_json TEXT
        )
        """
    )
    cursor.execute(
        """
        INSERT INTO project_info (
            project_id, project_name, project_short_code, description,
            creation_timestamp, last_modified_timestamp, hdpc_schema_version
        ) VALUES (1, 'Batch Fixture', 'BATCH', 'Batch route fixture', '2026-03-29T09:00:00Z', '2026-03-29T09:05:00Z', '1.2.0')
        """
    )
    cursor.executemany(
        """
        INSERT INTO source_files (
            file_id, project_id, absolute_path, relative_path, filename, size_bytes,
            sha256_hash, mime_type, file_type, parent_file_id, status, added_timestamp,
            last_processed_timestamp, error_message, is_primary_source, pipeline_source, step_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (101, 1, prepared_path, "prepared.glb", "prepared.glb", 100, "hash-prepared", "model/gltf-binary", "primary_source", None, "ready", "2026-03-29T09:00:00Z", "2026-03-29T09:00:00Z", None, 1, "scan", "bootstrap"),
            (102, 1, draft_path, "draft.glb", "draft.glb", 100, "hash-draft", "model/gltf-binary", "primary_source", None, "ready", "2026-03-29T09:01:00Z", "2026-03-29T09:01:00Z", None, 1, "scan", "bootstrap"),
        ],
    )
    cursor.executemany(
        """
        INSERT INTO zenodo_records (
            record_id, project_id, source_file_id, record_title, record_status,
            record_metadata_json, zenodo_record_id, concept_rec_id, zenodo_doi, concept_doi,
            is_sandbox, created_timestamp, last_updated_timestamp, version, last_api_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                1,
                1,
                101,
                "Prepared Alpha",
                "prepared",
                json.dumps({"metadata": {"title": "Prepared Alpha"}}),
                None,
                None,
                None,
                None,
                1,
                "2026-03-29T09:10:00Z",
                "2026-03-29T09:10:00Z",
                "1.0.0",
                None,
            ),
            (
                2,
                1,
                102,
                "Draft Beta",
                "draft",
                json.dumps(
                    {
                        "id": 9002,
                        "metadata": {"title": "Draft Beta", "communities": [{"identifier": "alpha"}]},
                        "links": {"html": "https://sandbox.zenodo.org/records/9002"},
                    }
                ),
                "9002",
                "7002",
                None,
                None,
                1,
                "2026-03-29T09:11:00Z",
                "2026-03-29T09:11:00Z",
                "1.0.0",
                None,
            ),
        ],
    )
    cursor.execute(
        """
        INSERT INTO record_files_map (
            map_id, record_id, file_id, file_path, file_purpose, upload_status, upload_timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (1, 2, 102, draft_path, "main", "pending", None),
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def session_batch_app():
    temp_dir = tempfile.mkdtemp(prefix="session-batch-routes-")
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "session-batch-testing"
    app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
    app.project_service = types.SimpleNamespace()
    setup_error_handlers(app)

    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(session_bp, url_prefix="/api/v1/sessions")

    with app.app_context():
        db.create_all()
        owner = User(email="owner@example.com", role=UserRole.USER, is_verified=True)
        owner.set_password("password123")
        moderator = User(email="mod@example.com", role=UserRole.MODERATOR, is_verified=True)
        moderator.set_password("password123")
        db.session.add(owner)
        db.session.add(moderator)
        db.session.commit()
        ZenodoCredentialService().upsert_credential(
            owner_type="user", owner_id=owner.id, environment="sandbox",
            token="test-sandbox-token", actor_user_id=owner.id,
        )

        hdpc_path = os.path.join(temp_dir, "session.hdpc")
        _build_batch_hdpc(hdpc_path, temp_dir)
        session_row = DBSession(user_id=owner.id, session_dir=temp_dir, hdpc_path=hdpc_path, status="completed")
        db.session.add(session_row)
        db.session.commit()
        session_id = session_row.id

        owner_token = create_access_token(identity=str(owner.id))
        moderator_token = create_access_token(identity=str(moderator.id))

    return app, temp_dir, owner_token, moderator_token, session_id


def test_session_batch_launch_and_history_routes(monkeypatch, session_batch_app):
    app, _, owner_token, _, session_id = session_batch_app
    client = app.test_client()

    class _DummyTask:
        id = "batch-task-1"

    dummy_tasks = types.SimpleNamespace(
        execute_session_batch_operation_task=types.SimpleNamespace(delay=lambda **kwargs: _DummyTask())
    )
    monkeypatch.setitem(sys.modules, "tasks", dummy_tasks)

    response = client.post(
        f"/api/v1/sessions/{session_id}/batch-operations",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"operation_type": "upload_files"},
    )

    assert response.status_code == 202
    payload = response.get_json()["data"]
    assert payload["task_id"] == "batch-task-1"
    assert payload["target_ids"] == [2]

    history_response = client.get(
        f"/api/v1/sessions/{session_id}/batch-operations",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert history_response.status_code == 200
    tasks = history_response.get_json()["data"]["tasks"]
    assert tasks[0]["task_id"] == "batch-task-1"
    with app.app_context():
        assert get_task_entry("batch-task-1")["operation_type"] == "upload_files"


def test_session_batch_history_launch_is_idempotent(session_batch_app):
    app, _, _, _, session_id = session_batch_app

    with app.app_context():
        from services.session_batch_history_service import record_task_launch, update_task_entry

        record_task_launch(
            task_id="duplicate-launch-task",
            session_id=session_id,
            operation_type="discard_drafts",
            target_ids=[2],
            options={},
            requested_by_user_id=1,
            requested_by_email="owner@example.com",
        )
        record_task_launch(
            task_id="duplicate-launch-task",
            session_id=session_id,
            operation_type="discard_drafts",
            target_ids=[2],
            options={},
            requested_by_user_id=1,
            requested_by_email="owner@example.com",
        )
        update_task_entry(
            "duplicate-launch-task",
            state="SUCCESS",
            result={
                "status": "completed",
                "summary": {"total_items": 1, "completed": 1, "skipped": 0, "failed": 0},
                "progress": {"total_items": 1, "processed": 1, "completed": 1, "skipped": 0, "failed": 0, "percent": 100},
            },
        )

        entry = get_task_entry("duplicate-launch-task")
        assert entry["state"] == "SUCCESS"
        assert entry["summary"]["completed"] == 1


def test_session_batch_task_status_route(monkeypatch, session_batch_app):
    app, _, owner_token, _, session_id = session_batch_app
    client = app.test_client()

    with app.app_context():
        from services.session_batch_history_service import record_task_launch

        record_task_launch(
            task_id="batch-task-2",
            session_id=session_id,
            operation_type="create_drafts",
            target_ids=[1],
            options={},
            requested_by_user_id=1,
            requested_by_email="owner@example.com",
        )

    class _DummyAsyncResult:
        state = "SUCCESS"
        result = {
            "status": "completed",
            "progress": {"total_items": 1, "processed": 1, "completed": 1, "skipped": 0, "failed": 0, "percent": 100},
            "results": [{"target_id": 1, "status": "completed", "result_code": "completed"}],
            "summary": {"total_items": 1, "completed": 1, "skipped": 0, "failed": 0},
        }
        info = result

    dummy_celery = types.SimpleNamespace(celery=types.SimpleNamespace(AsyncResult=lambda task_id: _DummyAsyncResult()))
    monkeypatch.setitem(sys.modules, "celery_app", dummy_celery)

    response = client.get(
        f"/api/v1/sessions/{session_id}/batch-operations/batch-task-2",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["state"] == "SUCCESS"
    assert payload["result"]["summary"]["completed"] == 1
