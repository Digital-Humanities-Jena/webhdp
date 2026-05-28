from flask import Flask
from flask_jwt_extended import JWTManager

from database.database import db
from database.models import SystemConfig, User, UserRole
from services.setup_guidance_service import build_admin_setup_guidance


def _make_app(*, mode="server", allow_local=False, storage_mode="pure_cloud", renderer=True, usdz=True):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
    app.config["SECRET_KEY"] = "real-secret-" + "a" * 32
    app.config["CREDENTIAL_ENCRYPTION_KEY"] = "credential-secret-" + "b" * 32
    app.config["WEBHDP_DEPLOYMENT_MODE"] = mode
    app.config["WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS"] = allow_local
    app.config["STORAGE_MODE"] = storage_mode
    app.config["ENABLE_RENDERER"] = renderer
    app.config["ENABLE_USDZ_CONVERSION"] = usdz
    db.init_app(app)
    JWTManager(app)
    return app


def _seed_admin():
    admin = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
    admin.set_password("password123")
    db.session.add(admin)
    db.session.add(SystemConfig(key="setup_completed", value="true"))
    db.session.commit()


def _readiness(local_paths_ok=True):
    return {
        "ready": local_paths_ok,
        "blockers": [] if local_paths_ok else ["local_input"],
        "checks": {
            "database": {"ok": True},
            "sessions_path": {"ok": True},
            "local_input": {"ok": local_paths_ok},
            "local_output": {"ok": True},
            "backup": {"ok": True, "backup_count": 1},
            "redis": {"ok": True},
            "maintenance": {"enabled": False},
        },
    }


def _cloud(available):
    return {
        "active_storage": "dropbox" if available else None,
        "active_message": "ok" if available else "missing",
        "services": {
            "dropbox": {"available": available, "message": "dropbox"},
            "gdrive": {"available": False, "message": "gdrive"},
        },
    }


def _item(payload, item_id):
    return next(item for item in payload["checklist"] if item["id"] == item_id)


def test_server_guidance_requires_cloud_only_for_cloud_storage():
    app = _make_app(mode="server", allow_local=False, storage_mode="pure_cloud")
    with app.app_context():
        db.create_all()
        _seed_admin()

        payload = build_admin_setup_guidance(
            app,
            readiness_report=_readiness(),
            cloud_status=_cloud(False),
            hpc_config={"enabled": False, "has_token": False, "base_url": "", "last_validation_status": "unknown"},
        )
        assert payload["deployment_class"] == "server"
        assert _item(payload, "cloud_storage")["required_level"] == "Mandatory"
        assert _item(payload, "cloud_storage")["status"] == "action_required"

        app.config["STORAGE_MODE"] = "server_only"
        payload = build_admin_setup_guidance(
            app,
            readiness_report=_readiness(),
            cloud_status=_cloud(False),
            hpc_config={"enabled": False, "has_token": False, "base_url": "", "last_validation_status": "unknown"},
        )
        assert _item(payload, "cloud_storage")["required_level"] == "Optional"
        assert _item(payload, "cloud_storage")["status"] == "complete"


def test_compute_rules_distinguish_server_hpc_requirement_and_disabled_compute():
    app = _make_app(mode="server", allow_local=False, storage_mode="server_only", renderer=True, usdz=True)
    with app.app_context():
        db.create_all()
        _seed_admin()

        payload = build_admin_setup_guidance(
            app,
            readiness_report=_readiness(),
            cloud_status=_cloud(False),
            hpc_config={"enabled": True, "has_token": True, "base_url": "https://hpc.example", "last_validation_status": "unknown"},
        )
        assert _item(payload, "compute_runtime")["required_level"] == "Mandatory"
        assert _item(payload, "compute_runtime")["status"] == "action_required"

        app.config["ENABLE_RENDERER"] = False
        app.config["ENABLE_USDZ_CONVERSION"] = False
        payload = build_admin_setup_guidance(
            app,
            readiness_report=_readiness(),
            cloud_status=_cloud(False),
            hpc_config={"enabled": False, "has_token": False, "base_url": "", "last_validation_status": "unknown"},
        )
        assert _item(payload, "compute_runtime")["required_level"] == "Optional"
        assert _item(payload, "compute_runtime")["status"] == "complete"


def test_local_guidance_uses_local_component_health_without_hpc_calls():
    app = _make_app(mode="local", allow_local=True, storage_mode="local", renderer=True, usdz=True)
    with app.app_context():
        db.create_all()
        _seed_admin()

        payload = build_admin_setup_guidance(
            app,
            readiness_report=_readiness(local_paths_ok=True),
            cloud_status=_cloud(False),
            hpc_config={"enabled": False, "has_token": False, "base_url": "", "last_validation_status": "unknown"},
            runtime_checks={"fast_renderer": True, "any_to_usdz": True},
        )

        assert payload["deployment_class"] == "workstation-local"
        assert _item(payload, "local_folder_workflows")["required_level"] == "Mandatory"
        assert _item(payload, "compute_runtime")["status"] == "complete"
        assert _item(payload, "hpc_link")["required_level"] == "Optional"
