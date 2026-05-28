from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import User, UserRole
from services.cloud_upload_service import CloudUploadService, STORAGE_MODE_LOCAL, STORAGE_MODE_PURE_CLOUD


def _make_app(*, deployment_mode: str, allow_local: bool):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "test-secret"
    app.config["JWT_SECRET_KEY"] = "storage-runtime-secret"
    app.config["STORAGE_MODE"] = STORAGE_MODE_LOCAL
    app.config["WEBHDP_DEPLOYMENT_MODE"] = deployment_mode
    app.config["WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS"] = allow_local
    db.init_app(app)
    JWTManager(app)
    return app


def _user_headers(app):
    with app.app_context():
        db.create_all()
        user = User(email="user@example.com", role=UserRole.USER, is_verified=True)
        user.set_password("password")
        db.session.add(user)
        db.session.commit()
        return {"Authorization": f"Bearer {create_access_token(identity=str(user.id))}"}


def _cleanup(app):
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_server_deployment_forces_non_admin_local_storage_to_cloud():
    app = _make_app(deployment_mode="server", allow_local=False)
    headers = _user_headers(app)
    try:
        with app.test_request_context(headers=headers):
            assert CloudUploadService.get_storage_mode() == STORAGE_MODE_PURE_CLOUD
    finally:
        _cleanup(app)


def test_workstation_local_allows_non_admin_configured_local_storage():
    app = _make_app(deployment_mode="local", allow_local=True)
    headers = _user_headers(app)
    try:
        with app.test_request_context(headers=headers):
            assert CloudUploadService.get_storage_mode() == STORAGE_MODE_LOCAL
    finally:
        _cleanup(app)
