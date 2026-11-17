#!/usr/bin/env python3
"""Reconstruct uploaded photographs with genuine, pinned Reprojector/COLMAP.

Invoked only by the trusted HPC-Link registry inside a Slurm allocation. The
request contains data and bounded scientific parameters, never executable paths.
The full reconstruction workspace remains private; only the declared portable
scientific artifacts are returned to the requesting application.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import struct
import sys
import zipfile


SOURCE_FILES = (
    "__init__.py", "colmap.py", "geometry.py", "lens.py", "recipes.py",
    "reconstruction.py", "reconstruction_quality.py", "stage_receipts.py",
    "feature_matching.py", "flexglue.py",
)
OUTPUTS = {
    "mesh": "model.ply", "model": "model.glb", "point_cloud": "fused.ply",
    "report": "reconstruction-report.json", "preview": "reconstruction-preview.png",
    "package": "reconstruction-package.zip",
}


def sha256(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def source_digest(source):
    """Hash only the complete, explicit scientific dependency closure."""
    source = Path(source)
    inventory = {name: sha256(source / "reprojector" / name) for name in SOURCE_FILES}
    return hashlib.sha256(json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n")


def bounded_parameters(raw):
    if not isinstance(raw, dict) or set(raw) - {"max_image_size", "mesher"}:
        raise ValueError("Only max_image_size and mesher are accepted.")
    size = raw.get("max_image_size", 960)
    if type(size) is not int or not 640 <= size <= 2400:
        raise ValueError("max_image_size must be an integer from 640 to 2400.")
    mesher = raw.get("mesher", "poisson")
    if mesher not in {"poisson", "delaunay"}:
        raise ValueError("mesher must be poisson or delaunay.")
    return {"max_image_size": size, "mesher": mesher}


def stage_inputs(request, input_root, workspace):
    from PIL import Image

    values = (request.get("inputs") or {}).get("input_files")
    if not isinstance(values, list) or not 3 <= len(values) <= 30:
        raise ValueError("Provide 3 to 30 overlapping photographs.")
    input_root = Path(input_root).resolve(strict=True)
    destination = Path(workspace) / "input/images"
    destination.mkdir(parents=True, exist_ok=False)
    captures, source_names, hashes = [], set(), {}
    Image.MAX_IMAGE_PIXELS = 80_000_000
    for index, raw in enumerate(values):
        if not isinstance(raw, str):
            raise ValueError("Every photograph must be a staged file path.")
        path = Path(raw)
        resolved = path.resolve(strict=True)
        if path.is_symlink() or not resolved.is_relative_to(input_root) or not resolved.is_file():
            raise ValueError("Photograph is outside the staged input directory.")
        if resolved.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            raise ValueError("Photographs must be JPEG or PNG.")
        if path.name in source_names:
            raise ValueError("Photograph filenames must be unique.")
        source_names.add(path.name)
        with Image.open(resolved) as image:
            if image.format not in {"JPEG", "PNG"} or image.width * image.height > 80_000_000:
                raise ValueError("Unsupported or oversized photograph.")
            dimensions = [image.width, image.height]
            image.verify()
        name = f"{index:04d}{resolved.suffix.lower()}"
        copied = destination / name
        shutil.copyfile(resolved, copied)
        fingerprint = sha256(copied)
        if fingerprint != sha256(resolved):
            raise ValueError("Photograph changed during input staging.")
        hashes[name] = fingerprint
        captures.append({"name": name, "originalName": path.name, "sha256": fingerprint,
                         "width": dimensions[0], "height": dimensions[1]})
    write_json(destination.parent / "capture-hashes.json", hashes)
    return captures


def build_recipe(parameters, allocation_job_id, cpus=4):
    from reprojector.recipes import normalize_recipe

    return normalize_recipe({
        "name": "WebHDP-Link genuine photograph reconstruction", "backend": "colmap",
        "features": {"maxImageSize": parameters["max_image_size"], "maximumFeatures": 8192},
        "dense": {"maxImageSize": parameters["max_image_size"], "geometricConsistency": True},
        "meshing": {"method": parameters["mesher"], "poissonDepth": 8},
        "qa": {"minimumRegisteredFraction": 0.75, "minimumRegisteredImages": 3,
               "maximumMeanReprojectionError": 4.0, "override": None},
        "executor": {"kind": "allocated", "allocationJobID": allocation_job_id,
                     "partition": "gpu", "gpuType": "gpu", "gpus": 1, "cpus": cpus,
                     "memoryGiB": 16, "hours": 12, "python": "python3", "colmap": "colmap"},
    })


def render_preview(cloud, target, camera_rotation=None):
    """Orthographic views of measured cloud points; no generated geometry."""
    import numpy as np
    from PIL import Image, ImageDraw

    points = np.asarray(cloud.vertices, dtype=float)
    if not len(points) or not np.isfinite(points).all():
        raise ValueError("Dense point cloud is empty or nonfinite.")
    stride = max(1, math.ceil(len(points) / 250_000))
    points = points[::stride]
    colors = np.asarray(cloud.colors)[::stride, :3] if hasattr(cloud, "colors") and len(cloud.colors) else np.tile([85, 147, 165], (len(points), 1))
    points = points - np.median(points, axis=0)
    if camera_rotation is not None:
        points = points @ np.asarray(camera_rotation).T
    image = Image.new("RGB", (1080, 430), "#101a24")
    draw = ImageDraw.Draw(image)
    draw.text((20, 16), "COLMAP reconstruction | measured dense points", fill="white")
    for panel, degrees in enumerate((-30, 0, 30)):
        angle = math.radians(degrees)
        rotation = np.array([[math.cos(angle), 0, math.sin(angle)], [0, 1, 0], [-math.sin(angle), 0, math.cos(angle)]])
        view = points @ rotation.T
        lower, upper = np.percentile(view[:, :2], [1, 99], axis=0)
        scale = min(325 / max(upper[0] - lower[0], 1e-12), 335 / max(upper[1] - lower[1], 1e-12))
        xy = (view[:, :2] - (upper + lower) / 2) * scale + [180, 220]
        pixels = np.rint(xy).astype(int)
        visible = (pixels[:, 0] >= 10) & (pixels[:, 0] < 350) & (pixels[:, 1] >= 50) & (pixels[:, 1] < 400)
        order = np.argsort(-view[:, 2], kind="stable")
        order = order[visible[order]]
        for point in order:
            x, y = pixels[point]
            draw.point((int(x) + panel * 360, int(y)), fill=tuple(int(v) for v in colors[point]))
        draw.text((panel * 360 + 20, 408), f"View {degrees:+d} degrees", fill="#becbda")
    image.save(target)


def publish_bundle(bundle_root, output_root, complete, captures, parameters, runtime, colmap_sha256, source_sha256):
    import numpy as np
    import trimesh
    from reprojector.colmap import quaternion_rotation
    from reprojector.reconstruction import validate_bundle

    bundle_root, output_root = Path(bundle_root), Path(output_root)
    bundle = validate_bundle(bundle_root)
    qa = json.loads((bundle_root / "pipeline/qa.json").read_text())
    if qa.get("status") != "passed" or qa.get("override"):
        raise ValueError("Only reconstructions passing the fixed quality gate can be published.")
    mesh = trimesh.load(bundle_root / "model.ply", force="mesh", process=False)
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0 or not np.isfinite(mesh.vertices).all():
        raise ValueError("COLMAP did not produce a finite triangle mesh.")
    cloud = trimesh.load(bundle_root / "fused.ply", process=False)
    if not hasattr(cloud, "vertices") or not len(cloud.vertices):
        raise ValueError("COLMAP did not produce a dense point cloud.")
    shutil.copyfile(bundle_root / "model.ply", output_root / OUTPUTS["mesh"])
    shutil.copyfile(bundle_root / "fused.ply", output_root / OUTPUTS["point_cloud"])
    mesh.export(output_root / OUTPUTS["model"], file_type="glb")
    with (bundle_root / "source-calibration/images.bin").open("rb") as stream:
        count, = struct.unpack("<Q", stream.read(8))
        if not count:
            raise ValueError("No camera can orient the reconstruction preview.")
        header = struct.unpack("<idddddddi", stream.read(struct.calcsize("<idddddddi")))
    render_preview(cloud, output_root / OUTPUTS["preview"], quaternion_rotation(header[1:5]))
    report = {
        "schemaVersion": 1, "profile": "urn:webhdp-link:photogrammetry-report:1",
        "status": "complete", "algorithm": "COLMAP SIFT, exhaustive matching, incremental SfM, geometric PatchMatch stereo, fusion and " + parameters["mesher"] + " meshing",
        "cudaUsed": True, "cudaEvidence": "Successful geometric PatchMatch stereo and nonempty geometric depth maps; COLMAP CUDA capability gate passed.",
        "inputImages": len(captures), "registeredImages": qa["registeredImages"],
        "registeredFraction": qa["registeredFraction"], "sparsePoints": qa["sparsePoints"],
        "densePoints": len(cloud.vertices), "meshVertices": len(mesh.vertices), "meshTriangles": len(mesh.faces),
        "meanReprojectionErrorPixels": qa["meanReprojectionErrorPixels"], "qa": qa,
        "parameters": parameters, "captures": captures, "runtime": runtime,
        "colmapSHA256": colmap_sha256, "reprojectorSourceSHA256": source_sha256,
        "nativeBundleSHA256": complete["bundleSHA256"], "nativeReceiptSHA256": complete["receiptSHA256"],
        "elapsedSeconds": complete["elapsedSeconds"], "coordinates": bundle["coordinates"],
        "limitations": ["Physical scale and independent accuracy are unmeasured.",
                        "GLB preserves reconstructed coordinates; it contains geometry without baked textures.",
                        "Preview projects measured dense points; extreme outer points may lie outside its view."],
    }
    report["artifacts"] = {name: {"path": filename, "sha256": sha256(output_root / filename)}
                           for name, filename in OUTPUTS.items() if name not in {"report", "package"}}
    write_json(output_root / OUTPUTS["report"], report)
    # A distinct, portable scientific package: never publish private stage logs,
    # runtime paths, source code, or scheduler/account identifiers.
    package_files = {filename: output_root / filename for name, filename in OUTPUTS.items() if name != "package"}
    for directory in ("sparse", "source-calibration", "depth_maps", "images"):
        for path in sorted((bundle_root / directory).rglob("*")):
            if path.is_file():
                package_files[str(path.relative_to(bundle_root))] = path
    package_files["rectification-map.json"] = bundle_root / "rectification-map.json"
    inventory = {name: {"sha256": sha256(path), "bytes": path.stat().st_size} for name, path in package_files.items()}
    manifest = {"schemaVersion": 1, "profile": "urn:webhdp-link:photogrammetry-package:1", "files": inventory,
                "originalCaptures": captures, "nativeBundleSHA256": complete["bundleSHA256"],
                "scope": "Derived scientific outputs. Original captures and private execution receipts remain in the native reconstruction workspace. Capture references in rectification-map.json are identified by SHA256 in originalCaptures."}
    with zipfile.ZipFile(output_root / OUTPUTS["package"], "w", zipfile.ZIP_DEFLATED, compresslevel=5) as archive:
        for name, path in package_files.items():
            archive.write(path, name)
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return report


def execute(request, *, input_root, output_root, source, expected_source_sha256, colmap, expected_colmap_sha256, cpus=4):
    source, colmap = Path(source).resolve(strict=True), Path(colmap).resolve(strict=True)
    if source_digest(source) != expected_source_sha256 or sha256(colmap) != expected_colmap_sha256:
        raise ValueError("The installed scientific runtime changed; a new reviewed component version is required.")
    allocation = os.environ.get("SLURM_JOB_ID", "")
    if not re.fullmatch(r"\d+", allocation):
        raise ValueError("Photogrammetry must run inside the centrally managed Slurm allocation.")
    if "CUDA_VISIBLE_DEVICES" in os.environ and not os.environ["CUDA_VISIBLE_DEVICES"].strip():
        raise ValueError("The scheduler did not assign a visible GPU.")
    parameters = bounded_parameters(request.get("parameters") or {})
    sys.path.insert(0, str(source))
    from reprojector.reconstruction import run_pipeline, validate_worker_runtime

    runtime = validate_worker_runtime()
    output_root = Path(output_root).resolve(strict=True)
    workspace = output_root / "private-reconstruction"
    workspace.mkdir(exist_ok=False)
    captures = stage_inputs(request, input_root, workspace)
    recipe = build_recipe(parameters, allocation, cpus)
    os.environ.update(OMP_NUM_THREADS=str(cpus), OPENBLAS_NUM_THREADS="1", QT_QPA_PLATFORM="offscreen")
    runtime["colmap"] = subprocess.run([str(colmap), "--help"], capture_output=True, text=True, check=True, timeout=60).stdout.splitlines()[0]
    complete = run_pipeline(workspace, recipe, [str(colmap)], {
        "executableSHA256": expected_colmap_sha256, "reprojectorSourceSHA256": expected_source_sha256,
        "allocationJobID": allocation, "workerRuntime": runtime,
    })
    bundle = (workspace / complete["bundlePath"]).resolve(strict=True)
    if not bundle.is_relative_to(workspace):
        raise ValueError("The reconstruction bundle escapes its private workspace.")
    report = publish_bundle(bundle, output_root, complete, captures, parameters, runtime, expected_colmap_sha256, expected_source_sha256)
    paths = {name: str(output_root / filename) for name, filename in OUTPUTS.items()}
    return {"success": True, "status": "completed", "outputs": paths,
            "artifacts": [{"name": name, "artifact_kind": "file", "path": path} for name, path in paths.items()],
            "summary": {key: report[key] for key in ("registeredImages", "inputImages", "sparsePoints", "densePoints", "meshVertices", "meshTriangles", "meanReprojectionErrorPixels", "cudaUsed")}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reprojector-source", required=True)
    parser.add_argument("--reprojector-source-sha256", required=True)
    parser.add_argument("--colmap", required=True)
    parser.add_argument("--colmap-sha256", required=True)
    parser.add_argument("--expected-runner-sha256", required=True)
    parser.add_argument("--cpus", type=int, default=4)
    args = parser.parse_args()
    response = Path(os.environ["WEBHDP_COMPONENT_RESPONSE"])
    try:
        if sha256(__file__) != args.expected_runner_sha256:
            raise ValueError("The installed component runner changed.")
        request = json.loads(Path(os.environ["WEBHDP_COMPONENT_REQUEST"]).read_text())
        result = execute(request, input_root=os.environ["WEBHDP_INPUT_DIR"], output_root=os.environ["WEBHDP_OUTPUT_DIR"],
                         source=args.reprojector_source, expected_source_sha256=args.reprojector_source_sha256,
                         colmap=args.colmap, expected_colmap_sha256=args.colmap_sha256, cpus=args.cpus)
    except Exception as error:
        # Native private logs retain details, while the structured response does
        # not reveal installed paths or usernames to an integrating application.
        import traceback
        traceback.print_exc()
        result = {"success": False, "status": "failed", "error": "Photogrammetry failed its runtime or reconstruction checks. The WebHDP operator can inspect the private step log.",
                  "error_type": type(error).__name__}
    write_json(response, result)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
