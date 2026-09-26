import json

import pytest
from datetime import datetime, timedelta


pytest.importorskip("flask_jwt_extended")
pytest.importorskip("cryptography.fernet")

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import AuditEvent, Notification, SystemConfig, User, UserMfaChallenge, UserRecoveryCode, UserRole
from middleware import setup_error_handlers
from routes.auth_routes import auth_bp
from services.zenodo_credential_service import ZenodoCredentialService


class CapturingEmailService:
    def __init__(self):
        self.login_codes = []

    def send_login_mfa_code_email(self, to_email, code, expires_minutes):
        self.login_codes.append(
            {
                "to_email": to_email,
                "code": code,
                "expires_minutes": expires_minutes,
                "body": f"Your WebHDP verification code is {code}",
            }
        )
        return True


@pytest.fixture()
def auth_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "auth-test-secret"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = "auth-test-jwt"
    app.config["MFA_EMAIL_CODE_TTL_SECONDS"] = 600
    app.config["MFA_EMAIL_MAX_VERIFY_ATTEMPTS"] = 5
    app.config["MFA_EMAIL_RESEND_COOLDOWN_SECONDS"] = 60
    app.config["MFA_RECOVERY_CODE_COUNT"] = 3
    app.config["MFA_RECOVERY_CODE_LENGTH"] = 12
    app.config["MFA_ADMIN_RECOVERY_CODE_TTL_SECONDS"] = 86400
    app.config["MFA_RECOVERY_RATE_LIMIT_ATTEMPTS"] = 5
    app.config["MFA_RECOVERY_RATE_LIMIT_WINDOW_SECONDS"] = 300
    app.config["MFA_RECOVERY_RATE_LIMIT_LOCKOUT_SECONDS"] = 900

    setup_error_handlers(app)
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(auth_bp, url_prefix="/api/v1/auth")
    app.email_service = CapturingEmailService()

    with app.app_context():
        db.create_all()
        user = User(email="owner@example.com", role=UserRole.USER, is_verified=True, mfa_enabled=True)
        user.set_password("password123")
        user.set_capabilities(["developer_access"])
        recipient = User(email="recipient@example.com", role=UserRole.USER, is_verified=True)
        recipient.set_password("password123")
        db.session.add_all([user, recipient])
        db.session.commit()

        credential_service = ZenodoCredentialService()
        credential_service.upsert_credential(
            owner_type="user",
            owner_id=user.id,
            environment="sandbox",
            token="sandbox-secret-token",
            actor_user_id=user.id,
        )

        token = create_access_token(identity=str(user.id))
        recipient_token = create_access_token(identity=str(recipient.id))

        yield {
            "app": app,
            "client": app.test_client(),
            "user_id": user.id,
            "recipient_id": recipient.id,
            "headers": {"Authorization": f"Bearer {token}"},
            "recipient_headers": {"Authorization": f"Bearer {recipient_token}"},
            "email_service": app.email_service,
        }

        db.session.remove()
        db.drop_all()


def _login_for_mfa(auth_app, email="owner@example.com", password="password123"):
    return auth_app["client"].post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )


def test_password_login_requires_email_mfa_and_sends_code(auth_app):
    response = _login_for_mfa(auth_app)

    assert response.status_code == 202
    payload = response.get_json()["data"]
    assert payload["mfa_required"] is True
    assert payload["method"] == "email"
    assert payload["mfa_token"]
    assert payload["masked_email"] == "ow***r@example.com"
    assert "access_token" not in payload

    sent = auth_app["email_service"].login_codes[-1]
    assert sent["to_email"] == "owner@example.com"
    assert sent["code"].isdigit()
    assert len(sent["code"]) == 6
    assert sent["body"].startswith(f"Your WebHDP verification code is {sent['code']}")
    with auth_app["app"].app_context():
        challenge = UserMfaChallenge.query.one()
        assert challenge.method == "email"
        assert challenge.code_hash != sent["code"]


def test_development_inline_mfa_delivery_returns_code_without_email(auth_app):
    auth_app["app"].config["MFA_DEVELOPMENT_CODE_DELIVERY"] = "inline"

    response = _login_for_mfa(auth_app)

    assert response.status_code == 202
    payload = response.get_json()["data"]
    assert payload["mfa_required"] is True
    assert payload["delivery"] == "development_inline"
    assert payload["development_mfa_code"].isdigit()
    assert len(payload["development_mfa_code"]) == 6
    assert auth_app["email_service"].login_codes == []

    verify_response = auth_app["client"].post(
        "/api/v1/auth/login/verify-code",
        json={"mfa_token": payload["mfa_token"], "code": payload["development_mfa_code"]},
    )
    assert verify_response.status_code == 200
    assert verify_response.get_json()["data"]["access_token"]


def test_development_inline_mfa_delivery_is_ignored_in_production(auth_app, monkeypatch):
    auth_app["app"].config["MFA_DEVELOPMENT_CODE_DELIVERY"] = "inline"
    monkeypatch.setenv("FLASK_ENV", "production")

    response = _login_for_mfa(auth_app)

    assert response.status_code == 202
    payload = response.get_json()["data"]
    assert payload["delivery"] == "email"
    assert "development_mfa_code" not in payload
    assert auth_app["email_service"].login_codes


def test_email_mfa_code_completes_login_and_consumes_challenge(auth_app):
    login_response = _login_for_mfa(auth_app)
    mfa_token = login_response.get_json()["data"]["mfa_token"]
    code = auth_app["email_service"].login_codes[-1]["code"]

    verify_response = auth_app["client"].post(
        "/api/v1/auth/login/verify-code",
        json={"mfa_token": mfa_token, "code": code},
    )

    assert verify_response.status_code == 200
    payload = verify_response.get_json()["data"]
    assert payload["access_token"]
    assert payload["user"]["email"] == "owner@example.com"
    with auth_app["app"].app_context():
        challenge = UserMfaChallenge.query.one()
        assert challenge.consumed_at is not None

    reuse_response = auth_app["client"].post(
        "/api/v1/auth/login/verify-code",
        json={"mfa_token": mfa_token, "code": code},
    )
    assert reuse_response.status_code == 400
    assert reuse_response.get_json()["error"]["code"] == "MFA_CHALLENGE_INVALID"


def test_email_mfa_wrong_codes_lock_challenge(auth_app):
    login_response = _login_for_mfa(auth_app)
    mfa_token = login_response.get_json()["data"]["mfa_token"]

    for attempt in range(4):
        response = auth_app["client"].post(
            "/api/v1/auth/login/verify-code",
            json={"mfa_token": mfa_token, "code": f"00000{attempt}"},
        )
        assert response.status_code == 400
        assert response.get_json()["error"]["code"] == "MFA_CODE_INVALID"

    locked_response = auth_app["client"].post(
        "/api/v1/auth/login/verify-code",
        json={"mfa_token": mfa_token, "code": "999999"},
    )
    assert locked_response.status_code == 429
    assert locked_response.get_json()["error"]["code"] == "MFA_CHALLENGE_LOCKED"


def test_email_mfa_rejects_expired_and_malformed_challenges(auth_app):
    login_response = _login_for_mfa(auth_app)
    mfa_token = login_response.get_json()["data"]["mfa_token"]
    code = auth_app["email_service"].login_codes[-1]["code"]
    with auth_app["app"].app_context():
        challenge = UserMfaChallenge.query.one()
        challenge.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()

    expired_response = auth_app["client"].post(
        "/api/v1/auth/login/verify-code",
        json={"mfa_token": mfa_token, "code": code},
    )
    assert expired_response.status_code == 400
    assert expired_response.get_json()["error"]["code"] == "MFA_CHALLENGE_INVALID"

    malformed_response = auth_app["client"].post(
        "/api/v1/auth/login/verify-code",
        json={"mfa_token": "missing-token", "code": "123456"},
    )
    assert malformed_response.status_code == 400
    assert malformed_response.get_json()["error"]["code"] == "MFA_CHALLENGE_INVALID"


def test_email_mfa_resend_replaces_code_after_cooldown(auth_app):
    login_response = _login_for_mfa(auth_app)
    mfa_token = login_response.get_json()["data"]["mfa_token"]
    first_code = auth_app["email_service"].login_codes[-1]["code"]

    cooldown_response = auth_app["client"].post(
        "/api/v1/auth/login/resend-code",
        json={"mfa_token": mfa_token},
    )
    assert cooldown_response.status_code == 429
    assert cooldown_response.get_json()["error"]["code"] == "MFA_RESEND_COOLDOWN"

    with auth_app["app"].app_context():
        challenge = UserMfaChallenge.query.one()
        challenge.last_sent_at = datetime.utcnow() - timedelta(seconds=61)
        db.session.commit()

    resend_response = auth_app["client"].post(
        "/api/v1/auth/login/resend-code",
        json={"mfa_token": mfa_token},
    )
    assert resend_response.status_code == 200
    second_code = auth_app["email_service"].login_codes[-1]["code"]
    assert second_code != first_code

    old_code_response = auth_app["client"].post(
        "/api/v1/auth/login/verify-code",
        json={"mfa_token": mfa_token, "code": first_code},
    )
    assert old_code_response.status_code == 400

    new_code_response = auth_app["client"].post(
        "/api/v1/auth/login/verify-code",
        json={"mfa_token": mfa_token, "code": second_code},
    )
    assert new_code_response.status_code == 200


def test_unverified_users_still_cannot_start_mfa(auth_app):
    with auth_app["app"].app_context():
        unverified = User(email="new@example.com", role=UserRole.USER, is_verified=False)
        unverified.set_password("password123")
        db.session.add(unverified)
        db.session.commit()

    response = _login_for_mfa(auth_app, email="new@example.com")

    assert response.status_code == 403
    assert "verify your email" in response.get_json()["error"]["message"]
    assert auth_app["email_service"].login_codes == []


def test_configured_provider_bypass_skips_email_mfa(auth_app):
    with auth_app["app"].app_context():
        gmail_user = User(email="person@gmail.com", role=UserRole.USER, is_verified=True)
        gmail_user.set_password("password123")
        db.session.add(gmail_user)
        db.session.add(
            SystemConfig(
                key="mfa_provider_bypass",
                value=json.dumps({"enabled": True, "domains": ["gmail.com"]}),
            )
        )
        db.session.commit()

    response = _login_for_mfa(auth_app, email="person@gmail.com")

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["access_token"]
    assert payload["user"]["email"] == "person@gmail.com"
    assert auth_app["email_service"].login_codes == []
    with auth_app["app"].app_context():
        assert UserMfaChallenge.query.count() == 0


def test_recovery_code_generation_returns_plaintext_once_and_stores_hashes(auth_app):
    empty_response = auth_app["client"].get(
        "/api/v1/auth/me/recovery-codes",
        headers=auth_app["headers"],
    )
    assert empty_response.status_code == 200
    assert empty_response.get_json()["data"]["recovery_codes"]["remaining_count"] == 0

    generate_response = auth_app["client"].post(
        "/api/v1/auth/me/recovery-codes",
        headers=auth_app["headers"],
        json={"current_password": "password123"},
    )

    assert generate_response.status_code == 200
    payload = generate_response.get_json()["data"]
    codes = payload["codes"]
    assert len(codes) == 3
    assert payload["recovery_codes"]["remaining_count"] == 3
    assert all("-" in code for code in codes)
    response_text = generate_response.get_data(as_text=True)
    with auth_app["app"].app_context():
        rows = UserRecoveryCode.query.filter_by(user_id=auth_app["user_id"]).all()
        assert len(rows) == 3
        for row in rows:
            assert row.source == "user_generated"
            assert row.code_hash not in codes
            assert row.code_hash not in response_text
            assert row.code_prefix in [code.replace("-", "")[:4] for code in codes]
        audit_event = AuditEvent.query.filter_by(event_type="auth.recovery_codes_regenerated").one()
        assert audit_event.details["count"] == 3

    status_response = auth_app["client"].get(
        "/api/v1/auth/me/recovery-codes",
        headers=auth_app["headers"],
    )
    assert status_response.status_code == 200
    assert "codes" not in status_response.get_json()["data"]


def test_recovery_code_completes_mfa_and_is_single_use(auth_app):
    generate_response = auth_app["client"].post(
        "/api/v1/auth/me/recovery-codes",
        headers=auth_app["headers"],
        json={"current_password": "password123"},
    )
    recovery_code = generate_response.get_json()["data"]["codes"][0]
    login_response = _login_for_mfa(auth_app)
    mfa_token = login_response.get_json()["data"]["mfa_token"]

    verify_response = auth_app["client"].post(
        "/api/v1/auth/login/verify-recovery-code",
        json={"mfa_token": mfa_token, "recovery_code": recovery_code},
    )

    assert verify_response.status_code == 200
    assert verify_response.get_json()["data"]["access_token"]
    with auth_app["app"].app_context():
        row = UserRecoveryCode.query.filter_by(user_id=auth_app["user_id"], code_prefix=recovery_code.replace("-", "")[:4]).first()
        assert row.used_at is not None
        audit_event = AuditEvent.query.filter_by(event_type="auth.recovery_code_login").one()
        assert audit_event.details["source"] == "user_generated"

    second_login = _login_for_mfa(auth_app)
    second_token = second_login.get_json()["data"]["mfa_token"]
    reuse_response = auth_app["client"].post(
        "/api/v1/auth/login/verify-recovery-code",
        json={"mfa_token": second_token, "recovery_code": recovery_code},
    )
    assert reuse_response.status_code == 400
    assert reuse_response.get_json()["error"]["code"] == "MFA_RECOVERY_CODE_INVALID"


def test_recovery_code_regeneration_invalidates_old_codes(auth_app):
    first_response = auth_app["client"].post(
        "/api/v1/auth/me/recovery-codes",
        headers=auth_app["headers"],
        json={"current_password": "password123"},
    )
    old_code = first_response.get_json()["data"]["codes"][0]

    second_response = auth_app["client"].post(
        "/api/v1/auth/me/recovery-codes",
        headers=auth_app["headers"],
        json={"current_password": "password123"},
    )
    new_code = second_response.get_json()["data"]["codes"][0]

    login_response = _login_for_mfa(auth_app)
    old_response = auth_app["client"].post(
        "/api/v1/auth/login/verify-recovery-code",
        json={"mfa_token": login_response.get_json()["data"]["mfa_token"], "recovery_code": old_code},
    )
    assert old_response.status_code == 400

    fresh_login = _login_for_mfa(auth_app)
    new_response = auth_app["client"].post(
        "/api/v1/auth/login/verify-recovery-code",
        json={"mfa_token": fresh_login.get_json()["data"]["mfa_token"], "recovery_code": new_code},
    )
    assert new_response.status_code == 200


def test_admin_issued_recovery_code_can_complete_mfa(auth_app):
    from services.recovery_code_service import create_admin_recovery_code

    with auth_app["app"].app_context():
        user = db.session.get(User, auth_app["user_id"])
        recovery_code, recovery_row = create_admin_recovery_code(user)
        db.session.commit()
        row_id = recovery_row.id

    login_response = _login_for_mfa(auth_app)
    verify_response = auth_app["client"].post(
        "/api/v1/auth/login/verify-recovery-code",
        json={"mfa_token": login_response.get_json()["data"]["mfa_token"], "recovery_code": recovery_code},
    )

    assert verify_response.status_code == 200
    with auth_app["app"].app_context():
        row = db.session.get(UserRecoveryCode, row_id)
        assert row.used_at is not None
        audit_event = AuditEvent.query.filter_by(event_type="auth.recovery_code_login").one()
        assert audit_event.details["source"] == "admin_issued"


def test_recovery_code_rejects_expired_malformed_and_wrong_codes(auth_app):
    from services.recovery_code_service import create_admin_recovery_code

    with auth_app["app"].app_context():
        user = db.session.get(User, auth_app["user_id"])
        expired_code, expired_row = create_admin_recovery_code(user)
        expired_row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()

    login_response = _login_for_mfa(auth_app)
    expired_response = auth_app["client"].post(
        "/api/v1/auth/login/verify-recovery-code",
        json={"mfa_token": login_response.get_json()["data"]["mfa_token"], "recovery_code": expired_code},
    )
    assert expired_response.status_code == 400
    assert expired_response.get_json()["error"]["code"] == "MFA_RECOVERY_CODE_INVALID"

    malformed_login = _login_for_mfa(auth_app)
    malformed_response = auth_app["client"].post(
        "/api/v1/auth/login/verify-recovery-code",
        json={"mfa_token": malformed_login.get_json()["data"]["mfa_token"], "recovery_code": "not-a-real-code"},
    )
    assert malformed_response.status_code == 400
    assert malformed_response.get_json()["error"]["code"] == "MFA_RECOVERY_CODE_INVALID"


def test_recovery_code_verification_has_dedicated_rate_limit(auth_app):
    import routes.auth_routes as auth_routes

    auth_routes._recovery_rate_limit_events.clear()
    auth_routes._recovery_rate_limit_lockouts.clear()
    auth_app["app"].config["MFA_RECOVERY_RATE_LIMIT_ATTEMPTS"] = 2

    login_response = _login_for_mfa(auth_app)
    mfa_token = login_response.get_json()["data"]["mfa_token"]

    for _ in range(2):
        response = auth_app["client"].post(
            "/api/v1/auth/login/verify-recovery-code",
            json={"mfa_token": mfa_token, "recovery_code": "WRONG-CODE-0000"},
        )
        assert response.status_code == 400
        assert response.get_json()["error"]["code"] == "MFA_RECOVERY_CODE_INVALID"

    limited_response = auth_app["client"].post(
        "/api/v1/auth/login/verify-recovery-code",
        json={"mfa_token": mfa_token, "recovery_code": "WRONG-CODE-0000"},
    )
    assert limited_response.status_code == 429
    assert limited_response.get_json()["error"]["code"] == "MFA_RECOVERY_RATE_LIMITED"


def test_personal_zenodo_validate_returns_live_write_report(monkeypatch, auth_app):
    class _Response:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = ""

        def json(self):
            return self._payload

    monkeypatch.setattr("services.zenodo_credential_service.requests.get", lambda *args, **kwargs: _Response(200, []))
    monkeypatch.setattr("services.zenodo_credential_service.requests.post", lambda *args, **kwargs: _Response(201, {"id": 9876}))
    monkeypatch.setattr("services.zenodo_credential_service.requests.delete", lambda *args, **kwargs: _Response(204, {}))

    response = auth_app["client"].post(
        "/api/v1/auth/me/zenodo-credentials/sandbox/validate",
        headers=auth_app["headers"],
    )

    assert response.status_code == 200
    credential = response.get_json()["data"]["credential"]
    assert credential["validation_mode"] == "live_write_cleanup"
    assert credential["validation_status"] == "valid"
    assert credential["validation_report"]["capabilities"]["authentication"]["status"] == "verified"
    assert credential["validation_report"]["capabilities"]["deposit_read"]["status"] == "verified"
    assert credential["validation_report"]["capabilities"]["draft_create"]["status"] == "verified"
    assert credential["validation_report"]["capabilities"]["draft_cleanup"]["status"] == "verified"


def test_personal_zenodo_share_accept_and_active_routes(auth_app):
    create_response = auth_app["client"].post(
        "/api/v1/auth/me/zenodo-credentials",
        headers=auth_app["headers"],
        json={"name": "Shared sandbox", "environment": "sandbox", "token": "route-shared-secret"},
    )
    assert create_response.status_code == 201
    credential = create_response.get_json()["data"]["credential"]
    assert credential["masked_preview"] == "rout...cret"
    assert "route-shared-secret" not in create_response.get_data(as_text=True)

    share_response = auth_app["client"].post(
        f"/api/v1/auth/me/zenodo-credentials/{credential['id']}/share",
        headers=auth_app["headers"],
        json={"recipient_email": "recipient@example.com"},
    )
    assert share_response.status_code == 201
    share = share_response.get_json()["data"]["share"]
    assert share["status"] == "pending"
    with auth_app["app"].app_context():
        received_notification = Notification.query.filter_by(
            recipient_user_id=auth_app["recipient_id"],
            notification_type="credential.share_received",
        ).one()
        assert received_notification.action_url == "/account/configuration"

    pending_response = auth_app["client"].get(
        "/api/v1/auth/me/zenodo-credentials",
        headers=auth_app["recipient_headers"],
    )
    assert pending_response.status_code == 200
    pending_payload = pending_response.get_json()["data"]
    assert pending_payload["credentials"] == []
    assert pending_payload["incoming_shares"][0]["credential"]["name"] == "Shared sandbox"
    assert "route-shared-secret" not in pending_response.get_data(as_text=True)

    accept_response = auth_app["client"].post(
        f"/api/v1/auth/me/zenodo-credential-shares/{share['id']}/accept",
        headers=auth_app["recipient_headers"],
    )
    assert accept_response.status_code == 200
    with auth_app["app"].app_context():
        accepted_notification = Notification.query.filter_by(
            recipient_user_id=auth_app["user_id"],
            notification_type="credential.share_accepted",
        ).one()
        assert accepted_notification.severity == "success"

    active_response = auth_app["client"].put(
        "/api/v1/auth/me/zenodo-active-credentials/sandbox",
        headers=auth_app["recipient_headers"],
        json={"credential_id": credential["id"]},
    )
    assert active_response.status_code == 200
    active_credential = active_response.get_json()["data"]["credential"]
    assert active_credential["source"] == "shared"
    assert active_credential["active"] is True

    list_response = auth_app["client"].get(
        "/api/v1/auth/me/zenodo-credentials",
        headers=auth_app["recipient_headers"],
    )
    assert list_response.status_code == 200
    payload = list_response.get_json()["data"]
    assert payload["active"]["sandbox"]["id"] == credential["id"]
    assert payload["credentials"][0]["source"] == "shared"
    assert "route-shared-secret" not in list_response.get_data(as_text=True)

    revoke_response = auth_app["client"].delete(
        f"/api/v1/auth/me/zenodo-credential-shares/{share['id']}",
        headers=auth_app["headers"],
    )
    assert revoke_response.status_code == 200
    with auth_app["app"].app_context():
        revoked_notification = Notification.query.filter_by(
            recipient_user_id=auth_app["recipient_id"],
            notification_type="credential.share_revoked",
        ).one()
        assert revoked_notification.severity == "warning"


def test_personal_zenodo_share_decline_notifies_owner(auth_app):
    create_response = auth_app["client"].post(
        "/api/v1/auth/me/zenodo-credentials",
        headers=auth_app["headers"],
        json={"name": "Decline sandbox", "environment": "sandbox", "token": "route-decline-secret"},
    )
    assert create_response.status_code == 201
    credential = create_response.get_json()["data"]["credential"]

    share_response = auth_app["client"].post(
        f"/api/v1/auth/me/zenodo-credentials/{credential['id']}/share",
        headers=auth_app["headers"],
        json={"recipient_email": "recipient@example.com"},
    )
    assert share_response.status_code == 201
    share = share_response.get_json()["data"]["share"]

    decline_response = auth_app["client"].post(
        f"/api/v1/auth/me/zenodo-credential-shares/{share['id']}/decline",
        headers=auth_app["recipient_headers"],
    )
    assert decline_response.status_code == 200
    with auth_app["app"].app_context():
        declined_notification = Notification.query.filter_by(
            recipient_user_id=auth_app["user_id"],
            notification_type="credential.share_declined",
        ).one()
        assert declined_notification.payload["status"] == "declined"


def test_auth_me_returns_derived_groups_from_capabilities(auth_app):
    response = auth_app["client"].get("/api/v1/auth/me", headers=auth_app["headers"])

    assert response.status_code == 200
    user_payload = response.get_json()["data"]["user"]
    assert "developer_access" in user_payload["capabilities"]
    assert "developer" in user_payload["groups"]


def test_account_update_accepts_internal_profile_visibility_and_rejects_public(auth_app):
    internal_response = auth_app["client"].put(
        "/api/v1/auth/me",
        headers=auth_app["headers"],
        json={"profile_visibility": "internal"},
    )
    assert internal_response.status_code == 200
    assert internal_response.get_json()["data"]["user"]["profile_visibility"] == "internal"

    public_response = auth_app["client"].put(
        "/api/v1/auth/me",
        headers=auth_app["headers"],
        json={"profile_visibility": "public"},
    )
    assert public_response.status_code == 400
    assert "private or internal" in public_response.get_json()["error"]["message"]


def test_password_login_is_default_without_email_delivery(auth_app):
    response = _login_for_mfa(auth_app, email="recipient@example.com")
    assert response.status_code == 200
    assert response.get_json()["data"]["access_token"]
    assert response.get_json()["data"]["user"]["mfa_enabled"] is False
    assert not auth_app["email_service"].login_codes


def test_optional_mfa_enrollment_verify_and_disable(auth_app):
    client = auth_app["client"]
    headers = auth_app["recipient_headers"]
    start = client.post("/api/v1/auth/me/mfa", headers=headers, json={"enabled": True, "current_password": "password123"})
    assert start.status_code == 202
    token = start.get_json()["data"]["mfa_token"]
    code = auth_app["email_service"].login_codes[-1]["code"]
    assert _login_for_mfa(auth_app, email="recipient@example.com").status_code == 200
    assert client.post("/api/v1/auth/login/verify-code", json={"mfa_token": token, "code": code}).status_code == 400
    assert client.post("/api/v1/auth/me/mfa/verify", headers=auth_app["headers"], json={"mfa_token": token, "code": code}).status_code == 400
    confirmed = client.post("/api/v1/auth/me/mfa/verify", headers=headers, json={"mfa_token": token, "code": code})
    assert confirmed.status_code == 200
    assert confirmed.get_json()["data"]["user"]["mfa_enabled"] is True
    assert _login_for_mfa(auth_app, email="recipient@example.com").status_code == 202
    assert client.post("/api/v1/auth/me/mfa", headers=headers, json={"enabled": False, "current_password": "wrong"}).status_code == 400
    assert client.post("/api/v1/auth/me/mfa", headers=headers, json={"enabled": False, "current_password": "password123"}).status_code == 200
    assert _login_for_mfa(auth_app, email="recipient@example.com").status_code == 200


def test_provider_setting_cannot_bypass_user_enabled_mfa(auth_app):
    with auth_app["app"].app_context():
        db.session.add(SystemConfig(key="mfa_provider_bypass", value=json.dumps({"enabled": True, "domains": ["example.com"]})))
        db.session.commit()
    assert _login_for_mfa(auth_app).status_code == 202
