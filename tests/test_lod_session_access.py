import json

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import (
    Institution,
    InstitutionMembership,
    InstitutionRole,
    Session as DBSession,
    User,
    UserMetadata,
    UserRole,
)
from routes.iiif_routes import iiif_bp
from routes import iiif_routes


class _FrameStub:
    def __init__(self, rows):
        self._rows = list(rows)
        self.iloc = self

    def __len__(self):
        return len(self._rows)

    def __getitem__(self, index):
        return self._rows[index]


class _StubIiifService:
    def generate_iiif_manifest_with_report(self, **kwargs):
        return {
            "content": '{"id":"https://example.org/manifest.json","type":"Manifest"}',
            "minimum_viable_applied": False,
            "validation": None,
        }

    def validate_iiif_manifest(self, manifest_json):
        return {"valid": True, "errors": [], "warnings": []}


@pytest.fixture()
def lod_access_app(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = "lod-access-jwt"

    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(iiif_bp, url_prefix="/api/v1/iiif")

    monkeypatch.setattr(
        iiif_routes.msf_service,
        "parse_msf_file_with_profile",
        lambda *args, **kwargs: (
            _FrameStub([{"filename": "artifact.glb", "title": "Artifact"}]),
            {"filename_column": "filename"},
        ),
    )
    monkeypatch.setattr(iiif_routes, "build_pipeline_aligned_lod_metadata", lambda **kwargs: {"title": "Artifact"})
    monkeypatch.setattr(iiif_routes, "iiif_service", _StubIiifService())

    with app.app_context():
        db.create_all()
        owner = User(email="owner@example.com", role=UserRole.USER, is_verified=True)
        owner.set_password("password123")
        viewer = User(email="viewer@example.com", role=UserRole.USER, is_verified=True)
        viewer.set_password("password123")
        outsider = User(email="outsider@example.com", role=UserRole.USER, is_verified=True)
        outsider.set_password("password123")
        db.session.add_all([owner, viewer, outsider])
        db.session.flush()

        institution = Institution(name="LOD Lab", slug="lod-lab", created_by_user_id=owner.id)
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
                    user_id=viewer.id,
                    role=InstitutionRole.READER,
                ),
            ]
        )

        session_dir = tmp_path / "session"
        uploads_dir = session_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        msf_path = uploads_dir / "upload.msf.csv"
        msf_path.write_text("filename,title\nartifact.glb,Artifact\n", encoding="utf-8")
        hdpc_path = session_dir / "session.hdpc"
        hdpc_path.write_text("", encoding="utf-8")

        session_row = DBSession(
            user_id=owner.id,
            institution_id=institution.id,
            session_dir=str(session_dir),
            hdpc_path=str(hdpc_path),
            status="completed",
            sharing_scope="institution",
        )
        db.session.add(session_row)
        db.session.flush()
        db.session.add(
            UserMetadata(
                session_id=session_row.id,
                field_name="msf_profile",
                field_value=json.dumps({"file_path": str(msf_path), "parse_options": {}}),
            )
        )
        db.session.commit()

        with app.app_context():
            owner_headers = {"Authorization": f"Bearer {create_access_token(identity=str(owner.id))}"}
            viewer_headers = {"Authorization": f"Bearer {create_access_token(identity=str(viewer.id))}"}
            outsider_headers = {"Authorization": f"Bearer {create_access_token(identity=str(outsider.id))}"}

        yield {
            "client": app.test_client(),
            "session_id": session_row.id,
            "owner_headers": owner_headers,
            "viewer_headers": viewer_headers,
            "outsider_headers": outsider_headers,
        }

        db.session.remove()
        db.drop_all()


def test_iiif_mapping_route_uses_session_permissions(lod_access_app):
    client = lod_access_app["client"]
    session_id = lod_access_app["session_id"]

    viewer_response = client.post(
        "/api/v1/iiif/test-mapping",
        headers=lod_access_app["viewer_headers"],
        json={"session_id": session_id, "row_index": 0},
    )
    assert viewer_response.status_code == 200
    assert viewer_response.get_json()["data"]["validation"]["valid"] is True

    outsider_response = client.post(
        "/api/v1/iiif/test-mapping",
        headers=lod_access_app["outsider_headers"],
        json={"session_id": session_id, "row_index": 0},
    )
    assert outsider_response.status_code == 404


def test_lod_mapping_cannot_read_another_sessions_file_or_a_symlink(lod_access_app, tmp_path):
    client = lod_access_app['client']
    outside = tmp_path / 'private.csv'
    outside.write_text('secret,value\nprivate,data\n')
    payload = {'session_id': lod_access_app['session_id'], 'row_index': 0, 'msf_path': str(outside)}
    assert client.post('/api/v1/iiif/test-mapping', headers=lod_access_app['viewer_headers'], json=payload).status_code == 400
    link = tmp_path / 'session' / 'uploads' / 'linked.csv'
    link.symlink_to(outside)
    payload['msf_path'] = str(link)
    assert client.post('/api/v1/iiif/test-mapping', headers=lod_access_app['viewer_headers'], json=payload).status_code == 400
    payload.pop('session_id')
    assert client.post('/api/v1/iiif/test-mapping', headers=lod_access_app['viewer_headers'], json=payload).status_code == 400


def test_ambiguous_preview_source_is_an_actionable_validation_error(lod_access_app, monkeypatch):
    def ambiguous(**kwargs):
        raise ValueError('Ambiguous filename model.glb. Use the exact relative source path.')
    monkeypatch.setattr(iiif_routes, 'build_pipeline_aligned_lod_metadata', ambiguous)
    response = lod_access_app['client'].post(
        '/api/v1/iiif/test-mapping', headers=lod_access_app['viewer_headers'],
        json={'session_id': lod_access_app['session_id'], 'row_index': 0},
    )
    assert response.status_code == 400
    assert 'exact relative source path' in response.get_json()['error']['message']
