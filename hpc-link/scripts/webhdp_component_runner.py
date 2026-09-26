#!/usr/bin/env python3
"""Run WebHDP HDP components inside an HPC-Link allocation.

The runner is intentionally file based. HPC-Link stages a request JSON path in
WEBHDP_COMPONENT_REQUEST and expects a response JSON at WEBHDP_COMPONENT_RESPONSE.
Input files are resolved inside WEBHDP_INPUT_DIR, and component outputs are
written below WEBHDP_OUTPUT_DIR so WebHDP can keep only remote artifact refs.
"""

from __future__ import annotations

import argparse
import json
import hashlib
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any


SUPPORTED_RENDER_FORMATS = {
    ".obj",
    ".glb",
    ".gltf",
    ".usdz",
    ".ply",
    ".fbx",
    ".dae",
    ".stl",
    ".usd",
    ".usda",
    ".usdc",
    ".abc",
}

SUPPORTED_USDZ_FORMATS = {
    ".glb",
    ".gltf",
    ".obj",
    ".fbx",
    ".ply",
    ".stl",
    ".abc",
    ".dae",
    ".x3d",
    ".wrl",
    ".usd",
    ".usda",
    ".usdc",
}

QUALITY_PRESETS = {
    "draft": {"resolution": 256, "samples": 8},
    "medium": {"resolution": 512, "samples": 32},
    "high": {"resolution": 1024, "samples": 128},
    "ultra": {"resolution": 2048, "samples": 256},
}


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _runtime_root() -> Path:
    configured = os.environ.get("WEBHDP_COMPONENT_RUNTIME_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parent


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
    if not response_path:
        print(json.dumps(payload, sort_keys=True))
        return
    Path(response_path).parent.mkdir(parents=True, exist_ok=True)
    with open(response_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True)
    print(json.dumps(payload, sort_keys=True))


def _component_output_dir(component_key: str, request: dict[str, Any]) -> Path:
    remote_output_dir = Path(
        request.get("remote_output_dir")
        or os.environ.get("WEBHDP_OUTPUT_DIR")
        or "."
    ).resolve()
    step_id = str(request.get("step_id") or component_key).strip() or component_key
    safe_step = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in step_id)
    target = remote_output_dir / safe_step
    target.mkdir(parents=True, exist_ok=True)
    return target


def _find_by_name(root: Path, name: str) -> Path | None:
    if not root.exists():
        return None
    for candidate in root.rglob(name):
        if candidate.is_file():
            return candidate.resolve()
    return None


def _resolve_input_path(value: Any, remote_input_dir: Path) -> Path:
    text = str(value or "").strip()
    if not text:
        raise RuntimeError("Empty input path")
    candidate = Path(text)
    if candidate.is_absolute() and candidate.exists():
        return candidate.resolve()
    if not candidate.is_absolute():
        relative_candidate = (remote_input_dir / candidate).resolve()
        if relative_candidate.exists():
            return relative_candidate
    by_name = _find_by_name(remote_input_dir, candidate.name)
    if by_name is not None:
        return by_name
    raise FileNotFoundError(f"Could not resolve staged input file for {text!r} under {remote_input_dir}")


def _common_input_root(paths: list[Path], remote_input_dir: Path) -> Path:
    if not paths:
        return remote_input_dir
    try:
        common = Path(os.path.commonpath([str(path.parent) for path in paths]))
    except ValueError:
        return remote_input_dir
    try:
        common.relative_to(remote_input_dir)
        return common
    except ValueError:
        return remote_input_dir


def _resolve_staged_input(value: str, request: dict[str, Any], remote_input_dir: Path) -> Path:
    for item in request.get("staged_files") or []:
        if item.get("local_path") == value and item.get("remote_path"):
            resolved = Path(item["remote_path"]).resolve()
            if not resolved.is_relative_to(remote_input_dir.resolve()) or not resolved.is_file():
                raise ValueError("Staged input must exist inside the allocation input directory")
            return resolved
    return _resolve_input_path(value, remote_input_dir)


def _collect_render_inputs(request: dict[str, Any], remote_input_dir: Path) -> tuple[list[str], list[Path]]:
    inputs = request.get("inputs") if isinstance(request.get("inputs"), dict) else {}
    batch_records = request.get("batch_records") if isinstance(request.get("batch_records"), list) else []
    original_values: list[str] = []
    for item in _listify(inputs.get("input_files") or inputs.get("input-files")):
        if str(item or "").strip():
            original_values.append(str(item).strip())
    for record in batch_records:
        if isinstance(record, dict) and str(record.get("file_path") or "").strip():
            value = str(record["file_path"]).strip()
            if value not in original_values:
                original_values.append(value)
    if not original_values and str(inputs.get("input-dir") or inputs.get("input_dir") or "").strip():
        input_dir = _resolve_input_path(inputs.get("input-dir") or inputs.get("input_dir"), remote_input_dir)
        originals = []
        remotes = []
        for path in input_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in SUPPORTED_RENDER_FORMATS:
                originals.append(str(path))
                remotes.append(path.resolve())
        return originals, remotes
    remote_paths = [_resolve_staged_input(value, request, remote_input_dir) for value in original_values]
    return original_values, remote_paths


def _render_component(request: dict[str, Any]) -> dict[str, Any]:
    runtime_root = _runtime_root()
    fast_renderer_dir = runtime_root / "external_code" / "fast_renderer"
    sys.path.insert(0, str(fast_renderer_dir))
    from processor import OptimizedRendererProcessor  # type: ignore

    remote_input_dir = Path(
        request.get("remote_input_dir")
        or os.environ.get("WEBHDP_INPUT_DIR")
        or "."
    ).resolve()
    output_dir = _component_output_dir("fast_renderer", request)
    parameters = request.get("parameters") if isinstance(request.get("parameters"), dict) else {}
    originals, remote_paths = _collect_render_inputs(request, remote_input_dir)
    if not remote_paths:
        return {"success": False, "status": "failed", "error": "No staged render inputs resolved", "record_results": {}}

    preset = str(parameters.get("preset") or "medium")
    quality = dict(QUALITY_PRESETS.get(preset, QUALITY_PRESETS["medium"]))
    if parameters.get("resolution") not in (None, ""):
        quality["resolution"] = int(parameters["resolution"])
    if parameters.get("samples") not in (None, ""):
        quality["samples"] = int(parameters["samples"])

    renderer = OptimizedRendererProcessor(
        resolution=quality["resolution"],
        samples=quality["samples"],
        camera_dist=float(parameters.get("camera-dist") or parameters.get("camera_dist") or 1.8),
        engine=str(parameters.get("engine") or "CYCLES"),
        transparent_background=_as_bool(parameters.get("transparent-background"), True),
        batch_size=int(parameters.get("batch-size") or parameters.get("batch_size") or 50),
        num_images=int(parameters.get("angle-iteration") or parameters.get("angle_iteration") or 5),
        timeout_multiplier=float(parameters.get("timeout-multiplier") or parameters.get("timeout_multiplier") or 1.0),
        strict_gpu=_as_bool(parameters.get("strict_gpu") or parameters.get("require_gpu"), False),
    )
    if parameters.get("light-energy") not in (None, ""):
        renderer.light_energy = float(parameters["light-energy"])
    if parameters.get("light-angle") not in (None, ""):
        renderer.light_angle = float(parameters["light-angle"])
    angles = parameters.get("angles")
    if isinstance(angles, list) and angles:
        renderer.custom_angles = angles
        renderer.num_images = len(angles)

    input_root = _common_input_root(remote_paths, remote_input_dir)
    started = time.time()
    render_result = renderer.process_batch([str(path) for path in remote_paths], str(output_dir), str(input_root))
    duration = time.time() - started
    raw_results = render_result.get("results", {}) if isinstance(render_result, dict) else {}
    record_results: dict[str, Any] = {}
    artifacts: list[dict[str, Any]] = []

    for original, remote_path in zip(originals, remote_paths):
        raw = raw_results.get(str(remote_path.resolve()), raw_results.get(str(remote_path), {}))
        remote_output_subdir = output_dir / remote_path.relative_to(input_root)
        render_outputs = sorted(str(path.resolve()) for path in remote_output_subdir.rglob("*") if path.is_file())
        thumbnail_files = [path for path in render_outputs if Path(path).suffix.lower() == ".png"]
        success = bool(raw.get("success")) and bool(render_outputs)
        result_payload = {
            "success": success,
            "status": "completed" if success else "failed",
            "error": None if success else raw.get("error") or "Fast Renderer did not produce output files.",
            "duration": raw.get("duration") or duration,
            "outputs": {
                "render_outputs": render_outputs,
                "thumbnail_files": thumbnail_files,
            },
            "render_status": {
                **(raw if isinstance(raw, dict) else {}),
                "success": success,
                "status": "completed" if success else "failed",
            },
            "artifacts": [
                {
                    "artifact_kind": "file",
                    "name": Path(path).name,
                    "remote_path": path,
                    "metadata": {"step": "fast_renderer"},
                }
                for path in render_outputs
            ],
        }
        record_results[original] = result_payload
        artifacts.extend(result_payload["artifacts"])

    success = bool(record_results) and all(item.get("success") for item in record_results.values())
    return {
        "success": success,
        "status": "completed" if success else "failed",
        "record_results": record_results,
        "results": raw_results,
        "outputs": {"output-dir": str(output_dir)},
        "artifacts": artifacts,
        "logs": {"stdout": "\n".join(render_result.get("logs", []) if isinstance(render_result, dict) else []), "stderr": ""},
        "command": ["hpc_link", "fast_renderer"],
    }


def _run_usdz_conversion(input_path: Path, output_path: Path, parameters: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    runtime_root = _runtime_root()
    script_path = runtime_root / "external_code" / "any_to_usdz" / "converter_script.py"
    blender = os.environ.get("BLENDER_BIN") or shutil.which("blender")
    if not blender:
        raise RuntimeError("Blender executable not found in PATH; set BLENDER_BIN")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = output_path.parent / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for key in ("TMPDIR", "TEMP", "TMP"):
        env[key] = str(tmp_dir)
    xdg_runtime_dir = tmp_dir / "xdg-runtime"
    xdg_runtime_dir.mkdir(parents=True, exist_ok=True)
    env.setdefault("XDG_RUNTIME_DIR", str(xdg_runtime_dir))
    cmd = [
        blender,
        "--background",
        "--python",
        str(script_path),
        "--",
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--scale",
        str(parameters.get("scale") or 1.0),
    ]
    if _as_bool(parameters.get("apply_modifiers"), True):
        cmd.append("--apply-modifiers")
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=int(parameters.get("timeout_seconds") or 900),
        env=env,
    )
    validation = _validate_usdz_output(output_path)
    stderr_has_export_error = "Runtime Error:" in proc.stderr or "Traceback (most recent call last):" in proc.stderr
    success = proc.returncode == 0 and validation["valid"] and not stderr_has_export_error
    return success, {
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
        "output_validation": validation,
    }


def _validate_usdz_output(output_path: Path) -> dict[str, Any]:
    if not output_path.exists():
        return {"valid": False, "error": "USDZ output file is missing"}
    size = output_path.stat().st_size
    if size < 1024:
        return {"valid": False, "error": f"USDZ output is too small to contain a converted model ({size} bytes)", "size": size}
    try:
        with zipfile.ZipFile(output_path) as archive:
            broken_member = archive.testzip()
            if broken_member:
                return {"valid": False, "error": f"USDZ archive member failed CRC validation: {broken_member}", "size": size}
            members = archive.infolist()
    except zipfile.BadZipFile:
        return {"valid": False, "error": "USDZ output is not a valid ZIP archive", "size": size}
    usd_members = [
        item for item in members
        if item.filename.lower().endswith((".usd", ".usda", ".usdc"))
    ]
    if not usd_members:
        return {"valid": False, "error": "USDZ archive does not contain a USD stage", "size": size}
    if not any(item.file_size > 512 for item in usd_members):
        return {"valid": False, "error": "USDZ archive contains only empty or placeholder USD stages", "size": size}
    return {
        "valid": True,
        "size": size,
        "members": [{"name": item.filename, "size": item.file_size} for item in members],
    }


def _usdz_component(request: dict[str, Any]) -> dict[str, Any]:
    remote_input_dir = Path(
        request.get("remote_input_dir")
        or os.environ.get("WEBHDP_INPUT_DIR")
        or "."
    ).resolve()
    parameters = request.get("parameters") if isinstance(request.get("parameters"), dict) else {}
    inputs = request.get("inputs") if isinstance(request.get("inputs"), dict) else {}
    record_context = request.get("record_context") if isinstance(request.get("record_context"), dict) else {}
    original = str(inputs.get("input_file") or record_context.get("file_path") or "").strip()
    if not original:
        return {"success": False, "status": "failed", "error": "USDZ Converter requires an input file.", "outputs": {}}
    input_path = _resolve_staged_input(original, request, remote_input_dir)
    output_dir = _component_output_dir("any_to_usdz", request) / input_path.stem
    output_path = output_dir / f"{input_path.stem}.usdz"
    started = time.time()
    success, details = _run_usdz_conversion(input_path, output_path, parameters)
    payload = {
        "success": success,
        "status": "completed" if success else "failed",
        "outputs": {"output_path": str(output_path)} if success else {},
        "details": details,
        "duration": time.time() - started,
        "command": ["hpc_link", "any_to_usdz"],
    }
    if success:
        payload["artifacts"] = [
            {
                "artifact_kind": "file",
                "name": output_path.name,
                "remote_path": str(output_path),
                "metadata": {"step": "any_to_usdz"},
            }
        ]
    else:
        payload["error"] = details.get("stderr_tail") or details.get("stdout_tail") or "USDZ conversion failed"
    return payload


def _generic_singularity_component(component_key: str, request: dict[str, Any]) -> dict[str, Any]:
    profile = request.get("profile") if isinstance(request.get("profile"), dict) else {}
    image = str(profile.get("image") or profile.get("sif_remote_path") or "").strip()
    expected_checksum = profile.get("sif_sha256")
    if expected_checksum:
        with open(image, "rb") as source:
            actual_checksum = hashlib.file_digest(source, "sha256").hexdigest()
        if actual_checksum != expected_checksum:
            raise ValueError("SIF checksum changed; refusing to run an unverified artifact")
    if not image:
        raise RuntimeError(f"Component {component_key!r} does not declare a Singularity image")
    entrypoint = profile.get("entrypoint")
    if not isinstance(entrypoint, list) or not all(str(item).strip() for item in entrypoint):
        raise RuntimeError(f"Component {component_key!r} requires a non-empty Singularity entrypoint")

    remote_input_dir = Path(
        request.get("remote_input_dir")
        or os.environ.get("WEBHDP_INPUT_DIR")
        or "."
    ).resolve()
    remote_output_dir = Path(
        request.get("remote_output_dir")
        or os.environ.get("WEBHDP_OUTPUT_DIR")
        or "."
    ).resolve()
    request_env = os.environ.get("WEBHDP_COMPONENT_REQUEST")
    response_env = os.environ.get("WEBHDP_COMPONENT_RESPONSE")
    if not request_env:
        raise RuntimeError("WEBHDP_COMPONENT_REQUEST is required for Singularity components")
    if not response_env:
        raise RuntimeError("WEBHDP_COMPONENT_RESPONSE is required for Singularity components")
    request_path = Path(request_env).resolve()
    response_path = Path(response_env).resolve()

    remote_input_dir.mkdir(parents=True, exist_ok=True)
    remote_output_dir.mkdir(parents=True, exist_ok=True)
    singularity = os.environ.get("SINGULARITY_BIN") or shutil.which("singularity") or shutil.which("apptainer")
    if not singularity:
        raise RuntimeError("Singularity/Apptainer executable not found")

    session_root = request_path.parent
    binds = [
        f"{session_root}:{session_root}",
        f"{remote_input_dir}:/inputs",
        f"{remote_output_dir}:/outputs",
    ]
    cmd = [singularity, "exec", "--cleanenv", "--containall", "--no-home", "--pwd", "/outputs"]
    for bind in binds:
        cmd.extend(["--bind", bind])
    cmd.append(image)
    cmd.extend([str(item) for item in entrypoint])
    env = os.environ.copy()
    env.update(
        {
            "SINGULARITYENV_WEBHDP_COMPONENT_REQUEST": str(request_path),
            "SINGULARITYENV_WEBHDP_COMPONENT_RESPONSE": str(response_path),
            "SINGULARITYENV_WEBHDP_INPUT_DIR": "/inputs",
            "SINGULARITYENV_WEBHDP_OUTPUT_DIR": "/outputs",
            "SINGULARITYENV_WEBHDP_COMPONENT_KEY": component_key,
            "APPTAINERENV_WEBHDP_COMPONENT_REQUEST": str(request_path),
            "APPTAINERENV_WEBHDP_COMPONENT_RESPONSE": str(response_path),
            "APPTAINERENV_WEBHDP_INPUT_DIR": "/inputs",
            "APPTAINERENV_WEBHDP_OUTPUT_DIR": "/outputs",
            "APPTAINERENV_WEBHDP_COMPONENT_KEY": component_key,
        }
    )
    started = time.time()
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=int(request.get("timeout_seconds") or 7200),
        env=env,
    )
    parsed = None
    if response_path.exists() and response_path.stat().st_size > 0:
        try:
            with open(response_path, "r", encoding="utf-8") as handle:
                parsed = json.load(handle)
        except json.JSONDecodeError:
            parsed = None
    if parsed is None and proc.stdout.strip().startswith("{") and proc.stdout.strip().endswith("}"):
        try:
            parsed = json.loads(proc.stdout.strip())
        except json.JSONDecodeError:
            parsed = None
    result = parsed if isinstance(parsed, dict) else {}
    result = _rewrite_container_paths(result, remote_input_dir=remote_input_dir, remote_output_dir=remote_output_dir)
    result.setdefault("success", proc.returncode == 0)
    result.setdefault("status", "completed" if result.get("success") else "failed")
    result.setdefault("duration", time.time() - started)
    result.setdefault("command", ["singularity", "exec", image, *[str(item) for item in entrypoint]])
    result.setdefault("logs", {"stdout": proc.stdout, "stderr": proc.stderr})
    if proc.returncode != 0:
        result["success"] = False
        result["status"] = "failed"
        result.setdefault("error", proc.stderr[-2000:] or proc.stdout[-2000:] or "Singularity component failed")
    return result


def _rewrite_container_paths(value: Any, *, remote_input_dir: Path, remote_output_dir: Path) -> Any:
    if isinstance(value, dict):
        return {
            key: _rewrite_container_paths(item, remote_input_dir=remote_input_dir, remote_output_dir=remote_output_dir)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _rewrite_container_paths(item, remote_input_dir=remote_input_dir, remote_output_dir=remote_output_dir)
            for item in value
        ]
    if isinstance(value, str):
        if value == "/outputs":
            return str(remote_output_dir)
        if value.startswith("/outputs/"):
            return str(remote_output_dir / value[len("/outputs/"):])
        if value == "/inputs":
            return str(remote_input_dir)
        if value.startswith("/inputs/"):
            return str(remote_input_dir / value[len("/inputs/"):])
    return value


def _preflight() -> dict[str, Any]:
    blender = os.environ.get("BLENDER_BIN") or shutil.which("blender")
    checks = {"blender": {"success": False, "path": blender}}
    if blender:
        proc = subprocess.run([blender, "--version"], capture_output=True, text=True, timeout=20, check=False)
        checks["blender"].update(
            {
                "success": proc.returncode == 0,
                "stdout_tail": proc.stdout[:1000],
                "stderr_tail": proc.stderr[:1000],
            }
        )
    nvidia = shutil.which("nvidia-smi")
    if nvidia:
        proc = subprocess.run([nvidia], capture_output=True, text=True, timeout=20, check=False)
        gpu_required = _as_bool(os.environ.get("WEBHDP_EXPECT_GPU"), default=False)
        checks["nvidia_smi"] = {
            "success": proc.returncode == 0 or not gpu_required,
            "required": gpu_required,
            "stdout_tail": proc.stdout[:1200],
            "stderr_tail": proc.stderr[:1200],
        }
    return {"success": all(item.get("success") for item in checks.values()), "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    try:
        if args.preflight:
            payload = _preflight()
        else:
            request = _read_request()
            component_key = str(request.get("component_key") or os.environ.get("WEBHDP_COMPONENT_KEY") or "").strip()
            if component_key == "fast_renderer":
                payload = _render_component(request)
            elif component_key == "any_to_usdz":
                payload = _usdz_component(request)
            else:
                payload = _generic_singularity_component(component_key, request)
    except BaseException as exc:
        payload = {"success": False, "status": "failed", "error": str(exc), "command": ["hpc_link", "webhdp_component_runner"]}
    _write_response(payload)
    return 0 if payload.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
