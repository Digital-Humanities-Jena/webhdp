#!/usr/bin/env python3
"""File-based HDP Component contract for the 3DOM-FBK mesh optimizer."""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


def inspect_glb(path: Path) -> dict:
    """Reject truncated containers, external resources and empty/non-mesh assets."""
    with path.open('rb') as source:
        header = source.read(12)
        if len(header) != 12:
            raise ValueError('The GLB header is incomplete.')
        magic, version, length = struct.unpack('<4sII', header)
        if magic != b'glTF' or version != 2 or length != path.stat().st_size:
            raise ValueError('Expected a complete GLB 2.0 file.')
        chunk = source.read(8)
        if len(chunk) != 8:
            raise ValueError('The GLB JSON chunk is missing.')
        size, kind = struct.unpack('<I4s', chunk)
        if kind != b'JSON' or size > min(length - 20, 64 * 1024 * 1024):
            raise ValueError('The GLB JSON chunk is invalid or too large.')
        document = json.loads(source.read(size))
        while source.tell() < length:
            chunk = source.read(8)
            if len(chunk) != 8:
                raise ValueError('The GLB contains a truncated chunk.')
            size, _ = struct.unpack('<I4s', chunk)
            if size % 4 or source.tell() + size > length:
                raise ValueError('The GLB contains an invalid chunk length.')
            source.seek(size, 1)
    if not document.get('meshes') or not any(m.get('primitives') for m in document['meshes']):
        raise ValueError('The GLB does not contain a mesh.')
    if document.get('animations') or document.get('skins'):
        raise ValueError('Animated and skinned models are not supported. Export a static GLB first.')
    for mesh in document['meshes']:
        for primitive in mesh.get('primitives', []):
            if primitive.get('mode', 4) not in {4, 5, 6} or primitive.get('targets'):
                raise ValueError('Use a static triangle mesh without point, line or morph-target primitives.')
    for item in document.get('buffers', []) + document.get('images', []):
        uri = item.get('uri', '')
        if uri and not uri.startswith('data:'):
            raise ValueError('External resources are not supported. Export a self-contained GLB first.')
    return {'bytes': length, 'meshes': len(document['meshes']),
            'materials': len(document.get('materials', [])), 'images': len(document.get('images', []))}


def execute(request: dict) -> dict:
    path = Path(str((request.get('inputs') or {}).get('input_file') or ''))
    if not path.is_absolute():
        path = Path(os.environ.get('WEBHDP_INPUT_DIR', '/inputs')) / path
    path = path.resolve(strict=True)
    if not path.is_file() or path.suffix.lower() != '.glb':
        raise ValueError('Select a self-contained static .glb model.')
    before = inspect_glb(path)
    params = request.get('parameters') or {}
    quality = params.get('quality', 'MEDIUM')
    if quality not in {'LOW', 'MEDIUM', 'HIGH'}:
        raise ValueError('Quality must be LOW, MEDIUM or HIGH.')
    resolution = params.get('texture_resolution', 1024)
    if isinstance(resolution, bool) or resolution not in {256, 512, 1024, 2048, 4096}:
        raise ValueError('Texture resolution must be 256, 512, 1024, 2048 or 4096.')
    mode = params.get('geometry_mode', 'preserve_uvs')
    if mode != 'preserve_uvs':
        raise ValueError('This component version supports preserving UVs only; remeshing is not enabled.')
    output_root = Path(os.environ.get('WEBHDP_OUTPUT_DIR', '/outputs'))
    output_root.mkdir(parents=True, exist_ok=True)
    # A separate directory per invocation prevents same-name records and retries
    # from overwriting another result or mistaking stale output for success.
    output = Path(tempfile.mkdtemp(prefix='mesh-optimizer-', dir=output_root))
    command = ['blender', '--background', '--factory-startup', '--python-exit-code', '1',
               '--python', '/opt/webhdp/mesh_optimizer/blender_entry.py', '--',
               '--input', str(path), '--output', str(output), '--decimation_presets', quality,
               '--image_resolution', str(resolution), '--no_subfolder']
    command.append('--skip_remesh')
    log = output / 'optimization.log'
    with log.open('w') as stream:
        process = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=False)
    if process.returncode:
        errors = []
        with log.open(errors='replace') as stream:
            for line in stream:
                if 'CRITICAL ERROR:' in line or 'ERROR:' in line:
                    errors.append(line.strip()[-1000:])
                    errors = errors[-5:]
        with log.open('rb') as stream:
            stream.seek(max(0, log.stat().st_size - 6000))
            tail = stream.read().decode('utf-8', errors='replace')
        return {'success': False, 'status': 'failed',
                'error': errors[-1] if errors else 'Mesh optimization failed. Check the component log for details.',
                'outputs': {}, 'logs': {'stderr': tail, 'stdout': ''}}
    model = output / f'{path.stem}_optimized.glb'
    after = inspect_glb(model)
    if before['images'] and not after['images']:
        raise ValueError('Optimization lost the model textures; the result was rejected.')
    report = output / 'optimization_report.json'
    report.write_text(json.dumps({'source': path.name, 'result': model.name,
                                  'before': before, 'after': after, 'parameters': {
                                      'quality': quality, 'texture_resolution': resolution, 'geometry_mode': mode}}, indent=2))
    return {'success': True, 'status': 'completed',
            'outputs': {'optimized_model': str(model), 'optimized_models': [str(model)], 'optimization_report': str(report)},
            'artifacts': [{'artifact_kind': 'file', 'name': p.name, 'remote_path': str(p),
                           'metadata': {'component': 'mesh_optimizer'}} for p in (model, report)],
            'logs': {'stdout': f'Optimized {path.name}: {before["bytes"]} → {after["bytes"]} bytes.', 'stderr': ''}}


def main() -> int:
    try:
        request = json.loads(Path(os.environ['WEBHDP_COMPONENT_REQUEST']).read_text())
        result = execute(request)
    except Exception as exc:
        result = {'success': False, 'status': 'failed', 'error': str(exc), 'outputs': {}}
    Path(os.environ['WEBHDP_COMPONENT_RESPONSE']).write_text(json.dumps(result))
    print(json.dumps(result))
    return 0 if result['success'] else 1


if __name__ == '__main__':
    sys.exit(main())
