import json

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import RDF, RDFS

from services.linked_data_service import CRM, generate_linked_data


@pytest.mark.parametrize("host", ["zenodo.org", "sandbox.zenodo.org"])
def test_exports_preserve_graph_unicode_creators_and_file_names(host):
    record = {"id": 123, "links": {"html": f"https://{host}/deposit/123"}}
    outputs = generate_linked_data(
        {"title": "Gefäß & <object>", "description": "Überlieferung", "creators": [{"name": "Example, Researcher"}]},
        record, main_file_key="模型 one.glb", additional_files=[{"key": "thumbnail.png"}],
    )
    xml = Graph().parse(data=outputs["cidoc_crm"][1], format="xml")
    ld = Graph().parse(data=outputs["jsonld"][1], format="json-ld")
    assert isomorphic(xml, ld)
    subject = URIRef(f"https://{host}/records/123#dataset")
    assert (subject, RDF.type, CRM.E73_Information_Object) in xml
    assert (subject, RDFS.label, Literal("Gefäß & <object>")) in xml
    assert len(list(xml.objects(subject, CRM.P106_is_composed_of))) == 2
    assert len(list(xml.subjects(RDF.type, CRM.E65_Creation))) == 1
    assert "@context" in json.loads(outputs["jsonld"][1])


def test_export_does_not_copy_private_download_links_or_invent_creators():
    outputs = generate_linked_data({}, {
        "id": 123, "files": [{"filename": "object.glb", "links": {"download": "https://zenodo.org/private?access_token=secret"}}]
    }, main_file_key="object.glb")
    xml = outputs["cidoc_crm"][1]
    assert "secret" not in xml
    assert "access_token" not in xml
    graph = Graph().parse(data=xml, format="xml")
    assert not list(graph.subjects(RDF.type, CRM.E65_Creation))


def test_missing_record_identity_is_rejected():
    with pytest.raises(ValueError, match="identifier"):
        generate_linked_data({}, {}, main_file_key="object.glb")
