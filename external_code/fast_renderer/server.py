from flask import Flask, request, jsonify
import os
import logging
import sys
import subprocess
from glob import glob
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List
from processor import OptimizedRendererProcessor, QUALITY_PRESETS
from main import scan_models, check_textures

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
SUPPORTED_ENGINES = {"BLENDER_EEVEE", "BLENDER_WORKBENCH", "CYCLES"}
ENGINE_ALIASES = {
    "BLENDER_EEVEE_NEXT": "BLENDER_EEVEE",
}


def _resolve_input_directory(input_path: str | None, input_files: List[str] | None) -> str:
    normalized_files = [str(path).strip() for path in (input_files or []) if str(path or "").strip()]
    if normalized_files:
        parent_dirs = []
        for path in normalized_files:
            if os.path.isdir(path):
                parent_dirs.append(path)
            else:
                parent_dirs.append(os.path.dirname(path) or os.path.dirname(os.path.abspath(path)))
        try:
            return os.path.commonpath(parent_dirs)
        except ValueError:
            return parent_dirs[0] if parent_dirs else ""

    candidate = str(input_path or "").strip()
    if not candidate:
        return ""
    if os.path.isdir(candidate):
        return candidate
    return os.path.dirname(candidate) or os.path.dirname(os.path.abspath(candidate))


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _detect_visible_gpu_count() -> int:
    slurm_gpus_on_node = os.environ.get("SLURM_GPUS_ON_NODE", "").strip()
    if slurm_gpus_on_node.isdigit():
        return int(slurm_gpus_on_node)

    slurm_step_gpus = os.environ.get("SLURM_STEP_GPUS", "").strip()
    if slurm_step_gpus:
        parts = [p.strip() for p in slurm_step_gpus.split(",") if p.strip()]
        if parts:
            return len(parts)

    slurm_job_gpus = os.environ.get("SLURM_JOB_GPUS", "").strip()
    if slurm_job_gpus:
        parts = [p.strip() for p in slurm_job_gpus.split(",") if p.strip()]
        if parts:
            return len(parts)

    # Honor explicit GPU masking first.
    masked = os.environ.get("CUDA_VISIBLE_DEVICES", "").strip()
    if masked and masked not in {"NoDevFiles", "-1"}:
        if masked.lower() == "all":
            # Continue to filesystem probes to infer count.
            masked = ""
        else:
            parts = [p.strip() for p in masked.split(",") if p.strip()]
            if parts:
                return len(parts)

    nvidia_visible = os.environ.get("NVIDIA_VISIBLE_DEVICES", "").strip()
    if nvidia_visible and nvidia_visible.lower() not in {"void", "none"}:
        if nvidia_visible.lower() == "all":
            # Continue to filesystem probes to infer count.
            nvidia_visible = ""
        else:
            parts = [p.strip() for p in nvidia_visible.split(",") if p.strip()]
            if parts:
                return len(parts)

    # Works in --nv Singularity runtime even without nvidia-smi binary in container.
    proc_gpu_paths = glob("/proc/driver/nvidia/gpus/*")
    if proc_gpu_paths:
        return len(proc_gpu_paths)

    dev_gpu_nodes = [p for p in glob("/dev/nvidia[0-9]*") if os.path.basename(p)[6:].isdigit()]
    if dev_gpu_nodes:
        return len(dev_gpu_nodes)

    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=index", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout:
            return len([line for line in proc.stdout.splitlines() if line.strip()])
    except Exception:
        pass
    return 0


def _render_subset_worker(
    subset_files: List[str],
    output_dir: str,
    input_dir: str,
    renderer_kwargs: Dict[str, Any],
    dynamic_params: Dict[str, Any],
    gpu_slot: int,
) -> Dict[str, Any]:
    previous_visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_slot)
    try:
        renderer = OptimizedRendererProcessor(**renderer_kwargs)
        if "light_energy" in dynamic_params:
            renderer.light_energy = dynamic_params["light_energy"]
        if "light_angle" in dynamic_params:
            renderer.light_angle = dynamic_params["light_angle"]
        if "custom_angles" in dynamic_params:
            renderer.custom_angles = dynamic_params["custom_angles"] or []
            renderer.num_images = len(renderer.custom_angles) if renderer.custom_angles else renderer.num_images
        return renderer.process_batch(subset_files, output_dir, input_dir)
    finally:
        if previous_visible is None:
            os.environ.pop("CUDA_VISIBLE_DEVICES", None)
        else:
            os.environ["CUDA_VISIBLE_DEVICES"] = previous_visible


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "service": "fast_renderer"}), 200

@app.route('/render', methods=['POST'])
def render():
    # Use app.logger.error to ensure it appears in the Flask log with correct levels
    app.logger.error(f"DEBUG_RENDER_START: Headers: {dict(request.headers)}")
    try:
        data = request.get_json(silent=True, force=True)
    except Exception as e:
        app.logger.error(f"DEBUG_JSON_PARSE_ERROR: {e}")
        return jsonify({"error": f"JSON Parse Error: {e}"}), 400

    if not data:
        app.logger.error("DEBUG_NO_DATA")
        return jsonify({"error": "No data provided"}), 400

    app.logger.error(f"DEBUG_PAYLOAD_KEYS: {list(data.keys())}")

    input_path = data.get("input_path")
    output_dir = data.get("output_dir")
    input_files = data.get("input_files")

    if (not input_path and not input_files) or not output_dir:
        app.logger.error(f"DEBUG_MISSING_PARAMS: input_path={bool(input_path)}, input_files={bool(input_files)}, output_dir={bool(output_dir)}")
        return jsonify({"error": "Either input_path or input_files, and output_dir are required"}), 400

    # Optional parameters with defaults
    preset_name = data.get("preset", "medium")
    quality = QUALITY_PRESETS.get(preset_name, QUALITY_PRESETS["medium"]).copy()

    # Overrides
    if "resolution" in data: quality["resolution"] = data["resolution"]
    if "samples" in data: quality["samples"] = data["samples"]
    if "camera_dist" in data: quality["camera_dist"] = data["camera_dist"]

    require_gpu_default = _as_bool(
        os.environ.get("FAST_RENDERER_REQUIRE_GPU", os.environ.get("REQUIRE_GPU", "false")),
        default=False,
    )
    force_cycles_default = _as_bool(
        os.environ.get("FAST_RENDERER_FORCE_CYCLES", "true" if require_gpu_default else "false"),
        default=require_gpu_default,
    )
    require_gpu = _as_bool(data.get("require_gpu", require_gpu_default), default=require_gpu_default)
    strict_gpu = _as_bool(data.get("strict_gpu", require_gpu), default=require_gpu)

    engine_raw = data.get("engine", "CYCLES")
    engine = str(engine_raw).strip().upper() if engine_raw is not None else "CYCLES"
    engine = ENGINE_ALIASES.get(engine, engine)
    warnings = []
    if engine not in SUPPORTED_ENGINES:
        warnings.append(
            f"Unsupported render engine '{engine_raw}' requested. Falling back to CYCLES."
        )
        engine = "CYCLES"
    elif force_cycles_default and engine == "BLENDER_EEVEE":
        warnings.append(
            "BLENDER_EEVEE requested while FAST_RENDERER_FORCE_CYCLES is active; coercing engine to CYCLES."
        )
        engine = "CYCLES"
    formats = data.get("formats", [".obj", ".glb", ".gltf"])

    try:
        # File Scan Logic (Reuse from main.py logic)
        files = []
        real_input_dir = _resolve_input_directory(input_path, input_files)

        if input_files:
            files = input_files
            logger.info(f"Processing batch of {len(files)} explicitly provided files.")
        elif os.path.isfile(input_path):
            files = [input_path]
            real_input_dir = os.path.dirname(input_path)
            logger.info(f"Processing single file: {input_path}")
        else:
            if not os.path.exists(input_path):
                 return jsonify({"error": f"Input path does not exist: {input_path}"}), 404
            files = scan_models(input_path, formats)
            logger.info(f"Scanned directory {input_path}, found {len(files)} files")

        if not files:
            logger.error(f"No valid files found to render. formats={formats}, input_path={input_path}, input_files={bool(input_files)}")
            return jsonify({"error": "No valid files found to render"}), 400

        renderer_kwargs = {
            "resolution": quality["resolution"],
            "samples": quality["samples"],
            "camera_dist": quality["camera_dist"],
            "engine": engine,
            "transparent_background": data.get("transparent_background", True),
            "batch_size": data.get("batch_size", 50),
            "num_images": data.get("angle_iteration", 5),
            "timeout_multiplier": data.get("timeout_multiplier", 1.0),
            "strict_gpu": strict_gpu,
        }
        renderer = OptimizedRendererProcessor(**renderer_kwargs)

        # Set dynamic properties
        if "light_energy" in data:
            renderer.light_energy = data["light_energy"]
        if "light_angle" in data:
            renderer.light_angle = data["light_angle"]

        # Apply custom angles if provided
        if "custom_angles" in data:
            renderer.custom_angles = data["custom_angles"]
            renderer.num_images = len(data["custom_angles"])

        dynamic_params = {
            "light_energy": getattr(renderer, "light_energy", 4.0),
            "light_angle": getattr(renderer, "light_angle", 45.0),
            "custom_angles": getattr(renderer, "custom_angles", []),
        }

        visible_gpus = _detect_visible_gpu_count()
        if require_gpu and visible_gpus <= 0:
            error_message = (
                "GPU is required for this render request, but no visible GPUs were detected "
                "(check GPU allocation and Singularity --nv runtime)."
            )
            logger.error(error_message)
            return jsonify({"success": False, "error": error_message, "warnings": warnings}), 503
        parallel_mode = _as_bool(data.get("parallel_mode", True), default=True)
        max_workers_env = int(str(os.environ.get("FAST_RENDERER_MAX_WORKERS", "0")) or "0")
        requested_workers_raw = data.get("parallel_workers", 0)
        try:
            requested_workers = int(requested_workers_raw)
        except (TypeError, ValueError):
            requested_workers = 0

        auto_workers = 1
        if visible_gpus > 0:
            auto_workers = min(visible_gpus, len(files))
        else:
            cpu_worker_cap = int(str(os.environ.get("FAST_RENDERER_CPU_WORKERS", os.cpu_count() or 1)) or "1")
            auto_workers = max(1, min(cpu_worker_cap, len(files), 8))
        if requested_workers > 0:
            worker_count = min(requested_workers, len(files))
        else:
            worker_count = auto_workers
        if max_workers_env > 0:
            worker_count = min(worker_count, max_workers_env)
        worker_count = max(1, worker_count)

        results: Dict[str, Any] = {}
        logs: List[str] = []
        pre_logs: List[str] = []

        used_parallel = parallel_mode and worker_count > 1 and len(files) > 1

        if used_parallel:
            chunk_size = (len(files) + worker_count - 1) // worker_count
            subsets = [files[i : i + chunk_size] for i in range(0, len(files), chunk_size)]
            logs.append(
                f"SERVER_LOG:parallel_render enabled workers={worker_count} visible_gpus={visible_gpus} files={len(files)}"
            )
            logger.info(
                "Parallel render enabled (workers=%s, visible_gpus=%s, files=%s)",
                worker_count,
                visible_gpus,
                len(files),
            )

            gpu_slots = max(1, visible_gpus)
            with ProcessPoolExecutor(max_workers=worker_count) as pool:
                future_map = {}
                for idx, subset in enumerate(subsets):
                    gpu_slot = idx % gpu_slots
                    future = pool.submit(
                        _render_subset_worker,
                        subset,
                        output_dir,
                        real_input_dir,
                        renderer_kwargs,
                        dynamic_params,
                        gpu_slot,
                    )
                    future_map[future] = subset

                for future in as_completed(future_map):
                    subset = future_map[future]
                    try:
                        subset_output = future.result()
                        subset_results = subset_output.get("results", {})
                        subset_logs = subset_output.get("logs", [])
                        if isinstance(subset_results, dict):
                            results.update(subset_results)
                        if isinstance(subset_logs, list):
                            logs.extend(subset_logs)
                    except Exception as exc:
                        error_msg = f"Parallel worker failed: {exc}"
                        logger.error(error_msg, exc_info=True)
                        warnings.append(error_msg)
                        for file_path in subset:
                            results[file_path] = {
                                "success": False,
                                "error": error_msg,
                                "num_files": 0,
                            }
        else:
            if parallel_mode and len(files) > 1 and worker_count <= 1:
                pre_logs.append(
                    f"SERVER_LOG:parallel_render requested but unavailable (visible_gpus={visible_gpus}, workers={worker_count})"
                )
            output_data = renderer.process_batch(files, output_dir, real_input_dir)
            results = output_data.get("results", {})
            logs = pre_logs + (output_data.get("logs", []) or [])

        # Summarize results
        success_count = sum(1 for r in results.values() if r.get("success"))

        return jsonify({
            "success": True,
            "processed_count": len(files),
            "success_count": success_count,
            "results": results,
            "logs": logs,
            "warnings": warnings,
            "execution": {
                "engine": engine,
                "require_gpu": require_gpu,
                "strict_gpu": strict_gpu,
                "force_cycles": force_cycles_default,
                "parallel_mode": parallel_mode,
                "worker_count": worker_count,
                "visible_gpus": visible_gpus,
                "used_parallel": used_parallel,
            },
        })

    except Exception as e:
        logger.error(f"Render failed: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5002))
    app.run(host="0.0.0.0", port=port)
