#!/usr/bin/env python3
"""SIF entrypoint for the WebHDP glTF/GLB validator component."""

from __future__ import annotations

import json
import os
import struct
import sys
import time
from pathlib import Path
from typing import Any


def _read_request() -> dict[str, Any]:
    request_path = os.environ.get("WEBHDP_COMPONENT_REQUEST")
    if not request_path:
        raise RuntimeError("WEBHDP_COMPONENT_REQUEST is not set")
    with open(request_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError("Component request must be a JSON object")
    return payload


def _write_response(payload: dict[str, Any]) -> None:
    response_path = os.environ.get("WEBHDP_COMPONENT_RESPONSE")
    if response_path:
        Path(response_path).parent.mkdir(parents=True, exist_ok=True)
        with open(response_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
    print(json.dumps(payload, sort_keys=True))


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_input(value: Any) -> Path:
    text = str(value or "").strip()
    if not text:
        raise RuntimeError("input_file is required")
    candidate = Path(text)
    if candidate.is_absolute() and candidate.exists():
        return candidate.resolve()
    input_root = Path(os.environ.get("WEBHDP_INPUT_DIR") or "/inputs")
    relative = input_root / candidate
    if relative.exists():
        return relative.resolve()
    by_name = input_root / candidate.name
    if by_name.exists():
        return by_name.resolve()
    raise FileNotFoundError(f"Could not resolve input_file {text!r}")


def _validate_glb_header(path: Path, errors: list[str], warnings: list[str]) -> dict[str, Any]:
    details: dict[str, Any] = {}
    with open(path, "rb") as handle:
        header = handle.read(12)
    if len(header) < 12:
        errors.append("GLB header is incomplete.")
        return details
    magic, version, length = struct.unpack("<III", header)
    details.update({"magic": magic, "version": version, "declared_length": length})
    if magic != 0x46546C67:
        errors.append("GLB magic header is invalid.")
    if version != 2:
        errors.append(f"Unsupported GLB version {version}; expected 2.")
    actual = path.stat().st_size
    if length != actual:
        warnings.append(f"GLB declared length {length} differs from actual size {actual}.")
    return details


def _inspect_with_pygltflib(path: Path, errors: list[str], warnings: list[str]) -> dict[str, Any]:
    try:
        from pygltflib import GLTF2
    except Exception as exc:
        warnings.append(f"pygltflib is not available; structural checks are limited: {exc}")
        return {}

    try:
        gltf = GLTF2().load(str(path))
    except Exception as exc:
        errors.append(f"pygltflib could not load the asset: {exc}")
        return {}

    return {
        "scene_count": len(gltf.scenes or []),
        "node_count": len(gltf.nodes or []),
        "mesh_count": len(gltf.meshes or []),
        "material_count": len(gltf.materials or []),
        "image_count": len(gltf.images or []),
        "animation_count": len(gltf.animations or []),
    }


def main() -> int:
    started = time.time()
    request = _read_request()
    inputs = request.get("inputs") if isinstance(request.get("inputs"), dict) else {}
    parameters = request.get("parameters") if isinstance(request.get("parameters"), dict) else {}
    path = _resolve_input(inputs.get("input_file"))
    errors: list[str] = []
    warnings: list[str] = []

    suffix = path.suffix.lower()
    if suffix not in {".glb", ".gltf"}:
        errors.append(f"Unsupported file extension {suffix}; expected .glb or .gltf.")
    size_bytes = path.stat().st_size
    max_size = int(parameters.get("max_file_size_mb") or 512) * 1024 * 1024
    if size_bytes > max_size:
        warnings.append(f"File size {size_bytes} exceeds configured warning threshold {max_size}.")

    details: dict[str, Any] = {"size_bytes": size_bytes, "extension": suffix}
    if suffix == ".glb":
        details["glb_header"] = _validate_glb_header(path, errors, warnings)
    details["gltf"] = _inspect_with_pygltflib(path, errors, warnings)
    if _as_bool(parameters.get("require_textures")) and not details.get("gltf", {}).get("image_count"):
        warnings.append("No image textures are declared.")
    strict = _as_bool(parameters.get("strict"))
    success = not errors and not (strict and warnings)

    output_dir = Path(os.environ.get("WEBHDP_OUTPUT_DIR") or "/outputs")
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{path.stem}_validation_report.json"
    report = {
        "valid": success,
        "errors": errors,
        "warnings": warnings,
        "details": details,
        "input_file": str(path),
        "duration": time.time() - started,
    }
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)

    response = {
        "success": success,
        "status": "completed" if success else "failed",
        "error": None if success else "; ".join(errors or warnings),
        "outputs": {"validation_report": str(report_path)},
        "artifacts": [
            {
                "artifact_kind": "file",
                "name": report_path.name,
                "remote_path": str(report_path),
                "metadata": {"component": "gltf_validator"},
            }
        ],
        "validation": report,
        "logs": {"stdout": f"Validated {path.name}", "stderr": ""},
    }
    _write_response(response)
    return 0 if success else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _write_response({"success": False, "status": "failed", "error": str(exc), "logs": {"stdout": "", "stderr": str(exc)}})
        raise
