import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from lxml import etree

from database.database import db, init_db
from database.lod_template_bootstrap import ensure_default_lod_templates
from database.models import LodTemplate
from database.seed_edm_templates import MODEL_3D_TEMPLATE
from routes.template_routes import template_bp
from services.edm_service import EdmService


@pytest.fixture
def preview_app(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'template-preview.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY="template-preview-tests-with-a-long-secret-key",
        ENABLE_LOCAL_EDM_VALIDATION=False,
        ENABLE_METIS_VALIDATION=False,
        LOCAL_EDM_VALIDATOR_REQUIRED=False,
    )
    init_db(app)
    JWTManager(app)
    app.register_blueprint(template_bp, url_prefix="/templates")
    app.edm_service = EdmService()
    monkeypatch.setattr("routes.template_routes.check_admin_access", lambda: True)
    with app.app_context():
        db.create_all()
        ensure_default_lod_templates()
        token = create_access_token(identity="1")
        template_id = LodTemplate.query.filter_by(name="3D Model").one().id
    yield app, {"Authorization": f"Bearer {token}"}, template_id
    with app.app_context():
        db.session.remove()
        db.drop_all()


def _preview_data():
    return {
        "metadata": {
            "title": "Terrain model",
            "description": "A synthetic terrain model with a textured surface for preview validation.",
            "creators": [{"name": "Museum collection"}],
            "upload_type": "dataset",
            "resource_type": "3D Model",
            "license": "cc-by-4.0",
            "language": "en",
        },
        "zenodo": {
            "id": 12345,
            "metadata": {"prereserve_doi": {"doi": "10.5072/zenodo.12345"}},
            "links": {"html": "https://sandbox.zenodo.org/records/12345"},
        },
        "main_file_key": "terrain.glb",
    }


def _legacy_3d_template():
    dc_type = '    <dc:type rdf:resource="{{ helpers.map_3d_type(metadata) }}"/>\n'
    return MODEL_3D_TEMPLATE.replace(dc_type, "").replace(
        "    <edm:type>3D</edm:type>\n    {% set digital_source_type_uri",
        "    <edm:type>3D</edm:type>\n" + dc_type + "    {% set digital_source_type_uri",
    )


def test_saved_legacy_3d_preview_uses_export_preparation_without_rewriting_template(preview_app):
    app, headers, template_id = preview_app
    data = {**_preview_data(), "template_id": template_id}
    with app.app_context():
        template = db.session.get(LodTemplate, template_id)
        template.content = _legacy_3d_template()
        db.session.commit()
        original_content = template.content
        raw = app.edm_service.render_template(template_id, data["metadata"], data["zenodo"], main_file_key=data["main_file_key"])
        assert app.edm_service.validate_with_xsd(raw)["valid"] is False
        exported = app.edm_service.generate_edm_xml_with_report(
            metadata=data["metadata"], zenodo_record=data["zenodo"],
            template_id=template_id, main_file_key=data["main_file_key"], validate=False,
        )["content"]

    response = app.test_client().post("/templates/preview", json=data, headers=headers)
    assert response.status_code == 200
    xml = response.json["data"]["xml"]
    assert xml == exported
    validation = app.test_client().post("/templates/validate", json={"xml": xml}, headers=headers)
    assert validation.json["data"]["valid"] is True
    assert validation.json["data"]["details"]["xsd"]["valid"] is True
    with app.app_context():
        assert db.session.get(LodTemplate, template_id).content == original_content


def test_raw_admin_preview_shares_preparation_and_preserves_real_schema_errors(preview_app):
    app, headers, _ = preview_app
    data = {**_preview_data(), "content": _legacy_3d_template()}
    response = app.test_client().post("/templates/preview", json=data, headers=headers)
    assert response.status_code == 200
    xml = response.json["data"]["xml"]
    assert app.edm_service.validate_with_xsd(xml)["valid"] is True

    data["content"] = data["content"].replace("</edm:WebResource>", "<edm:unexpectedProperty>Invalid</edm:unexpectedProperty></edm:WebResource>", 1)
    response = app.test_client().post("/templates/preview", json=data, headers=headers)
    assert response.status_code == 200
    xml = response.json["data"]["xml"]
    assert "unexpectedProperty" in xml
    validation = app.test_client().post("/templates/validate", json={"xml": xml}, headers=headers)
    assert validation.json["data"]["valid"] is False
    assert validation.json["data"]["details"]["xsd"]["valid"] is False


def test_new_3d_template_renders_webresource_elements_in_schema_order(preview_app):
    app, _, template_id = preview_app
    data = _preview_data()
    with app.app_context():
        raw = app.edm_service.render_template(template_id, data["metadata"], data["zenodo"], main_file_key=data["main_file_key"])
        assert app.edm_service.validate_with_xsd(raw)["valid"] is True
    root = etree.fromstring(raw.encode())
    resource = root.xpath("//edm:WebResource[dc:type]", namespaces=app.edm_service.namespaces)[0]
    names = [etree.QName(child).localname for child in resource if isinstance(child.tag, str)]
    assert names == ["format", "type", "rights", "type"]


def test_preview_requires_authentication(preview_app):
    app, _, template_id = preview_app
    assert app.test_client().post("/templates/preview", json={**_preview_data(), "template_id": template_id}).status_code == 401
