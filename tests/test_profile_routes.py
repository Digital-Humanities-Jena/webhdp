import pytest
from datetime import datetime

pytest.importorskip("flask_jwt_extended")

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import Institution, User, UserRole
from middleware import setup_error_handlers
from routes.profile_routes import _is_internal_profile, profile_bp


@pytest.fixture()
def profile_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "profile-test-secret"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = "profile-test-jwt"

    setup_error_handlers(app)
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(profile_bp, url_prefix="/api/v1/profiles")

    with app.app_context():
        db.create_all()
        viewer = User(email="viewer@example.com", role=UserRole.USER, is_verified=True)
        viewer.set_password("password123")
        admin = User(email="admin@example.com", role=UserRole.ADMIN, is_verified=True)
        admin.set_password("password123")
        internal_user = User(
            email="ada@example.com",
            slug="ada-curator",
            role=UserRole.USER,
            is_verified=True,
            display_name="Ada Curator",
            full_name="Ada Lovelace",
            affiliation="Museum Lab",
            orcid="0000-0000-0000-0001",
            bio="Digitisation lead",
            profile_visibility="internal",
            show_orcid=True,
            show_affiliation=True,
            show_email=False,
        )
        internal_user.set_password("password123")
        private_user = User(
            email="private@example.com",
            slug="private-curator",
            role=UserRole.USER,
            is_verified=True,
            profile_visibility="private",
        )
        private_user.set_password("password123")
        internal_institution = Institution(
            name="Museum Network",
            display_name="Museum Network Internal",
            slug="museum-network",
            description="Shared heritage workspace",
            website_url="https://museum.example",
            logo_url="https://museum.example/logo.png",
            profile_visibility="internal",
        )
        private_institution = Institution(
            name="Private Museum",
            slug="private-museum",
            profile_visibility="private",
        )
        db.session.add_all([viewer, admin, internal_user, private_user, internal_institution, private_institution])
        db.session.commit()
        token = create_access_token(identity=str(viewer.id))
        admin_token = create_access_token(identity=str(admin.id))

        yield {
            "client": app.test_client(),
            "headers": {"Authorization": f"Bearer {token}"},
            "admin_headers": {"Authorization": f"Bearer {admin_token}"},
            "internal_user_public_id": internal_user.public_id,
            "internal_institution_public_id": internal_institution.public_id,
        }

        db.session.remove()
        db.drop_all()


def test_authenticated_user_can_fetch_internal_user_profile_by_slug_and_public_id(profile_app):
    client = profile_app["client"]

    slug_response = client.get("/api/v1/profiles/users/ada-curator", headers=profile_app["headers"])
    assert slug_response.status_code == 200
    slug_payload = slug_response.get_json()["data"]["user"]
    assert slug_payload["public_id"] == profile_app["internal_user_public_id"]
    assert slug_payload["display_name"] == "Ada Curator"
    assert slug_payload["orcid"] == "0000-0000-0000-0001"
    assert slug_payload["affiliation"] == "Museum Lab"
    assert "email" not in slug_payload

    id_response = client.get(
        f"/api/v1/profiles/users/{profile_app['internal_user_public_id']}",
        headers=profile_app["headers"],
    )
    assert id_response.status_code == 200
    assert id_response.get_json()["data"]["user"]["slug"] == "ada-curator"


def test_profile_routes_require_auth_and_hide_private_profiles(profile_app):
    client = profile_app["client"]

    unauthenticated = client.get("/api/v1/profiles/users/ada-curator")
    assert unauthenticated.status_code == 401

    private_user = client.get("/api/v1/profiles/users/private-curator", headers=profile_app["headers"])
    assert private_user.status_code == 404

    private_institution = client.get(
        "/api/v1/profiles/institutions/private-museum",
        headers=profile_app["headers"],
    )
    assert private_institution.status_code == 404


def test_admin_can_fetch_private_user_profile(profile_app):
    response = profile_app["client"].get(
        "/api/v1/profiles/users/private-curator",
        headers=profile_app["admin_headers"],
    )

    assert response.status_code == 200
    payload = response.get_json()["data"]["user"]
    assert payload["slug"] == "private-curator"
    assert payload["email"] == "private@example.com"


def test_authenticated_user_can_fetch_internal_institution_profile_by_slug_and_public_id(profile_app):
    client = profile_app["client"]

    slug_response = client.get("/api/v1/profiles/institutions/museum-network", headers=profile_app["headers"])
    assert slug_response.status_code == 200
    slug_payload = slug_response.get_json()["data"]["institution"]
    assert slug_payload["public_id"] == profile_app["internal_institution_public_id"]
    assert slug_payload["name"] == "Museum Network Internal"
    assert slug_payload["legal_name"] == "Museum Network"

    id_response = client.get(
        f"/api/v1/profiles/institutions/{profile_app['internal_institution_public_id']}",
        headers=profile_app["headers"],
    )
    assert id_response.status_code == 200
    assert id_response.get_json()["data"]["institution"]["slug"] == "museum-network"


def test_legacy_public_visibility_is_treated_as_internal_for_reads():
    legacy_user = User(email="legacy@example.com", profile_visibility="public")
    legacy_user.created_at = datetime.utcnow()
    legacy_institution = Institution(name="Legacy Museum", slug="legacy-museum", profile_visibility="public")

    assert legacy_user.to_dict()["profile_visibility"] == "internal"
    assert legacy_institution.to_dict()["profile_visibility"] == "internal"
    assert _is_internal_profile("public") is True
