#!/usr/bin/env python3
"""File-based HDP Component contract for the 3DOM-FBK mesh optimizer."""
from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


def _integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{label} must be an integer of at least {minimum}.')
    return value


def _reference(items, index, label):
    index = _integer(index, label)
    if index >= len(items):
        raise ValueError(f'{label} references missing data.')
    return items[index]


def inspect_glb(path: Path) -> dict:
    """Validate the container and resource boundaries before invoking Blender.

    This is a bounded preflight, not a replacement for the glTF conformance
    validator. Blender validates decoded geometry and image data at import.
    """
    binary_size = None
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
        if kind != b'JSON' or size % 4 or size > min(length - 20, 64 * 1024 * 1024):
            raise ValueError('The GLB JSON chunk is invalid or too large.')
        def invalid_constant(value):
            raise ValueError('The GLB JSON contains a non-finite number.')
        document = json.loads(source.read(size), parse_constant=invalid_constant)
        while source.tell() < length:
            chunk = source.read(8)
            if len(chunk) != 8:
                raise ValueError('The GLB contains a truncated chunk.')
            size, kind = struct.unpack('<I4s', chunk)
            if size % 4 or source.tell() + size > length:
                raise ValueError('The GLB contains an invalid chunk length.')
            if kind == b'JSON' or (kind == b'BIN\x00' and binary_size is not None):
                raise ValueError('The GLB contains duplicate JSON or binary chunks.')
            if kind == b'BIN\x00':
                binary_size = size
            source.seek(size, 1)
    if not isinstance(document, dict) or not isinstance(document.get('asset'), dict) or document['asset'].get('version') != '2.0':
        raise ValueError('Expected a glTF 2.0 JSON object.')
    for key in ('meshes', 'buffers', 'bufferViews', 'accessors', 'images', 'textures', 'materials', 'nodes', 'scenes', 'animations', 'skins'):
        items = document.get(key, [])
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValueError(f'The GLB {key} must be a list of objects.')
    if not document.get('meshes'):
        raise ValueError('The GLB does not contain a mesh.')
    if document.get('animations') or document.get('skins'):
        raise ValueError('Animated and skinned models are not supported. Export a static GLB first.')
    supported = {'KHR_draco_mesh_compression', 'KHR_mesh_quantization', 'KHR_texture_transform',
                 'KHR_materials_unlit', 'KHR_materials_clearcoat', 'KHR_materials_transmission',
                 'KHR_materials_volume', 'KHR_materials_ior', 'KHR_materials_specular',
                 'KHR_materials_sheen', 'KHR_materials_emissive_strength', 'KHR_materials_anisotropy',
                 'KHR_materials_iridescence', 'KHR_materials_dispersion', 'KHR_lights_punctual'}
    for key in ('extensionsUsed', 'extensionsRequired'):
        values = document.get(key, [])
        if not isinstance(values, list) or any(not isinstance(x, str) for x in values):
            raise ValueError(f'The GLB {key} must be a list of extension names.')
        unsupported = set(values) - supported
        if unsupported:
            raise ValueError('Unsupported GLB extensions: ' + ', '.join(sorted(unsupported)) + '. Export a static GLB with standard materials and embedded PNG/JPEG textures.')
    buffers = document.get('buffers', [])
    views = document.get('bufferViews', [])
    accessors = document.get('accessors', [])
    for index, item in enumerate(buffers):
        size = _integer(item.get('byteLength'), 'Buffer size', 1)
        uri = item.get('uri')
        if uri is None:
            if index != 0 or binary_size is None or size > binary_size or binary_size - size > 3:
                raise ValueError('The GLB binary buffer is missing or has an invalid length.')
        elif not isinstance(uri, str) or not uri.startswith('data:'):
            raise ValueError('External resources are not supported. Export a self-contained GLB first.')
        else:
            import base64
            try:
                prefix, encoded = uri.split(',', 1)
                if not prefix.endswith(';base64') or len(base64.b64decode(encoded, validate=True)) != size:
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValueError('The embedded buffer data is invalid.') from None
    for view in views:
        buffer = _reference(buffers, view.get('buffer'), 'Buffer view')
        offset = _integer(view.get('byteOffset', 0), 'Buffer view offset')
        size = _integer(view.get('byteLength'), 'Buffer view size', 1)
        if offset + size > buffer['byteLength']:
            raise ValueError('A buffer view extends beyond its buffer.')
    component_bytes = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
    widths = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT2': 4, 'MAT3': 9, 'MAT4': 16}
    for accessor in accessors:
        count = _integer(accessor.get('count'), 'Accessor count', 1)
        component = accessor.get('componentType'); kind = accessor.get('type')
        if type(component) is not int or component not in component_bytes or not isinstance(kind, str) or kind not in widths:
            raise ValueError('An accessor has an invalid component type or shape.')
        element = component_bytes[component] * widths[kind]
        # Matrix columns have four-byte alignment, including byte/short data.
        if kind.startswith('MAT'):
            dimension = int(kind[-1]); column = dimension * component_bytes[component]
            element = dimension * ((column + 3) // 4 * 4)
        if 'bufferView' in accessor:
            view = _reference(views, accessor['bufferView'], 'Accessor buffer view')
            stride = _integer(view.get('byteStride', element), 'Accessor stride', element)
            offset = _integer(accessor.get('byteOffset', 0), 'Accessor offset')
            if offset + (count - 1) * stride + element > view['byteLength']:
                raise ValueError('An accessor extends beyond its buffer view.')
        if 'sparse' in accessor:
            sparse = accessor['sparse']
            if not isinstance(sparse, dict) or _integer(sparse.get('count'), 'Sparse count', 1) > count:
                raise ValueError('The sparse accessor is invalid.')
            for key in ('indices', 'values'):
                part = sparse.get(key)
                if not isinstance(part, dict):
                    raise ValueError('The sparse accessor is incomplete.')
                view = _reference(views, part.get('bufferView'), 'Sparse buffer view')
                unit = element
                if key == 'indices':
                    component = part.get('componentType')
                    if type(component) is not int or component not in (5121, 5123, 5125):
                        raise ValueError('Sparse indices have an invalid component type.')
                    unit = component_bytes[component]
                if _integer(part.get('byteOffset', 0), 'Sparse offset') + sparse['count'] * unit > view['byteLength']:
                    raise ValueError('A sparse accessor extends beyond its buffer view.')
    primitives = 0
    for mesh in document['meshes']:
        items = mesh.get('primitives')
        if not isinstance(items, list) or not items or any(not isinstance(p, dict) for p in items):
            raise ValueError('A mesh has no valid primitives.')
        for primitive in items:
            primitives += 1
            if primitive.get('mode', 4) not in (4, 5, 6) or primitive.get('targets'):
                raise ValueError('Use a static triangle mesh without point, line or morph-target primitives.')
            attrs = primitive.get('attributes')
            if not isinstance(attrs, dict) or 'POSITION' not in attrs:
                raise ValueError('A mesh primitive is missing positions.')
            for index in attrs.values():
                _reference(accessors, index, 'Mesh attribute')
            position = accessors[attrs['POSITION']]
            if position['type'] != 'VEC3' or position['count'] < 3:
                raise ValueError('A mesh primitive has no triangle positions.')
            if 'indices' in primitive:
                _reference(accessors, primitive['indices'], 'Mesh indices')
            if 'material' in primitive:
                _reference(document.get('materials', []), primitive['material'], 'Mesh material')
    for item in document.get('images', []):
        if 'uri' in item and (not isinstance(item['uri'], str) or not item['uri'].startswith('data:')):
            raise ValueError('External resources are not supported. Export a self-contained GLB first.')
        if 'bufferView' in item:
            _reference(views, item['bufferView'], 'Image buffer view')
        elif not isinstance(item.get('uri'), str) or not item['uri'].startswith('data:'):
            raise ValueError('External resources are not supported. Export a self-contained GLB first.')
    used_materials = {primitive['material'] for mesh in document['meshes']
                      for primitive in mesh['primitives'] if 'material' in primitive}
    used_images = set()
    for index in used_materials:
        pending = [document['materials'][index]]
        while pending:
            value = pending.pop()
            if not isinstance(value, dict):
                continue
            for key, item in value.items():
                if key.endswith('Texture') and isinstance(item, dict) and 'index' in item:
                    texture = _reference(document.get('textures', []), item['index'], 'Material texture')
                    image = texture.get('source')
                    _reference(document.get('images', []), image, 'Texture image')
                    used_images.add(image)
                elif key != 'extras' and isinstance(item, dict):
                    pending.append(item)
    nodes = document.get('nodes', [])
    children = []
    for node in nodes:
        if 'mesh' in node:
            _reference(document['meshes'], node['mesh'], 'Node mesh')
        edges = node.get('children', [])
        if not isinstance(edges, list):
            raise ValueError('Node children must be a list.')
        for index in edges:
            _reference(nodes, index, 'Child node')
        children.append(edges)
    # Iterative traversal avoids recursion exhaustion on deeply nested uploads.
    states = [0] * len(nodes)
    for index in range(len(nodes)):
        stack = [(index, False)]
        while stack:
            current, leaving = stack.pop()
            if leaving:
                states[current] = 2
            elif states[current] == 1:
                raise ValueError('The GLB scene hierarchy contains a cycle.')
            elif states[current] == 0:
                states[current] = 1
                stack.append((current, True))
                stack.extend((child, False) for child in children[current])
    scenes = document.get('scenes', [])
    for scene in scenes:
        if not isinstance(scene.get('nodes', []), list):
            raise ValueError('Scene nodes must be a list.')
        for index in scene.get('nodes', []):
            _reference(nodes, index, 'Scene node')
    if 'scene' in document:
        _reference(scenes, document['scene'], 'Default scene')
    return {'bytes': length, 'meshes': len(document['meshes']), 'primitives': primitives,
            'materials': len(document.get('materials', [])), 'images': len(document.get('images', [])),
            'used_images': len(used_images)}


def materialize_default_material(source_path: Path, target_path: Path) -> Path:
    """Give absent materials explicit glTF defaults before Blender imports them.

    Blender versions otherwise synthesize different roughness/metalness values
    and may ignore vertex colors. Only the temporary import copy is rewritten.
    """
    with source_path.open('rb') as source:
        source.seek(12)
        size, _ = struct.unpack('<I4s', source.read(8))
        document = json.loads(source.read(size))
        missing = [primitive for mesh in document['meshes'] for primitive in mesh['primitives']
                   if 'material' not in primitive]
        if not missing:
            return source_path
        materials = document.setdefault('materials', [])
        index = len(materials)
        materials.append({})
        for primitive in missing:
            primitive['material'] = index
        payload = json.dumps(document, separators=(',', ':')).encode('utf-8')
        payload += b' ' * (-len(payload) % 4)
        length = source_path.stat().st_size - size + len(payload)
        with target_path.open('wb') as target:
            target.write(struct.pack('<4sIII4s', b'glTF', 2, length, len(payload), b'JSON'))
            target.write(payload)
            shutil.copyfileobj(source, target)
    return target_path


def execute(request: dict) -> dict:
    if not isinstance(request, dict) or not isinstance(request.get('inputs'), dict) or not isinstance(request.get('parameters', {}), dict):
        raise ValueError('A component request must contain input and parameter objects.')
    path = Path(str(request['inputs'].get('input_file') or ''))
    if not path.is_absolute():
        path = Path(os.environ.get('WEBHDP_INPUT_DIR', '/inputs')) / path
    path = path.resolve(strict=True)
    if not path.is_file() or path.suffix.lower() != '.glb':
        raise ValueError('Select a self-contained static .glb model.')
    before = inspect_glb(path)
    params = request.get('parameters') or {}
    quality = params.get('quality', 'MEDIUM')
    if not isinstance(quality, str) or quality not in {'LOW', 'MEDIUM', 'HIGH'}:
        raise ValueError('Quality must be LOW, MEDIUM or HIGH.')
    resolution = params.get('texture_resolution', 1024)
    if type(resolution) is not int or resolution not in {256, 512, 1024, 2048, 4096}:
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
    if before['used_images'] and not after['used_images']:
        raise ValueError('Optimization lost the model textures; the result was rejected.')
    checks = output / 'geometry_checks.json'
    geometry_checks = json.loads(checks.read_text()) if checks.exists() else []
    report = output / 'optimization_report.json'
    report.write_text(json.dumps({'source': path.name, 'result': model.name,
                                  'before': before, 'after': after, 'geometry_checks': geometry_checks,
                                  'texture_handling': 'Preserved material graphs; resized embedded images without upscaling.',
                                  'parameters': {
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
