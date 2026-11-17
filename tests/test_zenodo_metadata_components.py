"""Execute published processors and check metadata, privacy and rejected inputs."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import zipfile

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "external_code/zenodo_component_runtime"
sys.path.insert(0, str(RUNTIME))
spec = importlib.util.spec_from_file_location("zenodo_metadata_runner", RUNTIME / "component_runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def build_fixtures(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    exif = Image.Exif()
    exif[271] = "WebHDP fixture camera"
    exif[315] = "Example Creator example@example.invalid"
    exif[34853] = {1: "N", 2: (50.0, 0.0, 0.0), 3: "E", 4: (11.0, 0.0, 0.0)}
    photo = destination / "metadata-photo.jpg"
    Image.new("RGB", (96, 64), (32, 64, 128)).save(photo, exif=exif)
    texture = destination / "diffuse texture.png"
    Image.new("RGB", (4, 4), "orange").save(texture)
    material = "newmtl stone\nKd 0.8 0.7 0.6\nNs 20\nmap_Kd -s 1 1 1 ../textures/diffuse texture.png\nnewmtl metal\nPm 0.9\nPr 0.2\n"
    obj = "mtllib materials/fixture.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nusemtl stone\nf 1 2 3\n"
    bundle = destination / "material-model.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("model.obj", obj)
        archive.writestr("materials/fixture.mtl", material)
        archive.writestr("textures/diffuse texture.png", texture.read_bytes())
    binary = struct.pack("<12f12H", 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 2, 1, 0, 1, 3, 0, 3, 2, 1, 2, 3)
    model = {"asset": {"version": "2.0", "generator": "WebHDP measured tetrahedron fixture"},
             "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
             "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}],
             "materials": [{"name": "stone"}], "buffers": [{"byteLength": len(binary)}],
             "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 48, "target": 34962},
                             {"buffer": 0, "byteOffset": 48, "byteLength": 24, "target": 34963}],
             "accessors": [{"bufferView": 0, "componentType": 5126, "count": 4, "type": "VEC3", "min": [0, 0, 0], "max": [1, 1, 1]},
                           {"bufferView": 1, "componentType": 5123, "count": 12, "type": "SCALAR"}]}
    encoded = json.dumps(model, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 4)
    glb = destination / "tetrahedron.glb"
    glb.write_bytes(struct.pack("<5I", 0x46546C67, 2, 28 + len(encoded) + len(binary), len(encoded), 0x4E4F534A)
                    + encoded + struct.pack("<2I", len(binary), 0x004E4942) + binary)
    return {"image_metadata_extractor": photo, "mtl_metadata_extractor": bundle, "glb_metadata_extractor": glb}


@pytest.fixture
def staged(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBHDP_INPUT_DIR", str(tmp_path))
    return tmp_path, build_fixtures(tmp_path)


def execute(staged, key, parameters=None, path=None, output="out"):
    root, fixtures = staged
    result = runner.run_component(key, {"inputs": {"input_file": str(path or fixtures[key])}, "parameters": parameters or {}}, root / output)
    report = json.loads(Path(result["outputs"]["metadata_report"]).read_text(), parse_constant=lambda value: pytest.fail("Nonfinite JSON: " + value))
    assert result["status"] == "completed"
    assert report["success"]
    assert report["source_provenance"]["license"] == "GPL-3.0-or-later"
    assert len(report["source_provenance"]["processor_sha256"]) == 64
    return result, report


def test_image_real_exif_privacy_and_source_unchanged(staged):
    source = staged[1]["image_metadata_extractor"]
    before = source.read_bytes()
    result, report = execute(staged, "image_metadata_extractor")
    assert result["summary"] == {"width": 96, "height": 64, "format": "JPEG", "mode": "RGB"}
    facts = report["results"]
    assert facts["basic_info"]["sha256"] == hashlib.sha256(before).hexdigest()
    assert facts["exif_data"]["data"]["Make"] == "WebHDP fixture camera"
    assert "example@example.invalid" not in facts["exif_data"]["data"]["Artist"]
    assert "GPSInfo" not in facts["exif_data"]["data"]
    assert source.read_bytes() == before
    _, unfiltered = execute(staged, "image_metadata_extractor", {"remove_gps": False, "remove_mail": False, "remove_address": False, "include_hash": False}, output="unfiltered")
    assert "GPSInfo" in unfiltered["results"]["exif_data"]["data"]
    assert "example@example.invalid" in unfiltered["results"]["exif_data"]["data"]["Artist"]
    assert "sha256" not in unfiltered["results"]["basic_info"]


def test_image_png_exif_uses_portable_pillow_api(staged):
    source = staged[0] / "exif.png"
    exif = Image.Exif()
    exif[271] = "PNG metadata fixture"
    Image.new("RGB", (8, 5)).save(source, exif=exif)
    _, report = execute(staged, "image_metadata_extractor", path=source)
    assert report["results"]["exif_data"]["data"]["Make"] == "PNG metadata fixture"


def test_image_technical_and_maker_note_flags(staged):
    source = staged[0] / "technical.jpg"
    exif = Image.Exif()
    exif[271] = "Fixture camera"
    exif[33434] = 0.01
    exif[37500] = b"\x00\x01\x02\x03"
    Image.new("RGB", (12, 8)).save(source, exif=exif)
    _, default = execute(staged, "image_metadata_extractor", path=source)
    assert "ExposureTime" in default["results"]["exif_data"]["data"]
    assert "MakerNote" not in default["results"]["exif_data"]["data"]
    _, selected = execute(staged, "image_metadata_extractor", {"include_technical_details": False, "readable_maker_notes_only": False}, path=source, output="selected")
    assert "ExposureTime" not in selected["results"]["exif_data"]["data"]
    assert "MakerNote" in selected["results"]["exif_data"]["data"]
    assert selected["results"]["exif_data"]["data"]["Make"] == "Fixture camera"


def test_mtl_nested_texture_spaces_and_vector_options(staged):
    result, report = execute(staged, "mtl_metadata_extractor")
    assert result["summary"]["total_materials"] == 2
    assert result["summary"]["total_textures"] == 1
    material = report["results"]["all_materials"][0]
    texture = material["textures"]["diffuse_map"]
    assert texture["exists"] is True
    assert texture["filename"] == "textures/diffuse texture.png"
    assert texture["options"]["s"] == ["1", "1", "1"]
    assert not report["results"]["mtl_files"][0]["parse_errors"]


def test_direct_material_and_missing_texture_report(staged):
    source = staged[0] / "direct.mtl"
    source.write_text("newmtl stone\nKd 0.2 0.3 0.4\nmap_Kd missing.png\n")
    _, report = execute(staged, "mtl_metadata_extractor", path=source)
    assert report["results"]["summary"]["total_materials"] == 1
    assert report["results"]["all_materials"][0]["textures"]["diffuse_map"]["exists"] is False


def test_mtl_analysis_and_advanced_property_flags(staged):
    source = staged[0] / "properties.mtl"
    source.write_text("newmtl stone\ncustom_property 1 2 3\n")
    _, default = execute(staged, "mtl_metadata_extractor", path=source)
    assert default["results"]["all_materials"][0]["properties"]["unknown_custom_property"] == [1, 2, 3]
    _, selected = execute(staged, "mtl_metadata_extractor", {"parse_advanced_properties": False, "include_material_analysis": False}, path=source, output="selected")
    assert selected["results"]["all_materials"][0]["properties"] == {}
    assert selected["results"]["material_analysis"] == {}
    assert selected["results"]["all_materials"][0]["raw_properties"]["custom_property"] == "1 2 3"


def test_glb_measured_tetrahedron(staged):
    result, report = execute(staged, "glb_metadata_extractor")
    assert result["summary"] == {"meshes": 1, "nodes": 1, "materials": 1, "total_vertices": 4, "triangles": 4}
    facts = report["results"]
    assert facts["bounds_available"]
    assert facts["bounding_box"] == {"min": [0, 0, 0], "max": [1, 1, 1]}
    assert facts["approximate_volume"] == 1  # bounding box, not tetrahedron volume
    assert "not enclosed mesh volume" in facts["volume_interpretation"]


def test_glb_optional_measurement_flags(staged):
    _, report = execute(staged, "glb_metadata_extractor", {"calculate_volume": False, "include_detailed_primitives": False, "include_extension_details": False})
    assert "approximate_volume" not in report["results"]
    assert "primitive_details" not in report["results"]
    assert report["results"]["summary"]["total_triangles"] == 4


@pytest.mark.parametrize("mode,count,expected", [(4, 6, 2), (5, 5, 3), (6, 5, 3), (1, 6, 0)])
def test_gltf_unindexed_triangle_modes_and_absent_bounds(staged, mode, count, expected):
    source = staged[0] / "primitive.gltf"
    source.write_text(json.dumps({"asset": {"version": "2.0"}, "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "mode": mode}]}],
                                 "accessors": [{"componentType": 5126, "count": count, "type": "VEC3"}]}))
    result, report = execute(staged, "glb_metadata_extractor", path=source)
    assert result["summary"]["triangles"] == expected
    assert report["results"]["bounds_available"] is False
    assert report["results"]["bounding_box"] is None
    assert report["results"]["approximate_volume"] is None


@pytest.mark.parametrize("reference", ["../../outside.png", "/etc/passwd", "https://example.invalid/private.png", "C:/outside.png"])
def test_mtl_rejects_resource_escape(staged, reference):
    source = staged[0] / "bad.mtl"
    source.write_text("newmtl stone\nmap_Kd " + reference + "\n")
    with pytest.raises(ValueError, match="reference"):
        execute(staged, "mtl_metadata_extractor", path=source)


def test_gltf_external_resource_escape_and_invalid_glb(staged):
    source = staged[0] / "bad.gltf"
    source.write_text(json.dumps({"asset": {"version": "2.0"}, "buffers": [{"uri": "%2e%2e/outside.bin", "byteLength": 12}]}))
    with pytest.raises(ValueError, match="escapes"):
        execute(staged, "glb_metadata_extractor", path=source)
    bad = staged[0] / "bad.glb"
    bad.write_bytes(b"not a model")
    with pytest.raises(ValueError, match="header"):
        execute(staged, "glb_metadata_extractor", path=bad)


def test_corrupt_image_and_invalid_parameter_fail(staged):
    source = staged[0] / "corrupt.png"
    source.write_bytes(b"not an image")
    with pytest.raises(Exception):
        execute(staged, "image_metadata_extractor", path=source)
    with pytest.raises(ValueError, match="booleans"):
        execute(staged, "image_metadata_extractor", {"remove_gps": "false"})
    with pytest.raises(ValueError, match="Unknown"):
        execute(staged, "image_metadata_extractor", {"probe_bytes": 128})


def test_bundles_reject_unsafe_and_ambiguous_entries(staged):
    source = staged[0] / "bad.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("../outside.mtl", "newmtl bad")
    with pytest.raises(ValueError, match="Unsafe"):
        execute(staged, "mtl_metadata_extractor", path=source)
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("one.obj", "v 0 0 0")
        archive.writestr("two.obj", "v 0 0 0")
    with pytest.raises(ValueError, match="exactly one"):
        execute(staged, "mtl_metadata_extractor", path=source)
