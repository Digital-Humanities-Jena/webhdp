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


def test_admin_version_detection_config_routes_round_trip():
    app = _make_app()
    with app.app_context():
        db.create_all()
        admin = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
        admin.set_password("password123")
        db.session.add(admin)
        db.session.commit()
        token = create_access_token(identity=str(admin.id))

    client = app.test_client()

    get_response = client.get(
        "/api/v1/admin/version-detection-config",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_response.status_code == 200
    default_config = get_response.get_json()["data"]["config"]
    assert default_config["preset"] == "balanced"
    assert default_config["thresholds"] == {
        "version_recommendation_score": 0.9,
        "warning_score": 0.35,
    }
    assert default_config["allow_force_create_fresh"] is True
    assert default_config["enabled_signals"] == {
        "hash_matching": True,
        "metadata_similarity": True,
    }
    assert default_config["hash_collision_policy"] == {
        "enabled": True,
        "min_size_bytes": 1048576,
        "excluded_extensions": [".csv", ".json", ".log", ".md", ".text", ".tsv", ".txt", ".xml"],
        "exclude_generated_renders": True,
    }

    post_response = client.post(
        "/api/v1/admin/version-detection-config",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "preset": "STRICT",
            "allow_force_create_fresh": False,
            "enabled_signals": {
                "hash_matching": False,
            },
            "hash_collision_policy": {
                "enabled": True,
                "min_size_bytes": 2048,
                "excluded_extensions": ["json", ".XML", "txt"],
                "exclude_generated_renders": False,
            },
        },
    )
    assert post_response.status_code == 200
    saved_config = post_response.get_json()["data"]["config"]
    assert saved_config == {
        "preset": "strict",
        "thresholds": {
            "version_recommendation_score": 0.95,
            "warning_score": 0.45,
        },
        "allow_force_create_fresh": False,
        "enabled_signals": {
            "hash_matching": False,
            "metadata_similarity": True,
        },
        "hash_collision_policy": {
            "enabled": True,
            "min_size_bytes": 2048,
            "excluded_extensions": [".json", ".txt", ".xml"],
            "exclude_generated_renders": False,
        },
    }

    with app.app_context():
        persisted = db.session.get(SystemConfig, "version_detection_policy")
        assert persisted is not None
        assert json.loads(persisted.value) == saved_config

    round_trip_response = client.get(
        "/api/v1/admin/version-detection-config",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert round_trip_response.status_code == 200
    assert round_trip_response.get_json()["data"]["config"] == saved_config
