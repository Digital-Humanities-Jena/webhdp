"""Build the original CC0 demo meshes, textures, thumbnails and upload archives."""

from __future__ import annotations

import csv
from io import BytesIO, StringIO
import json
import math
from pathlib import Path
import random
import struct
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from PIL import Image, ImageDraw, ImageFilter


DIRECTORY = Path(__file__).parent
CREATOR = "Digital Humanities Jena"
LICENSE = "cc0-1.0"


def material_texture(style):
    size = 160
    texture = Image.new("RGB", (size, size))
    random_source = random.Random(307)
    for y in range(size):
        for x in range(size):
            if style == "clay":
                wave = y + 3 * math.sin(x * math.tau / 20)
                color = (105, 50, 37) if 33 < wave < 46 or 115 < wave < 124 else (189, 95, 60)
                if 59 < y < 102 and math.sin(x * math.tau / 20) + math.cos(y * math.tau / 27) > .9:
                    color = (220, 147, 87)
            elif style == "glaze":
                wave = y + 2 * math.sin(x * math.tau / 40)
                if 17 < wave < 32 or 113 < wave < 126:
                    color = (42, 70, 103)
                elif 34 < wave < 43 or 106 < wave < 111:
                    color = (177, 132, 65)
                elif 55 < wave < 100 and math.sin(x * math.tau / 20 + y / 15) > .55:
                    color = (228, 222, 190)
                else:
                    color = (73, 136, 139)
            else:
                u, v = x / size - .5, y / size - .5
                radius, angle = math.hypot(u, v), math.atan2(v, u)
                edge = max(abs(u), abs(v))
                if edge > .465 or .42 < edge < .435:
                    color = (32, 79, 88)
                elif edge > .397:
                    color = (200, 151, 87)
                elif radius < .055:
                    color = (210, 151, 68)
                elif .10 < radius < .19 + .07 * math.cos(8 * angle):
                    color = (35, 96, 108)
                elif abs(abs(u) - .32) + abs(abs(v) - .32) < .07:
                    color = (164, 87, 54)
                else:
                    color = (228, 214, 178)
            wear = random_source.randint(-7, 7)
            texture.putpixel((x, y), tuple(value + wear for value in color))
    return texture


def lathe(profile, steps=48):
    vertices, uvs, triangles = [], [], []
    for ring, (radius, height) in enumerate(profile):
        for side in range(steps + 1):
            angle = math.tau * side / steps
            vertices.append((radius * math.cos(angle), height, radius * math.sin(angle)))
            uvs.append((side / steps, ring / (len(profile) - 1)))
    for ring in range(len(profile) - 1):
        for side in range(steps):
            left = ring * (steps + 1) + side
            right = left + steps + 1
            triangles.extend([(left, right, right + 1), (left, right + 1, left + 1)])
    return vertices, uvs, triangles


def tile_mesh():
    divisions = 48
    vertices, uvs, triangles = [], [], []
    for row in range(divisions + 1):
        for column in range(divisions + 1):
            u, v = column / divisions, row / divisions
            vertices.append((2 * u - 1, .15, 2 * v - 1))
            uvs.append((u, v))
    for row in range(divisions):
        for column in range(divisions):
            start = row * (divisions + 1) + column
            below = start + divisions + 1
            triangles.extend([(start, below, start + 1), (below, below + 1, start + 1)])
    perimeter = [(-1, .15, -1), (1, .15, -1), (1, .15, 1), (-1, .15, 1)]
    for index, first in enumerate(perimeter):
        second = perimeter[(index + 1) % len(perimeter)]
        start = len(vertices)
        vertices.extend([first, second, (first[0], -.15, first[2]), (second[0], -.15, second[2])])
        uvs.extend([(0, 0)] * 4)
        triangles.extend([(start, start + 1, start + 2), (start + 1, start + 3, start + 2)])
    return vertices, uvs, triangles


def seal_mesh():
    mesh = lathe([(.67, 0), (.84, .06), (.87, .14), (.86, .25), (.81, .33), (.75, .37), (.012, .37)], steps=64)
    vertices, uvs, triangles = mesh
    center = len(vertices)
    vertices.append((0, .394, 0))
    uvs.append((.5, .5))
    for index in range(16):
        angle = math.tau * index / 16
        radius = .62 if index % 2 == 0 else .235
        vertices.append((math.sin(angle) * radius, .394, math.cos(angle) * radius))
        uvs.append((.5, .5))
        triangles.append((center, center + 1 + index, center + 1 + (index + 1) % 16))
    return vertices, uvs, triangles


def obj(mesh, material_path, title, *, inlay_height=None):
    vertices, uvs, triangles = mesh
    lines = [f"mtllib {material_path}", f"o {title}", "usemtl Surface", "s 1"]
    lines.extend("v " + " ".join(f"{value:.6f}" for value in vertex) for vertex in vertices)
    lines.extend(f"vt {u:.6f} {1 - v:.6f}" for u, v in uvs)
    material = "Surface"
    for triangle in triangles:
        next_material = "Inlay" if inlay_height and all(vertices[index][1] > inlay_height for index in triangle) else "Surface"
        if material != next_material:
            lines.append(f"usemtl {next_material}")
            material = next_material
        lines.append("f " + " ".join(f"{index + 1}/{index + 1}" for index in triangle))
    return ("\n".join(lines) + "\n").encode()


def gltf(mesh):
    vertices, uvs, triangles = mesh
    positions = b"".join(struct.pack("<3f", *vertex) for vertex in vertices)
    texcoords = b"".join(struct.pack("<2f", *uv) for uv in uvs)
    indices = b"".join(struct.pack("<3H", *triangle) for triangle in triangles)
    geometry = positions + texcoords + indices
    document = {
        "asset": {"version": "2.0", "generator": "WebHDP sample builder"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
        "meshes": [{"name": "Painted Floor Tile", "primitives": [{
            "attributes": {"POSITION": 0, "TEXCOORD_0": 1}, "indices": 2, "material": 0,
        }]}],
        "buffers": [{"uri": "buffers/tile.bin", "byteLength": len(geometry)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": offset, "byteLength": len(data), "target": target}
            for offset, data, target in [(0, positions, 34962), (len(positions), texcoords, 34962),
                                         (len(positions) + len(texcoords), indices, 34963)]
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(vertices), "type": "VEC3",
             "min": [min(values) for values in zip(*vertices)], "max": [max(values) for values in zip(*vertices)]},
            {"bufferView": 1, "componentType": 5126, "count": len(uvs), "type": "VEC2"},
            {"bufferView": 2, "componentType": 5123, "count": len(triangles) * 3, "type": "SCALAR"},
        ],
        "materials": [{"pbrMetallicRoughness": {
            "baseColorTexture": {"index": 0}, "roughnessFactor": .78, "metallicFactor": 0,
        }, "doubleSided": True}],
        "textures": [{"source": 0}], "images": [{"uri": "surface/floor-tiel.png"}],
    }
    return (json.dumps(document, indent=2) + "\n").encode(), geometry


def png(image):
    data = BytesIO()
    image.save(data, format="PNG", optimize=True)
    return data.getvalue()


def thumbnail(mesh, texture, background, side_color, *, camera):
    """Render the same fixture triangles with an orthographic camera."""
    width, height = 640, 360
    canvas = Image.new("RGB", (width, height), background)
    vertices, uvs, triangles = mesh
    azimuth, elevation = camera
    ca, sa = math.cos(azimuth), math.sin(azimuth)
    ce, se = math.cos(elevation), math.sin(elevation)
    turned = [(ca * x - sa * z, y, sa * x + ca * z) for x, y, z in vertices]
    view = [(x, ce * y - se * z, se * y + ce * z) for x, y, z in turned]
    bounds = [(min(axis), max(axis)) for axis in list(zip(*view))[:2]]
    scale = min(430 / (bounds[0][1] - bounds[0][0]), 272 / (bounds[1][1] - bounds[1][0]))
    mid_x, mid_y = [(low + high) / 2 for low, high in bounds]
    xy = [(width / 2 + (x - mid_x) * scale, height / 2 - 5 - (y - mid_y) * scale) for x, y, _ in view]
    shadow = Image.new("L", canvas.size)
    shadow_y = min(height - 42, max(y for _, y in xy) - 5)
    ImageDraw.Draw(shadow).ellipse((width / 2 - 150, shadow_y - 5, width / 2 + 150, shadow_y + 17), fill=65)
    canvas.paste(tuple(max(0, value - 85) for value in background), (0, 0), shadow.filter(ImageFilter.GaussianBlur(19)))
    draw = ImageDraw.Draw(canvas)
    def drawing_depth(indices):
        inlay = not texture and all(vertices[index][1] > .39 for index in indices)
        return inlay, sum(view[index][2] for index in indices)

    for face in sorted(triangles, key=drawing_depth):
        a, b, c = [view[index] for index in face]
        first, second = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
        normal = [first[(i + 1) % 3] * second[(i + 2) % 3] - first[(i + 2) % 3] * second[(i + 1) % 3] for i in range(3)]
        length = math.sqrt(sum(value * value for value in normal))
        if length == 0:
            continue
        light = .63 + .37 * abs(sum(value * direction for value, direction in zip(normal, (-.36, .70, .61))) / length)
        u, v = [sum(uvs[index][axis] for index in face) / 3 for axis in range(2)]
        if texture and (texture[1] == "clay" or u or v):
            image = texture[0]
            color = image.getpixel((int(u * (image.width - 1)), int(v * (image.height - 1))))
        elif texture:
            color = side_color
        elif all(vertices[index][1] > .39 for index in face):
            color = (195, 147, 83)
        else:
            color = side_color
        draw.polygon([xy[index] for index in face], fill=tuple(round(value * light) for value in color))
    return canvas


def sample(identifier, title, description, layout, texture_status, model, files, picture):
    data = StringIO(newline="")
    writer = csv.writer(data)
    writer.writerow(["filename", "title", "description", "creator", "license", "keywords", "language"])
    writer.writerow([model, title, description, CREATOR, LICENSE, "3D model, cultural heritage, WebHDP sample", "eng"])
    filename, preview = identifier + ".zip", identifier + ".png"
    with ZipFile(DIRECTORY / filename, "w") as bundle:
        for name, content in sorted({**files, "metadata.csv": data.getvalue().encode("utf-8")}.items()):
            entry = ZipInfo(name)
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            bundle.writestr(entry, content, compress_type=ZIP_DEFLATED, compresslevel=9)
    (DIRECTORY / preview).write_bytes(png(picture))
    return dict(id=identifier, title=title, description=description, layout=layout, texture_status=texture_status,
                filename=filename, format=Path(model).suffix[1:], preview=preview, creator=CREATOR, license=LICENSE)


def batch(samples):
    filename = "three-model-batch.zip"
    metadata = StringIO(newline="")
    rows = []
    with ZipFile(DIRECTORY / filename, "w", compression=ZIP_DEFLATED, compresslevel=9) as target:
        for item in samples:
            prefix = item["id"] + "/"
            with ZipFile(DIRECTORY / item["filename"]) as source:
                row = next(csv.DictReader(source.read("metadata.csv").decode().splitlines()))
                row["filename"] = prefix + row["filename"]
                rows.append({"sample_id": item["id"], **row})
                for name in source.namelist():
                    if name != "metadata.csv":
                        entry = ZipInfo(prefix + name)
                        entry.create_system = 3
                        entry.external_attr = 0o100644 << 16
                        target.writestr(entry, source.read(name), compress_type=ZIP_DEFLATED, compresslevel=9)
        fields = [key for key in rows[0] if key != "sample_id"]
        writer = csv.DictWriter(metadata, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        target.writestr(ZipInfo("metadata.csv"), metadata.getvalue().encode("utf-8"))
    return {"id": "three-model-batch", "title": "Three-model batch", "format": "batch", "filename": filename,
            "description": "Prepare the Glazed Bowl, Painted Floor Tile and Bronze Seal in one request.",
            "layout": "Three model folders and one shared metadata.csv", "license": LICENSE, "records": rows}


def build():
    clay = material_texture("clay")
    ceramic = material_texture("tile")
    vessel = lathe([(.40, 0), (.48, .04), (.49, .12), (.61, .19), (.70, .28), (.75, .41),
                    (.78, .57), (.77, .72), (.74, .84), (.67, .98), (.60, 1.09), (.58, 1.17),
                    (.61, 1.19), (.61, 1.24), (.54, 1.24), (.52, 1.19), (.56, 1.10), (.63, .97),
                    (.68, .83), (.70, .67), (.68, .50), (.61, .31), (.37, .14), (.035, .13)])
    tile = tile_mesh()
    seal = seal_mesh()
    glaze = material_texture("glaze")
    bowl = lathe([(.04, 0), (.38, 0), (.42, .035), (.41, .075), (.47, .13), (.65, .22), (.82, .34),
                  (.96, .45), (1.02, .51), (1.03, .54), (1.005, .57), (.975, .55), (.93, .49),
                  (.82, .38), (.66, .27), (.48, .17), (.32, .135), (.04, .125)])
    gltf_document, geometry = gltf(tile)
    datasets = [
        sample(
            "terracotta-vessel", "Terracotta Vessel", "A hand-built vessel model with ochre bands and a complete set of material files.",
            "Deeply nested OBJ and MTL with a texture subfolder", "Complete texture paths", "vessel/export/geometry/vessel.obj",
            {"vessel/export/geometry/vessel.obj": obj(vessel, "vessel.mtl", "TerracottaVessel"),
             "vessel/export/geometry/vessel.mtl": b"newmtl Surface\nKd 0.78 0.41 0.29\nmap_Kd images/clay.png\n",
             "vessel/export/geometry/images/clay.png": png(clay)},
            thumbnail(vessel, (clay, "clay"), (235, 221, 200), (180, 110, 73), camera=(.43, .38)),
        ),
        sample(
            "painted-floor-tile", "Painted Floor Tile", "A glazed tile model with a transposed letter in its texture reference. WebHDP reconnects the correct image.",
            "glTF with separate binary and image folders", "One misspelled texture name", "tile/tile.gltf",
            {"tile/tile.gltf": gltf_document, "tile/buffers/tile.bin": geometry,
             "tile/surface/floor-tile.png": png(ceramic)},
            thumbnail(tile, (ceramic, "ceramic"), (219, 230, 223), (123, 86, 66), camera=(.43, .75)),
        ),
        sample(
            "bronze-seal", "Bronze Seal", "A stamped seal model without its surface texture. WebHDP keeps the geometry and uses the bronze material colour.",
            "Root-level OBJ and MTL, with optional texture absent", "One missing texture", "seal.obj",
            {"seal.obj": obj(seal, "seal.mtl", "BronzeSeal", inlay_height=.39),
             "seal.mtl": b"newmtl Surface\nKd 0.59 0.42 0.23\nKs 0.3 0.27 0.14\nNs 36\nmap_Kd maps/seal-patina.png\n"
                         b"newmtl Inlay\nKd 0.77 0.58 0.33\nKs 0.4 0.3 0.15\nNs 40\n"},
            thumbnail(seal, None, (215, 223, 230), (143, 101, 60), camera=(.47, .80)),
        ),
        sample(
            "glazed-bowl", "Glazed Bowl",
            "A shallow ceramic bowl with a moved glaze image and a damaged detail texture. WebHDP reconnects the glaze and omits the damaged map.",
            "OBJ and MTL with separate surface assets", "Moved glaze image and damaged detail map", "bowl.obj",
            {"bowl.obj": obj(bowl, "bowl.mtl", "GlazedBowl"),
             "bowl.mtl": b"newmtl Surface\nKd 0.39 0.62 0.63\nKs 0.23 0.27 0.28\nNs 35\n"
                         b"map_Kd original/bowl-glaze.png\nbump detail/bowl-detail.png\n",
             "surface/bowl-glaze.png": png(glaze),
             "detail/bowl-detail.png": png(Image.new("RGB", (16, 16), (128, 128, 128)))[:45]},
            thumbnail(bowl, (glaze, "glaze"), (220, 229, 229), (73, 136, 139), camera=(.47, .70)),
        ),
    ]
    datasets.append(batch([datasets[3], datasets[1], datasets[2]]))
    (DIRECTORY / "manifest.json").write_text(json.dumps({"datasets": datasets}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    build()
