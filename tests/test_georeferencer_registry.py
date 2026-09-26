"""Registry and record isolation for the installable georeferencing pipeline."""
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_pipeline_requires_verified_installation():
    from flask import Flask
    from database.database import db
    from services.native_pipeline_system import NativePipelineSystemService
    from constants import GEOREFERENCING_PIPELINE_DEFINITION
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    with app.app_context(), patch.dict('os.environ', {'WEBHDP_CORE_ONLY': 'true'}):
        db.create_all()
        service = NativePipelineSystemService(); app.native_pipeline_service = service
        service.ensure_seeded()
        assert 'model_georeferencing' not in {p['identifier'] for p in service.list_pipelines()}
        manifest = yaml.safe_load((ROOT/'external_code/georeferencer/component.yaml').read_text())
        manifest['execution']['profiles'][0]['sif_sha256'] = 'a'*64
        service.import_component_from_manifest(manifest, source_path=str(ROOT/'external_code/georeferencer'))
        validation = service.validate_pipeline_config(GEOREFERENCING_PIPELINE_DEFINITION)
        assert validation['valid'], validation['errors']
        import copy
        invalid = copy.deepcopy(GEOREFERENCING_PIPELINE_DEFINITION)
        invalid['steps'][0]['scope'] = 'batch'
        assert any('record scope' in error for error in service.validate_pipeline_config(invalid)['errors'])
        service._seed_state = 'idle'; service.ensure_seeded()
        pipeline = service.get_pipeline('model_georeferencing')['config']
        assert [step['component_ref'] for step in pipeline['steps']] == ['georeferencer', 'fast_renderer']
        assert pipeline['steps'][1]['input_bindings'][0]['source_output'] == 'georeferenced_model'
        db.session.remove(); db.drop_all()


def test_reference_binding_uses_only_original_files_of_current_record(tmp_path):
    from services.native_pipeline_system import NativePipelineSystemService
    source = tmp_path/'site.glb'; source.touch()
    reference = tmp_path/'site.tif'; reference.touch()
    missing = tmp_path/'missing.tif'
    with patch('services.hdpc_local_service.read_hdpc_record_inputs', return_value=[
        {'absolute_path': str(source)}, {'absolute_path': str(reference)},
        {'absolute_path': str(reference)}, {'absolute_path': str(missing)}]) as read:
        paths = NativePipelineSystemService()._resolve_binding_value(
            {'type': 'record_source_files'}, {'record_id': 42}, {'hdpc_path': 'session.hdpc'})
    read.assert_called_once_with('session.hdpc', 42)
    assert paths == sorted([str(source), str(reference)])


def test_single_upstream_reference_is_normalized_for_file_list_contract():
    from services.native_pipeline_system import NativePipelineSystemService
    service = NativePipelineSystemService()
    fields = [{'name': 'reference_files', 'type': 'file_list'}]
    assert service._apply_default_input_bindings(fields, {'reference_files': '/session/reference.tif'}, {}, {}) == {
        'reference_files': ['/session/reference.tif']}
    assert service._apply_default_input_bindings(fields, {'reference_files': ''}, {}, {}) == {'reference_files': []}
