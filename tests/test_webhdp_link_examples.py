"""Content and rejection checks for real WebHDP-Link example processors."""

import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import zipfile

import pytest

from external_code.webhdp_link_examples.runner import (
    digest, glb_bytes, hmsm_source_digest, mesh_package, photo_preparation, piano_digitization,
)
from external_code.webhdp_link_examples.seed import PUBLICATIONS
from services.native_pipeline_adapters import AdapterExecutionRequest, LocalCliAdapter


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "external_code/webhdp_link_examples"
FIXTURES = EXAMPLES / "fixtures"


def test_photo_preparation_hashes_actual_inputs_and_is_explicit_about_scope(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    sources = sorted(FIXTURES.glob("photo-*.jpg"))
    report = photo_preparation([str(path) for path in sources], tmp_path, 160)
    assert report["image_count"] == 3
    assert report["photogrammetry_executed"] is False
    assert [image["sha256"] for image in report["images"]] == [digest(path) for path in sources]
    assert [image["width"] for image in report["images"]] == [720, 720, 720]
    with Image.open(tmp_path / "contact-sheet.jpg") as image:
        assert image.size == (528, 202)
        assert len(image.getcolors(image.width * image.height)) > 100
    handoff = json.loads((tmp_path / "reconstruction-request.json").read_text())
    assert handoff["state"] == "prepared_not_executed"
    assert str(FIXTURES) not in (tmp_path / "photo-report.json").read_text()


def test_photo_rejects_duplicate_names_and_oversized_parameter(tmp_path):
    pytest.importorskip("PIL")
    with pytest.raises(ValueError, match="distinct filename"):
        photo_preparation([str(FIXTURES / "photo-1.jpg")] * 2, tmp_path)
    with pytest.raises(ValueError, match="max_side"):
        photo_preparation([str(FIXTURES / "photo-1.jpg")], tmp_path, 50000)


def _read_glb(path):
    data = path.read_bytes()
    magic, version, size = struct.unpack_from("<4sII", data)
    assert (magic, version, size) == (b"glTF", 2, len(data))
    json_size, json_kind = struct.unpack_from("<I4s", data, 12)
    assert json_kind == b"JSON"
    model = json.loads(data[20:20 + json_size])
    binary_size, binary_kind = struct.unpack_from("<I4s", data, 20 + json_size)
    assert binary_kind == b"BIN\0"
    binary = data[28 + json_size:]
    assert binary_size == len(binary) == model["buffers"][0]["byteLength"]
    return model, binary


def test_mesh_conversion_contains_correct_scaled_geometry_and_fixity(tmp_path):
    report = mesh_package(FIXTURES / "tetrahedron.obj", tmp_path, 4, "A tetrahedron")
    assert report["vertices"] == 4 and report["triangles"] == 4
    assert report["checks"]["closed_consistent_edge_topology"] is True
    assert report["transform"]["uniform_scale"] == 2
    assert report["publication_status"] == "prepared_not_uploaded"
    model, binary = _read_glb(tmp_path / "normalized.glb")
    assert model["accessors"][0]["min"] == [-2, -2, -2]
    assert model["accessors"][0]["max"] == [2, 2, 2]
    assert model["accessors"][0]["count"] == 12
    points = struct.unpack_from("<36f", binary)
    assert set(zip(points[0::3], points[1::3], points[2::3])) == {(-2, -2, -2), (2, -2, -2), (-2, 2, -2), (-2, -2, 2)}
    with zipfile.ZipFile(tmp_path / "model-package.zip") as archive:
        inventory = json.loads(archive.read("checksums.json"))
        assert set(inventory) == {"source.obj", "normalized.glb", "mesh-report.json", "zenodo-metadata.json"}
        for name, sha in inventory.items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == sha
        assert archive.read("source.obj") == (FIXTURES / "tetrahedron.obj").read_bytes()
    assert str(FIXTURES) not in (tmp_path / "mesh-report.json").read_text()


@pytest.mark.parametrize("body", [
    "v nan 0 0\nv 0 1 0\nv 1 0 0\nf 1 2 3\n",
    "v 0 0 0\nv 1 0 0\nv 2 0 0\nf 1 2 3\n",
    "v 0 0 0\nv 0 1 0\nv 1 0 0\nf 1 2 8\n",
    "mtllib ../../private.mtl\nv 0 0 0\n",
    "v 0 0 0\nv 0 1 0\nv 1 0 0\nv 1 1 0\nf 1 2 3 4\n",
])
def test_mesh_rejects_nonfinite_degenerate_external_or_unsupported_geometry(tmp_path, body):
    source = tmp_path / "bad.obj"
    source.write_text(body)
    with pytest.raises(ValueError):
        mesh_package(source, tmp_path / "results")
    assert not (tmp_path / "results/model-package.zip").exists()


def test_open_mesh_is_reported_instead_of_claimed_closed(tmp_path):
    source = tmp_path / "open.obj"
    source.write_text("v 0 0 0\nv 0 1 0\nv 1 0 0\nf 1 2 3\n")
    report = mesh_package(source, tmp_path / "out")
    assert report["checks"]["boundary_edges"] == 3
    assert report["checks"]["closed_consistent_edge_topology"] is False


def test_component_runs_through_real_native_cli_adapter(tmp_path):
    request = AdapterExecutionRequest(step_id="process", workdir=str(tmp_path), inputs={"input_file": str(FIXTURES / "tetrahedron.obj")},
        parameters={"target_extent": 2, "title": "Native execution"}, profile={
            "adapter": "local_cli", "entrypoint": [sys.executable, str(EXAMPLES / "runner.py"), "mesh"],
            "output_collection": [{"name": "model_file", "path": "normalized.glb"}, {"name": "mesh_report", "path": "mesh-report.json"}]})
    result = LocalCliAdapter().execute(request)
    assert result["success"] is True, result
    assert len(result["artifacts"]) == 2
    assert json.loads(Path(result["outputs"]["mesh_report"]).read_text())["title"] == "Native execution"
    assert '"status": "completed"' in result["logs"]["stdout"]


def test_component_code_pin_rejects_changed_executable(tmp_path):
    request = AdapterExecutionRequest(step_id="process", workdir=str(tmp_path), inputs={"input_file": str(FIXTURES / "tetrahedron.obj")}, parameters={}, profile={
        "adapter": "local_cli", "entrypoint": [sys.executable, str(EXAMPLES / "runner.py"), "mesh", "--expected-runner-sha256", "0" * 64]})
    result = LocalCliAdapter().execute(request)
    assert result["success"] is False
    assert "code changed" in result["logs"]["stderr"]


def test_publication_contract_exposes_only_scientific_parameters():
    assert {item["id"] for item in PUBLICATIONS} == {"link-photo-preparation", "link-piano-roll", "link-model-deposit"}
    assert all(item["pipeline_version"] == "1.0.0" for item in PUBLICATIONS)
    public = json.dumps(PUBLICATIONS)
    assert "hmsm_source" not in public and "hmsm_python" not in public and "entrypoint" not in public


def _midi_pitches(data):
    """Read note-ons independently of HMSM's MIDI writer."""
    assert data[:4] == b"MThd"
    cursor = 8 + int.from_bytes(data[4:8], "big")
    pitches = []
    while cursor < len(data):
        assert data[cursor:cursor + 4] == b"MTrk"
        end = cursor + 8 + int.from_bytes(data[cursor + 4:cursor + 8], "big")
        index, running = cursor + 8, None
        def variable():
            nonlocal index
            value = 0
            while True:
                byte = data[index]; index += 1
                value = (value << 7) | (byte & 127)
                if byte < 128:
                    return value
        while index < end:
            variable()
            status = data[index]
            if status >= 128:
                index += 1
                if status < 240:
                    running = status
            else:
                status = running
            if status == 255:
                index += 1
                length = variable(); index += length
            elif status in (240, 247):
                length = variable(); index += length
            else:
                count = 1 if status >> 4 in (12, 13) else 2
                if status >> 4 == 9 and data[index + 1] > 0:
                    pitches.append(data[index])
                index += count
        cursor = end
    return pitches


def test_real_hmsm_extracts_expected_midi_and_sanitized_evidence(tmp_path):
    pytest.importorskip("PIL")
    root, python = os.environ.get("WEBHDP_LINK_HMSM_SOURCE"), os.environ.get("WEBHDP_LINK_HMSM_PYTHON")
    if not root or not python:
        pytest.skip("Set the two WEBHDP_LINK_HMSM runtime variables for the real HMSM integration check.")
    report = piano_digitization(FIXTURES / "piano-roll.png", tmp_path, root, python, expected_source_sha256=hmsm_source_digest(root))
    expected = [60, 64, 67, 64, 60, 55, 48]
    assert report["note_count"] == 7
    assert [note["pitch"] for note in report["notes"]] == expected
    assert _midi_pitches((tmp_path / "result.mid").read_bytes()) == expected
    with zipfile.ZipFile(tmp_path / "piano-evidence.zip") as archive:
        inventory = json.loads(archive.read("checksums.json"))
        for name, sha in inventory.items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == sha
        assert str(FIXTURES).encode() not in archive.read("piano-report.json")
        assert root.encode() not in archive.read("piano-report.json")
    with pytest.raises(ValueError, match="source changed"):
        piano_digitization(FIXTURES / "piano-roll.png", tmp_path, root, python, expected_source_sha256="0" * 64)
