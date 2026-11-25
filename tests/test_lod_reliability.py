import json
from unittest.mock import Mock

import pytest
from flask import Flask

from services.edm_service import EDM_SCHEMA_VERSION, EdmService
from services.lod_reliability import MetadataRows, assert_public_document, atomic_write, digest, public_url
from services.lod_artifact_service import generate_artifacts
from services.linked_data_service import generate_linked_data, validate_linked_data


@pytest.mark.parametrize('report', [None, [], {}, {'validationResults': []}, {'validationResults': [None]}, {'validationResults': [{'status': 'UNKNOWN'}]}, {'validationResults': [{'status': 'SKIPPED'}]}, {'validationResults': [{'status': 'PASSED'}, {'status': 'FAILED'}]}])
def test_incomplete_validation_never_passes(report):
    assert EdmService()._normalize_local_validator_report(report)['valid'] is False


def test_explicit_validation_pass_and_unicode_identifiers():
    service = EdmService()
    assert service._normalize_local_validator_report({'validationResults': [{'step': step, 'status': 'PASSED'} for step in ('VALIDATE_EXTERNAL', 'VALIDATE_INTERNAL')]})['valid'] is True
    assert len({service.generate_uri('agent', name) for name in ['Müller', 'Möller', '王', '李', 'ABC', 'abc']}) == 6
    assert service.generate_uri('agent', 'é') == service.generate_uri('agent', 'e\u0301')


@pytest.mark.parametrize('url', ['https://zenodo.org/records/123?access_token=REVIEW_SENTINEL', 'https://user:REVIEW_SENTINEL@zenodo.org/records/123', 'file:///private/document', 'https://assets.example/a?X-Amz-Signature=REVIEW_SENTINEL'])
def test_private_urls_never_enter_public_outputs(url):
    assert not public_url(url)
    with pytest.raises(ValueError, match='private or credential'):
        assert_public_document(f'<a href="{url}">file</a>')
    service = EdmService()
    assert service.get_record_html_url({'id': 123, 'links': {'html': url}}) == 'https://zenodo.org/records/123'
    assert 'REVIEW_SENTINEL' not in service.get_file_content_url({'key': 'model.glb', 'links': {'content': url}}, '123', is_sandbox=False)


def test_relative_path_matching_rejects_ambiguous_basenames():
    rows = MetadataRows([('left/model.glb', {'title': 'Left'}), ('right/model.glb', {'title': 'Right'})], ['left/model.glb', 'right/model.glb'])
    assert rows.get('left/model.glb')['title'] == 'Left'
    with pytest.raises(ValueError, match='Ambiguous'):
        rows.get('model.glb')
    with pytest.raises(ValueError, match='Duplicate'):
        MetadataRows([('é.glb', {}), ('e\u0301.glb', {})], [])
    rows = MetadataRows([('model.glb', {})], ['left/model.glb', 'right/model.glb'])
    with pytest.raises(ValueError, match='Ambiguous'):
        rows.get('left/model.glb')


def test_case_sensitive_exact_match_and_unique_case_fallback():
    rows = MetadataRows([('A.glb', 1), ('a.glb', 2)], ['A.glb', 'a.glb'])
    assert rows.get('A.glb') == 1
    assert rows.get('a.glb') == 2
    assert MetadataRows([('nested/é.glb', 3)], ['nested/é.glb']).get('NESTED/e\u0301.GLB') == 3


def test_atomic_write_preserves_original_on_replace_failure(tmp_path, monkeypatch):
    path = tmp_path / 'edm.xml'
    path.write_text('previous')
    monkeypatch.setattr('services.lod_reliability.os.replace', Mock(side_effect=OSError('disk full')))
    with pytest.raises(OSError):
        atomic_write(str(path), 'replacement')
    assert path.read_text() == 'previous'
    assert list(tmp_path.iterdir()) == [path]


def specification():
    return {'options': {}, 'record': {'id': 123}, 'main_file_key': '模型.glb', 'additional_files': [], 'allow_placeholder_thumbnail': False,
            'metadata': {key: {'title': 'Museum object', 'creators': [{'name': 'Müller'}]} for key in ('edm', 'iiif', 'mets', 'cidoc_crm', 'jsonld')}}


def services_app():
    app = Flask(__name__)
    app.config['ENABLE_LOCAL_EDM_VALIDATION'] = False
    app.edm_service = Mock()
    app.edm_service.generate_edm_xml_with_report.return_value = {'content': '<rdf/>', 'minimum_viable_applied': False}
    app.edm_service.validate_edm_document.return_value = {'valid': False, 'errors': ['invalid EDM']}
    app.iiif_service = Mock()
    app.iiif_service.generate_iiif_manifest_with_report.return_value = {'content': '{}', 'validation': {'valid': True}}
    app.mets_service = Mock()
    app.mets_service.generate_mets_xml_with_report.return_value = {'content': '<mets/>', 'validation': {'valid': True}}
    return app


def test_failed_format_is_not_registered_and_retry_reuses_successes(tmp_path):
    app = services_app()
    register = Mock()
    with app.app_context():
        outputs, manifest = generate_artifacts(str(tmp_path), specification(), register)
        assert 'edm' not in outputs
        assert set(outputs) == {'iiif', 'mets', 'cidoc_crm', 'jsonld'}
        assert not (tmp_path / 'edm.xml').exists()
        assert manifest['formats']['edm']['validation']['valid'] is False
        assert register.call_count == 4
        app.edm_service.validate_edm_document.return_value = {'valid': True}
        outputs, manifest = generate_artifacts(str(tmp_path), specification(), register)
        assert len(outputs) == 5
        assert manifest['formats']['iiif']['reused'] is True
        assert app.iiif_service.generate_iiif_manifest_with_report.call_count == 1
        assert app.edm_service.generate_edm_xml_with_report.call_count == 2
        assert manifest['formats']['edm']['sha256'] == digest((tmp_path / 'edm.xml').read_bytes())
        (tmp_path / 'iiif.json').write_text('tampered')
        generate_artifacts(str(tmp_path), specification(), register)
        assert app.iiif_service.generate_iiif_manifest_with_report.call_count == 2
        assert not any(call.args[0].endswith('lod-generation.json') for call in register.call_args_list)


def test_changed_settings_regenerate_outputs_and_missing_valid_is_rejected(tmp_path):
    app = services_app()
    spec = specification()
    with app.app_context():
        generate_artifacts(str(tmp_path), spec, Mock())
        spec['metadata']['iiif']['title'] = 'Revised'
        app.iiif_service.generate_iiif_manifest_with_report.return_value['validation'] = {'warnings': []}
        outputs, manifest = generate_artifacts(str(tmp_path), spec, Mock())
    assert 'iiif' not in outputs
    assert manifest['formats']['iiif']['success'] is False


def test_edm_retry_revalidates_older_schema_without_regenerating_other_formats(tmp_path):
    app = services_app()
    spec = specification()
    register = Mock()
    with app.app_context():
        app.edm_service.validate_edm_document.return_value = {'valid': True}
        generate_artifacts(str(tmp_path), spec, register)
        app.edm_service.validate_edm_document.return_value = {
            'valid': True, 'details': {'xsd': {'schema_version': EDM_SCHEMA_VERSION}},
        }
        _, updated = generate_artifacts(str(tmp_path), spec, register)
        _, retried = generate_artifacts(str(tmp_path), spec, register)
    assert not updated['formats']['edm'].get('reused')
    assert updated['formats']['iiif']['reused'] is True
    assert retried['formats']['edm']['reused'] is True
    assert app.edm_service.validate_edm_document.call_count == 2


def test_graph_validation_rejects_missing_relationships_and_remote_context():
    outputs = generate_linked_data({'title': 'Object'}, {'id': 123}, main_file_key='file.glb')
    for standard, (_, content) in outputs.items():
        assert validate_linked_data(content, standard)['valid'] is True
    assert validate_linked_data('{"@context":"https://example.org/context"}', 'jsonld')['valid'] is False
    assert validate_linked_data('<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/>', 'cidoc_crm')['valid'] is False


def test_pinned_templates_survive_edits_and_explicit_edm_choice_is_not_replaced(tmp_path):
    from test_edm_service_minimum_viable import _build_generation_app
    from database.database import db
    from database.models import LodTemplate
    from services.lod_reliability import snapshot_templates, pinned_templates, resolve_template
    from database.lod_template_bootstrap import ensure_default_lod_templates
    app = _build_generation_app(tmp_path)
    with app.app_context():
        db.create_all()
        ensure_default_lod_templates()
        source = LodTemplate.query.filter_by(standard='edm').first()
        selected = LodTemplate(name='Chosen museum template', standard='edm', content=source.content.replace('</rdf:RDF>', '<!-- chosen-template -->\n</rdf:RDF>'), is_default=False)
        db.session.add(selected)
        db.session.commit()
        snapshot = snapshot_templates({'edm_template_id': selected.id})
        selected.content = selected.content.replace('chosen-template', 'later-edit')
        db.session.commit()
        with pinned_templates(snapshot):
            rendered = EdmService().render_template(selected.id, {'title': 'Artifact', 'creators': [{'name': 'Museum'}]}, {'id': 123, 'files': [{'key': 'model.glb'}]}, main_file_key='model.glb')
            assert 'chosen-template' in rendered
            assert 'later-edit' not in rendered
            assert resolve_template('edm').id == selected.id
        assert 'later-edit' in resolve_template('edm', selected.id).content
        with pytest.raises(ValueError, match='IIIF'):
            resolve_template('iiif', selected.id)


@pytest.mark.parametrize('source_name', ['模型.glb', 'nested model.obj', 'scene.gltf', 'collection photo.tif', 'scan.pdf', 'oral history.wav'])
def test_all_five_formats_generate_and_validate_with_real_services(tmp_path, source_name):
    from test_edm_service_minimum_viable import _build_generation_app
    from database.database import db
    from services.iiif_service import IiifService
    from services.mets_service import MetsService
    from services.lod_reliability import snapshot_templates
    app = _build_generation_app(tmp_path)
    app.edm_service = EdmService()
    app.iiif_service = IiifService()
    app.mets_service = MetsService()
    spec = specification()
    spec['main_file_key'] = source_name
    spec['additional_files'] = [{'key': 'object_r000.png', 'size': 100}]
    for metadata in spec['metadata'].values():
        metadata.update(description='A documented heritage object used to validate metadata exports.', license='cc-by-4.0', upload_type='dataset', publication_date='2026-09-26')
    with app.app_context():
        db.create_all()
        spec['templates'] = snapshot_templates({})
        outputs, manifest = generate_artifacts(str(tmp_path / 'outputs'), spec, Mock())
    assert set(outputs) == {'edm', 'iiif', 'mets', 'cidoc_crm', 'jsonld'}, manifest['formats']
    assert all(item['validation']['valid'] is True for item in manifest['formats'].values())


def test_preview_uses_selected_row_filename_instead_of_example_model():
    from routes.lod_mapping_helpers import record_for_metadata_row
    record, name = record_for_metadata_row({'filename': 'collection/überblick.pdf'}, {'filename_column': 'filename'}, {'id': 123, 'files': [{'key': 'sample_model.glb'}]})
    assert name == 'überblick.pdf'
    assert record['files'] == [{'key': name, 'filename': name}]


def test_enabling_required_validation_invalidates_cached_exports(tmp_path):
    app = services_app()
    app.edm_service.validate_edm_document.return_value = {'valid': True}
    with app.app_context():
        generate_artifacts(str(tmp_path), specification(), Mock())
        app.config['LOCAL_EDM_VALIDATOR_REQUIRED'] = True
        app.edm_service.validate_edm_document.return_value = {'valid': False, 'errors': ['Validator unavailable']}
        outputs, manifest = generate_artifacts(str(tmp_path), specification(), Mock())
    assert 'edm' not in outputs
    assert app.edm_service.validate_edm_document.call_count == 2
    assert app.edm_service.validate_edm_document.call_args.kwargs['include_remote'] is True
