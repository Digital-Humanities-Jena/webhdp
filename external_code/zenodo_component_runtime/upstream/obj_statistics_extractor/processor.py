"""
OBJ Statistics Extractor Processor
Extracts comprehensive statistics from OBJ 3D model files
"""

from pathlib import Path
from typing import Union, Dict, Any, List, Optional
import json
import math


class OBJStatisticsProcessor:
    """Extracts comprehensive statistics from OBJ files"""

    def __init__(
        self,
        calculate_detailed_geometry: bool = True,
        include_material_analysis: bool = True,
        compute_mesh_quality: bool = False,
        progress_reporting: bool = True,
    ):
        self.calculate_detailed_geometry = calculate_detailed_geometry
        self.include_material_analysis = include_material_analysis
        self.compute_mesh_quality = compute_mesh_quality
        self.progress_reporting = progress_reporting

    def process(self, obj_file: Union[str, Path]) -> Dict[str, Any]:
        """
        Extract statistics from OBJ file

        Args:
            obj_file: Path to OBJ file

        Returns:
            Dict containing comprehensive statistics and analysis
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
                "processor_version": "1.0.0",
                "parameters_used": {
                    "calculate_detailed_geometry": self.calculate_detailed_geometry,
                    "include_material_analysis": self.include_material_analysis,
                    "compute_mesh_quality": self.compute_mesh_quality,
                    "progress_reporting": self.progress_reporting,
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

            # Extract statistics using optimized function
            statistics = self._extract_obj_statistics_optimized(obj_path)
            result["results"] = statistics

        except Exception as e:
            result["errors"].append(f"Error extracting OBJ statistics: {str(e)}")
            result["success"] = False

        # Set final success status
        result["success"] = len(result["errors"]) == 0

        return result

    def _extract_obj_statistics_optimized(self, obj_path: Path) -> Dict[str, Any]:
        """
        Optimized version of the original function with enhanced features
        """
        # Initialize comprehensive statistics structure
        stats = {
            # Basic geometric counts
            "geometric_vertices": 0,
            "texture_coordinates": 0,
            "vertex_normals": 0,
            "parameter_space_vertices": 0,
            "faces": 0,
            "lines": 0,
            "points": 0,
            # Face type breakdown
            "triangular_faces": 0,
            "quad_faces": 0,
            "n_gon_faces": 0,
            "face_type_distribution": {},
            # Object and group structure
            "objects": 0,
            "groups": 0,
            "smoothing_groups": 0,
            "object_names": set(),
            "group_names": set(),
            # Material information
            "material_libraries": [],
            "material_names": set(),
            "material_usage_count": {},
            # File structure
            "comments": 0,
            "blank_lines": 0,
            "total_lines": 0,
            "unknown_commands": set(),
            # Geometric analysis
            "bounding_box": {
                "min": [float("inf"), float("inf"), float("inf")],
                "max": [float("-inf"), float("-inf"), float("-inf")],
            },
            "dimensions": {"width": 0, "height": 0, "depth": 0},
            "center_point": [0, 0, 0],
            # Advanced calculations (if enabled)
            "total_face_area": 0,
            "estimated_volume": 0,
            "surface_area_to_volume_ratio": 0,
        }

        # Working data
        vertices = []
        current_object = "default"
        current_group = "default"
        current_material = None
        line_count = 0
        face_vertices_for_quality = []

        # Progress tracking
        file_size = obj_path.stat().st_size
        bytes_processed = 0
        last_progress = 0

        try:
            with open(obj_path, "r", encoding="utf-8", errors="replace") as file:
                for line in file:
                    line_count += 1
                    stats["total_lines"] += 1
                    bytes_processed += len(line.encode("utf-8"))

                    # Progress reporting for large files
                    if self.progress_reporting and file_size > 1024 * 1024:  # > 1MB
                        progress = int((bytes_processed / file_size) * 100)
                        if progress >= last_progress + 10:  # Report every 10%
                            last_progress = progress

                    original_line = line
                    line = line.strip()

                    # Count blank lines
                    if not line:
                        stats["blank_lines"] += 1
                        continue

                    # Split into parts
                    parts = line.split()
                    if not parts:
                        continue

                    command = parts[0]

                    # Process different OBJ commands
                    if command == "v":
                        # Geometric vertex
                        if len(parts) >= 4:
                            vertex = self._parse_vertex(parts[1:4])
                            if vertex:
                                vertices.append(vertex)
                                self._update_bounding_box(stats, vertex)
                                stats["geometric_vertices"] += 1

                    elif command == "vt":
                        # Texture coordinate
                        stats["texture_coordinates"] += 1

                    elif command == "vn":
                        # Vertex normal
                        stats["vertex_normals"] += 1

                    elif command == "vp":
                        # Parameter space vertex
                        stats["parameter_space_vertices"] += 1

                    elif command == "f":
                        # Face
                        stats["faces"] += 1
                        face_data = self._process_face(parts[1:], vertices, stats)

                        if self.compute_mesh_quality and face_data:
                            face_vertices_for_quality.append(face_data)

                        # Track material usage
                        if current_material and self.include_material_analysis:
                            stats["material_usage_count"][current_material] = (
                                stats["material_usage_count"].get(current_material, 0) + 1
                            )

                    elif command == "l":
                        # Line
                        stats["lines"] += 1

                    elif command == "p":
                        # Point
                        stats["points"] += 1

                    elif command == "o":
                        # Object
                        stats["objects"] += 1
                        current_object = " ".join(parts[1:]) if len(parts) > 1 else f"object_{stats['objects']}"
                        stats["object_names"].add(current_object)

                    elif command == "g":
                        # Group
                        stats["groups"] += 1
                        current_group = " ".join(parts[1:]) if len(parts) > 1 else f"group_{stats['groups']}"
                        stats["group_names"].add(current_group)

                    elif command == "s":
                        # Smoothing group
                        stats["smoothing_groups"] += 1

                    elif command == "mtllib" and self.include_material_analysis:
                        # Material library
                        if len(parts) > 1:
                            mtllib_name = " ".join(parts[1:])
                            stats["material_libraries"].append(mtllib_name)

                    elif command == "usemtl" and self.include_material_analysis:
                        # Use material
                        if len(parts) > 1:
                            current_material = " ".join(parts[1:])
                            stats["material_names"].add(current_material)

                    elif command == "#":
                        # Comment
                        stats["comments"] += 1

                    else:
                        # Unknown command
                        stats["unknown_commands"].add(command)

            # Post-processing calculations
            self._finalize_statistics(stats, vertices, face_vertices_for_quality)

        except UnicodeDecodeError as e:
            raise Exception(f"File encoding error: {str(e)}")
        except Exception as e:
            raise Exception(f"Error processing OBJ file: {str(e)}")

        return stats

    def _parse_vertex(self, coord_parts: List[str]) -> Optional[List[float]]:
        """Parse vertex coordinates with error handling"""
        try:
            return [float(coord_parts[0]), float(coord_parts[1]), float(coord_parts[2])]
        except (ValueError, IndexError):
            return None

    def _update_bounding_box(self, stats: Dict[str, Any], vertex: List[float]):
        """Update bounding box with new vertex"""
        for i in range(3):
            stats["bounding_box"]["min"][i] = min(stats["bounding_box"]["min"][i], vertex[i])
            stats["bounding_box"]["max"][i] = max(stats["bounding_box"]["max"][i], vertex[i])

    def _process_face(
        self, face_parts: List[str], vertices: List[List[float]], stats: Dict[str, Any]
    ) -> Optional[List[List[float]]]:
        """Process face definition and update statistics"""
        try:
            face_vertices = []
            vertex_count = len(face_parts)

            # Update face type counts
            if vertex_count == 3:
                stats["triangular_faces"] += 1
            elif vertex_count == 4:
                stats["quad_faces"] += 1
            else:
                stats["n_gon_faces"] += 1

            # Track face type distribution
            face_type = f"{vertex_count}-gon"
            stats["face_type_distribution"][face_type] = stats["face_type_distribution"].get(face_type, 0) + 1

            # Extract vertex positions for area calculation
            if self.calculate_detailed_geometry:
                for vert_ref in face_parts:
                    try:
                        # Parse vertex reference (can be v, v/vt, v/vt/vn, or v//vn)
                        idx = int(vert_ref.split("/")[0]) - 1  # OBJ uses 1-based indexing
                        if 0 <= idx < len(vertices):
                            face_vertices.append(vertices[idx])
                    except (ValueError, IndexError):
                        continue

                # Calculate face area if we have enough vertices
                if len(face_vertices) >= 3:
                    area = self._calculate_face_area(face_vertices)
                    stats["total_face_area"] += area

                return face_vertices

        except Exception:
            # Don't fail the entire process for one bad face
            pass

        return None

    def _calculate_face_area(self, face_vertices: List[List[float]]) -> float:
        """Calculate face area using cross product (works for triangles and convex polygons)"""
        if len(face_vertices) < 3:
            return 0

        try:
            # For triangles, use cross product
            if len(face_vertices) == 3:
                a, b, c = face_vertices
                vector1 = [b[i] - a[i] for i in range(3)]
                vector2 = [c[i] - a[i] for i in range(3)]
                cross_product = [
                    vector1[1] * vector2[2] - vector1[2] * vector2[1],
                    vector1[2] * vector2[0] - vector1[0] * vector2[2],
                    vector1[0] * vector2[1] - vector1[1] * vector2[0],
                ]
                return 0.5 * math.sqrt(sum(x * x for x in cross_product))

            # For polygons, triangulate and sum areas
            else:
                total_area = 0
                for i in range(1, len(face_vertices) - 1):
                    triangle = [face_vertices[0], face_vertices[i], face_vertices[i + 1]]
                    total_area += self._calculate_face_area(triangle)
                return total_area

        except Exception:
            return 0

    def _finalize_statistics(
        self, stats: Dict[str, Any], vertices: List[List[float]], face_vertices_for_quality: List[List[List[float]]]
    ):
        """Finalize calculations and add derived statistics"""

        # Calculate dimensions and center point
        if stats["geometric_vertices"] > 0:
            for i, dimension in enumerate(["width", "height", "depth"]):
                stats["dimensions"][dimension] = stats["bounding_box"]["max"][i] - stats["bounding_box"]["min"][i]

            # Calculate center point
            stats["center_point"] = [
                (stats["bounding_box"]["min"][i] + stats["bounding_box"]["max"][i]) / 2 for i in range(3)
            ]

            # Estimate volume (bounding box volume)
            stats["estimated_volume"] = (
                stats["dimensions"]["width"] * stats["dimensions"]["height"] * stats["dimensions"]["depth"]
            )

            # Surface area to volume ratio
            if stats["estimated_volume"] > 0:
                stats["surface_area_to_volume_ratio"] = stats["total_face_area"] / stats["estimated_volume"]

        # Convert sets to sorted lists for JSON serialization
        stats["material_names"] = sorted(list(stats["material_names"]))
        stats["object_names"] = sorted(list(stats["object_names"]))
        stats["group_names"] = sorted(list(stats["group_names"]))
        stats["unknown_commands"] = sorted(list(stats["unknown_commands"]))

        # Add mesh quality metrics if requested
        if self.compute_mesh_quality:
            stats["mesh_quality"] = self._calculate_mesh_quality(face_vertices_for_quality)

        # Add summary statistics
        stats["summary"] = {
            "total_elements": (
                stats["geometric_vertices"] + stats["faces"] + stats["texture_coordinates"] + stats["vertex_normals"]
            ),
            "has_textures": stats["texture_coordinates"] > 0,
            "has_normals": stats["vertex_normals"] > 0,
            "has_materials": len(stats["material_names"]) > 0,
            "is_triangulated": stats["triangular_faces"] == stats["faces"],
            "complexity_score": self._calculate_complexity_score(stats),
            "file_efficiency": self._calculate_file_efficiency(stats),
        }

    def _calculate_mesh_quality(self, face_vertices_for_quality: List[List[List[float]]]) -> Dict[str, Any]:
        """Calculate mesh quality metrics"""
        quality_metrics = {
            "degenerate_faces": 0,
            "small_faces": 0,
            "aspect_ratio_stats": {"min": None, "max": None, "average": None},
            "edge_length_stats": {"min": None, "max": None, "average": None},
        }

        if not face_vertices_for_quality:
            return quality_metrics

        aspect_ratios = []
        edge_lengths = []

        for face_vertices in face_vertices_for_quality:
            if len(face_vertices) < 3:
                quality_metrics["degenerate_faces"] += 1
                continue

            # Calculate edge lengths
            face_edge_lengths = []
            for i in range(len(face_vertices)):
                next_i = (i + 1) % len(face_vertices)
                edge_length = math.sqrt(sum((face_vertices[i][j] - face_vertices[next_i][j]) ** 2 for j in range(3)))
                face_edge_lengths.append(edge_length)
                edge_lengths.append(edge_length)

            # Check for small faces (very small edge lengths)
            if any(length < 1e-6 for length in face_edge_lengths):
                quality_metrics["small_faces"] += 1

            # Calculate aspect ratio for triangles
            if len(face_vertices) == 3 and len(face_edge_lengths) == 3:
                max_edge = max(face_edge_lengths)
                min_edge = min(face_edge_lengths)
                if min_edge > 0:
                    aspect_ratio = max_edge / min_edge
                    aspect_ratios.append(aspect_ratio)

        # Calculate statistics
        if aspect_ratios:
            quality_metrics["aspect_ratio_stats"] = {
                "min": min(aspect_ratios),
                "max": max(aspect_ratios),
                "average": sum(aspect_ratios) / len(aspect_ratios),
            }

        if edge_lengths:
            quality_metrics["edge_length_stats"] = {
                "min": min(edge_lengths),
                "max": max(edge_lengths),
                "average": sum(edge_lengths) / len(edge_lengths),
            }

        return quality_metrics

    def _calculate_complexity_score(self, stats: Dict[str, Any]) -> int:
        """Calculate a complexity score from 1-10 based on model statistics"""
        score = 1

        # Vertex count contribution (0-3 points)
        if stats["geometric_vertices"] > 100000:
            score += 3
        elif stats["geometric_vertices"] > 10000:
            score += 2
        elif stats["geometric_vertices"] > 1000:
            score += 1

        # Face count contribution (0-2 points)
        if stats["faces"] > 50000:
            score += 2
        elif stats["faces"] > 5000:
            score += 1

        # Structure complexity (0-2 points)
        if stats["objects"] > 10 or stats["groups"] > 10:
            score += 2
        elif stats["objects"] > 3 or stats["groups"] > 3:
            score += 1

        # Material complexity (0-2 points)
        if len(stats["material_names"]) > 10:
            score += 2
        elif len(stats["material_names"]) > 3:
            score += 1

        # N-gon penalty (0-1 point)
        if stats["n_gon_faces"] > stats["faces"] * 0.1:  # More than 10% n-gons
            score += 1

        return min(score, 10)  # Cap at 10

    def _calculate_file_efficiency(self, stats: Dict[str, Any]) -> float:
        """Calculate file efficiency (useful content vs total lines)"""
        useful_lines = (
            stats["geometric_vertices"]
            + stats["faces"]
            + stats["texture_coordinates"]
            + stats["vertex_normals"]
            + stats["objects"]
            + stats["groups"]
        )

        if stats["total_lines"] > 0:
            return useful_lines / stats["total_lines"]
        return 0

    def save_results(self, results: Dict[str, Any], output_path: Path) -> None:
        """Save results to JSON file"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
