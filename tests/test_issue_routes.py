import pytest


pytest.importorskip("flask_jwt_extended")

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import Notification, User, UserRole
from middleware import setup_error_handlers
from routes.issues_routes import issues_bp


@pytest.fixture()
def issue_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "issue-test-secret"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = "issue-test-jwt"

    setup_error_handlers(app)
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(issues_bp, url_prefix="/api/v1/issues")

    with app.app_context():
        db.create_all()

        reporter = User(email="reporter@example.com", role=UserRole.USER, is_verified=True)
        reporter.set_password("password123")
        reporter.set_capabilities([])

        developer = User(email="developer@example.com", role=UserRole.USER, is_verified=True)
        developer.set_password("password123")
        developer.set_capabilities(["developer_access"])

        moderator = User(email="moderator@example.com", role=UserRole.MODERATOR, is_verified=True)
        moderator.set_password("password123")
        moderator.set_capabilities([])

        admin = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
        admin.set_password("password123")
        admin.set_capabilities([])

        db.session.add_all([reporter, developer, moderator, admin])
        db.session.commit()

        yield {
            "app": app,
            "client": app.test_client(),
            "reporter": reporter,
            "developer": developer,
            "moderator": moderator,
            "admin": admin,
            "reporter_headers": {"Authorization": f"Bearer {create_access_token(identity=str(reporter.id))}"},
            "developer_headers": {"Authorization": f"Bearer {create_access_token(identity=str(developer.id))}"},
            "moderator_headers": {"Authorization": f"Bearer {create_access_token(identity=str(moderator.id))}"},
            "admin_headers": {"Authorization": f"Bearer {create_access_token(identity=str(admin.id))}"},
        }

        db.session.remove()
        db.drop_all()


def _create_issue(client, headers):
    response = client.post(
        "/api/v1/issues",
        headers=headers,
        json={
            "title": "Provenance panel does not load",
            "issue_type": "data",
            "reporter_impact": "high",
            "page_key": "session_provenance_report",
            "route_name": "SessionProvenanceReport",
            "route_path": "/sessions/17/provenance-report",
            "current_url": "https://example.test/sessions/17/provenance-report",
            "public_description": "The provenance page stays blank after navigation.",
            "expected_behavior": "The report should render charts and snapshots.",
            "technical_details": "Observed after opening the session report from Submission Detail.",
            "route_context": {
                "path": "/sessions/17/provenance-report",
                "full_path": "/sessions/17/provenance-report",
                "params": {"sessionId": "17"},
                "query": {},
            },
            "related_entity_ids": {"session_id": 17},
            "environment_context": {
                "app_version": {"version": "test-build", "timestamp": "2026-03-31T10:00:00Z"},
            },
            "user_context": {"reporter_role": "user", "reporter_groups": []},
            "capture_context": {"source": "pytest"},
        },
    )
    assert response.status_code == 201
    return response.get_json()["data"]["issue"]


def test_reporter_can_create_and_list_own_issue(issue_app):
    created_issue = _create_issue(issue_app["client"], issue_app["reporter_headers"])

    list_response = issue_app["client"].get("/api/v1/issues?scope=my", headers=issue_app["reporter_headers"])

    assert list_response.status_code == 200
    issues = list_response.get_json()["data"]["issues"]
    assert len(issues) == 1
    assert issues[0]["id"] == created_issue["id"]
    assert issues[0]["page_key"] == "session_provenance_report"
    assert issues[0]["code_references"]["first_order"] == []


def test_developer_queue_can_view_issue_and_receive_code_references(issue_app):
    created_issue = _create_issue(issue_app["client"], issue_app["reporter_headers"])

    queue_response = issue_app["client"].get("/api/v1/issues?scope=queue", headers=issue_app["developer_headers"])
    assert queue_response.status_code == 200
    assert queue_response.get_json()["data"]["permissions"]["can_view_issue_queue"] is True
    assert len(queue_response.get_json()["data"]["issues"]) == 1

    detail_response = issue_app["client"].get(f"/api/v1/issues/{created_issue['id']}", headers=issue_app["developer_headers"])
    assert detail_response.status_code == 200
    issue_payload = detail_response.get_json()["data"]["issue"]
    first_order = issue_payload["code_references"]["first_order"]
    second_order = issue_payload["code_references"]["second_order"]
    third_order = issue_payload["code_references"]["third_order"]

    assert any("SessionProvenanceReportView.vue" in item["path_or_endpoint"] for item in first_order)
    assert any("/api/v1/sessions/<session_id>/provenance-report" in item["path_or_endpoint"] for item in first_order)
    assert any("routes/session_routes.py" in item["path_or_endpoint"] for item in second_order)
    assert any("database/models.py" in item["path_or_endpoint"] for item in third_order)


def test_issue_registry_exposes_assignable_users_only_to_triage_viewers(issue_app):
    reporter_registry = issue_app["client"].get("/api/v1/issues/registry", headers=issue_app["reporter_headers"])
    assert reporter_registry.status_code == 200
    assert reporter_registry.get_json()["data"]["assignable_users"] == []

    developer_registry = issue_app["client"].get("/api/v1/issues/registry", headers=issue_app["developer_headers"])
    assert developer_registry.status_code == 200
    assignable_users = developer_registry.get_json()["data"]["assignable_users"]
    assignable_emails = {entry["email"] for entry in assignable_users}

    assert "developer@example.com" in assignable_emails
    assert "moderator@example.com" in assignable_emails
    assert "admin@example.com" in assignable_emails
    assert "reporter@example.com" not in assignable_emails


def test_reporter_cannot_patch_internal_fields_but_moderator_can(issue_app):
    created_issue = _create_issue(issue_app["client"], issue_app["reporter_headers"])

    forbidden_response = issue_app["client"].patch(
        f"/api/v1/issues/{created_issue['id']}",
        headers=issue_app["reporter_headers"],
        json={"status": "triaged"},
    )
    assert forbidden_response.status_code == 403

    allowed_response = issue_app["client"].patch(
        f"/api/v1/issues/{created_issue['id']}",
        headers=issue_app["moderator_headers"],
        json={"status": "triaged", "internal_priority": "high"},
    )
    assert allowed_response.status_code == 200
    issue_payload = allowed_response.get_json()["data"]["issue"]
    assert issue_payload["status"] == "triaged"
    assert issue_payload["internal_priority"] == "high"
    with issue_app["app"].app_context():
        status_notification = Notification.query.filter_by(
            recipient_user_id=issue_app["reporter"].id,
            notification_type="issue.status_changed",
        ).one()
        assert status_notification.entity_id == str(created_issue["id"])
        assert status_notification.action_url == f"/issues/{created_issue['id']}"

    comment_response = issue_app["client"].post(
        f"/api/v1/issues/{created_issue['id']}/comments",
        headers=issue_app["moderator_headers"],
        json={"body": "Investigating backend route bindings.", "is_internal": True},
    )
    assert comment_response.status_code == 201
    comment_payload = comment_response.get_json()["data"]["comment"]
    assert comment_payload["is_internal"] is True
    with issue_app["app"].app_context():
        assert Notification.query.filter_by(notification_type="issue.commented").count() == 0


def test_reporter_cannot_patch_captured_context_fields(issue_app):
    created_issue = _create_issue(issue_app["client"], issue_app["reporter_headers"])

    forbidden_response = issue_app["client"].patch(
        f"/api/v1/issues/{created_issue['id']}",
        headers=issue_app["reporter_headers"],
        json={
            "current_url": "https://example.test/elsewhere",
            "route_context": {
                "path": "/elsewhere",
                "full_path": "/elsewhere",
                "params": {},
                "query": {},
            },
        },
    )
    assert forbidden_response.status_code == 403
    assert "captured context" in forbidden_response.get_json()["error"]["message"]


def test_reporter_can_still_patch_allowed_report_fields(issue_app):
    created_issue = _create_issue(issue_app["client"], issue_app["reporter_headers"])

    allowed_response = issue_app["client"].patch(
        f"/api/v1/issues/{created_issue['id']}",
        headers=issue_app["reporter_headers"],
        json={
            "title": "Provenance panel loads partially",
            "page_key": "submission_detail",
            "public_description": "The report now renders only the header.",
        },
    )
    assert allowed_response.status_code == 200
    issue_payload = allowed_response.get_json()["data"]["issue"]
    assert issue_payload["title"] == "Provenance panel loads partially"
    assert issue_payload["page_key"] == "submission_detail"
    assert issue_payload["page_label"] == "Submission Detail"


def test_issue_assignment_requires_triage_eligible_assignee(issue_app):
    created_issue = _create_issue(issue_app["client"], issue_app["reporter_headers"])

    allowed_response = issue_app["client"].patch(
        f"/api/v1/issues/{created_issue['id']}",
        headers=issue_app["moderator_headers"],
        json={"assignee_user_id": issue_app["developer"].id},
    )
    assert allowed_response.status_code == 200
    assert allowed_response.get_json()["data"]["issue"]["assignee"]["email"] == "developer@example.com"
    with issue_app["app"].app_context():
        assignment_notification = Notification.query.filter_by(
            recipient_user_id=issue_app["developer"].id,
            notification_type="issue.assigned",
        ).one()
        assert assignment_notification.title == "Issue assigned to you"
        assert assignment_notification.action_url == f"/issues/{created_issue['id']}"

    invalid_response = issue_app["client"].patch(
        f"/api/v1/issues/{created_issue['id']}",
        headers=issue_app["moderator_headers"],
        json={"assignee_user_id": issue_app["reporter"].id},
    )
    assert invalid_response.status_code == 400
    assert "triage access" in invalid_response.get_json()["error"]["message"]


def test_public_issue_comment_notifies_involved_users_except_actor(issue_app):
    created_issue = _create_issue(issue_app["client"], issue_app["reporter_headers"])
    assign_response = issue_app["client"].patch(
        f"/api/v1/issues/{created_issue['id']}",
        headers=issue_app["moderator_headers"],
        json={"assignee_user_id": issue_app["developer"].id},
    )
    assert assign_response.status_code == 200

    comment_response = issue_app["client"].post(
        f"/api/v1/issues/{created_issue['id']}/comments",
        headers=issue_app["reporter_headers"],
        json={"body": "I can provide a screenshot.", "is_internal": False},
    )
    assert comment_response.status_code == 201

    with issue_app["app"].app_context():
        comment_notifications = Notification.query.filter_by(notification_type="issue.commented").all()
        assert len(comment_notifications) == 1
        assert comment_notifications[0].recipient_user_id == issue_app["developer"].id
