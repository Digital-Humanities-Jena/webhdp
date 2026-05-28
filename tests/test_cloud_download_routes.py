import os
import shutil
import tempfile

import pytest

pytest.importorskip("flask_jwt_extended")
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import AuditEvent, CloudMirrorObject, Session as DBSession, User, UserMetadata, UserRole
from middleware import setup_error_handlers
from routes.session_routes import session_bp
from constants import UPLOAD_STORAGE_MODE_FIELD


@pytest.fixture()
def cloud_download_app():
    temp_dir = tempfile.mkdtemp(prefix="cloud-download-routes-")
    hdpc_path = os.path.join(temp_dir, "session.hdpc")
    with open(hdpc_path, "w", encoding="utf-8") as handle:
        handle.write("hdpc")

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = "cloud-download-secret"

    db.init_app(app)
    JWTManager(app)
    setup_error_handlers(app)
    app.register_blueprint(session_bp, url_prefix="/api/v1/sessions")

    with app.app_context():
        db.create_all()

        owner = User(email="owner-cloud@example.com", role=UserRole.USER, is_verified=True)
        owner.set_password("password123")
        outsider = User(email="outsider-cloud@example.com", role=UserRole.USER, is_verified=True)
        outsider.set_password("password123")
        db.session.add_all([owner, outsider])
        db.session.flush()

        mirrored_session = DBSession(
            user_id=owner.id,
            session_dir=temp_dir,
            hdpc_path=hdpc_path,
            status="scanned",
        )
        local_session = DBSession(
            user_id=owner.id,
            session_dir=os.path.join(temp_dir, "local"),
            hdpc_path=hdpc_path,
            status="scanned",
        )
        db.session.add_all([mirrored_session, local_session])
        db.session.flush()

        mirror = CloudMirrorObject(
            session_id=mirrored_session.id,
            artifact_kind="batch_zip",
            original_filename="dataset.zip",
            storage_provider="dropbox",
            cloud_path="/hdp_uploads/dataset.zip",
            status="available",
        )
        failed_mirror = CloudMirrorObject(
            session_id=mirrored_session.id,
            artifact_kind="msf",
            original_filename="metadata.xlsx",
            status="failed",
            error="Cloud storage was unavailable.",
        )
        db.session.add_all(
            [
                mirror,
                failed_mirror,
                UserMetadata(
                    session_id=mirrored_session.id,
                    field_name=UPLOAD_STORAGE_MODE_FIELD,
                    field_value="cloud_backup",
                ),
                UserMetadata(
                    session_id=local_session.id,
                    field_name=UPLOAD_STORAGE_MODE_FIELD,
                    field_value="local",
                ),
            ]
        )
        db.session.commit()

        payload = {
            "app": app,
            "client": app.test_client(),
            "owner_headers": {"Authorization": f"Bearer {create_access_token(identity=str(owner.id))}"},
            "outsider_headers": {"Authorization": f"Bearer {create_access_token(identity=str(outsider.id))}"},
            "mirrored_session_id": mirrored_session.id,
            "local_session_id": local_session.id,
            "mirror_id": mirror.id,
        }
        yield payload

        db.session.remove()
        db.drop_all()
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_cloud_downloads_report_availability_and_failures(cloud_download_app, monkeypatch):
    monkeypatch.setattr(
        "services.cloud_mirror_service.CloudUploadService.check_cloud_object_available",
        lambda cloud_path, storage_type: (True, "Dropbox mirror is available"),
    )

    response = cloud_download_app["client"].get(
        f"/api/v1/sessions/{cloud_download_app['mirrored_session_id']}/cloud-downloads",
        headers=cloud_download_app["owner_headers"],
    )

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["available"] is True
    assert [item["original_filename"] for item in payload["items"]] == ["dataset.zip", "metadata.xlsx"]
    assert payload["items"][0]["can_download"] is True
    assert payload["items"][1]["can_download"] is False
    assert payload["items"][1]["availability_message"] == "Cloud storage was unavailable."


def test_mirror_local_artifact_persists_cloud_reference(cloud_download_app, monkeypatch):
    from services.cloud_mirror_service import ARTIFACT_SINGLE_FILE, mirror_local_artifact

    source_path = os.path.join(tempfile.mkdtemp(prefix="cloud-mirror-source-"), "model.glb")
    with open(source_path, "wb") as handle:
        handle.write(b"model")

    monkeypatch.setattr(
        "services.cloud_mirror_service.CloudUploadService.upload_file",
        lambda local_path, remote_name: {
            "success": True,
            "storage_type": "dropbox",
            "remote_path": "/hdp_uploads/model.glb",
            "remote_url": "https://dropbox.invalid/model",
            "file_id": "id:dbx",
        },
    )

    with cloud_download_app["app"].app_context():
        row = mirror_local_artifact(
            session_id=cloud_download_app["mirrored_session_id"],
            local_path=source_path,
            original_filename="model.glb",
            artifact_kind=ARTIFACT_SINGLE_FILE,
            storage_mode="cloud_backup",
        )
        db.session.commit()
        persisted = db.session.get(CloudMirrorObject, row.id)
        assert persisted.status == "available"
        assert persisted.storage_provider == "dropbox"
        assert persisted.cloud_path == "/hdp_uploads/model.glb"


def test_cloud_downloads_report_local_mode_unavailable(cloud_download_app):
    response = cloud_download_app["client"].get(
        f"/api/v1/sessions/{cloud_download_app['local_session_id']}/cloud-downloads",
        headers=cloud_download_app["owner_headers"],
    )

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["available"] is False
    assert payload["items"] == []
    assert "HPC/local storage mode" in payload["reason"]


def test_cloud_download_redirect_is_owner_only_and_audited(cloud_download_app, monkeypatch):
    monkeypatch.setattr(
        "services.cloud_upload_service.CloudUploadService.check_cloud_object_available",
        lambda cloud_path, storage_type: (True, "available"),
    )
    monkeypatch.setattr(
        "services.cloud_upload_service.CloudUploadService.get_file_download_url",
        lambda cloud_path, storage_type: "https://example.invalid/download/dataset.zip",
    )

    outsider_response = cloud_download_app["client"].get(
        f"/api/v1/sessions/{cloud_download_app['mirrored_session_id']}/cloud-downloads/{cloud_download_app['mirror_id']}?as_json=true",
        headers=cloud_download_app["outsider_headers"],
    )
    assert outsider_response.status_code == 404

    owner_response = cloud_download_app["client"].get(
        f"/api/v1/sessions/{cloud_download_app['mirrored_session_id']}/cloud-downloads/{cloud_download_app['mirror_id']}?as_json=true",
        headers=cloud_download_app["owner_headers"],
    )
    assert owner_response.status_code == 200
    assert owner_response.get_json()["data"]["download_url"] == "https://example.invalid/download/dataset.zip"

    with cloud_download_app["app"].app_context():
        event = AuditEvent.query.filter_by(event_type="cloud_mirror_downloaded").first()
        assert event is not None
        assert event.entity_id == str(cloud_download_app["mirror_id"])
