from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from routes.tools_routes import tools_bp
from services.cloud_upload_service import CloudUploadService, STORAGE_MODE_LOCAL
from services.msf_service import MSFService
from services.user_service import UserService
from database.models import UserRole


class _DummyProjectService:
    def _translate_path(self, path, to_container=True):
        return path


def _make_app(tmp_path):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
    app.config["LOCAL_INPUT_PATH"] = str(tmp_path)
    JWTManager(app)
    app.project_service = _DummyProjectService()
    app.msf_service = MSFService()
    app.register_blueprint(tools_bp, url_prefix="/api/v1/tools")
    return app


def _auth_headers(app):
    with app.app_context():
        token = create_access_token(identity="1")
    return {"Authorization": f"Bearer {token}"}


def test_tools_context_includes_pipeline_platform_contract(tmp_path, monkeypatch):
    app = _make_app(tmp_path)

    class _DummyUser:
        role = UserRole.ADMIN

    monkeypatch.setattr(UserService, "get_by_id", lambda self, _user_id: _DummyUser())
    monkeypatch.setattr(CloudUploadService, "get_storage_mode", lambda: STORAGE_MODE_LOCAL)

    client = app.test_client()
    response = client.get("/api/v1/tools/context", headers=_auth_headers(app))

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    contract = payload["data"]["pipeline_platform"]
    assert contract["official_platform_id"] == "webhdp_native_pipeline_platform"
    assert contract["decision"]["retain_native_component_registry"] is True
    assert contract["decision"]["retire_legacy_pipeline_manager_api"] is True
    assert contract["decision"]["retire_legacy_cli_http_route"] is True
    assert contract["supported_surfaces"]["playground_execute"] == "/api/v2/playground/execute"
    retired_ids = {item["id"] for item in contract["retired_surfaces"]}
    assert "legacy_pipeline_manager_api" in retired_ids
