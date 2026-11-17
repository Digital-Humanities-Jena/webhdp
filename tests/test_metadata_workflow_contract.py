from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from routes.metadata_routes import metadata_bp
from routes.tools_routes import tools_bp
from services.cloud_upload_service import CloudUploadService, STORAGE_MODE_LOCAL
from services.metadata_service import MetadataService
from services.project_service import ProjectService
from services.msf_service import MSFService
from services.user_service import UserService
from database.database import db
from database.models import Session, UserRole


class _DummyProjectService:
    def _translate_path(self, path, to_container=True):
        return path


class _DummyHpcConfig:
    enabled = True
    base_url = "http://hpc-link.example"


class _DummyHpcAllocationService:
    def get_or_create_config(self):
        return _DummyHpcConfig()

    def user_can_allocate(self, user, purpose="workflow"):
        return True

    def get_active_for_session(self, session_id, *, user_id):
        return object() if session_id == 42 and user_id == 1 else None


def _make_app(tmp_path):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
    app.config["LOCAL_INPUT_PATH"] = str(tmp_path)
    JWTManager(app)
    app.project_service = _DummyProjectService()
    app.msf_service = MSFService()
    app.register_blueprint(metadata_bp, url_prefix="/api/v1/metadata")
    app.register_blueprint(tools_bp, url_prefix="/api/v1/tools")
    return app


def _auth_headers(app):
    with app.app_context():
        token = create_access_token(identity="1")
    return {"Authorization": f"Bearer {token}"}


def test_metadata_workflow_support_endpoint_exposes_official_contract(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()

    response = client.get("/api/v1/metadata/workflow-support", headers=_auth_headers(app))

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["official_workflow_id"] == "webhdp_native_msf"
    assert payload["data"]["decision"]["retire_legacy_prepare_metadata"] is True
    assert payload["data"]["supported_surfaces"]["output_preview_qa"] == "/api/v1/tools/output-preview/local"
    assert payload["data"]["retired_surfaces"][0]["id"] == "legacy_prepare_metadata_for_file"


def test_tools_context_includes_metadata_workflow_contract(tmp_path, monkeypatch):
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
    assert payload["data"]["metadata_workflow"]["official_workflow_id"] == "webhdp_native_msf"
    assert payload["data"]["metadata_workflow"]["decision"]["port_old_mapping_workflow"] is False


def test_tools_context_passes_hpc_runtime_state_into_component_report(tmp_path, monkeypatch):
    app = _make_app(tmp_path)
    app.hpc_allocation_service = _DummyHpcAllocationService()

    class _DummyUser:
        id = 1
        role = UserRole.ADMIN
        capabilities = []

    monkeypatch.setattr(db.session, "get", lambda model, key: Session(id=key, user_id=1))
    monkeypatch.setattr(UserService, "get_by_id", lambda self, _user_id: _DummyUser())
    monkeypatch.setattr(CloudUploadService, "get_storage_mode", lambda: STORAGE_MODE_LOCAL)

    client = app.test_client()
    response = client.get("/api/v1/tools/context?session_id=42", headers=_auth_headers(app))

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["hpc_link_available"] is True
    assert payload["data"]["can_allocate_hpc"] is True
    assert payload["data"]["active_hpc_allocation"] is True
    runtime = payload["data"]["component_runtime"]["fast_renderer"]
    assert runtime["hpc_link_available"] is True
    assert runtime["can_allocate_hpc"] is True
    assert runtime["active_hpc_allocation"] is True
    assert runtime["allocation_required"] is False


def test_legacy_prepare_metadata_methods_raise_clear_error():
    project_service = ProjectService("http://example.invalid", api_client=None)
    metadata_service = MetadataService()

    try:
        project_service.prepare_metadata_for_file("101")
        assert False, "Expected prepare_metadata_for_file to be retired"
    except NotImplementedError as exc:
        assert "retired" in str(exc).lower()

    try:
        metadata_service.prepare_metadata("101")
        assert False, "Expected prepare_metadata to be retired"
    except NotImplementedError as exc:
        assert "retired" in str(exc).lower()
