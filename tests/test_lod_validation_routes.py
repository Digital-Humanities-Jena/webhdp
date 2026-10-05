from types import SimpleNamespace
import pandas as pd
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from routes import edm_routes, iiif_routes, mets_routes, msf_routes, tools_routes
from routes.edm_routes import edm_bp
from routes.iiif_routes import iiif_bp
from routes.mets_routes import mets_bp
from routes.tools_routes import tools_bp
from services.cloud_upload_service import STORAGE_MODE_LOCAL


class _DummyProjectService:
    def _translate_path(self, path, to_container=True):
        return path


class _PreviewMsfService:
    def parse_msf_file_with_profile(self, msf_path, parse_options=None):
        frame = pd.DataFrame(
            [
                {
                    "filename": "artifact.glb",
                    "title": "Artifact",
                }
            ]
        )
        return frame, {"filename_column": "filename"}


class _PreviewEdmService:
    def generate_edm_xml_with_report(self, **kwargs):
        return {
            "content": """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:edm="http://www.europeana.eu/schemas/edm/"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:ore="http://www.openarchives.org/ore/terms/">
  <edm:ProvidedCHO rdf:about="#cho1"><dc:title>Artifact</dc:title></edm:ProvidedCHO>
  <ore:Aggregation rdf:about="#agg1"><edm:aggregatedCHO rdf:resource="#cho1"/></ore:Aggregation>
</rdf:RDF>""",
            "minimum_viable_applied": True,
            "validation": None,
        }

    def validate_edm_document(self, xml_string, metadata=None, include_remote=False):
        return {
            "valid": True,
            "errors": [],
            "warnings": ["Business warning"],
            "details": {
                "basic": {"valid": True, "errors": [], "warnings": []},
                "xsd": {"valid": True, "errors": [], "warnings": [], "skipped": True, "message": "Skipped"},
                "schematron": {"valid": True, "errors": [], "warnings": [], "skipped": True, "message": "Skipped"},
                "business": {"valid": True, "errors": [], "warnings": ["Business warning"]},
                "remote": None,
            },
        }


class _PreviewIiifService:
    def generate_iiif_manifest_with_report(self, **kwargs):
        return {
            "content": """{
  "@context": "http://iiif.io/api/presentation/3/context.json",
  "id": "https://example.org/manifest.json",
  "type": "Manifest",
  "label": {"en": ["Artifact"]},
  "items": [
    {
      "id": "https://example.org/canvas/1",
      "type": "Canvas",
      "items": [
        {
          "id": "https://example.org/page/1",
          "type": "AnnotationPage",
          "items": [
            {
              "id": "https://example.org/annotation/1",
              "type": "Annotation",
              "motivation": ["painting"],
              "body": {
                "type": "SpecificResource",
                "source": [
                  {
                    "id": "https://example.org/files/artifact.glb",
                    "type": "Model",
                    "format": "model/gltf-binary"
                  }
                ]
              },
              "target": {
                "type": "SpecificResource",
                "source": [
                  {
                    "id": "https://example.org/canvas/1",
                    "type": "Canvas"
                  }
                ]
              }
            }
          ]
        }
      ]
    }
  ]
}""",
            "minimum_viable_applied": False,
            "validation": None,
        }

    def validate_iiif_manifest(self, manifest_json):
        return {
            "valid": True,
            "errors": [],
            "warnings": ["Manifest has no thumbnail."],
            "details": {"canvas_count": 1},
        }


class _PreviewMetsService:
    def generate_mets_xml_with_report(self, **kwargs):
        return {
            "content": """<?xml version="1.0" encoding="UTF-8"?>
<mets:mets xmlns:mets="http://www.loc.gov/METS/"
           xmlns:mods="http://www.loc.gov/mods/v3"
           xmlns:xlink="http://www.w3.org/1999/xlink"
           OBJID="obj"
           LABEL="Artifact">
  <mets:metsHdr CREATEDATE="2024-01-01T00:00:00Z" />
  <mets:dmdSec ID="dmdSec_1">
    <mets:mdWrap MDTYPE="MODS">
      <mets:xmlData>
        <mods:mods>
          <mods:titleInfo><mods:title>Artifact</mods:title></mods:titleInfo>
        </mods:mods>
      </mets:xmlData>
    </mets:mdWrap>
  </mets:dmdSec>
  <mets:fileSec>
    <mets:fileGrp USE="ORIGINAL">
      <mets:file ID="FILE_artifact_glb" MIMETYPE="model/gltf-binary">
        <mets:FLocat LOCTYPE="URL" xlink:href="https://example.org/files/artifact.glb" />
      </mets:file>
    </mets:fileGrp>
  </mets:fileSec>
  <mets:structMap TYPE="LOGICAL">
    <mets:div DMDID="dmdSec_1" LABEL="Artifact">
      <mets:fptr FILEID="FILE_artifact_glb" />
    </mets:div>
  </mets:structMap>
</mets:mets>""",
            "minimum_viable_applied": True,
            "validation": None,
        }

    def validate_mets_xml(self, xml_string):
        return {
            "valid": True,
            "errors": [],
            "warnings": [],
            "details": {"file_count": 1},
        }


def _make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["JWT_SECRET_KEY"] = "test-jwt-secret"
    app.config["ENABLE_METIS_VALIDATION"] = False
    JWTManager(app)
    return app


def _make_token(app):
    with app.app_context():
        return create_access_token(identity="1")


def _auth_headers(app):
    return {"Authorization": f"Bearer {_make_token(app)}"}


def test_iiif_test_mapping_returns_validation_and_repair_flag(tmp_path, monkeypatch):
    app = _make_app()
    app.register_blueprint(iiif_bp, url_prefix="/api/v1/iiif")

    msf_path = tmp_path / "input.csv"
    msf_path.write_text("filename,title\nartifact.glb,Artifact\n", encoding="utf-8")

    monkeypatch.setattr(iiif_routes, "_resolve_authorized_session", lambda sid: (SimpleNamespace(id=1, session_dir=str(tmp_path), hdpc_path=""), None))
    monkeypatch.setattr(iiif_routes, "_get_session_msf_profile", lambda session: {})
    monkeypatch.setattr(iiif_routes.msf_service, "parse_msf_file_with_profile", lambda *args, **kwargs: (
        pd.DataFrame([{"filename": "artifact.glb", "title": "Artifact"}]),
        {"filename_column": "filename"},
    ))
    monkeypatch.setattr(
        iiif_routes,
        "build_pipeline_aligned_lod_metadata",
        lambda **kwargs: ({"title": "Artifact"}, {}) if kwargs.get("with_provenance") else {"title": "Artifact"},
    )
    monkeypatch.setattr(iiif_routes, "iiif_service", _PreviewIiifService())

    client = app.test_client()
    response = client.post(
        "/api/v1/iiif/test-mapping",
        headers=_auth_headers(app),
        json={"msf_path": str(msf_path), "row_index": 0},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["validation"]["valid"] is True
    assert payload["data"]["minimum_viable_applied"] is False


def test_mets_test_mapping_returns_validation_and_repair_flag(tmp_path, monkeypatch):
    app = _make_app()
    app.register_blueprint(mets_bp, url_prefix="/api/v1/mets")

    msf_path = tmp_path / "input.csv"
    msf_path.write_text("filename,title\nartifact.glb,Artifact\n", encoding="utf-8")

    monkeypatch.setattr(mets_routes, "_resolve_authorized_session", lambda sid: (SimpleNamespace(id=1, session_dir=str(tmp_path), hdpc_path=""), None))
    monkeypatch.setattr(mets_routes, "_get_session_msf_profile", lambda session: {})
    monkeypatch.setattr(mets_routes.msf_service, "parse_msf_file_with_profile", lambda *args, **kwargs: (
        pd.DataFrame([{"filename": "artifact.glb", "title": "Artifact"}]),
        {"filename_column": "filename"},
    ))
    monkeypatch.setattr(
        mets_routes,
        "build_pipeline_aligned_lod_metadata",
        lambda **kwargs: ({"title": "Artifact"}, {}) if kwargs.get("with_provenance") else {"title": "Artifact"},
    )
    monkeypatch.setattr(mets_routes, "mets_service", _PreviewMetsService())

    client = app.test_client()
    response = client.post(
        "/api/v1/mets/test-mapping",
        headers=_auth_headers(app),
        json={"msf_path": str(msf_path), "row_index": 0},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["validation"]["valid"] is True
    assert payload["data"]["minimum_viable_applied"] is True


def test_edm_test_mapping_returns_validation_and_repair_flag(tmp_path, monkeypatch):
    app = _make_app()
    app.register_blueprint(edm_bp, url_prefix="/api/v1/edm")

    msf_path = tmp_path / "input.csv"
    msf_path.write_text("filename,title\nartifact.glb,Artifact\n", encoding="utf-8")

    monkeypatch.setattr(edm_routes, "_resolve_authorized_session", lambda sid: (SimpleNamespace(id=1, session_dir=str(tmp_path), hdpc_path=""), None))
    monkeypatch.setattr(edm_routes, "_get_session_msf_profile", lambda session: {})
    monkeypatch.setattr(edm_routes.msf_service, "parse_msf_file_with_profile", lambda *args, **kwargs: (
        pd.DataFrame([{"filename": "artifact.glb", "title": "Artifact"}]),
        {"filename_column": "filename"},
    ))
    monkeypatch.setattr(
        edm_routes,
        "build_pipeline_aligned_lod_metadata",
        lambda **kwargs: ({"title": "Artifact"}, {}) if kwargs.get("with_provenance") else {"title": "Artifact"},
    )
    monkeypatch.setattr(edm_routes, "edm_service", _PreviewEdmService())

    client = app.test_client()
    response = client.post(
        "/api/v1/edm/test-mapping",
        headers=_auth_headers(app),
        json={"msf_path": str(msf_path), "row_index": 0, "template_id": 1},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["validation"]["valid"] is True
    assert payload["data"]["minimum_viable_applied"] is True


def test_output_preview_local_returns_structured_validation_sections(tmp_path, monkeypatch):
    app = _make_app()
    app.config["LOCAL_INPUT_PATH"] = str(tmp_path / "local_input")
    app.project_service = _DummyProjectService()
    app.msf_service = _PreviewMsfService()
    app.edm_service = _PreviewEdmService()
    app.iiif_service = _PreviewIiifService()
    app.mets_service = _PreviewMetsService()
    app.register_blueprint(tools_bp, url_prefix="/api/v1/tools")

    input_root = tmp_path / "local_input"
    input_root.mkdir(parents=True)
    (input_root / "artifact.glb").write_bytes(b"glb")
    msf_path = input_root / "input.csv"
    msf_path.write_text("filename,title\nartifact.glb,Artifact\n", encoding="utf-8")

    monkeypatch.setattr(msf_routes, "_is_admin_request_user", lambda: True)
    monkeypatch.setattr(
        msf_routes.CloudUploadService,
        "get_storage_mode",
        staticmethod(lambda: STORAGE_MODE_LOCAL),
    )
    monkeypatch.setattr(
        tools_routes,
        "build_pipeline_aligned_lod_metadata",
        lambda **kwargs: ({"title": "Artifact"}, {}) if kwargs.get("with_provenance") else {"title": "Artifact"},
    )

    client = app.test_client()
    response = client.post(
        "/api/v1/tools/output-preview/local",
        headers=_auth_headers(app),
        json={"msf_path": str(msf_path), "row_index": 0, "targets": ["edm", "iiif", "mets"]},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True

    edm_output = payload["data"]["outputs"]["edm"]
    assert edm_output["minimum_viable_applied"] is True
    assert edm_output["validation"]["summary"]["validation_scope"] == "local"
    assert edm_output["validation"]["sections"][0]["label"] == "Basic XML"

    iiif_output = payload["data"]["outputs"]["iiif"]
    assert iiif_output["minimum_viable_applied"] is False
    assert iiif_output["validation"]["sections"][0]["label"] == "IIIF"

    mets_output = payload["data"]["outputs"]["mets"]
    assert mets_output["minimum_viable_applied"] is True
    assert mets_output["validation"]["summary"]["error_count"] == 0
