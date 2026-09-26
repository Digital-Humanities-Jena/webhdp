#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HDP Pipeline Component: processor.py (Core Logic Layer)
for Fast Renderer Component.

This file contains the OptimizedRendererProcessor class and configuration
constants. It is strictly a processing library and does not handle
CLI parsing or high-level orchestration.
"""
import json
import logging
import os
import shutil
import string
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

CYCLES_BACKEND_CANDIDATES = ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL")
CYCLES_BACKEND_DEVICE_TYPES = {
    "OPTIX": {"OPTIX"},
    "CUDA": {"CUDA"},
    "HIP": {"HIP"},
    "ONEAPI": {"ONEAPI"},
    "METAL": {"METAL"},
}


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


def select_cycles_backend(device_inventory: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """
    Pick the first Cycles backend that exposes at least one non-CPU device of
    the expected type. This mirrors the Blender-side fallback logic.
    """
    diagnostics: List[str] = []
    for candidate in CYCLES_BACKEND_CANDIDATES:
        devices = list(device_inventory.get(candidate) or [])
        preferred_types = CYCLES_BACKEND_DEVICE_TYPES.get(candidate, set())
        matched = []
        for device in devices:
            device_type = str(device.get("type") or "").strip().upper()
            if device_type == "CPU":
                continue
            if preferred_types and device_type not in preferred_types:
                continue
            matched.append(device)
        diagnostics.append(f"{candidate}:{len(matched)}/{len(devices)}")
        if matched:
            return {
                "backend": candidate,
                "matched_devices": matched,
                "diagnostics": diagnostics,
            }

    return {
        "backend": None,
        "matched_devices": [],
        "diagnostics": diagnostics,
    }

# Consumed by main.py to determine default settings
QUALITY_PRESETS = {
    "draft": {"resolution": 256, "samples": 8, "camera_dist": 1.0},
    "medium": {"resolution": 512, "samples": 32, "camera_dist": 1.8},
    "high": {"resolution": 1024, "samples": 128, "camera_dist": 2.5},
    "ultra": {"resolution": 2048, "samples": 256, "camera_dist": 3.0},
}

# Internal template for the Blender background process
OPTIMIZED_BATCH_TEMPLATE = '''
import bpy
import os
import sys
import math
import time
import json
from mathutils import Vector
import importlib

# --- Parameters Injected by Processor ---
MODELS_TO_RENDER = ${models_list}
OUTPUT_BASE_DIR = r"${output_dir}"
ENGINE = "${engine}"
NUM_IMAGES = ${num_images}
CAMERA_DIST = ${camera_dist}
RESOLUTION = ${resolution}
SAMPLES = ${samples}
TRANSPARENT = ${transparent}
LIGHT_ENERGY = ${light_energy}
LIGHT_ANGLE = ${light_angle}
CUSTOM_ANGLES = ${custom_angles}
STRICT_GPU = ${strict_gpu}

# --- Utility Functions ---
def reset_scene() -> None:
    """Clears the scene of all objects, materials, and data."""
    if bpy.ops.object.mode_set.poll():
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    if bpy.context.selected_objects:
        bpy.ops.object.delete()
    bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)

def configure_cycles_devices(scene):
    """
    Attempt to force Cycles GPU rendering by selecting a supported backend and
    enabling all non-CPU devices.
    """
    backend_used = None
    enabled_gpu_devices = 0
    reason = ""
    try:
        addon = bpy.context.preferences.addons.get("cycles")
        prefs = addon.preferences if addon and hasattr(addon, "preferences") else None
        if not prefs:
            return False, backend_used, enabled_gpu_devices, "Cycles preferences unavailable"

        diagnostics = []
        candidates = ["OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"]
        for candidate in candidates:
            try:
                prefs.compute_device_type = candidate
            except Exception as exc:
                diagnostics.append(f"{candidate}:unavailable({exc})")
                continue

            try:
                if hasattr(prefs, "refresh_devices"):
                    prefs.refresh_devices()
                elif hasattr(prefs, "get_devices"):
                    prefs.get_devices()
            except Exception as exc:
                diagnostics.append(f"{candidate}:refresh_failed({exc})")
                continue

            devices = list(getattr(prefs, "devices", []) or [])
            preferred_types = {
                "OPTIX": {"OPTIX"},
                "CUDA": {"CUDA"},
                "HIP": {"HIP"},
                "ONEAPI": {"ONEAPI"},
                "METAL": {"METAL"},
            }.get(candidate, set())
            matched_for_candidate = 0
            for device in devices:
                try:
                    device_type = getattr(device, "type", "").upper()
                    if device_type == "CPU":
                        device.use = False
                        continue
                    if preferred_types and device_type not in preferred_types:
                        device.use = False
                        continue
                    device.use = True
                    matched_for_candidate += 1
                except Exception:
                    continue

            diagnostics.append(f"{candidate}:{matched_for_candidate}/{len(devices)}")
            if matched_for_candidate > 0:
                backend_used = candidate
                enabled_gpu_devices = matched_for_candidate
                scene.cycles.device = "GPU"
                return True, backend_used, enabled_gpu_devices, "; ".join(diagnostics)

        reason = "No GPU devices enabled for Cycles"
        if diagnostics:
            reason = f"{reason}; attempts={' | '.join(diagnostics)}"
    except Exception as exc:
        reason = str(exc)

    scene.cycles.device = "CPU"
    return False, backend_used, enabled_gpu_devices, reason

def resolve_render_engine(render):
    requested_engine = str(ENGINE).strip().upper()
    candidates = [requested_engine]
    if requested_engine == "BLENDER_EEVEE":
        candidates = ["BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"]
    elif requested_engine == "BLENDER_EEVEE_NEXT":
        candidates = ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"]

    if requested_engine == "CYCLES":
        try:
            import addon_utils
            enabled, loaded = addon_utils.check("cycles")
            if not loaded:
                addon_utils.enable("cycles", default_set=False, persistent=False)
            print(f"BATCH_LOG:DEBUG:engine:cycles_addon enabled={enabled} loaded={loaded}")
        except Exception as exc:
            print(f"BATCH_LOG:WARNING:engine:Unable to enforce cycles add-on load ({exc})")

    last_error = ""
    for candidate in candidates:
        try:
            render.engine = candidate
            return candidate
        except Exception as exc:
            last_error = str(exc)
            continue

    print(
        f"BATCH_LOG:WARNING:engine:Unsupported engine '{ENGINE}' "
        f"(last_error={last_error}), falling back to BLENDER_WORKBENCH"
    )
    render.engine = "BLENDER_WORKBENCH"
    return "BLENDER_WORKBENCH"

def setup_camera_and_scene():
    """Sets up render engine, resolution, lighting, and adaptive camera."""
    scene = bpy.context.scene
    render = scene.render

    normalized_engine = resolve_render_engine(render)
    print(f"BATCH_LOG:DEBUG:engine:requested={ENGINE} selected={normalized_engine}")
    render.resolution_x, render.resolution_y = RESOLUTION, RESOLUTION
    render.image_settings.file_format = "PNG"
    render.image_settings.color_mode = "RGBA"
    render.film_transparent = TRANSPARENT

    if normalized_engine == 'CYCLES':
        scene.render.use_persistent_data = True
        scene.cycles.samples = SAMPLES
        scene.cycles.use_denoising = True
        gpu_ok, backend_used, gpu_count, reason = configure_cycles_devices(scene)
        if gpu_ok:
            print(f"BATCH_LOG:DEBUG:cycles:Using GPU backend={backend_used} devices={gpu_count}")
        else:
            failure_msg = (
                f"Cycles GPU unavailable (backend={backend_used} reason={reason})"
            )
            if STRICT_GPU:
                raise RuntimeError(failure_msg)
            print(f"BATCH_LOG:WARNING:cycles:{failure_msg}; falling back to CPU")
    elif normalized_engine in ['BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT']:
        # Compatibility for older and newer Blender versions
        if hasattr(scene, 'eevee'):
            # In Blender 4.3+, EEVEE_NEXT is the standard, though enum might vary
            # We set samples based on what's available
            if hasattr(scene.eevee, 'taa_render_samples'):
                 scene.eevee.taa_render_samples = SAMPLES
            elif hasattr(scene.eevee, 'render_samples'):
                 scene.eevee.render_samples = SAMPLES

    # Lighting setup
    light_data = bpy.data.lights.new(name="SunLight", type='SUN')
    light_data.energy = LIGHT_ENERGY
    light_obj = bpy.data.objects.new(name="SunLight", object_data=light_data)
    scene.collection.objects.link(light_obj)
    light_obj.location = (0, -2, 2)
    light_obj.rotation_euler = (math.radians(LIGHT_ANGLE), 0, 0)

    # Camera setup
    cam_data = bpy.data.cameras.new("Camera")
    cam = bpy.data.objects.new("Camera", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    cam_constraint = cam.constraints.new(type="TRACK_TO")
    cam_constraint.track_axis = "TRACK_NEGATIVE_Z"
    cam_constraint.up_axis = "UP_Y"

    empty = bpy.data.objects.new("Empty", None)
    scene.collection.objects.link(empty)
    empty.location = (0, 0, 0)
    cam_constraint.target = empty

    return cam, cam_data

def scene_bounding_sphere():
    """Calculates the bounding sphere radius of all MESH objects."""
    bbox_min, bbox_max = scene_bbox()
    if bbox_min is None or bbox_max is None:
        return None
    center = (bbox_min + bbox_max) / 2
    max_dist = 0
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            for vertex in obj.data.vertices:
                world_co = obj.matrix_world @ vertex.co
                dist = (world_co - center).length
                max_dist = max(max_dist, dist)
    return max_dist

def scene_bbox(ignore_matrix=False):
    bbox_min, bbox_max = (math.inf,) * 3, (-math.inf,) * 3
    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not mesh_objects:
        return None, None
    for obj in mesh_objects:
        for coord in obj.bound_box:
            coord = Vector(coord)
            if not ignore_matrix:
                coord = obj.matrix_world @ coord
            bbox_min = tuple(min(x, y) for x, y in zip(bbox_min, coord))
            bbox_max = tuple(max(x, y) for x, y in zip(bbox_max, coord))
    return Vector(bbox_min), Vector(bbox_max)

def normalize_scene():
    """Scales and centers all MESH objects."""
    bbox_min, bbox_max = scene_bbox()
    if bbox_min is None or bbox_max is None:
        return
    diagonal = bbox_max - bbox_min
    if max(diagonal) == 0:
        return
    scale = 1 / max(diagonal)
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            obj.scale = obj.scale * scale
    bpy.context.view_layer.update()
    bbox_min, bbox_max = scene_bbox()
    if bbox_min is not None:
        offset = -(bbox_min + bbox_max) / 2
        for obj in bpy.context.scene.objects:
            if obj.type == "MESH":
                obj.matrix_world.translation += offset
    bpy.ops.object.select_all(action="DESELECT")

def validate_texture_images():
    """Reject missing or unreadable textures instead of rendering placeholders."""
    for image in bpy.data.images:
        if image.source not in {"FILE", "TILED"}:
            continue
        if not image.has_data:
            image.reload()
        if not all(image.size) or not len(image.pixels):
            raise RuntimeError("Texture could not be decoded: " + image.name)

def import_model(filepath: str):
    """Imports a 3D model into Blender with format detection."""
    import os
    ext = os.path.splitext(filepath)[1].lower()
    if ext in [".gltf", ".glb"]:
        bpy.ops.import_scene.gltf(filepath=filepath, merge_vertices=True)
        return
    if ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=filepath)
        return
    if ext == ".obj":
        obj_dir = os.path.dirname(filepath)
        if hasattr(bpy.ops.wm, "obj_import"):
            bpy.ops.wm.obj_import(filepath=filepath)
        else:
            bpy.ops.import_scene.obj(filepath=filepath, directory=obj_dir)
        return
    if ext in [".usd", ".usda", ".usdc", ".usdz"]:
        if hasattr(bpy.ops.wm, "usd_import"):
            bpy.ops.wm.usd_import(filepath=filepath)
            return
        raise RuntimeError("USD import not supported in this Blender version")
    if ext == ".abc":
        bpy.ops.wm.alembic_import(filepath=filepath)
        return
    if ext == ".dae":
        bpy.ops.wm.collada_import(filepath=filepath)
        return
    if ext == ".stl":
        if hasattr(bpy.ops.wm, "stl_import"):
            bpy.ops.wm.stl_import(filepath=filepath)
        else:
            bpy.ops.import_mesh.stl(filepath=filepath)
        return
    if ext == ".ply":
        if hasattr(bpy.ops.wm, "ply_import"):
            bpy.ops.wm.ply_import(filepath=filepath)
            return
        if "io_mesh_ply" not in bpy.context.preferences.addons:
            try:
                bpy.ops.preferences.addon_enable(module="io_mesh_ply")
            except:
                pass
        if hasattr(bpy.ops.import_mesh, "ply"):
            bpy.ops.import_mesh.ply(filepath=filepath)
            return
        raise RuntimeError("PLY import failed")
    raise RuntimeError(f"Unsupported format: '{ext}'")

def main():
    for idx, model_info in enumerate(MODELS_TO_RENDER):
        object_path = model_info["path"]
        object_uid = model_info["uid"]
        print(f"BATCH_LOG:PROGRESS:{idx+1}/{len(MODELS_TO_RENDER)}:{object_uid}")
        try:
            start_time = time.time()
            stage_timings = {}

            stage_start = time.time()
            reset_scene()
            stage_timings["scene_reset"] = time.time() - stage_start

            stage_start = time.time()
            cam, cam_data = setup_camera_and_scene()
            stage_timings["scene_setup"] = time.time() - stage_start

            try:
                stage_start = time.time()
                import_model(object_path)
                validate_texture_images()
                stage_timings["model_import"] = time.time() - stage_start
            except Exception as e:
                print(f"BATCH_LOG:FAILURE:{object_path}:Import failed ({e})")
                reset_scene()
                continue

            stage_start = time.time()
            imported_meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
            if not imported_meshes:
                raise RuntimeError("No MESH objects found.")
            bpy.context.view_layer.objects.active = imported_meshes[0]
            for obj in imported_meshes:
                obj.select_set(True)
            if len(imported_meshes) > 1:
                bpy.ops.object.join()
            normalize_scene()
            stage_timings["mesh_prepare_and_normalize"] = time.time() - stage_start

            stage_start = time.time()
            bounding_radius = scene_bounding_sphere()
            if bounding_radius is None or bounding_radius == 0:
                bounding_radius = 0.5
            camera_fov = cam_data.angle
            adaptive_distance = (bounding_radius / math.tan(camera_fov / 2)) * 1.15
            adaptive_distance = max(adaptive_distance, 1.0)
            stage_timings["camera_distance_calculation"] = time.time() - stage_start

            output_subdir = model_info["output_subdir"]
            model_output_dir = os.path.join(OUTPUT_BASE_DIR, output_subdir)

            if CUSTOM_ANGLES:
                angles_data = [(math.radians(a), math.radians(60), int(a % 360)) for a in CUSTOM_ANGLES]
            else:
                if NUM_IMAGES > 1:
                    # NUM_IMAGES - 1 from side, 1 from top
                    angles_data = []
                    for i in range(NUM_IMAGES - 1):
                        theta = (i / (NUM_IMAGES - 1)) * 360
                        angles_data.append((math.radians(theta), math.radians(60), int(theta % 360)))
                    # Add top view (theta=0, phi=0)
                    angles_data.append((0, 0, 999)) # 999 as a special marker for top
                else:
                    angles_data = [(0, math.radians(60), 0)]

            stage_start = time.time()
            for theta, phi, angle_int in angles_data:
                point = (
                    adaptive_distance * math.sin(phi) * math.cos(theta),
                    adaptive_distance * math.sin(phi) * math.sin(theta),
                    adaptive_distance * math.cos(phi),
                )
                cam.location = point
                bpy.context.view_layer.update()

                suffix = "top" if angle_int == 999 else f"r{angle_int:03d}"
                filename = f"{object_uid}_{suffix}.png"
                render_path = os.path.join(model_output_dir, filename)
                bpy.context.scene.render.filepath = render_path
                try:
                    bpy.ops.render.render(write_still=True)
                except Exception as render_err:
                    if STRICT_GPU and bpy.context.scene.render.engine == "CYCLES":
                        raise RuntimeError(f"Cycles render failed: {render_err}")
                    print(f"BATCH_LOG:WARNING:{object_path}:Render failed with {ENGINE}, trying WORKBENCH. Error: {render_err}")
                    bpy.context.scene.render.engine = 'BLENDER_WORKBENCH'
                    bpy.ops.render.render(write_still=True)
            stage_timings["render_images"] = time.time() - stage_start

            duration = time.time() - start_time
            stage_timings["total"] = duration
            stage_timings["num_images"] = len(angles_data)
            print(f"BATCH_LOG:TIMING:{object_path}:{json.dumps(stage_timings, separators=(',', ':'))}")
            print(f"BATCH_LOG:SUCCESS:{object_path}:{duration:.2f}s")
        except Exception as e:
            print(f"BATCH_LOG:FAILURE:{object_path}:{str(e).replace(chr(10), ' ')}")
            reset_scene()
            continue

if __name__ == "__main__":
    main()
'''


class OptimizedRendererProcessor:
    """
    Renders batches of 3D models using a fast and accurate pipeline.
    This class handles the logic of preparing the Blender script,
    creating temporary files, and invoking the Blender subprocess.
    """

    def __init__(self, **kwargs: Any):
        """Initializes the OptimizedRendererProcessor with validated parameters."""
        self.num_images = int(kwargs.get("num_images", 5))
        self.engine = str(kwargs.get("engine", "CYCLES"))
        self.camera_dist = float(kwargs.get("camera_dist", 1.8))
        self.resolution = int(kwargs.get("resolution", 512))
        self.samples = int(kwargs.get("samples", 16))
        self.transparent_background = bool(kwargs.get("transparent_background", True))
        self.batch_size = int(kwargs.get("batch_size", 50))
        self.timeout_multiplier = float(kwargs.get("timeout_multiplier", 1.0))
        self.strict_gpu = _as_bool(
            kwargs.get(
                "strict_gpu",
                os.environ.get("FAST_RENDERER_STRICT_GPU", os.environ.get("REQUIRE_GPU", "false")),
            ),
            default=False,
        )

        # Defaults for dynamic properties
        self.light_energy = 4.0
        self.light_angle = 45.0
        self.custom_angles = []

        self.blender_executable = self._find_blender_executable()
        self._validate_blender_executable()

    def _validate_blender_executable(self) -> None:
        """Validates that Blender executable exists and is functional."""
        if not Path(self.blender_executable).exists():
            raise RuntimeError(f"Blender executable not found at: {self.blender_executable}")

        try:
            result = subprocess.run(
                [self.blender_executable, "--version"], capture_output=True, text=True, timeout=10, check=False
            )
            if result.returncode != 0:
                raise RuntimeError(f"Blender executable test failed: {result.stderr}")
            logger.info(f"Using Blender: {result.stdout.splitlines()[0]}")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Blender executable test timed out")
        except Exception as e:
            raise RuntimeError(f"Failed to validate Blender: {e}")

    def _find_blender_executable(self) -> str:
        """Finds a Blender executable on the system."""
        configured = os.environ.get("BLENDER_BIN")
        if configured:
            return configured
        blender_path = shutil.which("blender")
        if blender_path:
            return blender_path
        common_paths = [
            "/usr/bin/blender",
            "/Applications/Blender.app/Contents/MacOS/blender",
            "C:/Program Files/Blender Foundation/Blender/blender.exe",
        ]
        for path in common_paths:
            if Path(path).exists() and os.access(path, os.X_OK):
                return path
        raise RuntimeError("Blender not found. Please install Blender.")

    def _prepare_output_directories(self, file_paths: List[str], output_dir: str, input_dir: str) -> None:
        """Pre-creates output directories with validation."""
        input_path_obj = Path(input_dir)
        output_path_obj = Path(output_dir)

        if not output_path_obj.exists():
            try:
                output_path_obj.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                raise RuntimeError(f"Cannot create output directory '{output_dir}': {e}")

        if not os.access(output_path_obj, os.W_OK):
            raise RuntimeError(f"Output directory is not writable: {output_dir}")

        missing_files = []
        for path in file_paths:
            if not Path(path).exists():
                missing_files.append(path)

        if missing_files:
            raise FileNotFoundError(f"Input files not found: {missing_files[:5]}")

        for path in file_paths:
            path_obj = Path(path)
            try:
                relative_path = path_obj.relative_to(input_path_obj)
                output_sub_dir = relative_path
                model_output_dir = output_path_obj / output_sub_dir
                model_output_dir.mkdir(parents=True, exist_ok=True)
            except ValueError as e:
                raise ValueError(f"File '{path}' is not within input directory '{input_dir}': {e}")
            except Exception as e:
                raise RuntimeError(f"Failed to create directory for '{path}': {e}")

    def process_batch(self, file_paths: List[str], output_dir: str, input_dir: str) -> Dict[str, Any]:
        """Processes batches with memory management and robust error handling.
        Returns a dictionary containing:
            - results: Dict[str, Dict[str, Any]] mapping paths to success/error
            - logs: List[str] containing all stdout logs
        """
        if not file_paths:
            logger.warning("No files to process")
            return {"results": {}, "logs": []}

        abs_file_paths = [str(Path(p).resolve()) for p in file_paths]
        abs_input_dir = str(Path(input_dir).resolve())
        abs_output_dir = str(Path(output_dir).resolve())

        self._prepare_output_directories(abs_file_paths, abs_output_dir, abs_input_dir)

        all_results = {}
        all_logs = []
        total_chunks = (len(abs_file_paths) - 1) // self.batch_size + 1

        for chunk_idx in range(0, len(abs_file_paths), self.batch_size):
            chunk = abs_file_paths[chunk_idx : chunk_idx + self.batch_size]
            current_chunk_num = chunk_idx // self.batch_size + 1

            logger.info(f"Processing chunk {current_chunk_num}/{total_chunks} ({len(chunk)} models)")

            try:
                script_content = self._generate_batch_script(chunk, abs_output_dir, abs_input_dir)
                results, logs = self._execute_render_batch(script_content, abs_output_dir, chunk, abs_input_dir)
                all_logs.extend(logs)

                for path in chunk:
                    if path not in results:
                        results[path] = {
                            "success": False,
                            "error": "Model not processed by Blender batch.",
                            "num_files": 0,
                        }

                all_results.update(results)
                successful = sum(1 for r in results.values() if r.get("success", False))
                logger.info(f"Chunk {current_chunk_num}: {successful}/{len(chunk)} successful")

            except Exception as e:
                logger.error(f"Chunk {current_chunk_num} failed: {e}", exc_info=True)
                all_logs.append(f"EXCEPTION: {str(e)}")
                for path in chunk:
                    if path not in all_results:
                        all_results[path] = {
                            "success": False,
                            "error": f"Chunk processing error: {str(e)}",
                            "num_files": 0,
                        }

        total_success = sum(1 for r in all_results.values() if r.get("success", False))
        logger.info(f"Batch complete: {total_success}/{len(abs_file_paths)} models rendered successfully")

        return {"results": all_results, "logs": all_logs}

    def _generate_batch_script(self, file_paths: List[str], output_dir: str, input_dir: str) -> str:
        """Generates a Python script for Blender by substituting placeholders in the template."""
        template = string.Template(OPTIMIZED_BATCH_TEMPLATE)
        models_list = []
        input_path_obj = Path(input_dir)
        for p in file_paths:
            path_obj = Path(p)
            relative_path = path_obj.relative_to(input_path_obj)
            output_sub_dir = relative_path

            models_list.append(
                {
                    "path": str(path_obj.resolve()).replace("\\", "/"),
                    "uid": path_obj.stem,
                    "output_subdir": str(output_sub_dir).replace("\\", "/"),
                }
            )
        substitutions = {
            "models_list": json.dumps(models_list, indent=4),
            "output_dir": str(Path(output_dir).resolve()).replace("\\", "/"),
            "engine": self.engine,
            "num_images": self.num_images,
            "camera_dist": self.camera_dist,
            "resolution": self.resolution,
            "samples": self.samples,
            "transparent": self.transparent_background,
            "light_energy": getattr(self, "light_energy", 4.0),
            "light_angle": getattr(self, "light_angle", 45.0),
            "custom_angles": json.dumps(getattr(self, "custom_angles", [])),
            "strict_gpu": self.strict_gpu,
        }
        return template.substitute(substitutions)

    def _execute_render_batch(
        self, script_content: str, output_dir: str, file_paths: List[str], input_dir: str
    ) -> tuple[Dict[str, Dict[str, Any]], List[str]]:
        """Executes Blender with adaptive timeout and robust error handling.
        Returns a tuple of (results, logs).
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as temp_script:
            temp_script.write(script_content)
            temp_script_path = temp_script.name

        base_time_per_model = 60
        time_per_image = 120 if self.engine in ["BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"] else 180
        resolution_factor = (self.resolution / 512) ** 2

        timeout_seconds = len(file_paths) * (
            base_time_per_model + self.num_images * time_per_image * resolution_factor
        )
        timeout_seconds = int(timeout_seconds * self.timeout_multiplier)

        min_timeout, max_timeout = 300, 14400
        timeout_seconds = max(min_timeout, min(timeout_seconds, max_timeout))

        logger.info(f"Blender timeout set to {timeout_seconds}s")

        cmd = [self.blender_executable, "--background", "--python", temp_script_path]
        results = {}
        logs = []
        timing_payload_by_path = {}

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=timeout_seconds)

            if proc.returncode != 0:
                debug_log_file = Path(output_dir) / f"blender_error_{int(time.time())}.log"
                debug_log_file.write_text(
                    f"Return Code: {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
                )
                logger.error(f"Blender exited with code {proc.returncode}. Debug log: {debug_log_file}")

            # Log full output for debugging if success count is 0
            if proc.stdout:
                stdout_lines = proc.stdout.splitlines()
                logs.extend(stdout_lines)

                # If no successful renders reported, dump the whole stdout to logger
                if "BATCH_LOG:SUCCESS" not in proc.stdout:
                    logger.warning("Blender produced no success logs. Full output follows:")
                    for line in stdout_lines:
                        logger.warning(f"BLENDER: {line}")

                for line in stdout_lines:
                    if line.startswith("BATCH_LOG:"):
                        try:
                            parts = line.split(":", 3)
                            if len(parts) >= 4:
                                _, status, path, message = parts
                                if status == "SUCCESS":
                                    duration = message.replace("s", "").strip()
                                    try:
                                        parsed_duration = float(duration)
                                    except (TypeError, ValueError):
                                        parsed_duration = None

                                    # Find images
                                    images = []
                                    try:
                                        rel_path = Path(path).relative_to(Path(input_dir))
                                        model_out_subdir = rel_path
                                        model_out_path = Path(output_dir) / model_out_subdir
                                        if model_out_path.exists():
                                            images = [str(p.resolve()) for p in model_out_path.glob("*.png")]
                                    except Exception as e:
                                        logger.error(f"Failed to scan results for {path}: {e}")

                                    results[path] = {
                                        "success": True,
                                        "error": "",
                                        "num_files": len(images),
                                        "duration": parsed_duration if parsed_duration is not None else duration,
                                        "images": sorted(images)
                                    }
                                    if isinstance(timing_payload_by_path.get(path), dict):
                                        results[path]["subprocess_timings"] = timing_payload_by_path[path]
                                elif status == "FAILURE":
                                    results[path] = {"success": False, "error": message.strip(), "num_files": 0}
                                elif status == "DEBUG":
                                    logger.debug(f"{path}: {message.strip()}")
                                elif status == "TIMING":
                                    try:
                                        parsed_payload = json.loads(message)
                                        if isinstance(parsed_payload, dict):
                                            timing_payload_by_path[path] = parsed_payload
                                            existing = results.get(path)
                                            if isinstance(existing, dict):
                                                existing["subprocess_timings"] = parsed_payload
                                    except json.JSONDecodeError:
                                        logger.warning(f"Failed to parse timing payload for {path}: {message}")
                        except (ValueError, IndexError):
                            pass

            if proc.stderr:
                logs.extend(proc.stderr.splitlines())
                if "BATCH_LOG:SUCCESS" not in (proc.stdout or ""):
                    for line in proc.stderr.splitlines():
                        logger.error(f"BLENDER_ERR: {line}")

            return results, logs

        except subprocess.TimeoutExpired:
            logger.error(f"Blender batch timed out after {timeout_seconds}s")
            for path in file_paths:
                if path not in results:
                    results[path] = {
                        "success": False,
                        "error": f"Blender process timed out after {timeout_seconds}s",
                        "num_files": 0,
                    }
            return results, []
        except Exception as e:
            logger.error(f"Unexpected error executing Blender: {e}", exc_info=True)
            raise
        finally:
            try:
                os.unlink(temp_script_path)
            except Exception:
                pass
