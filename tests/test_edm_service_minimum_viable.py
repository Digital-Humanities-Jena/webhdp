from lxml import etree
from flask import Flask
import pytest

from database.database import db, init_db
from database.lod_template_bootstrap import ensure_default_lod_templates
from services.edm_service import EDM_SCHEMA_VERSION, EdmService


def _parse(xml_text: str):
    return etree.fromstring(xml_text.encode("utf-8"))


def _build_generation_app(tmp_path):
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'edm-generation.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        ENABLE_LOCAL_EDM_VALIDATION=False,
        ENABLE_METIS_VALIDATION=False,
        LOCAL_EDM_VALIDATOR_REQUIRED=False,
        ENABLE_RENDERER=False,
        ZENODO_SANDBOX_MODE=False,
    )
    init_db(app)
    return app


def test_normalize_controlled_vocab_helpers_map_to_valid_uris():
    service = EdmService()

    assert (
        service.normalize_intended_usage_uri("Research")
        == "http://data.europeana.eu/vocabulary/usageArea/Research"
    )
    assert (
        service.normalize_digital_source_type_uri("3D reconstruction")
        == "https://cv.iptc.org/newscodes/digitalsourcetype/dataDrivenMedia"
    )
    assert service.iso_date("1969.0") == "1969-01-01"


def test_generate_uri_without_identifier_uses_initialized_counter():
    service = EdmService()

    assert service.generate_uri("agent") == "#agent1"
    assert service.generate_uri("agent") == "#agent2"


def test_3d_model_type_mapping_accepts_component_model_type_output():
    service = EdmService()

    assert (
        service.map_3d_type({"model_type": "point_cloud"})
        == "http://data.europeana.eu/vocabulary/modelType/3DPointCloud"
    )
    assert (
        service.map_3d_type({"model_type": "mesh", "point_count": 100})
        == "http://data.europeana.eu/vocabulary/modelType/3DMesh"
    )
    assert (
        service.map_3d_type({"point_count": "0"})
        == "http://data.europeana.eu/vocabulary/modelType/3DMesh"
    )
    assert (
        service.map_3d_type({"point_count": "12,345"})
        == "http://data.europeana.eu/vocabulary/modelType/3DPointCloud"
    )


def test_edm_validation_rejects_schema_invalid_edm_type():
    service = EdmService()
    input_xml = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:edm="http://www.europeana.eu/schemas/edm/"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:ore="http://www.openarchives.org/ore/terms/">
  <edm:ProvidedCHO rdf:about="#cho1">
    <dc:title>Sample</dc:title>
    <edm:type>DOCUMENT</edm:type>
  </edm:ProvidedCHO>
  <ore:Aggregation rdf:about="#agg1">
    <edm:aggregatedCHO rdf:resource="#cho1"/>
    <edm:rights rdf:resource="http://creativecommons.org/licenses/by/4.0/"/>
  </ore:Aggregation>
</rdf:RDF>"""

    result = service.validate_edm_document(input_xml, include_remote=False)

    assert result["valid"] is False
    assert any("Invalid edm:type value 'DOCUMENT'" in error for error in result["errors"])


def test_license_mapping_accepts_common_public_domain_identifiers(tmp_path):
    app = _build_generation_app(tmp_path)
    with app.app_context():
        db.create_all()
        service = EdmService()

        assert service._map_license_to_uri("CC0-1.0") == "http://creativecommons.org/publicdomain/zero/1.0/"
        assert service._map_license_to_uri("Public Domain Mark") == "http://creativecommons.org/publicdomain/mark/1.0/"


@pytest.mark.parametrize("emit_advisory_fields", [False, True])
def test_generation_without_main_file_key_handles_string_resource_type_and_keeps_3d_schema(tmp_path, emit_advisory_fields):
    app = _build_generation_app(tmp_path)
    app.config["EMIT_EUROPEANA_3D_ADVISORY_FIELDS"] = emit_advisory_fields
    with app.app_context():
        db.create_all()
        ensure_default_lod_templates()
        service = EdmService()

        generation = service.generate_edm_xml_with_report(
            metadata={
                "title": "Sample 3D Artifact",
                "description": "A richly described 3D artifact record used for generation smoke testing.",
                "creators": [{"name": "Ada Lovelace"}],
                "language": "en",
                "country": "EU",
                "license": "cc-by-4.0",
                "upload_type": "dataset",
                "resource_type": "3D Model",
                "digital_source_type": "3D reconstruction",
                "intended_usage": "Research",
                "vertex_count": "1234",
                "polygon_count": "567",
            },
            zenodo_record={
                "id": "12345",
                "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.12345"}},
                "links": {"html": "https://zenodo.org/deposit/12345"},
                "files": [
                    {"key": "model.glb", "filename": "model.glb", "size": 1000},
                    {"key": "model_r029.png", "filename": "model_r029.png", "size": 500},
                ],
            },
            validate=False,
        )
        doc = _parse(generation["content"])
        ns = {
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
            "edm": "http://www.europeana.eu/schemas/edm/",
            "dc": "http://purl.org/dc/elements/1.1/",
            "schema": "https://schema.org/",
        }

        assert doc.xpath("//edm:ProvidedCHO/edm:type[text()='3D']", namespaces=ns)
        assert doc.xpath("//edm:WebResource/edm:type[text()='3D']", namespaces=ns)
        assert doc.xpath(
            "//edm:WebResource/dc:type[@rdf:resource='http://data.europeana.eu/vocabulary/modelType/3DMesh']",
            namespaces=ns,
        )
        for field in ("schema:digitalSourceType", "edm:intendedUsage", "edm:polygonCount", "edm:vertexCount"):
            assert bool(doc.xpath(f"//edm:WebResource/{field}", namespaces=ns)) is emit_advisory_fields
        report = service.validate_edm_document(generation["content"], include_remote=False)
        assert report["valid"] is True, report["errors"]
        assert report["details"]["xsd"]["schema_version"] == EDM_SCHEMA_VERSION


def test_document_generation_uses_text_edm_type(tmp_path):
    app = _build_generation_app(tmp_path)
    with app.app_context():
        db.create_all()
        ensure_default_lod_templates()
        service = EdmService()

        generation = service.generate_edm_xml_with_report(
            metadata={
                "title": "Report",
                "description": "A sufficiently long report description for the generation smoke test.",
                "creators": [{"name": "Author"}],
                "language": "en",
                "license": "cc-by-4.0",
                "upload_type": "publication",
            },
            zenodo_record={
                "id": "55",
                "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.55"}},
                "links": {"html": "https://zenodo.org/records/55"},
                "files": [{"key": "report.pdf", "filename": "report.pdf", "size": 99}],
            },
            main_file_key="report.pdf",
            validate=False,
        )
        doc = _parse(generation["content"])
        ns = {"edm": "http://www.europeana.eu/schemas/edm/"}

        assert [node.text for node in doc.xpath("//edm:ProvidedCHO/edm:type", namespaces=ns)] == ["TEXT"]
        assert service.validate_edm_document(generation["content"], include_remote=False)["valid"] is True


def test_minimum_viable_edm_injects_required_baseline_fields():
    service = EdmService()
    input_xml = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:edm="http://www.europeana.eu/schemas/edm/"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:ore="http://www.openarchives.org/ore/terms/"
         xmlns:schema="https://schema.org/">
  <edm:ProvidedCHO rdf:about="#cho1">
    <dc:title>Sample</dc:title>
  </edm:ProvidedCHO>
  <edm:WebResource rdf:about="https://example.org/object">
    <schema:digitalSourceType rdf:resource="3D reconstruction"/>
    <edm:intendedUsage rdf:resource="Research"/>
  </edm:WebResource>
  <ore:Aggregation rdf:about="#agg1">
    <edm:aggregatedCHO rdf:resource="#cho1"/>
  </ore:Aggregation>
</rdf:RDF>"""

    repaired = service._ensure_minimum_viable_edm(input_xml, {"license": "cc-by-4.0"})
    doc = _parse(repaired)
    ns = {
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "edm": "http://www.europeana.eu/schemas/edm/",
        "dc": "http://purl.org/dc/elements/1.1/",
        "ore": "http://www.openarchives.org/ore/terms/",
        "schema": "https://schema.org/",
    }

    dc_types = doc.xpath("//edm:ProvidedCHO/dc:type", namespaces=ns)
    assert dc_types
    assert (dc_types[0].text or "").strip() != ""

    assert not doc.xpath("//edm:WebResource/edm:intendedUsage", namespaces=ns)
    assert not doc.xpath("//edm:WebResource/schema:digitalSourceType", namespaces=ns)
    rights = doc.xpath("string(//ore:Aggregation/edm:rights/@rdf:resource)", namespaces=ns)
    assert rights != ""


def test_minimum_viable_edm_reorders_webresource_and_providedcho_for_schema_compliance():
    service = EdmService()
    input_xml = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:edm="http://www.europeana.eu/schemas/edm/"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:ore="http://www.openarchives.org/ore/terms/"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:schema="https://schema.org/">
  <edm:ProvidedCHO rdf:about="#cho1">
    <owl:sameAs rdf:resource="https://example.org/cho1"/>
    <dc:title>Sample</dc:title>
    <edm:type>3D</edm:type>
  </edm:ProvidedCHO>
  <edm:WebResource rdf:about="https://example.org/object">
    <edm:intendedUsage rdf:resource="Research"/>
    <schema:digitalSourceType rdf:resource="3D reconstruction"/>
    <edm:type>3D</edm:type>
    <dc:type rdf:resource="http://data.europeana.eu/vocabulary/modelType/3DMesh"/>
    <dc:format>model/obj</dc:format>
  </edm:WebResource>
  <ore:Aggregation rdf:about="#agg1">
    <edm:aggregatedCHO rdf:resource="#cho1"/>
    <edm:rights rdf:resource="http://creativecommons.org/licenses/by/4.0/"/>
  </ore:Aggregation>
</rdf:RDF>"""

    repaired = service._ensure_minimum_viable_edm(input_xml, {"license": "cc-by-4.0"})
    doc = _parse(repaired)
    ns = {
        "edm": "http://www.europeana.eu/schemas/edm/",
        "dc": "http://purl.org/dc/elements/1.1/",
        "schema": "https://schema.org/",
        "owl": "http://www.w3.org/2002/07/owl#",
    }

    cho = doc.xpath("//edm:ProvidedCHO", namespaces=ns)[0]
    cho_children = [node.tag for node in list(cho) if isinstance(node.tag, str)]
    assert cho_children.index("{http://purl.org/dc/elements/1.1/}title") < cho_children.index(
        "{http://www.europeana.eu/schemas/edm/}type"
    )
    assert cho_children.index("{http://www.europeana.eu/schemas/edm/}type") < cho_children.index(
        "{http://www.w3.org/2002/07/owl#}sameAs"
    )

    web = doc.xpath("//edm:WebResource", namespaces=ns)[0]
    web_children = [node.tag for node in list(web) if isinstance(node.tag, str)]
    assert web_children.index("{http://purl.org/dc/elements/1.1/}format") < web_children.index(
        "{http://purl.org/dc/elements/1.1/}type"
    )
    assert web_children.index("{http://purl.org/dc/elements/1.1/}type") < web_children.index(
        "{http://www.europeana.eu/schemas/edm/}type"
    )
    assert "{https://schema.org/}digitalSourceType" not in web_children
    assert "{http://www.europeana.eu/schemas/edm/}intendedUsage" not in web_children


def test_minimum_viable_edm_removes_deferred_3drepo_viewer_and_keeps_direct_3d_webresource():
    service = EdmService()
    input_xml = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:edm="http://www.europeana.eu/schemas/edm/"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:ore="http://www.openarchives.org/ore/terms/"
         xmlns:svcs="http://rdfs.org/sioc/services#">
  <edm:ProvidedCHO rdf:about="https://doi.org/10.5281/zenodo.443547">
    <dc:title>{{ no such element: services.edm_service.DotDict object['title'] }}</dc:title>
  </edm:ProvidedCHO>
  <edm:WebResource rdf:about="https://3drepo.eu/modelviewer.html?https%3A%2F%2Fsandbox.zenodo.org%2Fapi%2Frecords%2F443547%2Ffiles%2F0021_FLI_PL_low_poly_FIN.glb%2Fcontent">
    <dc:format>model/gltf-binary</dc:format>
  </edm:WebResource>
  <edm:WebResource rdf:about="https://sandbox.zenodo.org/api/records/443547/files/0021_FLI_PL_low_poly_FIN_r000.png/content">
    <dc:format>image/jpeg</dc:format>
  </edm:WebResource>
  <ore:Aggregation rdf:about="https://doi.org/10.5281/zenodo.443547#aggregation">
    <edm:aggregatedCHO rdf:resource="https://doi.org/10.5281/zenodo.443547"/>
    <edm:isShownBy rdf:resource="https://3drepo.eu/modelviewer.html?https%3A%2F%2Fsandbox.zenodo.org%2Fapi%2Frecords%2F443547%2Ffiles%2F0021_FLI_PL_low_poly_FIN.glb%2Fcontent"/>
    <edm:hasView rdf:resource="https://sandbox.zenodo.org/api/records/443547/files/0021_FLI_PL_low_poly_FIN.glb/content"/>
    <edm:hasView rdf:resource="https://sandbox.zenodo.org/api/records/443547/files/0021_FLI_PL_low_poly_FIN_r000.png/content"/>
    <edm:object rdf:resource="https://sandbox.zenodo.org/api/records/443547/files/0021_FLI_PL_low_poly_FIN_r000.png/content"/>
  </ore:Aggregation>
</rdf:RDF>"""

    repaired = service._ensure_minimum_viable_edm(
        input_xml,
        {
            "license": "cc-by-4.0",
            "title": "Chocolate' flint : 3D documentation",
            "edm_type_override": "3D",
            "digital_source_type": "digitisation",
            "intended_usage": "Research",
        },
    )
    doc = _parse(repaired)
    ns = {
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "edm": "http://www.europeana.eu/schemas/edm/",
        "dc": "http://purl.org/dc/elements/1.1/",
        "dcterms": "http://purl.org/dc/terms/",
        "ore": "http://www.openarchives.org/ore/terms/",
        "schema": "https://schema.org/",
        "svcs": "http://rdfs.org/sioc/services#",
    }

    assert not doc.xpath(
        "//ore:Aggregation/edm:isShownBy[contains(@rdf:resource,'3drepo.eu/modelviewer')]",
        namespaces=ns,
    )
    assert not doc.xpath(
        "//edm:WebResource[contains(@rdf:about,'3drepo.eu/modelviewer')]",
        namespaces=ns,
    )
    assert not doc.xpath("//svcs:Service", namespaces=ns)

    assert doc.xpath(
        "//edm:WebResource[@rdf:about='https://sandbox.zenodo.org/api/records/443547/files/0021_FLI_PL_low_poly_FIN.glb/content']",
        namespaces=ns,
    )
    assert doc.xpath(
        "//edm:WebResource[@rdf:about='https://sandbox.zenodo.org/api/records/443547/files/0021_FLI_PL_low_poly_FIN.glb/content']/dc:type[@rdf:resource]",
        namespaces=ns,
    )
    assert doc.xpath(
        "//edm:WebResource[@rdf:about='https://sandbox.zenodo.org/api/records/443547/files/0021_FLI_PL_low_poly_FIN.glb/content']/edm:type[text()='3D']",
        namespaces=ns,
    )

    assert (
        doc.xpath(
            "string(//edm:WebResource[@rdf:about='https://sandbox.zenodo.org/api/records/443547/files/0021_FLI_PL_low_poly_FIN_r000.png/content']/dc:format)",
            namespaces=ns,
        )
        == "image/png"
    )


def test_all_bundled_templates_pass_real_edm_xsd(tmp_path):
    from database.models import LodTemplate
    app = _build_generation_app(tmp_path)
    with app.app_context():
        db.create_all()
        ensure_default_lod_templates()
        service = EdmService()
        for template in LodTemplate.query.filter_by(standard="edm").all():
            generation = service.generate_edm_xml_with_report(
                metadata={"title": "Heritage object & context", "description": "A documented heritage object used to validate the bundled metadata templates.",
                          "creators": [{"name": "Example, Researcher", "affiliation": "Museum"}],
                          "license": "cc-by-4.0", "upload_type": "dataset", "publication_date": "2026-09-26"},
                zenodo_record={"id": 123, "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.123"}},
                               "links": {"html": "https://zenodo.org/records/123"},
                               "files": [{"key": "object.glb", "size": 1000}, {"key": "object_r000.png", "size": 100}]},
                template_id=template.id, main_file_key="object.glb", validate=False,
            )
            result = service.validate_with_xsd(generation["content"])
            assert result["valid"], (template.name, result["errors"])
            assert result["skipped"] is False


def test_xsd_validation_rejects_well_formed_but_unknown_elements():
    result = EdmService().validate_with_xsd('<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><unknown/></rdf:RDF>')
    assert result["valid"] is False
    assert result["errors"]
