"""Produce an ordered detail ladder while retaining geometry outside the error budget."""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def surface(obj, mesh):
    mesh.calc_loop_triangles()
    vertices = [obj.matrix_world @ vertex.co for vertex in mesh.vertices]
    triangles = [tuple(triangle.vertices) for triangle in mesh.loop_triangles]
    if not triangles or not all(math.isfinite(component) for vertex in vertices for component in vertex):
        raise ValueError('The GLB must contain finite, non-empty triangle surfaces.')
    tree = BVHTree.FromPolygons(vertices, triangles, all_triangles=True)
    if not any((vertices[b] - vertices[a]).cross(vertices[c] - vertices[a]).length > 0 for a, b, c in triangles):
        raise ValueError('Degenerate surfaces cannot be simplified.')
    points = list(vertices)
    for a, b, c in triangles:
        points.extend(((vertices[a] + vertices[b]) / 2, (vertices[b] + vertices[c]) / 2,
                       (vertices[c] + vertices[a]) / 2, (vertices[a] + vertices[b] + vertices[c]) / 3))
    return tree, points, len(triangles)


def sampled_error(points, tree):
    return max((hit[3] if hit and hit[3] is not None else float('inf'))
               for hit in (tree.find_nearest(point) for point in points))


def material_areas(obj, mesh):
    """Keep overlapping surfaces and small material groups in the acceptance guard."""
    mesh.calc_loop_triangles()
    areas = {}
    for triangle in mesh.loop_triangles:
        a, b, c = [obj.matrix_world @ mesh.vertices[index].co for index in triangle.vertices]
        key = triangle.material_index
        areas[key] = areas.get(key, 0.0) + (b - a).cross(c - a).length * 0.5
    return areas


def generate(source, output, ratio, max_error):
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(source))
    objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    if not objects:
        raise ValueError('No mesh surfaces were imported.')
    originals = {}
    accepted_errors = {}
    total = 0
    for obj in objects:
        obj.data = obj.data.copy()
        tree, points, triangles = surface(obj, obj.data)
        low = Vector(tuple(min(point[axis] for point in points) for axis in range(3)))
        high = Vector(tuple(max(point[axis] for point in points) for axis in range(3)))
        diagonal = (high - low).length
        originals[obj.name] = (tree, points, triangles, diagonal, material_areas(obj, obj.data))
        accepted_errors[obj.name] = 0.0
        total += triangles
    report = {'source_triangles': total, 'levels': {}, 'blender_version': bpy.app.version_string,
              'method': 'guarded_decimation', 'max_material_area_change': 0.025,
              'generated_levels': ['high', 'medium', 'low']}
    for level, target_ratio in (('high', math.sqrt(ratio)), ('medium', ratio), ('low', ratio * ratio)):
        checks = []
        triangles_after = 0
        for obj in objects:
            source_tree, source_points, source_triangles, diagonal, source_areas = originals[obj.name]
            _, _, before = surface(obj, obj.data)
            target = max(1, math.floor(source_triangles * target_ratio))
            status, reason = 'retained', 'Already at or below the requested detail budget.'
            measured, candidate_error = accepted_errors[obj.name], None
            if before > target:
                previous = obj.data
                obj.data = previous.copy()
                modifier = obj.modifiers.new('LOD reduction', 'DECIMATE')
                modifier.ratio = target / before
                modifier.use_collapse_triangulate = True
                bpy.context.view_layer.objects.active = obj
                obj.select_set(True)
                bpy.ops.object.modifier_apply(modifier=modifier.name)
                try:
                    result_tree, result_points, after = surface(obj, obj.data)
                    candidate_error = max(sampled_error(source_points, result_tree), sampled_error(result_points, source_tree))
                    allowed = max_error * diagonal
                    if candidate_error > allowed + max(diagonal * 1e-9, 1e-15) or after > before:
                        raise ValueError('Reduction exceeded the geometric error limit.')
                    areas = material_areas(obj, obj.data)
                    if areas.keys() != source_areas.keys() or any(
                            not math.isclose(area, areas[key], rel_tol=0.025, abs_tol=1e-20)
                            for key, area in source_areas.items()):
                        raise ValueError('Reduction exceeded the surface area limit for a material group.')
                    status = 'reduced' if after < before else 'retained'
                    reason = 'Within the sampled error limit.' if status == 'reduced' else 'No further reduction was possible.'
                except ValueError as exc:
                    reduced = obj.data
                    obj.data = previous
                    bpy.data.meshes.remove(reduced)
                    reason = str(exc)
                else:
                    measured = accepted_errors[obj.name] = candidate_error
                    if previous.users == 0:
                        bpy.data.meshes.remove(previous)
            _, _, after = surface(obj, obj.data)
            triangles_after += after
            checks.append({'mesh': obj.name, 'status': status, 'reason': reason, 'before_triangles': before,
                           'triangles': after, 'target_triangles': target, 'sampled_error': measured,
                           'candidate_sampled_error': candidate_error if candidate_error is not None and math.isfinite(candidate_error) else None,
                           'error_limit': max_error * diagonal})
        options = {'filepath': str(output / f'lod-{level}.glb'), 'export_format': 'GLB',
                   'export_normals': True, 'export_tangents': True, 'export_texcoords': True,
                   'export_attributes': True, 'export_all_vertex_colors': True, 'export_vertex_color': 'ACTIVE',
                   'export_colors': True, 'export_animations': False, 'export_skins': False,
                   'export_yup': True, 'export_keep_originals': False}
        supported = bpy.ops.export_scene.gltf.get_rna_type().properties.keys()
        bpy.ops.export_scene.gltf(**{key: value for key, value in options.items() if key in supported})
        report['levels'][level] = {'target_ratio': target_ratio, 'triangles': triangles_after,
                                   'reduction_percent': 100 * (1 - triangles_after / total), 'geometry_checks': checks}
    (output / 'lod-report.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')


if __name__ == '__main__':
    source, output, ratio, max_error = sys.argv[sys.argv.index('--') + 1:]
    generate(Path(source), Path(output), float(ratio), float(max_error))
