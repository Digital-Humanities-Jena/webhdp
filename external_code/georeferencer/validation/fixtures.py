"""Generate reproducible textured site fixtures with known projected placement."""
import argparse
import io
import json
import math
import struct
from pathlib import Path

import cv2
import numpy as np
import rasterio
from PIL import Image, ImageDraw
from rasterio.transform import from_origin


def texture(seed):
    rng = np.random.default_rng(seed)
    image = Image.fromarray(rng.integers(30, 90, (640, 800, 3), dtype='uint8'))
    draw = ImageDraw.Draw(image)
    for _ in range(150):
        x, y = rng.integers(0, 730), rng.integers(0, 570)
        w, h = rng.integers(10, 65, 2)
        color = tuple(int(n) for n in rng.integers(80, 240, 3))
        draw.rectangle((x+4, y+5, x+w+4, y+h+5), fill=(20, 25, 20))
        draw.rectangle((x, y, x+w, y+h), fill=color, outline=(250, 250, 220), width=2)
        draw.line((x, y, x+w, y+h), fill=(40, 50, 40), width=2)
    for y in (80, 230, 470):
        draw.line((0, y, 800, y+30), fill=(130, 135, 140), width=12)
    return image


def glb(path, image, translation=None, relief=False):
    buffer = bytearray(); views = []
    def append(data):
        buffer.extend(b'\0'*(-len(buffer)%4))
        views.append({'buffer': 0, 'byteOffset': len(buffer), 'byteLength': len(data)})
        buffer.extend(data)
        return len(views)-1
    if relief:
        xx, zz = np.meshgrid(np.linspace(-10, 10, 65), np.linspace(-8, 8, 65))
        yy = 1.5 + 1.2*np.sin(xx*.4)*np.cos(zz*.5)
        positions = np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()]).astype('<f4')
        uv = np.column_stack([(xx.ravel()+10)/20, (zz.ravel()+8)/16]).astype('<f4')
        indices = np.array([[row*65+col, (row+1)*65+col+1, row*65+col+1,
                             row*65+col, (row+1)*65+col, (row+1)*65+col+1]
                            for row in range(64) for col in range(64)], dtype='<u2').ravel()
    else:
        positions = np.array([[-10, 0, -8], [10, 0, -8], [10, 0, 8], [-10, 0, 8]], dtype='<f4')
        uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype='<f4')
        indices = np.array([0, 2, 1, 0, 3, 2], dtype='<u2')
    append(positions.tobytes())
    append(uv.tobytes())
    append(indices.tobytes())
    png = io.BytesIO(); image.save(png, format='PNG'); append(png.getvalue())
    document = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'TEXCOORD_0': 1}, 'indices': 2, 'material': 0}]}],
        'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': len(positions), 'type': 'VEC3',
                       'min': positions.min(axis=0).tolist(), 'max': positions.max(axis=0).tolist()},
                      {'bufferView': 1, 'componentType': 5126, 'count': len(uv), 'type': 'VEC2'},
                      {'bufferView': 2, 'componentType': 5123, 'count': len(indices), 'type': 'SCALAR'}],
        'buffers': [{'byteLength': len(buffer)}], 'bufferViews': views,
        'images': [{'bufferView': 3, 'mimeType': 'image/png'}], 'textures': [{'source': 0}],
        'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}, 'metallicFactor': 0, 'roughnessFactor': 1},
                       'extensions': {'KHR_materials_unlit': {}}}], 'extensionsUsed': ['KHR_materials_unlit']}
    if translation is not None:
        document['nodes'][0]['translation'] = translation
    payload = json.dumps(document).encode(); payload += b' '*(-len(payload)%4)
    buffer.extend(b'\0'*(-len(buffer)%4))
    path.write_bytes(struct.pack('<4sIII4s', b'glTF', 2, 28+len(payload)+len(buffer), len(payload), b'JSON')+payload+struct.pack('<I4s', len(buffer), b'BIN\x00')+buffer)


def generate(root):
    root.mkdir(parents=True, exist_ok=True)
    cases = []
    for name, angle, seed, crs in [('north', 0, 42, 'EPSG:32632'), ('rotated', 31, 84, 'EPSG:32632'),
                                   ('quarter', 90, 95, 'EPSG:25832'), ('unicode_ä', 187, 19, 'EPSG:32732'),
                                   ('distant_origin', 0, 135, 'EPSG:32632'),
                                   ('grayscale', 45, 157, 'EPSG:32632'),
                                   ('relief', 23, 187, 'EPSG:32632'),
                                   ('mismatch', 0, 42, 'EPSG:32632')]:
        folder = root/name; folder.mkdir(exist_ok=True)
        image = texture(seed)
        glb(folder/'site.glb', image, [10000, 0, -20000] if name == 'distant_origin' else None, relief=name == 'relief')
        reference = texture(9999) if name == 'mismatch' else image
        theta = math.radians(angle); c, s = math.cos(theta), math.sin(theta)
        # Source texture pixel centres → reference pixel centres.
        affine = np.array([[c*.625, s*.625, 499.5-c*249.6875-s*199.6875],
                           [-s*.625, c*.625, 499.5+s*249.6875-c*199.6875]])
        pixels = cv2.warpAffine(np.array(reference), affine, (1000, 1000), borderValue=(40, 60, 40))
        bands = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)[None] if name == 'grayscale' else np.moveaxis(pixels, -1, 0)
        with rasterio.open(folder/'site.tif', 'w', driver='GTiff', width=1000, height=1000, count=len(bands),
            dtype='uint8', crs=crs, transform=from_origin(600000, 5600000, .04, .04)) as target:
            target.write(bands)
        cases.append({'name': name, 'expected_success': name != 'mismatch', 'angle': angle,
                      'expected_anchor': [600020, 5599980], 'expected_scale': 1.0})
    (root/'cases.json').write_text(json.dumps(cases, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('output', type=Path)
    generate(parser.parse_args().output)
