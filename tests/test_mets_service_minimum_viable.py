from lxml import etree
import pytest

from services.mets_service import MetsService


def _sample_zenodo_record():
    return {
        "id": "443547",
        "metadata": {"publication_date": "2024-01-01", "creators": [{"name": "Example, Person"}],
                     "prereserve_doi": {"doi": "10.5072/zenodo.443547"}},
        "links": {"html": "https://sandbox.zenodo.org/records/443547"},
        "files": [
            {
                "key": "artifact.glb",
                "filename": "artifact.glb",
                "size": 1024,
            },
            {
                "key": "artifact_r000.png",
                "filename": "artifact_r000.png",
                "size": 256,
            },
        ],
    }


def test_minimum_viable_mets_repairs_sparse_document():
    service = MetsService()
    metadata = {
        "title": "Artifact",
        "publication_date": "2024-01-01",
        "license": "cc-by-4.0",
        "provider": "Zenodo",
    }
    sparse_xml = """<?xml version="1.0" encoding="UTF-8"?>
<mets:mets xmlns:mets="http://www.loc.gov/METS/"
           xmlns:mods="http://www.loc.gov/mods/v3"
           xmlns:xlink="http://www.w3.org/1999/xlink" />"""

    repaired = service._ensure_minimum_viable_mets(sparse_xml, metadata, _sample_zenodo_record())
    validation = service.validate_mets_xml(repaired)

    assert validation["valid"] is True
    assert validation["errors"] == []
    assert validation["details"]["xsd"]["valid"] is True

    root = etree.fromstring(repaired.encode("utf-8"))
    ns = service.namespaces
    assert root.get("OBJID")
    assert root.xpath("string(.//mods:titleInfo/mods:title)", namespaces=ns) == "Artifact"
    assert root.xpath("count(.//mets:file)", namespaces=ns) >= 1
    assert root.xpath("count(.//mets:structMap//mets:fptr)", namespaces=ns) >= 1
    assert root.xpath("string(.//mods:originInfo/mods:dateCreated)", namespaces=ns) == ""
    assert root.xpath("string(.//mods:originInfo/mods:dateIssued)", namespaces=ns) == "2024-01-01"
    assert not root.xpath(".//mets:file[@CHECKSUM]", namespaces=ns)
    assert not root.xpath(".//mets:file[@CHECKSUMTYPE]", namespaces=ns)


def test_minimum_viable_mets_keeps_object_creation_date_separate_from_publication_date():
    service = MetsService()
    metadata = {
        "title": "Artifact",
        "cho_created": "1969-01-01",
        "publication_date": "2024-01-01",
        "license": "cc-by-4.0",
        "provider": "Zenodo",
    }
    sparse_xml = """<?xml version="1.0" encoding="UTF-8"?>
<mets:mets xmlns:mets="http://www.loc.gov/METS/"
           xmlns:mods="http://www.loc.gov/mods/v3"
           xmlns:xlink="http://www.w3.org/1999/xlink" />"""

    repaired = service._ensure_minimum_viable_mets(sparse_xml, metadata, _sample_zenodo_record())
    root = etree.fromstring(repaired.encode("utf-8"))
    ns = service.namespaces

    assert root.xpath("string(.//mods:originInfo/mods:dateCreated)", namespaces=ns) == "1969-01-01"
    assert root.xpath("string(.//mods:originInfo/mods:dateIssued)", namespaces=ns) == "2024-01-01"
    assert root.xpath("string(.//mods:originInfo/mods:dateCreated/@encoding)", namespaces=ns) == "iso8601"


def test_minimum_viable_mets_does_not_mark_free_text_creation_dates_as_iso8601():
    service = MetsService()
    metadata = {
        "title": "Artifact",
        "cho_created": "3rd or 4th millennium BC",
        "publication_date": "2024-01-01",
        "license": "cc-by-4.0",
        "provider": "Zenodo",
    }
    sparse_xml = """<?xml version="1.0" encoding="UTF-8"?>
<mets:mets xmlns:mets="http://www.loc.gov/METS/"
           xmlns:mods="http://www.loc.gov/mods/v3"
           xmlns:xlink="http://www.w3.org/1999/xlink" />"""

    repaired = service._ensure_minimum_viable_mets(sparse_xml, metadata, _sample_zenodo_record())
    root = etree.fromstring(repaired.encode("utf-8"))
    ns = service.namespaces

    assert root.xpath("string(.//mods:originInfo/mods:dateCreated)", namespaces=ns) == "3rd or 4th millennium BC"
    assert root.xpath("string(.//mods:originInfo/mods:dateCreated/@encoding)", namespaces=ns) == ""


def test_minimum_viable_mets_omits_unknown_creation_dates():
    service = MetsService()
    metadata = {
        "title": "Artifact",
        "cho_created": "Unknown",
        "publication_date": "2024-01-01",
        "license": "cc-by-4.0",
        "provider": "Zenodo",
    }
    sparse_xml = """<?xml version="1.0" encoding="UTF-8"?>
<mets:mets xmlns:mets="http://www.loc.gov/METS/"
           xmlns:mods="http://www.loc.gov/mods/v3"
           xmlns:xlink="http://www.w3.org/1999/xlink" />"""

    repaired = service._ensure_minimum_viable_mets(sparse_xml, metadata, _sample_zenodo_record())
    root = etree.fromstring(repaired.encode("utf-8"))
    ns = service.namespaces

    assert root.xpath("string(.//mods:originInfo/mods:dateCreated)", namespaces=ns) == ""


def test_mets_validation_rejects_broken_file_reference():
    service = MetsService()
    invalid_xml = """<?xml version="1.0" encoding="UTF-8"?>
<mets:mets xmlns:mets="http://www.loc.gov/METS/"
           xmlns:mods="http://www.loc.gov/mods/v3"
           xmlns:xlink="http://www.w3.org/1999/xlink"
           OBJID="obj"
           LABEL="label">
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
      <mets:file ID="FILE_real" MIMETYPE="model/gltf-binary">
        <mets:FLocat LOCTYPE="URL" xlink:href="https://example.org/artifact.glb" />
      </mets:file>
    </mets:fileGrp>
  </mets:fileSec>
  <mets:structMap TYPE="LOGICAL">
    <mets:div DMDID="dmdSec_1" LABEL="Artifact">
      <mets:fptr FILEID="FILE_missing" />
    </mets:div>
  </mets:structMap>
</mets:mets>"""

    validation = service.validate_mets_xml(invalid_xml)
    assert validation["valid"] is False
    assert any("unknown FILEID" in error for error in validation["errors"])


def test_mets_validation_runs_xsd_checks():
    service = MetsService()
    invalid_xml = """<?xml version="1.0" encoding="UTF-8"?>
<mets:mets xmlns:mets="http://www.loc.gov/METS/"
           xmlns:mods="http://www.loc.gov/mods/v3"
           xmlns:xlink="http://www.w3.org/1999/xlink"
           OBJID="obj"
           LABEL="label">
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
      <mets:file ID="FILE_real" MIMETYPE="model/gltf-binary" CHECKSUM="abc" CHECKSUMTYPE="SHA999">
        <mets:FLocat LOCTYPE="URL" xlink:href="https://example.org/artifact.glb" />
      </mets:file>
    </mets:fileGrp>
  </mets:fileSec>
  <mets:structMap TYPE="LOGICAL">
    <mets:div DMDID="dmdSec_1" LABEL="Artifact">
      <mets:fptr FILEID="FILE_real" />
    </mets:div>
  </mets:structMap>
</mets:mets>"""

    validation = service.validate_mets_xml(invalid_xml)
    assert validation["valid"] is False
    assert validation["details"]["xsd"]["valid"] is False
    assert any("CHECKSUMTYPE" in error for error in validation["errors"])


@pytest.mark.parametrize("filename", ["offset torus.fbx", "模型 🏺 #1?.obj", "image #1?.jpg"])
def test_seeded_mets_handles_complex_filenames_and_self_preview(filename):
    from flask import Flask
    from database.database import db

    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI="sqlite:///:memory:", SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    with app.app_context():
        db.create_all()
        try:
            service = MetsService()
            record = _sample_zenodo_record()
            record["files"] = [{"filename": filename, "size": 1024}]
            if not filename.endswith(".jpg"):
                record["files"].append({"filename": filename.rsplit(".", 1)[0] + "_r000.png", "size": 256})
            content = service.generate_mets_xml(
                {"title": "Museum & Research", "publication_date": "2026-09-26", "license": "cc-by-4.0"},
                record,
                main_file_key=filename,
            )
            assert service.validate_mets_xml(content)["valid"]
            root = etree.fromstring(content.encode())
            ids = root.xpath(".//mets:file/@ID", namespaces=service.namespaces)
            assert len(ids) == len(set(ids)) == 2
            references = root.xpath(".//mets:fptr/@FILEID", namespaces=service.namespaces)
            assert set(references) == set(ids)
        finally:
            db.session.remove()
            db.drop_all()


def test_existing_mets_template_identifiers_are_upgraded_with_their_references():
    from flask import Flask
    from database.database import db
    from database.models import LodTemplate, LodStandard
    from database.seed_mets_mods_templates import METS_MODS_TEMPLATE

    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI="sqlite:///:memory:", SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    with app.app_context():
        db.create_all()
        try:
            legacy = METS_MODS_TEMPLATE
            for variable, role in [("main_file", "FILE"), ("thumb", "THUMB"), ("thumbnail_file", "THUMB")]:
                legacy = legacy.replace(
                    "{{ helpers.file_id(" + variable + ".filename, '" + role + "') }}",
                    "FILE_{{ " + variable + ".filename | replace('.', '_') }}",
                )
            template = LodTemplate(name="Existing METS", standard=LodStandard.METS, format="xml", content=legacy, is_default=True)
            db.session.add(template)
            db.session.commit()
            record = _sample_zenodo_record()
            record["files"] = [{"filename": "image with spaces.jpg", "size": 1024}]
            content = MetsService().generate_mets_xml(
                {"title": "Existing template", "publication_date": "2026-09-26", "license": "cc-by-4.0"}, record
            )
            assert MetsService().validate_mets_xml(content)["valid"]
            assert "helpers.file_id" in template.content
        finally:
            db.session.remove()
            db.drop_all()


def test_mets_file_ids_do_not_collide_when_punctuation_is_normalized():
    service = MetsService()
    assert service._safe_file_id("model a.png") != service._safe_file_id("model_a.png")
