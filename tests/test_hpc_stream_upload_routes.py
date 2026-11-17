import io
from types import SimpleNamespace

from api_utils import APIResponse
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import User, UserRole
from exceptions import AppException
from routes.hpc_link_routes import hpc_link_bp
from routes.session_routes import session_bp
from routes.upload_routes import upload_bp
from services.cloud_upload_service import CloudUploadService, issue_stream_receipt, read_stream_receipt


class _FakeHpcAllocationService:
    def __init__(self):
        self.captured = {}

    def get_allocation(self, allocation_id, user):
        self.captured["allocation_id"] = allocation_id
        self.captured["user_id"] = user.id
        return type("Allocation", (), {"remote_session_id": "remote-1"})()

    def stage_cloud_references(self, allocation, files):
        self.captured["allocation"] = allocation
        self.captured["files"] = files
        return {"staged_files": [{"name": files[0]["name"], "remote_path": "/remote/uploads/model.zip"}]}

    def serialize_allocation(self, allocation):
        return {'allocation_id': self.captured['allocation_id']}


def _make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "stream-upload-test"
    app.config["JWT_SECRET_KEY"] = "stream-upload-jwt"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.hpc_allocation_service = _FakeHpcAllocationService()
    app.project_service = SimpleNamespace()
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(upload_bp, url_prefix="/api/v1/upload")
    app.register_blueprint(hpc_link_bp, url_prefix='/api/v1/hpc-link')
    app.register_blueprint(session_bp, url_prefix='/api/v1/sessions')
    app.register_error_handler(AppException, lambda exc: APIResponse.error(exc.error_code, exc.message, exc.status_code))
    return app


def test_stream_upload_stages_uploaded_cloud_object_on_hpc(monkeypatch):
    app = _make_app()
    with app.app_context():
        db.create_all()
        user = User(email="hpc-stream@example.com", role=UserRole.USER, is_verified=True)
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))

        monkeypatch.setattr(
            "routes.upload_routes.CloudUploadService.stream_upload_file",
            lambda stream, filename, file_size: {
                "success": True,
                "storage_type": "dropbox",
                "remote_path": "/hdp_uploads/model.zip",
                "file_id": "id:abc",
                "message": "ok",
            },
        )

        response = app.test_client().post(
            "/api/v1/upload/stream",
            data=b"zip-bytes",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
                "X-File-Name": "model.zip",
                "X-HPC-Allocation-ID": "alloc-1",
                "X-HPC-Relative-Dir": "uploads",
            },
        )

        payload = response.get_json()
        assert response.status_code == 200
        assert payload["data"]["hpc_staging"]["staged_files"][0]["name"] == "model.zip"
        assert app.hpc_allocation_service.captured["allocation_id"] == "alloc-1"
        assert app.hpc_allocation_service.captured["files"][0]["cloud_path"] == "/hdp_uploads/model.zip"
        assert app.hpc_allocation_service.captured["files"][0]["storage_type"] == "dropbox"
        assert read_stream_receipt(payload['data']['cloud_upload_receipt'], user.id)['path'] == '/hdp_uploads/model.zip'

        db.session.remove()
        db.drop_all()


def test_untrusted_cloud_paths_never_pass_to_provider_credentials(monkeypatch, tmp_path):
    app = _make_app()
    with app.app_context():
        db.create_all()
        owner = User(email='owner@example.com', is_verified=True, password_hash='not-used')
        other = User(email='other@example.com', is_verified=True, password_hash='not-used')
        db.session.add_all([owner, other])
        db.session.commit()
        receipt = issue_stream_receipt(owner.id, 'models.zip', {'storage_type': 'dropbox', 'remote_path': '/hdp_uploads/own.zip'})
        owner_headers = {'Authorization': f'Bearer {create_access_token(identity=str(owner.id))}'}
        other_headers = {'Authorization': f'Bearer {create_access_token(identity=str(other.id))}'}
        provider_calls = []
        monkeypatch.setattr(CloudUploadService, 'get_storage_mode', lambda: 'pure_cloud')
        monkeypatch.setattr(CloudUploadService, 'get_available_storage', lambda: ('dropbox', 'configured'))
        monkeypatch.setattr(CloudUploadService, 'get_file_download_url', lambda path, provider: provider_calls.append((path, provider)))
        monkeypatch.setenv('SHARED_SESSION_PATH', str(tmp_path))
        client = app.test_client()
        batch_url = '/api/v1/sessions/directory'
        staging_url = '/api/v1/hpc-link/allocations/owner-allocation/stage/cloud-references'
        raw = {'cloud_path': 'https://127.0.0.1/metadata', 'storage_type': 'dropbox'}
        for payload, headers in ((raw, owner_headers), ({**raw, 'cloud_upload_receipt': receipt}, other_headers),
                                 ({**raw, 'cloud_upload_receipt': 'invalid-' + receipt}, owner_headers)):
            assert client.post(batch_url, data=payload, headers=headers).status_code == 403
            assert client.post(staging_url, json={'files': [payload]}, headers=headers).status_code == 403
        assert provider_calls == []
        assert 'files' not in app.hpc_allocation_service.captured
        valid = {**raw, 'cloud_upload_receipt': receipt}
        assert client.post(staging_url, json={'files': [valid]}, headers=owner_headers).status_code == 200
        assert app.hpc_allocation_service.captured['files'][0]['cloud_path'] == '/hdp_uploads/own.zip'
        # The batch workflow reaches the provider only with the signed object.
        client.post(batch_url, data={**valid, 'msf_file': (io.BytesIO(b'name\nexample'), 'manifest.csv')}, headers=owner_headers)
        assert provider_calls == [('/hdp_uploads/own.zip', 'dropbox')]
