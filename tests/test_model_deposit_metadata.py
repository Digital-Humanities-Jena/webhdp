import csv
import json
from unittest.mock import Mock
from urllib.parse import quote

import pytest
from lxml import etree
from openpyxl import Workbook
from rdflib import Graph, Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import DCTERMS

from database.database import db
from services.edm_service import EdmService
from services.iiif_service import IiifService
from services.linked_data_service import CRM
from services.mets_service import MetsService
from services.model_deposit_metadata import generate_deposit_metadata, read_deposit_metadata
from test_edm_service_minimum_viable import _build_generation_app

SOURCE = 'collection/Maßstab.obj'
FORM = {'title': 'Form fallback', 'description': 'The form description.', 'creator': 'Form, Creator'}


@pytest.mark.parametrize('suffix', ['.csv', '.xlsx'])
def test_msf_maps_aliases_and_preserves_creators_rights_and_object_date(tmp_path, suffix):
    path = tmp_path / f'Metadata{suffix}'
    rows = [
        ['File Name', 'dc:title', 'dc:description', 'dc:creator', 'Affiliation', 'dc:language', 'dc:rights', 'dcterms:created', 'dc:subject'],
        [SOURCE.replace('/', '\\'), 'Maßstab & Mörtel', 'Liegender <Stein>', 'Marín, José; Textile Archive', 'Museum; Textile Lab', 'DEU', 'cc0-1.0', '1868', '3D, heritage'],
        ['other/Maßstab.obj', 'Other item', '', '', '', '', '', '', ''],
    ]
    if suffix == '.csv':
        with path.open('w', newline='', encoding='utf-8-sig') as stream:
            csv.writer(stream, delimiter=';').writerows(rows)
    else:
        workbook = Workbook()
        workbook.active.title = 'Models'
        for row in rows:
            workbook.active.append(row)
        workbook.save(path)

    result = read_deposit_metadata(SOURCE, msf_path=path, form_metadata=FORM)
    zenodo = result['zenodo']
    assert zenodo['title'] == 'Maßstab & Mörtel'
    assert zenodo['description'] == 'Liegender &lt;Stein&gt;'
    assert zenodo['creators'] == [
        {'name': 'Marín, José', 'affiliation': 'Museum'},
        {'name': 'Textile Archive', 'affiliation': 'Textile Lab'},
    ]
    assert zenodo['language'] == 'deu'
    assert zenodo['license'] == 'cc0-1.0'
    assert zenodo['keywords'] == ['3D', 'heritage']
    assert zenodo['publication_date'] != '1868'
    assert 'cho_created' not in zenodo
    for export in result['formats'].values():
        assert export['cho_created'] == '1868'
        assert export['description'] == 'Liegender <Stein>'


@pytest.mark.parametrize(('csv_rows', 'error'), [
    ('one/other.obj', 'No metadata row'),
    ('elsewhere/Maßstab.obj', 'different model path'),
    ('collection/Maßstab.obj\ncollection/Maßstab.obj', 'Duplicate metadata row'),
    ('elsewhere/Maßstab.obj\nsecond/Maßstab.obj', 'Ambiguous metadata'),
])
def test_msf_does_not_guess_between_model_rows(tmp_path, csv_rows, error):
    path = tmp_path / 'metadata.csv'
    path.write_text('filename,title\n' + '\n'.join(f'{name},Candidate' for name in csv_rows.splitlines()), encoding='utf-8')
    with pytest.raises(ValueError, match=error):
        read_deposit_metadata(SOURCE, msf_path=path, form_metadata=FORM)


def test_form_keeps_commas_and_rejects_private_content():
    result = read_deposit_metadata(SOURCE, form_metadata=FORM)
    assert result['zenodo']['creators'] == [{'name': 'Form, Creator'}]
    assert result['zenodo']['upload_type'] == 'dataset'
    with pytest.raises(ValueError, match='private or credential'):
        read_deposit_metadata(SOURCE, form_metadata={**FORM, 'description': 'https://example.org/source?access_token=sentinel'})


@pytest.mark.parametrize('extension', ['.zip', '.glb'])
def test_all_exports_use_actual_sandbox_files_and_validate(tmp_path, extension):
    app = _build_generation_app(tmp_path)
    app.config['ENABLE_RENDERER'] = True
    app.edm_service = EdmService()
    app.iiif_service = IiifService()
    app.mets_service = MetsService()
    name = 'Maßstab & Mörtel' + extension
    draft = {'id': 6789, 'metadata': {'prereserve_doi': {'doi': '10.5072/zenodo.6789'}}}
    linked_name = 'preview.png'
    progress = Mock()
    with app.app_context():
        db.create_all()
        attachments = generate_deposit_metadata(
            tmp_path, draft=draft, metadata=read_deposit_metadata(SOURCE, form_metadata={**FORM, 'keywords': 'heritage, research'}),
            main_file_key=name, additional_files=[{'key': name, 'size': 500}, {'key': linked_name, 'size': 50}],
            progress=progress,
        )
    assert set(attachments) == {'edm', 'iiif', 'mets', 'cidoc_crm', 'jsonld'}
    assert set(attachments.values()) == {'edm.xml', 'iiif.json', 'mets.xml', 'cidoc-crm.xml', 'metadata.jsonld'}
    progress.assert_any_call(None, 5, 5)
    manifest = json.loads((tmp_path / 'lod-generation.json').read_text())
    assert all(entry['validation']['valid'] for entry in manifest['formats'].values())

    base = 'https://sandbox.zenodo.org/records/6789'
    content_url = f'https://sandbox.zenodo.org/api/records/6789/files/{quote(name, safe="")}/content'
    for standard in ('edm', 'mets'):
        output = (tmp_path / attachments[standard]).read_bytes()
        etree.fromstring(output)
        assert content_url.encode() in output
        assert f'/api/records/6789/files/{linked_name}/content'.encode() in output
    iiif = json.loads((tmp_path / attachments['iiif']).read_text())
    assert iiif['id'] == 'https://sandbox.zenodo.org/api/records/6789/files/iiif.json/content'
    assert iiif['rights'] == 'http://creativecommons.org/licenses/by/4.0/'
    assert iiif['metadata'] == [
        {'label': {'en': ['Creator']}, 'value': {'en': ['Form, Creator']}},
        {'label': {'en': ['Keywords']}, 'value': {'en': ['heritage, research']}},
    ]
    assert iiif['thumbnail'][0]['id'] == 'https://sandbox.zenodo.org/api/records/6789/files/preview.png/content'
    assert content_url in json.dumps(iiif)
    if extension == '.zip':
        assert iiif['items'][0]['rendering'][0]['format'] == 'application/zip'
    else:
        assert iiif['items'][0]['items'][0]['items'][0]['body'][0]['format'] == 'model/gltf-binary'

    rdf_xml = Graph().parse(tmp_path / attachments['cidoc_crm'], format='xml')
    jsonld = Graph().parse(tmp_path / attachments['jsonld'], format='json-ld')
    dataset = URIRef(base + '#dataset')
    assert isomorphic(rdf_xml, jsonld)
    assert (dataset, DCTERMS.isReferencedBy, URIRef(base)) in rdf_xml
    assert (dataset, DCTERMS.subject, Literal('heritage')) in rdf_xml
    assert set(rdf_xml.objects(dataset, CRM.P106_is_composed_of)) == {
        URIRef(f'{base}/files/{quote(asset, safe="")}') for asset in (name, linked_name)
    }
