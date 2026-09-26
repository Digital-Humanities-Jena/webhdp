"""Contract and failure checks for the HPC mesh optimizer."""
import importlib.util
import json
import struct
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mesh_optimizer_runner', ROOT / 'external_code/mesh_optimizer/runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def glb(path, **extra):
    document = {'asset': {'version': '2.0'}, 'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}], **extra}
    payload = json.dumps(document).encode()
    payload += b' ' * (-len(payload) % 4)
    path.write_bytes(struct.pack('<4sIII4s', b'glTF', 2, 20 + len(payload), len(payload), b'JSON') + payload)
    return path


@pytest.mark.parametrize('data', [b'', b'not a model', struct.pack('<4sII', b'glTF', 2, 100)])
def test_rejects_truncated_input(tmp_path, data):
    path = tmp_path / 'broken.glb'; path.write_bytes(data)
    with pytest.raises(ValueError):
        runner.inspect_glb(path)


@pytest.mark.parametrize('extra', [{'meshes': []}, {'animations': [{}]}, {'skins': [{}]}, {'images': [{'uri': '../texture.png'}]}])
def test_unsupported_models_fail_before_start(tmp_path, extra):
    path = glb(tmp_path / 'model.glb', **extra)
    with patch.object(runner.subprocess, 'run') as process, pytest.raises(ValueError):
        runner.execute({'inputs': {'input_file': str(path)}})
    process.assert_not_called()


def test_success_requires_a_new_valid_output_and_embedded_textures(tmp_path, monkeypatch):
    path = glb(tmp_path / 'model.glb', images=[{'bufferView': 0}])
    monkeypatch.setenv('WEBHDP_OUTPUT_DIR', str(tmp_path / 'outputs'))
    request = {'inputs': {'input_file': str(path)}}
    with patch.object(runner.subprocess, 'run', return_value=SimpleNamespace(returncode=0)):
        with pytest.raises(FileNotFoundError):
            runner.execute(request)
    def missing_textures(command, **kwargs):
        glb(Path(command[command.index('--output') + 1]) / 'model_optimized.glb')
        return SimpleNamespace(returncode=0)
    with patch.object(runner.subprocess, 'run', side_effect=missing_textures), pytest.raises(ValueError, match='lost.*textures'):
        runner.execute(request)


def test_retries_and_same_name_records_get_independent_outputs(tmp_path, monkeypatch):
    path = glb(tmp_path / 'model.glb')
    monkeypatch.setenv('WEBHDP_OUTPUT_DIR', str(tmp_path / 'outputs'))
    def complete(command, **kwargs):
        glb(Path(command[command.index('--output') + 1]) / 'model_optimized.glb')
        return SimpleNamespace(returncode=0)
    with patch.object(runner.subprocess, 'run', side_effect=complete):
        first = runner.execute({'inputs': {'input_file': str(path)}})
        second = runner.execute({'inputs': {'input_file': str(path)}})
    assert first['success'] and second['success']
    assert first['outputs']['optimized_model'] != second['outputs']['optimized_model']
    assert all(Path(a['remote_path']).is_file() for a in first['artifacts'])


def test_failed_blender_does_not_report_outputs(tmp_path, monkeypatch):
    path = glb(tmp_path / 'model.glb')
    monkeypatch.setenv('WEBHDP_OUTPUT_DIR', str(tmp_path / 'outputs'))
    with patch.object(runner.subprocess, 'run', return_value=SimpleNamespace(returncode=1)):
        result = runner.execute({'inputs': {'input_file': str(path)}})
    assert result['success'] is False
    assert result['outputs'] == {}


def test_image_builder_removes_private_modes_from_runtime_files(tmp_path):
    spec = importlib.util.spec_from_file_location('mesh_optimizer_builder', ROOT / 'external_code/mesh_optimizer/build_sif.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    nested = tmp_path / 'pipeline'; nested.mkdir(mode=0o700)
    source = nested / 'core.py'; source.write_text(''); source.chmod(0o600)
    builder.make_runtime_readable(tmp_path)
    assert nested.stat().st_mode & 0o777 == 0o755
    assert source.stat().st_mode & 0o777 == 0o644


def test_pipeline_is_available_only_after_installing_verified_component():
    from flask import Flask
    from database.database import db
    from services.native_pipeline_system import NativePipelineSystemService
    from constants import MESH_OPTIMIZATION_PIPELINE_DEFINITION
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    with app.app_context(), patch.dict('os.environ', {'WEBHDP_CORE_ONLY': 'true'}):
        db.create_all()
        service = NativePipelineSystemService(); app.native_pipeline_service = service
        service.ensure_seeded()
        assert 'mesh_optimization' not in {p['identifier'] for p in service.list_pipelines()}
        manifest = yaml.safe_load((ROOT / 'external_code/mesh_optimizer/component.yaml').read_text())
        manifest['execution']['profiles'][0]['sif_sha256'] = 'a' * 64
        service.import_component_from_manifest(manifest, source_path=str(ROOT / 'external_code/mesh_optimizer'))
        validation = service.validate_pipeline_config(MESH_OPTIMIZATION_PIPELINE_DEFINITION)
        assert validation['valid'], validation['errors']
        service._seed_state = 'idle'; service.ensure_seeded()
        assert 'mesh_optimization' in {p['identifier'] for p in service.list_pipelines()}
        assert len(service.get_pipeline('mesh_optimization')['config']['steps']) == 2
        db.session.remove(); db.drop_all()
