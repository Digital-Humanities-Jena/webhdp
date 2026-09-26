"""Render with the pinned 3DGeoRef renderer and record the exact camera mapping."""
import importlib.util
import json
import sys
from pathlib import Path

import bpy
import numpy as np


def main():
    source, output = sys.argv[sys.argv.index('--') + 1:]
    output = Path(output)
    spec = importlib.util.spec_from_file_location('georef_multiview', '/app/pipeline/rendering/multiview.py')
    upstream = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(upstream)
    upstream.clear_scene()
    upstream.import_model(source)
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    center, size, _, _ = upstream.get_combined_bounding_box(meshes)
    if not meshes or not np.isfinite([*center, *size]).all() or min(size.x, size.y) <= 0:
        raise ValueError('The model has no usable horizontal footprint.')
    if max(size.x, size.y) / min(size.x, size.y) > 32:
        raise ValueError('The model footprint is too narrow for reliable image matching.')
    prefs = bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type = 'CUDA'
    prefs.get_devices()
    devices = [device for device in prefs.devices if device.type == 'CUDA']
    if not devices:
        raise RuntimeError('No CUDA GPU is available in the allocation.')
    for device in prefs.devices:
        device.use = device.type == 'CUDA'
    upstream.setup_hdri_lighting(upstream.HDRI_PATH)
    width, height = upstream.render_top_ortho_view_from_meshes(
        str(output / 'top_view.png'), pixel_density=1024/max(size.x, size.y), min_res=1, max_res=1024)
    camera = bpy.context.scene.camera
    frame = upstream.ortho_camera_corners(camera)
    left, right = min(p.x for p in frame), max(p.x for p in frame)
    bottom, top = min(p.y for p in frame), max(p.y for p in frame)
    sx, sy = width/(right-left), height/(top-bottom)
    # Blender imports glTF's Y-up coordinates as (x, -z, y).
    matrix = [[sx, 0, 0, -left*sx-0.5], [0, 0, sy, top*sy-0.5], [0, 0, 0, 1]]
    (output / 'camera.json').write_text(json.dumps({'model_to_pixel': matrix, 'size': [width, height]}))


if __name__ == '__main__':
    main()
