#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HDP Pipeline Component: main.py (CLI Interface Layer)
for Fast Renderer Component.

This script parses command-line arguments, instantiates the
OptimizedRendererProcessor, and orchestrates the rendering
execution (including parallel and HPC modes).
"""

import argparse
import json
import logging
import os
import platform
import subprocess
from concurrent.futures import ProcessPoolExecutor
from glob import glob

# Import the core logic class and constants from processor.py
try:
    from processor import QUALITY_PRESETS, OptimizedRendererProcessor
except ImportError:
    print("Error: Could not import OptimizedRendererProcessor from processor.py.")
    print("Please ensure processor.py is in the same directory.")
    exit(1)

logger = logging.getLogger(__name__)


# --- Utility Functions (Part of CLI/Orchestration Layer) ---


def scan_models(input_dir: str, extensions: list[str]) -> list[str]:
    """Recursively scans for model files with given extensions."""
    found = []
    for ext in extensions:
        # Ensure extensions have a dot
        ext_with_dot = ext if ext.startswith(".") else f".{ext}"
        found.extend(glob(os.path.join(input_dir, f"**/*{ext_with_dot}"), recursive=True))
    return found


def check_textures(model_path: str) -> bool:
    """Checks if any texture files exist beside the model with same basename."""
    base_dir = os.path.dirname(model_path)
    base_name = os.path.splitext(os.path.basename(model_path))[0]
    texture_exts = [".png", ".jpg", ".jpeg", ".tga", ".tif"]
    for ext in texture_exts:
        if os.path.exists(os.path.join(base_dir, base_name + ext)):
            return True
    return False


def detect_available_gpus() -> int:
    """Detects the number of available GPUs in a portable way.

    Returns:
        int: Number of GPUs detected (defaults to 1 if unknown).
    """
    try:
        # Nvidia GPUs
        result = subprocess.run(
            ["nvidia-smi", "--list-gpus"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.stdout:
            return len([line for line in result.stdout.splitlines() if "GPU" in line])

    except Exception:
        pass

    # Apple Metal (M1/M2/M3)
    try:
        if "Apple" in platform.machine() or "arm" in platform.processor():
            return 1
    except Exception:
        pass

    # Fallback to at least one device
    return 1


def _run_parallel(renderer, files, args):
    """Executes parallel rendering across multiple GPUs or CPUs within a node."""
    gpu_count = detect_available_gpus()
    # Ensure we don't spawn more workers than necessary
    gpu_count = min(gpu_count, len(files))
    if gpu_count <= 0:
        logger.warning("No files or no GPUs detected, skipping parallel run.")
        return {}

    logger.info(f"Parallel mode active using {gpu_count} worker(s).")

    def render_subset(subset, gpu_id):
        """
        Worker function executed by the ProcessPoolExecutor.
        This function runs in a separate process.
        """
        try:
            os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_id)

            local_renderer = OptimizedRendererProcessor(
                resolution=renderer.resolution,
                samples=renderer.samples,
                camera_dist=renderer.camera_dist,
                engine=renderer.engine,
                transparent_background=renderer.transparent_background,
                batch_size=renderer.batch_size,
                timeout_multiplier=renderer.timeout_multiplier,
            )
            # Copy over dynamic (non-init) parameters
            local_renderer.light_energy = renderer.light_energy
            local_renderer.light_angle = renderer.light_angle
            local_renderer.custom_angles = renderer.custom_angles
            return local_renderer.process_batch(subset, args.output_dir, args.input_dir)

        except Exception as e:
            logger.error(f"Worker {gpu_id} failed catastrophically: {e}", exc_info=True)
            return {
                path: {
                    "success": False,
                    "error": f"Worker {gpu_id} failed: {e}",
                    "num_files": 0,
                }
                for path in subset
            }

    # Split the file list into chunks for each worker
    subset_size = (len(files) + gpu_count - 1) // gpu_count
    file_splits = [files[i : i + subset_size] for i in range(0, len(files), subset_size)]

    results = {}
    with ProcessPoolExecutor(max_workers=gpu_count) as executor:
        # Map each file-split chunk to a GPU ID (worker)
        future_to_id = {
            executor.submit(render_subset, subset, gpu_id): gpu_id
            for gpu_id, subset in enumerate(file_splits)
            if subset
        }

        for future in future_to_id:
            gpu_id = future_to_id[future]
            try:
                part_result = future.result()
                results.update(part_result)
            except Exception as e:
                logger.error(f"Failed to retrieve result from worker {gpu_id}: {e}")

    return results


def _run_distributed_hpc(renderer, files, args):
    """Executes distributed chunk processing for HPC job arrays."""
    total = args.total_chunks
    index = args.chunk_index

    # Robust chunking
    if total is None or total <= 0:
        logger.error(f"Invalid total_chunks: {total}. Defaulting to single-chunk run.")
        total = 1
        index = 0
    if index is None or index < 0 or index >= total:
        logger.error(f"Invalid chunk_index: {index} (out of {total}). This node will do no work.")
        return {}

    chunk_size = (len(files) + total - 1) // total
    start = index * chunk_size
    end = min(len(files), (index + 1) * chunk_size)

    node_files = files[start:end]

    logger.info(f"HPC mode: processing chunk {index+1}/{total} " f"(models {start+1} to {end} of {len(files)}).")

    if not node_files:
        logger.warning(f"HPC chunk {index+1} has no files to process.")
        return {}

    # HPC mode delegates to parallel mode on each node
    return _run_parallel(renderer, node_files, args)


def detect_hpc_chunk_environment() -> tuple[int, int] | None:
    """Detects if running under an HPC job array environment like SLURM."""
    logger.debug("Checking for SLURM job array environment...")
    try:
        # --- SLURM ---
        slurm_task_id_str = os.getenv("SLURM_ARRAY_TASK_ID")
        slurm_task_count_str = os.getenv("SLURM_ARRAY_TASK_COUNT")
        slurm_task_min_str = os.getenv("SLURM_ARRAY_TASK_MIN")

        if slurm_task_id_str and slurm_task_count_str and slurm_task_min_str:
            try:
                task_id = int(slurm_task_id_str)
                task_count = int(slurm_task_count_str)
                task_min = int(slurm_task_min_str)

                chunk_index = task_id - task_min
                total_chunks = task_count

                if 0 <= chunk_index < total_chunks:
                    logger.info(f"Detected SLURM: Task {task_id} " f"(index {chunk_index}) of {total_chunks}.")
                    return chunk_index, total_chunks
                else:
                    logger.error(
                        f"SLURM env sanity check failed: ID={task_id}, " f"MIN={task_min}, COUNT={task_count}"
                    )
                    return None
            except ValueError:
                logger.error("Could not parse SLURM environment variables.")
                return None
    except Exception as e:
        logger.warning(f"Could not auto-detect HPC environment: {e}", exc_info=True)

    logger.debug("No HPC job array environment detected.")
    return None


def main():
    """
    Main CLI entry point for the Fast Renderer component.
    Parses args, sets up logging, applies presets, and triggers
    the appropriate rendering mode.
    """
    parser = argparse.ArgumentParser(
        description="Optimized 3D model batch renderer (HDP Component CLI)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # === Paths & basic setup (from component.yaml inputs/outputs) ===
    parser.add_argument(
        "--input-dir",
        default="./input",
        help="Directory containing 3D models to render.",
    )
    parser.add_argument(
        "--output-dir",
        default="./output",
        help="Directory to save rendered images.",
    )

    # === Parameters (from component.yaml parameter_groups) ===
    # Group 1: Render Quality
    parser.add_argument(
        "--preset",
        choices=QUALITY_PRESETS.keys(),
        default="medium",
        help="Render quality preset.",
    )
    parser.add_argument("--resolution", type=int, help="Manual override for resolution.")
    parser.add_argument("--samples", type=int, help="Manual override for render samples.")
    parser.add_argument("--camera-dist", type=float, help="Manual override for camera distance.")

    # Group 2: Render Configuration
    parser.add_argument("--engine", default="CYCLES", help="Blender rendering engine to use.")
    parser.add_argument(
        "--formats",
        nargs="+",
        default=[".obj", ".glb", ".gltf", ".usdz", ".ply", ".fbx", ".dae", ".stl", ".usd", ".usda", ".usdc", ".abc"],
        help="Space-separated list of file formats to scan for.",
    )
    parser.add_argument(
        "--transparent-background",
        action="store_true",
        default=True,
        help="Use transparent PNG background.",
    )

    # Group 3: Camera and Lighting
    parser.add_argument(
        "--angles",
        nargs="+",
        type=float,
        default=[0, 72, 144, 216, 288],
        help="Space-separated list of camera rotation angles.",
    )
    parser.add_argument(
        "--angle-iteration",
        type=int,
        help="Number of evenly spaced angles around the model.",
    )
    parser.add_argument("--light-energy", type=float, default=4.0, help="Light source intensity.")
    parser.add_argument(
        "--light-angle",
        type=float,
        default=45.0,
        help="Directional light angle in degrees.",
    )

    # Group 4: Processing and Performance
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of models processed per Blender run.",
    )
    parser.add_argument(
        "--timeout-multiplier",
        type=float,
        default=1.0,
        help="Timeout scaling factor.",
    )
    parser.add_argument(
        "--parallel-mode",
        action="store_true",
        help="Enable parallel rendering on a single node.",
    )
    parser.add_argument(
        "--hpc-mode",
        action="store_true",
        help="Enable HPC optimizations (implies parallel mode).",
    )
    parser.add_argument(
        "--chunk-index",
        type=int,
        help="Chunk index for distributed HPC execution.",
    )
    parser.add_argument(
        "--total-chunks",
        type=int,
        help="Total number of chunks for distributed rendering.",
    )

    # Group 5: Validation and Debugging
    parser.add_argument(
        "--check-textures",
        action="store_true",
        help="Verify presence of associated texture files.",
    )
    parser.add_argument(
        "--skip-missing-textures",
        action="store_true",
        help="If texture checking is enabled, skip warnings.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration and scan models without rendering.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable detailed debug logging output.")
    parser.add_argument(
        "--no-ansi",
        action="store_true",
        help="Disable ANSI color formatting in console output.",
    )

    args = parser.parse_args()

    # === Hierarchical Activation: HPC implies parallel mode ===
    if args.hpc_mode:
        args.parallel_mode = True

        # Detect HPC job array configuration automatically
        if args.chunk_index is None or args.total_chunks is None:
            env_chunks = detect_hpc_chunk_environment()
            if env_chunks:
                args.chunk_index, args.total_chunks = env_chunks
            else:
                logger.warning("HPC mode enabled but no scheduler detected. " "Defaulting to single-chunk run.")
                args.chunk_index, args.total_chunks = 0, 1

    # === Logging configuration ===
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    if args.no_ansi:
        logging.addLevelName(logging.INFO, "INFO")
        logging.addLevelName(logging.ERROR, "ERROR")

    logger.info("Starting Fast Renderer Component CLI.")

    # === Ensure directories exist ===
    # Handle case where input_dir is passed as a file path (from pipeline mapping)
    input_is_file = False
    if os.path.isfile(args.input_dir):
        input_is_file = True
        real_input_dir = os.path.dirname(args.input_dir)
    else:
        real_input_dir = args.input_dir
        os.makedirs(real_input_dir, exist_ok=True)

    os.makedirs(args.output_dir, exist_ok=True)

    # === Apply preset and overrides ===
    quality = QUALITY_PRESETS[args.preset].copy()
    if args.resolution:
        quality["resolution"] = args.resolution
    if args.samples:
        quality["samples"] = args.samples
    if args.camera_dist:
        quality["camera_dist"] = args.camera_dist

    # === Initialize renderer (from processor.py) ===
    try:
        renderer = OptimizedRendererProcessor(
            resolution=quality["resolution"],
            samples=quality["samples"],
            camera_dist=quality["camera_dist"],
            engine=args.engine,
            transparent_background=args.transparent_background,
            batch_size=args.batch_size,
            timeout_multiplier=args.timeout_multiplier,
        )
    except Exception as e:
        logger.error(f"Failed to initialize renderer: {e}", exc_info=True)
        return

    # Inject dynamic parameters for Blender scripts
    renderer.light_energy = args.light_energy
    renderer.light_angle = args.light_angle

    # === Angle configuration ===
    if args.angles and args.angle_iteration:
        logger.error("Cannot use --angles and --angle-iteration together.")
        return
    if args.angles:
        # No more splitting, argparse gives us a list directly
        renderer.custom_angles = args.angles
        renderer.num_images = len(renderer.custom_angles)
    elif args.angle_iteration:
        renderer.custom_angles = []
        renderer.num_images = args.angle_iteration
    else:
        # Fallback to default (from argparse)
        renderer.custom_angles = args.angles
        renderer.num_images = len(renderer.custom_angles)

    # === Scan & dry-run checks ===
    if input_is_file:
        files = [args.input_dir]
        logger.info(f"Processing single file input: {args.input_dir}")
    else:
        file_formats = args.formats
        files = scan_models(real_input_dir, file_formats)

    if not files:
        logger.warning("No model files found matching provided formats.")
        return

    logger.info(f"Found {len(files)} model(s) matching extensions {args.formats}")

    if args.dry_run:
        logger.info("Dry run completed successfully. No rendering performed.")
        return

    # === Conditional texture checking ===
    filtered = files
    if args.check_textures:
        filtered_checked = []
        for f in files:
            has_tex = check_textures(f)
            if has_tex or args.skip_missing_textures:
                filtered_checked.append(f)
            else:
                logger.warning(f"Missing textures for {f} " "(use --skip-missing-textures to continue).")
        filtered = filtered_checked
        logger.info(f"After texture check: {len(filtered)} model(s) remain for rendering.")

    if not filtered:
        logger.warning("No valid models remaining for rendering after prechecks.")
        return

    # === Rendering Execution ===
    results = {}
    try:
        if args.hpc_mode:
            results = _run_distributed_hpc(renderer, filtered, args)
        elif args.parallel_mode:
            results = _run_parallel(renderer, filtered, args)
        else:
            results = renderer.process_batch(filtered, args.output_dir, real_input_dir)
    except Exception as e:
        logger.error(f"An unexpected error occurred during processing: {e}", exc_info=True)

    logger.info("Rendering complete.")

    # Print final JSON results to stdout for pipeline integration
    print(json.dumps(results, indent=4))


if __name__ == "__main__":
    main()
