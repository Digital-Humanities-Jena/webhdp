"""Run the pinned upstream pipeline with strict GPU and baking checks."""
import runpy
import sys
from pathlib import Path

import bpy

sys.path.insert(0, '/app/pipeline')
from tex_baker import TextureAnalyzer, TextureBaker
from io_helper import MeshIO
from preprocess import MeshPreprocessor
from material_assembler import MaterialAssembler

original_load = MeshIO.load


def load_material_groups(path):
    objects = original_load(path)
    if Path(path).suffix.lower() not in {'.glb', '.gltf'}:
        return objects
    # Upstream groups by the first material slot. Split imported multi-material
    # meshes first so every face retains its own source material during baking.
    for obj in objects:
        if len({face.material_index for face in obj.data.polygons}) <= 1:
            continue
        obj.data = obj.data.copy()
        bpy.ops.object.select_all(action='DESELECT')
        obj.hide_set(False)
        obj.hide_viewport = False
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
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
    return objects


MeshIO.load = staticmethod(load_material_groups)
original_activate = MeshPreprocessor._set_active_object


def activate_only(obj):
    bpy.ops.object.select_all(action='DESELECT')
    original_activate(obj)


MeshPreprocessor._set_active_object = staticmethod(activate_only)

original_analyze = TextureAnalyzer.analyze_mesh_materials
original_assemble = MaterialAssembler.assemble_material


def analyze_material(obj):
    maps, uniforms = original_analyze(obj)
    material = obj.active_material
    if material and material.use_nodes:
        principled = next((node for node in material.node_tree.nodes if node.type == 'BSDF_PRINCIPLED'), None)
        if principled:
            # Preserve constant roughness instead of inventing it from AO.
            if not principled.inputs['Roughness'].is_linked:
                uniforms['ROUGHNESS'] = principled.inputs['Roughness'].default_value
            uniforms['_source_material'] = material
    return maps, uniforms


def assemble_material(obj, tex_dir, uniform_props=None):
    original_assemble(obj, tex_dir, uniform_props)
    source = (uniform_props or {}).get('_source_material')
    if not source:
        return
    target = obj.active_material
    source_bsdf = next(node for node in source.node_tree.nodes if node.type == 'BSDF_PRINCIPLED')
    target_bsdf = next(node for node in target.node_tree.nodes if node.type == 'BSDF_PRINCIPLED')
    cloned = {}

    def clone_node(node):
        if node in cloned:
            return cloned[node]
        copy = target.node_tree.nodes.new(node.bl_idname)
        cloned[node] = copy
        for prop in ('image', 'interpolation', 'extension', 'projection', 'operation', 'uv_map', 'vector_type', 'blend_type'):
            if hasattr(node, prop):
                setattr(copy, prop, getattr(node, prop))
        for index, socket in enumerate(node.inputs):
            if index >= len(copy.inputs):
                continue
            if hasattr(socket, 'default_value'):
                copy.inputs[index].default_value = socket.default_value
            for link in socket.links:
                parent = clone_node(link.from_node)
                target.node_tree.links.new(parent.outputs[list(link.from_node.outputs).index(link.from_socket)], copy.inputs[index])
        return copy

    # The upstream material assembler omits these glTF surface properties.
    # Alpha texture graphs keep the source UVs and embedded images intact.
    for name in ('Alpha', 'IOR', 'Transmission Weight', 'Coat Weight', 'Coat Roughness', 'Specular IOR Level'):
        if name not in source_bsdf.inputs or name not in target_bsdf.inputs:
            continue
        socket = source_bsdf.inputs[name]
        target_bsdf.inputs[name].default_value = socket.default_value
        for link in socket.links:
            node = clone_node(link.from_node)
            target.node_tree.links.new(node.outputs[list(link.from_node.outputs).index(link.from_socket)], target_bsdf.inputs[name])
    target.surface_render_method = source.surface_render_method
    target.use_backface_culling = source.use_backface_culling


TextureAnalyzer.analyze_mesh_materials = staticmethod(analyze_material)
MaterialAssembler.assemble_material = staticmethod(assemble_material)

# Select CUDA before enumerating devices; otherwise Blender can report only CPU.
prefs = bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type = 'CUDA'
prefs.get_devices()
if not any(device.type == 'CUDA' for device in prefs.devices):
    raise RuntimeError('No CUDA device is available. Use an active GPU allocation.')

# Upstream logs individual bake failures and continues. Partial textures are not
# acceptable artifacts, so propagate a failed bake to the component response.
original_bake = TextureBaker._run_bake_operation


def checked_bake(self, map_type):
    if not original_bake(self, map_type):
        raise RuntimeError(f'Texture baking failed for {map_type}.')
    return True


TextureBaker._run_bake_operation = checked_bake

original_bake_all = TextureBaker.bake_all


def bake_with_uvs(self, high_poly_obj, low_poly_obj, maps_list, base_output_path=None):
    # Solid-color CAD/architectural parts commonly have no UVs. Upstream also
    # bakes AO for these parts, which still requires a target UV layer.
    if not low_poly_obj.data.uv_layers:
        bpy.ops.object.select_all(action='DESELECT')
        low_poly_obj.select_set(True)
        bpy.context.view_layer.objects.active = low_poly_obj
        bpy.ops.object.mode_set(mode='EDIT')
        try:
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.smart_project(island_margin=0.02)
        finally:
            bpy.ops.object.mode_set(mode='OBJECT')
    return original_bake_all(self, high_poly_obj, low_poly_obj, maps_list, base_output_path)


TextureBaker.bake_all = bake_with_uvs
runpy.run_path('/app/pipeline/core.py', run_name='__main__')
