"""Real OBJ geometry, dependency confinement and optional real Blender conversion."""
import io
import json
import math
import os
from pathlib import Path
import struct
import zipfile

import pytest
from PIL import Image

from external_code.zenodo_component_runtime import obj_components as obj
from external_code.zenodo_component_runtime.component_runner import run_component


TETRA = "v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\nf 1 3 2\nf 1 2 4\nf 1 4 3\nf 2 3 4\n"


@pytest.fixture
def staging(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBHDP_INPUT_DIR", str(tmp_path))
    return tmp_path


def analyze(staging, content=TETRA, **parameters):
    source = staging / "input.obj"
    source.write_text(content)
    result = run_component("obj_statistics_extractor", {"inputs": {"input_file": str(source)}, "parameters": parameters}, staging / "out")
    return json.loads(Path(result["outputs"]["report"]).read_text())


def textured_zip(staging):
    stream = io.BytesIO()
    Image.new("RGB", (16, 8), "orange").save(stream, format="PNG")
    source = staging / "scene.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("scene/model.obj", "mtllib materials/model.mtl\nusemtl Clay\n" + TETRA)
        archive.writestr("scene/materials/model.mtl", "newmtl Clay\nKd .8 .4 .1\nmap_Kd -s 1 1 1 ../textures/clay color.png\n")
        archive.writestr("scene/textures/clay color.png", stream.getvalue())
    return source


def test_tetrahedron_has_analytic_area_volume_and_quality(staging):
    report = analyze(staging, compute_mesh_quality=True)
    result = report["results"]
    assert result["geometric_vertices"] == result["faces"] == 4
    assert result["bounding_box"] == {"min": [0, 0, 0], "max": [1, 1, 1], "dimensions": [1, 1, 1]}
    assert result["geometry"]["surface_area"] == pytest.approx((3 + math.sqrt(3)) / 2)
    assert result["geometry"]["volume"] == pytest.approx(1 / 6)
    assert result["mesh_quality"] == {"boundary_edges": 0, "nonmanifold_edges": 0, "degenerate_triangles": 0}


def test_concave_polygon_negative_indices_and_open_volume(staging):
    report = analyze(staging, "v 0 0 0\nv 2 0 0\nv 2 2 0\nv 1 1 0\nv 0 2 0\nf -5 -4 -3 -2 -1\n", compute_mesh_quality=True)
    result = report["results"]
    assert result["n_gon_faces"] == 1
    assert result["geometry"]["triangle_count"] == 3
    assert result["geometry"]["surface_area"] == pytest.approx(3)
    assert result["geometry"]["volume"] is None
    assert result["mesh_quality"]["boundary_edges"] == 5


def test_inconsistent_orientation_withholds_volume(staging):
    report = analyze(staging, TETRA.replace("f 1 3 2", "f 1 2 3"))
    assert report["results"]["geometry"]["closed_manifold"] is True
    assert report["results"]["geometry"]["volume"] is None


@pytest.mark.parametrize("content", [TETRA + "f 0 2 3\n", TETRA + "f 1 2 5\n", TETRA + "f 1/1 2/2 3/3\n", TETRA.replace("v 0 0 0", "v nan 0 0"), "v 1 2\n", "f 1 2 3\n"])
def test_bad_geometry_is_rejected(staging, content):
    with pytest.raises(ValueError):
        analyze(staging, content)


@pytest.mark.parametrize("parameters", [{"compute_mesh_quality": "true"}, {"calculate_detailed_geometry": 1}, {"script": "anything"}])
def test_invalid_parameters_are_rejected(staging, parameters):
    with pytest.raises(ValueError):
        analyze(staging, **parameters)


def test_material_options_nested_paths_and_spaces(staging):
    result = run_component("obj_statistics_extractor", {"inputs": {"input_file": str(textured_zip(staging))}}, staging / "out")
    report = json.loads(Path(result["outputs"]["report"]).read_text())
    assert report["dependencies"]["materials"] == ["Clay"]
    assert report["dependencies"]["missing"] == []
    assert report["dependencies"]["textures"][0]["reference"] == "../textures/clay color.png"
    assert len(report["dependencies"]["textures"][0]["sha256"]) == 64


@pytest.mark.parametrize("reference", ["../outside.mtl", "/etc/passwd", "C:/private.mtl", "..\\outside.mtl"])
def test_material_path_escape_with_tabs_is_rejected(staging, reference):
    with pytest.raises(ValueError):
        analyze(staging, "mtllib\t" + reference + "\n" + TETRA)


def test_missing_texture_fails_before_blender(staging, monkeypatch):
    monkeypatch.setenv("WEBHDP_BLENDER", "/not/a/blender")
    source = staging / "scene.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("model.obj", "mtllib model.mtl\n" + TETRA)
        archive.writestr("model.mtl", "newmtl Clay\nmap_Kd missing.png\n")
    with pytest.raises(ValueError, match="Missing material/texture dependencies"):
        run_component("obj_to_glb_converter", {"inputs": {"input_file": str(source)}}, staging / "out")


def test_zip_requires_one_obj_and_rejects_traversal(staging):
    source = staging / "scene.zip"
    for index, names in enumerate([["a.obj", "b.obj"], ["../model.obj"]]):
        with zipfile.ZipFile(source, "w") as archive:
            for name in names:
                archive.writestr(name, TETRA)
        with pytest.raises(ValueError):
            run_component("obj_statistics_extractor", {"inputs": {"input_file": str(source)}}, staging / f"out{index}")


def test_lightweight_analysis_respects_options(staging):
    report = analyze(staging, calculate_detailed_geometry=False, include_material_analysis=False)
    assert "geometry" not in report["results"]
    assert report["dependencies"] is None


@pytest.mark.skipif(not os.environ.get("WEBHDP_TEST_BLENDER"), reason="Requires an installed real Blender executable")
@pytest.mark.parametrize("optimize", [False, True])
def test_real_blender_embeds_texture_and_preserves_tetrahedron(staging, monkeypatch, optimize):
    monkeypatch.setenv("WEBHDP_BLENDER", os.environ["WEBHDP_TEST_BLENDER"])
    result = run_component("obj_to_glb_converter", {"inputs": {"input_file": str(textured_zip(staging))}, "parameters": {"optimize_geometry": optimize}}, staging / "out")
    data = Path(result["outputs"]["model_file"]).read_bytes()
    assert data[:4] == b"glTF"
    length = struct.unpack_from("<I", data, 12)[0]
    document = json.loads(data[20:20 + length])
    assert len(document["images"]) == 1
    assert all("uri" not in row for row in document["images"] + document["buffers"])
    report = json.loads(Path(result["outputs"]["report"]).read_text())
    assert report["output_geometry"]["triangles"] == 4
    assert report["blender"]["before"]["vertices"] == report["blender"]["after"]["vertices"] == 4
    assert report["blender"]["optimize_geometry"] is optimize


@pytest.mark.skipif(not os.environ.get("WEBHDP_TEST_BLENDER"), reason="Requires an installed real Blender executable")
def test_real_blender_material_exclusion_is_effective(staging, monkeypatch):
    monkeypatch.setenv("WEBHDP_BLENDER", os.environ["WEBHDP_TEST_BLENDER"])
    result = run_component("obj_to_glb_converter", {"inputs": {"input_file": str(textured_zip(staging))}, "parameters": {"include_materials": False}}, staging / "out")
    assert result["summary"]["triangles"] == 4
    assert result["summary"]["materials"] == result["summary"]["embedded_images"] == 0


@pytest.mark.skipif(not os.environ.get("WEBHDP_TEST_BLENDER"), reason="Requires an installed real Blender executable")
def test_real_blender_optimization_merges_duplicate_vertices(staging, monkeypatch):
    monkeypatch.setenv("WEBHDP_BLENDER", os.environ["WEBHDP_TEST_BLENDER"])
    source = staging / "duplicate.obj"
    source.write_text(TETRA.replace("f 1 3 2", "v 0 0 0\nf 5 3 2"))
    result = run_component("obj_to_glb_converter", {"inputs": {"input_file": str(source)}, "parameters": {"optimize_geometry": True}}, staging / "out")
    report = json.loads(Path(result["outputs"]["report"]).read_text())
    assert report["blender"]["before"]["vertices"] == 5
    assert report["blender"]["after"]["vertices"] == 4
    assert result["summary"]["triangles"] == 4


def test_flat_dependency_files_are_staged_and_texture_search_is_effective(staging):
    source = staging / "model.obj"
    source.write_text("mtllib model.mtl\n" + TETRA)
    material = staging / "model.mtl"
    material.write_text("newmtl Clay\nmap_Kd textures/tile.png\n")
    texture = staging / "tile.png"
    Image.new("RGB", (2, 2), "red").save(texture)
    working = staging / "work"
    working.mkdir()
    _, prepared, root = obj.prepare_obj({"input_file": str(source), "dependency_files": [str(material), str(texture)]}, working)
    assert obj.material_dependencies(prepared, root, search=False)["missing"] == ["textures/tile.png"]
    checked = obj.material_dependencies(prepared, root, search=True)
    assert checked["missing"] == []
    assert (root / "textures/tile.png").read_bytes() == texture.read_bytes()


@pytest.mark.skipif(not os.environ.get("WEBHDP_TEST_BLENDER"), reason="Requires an installed real Blender executable")
def test_unused_textured_material_does_not_fail_valid_conversion(staging, monkeypatch):
    monkeypatch.setenv("WEBHDP_BLENDER", os.environ["WEBHDP_TEST_BLENDER"])
    source = staging / "model.obj"
    source.write_text("mtllib unused.mtl\n" + TETRA)
    material = staging / "unused.mtl"
    material.write_text("newmtl Unused\nmap_Kd unused.png\n")
    texture = staging / "unused.png"
    Image.new("RGB", (4, 4), "blue").save(texture)
    result = run_component("obj_to_glb_converter", {"inputs": {"input_file": str(source), "dependency_files": [str(material), str(texture)]}}, staging / "out")
    assert result["summary"]["triangles"] == 4
    assert result["summary"]["embedded_images"] == 0
    report = json.loads(Path(result["outputs"]["report"]).read_text())
    assert report["warnings"] == []


@pytest.mark.skipif(not os.environ.get("WEBHDP_TEST_BLENDER"), reason="Requires an installed real Blender executable")
@pytest.mark.parametrize("search", [False, True])
def test_real_blender_respects_disabled_texture_search(staging, monkeypatch, search):
    monkeypatch.setenv("WEBHDP_BLENDER", os.environ["WEBHDP_TEST_BLENDER"])
    source = staging / "model.obj"
    source.write_text("mtllib model.mtl\nusemtl Clay\n" + TETRA)
    material = staging / "model.mtl"
    material.write_text("newmtl Clay\nmap_Kd missing-dir/tile.png\n")
    texture = staging / "tile.png"
    Image.new("RGB", (4, 4), "red").save(texture)
    result = run_component("obj_to_glb_converter", {"inputs": {"input_file": str(source), "dependency_files": [str(material), str(texture)]}, "parameters": {"search_textures": search, "ignore_missing_textures": True}}, staging / "out")
    assert result["summary"]["triangles"] == 4
    assert result["summary"]["embedded_images"] == int(search)
    report = json.loads(Path(result["outputs"]["report"]).read_text())
    assert bool(report["dependencies"]["missing"]) is not search
    assert material.read_text() == "newmtl Clay\nmap_Kd missing-dir/tile.png\n"
