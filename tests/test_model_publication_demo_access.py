import time
from uuid import uuid4

import pytest
from flask import Flask, jsonify
from flask_jwt_extended import JWTManager, create_access_token, decode_token, jwt_required

from database.database import db
from database.models import SystemConfig, User, UserRole
from middleware import setup_error_handlers
from routes.auth_routes import auth_bp
from routes.model_publication_routes import model_publication_bp
from routes.webhdp_link_routes import webhdp_link_bp
from services import model_publication_queue as queue, webhdp_link_service as link
from services.model_publication_accounts import (
    DEMO_CAPABILITY,
    DEMO_CLAIM,
    DEMO_SECONDS,
    demo_config_key,
    register_demo_jwt_scope,
)

DEMO_EMAIL = "model-demo-44d50ec1@webhdp.invalid"
DEMO_PASSWORD = "demonstration fixture password"
PUBLICATION = "/api/v1/model-publication"
AUTH = "/api/v1/auth"
LINK = "/api/v1/link"


def bearer(token):
    return {"Authorization": "Bearer " + token}


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("ZENODO_SANDBOX_API_KEY", "private-sandbox-fixture")
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        JWT_SECRET_KEY="isolated-demo-access-signing-key-for-tests",
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        MODEL_PUBLICATION_ENABLED=True,
        MODEL_PUBLICATION_ROOT=tmp_path,
    )
    db.init_app(app)
    jwt = JWTManager(app)
    register_demo_jwt_scope(jwt)
    setup_error_handlers(app)
    app.register_blueprint(auth_bp, url_prefix=AUTH)
    app.register_blueprint(model_publication_bp, url_prefix=PUBLICATION)
    app.register_blueprint(webhdp_link_bp, url_prefix=LINK)

    @app.get("/start-session-file")
    @jwt_required()
    def ordinary_account_route():
        return jsonify({"data": "normal-account-only"})

    (tmp_path / ".heartbeat").touch()
    with app.app_context():
        db.create_all()
        admin = User(email="admin@example.test", password_hash="unused", role=UserRole.ADMIN, is_verified=True)
        demo = User(email=DEMO_EMAIL, display_name="Live demonstration", is_verified=True)
        demo.set_password(DEMO_PASSWORD)
        db.session.add_all([admin, demo])
        db.session.commit()
        expiry = int(time.time()) + DEMO_SECONDS
        key = demo_config_key(demo.id)
        db.session.add(SystemConfig(key=key, value=str(expiry)))
        db.session.commit()

        browser_app = link.save_client({"id": "model-deposit-tests", "name": "Test application"})
        with app.test_request_context():
            existing_token = link.issue_token(browser_app, demo, service=True)["access_token"]
        demo.set_capabilities([DEMO_CAPABILITY])
        db.session.commit()

        yield {
            "app": app,
            "client": app.test_client(),
            "admin_id": admin.id,
            "admin_jwt": create_access_token(identity=str(admin.id)),
            "demo_id": demo.id,
            "demo_link": existing_token,
            "expiry": expiry,
            "policy_key": key,
            "queue_root": tmp_path,
        }


def demo_login(api):
    return api["client"].post(AUTH + "/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})


def test_demo_scope_limits_routes_and_returns_minimal_user_context(api):
    client = api["client"]
    login = demo_login(api)
    assert login.status_code == 200
    data = login.json["data"]
    assert data["user"] == {
        "email": DEMO_EMAIL,
        "display_name": "Live demonstration",
        "role": "user",
        "model_publication_only": True,
        "model_publication_expires_at": api["expiry"],
    }
    jwt = decode_token(data["access_token"])
    assert jwt[DEMO_CLAIM] is True
    assert abs(jwt["exp"] - api["expiry"]) <= 1
    headers = bearer(data["access_token"])

    assert client.get(AUTH + "/me", headers=headers).json["data"]["user"] == data["user"]
    assert client.get(PUBLICATION + "/availability", headers=headers).status_code == 200
    assert client.get(PUBLICATION + "/queue", headers=headers).status_code == 200
    assert client.get(PUBLICATION + "/samples").status_code == 200
    assert client.get("/start-session-file", headers=bearer(api["admin_jwt"])).json["data"] == "normal-account-only"
    for method, path in (
        ("GET", "/start-session-file"),
        ("GET", AUTH + "/me/zenodo-credentials"),
        ("PUT", AUTH + "/me"),
        ("PUT", AUTH + "/me/password"),
        ("POST", AUTH + "/me/mfa"),
    ):
        response = client.open(path, method=method, headers=headers, json={})
        assert response.status_code == 403
        assert response.json["error"]["code"] == "DEMO_WORKFLOW_ONLY"
    assert client.post(LINK + "/oauth/authorize", headers=headers, json={}).status_code in {401, 403}
    assert client.post(AUTH + "/logout", headers=headers).status_code == 200


def test_demo_cannot_read_other_sign_ins_or_accounts_results(api):
    client = api["client"]
    base = api["queue_root"]
    demo_headers = bearer(demo_login(api).json["data"]["access_token"])
    other_demo_headers = bearer(demo_login(api).json["data"]["access_token"])
    own = client.post(PUBLICATION + "/jobs", headers=demo_headers, data={"sample_id": "bronze-seal"})
    assert own.status_code == 202
    own_id = own.json["data"]["job"]["id"]
    admin_id, _ = queue.reserve(
        base, user_id=api["admin_id"], sign_in="owner-sign-in", request_key=uuid4().hex,
        demo_window=0, parameters={"sample_id": "bronze-seal"},
    )
    queue.enqueue(base, admin_id)

    for owner in (own_id, admin_id):
        queue.claim(base)
        marker = base / owner / "results" / "model.zip"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_bytes(b"private fixture")
        queue.update(base, owner, "completed", result={"files": [{"name": "model.zip"}]})

    assert client.get(PUBLICATION + f"/jobs/{own_id}/files/model.zip", headers=demo_headers).data == b"private fixture"
    for job, headers in ((own_id, other_demo_headers), (admin_id, demo_headers)):
        assert client.get(PUBLICATION + f"/jobs/{job}", headers=headers).status_code == 404
        assert client.get(PUBLICATION + f"/jobs/{job}/files/model.zip", headers=headers).status_code == 404
    assert client.get(PUBLICATION + "/jobs", headers=other_demo_headers).json["data"]["jobs"] == []


def test_closed_or_elevated_demo_cannot_sign_in_and_issue_link_credentials(api):
    client = api["client"]
    demo = db.session.get(User, api["demo_id"])
    demo.set_capabilities([])
    db.session.commit()
    # The reserved account address retains the scope even if the capability is removed.
    token = demo_login(api).json["data"]["access_token"]
    assert client.get(AUTH + "/me/zenodo-credentials", headers=bearer(token)).status_code == 403
    assert client.get(LINK + "/pipelines", headers=bearer(api["demo_link"])).status_code == 403
    assert client.post(
        LINK + "/admin/clients/model-deposit-tests/tokens",
        headers=bearer(api["admin_jwt"]), json={"user_id": demo.id},
    ).status_code == 403

    demo.role = UserRole.ADMIN
    db.session.commit()
    assert demo_login(api).json["error"]["code"] == "DEMO_CLOSED"
    assert client.get(PUBLICATION + "/jobs", headers=bearer(token)).status_code == 403

    demo.role = UserRole.USER
    policy = db.session.get(SystemConfig, api["policy_key"])
    policy.value = str(int(time.time()) - 1)
    db.session.commit()
    assert demo_login(api).json["error"]["code"] == "DEMO_CLOSED"
    assert client.get(PUBLICATION + "/jobs", headers=bearer(token)).status_code == 403


def test_demo_login_throttling_is_independent_of_regular_logins_and_other_sources(api, monkeypatch):
    monkeypatch.setenv("LOGIN_RATE_LIMIT_ATTEMPTS", "5")
    client = api["client"]
    first_ip = {"X-Forwarded-For": "192.0.2.10"}
    second_ip = {"X-Forwarded-For": "192.0.2.11"}
    good = {"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
    invalid = {"email": DEMO_EMAIL, "password": "incorrect"}
    for _ in range(5):
        response = client.post(AUTH + "/login", json=invalid, headers=first_ip)
        assert response.status_code == 400
        assert response.json["error"]["message"] == "Invalid email or password"

    assert client.post(AUTH + "/login", json=good, headers=first_ip).status_code == 200

    missing_demo = {"email": "model-demo-00000000@webhdp.invalid", "password": "incorrect"}
    for _ in range(20):
        assert client.post(AUTH + "/login", json=missing_demo, headers=first_ip).status_code == 400
    limited = client.post(AUTH + "/login", json=good, headers=first_ip)
    assert limited.status_code == 429
    assert 1 <= limited.json["error"]["details"]["retry_after_seconds"] <= 30
    assert client.post(AUTH + "/login", json=good, headers=second_ip).status_code == 200

    regular = {"email": "regular@example.test", "password": "incorrect"}
    for _ in range(5):
        assert client.post(AUTH + "/login", json=regular, headers=first_ip).status_code == 400
    assert client.post(AUTH + "/login", json=regular, headers=first_ip).status_code == 429
