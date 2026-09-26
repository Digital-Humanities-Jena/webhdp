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
    data = struct.pack('<9f', 0, 0, 0, 1, 0, 0, 0, 1, 0)
    document = {'asset': {'version': '2.0'},
                'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
                'buffers': [{'byteLength': len(data)}],
                'bufferViews': [{'buffer': 0, 'byteLength': len(data)}],
                'accessors': [{'bufferView': 0, 'componentType': 5126, 'type': 'VEC3', 'count': 3}],
                **extra}
    payload = json.dumps(document).encode()
    payload += b' ' * (-len(payload) % 4)
    path.write_bytes(struct.pack('<4sIII4s', b'glTF', 2, 28 + len(payload) + len(data), len(payload), b'JSON') + payload
                     + struct.pack('<I4s', len(data), b'BIN\x00') + data)
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
    path = glb(tmp_path / 'model.glb', images=[{'bufferView': 0}], textures=[{'source': 0}],
               materials=[{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}],
               meshes=[{'primitives': [{'attributes': {'POSITION': 0}, 'material': 0}]}])
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


@pytest.mark.parametrize('extra, message', [
    ({'bufferViews': [{'buffer': 0, 'byteLength': 1000}]}, 'beyond'),
    ({'buffers': [{'byteLength': 1000}]}, 'invalid length'),
    ({'accessors': [{'bufferView': 0, 'componentType': 5126, 'type': 'VEC3', 'count': 4}]}, 'beyond'),
    ({'accessors': [{'bufferView': 9, 'componentType': 5126, 'type': 'VEC3', 'count': 3}]}, 'missing data'),
    ({'nodes': [{'children': [1]}, {'children': [0]}]}, 'cycle'),
    ({'nodes': [{'mesh': 3}]}, 'missing data'),
    ({'meshes': [None]}, 'list of objects'),
    ({'extensionsRequired': ['EXT_meshopt_compression']}, 'Unsupported GLB extensions'),
    ({'images': [{'bufferView': 99}]}, 'missing data'),
    ({'meshes': [{'primitives': [{'attributes': {}}]}]}, 'missing positions'),
    ({'scene': 2, 'scenes': [{}]}, 'missing data'),
])
def test_invalid_resources_fail_before_gpu(tmp_path, extra, message):
    path = glb(tmp_path / 'bad.glb', **extra)
    with patch.object(runner.subprocess, 'run') as process, pytest.raises(ValueError, match=message):
        runner.execute({'inputs': {'input_file': str(path)}})
    process.assert_not_called()


@pytest.mark.parametrize('resolution', [True, 1024.0, '1024', 0, 5120, [], {}])
def test_texture_resolution_requires_supported_integer(tmp_path, resolution):
    path = glb(tmp_path / 'model.glb')
    with patch.object(runner.subprocess, 'run') as process, pytest.raises(ValueError, match='Texture resolution'):
        runner.execute({'inputs': {'input_file': str(path)}, 'parameters': {'texture_resolution': resolution}})
    process.assert_not_called()


def test_rejects_duplicate_binary_chunk(tmp_path):
    path = glb(tmp_path / 'model.glb')
    data = bytearray(path.read_bytes()) + struct.pack('<I4s', 0, b'BIN\x00')
    struct.pack_into('<I', data, 8, len(data)); path.write_bytes(data)
    with pytest.raises(ValueError, match='duplicate'):
        runner.inspect_glb(path)


def test_valid_sparse_positions(tmp_path):
    path = glb(tmp_path / 'sparse.glb', accessors=[{
        'componentType': 5126, 'type': 'VEC3', 'count': 3,
        'sparse': {'count': 1, 'indices': {'bufferView': 0, 'componentType': 5121},
                   'values': {'bufferView': 0, 'byteOffset': 4}}}])
    assert runner.inspect_glb(path)['primitives'] == 1


def test_import_copy_makes_default_material_explicit_without_changing_source(tmp_path):
    source = glb(tmp_path / 'source.glb')
    original = source.read_bytes()
    target = tmp_path / 'prepared.glb'
    assert runner.materialize_default_material(source, target) == target
    assert source.read_bytes() == original
    assert runner.inspect_glb(target)['materials'] == 1
    data = target.read_bytes()
    document = json.loads(data[20:20 + struct.unpack_from('<I', data, 12)[0]])
    assert document['materials'] == [{}]
    assert document['meshes'][0]['primitives'][0]['material'] == 0
    assert data[-36:] == original[-36:]


def test_import_copy_preserves_explicit_materials(tmp_path):
    source = glb(tmp_path / 'source.glb', materials=[{'name': 'Paint'}],
                 meshes=[{'primitives': [{'attributes': {'POSITION': 0}, 'material': 0}]}])
    target = tmp_path / 'prepared.glb'
    assert runner.materialize_default_material(source, target) == source
    assert not target.exists()



def test_unused_images_do_not_require_textured_output(tmp_path):
    path = glb(tmp_path / 'unused.glb', images=[{'bufferView': 0}])
    result = runner.inspect_glb(path)
    assert result['images'] == 1
    assert result['used_images'] == 0
