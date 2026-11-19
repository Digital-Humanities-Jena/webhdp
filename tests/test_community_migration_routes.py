import json
import os
import sqlite3
import sys
import tempfile
import types

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import Session as DBSession, User, UserRole
from middleware import setup_error_handlers
from routes.tools_routes import tools_bp
from services.community_migration_service import CommunityMigrationService
from services.zenodo_account_retrieval_history_service import record_retrieval_launch, update_retrieval_entry


def _create_hdpc(path, records):
    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE zenodo_records (
            record_id INTEGER PRIMARY KEY,
            record_title TEXT,
            record_status TEXT,
            record_metadata_json TEXT,
            zenodo_record_id TEXT,
            concept_rec_id TEXT,
            zenodo_doi TEXT,
            created_timestamp TEXT,
            last_updated_timestamp TEXT,
            record_origin TEXT
        )
        """
    )
    for record in records:
        cursor.execute(
            """
            INSERT INTO zenodo_records (
                record_id, record_title, record_status, record_metadata_json, zenodo_record_id,
                concept_rec_id, zenodo_doi, created_timestamp, last_updated_timestamp, record_origin
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["record_id"],
                record["title"],
                record["status"],
                json.dumps(record["metadata"]),
                record.get("zenodo_record_id"),
                record.get("concept_rec_id"),
                record.get("doi"),
                record.get("created", "2026-03-01T00:00:00Z"),
                record.get("modified", "2026-03-01T00:00:00Z"),
                "zenodo_retrieval",
            ),
        )
    conn.commit()
    conn.close()


class _ProjectService:
    def __init__(self):
        self.append_tokens = []
        self.remove_tokens = []

    def _set_communities(self, hdpc_path, local_record_id, communities):
        conn = sqlite3.connect(hdpc_path)
        try:
            row = conn.execute(
                "SELECT record_metadata_json FROM zenodo_records WHERE record_id = ?",
                (int(local_record_id),),
            ).fetchone()
            payload = json.loads(row[0] or "{}")
            payload.setdefault("metadata", {})["communities"] = [{"identifier": item} for item in communities]
            conn.execute(
                "UPDATE zenodo_records SET record_metadata_json = ? WHERE record_id = ?",
                (json.dumps(payload), int(local_record_id)),
            )
            conn.commit()
        finally:
            conn.close()

    def append_community_to_record(self, **kwargs):
        self.append_tokens.append(kwargs.get("access_token"))
        self._set_communities(kwargs["hdpc_path"], kwargs["local_record_id"], ["alpha", "beta"])
        return {
            "success": True,
            "result": {
                "status": "succeeded",
                "message": "appended",
                "communities_after": ["alpha", "beta"],
            },
        }

    def remove_community_from_record(self, **kwargs):
        self.remove_tokens.append(kwargs.get("access_token"))
        self._set_communities(kwargs["hdpc_path"], kwargs["local_record_id"], ["beta"])
        return {
            "success": True,
            "result": {
                "status": "succeeded",
                "message": "removed",
                "communities_after": ["beta"],
            },
        }


def _build_app():
    temp_dir = tempfile.mkdtemp(prefix="community-migration-")
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
    app.project_service = _ProjectService()
    setup_error_handlers(app)
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(tools_bp, url_prefix="/api/v1/tools")
    with app.app_context():
        db.create_all()
        moderator = User(email="mod@example.com", role=UserRole.MODERATOR, is_verified=True)
        moderator.set_password("password123")
        user = User(email="user@example.com", role=UserRole.USER, is_verified=True)
        user.set_password("password123")
        db.session.add_all([moderator, user])
        db.session.commit()

        hdpc_path = os.path.join(temp_dir, "retrieval.hdpc")
        _create_hdpc(
            hdpc_path,
            [
                {
                    "record_id": 1,
                    "title": "Editable source only",
                    "status": "published",
                    "zenodo_record_id": "1001",
                    "metadata": {
                        "metadata": {"title": "Editable source only", "communities": [{"identifier": "alpha"}]},
                        "webhdp_retrieval": {"capabilities": {"had_edit_rights": True}},
                    },
                },
                {
                    "record_id": 2,
                    "title": "Already target",
                    "status": "published",
                    "zenodo_record_id": "1002",
                    "metadata": {
                        "metadata": {"title": "Already target", "communities": [{"identifier": "alpha"}, {"identifier": "beta"}]},
                        "webhdp_retrieval": {"capabilities": {"had_edit_rights": True}},
                    },
                },
                {
                    "record_id": 3,
                    "title": "No edit link",
                    "status": "published",
                    "zenodo_record_id": "1003",
                    "metadata": {
                        "metadata": {"title": "No edit link", "communities": [{"identifier": "alpha"}]},
                        "webhdp_retrieval": {"capabilities": {"had_edit_rights": False}},
                    },
                },
            ],
        )
        session = DBSession(
            user_id=moderator.id,
            session_dir=temp_dir,
            hdpc_path=hdpc_path,
            status="completed",
            default_zenodo_environment="production",
            publishing_user_id=moderator.id,
        )
        db.session.add(session)
        db.session.commit()
        record_retrieval_launch(
            retrieval_id="retrieval-1",
            task_id=None,
            credential_id=1,
            environment="production",
            requested_by_user_id=moderator.id,
            requested_by_email=moderator.email,
            credential_summary={"credential_id": 1},
        )
        update_retrieval_entry(
            "retrieval-1",
            state="SUCCESS",
            summary={"retrieved_records": 3},
            manifest={"shards": [{"session_id": session.id, "hdpc_path": hdpc_path, "shard_index": 1}]},
        )
        moderator_token = create_access_token(identity=str(moderator.id))
        user_token = create_access_token(identity=str(user.id))
    return app, moderator_token, user_token


def test_community_migration_plan_counts_candidates():
    app, moderator_token, _ = _build_app()
    client = app.test_client()

    response = client.post(
        "/api/v1/tools/community-migrations/plan",
        headers={"Authorization": f"Bearer {moderator_token}"},
        json={
            "source_retrieval_id": "retrieval-1",
            "source_community": "alpha",
            "target_community": "beta",
            "filters": {"editable_only": False},
        },
    )

    assert response.status_code == 200
    summary = response.get_json()["data"]["summary"]
    data = response.get_json()["data"]
    assert summary["total_records"] == 3
    assert summary["editable"] == 2
    assert summary["ineligible"] == 1
    assert summary["already_in_target"] == 1
    assert summary["append_needed"] == 1
    assert summary["target_acceptance_policy"] == "direct"
    assert summary["target_owner_token_required"] is False
    assert summary["target_owner_token_status"] == "Not required"
    assert summary["credential_strategy"] == "source_record_edit_token"
    assert data["plan_checksum"]
    assert summary["plan_checksum"] == data["plan_checksum"]


def test_community_migration_forbids_regular_users():
    app, _, user_token = _build_app()
    client = app.test_client()

    response = client.get(
        "/api/v1/tools/community-migrations/context",
        headers={"Authorization": f"Bearer {user_token}"},
    )

    assert response.status_code == 403


def test_community_migration_validates_required_fields():
    app, moderator_token, _ = _build_app()
    client = app.test_client()

    response = client.post(
        "/api/v1/tools/community-migrations/plan",
        headers={"Authorization": f"Bearer {moderator_token}"},
        json={"source_retrieval_id": "retrieval-1", "source_community": "alpha"},
    )

    assert response.status_code == 400


def test_community_migration_validates_dates_cleanly():
    app, moderator_token, _ = _build_app()
    client = app.test_client()

    response = client.post(
        "/api/v1/tools/community-migrations/plan",
        headers={"Authorization": f"Bearer {moderator_token}"},
        json={
            "source_retrieval_id": "retrieval-1",
            "source_community": "alpha",
            "target_community": "beta",
            "filters": {"created_from": "not-a-date"},
        },
    )

    assert response.status_code == 400
    assert "created_from" in response.get_json()["error"]["message"]


def test_community_migration_date_filters_use_iso_dates():
    app, moderator_token, _ = _build_app()
    client = app.test_client()

    response = client.post(
        "/api/v1/tools/community-migrations/plan",
        headers={"Authorization": f"Bearer {moderator_token}"},
        json={
            "source_retrieval_id": "retrieval-1",
            "source_community": "alpha",
            "target_community": "beta",
            "filters": {"created_from": "2026-03-02", "editable_only": False},
        },
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["summary"]["total_records"] == 0


def test_community_migration_rejects_stale_plan_checksum():
    app, moderator_token, _ = _build_app()
    client = app.test_client()

    response = client.post(
        "/api/v1/tools/community-migrations/jobs",
        headers={"Authorization": f"Bearer {moderator_token}"},
        json={
            "source_retrieval_id": "retrieval-1",
            "source_community": "alpha",
            "target_community": "beta",
            "filters": {"editable_only": True},
            "plan_checksum": "stale-plan-checksum",
        },
    )

    assert response.status_code == 400
    assert "changed since dry-run" in response.get_json()["error"]["message"]


def test_community_migration_job_queues_task(monkeypatch):
    app, moderator_token, _ = _build_app()
    client = app.test_client()

    class _Task:
        id = "community-migration-task-1"

    monkeypatch.setitem(
        sys.modules,
        "tasks",
        types.SimpleNamespace(execute_community_migration_job=types.SimpleNamespace(delay=lambda **kwargs: _Task())),
    )

    plan_response = client.post(
        "/api/v1/tools/community-migrations/plan",
        headers={"Authorization": f"Bearer {moderator_token}"},
        json={
            "source_retrieval_id": "retrieval-1",
            "source_community": "alpha",
            "target_community": "beta",
            "filters": {"editable_only": True},
        },
    )
    plan_checksum = plan_response.get_json()["data"]["plan_checksum"]

    response = client.post(
        "/api/v1/tools/community-migrations/jobs",
        headers={"Authorization": f"Bearer {moderator_token}"},
        json={
            "source_retrieval_id": "retrieval-1",
            "source_community": "alpha",
            "target_community": "beta",
            "filters": {"editable_only": True},
            "plan_checksum": plan_checksum,
        },
    )

    assert response.status_code == 202
    data = response.get_json()["data"]
    assert data["task_id"] == "community-migration-task-1"
    assert data["summary"]["total_records"] == 2


def test_community_migration_execution_removes_source_only_after_target_verified():
    app, moderator_token, _ = _build_app()
    with app.app_context():
        user = User.query.filter_by(email="mod@example.com").first()
        service = CommunityMigrationService()
        job = service.create_job(
            user=user,
            source_retrieval_id="retrieval-1",
            source_community="alpha",
            target_community="beta",
            filters={"editable_only": True},
            options={"remove_source_after_verify": True},
        )
        result = service.execute_job(job.public_id)

    assert result["state"] == "SUCCESS"
    assert result["summary"]["source_removed"] == 2
    assert all(record["final_status"] == "succeeded" for record in result["records"])


def test_community_migration_direct_target_uses_source_record_token_without_target_owner_token():
    app, moderator_token, _ = _build_app()
    with app.app_context():
        user = User.query.filter_by(email="mod@example.com").first()
        service = CommunityMigrationService()
        service.publishing_context_service = types.SimpleNamespace(
            resolve_token_for_session=lambda session, environment, **kwargs: {
                "token": "source-record-edit-token",
                "source": "user",
                "owner_type": "user",
            }
        )
        job = service.create_job(
            user=user,
            source_retrieval_id="retrieval-1",
            source_community="alpha",
            target_community="beta",
            filters={"editable_only": True},
            options={"target_acceptance_policy": "direct"},
        )
        result = service.execute_job(job.public_id)

    assert result["state"] == "SUCCESS"
    assert result["summary"]["target_owner_token_required"] is False
    assert result["summary"]["target_acceptance_policy"] == "direct"
    assert app.project_service.append_tokens == ["source-record-edit-token"]
