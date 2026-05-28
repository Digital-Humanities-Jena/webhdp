import importlib
import json

import pytest
pytest.importorskip("flask_sqlalchemy")
pytest.importorskip("cryptography.fernet")
from flask import Flask

from database.database import db
from database.models import AuditEvent, User, UserRole

zenodo_credential_service = importlib.import_module("services.zenodo_credential_service")
ZenodoCredentialService = zenodo_credential_service.ZenodoCredentialService


class _MockResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


@pytest.fixture()
def credential_service_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "credential-service-secret"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    with app.app_context():
        db.create_all()
        user = User(email="owner@example.com", role=UserRole.USER, is_verified=True)
        user.set_password("password123")
        recipient = User(email="recipient@example.com", role=UserRole.USER, is_verified=True)
        recipient.set_password("password123")
        db.session.add_all([user, recipient])
        db.session.commit()

        yield {
            "app": app,
            "user_id": user.id,
            "recipient_id": recipient.id,
        }

        db.session.remove()
        db.drop_all()


def test_serialize_handles_missing_validation_report(credential_service_app):
    service = ZenodoCredentialService()

    with credential_service_app["app"].app_context():
        credential = service.upsert_credential(
            owner_type="user",
            owner_id=credential_service_app["user_id"],
            environment="sandbox",
            token="sandbox-token",
            actor_user_id=credential_service_app["user_id"],
        )

        serialized = service.serialize(credential)
        assert serialized["validation_status"] == "unknown"
        assert serialized["validation_mode"] == "live_write_cleanup"
        assert serialized["validation_report"] is None
        assert serialized["recommended_scopes"] == ["deposit:write", "deposit:actions"]


def test_named_credentials_share_accept_and_active_resolution_without_token_leakage(credential_service_app):
    service = ZenodoCredentialService()
    clear_token = "shared-secret-token"

    with credential_service_app["app"].app_context():
        first = service.create_credential(
            user_id=credential_service_app["user_id"],
            environment="sandbox",
            token="owner-first-token",
            name="Owner sandbox",
            actor_user_id=credential_service_app["user_id"],
        )
        second = service.create_credential(
            user_id=credential_service_app["user_id"],
            environment="sandbox",
            token=clear_token,
            name="Shared sandbox",
            actor_user_id=credential_service_app["user_id"],
        )

        owner_listing = service.list_available_credentials(credential_service_app["user_id"], "sandbox")
        assert [item["name"] for item in owner_listing["credentials"]] == ["Owner sandbox", "Shared sandbox"]
        assert owner_listing["active"]["sandbox"]["id"] == first.id

        share = service.share_credential(
            credential_id=second.id,
            owner_user_id=credential_service_app["user_id"],
            recipient_email="recipient@example.com",
        )
        pending_listing = service.list_available_credentials(credential_service_app["recipient_id"], "sandbox")
        assert pending_listing["credentials"] == []
        assert pending_listing["incoming_shares"][0]["credential"]["name"] == "Shared sandbox"

        service.respond_to_share(
            share_id=share.id,
            user_id=credential_service_app["recipient_id"],
            status="accepted",
        )
        service.set_active_credential(
            user_id=credential_service_app["recipient_id"],
            environment="sandbox",
            credential_id=second.id,
        )

        recipient_listing = service.list_available_credentials(credential_service_app["recipient_id"], "sandbox")
        assert recipient_listing["credentials"][0]["source"] == "shared"
        assert recipient_listing["credentials"][0]["active"] is True
        assert recipient_listing["active"]["sandbox"]["id"] == second.id
        assert clear_token not in json.dumps(recipient_listing)


def test_validate_credential_success_creates_and_deletes_test_draft_without_leaking_token(monkeypatch, credential_service_app):
    service = ZenodoCredentialService()
    calls = []
    clear_token = "secret-live-token"

    def fake_get(url, **kwargs):
        calls.append(("get", url, kwargs))
        return _MockResponse(200, [])

    def fake_post(url, **kwargs):
        calls.append(("post", url, kwargs))
        return _MockResponse(201, {"id": 12345})

    def fake_delete(url, **kwargs):
        calls.append(("delete", url, kwargs))
        return _MockResponse(204, {})

    monkeypatch.setattr(zenodo_credential_service.requests, "get", fake_get)
    monkeypatch.setattr(zenodo_credential_service.requests, "post", fake_post)
    monkeypatch.setattr(zenodo_credential_service.requests, "delete", fake_delete)

    with credential_service_app["app"].app_context():
        service.upsert_credential(
            owner_type="user",
            owner_id=credential_service_app["user_id"],
            environment="sandbox",
            token=clear_token,
            actor_user_id=credential_service_app["user_id"],
        )

        credential = service.validate_credential(
            owner_type="user",
            owner_id=credential_service_app["user_id"],
            environment="sandbox",
            actor_user_id=credential_service_app["user_id"],
        )
        serialized = service.serialize(credential)
        audit_event = AuditEvent.query.filter_by(event_type="zenodo_credential_validated").first()

        assert [call[0] for call in calls] == ["get", "post", "delete"]
        assert calls[0][2]["params"] == {"size": 1}
        assert calls[1][2]["json"] == {}
        assert calls[2][1].endswith("/api/deposit/depositions/12345")
        assert serialized["validation_status"] == "valid"
        assert serialized["validation_mode"] == "live_write_cleanup"
        assert serialized["last_validation_error"]
        assert serialized["validation_report"]["capabilities"]["authentication"]["status"] == "verified"
        assert serialized["validation_report"]["capabilities"]["deposit_read"]["status"] == "verified"
        assert serialized["validation_report"]["capabilities"]["draft_create"]["status"] == "verified"
        assert serialized["validation_report"]["capabilities"]["draft_cleanup"]["status"] == "verified"
        assert clear_token not in json.dumps(serialized)
        assert audit_event is not None
        assert clear_token not in audit_event.details_json


def test_validate_token_401_marks_invalid(monkeypatch):
    service = ZenodoCredentialService()
    monkeypatch.setattr(
        zenodo_credential_service.requests,
        "get",
        lambda *args, **kwargs: _MockResponse(401, {"message": "Unauthorized"}),
    )

    report = service.validate_token("sandbox", "bad-token")

    assert report["aggregate_status"] == "invalid"
    assert "invalid" in report["summary"].lower() or "rejected" in report["summary"].lower()
    assert report["capabilities"]["authentication"]["status"] == "invalid"
    assert report["capabilities"]["draft_create"]["status"] == "invalid"


def test_validate_token_403_marks_scope_guidance(monkeypatch):
    service = ZenodoCredentialService()
    monkeypatch.setattr(
        zenodo_credential_service.requests,
        "get",
        lambda *args, **kwargs: _MockResponse(403, {"message": "Missing deposit scopes"}),
    )

    report = service.validate_token("production", "scoped-token")

    assert report["aggregate_status"] == "invalid"
    assert "deposit:write" in report["summary"]
    assert report["capabilities"]["authentication"]["status"] == "verified"
    assert report["capabilities"]["deposit_read"]["status"] == "invalid"
    assert report["capabilities"]["draft_create"]["status"] == "invalid"


def test_validate_token_429_marks_unreachable(monkeypatch):
    service = ZenodoCredentialService()
    monkeypatch.setattr(
        zenodo_credential_service.requests,
        "get",
        lambda *args, **kwargs: _MockResponse(429, {"message": "Too Many Requests"}),
    )

    report = service.validate_token("sandbox", "rate-limited-token")

    assert report["aggregate_status"] == "unreachable"
    assert report["capabilities"]["authentication"]["status"] == "unreachable"


def test_validate_token_draft_create_scope_failure_marks_invalid(monkeypatch):
    service = ZenodoCredentialService()
    monkeypatch.setattr(
        zenodo_credential_service.requests,
        "get",
        lambda *args, **kwargs: _MockResponse(200, []),
    )
    monkeypatch.setattr(
        zenodo_credential_service.requests,
        "post",
        lambda *args, **kwargs: _MockResponse(403, {"message": "Missing deposit:write"}),
    )

    report = service.validate_token("sandbox", "read-only-token")

    assert report["aggregate_status"] == "invalid"
    assert report["capabilities"]["deposit_read"]["status"] == "verified"
    assert report["capabilities"]["draft_create"]["status"] == "invalid"
    assert report["capabilities"]["draft_cleanup"]["status"] == "unverified"


def test_validate_token_cleanup_failure_returns_warning(monkeypatch):
    service = ZenodoCredentialService()
    monkeypatch.setattr(
        zenodo_credential_service.requests,
        "get",
        lambda *args, **kwargs: _MockResponse(200, []),
    )
    monkeypatch.setattr(
        zenodo_credential_service.requests,
        "post",
        lambda *args, **kwargs: _MockResponse(201, {"id": 4444}),
    )
    monkeypatch.setattr(
        zenodo_credential_service.requests,
        "delete",
        lambda *args, **kwargs: _MockResponse(500, {"message": "Server error"}),
    )

    report = service.validate_token("production", "cleanup-fail-token")

    assert report["aggregate_status"] == "warning"
    assert report["capabilities"]["draft_create"]["status"] == "verified"
    assert report["capabilities"]["draft_cleanup"]["status"] == "warning"
