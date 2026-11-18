"""Prepare real sample meshes and keep all dependency resolution local."""

from io import BytesIO
import csv
import json
from pathlib import Path
import struct
import zipfile

from PIL import Image
import pytest

from services.model_preparation_service import prepare_model


SAMPLES = Path(__file__).parents[1] / "datasets" / "quick-publication"
TRIANGLE = "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"


def archive(tmp_path, files):
    source = tmp_path / "model.zip"
    with zipfile.ZipFile(source, "w") as package:
        for path, data in files.items():
            package.writestr(path, data)
    return source


def basic_obj(reference):
    return {
        "scan.obj": "mtllib scan.mtl\nusemtl Clay\n" + TRIANGLE,
        "scan.mtl": "newmtl Clay\nKd .6 .4 .2\nmap_Kd -s 1 1 1 " + reference + "\n",
    }


def png():
    stream = BytesIO()
    Image.new("RGB", (2, 2), "red").save(stream, format="PNG")
    return stream.getvalue()


@pytest.mark.parametrize(
    ("sample", "expected_kinds"),
    [
        ("terracotta-vessel", []), ("painted-floor-tile", ["relinked"]),
        ("bronze-seal", ["material_fallback"]), ("glazed-bowl", ["relinked", "material_fallback"]),
    ],
)
def test_prepare_public_samples_and_match_metadata_row(tmp_path, sample, expected_kinds):
    result = prepare_model(SAMPLES / f"{sample}.zip", tmp_path)
    assert result["model"] in result["files"]
    assert all((tmp_path / name).is_file() for name in result["files"])
    assert [item["kind"] for item in result["repairs"]] == expected_kinds
    with (tmp_path / result["msf"]).open(encoding="utf-8") as stream:
        metadata = next(csv.DictReader(stream))
    assert metadata["filename"] == result["model"]
    assert metadata["license"] == "cc0-1.0"
    if sample == "painted-floor-tile":
        document = json.loads((tmp_path / result["model"]).read_text())
        assert document["images"][0]["uri"] == "surface/floor-tile.png"
        assert document["buffers"][0]["uri"] == "buffers/tile.bin"
    elif sample == "bronze-seal":
        material = (tmp_path / "seal.mtl").read_text()
        assert "map_Kd" not in material
        assert "Kd 0.59 0.42 0.23" in material
    elif sample == "glazed-bowl":
        material = (tmp_path / "bowl.mtl").read_text()
        assert "map_Kd surface/bowl-glaze.png" in material
        assert "bump" not in material
        assert result["repairs"][1]["reason"] == "unreadable_texture"
        assert result["files"] == ["bowl.mtl", "bowl.obj", "surface/bowl-glaze.png"]
        assert not (tmp_path / "detail" / "bowl-detail.png").exists()


def test_relink_moved_texture_with_case_difference_and_preserve_map_options(tmp_path):
    files = basic_obj("lost/Clay.png") | {"images/clay.png": png(), "extra.txt": "ignored"}
    result = prepare_model(archive(tmp_path, files), tmp_path / "result")
    assert result["repairs"][0]["replacement"] == "images/clay.png"
    material = (tmp_path / "result" / "scan.mtl").read_text()
    assert "map_Kd -s 1 1 1 images/clay.png" in material
    assert result["files"] == ["images/clay.png", "scan.mtl", "scan.obj"]


def test_ambiguous_matches_do_not_replace_missing_texture_with_arbitrary_image(tmp_path):
    files = basic_obj("missing/clay.png") | {"a/clay.png": png(), "b/clay.png": png()}
    result = prepare_model(archive(tmp_path, files), tmp_path / "result")
    assert result["repairs"][0]["kind"] == "material_fallback"
    assert "Several possible matches" in result["warnings"][0]
    assert result["files"] == ["scan.mtl", "scan.obj"]


@pytest.mark.parametrize("reference", ["../private.png", "/private.png", "https://example.org/image.png"])
def test_unsafe_texture_references_are_rejected_before_writing_files(tmp_path, reference):
    output = tmp_path / "result"
    with pytest.raises(ValueError):
        prepare_model(archive(tmp_path, basic_obj(reference)), output)
    assert not output.exists()


def test_bundle_paths_cannot_escape_or_collide(tmp_path):
    output = tmp_path / "result"
    for invalid_path in ("../texture.png", "/texture.png", "nested/../../texture.png", "SCAN.obj"):
        with pytest.raises(ValueError):
            prepare_model(archive(tmp_path, {"scan.obj": TRIANGLE, invalid_path: png()}), output)
        assert not output.exists()


def test_invalid_images_fail_instead_of_becoming_draft_artifacts(tmp_path):
    files = basic_obj("clay.png") | {"clay.png": b"<script></script>"}
    with pytest.raises(ValueError, match="readable PNG or JPEG"):
        prepare_model(archive(tmp_path, files), tmp_path / "result")


def test_corrupt_relocated_texture_reports_only_the_fallback(tmp_path):
    files = basic_obj("missing/glaze.png") | {"moved/glaze.png": png()[:45]}
    result = prepare_model(archive(tmp_path, files), tmp_path / "result")
    assert [item["kind"] for item in result["repairs"]] == ["material_fallback"]
    assert result["repairs"][0]["reason"] == "unreadable_texture"
    assert result["files"] == ["scan.mtl", "scan.obj"]


def test_truncated_archive_does_not_write_any_artifacts(tmp_path):
    source = archive(tmp_path, basic_obj("missing/glaze.png"))
    source.write_bytes(source.read_bytes()[:-16])
    output = tmp_path / "result"
    with pytest.raises(ValueError, match="not a readable, unencrypted ZIP"):
        prepare_model(source, output)
    assert not output.exists()


@pytest.mark.parametrize(
    ("path", "contents", "message"),
    [
        ("scan.gltf", '{"asset": {"version": "2.0"},', "glTF document is damaged or incomplete"),
        ("scan.obj", TRIANGLE.replace("f 1 2 3", "f 1 2 9"), "vertex that is missing"),
        ("scan.obj", TRIANGLE.replace("f 1 2 3", "f 1 2 no"), "invalid vertex index"),
    ],
)
def test_corrupt_geometry_does_not_write_any_artifacts(tmp_path, path, contents, message):
    source = archive(tmp_path, {path: contents})
    output = tmp_path / "result"
    with pytest.raises(ValueError, match=message):
        prepare_model(source, output)
    assert not output.exists()


def glb(document, binary):
    encoded = json.dumps(document).encode()
    encoded += b" " * (-len(encoded) % 4)
    chunks = struct.pack("<I4s", len(encoded), b"JSON") + encoded
    chunks += struct.pack("<I4s", len(binary), b"BIN\x00") + binary
    return struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks


def test_self_contained_glb_with_geometry_is_preserved(tmp_path):
    vertices = struct.pack("<9f", 0, 0, 0, 0, 1, 0, 1, 0, 0)
    document = {
        "asset": {"version": "2.0"},
        "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "accessors": [{"type": "VEC3", "componentType": 5126, "bufferView": 0, "count": 3}],
        "bufferViews": [{"buffer": 0, "byteLength": len(vertices)}],
        "buffers": [{"byteLength": len(vertices)}],
    }
    source = tmp_path / "artifact.glb"
    source.write_bytes(glb(document, vertices))
    result = prepare_model(source, tmp_path / "result")
    assert result["files"] == ["artifact.glb"]
    assert (tmp_path / "result" / "artifact.glb").read_bytes() == source.read_bytes()
