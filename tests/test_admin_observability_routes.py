import os
import tempfile
from datetime import datetime, timedelta

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import AuditEvent, Notification, NotificationDelivery, NotificationPreference, User, UserRecoveryCode, UserRole
from middleware import setup_error_handlers
from routes.admin_routes import admin_bp
from services.api_activity_service import record_api_activity


def _make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
    app.config["SECRET_KEY"] = "test-secret"
    app.config["NOTIFICATION_DIGEST_MAX_PER_USER"] = 10
    app.config["NOTIFICATION_DIGEST_USER_BATCH_SIZE"] = 1
    app.config["NOTIFICATION_READ_RETENTION_DAYS"] = 30
    setup_error_handlers(app)

    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(admin_bp, url_prefix="/api/v1/admin")
    return app


def test_admin_recovery_reset_issues_temporary_password_and_recovery_code():
    app = _make_app()
    with app.app_context():
        db.create_all()
        admin = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
        admin.set_password("password123")
        target = User(email="target@example.com", role=UserRole.USER, is_verified=True)
        target.set_password("old-password")
        db.session.add_all([admin, target])
        db.session.commit()
        admin_id = admin.id
        target_id = target.id
        token = create_access_token(identity=str(admin_id))

    client = app.test_client()
    response = client.post(
        f"/api/v1/admin/users/{target_id}/recovery-reset",
        headers={"Authorization": f"Bearer {token}"},
        json={"temporary_password": "temporary-password-1"},
    )

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["temporary_password"] == "temporary-password-1"
    assert payload["recovery_code"]
    assert payload["user"]["force_password_change"] is True
    assert payload["user"]["admin_recovery_codes"]["remaining_count"] == 1
    assert payload["user"]["last_recovery_reset_at"]
    assert payload["recovery_code"] not in str(payload["user"])
    assert payload["temporary_password"] not in str(payload["user"])
    with app.app_context():
        target = db.session.get(User, target_id)
        assert target.check_password("temporary-password-1")
        assert target.force_password_change is True
        assert target.token_version == 1
        recovery_row = UserRecoveryCode.query.filter_by(user_id=target_id, source="admin_issued").one()
        assert recovery_row.used_at is None
        assert recovery_row.code_hash != payload["recovery_code"]
        audit_event = AuditEvent.query.filter_by(event_type="admin.user_recovery_reset").one()
        assert audit_event.actor_user_id == admin_id
        assert audit_event.entity_id == str(target_id)

    self_response = client.post(
        f"/api/v1/admin/users/{admin_id}/recovery-reset",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert self_response.status_code == 400

    list_response = client.get(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_response.status_code == 200
    users = list_response.get_json()["data"]["users"]
    target_payload = next(item for item in users if item["id"] == target_id)
    assert target_payload["force_password_change"] is True
    assert target_payload["admin_recovery_codes"]["remaining_count"] == 1
    assert target_payload["last_recovery_reset_at"]

    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_admin_observability_routes(monkeypatch):
    temp_dir = tempfile.TemporaryDirectory()
    current_dir = os.getcwd()
    os.chdir(temp_dir.name)
    try:
        app = _make_app()
        with app.app_context():
            db.create_all()
            admin = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
            admin.set_password("password123")
            db.session.add(admin)
            db.session.flush()
            notification = Notification(
                recipient_user_id=admin.id,
                notification_type="admin.test",
                category="admin",
                severity="info",
                title="Admin notification",
                payload_json="{}",
            )
            db.session.add(notification)
            db.session.flush()
            db.session.add(
                NotificationDelivery(
                    notification_id=notification.id,
                    recipient_user_id=admin.id,
                    channel="email",
                    status="failed",
                    error="SMTP down",
                )
            )
            db.session.add(
                NotificationDelivery(
                    notification_id=notification.id,
                    recipient_user_id=admin.id,
                    channel="email",
                    status="failed",
                    error="Old SMTP down",
                    created_at=datetime.utcnow() - timedelta(days=10),
                )
            )
            old_read = Notification(
                recipient_user_id=admin.id,
                notification_type="system.old",
                category="system",
                severity="info",
                title="Old read notification",
                payload_json="{}",
                read_at=datetime.utcnow() - timedelta(days=45),
            )
            db.session.add(old_read)
            db.session.add(NotificationPreference(user_id=admin.id, category="admin", digest_enabled=True))
            second = User(email="second@example.com", role=UserRole.USER, is_verified=True)
            second.set_password("password123")
            db.session.add(second)
            db.session.flush()
            db.session.add(
                Notification(
                    recipient_user_id=second.id,
                    notification_type="admin.test",
                    category="admin",
                    severity="info",
                    title="Second user notification",
                    payload_json="{}",
                )
            )
            db.session.add(NotificationPreference(user_id=second.id, category="admin", digest_enabled=True))
            db.session.commit()
            token = create_access_token(identity=str(admin.id))

        client = app.test_client()

        monkeypatch.setenv("ZENODO_SANDBOX_API_KEY", "sandbox-secret-1234")
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", os.path.join(temp_dir.name, "gdrive.json"))

        record_api_activity(
            {
                "method": "GET",
                "path": "/api/v1/sessions/1/workspace-summary",
                "status_code": 200,
                "duration_ms": 42,
            }
        )
        record_api_activity(
            {
                "method": "POST",
                "path": "/api/v1/admin/observability/checks/zenodo_sandbox",
                "status_code": 500,
                "duration_ms": 15,
            }
        )

        credentials_response = client.get(
            "/api/v1/admin/observability/credentials-status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert credentials_response.status_code == 200
        integrations = credentials_response.get_json()["data"]["integrations"]
        assert any(item["id"] == "zenodo_sandbox" and item["configured"] for item in integrations)

        activity_response = client.get(
            "/api/v1/admin/observability/api-activity?route_family=sessions&hours=24",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert activity_response.status_code == 200
        activity_payload = activity_response.get_json()["data"]
        assert activity_payload["summary"]["total_entries"] == 1
        assert activity_payload["entries"][0]["route_family"] == "sessions"

        monkeypatch.setattr(
            "routes.admin_routes.AdminObservabilityService.run_check",
            lambda check_id, app=None: {"ok": True, "status": f"checked:{check_id}", "checked_at": "2026-03-29T12:00:00"},
        )
        check_response = client.post(
            "/api/v1/admin/observability/checks/zenodo_sandbox",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert check_response.status_code == 200
        assert check_response.get_json()["data"]["status"] == "checked:zenodo_sandbox"

        delivery_response = client.get(
            "/api/v1/admin/observability/notification-deliveries?status=failed",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert delivery_response.status_code == 200
        delivery_payload = delivery_response.get_json()["data"]
        assert delivery_payload["summary"]["statuses"]["failed"] == 1
        assert delivery_payload["summary"]["total"] == 1
        assert delivery_payload["deliveries"][0]["notification"]["title"] == "Admin notification"

        sent_digests = []

        class FakeEmailService:
            def send_notification_digest_email(self, to_email, notifications):
                sent_digests.append((to_email, [item["title"] for item in notifications]))
                return True

        app.email_service = FakeEmailService()
        digest_response = client.post(
            "/api/v1/admin/observability/notification-digest/run",
            headers={"Authorization": f"Bearer {token}"},
            json={"max_per_user": 10, "user_batch_size": 1},
        )
        assert digest_response.status_code == 200
        assert digest_response.get_json()["data"]["sent_users"] == 1
        assert digest_response.get_json()["data"]["processed_users"] == 1
        assert sent_digests == [("admin@example.com", ["Admin notification"])]

        cleanup_response = client.post(
            "/api/v1/admin/observability/notifications/cleanup",
            headers={"Authorization": f"Bearer {token}"},
            json={"batch_size": 100},
        )
        assert cleanup_response.status_code == 200
        assert cleanup_response.get_json()["data"]["deleted_notifications"] == 1
    finally:
        os.chdir(current_dir)
        temp_dir.cleanup()
