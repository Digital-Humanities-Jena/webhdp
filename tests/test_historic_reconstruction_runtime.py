"""Portable scientific stages: real images, pair selection, geometry and failures."""
import importlib.util
import json
import stat
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("historic_runtime", ROOT / "external_code/historic_reconstruction_runtime/component_runner.py")
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


@pytest.fixture
def staging(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBHDP_INPUT_DIR", str(tmp_path))
    return tmp_path


def image(path, color="red", exif=False):
    im = Image.new("RGB", (100, 200), color)
    metadata = Image.Exif()
    if exif:
        metadata[274] = 6
        metadata[271] = "misleading scanner"
    im.save(path, exif=metadata)
    return path


def prepared(staging, count=3):
    paths = [image(staging / f"photo-{index}.jpg", (index * 60, 50, 90)) for index in range(count)]
    return runtime.run_component("prepare", {"inputs": {"input_files": list(map(str, paths))}}, staging / "prepared")


def read_bundle(path):
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read("dataset.json"))


def test_preparation_rotates_strips_metadata_and_records_fixity(staging):
    source = image(staging / "scan.jpg", exif=True)
    result = runtime.run_component("prepare", {"inputs": {"input_file": str(source)}}, staging / "out")
    assert result["status"] == "completed"
    with zipfile.ZipFile(result["outputs"]["dataset"]) as archive:
        metadata = json.loads(archive.read("dataset.json"))
        row = metadata["images"][0]
        assert row["original_size"] == [100, 200]
        assert row["size"] == [200, 100]
        assert row["source_sha256"] == runtime.sha256(source)
        with archive.open("images/000001.jpg") as stream, Image.open(stream) as im:
            assert im.size == (200, 100)
            assert not im.getexif()
    assert Image.open(source).getexif()[274] == 6


def test_preparation_is_deterministic_and_handles_alpha(staging):
    source = staging / "alpha.png"
    Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(source)
    a = runtime.run_component("prepare", {"inputs": {"input_file": str(source)}}, staging / "a")
    b = runtime.run_component("prepare", {"inputs": {"input_file": str(source)}}, staging / "b")
    assert runtime.sha256(a["outputs"]["dataset"]) == runtime.sha256(b["outputs"]["dataset"])
    with zipfile.ZipFile(a["outputs"]["dataset"]) as archive, archive.open("images/000001.jpg") as stream:
        assert Image.open(stream).getpixel((0, 0)) == (255, 255, 255)


@pytest.mark.parametrize("inputs", [{}, {"input_file": "a", "input_files": ["b"]}])
def test_preparation_requires_one_input_form(staging, inputs):
    with pytest.raises(ValueError, match="exclusively"):
        runtime.run_component("prepare", {"inputs": inputs}, staging / "out")


def test_preparation_rejects_invalid_parameters(staging):
    source = image(staging / "scan.jpg")
    for params in ({"max_image_size": True}, {"max_image_size": 1}, {"script": "evil"}):
        with pytest.raises(ValueError):
            runtime.run_component("prepare", {"inputs": {"input_file": str(source)}, "parameters": params}, staging / "out")


@pytest.mark.parametrize("filename", ["../escape.jpg", "/escape.jpg", "a\\escape.jpg", "C:/escape.jpg"])
def test_archive_rejects_traversal(staging, filename):
    source = staging / "bad.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(filename, b"bad")
    with pytest.raises(ValueError, match="unsafe"):
        runtime.extract_archive(source, staging / "extract")
    assert not (staging.parent / "escape.jpg").exists()


def test_archive_rejects_links_and_case_collisions(staging):
    source = staging / "bad.zip"
    info = zipfile.ZipInfo("image.jpg")
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(info, "../../outside")
    with pytest.raises(ValueError, match="unsafe"):
        runtime.extract_archive(source, staging / "extract1")
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("Image.jpg", b"a")
        archive.writestr("image.jpg", b"b")
    with pytest.raises(ValueError, match="duplicate"):
        runtime.extract_archive(source, staging / "extract2")


def test_staged_file_rejects_escape_and_links(staging):
    source = image(staging / "scan.jpg")
    (staging / "alias.jpg").symlink_to(source)
    with pytest.raises(ValueError):
        runtime.staged_file({"input_file": str(staging / "alias.jpg")}, "input_file")
    with pytest.raises(ValueError):
        runtime.staged_file({"input_file": str(Path(__file__))}, "input_file")


def test_exhaustive_pairs_and_gps_selection(staging):
    original = prepared(staging, 4)
    result = runtime.run_component("pairs", {"inputs": {"input_file": original["outputs"]["dataset"]}}, staging / "pairs")
    assert result["summary"]["pair_count"] == 6
    assert len(Path(result["outputs"]["pairs"]).read_text().splitlines()) == 6
    gps = staging / "gps.json"
    gps.write_text(json.dumps({f"photo-{i}.jpg": [50.0, 11 + i * 0.0001] for i in range(4)}))
    result = runtime.run_component("pairs", {"inputs": {"input_file": original["outputs"]["dataset"], "gps_file": str(gps)},
                                            "parameters": {"method": "gps", "max_neighbors": 1}}, staging / "gps-pairs")
    assert 2 <= result["summary"]["pair_count"] <= 3
    manifest = read_bundle(result["outputs"]["dataset"])
    assert manifest["pair_selection"]["method"] == "gps"
    assert manifest["pair_selection"]["pairs_sha256"] == runtime.sha256(result["outputs"]["pairs"])


def test_gps_requires_all_finite_coordinates(staging):
    original = prepared(staging)
    gps = staging / "gps.json"
    gps.write_text(json.dumps({"photo-0.jpg": [91, 10]}))
    with pytest.raises(ValueError, match="GPS"):
        runtime.run_component("pairs", {"inputs": {"input_file": original["outputs"]["dataset"], "gps_file": str(gps)},
                                        "parameters": {"method": "gps"}}, staging / "pairs")


def test_dataset_fixity_rejects_mutated_image(staging):
    original = prepared(staging)
    broken = staging / "broken.zip"
    with zipfile.ZipFile(original["outputs"]["dataset"]) as source, zipfile.ZipFile(broken, "w") as target:
        for name in source.namelist():
            target.writestr(name, b"changed" if name.endswith("000001.jpg") else source.read(name))
    with pytest.raises(ValueError, match="fixity"):
        runtime.run_component("pairs", {"inputs": {"input_file": str(broken)}}, staging / "pairs")


def test_pair_fixity_rejects_mutated_pairs(staging):
    original = prepared(staging)
    selected = runtime.run_component("pairs", {"inputs": {"input_file": original["outputs"]["dataset"]}}, staging / "pairs")
    root = runtime.extract_archive(selected["outputs"]["dataset"], staging / "extracted")
    (root / "pairs.txt").write_text("000001.jpg unknown.jpg\n")
    with pytest.raises(ValueError, match="fixity"):
        runtime.selected_pairs(root, json.loads((root / "dataset.json").read_text()))


def test_descriptor_matching_obeys_mutual_and_ambiguity_checks():
    identity = np.eye(8, dtype=np.uint8) * 255
    assert np.array_equal(runtime.match_descriptors(identity, identity[::-1]), np.array([[i, 7-i] for i in range(8)]))
    ambiguous = np.repeat(identity[:1], 3, axis=0)
    assert runtime.match_descriptors(ambiguous, ambiguous).shape == (0, 2)


def test_similarity_recovers_transform_and_rejects_outlier():
    source = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 2, 3], [-3, 1, 2]], float)
    rotation = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
    target = 3 * source @ rotation.T + [50, 60, 70]
    target[-1] += 100
    scale, fitted_rotation, translation, errors, inliers = runtime.robust_similarity(source, target, 0.01)
    assert scale == pytest.approx(3)
    assert np.allclose(rotation, fitted_rotation)
    assert np.allclose(translation, [50, 60, 70])
    assert inliers.tolist() == [True] * 5 + [False]
    assert max(errors[inliers]) < 1e-10


@pytest.mark.parametrize("points", [[[0,0,0]]*3, [[0,0,0],[1,0,0],[2,0,0]]])
def test_similarity_rejects_degenerate_controls(points):
    with pytest.raises(ValueError, match="collinear"):
        runtime.fit_similarity(points, points)


def test_cpu_count_respects_allocation(monkeypatch):
    monkeypatch.setenv("SLURM_CPUS_PER_TASK", "2")
    assert runtime.cpu_count() == 2


@pytest.mark.parametrize("trim", [-1, 21, float("nan"), True, "5"])
def test_dense_rejects_invalid_surface_threshold_before_processing(staging, trim):
    with pytest.raises(ValueError, match="poisson_trim"):
        runtime.run_component("dense", {"inputs": {}, "parameters": {"poisson_trim": trim}}, staging / "out")


@pytest.mark.parametrize("empty_stage", ["stereo_fusion", "poisson_mesher"])
def test_dense_empty_geometry_reports_stage_and_preserves_diagnostics(staging, monkeypatch, empty_stage):
    """COLMAP can exit successfully after producing an empty PLY; expose that failure."""
    pc = pytest.importorskip("pycolmap")
    model = pc.synthesize_dataset(pc.SyntheticDatasetOptions())
    root = staging / "bundle"
    (root / "images").mkdir(parents=True)
    (root / "sparse").mkdir()
    records = []
    for item in model.images.values():
        source = image(root / "images" / item.name)
        records.append({"name": item.name, "sha256": runtime.sha256(source)})
    runtime.write_json(root / "dataset.json", {"schema": runtime.SCHEMA, "images": records})
    model.write(str(root / "sparse"))
    archive = runtime.pack_archive(root, staging / "bundle.zip")
    calls = []

    def external_command(command, log):
        calls.append(command)
        log.write_text("x" * 6000 + "\nCOLMAP diagnostic: geometry rejected\n")
        if command[1] == "stereo_fusion":
            count = 0 if empty_stage == "stereo_fusion" else 3
            Path(command[command.index("--output_path") + 1]).write_text(
                f"ply\nformat ascii 1.0\nelement vertex {count}\n"
                "property float x\nproperty float y\nproperty float z\nend_header\n"
                + "0 0 0\n" * count)
        elif command[1] == "poisson_mesher":
            Path(command[command.index("--output_path") + 1]).write_text(
                "ply\nformat ascii 1.0\ncomment Running Surface Trimmer\n"
                "element vertex 0\nelement face 0\nend_header\n")

    monkeypatch.setattr(runtime.shutil, "which", lambda _: "/operator/colmap")
    monkeypatch.setattr(runtime, "run_command", external_command)
    with pytest.raises(ValueError, match=empty_stage) as caught:
        runtime.run_component("dense", {"inputs": {"input_file": str(archive)}}, staging / "out")
    assert "COLMAP diagnostic: geometry rejected" in str(caught.value)
    assert len(str(caught.value)) < 3300
    assert not list((staging / "out").glob("historic-*"))
    if empty_stage == "stereo_fusion":
        assert all(command[1] != "poisson_mesher" for command in calls)
    else:
        assert "0 faces from 3 fused points" in str(caught.value)
        assert "poisson_trim=5.0" in str(caught.value)
        assert calls[-1][calls[-1].index("--PoissonMeshing.trim") + 1] == "5.0"


def test_georeference_transforms_real_colmap_model(staging):
    pc = pytest.importorskip("pycolmap")
    model = pc.synthesize_dataset(pc.SyntheticDatasetOptions())
    root = staging / "bundle"
    (root / "images").mkdir(parents=True)
    (root / "sparse").mkdir()
    records = []
    for item in model.images.values():
        source = image(root / "images" / item.name)
        records.append({"name": item.name, "original_name": item.name, "sha256": runtime.sha256(source)})
    runtime.write_json(root / "dataset.json", {"schema": runtime.SCHEMA, "images": records})
    model.write(str(root / "sparse"))
    source_points = np.array([point.xyz for point in list(model.points3D.values())[:5]])
    target_points = 2 * source_points + [4, 5, 6]
    runtime.write_json(root / "control_points.json", {"points": [{"source": a.tolist(), "target": b.tolist()} for a,b in zip(source_points, target_points)]})
    archive = runtime.pack_archive(root, staging / "bundle.zip")
    result = runtime.run_component("georeference", {"inputs": {"input_file": str(archive)}, "parameters": {"crs": "test-metre-frame"}}, staging / "out")
    transformed_root = runtime.extract_archive(result["outputs"]["reconstruction"], staging / "transformed")
    transformed = pc.Reconstruction(str(transformed_root / "sparse"))
    for point_id, point in model.points3D.items():
        assert np.allclose(transformed.points3D[point_id].xyz, 2 * point.xyz + [4, 5, 6])
    for image_id, original in model.images.items():
        assert np.allclose(transformed.images[image_id].projection_center(), 2 * original.projection_center() + [4,5,6])
    assert result["summary"]["inlier_rmse"] < 1e-10
    assert result["summary"]["crs_reprojection_performed"] is False


def test_masks_use_colmap_names_and_require_binary_coverage(staging):
    original = prepared(staging, 2)
    root = runtime.extract_archive(original["outputs"]["dataset"], staging / "extracted")
    manifest = json.loads((root / "dataset.json").read_text())
    (root / "masks").mkdir()
    for row in manifest["images"]:
        Image.new("L", tuple(row["size"]), 255).save(root / "masks" / (Path(row["name"]).stem + ".png"))
    output = staging / "valid"
    output.mkdir()
    mask_dir, hashes = runtime.prepare_masks(root, manifest, output)
    assert (mask_dir / "000001.jpg.png").is_file()
    assert len(hashes) == 2
    Image.new("L", tuple(manifest["images"][0]["size"]), 123).save(root / "masks" / "000001.png")
    output = staging / "invalid"
    output.mkdir()
    with pytest.raises(ValueError, match="only 0"):
        runtime.prepare_masks(root, manifest, output)


def test_export_supports_aliases_without_duplicate_copy(staging, monkeypatch):
    def alias_stage(inputs, params, work):
        file = runtime.write_json(work / "one.json", {"evidence": True})
        return {"first": file, "second": file}, {}
    monkeypatch.setitem(runtime.STAGES, "alias", alias_stage)
    result = runtime.run_component("alias", {"inputs": {}}, staging / "out")
    assert result["outputs"]["first"] == result["outputs"]["second"]
    assert len(result["artifacts"]) == 1
    assert result["artifacts"][0]["metadata"]["roles"] == ["first", "second"]


def test_research_dispatch_reports_missing_operator_runtime(staging, monkeypatch):
    monkeypatch.delenv("HISTORIC_RECONSTRUCTION_UPSTREAM_CONFIG", raising=False)
    with pytest.raises(ValueError, match="runtime is not installed"):
        runtime.run_component("upstream-segmentation", {"inputs": {}}, staging / "research")
