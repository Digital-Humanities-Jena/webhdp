"""Adapt the pinned optimizer's UV-preserving path without lossy OBJ round trips."""
import runpy
import math
import json
import tempfile
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).parent))
from runner import materialize_default_material

sys.path.insert(0, '/app/pipeline')
from tex_baker import TextureAnalyzer
from io_helper import MeshIO
from preprocess import MeshPreprocessor
from material_assembler import MaterialAssembler
from decimate import MeshDecimator

original_load = MeshIO.load
original_export = MeshIO.export
intermediates = {}


def load_material_groups(path):
    # OBJ has only one UV set and cannot represent glTF vertex colors, custom
    # normals or PBR materials. The supported skip-remesh path needs no external
    # geometry tool, so retain an independent Blender mesh for its intermediate.
    if path in intermediates:
        source = intermediates.pop(path)
        obj = source.copy()
        obj.data = source.data.copy()
        bpy.context.scene.collection.objects.link(obj)
        obj.hide_set(False)
        obj.hide_viewport = False
        return [obj]
    with tempfile.TemporaryDirectory(prefix='mesh-import-') as scratch:
        prepared = materialize_default_material(Path(path), Path(scratch) / Path(path).name) if Path(path).suffix.lower() == '.glb' else Path(path)
        objects = original_load(str(prepared))
    if Path(path).suffix.lower() not in {'.glb', '.gltf'}:
        return objects
    for obj in objects:
        if any(not math.isfinite(value) for vertex in obj.data.vertices for value in vertex.co):
            raise ValueError('The model contains non-finite vertex positions.')
        if not any(face.area > 0 for face in obj.data.polygons):
            raise ValueError('The model contains a mesh with no non-degenerate triangle surfaces.')
    # Split multi-material primitives before upstream groups by the first slot.
    for obj in objects:
        obj.data = obj.data.copy()
        if len({face.material_index for face in obj.data.polygons}) <= 1:
            continue
        activate_only(obj)
        bpy.ops.object.mode_set(mode='EDIT')
        try:
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.separate(type='MATERIAL')
        finally:
            bpy.ops.object.mode_set(mode='OBJECT')
    objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH' and obj.data.polygons]
    for obj in objects:
        used = {face.material_index for face in obj.data.polygons}
        if len(used) == 1 and obj.data.materials:
            index = next(iter(used))
            material = obj.data.materials[index] if index < len(obj.data.materials) else None
            obj.data.materials.clear()
            if material:
                obj.data.materials.append(material)
            for face in obj.data.polygons:
                face.material_index = 0
    if not objects:
        raise ValueError('The selected scene does not contain triangle surfaces.')
    return objects


def export_preserving_attributes(path, objects=None):
    if Path(path).suffix.lower() == '.obj':
        if not objects or len(objects) != 1 or '--skip_remesh' not in sys.argv:
            raise RuntimeError('Only the UV-preserving mesh intermediate is supported.')
        intermediates[path] = objects[0]
        return True
    if Path(path).suffix.lower() == '.glb':
        bpy.ops.object.select_all(action='DESELECT')
        for obj in objects or []:
            obj.select_set(True)
        bpy.ops.export_scene.gltf(filepath=path, use_selection=True, export_tangents=True,
            export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=6,
            export_draco_position_quantization=14, export_draco_normal_quantization=10,
            export_draco_texcoord_quantization=12, export_draco_color_quantization=10,
            export_draco_generic_quantization=10)
        return True
    return original_export(path, objects)


def activate_only(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.hide_set(False)
    obj.hide_viewport = False
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def clean_mesh(obj):
    # A fixed world-independent merge distance destroys small models and seams.
    # Imported glTF is already triangulated; remove only loose geometry without
    # recalculating authored normals, winding, UVs or color attributes.
    activate_only(obj)
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.delete_loose()
        bpy.ops.mesh.quads_convert_to_tris(quad_method='BEAUTY', ngon_method='BEAUTY')
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
    if not obj.data.polygons:
        raise ValueError('The model has no triangle surfaces after cleanup.')


MeshIO.load = staticmethod(load_material_groups)
MeshIO.export = staticmethod(export_preserving_attributes)
MeshPreprocessor._set_active_object = staticmethod(activate_only)
MeshPreprocessor.clean_and_fix = staticmethod(clean_mesh)

# Retain the complete imported shader graph. Rebaking onto overlapping/tiled UVs
# mixes unrelated surfaces; the upstream baker also cannot bake metallic or
# opacity and replaces unlit/extension materials. With UVs preserved, resampling
# existing images preserves all those properties without a lossy bake.
resolution = int(sys.argv[sys.argv.index('--image_resolution') + 1])
resized_images = {}


def analyze_material(obj):
    return set(), {'_source_material': obj.active_material}


def assemble_material(obj, tex_dir, uniform_props=None):
    source = (uniform_props or {}).get('_source_material')
    obj.data.materials.clear()
    if not source:
        # An absent glTF material has defined defaults; keep it absent.
        return
    material = source.copy()
    obj.data.materials.append(material)
    if not material.use_nodes:
        return
    for node in material.node_tree.nodes:
        if node.type != 'TEX_IMAGE' or not node.image:
            continue
        image = node.image
        if image not in resized_images:
            width, height = image.size
            if width <= 0 or height <= 0:
                raise ValueError(f'Texture {image.name!r} could not be decoded.')
            if max(width, height) > resolution:
                copy = image.copy()
                ratio = resolution / max(width, height)
                copy.scale(max(1, round(width * ratio)), max(1, round(height * ratio)))
                copy.pack()
                resized_images[image] = copy
            else:
                resized_images[image] = image
        node.image = resized_images[image]


TextureAnalyzer.analyze_mesh_materials = staticmethod(analyze_material)
MaterialAssembler.assemble_material = staticmethod(assemble_material)

geometry_checks = []
original_decimate = MeshDecimator.apply_decimate


def surface_tree(obj):
    mesh = bmesh.new()
    try:
        mesh.from_mesh(obj.data)
        mesh.transform(obj.matrix_world)
        return BVHTree.FromBMesh(mesh)
    finally:
        mesh.free()


def vertex_surface_distance(target, source):
    # The upstream reference is an unlinked object. Evaluating it through the
    # dependency graph can return stale geometry between decimation attempts.
    tree = surface_tree(source)
    distances = [tree.find_nearest(target.matrix_world @ vertex.co)[3] for vertex in target.data.vertices]
    if not distances or any(value is None for value in distances):
        raise ValueError('Cannot measure an empty or degenerate surface.')
    return max(distances)


MeshDecimator._calculate_hausdorff_one_sided = staticmethod(vertex_surface_distance)


def checked_decimate(obj, **kwargs):
    # Upstream accepts its last attempt even when it exceeds its error limit.
    # Check in both directions and keep the preceding mesh if reduction would
    # discard surface details. A larger correct result is preferable to damage.
    initial_faces = len(obj.data.polygons)
    target = kwargs.get('custom_target') if kwargs.get('preset') == 'CUSTOM' else MeshDecimator.PRESETS[kwargs.get('preset', 'MEDIUM')]
    if initial_faces <= target:
        return True
    original = obj.data.copy()
    points = [obj.matrix_world @ vertex.co for vertex in original.vertices]
    bounds = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    diagonal = (bounds[6] - bounds[0]).length
    source_tree = surface_tree(obj)
    try:
        if not original_decimate(obj, **kwargs):
            raise RuntimeError('Geometry optimization failed.')
        threshold = kwargs.get('hausdorf_threshold', 0.001) * diagonal
        result_tree = surface_tree(obj)
        for vertices, tree in ((points, result_tree),
                               ([obj.matrix_world @ v.co for v in obj.data.vertices], source_tree)):
            if any((hit := tree.find_nearest(point))[3] is None or hit[3] > threshold + 1e-9 for point in vertices):
                reduced = obj.data
                obj.data = original
                geometry_checks.append({'mesh': obj.name, 'status': 'retained', 'faces': initial_faces,
                                        'reason': 'Reduction exceeded the geometric error limit.'})
                if reduced.users == 0:
                    bpy.data.meshes.remove(reduced)
                return True
        geometry_checks.append({'mesh': obj.name, 'status': 'reduced' if len(obj.data.polygons) < initial_faces else 'retained', 'before_faces': initial_faces,
                                'after_faces': len(obj.data.polygons), 'vertex_surface_error_limit': threshold})
        return True
    finally:
        if original.users == 0:
            bpy.data.meshes.remove(original)


MeshDecimator.apply_decimate = staticmethod(checked_decimate)

prefs = bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type = 'CUDA'
prefs.get_devices()
if not any(device.type == 'CUDA' for device in prefs.devices):
    raise RuntimeError('No CUDA device is available. Use an active GPU allocation.')

runpy.run_path('/app/pipeline/core.py', run_name='__main__')

output = Path(sys.argv[sys.argv.index('--output') + 1])
(output / 'geometry_checks.json').write_text(json.dumps(geometry_checks, indent=2))
