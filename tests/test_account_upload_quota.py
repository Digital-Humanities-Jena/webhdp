"""Verify that upload reservations remain private and cannot overbook an account."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from io import BytesIO
from threading import Event
from types import SimpleNamespace
import zipfile

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from werkzeug.datastructures import FileStorage

from api_utils import APIResponse
from database.database import db
from database.models import AccountUploadReservation, File, Session, User, UserRole
from exceptions import AppException
from routes.account_usage_routes import account_usage_bp
from routes.msf_routes import msf_bp
from services.account_upload_quota import UploadQuotaError, admit_upload, attach_upload_to_session, batch_input_size, finish_stream_upload, upload_usage
from services.cloud_upload_service import CloudUploadService, STORAGE_MODE_SERVER_ONLY


@pytest.fixture
def accounts(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, JWT_SECRET_KEY="test-jwt-key" * 4, SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path}/users.db",
                      ACCOUNT_UPLOAD_STORAGE_BYTES=30, ACCOUNT_UPLOAD_MAX_ACTIVE=1, ACCOUNT_UPLOAD_STREAM_DAILY_BYTES=20,
                      MAX_CONTENT_LENGTH=1000, MODEL_PUBLICATION_ROOT=tmp_path / "queue", UPLOAD_FOLDER=str(tmp_path / "msf"))
    db.init_app(app)
    JWTManager(app)
    app.project_service = SimpleNamespace(_translate_path=lambda path, **_: path)
    app.register_blueprint(account_usage_bp, url_prefix="/api/v1/account")
    app.register_blueprint(msf_bp, url_prefix="/api/v1/msf")
    app.register_error_handler(AppException, lambda exc: APIResponse.error(exc.error_code, exc.message, exc.status_code, details=exc.details))
    monkeypatch.setattr(CloudUploadService, "get_storage_mode", lambda: STORAGE_MODE_SERVER_ONLY)
    with app.app_context():
        db.create_all()
        users = [User(email=email, password_hash="test-only", role=UserRole.USER, is_verified=True) for email in
                 ("first@example.test", "second@example.test", "model-demo-12345678@webhdp.invalid")]
        db.session.add_all(users)
        db.session.commit()
        identities = [user.id for user in users]
        tokens = [{"Authorization": f"Bearer {create_access_token(identity=str(user.id))}"} for user in users]
    return app, identities, tokens


def put_session(user_id, size, *, tracked=False, status="scanned"):
    session = Session(user_id=user_id, session_dir="/private/session", status=status)
    db.session.add(session)
    db.session.flush()
    if tracked:
        attach_upload_to_session(session)
    if size:
        db.session.add(File(session_id=session.id, filename="model.glb", path="/private/model.glb", size=size))
    db.session.commit()


def test_usage_counts_legacy_sources_and_reservations_once_and_stays_private(accounts):
    app, (first, second, _), (owner, foreign, demo) = accounts
    with app.test_request_context():
        put_session(first, 7)
        with admit_upload(first, 12):
            put_session(first, 8, tracked=True)
        put_session(second, 3)
        with pytest.raises(UploadQuotaError) as quota:
            with admit_upload(first, 12):
                pytest.fail("overbooked account storage")
        assert (quota.value.status_code, quota.value.error_code) == (413, "UPLOAD_STORAGE_QUOTA")
    client = app.test_client()
    response = client.get("/api/v1/account/usage?user_id=999", headers=owner)
    assert response.cache_control.private and response.cache_control.no_store
    assert response.json["data"]["uploads"] == {"used_bytes": 19, "limit_bytes": 30, "active": 0, "active_limit": 1,
                                                  "request_limit_bytes": 1000, "stream_limit_bytes": 20,
                                                  "stream_bytes_last_24_hours": 0}
    assert client.get("/api/v1/account/usage", headers=foreign).json["data"]["uploads"]["used_bytes"] == 3
    assert client.get("/api/v1/account/usage", headers=demo).status_code == 403


def test_admission_reserves_in_flight_capacity_until_request_finishes(accounts):
    app, (first, second, _), _ = accounts
    ready, release = Event(), Event()

    def receive():
        with app.test_request_context(), admit_upload(first, 7):
            ready.set()
            assert release.wait(3)

    with ThreadPoolExecutor() as pool:
        holding = pool.submit(receive)
        assert ready.wait(3)
        try:
            with app.test_request_context():
                with pytest.raises(UploadQuotaError) as quota:
                    with admit_upload(first, 1):
                        pytest.fail("overbooked account concurrency")
                assert (quota.value.status_code, quota.value.error_code) == (429, "UPLOAD_CONCURRENCY_QUOTA")
                with admit_upload(second, 1):
                    assert upload_usage(db.session.get(User, second))["active"] == 1
        finally:
            release.set()
        holding.result()
    with app.test_request_context():
        assert upload_usage(db.session.get(User, first))["active"] == 0
        with admit_upload(first, 1):
            put_session(first, 0, tracked=True, status="queued")
        assert upload_usage(db.session.get(User, first))["active"] == 1


def test_cloud_limit_counts_only_successfully_accepted_transfers_and_rolls_off(accounts):
    app, (first, _, _), _ = accounts
    with app.test_request_context():
        with admit_upload(first, 17, kind="stream") as identity:
            finish_stream_upload(identity)
        with admit_upload(first, 1, kind="stream"):
            pass
        usage = upload_usage(db.session.get(User, first))
        assert usage["stream_bytes_last_24_hours"] == 17 and usage["used_bytes"] == 0
        with pytest.raises(UploadQuotaError) as quota:
            with admit_upload(first, 4, kind="stream"):
                pytest.fail("overbooked cloud transfer window")
        assert quota.value.error_code == "UPLOAD_STREAM_QUOTA"
        db.session.get(AccountUploadReservation, identity).finished_at = datetime.utcnow() - timedelta(days=1, seconds=1)
        db.session.commit()
        with admit_upload(first, 4, kind="stream"):
            pass


def test_spreadsheet_workspace_is_private_and_bounded(accounts, monkeypatch):
    app, _, (owner, foreign, _) = accounts
    monkeypatch.setattr("routes.msf_routes.MSF_FILE_BYTES", 50)
    monkeypatch.setattr("routes.msf_routes.MSF_WORKSPACE_BYTES", 45)
    client = app.test_client()
    contents = b"filename,title\nasset.glb,Model\n"
    path_response = client.post("/api/v1/msf/upload", data={"file": (BytesIO(contents), "model.csv")}, headers=owner)
    assert path_response.status_code == 200
    path = path_response.json["data"]["msf_path"]
    for route, body in (("parse", {}), ("metadata-for-files", {"filenames": ["asset.glb"]})):
        assert client.post(f"/api/v1/msf/{route}", json={"msf_path": path, **body}, headers=owner).status_code == 200
        assert client.post(f"/api/v1/msf/{route}", json={"msf_path": path, **body}, headers=foreign).status_code == 400
    full = client.post("/api/v1/msf/upload", data={"file": (BytesIO(contents), "another.csv")}, headers=owner)
    assert full.status_code == 413
    assert full.json["error"]["code"] == "MSF_WORKSPACE_QUOTA"


def test_batch_weight_uses_expanded_sources_instead_of_only_compressed_size():
    compressed = BytesIO()
    with zipfile.ZipFile(compressed, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("asset.obj", "data" * 1000)
    spreadsheet = BytesIO(b"filename,title\n")
    archive = FileStorage(compressed, filename="asset.zip")
    assert batch_input_size(archive, FileStorage(spreadsheet, filename="asset.csv")) == 4000 + len(spreadsheet.getvalue())
    assert archive.tell() == 0 and spreadsheet.tell() == 0
