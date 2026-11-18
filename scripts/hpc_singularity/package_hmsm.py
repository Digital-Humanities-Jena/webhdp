#!/usr/bin/env python3
"""Generate HMSM Studio installation requests for a verified HPC SIF."""

import argparse
from copy import deepcopy
import json
from pathlib import Path, PurePosixPath
import re

import yaml


CATALOG = Path(__file__).resolve().parents[2] / "external_code"
COMPONENTS = ("hmsm_scan_digitizer", "hmsm_midi_interpretation", "hmsm_midi_reconstruction")


def package_hmsm(sif_source: str, sif_sha256: str, version: str) -> dict:
    source = PurePosixPath(sif_source)
    if not source.is_absolute() or source.suffix != ".sif" or ".." in source.parts:
        raise ValueError("Use an absolute .sif path on the cluster.")
    if not re.fullmatch(r"[0-9a-f]{64}", sif_sha256):
        raise ValueError("Use the lowercase SHA-256 of the verified SIF.")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Use an immutable component version such as 1.0.1.")

    packages = {}
    for key in COMPONENTS:
        manifest = yaml.safe_load((CATALOG / key / "component.yaml").read_text(encoding="utf-8"))
        local = next(profile for profile in manifest["execution"]["profiles"] if profile["id"] == "local_docker")
        manifest["metadata"]["version"] = version
        manifest["distribution"]["installation_scope"] = ["hpc_sif"]
        manifest["execution"]["profiles"] = [{
            "id": "hpc_singularity",
            "adapter": "hpc_link",
            "handler": "generic_singularity_component",
            "runtime": "singularity",
            "image": source.name,
            "entrypoint": deepcopy(local["entrypoint"]),
            "resources": deepcopy(local["resources"]),
        }]
        test = manifest["install"]["test"]
        manifest["install"] = {
            "strategies": [{"id": "hpc_sif", "runtime": "singularity", "profile": "hpc_singularity"}],
        }
        manifest["hpc"] = {"test": test}
        packages[key] = {
            "install_strategy": "hpc_sif",
            "manifest": manifest,
            "sif_source": str(source),
            "sif_sha256": sif_sha256,
        }
    return packages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sif", required=True, help="Absolute path of the verified SIF on the cluster")
    parser.add_argument("--sha256", required=True, help="Verified SHA-256 of the SIF")
    parser.add_argument("--version", required=True, help="Version assigned to these installed components")
    args = parser.parse_args()
    try:
        print(json.dumps(package_hmsm(args.sif, args.sha256, args.version), indent=2))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
