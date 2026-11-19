import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from flask_mail import Mail

from database.database import db
from database.models import AuditEvent, Institution, InstitutionInvitation, InstitutionMembership, InstitutionRole, User, UserRole
from middleware import setup_error_handlers
from routes.auth_routes import auth_bp
from routes.institution_invitation_routes import institution_invitation_bp
from services import institution_invitation_service
from services.email_service import EmailService


@pytest.fixture
def site(tmp_path):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'invitations.sqlite'}",
        JWT_SECRET_KEY="invitation test JWT key of at least 32 bytes",
        FRONTEND_URL="https://webhdp.example.test",
        MAIL_DEFAULT_SENDER="mail@example.test",
    )
    db.init_app(app)
    JWTManager(app)
    setup_error_handlers(app)
    app.register_blueprint(auth_bp, url_prefix="/api/v1/auth")
    app.register_blueprint(institution_invitation_bp, url_prefix="/api/v1/institutions")
    sent = []

    def capture(*arguments):
        sent.append(arguments)
        return True

    app.email_service = SimpleNamespace(send_institution_invitation=capture)
    ids = {}

    def add_user(email, *, verified=True, role=UserRole.USER):
        with app.app_context():
            user = User(email=email, is_verified=verified, role=role)
            user.set_password("test account password")
            db.session.add(user)
            db.session.commit()
            ids[email] = user.id
            return {"Authorization": "Bearer " + create_access_token(identity=str(user.id))}

    with app.app_context():
        db.create_all()
    headers = {
        label: add_user(f"{label}@example.test", role=UserRole.ADMIN if label == "admin" else UserRole.USER)
        for label in ("admin", "owner", "manager", "reader", "outsider")
    }
    with app.app_context():
        institution = Institution(name="Workshop Museum", slug="workshop-museum")
        other = Institution(name="Other Institution", slug="other-institution")
        db.session.add_all([institution, other])
        db.session.flush()
        for label, role in (("owner", InstitutionRole.OWNER), ("manager", InstitutionRole.MANAGER),
                            ("reader", InstitutionRole.READER)):
            db.session.add(InstitutionMembership(institution_id=institution.id, user_id=ids[f"{label}@example.test"], role=role))
        institution_id, other_id = institution.id, other.id
        db.session.commit()

    return SimpleNamespace(
        app=app, client=app.test_client(), sent=sent, ids=ids, headers=headers, add_user=add_user,
        institution_id=institution_id, other_id=other_id,
        url=f"/api/v1/institutions/{institution_id}/invitations",
    )


def issue(site, email="recipient@example.test", *, role="curator", actor="manager"):
    return site.client.post(site.url, json={"email": email, "role": role}, headers=site.headers[actor])


def recipient_action(site, action, token, headers):
    return site.client.post(f"/api/v1/institutions/invitations/{action}", json={"token": token}, headers=headers)


def test_invite_before_registration_and_accept_only_as_verified_recipient(site):
    response = issue(site, "Recipient@Example.test")
    assert response.status_code == 200
    saved = response.json["data"]
    assert saved["delivery"] == "sent"
    assert saved["invitation"]["email"] == "Recipient@example.test"
    assert "no-store" in response.headers["Cache-Control"]
    mail_address, token, name, role = site.sent[0]
    assert (mail_address, name, role) == ("Recipient@example.test", "Workshop Museum", "curator")
    assert token not in response.get_data(as_text=True)
    with site.app.app_context():
        row = db.session.get(InstitutionInvitation, saved["invitation"]["id"])
        assert row.recipient_email == "recipient@example.test"
        assert row.token_hash == hashlib.sha256(token.encode("ascii")).hexdigest()
        assert row.accepted_at is None

    mismatch = recipient_action(site, "preview", token, site.headers["outsider"])
    assert mismatch.status_code == 403
    assert mismatch.json["error"]["code"] == "INVITATION_EMAIL_MISMATCH"
    assert "recipient@example.test" not in mismatch.get_data(as_text=True)
    assert recipient_action(site, "accept", token, site.headers["outsider"]).status_code == 403

    recipient = site.add_user("recipient@example.test", verified=False)
    assert recipient_action(site, "accept", token, recipient).status_code == 403
    with site.app.app_context():
        user = db.session.get(User, site.ids["recipient@example.test"])
        user.is_verified = True
        db.session.commit()

    preview = recipient_action(site, "preview", token, recipient)
    assert preview.json["data"]["institution"]["name"] == "Workshop Museum"
    assert preview.json["data"]["role"] == "curator"
    assert "recipient@example.test" not in preview.get_data(as_text=True)
    accepted = recipient_action(site, "accept", token, recipient)
    assert accepted.status_code == 200
    assert accepted.json["data"]["membership"]["role"] == "curator"
    assert recipient_action(site, "accept", token, recipient).status_code == 404
    assert site.client.delete(site.url + "/" + saved["invitation"]["id"], headers=site.headers["manager"]).status_code == 409
    with site.app.app_context():
        row = db.session.get(InstitutionInvitation, saved["invitation"]["id"])
        assert row.accepted_by_user_id == site.ids["recipient@example.test"]
        assert row.token_hash is None
        assert InstitutionMembership.query.filter_by(institution_id=site.institution_id, user_id=row.accepted_by_user_id).one().role == InstitutionRole.CURATOR
        audit = AuditEvent.query.filter_by(event_type="institution_invitation_accepted").one()
        assert audit.actor_user_id == row.accepted_by_user_id
        assert token not in audit.details_json
        assert "recipient@example.test" not in audit.details_json


def test_first_time_user_can_register_sign_in_then_accept(site):
    email = "NewResearcher@example.test"
    confirmation_links = []

    def capture_verification(address, token):
        confirmation_links.append((address, token))
        return True

    site.app.email_service.send_verification_email = capture_verification
    assert issue(site, email).status_code == 200
    invitation_token = site.sent[-1][1]
    response = site.client.post("/api/v1/auth/register", json={"email": email})
    assert response.status_code == 202
    assert confirmation_links[0][0] == email
    with site.app.app_context():
        assert User.query.filter_by(email=email).first() is None

    password = "new account test password"
    response = site.client.post(
        "/api/v1/auth/verify-email", json={"token": confirmation_links[0][1], "password": password}
    )
    assert response.status_code == 200
    login = site.client.post("/api/v1/auth/login", json={"email": email.lower(), "password": password})
    headers = {"Authorization": "Bearer " + login.json["data"]["access_token"]}
    accepted = recipient_action(site, "accept", invitation_token, headers)
    assert accepted.status_code == 200
    assert accepted.json["data"]["membership"]["role"] == "curator"
    account = site.client.get("/api/v1/auth/me", headers=headers)
    assert account.json["data"]["user"]["memberships"][0]["institution_id"] == site.institution_id


def test_invitations_are_managed_only_in_their_institution_and_owner_grants_are_protected(site):
    assert issue(site, actor="reader").status_code in {403, 404}
    assert issue(site, actor="outsider").status_code in {403, 404}
    assert issue(site, actor="manager", role="owner").status_code == 403
    assert site.sent == []
    created = issue(site, actor="owner", role="owner").json["data"]["invitation"]
    assert site.client.get(site.url, headers=site.headers["manager"]).json["data"]["invitations"] == []
    assert site.client.get(site.url, headers=site.headers["owner"]).json["data"]["total"] == 1
    assert site.client.delete(site.url + "/" + created["id"], headers=site.headers["manager"]).status_code == 404
    wrong_workspace_url = f"/api/v1/institutions/{site.other_id}/invitations/{created['id']}"
    assert site.client.delete(wrong_workspace_url, headers=site.headers["admin"]).status_code == 404
    assert site.client.get(site.url, headers=site.headers["reader"]).status_code in {403, 404}


@pytest.mark.parametrize("problem", ["expired", "revoked", "issuer_lost_access"])
def test_inactive_invitation_cannot_grant_membership(site, problem):
    recipient = site.add_user("recipient@example.test")
    created = issue(site).json["data"]["invitation"]
    token = site.sent[-1][1]
    if problem == "revoked":
        for _ in range(2):
            revoked = site.client.delete(site.url + "/" + created["id"], headers=site.headers["manager"])
            assert revoked.json["data"]["invitation"]["status"] == "revoked"
    else:
        with site.app.app_context():
            if problem == "expired":
                row = db.session.get(InstitutionInvitation, created["id"])
                row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
            else:
                membership = InstitutionMembership.query.filter_by(user_id=site.ids["manager@example.test"]).one()
                membership.role = InstitutionRole.READER
            db.session.commit()
    assert recipient_action(site, "preview", token, recipient).json["error"]["code"] == "INVITATION_INVALID"
    assert recipient_action(site, "accept", token, recipient).status_code == 404
    with site.app.app_context():
        assert InstitutionMembership.query.filter_by(user_id=site.ids["recipient@example.test"]).first() is None


def test_failed_delivery_is_retriable_and_resend_invalidates_old_link(site, monkeypatch, caplog):
    recipient = site.add_user("recipient@example.test")
    original_sender = site.app.email_service.send_institution_invitation

    def fail_with_sensitive_diagnostics(*arguments):
        original_sender(*arguments)
        raise RuntimeError(f"Transport details {arguments[0]} {arguments[1]}")

    monkeypatch.setattr(site.app.email_service, "send_institution_invitation", fail_with_sensitive_diagnostics)
    with caplog.at_level(logging.WARNING):
        initial = issue(site)
    original = initial.json["data"]
    old_token = site.sent[-1][1]
    assert original["delivery"] == "failed"
    assert original["invitation"]["delivery"] == "failed"
    assert old_token not in caplog.text
    assert "recipient@example.test" not in caplog.text
    too_soon = issue(site)
    assert too_soon.status_code == 429
    assert too_soon.json["error"]["code"] == "INVITATION_RATE_LIMITED"
    assert 0 < int(too_soon.headers["Retry-After"]) <= 60

    with site.app.app_context():
        row = db.session.get(InstitutionInvitation, original["invitation"]["id"])
        row.delivery_attempted_at -= timedelta(minutes=2)
        db.session.commit()
    monkeypatch.setattr(site.app.email_service, "send_institution_invitation", original_sender)
    resent = issue(site, role="reader").json["data"]
    assert resent["invitation"]["id"] == original["invitation"]["id"]
    assert resent["delivery"] == "sent"
    new_token = site.sent[-1][1]
    assert new_token != old_token
    assert recipient_action(site, "accept", old_token, recipient).status_code == 404
    assert recipient_action(site, "accept", new_token, recipient).json["data"]["membership"]["role"] == "reader"


def test_acceptance_preserves_existing_membership_role(site):
    assert issue(site, "reader@example.test", role="manager").status_code == 200
    accepted = recipient_action(site, "accept", site.sent[-1][1], site.headers["reader"])
    assert accepted.status_code == 200
    assert accepted.json["data"]["already_member"] is True
    assert accepted.json["data"]["membership"]["role"] == "reader"


def test_a_failed_resend_preserves_the_previously_delivered_invitation(site, monkeypatch):
    recipient = site.add_user("recipient@example.test")
    invitation = issue(site, role="reader").json["data"]["invitation"]
    old_token = site.sent[-1][1]
    with site.app.app_context():
        row = db.session.get(InstitutionInvitation, invitation["id"])
        row.delivery_attempted_at -= timedelta(minutes=2)
        db.session.commit()

    monkeypatch.setattr(site.app.email_service, "send_institution_invitation", lambda *_: False)
    failed = issue(site, role="curator").json["data"]
    assert failed["delivery"] == "failed"
    assert failed["invitation"]["role"] == "reader"
    assert recipient_action(site, "accept", old_token, recipient).json["data"]["membership"]["role"] == "reader"


def test_two_workers_cannot_consume_the_same_invitation(site):
    recipient = site.add_user("recipient@example.test")
    assert issue(site).status_code == 200
    token = site.sent[-1][1]
    concurrent = Barrier(2)

    def accept():
        with site.app.test_client() as client:
            concurrent.wait(timeout=3)
            return client.post(
                "/api/v1/institutions/invitations/accept", json={"token": token}, headers=recipient
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: accept(), range(2)))
    assert results.count(200) == 1
    assert set(results) in ({200, 404}, {200, 409})
    with site.app.app_context():
        assert InstitutionMembership.query.filter_by(user_id=site.ids["recipient@example.test"]).count() == 1
        assert AuditEvent.query.filter_by(event_type="institution_invitation_accepted").count() == 1


def test_acceptance_failure_rolls_back_grant_and_never_notifies_before_commit(site, monkeypatch):
    recipient = site.add_user("recipient@example.test")
    assert issue(site).status_code == 200
    token = site.sent[-1][1]
    original_audit = institution_invitation_service._audit
    notifications = []
    monkeypatch.setattr("services.institution_service.notify_user", lambda **data: notifications.append(data))

    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(institution_invitation_service, "_audit", fail_audit)
    assert recipient_action(site, "accept", token, recipient).status_code == 500
    with site.app.app_context():
        assert InstitutionMembership.query.filter_by(user_id=site.ids["recipient@example.test"]).first() is None
        assert AuditEvent.query.filter_by(event_type="institution_membership_upserted").first() is None
        assert InstitutionInvitation.query.one().accepted_at is None
    assert notifications == []
    monkeypatch.setattr(institution_invitation_service, "_audit", original_audit)
    assert recipient_action(site, "accept", token, recipient).status_code == 200


def test_legacy_addresses_with_ambiguous_identity_do_not_accept_invitations(site):
    first = site.add_user("Recipient@example.test")
    second = site.add_user("recipient@example.test")
    assert issue(site).status_code == 200
    for actor in (first, second):
        result = recipient_action(site, "accept", site.sent[-1][1], actor)
        assert result.status_code == 409
        assert result.json["error"]["code"] == "EMAIL_IDENTITY_AMBIGUOUS"


def test_invalid_invitation_details_do_not_send_email(site):
    for invalid in ("invalid-address", "recipient@example.test\r\nBcc: someone@example.test"):
        assert issue(site, invalid).status_code == 400
    response = issue(site, role={"role": "owner"})
    assert response.status_code == 400
    assert site.sent == []


def test_delivery_limit_counts_attempts_for_the_institution(site, monkeypatch):
    monkeypatch.setattr("services.institution_invitation_service.INSTITUTION_DELIVERY_LIMIT", 1)
    assert issue(site, "first@example.test").status_code == 200
    limited = issue(site, "second@example.test")
    assert limited.status_code == 429
    assert 0 < int(limited.headers["Retry-After"]) <= 3600
    assert len(site.sent) == 1


def test_institution_invitation_link_keeps_token_in_fragment(site):
    mail = Mail(site.app)
    with site.app.app_context(), mail.record_messages() as messages:
        assert EmailService(mail).send_institution_invitation("recipient@example.test", "test-token", "Workshop Museum", "reader")
    link = next(line for line in messages[0].body.splitlines() if line.startswith("https://"))
    url = urlsplit(link)
    assert url.scheme == "https"
    assert url.path == "/institution-invitation"
    assert url.query == ""
    assert parse_qs(url.fragment) == {"token": ["test-token"]}
