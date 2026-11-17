#!/usr/bin/env python3
"""Portable, evidence-producing historic reconstruction stages for WebHDP.

This is an independently implemented COLMAP baseline. It does not impersonate
upstream learned matching, semantic masking, or downloaded panorama evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import math
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import traceback
import warnings
import zipfile
from pathlib import Path, PurePosixPath

VERSION = "1.0.0"
SCHEMA = "webhdp.historic-dataset/1"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}
MAX_IMAGES = 1000
MAX_ARCHIVE_BYTES = 8 * 1024**3
MAX_ARCHIVE_FILES = 30000


def sha256(path):
    # MVS Anywhere's published PyTorch/PyTorch3D environment uses Python 3.10.
    # Stream large artifacts without requiring Python 3.11's file_digest API.
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return path


def staged_file(inputs, name, required=True):
    value = inputs.get(name)
    if value in (None, "") and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a staged file path.")
    root = Path(os.environ.get("WEBHDP_INPUT_DIR", "/inputs")).resolve(strict=True)
    path = root / value
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(f"{name} must be a regular file inside the staged input directory.")
    return resolved


def extract_archive(path, destination):
    """Extract bounded regular files only, never traversals, links or duplicates."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    seen, total = set(), 0
    with zipfile.ZipFile(path) as archive:
        if len(archive.infolist()) > MAX_ARCHIVE_FILES:
            raise ValueError("Archive contains too many entries.")
        for item in archive.infolist():
            raw = item.filename
            name = PurePosixPath(raw)
            mode = item.external_attr >> 16
            if (not raw or "\\" in raw or "\x00" in raw or name.is_absolute()
                    or any(part in {"..", "."} for part in raw.rstrip("/").split("/"))
                    or ":" in name.parts[0] or raw.casefold().rstrip("/") in seen
                    or (stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)))):
                raise ValueError("Archive contains unsafe or duplicate paths.")
            seen.add(raw.casefold().rstrip("/"))
            total += item.file_size
            if total > MAX_ARCHIVE_BYTES or item.file_size > 2 * 1024**3:
                raise ValueError("Archive exceeds the uncompressed size limit.")
            if item.flag_bits & 1:
                raise ValueError("Encrypted archives are not supported.")
            target = destination.joinpath(*name.parts)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
    return destination


def pack_archive(root, archive):
    root, archive = Path(root), Path(archive)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ValueError("Refusing to package a symbolic link.")
            if path.is_file():
                # Fixed ZIP timestamps make unchanged content reproducible.
                info = zipfile.ZipInfo(path.relative_to(root).as_posix(), (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                with path.open("rb") as source, output.open(info, "w", force_zip64=True) as target:
                    shutil.copyfileobj(source, target)
    return archive


def parameters(raw, specification):
    if not isinstance(raw, dict) or set(raw) - set(specification):
        raise ValueError("Unknown component parameters.")
    result = {}
    for name, (default, kind, limits) in specification.items():
        value = raw.get(name, default)
        if kind == "number":
            valid = type(value) in (int, float) and math.isfinite(value)
        else:
            valid = type(value) is kind
        if not valid:
            raise ValueError(f"Invalid type for {name}.")
        if isinstance(limits, tuple) and not limits[0] <= value <= limits[1]:
            raise ValueError(f"{name} must be between {limits[0]} and {limits[1]}.")
        if isinstance(limits, set) and value not in limits:
            raise ValueError(f"Unsupported value for {name}.")
        result[name] = value
    return result


def report(stage, output, values):
    return write_json(output / f"{stage}-report.json", {
        "schema": "webhdp.historic-report/1", "runtime_version": VERSION,
        "stage": stage, "implementation": "portable-colmap-baseline", **values,
    })


def prepare(inputs, raw, output):
    from PIL import Image, ImageOps
    p = parameters(raw, {"max_image_size": (1600, int, (256, 8192)), "jpeg_quality": (95, int, (50, 100))})
    if bool(inputs.get("input_file")) == bool(inputs.get("input_files")):
        raise ValueError("Provide input_file or input_files, exclusively.")
    sources = []
    if inputs.get("input_files"):
        values = inputs["input_files"]
        if not isinstance(values, list) or not 1 <= len(values) <= MAX_IMAGES:
            raise ValueError(f"Supply 1 to {MAX_IMAGES} images.")
        sources = [(staged_file({"image": value}, "image"), Path(value).name) for value in values]
    else:
        source = staged_file(inputs, "input_file")
        if source.suffix.lower() == ".zip":
            root = extract_archive(source, output / "source")
            sources = [(path, path.relative_to(root).as_posix()) for path in sorted(root.rglob("*"))
                       if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS and "__MACOSX" not in path.parts]
        else:
            sources = [(source, source.name)]
    if not 1 <= len(sources) <= MAX_IMAGES:
        raise ValueError(f"Supply 1 to {MAX_IMAGES} supported images.")
    original_names = [name for _, name in sources]
    if len(set(original_names)) != len(original_names):
        raise ValueError("Image names must be unique; use a ZIP with distinct relative paths.")
    dataset = output / "dataset"
    images = dataset / "images"
    images.mkdir(parents=True)
    records = []
    Image.MAX_IMAGE_PIXELS = 100_000_000
    for index, (source, original_name) in enumerate(sorted(sources, key=lambda item: item[1])):
        if source.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ValueError("Unsupported image extension.")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source) as image:
                if getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Multi-frame images must be split before reconstruction.")
                image.load()
                original_size = list(image.size)
                image = ImageOps.exif_transpose(image)
                image.thumbnail((p["max_image_size"],) * 2, Image.Resampling.LANCZOS)
                if "A" in image.getbands() or image.mode == "P":
                    rgba = image.convert("RGBA")
                    clean = Image.new("RGB", rgba.size, "white")
                    clean.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    clean = Image.new("RGB", image.size)
                    clean.paste(image.convert("RGB"))
                name = f"{index + 1:06d}.jpg"
                target = images / name
                clean.save(target, quality=p["jpeg_quality"], optimize=True)
                records.append({"name": name, "original_name": original_name, "source_sha256": sha256(source),
                                "sha256": sha256(target), "original_size": original_size, "size": list(clean.size)})
    manifest = {"schema": SCHEMA, "images": records, "preparation": p,
                "coordinate_frame": "unregistered", "metadata_removed": True}
    write_json(dataset / "dataset.json", manifest)
    result = report("prepare", output, {"image_count": len(records), "images": records, "parameters": p})
    return {"dataset": pack_archive(dataset, output / "prepared-dataset.zip"), "report": result}, {"image_count": len(records)}


def read_dataset(inputs, output):
    from PIL import Image
    root = extract_archive(staged_file(inputs, "input_file"), output / "dataset")
    manifest = json.loads((root / "dataset.json").read_text(encoding="utf-8"))
    records = manifest.get("images")
    if manifest.get("schema") != SCHEMA or not isinstance(records, list) or not 1 <= len(records) <= MAX_IMAGES:
        raise ValueError("Input must be a prepared historic dataset bundle.")
    names = set()
    for row in records:
        name = row.get("name", "")
        if (not isinstance(name, str) or not name or Path(name).name != name or "\\" in name
                or name in names or any(c.isspace() for c in name) or name.startswith(".")):
            raise ValueError("Dataset image names must be unique safe basenames without spaces.")
        path = root / "images" / name
        if not path.is_file() or sha256(path) != row.get("sha256"):
            raise ValueError(f"Dataset image fixity failed for {name}.")
        with Image.open(path) as image:
            if max(image.size) > 8192 or min(image.size) < 1 or image.width * image.height > 100_000_000:
                raise ValueError("Dataset image dimensions exceed preparation limits.")
            if row.get("size") is not None and list(image.size) != row["size"]:
                raise ValueError("Dataset image dimensions disagree with its manifest.")
            image.verify()
        names.add(name)
    actual = {path.name for path in (root / "images").iterdir() if path.is_file()}
    if actual != names:
        raise ValueError("Dataset contains unlisted image files.")
    return root, manifest


def haversine(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2)**2
    return 6371008.8 * 2 * math.asin(math.sqrt(min(1, h)))


def pairs(inputs, raw, output):
    p = parameters(raw, {"method": ("exhaustive", str, {"exhaustive", "gps"}),
                         "max_neighbors": (20, int, (1, 10000)), "radius_m": (1000, "number", (1, 10000000))})
    root, manifest = read_dataset(inputs, output)
    names = sorted(row["name"] for row in manifest["images"])
    if len(names) < 2:
        raise ValueError("Pair selection needs at least two images.")
    gps, selected = {}, set()
    if p["method"] == "exhaustive":
        selected.update(itertools.combinations(names, 2))
    else:
        raw_gps = json.loads(staged_file(inputs, "gps_file").read_text(encoding="utf-8"))
        if not isinstance(raw_gps, dict):
            raise ValueError("GPS JSON must map original or prepared image names to [latitude, longitude].")
        for row in manifest["images"]:
            value = raw_gps.get(row["name"], raw_gps.get(row["original_name"]))
            if (not isinstance(value, list) or len(value) != 2 or
                    any(type(v) not in (float, int) or not math.isfinite(v) for v in value)
                    or not -90 <= value[0] <= 90 or not -180 <= value[1] <= 180):
                raise ValueError(f"Missing or invalid GPS coordinates for {row['original_name']}.")
            gps[row["name"]] = value
        for first in names:
            neighbors = sorted((haversine(gps[first], gps[second]), second) for second in names if first != second)
            for distance, second in neighbors[:p["max_neighbors"]]:
                if distance <= p["radius_m"]:
                    selected.add(tuple(sorted((first, second))))
    if not selected:
        raise ValueError("Pair selection returned no pairs; increase the GPS radius.")
    pair_file = root / "pairs.txt"
    pair_file.write_text("".join(f"{a} {b}\n" for a, b in sorted(selected)), encoding="utf-8")
    isolated = sorted(set(names) - {name for pair in selected for name in pair})
    manifest["pair_selection"] = {**p, "pair_count": len(selected), "isolated_images": isolated,
                                  "pairs_sha256": sha256(pair_file)}
    if gps:
        write_json(root / "gps.json", gps)
    write_json(root / "dataset.json", manifest)
    result = report("pairs", output, manifest["pair_selection"])
    return {"dataset": pack_archive(root, output / "paired-dataset.zip"), "pairs": pair_file,
            "report": result}, {"pair_count": len(selected), "isolated_images": isolated}


def cpu_count():
    try:
        allocated = int(os.environ.get("SLURM_CPUS_PER_TASK", os.cpu_count() or 1))
    except ValueError:
        allocated = 1
    return max(1, min(8, allocated))


def load_pycolmap():
    try:
        import pycolmap
    except ImportError as exc:
        raise ValueError("Install the historic reconstruction runtime with pycolmap; the WebHDP server does not execute SfM itself.") from exc
    if not hasattr(pycolmap, "FeatureExtractionOptions"):
        raise ValueError("This runtime requires pycolmap 3.13 or newer.")
    return pycolmap


def selected_pairs(root, manifest):
    names = {row["name"] for row in manifest["images"]}
    path = root / "pairs.txt"
    if not path.exists():
        return sorted(itertools.combinations(sorted(names), 2))
    if manifest.get("pair_selection", {}).get("pairs_sha256") != sha256(path):
        raise ValueError("Pair selection fixity failed.")
    result = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        values = line.split()
        if len(values) != 2 or values[0] == values[1] or any(name not in names for name in values):
            raise ValueError("Pair file references an unknown image or invalid pair.")
        result.add(tuple(sorted(values)))
    if not result:
        raise ValueError("Pair file is empty.")
    return sorted(result)


def match_descriptors(first, second, block_size=256):
    """Bounded-memory SIFT cosine matching: ratio 0.8, distance 0.7, mutual check."""
    import numpy as np
    if len(first) < 2 or len(second) < 2:
        return np.empty((0, 2), dtype=np.uint32)
    first, second = np.asarray(first, dtype=np.float32), np.asarray(second, dtype=np.float32)
    first /= np.maximum(np.linalg.norm(first, axis=1, keepdims=True), 1e-12)
    second /= np.maximum(np.linalg.norm(second, axis=1, keepdims=True), 1e-12)
    candidates, reverse_dist = [], np.full(len(second), np.inf)
    reverse_idx = np.zeros(len(second), dtype=np.int64)
    for start in range(0, len(first), block_size):
        distances = np.maximum(0, 2 - 2 * first[start:start + block_size] @ second.T)
        ordered = np.argpartition(distances, 1, axis=1)[:, :2]
        for local, indexes in enumerate(ordered):
            indexes = indexes[np.argsort(distances[local, indexes])]
            best, next_best = indexes
            if distances[local, best] < 0.8**2 * distances[local, next_best] and distances[local, best] < 0.7**2:
                candidates.append((start + local, int(best)))
        local = np.argmin(distances, axis=0)
        minimum = distances[local, np.arange(len(second))]
        update = minimum < reverse_dist
        reverse_dist[update] = minimum[update]
        reverse_idx[update] = start + local[update]
    return np.asarray([(a, b) for a, b in candidates if reverse_idx[b] == a], dtype=np.uint32).reshape(-1, 2)


def prepare_masks(root, manifest, output):
    """Map upstream stem masks to COLMAP's filename-plus-PNG convention."""
    from PIL import Image
    if not (root / "masks").is_dir():
        return None, {}
    target = output / "colmap-masks"
    target.mkdir()
    hashes = {}
    for row in manifest["images"]:
        name = row["name"]
        source = root / "masks" / (Path(name).stem + ".png")
        if not source.is_file():
            raise ValueError("A semantic mask is required for every dataset image.")
        with Image.open(source) as mask, Image.open(root / "images" / name) as original:
            if mask.mode != "L" or mask.size != original.size:
                raise ValueError("Semantic masks must be grayscale and match the image dimensions.")
            colors = mask.getcolors(maxcolors=3)
            if colors is None or any(value not in (0, 255) for _, value in colors):
                raise ValueError("Semantic masks must contain only 0 (exclude) and 255 (include).")
        shutil.copyfile(source, target / (name + ".png"))
        hashes[name] = sha256(source)
    return target, hashes


def sparse(inputs, raw, output):
    p = parameters(raw, {"use_gpu": (False, bool, None), "max_num_features": (8192, int, (128, 65536)),
                         "min_model_size": (3, int, (2, 10000)),
                         "camera_model": ("SIMPLE_RADIAL", str, {"SIMPLE_RADIAL", "PINHOLE", "SIMPLE_PINHOLE", "OPENCV"})})
    root, manifest = read_dataset(inputs, output)
    names = sorted(row["name"] for row in manifest["images"])
    if len(names) < p["min_model_size"]:
        raise ValueError("Fewer input images than the requested minimum model size.")
    selected = selected_pairs(root, manifest)
    pc = load_pycolmap()
    if p["use_gpu"] and not pc.has_cuda:
        raise ValueError("CUDA was requested, but this pycolmap build has no CUDA support.")
    device = pc.Device.cuda if p["use_gpu"] else pc.Device.cpu
    database = output / "database.db"
    extraction = pc.FeatureExtractionOptions()
    extraction.sift.max_num_features = p["max_num_features"]
    extraction.num_threads = cpu_count()
    mask_dir, mask_hashes = prepare_masks(root, manifest, output)
    reader = pc.ImageReaderOptions(camera_model=p["camera_model"])
    if mask_dir is not None:
        reader.mask_path = str(mask_dir)
    pc.extract_features(str(database), str(root / "images"), image_names=names,
                        camera_mode=pc.CameraMode.PER_IMAGE, reader_options=reader,
                        extraction_options=extraction, device=device)
    full_pair_count = len(names) * (len(names) - 1) // 2
    matching_engine = "colmap-exhaustive-sift"
    if len(selected) == full_pair_count:
        matching = pc.FeatureMatchingOptions()
        matching.num_threads = cpu_count()
        pc.match_exhaustive(str(database), matching_options=matching, device=device)
    else:
        matching_engine = "numpy-sift-selected-pairs-cpu"
        with pc.Database.open(str(database)) as db:
            ids = {image.name: image.image_id for image in db.read_all_images()}
            for first, second in selected:
                matches = match_descriptors(db.read_descriptors(ids[first]), db.read_descriptors(ids[second]))
                db.write_matches(ids[first], ids[second], matches)
        pc.verify_matches(str(database), str(root / "pairs.txt"))
    models_path = output / "models"
    models_path.mkdir()
    options = pc.IncrementalPipelineOptions()
    options.min_model_size = p["min_model_size"]
    options.num_threads = cpu_count()
    options.random_seed = 0
    options.ba_use_gpu = False  # CUDA extraction/matching does not require cuDSS BA.
    models = pc.incremental_mapping(str(database), str(root / "images"), str(models_path), options=options)
    if not models:
        raise ValueError("COLMAP could not reconstruct a scene. Supply overlapping photographs with sufficient texture and parallax.")
    model = max(models.values(), key=lambda candidate: (candidate.num_reg_images(), candidate.num_points3D()))
    if model.num_reg_images() < p["min_model_size"] or model.num_points3D() == 0:
        raise ValueError("Reconstruction failed the minimum registered-image and nonempty-point quality gates.")
    sparse_dir = root / "sparse"
    if sparse_dir.exists():
        shutil.rmtree(sparse_dir)
    sparse_dir.mkdir()
    model.write(str(sparse_dir))
    point_cloud = output / "sparse-points.ply"
    model.export_PLY(str(point_cloud))
    registered_names = sorted(image.name for image in model.images.values() if image.has_pose)
    metrics = {"input_images": len(names), "registered_images": model.num_reg_images(),
               "unregistered_images": sorted(set(names) - set(registered_names)),
               "points3D": model.num_points3D(), "mean_reprojection_error": model.compute_mean_reprojection_error(),
               "model_count": len(models), "selected_model_policy": "most-registered-images-then-points",
               "pair_count": len(selected), "matching_engine": matching_engine,
               "pycolmap_version": pc.__version__, "cuda_requested": p["use_gpu"], "parameters": p,
               "mask_count": len(mask_hashes), "mask_sha256": mask_hashes}
    result = report("sparse", output, metrics)
    manifest["coordinate_frame"] = "arbitrary-colmap-units"
    manifest["reconstruction"] = metrics
    write_json(root / "dataset.json", manifest)
    shutil.copyfile(result, root / "reconstruction-report.json")
    return {"reconstruction": pack_archive(root, output / "sparse-reconstruction.zip"),
            "point_cloud": point_cloud, "report": result}, metrics


def validate_model_names(model, manifest):
    names = {row["name"] for row in manifest["images"]}
    if any(image.name not in names for image in model.images.values()):
        raise ValueError("Sparse model references images outside the declared dataset.")


def run_command(command, log):
    with log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(command) + "\n")
        stream.flush()
        subprocess.run(command, check=True, stdout=stream, stderr=subprocess.STDOUT,
                       timeout=7200, env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})


def ply_count(path, element):
    with Path(path).open("rb") as stream:
        if stream.readline().strip() != b"ply":
            raise ValueError("Expected a PLY geometry file.")
        for _ in range(200):
            line = stream.readline()
            if line.startswith(f"element {element} ".encode()):
                return int(line.split()[2])
            if line.strip() == b"end_header":
                break
    return 0


def dense(inputs, raw, output):
    p = parameters(raw, {"max_image_size": (1600, int, (256, 8192)), "geometric_consistency": (True, bool, None),
                         "poisson_trim": (5.0, "number", (0, 20))})
    root, manifest = read_dataset(inputs, output)
    pc = load_pycolmap()
    model = pc.Reconstruction(str(root / "sparse"))
    validate_model_names(model, manifest)
    if model.num_reg_images() < 2 or model.num_points3D() == 0:
        raise ValueError("Dense reconstruction requires a nonempty registered sparse model.")
    executable = shutil.which(os.environ.get("HISTORIC_RECONSTRUCTION_COLMAP", "colmap"))
    if not executable:
        raise ValueError("Dense reconstruction requires an operator-installed CUDA-enabled COLMAP executable.")
    work = output / "dense-workspace"
    work.mkdir()
    log = output / "dense-command.log"
    commands = [
        [executable, "image_undistorter", "--image_path", str(root / "images"), "--input_path", str(root / "sparse"),
         "--output_path", str(work), "--output_type", "COLMAP", "--max_image_size", str(p["max_image_size"])],
        [executable, "patch_match_stereo", "--workspace_path", str(work), "--workspace_format", "COLMAP",
         "--PatchMatchStereo.geom_consistency", "1" if p["geometric_consistency"] else "0"],
        [executable, "stereo_fusion", "--workspace_path", str(work), "--workspace_format", "COLMAP",
         "--input_type", "geometric" if p["geometric_consistency"] else "photometric", "--StereoFusion.num_threads", str(cpu_count()), "--output_path", str(output / "dense-points.ply")],
        [executable, "poisson_mesher", "--input_path", str(output / "dense-points.ply"), "--output_path", str(output / "mesh.ply"),
         "--PoissonMeshing.num_threads", str(cpu_count()), "--PoissonMeshing.depth", "10", "--PoissonMeshing.trim", str(p["poisson_trim"])],
    ]
    for command in commands:
        try:
            run_command(command, log)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            tail = log.read_text(errors="replace")[-3000:]
            raise ValueError(f"COLMAP {command[1]} failed: {tail}") from exc
        if command[1] == "stereo_fusion" and ply_count(output / "dense-points.ply", "vertex") == 0:
            raise ValueError("COLMAP stereo_fusion produced 0 points. " + log.read_text(errors="replace")[-3000:])
    points, faces = ply_count(output / "dense-points.ply", "vertex"), ply_count(output / "mesh.ply", "face")
    if faces == 0:
        raise ValueError(f"COLMAP poisson_mesher produced 0 faces from {points} fused points "
                         f"with poisson_trim={p['poisson_trim']}; lower the trimming threshold for sparse surfaces. "
                         + log.read_text(errors="replace")[-3000:])
    version = subprocess.run([executable, "-h"], capture_output=True, text=True, timeout=30, check=False)
    metrics = {"points": points, "faces": faces, "parameters": p,
               "colmap_version": (version.stdout + version.stderr).splitlines()[:2],
               "coordinate_frame": manifest.get("coordinate_frame"), "texture": "untextured-poisson-surface", "poisson_depth": 10, "cpu_threads": cpu_count()}
    result = report("dense", output, metrics)
    for file in (output / "dense-points.ply", output / "mesh.ply", result, log):
        shutil.copyfile(file, root / file.name)
    manifest["dense"] = metrics
    write_json(root / "dataset.json", manifest)
    return {"reconstruction": pack_archive(root, output / "dense-reconstruction.zip"),
            "point_cloud": output / "dense-points.ply", "mesh": output / "mesh.ply", "report": result}, metrics


def fit_similarity(source, target):
    import numpy as np
    source, target = np.asarray(source, dtype=float), np.asarray(target, dtype=float)
    if source.shape != target.shape or source.ndim != 2 or source.shape[1] != 3 or len(source) < 3:
        raise ValueError("At least three corresponding 3D control points are required.")
    if not np.isfinite(source).all() or not np.isfinite(target).all():
        raise ValueError("Control coordinates must be finite.")
    a, b = source - source.mean(axis=0), target - target.mean(axis=0)
    if np.linalg.matrix_rank(a) < 2 or np.linalg.matrix_rank(b) < 2:
        raise ValueError("Control points must not be coincident or collinear.")
    u, values, vt = np.linalg.svd(b.T @ a / len(a))
    signs = np.ones(3)
    signs[-1] = np.linalg.det(u @ vt)
    rotation = u @ np.diag(signs) @ vt
    scale = float(np.dot(values, signs) / np.mean(np.sum(a * a, axis=1)))
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Control points do not define a positive-scale similarity.")
    translation = target.mean(axis=0) - scale * rotation @ source.mean(axis=0)
    return scale, rotation, translation


def robust_similarity(source, target, max_error):
    import numpy as np
    source, target = np.asarray(source, dtype=float), np.asarray(target, dtype=float)
    fit_similarity(source, target)  # Validate the full input before sampling.
    n = len(source)
    if n <= 20:
        samples = list(itertools.combinations(range(n), 3))
    else:
        rng = np.random.default_rng(0)
        samples = [rng.choice(n, 3, replace=False) for _ in range(2048)]
    best, best_score = None, (0, -math.inf)
    for indexes in samples:
        try:
            scale, rotation, translation = fit_similarity(source[list(indexes)], target[list(indexes)])
        except ValueError:
            continue
        errors = np.linalg.norm(scale * source @ rotation.T + translation - target, axis=1)
        inliers = errors <= max_error
        score = (int(inliers.sum()), -float(np.median(errors[inliers])) if inliers.any() else -math.inf)
        if score > best_score:
            best, best_score = inliers, score
    if best is None or best.sum() < max(3, math.ceil(n / 2)):
        raise ValueError("Too few consistent control points for georeferencing.")
    for _ in range(4):
        scale, rotation, translation = fit_similarity(source[best], target[best])
        errors = np.linalg.norm(scale * source @ rotation.T + translation - target, axis=1)
        updated = errors <= max_error
        if np.array_equal(updated, best):
            break
        if updated.sum() < max(3, math.ceil(n / 2)):
            raise ValueError("Control-point refinement failed the inlier quality gate.")
        best = updated
    scale, rotation, translation = fit_similarity(source[best], target[best])
    errors = np.linalg.norm(scale * source @ rotation.T + translation - target, axis=1)
    if any(errors[best] > max_error):
        raise ValueError("Control-point fit exceeds the maximum error.")
    return scale, rotation, translation, errors, best


def georeference(inputs, raw, output):
    p = parameters(raw, {"max_error": (1.0, "number", (1e-9, 1000000)), "crs": ("local", str, None)})
    if not 1 <= len(p["crs"].strip()) <= 200:
        raise ValueError("Provide a coordinate-system label of 1 to 200 characters.")
    root, manifest = read_dataset(inputs, output)
    if manifest.get("dense"):
        raise ValueError("Georeference the sparse reconstruction before dense meshing so all outputs share the same frame.")
    controls_path = staged_file(inputs, "control_points_file", required=False)
    if controls_path is None:
        controls_path = root / "control_points.json"
        if not controls_path.is_file():
            raise ValueError("Supply control_points_file or a control_points.json inside the reconstruction bundle.")
    controls = json.loads(controls_path.read_text(encoding="utf-8"))
    rows = controls.get("points") if isinstance(controls, dict) else None
    if not isinstance(rows, list) or not 3 <= len(rows) <= 1000:
        raise ValueError("Control-point JSON must contain points: [{source: [x,y,z], target: [x,y,z]}], with 3 to 1000 rows.")
    try:
        source, target = [row["source"] for row in rows], [row["target"] for row in rows]
        if any(len(point) != 3 or any(type(v) not in (int, float) for v in point) for point in source + target):
            raise ValueError("Each control coordinate must contain three numbers.")
    except (KeyError, TypeError) as exc:
        raise ValueError("Malformed control-point coordinates.") from exc
    scale, rotation, translation, errors, inliers = robust_similarity(source, target, p["max_error"])
    pc = load_pycolmap()
    model = pc.Reconstruction(str(root / "sparse"))
    validate_model_names(model, manifest)
    if model.num_points3D() == 0 or model.num_reg_images() < 2:
        raise ValueError("Georeferencing requires a nonempty registered sparse model.")
    model.transform(pc.Sim3d(scale, pc.Rotation3d(rotation), translation))
    model.write(str(root / "sparse"))
    point_cloud = output / "georeferenced-points.ply"
    model.export_PLY(str(point_cloud))
    metrics = {"crs": p["crs"], "scale": scale, "rotation": rotation.tolist(), "translation": translation.tolist(),
               "inliers": inliers.tolist(), "control_residuals": errors.tolist(),
               "inlier_rmse": float(math.sqrt(sum(errors[inliers]**2) / sum(inliers))),
               "control_points_sha256": sha256(controls_path), "parameters": p,
               "coordinate_units": "target-control-point-units", "crs_reprojection_performed": False}
    transform = write_json(output / "similarity-transform.json", metrics)
    result = report("georeference", output, metrics)
    manifest["coordinate_frame"] = p["crs"]
    manifest["georeferencing"] = metrics
    write_json(root / "dataset.json", manifest)
    shutil.copyfile(transform, root / "similarity-transform.json")
    return {"reconstruction": pack_archive(root, output / "georeferenced-reconstruction.zip"),
            "point_cloud": point_cloud, "transform": transform, "report": result}, metrics


STAGES = {"prepare": prepare, "pairs": pairs, "sparse": sparse, "dense": dense, "georeference": georeference}
UPSTREAM_STAGES = {"segmentation", "original_sfm", "geolocalization", "dense_intrinsics", "refine_keypoints", "mvs"}


def run_component(stage, request, output_dir=None):
    if not isinstance(request, dict) or not isinstance(request.get("inputs"), dict):
        raise TypeError("A component request must contain an inputs object.")
    raw = request.get("parameters")
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise TypeError("parameters must be an object.")
    output = Path(output_dir or os.environ["WEBHDP_OUTPUT_DIR"]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="historic-", dir=output) as temporary:
        work = Path(temporary)
        if stage.startswith("upstream-") and stage[9:] in UPSTREAM_STAGES:
            spec = importlib.util.spec_from_file_location("historic_reconstruction_upstream", Path(__file__).with_name("upstream.py"))
            upstream = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(upstream)
            files, summary = upstream.run(stage[9:], request["inputs"], raw, work)
        elif stage in STAGES:
            files, summary = STAGES[stage](request["inputs"], raw, work)
        else:
            raise ValueError("Unknown historic reconstruction stage.")
        outputs, artifacts = {}, []
        sources = {}
        for role, file in files.items():
            file = Path(file)
            if file.is_symlink() or not file.is_file() or not file.resolve().is_relative_to(work):
                raise ValueError(f"Stage failed to produce safe output {role}.")
            if file.name in sources and sources[file.name] != file.resolve():
                raise ValueError("Stage output names collide.")
            sources[file.name] = file.resolve()
            if (output / file.name).exists():
                raise ValueError("Output directory already contains a stage result; use a fresh run directory.")
            outputs[role] = str(output / file.name)
        for name, source in sources.items():
            target = output / name
            shutil.copyfile(source, target)
            roles = [role for role, path in outputs.items() if path == str(target)]
            artifacts.append({"name": target.name, "artifact_kind": "file", "path": str(target),
                              "metadata": {"role": roles[0], "roles": roles, "sha256": sha256(target), "bytes": target.stat().st_size}})
    return {"success": True, "status": "completed", "outputs": outputs, "artifacts": artifacts, "summary": summary}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=list(STAGES) + ["upstream-" + value for value in sorted(UPSTREAM_STAGES)])
    parser.add_argument("--webhdp-input", default=os.environ.get("WEBHDP_COMPONENT_REQUEST"))
    parser.add_argument("--webhdp-output-dir", default=os.environ.get("WEBHDP_OUTPUT_DIR"))
    parser.add_argument("--webhdp-result", default=os.environ.get("WEBHDP_COMPONENT_RESPONSE"))
    args = parser.parse_args()
    if not all((args.webhdp_input, args.webhdp_output_dir, args.webhdp_result)):
        parser.error("Provide the WebHDP request, output directory and response through environment or CLI flags.")
    try:
        request = json.loads(Path(args.webhdp_input).read_text(encoding="utf-8"))
        result = run_component(args.stage, request, args.webhdp_output_dir)
    except Exception as exc:  # noqa: BLE001 - the contract must return a failure envelope.
        traceback.print_exc()
        result = {"success": False, "status": "failed", "error": str(exc)}
    write_json(args.webhdp_result, result)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
