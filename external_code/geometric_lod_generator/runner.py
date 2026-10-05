"""Run CPU geometric LOD generation for static, self-contained GLB assets."""
import hashlib
import importlib.util
import json
import math
import os
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path


def _contract():
    path = Path(__file__).with_name('glb_contract.py')
    if not path.exists():
        path = Path(__file__).parent.parent / 'mesh_optimizer' / 'runner.py'
    spec = importlib.util.spec_from_file_location('lod_glb_contract', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _number(value, label, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value < maximum or not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number greater than zero and less than {maximum}.')
    return float(value)


def _hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _document(path):
    with path.open('rb') as stream:
        stream.seek(12)
        size = struct.unpack('<I', stream.read(4))[0]
        stream.seek(20)
        return json.loads(stream.read(size))


def _triangle_count(document):
    """Count exported scene instances independently of Blender's report."""
    scenes = document.get('scenes') or []
    if len(scenes) != 1:
        raise ValueError('A geometric LOD output must contain one scene.')
    pending, visited, count = list(scenes[0].get('nodes', [])), set(), 0
    while pending:
        index = pending.pop()
        if index in visited:
            raise ValueError('A geometric LOD output contains a repeated scene node.')
        visited.add(index)
        node = document['nodes'][index]
        pending.extend(node.get('children', []))
        if 'mesh' in node:
            for primitive in document['meshes'][node['mesh']]['primitives']:
                accessor = primitive.get('indices', primitive['attributes']['POSITION'])
                vertices = document['accessors'][accessor]['count']
                if primitive.get('mode', 4) != 4 or vertices % 3:
                    raise ValueError('A geometric LOD output must contain complete triangles.')
                count += vertices // 3
    return count


def validate_parameters(parameters):
    return (_number(parameters.get('target_ratio', 0.5), 'Target ratio', 1),
            _number(parameters.get('max_relative_error', 0.001), 'Relative error limit', 0.1))


def validate_request(request):
    """Check source and parameters without Blender, output writes, or processes."""
    if not isinstance(request, dict) or not isinstance(request.get('inputs'), dict) or not isinstance(request.get('parameters', {}), dict):
        raise ValueError('A component request must contain input and parameter objects.')
    source = Path((request.get('inputs') or {}).get('input_file') or '').resolve()
    if not source.is_file() or source.suffix.lower() != '.glb':
        raise ValueError('Geometric LOD requires a static, self-contained GLB. Export other formats as GLB first.')
    parameters = request.get('parameters') or {}
    ratio, error_limit = validate_parameters(parameters)
    contract = _contract()
    source_info = contract.inspect_glb(source)
    document = _document(source)
    if len(document.get('scenes', [])) != 1:
        raise ValueError('Geometric LOD supports one scene. Export the intended scene as a separate GLB.')
    if any(primitive.get('targets') for mesh in document.get('meshes', []) for primitive in mesh.get('primitives', [])):
        raise ValueError('Geometric LOD does not support morph targets. Export a static GLB first.')
    return source, ratio, error_limit, source_info


def execute(request):
    source, ratio, error_limit, source_info = validate_request(request)
    contract = _contract()
    blender = os.environ.get('WEBHDP_BLENDER_BIN') or shutil.which('blender')
    if not blender:
        raise RuntimeError('Blender is required for geometric LOD generation. Install the component image before running it.')
    output_root = Path(os.environ.get('WEBHDP_OUTPUT_DIR') or '/outputs')
    output_root.mkdir(parents=True, exist_ok=True)
    original_hash = _hash(source)
    # A new directory prevents collisions between retries and identically named records.
    output = Path(tempfile.mkdtemp(prefix='geometric-lod-', dir=output_root))
    report = output / 'lod-report.json'
    try:
        prepared = contract.materialize_default_material(source, output / 'import.glb')
        command = [blender, '--background', '--factory-startup', '--python-use-system-env', '--python-exit-code', '1',
                   '--python', str(Path(__file__).with_name('blender_entry.py')), '--',
                   str(prepared), str(output), str(ratio), str(error_limit)]
        process = subprocess.run(command, capture_output=True, text=True, timeout=600)
        if process.returncode:
            raise RuntimeError('Geometric LOD failed: ' + (process.stderr or process.stdout)[-2000:])
        payload = json.loads(report.read_text(encoding='utf-8'))
        outputs = {'analysis_report': str(report)}
        if set(payload.get('levels', {})) != {'high', 'medium', 'low'}:
            raise ValueError('Geometric LOD did not produce the complete detail ladder.')
        previous_triangles = payload['source_triangles']
        for level in ('high', 'medium', 'low'):
            path = output / f'lod-{level}.glb'
            info = contract.inspect_glb(path)
            if source_info['used_images'] and not info['used_images']:
                raise ValueError('A geometric LOD output lost its embedded textures.')
            entry = payload['levels'][level]
            if _triangle_count(_document(path)) != entry['triangles']:
                raise ValueError('A geometric LOD output does not match its reported triangle count.')
            if not 0 < entry['triangles'] <= previous_triangles:
                raise ValueError('Geometric LOD triangle counts must form a non-increasing ladder.')
            previous_triangles = entry['triangles']
            entry.update(bytes=path.stat().st_size, sha256=_hash(path))
            outputs[f'lod_{level}'] = str(path)
        if _hash(source) != original_hash:
            raise ValueError('The source changed during geometric LOD generation.')
        payload.update(component='geometric_lod_generator', version='1.0.1',
                       source_filename=source.name, source_bytes=source.stat().st_size, source_sha256=original_hash,
                       target_ratio=ratio, max_relative_error=error_limit, mutated_original=False,
                       quality_note='Bidirectional vertex, edge-midpoint and triangle-centroid sampling; this is not a continuous surface-distance guarantee.')
        report.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')
        if prepared != source:
            prepared.unlink()
        outputs['lod_preview'] = outputs['lod_medium']
        artifacts = [{'key': name, 'filename': Path(path).name, 'remote_path': path,
                      'mime_type': 'application/json' if name == 'analysis_report' else 'model/gltf-binary'}
                     for name, path in outputs.items() if name != 'lod_preview']
        return {'success': True, 'status': 'completed', 'outputs': outputs, 'artifacts': artifacts,
                'metadata': {'component': 'geometric_lod_generator', 'lod': payload}}
    except Exception:
        shutil.rmtree(output)
        raise
