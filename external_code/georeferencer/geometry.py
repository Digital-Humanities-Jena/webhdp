"""Alignment checks and lossless glTF placement for the reference-image workflow."""
import json
import shutil
import struct

import cv2
import numpy as np


def fit_alignment(source, target, render_size, reference_size):
    source = np.asarray(source, dtype=np.float64).reshape(-1, 2)
    target = np.asarray(target, dtype=np.float64).reshape(-1, 2)
    if source.shape != target.shape or len(source) < 20 or not np.isfinite([source, target]).all():
        raise ValueError('Too few reliable image matches. Use a textured model and a reference covering the same site.')
    # Duplicate correspondences must not inflate confidence or fit statistics.
    _, indices = np.unique(np.round(source, 2), axis=0, return_index=True)
    source, target = source[indices], target[indices]
    # A similarity transform preserves the model's shape and is representable
    # by glTF TRS. General affine fits can introduce unsupported shear.
    affine, mask = cv2.estimateAffinePartial2D(source, target, method=cv2.RANSAC,
                                       ransacReprojThreshold=3.0, maxIters=10000, confidence=0.999)
    if affine is None or mask is None or not np.isfinite(affine).all():
        raise ValueError('No stable alignment could be calculated.')
    keep = mask.ravel().astype(bool)
    count = int(keep.sum())
    ratio = count / len(source)
    if count < 20 or ratio < 0.35:
        raise ValueError('Alignment rejected: too few consistent matches.')
    good = source[keep]
    coverage = abs(cv2.contourArea(cv2.convexHull(good.astype(np.float32)))) / np.prod(render_size)
    predicted = good @ affine[:, :2].T + affine[:, 2]
    errors = np.linalg.norm(predicted - target[keep], axis=1)
    rmse = float(np.sqrt(np.mean(errors ** 2)))
    if coverage < 0.10 or rmse > 2.5 or np.linalg.det(affine[:, :2]) <= 0:
        raise ValueError('Alignment rejected: matches are clustered, mirrored, or inaccurate.')
    corners = np.array([[0, 0], [render_size[0]-1, 0],
                        [render_size[0]-1, render_size[1]-1], [0, render_size[1]-1]])
    projected = corners @ affine[:, :2].T + affine[:, 2]
    margin = 3.0
    if (projected < -margin).any() or (projected > np.asarray(reference_size)-1+margin).any():
        raise ValueError('The reference does not cover the complete model footprint.')
    return np.vstack([affine, [0, 0, 1]]), {
        'inliers': count, 'matches': len(source), 'inlier_ratio': ratio,
        'render_coverage': float(coverage), 'rmse_reference_pixels': rmse,
        'p95_reference_pixels': float(np.percentile(errors, 95)),
    }


def placement(pixel_to_map, alignment, model_to_pixel, source_center=(0, 0)):
    """Return source glTF → local east/up/south and the projected anchor.

    Matrices act on column vectors. Rasterio uses pixel corners; feature
    coordinates use pixel centres, so the half-pixel offset is explicit.
    """
    centers = np.array([[1, 0, 0.5], [0, 1, 0.5], [0, 0, 1]])
    world = np.asarray(pixel_to_map) @ centers @ alignment @ np.asarray(model_to_pixel)
    horizontal = world[:2, [0, 2]]
    scales = np.linalg.svd(horizontal, compute_uv=False)
    if not np.isfinite(world).all() or scales[-1] <= 1e-10 or scales[0] / scales[-1] > 1.001:
        raise ValueError('Alignment would distort the model. Check that the model is upright and the reference is an orthophoto.')
    if np.linalg.det(horizontal) >= 0:
        raise ValueError('Alignment has an invalid axis orientation.')
    # Blender stores world-space camera corners as float32. Remove their tiny
    # numerical anisotropy, anchoring at the footprint centre so the correction
    # does not grow with a distant source origin. Never assign an elevation.
    center = np.asarray(source_center, dtype=float)
    anchor = horizontal @ center + world[:2, 3]
    vertical_scale = float(np.sqrt(scales.prod()))
    u, _, vh = np.linalg.svd(horizontal)
    world[:2, [0, 2]] = (u @ vh) * vertical_scale
    result = np.eye(4)
    result[0] = world[0]
    result[1] = [0, vertical_scale, 0, 0]
    result[2] = -world[1]
    result[0, 3], result[2, 3] = -(result[[0, 2]][:, [0, 2]] @ center)
    return result, anchor, vertical_scale


def write_placed_glb(source, destination, matrix, metadata):
    """Wrap scene roots; retain every binary byte, material and original node."""
    matrix = np.asarray(matrix, dtype=float)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise ValueError('Invalid model placement matrix.')
    with source.open('rb') as stream:
        stream.seek(12)
        size, _ = struct.unpack('<I4s', stream.read(8))
        document = json.loads(stream.read(size))
        nodes = document.setdefault('nodes', [])
        scenes = document.get('scenes')
        if not scenes:
            raise ValueError('The GLB must contain an explicit scene with mesh nodes.')
        for scene in scenes:
            roots = scene.get('nodes', [])
            if roots:
                index = len(nodes)
                nodes.append({'name': 'Georeference placement', 'children': roots,
                              'matrix': matrix.T.ravel().tolist()})
                scene['nodes'] = [index]
        extras = document['asset'].get('extras')
        # glTF permits arbitrary extras, including arrays and strings.
        if not isinstance(extras, dict):
            extras = {'source_extras': extras} if extras is not None else {}
        document['asset']['extras'] = {**extras, 'webhdp_georeference': metadata}
        payload = json.dumps(document, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
        payload += b' ' * (-len(payload) % 4)
        length = source.stat().st_size - size + len(payload)
        with destination.open('wb') as target:
            target.write(struct.pack('<4sIII4s', b'glTF', 2, length, len(payload), b'JSON'))
            target.write(payload)
            shutil.copyfileobj(stream, target)
