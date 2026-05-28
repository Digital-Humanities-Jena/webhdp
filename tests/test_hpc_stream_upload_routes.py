from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import User, UserRole
from routes.upload_routes import upload_bp


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


def _make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "stream-upload-test"
    app.config["JWT_SECRET_KEY"] = "stream-upload-jwt"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.hpc_allocation_service = _FakeHpcAllocationService()
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(upload_bp, url_prefix="/api/v1/upload")
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

        db.session.remove()
        db.drop_all()
