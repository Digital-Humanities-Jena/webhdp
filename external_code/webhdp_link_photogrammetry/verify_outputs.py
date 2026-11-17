"""Independently decode a completed Link run's scientific artifacts.

This verifier does not import the reconstruction worker or regenerate geometry.
It reads PLY, glTF 2.0 and COLMAP binary records, checks ZIP fixity and compares
uploaded photograph bytes. The resulting evidence contains no local paths.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import struct
import zipfile

import numpy as np


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_ply(data):
    stream = io.BytesIO(data)
    require(stream.readline().strip() == b"ply", "Invalid PLY signature")
    elements, current, encoding = [], None, None
    for _ in range(1000):
        line = stream.readline().decode("ascii").strip().split()
        require(line, "Truncated PLY header")
        if line[0] == "format":
            encoding = line[1]
        elif line[0] == "element":
            current = {"name": line[1], "count": int(line[2]), "properties": []}
            require(0 <= current["count"] <= 100_000_000, "PLY element count exceeds limit")
            elements.append(current)
        elif line[0] == "property":
            require(current is not None, "PLY property has no element")
            current["properties"].append(line[1:])
        elif line[0] == "end_header":
            break
    else:
        raise ValueError("PLY header exceeds limit")
    require(encoding in {"binary_little_endian", "binary_big_endian", "ascii"}, "Unsupported PLY encoding")
    codes = {"char": "b", "int8": "b", "uchar": "B", "uint8": "B", "short": "h", "int16": "h",
             "ushort": "H", "uint16": "H", "int": "i", "int32": "i", "uint": "I", "uint32": "I",
             "float": "f", "float32": "f", "double": "d", "float64": "d"}
    endian = "<" if encoding == "binary_little_endian" else ">"
    def scalar(kind, tokens):
        code = codes[kind]
        if encoding == "ascii":
            return float(next(tokens)) if code in {"f", "d"} else int(next(tokens))
        return struct.unpack(endian + code, stream.read(struct.calcsize(code)))[0]
    vertices, faces = [], []
    for element in elements:
        for _ in range(element["count"]):
            tokens = iter(stream.readline().decode("ascii").split()) if encoding == "ascii" else None
            row = {}
            for prop in element["properties"]:
                if prop[0] == "list":
                    count = int(scalar(prop[1], tokens))
                    require(0 <= count <= 1_000_000, "PLY list exceeds limit")
                    row[prop[3]] = [scalar(prop[2], tokens) for _ in range(count)]
                else:
                    row[prop[1]] = scalar(prop[0], tokens)
            if element["name"] == "vertex":
                vertices.append([row[axis] for axis in "xyz"])
            elif element["name"] == "face":
                indices = row.get("vertex_indices", row.get("vertex_index"))
                require(indices is not None and len(indices) == 3, "Expected a triangle PLY mesh")
                faces.append(indices)
    require(not stream.read().strip(), "Unexpected trailing PLY payload")
    vertices, faces = np.asarray(vertices, dtype=float), np.asarray(faces, dtype=np.int64)
    require(vertices.ndim == 2 and vertices.shape[1] == 3 and len(vertices) > 0 and np.isfinite(vertices).all(), "Invalid PLY vertices")
    if len(faces):
        require(faces.min() >= 0 and faces.max() < len(vertices), "PLY face index escapes vertex array")
    return vertices, faces


def read_glb(data):
    magic, version, size = struct.unpack_from("<4sII", data)
    require((magic, version, size) == (b"glTF", 2, len(data)), "Invalid glTF 2.0 binary header")
    chunks, offset = {}, 12
    while offset < len(data):
        count, kind = struct.unpack_from("<I4s", data, offset)
        require(kind not in chunks and offset + 8 + count <= len(data), "Invalid GLB chunk")
        chunks[kind] = data[offset + 8: offset + 8 + count]
        offset += count + 8
    model, binary = json.loads(chunks[b"JSON"]), chunks[b"BIN\0"]
    require(len(model["buffers"]) == 1 and "uri" not in model["buffers"][0], "Expected self-contained GLB buffer")
    def accessor(identifier):
        item = model["accessors"][identifier]
        require("sparse" not in item, "Sparse accessor not expected")
        view = model["bufferViews"][item["bufferView"]]
        require(view.get("buffer", 0) == 0, "Unexpected buffer index")
        kind = {5120: "i1", 5121: "u1", 5122: "<i2", 5123: "<u2", 5125: "<u4", 5126: "<f4"}[item["componentType"]]
        width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[item["type"]]
        dtype, count = np.dtype(kind), item["count"]
        start = view.get("byteOffset", 0) + item.get("byteOffset", 0)
        stride = view.get("byteStride", dtype.itemsize * width)
        require(count > 0 and stride >= width * dtype.itemsize, "Invalid GLB accessor layout")
        end = start + (count - 1) * stride + width * dtype.itemsize
        require(end <= view.get("byteOffset", 0) + view["byteLength"] <= len(binary), "GLB accessor escapes buffer view")
        return np.ndarray((count, width), dtype=dtype, buffer=binary, offset=start, strides=(stride, dtype.itemsize)).copy()
    primitives = [primitive for mesh in model["meshes"] for primitive in mesh["primitives"]]
    require(len(primitives) == 1 and primitives[0].get("mode", 4) == 4, "Expected one triangle mesh in the derived GLB")
    primitive = primitives[0]
    vertices = accessor(primitive["attributes"]["POSITION"])
    indices = accessor(primitive["indices"]).ravel()
    require(len(indices) % 3 == 0 and indices.min() >= 0 and indices.max() < len(vertices), "Invalid GLB triangle indices")
    require(np.isfinite(vertices).all(), "GLB contains nonfinite positions")
    return vertices, indices.reshape((-1, 3))


def sparse_summary(images, points):
    image_stream, point_stream = io.BytesIO(images), io.BytesIO(points)
    registered, = struct.unpack("<Q", image_stream.read(8))
    names = []
    for _ in range(registered):
        header = struct.unpack("<idddddddi", image_stream.read(struct.calcsize("<idddddddi")))
        require(np.isfinite(header[1:8]).all() and abs(sum(value * value for value in header[1:5]) - 1) < 0.001, "Invalid recovered camera pose")
        name = bytearray()
        while True:
            value = image_stream.read(1)
            require(value and len(name) < 4096, "Invalid camera name")
            if value == b"\0":
                break
            name += value
        names.append(name.decode("utf8"))
        count, = struct.unpack("<Q", image_stream.read(8))
        require(len(image_stream.read(count * 24)) == count * 24, "Truncated camera observations")
    require(not image_stream.read(), "Trailing camera bytes")
    count, = struct.unpack("<Q", point_stream.read(8))
    errors = []
    for _ in range(count):
        row = struct.unpack("<QdddBBBd", point_stream.read(struct.calcsize("<QdddBBBd")))
        require(np.isfinite(row[1:4]).all() and np.isfinite(row[-1]) and row[-1] >= 0, "Invalid sparse point")
        errors.append(row[-1])
        track_count, = struct.unpack("<Q", point_stream.read(8))
        require(len(point_stream.read(track_count * 8)) == track_count * 8, "Truncated point tracks")
    require(count > 0 and not point_stream.read(), "Invalid sparse point inventory")
    return {"registeredImages": registered, "names": sorted(names), "sparsePoints": count,
            "meanReprojectionErrorPixels": float(np.mean(errors))}


def depth_summary(data):
    fields, offset = [], 0
    for _ in range(3):
        end = data.index(b"&", offset)
        fields.append(int(data[offset:end]))
        offset = end + 1
    width, height, channels = fields
    values = np.frombuffer(data[offset:], dtype="<f4")
    require(width > 0 and height > 0 and channels == 1 and len(values) == width * height, "Invalid geometric depth layout")
    require(np.isfinite(values).all() and np.count_nonzero(values > 0) > 0, "Geometric depth has no finite measurements")
    return {"width": width, "height": height, "positiveMeasurements": int(np.count_nonzero(values > 0))}


def verify(artifacts, original_captures, run_record):
    artifacts, original_captures = Path(artifacts), Path(original_captures)
    def local_file(name):
        exact = artifacts / name
        matches = [exact] if exact.is_file() else list(artifacts.glob("*-" + name))
        require(len(matches) == 1, "Missing or ambiguous downloaded artifact: " + name)
        return matches[0]
    run = json.loads(Path(run_record).read_text())
    require(run["status"] == "succeeded", "The new Link run did not succeed")
    transport = []
    for item in run["artifacts"]:
        data = local_file(item["name"]).read_bytes()
        require(len(data) == item["size"] and digest(data) == item["sha256"], "API artifact fixity mismatch")
        transport.append({"name": item["name"], "bytes": len(data), "sha256": digest(data)})
    report = json.loads(local_file("reconstruction-report.json").read_text())
    require(report["status"] == "complete" and report["elapsedSeconds"] > 0, "Invalid reconstruction completion")
    require(report["qa"]["status"] == "passed" and not report["qa"].get("override"), "The fixed quality gate did not pass")
    vertices, faces = read_ply(local_file("model.ply").read_bytes())
    glb_vertices, glb_faces = read_glb(local_file("model.glb").read_bytes())
    dense, cloud_faces = read_ply(local_file("fused.ply").read_bytes())
    require(len(cloud_faces) == 0, "Expected a fused point cloud")
    require(vertices.shape == glb_vertices.shape and np.allclose(vertices, glb_vertices, rtol=1e-6, atol=1e-6), "GLB positions differ from actual reconstructed PLY")
    require(np.array_equal(faces, glb_faces), "GLB triangles differ from actual reconstructed PLY")
    require(len(vertices) == report["meshVertices"] and len(faces) == report["meshTriangles"] and len(dense) == report["densePoints"], "Decoded geometry counts differ from report")
    captures = []
    for item in report["captures"]:
        require(PurePosixPath(item["originalName"]).name == item["originalName"], "Unsafe original capture name")
        actual = digest((original_captures / item["originalName"]).read_bytes())
        require(actual == item["sha256"], "Original photograph hash differs from new run input")
        captures.append({"name": item["originalName"], "sha256": actual})
    require(len(captures) == report["inputImages"] and len({row["name"] for row in captures}) == len(captures), "Invalid input inventory")
    with zipfile.ZipFile(local_file("reconstruction-package.zip")) as package:
        names = package.namelist()
        require(len(names) == len(set(names)) and all(not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts for name in names), "Unsafe ZIP entry")
        manifest = json.loads(package.read("manifest.json"))
        require(set(names) == set(manifest["files"]) | {"manifest.json"}, "ZIP inventory differs from contents")
        for name, item in manifest["files"].items():
            data = package.read(name)
            require(digest(data) == item["sha256"] and len(data) == item["bytes"], "ZIP artifact fixity mismatch: " + name)
        require(package.read("model.ply") == local_file("model.ply").read_bytes(), "ZIP mesh differs from returned mesh")
        sparse = sparse_summary(package.read("source-calibration/images.bin"), package.read("source-calibration/points3D.bin"))
        require(sparse["registeredImages"] == report["registeredImages"] and sparse["sparsePoints"] == report["sparsePoints"], "Recovered calibration counts differ from report")
        require(abs(sparse["meanReprojectionErrorPixels"] - report["meanReprojectionErrorPixels"]) < 1e-10, "Recomputed sparse error differs from report")
        depths = {PurePosixPath(name).name: depth_summary(package.read(name)) for name in names if name.startswith("depth_maps/")}
        require(len(depths) == report["registeredImages"], "Missing per-camera measured depths")
    from PIL import Image
    with Image.open(local_file("reconstruction-preview.png")) as preview:
        require(preview.format == "PNG" and preview.size == (1080, 430), "Unexpected preview format")
        pixels = np.asarray(preview.convert("RGB"))
        require(len(np.unique(pixels.reshape((-1, 3)), axis=0)) > 100, "Preview has insufficient image content")
    result = {
        "schemaVersion": 1, "verifiedAt": datetime.now(timezone.utc).isoformat(),
        "runId": run.get("id", run.get("run_id")), "status": "passed", "inputImages": len(captures),
        "registeredImages": sparse["registeredImages"], "sparsePoints": sparse["sparsePoints"],
        "meanReprojectionErrorPixels": sparse["meanReprojectionErrorPixels"],
        "meshVertices": len(vertices), "meshTriangles": len(faces), "densePoints": len(dense),
        "glbMatchesPly": True, "maxGLBPositionDifference": float(np.max(np.abs(vertices - glb_vertices))),
        "apiArtifactFixity": transport, "zipInventoryEntries": len(manifest["files"]),
        "zipInventoryVerified": True, "originalCaptureFixity": captures, "geometricDepths": depths,
        "cudaReported": report["cudaUsed"], "cudaEvidenceScope": "New run produced verified geometric depth maps; actual GPU allocation evidence is recorded separately by the central HPC service.",
        "nativeBundleSHA256": report["nativeBundleSHA256"], "nativeReceiptSHA256": report["nativeReceiptSHA256"],
        "preview": {"width": 1080, "height": 430, "decoded": True, "visualReview": "pending"},
        "independentParser": "PLY, GLB and COLMAP binary records decoded without importing the reconstruction worker or its geometry exporter.",
        "limitations": ["This validates byte integrity and reconstruction consistency, not independent metric accuracy or physical scale."],
    }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--original-captures", required=True)
    parser.add_argument("--run-record", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    evidence = verify(args.artifacts, args.original_captures, args.run_record)
    Path(args.output).write_text(json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({key: evidence[key] for key in ("runId", "status", "registeredImages", "sparsePoints", "meshVertices", "meshTriangles", "densePoints")}, sort_keys=True))


if __name__ == "__main__":
    main()
