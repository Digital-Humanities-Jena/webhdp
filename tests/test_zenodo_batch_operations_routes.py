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
from routes.tools_routes import tools_bp


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
                f"hash-{record['file_id']}",
            ),
        )
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
                json.dumps(record["metadata"]),
                str(record.get("zenodo_record_id") or "") or None,
                record.get("concept_rec_id"),
                record.get("zenodo_doi"),
                1 if record.get("is_sandbox") else 0,
                record.get("created_timestamp", "2026-03-10T10:00:00Z"),
                record.get("updated_timestamp", "2026-03-10T10:05:00Z"),
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
                "uploaded",
                "2026-03-10T10:05:00Z",
                source_path,
            ),
        )

    conn.commit()
    conn.close()


class _DummyProjectService:
    def _translate_path(self, path, to_container=False):
        return path


@pytest.fixture()
def zenodo_batch_app():
    temp_dir = tempfile.mkdtemp(prefix="zenodo-batch-tools-")
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
    app.project_service = _DummyProjectService()
    setup_error_handlers(app)

    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(session_bp, url_prefix="/api/v1/sessions")
    app.register_blueprint(tools_bp, url_prefix="/api/v1/tools")

    with app.app_context():
        db.create_all()
        moderator = User(email="mod@example.com", role=UserRole.MODERATOR, is_verified=True)
        moderator.set_password("password123")
        regular = User(email="user@example.com", role=UserRole.USER, is_verified=True)
        regular.set_password("password123")
        db.session.add(moderator)
        db.session.add(regular)
        db.session.commit()

        hdpc_one = os.path.join(temp_dir, "session1.hdpc")
        _create_hdpc(
            hdpc_one,
            [
                {
                    "record_id": 1,
                    "file_id": 101,
                    "title": "Draft Alpha",
                    "status": "draft",
                    "source_path": os.path.join(temp_dir, "dataset_a", "draft_alpha.glb"),
                    "zenodo_record_id": "9001",
                    "zenodo_doi": "10.5072/zenodo.9001",
                    "is_sandbox": True,
                    "metadata": {
                        "id": 9001,
                        "metadata": {
                            "title": "Draft Alpha",
                            "creators": [{"name": "Ada Curator"}],
                            "communities": [{"identifier": "alpha"}],
                            "publication_date": "2026-03-10",
                        },
                        "links": {
                            "self": "https://sandbox.zenodo.org/api/deposit/depositions/9001",
                            "publish": "https://sandbox.zenodo.org/api/deposit/depositions/9001/actions/publish",
                            "html": "https://sandbox.zenodo.org/records/9001",
                        },
                    },
                },
                {
                    "record_id": 2,
                    "file_id": 102,
                    "title": "Published Beta",
                    "status": "published",
                    "source_path": os.path.join(temp_dir, "dataset_a", "published_beta.glb"),
                    "zenodo_record_id": "9002",
                    "concept_rec_id": "7002",
                    "zenodo_doi": "10.5281/zenodo.9002",
                    "is_sandbox": False,
                    "metadata": {
                        "id": 9002,
                        "conceptrecid": "7002",
                        "doi": "10.5281/zenodo.9002",
                        "metadata": {
                            "title": "Published Beta",
                            "creators": [{"name": "Ada Curator"}],
                            "communities": [{"identifier": "beta"}, {"identifier": "gamma"}],
                            "publication_date": "2026-03-12",
                        },
                        "links": {
                            "html": "https://zenodo.org/records/9002",
                            "edit": "https://zenodo.org/api/deposit/depositions/9002/actions/edit",
                        },
                    },
                },
            ],
        )
        db.session.add(DBSession(user_id=moderator.id, session_dir=temp_dir, hdpc_path=hdpc_one, status="completed"))

        hdpc_two = os.path.join(temp_dir, "session2.hdpc")
        _create_hdpc(
            hdpc_two,
            [
                {
                    "record_id": 10,
                    "file_id": 201,
                    "title": "Published No Edit",
                    "status": "published",
                    "source_path": os.path.join(temp_dir, "dataset_b", "published_no_edit.glb"),
                    "zenodo_record_id": "9010",
                    "concept_rec_id": "7010",
                    "zenodo_doi": "10.5281/zenodo.9010",
                    "is_sandbox": False,
                    "metadata": {
                        "id": 9010,
                        "conceptrecid": "7010",
                        "doi": "10.5281/zenodo.9010",
                        "metadata": {
                            "title": "Published No Edit",
                            "creators": [{"name": "Bruno Curator"}],
                            "communities": [{"identifier": "delta"}],
                            "publication_date": "2026-03-14",
                        },
                        "links": {
                            "html": "https://zenodo.org/records/9010",
                        },
                    },
                }
            ],
        )
        db.session.add(DBSession(user_id=regular.id, session_dir=temp_dir, hdpc_path=hdpc_two, status="completed"))
        db.session.commit()

        moderator_token = create_access_token(identity=str(moderator.id))
        user_token = create_access_token(identity=str(regular.id))

    return app, moderator_token, user_token


def test_zenodo_batch_records_route_groups_and_filters(zenodo_batch_app):
    app, moderator_token, _ = zenodo_batch_app
    client = app.test_client()

    response = client.get(
        "/api/v1/tools/zenodo-batch-operations/records?creator=ada&community=alpha",
        headers={"Authorization": f"Bearer {moderator_token}"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["summary"]["records_filtered"] == 1
    assert len(payload["data"]["groups"]) == 1

    record = payload["data"]["groups"][0]["records"][0]
    assert record["record_title"] == "Draft Alpha"
    assert record["creators_normalized"] == ["Ada Curator"]
    assert record["communities_normalized"] == ["alpha"]
    assert record["operation_eligibility"]["append_if_missing"]["eligible"] is True
    assert record["operation_eligibility"]["remove_all"]["eligible"] is True


def test_zenodo_batch_records_route_forbids_regular_users(zenodo_batch_app):
    app, _, user_token = zenodo_batch_app
    client = app.test_client()

    response = client.get(
        "/api/v1/tools/zenodo-batch-operations/records",
        headers={"Authorization": f"Bearer {user_token}"},
    )

    assert response.status_code == 403


def test_launch_zenodo_batch_operation_counts_eligible_records(monkeypatch, zenodo_batch_app):
    app, moderator_token, _ = zenodo_batch_app
    client = app.test_client()

    class _DummyTask:
        id = "task-123"

    dummy_tasks = types.SimpleNamespace(
        execute_zenodo_batch_community_operation=types.SimpleNamespace(delay=lambda **kwargs: _DummyTask())
    )
    monkeypatch.setitem(sys.modules, "tasks", dummy_tasks)

    response = client.post(
        "/api/v1/tools/zenodo-batch-operations/community-operations",
        headers={"Authorization": f"Bearer {moderator_token}"},
        json={
            "operation": "append_if_missing",
            "community_identifier": "omega",
            "record_refs": [
                {"session_id": 1, "local_record_id": 1},
                {"session_id": 2, "local_record_id": 10},
            ],
        },
    )

    assert response.status_code == 202
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["task_id"] == "task-123"
    assert payload["data"]["selected_count"] == 2
    assert payload["data"]["eligible_count"] == 1
    assert payload["data"]["ineligible_count"] == 1


def test_zenodo_batch_task_status_route(monkeypatch, zenodo_batch_app):
    app, moderator_token, _ = zenodo_batch_app
    client = app.test_client()

    class _DummyAsyncResult:
        state = "SUCCESS"
        result = {
            "status": "completed",
            "progress": {"total_records": 2, "processed": 2, "percent": 100},
            "results": [{"session_id": 1, "local_record_id": 1, "status": "succeeded"}],
        }
        info = result

    dummy_module = types.SimpleNamespace(celery=types.SimpleNamespace(AsyncResult=lambda task_id: _DummyAsyncResult()))
    monkeypatch.setitem(sys.modules, "celery_app", dummy_module)

    response = client.get(
        "/api/v1/tools/zenodo-batch-operations/tasks/task-123",
        headers={"Authorization": f"Bearer {moderator_token}"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data"]["state"] == "SUCCESS"
    assert payload["data"]["result"]["results"][0]["status"] == "succeeded"


def test_zenodo_batch_history_route_returns_persisted_runs(monkeypatch, zenodo_batch_app):
    app, moderator_token, _ = zenodo_batch_app
    client = app.test_client()

    class _DummyTask:
        id = "task-123"

    dummy_tasks = types.SimpleNamespace(
        execute_zenodo_batch_community_operation=types.SimpleNamespace(delay=lambda **kwargs: _DummyTask())
    )
    monkeypatch.setitem(sys.modules, "tasks", dummy_tasks)

    response = client.post(
        "/api/v1/tools/zenodo-batch-operations/community-operations",
        headers={"Authorization": f"Bearer {moderator_token}"},
        json={
            "operation": "append_if_missing",
            "community_identifier": "omega",
            "record_refs": [{"session_id": 1, "local_record_id": 1}],
        },
    )

    assert response.status_code == 202

    history_response = client.get(
        "/api/v1/tools/zenodo-batch-operations/history",
        headers={"Authorization": f"Bearer {moderator_token}"},
    )

    assert history_response.status_code == 200
    payload = history_response.get_json()
    assert payload["data"]["tasks"][0]["task_id"] == "task-123"
    assert payload["data"]["tasks"][0]["operation"] == "append_if_missing"
    assert payload["data"]["tasks"][0]["selected_count"] == 1
    assert payload["data"]["tasks"][0]["requested_by"]["email"] == "mod@example.com"


def test_zenodo_batch_task_status_uses_persisted_history_when_celery_is_pending(monkeypatch, zenodo_batch_app):
    app, moderator_token, _ = zenodo_batch_app
    client = app.test_client()

    class _DummyTask:
        id = "task-123"

    queue_module = types.SimpleNamespace(
        execute_zenodo_batch_community_operation=types.SimpleNamespace(delay=lambda **kwargs: _DummyTask())
    )
    monkeypatch.setitem(sys.modules, "tasks", queue_module)

    queue_response = client.post(
        "/api/v1/tools/zenodo-batch-operations/community-operations",
        headers={"Authorization": f"Bearer {moderator_token}"},
        json={
            "operation": "append_if_missing",
            "community_identifier": "omega",
            "record_refs": [{"session_id": 1, "local_record_id": 1}],
        },
    )

    assert queue_response.status_code == 202

    class _PendingAsyncResult:
        state = "PENDING"
        result = None
        info = None

    dummy_celery = types.SimpleNamespace(celery=types.SimpleNamespace(AsyncResult=lambda task_id: _PendingAsyncResult()))
    monkeypatch.setitem(sys.modules, "celery_app", dummy_celery)

    task_response = client.get(
        "/api/v1/tools/zenodo-batch-operations/tasks/task-123",
        headers={"Authorization": f"Bearer {moderator_token}"},
    )

    assert task_response.status_code == 200
    payload = task_response.get_json()
    assert payload["data"]["state"] == "PENDING"
    assert payload["data"]["progress"]["total_records"] == 1
    assert payload["data"]["status"] == "Queued Zenodo community operation"
