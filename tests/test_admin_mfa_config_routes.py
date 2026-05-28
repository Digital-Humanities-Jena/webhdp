import json

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import SystemConfig, User, UserRole
from middleware import setup_error_handlers
from routes.admin_routes import admin_bp


def _make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
    setup_error_handlers(app)

    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(admin_bp, url_prefix="/api/v1/admin")
    return app


def test_admin_mfa_config_routes_round_trip():
    app = _make_app()
    with app.app_context():
        db.create_all()
        admin = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
        admin.set_password("password123")
        db.session.add(admin)
        db.session.commit()
        token = create_access_token(identity=str(admin.id))

    client = app.test_client()
    headers = {"Authorization": f"Bearer {token}"}

    get_response = client.get("/api/v1/admin/mfa-config", headers=headers)
    assert get_response.status_code == 200
    default_config = get_response.get_json()["data"]["config"]
    assert default_config == {
        "enabled": False,
        "domains": ["gmail.com", "googlemail.com"],
    }

    post_response = client.post(
        "/api/v1/admin/mfa-config",
        headers=headers,
        json={"enabled": True, "domains": ["@GMAIL.com", "googlemail.com", "gmail.com"]},
    )
    assert post_response.status_code == 200
    saved_config = post_response.get_json()["data"]["config"]
    assert saved_config == {
        "enabled": True,
        "domains": ["gmail.com", "googlemail.com"],
    }

    with app.app_context():
        persisted = db.session.get(SystemConfig, "mfa_provider_bypass")
        assert persisted is not None
        assert json.loads(persisted.value) == saved_config

    invalid_response = client.post(
        "/api/v1/admin/mfa-config",
        headers=headers,
        json={"enabled": True, "domains": ["not a domain"]},
    )
    assert invalid_response.status_code == 400
    assert invalid_response.get_json()["error"]["code"] == "VALIDATION_ERROR"
