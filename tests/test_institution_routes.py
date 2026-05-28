import pytest
pytest.importorskip("flask_jwt_extended")
pytest.importorskip("cryptography.fernet")
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import Institution, InstitutionMembership, InstitutionRole, User, UserRole
from middleware import setup_error_handlers
from routes.institution_routes import institution_bp
from services.zenodo_credential_service import ZenodoCredentialService


@pytest.fixture()
def institution_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "institution-test-secret"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = "institution-test-jwt"

    setup_error_handlers(app)
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(institution_bp, url_prefix="/api/v1/institutions")

    with app.app_context():
        db.create_all()
        owner = User(email="owner@example.com", role=UserRole.USER, is_verified=True)
        owner.set_password("password123")
        manager = User(email="manager@example.com", role=UserRole.USER, is_verified=True)
        manager.set_password("password123")
        reader = User(email="reader@example.com", role=UserRole.USER, is_verified=True)
        reader.set_password("password123")
        moderator = User(email="moderator@example.com", role=UserRole.MODERATOR, is_verified=True)
        moderator.set_password("password123")
        admin = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
        admin.set_password("password123")
        db.session.add_all([owner, manager, reader, moderator, admin])
        db.session.flush()

        institution = Institution(
            name="Museum Network",
            slug="museum-network",
            created_by_user_id=owner.id,
        )
        db.session.add(institution)
        db.session.flush()

        db.session.add_all(
            [
                InstitutionMembership(
                    institution_id=institution.id,
                    user_id=owner.id,
                    role=InstitutionRole.OWNER,
                ),
                InstitutionMembership(
                    institution_id=institution.id,
                    user_id=manager.id,
                    role=InstitutionRole.MANAGER,
                ),
                InstitutionMembership(
                    institution_id=institution.id,
                    user_id=reader.id,
                    role=InstitutionRole.READER,
                ),
            ]
        )
        reader.default_institution_id = institution.id
        db.session.commit()

        credential_service = ZenodoCredentialService()
        credential_service.upsert_credential(
            owner_type="institution",
            owner_id=institution.id,
            environment="sandbox",
            token="sandbox-secret-token",
            actor_user_id=owner.id,
        )

        with app.app_context():
            owner_token = create_access_token(identity=str(owner.id))
            manager_token = create_access_token(identity=str(manager.id))
            reader_token = create_access_token(identity=str(reader.id))
            moderator_token = create_access_token(identity=str(moderator.id))
            admin_token = create_access_token(identity=str(admin.id))

        yield {
            "app": app,
            "client": app.test_client(),
            "institution_id": institution.id,
            "owner_id": owner.id,
            "manager_id": manager.id,
            "reader_id": reader.id,
            "owner_headers": {"Authorization": f"Bearer {owner_token}"},
            "manager_headers": {"Authorization": f"Bearer {manager_token}"},
            "reader_headers": {"Authorization": f"Bearer {reader_token}"},
            "moderator_headers": {"Authorization": f"Bearer {moderator_token}"},
            "admin_headers": {"Authorization": f"Bearer {admin_token}"},
        }

        db.session.remove()
        db.drop_all()


def test_institution_detail_redacts_credentials_for_reader(institution_app):
    client = institution_app["client"]
    institution_id = institution_app["institution_id"]

    reader_response = client.get(
        f"/api/v1/institutions/{institution_id}",
        headers=institution_app["reader_headers"],
    )
    assert reader_response.status_code == 200
    reader_payload = reader_response.get_json()["data"]["institution"]
    assert "zenodo_credentials" not in reader_payload

    manager_response = client.get(
        f"/api/v1/institutions/{institution_id}",
        headers=institution_app["manager_headers"],
    )
    assert manager_response.status_code == 200
    manager_payload = manager_response.get_json()["data"]["institution"]
    assert manager_payload["zenodo_credentials"]["sandbox"]["masked_preview"]

    reader_credential_response = client.get(
        f"/api/v1/institutions/{institution_id}/zenodo-credentials/sandbox",
        headers=institution_app["reader_headers"],
    )
    assert reader_credential_response.status_code == 404


def test_user_can_select_existing_institution_affiliation(institution_app):
    client = institution_app["client"]
    institution_id = institution_app["institution_id"]

    suggestions = client.get(
        "/api/v1/institutions/suggestions?q=Museum",
        headers=institution_app["moderator_headers"],
    )
    assert suggestions.status_code == 200
    assert suggestions.get_json()["data"]["institutions"][0]["name"] == "Museum Network"

    response = client.post(
        "/api/v1/institutions/affiliation",
        headers=institution_app["moderator_headers"],
        json={"institution_id": institution_id},
    )
    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["institution"]["name"] == "Museum Network"

    with institution_app["app"].app_context():
        moderator = User.query.filter_by(email="moderator@example.com").first()
        assert moderator.default_institution_id == institution_id
        assert moderator.affiliation == "Museum Network"
        assert InstitutionMembership.query.filter_by(user_id=moderator.id, institution_id=institution_id).first()


def test_user_affiliation_warns_on_similar_institution_before_create(institution_app):
    client = institution_app["client"]

    similar = client.post(
        "/api/v1/institutions/affiliation",
        headers=institution_app["moderator_headers"],
        json={"name": "Museum Networks"},
    )
    assert similar.status_code == 409
    assert similar.get_json()["error"]["code"] == "SIMILAR_INSTITUTION_EXISTS"
    assert similar.get_json()["error"]["details"]["similar"][0]["name"] == "Museum Network"

    created = client.post(
        "/api/v1/institutions/affiliation",
        headers=institution_app["moderator_headers"],
        json={"name": "Museum Networks", "confirm_create": True},
    )
    assert created.status_code == 201
    assert created.get_json()["data"]["created"] is True

    with institution_app["app"].app_context():
        assert Institution.query.filter_by(name="Museum Networks").first() is not None


def test_institution_membership_protects_last_owner_and_clears_default_institution(institution_app):
    client = institution_app["client"]
    institution_id = institution_app["institution_id"]
    owner_id = institution_app["owner_id"]
    reader_id = institution_app["reader_id"]

    demote_response = client.put(
        f"/api/v1/institutions/{institution_id}/memberships/{owner_id}",
        headers=institution_app["owner_headers"],
        json={"role": "manager"},
    )
    assert demote_response.status_code == 400
    assert demote_response.get_json()["error"]["code"] == "VALIDATION_ERROR"

    remove_response = client.delete(
        f"/api/v1/institutions/{institution_id}/memberships/{reader_id}",
        headers=institution_app["owner_headers"],
    )
    assert remove_response.status_code == 200

    with institution_app["app"].app_context():
        reader = db.session.get(User, reader_id)
        assert reader.default_institution_id is None


def test_institution_audit_events_require_manager_access(institution_app):
    client = institution_app["client"]
    institution_id = institution_app["institution_id"]

    reader_response = client.get(
        f"/api/v1/institutions/{institution_id}/audit-events",
        headers=institution_app["reader_headers"],
    )
    assert reader_response.status_code == 404

    manager_response = client.get(
        f"/api/v1/institutions/{institution_id}/audit-events",
        headers=institution_app["manager_headers"],
    )
    assert manager_response.status_code == 200
    payload = manager_response.get_json()["data"]
    assert payload["pagination"]["total"] >= 1
    assert any(event["event_type"] == "zenodo_credential_created" for event in payload["audit_events"])


def test_primary_submission_community_is_unique_and_policy_is_resolved(institution_app):
    client = institution_app["client"]
    institution_id = institution_app["institution_id"]

    first_response = client.post(
        f"/api/v1/institutions/{institution_id}/communities",
        headers=institution_app["manager_headers"],
        json={
            "identifier": "alpha",
            "enabled": True,
            "is_primary_submission": True,
            "sort_order": 0,
        },
    )
    assert first_response.status_code == 201

    second_response = client.post(
        f"/api/v1/institutions/{institution_id}/communities",
        headers=institution_app["manager_headers"],
        json={
            "identifier": "beta",
            "enabled": True,
            "is_primary_submission": True,
            "is_moderation_default": True,
            "sort_order": 100,
        },
    )
    assert second_response.status_code == 201

    detail_response = client.get(
        f"/api/v1/institutions/{institution_id}",
        headers=institution_app["manager_headers"],
    )
    assert detail_response.status_code == 200
    institution_payload = detail_response.get_json()["data"]["institution"]
    by_identifier = {item["identifier"]: item for item in institution_payload["communities"]}

    assert by_identifier["alpha"]["is_primary_submission"] is False
    assert by_identifier["beta"]["is_primary_submission"] is True
    assert institution_payload["community_policy"]["primary_submission_community"] == "beta"
    assert institution_payload["community_policy"]["moderation_default_communities"] == ["beta"]
    assert institution_payload["community_policy"]["default_communities"] == ["beta", "alpha"]


def test_moderator_can_list_all_institutions_with_summary_only(institution_app):
    client = institution_app["client"]

    response = client.get(
        "/api/v1/institutions?all=true",
        headers=institution_app["moderator_headers"],
    )

    assert response.status_code == 200
    institutions = response.get_json()["data"]["institutions"]
    assert len(institutions) == 1
    assert institutions[0]["name"] == "Museum Network"
    assert institutions[0]["member_count"] == 3
    assert institutions[0]["role"] is None
    assert "memberships" not in institutions[0]
    assert "communities" not in institutions[0]
    assert "zenodo_credentials" not in institutions[0]


def test_admin_can_list_all_institutions_with_summary_only(institution_app):
    client = institution_app["client"]

    response = client.get(
        "/api/v1/institutions?all=true",
        headers=institution_app["admin_headers"],
    )

    assert response.status_code == 200
    institutions = response.get_json()["data"]["institutions"]
    assert len(institutions) == 1
    assert institutions[0]["name"] == "Museum Network"
    assert institutions[0]["member_count"] == 3
    assert institutions[0]["role"] is None
    assert "memberships" not in institutions[0]
    assert "communities" not in institutions[0]
    assert "zenodo_credentials" not in institutions[0]


def test_manager_can_validate_institution_credential_with_live_write_report(monkeypatch, institution_app):
    client = institution_app["client"]
    institution_id = institution_app["institution_id"]

    class _Response:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = ""

        def json(self):
            return self._payload

    monkeypatch.setattr("services.zenodo_credential_service.requests.get", lambda *args, **kwargs: _Response(200, []))
    monkeypatch.setattr("services.zenodo_credential_service.requests.post", lambda *args, **kwargs: _Response(403, {"message": "Missing deposit:write"}))

    response = client.post(
        f"/api/v1/institutions/{institution_id}/zenodo-credentials/sandbox/validate",
        headers=institution_app["manager_headers"],
    )

    assert response.status_code == 200
    credential = response.get_json()["data"]["credential"]
    assert credential["validation_mode"] == "live_write_cleanup"
    assert credential["validation_status"] == "invalid"
    assert credential["recommended_scopes"] == ["deposit:write", "deposit:actions"]
    assert credential["validation_report"]["capabilities"]["deposit_read"]["status"] == "verified"
    assert credential["validation_report"]["capabilities"]["draft_create"]["status"] == "invalid"


def test_reader_cannot_validate_institution_credential(institution_app):
    client = institution_app["client"]
    institution_id = institution_app["institution_id"]

    response = client.post(
        f"/api/v1/institutions/{institution_id}/zenodo-credentials/sandbox/validate",
        headers=institution_app["reader_headers"],
    )

    assert response.status_code == 404
