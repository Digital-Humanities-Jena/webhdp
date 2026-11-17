"""Install immutable central component/pipeline definitions from operator paths.

Preparing a package only creates local scientific files. Copying/registering it
on the HPC is an operator action; integrating websites never receive SSH access.
"""

from copy import deepcopy
import json
from pathlib import Path
import re
import shutil

import yaml

from .runner import SOURCE_FILES, sha256, source_digest


ROOT = Path(__file__).resolve().parent
COMPONENT_KEY = "link_reprojector_photogrammetry"
PUBLICATION = {
    "id": "link-photogrammetry", "name": "Photograph 3D reconstruction",
    "description": "Reconstruct overlapping photographs on the central WebHDP GPU using genuine COLMAP photogrammetry, with registration quality checks, calibrated cameras, measured point cloud, mesh and evidence package.",
    "pipeline_identifier": "link_photogrammetry", "pipeline_version": "1.0.0", "enabled": True,
    "execution_mode": "bundle", "step_timeout_seconds": 7200,
    "input": {"min_files": 3, "max_files": 30, "extensions": [".jpg", ".jpeg", ".png"]},
    "parameters": {
        "max_image_size": {"step_id": "reconstruct", "parameter": "max_image_size", "type": "integer", "minimum": 640, "maximum": 2400, "default": 960, "label": "Reconstruction image size"},
        "mesher": {"step_id": "reconstruct", "parameter": "mesher", "type": "string", "enum": ["poisson", "delaunay"], "default": "poisson", "label": "Surface reconstruction"},
    },
    "hpc": {"enabled": True, "walltime_hours": 12, "gpu_count": 1, "retain_allocation": True,
            "reuse_retained_allocation": True},
}


def _absolute(value, field):
    if not isinstance(value, str) or not value.startswith("/") or ".." in Path(value).parts or "\x00" in value:
        raise ValueError(field + " must be an absolute trusted operator path.")
    return value.rstrip("/")


def _checksum(value, field):
    if not isinstance(value, str) or not re.fullmatch("[a-f0-9]{64}", value):
        raise ValueError(field + " must be a SHA256 digest.")
    return value


def definitions(*, runtime_python, runtime_colmap, remote_component_root, colmap_sha256,
                reprojector_source_sha256, partition="gpu", gpu_type=None):
    """Return one manifest, native pipeline and public Link publication."""
    runtime_python = _absolute(runtime_python, "runtime_python")
    runtime_colmap = _absolute(runtime_colmap, "runtime_colmap")
    remote_root = _absolute(remote_component_root, "remote_component_root")
    _checksum(colmap_sha256, "colmap_sha256")
    _checksum(reprojector_source_sha256, "reprojector_source_sha256")
    manifest = yaml.safe_load((ROOT / "component.yaml").read_text())
    profile = manifest["execution"]["profiles"][0]
    profile["entrypoint"] = [
        "/usr/bin/env", "-u", "PYTHONPATH", "-u", "PYTHONHOME", "-u", "LD_LIBRARY_PATH",
        "OPENBLAS_NUM_THREADS=1", "OMP_NUM_THREADS=4", "QT_QPA_PLATFORM=offscreen",
        "PYTHONDONTWRITEBYTECODE=1", runtime_python, remote_root + "/runner.py",
        "--reprojector-source", remote_root + "/source",
        "--reprojector-source-sha256", reprojector_source_sha256,
        "--colmap", runtime_colmap, "--colmap-sha256", colmap_sha256,
        "--expected-runner-sha256", sha256(ROOT / "runner.py"), "--cpus", "4",
    ]
    publication = deepcopy(PUBLICATION)
    publication["hpc"]["partition"] = partition
    if gpu_type:
        publication["hpc"]["gpu_type"] = gpu_type
    pipeline = {
        "identifier": publication["pipeline_identifier"], "name": publication["name"],
        "description": publication["description"], "version": "1.0.0", "status": "active",
        "processingMode": "root", "tags": ["webhdp-link", "photogrammetry"],
        "steps": [{"id": "reconstruct", "name": "COLMAP reconstruction", "component_ref": COMPONENT_KEY,
                   "execution_profile_ref": "hpc", "scope": "record",
                   "parameters": {name: item["default"] for name, item in publication["parameters"].items()},
                   "input_bindings": [{"kind": "input", "target": "input_files", "type": "pipeline_source_files"}]}],
    }
    return manifest, pipeline, publication


def seed(service, **trusted_config):
    """Return a list containing the Link publication after native registration."""
    manifest, pipeline, publication = definitions(**trusted_config)
    service.import_component_from_manifest(manifest, source_path=str(ROOT), source_type="external")
    service.create_pipeline_version_from_config(pipeline["identifier"], pipeline, activate=True)
    return [publication]


def prepare_installation(destination, *, reprojector_source, **trusted_config):
    """Create a minimal, checksummed install payload; no transport or credentials.

    reprojector_source is the local repository root (containing python/).
    The package deliberately excludes repository metadata, caches, tests, notes,
    credentials, development tools and any unrelated application source.
    """
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    target = destination / "source/reprojector"
    target.mkdir(parents=True)
    source = Path(reprojector_source) / "python/reprojector"
    for name in SOURCE_FILES:
        shutil.copyfile(source / name, target / name)
    shutil.copyfile(ROOT / "runner.py", destination / "runner.py")
    digest = source_digest(destination / "source")
    supplied = trusted_config.pop("reprojector_source_sha256", digest)
    if supplied != digest:
        raise ValueError("Configured Reprojector source checksum does not match the installation payload.")
    manifest, _, _ = definitions(reprojector_source_sha256=digest, **trusted_config)
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    remote_root = trusted_config["remote_component_root"].rstrip("/")
    registry = {"component_key": COMPONENT_KEY, "version": "1.0.0", "manifest_path": remote_root + "/manifest.json",
                "manifest_sha256": sha256(manifest_path)}
    (destination / "component.json").write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n")
    files = {str(path.relative_to(destination)): sha256(path) for path in sorted(destination.rglob("*")) if path.is_file()}
    (destination / "checksums.json").write_text(json.dumps(files, indent=2, sort_keys=True) + "\n")
    return {**trusted_config, "reprojector_source_sha256": digest}
