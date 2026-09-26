"""Decode source/result meshes in Blender and verify geometry and attributes.

Usage: blender -b -P compare.py -- INPUT_DIR RESULT_DIR REPORT.json
RESULT_DIR contains component *-response.json files with /outputs paths.
"""
import json
import math
import struct
import sys
from pathlib import Path
import bpy
from mathutils import Vector


def document(path):
    with path.open('rb') as stream:
        stream.seek(12); size, _ = struct.unpack('<I4s', stream.read(8))
        return json.loads(stream.read(size))


def snapshot(path):
    bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(path))
    objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    points = [obj.matrix_world @ vertex.co for obj in objects for vertex in obj.data.vertices]
    if not points or any(not math.isfinite(v) for point in points for v in point):
        raise AssertionError('No finite geometry')
    area = 0; triangles = 0
    for obj in objects:
        obj.data.calc_loop_triangles()
        triangles += len(obj.data.loop_triangles)
        for tri in obj.data.loop_triangles:
            a, b, c = [obj.matrix_world @ obj.data.vertices[v].co for v in tri.vertices]
            area += (b-a).cross(c-a).length * 0.5
    return {'min': [min(p[i] for p in points) for i in range(3)],
            'max': [max(p[i] for p in points) for i in range(3)],
            'triangles': triangles, 'area': area,
            'uv_layers': max(len(obj.data.uv_layers) for obj in objects),
            'colors': any(obj.data.color_attributes for obj in objects)}


def material_features(doc):
    features = []
    used = {primitive['material'] for mesh in doc.get('meshes', []) for primitive in mesh['primitives'] if 'material' in primitive}
    materials = [doc['materials'][index] for index in sorted(used)]
    if any('material' not in primitive for mesh in doc.get('meshes', []) for primitive in mesh['primitives']):
        materials.append({})
    for material in materials:
        extensions = material.get('extensions', {})
        strength = extensions.get('KHR_materials_emissive_strength', {}).get('emissiveStrength', 1)
        pbr = material.get('pbrMetallicRoughness', {})
        features.append({'alpha': material.get('alphaMode', 'OPAQUE'),
                         'alpha_cutoff': round(material.get('alphaCutoff', 0.5), 4),
                         'unlit': 'KHR_materials_unlit' in extensions,
                         'emission': [round(value * strength, 4) for value in material.get('emissiveFactor', [0, 0, 0])],
                         'color': [round(value, 4) for value in pbr.get('baseColorFactor', [1, 1, 1, 1])],
                         'metallic': round(pbr.get('metallicFactor', 1), 4),
                         'roughness': round(pbr.get('roughnessFactor', 1), 4),
                         'double_sided': material.get('doubleSided', False)})
    for feature in features:
        if feature['alpha'] != 'MASK':
            feature.pop('alpha_cutoff')
        if feature['alpha'] == 'OPAQUE':
            feature['color'][3] = 1
        if feature['unlit']:
            # The unlit extension ignores lighting-dependent PBR properties.
            for key in ('metallic', 'roughness', 'emission'):
                feature.pop(key)
    return features


def compare(source, result):
    before, after = snapshot(source), snapshot(result)
    diagonal = (Vector(before['max']) - Vector(before['min'])).length
    tolerance = max(diagonal * 0.003, 1e-10)
    assert all(abs(before[k][i]-after[k][i]) <= tolerance for k in ('min','max') for i in range(3)), (source.name, 'bounds', before, after)
    assert after['triangles'] <= before['triangles'], (source.name, 'triangle growth')
    assert math.isclose(before['area'], after['area'], rel_tol=0.025, abs_tol=1e-20), (source.name, 'surface area', before, after)
    assert not before['colors'] or after['colors'], (source.name, 'lost vertex colors')
    assert after['uv_layers'] >= before['uv_layers'], (source.name, 'lost UV sets')
    source_materials, result_materials = material_features(document(source)), material_features(document(result))
    for material in source_materials:
        assert material in result_materials, (source.name, 'lost material properties', material, result_materials)
    return {'model': source.name, 'before': before, 'after': after}


if __name__ == '__main__':
    inputs, outputs, report = map(Path, sys.argv[sys.argv.index('--')+1:])
    results=[]
    for response in sorted(outputs.glob('*-response.json')):
        result=json.loads(response.read_text())
        if not result.get('success'): continue
        model=response.name.removesuffix('-response.json')
        path=outputs / Path(result['outputs']['optimized_model']).relative_to('/outputs')
        try:
            results.append(compare(inputs/(model+'.glb'),path))
        except Exception as exc:
            results.append({'model': model, 'error': str(exc)})
    report.write_text(json.dumps(results,indent=2))
    errors=[item for item in results if 'error' in item]
    print('COMPARISON',len(results),'models;',len(errors),'failures',errors)
    if errors: raise SystemExit(1)
