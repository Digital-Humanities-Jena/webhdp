"""Make a known-coordinate reference from an independently rendered real model.

This checks large scene handling and transformation recovery, not accuracy against
an independently surveyed orthophoto. The input model stays outside the repository.
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import rasterio
from rasterio.transform import from_origin


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    camera = json.loads((args.render/'camera.json').read_text())
    image = cv2.imread(str(args.render/'top_view.png'), cv2.IMREAD_UNCHANGED)
    rgb = cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2RGB)
    rgb[image[:, :, 3] < 128] = [60, 60, 60]
    # Change illumination and soften details to avoid an exact pixel-copy test.
    rgb = cv2.GaussianBlur(np.clip(rgb.astype(float)*0.8+25, 0, 255).astype('uint8'), (3, 3), .6)
    image_h, image_w = image.shape[:2]
    matrix = cv2.getRotationMatrix2D(((image_w-1)/2, (image_h-1)/2), 17, .70)
    matrix[:, 2] += [599.5-(image_w-1)/2, 599.5-(image_h-1)/2]
    pixels = cv2.warpAffine(rgb, matrix, (1200, 1200), borderValue=(60, 60, 60))
    mpp = 1/(camera['model_to_pixel'][0][0]*.70)
    args.output.mkdir(parents=True, exist_ok=True)
    with rasterio.open(args.output/'site.tif', 'w', driver='GTiff', width=1200, height=1200, count=3,
        dtype='uint8', crs='EPSG:32632', transform=from_origin(600000, 5600000, mpp, mpp)) as target:
        target.write(np.moveaxis(pixels, -1, 0))
    (args.output/'case.json').write_text(json.dumps({'name': args.output.name, 'expected_success': True,
        'angle': 17, 'expected_anchor': [600000+600*mpp, 5600000-600*mpp], 'expected_scale': 1.0}, indent=2))


if __name__ == '__main__':
    main()
