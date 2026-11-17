"""
OBJ to GLB Converter Processor - Enhanced Version
Converts OBJ 3D model files to GLB format using Blender with flexible output control
"""

from pathlib import Path
from typing import Union, Dict, Any, List, Optional, Tuple
import json
import subprocess
import sys
import tempfile
import shutil
import time
from datetime import datetime


class OBJToGLBProcessor:
    """Enhanced OBJ to GLB converter with batch processing and flexible output control"""

    def __init__(
        self,
        batch_mode: bool = False,
        save_in_input_dir: bool = False,
        search_textures: bool = True,
        ignore_missing_textures: bool = False,
        texture_search_extensions: str = ".jpg,.jpeg,.png,.tga,.bmp,.tiff",
        include_materials: bool = True,
        optimize_geometry: bool = False,
        recursive_search: bool = False,
        version: str = "undefined",
    ):
        self.batch_mode = batch_mode
        self.save_in_input_dir = save_in_input_dir
        self.search_textures = search_textures
        self.ignore_missing_textures = ignore_missing_textures
        if isinstance(texture_search_extensions, str):
            self.texture_extensions = [ext.strip() for ext in texture_search_extensions.split(",")]
        else:
            self.texture_extensions = texture_search_extensions
        self.include_materials = include_materials
        self.optimize_geometry = optimize_geometry
        self.recursive_search = recursive_search
        self.version = version

        # Find Blender executable
        self.blender_executable = self._find_blender_executable()

    def process_single_file(
        self,
        obj_file: Union[str, Path],
        glb_output_path: Optional[Union[str, Path]] = None,
        report_output_path: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        """
        Convert single OBJ file to GLB format

        Args:
            obj_file: Path to OBJ file to convert
            glb_output_path: Explicit path for GLB output (optional if save_in_input_dir=True)
            report_output_path: Path for JSON report output

        Returns:
            Dict containing conversion results and detailed report
        """
        start_time = time.time()
        obj_path = Path(obj_file)

        result = {
            "input_file": str(obj_path),
            "file_exists": obj_path.exists(),
            "success": True,
            "results": {},
            "errors": [],
            "metadata": {
                "processor_version": self.version,
                "processing_mode": "single_file",
                "start_time": datetime.now().isoformat(),
                "parameters_used": {
                    "save_in_input_dir": self.save_in_input_dir,
                    "search_textures": self.search_textures,
                    "ignore_missing_textures": self.ignore_missing_textures,
                    "texture_extensions": self.texture_extensions,
                    "include_materials": self.include_materials,
                    "optimize_geometry": self.optimize_geometry,
                },
            },
        }

        if not obj_path.exists():
            result["errors"].append(f"OBJ file does not exist: {obj_path}")
            result["success"] = False
            return result

        if not self.blender_executable:
            result["errors"].append("Blender executable not found. Please install Blender.")
            result["success"] = False
            return result

        try:
            # Determine GLB output path
            if glb_output_path:
                final_glb_path = Path(glb_output_path)
            elif self.save_in_input_dir:
                final_glb_path = obj_path.parent / f"{obj_path.stem}.glb"
            else:
                result["errors"].append("No GLB output path specified and save_in_input_dir is False")
                result["success"] = False
                return result

            # Add basic file info
            result["metadata"]["file_size"] = obj_path.stat().st_size
            result["metadata"]["file_name"] = obj_path.name
            result["metadata"]["blender_executable"] = str(self.blender_executable)
            result["metadata"]["glb_output_path"] = str(final_glb_path)

            # Perform conversion
            conversion_result = self._convert_obj_to_glb(obj_path, final_glb_path)
            result["results"] = conversion_result

            # Calculate processing time
            processing_time = time.time() - start_time
            result["metadata"]["processing_time_seconds"] = round(processing_time, 2)
            result["results"]["processing_time_seconds"] = round(processing_time, 2)

        except Exception as e:
            result["errors"].append(f"Error during conversion: {str(e)}")
            result["success"] = False

        # Set final success status
        result["success"] = len(result["errors"]) == 0 and result["results"].get("conversion_successful", False)

        # Save report if path provided
        if report_output_path:
            self.save_results(result, Path(report_output_path))

        return result

    def process_batch(
        self,
        input_dir: Union[str, Path],
        output_dir: Union[str, Path],
        batch_report_path: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        """
        Process all OBJ files in a directory

        Args:
            input_dir: Directory containing OBJ files
            output_dir: Directory for output files
            batch_report_path: Path for batch summary report

        Returns:
            Dict containing batch processing results
        """
        start_time = time.time()
        input_path = Path(input_dir)
        output_path = Path(output_dir)

        # Ensure output directory exists
        output_path.mkdir(parents=True, exist_ok=True)

        batch_result = {
            "input_directory": str(input_path),
            "output_directory": str(output_path),
            "success": True,
            "files_processed": 0,
            "files_successful": 0,
            "files_failed": 0,
            "errors": [],
            "file_results": [],
            "metadata": {
                "processor_version": "2.0.0",
                "processing_mode": "batch",
                "start_time": datetime.now().isoformat(),
                "recursive_search": self.recursive_search,
                "parameters_used": {
                    "save_in_input_dir": self.save_in_input_dir,
                    "search_textures": self.search_textures,
                    "ignore_missing_textures": self.ignore_missing_textures,
                    "texture_extensions": self.texture_extensions,
                    "include_materials": self.include_materials,
                    "optimize_geometry": self.optimize_geometry,
                },
            },
        }

        if not input_path.exists():
            batch_result["errors"].append(f"Input directory does not exist: {input_path}")
            batch_result["success"] = False
            return batch_result

        try:
            # Find all OBJ files
            if self.recursive_search:
                obj_files = list(input_path.rglob("*.obj"))
            else:
                obj_files = list(input_path.glob("*.obj"))

            if not obj_files:
                batch_result["errors"].append(f"No OBJ files found in {input_path}")
                batch_result["success"] = False
                return batch_result

            batch_result["metadata"]["obj_files_found"] = len(obj_files)

            # Process each file
            for obj_file in obj_files:
                try:
                    # Determine relative path for output structure
                    rel_path = obj_file.relative_to(input_path)

                    # Create output paths
                    if self.save_in_input_dir:
                        glb_output = obj_file.parent / f"{obj_file.stem}.glb"
                    else:
                        glb_output = output_path / rel_path.parent / f"{obj_file.stem}.glb"
                        glb_output.parent.mkdir(parents=True, exist_ok=True)

                    report_output = output_path / rel_path.parent / f"{obj_file.stem}_conversion_report.json"
                    report_output.parent.mkdir(parents=True, exist_ok=True)

                    # Process single file
                    file_result = self.process_single_file(obj_file, glb_output, report_output)

                    batch_result["file_results"].append(
                        {
                            "input_file": str(obj_file),
                            "relative_path": str(rel_path),
                            "glb_output": str(glb_output),
                            "report_output": str(report_output),
                            "success": file_result["success"],
                            "errors": file_result["errors"],
                        }
                    )

                    batch_result["files_processed"] += 1
                    if file_result["success"]:
                        batch_result["files_successful"] += 1
                    else:
                        batch_result["files_failed"] += 1

                except Exception as e:
                    error_msg = f"Error processing {obj_file}: {str(e)}"
                    batch_result["errors"].append(error_msg)
                    batch_result["files_failed"] += 1
                    batch_result["file_results"].append(
                        {"input_file": str(obj_file), "success": False, "errors": [error_msg]}
                    )

        except Exception as e:
            batch_result["errors"].append(f"Batch processing error: {str(e)}")
            batch_result["success"] = False

        # Calculate final statistics
        processing_time = time.time() - start_time
        batch_result["metadata"]["processing_time_seconds"] = round(processing_time, 2)
        batch_result["success"] = batch_result["files_failed"] == 0 and len(batch_result["errors"]) == 0

        # Save batch report if path provided
        if batch_report_path:
            self.save_results(batch_result, Path(batch_report_path))

        return batch_result

    def _find_blender_executable(self) -> Optional[Path]:
        """Find Blender executable on the system"""
        possible_names = ["blender", "blender.exe"]
        possible_paths = [
            Path("/usr/bin"),
            Path("/usr/local/bin"),
            Path("/opt/blender"),
            Path("/Applications/Blender.app/Contents/MacOS"),
            Path("C:/Program Files/Blender Foundation"),
            Path("C:/Program Files (x86)/Blender Foundation"),
        ]

        # First check if blender is in PATH
        try:
            result = subprocess.run(["which", "blender"], capture_output=True, text=True)
            if result.returncode == 0:
                return Path(result.stdout.strip())
        except:
            try:
                result = subprocess.run(["where", "blender"], capture_output=True, text=True)
                if result.returncode == 0:
                    return Path(result.stdout.strip().split("\n")[0])
            except:
                pass

        # Check common installation paths
        for path in possible_paths:
            if path.exists():
                for name in possible_names:
                    blender_path = path / name
                    if blender_path.exists() and blender_path.is_file():
                        return blender_path

                    # Check in subdirectories
                    for subdir in path.iterdir():
                        if subdir.is_dir():
                            blender_path = subdir / name
                            if blender_path.exists():
                                return blender_path

        return None

    def _convert_obj_to_glb(self, obj_path: Path, glb_output_path: Path) -> Dict[str, Any]:
        """Convert OBJ to GLB using Blender in headless mode"""

        # Ensure output directory exists
        glb_output_path.parent.mkdir(parents=True, exist_ok=True)

        # Create temporary directory for processing
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Copy OBJ file to temp directory
            temp_obj = temp_path / obj_path.name
            shutil.copy2(obj_path, temp_obj)

            # Copy MTL file if it exists
            mtl_path = obj_path.with_suffix(".mtl")
            temp_mtl = None
            if mtl_path.exists():
                temp_mtl = temp_path / mtl_path.name
                shutil.copy2(mtl_path, temp_mtl)

            # Find and copy textures if enabled
            found_textures = []
            missing_textures = []

            if self.search_textures:
                found_textures, missing_textures = self._find_and_copy_textures(obj_path, temp_path)

            # Create Blender script
            blender_script = self._create_blender_script(temp_obj, temp_path, found_textures, missing_textures)

            script_path = temp_path / "conversion_script.py"
            with open(script_path, "w") as f:
                f.write(blender_script)

            # Run Blender
            temp_glb_output = temp_path / f"{obj_path.stem}.glb"

            blender_cmd = [
                str(self.blender_executable),
                "--background",
                "--python",
                str(script_path),
                "--",
                str(temp_obj),
                str(temp_glb_output),
            ]

            try:
                result = subprocess.run(blender_cmd, capture_output=True, text=True, timeout=300, cwd=temp_path)

                # Check if conversion was successful
                conversion_successful = temp_glb_output.exists() and temp_glb_output.stat().st_size > 0

                # Copy GLB file to final output location
                if conversion_successful:
                    shutil.copy2(temp_glb_output, glb_output_path)

                return {
                    "conversion_successful": conversion_successful,
                    "output_file": str(glb_output_path) if conversion_successful else None,
                    "output_file_size": (
                        glb_output_path.stat().st_size if conversion_successful and glb_output_path.exists() else 0
                    ),
                    "blender_exit_code": result.returncode,
                    "blender_stdout": result.stdout,
                    "blender_stderr": result.stderr,
                    "textures_found": len(found_textures),
                    "textures_missing": len(missing_textures),
                    "found_texture_files": [str(t) for t in found_textures],
                    "missing_texture_files": missing_textures,
                    "materials_processed": temp_mtl is not None,
                }

            except subprocess.TimeoutExpired:
                return {
                    "conversion_successful": False,
                    "error": "Blender conversion timed out after 300 seconds",
                    "timeout": True,
                }
            except Exception as e:
                return {"conversion_successful": False, "error": f"Blender execution failed: {str(e)}"}

    def _find_and_copy_textures(self, obj_path: Path, temp_path: Path) -> Tuple[List[Path], List[str]]:
        """Find and copy texture files by reading the MTL file."""
        found_textures = []
        missing_textures = []

        # Find the MTL file associated with the OBJ file
        mtl_path = obj_path.with_suffix(".mtl")
        if not mtl_path.exists():
            return [], []  # No MTL file, so no textures to process

        search_dir = obj_path.parent
        texture_filenames = set()  # Use a set to avoid duplicate parsing

        # 1. Read the MTL file to discover all referenced texture files
        try:
            with open(mtl_path, "r") as f:
                for line in f:
                    parts = line.strip().split()
                    if not parts:
                        continue

                    # Look for common texture map directives
                    if parts[0] in ["map_Kd", "map_Ks", "map_Ka", "map_d", "map_bump", "bump", "norm"]:
                        # The texture path is the rest of the line
                        texture_path_str = " ".join(parts[1:])
                        if texture_path_str:
                            texture_filenames.add(texture_path_str)
        except Exception:
            # If MTL file is unreadable it does not proceed with textures.
            return [], []

        # 2. Search for and copy the discovered texture files
        for texture_filename in texture_filenames:
            # The path in the MTL can be relative, e.g., "textures/my_texture.jpg"
            # The full path is built relative to the OBJ's location
            potential_path = (search_dir / texture_filename).resolve()

            if potential_path.exists():
                # Re-create the same directory structure in the temp folder
                # e.g., if path is "textures/my_texture.jpg", create "temp/textures/"
                temp_dest_path = temp_path / texture_filename
                temp_dest_path.parent.mkdir(parents=True, exist_ok=True)

                shutil.copy2(potential_path, temp_dest_path)
                found_textures.append(potential_path)
            else:
                missing_textures.append(texture_filename)

        return found_textures, missing_textures

    def _create_blender_script(
        self, obj_path: Path, output_dir: Path, found_textures: List[Path], missing_textures: List[str]
    ) -> str:
        """Create a robust Blender Python script for conversion."""

        script = f'''
import bpy
import sys
from pathlib import Path

def convert_obj_to_glb():
    """Convert OBJ to GLB, automatically finding textures."""

    obj_filepath = Path(r"{obj_path}")
    output_dir = Path(r"{output_dir}")
    include_materials = {self.include_materials}
    optimize_geometry = {self.optimize_geometry}

    try:
        # Clear existing objects
        bpy.ops.object.select_all(action='SELECT')
        if bpy.context.selected_objects:
            bpy.ops.object.delete()

        # Import the OBJ
        bpy.ops.wm.obj_import(filepath=str(obj_filepath))

        # --- Robust Texture Handling ---
        # Use Blender's built-in operator to find all missing files.
        # Since the script runs from the temp directory where the textures are copied,
        # it will find them automatically, preserving subdirectories.
        bpy.ops.file.find_missing_files(directory=str(output_dir))

        # Optimize geometry if requested
        if optimize_geometry:
            for obj in bpy.context.selected_objects:
                if obj.type == 'MESH':
                    bpy.context.view_layer.objects.active = obj
                    bpy.ops.object.mode_set(mode='EDIT')
                    bpy.ops.mesh.remove_doubles()
                    bpy.ops.mesh.normals_make_consistent(inside=False)
                    bpy.ops.object.mode_set(mode='OBJECT')

        # Set the output file path
        glb_filepath = output_dir / f"{{obj_filepath.stem}}.glb"

        # Export to GLB, ensuring textures are packed into the file
        bpy.ops.export_scene.gltf(
            filepath=str(glb_filepath),
            export_format="GLB",
            use_selection=True,
            export_materials="EXPORT" if include_materials else "NONE"
        )

        print(f"Conversion successful: {{glb_filepath}}")

    except Exception as e:
        print(f"Conversion Error (OBJ -> GLB): {{obj_filepath}} (Reason: {{str(e)}})")
        sys.exit(1)

# Run conversion
if __name__ == "__main__":
    convert_obj_to_glb()
'''
        return script

    def save_results(self, results: Dict[str, Any], output_path: Path) -> None:
        """Save results to JSON file"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
