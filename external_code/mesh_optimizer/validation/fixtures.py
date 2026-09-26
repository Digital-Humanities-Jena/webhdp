"""Generate deterministic edge cases with Blender: blender -b -P fixtures.py -- DIR."""
import json
import base64
import struct
import sys
from pathlib import Path
import bpy

root = Path(sys.argv[sys.argv.index('--') + 1]); root.mkdir(parents=True, exist_ok=True)


def reset():
    bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)


def export(name):
    bpy.ops.export_scene.gltf(filepath=str(root / (name + '.glb')), export_format='GLB')


def cube():
    bpy.ops.mesh.primitive_cube_add()
    return bpy.context.object


reset(); obj = cube(); obj.data.materials.clear(); export('no-material')
reset(); obj = cube(); obj.scale = (0.000001,) * 3
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True); export('microscopic')
reset(); obj = cube(); obj.location = (100000, -200000, 300000); export('large-coordinates')
reset(); obj = cube(); obj.name = '一体 — café'; export('模型 café with spaces')
reset(); obj = cube()
for name, color in [('Red', (1, 0, 0, 1)), ('Blue', (0, 0, 1, 1))]:
    mat = bpy.data.materials.new(name); mat.use_nodes = True
    mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value = color
    obj.data.materials.append(mat)
for face in obj.data.polygons: face.material_index = face.index % 2
export('multiple-materials')
reset(); obj = cube(); parent = bpy.data.objects.new('Transformed parent', None)
bpy.context.collection.objects.link(parent); parent.rotation_euler = (0.2, -0.3, 0.8); parent.location = (7, 4, -2)
obj.parent = parent; obj.scale = (-1, 2, 0.5)
other = obj.copy(); other.data = obj.data; bpy.context.collection.objects.link(other); other.location = (4, 2, 0)
export('hierarchy-instances')
reset(); bpy.ops.mesh.primitive_grid_add(x_subdivisions=220, y_subdivisions=220, size=4)
obj = bpy.context.object
import math
for v in obj.data.vertices: v.co.z = 0.15 * math.sin(v.co.x * 5) * math.cos(v.co.y * 5)
export('dense-surface')
reset(); bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=8, radius=1); bpy.ops.object.shade_smooth(); export('dense-sphere')
reset(); obj = cube(); obj.scale = (0, 0, 0)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True); export('degenerate')
# Sparse positions in an embedded data URI exercise a GLB without a BIN chunk.
data = bytes([1, 2, 0, 0]) + struct.pack('<6f', 1, 0, 0, 0, 1, 0)
doc = {'asset': {'version': '2.0'},
       'buffers': [{'byteLength': len(data), 'uri': 'data:application/octet-stream;base64,' + base64.b64encode(data).decode()}],
       'bufferViews': [{'buffer': 0, 'byteLength': 2}, {'buffer': 0, 'byteOffset': 4, 'byteLength': 24}],
       'accessors': [{'componentType': 5126, 'type': 'VEC3', 'count': 3, 'min': [0, 0, 0], 'max': [1, 1, 0],
                      'sparse': {'count': 2, 'indices': {'bufferView': 0, 'componentType': 5121}, 'values': {'bufferView': 1}}}],
       'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
       'nodes': [{'mesh': 0}], 'scenes': [{'nodes': [0]}], 'scene': 0}
payload = json.dumps(doc).encode(); payload += b' ' * (-len(payload) % 4)
(root / 'sparse-data-uri.glb').write_bytes(struct.pack('<4sIII4s', b'glTF', 2, 20 + len(payload), len(payload), b'JSON') + payload)
(root / 'synthetic-cases.json').write_text(json.dumps({'generated_with': bpy.app.version_string,
    'cases': ['no-material', 'microscopic', 'large-coordinates', '模型 café with spaces',
              'multiple-materials', 'hierarchy-instances', 'dense-surface', 'dense-sphere', 'sparse-data-uri', 'degenerate']}, indent=2))
