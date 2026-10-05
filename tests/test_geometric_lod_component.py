"""Contract failures and optional real CPU Blender coverage for geometric LOD."""
import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from test_mesh_optimizer_component import glb

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('geometric_lod_runner', ROOT / 'external_code/geometric_lod_generator/runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@pytest.mark.parametrize('value', [-1, 0, 1, 2, True, '0.5', None, float('nan'), float('inf')])
def test_invalid_ratio_fails_before_blender(tmp_path, value):
    source = glb(tmp_path / 'source.glb')
    with patch.object(runner.subprocess, 'run') as process, pytest.raises(ValueError, match='Target ratio'):
        runner.execute({'inputs': {'input_file': str(source)}, 'parameters': {'target_ratio': value}})
    process.assert_not_called()


def test_unsupported_input_and_missing_runtime_are_explicit(tmp_path, monkeypatch):
    source = tmp_path / 'source.obj'; source.write_text('v 0 0 0')
    with pytest.raises(ValueError, match='GLB'):
        runner.execute({'inputs': {'input_file': str(source)}})
    source = glb(tmp_path / 'source.glb', scene=0, scenes=[{'nodes': [0]}], nodes=[{'mesh': 0}])
    monkeypatch.delenv('WEBHDP_BLENDER_BIN', raising=False)
    monkeypatch.setattr(runner.shutil, 'which', lambda executable: None)
    with pytest.raises(RuntimeError, match='Blender is required'):
        runner.execute({'inputs': {'input_file': str(source)}})


def test_failed_blender_removes_partial_artifacts_and_keeps_source(tmp_path, monkeypatch):
    source = glb(tmp_path / 'source.glb', scene=0, scenes=[{'nodes': [0]}], nodes=[{'mesh': 0}])
    original = source.read_bytes()
    output = tmp_path / 'outputs'
    monkeypatch.setenv('WEBHDP_OUTPUT_DIR', str(output))
    monkeypatch.setenv('WEBHDP_BLENDER_BIN', 'blender')
    with patch.object(runner.subprocess, 'run', side_effect=subprocess.TimeoutExpired('blender', 600)), pytest.raises(subprocess.TimeoutExpired):
        runner.execute({'inputs': {'input_file': str(source)}})
    assert source.read_bytes() == original
    assert not list(output.iterdir())


@pytest.mark.parametrize('scenes', [[], [{'nodes': [0]}, {'nodes': [0]}]])
def test_ambiguous_or_missing_scene_fails_before_blender(tmp_path, scenes):
    source = glb(tmp_path / 'source.glb', scenes=scenes, nodes=[{'mesh': 0}])
    with patch.object(runner.subprocess, 'run') as process, pytest.raises(ValueError, match='one scene'):
        runner.execute({'inputs': {'input_file': str(source)}})
    process.assert_not_called()


BLENDER = os.environ.get('WEBHDP_TEST_BLENDER')
IMAGE = os.environ.get('WEBHDP_TEST_GEOMETRIC_IMAGE')


def execute_lod(request, output, runtime):
    if runtime == 'local':
        return runner.execute(request)
    output.mkdir(parents=True, exist_ok=True)
    source = Path(request['inputs']['input_file'])
    request_file = output / 'request.json'
    result_file = output / 'result.json'
    request_file.write_text(json.dumps({**request, 'inputs': {'input_file': '/inputs/' + source.name}}))
    result_file.unlink(missing_ok=True)
    process = subprocess.run([
        'docker', 'run', '--rm', '--network', 'none', '--cpus=1', '--memory=8g',
        '-v', str(source.parent) + ':/inputs:ro', '-v', str(output) + ':/outputs',
        '-e', 'WEBHDP_COMPONENT_REQUEST=/outputs/request.json',
        '-e', 'WEBHDP_COMPONENT_RESPONSE=/outputs/result.json', IMAGE,
    ], capture_output=True, text=True, timeout=660)
    result = json.loads(result_file.read_text()) if result_file.exists() else {}
    assert process.returncode == 0 and result.get('success'), result or process.stderr[-2000:]
    result['outputs'] = {key: str(output / Path(path).relative_to('/outputs')) for key, path in result['outputs'].items()}
    return result


@pytest.mark.skipif(not BLENDER, reason='Set WEBHDP_TEST_BLENDER to run the CPU Blender integration checks')
@pytest.mark.parametrize('kind', ['smooth', 'textured', 'tight_limit'])
@pytest.mark.parametrize('runtime', ['local', 'container'])
def test_real_cpu_ladder_and_conservative_retention(tmp_path, monkeypatch, kind, runtime):
    if runtime == 'container' and not IMAGE:
        pytest.skip('Set WEBHDP_TEST_GEOMETRIC_IMAGE to check the packaged CPU runtime')
    fixture = tmp_path / 'fixture.py'
    source = tmp_path / 'source.glb'
    fixture.write_text('''import bpy, sys
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32)
obj=bpy.context.object
bpy.ops.object.shade_smooth()
material=bpy.data.materials.new('Paint'); material.use_nodes=True
material.diffuse_color=(0.2,0.4,0.8,1)
obj.data.materials.append(material)
if sys.argv[-1]=='textured':
    image=bpy.data.images.new('Embedded',width=8,height=8)
    image.generated_color=(0.2,0.4,0.8,1); image.pack()
    texture=material.node_tree.nodes.new('ShaderNodeTexImage'); texture.image=image
    material.node_tree.links.new(texture.outputs['Color'],material.node_tree.nodes.get('Principled BSDF').inputs['Base Color'])
    obj.data.uv_layers.new(name='ExtraUV')
    obj.data.color_attributes.new(name='Color',type='BYTE_COLOR',domain='CORNER')
bpy.ops.export_scene.gltf(filepath=sys.argv[-2],export_format='GLB',export_all_vertex_colors=True,export_vertex_color='ACTIVE')
''')
    subprocess.run([BLENDER, '--background', '--factory-startup', '--python-exit-code', '1', '--python', str(fixture), '--', str(source), kind], check=True, capture_output=True, timeout=60)
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setenv('WEBHDP_BLENDER_BIN', BLENDER)
    output = tmp_path / 'outputs'
    monkeypatch.setenv('WEBHDP_OUTPUT_DIR', str(output))
    result = execute_lod({'inputs': {'input_file': str(source)}, 'parameters': {
        'target_ratio': 0.5, 'max_relative_error': 0.0000001 if kind == 'tight_limit' else 0.01}}, output, runtime)
    report = json.loads(Path(result['outputs']['analysis_report']).read_text())
    counts = [report['source_triangles'], *(report['levels'][level]['triangles'] for level in ('high', 'medium', 'low'))]
    assert counts == sorted(counts, reverse=True)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    assert len(result['artifacts']) == 4
    if kind == 'tight_limit':
        assert counts[-1] == counts[0]
        checks = [item for level in report['levels'].values() for item in level['geometry_checks']]
        assert all(item['status'] == 'retained' and item['sampled_error'] == 0 for item in checks)
        assert all(item['candidate_sampled_error'] > item['error_limit'] for item in checks)
    else:
        assert counts[-1] < counts[0] * 0.3
    if kind == 'smooth':
        retry = execute_lod({'inputs': {'input_file': str(source)}, 'parameters': {
            'target_ratio': 0.25, 'max_relative_error': 0.01}}, output, runtime)
        assert Path(retry['outputs']['lod_medium']).parent != Path(result['outputs']['lod_medium']).parent
        retry_report = json.loads(Path(retry['outputs']['analysis_report']).read_text())
        assert retry_report['levels']['medium']['triangles'] < report['levels']['medium']['triangles']
        assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    if kind == 'textured':
        for level in ('high', 'medium', 'low'):
            info = runner._contract().inspect_glb(Path(result['outputs'][f'lod_{level}']))
            assert info['used_images'] == 1
            import struct
            payload = Path(result['outputs'][f'lod_{level}']).read_bytes()
            document = json.loads(payload[20:20 + struct.unpack_from('<I', payload, 12)[0]])
            attributes = document['meshes'][0]['primitives'][0]['attributes']
            assert {'TEXCOORD_0', 'TEXCOORD_1', 'COLOR_0', 'NORMAL'} <= attributes.keys()
            assert document['materials'][0]['pbrMetallicRoughness'] == runner._document(source)['materials'][0]['pbrMetallicRoughness']
