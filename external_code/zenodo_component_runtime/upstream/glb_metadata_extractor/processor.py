"""
GLB Metadata Extractor Processor
Extracts comprehensive metadata from GLB/glTF 3D model files
"""

import json
import math
from pathlib import Path
from typing import Any, Dict, Union

from pygltflib import GLTF2


class GLBMetadataProcessor:
    """Extracts metadata and statistics from GLB/glTF files"""

    def __init__(
        self,
        include_detailed_primitives: bool = False,
        calculate_volume: bool = True,
        include_extension_details: bool = True,
    ):
        self.include_detailed_primitives = include_detailed_primitives
        self.calculate_volume = calculate_volume
        self.include_extension_details = include_extension_details

    def process(self, glb_file: Union[str, Path]) -> Dict[str, Any]:
        """
        Extract metadata from GLB/glTF file

        Args:
            glb_file: Path to GLB or glTF file

        Returns:
            Dict containing comprehensive metadata and statistics
        """
        glb_path = Path(glb_file)

        result = {
            "input_file": str(glb_path),
            "file_exists": glb_path.exists(),
            "success": True,
            "results": {},
            "errors": [],
            "metadata": {
                "processor_version": "0.1.0",
                "parameters_used": {
                    "include_detailed_primitives": self.include_detailed_primitives,
                    "calculate_volume": self.calculate_volume,
                    "include_extension_details": self.include_extension_details,
                },
            },
        }

        if not glb_path.exists():
            result["errors"].append(f"GLB file does not exist: {glb_path}")
            result["success"] = False
            return result

        try:
            # Add basic file info
            result["metadata"]["file_size"] = glb_path.stat().st_size
            result["metadata"]["file_name"] = glb_path.name
            result["metadata"]["file_extension"] = glb_path.suffix.lower()

            # Extract GLB metadata using your function (enhanced)
            glb_stats = self._extract_glb_metadata(glb_path)
            result["results"] = glb_stats

        except Exception as e:
            result["errors"].append(f"Error processing GLB file: {str(e)}")
            result["success"] = False

        # Set final success status
        result["success"] = len(result["errors"]) == 0

        return result

    def _extract_glb_metadata(self, glb_path: Path) -> Dict[str, Any]:
        """
        Enhanced version of your original function with additional features
        """
        try:
            gltf = GLTF2().load(str(glb_path))
        except Exception as e:
            raise Exception(f"Failed to load GLB file: {str(e)}")

        stats = {
            "file_size": glb_path.stat().st_size,
            "scenes": len(gltf.scenes) if gltf.scenes else 0,
            "nodes": len(gltf.nodes) if gltf.nodes else 0,
            "meshes": len(gltf.meshes) if gltf.meshes else 0,
            "materials": len(gltf.materials) if gltf.materials else 0,
            "textures": len(gltf.textures) if gltf.textures else 0,
            "images": len(gltf.images) if gltf.images else 0,
            "animations": len(gltf.animations) if gltf.animations else 0,
            "skins": len(gltf.skins) if gltf.skins else 0,
            "cameras": len(gltf.cameras) if gltf.cameras else 0,
            "total_primitives": 0,
            "total_vertices": 0,
            "total_indices": 0,
            "bounding_box": {
                "min": [float("inf"), float("inf"), float("inf")],
                "max": [float("-inf"), float("-inf"), float("-inf")],
            },
            "used_extensions": set(),
        }

        # Detailed primitive information (if requested)
        primitive_details = []

        # Process meshes and their primitives
        if gltf.meshes:
            for mesh_idx, mesh in enumerate(gltf.meshes):
                if mesh.primitives:
                    for prim_idx, primitive in enumerate(mesh.primitives):
                        stats["total_primitives"] += 1

                        primitive_info = {
                            "mesh_index": mesh_idx,
                            "primitive_index": prim_idx,
                            "material_index": primitive.material,
                            "mode": primitive.mode if primitive.mode is not None else 4,  # Default TRIANGLES
                        }

                        # Count vertices
                        position_accessor_index = getattr(primitive.attributes, "POSITION", None)
                        if position_accessor_index is not None:
                            accessor = gltf.accessors[position_accessor_index]
                            vertex_count = accessor.count
                            stats["total_vertices"] += vertex_count
                            primitive_info["vertex_count"] = vertex_count

                            # Update bounding box
                            if accessor.min and accessor.max:
                                for i in range(3):
                                    stats["bounding_box"]["min"][i] = min(
                                        stats["bounding_box"]["min"][i], accessor.min[i]
                                    )
                                    stats["bounding_box"]["max"][i] = max(
                                        stats["bounding_box"]["max"][i], accessor.max[i]
                                    )

                        # Count indices
                        if primitive.indices is not None:
                            indices_count = gltf.accessors[primitive.indices].count
                            stats["total_indices"] += indices_count
                            primitive_info["indices_count"] = indices_count

                        # Collect attribute types
                        attributes = []
                        if hasattr(primitive.attributes, "POSITION") and primitive.attributes.POSITION is not None:
                            attributes.append("POSITION")
                        if hasattr(primitive.attributes, "NORMAL") and primitive.attributes.NORMAL is not None:
                            attributes.append("NORMAL")
                        if hasattr(primitive.attributes, "TEXCOORD_0") and primitive.attributes.TEXCOORD_0 is not None:
                            attributes.append("TEXCOORD_0")
                        if hasattr(primitive.attributes, "COLOR_0") and primitive.attributes.COLOR_0 is not None:
                            attributes.append("COLOR_0")
                        primitive_info["attributes"] = attributes

                        if self.include_detailed_primitives:
                            primitive_details.append(primitive_info)

        # Calculate dimensions and additional metrics
        if stats["bounding_box"]["min"][0] != float("inf") and stats["bounding_box"]["max"][0] != float("-inf"):

            dimensions = [stats["bounding_box"]["max"][i] - stats["bounding_box"]["min"][i] for i in range(3)]
            stats["dimensions"] = {"width": dimensions[0], "height": dimensions[1], "depth": dimensions[2]}

            # Calculate volume if requested
            if self.calculate_volume:
                volume = dimensions[0] * dimensions[1] * dimensions[2]
                stats["approximate_volume"] = volume

            # Calculate diagonal (useful for scaling)
            diagonal = math.sqrt(sum(d * d for d in dimensions))
            stats["bounding_box_diagonal"] = diagonal
        else:
            stats["dimensions"] = {"width": 0, "height": 0, "depth": 0}
            if self.calculate_volume:
                stats["approximate_volume"] = 0
            stats["bounding_box_diagonal"] = 0

        # Collect used extensions
        if gltf.extensionsUsed:
            stats["used_extensions"] = set(gltf.extensionsUsed)

        # Extension details if requested
        if self.include_extension_details and gltf.extensionsUsed:
            extension_details = {}
            for ext in gltf.extensionsUsed:
                extension_details[ext] = {
                    "required": ext in (gltf.extensionsRequired or []),
                    "description": self._get_extension_description(ext),
                }
            stats["extension_details"] = extension_details

        # Convert sets to sorted lists for JSON serialization
        stats["used_extensions"] = sorted(list(stats["used_extensions"]))

        # Add detailed primitive information if requested
        if self.include_detailed_primitives:
            stats["primitive_details"] = primitive_details

        # Add summary statistics
        stats["summary"] = {
            "total_triangles": stats["total_indices"] // 3 if stats["total_indices"] > 0 else 0,
            "average_vertices_per_primitive": (
                stats["total_vertices"] / stats["total_primitives"] if stats["total_primitives"] > 0 else 0
            ),
            "has_animations": stats["animations"] > 0,
            "has_textures": stats["textures"] > 0,
            "has_materials": stats["materials"] > 0,
            "complexity_score": self._calculate_complexity_score(stats),
        }

        return stats

    def _get_extension_description(self, extension_name: str) -> str:
        """Get human-readable description of glTF extension"""
        extension_descriptions = {
            "KHR_materials_pbrSpecularGlossiness": "PBR Specular-Glossiness materials",
            "KHR_materials_unlit": "Unlit materials",
            "KHR_draco_mesh_compression": "Draco mesh compression",
            "KHR_texture_transform": "Texture coordinate transformations",
            "KHR_materials_ior": "Index of refraction for materials",
            "KHR_materials_transmission": "Transmission (glass-like) materials",
            "KHR_materials_volume": "Volume materials",
            "KHR_materials_clearcoat": "Clearcoat materials",
            "KHR_materials_sheen": "Sheen materials",
            "KHR_materials_specular": "Specular materials",
            "KHR_lights_punctual": "Punctual lights",
            "KHR_texture_basisu": "Basis Universal texture compression",
            "MSFT_texture_dds": "DirectDraw Surface textures",
            "EXT_texture_webp": "WebP texture format",
            "KHR_mesh_quantization": "Mesh attribute quantization",
        }
        return extension_descriptions.get(extension_name, "Unknown extension")

    def _calculate_complexity_score(self, stats: Dict[str, Any]) -> int:
        """Calculate a complexity score from 1-10 based on model statistics"""
        score = 1

        # Vertex count contribution (0-3 points)
        if stats["total_vertices"] > 100000:
            score += 3
        elif stats["total_vertices"] > 10000:
            score += 2
        elif stats["total_vertices"] > 1000:
            score += 1

        # Texture count contribution (0-2 points)
        if stats["textures"] > 10:
            score += 2
        elif stats["textures"] > 3:
            score += 1

        # Animation contribution (0-2 points)
        if stats["animations"] > 5:
            score += 2
        elif stats["animations"] > 0:
            score += 1

        # Material complexity (0-2 points)
        if stats["materials"] > 10:
            score += 2
        elif stats["materials"] > 3:
            score += 1

        # Extension usage (0-1 point)
        if len(stats["used_extensions"]) > 2:
            score += 1

        return min(score, 10)  # Cap at 10

    def save_results(self, results: Dict[str, Any], output_path: Path) -> None:
        """Save results to JSON file"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
