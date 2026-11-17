#!/usr/bin/env python3
"""WebHDP file-contract entrypoint for the published Zenodo component adapters."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile
import traceback

try:
    from .common import sha256, write_json
except ImportError:
    from common import sha256, write_json

COMPONENTS = {
    "validate_file_integrity", "hdpc_exporter", "obj_to_glb_converter",
    "obj_statistics_extractor", "mtl_metadata_extractor", "glb_metadata_extractor",
    "image_metadata_extractor",
}


def run_component(component, request, output):
    if component not in COMPONENTS:
        raise ValueError("Unsupported component")
    if not isinstance(request, dict) or not isinstance(request.get("inputs"), dict):
        raise ValueError("A request with inputs is required")
    raw = request.get("parameters") or {}
    if not isinstance(raw, dict):
        raise ValueError("Parameters must be an object")
    if component in {"validate_file_integrity", "hdpc_exporter"}:
        try:
            from . import data_components as stage
        except ImportError:
            import data_components as stage
    elif component in {"obj_to_glb_converter", "obj_statistics_extractor"}:
        try:
            from . import obj_components as stage
        except ImportError:
            import obj_components as stage
    else:
        try:
            from . import metadata_components as stage
        except ImportError:
            import metadata_components as stage
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="community-", dir=output) as temporary:
        work = Path(temporary)
        files, summary = stage.run(component, request["inputs"], raw, work)
        outputs, artifacts, destinations = {}, [], {}
        for role, source in files.items():
            source = Path(source).resolve(strict=True)
            if not source.is_relative_to(work) or not source.is_file():
                raise ValueError("Component returned an unsafe or missing artifact")
            target = output / source.name
            if target.name in destinations:
                if destinations[target.name] != source:
                    raise ValueError("Artifact filename collision")
            else:
                if target.exists():
                    raise ValueError("Output already exists; use a fresh run directory")
                shutil.copyfile(source, target)
                destinations[target.name] = source
                artifacts.append({"name": target.name, "path": str(target), "artifact_kind": "file",
                                  "metadata": {"role": role, "sha256": sha256(target), "bytes": target.stat().st_size}})
            outputs[role] = str(target)
    return {"success": True, "status": "completed", "outputs": outputs, "artifacts": artifacts, "summary": summary}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=sorted(COMPONENTS))
    parser.add_argument("--webhdp-input", default=os.environ.get("WEBHDP_COMPONENT_REQUEST"))
    parser.add_argument("--webhdp-output-dir", default=os.environ.get("WEBHDP_OUTPUT_DIR"))
    parser.add_argument("--webhdp-result", default=os.environ.get("WEBHDP_COMPONENT_RESPONSE"))
    args = parser.parse_args()
    if not all((args.webhdp_input, args.webhdp_output_dir, args.webhdp_result)):
        parser.error("Provide request, output directory and response path")
    try:
        result = run_component(args.component, json.loads(Path(args.webhdp_input).read_text()), args.webhdp_output_dir)
    except Exception as exc:
        traceback.print_exc()
        result = {"success": False, "status": "failed", "outputs": {}, "error": str(exc)}
    write_json(args.webhdp_result, result)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
