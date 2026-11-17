"""Render an actual validation mesh from reconstructed camera poses with Blender."""
import argparse
import json
import re
import sys
from pathlib import Path

import bpy
from mathutils import Matrix

parser = argparse.ArgumentParser()
parser.add_argument("--mesh", type=Path, required=True)
parser.add_argument("--cameras", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
args.output.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.wm.ply_import(filepath=str(args.mesh.resolve()))
mesh = bpy.context.object
material = bpy.data.materials.new("Measured vertex colors")
material.use_nodes = True
nodes = material.node_tree.nodes
shader = nodes.get("Principled BSDF")
shader.inputs["Roughness"].default_value = 0.8
if mesh.data.color_attributes:
    colors = nodes.new("ShaderNodeVertexColor")
    colors.layer_name = mesh.data.color_attributes[0].name
    material.node_tree.links.new(colors.outputs["Color"], shader.inputs["Base Color"])
mesh.data.materials.clear()
mesh.data.materials.append(material)
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 16
scene.cycles.use_denoising = True
scene.render.threads_mode = "FIXED"
scene.render.threads = 4
scene.render.resolution_x = 960
scene.render.resolution_y = 640
scene.render.resolution_percentage = 100
scene.world.use_nodes = True
scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (1, 1, 1, 1)
scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.8
scene.view_settings.view_transform = "Standard"
camera_data = bpy.data.cameras.new("Reconstructed camera")
camera = bpy.data.objects.new("Reconstructed camera", camera_data)
scene.collection.objects.link(camera)
scene.camera = camera
poses = json.loads(args.cameras.read_text())
for index in (0, len(poses) // 2, len(poses) - 1):
    pose = poses[index]
    rotation = Matrix(pose["rotation_world_to_camera"]).transposed()
    camera.rotation_euler = (rotation @ Matrix.Diagonal((1, -1, -1))).to_euler()
    camera.location = pose["center"]
    focal = float(re.search(r"focal_length = ([0-9.]+)", pose["camera"]).group(1))
    camera_data.sensor_width = 36
    camera_data.lens = focal * 36 / 960
    camera_data.clip_start = 0.01
    camera_data.clip_end = 1000
    scene.render.filepath = str((args.output / f"mesh-camera-{index + 1:02d}.png").resolve())
    bpy.ops.render.render(write_still=True)
