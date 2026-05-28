import os
import shutil
import tempfile

import pytest

pytest.importorskip("flask_jwt_extended")
pytest.importorskip("flask_sqlalchemy")
pytest.importorskip("pydantic")
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import File, Session as DBSession, User, UserRole
from middleware import setup_error_handlers
from routes.metadata_routes import metadata_bp
from routes.msf_routes import msf_bp
from routes.pipeline_routes import pipeline_bp
from routes.pipeline_v2_routes import pipeline_v2_bp
from routes.session_routes import session_bp


@pytest.fixture()
def explorer_only_app():
    temp_dir = tempfile.mkdtemp(prefix="explorer-only-routes-")
    hdpc_path = os.path.join(temp_dir, "session.hdpc")
    with open(hdpc_path, "w", encoding="utf-8") as handle:
        handle.write("placeholder")

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "explorer-only-secret"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = "explorer-only-jwt"
    setup_error_handlers(app)

    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(session_bp, url_prefix="/api/v1/sessions")
    app.register_blueprint(metadata_bp, url_prefix="/api/v1/metadata")
    app.register_blueprint(msf_bp, url_prefix="/api/v1/msf")
    app.register_blueprint(pipeline_bp, url_prefix="/api/v1/pipelines")
    app.register_blueprint(pipeline_v2_bp, url_prefix="/api/v2")

    with app.app_context():
        db.create_all()

        user = User(email="reader@example.com", role=UserRole.USER, is_verified=True)
        user.set_password("password123")
        db.session.add(user)
        db.session.flush()

        session_row = DBSession(
            user_id=user.id,
            session_dir=temp_dir,
            hdpc_path=hdpc_path,
            status="completed",
            sharing_scope="private",
            credential_preference="user",
            publishing_user_id=user.id,
            default_zenodo_environment="sandbox",
            use_institution_default_communities=False,
            origin_type="hdpc_import",
            access_mode="explorer_only",
        )
        db.session.add(session_row)
        db.session.flush()

        file_row = File(
            session_id=session_row.id,
            filename="sample.obj",
            path=os.path.join(temp_dir, "sample.obj"),
            status="uploaded",
        )
        db.session.add(file_row)
        db.session.commit()

        token = create_access_token(identity=str(user.id))

        yield {
            "app": app,
            "client": app.test_client(),
            "session_id": session_row.id,
            "file_id": file_row.id,
            "headers": {"Authorization": f"Bearer {token}"},
            "temp_dir": temp_dir,
        }

        db.session.remove()
        db.drop_all()
    shutil.rmtree(temp_dir, ignore_errors=True)


def _assert_read_only(response):
    assert response.status_code == 409
    payload = response.get_json()
    assert payload["error"]["code"] == "SESSION_READ_ONLY"


def test_explorer_only_sessions_allow_views_but_block_mutations(explorer_only_app):
    client = explorer_only_app["client"]
    headers = explorer_only_app["headers"]
    session_id = explorer_only_app["session_id"]
    file_id = explorer_only_app["file_id"]
    temp_dir = explorer_only_app["temp_dir"]

    view_response = client.get(f"/api/v1/sessions/{session_id}", headers=headers)
    assert view_response.status_code == 200
    assert view_response.get_json()["data"]["session"]["access_mode"] == "explorer_only"

    workflow_state = client.get(f"/api/v1/sessions/{session_id}/workflow-state", headers=headers)
    assert workflow_state.status_code == 200

    _assert_read_only(
        client.put(
            f"/api/v1/sessions/{session_id}/workflow-state",
            headers=headers,
            json={"phase": "metadata"},
        )
    )
    _assert_read_only(
        client.put(
            f"/api/v1/metadata/user/{session_id}",
            headers=headers,
            json={
                "upload_type": "dataset",
                "publication_date": "2026-03-30",
                "title": "Read Only",
                "creators": [{"name": "Example"}],
                "description": "Read only import",
                "access_right": "open",
                "license": "cc-by-4.0",
            },
        )
    )
    _assert_read_only(
        client.put(
            f"/api/v1/metadata/user/{session_id}/draft",
            headers=headers,
            json={"title": "Draft"},
        )
    )
    _assert_read_only(
        client.put(
            f"/api/v1/metadata/file/{file_id}",
            headers=headers,
            json={"metadata": {"field": "value"}},
        )
    )
    _assert_read_only(
        client.post(
            f"/api/v1/metadata/session/{session_id}/batch-update",
            headers=headers,
            json={"title": "Batch"},
        )
    )
    _assert_read_only(
        client.post(
            f"/api/v1/sessions/{session_id}/versioning/match-files",
            headers=headers,
            json={"directory_path": temp_dir, "match_method": "filename"},
        )
    )
    _assert_read_only(
        client.post(
            f"/api/v1/sessions/{session_id}/batch-operations",
            headers=headers,
            json={"operation_type": "create_drafts"},
        )
    )
    _assert_read_only(
        client.post(
            f"/api/v1/sessions/{session_id}/records/1/discard-draft",
            headers=headers,
        )
    )
    _assert_read_only(
        client.post(
            f"/api/v1/sessions/{session_id}/records/1/create-version",
            headers=headers,
            json={"publish": False},
        )
    )
    _assert_read_only(
        client.post(
            f"/api/v1/sessions/{session_id}/resume",
            headers=headers,
        )
    )
    _assert_read_only(
        client.post(
            "/api/v1/pipelines/test/execute_on_local_files",
            headers=headers,
            json={"session_id": session_id, "local_file_paths": ["/tmp/example.obj"]},
        )
    )
    _assert_read_only(
        client.post(
            "/api/v2/pipelines/test/execute",
            headers=headers,
            json={"session_id": session_id, "local_file_paths": ["/tmp/example.obj"], "record_ids": []},
        )
    )
    _assert_read_only(
        client.post(
            f"/api/v1/msf/workflow/session/{session_id}/analyze",
            headers=headers,
            json={},
        )
    )
