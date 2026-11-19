from io import BytesIO
import os
from types import SimpleNamespace

from flask import Flask

from middleware import setup_error_handlers


def test_account_controls_work_when_an_upload_mount_is_unavailable(monkeypatch, tmp_path):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        MAX_CONTENT_LENGTH=1024 * 1024,
        MIN_UPLOAD_FREE_BYTES=100,
        LOCAL_INPUT_PATH=str(tmp_path / "inaccessible"),
    )
    monkeypatch.delenv("SHARED_SESSION_PATH", raising=False)
    setup_error_handlers(app)

    @app.post("/api/v1/auth/login")
    def login():
        return {"ok": True}

    @app.post("/api/v1/sessions/directory")
    def directory():
        return {"ok": True}

    real_makedirs = os.makedirs

    def check_mount(path, **kwargs):
        if path == app.config["LOCAL_INPUT_PATH"]:
            raise PermissionError()
        return real_makedirs(path, **kwargs)

    monkeypatch.setattr("middleware.os.makedirs", check_mount)
    client = app.test_client()

    assert client.post("/api/v1/auth/login", json={"email": "account@example.test"}).status_code == 200
    response = client.post("/api/v1/sessions/directory", json={"cloud_upload_receipt": "test-receipt"})
    assert response.status_code == 507
    assert response.json["error"]["code"] == "UPLOAD_STORAGE_UNAVAILABLE"


def test_multipart_upload_is_guarded_without_returning_the_storage_path(monkeypatch, tmp_path):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        MAX_CONTENT_LENGTH=1024 * 1024,
        MIN_UPLOAD_FREE_BYTES=100,
        LOCAL_INPUT_PATH=str(tmp_path),
    )
    monkeypatch.delenv("SHARED_SESSION_PATH", raising=False)
    setup_error_handlers(app)

    @app.post("/api/v1/sessions/file")
    def upload():
        return {"ok": True}

    monkeypatch.setattr("middleware.shutil.disk_usage", lambda _path: SimpleNamespace(free=99))
    with app.test_client() as client:
        response = client.post("/api/v1/sessions/file", data={"file": (BytesIO(b"sample"), "model.glb")})
    assert response.status_code == 507
    assert response.json["error"]["code"] == "INSUFFICIENT_STORAGE"
    assert "path" not in response.json["error"]["details"]
