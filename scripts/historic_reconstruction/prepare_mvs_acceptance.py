#!/usr/bin/env python3
"""Pin an already provisioned private MVS runtime for real GPU acceptance.

Run with Python >=3.11 after the official model and auxiliary model caches have
been downloaded. This does not install software or replace upstream algorithms.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path


def digest(path, algorithm="sha256"):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, algorithm).digest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--runner-dir", type=Path)
    parser.add_argument("--preserve-pins", action="store_true", help="Refuse any change to an existing checked installation")
    args = parser.parse_args()
    root, source_input = args.root.resolve(), args.input.resolve(strict=True)
    runner_dir = (args.runner_dir or root / "runtime").resolve(strict=True)
    spec = importlib.util.spec_from_file_location("mvs_acceptance_upstream", runner_dir / "upstream.py")
    upstream = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(upstream)

    def pin(path, tree=False):
        result = {"path": str(path), "sha256": upstream.tree_sha256(path) if tree else digest(path).hex()}
        if tree:
            result["kind"] = "tree"
        return result

    checkpoint = root / "assets/mvsanywhere_hero.ckpt"
    model_md5 = base64.b64encode(digest(checkpoint, "md5")).decode()
    if model_md5 != "bZ23qETYc6eQuaZQPfevFA==":
        raise ValueError("Official MVS checkpoint does not match the publisher's x-goog-hash MD5")
    config = {
        "schema_version": 1,
        "enabled_stages": ["mvs"],
        "allow_network": False,
        "timeout_seconds": 1800,
        "python": pin(root / "env-py310/bin/python"),
        "source": pin(root / "upstream/historic_reconstruction_pipeline", True),
        "dependencies": [pin(root / "source/src", True), pin(root / "dependencies/hloc", True)],
        "assets": {
            "mvs_repository": pin(root / "source", True),
            "mvs_extension_cache": pin(root / "torch-extensions", True),
            "mvs_cuda_compiler": pin(root / "env-py310/bin/nvcc"),
            "mvs_cxx_compiler": pin(root / "env-py310/bin/x86_64-conda-linux-gnu-c++"),
            "mvs_ninja": pin(root / "env-py310/bin/ninja"),
            "mvs_model_config": pin(root / "source/configs/models/mvsanywhere_model.yaml"),
            "mvs_data_config": pin(root / "source/configs/data/colmap/colmap_empty.yaml"),
            "mvs_checkpoint": pin(checkpoint),
            "torch_cache": pin(root / "torch-cache", True),
        },
    }
    if args.preserve_pins:
        previous = json.loads((root / "operator-config.json").read_text())
        if config != previous:
            raise ValueError("Pinned installation changed; do not replace evidence with new checksums")
    # The measured Statue input spans depths beyond the upstream 3-unit default.
    # Keep its original scale and explicitly record the chosen fusion clip.
    request = {"inputs": {"input_file": str(source_input)}, "parameters": {
        "batch_size": 1, "fusion_max_depth": 30.0, "fusion_resolution": 0.04}}
    provenance = {
        "model_url": "https://storage.googleapis.com/niantic-lon-static/research/mvsanywhere/mvsanywhere_hero.ckpt",
        "model_bytes": checkpoint.stat().st_size,
        "model_sha256": config["assets"]["mvs_checkpoint"]["sha256"],
        "model_publisher_md5_base64": model_md5,
        "model_publisher_md5_verified": True,
        "mvs_repository": "https://github.com/nianticlabs/mvsanywhere",
        "mvs_commit": subprocess.check_output(["git", "-C", str(root / "source"), "rev-parse", "HEAD"], text=True).strip(),
        "input_sha256": digest(source_input).hex(),
        "wrapper_directory": str(runner_dir),
        "wrapper_sha256": {name: digest(runner_dir / name).hex() for name in ("component_runner.py", "upstream.py")},
    }
    for name, value in (("operator-config.json", config), ("request.json", request), ("provisioning-receipt.json", provenance)):
        (root / name).write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    main()
