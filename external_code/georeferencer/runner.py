#!/usr/bin/env python3
"""HDP contract for 3DGeoRef's renderer and LoFTR reference-image alignment."""
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

if Path('/opt/webhdp/python').is_dir():
    sys.path.insert(0, '/opt/webhdp/python')

import cv2
import numpy as np

from geometry import fit_alignment, placement, write_placed_glb

ROOT = Path(__file__).resolve().parent
UPSTREAM_REVISION = 'e50e4562b43c0b105d77e417d01fedb5139529a6'


def glb_contract():
    # Package the same bounded preflight as Mesh Optimizer; no Blender imports.
    path = ROOT / 'glb_contract.py'
    if not path.exists():
        path = ROOT.parent / 'mesh_optimizer/runner.py'
    spec = importlib.util.spec_from_file_location('glb_preflight', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def input_path(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Select the model and its reference GeoTIFF.')
    path = Path(value)
    root = Path(os.environ.get('WEBHDP_INPUT_DIR', '/inputs')).resolve()
    if not path.is_absolute():
        path = root / path
    path = path.resolve(strict=True)
    if os.environ.get('WEBHDP_INPUT_DIR') and not path.is_relative_to(root):
        raise ValueError('Inputs must be staged inside the component input directory.')
    if not path.is_file():
        raise ValueError('An input file is missing.')
    return path


def resolve_inputs(request):
    if not isinstance(request, dict) or not isinstance(request.get('inputs'), dict):
        raise ValueError('The component request must contain inputs.')
    if request.get('parameters') not in (None, {}):
        raise ValueError('This component has no configurable parameters. Supply a model and reference image.')
    source = input_path(request['inputs'].get('input_file'))
    if source.suffix.lower() != '.glb':
        raise ValueError('Select a self-contained static GLB model.')
    references = request['inputs'].get('reference_files')
    if not isinstance(references, list) or any(not isinstance(item, str) for item in references):
        raise ValueError('Supply one reference GeoTIFF in the model bundle.')
    # Bundle lists also include the model, spreadsheet and related resources.
    candidates = sorted({str(input_path(item)) for item in references
                         if Path(item).suffix.lower() in {'.tif', '.tiff'}})
    if len(candidates) != 1:
        raise ValueError('Each model bundle must contain exactly one reference GeoTIFF (.tif or .tiff).')
    glb_contract().inspect_glb(source)
    return source, Path(candidates[0])


def read_reference(path):
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.windows import Window
    from pyproj import CRS
    # Reject VRT and other drivers that could read external files or URLs.
    with rasterio.open(path, driver='GTiff') as dataset:
        crs = CRS.from_user_input(dataset.crs) if dataset.crs else None
        if crs is None or not crs.is_projected or any(abs(axis.unit_conversion_factor-1) > 1e-9 for axis in crs.axis_info[:2]):
            raise ValueError('The reference needs a projected coordinate system measured in metres. Reproject the GeoTIFF before uploading.')
        if dataset.count not in {1, 3, 4} or any(dtype != 'uint8' for dtype in dataset.dtypes):
            raise ValueError('Use an 8-bit grayscale, RGB or RGBA orthophoto.')
        if min(dataset.width, dataset.height) < 64 or dataset.width * dataset.height > 100_000_000:
            raise ValueError('Reference dimensions must be at least 64 pixels per side and at most 100 million pixels.')
        if max(dataset.bounds.right-dataset.bounds.left, dataset.bounds.top-dataset.bounds.bottom) > 5000:
            raise ValueError('Crop the reference to a local area no larger than 5 km around the model.')
        scale = min(1, 1024 / max(dataset.width, dataset.height))
        width, height = max(8, math.ceil(dataset.width*scale)), max(8, math.ceil(dataset.height*scale))
        window = Window(0, 0, width/scale, height/scale)
        channels = [1] if dataset.count == 1 else [1, 2, 3]
        image = dataset.read(channels, window=window, boundless=True, fill_value=0,
                             out_shape=(len(channels), height, width), resampling=Resampling.bilinear)
        image = np.moveaxis(image, 0, -1)
        if len(channels) == 1:
            image = np.repeat(image, 3, axis=2)
        mask = dataset.dataset_mask(window=window, boundless=True, out_shape=(height, width), resampling=Resampling.nearest) > 0
        if mask.mean() < 0.25:
            raise ValueError('The reference has too little valid imagery.')
        image[~mask] = 0
        transform = dataset.transform * dataset.transform.scale(1/scale, 1/scale)
        matrix = np.array(transform).reshape(3, 3)
        if not np.isfinite(matrix).all() or abs(np.linalg.det(matrix)) < 1e-12:
            raise ValueError('The reference has an invalid coordinate transform.')
        # Keep square ground pixels: the read window pads the far edges rather
        # than stretching a non-square image to rounded display dimensions.
        original_scales = np.linalg.svd(np.array(dataset.transform).reshape(3, 3)[:2, :2], compute_uv=False)
        if original_scales[0] / original_scales[-1] > 1.00001:
            raise ValueError('The orthophoto must use square, orthogonal ground pixels. Reproject it before uploading.')
        return image, mask, matrix, crs


def inverse_rotation(points, turns, width, height):
    x, y = points[:, 0], points[:, 1]
    if turns == 1:
        return np.column_stack([width-1-y, x])
    if turns == 2:
        return np.column_stack([width-1-x, height-1-y])
    if turns == 3:
        return np.column_stack([y, height-1-x])
    return points


def match_images(render, reference, render_mask, reference_mask):
    import torch
    from kornia.feature import LoFTR
    if not torch.cuda.is_available():
        raise RuntimeError('A CUDA GPU is required for image matching.')
    checkpoint = ROOT / 'outdoor_ds.ckpt'
    if not checkpoint.is_file():
        raise RuntimeError('The installed component is missing its verified LoFTR weights.')
    # No downloads at execution time, and no external geolocation requests.
    model = LoFTR(pretrained=None)
    model.load_state_dict(torch.load(checkpoint, map_location='cpu', weights_only=True)['state_dict'])
    model = model.cuda().eval()
    def tensor(image):
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        h, w = gray.shape
        padded = np.pad(gray, ((0, -h % 8), (0, -w % 8)))
        return torch.from_numpy(padded.copy()).float()[None, None].cuda() / 255
    candidates = []
    reference_tensor = tensor(reference)
    h, w = render.shape[:2]
    for turns in range(4):
        print(f'Matching reference: orientation {turns+1}/4', flush=True)
        with torch.inference_mode():
            result = model({'image0': tensor(np.rot90(render, turns)), 'image1': reference_tensor})
        confidence = result['confidence'].cpu().numpy() >= 0.5
        source = inverse_rotation(result['keypoints0'].cpu().numpy()[confidence], turns, w, h)
        target = result['keypoints1'].cpu().numpy()[confidence]
        inside = ((source >= 0).all(axis=1) & (source <= [w-1, h-1]).all(axis=1)
                  & (target >= 0).all(axis=1) & (target <= [reference.shape[1]-1, reference.shape[0]-1]).all(axis=1))
        source, target = source[inside], target[inside]
        a, b = np.rint(source).astype(int), np.rint(target).astype(int)
        valid = render_mask[a[:, 1], a[:, 0]] & reference_mask[b[:, 1], b[:, 0]]
        try:
            matrix, quality = fit_alignment(source[valid], target[valid], (w, h), reference.shape[1::-1])
            candidates.append((matrix, quality))
        except ValueError as exc:
            print(f'Orientation {turns+1}: {len(source[valid])} candidate matches; {exc}', flush=True)
            continue
    if not candidates:
        raise ValueError('No reliable alignment found. Check the site, model orientation, texture detail and reference coverage.')
    candidates.sort(key=lambda item: item[1]['inliers'], reverse=True)
    best, quality = candidates[0]
    corners = np.array([[0, 0, 1], [w-1, 0, 1], [0, h-1, 1], [w-1, h-1, 1]])
    for alternative, other in candidates[1:]:
        if other['inliers'] >= 0.8*quality['inliers'] and np.max(np.linalg.norm(corners @ (best-alternative).T, axis=1)) > 10:
            raise ValueError('Several conflicting alignments are equally plausible. Use a more distinctive reference crop.')
    return best, quality


def digest(path):
    with path.open('rb') as stream:
        checksum = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            checksum.update(chunk)
        return checksum.hexdigest()


def execute(request):
    source, reference_path = resolve_inputs(request)
    reference, valid, pixel_to_map, crs = read_reference(reference_path)
    base = Path(os.environ.get('WEBHDP_OUTPUT_DIR', '/outputs'))
    base.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='georef-', dir=base))
    try:
        with tempfile.TemporaryDirectory(prefix='georef-work-') as scratch:
            scratch = Path(scratch)
            prepared = glb_contract().materialize_default_material(source, scratch / 'prepared.glb')
            print('Rendering the model footprint', flush=True)
            with (scratch / 'render.log').open('w') as log:
                process = subprocess.run(['blender', '-b', '--factory-startup', '--disable-autoexec',
                    '--python-exit-code', '1', '--python', str(ROOT / 'blender_entry.py'), '--',
                    str(prepared), str(scratch)], stdout=log, stderr=subprocess.STDOUT, timeout=900)
            if process.returncode:
                raise RuntimeError('Model rendering failed. Check that the model has a valid, upright textured mesh and that the allocation has a GPU.')
            camera = json.loads((scratch / 'camera.json').read_text())
            render = cv2.imread(str(scratch / 'top_view.png'), cv2.IMREAD_UNCHANGED)
            if render is None or render.ndim != 3 or render.shape[2] != 4 or list(render.shape[1::-1]) != camera['size']:
                raise ValueError('The renderer did not produce a valid footprint image.')
            render_mask = render[:, :, 3] >= 128
            rgb = cv2.cvtColor(render[:, :, :3], cv2.COLOR_BGR2RGB)
            rgb[~render_mask] = 0
            alignment, quality = match_images(rgb, reference, render_mask, valid)
            footprint = cv2.warpAffine(render_mask.astype('uint8'), alignment[:2], reference.shape[1::-1], flags=cv2.INTER_NEAREST).astype(bool)
            if not footprint.any() or valid[footprint].mean() < 0.95:
                raise ValueError('The reference contains missing imagery under the model footprint. Supply a complete orthophoto.')
            mapping = np.asarray(camera['model_to_pixel'])[:, [0, 2, 3]]
            center = np.linalg.solve(mapping, [render.shape[1]/2-0.5, render.shape[0]/2-0.5, 1])[:2]
            matrix, anchor, scale = placement(pixel_to_map, alignment, camera['model_to_pixel'], center)
            from pyproj import Transformer
            longitude, latitude = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True).transform(*anchor, errcheck=True)
            if not np.isfinite([longitude, latitude]).all() or not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
                raise ValueError('The resulting geographic coordinates are invalid.')
            metadata = {'crs': crs.to_string(), 'anchor_easting': float(anchor[0]), 'anchor_northing': float(anchor[1]),
                        'longitude': longitude, 'latitude': latitude,
                        'anchor_reference': 'Horizontal footprint centre of the model',
                        'local_axes': ['east', 'up', 'south'], 'units': 'metre',
                        'vertical_reference': 'Unassigned: heights are relative to the source model origin.',
                        'absolute_elevation': None}
            model = output / f'{source.stem}_georeferenced.glb'
            write_placed_glb(source, model, matrix, metadata)
            glb_contract().inspect_glb(model)
            quality['rmse_metres_upper_bound'] = float(quality['rmse_reference_pixels'] * np.linalg.svd(pixel_to_map[:2, :2], compute_uv=False)[0])
            report = output / 'georeferencing_report.json'
            report.write_text(json.dumps({'component': 'georeferencer', 'version': '1.0.0',
                'upstream_revision': UPSTREAM_REVISION, 'source': source.name, 'source_sha256': digest(source),
                'reference': reference_path.name, 'reference_sha256': digest(reference_path),
                'georeference': metadata, 'source_to_local_matrix': matrix.tolist(),
                'render_to_reference_matrix': alignment.tolist(), 'vertical_scale': scale, 'quality': quality,
                'review_required': True, 'accuracy_note': 'Image residuals measure matching consistency, not survey accuracy. Review the overlay and reference accuracy before reuse.'}, indent=2, allow_nan=False))
            warped = cv2.warpAffine(rgb, alignment[:2], reference.shape[1::-1])
            overlay = reference.copy()
            overlay[footprint] = (reference[footprint].astype(float)*0.5 + warped[footprint]*0.5).astype('uint8')
            contours, _ = cv2.findContours(footprint.astype('uint8'), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(overlay, contours, -1, (255, 210, 0), 2)
            preview = output / 'alignment_overlay.png'
            if not cv2.imwrite(str(preview), cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR)):
                raise RuntimeError('Could not write the alignment preview.')
            outputs = {'georeferenced_model': str(model), 'georeferencing_report': str(report), 'alignment_preview': str(preview)}
            return {'success': True, 'status': 'completed', 'outputs': outputs,
                    'artifacts': [{'artifact_kind': 'file', 'name': Path(value).name, 'remote_path': value,
                                   'metadata': {'component': 'georeferencer'}} for value in outputs.values()],
                    'logs': {'stdout': f'Alignment accepted: {quality["inliers"]} inliers. Review the overlay and coordinate report before reuse.', 'stderr': ''}}
    except Exception:
        import shutil
        shutil.rmtree(output)
        raise


def main():
    try:
        result = execute(json.loads(Path(os.environ['WEBHDP_COMPONENT_REQUEST']).read_text()))
    except Exception as exc:
        result = {'success': False, 'status': 'failed', 'error': str(exc), 'outputs': {}}
    Path(os.environ['WEBHDP_COMPONENT_RESPONSE']).write_text(json.dumps(result, allow_nan=False))
    return 0 if result['success'] else 1


if __name__ == '__main__':
    sys.exit(main())
