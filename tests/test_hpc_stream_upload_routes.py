import io
from pathlib import Path
import sys
from types import SimpleNamespace
import zipfile

from api_utils import APIResponse
from flask import Flask, session as flask_session
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from constants import CLOUD_BATCH_INPUT_DIR
from database.models import AccountUploadReservation, Session, User, UserRole
from exceptions import AppException, SecurityError
from routes.hpc_link_routes import hpc_link_bp
from routes.session_routes import session_bp
from routes.upload_routes import upload_bp
from services.account_upload_quota import attach_upload_to_session
from services.cloud_upload_service import CloudUploadService, issue_stream_receipt, read_stream_receipt


class _FakeHpcAllocationService:
    def __init__(self):
        self.captured = {}

    def get_allocation(self, allocation_id, user):
        self.captured["allocation_id"] = allocation_id
        self.captured["user_id"] = user.id
        return type("Allocation", (), {"remote_session_id": "remote-1"})()

    def get_allocation_for_compute(self, allocation_id, user):
        return self.get_allocation(allocation_id, user)

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
        assert payload["data"]["hpc_staging"]["staged_files"] == [{"name": "model.zip"}]
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


def test_cloud_batch_reserves_expanded_source_before_staging_it(monkeypatch, tmp_path):
    app = _make_app()
    app.config["ACCOUNT_UPLOAD_STORAGE_BYTES"] = 750
    archive = io.BytesIO()
    model = b"a" * 4000
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("model/asset.glb", model)
    compressed = archive.getvalue()
    manifest = b"filename,title\nasset.glb,Test Model\n"
    assert len(compressed) + len(manifest) < 750
    monkeypatch.setenv("SHARED_SESSION_PATH", str(tmp_path))
    monkeypatch.setattr(CloudUploadService, "get_storage_mode", lambda: "pure_cloud")
    monkeypatch.setattr(CloudUploadService, "get_available_storage", lambda: ("dropbox", "configured"))
    monkeypatch.setattr(CloudUploadService, "get_file_download_url", lambda *_: "https://object.example.test/asset.zip")
    monkeypatch.setattr("utils.remote_storage.RemoteStorageFile", lambda *_: io.BytesIO(compressed))
    monkeypatch.setattr("services.cloud_mirror_service.mirror_local_artifact", lambda **_: None)
    dispatched = []
    extraction_observed = []

    from security import safe_extract_zip

    def extract(archive, destination):
        extraction_observed.append(AccountUploadReservation.query.one().size_bytes)
        return safe_extract_zip(archive, destination)

    def create_workspace(**kwargs):
        workspace = tmp_path / "session"
        uploads = workspace / "uploads"
        uploads.mkdir(parents=True)
        row = Session(user_id=user.id, session_dir=str(workspace), hdpc_path=str(workspace / "session.hdpc"), **kwargs)
        db.session.add(row)
        attach_upload_to_session(row)
        db.session.commit()
        flask_session["db_session_id"] = row.id
        return row.hdpc_path, str(workspace / "outputs"), str(uploads)

    def dispatch(*, kwargs, task_id):
        assert kwargs["zip_path"] is None and kwargs["input_directory_path"] is None
        dispatched.append(kwargs)
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr("routes.session_routes.safe_extract_zip", extract)
    monkeypatch.setitem(sys.modules, "app", SimpleNamespace(_create_session_dirs=create_workspace))
    monkeypatch.setitem(sys.modules, "tasks", SimpleNamespace(start_upload_coordinator=SimpleNamespace(apply_async=dispatch)))
    with app.app_context():
        db.create_all()
        user = User(email="cloud-source@example.test", is_verified=True, password_hash="test-only")
        db.session.add(user)
        db.session.commit()
        receipt = issue_stream_receipt(user.id, "bundle.zip", {"storage_type": "dropbox", "remote_path": "/hdp_uploads/bundle.zip"},
                                       size_bytes=len(compressed))
        headers = {"Authorization": f"Bearer {create_access_token(identity=str(user.id))}"}
        client = app.test_client()

        def submit():
            return client.post("/api/v1/sessions/directory", data={"cloud_upload_receipt": receipt, "msf_auto_patch": "false",
                "msf_file": (io.BytesIO(manifest), "manifest.csv")}, headers=headers)

        rejected = submit()
        assert rejected.status_code == 413 and rejected.json["error"]["code"] == "UPLOAD_STORAGE_QUOTA"
        assert not dispatched and not extraction_observed and not list(tmp_path.glob("hdp_zip_*"))
        assert AccountUploadReservation.query.count() == 0 and Session.query.count() == 0

        app.config["ACCOUNT_UPLOAD_STORAGE_BYTES"] = 4100
        accepted = submit()
        assert accepted.status_code == 202, accepted.json
        assert extraction_observed == [len(model) + len(manifest)]
        reservation = AccountUploadReservation.query.one()
        assert reservation.session_id == accepted.json["data"]["session_id"] and reservation.size_bytes == extraction_observed[0]
        saved_msf = Path(dispatched[0]["msf_path"])
        assert saved_msf.read_bytes() == manifest
        assert (saved_msf.parent / CLOUD_BATCH_INPUT_DIR / "model" / "asset.glb").read_bytes() == model
        assert not list(tmp_path.glob("hdp_zip_*"))


def test_stream_upload_checks_compute_scope_before_writing_to_cloud(monkeypatch):
    app = _make_app()
    with app.app_context():
        db.create_all()
        user = User(email="restricted@example.test", role=UserRole.USER, is_verified=True)
        user.set_password("test-password")
        db.session.add(user)
        db.session.commit()
        token = create_access_token(identity=str(user.id))

        def deny_compute(allocation_id, actor):
            assert allocation_id == "older-allocation" and actor.id == user.id
            raise SecurityError("HPC compute access is required.")

        monkeypatch.setattr(app.hpc_allocation_service, "get_allocation_for_compute", deny_compute)
        provider_calls = []
        monkeypatch.setattr(CloudUploadService, "stream_upload_file", lambda *args: provider_calls.append(args))
        response = app.test_client().post(
            "/api/v1/upload/stream", data=b"source",
            headers={"Authorization": f"Bearer {token}", "X-File-Name": "model.zip",
                     "X-HPC-Allocation-ID": "older-allocation"},
        )
        assert response.status_code == 403
        assert provider_calls == []
