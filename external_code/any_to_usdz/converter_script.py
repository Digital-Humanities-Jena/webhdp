import argparse
import os
import shutil
import sys
import time
import traceback
import zipfile
from typing import Callable, Dict

import bpy


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


def _safe_enable_addon(module_name: str) -> None:
    try:
        import addon_utils

        addon_utils.enable(module_name, default_set=True, persistent=False)
    except Exception as exc:
        print(f"[WARN] Could not enable addon '{module_name}': {exc}")


def _enable_required_addons(extension: str) -> None:
    addon_map = {
        ".glb": ["io_scene_gltf2"],
        ".gltf": ["io_scene_gltf2"],
        ".obj": ["io_scene_obj"],
        ".fbx": ["io_scene_fbx"],
        ".ply": ["io_mesh_ply"],
        ".stl": ["io_mesh_stl"],
        ".x3d": ["io_scene_x3d"],
        ".wrl": ["io_scene_x3d"],
        ".dae": ["io_scene_dae"],
    }
    for addon in addon_map.get(extension, []):
        _safe_enable_addon(addon)


def _import_obj(filepath: str) -> None:
    if hasattr(bpy.ops.wm, "obj_import"):
        bpy.ops.wm.obj_import(filepath=filepath)
    else:
        bpy.ops.import_scene.obj(filepath=filepath, use_image_search=True)


def _import_ply(filepath: str) -> None:
    if hasattr(bpy.ops.wm, "ply_import"):
        bpy.ops.wm.ply_import(filepath=filepath)
    else:
        bpy.ops.import_mesh.ply(filepath=filepath)


def _import_stl(filepath: str) -> None:
    if hasattr(bpy.ops.wm, "stl_import"):
        bpy.ops.wm.stl_import(filepath=filepath)
    else:
        bpy.ops.import_mesh.stl(filepath=filepath)


IMPORTERS: Dict[str, Callable[[str], None]] = {
    ".glb": lambda path: bpy.ops.import_scene.gltf(filepath=path),
    ".gltf": lambda path: bpy.ops.import_scene.gltf(filepath=path),
    ".obj": _import_obj,
    ".fbx": lambda path: bpy.ops.import_scene.fbx(filepath=path, use_image_search=True),
    ".ply": _import_ply,
    ".stl": _import_stl,
    ".abc": lambda path: bpy.ops.wm.alembic_import(filepath=path),
    ".dae": lambda path: bpy.ops.wm.collada_import(filepath=path),
    ".x3d": lambda path: bpy.ops.import_scene.x3d(filepath=path),
    ".wrl": lambda path: bpy.ops.import_scene.x3d(filepath=path),
    ".usd": lambda path: bpy.ops.wm.usd_import(filepath=path),
    ".usda": lambda path: bpy.ops.wm.usd_import(filepath=path),
    ".usdc": lambda path: bpy.ops.wm.usd_import(filepath=path),
}


def _select_all_objects() -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in bpy.context.scene.objects:
        obj.select_set(True)
    if bpy.ops.object.mode_set.poll():
        bpy.ops.object.mode_set(mode="OBJECT")


def _apply_modifiers() -> None:
    print("Applying modifiers to all mesh objects...")
    for obj in bpy.context.selected_objects:
        if obj.type != "MESH":
            continue
        bpy.context.view_layer.objects.active = obj
        for modifier in list(obj.modifiers):
            try:
                bpy.ops.object.modifier_apply(modifier=modifier.name)
            except Exception as exc:
                print(f"[WARN] Failed to apply modifier '{modifier.name}' on '{obj.name}': {exc}")


def _scale_scene(scale: float) -> None:
    if scale == 1.0:
        return
    print(f"Scaling scene by factor: {scale}")
    bpy.ops.transform.resize(value=(scale, scale, scale))
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)


def _pack_textures() -> None:
    # Helps preserve referenced textures for formats like OBJ/MTL or glTF with external images.
    try:
        if bpy.ops.file.pack_all.poll():
            bpy.ops.file.pack_all()
            print("Packed external resources into the scene.")
    except Exception as exc:
        print(f"[WARN] Could not pack external resources: {exc}")


def _prepare_export_path(output_path: str) -> tuple[str, str | None]:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    if not output_path.lower().endswith(".usdz"):
        with open(output_path, "ab"):
            pass
        os.chmod(output_path, 0o600)
        return output_path, None

    stage_root = os.path.join(os.path.dirname(output_path), "__usdz_stage__")
    if os.path.isdir(stage_root):
        shutil.rmtree(stage_root)
    os.makedirs(stage_root, exist_ok=True)
    export_path = os.path.join(stage_root, f"{os.path.splitext(os.path.basename(output_path))[0]}.usdc")
    with open(export_path, "ab"):
        pass
    os.chmod(export_path, 0o600)
    return export_path, stage_root


def _package_usdz(stage_root: str, export_path: str, output_path: str) -> None:
    temp_output_path = f"{output_path}.tmp"
    if os.path.exists(temp_output_path):
        os.remove(temp_output_path)
    with zipfile.ZipFile(temp_output_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.write(export_path, os.path.basename(export_path))
        for root, _, files in os.walk(stage_root):
            for filename in sorted(files):
                path = os.path.join(root, filename)
                if os.path.abspath(path) == os.path.abspath(export_path):
                    continue
                archive.write(path, os.path.relpath(path, stage_root))
    os.replace(temp_output_path, output_path)
    os.chmod(output_path, 0o600)


def convert(input_path: str, output_path: str, scale: float = 1.0, apply_modifiers: bool = True) -> None:
    overall_start = time.time()
    input_path = os.path.abspath(input_path)
    output_path = os.path.abspath(output_path)
    extension = os.path.splitext(input_path)[1].lower()

    if extension not in SUPPORTED_EXTENSIONS:
        raise RuntimeError(f"Unsupported file extension '{extension}'.")
    if not os.path.exists(input_path):
        raise RuntimeError(f"Input path does not exist: {input_path}")

    # Reset to a clean scene for deterministic conversion.
    stage_start = time.time()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    print(f"TIMING:scene_reset:{time.time() - stage_start:.6f}")

    stage_start = time.time()
    _enable_required_addons(extension)
    print(f"TIMING:addon_enable:{time.time() - stage_start:.6f}")

    importer = IMPORTERS.get(extension)
    if importer is None:
        raise RuntimeError(f"No importer configured for '{extension}'.")

    previous_cwd = os.getcwd()
    input_dir = os.path.dirname(input_path) or previous_cwd

    print(f"Importing '{input_path}' (type: {extension})")
    stage_start = time.time()
    try:
        os.chdir(input_dir)
        importer(input_path)
    finally:
        os.chdir(previous_cwd)
    print(f"TIMING:model_import:{time.time() - stage_start:.6f}")

    if len(bpy.context.scene.objects) == 0:
        raise RuntimeError("No scene objects were imported from the source model.")

    stage_start = time.time()
    _select_all_objects()
    print(f"TIMING:object_selection:{time.time() - stage_start:.6f}")
    if apply_modifiers:
        stage_start = time.time()
        _apply_modifiers()
        print(f"TIMING:modifier_application:{time.time() - stage_start:.6f}")

    stage_start = time.time()
    _scale_scene(scale)
    print(f"TIMING:scene_scaling:{time.time() - stage_start:.6f}")

    stage_start = time.time()
    _pack_textures()
    print(f"TIMING:texture_packing:{time.time() - stage_start:.6f}")

    export_path, stage_root = _prepare_export_path(output_path)

    print(f"Exporting USD to '{export_path}'")
    stage_start = time.time()
    bpy.ops.wm.usd_export(
        filepath=export_path,
        export_materials=True,
        export_textures=True,
        relative_paths=True,
    )
    print(f"TIMING:usdz_export:{time.time() - stage_start:.6f}")

    if stage_root:
        stage_start = time.time()
        _package_usdz(stage_root, export_path, output_path)
        print(f"TIMING:usdz_package:{time.time() - stage_start:.6f}")

    stage_start = time.time()
    if not os.path.exists(output_path):
        raise RuntimeError("Export finished but USDZ file was not created.")
    if os.path.getsize(output_path) < 1024:
        raise RuntimeError(f"Export finished but USDZ output is unexpectedly small ({os.path.getsize(output_path)} bytes).")
    print(f"TIMING:output_verification:{time.time() - stage_start:.6f}")
    print(f"TIMING:total:{time.time() - overall_start:.6f}")

    print("Conversion complete.")


def main() -> int:
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Input model path")
    parser.add_argument("--output", required=True, help="Output USDZ path")
    parser.add_argument("--scale", type=float, default=1.0, help="Scale factor")
    parser.add_argument("--apply-modifiers", action="store_true", help="Apply mesh modifiers")
    parsed = parser.parse_args(args)

    print(
        f"Starting conversion with scale={parsed.scale} apply_modifiers={parsed.apply_modifiers}"
    )
    convert(parsed.input, parsed.output, parsed.scale, parsed.apply_modifiers)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[ERROR] Conversion failed: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
