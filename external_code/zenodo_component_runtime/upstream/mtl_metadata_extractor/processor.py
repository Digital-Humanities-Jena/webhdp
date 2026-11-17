"""
MTL Metadata Extractor Processor
Extracts comprehensive metadata from MTL material files
"""

from pathlib import Path
from typing import Union, Dict, Any, List, Optional, Set, Tuple
import json
import re
from collections import Counter


class MTLMetadataProcessor:
    """Extracts metadata from MTL (material) files associated with OBJ models"""

    def __init__(
        self,
        validate_texture_files: bool = True,
        include_material_analysis: bool = True,
        search_texture_directories: bool = True,
        parse_advanced_properties: bool = True,
        version: str = "unknown",
    ):
        self.validate_texture_files = validate_texture_files
        self.include_material_analysis = include_material_analysis
        self.search_texture_directories = search_texture_directories
        self.parse_advanced_properties = parse_advanced_properties
        self.version = version

        # Define comprehensive MTL property mappings
        self.texture_keys = {
            # Diffuse/Color maps
            "map_Kd": "diffuse_map",
            "map_Ka": "ambient_map",
            "map_Ks": "specular_map",
            # Surface properties
            "map_Ns": "specular_highlight_map",
            "map_d": "alpha_map",
            "map_Tr": "transparency_map",
            # Normal and bump maps
            "map_bump": "bump_map",
            "map_Bump": "bump_map_alt",
            "bump": "bump_map_legacy",
            "norm": "normal_map",
            # Advanced maps
            "disp": "displacement_map",
            "map_refl": "reflection_map",
            "refl": "reflection_map_alt",
            "map_Ke": "emissive_map",
            # PBR extensions
            "map_Pr": "roughness_map",
            "map_Pm": "metallic_map",
            "map_Ps": "sheen_map",
            "map_RMA": "roughness_metallic_ao_map",
        }

        self.material_properties = {
            # Color properties
            "Ka": {"name": "ambient_color", "type": "color"},
            "Kd": {"name": "diffuse_color", "type": "color"},
            "Ks": {"name": "specular_color", "type": "color"},
            "Ke": {"name": "emissive_color", "type": "color"},
            "Tf": {"name": "transmission_filter", "type": "color"},
            # Scalar properties
            "Ns": {"name": "specular_exponent", "type": "float"},
            "Ni": {"name": "optical_density", "type": "float"},
            "d": {"name": "dissolve", "type": "float"},
            "Tr": {"name": "transparency", "type": "float"},
            # PBR properties
            "Pr": {"name": "roughness", "type": "float"},
            "Pm": {"name": "metallic", "type": "float"},
            "Ps": {"name": "sheen", "type": "float"},
            "Pc": {"name": "clearcoat_thickness", "type": "float"},
            "Pcr": {"name": "clearcoat_roughness", "type": "float"},
            # Other properties
            "illum": {"name": "illumination_model", "type": "int"},
            "sharpness": {"name": "reflection_sharpness", "type": "float"},
            "aniso": {"name": "anisotropy", "type": "float"},
            "anisor": {"name": "anisotropy_rotation", "type": "float"},
        }

        self.common_texture_dirs = [
            "textures",
            "texture",
            "tex",
            "maps",
            "materials",
            "images",
            "imgs",
            "../textures",
            "../texture",
        ]

    def process(self, obj_file: Union[str, Path]) -> Dict[str, Any]:
        """
        Extract MTL metadata from OBJ file references

        Args:
            obj_file: Path to OBJ file

        Returns:
            Dict containing comprehensive MTL metadata and analysis
        """
        obj_path = Path(obj_file)

        result = {
            "input_file": str(obj_path),
            "file_exists": obj_path.exists(),
            "success": True,
            "results": {},
            "errors": [],
            "warnings": [],
            "metadata": {
                "processor_version": self.version,
                "parameters_used": {
                    "validate_texture_files": self.validate_texture_files,
                    "include_material_analysis": self.include_material_analysis,
                    "search_texture_directories": self.search_texture_directories,
                    "parse_advanced_properties": self.parse_advanced_properties,
                },
            },
        }

        if not obj_path.exists():
            result["errors"].append(f"OBJ file does not exist: {obj_path}")
            result["success"] = False
            return result

        try:
            # Add basic file info
            result["metadata"]["file_size"] = obj_path.stat().st_size
            result["metadata"]["file_name"] = obj_path.name

            # Extract MTL references from OBJ file
            mtl_libraries = self._extract_mtl_references(obj_path)

            if not mtl_libraries:
                result["warnings"].append("No material libraries found in OBJ file")
                result["results"] = self._create_empty_result()
            else:
                # Process all MTL files
                mtl_metadata = self._process_mtl_files(obj_path, mtl_libraries)
                result["results"] = mtl_metadata

        except Exception as e:
            result["errors"].append(f"Error extracting MTL metadata: {str(e)}")
            result["success"] = False

        # Set final success status
        result["success"] = len(result["errors"]) == 0

        return result

    def _extract_mtl_references(self, obj_path: Path) -> List[str]:
        """Extract MTL library references from OBJ file"""
        mtl_libraries = []

        try:
            with open(obj_path, "r", encoding="utf-8", errors="replace") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if line.startswith("mtllib "):
                        # Extract MTL filename
                        mtl_name = line[7:].strip()  # Remove 'mtllib '
                        if mtl_name:
                            mtl_libraries.append(mtl_name)

        except Exception as e:
            raise Exception(f"Error reading OBJ file: {str(e)}")

        return mtl_libraries

    def _process_mtl_files(self, obj_path: Path, mtl_libraries: List[str]) -> Dict[str, Any]:
        """Process all MTL files referenced by the OBJ"""
        obj_dir = obj_path.parent

        result = {
            "mtl_files": [],
            "all_materials": [],
            "all_textures": [],
            "texture_analysis": {},
            "material_analysis": {},
            "summary": {},
        }

        all_materials = []
        all_textures = set()
        missing_mtl_files = []
        processed_mtl_files = []

        for mtl_filename in mtl_libraries:
            mtl_path = obj_dir / mtl_filename

            if mtl_path.exists():
                try:
                    mtl_data = self._parse_mtl_file(mtl_path, obj_dir)
                    mtl_data["filename"] = mtl_filename
                    mtl_data["file_path"] = str(mtl_path)
                    mtl_data["file_size"] = mtl_path.stat().st_size

                    processed_mtl_files.append(mtl_data)
                    all_materials.extend(mtl_data.get("materials", []))
                    all_textures.update(mtl_data.get("textures", []))

                except Exception as e:
                    missing_mtl_files.append({"filename": mtl_filename, "error": f"Parse error: {str(e)}"})
            else:
                missing_mtl_files.append({"filename": mtl_filename, "error": "File not found"})

        result["mtl_files"] = processed_mtl_files
        result["all_materials"] = all_materials
        result["all_textures"] = sorted(list(all_textures))

        if missing_mtl_files:
            result["missing_mtl_files"] = missing_mtl_files

        # Add analysis if requested
        if self.include_material_analysis:
            result["material_analysis"] = self._analyze_materials(all_materials)
            result["texture_analysis"] = self._analyze_textures(all_textures, obj_dir)

        # Add summary
        result["summary"] = self._create_summary(result)

        return result

    def _parse_mtl_file(self, mtl_path: Path, base_dir: Path) -> Dict[str, Any]:
        """Parse a single MTL file with comprehensive property extraction"""
        mtl_data = {"materials": [], "textures": set(), "parse_errors": [], "line_count": 0, "comment_count": 0}

        current_material = None

        try:
            with open(mtl_path, "r", encoding="utf-8", errors="replace") as f:
                for line_num, line in enumerate(f, 1):
                    mtl_data["line_count"] += 1
                    original_line = line
                    line = line.strip()

                    # Skip empty lines
                    if not line:
                        continue

                    # Handle comments
                    if line.startswith("#"):
                        mtl_data["comment_count"] += 1
                        continue

                    # Split line into parts
                    parts = line.split(None, 1)  # Split on whitespace, max 2 parts
                    if len(parts) < 1:
                        continue

                    key = parts[0]
                    value = parts[1] if len(parts) > 1 else ""

                    try:
                        # Handle new material definition
                        if key == "newmtl":
                            if current_material:
                                mtl_data["materials"].append(current_material)

                            current_material = {
                                "name": value.strip(),
                                "properties": {},
                                "textures": {},
                                "raw_properties": {},
                                "line_number": line_num,
                            }

                        # Handle texture maps
                        elif key in self.texture_keys and current_material:
                            texture_info = self._parse_texture_definition(value, base_dir)
                            texture_key = self.texture_keys[key]
                            current_material["textures"][texture_key] = texture_info

                            if texture_info["filename"]:
                                mtl_data["textures"].add(texture_info["filename"])

                        # Handle material properties
                        elif key in self.material_properties and current_material:
                            prop_info = self.material_properties[key]
                            parsed_value = self._parse_property_value(value, prop_info["type"])
                            current_material["properties"][prop_info["name"]] = parsed_value
                            current_material["raw_properties"][key] = value

                        # Handle unknown properties (store as raw)
                        elif current_material and key not in ["newmtl"]:
                            current_material["raw_properties"][key] = value

                            # Try to guess property type for advanced parsing
                            if self.parse_advanced_properties:
                                parsed_value = self._guess_parse_property(value)
                                if parsed_value is not None:
                                    current_material["properties"][f"unknown_{key}"] = parsed_value

                    except Exception as e:
                        mtl_data["parse_errors"].append(
                            {"line": line_num, "content": original_line.strip(), "error": str(e)}
                        )

            # Add the last material
            if current_material:
                mtl_data["materials"].append(current_material)

        except Exception as e:
            raise Exception(f"Error reading MTL file {mtl_path}: {str(e)}")

        # Convert texture set to sorted list
        mtl_data["textures"] = sorted(list(mtl_data["textures"]))

        return mtl_data

    def _parse_texture_definition(self, texture_line: str, base_dir: Path) -> Dict[str, Any]:
        """Parse texture definition with options and parameters"""
        parts = texture_line.strip().split()

        texture_info = {"filename": "", "exists": False, "full_path": None, "options": {}, "file_size": None}

        if not parts:
            return texture_info

        # Extract options and filename
        filename = parts[-1]  # Filename is typically the last part
        options = parts[:-1]  # Everything before filename are options

        # Parse texture options
        i = 0
        while i < len(options):
            option = options[i]

            # Common texture options
            if option == "-blendu" and i + 1 < len(options):
                texture_info["options"]["blend_u"] = options[i + 1]
                i += 2
            elif option == "-blendv" and i + 1 < len(options):
                texture_info["options"]["blend_v"] = options[i + 1]
                i += 2
            elif option == "-clamp" and i + 1 < len(options):
                texture_info["options"]["clamp"] = options[i + 1]
                i += 2
            elif option == "-mm" and i + 2 < len(options):
                texture_info["options"]["range_min"] = options[i + 1]
                texture_info["options"]["range_max"] = options[i + 2]
                i += 3
            elif option.startswith("-"):
                # Generic option handling
                if i + 1 < len(options) and not options[i + 1].startswith("-"):
                    texture_info["options"][option[1:]] = options[i + 1]
                    i += 2
                else:
                    texture_info["options"][option[1:]] = True
                    i += 1
            else:
                i += 1

        texture_info["filename"] = filename

        # Validate texture file existence if requested
        if self.validate_texture_files and filename:
            texture_path = self._find_texture_file(filename, base_dir)
            if texture_path:
                texture_info["exists"] = True
                texture_info["full_path"] = str(texture_path)
                try:
                    texture_info["file_size"] = texture_path.stat().st_size
                except:
                    pass

        return texture_info

    def _find_texture_file(self, filename: str, base_dir: Path) -> Optional[Path]:
        """Find texture file, searching common directories if needed"""
        # First try relative to MTL file
        texture_path = base_dir / filename
        if texture_path.exists():
            return texture_path

        # Search in common texture directories if enabled
        if self.search_texture_directories:
            for tex_dir in self.common_texture_dirs:
                search_path = base_dir / tex_dir / filename
                if search_path.exists():
                    return search_path

        return None

    def _parse_property_value(self, value: str, prop_type: str) -> Any:
        """Parse property value according to its expected type"""
        value = value.strip()

        try:
            if prop_type == "float":
                return float(value)
            elif prop_type == "int":
                return int(value)
            elif prop_type == "color":
                # Parse RGB color values
                parts = value.split()
                if len(parts) == 3:
                    return [float(parts[0]), float(parts[1]), float(parts[2])]
                elif len(parts) == 1:
                    # Single value for grayscale
                    val = float(parts[0])
                    return [val, val, val]
                else:
                    return value  # Return as string if can't parse
            else:
                return value
        except ValueError:
            return value  # Return as string if parsing fails

    def _guess_parse_property(self, value: str) -> Any:
        """Attempt to parse unknown property values"""
        value = value.strip()

        # Try float
        try:
            return float(value)
        except ValueError:
            pass

        # Try int
        try:
            return int(value)
        except ValueError:
            pass

        # Try color (space-separated floats)
        parts = value.split()
        if len(parts) in [1, 3]:
            try:
                return [float(p) for p in parts]
            except ValueError:
                pass

        return None  # Can't parse

    def _analyze_materials(self, materials: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze material properties and usage patterns"""
        analysis = {
            "total_count": len(materials),
            "property_usage": Counter(),
            "texture_usage": Counter(),
            "illumination_models": Counter(),
            "material_complexity": {},
            "naming_patterns": [],
            "property_statistics": {},
        }

        if not materials:
            return analysis

        material_names = []
        all_property_values = {}

        for material in materials:
            material_names.append(material["name"])

            # Count property usage
            for prop_name in material.get("properties", {}):
                analysis["property_usage"][prop_name] += 1

            # Count texture usage
            for texture_type in material.get("textures", {}):
                analysis["texture_usage"][texture_type] += 1

            # Track illumination models
            illum_model = material.get("properties", {}).get("illumination_model")
            if illum_model is not None:
                analysis["illumination_models"][illum_model] += 1

            # Calculate material complexity
            complexity_score = 0
            complexity_score += len(material.get("properties", {}))
            complexity_score += len(material.get("textures", {})) * 2  # Textures add more complexity

            analysis["material_complexity"][material["name"]] = complexity_score

            # Collect property values for statistics
            for prop_name, prop_value in material.get("properties", {}).items():
                if prop_name not in all_property_values:
                    all_property_values[prop_name] = []

                if isinstance(prop_value, (int, float)):
                    all_property_values[prop_name].append(prop_value)
                elif isinstance(prop_value, list) and all(isinstance(x, (int, float)) for x in prop_value):
                    all_property_values[prop_name].extend(prop_value)

        # Analyze naming patterns
        analysis["naming_patterns"] = self._analyze_naming_patterns(material_names)

        # Calculate property statistics
        for prop_name, values in all_property_values.items():
            if values:
                analysis["property_statistics"][prop_name] = {
                    "count": len(values),
                    "min": min(values),
                    "max": max(values),
                    "average": sum(values) / len(values),
                }

        return analysis

    def _analyze_textures(self, textures: Set[str], base_dir: Path) -> Dict[str, Any]:
        """Analyze texture files and patterns"""
        analysis = {
            "total_count": len(textures),
            "existing_count": 0,
            "missing_count": 0,
            "file_extensions": Counter(),
            "naming_patterns": [],
            "total_size_mb": 0,
            "size_distribution": {},
        }

        if not textures:
            return analysis

        texture_names = []
        sizes = []

        for texture in textures:
            texture_names.append(texture)

            # Extract file extension
            ext = Path(texture).suffix.lower()
            if ext:
                analysis["file_extensions"][ext] += 1

            # Check if file exists and get size
            if self.validate_texture_files:
                texture_path = self._find_texture_file(texture, base_dir)
                if texture_path:
                    analysis["existing_count"] += 1
                    try:
                        size_bytes = texture_path.stat().st_size
                        size_mb = size_bytes / (1024 * 1024)
                        sizes.append(size_mb)
                        analysis["total_size_mb"] += size_mb
                    except:
                        pass
                else:
                    analysis["missing_count"] += 1

        # Analyze naming patterns
        analysis["naming_patterns"] = self._analyze_naming_patterns(texture_names)

        # Size distribution
        if sizes:
            analysis["size_distribution"] = {
                "min_mb": min(sizes),
                "max_mb": max(sizes),
                "average_mb": sum(sizes) / len(sizes),
            }

        return analysis

    def _analyze_naming_patterns(self, names: List[str]) -> List[Dict[str, Any]]:
        """Analyze naming patterns in material/texture names"""
        patterns = []

        if not names:
            return patterns

        # Common prefixes
        prefixes = Counter()
        suffixes = Counter()

        for name in names:
            # Extract potential prefixes (before first underscore or number)
            prefix_match = re.match(r"^([a-zA-Z]+)", name)
            if prefix_match:
                prefixes[prefix_match.group(1)] += 1

            # Extract potential suffixes (after last underscore)
            if "_" in name:
                suffix = name.split("_")[-1]
                suffixes[suffix] += 1

        # Find common patterns
        if prefixes:
            most_common_prefix = prefixes.most_common(1)[0]
            if most_common_prefix[1] > 1:
                patterns.append({"type": "prefix", "pattern": most_common_prefix[0], "count": most_common_prefix[1]})

        if suffixes:
            most_common_suffix = suffixes.most_common(1)[0]
            if most_common_suffix[1] > 1:
                patterns.append({"type": "suffix", "pattern": most_common_suffix[0], "count": most_common_suffix[1]})

        return patterns

    def _create_summary(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Create summary statistics"""
        return {
            "mtl_files_found": len(result.get("mtl_files", [])),
            "mtl_files_missing": len(result.get("missing_mtl_files", [])),
            "total_materials": len(result.get("all_materials", [])),
            "total_textures": len(result.get("all_textures", [])),
            "has_textures": len(result.get("all_textures", [])) > 0,
            "has_materials": len(result.get("all_materials", [])) > 0,
            "texture_validation_enabled": self.validate_texture_files,
            "material_analysis_enabled": self.include_material_analysis,
        }

    def _create_empty_result(self) -> Dict[str, Any]:
        """Create empty result structure"""
        return {
            "mtl_files": [],
            "all_materials": [],
            "all_textures": [],
            "summary": {
                "mtl_files_found": 0,
                "mtl_files_missing": 0,
                "total_materials": 0,
                "total_textures": 0,
                "has_textures": False,
                "has_materials": False,
            },
        }

    def save_results(self, results: Dict[str, Any], output_path: Path) -> None:
        """Save results to JSON file"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
