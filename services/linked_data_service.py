"""Portable RDF exports for the digital record, without inferred object history.

CRM vocabulary: https://cidoc-crm.org/html/cidoc_crm_v7.1.3.html
The digital dataset is an E73 Information Object. Creators describe creation of
that dataset, not manufacture of the physical heritage object it may depict.
"""

import json
from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, RDF, RDFS

from services.edm_service import EdmService

CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")


def generate_linked_data(metadata, record, *, main_file_key, additional_files=None):
    """Serialize the same CIDOC-CRM graph as RDF/XML and JSON-LD."""
    edm = EdmService()
    record_url = edm.get_record_html_url(record)
    if not record.get("id") or not record_url.startswith("https://"):
        raise ValueError("Linked-data exports require a stable Zenodo record identifier")
    subject = URIRef(record_url + "#dataset")
    graph = Graph()
    graph.bind("crm", CRM)
    graph.bind("dcterms", DCTERMS)
    graph.bind("rdfs", RDFS)
    graph.add((subject, RDF.type, CRM.E73_Information_Object))
    graph.add((subject, DCTERMS.isReferencedBy, URIRef(record_url)))
    title = str(metadata.get("title") or main_file_key).strip()
    title_node = URIRef(record_url + "#title")
    graph.add((subject, CRM.P102_has_title, title_node))
    graph.add((title_node, RDF.type, CRM.E35_Title))
    graph.add((title_node, CRM.P190_has_symbolic_content, Literal(title)))
    graph.add((subject, RDFS.label, Literal(title)))
    if metadata.get("description"):
        graph.add((subject, CRM.P3_has_note, Literal(str(metadata["description"]))))
    doi = (record.get("metadata") or {}).get("prereserve_doi", {}).get("doi") or record.get("doi")
    if doi:
        graph.add((subject, DCTERMS.identifier, URIRef("https://doi.org/" + str(doi))))
    creators = metadata.get("creators") or []
    if isinstance(creators, list) and creators:
        creation = URIRef(record_url + "#creation")
        graph.add((creation, RDF.type, CRM.E65_Creation))
        graph.add((creation, CRM.P94_has_created, subject))
        for index, creator in enumerate(creators):
            name = creator.get("name") if isinstance(creator, dict) else str(creator)
            if not name:
                continue
            actor = URIRef(record_url + f"#creator-{index + 1}")
            graph.add((actor, RDF.type, CRM.E39_Actor))
            graph.add((actor, RDFS.label, Literal(name)))
            graph.add((creation, CRM.P14_carried_out_by, actor))
    files = edm._normalize_zenodo_files(record) + list(additional_files or [])
    if main_file_key and not any((f.get("key") or f.get("filename")) == main_file_key for f in files):
        files.append({"key": main_file_key})
    for file in files:
        name = file.get("key") or file.get("filename")
        if not name:
            continue
        # Never copy signed download links, local filesystem paths, or API tokens.
        asset = URIRef(record_url + "/files/" + quote(str(name), safe=""))
        graph.add((asset, RDF.type, CRM.E73_Information_Object))
        graph.add((asset, RDFS.label, Literal(str(name))))
        graph.add((subject, CRM.P106_is_composed_of, asset))
    xml = graph.serialize(format="xml")
    jsonld = graph.serialize(format="json-ld", context={
        "crm": str(CRM), "dcterms": str(DCTERMS), "rdfs": str(RDFS)
    }, auto_compact=True, indent=2)
    # Serialization is checked before artifacts become eligible for upload.
    Graph().parse(data=xml, format="xml")
    json.loads(jsonld)
    return {"cidoc_crm": ("cidoc-crm.xml", xml), "jsonld": ("metadata.jsonld", jsonld)}
