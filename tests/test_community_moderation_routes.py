import sys
import types

import pytest
pytest.importorskip("flask_jwt_extended")
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import Institution, InstitutionMembership, InstitutionRole, InstitutionZenodoCommunity, User, UserRole
from middleware import setup_error_handlers
from routes.session_routes import session_bp
from routes.tools_routes import tools_bp


def _sample_queue(community_identifier="3dbigdataspace"):
    return {
        "community": {
            "id": "community-1",
            "slug": community_identifier,
            "title": "3D Big Data Space",
            "identifier_used": community_identifier,
            "links": {
                "self": f"https://zenodo.org/api/communities/{community_identifier}",
                "self_html": f"https://zenodo.org/communities/{community_identifier}/",
                "requests": f"https://zenodo.org/api/communities/{community_identifier}/requests",
            },
        },
        "requests": [
            {
                "request_id": "req-1",
                "number": "1",
                "title": "Alpha ingestion",
                "type": "community-submission",
                "status": "submitted",
                "created": "2026-03-20T10:00:00+00:00",
                "updated": "2026-03-21T10:00:00+00:00",
                "topic_record": "record-1",
                "created_by": {"user": "42"},
                "receiver": {"user": "7"},
                "links": {"self": "https://zenodo.org/api/requests/req-1", "actions": {"accept": "a", "decline": "d"}},
                "is_open": True,
                "is_actionable": True,
            },
            {
                "request_id": "req-2",
                "number": "2",
                "title": "Beta inclusion",
                "type": "inclusion-request",
                "status": "submitted",
                "created": "2026-03-22T10:00:00+00:00",
                "updated": "2026-03-23T10:00:00+00:00",
                "topic_record": "record-2",
                "created_by": {"user": "43"},
                "receiver": {"user": "7"},
                "links": {"self": "https://zenodo.org/api/requests/req-2", "actions": {"accept": "a", "decline": "d"}},
                "is_open": True,
                "is_actionable": True,
            },
        ],
        "open_count": 2,
    }


@pytest.fixture()
def community_moderation_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
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
        db.session.flush()

        institution = Institution(name="Museum Network", slug="museum-network", created_by_user_id=moderator.id)
        db.session.add(institution)
        db.session.flush()
        db.session.add(
            InstitutionMembership(
                institution_id=institution.id,
                user_id=moderator.id,
                role=InstitutionRole.OWNER,
            )
        )
        db.session.add_all(
            [
                InstitutionZenodoCommunity(
                    institution_id=institution.id,
                    identifier="moderation-a",
                    enabled=True,
                    is_moderation_default=True,
                    sort_order=10,
                ),
                InstitutionZenodoCommunity(
                    institution_id=institution.id,
                    identifier="moderation-b",
                    enabled=True,
                    is_moderation_default=True,
                    sort_order=20,
                ),
                InstitutionZenodoCommunity(
                    institution_id=institution.id,
                    identifier="primary-only",
                    enabled=True,
                    is_primary_submission=True,
                    sort_order=30,
                ),
            ]
        )
        db.session.commit()

        moderator_token = create_access_token(identity=str(moderator.id))
        user_token = create_access_token(identity=str(regular.id))
        institution_id = institution.id

    return app, moderator_token, user_token, institution_id


def test_community_moderation_requests_route_uses_default_community(monkeypatch, community_moderation_app):
    app, moderator_token, _, _ = community_moderation_app
    client = app.test_client()

    def _mock_fetch(community_identifier):
        assert community_identifier == "3dbigdataspace"
        return _sample_queue(community_identifier)

    monkeypatch.setattr("routes.tools_routes.zenodo_moderation_service.fetch_open_community_requests", _mock_fetch)

    response = client.get(
        "/api/v1/tools/community-moderation/requests",
        headers={"Authorization": f"Bearer {moderator_token}"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["community"]["slug"] == "3dbigdataspace"
    assert payload["data"]["summary"]["open_requests_total"] == 2


def test_community_moderation_requests_route_filters_and_paginates(monkeypatch, community_moderation_app):
    app, moderator_token, _, _ = community_moderation_app
    client = app.test_client()

    monkeypatch.setattr(
        "routes.tools_routes.zenodo_moderation_service.fetch_open_community_requests",
        lambda community_identifier: _sample_queue(community_identifier),
    )

    response = client.get(
        "/api/v1/tools/community-moderation/requests?community_identifier=custom&q=beta&request_type=inclusion-request&page=1&per_page=10",
        headers={"Authorization": f"Bearer {moderator_token}"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data"]["summary"]["requests_filtered"] == 1
    assert payload["data"]["requests"][0]["request_id"] == "req-2"


def test_community_moderation_requests_route_forbids_regular_users(monkeypatch, community_moderation_app):
    app, _, user_token, _ = community_moderation_app
    client = app.test_client()

    monkeypatch.setattr(
        "routes.tools_routes.zenodo_moderation_service.fetch_open_community_requests",
        lambda community_identifier: _sample_queue(community_identifier),
    )

    response = client.get(
        "/api/v1/tools/community-moderation/requests",
        headers={"Authorization": f"Bearer {user_token}"},
    )

    assert response.status_code == 403


def test_launch_community_moderation_batch_counts_actionable_requests(monkeypatch, community_moderation_app):
    app, moderator_token, _, _ = community_moderation_app
    client = app.test_client()

    class _DummyTask:
        id = "mod-task-1"

    monkeypatch.setattr(
        "routes.tools_routes.zenodo_moderation_service.fetch_open_community_requests",
        lambda community_identifier: _sample_queue(community_identifier),
    )
    dummy_tasks = types.SimpleNamespace(
        execute_community_moderation_batch=types.SimpleNamespace(delay=lambda **kwargs: _DummyTask())
    )
    monkeypatch.setitem(sys.modules, "tasks", dummy_tasks)

    response = client.post(
        "/api/v1/tools/community-moderation/actions",
        headers={"Authorization": f"Bearer {moderator_token}"},
        json={
            "action": "accept",
            "community_identifier": "3d-big-data-space",
            "note": "Looks good.",
            "request_ids": ["req-1", "req-2"],
        },
    )

    assert response.status_code == 202
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["task_id"] == "mod-task-1"
    assert payload["data"]["selected_count"] == 2
    assert payload["data"]["actionable_count"] == 2


def test_community_moderation_history_route_returns_persisted_runs(monkeypatch, community_moderation_app):
    app, moderator_token, _, _ = community_moderation_app
    client = app.test_client()

    class _DummyTask:
        id = "mod-task-1"

    monkeypatch.setattr(
        "routes.tools_routes.zenodo_moderation_service.fetch_open_community_requests",
        lambda community_identifier: _sample_queue(community_identifier),
    )
    dummy_tasks = types.SimpleNamespace(
        execute_community_moderation_batch=types.SimpleNamespace(delay=lambda **kwargs: _DummyTask())
    )
    monkeypatch.setitem(sys.modules, "tasks", dummy_tasks)

    queue_response = client.post(
        "/api/v1/tools/community-moderation/actions",
        headers={"Authorization": f"Bearer {moderator_token}"},
        json={
            "action": "decline",
            "community_identifier": "3d-big-data-space",
            "request_ids": ["req-1"],
        },
    )

    assert queue_response.status_code == 202

    history_response = client.get(
        "/api/v1/tools/community-moderation/history",
        headers={"Authorization": f"Bearer {moderator_token}"},
    )

    assert history_response.status_code == 200
    payload = history_response.get_json()
    assert payload["data"]["tasks"][0]["task_id"] == "mod-task-1"
    assert payload["data"]["tasks"][0]["action"] == "decline"
    assert payload["data"]["tasks"][0]["community_identifier"] == "3d-big-data-space"


def test_community_moderation_task_status_route(monkeypatch, community_moderation_app):
    app, moderator_token, _, _ = community_moderation_app
    client = app.test_client()

    class _DummyAsyncResult:
        state = "SUCCESS"
        result = {
            "status": "completed",
            "progress": {"total_requests": 2, "processed": 2, "percent": 100},
            "results": [{"request_id": "req-1", "status": "accepted"}],
        }
        info = result

    dummy_module = types.SimpleNamespace(celery=types.SimpleNamespace(AsyncResult=lambda task_id: _DummyAsyncResult()))
    monkeypatch.setitem(sys.modules, "celery_app", dummy_module)

    response = client.get(
        "/api/v1/tools/community-moderation/tasks/mod-task-1",
        headers={"Authorization": f"Bearer {moderator_token}"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["data"]["state"] == "SUCCESS"
    assert payload["data"]["result"]["results"][0]["status"] == "accepted"


def test_institution_moderation_default_beats_primary_and_returns_context(monkeypatch, community_moderation_app):
    app, moderator_token, _, institution_id = community_moderation_app
    client = app.test_client()

    def _mock_fetch(community_identifier):
        assert community_identifier == "moderation-a"
        return _sample_queue(community_identifier)

    monkeypatch.setattr("routes.tools_routes.zenodo_moderation_service.fetch_open_community_requests", _mock_fetch)

    response = client.get(
        f"/api/v1/tools/community-moderation/requests?institution_id={institution_id}",
        headers={"Authorization": f"Bearer {moderator_token}"},
    )

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["moderation_context"]["community_identifier"] == "moderation-a"
    assert payload["moderation_context"]["resolution_source"] == "institution_moderation_default"
    assert payload["moderation_context"]["candidate_default_communities"] == ["moderation-a", "moderation-b"]
    assert payload["moderation_context"]["institution"]["id"] == institution_id


def test_explicit_community_identifier_beats_institution_defaults(monkeypatch, community_moderation_app):
    app, moderator_token, _, institution_id = community_moderation_app
    client = app.test_client()

    monkeypatch.setattr(
        "routes.tools_routes.zenodo_moderation_service.fetch_open_community_requests",
        lambda community_identifier: _sample_queue(community_identifier),
    )

    response = client.get(
        f"/api/v1/tools/community-moderation/requests?institution_id={institution_id}&community_identifier=manual-community",
        headers={"Authorization": f"Bearer {moderator_token}"},
    )

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["moderation_context"]["community_identifier"] == "manual-community"
    assert payload["moderation_context"]["resolution_source"] == "explicit"


def test_launch_community_moderation_batch_resolves_institution_default(monkeypatch, community_moderation_app):
    app, moderator_token, _, institution_id = community_moderation_app
    client = app.test_client()

    class _DummyTask:
        id = "mod-task-inst"

    monkeypatch.setattr(
        "routes.tools_routes.zenodo_moderation_service.fetch_open_community_requests",
        lambda community_identifier: _sample_queue(community_identifier),
    )
    dummy_tasks = types.SimpleNamespace(
        execute_community_moderation_batch=types.SimpleNamespace(delay=lambda **kwargs: _DummyTask())
    )
    monkeypatch.setitem(sys.modules, "tasks", dummy_tasks)

    response = client.post(
        "/api/v1/tools/community-moderation/actions",
        headers={"Authorization": f"Bearer {moderator_token}"},
        json={
            "action": "accept",
            "institution_id": institution_id,
            "request_ids": ["req-1"],
        },
    )

    assert response.status_code == 202
    payload = response.get_json()["data"]
    assert payload["community_identifier"] == "moderation-a"
    assert payload["moderation_context"]["resolution_source"] == "institution_moderation_default"


def test_primary_submission_beats_global_override_when_no_moderation_defaults(monkeypatch, community_moderation_app):
    app, moderator_token, _, institution_id = community_moderation_app
    client = app.test_client()

    with app.app_context():
        InstitutionZenodoCommunity.query.filter_by(institution_id=institution_id, is_moderation_default=True).delete()
        db.session.commit()

    monkeypatch.setattr(
        "routes.tools_routes.zenodo_moderation_service.fetch_open_community_requests",
        lambda community_identifier: _sample_queue(community_identifier),
    )

    response = client.get(
        f"/api/v1/tools/community-moderation/requests?institution_id={institution_id}",
        headers={"Authorization": f"Bearer {moderator_token}"},
    )

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["moderation_context"]["community_identifier"] == "primary-only"
    assert payload["moderation_context"]["resolution_source"] == "institution_primary_submission"


def test_unresolved_moderation_context_returns_validation_error(monkeypatch, community_moderation_app):
    app, moderator_token, _, institution_id = community_moderation_app
    client = app.test_client()

    with app.app_context():
        InstitutionZenodoCommunity.query.filter_by(institution_id=institution_id).delete()
        db.session.commit()

    monkeypatch.setattr(
        "routes.tools_routes.ZenodoConfigService.get_community_override_config",
        lambda: {"enabled": False, "community": ""},
    )

    response = client.get(
        f"/api/v1/tools/community-moderation/requests?institution_id={institution_id}",
        headers={"Authorization": f"Bearer {moderator_token}"},
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error"]["code"] == "VALIDATION_ERROR"


def _sample_sweep_plan(community_identifier="3dbigdataspace", action="accept"):
    return {
        "community": {
            "id": "community-1",
            "slug": community_identifier,
            "title": "3D Big Data Space",
            "identifier_used": community_identifier,
            "links": {"self_html": f"https://zenodo.org/communities/{community_identifier}/"},
        },
        "status": "submitted",
        "request_type": None,
        "total": 3,
        "preview": _sample_queue(community_identifier)["requests"],
        "preview_count": 2,
        "preview_actionable_count": 2,
        "action": action,
        "api_key_context": {"environment": "production", "source": "ZENODO_API_KEY", "configured": True},
    }


def test_community_moderation_sweep_plan_start_cancel_and_export(monkeypatch, community_moderation_app):
    app, moderator_token, _, _ = community_moderation_app
    client = app.test_client()

    class _DummyTask:
        id = "sweep-task-1"

    monkeypatch.setattr(
        "services.zenodo_moderation_service.summarize_community_requests",
        lambda community_identifier, action="accept", status="submitted", request_type=None, preview_size=100: _sample_sweep_plan(community_identifier, action),
    )
    dummy_tasks = types.SimpleNamespace(
        execute_community_moderation_sweep=types.SimpleNamespace(delay=lambda **kwargs: _DummyTask())
    )
    monkeypatch.setitem(sys.modules, "tasks", dummy_tasks)

    plan_response = client.post(
        "/api/v1/tools/community-moderation/sweeps/plan",
        headers={"Authorization": f"Bearer {moderator_token}"},
        json={"action": "accept", "community_identifier": "3dbigdataspace"},
    )

    assert plan_response.status_code == 200
    plan = plan_response.get_json()["data"]
    assert plan["summary"]["planned_requests"] == 3
    assert plan["confirmation_text"] == "ACCEPT 3 REQUESTS FOR 3dbigdataspace"

    bad_start = client.post(
        "/api/v1/tools/community-moderation/sweeps",
        headers={"Authorization": f"Bearer {moderator_token}"},
        json={
            "action": "accept",
            "community_identifier": "3dbigdataspace",
            "plan_checksum": plan["plan_checksum"],
            "confirmation_text": "wrong",
        },
    )
    assert bad_start.status_code == 400

    start_response = client.post(
        "/api/v1/tools/community-moderation/sweeps",
        headers={"Authorization": f"Bearer {moderator_token}"},
        json={
            "action": "accept",
            "community_identifier": "3dbigdataspace",
            "plan_checksum": plan["plan_checksum"],
            "confirmation_text": plan["confirmation_text"],
        },
    )
    assert start_response.status_code == 202
    job = start_response.get_json()["data"]
    assert job["task_id"] == "sweep-task-1"

    duplicate_response = client.post(
        "/api/v1/tools/community-moderation/sweeps",
        headers={"Authorization": f"Bearer {moderator_token}"},
        json={
            "action": "accept",
            "community_identifier": "3dbigdataspace",
            "plan_checksum": plan["plan_checksum"],
            "confirmation_text": plan["confirmation_text"],
        },
    )
    assert duplicate_response.status_code == 400

    poll_response = client.get(
        f"/api/v1/tools/community-moderation/sweeps/{job['job_id']}",
        headers={"Authorization": f"Bearer {moderator_token}"},
    )
    assert poll_response.status_code == 200
    assert poll_response.get_json()["data"]["job_id"] == job["job_id"]

    cancel_response = client.post(
        f"/api/v1/tools/community-moderation/sweeps/{job['job_id']}/cancel",
        headers={"Authorization": f"Bearer {moderator_token}"},
    )
    assert cancel_response.status_code == 202
    assert cancel_response.get_json()["data"]["state"] == "CANCEL_REQUESTED"

    export_response = client.get(
        f"/api/v1/tools/community-moderation/sweeps/{job['job_id']}/export?format=csv",
        headers={"Authorization": f"Bearer {moderator_token}"},
    )
    assert export_response.status_code == 200
    assert export_response.headers["Content-Type"].startswith("text/csv")


def test_community_moderation_sweep_forbids_regular_users(community_moderation_app):
    app, _, user_token, _ = community_moderation_app
    client = app.test_client()

    response = client.post(
        "/api/v1/tools/community-moderation/sweeps/plan",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"action": "accept", "community_identifier": "3dbigdataspace"},
    )

    assert response.status_code == 403
