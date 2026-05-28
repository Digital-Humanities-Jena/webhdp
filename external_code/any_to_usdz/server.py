import json
import logging
import os
import subprocess
import zipfile
from typing import Dict, List, Tuple

from flask import Flask, jsonify, request


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

SUPPORTED_EXTENSIONS = {
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

SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "converter_script.py")
_BLENDER_CAPABILITY_CACHE: Dict[str, object] | None = None


def _is_external_uri(uri: str) -> bool:
    normalized = (uri or "").strip().lower()
    return normalized.startswith("data:") or normalized.startswith("http://") or normalized.startswith("https://")


def _parse_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _preflight_references(input_path: str) -> Dict[str, List[str]]:
    referenced: List[str] = []
    missing: List[str] = []
    extension = os.path.splitext(input_path)[1].lower()
    base_dir = os.path.dirname(input_path)

    def add_reference(candidate: str) -> None:
        if not candidate or _is_external_uri(candidate):
            return
        resolved = os.path.abspath(os.path.join(base_dir, candidate))
        referenced.append(resolved)
        if not os.path.exists(resolved):
            missing.append(resolved)

    try:
        if extension == ".obj":
            with open(input_path, "r", encoding="utf-8", errors="ignore") as handle:
                mtl_files = []
                for raw_line in handle:
                    line = raw_line.strip()
                    if line.lower().startswith("mtllib "):
                        _, mtl_file = line.split(" ", 1)
                        mtl_files.append(mtl_file.strip())

            for mtl_file in mtl_files:
                add_reference(mtl_file)
                mtl_path = os.path.abspath(os.path.join(base_dir, mtl_file))
                if not os.path.exists(mtl_path):
                    continue
                with open(mtl_path, "r", encoding="utf-8", errors="ignore") as mtl_handle:
                    for raw_line in mtl_handle:
                        line = raw_line.strip()
                        if not line:
                            continue
                        lower = line.lower()
                        if lower.startswith(("map_", "bump ", "disp ", "refl ")):
                            parts = line.split()
                            if parts:
                                add_reference(parts[-1])

        if extension == ".gltf":
            with open(input_path, "r", encoding="utf-8", errors="ignore") as handle:
                gltf_json = json.load(handle)
            for image in gltf_json.get("images", []):
                add_reference(image.get("uri", ""))
            for buffer_entry in gltf_json.get("buffers", []):
                add_reference(buffer_entry.get("uri", ""))
    except Exception as exc:
        logger.warning(f"Reference preflight check failed for {input_path}: {exc}")

    return {"referenced_files": sorted(set(referenced)), "missing_files": sorted(set(missing))}


def _validate_usdz_output(output_path: str) -> Dict[str, object]:
    if not os.path.exists(output_path):
        return {"valid": False, "error": "USDZ output file is missing"}

    size = os.path.getsize(output_path)
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


def _check_blender_capabilities() -> Dict[str, object]:
    global _BLENDER_CAPABILITY_CACHE
    if _BLENDER_CAPABILITY_CACHE is not None:
        return _BLENDER_CAPABILITY_CACHE

    probe_script = (
        "import bpy, os, sys, tempfile; "
        "bpy.ops.wm.read_factory_settings(use_empty=True); "
        "bpy.ops.mesh.primitive_cube_add(); "
        "output=os.path.join(tempfile.gettempdir(), 'webhdp_usd_export_probe.usdc'); "
        "bpy.ops.wm.usd_export(filepath=output); "
        "ok=os.path.exists(output) and os.path.getsize(output) > 512; "
        "print('USD_EXPORT_PROBE', 'ok' if ok else 'invalid'); "
        "sys.exit(0 if ok else 1)"
    )
    try:
        result = subprocess.run(
            ["blender", "--background", "--python-expr", probe_script],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        _BLENDER_CAPABILITY_CACHE = {
            "ok": False,
            "error_code": "BLENDER_CAPABILITY_TIMEOUT",
            "diagnostic_hint": "Blender did not finish the USD export probe within 30 seconds.",
        }
        return _BLENDER_CAPABILITY_CACHE
    except Exception as exc:
        _BLENDER_CAPABILITY_CACHE = {
            "ok": False,
            "error_code": "BLENDER_CAPABILITY_CHECK_FAILED",
            "diagnostic_hint": str(exc),
        }
        return _BLENDER_CAPABILITY_CACHE

    if result.returncode != 0:
        _BLENDER_CAPABILITY_CACHE = {
            "ok": False,
            "error_code": "BLENDER_USD_EXPORT_UNAVAILABLE",
            "diagnostic_hint": "Blender is installed, but its USD export operator is not usable.",
            "stderr": result.stderr,
            "stdout": result.stdout,
        }
        return _BLENDER_CAPABILITY_CACHE

    _BLENDER_CAPABILITY_CACHE = {
        "ok": True,
        "usd_export": True,
        "stdout": result.stdout,
    }
    return _BLENDER_CAPABILITY_CACHE


def _classify_failure(stderr: str, stdout: str) -> Tuple[str, str]:
    combined = f"{stderr}\n{stdout}".lower()

    if "usd_export" in combined and "could not be found" in combined:
        return "BLENDER_USD_EXPORT_UNAVAILABLE", "Blender is installed, but its USD export operator is not usable. Rebuild the converter image with the supported AMD64 Blender runtime."
    if "no module named 'numpy'" in combined:
        return "BLENDER_NUMPY_MISSING", "Blender Python runtime is missing NumPy. Rebuild the converter image."
    if "unsupported file extension" in combined:
        return "UNSUPPORTED_INPUT_FORMAT", "The input format is not supported by the converter."
    if "no scene objects were imported" in combined:
        return "IMPORT_EMPTY_SCENE", "Importer loaded no scene objects. Check model integrity and sidecar references."
    if "input path does not exist" in combined:
        return "INPUT_FILE_MISSING", "Input path is not visible inside the converter container."
    return "BLENDER_CONVERSION_FAILED", "Blender failed to convert the model. Check stderr for details."


def _extract_timings(stdout: str) -> Dict[str, float]:
    timings: Dict[str, float] = {}
    for raw_line in (stdout or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("TIMING:"):
            continue
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        _, stage_name, value = parts
        try:
            timings[stage_name] = float(value.strip())
        except (TypeError, ValueError):
            continue
    return timings


@app.route("/health", methods=["GET"])
def health():
    capabilities = _check_blender_capabilities()
    if not capabilities.get("ok"):
        return jsonify(
            {
                "status": "degraded",
                "service": "any-to-usdz",
                "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
                "capabilities": capabilities,
            }
        ), 503

    return jsonify(
        {
            "status": "ok",
            "service": "any-to-usdz",
            "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
            "capabilities": {"usd_export": True},
        }
    ), 200


@app.route("/convert", methods=["POST"])
def convert():
    data = request.get_json(silent=True) or {}
    input_path = data.get("input_path")
    output_dir = data.get("output_dir")

    if not input_path or not output_dir:
        return jsonify({"success": False, "error": "input_path and output_dir are required"}), 400

    input_path = os.path.abspath(input_path)
    output_dir = os.path.abspath(output_dir)
    extension = os.path.splitext(input_path)[1].lower()

    if extension not in SUPPORTED_EXTENSIONS:
        return jsonify(
            {
                "success": False,
                "error": f"Unsupported input extension: {extension}",
                "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
            }
        ), 400
    if not os.path.isfile(input_path):
        return jsonify({"success": False, "error": f"Input file not found: {input_path}"}), 404

    preflight = _preflight_references(input_path)
    if preflight["missing_files"]:
        logger.warning(
            "Input references missing sidecar resources: %s",
            ", ".join(preflight["missing_files"][:8]),
        )

    filename = os.path.basename(input_path)
    stem = os.path.splitext(filename)[0]
    output_path = os.path.join(output_dir, stem, f"{stem}.usdz")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    try:
        scale = float(data.get("scale", 1.0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "scale must be a number"}), 400
    apply_modifiers = _parse_bool(data.get("apply_modifiers"), True)

    cmd = [
        "blender",
        "--background",
        "--python",
        SCRIPT_PATH,
        "--",
        "--input",
        input_path,
        "--output",
        output_path,
        "--scale",
        str(scale),
    ]
    if apply_modifiers:
        cmd.append("--apply-modifiers")

    tmp_dir = os.path.join(os.path.dirname(output_path), ".tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    env = os.environ.copy()
    for key in ("TMPDIR", "TEMP", "TMP"):
        env[key] = tmp_dir
    xdg_runtime_dir = os.path.join(tmp_dir, "xdg-runtime")
    os.makedirs(xdg_runtime_dir, exist_ok=True)
    env.setdefault("XDG_RUNTIME_DIR", xdg_runtime_dir)

    logger.info("Starting conversion: %s -> %s", input_path, output_path)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=900,
            env=env,
        )
    except subprocess.TimeoutExpired:
        logger.error("Conversion timeout for %s", input_path)
        return jsonify(
            {
                "success": False,
                "error": "Blender conversion timed out",
                "error_code": "BLENDER_TIMEOUT",
                "details": {"timeout_seconds": 900},
            }
        ), 504
    except Exception as exc:
        logger.error("Conversion execution error: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500

    if result.returncode != 0:
        error_code, hint = _classify_failure(result.stderr, result.stdout)
        timings = _extract_timings(result.stdout)
        logger.error("Blender conversion failed (%s): %s", error_code, result.stderr.strip()[:1000])
        return jsonify(
            {
                "success": False,
                "error": "Blender conversion failed",
                "error_code": error_code,
                "timings": timings,
                "details": {
                    "diagnostic_hint": hint,
                    "return_code": result.returncode,
                    "stderr": result.stderr,
                    "stdout": result.stdout,
                    "preflight": preflight,
                },
            }
        ), 500

    output_validation = _validate_usdz_output(output_path)
    stderr_has_export_error = "Runtime Error:" in result.stderr or "Traceback (most recent call last):" in result.stderr
    if not output_validation.get("valid") or stderr_has_export_error:
        error_code = "USDZ_OUTPUT_INVALID"
        hint = "Blender finished, but the USDZ archive failed validation."
        if stderr_has_export_error:
            hint = "Blender reported a USD export runtime error while writing the USDZ archive."
        logger.error("Blender produced an invalid USDZ (%s): %s", error_code, output_validation)
        return jsonify(
            {
                "success": False,
                "error": "Invalid USDZ output",
                "error_code": error_code,
                "details": {
                    "diagnostic_hint": hint,
                    "return_code": result.returncode,
                    "stderr": result.stderr,
                    "stdout": result.stdout,
                    "preflight": preflight,
                    "output_validation": output_validation,
                },
            }
        ), 500

    logger.info("Conversion successful: %s", output_path)
    warnings = []
    if preflight["missing_files"]:
        warnings.append("Some referenced sidecar files were missing; output may have incomplete materials/textures.")

    timings = _extract_timings(result.stdout)

    return jsonify(
        {
            "success": True,
            "output_path": output_path,
            "logs": result.stdout,
            "timings": timings,
            "warnings": warnings,
            "preflight": preflight,
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5003))
    app.run(host="0.0.0.0", port=port)
