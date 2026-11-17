"""A ZIP scene uploaded as a single source stays intact for the component."""

import io
import zipfile
from pathlib import Path

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import File, Session, User
from middleware import setup_error_handlers
from routes.single_file_routes import single_file_bp
from services.project_service import ProjectService
from session_manager import SessionManager


def test_direct_zip_upload_does_not_extract_or_rewrite_scene(tmp_path, monkeypatch):
    monkeypatch.setenv("SHARED_SESSION_PATH", str(tmp_path / "sessions"))
    monkeypatch.setenv("STORAGE_MODE", "server_only")
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="test-secret", JWT_SECRET_KEY="scene-zip-test-secret-long-enough",
                      SQLALCHEMY_DATABASE_URI="sqlite:///:memory:", SQLALCHEMY_TRACK_MODIFICATIONS=False,
                      MAX_CONTENT_LENGTH=1024 * 1024, ALLOWED_EXTENSIONS={".obj", ".glb"})
    db.init_app(app)
    JWTManager(app)
    setup_error_handlers(app)
    app.register_blueprint(single_file_bp, url_prefix="/api/v1/sessions")
    app.session_manager = SessionManager()
    app.project_service = ProjectService()

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("../escape.txt", "Components validate archive contents separately.")
        archive.writestr("images/scene.txt", "Source input")
    source_bytes = payload.getvalue()
    with app.app_context():
        db.create_all()
        user = User(email="zip-test@example.org", password_hash="unused-in-test", is_verified=True)
        db.session.add(user)
        db.session.commit()
        auth = {"Authorization": f"Bearer {create_access_token(identity=str(user.id))}"}
        response = app.test_client().post("/api/v1/sessions/file", headers=auth,
                                          data={"file": (io.BytesIO(source_bytes), "scene.zip")})
        assert response.status_code == 200, response.json
        result = response.json["data"]
        source = db.session.get(File, result["file_id"])
        assert Path(source.path).read_bytes() == source_bytes
        assert db.session.get(Session, result["session_id"]).status == "scanned"
        assert [item["name"] for item in result["foundFiles"]] == ["scene.zip"]
        assert not list(tmp_path.rglob("escape.txt"))
        assert not list(tmp_path.rglob("scene.txt"))
