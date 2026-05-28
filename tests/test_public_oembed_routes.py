from flask import Flask

from database.database import db
from database.models import Institution, User, UserRole
from middleware import setup_error_handlers
from routes.public_routes import public_bp


def _make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    app.register_blueprint(public_bp, url_prefix="/api/v1")

    @app.route("/embed/records/zenodo/123")
    def embed_shell():
        return "embed"

    setup_error_handlers(app)
    with app.app_context():
        db.create_all()
    return app


def test_public_record_endpoint_is_available_without_jwt(monkeypatch):
    monkeypatch.setattr(
        "routes.public_routes.build_public_record",
        lambda environment, zenodo_record_id, public_base_url: {
            "environment": environment,
            "zenodo_record_id": zenodo_record_id,
            "title": "Public 3D Model",
        },
    )
    client = _make_app().test_client()

    response = client.get("/api/v1/public/records/zenodo/123")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["title"] == "Public 3D Model"


def test_oembed_endpoint_returns_raw_oembed_json(monkeypatch):
    monkeypatch.setattr(
        "routes.public_routes.build_public_record",
        lambda environment, zenodo_record_id, public_base_url: {
            "title": "Public 3D Model",
            "provider_name": "WebHDP",
            "provider_url": public_base_url,
            "author_name": "",
            "embed_url": f"{public_base_url}/embed/records/{environment}/{zenodo_record_id}",
        },
    )
    client = _make_app().test_client()

    response = client.get(
        "/api/v1/oembed",
        query_string={
            "url": "https://webhdp.example/p/records/zenodo/123",
            "format": "json",
            "maxwidth": "320",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["type"] == "rich"
    assert payload["version"] == "1.0"
    assert payload["width"] == 320
    assert payload["height"] == 240
    assert "/embed/records/zenodo/123" in payload["html"]


def test_oembed_endpoint_rejects_xml_format():
    client = _make_app().test_client()

    response = client.get(
        "/api/v1/oembed",
        query_string={"url": "https://webhdp.example/p/records/zenodo/123", "format": "xml"},
    )

    assert response.status_code == 501
    assert response.get_json()["error"] == "Only JSON oEmbed responses are supported"


def test_oembed_endpoint_requires_public_record_url():
    client = _make_app().test_client()

    response = client.get("/api/v1/oembed", query_string={"url": "https://webhdp.example/dashboard"})

    assert response.status_code == 400
    assert "public record" in response.get_json()["error"]


def test_embed_route_allows_framing_without_relaxing_other_routes():
    client = _make_app().test_client()

    embed_response = client.get("/embed/records/zenodo/123")
    missing_response = client.get("/not-an-embed-route")

    assert embed_response.status_code == 200
    assert "frame-ancestors 'self'" in embed_response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in missing_response.headers["Content-Security-Policy"]


def test_public_user_profile_route_is_not_available():
    app = _make_app()
    with app.app_context():
        user = User(
            email="ada@example.com",
            slug="ada-curator",
            role=UserRole.USER,
            is_verified=True,
            display_name="Ada Curator",
            profile_visibility="internal",
        )
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()

    client = app.test_client()
    response = client.get("/api/v1/public/users/ada-curator")

    assert response.status_code == 404


def test_public_institution_profile_route_is_not_available():
    app = _make_app()
    with app.app_context():
        institution = Institution(
            name="Museum Network",
            display_name="Museum Network Internal",
            slug="museum-network",
            description="Shared heritage workspace",
            profile_visibility="internal",
        )
        db.session.add(institution)
        db.session.commit()

    client = app.test_client()
    response = client.get("/api/v1/public/institutions/museum-network")

    assert response.status_code == 404
