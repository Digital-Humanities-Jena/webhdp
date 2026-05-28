import json
import os
import tempfile

import pytest
pytest.importorskip("flask_jwt_extended")
pytest.importorskip("flask_sqlalchemy")
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from constants import WORKFLOW_STATE_FIELD
from database.database import db
from database.models import (
    AuditEvent,
    File,
    Institution,
    InstitutionMembership,
    InstitutionRole,
    Session as DBSession,
    Submission,
    User,
    UserMetadata,
    UserRole,
)
from middleware import setup_error_handlers
from routes.metadata_routes import metadata_bp
from routes.session_routes import session_bp
from routes.submission_routes import submission_bp
from routes.tools_routes import tools_bp


def _valid_zenodo_metadata(title: str) -> dict:
    return {
        "upload_type": "dataset",
        "publication_date": "2026-03-30",
        "title": title,
        "creators": [{"name": "Museum Curator"}],
        "description": "Shared institution metadata draft.",
        "access_right": "open",
        "license": "cc-by-4.0",
    }


@pytest.fixture()
def permission_matrix_app():
    temp_dir = tempfile.mkdtemp(prefix="permission-matrix-")
    hdpc_path = os.path.join(temp_dir, "session.hdpc")
    with open(hdpc_path, "w", encoding="utf-8") as handle:
        handle.write("hdpc")

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "permission-matrix-secret"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = "permission-matrix-jwt"
    setup_error_handlers(app)

    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(session_bp, url_prefix="/api/v1/sessions")
    app.register_blueprint(metadata_bp, url_prefix="/api/v1/metadata")
    app.register_blueprint(submission_bp, url_prefix="/api/v1/submissions")
    app.register_blueprint(tools_bp, url_prefix="/api/v1/tools")

    with app.app_context():
        db.create_all()
        owner = User(email="owner@example.com", role=UserRole.USER, is_verified=True)
        owner.set_password("password123")
        reader = User(email="reader@example.com", role=UserRole.USER, is_verified=True)
        reader.set_password("password123")
        curator = User(email="curator@example.com", role=UserRole.USER, is_verified=True)
        curator.set_password("password123")
        manager = User(email="manager@example.com", role=UserRole.USER, is_verified=True)
        manager.set_password("password123")
        outsider = User(email="outsider@example.com", role=UserRole.USER, is_verified=True)
        outsider.set_password("password123")
        moderator = User(email="moderator@example.com", role=UserRole.MODERATOR, is_verified=True)
        moderator.set_password("password123")
        db.session.add_all([owner, reader, curator, manager, outsider, moderator])
        db.session.flush()

        institution = Institution(name="Museum Network", slug="museum-network", created_by_user_id=owner.id)
        db.session.add(institution)
        db.session.flush()
        db.session.add_all(
            [
                InstitutionMembership(institution_id=institution.id, user_id=owner.id, role=InstitutionRole.OWNER),
                InstitutionMembership(institution_id=institution.id, user_id=reader.id, role=InstitutionRole.READER),
                InstitutionMembership(institution_id=institution.id, user_id=curator.id, role=InstitutionRole.CURATOR),
                InstitutionMembership(institution_id=institution.id, user_id=manager.id, role=InstitutionRole.MANAGER),
            ]
        )
        db.session.flush()

        shared_session = DBSession(
            user_id=owner.id,
            institution_id=institution.id,
            session_dir=temp_dir,
            hdpc_path=hdpc_path,
            status="active",
            sharing_scope="institution",
            credential_preference="institution",
            publishing_user_id=owner.id,
            default_zenodo_environment="sandbox",
            use_institution_default_communities=False,
        )
        private_session = DBSession(
            user_id=owner.id,
            institution_id=institution.id,
            session_dir=os.path.join(temp_dir, "private"),
            hdpc_path=hdpc_path,
            status="active",
            sharing_scope="private",
            credential_preference="user",
            publishing_user_id=owner.id,
            default_zenodo_environment="sandbox",
            use_institution_default_communities=False,
        )
        db.session.add_all([shared_session, private_session])
        db.session.flush()

        file_row = File(
            session_id=shared_session.id,
            filename="sample.obj",
            path=os.path.join(temp_dir, "sample.obj"),
            status="uploaded",
        )
        submission = Submission(
            session_id=shared_session.id,
            pipeline_id="metadata_only",
            status="completed",
            result=json.dumps({"details": []}),
            timings=json.dumps({"duration_ms": 100}),
        )
        private_submission = Submission(
            session_id=private_session.id,
            pipeline_id="private_pipeline",
            status="completed",
            result=json.dumps({"details": []}),
            timings=json.dumps({"duration_ms": 50}),
        )
        workflow_metadata = UserMetadata(
            session_id=shared_session.id,
            field_name=WORKFLOW_STATE_FIELD,
            field_value=json.dumps({"phase": "metadata", "is_batch_mode": False}),
        )
        draft_metadata = UserMetadata(
            session_id=shared_session.id,
            field_name="zenodo_metadata_draft",
            field_value=json.dumps(_valid_zenodo_metadata("Initial shared draft")),
        )
        audit_event = AuditEvent(
            actor_user_id=owner.id,
            institution_id=institution.id,
            session_id=shared_session.id,
            event_type="session_workspace_updated",
            entity_type="session",
            entity_id=str(shared_session.id),
            details_json=json.dumps({"source": "fixture"}),
        )
        db.session.add_all([file_row, submission, private_submission, workflow_metadata, draft_metadata, audit_event])
        db.session.commit()

        tokens = {
            "owner": create_access_token(identity=str(owner.id)),
            "reader": create_access_token(identity=str(reader.id)),
            "curator": create_access_token(identity=str(curator.id)),
            "manager": create_access_token(identity=str(manager.id)),
            "outsider": create_access_token(identity=str(outsider.id)),
            "moderator": create_access_token(identity=str(moderator.id)),
        }
        shared_session_id = shared_session.id
        private_session_id = private_session.id
        shared_submission_id = submission.id
        private_submission_id = private_submission.id
        file_id = file_row.id

        yield {
            "app": app,
            "client": app.test_client(),
            "temp_dir": temp_dir,
            "shared_session_id": shared_session_id,
            "private_session_id": private_session_id,
            "shared_submission_id": shared_submission_id,
            "private_submission_id": private_submission_id,
            "file_id": file_id,
            "headers": {
                key: {"Authorization": f"Bearer {token}"}
                for key, token in tokens.items()
            },
        }

        db.session.remove()
        db.drop_all()


def test_workflow_and_metadata_routes_follow_shared_session_roles(permission_matrix_app):
    client = permission_matrix_app["client"]
    session_id = permission_matrix_app["shared_session_id"]
    private_session_id = permission_matrix_app["private_session_id"]
    headers = permission_matrix_app["headers"]

    reader_workflow = client.get(f"/api/v1/sessions/{session_id}/workflow-state", headers=headers["reader"])
    assert reader_workflow.status_code == 200

    reader_workflow_update = client.put(
        f"/api/v1/sessions/{session_id}/workflow-state",
        headers=headers["reader"],
        json={"phase": "submit"},
    )
    assert reader_workflow_update.status_code == 404

    reader_metadata = client.get(f"/api/v1/metadata/user/{session_id}", headers=headers["reader"])
    assert reader_metadata.status_code == 200
    assert reader_metadata.get_json()["data"]["metadata"]["zenodo_metadata_draft"]["title"] == "Initial shared draft"

    reader_metadata_update = client.put(
        f"/api/v1/metadata/user/{session_id}",
        headers=headers["reader"],
        json=_valid_zenodo_metadata("Reader draft"),
    )
    assert reader_metadata_update.status_code == 404

    curator_workflow_update = client.put(
        f"/api/v1/sessions/{session_id}/workflow-state",
        headers=headers["curator"],
        json={"phase": "submit", "is_batch_mode": False},
    )
    assert curator_workflow_update.status_code == 200

    curator_metadata_update = client.put(
        f"/api/v1/metadata/user/{session_id}",
        headers=headers["curator"],
        json=_valid_zenodo_metadata("Curator draft"),
    )
    assert curator_metadata_update.status_code == 200

    reader_metadata_after_update = client.get(f"/api/v1/metadata/user/{session_id}", headers=headers["reader"])
    assert reader_metadata_after_update.status_code == 200
    assert (
        reader_metadata_after_update.get_json()["data"]["metadata"]["zenodo_metadata_draft"]["title"]
        == "Curator draft"
    )

    outsider_workflow = client.get(f"/api/v1/sessions/{session_id}/workflow-state", headers=headers["outsider"])
    assert outsider_workflow.status_code == 404

    outsider_metadata = client.get(f"/api/v1/metadata/user/{session_id}", headers=headers["outsider"])
    assert outsider_metadata.status_code == 404

    private_reader_workflow = client.get(
        f"/api/v1/sessions/{private_session_id}/workflow-state",
        headers=headers["reader"],
    )
    assert private_reader_workflow.status_code == 404

    private_reader_metadata = client.get(
        f"/api/v1/metadata/user/{private_session_id}",
        headers=headers["reader"],
    )
    assert private_reader_metadata.status_code == 404


def test_submission_routes_follow_shared_session_visibility(permission_matrix_app):
    client = permission_matrix_app["client"]
    shared_submission_id = permission_matrix_app["shared_submission_id"]
    private_submission_id = permission_matrix_app["private_submission_id"]
    headers = permission_matrix_app["headers"]

    reader_list = client.get("/api/v1/submissions", headers=headers["reader"])
    assert reader_list.status_code == 200
    assert [item["id"] for item in reader_list.get_json()["data"]["submissions"]] == [shared_submission_id]

    outsider_list = client.get("/api/v1/submissions", headers=headers["outsider"])
    assert outsider_list.status_code == 200
    assert outsider_list.get_json()["data"]["submissions"] == []

    moderator_list = client.get("/api/v1/submissions", headers=headers["moderator"])
    assert moderator_list.status_code == 200
    assert {item["id"] for item in moderator_list.get_json()["data"]["submissions"]} == {
        shared_submission_id,
        private_submission_id,
    }

    reader_detail = client.get(f"/api/v1/submissions/{shared_submission_id}", headers=headers["reader"])
    assert reader_detail.status_code == 200
    assert reader_detail.get_json()["data"]["submission"]["id"] == shared_submission_id

    reader_private_detail = client.get(f"/api/v1/submissions/{private_submission_id}", headers=headers["reader"])
    assert reader_private_detail.status_code == 404

    outsider_detail = client.get(f"/api/v1/submissions/{shared_submission_id}", headers=headers["outsider"])
    assert outsider_detail.status_code == 404


def test_session_audit_route_requires_manage_permission(permission_matrix_app):
    client = permission_matrix_app["client"]
    session_id = permission_matrix_app["shared_session_id"]
    headers = permission_matrix_app["headers"]

    owner_response = client.get(f"/api/v1/sessions/{session_id}/audit-events", headers=headers["owner"])
    assert owner_response.status_code == 200
    assert owner_response.get_json()["data"]["pagination"]["total"] >= 1

    manager_response = client.get(f"/api/v1/sessions/{session_id}/audit-events", headers=headers["manager"])
    assert manager_response.status_code == 200

    moderator_response = client.get(f"/api/v1/sessions/{session_id}/audit-events", headers=headers["moderator"])
    assert moderator_response.status_code == 200

    curator_response = client.get(f"/api/v1/sessions/{session_id}/audit-events", headers=headers["curator"])
    assert curator_response.status_code == 404

    reader_response = client.get(f"/api/v1/sessions/{session_id}/audit-events", headers=headers["reader"])
    assert reader_response.status_code == 404


def test_match_files_for_versioning_requires_edit_permission(monkeypatch, permission_matrix_app):
    client = permission_matrix_app["client"]
    session_id = permission_matrix_app["shared_session_id"]
    headers = permission_matrix_app["headers"]
    temp_dir = permission_matrix_app["temp_dir"]

    monkeypatch.setattr(
        "routes.session_routes.match_hdpc_files_for_versioning",
        lambda resolved_hdpc_path, directory_path, match_method: [
            {
                "filename": "sample.obj",
                "directory_path": directory_path,
                "match_method": match_method,
            }
        ],
    )

    reader_response = client.post(
        f"/api/v1/sessions/{session_id}/versioning/match-files",
        headers=headers["reader"],
        json={"directory_path": temp_dir, "match_method": "filename"},
    )
    assert reader_response.status_code == 404

    curator_response = client.post(
        f"/api/v1/sessions/{session_id}/versioning/match-files",
        headers=headers["curator"],
        json={"directory_path": temp_dir, "match_method": "filename"},
    )
    assert curator_response.status_code == 200
    assert curator_response.get_json()["data"]["matches"][0]["directory_path"] == temp_dir


def test_community_moderation_remains_platform_only(monkeypatch, permission_matrix_app):
    client = permission_matrix_app["client"]
    headers = permission_matrix_app["headers"]

    monkeypatch.setattr(
        "routes.tools_routes.zenodo_moderation_service.fetch_open_community_requests",
        lambda community_identifier: {
            "community": {"slug": community_identifier},
            "requests": [],
            "open_count": 0,
        },
    )

    manager_response = client.get(
        "/api/v1/tools/community-moderation/requests?community_identifier=manual-community",
        headers=headers["manager"],
    )
    assert manager_response.status_code == 403

    moderator_response = client.get(
        "/api/v1/tools/community-moderation/requests?community_identifier=manual-community",
        headers=headers["moderator"],
    )
    assert moderator_response.status_code == 200
    assert moderator_response.get_json()["data"]["filters"]["community_identifier"] == "manual-community"
