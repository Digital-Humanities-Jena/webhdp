"""Small, real processors used by the WebHDP-Link reference applications.

Only an administrator configures this executable and the HMSM installation.
Requests supply data and declared scientific parameters, never executable code.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import zipfile


MAX_INPUT_BYTES = 128 * 1024 * 1024


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def hmsm_source_digest(root):
    checksum = hashlib.sha256()
    for path in sorted((Path(root) / "backend/studio").glob("*.py")):
        checksum.update(path.name.encode())
        checksum.update(path.read_bytes())
    return checksum.hexdigest()


def source_file(value):
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Input must be a regular staged file.")
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("An example input may not exceed 128 MiB.")
    return path.resolve()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def _image(path):
    from PIL import Image, ImageOps
    # Bound decoded images as well as transport size. No image is fetched by URL.
    with Image.open(path) as source:
        if source.width * source.height > 40_000_000 or getattr(source, "n_frames", 1) != 1:
            raise ValueError("Use a single image containing at most 40 million pixels.")
        return ImageOps.exif_transpose(source).convert("RGB")


def photo_preparation(input_files, output, max_side=320):
    from PIL import Image, ImageDraw, ImageStat
    if not isinstance(max_side, int) or isinstance(max_side, bool) or not 64 <= max_side <= 1024:
        raise ValueError("max_side must be an integer from 64 to 1024.")
    if not isinstance(input_files, list) or not 1 <= len(input_files) <= 64:
        raise ValueError("Supply between one and 64 photographs.")
    paths = [source_file(item) for item in input_files]
    if len({path.name for path in paths}) != len(paths):
        raise ValueError("Each photograph needs a distinct filename.")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    columns = min(4, len(paths))
    rows = math.ceil(len(paths) / columns)
    # Keep even the largest allowed contact sheet below 20 million pixels.
    side = min(max_side, int(math.sqrt(20_000_000 / (columns * rows))) - 32)
    sheet = Image.new("RGB", (columns * (side + 16), rows * (side + 42)), "#eaf0f4")
    draw = ImageDraw.Draw(sheet)
    records = []
    for index, path in enumerate(paths):
        photo = _image(path)
        width, height = photo.size
        sha = digest(path)
        thumbnail = photo.copy()
        thumbnail.thumbnail((side, side))
        x, y = (index % columns) * (side + 16) + 8, (index // columns) * (side + 42) + 8
        sheet.paste(thumbnail, (x + (side - thumbnail.width) // 2, y + (side - thumbnail.height) // 2))
        label = path.name.encode("ascii", "replace").decode("ascii")[:38]
        draw.text((x, y + side + 4), label, fill="#183044")
        sample = photo.copy()
        sample.thumbnail((128, 128))
        records.append({"name": path.name, "bytes": path.stat().st_size, "sha256": sha,
                        "width": width, "height": height,
                        "mean_luminance": round(ImageStat.Stat(sample.convert("L")).mean[0], 2)})
        photo.close()
    warnings = []
    if len(paths) < 3:
        warnings.append("Fewer than three photographs; a reconstruction needs additional overlapping views.")
    if len({row["sha256"] for row in records}) != len(records):
        warnings.append("Duplicate photograph bytes were detected.")
    if any(min(row["width"], row["height"]) < 640 for row in records):
        warnings.append("Some photographs are small; these may be demonstration fixtures rather than reconstruction inputs.")
    report = {"schema_version": "1.0", "operation": "photo-preparation", "image_count": len(records),
              "photogrammetry_executed": False, "images": records, "warnings": warnings,
              "scope": "Decoded and oriented photographs, contact sheet, checksums, and a reconstruction handoff. No cameras or 3D geometry were estimated."}
    sheet.save(output / "contact-sheet.jpg", quality=88)
    write_json(output / "photo-report.json", report)
    write_json(output / "reconstruction-request.json", {
        "schema_version": "1.0", "backend": "colmap", "state": "prepared_not_executed",
        "source_images": [{key: row[key] for key in ("name", "sha256", "bytes")} for row in records],
        "recipe": {"schemaVersion": 1, "profile": "urn:reprojector:reconstruction-recipe:1",
                   "features": {"maxImageSize": 1600}, "dense": {"maxImageSize": 1600}},
        "operator_requirement": "Bind an installed Reprojector/COLMAP HDP Component to these files and validate the complete recipe on that worker. This handoff does not claim reconstruction readiness or geometric quality."})
    return report


def piano_digitization(input_file, output, hmsm_source, hmsm_python, model_id="generic_65_no_dynamics", roll_speed=6.0, expected_source_sha256=None):
    source = source_file(input_file)
    if model_id != "generic_65_no_dynamics":
        raise ValueError("This prototype exposes only the generic_65_no_dynamics carrier profile.")
    if not math.isfinite(roll_speed) or not 0.2 <= roll_speed <= 30:
        raise ValueError("roll_speed must be finite and between 0.2 and 30 feet per minute.")
    # Decode once before the full processor to bound malformed or oversized images.
    _image(source).close()
    root, python = Path(hmsm_source).resolve(), Path(hmsm_python).absolute()
    if not (root / "backend/studio/cli.py").is_file() or not python.is_file():
        raise ValueError("The administrator must configure an installed HMSM Studio runtime.")
    before = hmsm_source_digest(root)
    if expected_source_sha256 and before != expected_source_sha256:
        raise ValueError("HMSM source changed since component registration. Install a new component version.")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="webhdp-hmsm-") as temporary:
        # Avoid inheriting WebHDP/Zenodo credentials into a processing subprocess.
        environment = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT", "TMPDIR", "DYLD_FALLBACK_LIBRARY_PATH") if key in os.environ}
        environment.update(HMSM_DATA_DIR=str(Path(temporary) / "data"), VIPS_CONCURRENCY="2", OPENBLAS_NUM_THREADS="2", OMP_NUM_THREADS="2")
        command = [str(python), "-m", "backend.studio.cli", str(source), "--model", model_id,
                   "--output-name", "link-result", "--roll-speed", str(roll_speed)]
        completed = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True, timeout=300)
        if completed.returncode:
            # Native diagnostics may contain private paths. They are not public artifacts.
            raise ValueError("HMSM scan processing failed. Check the installed runtime and carrier image.")
        result_folder = Path(temporary) / "data/projects/link-result"
        native = json.loads((result_folder / "result.json").read_text())
        if hmsm_source_digest(root) != before or native.get("provenance", {}).get("software", {}).get("source_sha256") != before:
            raise ValueError("HMSM source changed during processing. Preserve the input and register a stable runtime.")
        note_fields = ("id", "pitch", "onset", "offset", "start", "end", "duration", "velocity", "confidence", "track", "time")
        notes = [{key: note[key] for key in note_fields if key in note} for note in native["notes"]]
        report = {"schema_version": "1.0", "operation": "hmsm-scan-digitization", "engine": "HMSM Studio",
                  "source": {"name": source.name, "sha256": digest(source)}, "model_id": model_id,
                  "roll_speed_fpm": roll_speed, "note_count": len(notes), "notes": notes,
                  "control_count": len(native.get("controls", [])), "duration_seconds": native.get("duration"),
                  "model_digest": native.get("provenance", {}).get("model_digest"),
                  "processor_sha256": digest(root / "backend/studio/extract.py"),
                  "software": native.get("provenance", {}).get("software"),
                  "limitations": native.get("limitations", []),
                  "scope": "Actual HMSM optical extraction and MIDI generation. Candidate notes require carrier-profile and historical review; synthetic fixtures demonstrate transport and execution."}
        for filename, relative in [("result.mid", "result.mid"), ("scan-preview.webp", "artifacts/source.webp"), ("track-preview.webp", "artifacts/tracks.webp")]:
            shutil.copyfile(result_folder / relative, output / filename)
        write_json(output / "piano-report.json", report)
    with zipfile.ZipFile(output / "piano-evidence.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename in ("result.mid", "piano-report.json", "scan-preview.webp", "track-preview.webp"):
            archive.write(output / filename, filename)
        archive.writestr("checksums.json", json.dumps({name: digest(output / name) for name in archive.namelist()}, indent=2))
    return report


def read_obj(path):
    vertices, faces = [], []
    with Path(path).open(encoding="utf-8-sig") as stream:
        for line_number, raw in enumerate(stream, 1):
            if len(raw) > 65536:
                raise ValueError("OBJ lines may not exceed 64 KiB.")
            row = raw.partition("#")[0].split()
            if not row:
                continue
            if row[0] == "v":
                if len(row) != 4:
                    raise ValueError("This example accepts three-dimensional OBJ vertices without vertex colors.")
                point = [float(value) for value in row[1:]]
                if not all(math.isfinite(value) and abs(value) <= 1e12 for value in point):
                    raise ValueError("OBJ coordinates must be finite and bounded.")
                vertices.append(point)
            elif row[0] == "f":
                if len(row) != 4:
                    raise ValueError("Triangulate the OBJ before upload; this example requires triangular faces.")
                face = []
                for token in row[1:]:
                    value = int(token.split("/")[0])
                    index = value - 1 if value > 0 else len(vertices) + value
                    if value == 0 or not 0 <= index < len(vertices):
                        raise ValueError(f"Invalid vertex index in OBJ line {line_number}.")
                    face.append(index)
                if len(set(face)) != 3:
                    raise ValueError("OBJ faces must contain three distinct vertices.")
                faces.append(face)
            elif row[0] in {"mtllib", "usemtl", "vt"}:
                raise ValueError("This geometry-only example does not accept materials or texture coordinates.")
            elif row[0] not in {"o", "g", "s", "vn"}:
                raise ValueError(f"Unsupported OBJ statement: {row[0]}.")
            if len(vertices) > 200_000 or len(faces) > 400_000:
                raise ValueError("The example supports up to 200,000 vertices and 400,000 triangles.")
    if len(vertices) < 3 or not faces:
        raise ValueError("OBJ must contain vertices and triangular faces.")
    return vertices, faces


def glb_bytes(vertices, faces):
    positions, normals = [], []
    for face in faces:
        a, b, c = [vertices[index] for index in face]
        u, v = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
        normal = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
        length = math.sqrt(sum(value * value for value in normal))
        if length < 1e-12:
            raise ValueError("Degenerate zero-area triangles are not supported.")
        for point in (a, b, c):
            positions.extend(point)
            normals.extend(value / length for value in normal)
    count = len(faces) * 3
    position_data = struct.pack("<" + "f" * len(positions), *positions)
    normal_data = struct.pack("<" + "f" * len(normals), *normals)
    indices = struct.pack("<" + "I" * count, *range(count))
    binary = position_data + normal_data + indices
    ranges = [(0, len(position_data), 34962), (len(position_data), len(normal_data), 34962), (len(position_data) + len(normal_data), len(indices), 34963)]
    model = {"asset": {"version": "2.0", "generator": "WebHDP-Link mesh preparation 1.0"},
             "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
             "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2, "mode": 4}]}],
             "buffers": [{"byteLength": len(binary)}],
             "bufferViews": [{"buffer": 0, "byteOffset": start, "byteLength": size, "target": target} for start, size, target in ranges],
             "accessors": [{"bufferView": 0, "componentType": 5126, "count": count, "type": "VEC3",
                            "min": [min(positions[axis::3]) for axis in range(3)], "max": [max(positions[axis::3]) for axis in range(3)]},
                           {"bufferView": 1, "componentType": 5126, "count": count, "type": "VEC3"},
                           {"bufferView": 2, "componentType": 5125, "count": count, "type": "SCALAR"}]}
    encoded = json.dumps(model, separators=(",", ":"), allow_nan=False).encode()
    encoded += b" " * (-len(encoded) % 4)
    binary += b"\0" * (-len(binary) % 4)
    return struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(binary)) + struct.pack("<I4s", len(encoded), b"JSON") + encoded + struct.pack("<I4s", len(binary), b"BIN\0") + binary


def mesh_package(input_file, output, target_extent=1.0, title="Model preparation"):
    source = source_file(input_file)
    if not math.isfinite(target_extent) or not .01 <= target_extent <= 1000:
        raise ValueError("target_extent must be finite and between 0.01 and 1000.")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200 or any(ord(c) < 32 for c in title):
        raise ValueError("title must contain one to 200 printable characters.")
    vertices, faces = read_obj(source)
    bounds = [[min(point[axis] for point in vertices) for axis in range(3)], [max(point[axis] for point in vertices) for axis in range(3)]]
    extent = max(bounds[1][axis] - bounds[0][axis] for axis in range(3))
    if extent <= 0:
        raise ValueError("The model has no spatial extent.")
    center = [(bounds[1][axis] + bounds[0][axis]) / 2 for axis in range(3)]
    scale = target_extent / extent
    normalized = [[(point[axis] - center[axis]) * scale for axis in range(3)] for point in vertices]
    edges = Counter(tuple(sorted(edge)) for face in faces for edge in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])))
    directed = Counter(edge for face in faces for edge in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])))
    boundary = sum(count == 1 for count in edges.values())
    nonmanifold = sum(count > 2 for count in edges.values())
    winding = sum(directed[(a, b)] == 2 or directed[(b, a)] == 2 for (a, b), count in edges.items() if count == 2)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "normalized.glb").write_bytes(glb_bytes(normalized, faces))
    report = {"schema_version": "1.0", "operation": "mesh-preparation", "title": title.strip(),
              "source": {"name": source.name, "sha256": digest(source)}, "vertices": len(vertices), "triangles": len(faces),
              "checks": {"boundary_edges": boundary, "nonmanifold_edges": nonmanifold, "inconsistent_winding_edges": winding,
                         "closed_consistent_edge_topology": boundary == nonmanifold == winding == 0},
              "transform": {"translation_before_scale": [-value for value in center], "uniform_scale": scale, "target_extent": target_extent, "units": "normalized units; no measured physical scale inferred"},
              "output_sha256": digest(output / "normalized.glb"), "publication_status": "prepared_not_uploaded",
              "required_before_deposition": ["creator names", "rights and license review", "scientific metadata review", "authenticated repository destination"],
              "scope": "Geometry-only triangular OBJ converted to glTF 2.0 GLB with flat normals. Topology counts do not prove manifold geometry, absence of self-intersections, or scientific fitness."}
    write_json(output / "mesh-report.json", report)
    write_json(output / "zenodo-metadata.json", {"metadata": {"title": title.strip(), "upload_type": "dataset", "description": "Geometry prepared through WebHDP-Link. Review the included provenance, rights and creator metadata before deposition."}})
    with zipfile.ZipFile(output / "model-package.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(source, "source.obj")
        for name in ("normalized.glb", "mesh-report.json", "zenodo-metadata.json"):
            archive.write(output / name, name)
        archive.writestr("checksums.json", json.dumps({"source.obj": digest(source), **{name: digest(output / name) for name in ("normalized.glb", "mesh-report.json", "zenodo-metadata.json")}}, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("photos", "piano", "mesh"))
    parser.add_argument("--input-file")
    parser.add_argument("--input-files", type=json.loads)
    parser.add_argument("--max-side", type=int, default=320)
    parser.add_argument("--model-id", default="generic_65_no_dynamics")
    parser.add_argument("--roll-speed", type=float, default=6.0)
    parser.add_argument("--hmsm-source")
    parser.add_argument("--hmsm-python")
    parser.add_argument("--hmsm-source-sha256")
    parser.add_argument("--expected-runner-sha256")
    parser.add_argument("--target-extent", type=float, default=1.0)
    parser.add_argument("--title", default="Model preparation")
    args = parser.parse_args()
    try:
        if args.expected_runner_sha256 and digest(__file__) != args.expected_runner_sha256:
            raise ValueError("Component code changed after registration. Install a new version.")
        if args.operation == "photos":
            photo_preparation(args.input_files, Path.cwd(), args.max_side)
        elif args.operation == "piano":
            if not args.hmsm_source or not args.hmsm_python:
                raise ValueError("An administrator must bind the HMSM source and Python runtime.")
            piano_digitization(args.input_file, Path.cwd(), args.hmsm_source, args.hmsm_python, args.model_id, args.roll_speed, args.hmsm_source_sha256)
        else:
            mesh_package(args.input_file, Path.cwd(), args.target_extent, args.title)
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        # Public diagnostics describe only the validation failure, never a traceback.
        parser.exit(1, f"Processing failed: {exc.__class__.__name__}: {str(exc) if isinstance(exc, ValueError) else 'Input or runtime could not be processed.'}\n")
    print(json.dumps({"status": "completed", "operation": args.operation}))


if __name__ == "__main__":
    main()
