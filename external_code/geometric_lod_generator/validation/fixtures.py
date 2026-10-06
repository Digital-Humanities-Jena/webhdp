"""Additional CPU detail cases: blender -b -P fixtures.py -- INPUT_DIR."""
from pathlib import Path
import sys
import bpy

root = Path(sys.argv[sys.argv.index('--') + 1])
root.mkdir(parents=True, exist_ok=True)


def reset():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)


def export(name):
    bpy.ops.export_scene.gltf(filepath=str(root / (name + '.glb')), export_format='GLB')


reset()
bpy.ops.mesh.primitive_torus_add(major_segments=96, minor_segments=12, major_radius=1, minor_radius=0.006)
export('thin-torus')
reset()
bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24)
sphere = bpy.context.object
bpy.ops.mesh.primitive_cube_add(size=0.025, location=(3, 0, 0))
bpy.ops.object.select_all(action='SELECT')
bpy.context.view_layer.objects.active = sphere
bpy.ops.object.join()
export('disconnected-small-island')
reset()
bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.object
modifier = obj.modifiers.new('Hard edge bevel', 'BEVEL')
modifier.width = 0.05
modifier.segments = 4
bpy.ops.object.modifier_apply(modifier=modifier.name)
export('hard-edges')
