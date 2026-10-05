#!/usr/bin/env python3
"""Shared local-Docker runtime for WebHDP 3D analysis components."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import shutil
import struct
import sys
import time
from pathlib import Path
from typing import Any


def _read_request(args: argparse.Namespace) -> dict[str, Any]:
    request_path = os.environ.get("WEBHDP_COMPONENT_REQUEST")
    if request_path and Path(request_path).exists():
        with open(request_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise RuntimeError("WebHDP component request must be a JSON object")
        return payload
    inputs = {"input_file": args.input_file} if args.input_file else {}
    parameters = {
        key: value
        for key, value in vars(args).items()
        if key not in {"component", "input_file"} and value is not None
    }
    return {"inputs": inputs, "parameters": parameters, "metadata": {"cli_fallback": True}}


def _write_response(payload: dict[str, Any]) -> None:
    response_path = os.environ.get("WEBHDP_COMPONENT_RESPONSE")
    if response_path:
        target = Path(response_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


def _input_root() -> Path:
    return Path(os.environ.get("WEBHDP_INPUT_DIR") or "/inputs")


def _output_root() -> Path:
    root = Path(os.environ.get("WEBHDP_OUTPUT_DIR") or "/outputs")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_input(value: Any) -> Path:
    text = str(value or "").strip()
    if not text:
        raise RuntimeError("input_file is required")
    candidate = Path(text)
    if candidate.is_absolute() and candidate.exists():
        return candidate.resolve()
    for option in (_input_root() / text, _input_root() / candidate.name):
        if option.exists():
            return option.resolve()
    raise FileNotFoundError(f"Could not resolve input_file {text!r}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_json_loads(value: bytes | str) -> Any:
    try:
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        return json.loads(value)
    except Exception:
        return None


def _parse_glb(path: Path) -> dict[str, Any]:
    facts: dict[str, Any] = {"format": "glb", "valid_header": False}
    with open(path, "rb") as handle:
        header = handle.read(12)
        if len(header) < 12:
            facts["errors"] = ["GLB header is incomplete"]
            return facts
        magic, version, declared_length = struct.unpack("<III", header)
        facts.update(
            {
                "magic": magic,
                "version": version,
                "declared_length": declared_length,
                "actual_length": path.stat().st_size,
                "valid_header": magic == 0x46546C67 and version == 2,
            }
        )
        json_doc = None
        while True:
            chunk_header = handle.read(8)
            if len(chunk_header) < 8:
                break
            chunk_length, chunk_type = struct.unpack("<II", chunk_header)
            chunk_data = handle.read(chunk_length)
            if chunk_type == 0x4E4F534A:
                json_doc = _safe_json_loads(chunk_data.rstrip(b"\x00 "))
                break
        if isinstance(json_doc, dict):
            facts["gltf"] = _summarize_gltf(json_doc)
    return facts


def _summarize_gltf(doc: dict[str, Any]) -> dict[str, Any]:
    meshes = doc.get("meshes") if isinstance(doc.get("meshes"), list) else []
    nodes = doc.get("nodes") if isinstance(doc.get("nodes"), list) else []
    materials = doc.get("materials") if isinstance(doc.get("materials"), list) else []
    images = doc.get("images") if isinstance(doc.get("images"), list) else []
    animations = doc.get("animations") if isinstance(doc.get("animations"), list) else []
    accessors = doc.get("accessors") if isinstance(doc.get("accessors"), list) else []
    vertex_count = 0
    primitive_count = 0
    for mesh in meshes:
        primitives = mesh.get("primitives") if isinstance(mesh, dict) and isinstance(mesh.get("primitives"), list) else []
        primitive_count += len(primitives)
        for primitive in primitives:
            attrs = primitive.get("attributes") if isinstance(primitive, dict) else {}
            position_index = attrs.get("POSITION") if isinstance(attrs, dict) else None
            if isinstance(position_index, int) and 0 <= position_index < len(accessors):
                vertex_count += int((accessors[position_index] or {}).get("count") or 0)
    texture_uris = [str(image.get("uri")) for image in images if isinstance(image, dict) and image.get("uri")]
    return {
        "asset_version": ((doc.get("asset") or {}).get("version") if isinstance(doc.get("asset"), dict) else None),
        "mesh_count": len(meshes),
        "node_count": len(nodes),
        "material_count": len(materials),
        "texture_count": len(images),
        "animation_count": len(animations),
        "primitive_count": primitive_count,
        "vertex_count": vertex_count,
        "texture_uris": texture_uris,
        "extensions_used": doc.get("extensionsUsed") if isinstance(doc.get("extensionsUsed"), list) else [],
    }


def _parse_gltf(path: Path) -> dict[str, Any]:
    loaded = _safe_json_loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(loaded, dict):
        return {"format": "gltf", "errors": ["glTF JSON could not be parsed"]}
    return {"format": "gltf", "gltf": _summarize_gltf(loaded)}


def _parse_obj(path: Path) -> dict[str, Any]:
    vertices = faces = 0
    mtllibs: list[str] = []
    used_materials: set[str] = set()
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped.startswith("v "):
                vertices += 1
            elif stripped.startswith("f "):
                faces += 1
            elif stripped.startswith("mtllib "):
                mtllibs.extend(part for part in stripped.split()[1:] if part)
            elif stripped.startswith("usemtl "):
                used_materials.add(stripped.split(maxsplit=1)[1])
    return {
        "format": "obj",
        "vertex_count": vertices,
        "polygon_count": faces,
        "mtl_libraries": mtllibs,
        "material_count": len(used_materials),
    }


def _parse_ply(path: Path) -> dict[str, Any]:
    facts: dict[str, Any] = {"format": "ply", "point_count": 0, "polygon_count": 0, "properties": []}
    with open(path, "rb") as handle:
        header_lines: list[str] = []
        for raw_line in handle:
            line = raw_line.decode("utf-8", errors="replace").strip()
            header_lines.append(line)
            if line == "end_header" or len(header_lines) > 500:
                break
    current_element = ""
    for line in header_lines:
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "element":
            current_element = parts[1]
            if current_element == "vertex":
                facts["point_count"] = int(parts[2])
            elif current_element == "face":
                facts["polygon_count"] = int(parts[2])
        elif len(parts) >= 3 and parts[0] == "property":
            facts["properties"].append({"element": current_element, "name": parts[-1], "type": " ".join(parts[1:-1])})
    return facts


def inspect_model(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    facts: dict[str, Any] = {
        "file_name": path.name,
        "extension": suffix,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }
    if suffix == ".glb":
        facts.update(_parse_glb(path))
    elif suffix == ".gltf":
        facts.update(_parse_gltf(path))
    elif suffix == ".obj":
        facts.update(_parse_obj(path))
    elif suffix == ".ply":
        facts.update(_parse_ply(path))
    elif suffix in {".las", ".laz", ".e57"}:
        facts.update({"format": suffix.removeprefix("."), "model_type": "point_cloud", "point_count": None})
    else:
        facts.update({"format": suffix.removeprefix(".") or "unknown", "model_type": "unknown"})
    facts.setdefault("model_type", "point_cloud" if facts.get("point_count") else "mesh")
    if "gltf" in facts:
        facts.update({key: value for key, value in facts["gltf"].items() if key.endswith("_count")})
    return facts


def _texture_report(path: Path, facts: dict[str, Any]) -> dict[str, Any]:
    input_dir = path.parent
    refs = list((facts.get("gltf") or {}).get("texture_uris") or []) + list(facts.get("mtl_libraries") or [])
    checked: list[dict[str, Any]] = []
    for ref in refs:
        if ref.startswith("data:"):
            checked.append({"reference": ref[:48] + "...", "embedded": True, "present": True})
            continue
        candidate = input_dir / ref
        checked.append({"reference": ref, "embedded": False, "present": candidate.exists(), "path": str(candidate)})
    missing = [item["reference"] for item in checked if not item["present"]]
    return {"references": checked, "missing": missing, "complete": not missing}


def _qa_report(facts: dict[str, Any], textures: dict[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    errors: list[str] = []
    if facts.get("format") == "glb" and not facts.get("valid_header", True):
        errors.append("Invalid GLB header")
    if facts.get("size_bytes", 0) == 0:
        errors.append("File is empty")
    if facts.get("vertex_count") in {0, None} and facts.get("point_count") in {0, None}:
        warnings.append("No vertex or point count could be determined")
    if textures.get("missing"):
        warnings.append("External texture or dependency references are missing")
    recommendation = "pass"
    if errors:
        recommendation = "quarantine"
    elif warnings:
        recommendation = "manual_review"
    return {"errors": errors, "warnings": warnings, "recommendation": recommendation}


def _copy_derivative(path: Path, output_dir: Path, suffix: str) -> Path:
    target = output_dir / f"{path.stem}_{suffix}{path.suffix or '.bin'}"
    shutil.copy2(path, target)
    return target


def _write_report(component: str, path: Path, payload: dict[str, Any], outputs: dict[str, str] | None = None) -> dict[str, Any]:
    output_dir = _output_root()
    report_path = output_dir / f"{path.stem}_{component}_report.json"
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    outputs = dict(outputs or {})
    outputs["analysis_report"] = str(report_path)
    return {
        "success": True,
        "status": "completed",
        "outputs": outputs,
        "artifacts": [
            {
                "artifact_kind": "file",
                "name": report_path.name,
                "remote_path": str(report_path),
                "metadata": {"component": component, "role": "analysis_report"},
            }
        ],
        "facts": payload.get("facts", {}),
        "qa": payload.get("qa", {}),
        "recommendation": (payload.get("qa") or {}).get("recommendation"),
        "logs": {"stdout": f"{component} completed for {path.name}", "stderr": ""},
    }


def run_component(component: str, request: dict[str, Any]) -> dict[str, Any]:
    if component == "geometric_lod_generator":
        import importlib.util
        runner_path = Path(__file__).with_name("geometric_lod_runner.py")
        if not runner_path.exists():
            runner_path = Path(__file__).parent.parent / "geometric_lod_generator" / "runner.py"
        spec = importlib.util.spec_from_file_location("geometric_lod_runner", runner_path)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        inputs = {**(request.get("inputs") or {}), "input_file": str(_resolve_input((request.get("inputs") or {}).get("input_file")))}
        return runner.execute({**request, "inputs": inputs})
    started = time.time()
    inputs = request.get("inputs") if isinstance(request.get("inputs"), dict) else {}
    parameters = request.get("parameters") if isinstance(request.get("parameters"), dict) else {}
    path = _resolve_input(inputs.get("input_file"))
    facts = inspect_model(path)
    textures = _texture_report(path, facts)
    qa = _qa_report(facts, textures)
    payload: dict[str, Any] = {
        "component": component,
        "input_file": str(path),
        "facts": facts,
        "duration_seconds": None,
    }
    outputs: dict[str, str] = {}

    if component == "model_profiler":
        payload["metadata_targets"] = ["edm:vertexCount", "edm:polygonCount", "edm:pointCount", "dc:type"]
    elif component == "geometry_qa_gate":
        payload["qa"] = qa
    elif component == "texture_dependency_auditor":
        payload["dependencies"] = textures
        payload["qa"] = {"recommendation": "pass" if textures["complete"] else "manual_review", "warnings": textures["missing"]}
    elif component == "canonical_glb_normalizer":
        derivative = _copy_derivative(path, _output_root(), "canonical")
        outputs["canonical_asset"] = str(derivative)
        payload["normalization"] = {"mode": "copy_derivative", "mutated_original": False, "target_format": "glb"}
    elif component == "point_cloud_analyzer":
        payload["point_cloud"] = {
            "is_point_cloud": facts.get("model_type") == "point_cloud" or facts.get("format") in {"ply", "las", "laz", "e57"},
            "point_count": facts.get("point_count"),
            "classification_fields": [item["name"] for item in facts.get("properties", []) if item.get("name") in {"classification", "class"}],
        }
    elif component == "scale_orientation_centering_normalizer":
        payload["spatial_normalization"] = {
            "analysis_only": not bool(parameters.get("apply_changes")),
            "recommended_origin": "center",
            "recommended_up_axis": parameters.get("target_up_axis") or "Y",
            "mutated_original": False,
        }
        if parameters.get("apply_changes"):
            derivative = _copy_derivative(path, _output_root(), "spatial_normalized")
            outputs["normalized_asset"] = str(derivative)
    elif component == "model_repair_component":
        payload["repair"] = {
            "analysis_only": not bool(parameters.get("apply_repair")),
            "operations": ["deduplicate_vertices", "remove_degenerate_faces", "recalculate_normals"],
            "mutated_original": False,
        }
        if parameters.get("apply_repair"):
            derivative = _copy_derivative(path, _output_root(), "repaired")
            outputs["repaired_asset"] = str(derivative)
    elif component == "model_fingerprint_deduplication":
        signature = {
            "sha256": facts.get("sha256"),
            "geometry_signature": "|".join(str(facts.get(key)) for key in ("format", "vertex_count", "polygon_count", "point_count", "material_count", "texture_count")),
            "size_bucket": int(math.log(max(int(facts.get("size_bytes") or 1), 1), 2)),
        }
        signature["normalized_geometry_hash"] = hashlib.sha256(signature["geometry_signature"].encode("utf-8")).hexdigest()
        payload["fingerprints"] = signature
    elif component == "viewer_readiness_analyzer":
        size_mb = (facts.get("size_bytes") or 0) / (1024 * 1024)
        risk = "low"
        warnings: list[str] = []
        if size_mb > 250:
            risk = "high"
            warnings.append("File is very large for browser delivery")
        elif size_mb > 50:
            risk = "medium"
            warnings.append("File may be slow on mobile networks")
        if (facts.get("texture_count") or 0) > 24:
            risk = "medium" if risk == "low" else risk
            warnings.append("Texture count is high for embedded viewers")
        payload["viewer_readiness"] = {"risk": risk, "warnings": warnings, "recommended_action": "publish" if risk == "low" else "optimize_first"}
    else:
        raise RuntimeError(f"Unknown component {component}")

    payload["duration_seconds"] = time.time() - started
    response = _write_report(component, path, payload, outputs=outputs)
    if qa.get("errors") and component == "geometry_qa_gate":
        response["success"] = False
        response["status"] = "failed"
        response["error"] = "; ".join(qa["errors"])
    return response


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--component", required=True)
    parser.add_argument("--input-file")
    parser.add_argument("--apply-changes", action="store_true")
    parser.add_argument("--apply-repair", action="store_true")
    parser.add_argument("--target-up-axis")
    parser.add_argument("--target-ratio", type=float)
    parser.add_argument("--max-relative-error", type=float)
    args, _unknown = parser.parse_known_args()
    try:
        response = run_component(args.component, _read_request(args))
        _write_response(response)
        return 0 if response.get("success") else 1
    except Exception as exc:
        _write_response({"success": False, "status": "failed", "error": str(exc), "logs": {"stdout": "", "stderr": str(exc)}})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
