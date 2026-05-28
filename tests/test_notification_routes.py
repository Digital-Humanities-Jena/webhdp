import pytest


pytest.importorskip("flask_jwt_extended")

from datetime import datetime, timedelta

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import Notification, NotificationDelivery, NotificationPreference, User, UserRole
from middleware import setup_error_handlers
from routes.notification_routes import notifications_bp
from services.notification_service import notify_user


@pytest.fixture()
def notification_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "notification-test-secret"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = "notification-test-jwt"

    setup_error_handlers(app)
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(notifications_bp, url_prefix="/api/v1/notifications")

    with app.app_context():
        db.create_all()
        owner = User(email="owner@example.com", role=UserRole.USER, is_verified=True)
        owner.set_password("password123")
        other = User(email="other@example.com", role=UserRole.USER, is_verified=True)
        other.set_password("password123")
        db.session.add_all([owner, other])
        db.session.commit()

        owner_headers = {"Authorization": f"Bearer {create_access_token(identity=str(owner.id))}"}
        other_headers = {"Authorization": f"Bearer {create_access_token(identity=str(other.id))}"}

        yield {
            "app": app,
            "client": app.test_client(),
            "owner": owner,
            "other": other,
            "owner_headers": owner_headers,
            "other_headers": other_headers,
        }

        db.session.remove()
        db.drop_all()


def test_notification_routes_list_count_and_read_all(notification_app):
    with notification_app["app"].app_context():
        notify_user(
            recipient_user_id=notification_app["owner"].id,
            notification_type="test.created",
            title="First notification",
            body="Useful update",
            action_url="/dashboard",
        )
        notify_user(
            recipient_user_id=notification_app["owner"].id,
            notification_type="test.created",
            title="Second notification",
        )
        db.session.commit()

    count_response = notification_app["client"].get(
        "/api/v1/notifications/unread-count",
        headers=notification_app["owner_headers"],
    )
    assert count_response.status_code == 200
    assert count_response.get_json()["data"]["unread_count"] == 2

    list_response = notification_app["client"].get(
        "/api/v1/notifications?state=unread",
        headers=notification_app["owner_headers"],
    )
    assert list_response.status_code == 200
    payload = list_response.get_json()["data"]
    assert [item["title"] for item in payload["notifications"]] == ["Second notification", "First notification"]
    assert payload["notifications"][1]["action_url"] == "/dashboard"

    read_all_response = notification_app["client"].post(
        "/api/v1/notifications/read-all",
        headers=notification_app["owner_headers"],
    )
    assert read_all_response.status_code == 200
    assert read_all_response.get_json()["data"]["updated_count"] == 2

    unread_response = notification_app["client"].get(
        "/api/v1/notifications?state=unread",
        headers=notification_app["owner_headers"],
    )
    assert unread_response.status_code == 200
    assert unread_response.get_json()["data"]["notifications"] == []


def test_notification_client_config_clamps_values_and_list_uses_limits(notification_app):
    with notification_app["app"].app_context():
        notification_app["app"].config.update(
            NOTIFICATION_POLL_INTERVAL_SECONDS=5,
            NOTIFICATION_DROPDOWN_LIMIT=500,
            NOTIFICATION_PAGE_LIMIT=2,
            NOTIFICATION_DIGEST_MAX_PER_USER=500,
        )
        for index in range(4):
            notify_user(
                recipient_user_id=notification_app["owner"].id,
                notification_type="test.created",
                title=f"Notification {index}",
            )
        db.session.commit()

    config_response = notification_app["client"].get(
        "/api/v1/notifications/client-config",
        headers=notification_app["owner_headers"],
    )
    assert config_response.status_code == 200
    config_payload = config_response.get_json()["data"]
    assert config_payload["poll_interval_seconds"] == 30
    assert config_payload["dropdown_limit"] == 50
    assert config_payload["page_limit"] == 2
    assert config_payload["digest_max_per_user"] == 50

    list_response = notification_app["client"].get(
        "/api/v1/notifications?limit=99",
        headers=notification_app["owner_headers"],
    )
    assert list_response.status_code == 200
    payload = list_response.get_json()["data"]
    assert len(payload["notifications"]) == 2
    assert payload["filters"]["limit"] == 2


def test_notification_routes_enforce_recipient_isolation_and_archive(notification_app):
    with notification_app["app"].app_context():
        notification = notify_user(
            recipient_user_id=notification_app["owner"].id,
            notification_type="test.private",
            title="Private notification",
        )
        db.session.commit()
        notification_id = notification.id

    forbidden_response = notification_app["client"].patch(
        f"/api/v1/notifications/{notification_id}",
        headers=notification_app["other_headers"],
        json={"read": True},
    )
    assert forbidden_response.status_code == 403

    update_response = notification_app["client"].patch(
        f"/api/v1/notifications/{notification_id}",
        headers=notification_app["owner_headers"],
        json={"read": True, "archived": True},
    )
    assert update_response.status_code == 200
    assert update_response.get_json()["data"]["notification"]["is_archived"] is True

    list_response = notification_app["client"].get(
        "/api/v1/notifications",
        headers=notification_app["owner_headers"],
    )
    assert list_response.status_code == 200
    assert list_response.get_json()["data"]["notifications"] == []


def test_notification_routes_filter_archived_and_category(notification_app):
    with notification_app["app"].app_context():
        notify_user(
            recipient_user_id=notification_app["owner"].id,
            notification_type="issue.assigned",
            title="Issue update",
        )
        archived = notify_user(
            recipient_user_id=notification_app["owner"].id,
            notification_type="pipeline.completed",
            title="Pipeline done",
        )
        archived.archived_at = archived.created_at
        db.session.commit()

    issue_response = notification_app["client"].get(
        "/api/v1/notifications?category=issues",
        headers=notification_app["owner_headers"],
    )
    assert issue_response.status_code == 200
    assert [item["title"] for item in issue_response.get_json()["data"]["notifications"]] == ["Issue update"]

    archived_response = notification_app["client"].get(
        "/api/v1/notifications?state=archived",
        headers=notification_app["owner_headers"],
    )
    assert archived_response.status_code == 200
    assert [item["title"] for item in archived_response.get_json()["data"]["notifications"]] == ["Pipeline done"]


def test_notification_preferences_update_and_delivery_controls(notification_app):
    sent_messages = []

    class FakeEmailService:
        def send_notification_email(self, to_email, notification):
            sent_messages.append((to_email, notification["title"], notification["category"]))
            return True

    notification_app["app"].email_service = FakeEmailService()

    default_response = notification_app["client"].get(
        "/api/v1/notifications/preferences",
        headers=notification_app["owner_headers"],
    )
    assert default_response.status_code == 200
    defaults = default_response.get_json()["data"]["categories"]
    assert any(item["category"] == "issues" and item["in_app_enabled"] is True for item in defaults)

    update_response = notification_app["client"].put(
        "/api/v1/notifications/preferences",
        headers=notification_app["owner_headers"],
        json={"preferences": [{"category": "issues", "in_app_enabled": False, "email_enabled": True}]},
    )
    assert update_response.status_code == 200

    with notification_app["app"].app_context():
        notify_user(
            recipient_user_id=notification_app["owner"].id,
            notification_type="issue.assigned",
            title="Email-only issue notification",
        )
        db.session.commit()

        preference = NotificationPreference.query.filter_by(
            user_id=notification_app["owner"].id,
            category="issues",
        ).first()
        assert preference is not None
        assert preference.in_app_enabled is False
        assert preference.email_enabled is True
        notification = Notification.query.filter_by(title="Email-only issue notification").one()
        assert notification.archived_at is not None
        assert notification.email_status == "sent"
        delivery = NotificationDelivery.query.filter_by(notification_id=notification.id, channel="email").one()
        assert delivery.status == "sent"

    assert sent_messages == [("owner@example.com", "Email-only issue notification", "issues")]


def test_notification_routes_require_auth(notification_app):
    response = notification_app["client"].get("/api/v1/notifications")
    assert response.status_code == 401


def test_notification_dedupe_updates_existing_row(notification_app):
    with notification_app["app"].app_context():
        first = notify_user(
            recipient_user_id=notification_app["owner"].id,
            notification_type="task.finished",
            title="Task completed",
            dedupe_key="task:1:completed",
        )
        second = notify_user(
            recipient_user_id=notification_app["owner"].id,
            notification_type="task.finished",
            title="Task completed again",
            severity="success",
            dedupe_key="task:1:completed",
        )
        db.session.commit()

        assert first.id == second.id
        assert Notification.query.count() == 1
        assert db.session.get(Notification, first.id).title == "Task completed again"


def test_notification_cleanup_preserves_active_unread(notification_app):
    with notification_app["app"].app_context():
        notification_app["app"].config.update(
            NOTIFICATION_DELIVERY_AUDIT_RETENTION_DAYS=30,
            NOTIFICATION_READ_RETENTION_DAYS=30,
            NOTIFICATION_ARCHIVED_RETENTION_DAYS=30,
        )
        now = datetime.utcnow()
        active = notify_user(
            recipient_user_id=notification_app["owner"].id,
            notification_type="test.active",
            title="Keep active",
        )
        old_read = notify_user(
            recipient_user_id=notification_app["owner"].id,
            notification_type="test.read",
            title="Delete old read",
        )
        old_read.read_at = now - timedelta(days=45)
        old_archived = notify_user(
            recipient_user_id=notification_app["owner"].id,
            notification_type="test.archived",
            title="Delete old archived",
        )
        old_archived.archived_at = now - timedelta(days=45)
        db.session.flush()
        db.session.add(
            NotificationDelivery(
                notification_id=active.id,
                recipient_user_id=notification_app["owner"].id,
                channel="email",
                status="failed",
                created_at=now - timedelta(days=45),
            )
        )
        db.session.commit()

        from services.notification_service import cleanup_notifications

        result = cleanup_notifications()

        assert result["deleted_notifications"] == 2
        assert result["deleted_deliveries"] == 1
        assert Notification.query.filter_by(title="Keep active").count() == 1
        assert Notification.query.filter_by(title="Delete old read").count() == 0
        assert Notification.query.filter_by(title="Delete old archived").count() == 0
