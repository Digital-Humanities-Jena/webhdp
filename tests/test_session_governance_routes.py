import os
import tempfile

import pytest
pytest.importorskip("flask_jwt_extended")
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import File, Institution, InstitutionMembership, InstitutionRole, Session as DBSession, User, UserRole
from middleware import setup_error_handlers
from routes.session_routes import session_bp


@pytest.fixture()
def session_governance_app():
    temp_dir = tempfile.mkdtemp(prefix="session-governance-")
    hdpc_path = os.path.join(temp_dir, "session.hdpc")
    with open(hdpc_path, "w", encoding="utf-8") as handle:
        handle.write("hdpc")

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = "session-governance-secret"
    setup_error_handlers(app)

    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(session_bp, url_prefix="/api/v1/sessions")

    with app.app_context():
        db.create_all()

        owner = User(email="owner@example.com", role=UserRole.USER, is_verified=True)
        owner.set_password("password123")
        manager = User(email="manager@example.com", role=UserRole.USER, is_verified=True)
        manager.set_password("password123")
        colleague = User(email="colleague@example.com", role=UserRole.USER, is_verified=True)
        colleague.set_password("password123")
        alternate = User(email="alternate@example.com", role=UserRole.USER, is_verified=True)
        alternate.set_password("password123")
        moderator = User(email="moderator@example.com", role=UserRole.MODERATOR, is_verified=True)
        moderator.set_password("password123")
        db.session.add_all([owner, manager, colleague, alternate, moderator])
        db.session.flush()

        institution = Institution(name="Museum Network", slug="museum-network", created_by_user_id=owner.id)
        other_institution = Institution(name="Archive Lab", slug="archive-lab", created_by_user_id=owner.id)
        db.session.add_all([institution, other_institution])
        db.session.flush()

        db.session.add_all(
            [
                InstitutionMembership(institution_id=institution.id, user_id=owner.id, role=InstitutionRole.OWNER),
                InstitutionMembership(institution_id=institution.id, user_id=manager.id, role=InstitutionRole.MANAGER),
                InstitutionMembership(institution_id=institution.id, user_id=colleague.id, role=InstitutionRole.READER),
                InstitutionMembership(
                    institution_id=other_institution.id,
                    user_id=owner.id,
                    role=InstitutionRole.CURATOR,
                ),
                InstitutionMembership(
                    institution_id=other_institution.id,
                    user_id=alternate.id,
                    role=InstitutionRole.READER,
                ),
            ]
        )

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
            use_institution_default_communities=True,
        )
        personal_session = DBSession(
            user_id=owner.id,
            session_dir=os.path.join(temp_dir, "personal"),
            hdpc_path=hdpc_path,
            status="active",
            sharing_scope="private",
            credential_preference="user",
            publishing_user_id=owner.id,
            default_zenodo_environment="sandbox",
            use_institution_default_communities=False,
        )
        db.session.add_all([shared_session, personal_session])
        db.session.flush()
        db.session.add_all(
            [
                File(
                    session_id=shared_session.id,
                    filename="shared-one.obj",
                    path=os.path.join(temp_dir, "shared-one.obj"),
                ),
                File(
                    session_id=shared_session.id,
                    filename="shared-two.obj",
                    path=os.path.join(temp_dir, "shared-two.obj"),
                ),
                File(
                    session_id=personal_session.id,
                    filename="personal-one.obj",
                    path=os.path.join(temp_dir, "personal-one.obj"),
                ),
            ]
        )
        db.session.commit()

        shared_session_id = shared_session.id
        personal_session_id = personal_session.id
        institution_id = institution.id
        other_institution_id = other_institution.id
        owner_id = owner.id
        manager_id = manager.id
        colleague_id = colleague.id
        alternate_id = alternate.id

        owner_token = create_access_token(identity=str(owner.id))
        manager_token = create_access_token(identity=str(manager.id))
        moderator_token = create_access_token(identity=str(moderator.id))

    return {
        "app": app,
        "client": app.test_client(),
        "shared_session_id": shared_session_id,
        "personal_session_id": personal_session_id,
        "institution_id": institution_id,
        "other_institution_id": other_institution_id,
        "owner_id": owner_id,
        "manager_id": manager_id,
        "colleague_id": colleague_id,
        "alternate_id": alternate_id,
        "owner_headers": {"Authorization": f"Bearer {owner_token}"},
        "manager_headers": {"Authorization": f"Bearer {manager_token}"},
        "moderator_headers": {"Authorization": f"Bearer {moderator_token}"},
    }


def test_session_list_and_detail_include_permissions(session_governance_app):
    client = session_governance_app["client"]
    session_id = session_governance_app["shared_session_id"]

    owner_list = client.get("/api/v1/sessions?scope=all", headers=session_governance_app["owner_headers"])
    assert owner_list.status_code == 200
    owner_session = next(item for item in owner_list.get_json()["data"]["sessions"] if item["id"] == session_id)
    assert owner_session["permissions"]["is_owner"] is True
    assert owner_session["permissions"]["can_manage"] is True
    assert owner_session["permissions"]["can_download_hdpc"] is True
    assert owner_session["permissions"]["can_download_shared_hdpc"] is True
    assert owner_session["file_count"] == 2
    assert owner_session["name"] == "shared-one.obj"
    assert owner_session["publishing_context"]["effective_credential_source"] == "system"

    manager_detail = client.get(
        f"/api/v1/sessions/{session_id}",
        headers=session_governance_app["manager_headers"],
    )
    assert manager_detail.status_code == 200
    manager_session = manager_detail.get_json()["data"]["session"]
    assert manager_session["permissions"]["is_owner"] is False
    assert manager_session["permissions"]["can_manage"] is True
    assert manager_session["permissions"]["can_download_hdpc"] is False
    assert manager_session["permissions"]["can_download_shared_hdpc"] is True


def test_session_workspace_route_returns_preview_candidates(session_governance_app):
    client = session_governance_app["client"]
    session_id = session_governance_app["shared_session_id"]
    other_institution_id = session_governance_app["other_institution_id"]

    owner_response = client.get(
        f"/api/v1/sessions/{session_id}/workspace",
        headers=session_governance_app["owner_headers"],
    )
    assert owner_response.status_code == 200
    owner_payload = owner_response.get_json()["data"]
    assert owner_payload["session"]["permissions"]["can_manage"] is True
    assert owner_payload["hdpc_download_policy"]["scope"] == "owner_only"
    assert owner_payload["shared_hdpc_download_policy"]["scope"] == "institution_reader_plus"
    assert owner_payload["shared_hdpc_download_policy"]["can_download"] is True
    assert {item["email"] for item in owner_payload["publishing_user_candidates"]} == {
        "owner@example.com",
        "manager@example.com",
        "colleague@example.com",
    }

    manager_response = client.get(
        f"/api/v1/sessions/{session_id}/workspace",
        headers=session_governance_app["manager_headers"],
    )
    assert manager_response.status_code == 200
    manager_payload = manager_response.get_json()["data"]
    assert manager_payload["session"]["permissions"]["can_manage"] is True
    assert manager_payload["shared_hdpc_download_policy"]["can_download"] is True
    assert {item["id"] for item in manager_payload["target_institutions"]} == {
        session_governance_app["institution_id"],
    }

    preview_response = client.get(
        f"/api/v1/sessions/{session_id}/workspace?institution_id={other_institution_id}",
        headers=session_governance_app["owner_headers"],
    )
    assert preview_response.status_code == 200
    preview_payload = preview_response.get_json()["data"]
    assert preview_payload["preview_institution_id"] == other_institution_id
    assert {item["email"] for item in preview_payload["publishing_user_candidates"]} == {
        "owner@example.com",
        "alternate@example.com",
    }

    moderator_response = client.get(
        f"/api/v1/sessions/{session_id}/workspace",
        headers=session_governance_app["moderator_headers"],
    )
    assert moderator_response.status_code == 200
    moderator_payload = moderator_response.get_json()["data"]
    assert {item["id"] for item in moderator_payload["target_institutions"]} == {
        session_governance_app["institution_id"],
        session_governance_app["other_institution_id"],
    }


def test_personal_session_rejects_non_owner_publishing_user(session_governance_app):
    client = session_governance_app["client"]
    session_id = session_governance_app["personal_session_id"]

    response = client.put(
        f"/api/v1/sessions/{session_id}/workspace",
        headers=session_governance_app["owner_headers"],
        json={
            "institution_id": None,
            "sharing_scope": "private",
            "credential_preference": "user",
            "publishing_user_id": session_governance_app["manager_id"],
            "default_zenodo_environment": "sandbox",
            "use_institution_default_communities": False,
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_hdpc_download_route_remains_owner_only(session_governance_app):
    client = session_governance_app["client"]
    app = session_governance_app["app"]
    session_id = session_governance_app["shared_session_id"]

    manager_response = client.get(
        f"/api/v1/sessions/{session_id}/hdpc",
        headers=session_governance_app["manager_headers"],
    )
    assert manager_response.status_code == 404

    owner_response = client.get(
        f"/api/v1/sessions/{session_id}/hdpc",
        headers=session_governance_app["owner_headers"],
    )
    assert owner_response.status_code == 200

    with app.app_context():
        session_row = db.session.get(DBSession, session_id)
        session_row.status = "queued"
        db.session.commit()

    queued_response = client.get(
        f"/api/v1/sessions/{session_id}/hdpc",
        headers=session_governance_app["owner_headers"],
    )
    assert queued_response.status_code == 400

    with app.app_context():
        session_row = db.session.get(DBSession, session_id)
        session_row.status = "submitting"
        db.session.commit()

    submitting_response = client.get(
        f"/api/v1/sessions/{session_id}/hdpc",
        headers=session_governance_app["owner_headers"],
    )
    assert submitting_response.status_code == 200
