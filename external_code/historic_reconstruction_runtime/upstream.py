"""Fixed adapters for the separately installed historic-reconstruction research code.

No upstream source, weights or arbitrary command lines are accepted from a run.
The operator configuration and every imported source tree are checked before use.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

STAGES = frozenset({"segmentation", "original_sfm", "geolocalization", "dense_intrinsics", "refine_keypoints", "mvs"})
MODULES = {
    "segmentation": "preprocess.generate_segmask",
    "original_sfm": "reconstruction.pipeline",
    "geolocalization": "geolocalization.geoloc_pipeline",
    "dense_intrinsics": "geolocalization.dense_intrinsics",
    "refine_keypoints": "matching.refine_keypoints.refine_model_keypoints",
    "mvs": "meshing.mvs_anywhere",
}
PARAMETERS = {
    "segmentation": set(),
    "original_sfm": {"min_num_matches", "min_inliers", "num_retrieval"},
    "geolocalization": {"skip_doppelgangers", "dense_intrinsics", "max_image_size", "min_num_matches", "min_inliers"},
    "dense_intrinsics": {"skip_doppelgangers"},
    "refine_keypoints": {"max_refine_num", "run_ba"},
    "mvs": {"batch_size", "fusion_max_depth", "fusion_resolution"},
}
IGNORED = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_sha256(root):
    """Stable inventory digest; includes native libraries/configs, excludes VCS/bytecode."""
    root = Path(root).resolve(strict=True)
    digest = hashlib.sha256()
    count = 0
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in IGNORED for part in rel.parts) or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_symlink():
            raise ValueError(f"Pinned source contains a symlink: {rel}")
        if path.is_file():
            digest.update(rel.as_posix().encode() + b"\0" + bytes.fromhex(file_sha256(path)))
            count += 1
    if not count:
        raise ValueError("Pinned source tree is empty")
    return digest.hexdigest()


def _checked_path(entry, *, tree=False):
    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
        raise ValueError("Operator runtime entries need path and sha256")
    path = Path(entry["path"])
    if not path.is_absolute() or not path.exists():
        raise ValueError("Operator runtime paths must be existing absolute paths")
    path = path.resolve()
    expected = entry.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("Operator runtime SHA-256 is required")
    actual = tree_sha256(path) if tree else file_sha256(path)
    if actual != expected.lower():
        raise ValueError("Operator runtime checksum mismatch")
    return path


def load_config(stage):
    if stage not in STAGES:
        raise ValueError("Unsupported historic research stage")
    value = os.environ.get("HISTORIC_RECONSTRUCTION_UPSTREAM_CONFIG", "")
    if not value:
        raise ValueError("Historic research runtime is not installed; configure HISTORIC_RECONSTRUCTION_UPSTREAM_CONFIG")
    path = Path(value)
    if not path.is_absolute() or not path.is_file():
        raise ValueError("Historic research operator configuration must be an absolute file path")
    config_bytes = path.read_bytes()
    config = json.loads(config_bytes)
    if config.get("schema_version") != 1 or stage not in config.get("enabled_stages", []):
        raise ValueError("Historic research stage is not enabled in the operator runtime")
    if not isinstance(config.get("allow_network", False), bool):
        raise ValueError("allow_network must be a boolean")
    _checked_path(config.get("python"))
    # Preserve a venv interpreter symlink: resolving it changes sys.prefix.
    config["_python"] = Path(config["python"]["path"])
    config["_source"] = _checked_path(config.get("source"), tree=True)
    if config["_source"].name != "historic_reconstruction_pipeline":
        raise ValueError("source.path must name the historic_reconstruction_pipeline package directory")
    config["_dependencies"] = [_checked_path(entry, tree=True) for entry in config.get("dependencies", [])]
    config["_assets"] = {key: _checked_path(entry, tree=entry.get("kind") == "tree")
                         for key, entry in config.get("assets", {}).items()}
    seconds = config.get("timeout_seconds", 21600)
    if isinstance(seconds, bool) or not isinstance(seconds, int) or not 60 <= seconds <= 604800:
        raise ValueError("Operator timeout_seconds must be 60..604800")
    config["timeout_seconds"] = seconds
    config["_config_path"] = path
    config["_config_sha256"] = hashlib.sha256(config_bytes).hexdigest()
    return config


def _assert_runtime_unchanged(config):
    """Recheck the installation selected at startup, never replacement pins."""
    def check_config():
        try:
            actual = file_sha256(config["_config_path"])
        except OSError as exc:
            raise ValueError("Operator runtime configuration changed during execution") from exc
        if actual != config["_config_sha256"]:
            raise ValueError("Operator runtime configuration changed during execution")

    check_config()
    _checked_path(config["python"])
    _checked_path(config["source"], tree=True)
    for entry in config.get("dependencies", []):
        _checked_path(entry, tree=True)
    for entry in config.get("assets", {}).values():
        _checked_path(entry, tree=entry.get("kind") == "tree")
    check_config()


def _number(parameters, name, default, low, high):
    value = parameters.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in {low}..{high}")
    return value


def _boolean(parameters, name, default=False):
    value = parameters.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _finite_number(parameters, name, default, low, high):
    value = parameters.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be a finite number in {low}..{high}")
    return float(value)


def _asset(config, name):
    path = config["_assets"].get(name)
    if path is None:
        raise ValueError(f"Operator runtime is missing pinned asset: {name}")
    return path


def _geolocation_acquisition_args(config):
    """An optional operator-owned seed bounds acquisition without altering inference.

    The upstream --pano-meta-json branch uses only the supplied panorama IDs,
    then applies its normal spatial/coverage filter. No discovery runs in that
    branch. All metadata is a checked installation asset, never run-supplied code.
    """
    settings = config.get("geolocation_acquisition")
    if settings is None:
        return []
    limits = {"max_panoramas": (8, 1, 32), "bounds_margin": (50, 0, 500),
              "zoom": (3, 0, 4), "cubemap_width": (1024, 320, 2048),
              "download_workers": (2, 1, 8)}
    if not isinstance(settings, dict) or set(settings) - set(limits):
        raise ValueError("Unsupported geolocation acquisition setting")
    values = {name: _number(settings, name, *limit) for name, limit in limits.items()}
    seed = _asset(config, "pano_metadata")
    if not seed.is_file() or seed.stat().st_size > 1024 * 1024:
        raise ValueError("Panorama seed must be a bounded JSON file")
    metadata = json.loads(seed.read_text())
    if not isinstance(metadata, dict) or not 1 <= len(metadata) <= values["max_panoramas"]:
        raise ValueError("Panorama seed exceeds the configured panorama count")
    for pano_id, entry in metadata.items():
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", pano_id) or not isinstance(entry, dict):
            raise ValueError("Invalid panorama seed identifier or metadata")
        for key, bound in (("lat", 90), ("lon", 180)):
            value = entry.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > bound:
                raise ValueError("Invalid panorama seed coordinates")
    args = ["--pano-meta-json", str(seed)]
    for name in ("bounds_margin", "zoom", "cubemap_width", "download_workers"):
        args += ["--" + name.replace("_", "-"), str(values[name])]
    return args


def _environment(config, output):
    inherited = {"PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TEMP", "TMP",
                 "LD_LIBRARY_PATH", "CUDA_VISIBLE_DEVICES", "CUDA_HOME", "CUDA_PATH", "NVIDIA_VISIBLE_DEVICES",
                 "NVIDIA_DRIVER_CAPABILITIES", "TORCH_HOME", "XDG_CACHE_HOME"}
    env = {key: value for key, value in os.environ.items() if key in inherited or key.startswith("SLURM_")}
    if config.get("allow_network", False):
        # Acquisition must honor the installed cluster's egress route. These
        # values are process-only and never copied into reports or public inputs.
        proxy_keys = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                      "http_proxy", "https_proxy", "all_proxy", "no_proxy"}
        env.update({key: value for key, value in os.environ.items() if key in proxy_keys})
        if "tls_ca_bundle" in config["_assets"]:
            certificate_bundle = str(_asset(config, "tls_ca_bundle"))
            env["SSL_CERT_FILE"] = certificate_bundle
            env["REQUESTS_CA_BUNDLE"] = certificate_bundle
    # The source and dependency roots are operator controlled and immutable.
    env["PYTHONPATH"] = os.pathsep.join(map(str, [config["_source"].parent, *config["_dependencies"]]))
    if "native_libraries" in config["_assets"]:
        libraries = _asset(config, "native_libraries")
        if not libraries.is_dir():
            raise ValueError("Pinned native_libraries must be a directory")
        env["LD_LIBRARY_PATH"] = str(libraries) + (os.pathsep + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["MKL_THREADING_LAYER"] = "GNU"
    thread_limits = [8, os.cpu_count() or 1]
    for key in ("SLURM_CPUS_PER_TASK", "OMP_NUM_THREADS"):
        value = os.environ.get(key, "")
        if value.isdecimal() and int(value) > 0:
            thread_limits.append(int(value))
    env["OMP_NUM_THREADS"] = str(min(thread_limits))
    env["OPENBLAS_NUM_THREADS"] = env["OMP_NUM_THREADS"]
    env["MKL_NUM_THREADS"] = env["OMP_NUM_THREADS"]
    env["MPLCONFIGDIR"] = str(output / "matplotlib-cache")
    # Network acquisition is only for panoramas, never implicit model updates.
    # ONNX Runtime 1.29+ enables POSIX telemetry in official binaries.
    # Panorama acquisition never authorizes model/runtime telemetry.
    env["ORT_DISABLE_TELEMETRY"] = "1"
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    if "model_cache" in config["_assets"]:
        env["HF_HOME"] = str(_asset(config, "model_cache"))
    if "torch_cache" in config["_assets"]:
        env["TORCH_HOME"] = str(_asset(config, "torch_cache"))
    if "romav2_hub" in config["_assets"]:
        env["ROMAV2_HUB_DIR"] = str(_asset(config, "romav2_hub"))
    return env


def _log_tail(log):
    # Read only the bounded suffix; scientific process logs can be large.
    with log.open("rb") as handle:
        handle.seek(max(0, log.stat().st_size - 6000))
        print(handle.read().decode("utf-8", errors="replace"), file=sys.stderr)


def _redact_proxy_log(log, env):
    """Remove exact proxy values without loading an unbounded scientific log."""
    keys = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"}
    values = sorted({env[key].encode("utf-8") for key in keys if env.get(key)}, key=len, reverse=True)
    if not values or not log.is_file():
        return
    pattern = re.compile(b"|".join(re.escape(value) for value in values))
    overlap = max(map(len, values)) - 1
    fd, name = tempfile.mkstemp(prefix=log.name + ".redacted-", dir=log.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as target, log.open("rb") as source:
            pending = b""
            while True:
                chunk = source.read(64 * 1024)
                pending += chunk
                safe_end = len(pending) if not chunk else max(0, len(pending) - overlap)
                consumed = 0
                for match in pattern.finditer(pending):
                    if match.start() >= safe_end:
                        break
                    target.write(pending[consumed:match.start()])
                    target.write(b"[REDACTED_PROXY]")
                    consumed = match.end()
                if consumed < safe_end:
                    target.write(pending[consumed:safe_end])
                pending = pending[max(consumed, safe_end):]
                if not chunk:
                    break
        os.replace(temporary, log)
    finally:
        temporary.unlink(missing_ok=True)


def _execute(command, config, env, cwd, log):
    child_env = {**env, "PWD": str(Path(cwd).resolve())}
    try:
        try:
            with log.open("ab") as handle:
                subprocess.run(command, check=True, cwd=cwd, env=child_env, stdout=handle,
                               stderr=subprocess.STDOUT, timeout=config["timeout_seconds"])
        finally:
            # Child libraries may include proxy configuration in error reprs.
            # Redact before either diagnostic tailing or successful archiving.
            _redact_proxy_log(log, child_env)
    except subprocess.TimeoutExpired as exc:
        _log_tail(log)
        raise ValueError("Historic research stage exceeded its configured time limit") from exc
    except subprocess.CalledProcessError as exc:
        # The outer file-contract runner removes temporary work on failure.
        # Surface a bounded diagnostic tail before that cleanup occurs.
        _log_tail(log)
        raise ValueError(f"Historic research stage failed with exit code {exc.returncode}; see component logs") from exc


def _mvs_runtime_context(config, env, output):
    """Prepare the upstream JIT dependency without writing into pinned assets."""
    repository = _asset(config, "mvs_repository")
    extension_source = repository / "src/mvsanywhere/tools/marching_cubes"
    if not all((extension_source / name).is_file() for name in
               ("ext.cpp", "marching_cubes_cpu.cpp", "marching_cubes.cu")):
        raise ValueError("Pinned MVS repository is missing the upstream CUDA extension sources")
    cache = output / "torch-extensions"
    shutil.copytree(_asset(config, "mvs_extension_cache"), cache)
    # Torch's loader needs a writable lock/build directory even for a compiled
    # cache. Copies are per run; the checked installation remains immutable.
    env["TORCH_EXTENSIONS_DIR"] = str(cache)
    env["CUDA_HOME"] = str(_asset(config, "mvs_cuda_compiler").parent.parent)
    libraries = str(Path(env["CUDA_HOME"]) / "lib")
    env["LD_LIBRARY_PATH"] = libraries + (os.pathsep + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    env["CXX"] = str(_asset(config, "mvs_cxx_compiler"))
    env["CC"] = env["CXX"]
    env["CUDAHOSTCXX"] = env["CXX"]
    env["PATH"] = str(_asset(config, "mvs_ninja").parent) + os.pathsep + env.get("PATH", "")
    env["MAX_JOBS"] = env["OMP_NUM_THREADS"]
    return repository


def _mvs_mesh_metrics(path):
    import numpy as np
    import trimesh
    mesh = trimesh.load(path, force="mesh", process=False)
    if len(mesh.vertices) < 3 or len(mesh.faces) < 1:
        raise ValueError("MVS produced an empty mesh")
    if not np.isfinite(mesh.vertices).all():
        raise ValueError("MVS mesh contains non-finite coordinates")
    if int(mesh.faces.min()) < 0 or int(mesh.faces.max()) >= len(mesh.vertices):
        raise ValueError("MVS mesh contains invalid face indices")
    area = float(mesh.area)
    if not math.isfinite(area) or area <= 0:
        raise ValueError("MVS mesh has no finite nonzero surface area")
    return {"vertices": len(mesh.vertices), "faces": len(mesh.faces), "surface_area": area}


def _preflight(stage, config, env, output, parameters):
    if stage in {"segmentation", "original_sfm", "geolocalization"}:
        _asset(config, "model_cache")
    if stage in {"original_sfm", "geolocalization", "refine_keypoints"}:
        _asset(config, "torch_cache")
    modules = ["numpy", "PIL", "torch", "pycolmap", "hloc.extract_features"]
    modules.append("historic_reconstruction_pipeline." + MODULES[stage])
    # mvs_anywhere uses a sibling absolute import in the supplied snapshot.
    if stage == "mvs":
        env["PYTHONPATH"] += os.pathsep + str(config["_source"] / "meshing")
    if stage in {"original_sfm", "geolocalization"} and not parameters.get("skip_doppelgangers", False):
        modules.extend(["mast3r.model", "utils.process_database"])
        _asset(config, "doppelgangers_weights")
    if stage == "dense_intrinsics" or parameters.get("dense_intrinsics", False):
        modules.append("romav2")
        _asset(config, "romav2_hub")
    if stage == "refine_keypoints":
        modules.append("vggsfm.runners.runner")
        _asset(config, "vggsfm_weights")
    working_directory = output
    if stage == "mvs":
        modules.extend(["mvsanywhere.options", "mvsanywhere.tools.fusers_helper"])
        for name in ("mvs_model_config", "mvs_data_config", "mvs_checkpoint"):
            _asset(config, name)
        working_directory = _mvs_runtime_context(config, env, output)
    script = """import importlib,inspect,json,sys
for name in json.loads(sys.argv[1]): importlib.import_module(name)
import torch
if sys.argv[2]=='1' and not torch.cuda.is_available(): raise RuntimeError('This research stage requires CUDA')
if sys.argv[3]=='original_sfm':
 import hloc.extract_features as ef
 import hloc.match_features as mf
 for name in ('mask_dir','stereo_list_path'):
  if name not in inspect.signature(ef.main).parameters: raise RuntimeError('The historic custom HLoc fork is required: '+name)
 if 'loma_inloc' not in ef.confs or 'megaloc' not in ef.confs or 'loma' not in mf.confs: raise RuntimeError('Historic HLoc configurations are missing')
if sys.argv[3] in ('original_sfm','geolocalization'):
 import pycolmap
 if not hasattr(pycolmap.BundleAdjustmentBackend,'CASPAR'): raise RuntimeError('The historic COLMAP build with CASPAR is required')
 caspar_options=pycolmap.IncrementalPipelineOptions(ba_local_backend=pycolmap.BundleAdjustmentBackend.CASPAR,ba_global_backend=pycolmap.BundleAdjustmentBackend.CASPAR)
 if not caspar_options.check(): raise RuntimeError('The installed COLMAP exposes CASPAR options but lacks a compiled CASPAR backend')
 if sys.argv[3]=='geolocalization' and (not hasattr(pycolmap.FeatureExtractorType,'LOMA_B') or not hasattr(pycolmap,'LomaExtractionOptions')): raise RuntimeError('The historic COLMAP build with compiled LoMa/ONNX support is required')
print(json.dumps({'torch':torch.__version__,'cuda':torch.cuda.is_available()}))
"""
    _execute([str(config["_python"]), "-c", script, json.dumps(modules),
              "0" if stage == "segmentation" else "1", stage], config, env, working_directory, output / "preflight.log")


def _images(dataset):
    root = dataset / "images"
    if not root.is_dir():
        raise ValueError("Input bundle must contain images/")
    names = sorted(path.relative_to(root).as_posix() for path in root.rglob("*")
                   if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)
    if not 1 <= len(names) <= 1000:
        raise ValueError("Input bundle must contain 1..1000 supported images")
    # Upstream HLoc pair files split on whitespace; use the portable prepare stage first.
    if any(any(char.isspace() for char in name) for name in names):
        raise ValueError("Historic research image names cannot contain whitespace; run image preparation first")
    (dataset / "image_list.txt").write_text("\n".join(names) + "\n")
    manifest_path = dataset / "dataset.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        rows = manifest.get("images", [])
        if not isinstance(rows, list) or len(rows) != len(names) or {row.get("name") for row in rows} != set(names):
            raise ValueError("Dataset image manifest does not match the staged images")
        if any(file_sha256(root / row["name"]) != row.get("sha256") for row in rows):
            raise ValueError("Dataset image fixity failed")
    else:
        from PIL import Image
        rows = []
        for name in names:
            with Image.open(root / name) as image:
                image.verify()
            with Image.open(root / name) as image:
                rows.append({"name": name, "original_name": name, "sha256": file_sha256(root / name), "size": list(image.size)})
        manifest = {"schema": "webhdp.historic-dataset/1", "images": rows, "coordinate_frame": "unregistered"}
        manifest_path.write_text(json.dumps(manifest, indent=2))
    return root, names


def _validate_geo(path, names, bounds=False):
    data = json.loads(path.read_text())
    points = data if bounds else [value for key, value in data.items() if key in names] if isinstance(data, dict) else []
    if not isinstance(points, list) or len(points) < (3 if bounds else 1):
        raise ValueError("Bounds need at least three latitude/longitude points; GPS needs matching image names")
    for point in points:
        if not isinstance(point, (tuple, list)) or len(point) < 2:
            raise ValueError("Coordinates must use [latitude, longitude]")
        lat, lon = point[:2]
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in (lat, lon)):
            raise ValueError("Coordinates must be finite numbers")
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError("Coordinates are outside latitude/longitude bounds")


def build_command(stage, config, dataset, workspace, parameters, geo=None):
    """Build argv from a fixed stage; public values never select code or flags."""
    if stage not in STAGES or set(parameters) - PARAMETERS[stage]:
        raise ValueError("Unsupported historic research stage or parameter")
    python = str(config["_python"])
    command = [python, "-m", "historic_reconstruction_pipeline." + MODULES[stage]]
    images = dataset / "images"
    image_list = dataset / "image_list.txt"
    if stage == "segmentation":
        return command + ["--image_dir", str(images), "--image_list_path", str(image_list), "--output_path_mask", str(dataset / "masks")]
    if stage == "original_sfm":
        # The upstream CLI exposes no options for its hard-coded weights or thresholds.
        # A fixed launcher calls its unchanged function with reviewed options.
        launcher = """import argparse,contextlib,json,sys,torch
from pathlib import Path
from historic_reconstruction_pipeline.reconstruction import pipeline as p
p.options['doppelgangers']['weights']=sys.argv[4]
p.options['mapper']['min_num_matches']=int(sys.argv[5])
p.options['mapper']['abs_pose_min_num_inliers']=int(sys.argv[6])
requested=int(sys.argv[7])
available=len([line for line in Path(sys.argv[3]).read_text().splitlines() if line.strip()])-1
effective=min(requested,available)
p.options['retrieval']['num_pairs_retrieval']=effective
settings={'retrieval_neighbors_requested':requested,'retrieval_neighbors_effective':effective}
(Path(sys.argv[1])/'adapter-settings.json').write_text(json.dumps(settings,indent=2)+'\\n')
print(json.dumps(settings),flush=True)
# The operator-pinned author's checkpoint stores its configuration as Namespace.
# Preserve restricted tensor loading on modern PyTorch; do not allow arbitrary
# checkpoint globals or disable weights_only for user-supplied files.
safe=getattr(torch.serialization,'safe_globals',None)
with safe([argparse.Namespace]) if safe else contextlib.nullcontext():
 p.run_pipeline(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]))
"""
        return [python, "-c", launcher, str(workspace), str(images), str(image_list), str(_asset(config, "doppelgangers_weights")),
                str(_number(parameters, "min_num_matches", 50, 15, 1000)), str(_number(parameters, "min_inliers", 100, 15, 1000)),
                str(_number(parameters, "num_retrieval", 100, 1, 10000))]
    if stage in {"geolocalization", "dense_intrinsics"}:
        args = ["--image-dir", str(images), "--pano-dir", str(dataset / "panoramas"), "--cubemap-dir", str(dataset / "cubemaps")]
        if _boolean(parameters, "skip_doppelgangers"):
            args += ["--skip-doppelgangers"]
        elif stage == "geolocalization":
            args += ["--dg-weights", str(_asset(config, "doppelgangers_weights"))]
            # This CLI uses the same operator-pinned checkpoint as original SfM.
            # Keep its one configuration class allowed only while that fixed
            # module runs; uploaded files never select code or checkpoint globals.
            launcher = """import argparse,contextlib,runpy,torch
safe=getattr(torch.serialization,'safe_globals',None)
with safe([argparse.Namespace]) if safe else contextlib.nullcontext():
 runpy.run_module('historic_reconstruction_pipeline.geolocalization.geoloc_pipeline',run_name='__main__',alter_sys=True)
"""
            command = [python, "-c", launcher]
        if stage == "dense_intrinsics":
            return command + ["--workspaces", str(workspace)] + args + ["--romav2-hub-dir", str(_asset(config, "romav2_hub"))]
        if not config.get("allow_network", False):
            raise ValueError("Geolocalization downloads Street View data; this operator runtime has network acquisition disabled")
        if geo is None:
            raise ValueError("Geolocalization requires a GPS or bounds JSON input")
        args += ["--image-list", str(image_list), "--workspace", str(workspace), geo[0], str(geo[1]),
                 "--max-image-size", str(_number(parameters, "max_image_size", 1024, 320, 4096)),
                 "--min-num-matches", str(_number(parameters, "min_num_matches", 50, 15, 1000)),
                 "--abs-pose-min-num-inliers", str(_number(parameters, "min_inliers", 100, 15, 1000))]
        args += _geolocation_acquisition_args(config)
        if _boolean(parameters, "dense_intrinsics"):
            args += ["--dense-intrinsics", "--romav2-hub-dir", str(_asset(config, "romav2_hub"))]
        if (dataset / "masks").is_dir():
            args += ["--mask-dir", str(dataset / "masks")]
        return command + args
    if stage == "refine_keypoints":
        args = ["--model_path", str(dataset / "sparse"), "--output_path", str(workspace / "refined"), "--image_dir", str(images),
                "--config_path", str(config.get("_refine_config", config["_source"] / "matching/refine_keypoints/demo.yaml")),
                "--max_refine_num", str(_number(parameters, "max_refine_num", 100000, 1, 1000000))]
        if _boolean(parameters, "run_ba", True):
            args.append("--run_ba")
        return command + args
    # Upstream MVS config names and weights are fixed in the operator installation.
    return command + ["--name", "webhdp-historic", "--output_base_path", str(workspace),
                      "--config_file", str(_asset(config, "mvs_model_config")),
                      "--data_config_file", str(_asset(config, "mvs_data_config")),
                      "--load_weights_from_checkpoint", str(_asset(config, "mvs_checkpoint")),
                      "--scan_parent_directory", str(dataset.parent), "--scan_name", dataset.name,
                      "--num_workers", "0", "--batch_size", str(_number(parameters, "batch_size", 1, 1, 4)),
                      "--run_fusion", "--cache_depths", "--depth_fuser", "open3d",
                      "--fusion_max_depth", str(_finite_number(parameters, "fusion_max_depth", 3.0, 0.01, 10000)),
                      "--fusion_resolution", str(_finite_number(parameters, "fusion_resolution", 0.04, 0.001, 10))]


def _model_report(paths, images, config, env, output, report_name="models.json"):
    if not paths:
        raise ValueError("Historic research stage produced no COLMAP model")
    result = output / report_name
    script = """import json,math,sys
from pathlib import Path
import numpy as np
from PIL import Image
import pycolmap
root=Path(sys.argv[2]).resolve()
results=[]
for name in json.loads(sys.argv[1]):
 rec=pycolmap.Reconstruction(name)
 count=rec.num_reg_images(); points=rec.num_points3D(); error=rec.compute_mean_reprojection_error()
 if count<3 or points<1 or not math.isfinite(error): raise RuntimeError('Incomplete COLMAP reconstruction')
 for camera in rec.cameras.values():
  if camera.width<1 or camera.height<1 or not np.isfinite(camera.params).all(): raise RuntimeError('Invalid COLMAP camera dimensions or parameters')
 for point in rec.points3D.values():
  if not np.isfinite(point.xyz).all() or not math.isfinite(point.error): raise RuntimeError('Non-finite COLMAP 3D point or error')
 input_count=panorama_count=0
 for image in rec.images.values():
  relative=Path(image.name)
  if relative.is_absolute() or '..' in relative.parts or chr(92) in image.name: raise RuntimeError('Unsafe COLMAP image reference')
  candidate=(root/image.name).resolve()
  cubemap_root=root.parent/'cubemaps'
  cubemap=(cubemap_root/image.name).resolve()
  historic=candidate.is_relative_to(root) and candidate.is_file()
  gsv=cubemap.is_relative_to(cubemap_root) and cubemap.is_file()
  if not historic and not gsv: raise RuntimeError('COLMAP image reference is outside staged images or missing')
  camera=rec.cameras[image.camera_id]
  with Image.open(candidate if historic else cubemap) as source:
   if source.size!=(camera.width,camera.height): raise RuntimeError('COLMAP camera dimensions disagree with image '+image.name)
   source.verify()
  has_pose=image.has_pose
  if callable(has_pose): has_pose=has_pose()
  if has_pose and not np.isfinite(image.cam_from_world().matrix()).all(): raise RuntimeError('Non-finite COLMAP image pose')
  if has_pose:
   if historic: input_count+=1
   else: panorama_count+=1
  if any(not np.isfinite(point.xy).all() for point in image.points2D): raise RuntimeError('Non-finite COLMAP image keypoint')
 results.append({'model':str(Path(name).name),'registered_images':count,'registered_input_images':input_count,'registered_panorama_images':panorama_count,'points3D':points,'mean_reprojection_error':error})
Path(sys.argv[3]).write_text(json.dumps(results))
"""
    _execute([str(config["_python"]), "-c", script, json.dumps([str(path) for path in paths]), str(images), str(result)],
             config, env, output, output / "validation.log")
    return json.loads(result.read_text())


def _require_historic_registration(models):
    if not any(model.get("registered_input_images", 0) >= 1 for model in models):
        raise ValueError("Geolocation produced no registered historic input image; panorama-only geometry is insufficient")


def _dense_intrinsics_evidence(workspace, names):
    """Validate fresh RoMa observations and calibration decisions, including no-update outcomes."""
    import numpy as np

    allowed_names = set(names)
    roots = sorted(Path(workspace).glob("scenes/*/*-dense_intrinsics/intrinsics"))
    if not roots:
        raise ValueError("Dense intrinsics produced no inference evidence")
    accepted = {"dist", "pp", "focal"}
    statuses = {"ok", "no_matches", "few_correspondences", "ransac_failed", "few_inliers"}
    counts = dict.fromkeys(("dist", "pp", "focal", "unchanged", "rejected"), 0)
    observations, processed, records = 0, set(), []

    def rows(path):
        if not path.is_file():
            raise ValueError("Missing dense intrinsics evidence: " + path.name)
        result = {}
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or row.get("name") not in allowed_names or row["name"] in result:
                raise ValueError("Invalid or duplicate dense intrinsics image identity")
            if row.get("status") not in statuses:
                raise ValueError("Dense intrinsics recorded an inference or calibration error")
            result[row["name"]] = row
        if not result:
            raise ValueError("Empty dense intrinsics evidence")
        return result

    def numeric(data, key, shape, integer=False, empty_layout=False):
        if key not in data:
            raise ValueError("Missing numeric dense intrinsics evidence: " + key)
        value = data[key]  # allow_pickle=False rejects object arrays before inspection.
        if empty_layout and shape[0] == 0 and value.shape == (0,) and value.dtype.kind in "iuf":
            return value
        if value.shape != shape or value.dtype.kind not in ("iu" if integer else "iuf") or not np.isfinite(value).all():
            raise ValueError("Invalid numeric dense intrinsics evidence: " + key)
        return value

    def count(row, key, required=False):
        value = row.get(key)
        if value is None and not required:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("Invalid dense intrinsics count: " + key)
        return value

    for root in roots:
        fits, decisions = rows(root / "fits.jsonl"), rows(root / "cameras.jsonl")
        if set(fits) != set(decisions):
            raise ValueError("Dense intrinsics fit and decision identities disagree")
        expected = {Path(name).stem + ".npz" for name in fits}
        if {path.name for path in (root / "matches").glob("*.npz")} != expected:
            raise ValueError("Dense intrinsics observations and fit identities disagree")
        for name, fit in fits.items():
            decision = decisions[name]
            kind = decision.get("decision")
            if kind not in counts or decision["status"] != fit["status"]:
                raise ValueError("Invalid dense intrinsics calibration decision")
            with np.load(root / "matches" / (Path(name).stem + ".npz"), allow_pickle=False) as data:
                metadata = data["meta"]
                if metadata.shape != () or metadata.dtype.kind not in "US":
                    raise ValueError("Invalid dense intrinsics observation metadata")
                meta = json.loads(str(metadata))
                if meta.get("name") != name or any(isinstance(meta.get(key), bool) or not isinstance(meta.get(key), int) or meta[key] < 1 for key in ("width", "height")):
                    raise ValueError("Dense intrinsics observation image identity or dimensions disagree")
                n = count(fit, "num_obs", required=True)
                numeric(data, "point_id", (n,), integer=True)
                view = numeric(data, "view", (n,), integer=True, empty_layout=True)
                for key, shape in (("uv_h", (n, 2)), ("uv_v", (n, 2)), ("xyz", (n, 3)),
                                   ("overlap", (n,)), ("cycle_px", (n,)), ("precision", (n, 3))):
                    numeric(data, key, shape, empty_layout=key in {"uv_h", "uv_v", "precision"})
                if not isinstance(meta.get("views"), list) or (n and ((view < 0).any() or (view >= len(meta["views"])).any())):
                    raise ValueError("Dense intrinsics observation references a missing panorama view")
                # Every retained numeric array must be safe and finite, including dense grid observations.
                for key in data.files:
                    value = data[key]
                    if key != "meta" and (value.dtype.kind not in "iufb" or not np.isfinite(value).all()):
                        raise ValueError("Invalid dense intrinsics auxiliary observation array")
            num_corr, num_inliers = count(fit, "num_corr"), count(fit, "num_inliers")
            if num_inliers is not None and (num_corr is None or num_inliers > num_corr):
                raise ValueError("Inconsistent dense intrinsics inlier count")
            if (fit["status"] == "no_matches") != (n == 0):
                raise ValueError("Dense intrinsics fit status disagrees with observations")
            fit_path = root / "fit" / (Path(name).stem + ".npz")
            if fit["status"] == "ok":
                if not fit_path.is_file() or not num_inliers:
                    raise ValueError("Successful dense intrinsics fit is missing inliers")
                with np.load(fit_path, allow_pickle=False) as data:
                    for key, shape, integer in (("point_id", (num_inliers,), True), ("uv", (num_inliers, 2), False),
                                                ("xyz", (num_inliers, 3), False), ("num_panos", (num_inliers,), False),
                                                ("source", (num_inliers,), True)):
                        numeric(data, key, shape, integer)
            if kind in accepted:
                if fit["status"] != "ok" or not (root.parent / "models_geolocalized/cameras.bin").is_file():
                    raise ValueError("Accepted dense calibration is missing its fit or new model")
                camera = decision.get("camera", {})
                for values, shape in ((decision.get("R"), (3, 3)), (decision.get("t"), (3,))):
                    array = np.asarray(values)
                    if array.shape != shape or array.dtype.kind not in "iuf" or not np.isfinite(array).all():
                        raise ValueError("Invalid calibrated camera pose")
                params = np.asarray(camera.get("params"))
                if not isinstance(camera.get("model"), str) or params.ndim != 1 or not params.size or params.dtype.kind not in "iuf" or not np.isfinite(params).all():
                    raise ValueError("Invalid calibrated camera parameters")
            counts[kind] += 1
            observations += n
            processed.add(name)
            records.append({"name": name, "scene": root.parent.parent.name, "decision": kind,
                            "status": fit["status"], "observations": n, "fit_correspondences": num_corr,
                            "inliers": num_inliers})
    if not observations:
        raise ValueError("Dense intrinsics produced no real correspondences")
    return {"accepted_updates": sum(counts[kind] for kind in accepted), "correspondences": observations,
            "processed_images": len(processed), "decision_counts": counts, "calibration_decisions": records}


def _dense_camera_changes(workspace, config, env, output):
    """Decode before/after cameras; a rejected update preserves its input camera."""
    result = output / "camera-changes.json"
    script = """import json,sys
from pathlib import Path
import numpy as np
import pycolmap
workspace=Path(sys.argv[1])
rows=[]
for path in sorted(workspace.glob('scenes/*/*-dense_intrinsics/intrinsics/cameras.jsonl')):
 calibrated=path.parent.parent
 original=calibrated.with_name(calibrated.name.removesuffix('-dense_intrinsics'))/'models_geolocalized'
 before=pycolmap.Reconstruction(original)
 before_images={im.name:im for im in before.images.values() if im.has_pose}
 new_path=calibrated/'models_geolocalized'
 after=pycolmap.Reconstruction(new_path) if (new_path/'cameras.bin').is_file() else None
 after_images={im.name:im for im in after.images.values() if im.has_pose} if after else {}
 for line in path.read_text().splitlines():
  if not line.strip(): continue
  row=json.loads(line); name=row['name']; accepted=row['decision'] in ('dist','pp','focal')
  if name not in before_images: raise ValueError('Calibration decision has no registered historic input camera')
  if accepted and name not in after_images: raise ValueError('Accepted camera absent from new calibrated model')
  old=before.cameras[before_images[name].camera_id]
  new=after.cameras[after_images[name].camera_id] if name in after_images else old if after is None else None
  changed=new is not None and (old.model.name!=new.model.name or old.params.shape!=new.params.shape or not np.allclose(old.params,new.params,rtol=1e-10,atol=1e-10))
  rows.append({'name':name,'scene':path.parent.parent.parent.name,'decision':row['decision'],
   'input_camera':{'model':old.model.name,'params':old.params.tolist()},
   'output_camera':None if new is None else {'model':new.model.name,'params':new.params.tolist()},
   'changed':bool(changed),'retained_input':after is None,'registered_in_output':name in after_images})
Path(sys.argv[2]).write_text(json.dumps({'camera_comparisons':rows,
 'changed_camera_intrinsics':sum(row['changed'] for row in rows),
 'unchanged_camera_intrinsics':sum(not row['changed'] and row['output_camera'] is not None for row in rows),
 'unregistered_output_cameras':sum(row['output_camera'] is None for row in rows)}))
"""
    _execute([str(config["_python"]), "-c", script, str(workspace), str(result)],
             config, env, output, output / "camera-comparison.log")
    return json.loads(result.read_text())


def _materialize_upstream_masks(dataset, names):
    """Replace only the original pipeline's confined, matching semantic-mask links."""
    from PIL import Image
    dataset = Path(dataset).resolve(strict=True)
    allowed = {dataset / "workspace/masks" / Path(name).with_suffix(".png"): name for name in names}
    materialized = []
    for path in sorted(dataset.rglob("*")):
        if not path.is_symlink():
            continue
        name = allowed.get(path)
        if name is None:
            raise ValueError("Unexpected symbolic link in research output")
        try:
            target = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("Broken or cyclic upstream semantic-mask link") from exc
        candidates = {dataset / "workspace/masks_semantic" / Path(name).with_suffix(".png"),
                      dataset / "masks" / Path(name).with_suffix(".png")}
        # Compare the resolved link to the exact lexical names. Never accept an
        # alternate link chain or another file merely because it is in the dataset.
        if target not in candidates or not target.is_relative_to(dataset) or not target.is_file():
            raise ValueError("Upstream semantic-mask link does not target its matching staged mask")
        with Image.open(dataset / "images" / name) as original, Image.open(target) as mask:
            if mask.mode != "L" or mask.size != original.size:
                raise ValueError("Upstream semantic-mask link has invalid mask pixels or dimensions")
            mask.verify()
        fd, temporary_name = tempfile.mkstemp(prefix=path.name + ".materialized-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as output, target.open("rb") as source:
                shutil.copyfileobj(source, output)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        materialized.append(path.relative_to(dataset).as_posix())
    return materialized


def run(stage, inputs, parameters, output):
    # Import lazily to keep checksum/config tools usable without processing dependencies.
    try:
        from .component_runner import staged_file, extract_archive, pack_archive, write_json
    except ImportError:
        # The adapter is also loaded by file specification from the native CLI
        # test harness. Resolve its sibling without changing global import paths.
        import importlib.util
        spec = importlib.util.spec_from_file_location("historic_reconstruction_helpers", Path(__file__).with_name("component_runner.py"))
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        staged_file, extract_archive = runner.staged_file, runner.extract_archive
        pack_archive, write_json = runner.pack_archive, runner.write_json
    if stage not in STAGES or set(parameters) - PARAMETERS[stage]:
        raise ValueError("Unsupported historic research stage or parameter")
    if set(inputs) - {"input_file", "gps_file", "bounds_file"}:
        raise ValueError("Unsupported historic research input")
    config = load_config(stage)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    source = staged_file(inputs, "input_file")
    dataset = output / "dataset"
    extract_archive(source, dataset)
    # Upstream loads pickle and object-array caches. Never load caller-provided ones.
    for path in dataset.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".pkl", ".pickle", ".npy", ".pt", ".pth", ".ckpt", ".py", ".so"}:
            raise ValueError("Research input bundles cannot contain executable code, weights, or pickle caches")
    images, names = _images(dataset)
    if stage in {"segmentation", "original_sfm", "geolocalization"}:
        mask_names = [Path(name).with_suffix(".png").as_posix() for name in names]
        if len(set(mask_names)) != len(mask_names):
            raise ValueError("Image names collide after conversion to segmentation mask filenames")
    if stage == "dense_intrinsics" or parameters.get("dense_intrinsics", False):
        if len({Path(name).stem for name in names}) != len(names):
            raise ValueError("Image names collide after conversion to dense intrinsics evidence filenames")
    if stage not in {"segmentation", "geolocalization", "dense_intrinsics"} and len(names) < 3:
        raise ValueError("Reconstruction requires at least three images")
    if stage == "segmentation" and (dataset / "masks").exists():
        shutil.rmtree(dataset / "masks")
    workspace = dataset / "workspace"
    if stage != "dense_intrinsics" and workspace.exists():
        raise ValueError("This stage requires a fresh input dataset without workspace/")
    if stage == "dense_intrinsics":
        if not (workspace / "scenes").is_dir():
            raise ValueError("Dense intrinsics requires the geolocalization workspace/scenes/ bundle")
        for path in workspace.glob("scenes/*/*-dense_intrinsics"):
            shutil.rmtree(path)
        for path in workspace.glob("scenes/*/.done/intrinsics_*"):
            path.unlink()
    workspace.mkdir(parents=True, exist_ok=True)
    geo = None
    if stage == "geolocalization":
        candidates = []
        for key, filename, flag in (("gps_file", "gps.json", "--gps-json"), ("bounds_file", "bounds.json", "--bounds-json")):
            value = staged_file(inputs, key, required=False) if inputs.get(key) else dataset / filename
            if value is not None and value.is_file():
                _validate_geo(value, names, bounds=key == "bounds_file")
                candidates.append((flag, value))
        if len(candidates) != 1:
            raise ValueError("Supply exactly one GPS or bounds JSON input")
        geo = candidates[0]
    if stage == "refine_keypoints":
        import yaml
        refine_config = yaml.safe_load((config["_source"] / "matching/refine_keypoints/demo.yaml").read_text())
        refine_config["resume_ckpt"] = str(_asset(config, "vggsfm_weights"))
        refine_config["auto_download_ckpt"] = False
        config["_refine_config"] = output / "vggsfm-config.yaml"
        config["_refine_config"].write_text(yaml.safe_dump(refine_config))
    command = build_command(stage, config, dataset, workspace, parameters, geo)
    env = _environment(config, output)
    _preflight(stage, config, env, output, parameters)
    if stage in {"refine_keypoints", "mvs"}:
        _model_report([dataset / "sparse"], images, config, env, output, "input-models.json")
    if stage == "dense_intrinsics":
        input_models = sorted({path.parent for pattern in ("scenes/*/*/models_geolocalized/cameras.bin", "scenes/*/models_gsv/cameras.bin") for path in workspace.glob(pattern)})
        input_model_reports = _model_report(input_models, images, config, env, output, "input-models.json")
        _require_historic_registration(input_model_reports)
    if stage == "mvs":
        # Generate tuples from the checked model and rebuild rectification; do not
        # consume caller-selected frame paths from cached tuple files.
        if (dataset / "dense").exists():
            shutil.rmtree(dataset / "dense")
        script = r"""import sys
from pathlib import Path
import pycolmap
from historic_reconstruction_pipeline.meshing.generate_mvs_tuples import compute_covisibility_efficiently
root=Path(sys.argv[1])
pycolmap.undistort_images(root/'dense',root/'sparse',root/'images')
rec=pycolmap.Reconstruction(root/'dense'/'sparse')
images=sorted(rec.images.values(),key=lambda im:im.image_id)
if len(images)<8: raise RuntimeError('MVS requires at least eight registered views for seven source views')
tuples=compute_covisibility_efficiently(images,images,INVALID_POINT_ID=pycolmap.INVALID_POINT3D_ID)
rows=[f"{root.name} {key} {' '.join(map(str,values))}" for key,values in sorted(tuples.items()) if len(values)==7]
if not rows: raise RuntimeError('No complete MVS view tuples')
(root/'mvs_tuples.txt').write_text('\n'.join(rows)+'\n')
"""
        _execute([str(config["_python"]), "-c", script, str(dataset)], config, env, output, output / "mvs-prepare.log")
    working_directory = _asset(config, "mvs_repository") if stage == "mvs" else output
    _execute(command, config, env, working_directory, output / "stage.log")
    metrics = {"stage": stage, "input_images": len(names), "upstream_execution": True}
    if stage == "segmentation":
        from PIL import Image
        for name in names:
            mask = (dataset / "masks" / name).with_suffix(".png")
            if not mask.is_file():
                raise ValueError("Segmentation did not produce a mask for every image")
            with Image.open(images / name) as original, Image.open(mask) as prediction:
                if original.size != prediction.size or prediction.mode != "L":
                    raise ValueError("Segmentation mask dimensions or type are invalid")
        metrics["masks"] = len(names)
    elif stage == "mvs":
        meshes = list(workspace.glob("**/meshes/**/*.ply"))
        if not meshes:
            raise ValueError("MVS produced no fused mesh")
        metrics.update(_mvs_mesh_metrics(meshes[0]))
        metrics.update(fusion_max_depth=_finite_number(parameters, "fusion_max_depth", 3.0, 0.01, 10000),
                       fusion_resolution=_finite_number(parameters, "fusion_resolution", 0.04, 0.001, 10),
                       fusion_units="input COLMAP model units")
    else:
        patterns = {
            "original_sfm": "models_cluster*/[0-9]*/cameras.bin",
            "geolocalization": "scenes/*/*/models_geolocalized/cameras.bin",
            "dense_intrinsics": "scenes/*/*-dense_intrinsics/models_geolocalized/cameras.bin",
            "refine_keypoints": "refined/cameras.bin",
        }
        paths = sorted({path.parent for path in workspace.glob(patterns[stage])})
        if stage == "dense_intrinsics":
            metrics.update(_dense_intrinsics_evidence(workspace, names))
            metrics["calibration_outcome"] = "calibrated_camera_model" if metrics["accepted_updates"] else "executed_no_accepted_updates"
            if not metrics["accepted_updates"]:
                if paths:
                    raise ValueError("Dense intrinsics wrote an unexplained model without accepted camera updates")
                paths = input_models
                metrics["retained_input_models"] = True
        metrics["models"] = _model_report(paths, images, config, env, output)
        if stage in {"geolocalization", "dense_intrinsics"}:
            _require_historic_registration(metrics["models"])
    if stage == "dense_intrinsics" or (stage == "geolocalization" and parameters.get("dense_intrinsics", False)):
        if stage == "geolocalization":
            metrics["dense_intrinsics"] = _dense_intrinsics_evidence(workspace, names)
        metrics.update(_dense_camera_changes(workspace, config, env, output))
    if stage == "original_sfm":
        metrics.update(json.loads((workspace / "adapter-settings.json").read_text()))
    if stage == "geolocalization":
        metrics["materialized_mask_links"] = _materialize_upstream_masks(dataset, names)
    # Accept only results produced without changing the pinned installation.
    _assert_runtime_unchanged(config)
    # Pickle caches are rebuildable implementation details, not portable artifacts.
    omitted = []
    for path in dataset.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".pkl", ".pickle", ".npy"}:
            omitted.append(path.relative_to(dataset).as_posix())
            path.unlink()
    report = output / "research-report.json"
    write_json(report, {"schema_version": 1, "metrics": metrics, "source_sha256": config["source"]["sha256"],
                        "input_sha256": file_sha256(source), "parameters": parameters, "omitted_rebuildable_caches": omitted,
                        "runtime_pins": {"python_sha256": config["python"]["sha256"], "dependencies": [row["sha256"] for row in config.get("dependencies", [])], "assets": {key: row["sha256"] for key, row in config.get("assets", {}).items()}},
                        "coordinate_reference": "local ENU; retain workspace/scenes/*/georef.json" if stage in {"geolocalization", "dense_intrinsics"} else "upstream model coordinates",
                        "georeferenced_camera_export": "not implemented by upstream" if stage == "geolocalization" else None})
    shutil.copy2(report, dataset / "research-report.json")
    logs = dataset / "research-logs"
    logs.mkdir(exist_ok=True)
    for log in output.glob("*.log"):
        shutil.copy2(log, logs / log.name)
    archive = pack_archive(dataset, output / "research-workspace.zip")
    files = {"workspace_bundle": archive, "report": report}
    if stage == "segmentation":
        files["dataset_bundle"] = archive
    return files, metrics
