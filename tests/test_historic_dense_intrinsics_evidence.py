"""Numeric contract fixtures for dense calibration evidence, not inference proof."""
import json
import os
from pathlib import Path
import sys

import numpy as np
import pytest

from external_code.historic_reconstruction_runtime import upstream as u


def evidence(tmp_path, decision="rejected", status="ok", count=12):
    root = tmp_path / "workspace/scenes/church/dg-dense_intrinsics/intrinsics"
    (root / "matches").mkdir(parents=True)
    (root / "fit").mkdir()
    name = "historic.jpg"
    meta = {"name": name, "width": 1600, "height": 1067,
            "sfm_model": "SIMPLE_PINHOLE", "sfm_params": [1200, 800, 533.5],
            "sfm_num_points3D": count, "sfm_R": np.eye(3).tolist(), "sfm_center": [0, 0, 0],
            "views": [{"pano_id": "pano1"}]}
    arrays = {"meta": np.asarray(json.dumps(meta)), "view": np.zeros(count, dtype=np.int32),
              "point_id": np.arange(count, dtype=np.int64),
              "uv_h": np.column_stack([np.arange(count) + 100., np.arange(count) + 200.]),
              "uv_v": np.column_stack([np.arange(count) + 90., np.arange(count) + 180.]),
              "xyz": np.column_stack([np.arange(count), np.ones(count), np.full(count, 5.)]),
              "overlap": np.full(count, .9), "cycle_px": np.full(count, .1),
              "precision": np.tile([1., 0., 1.], (count, 1))}
    np.savez_compressed(root / "matches/historic.npz", **arrays)
    fit = {"name": name, "status": status, "num_obs": count, "num_corr": count,
           "num_inliers": count, "models": {}, "selected": "SIMPLE_PINHOLE"}
    camera = {"name": name, "status": status, "decision": decision, "tiers": []}
    if decision in {"dist", "pp", "focal"}:
        camera.update(camera={"model": "SIMPLE_PINHOLE", "width": 1600, "height": 1067,
                              "params": [1250., 800., 533.5]}, R=np.eye(3).tolist(), t=[0., 0., 0.])
    (root / "fits.jsonl").write_text(json.dumps(fit) + "\n")
    (root / "cameras.jsonl").write_text(json.dumps(camera) + "\n")
    if status == "ok":
        np.savez_compressed(root / "fit/historic.npz", point_id=arrays["point_id"],
                            uv=arrays["uv_h"], xyz=arrays["xyz"], num_panos=np.ones(count, dtype=int),
                            source=np.zeros(count, dtype=int))
    if decision in {"dist", "pp", "focal"}:
        model = root.parent / "models_geolocalized"
        model.mkdir()
        # Presence only is this helper's contract. Real binary models are decoded
        # independently by _model_report and by the native acceptance auditor.
        (model / "cameras.bin").write_bytes(b"unit-test presence marker")
    return tmp_path / "workspace", root, arrays


def rewrite_row(path, **changes):
    row = json.loads(path.read_text())
    row.update(changes)
    path.write_text(json.dumps(row) + "\n")


@pytest.mark.parametrize("decision", ["rejected", "unchanged"])
def test_nonempty_real_numeric_evidence_allows_no_accepted_updates(tmp_path, decision):
    workspace, root, _ = evidence(tmp_path, decision=decision)
    result = u._dense_intrinsics_evidence(workspace, ["historic.jpg"])
    assert result["processed_images"] == 1
    assert result["correspondences"] == 12
    assert result["accepted_updates"] == 0
    assert result["decision_counts"][decision] == 1
    assert not (root.parent / "models_geolocalized").exists()


@pytest.mark.parametrize("decision", ["dist", "pp", "focal"])
def test_accepted_decisions_require_fit_and_output_model(tmp_path, decision):
    workspace, _, _ = evidence(tmp_path, decision=decision)
    result = u._dense_intrinsics_evidence(workspace, ["historic.jpg"])
    assert result["accepted_updates"] == 1
    assert result["decision_counts"][decision] == 1


def test_low_support_with_real_matches_can_be_valid_unchanged(tmp_path):
    workspace, _, _ = evidence(tmp_path, decision="unchanged", status="few_correspondences", count=4)
    result = u._dense_intrinsics_evidence(workspace, ["historic.jpg"])
    assert result["accepted_updates"] == 0 and result["correspondences"] == 4


@pytest.mark.parametrize("missing", ["matches/historic.npz", "fits.jsonl", "cameras.jsonl"])
def test_missing_scientific_evidence_is_rejected(tmp_path, missing):
    workspace, root, _ = evidence(tmp_path)
    (root / missing).unlink()
    with pytest.raises(ValueError):
        u._dense_intrinsics_evidence(workspace, ["historic.jpg"])


def test_empty_workspace_is_not_execution_proof(tmp_path):
    with pytest.raises(ValueError):
        u._dense_intrinsics_evidence(tmp_path, ["historic.jpg"])


def test_all_empty_matches_are_not_execution_proof(tmp_path):
    workspace, _, _ = evidence(tmp_path, decision="unchanged", status="no_matches", count=0)
    with pytest.raises(ValueError):
        u._dense_intrinsics_evidence(workspace, ["historic.jpg"])


def test_one_source_shaped_empty_image_can_coexist_with_real_matches(tmp_path):
    workspace, root, _ = evidence(tmp_path)
    name = "unmatched.jpg"
    meta = {"name": name, "width": 1600, "height": 1067, "views": []}
    # The pinned match_image writer uses np.zeros((0,)) for unobserved fields,
    # including image coordinates and floating-point view indices.
    arrays = {key: np.zeros((0,)) for key in ("view", "uv_h", "uv_v", "overlap", "cycle_px", "precision")}
    arrays.update(point_id=np.zeros((0,), dtype=np.int64), xyz=np.zeros((0, 3)), meta=np.asarray(json.dumps(meta)))
    np.savez_compressed(root / "matches/unmatched.npz", **arrays)
    with (root / "fits.jsonl").open("a") as stream:
        stream.write(json.dumps({"name": name, "status": "no_matches", "num_obs": 0}) + "\n")
    with (root / "cameras.jsonl").open("a") as stream:
        stream.write(json.dumps({"name": name, "status": "no_matches", "decision": "unchanged", "tiers": []}) + "\n")
    result = u._dense_intrinsics_evidence(workspace, ["historic.jpg", name])
    assert result["processed_images"] == 2 and result["correspondences"] == 12
    assert result["accepted_updates"] == 0 and result["decision_counts"]["unchanged"] == 1


@pytest.mark.parametrize("field,value", [("num_obs", 13), ("name", "another.jpg"), ("status", "error: model failure")])
def test_inconsistent_or_error_fit_is_rejected(tmp_path, field, value):
    workspace, root, _ = evidence(tmp_path)
    rewrite_row(root / "fits.jsonl", **{field: value})
    with pytest.raises(ValueError):
        u._dense_intrinsics_evidence(workspace, ["historic.jpg"])


@pytest.mark.parametrize("field,value", [("name", "another.jpg"), ("decision", "invented"), ("status", "error")])
def test_inconsistent_or_error_decision_is_rejected(tmp_path, field, value):
    workspace, root, _ = evidence(tmp_path)
    rewrite_row(root / "cameras.jsonl", **{field: value})
    with pytest.raises(ValueError):
        u._dense_intrinsics_evidence(workspace, ["historic.jpg"])


@pytest.mark.parametrize("corruption", ["shape", "nonfinite", "object"])
def test_malformed_numeric_matches_are_rejected_without_pickle(tmp_path, corruption):
    workspace, root, arrays = evidence(tmp_path)
    if corruption == "shape":
        arrays["uv_h"] = np.zeros((12, 3))
    elif corruption == "nonfinite":
        arrays["xyz"][0, 0] = np.nan
    else:
        arrays["uv_h"] = np.array([[{"unsafe": "object"}]], dtype=object)
    np.savez_compressed(root / "matches/historic.npz", **arrays)
    with pytest.raises(ValueError):
        u._dense_intrinsics_evidence(workspace, ["historic.jpg"])


@pytest.mark.parametrize("missing", ["fit/historic.npz", "../models_geolocalized/cameras.bin"])
def test_accepted_decision_without_fit_or_new_model_fails(tmp_path, missing):
    workspace, root, _ = evidence(tmp_path, decision="focal")
    (root / missing).unlink()
    with pytest.raises(ValueError):
        u._dense_intrinsics_evidence(workspace, ["historic.jpg"])


@pytest.fixture
def actual_camera_models(tmp_path):
    """Real serialized COLMAP models; synthetic geometry is only a unit fixture."""
    pc = pytest.importorskip("pycolmap")
    workspace = tmp_path / "workspace"
    before = workspace / "scenes/church/dg/models_geolocalized"
    before.mkdir(parents=True)
    reconstruction = pc.synthesize_dataset(pc.SyntheticDatasetOptions())
    reconstruction.write(str(before))
    image = next(iter(reconstruction.images.values()))
    evidence_root = before.parent.with_name("dg-dense_intrinsics") / "intrinsics"
    evidence_root.mkdir(parents=True)
    config = {"_python": Path(sys.executable), "timeout_seconds": 60}
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": str(Path(pc.__file__).resolve().parent.parent)}
    return pc, workspace, before, evidence_root, image.image_id, image.name, config, env


def test_camera_comparison_retains_actual_input_when_no_update_was_accepted(actual_camera_models, tmp_path):
    _, workspace, _, root, _, name, config, env = actual_camera_models
    (root / "cameras.jsonl").write_text(json.dumps({"name": name, "decision": "rejected"}) + "\n")
    result = u._dense_camera_changes(workspace, config, env, tmp_path)
    assert result["changed_camera_intrinsics"] == 0
    assert result["unchanged_camera_intrinsics"] == 1 and result["unregistered_output_cameras"] == 0
    row = result["camera_comparisons"][0]
    assert row["retained_input"] is True and row["input_camera"] == row["output_camera"]
    assert not (root.parent / "models_geolocalized").exists()


def test_camera_comparison_decodes_changed_intrinsics_from_actual_new_model(actual_camera_models, tmp_path):
    pc, workspace, before, root, image_id, name, config, env = actual_camera_models
    changed = pc.Reconstruction(str(before))
    camera = changed.cameras[changed.images[image_id].camera_id]
    parameters = camera.params.copy()
    parameters[0] *= 1.1
    camera.params = parameters
    destination = root.parent / "models_geolocalized"
    destination.mkdir()
    changed.write(str(destination))
    (root / "cameras.jsonl").write_text(json.dumps({"name": name, "decision": "focal"}) + "\n")
    result = u._dense_camera_changes(workspace, config, env, tmp_path)
    assert result["changed_camera_intrinsics"] == 1 and result["unchanged_camera_intrinsics"] == 0
    row = result["camera_comparisons"][0]
    assert row["output_camera"]["params"][0] == pytest.approx(row["input_camera"]["params"][0] * 1.1)
    assert row["retained_input"] is False and row["registered_in_output"] is True


def test_accepted_camera_must_exist_in_actual_new_model(actual_camera_models, tmp_path):
    pc, workspace, before, root, image_id, name, config, env = actual_camera_models
    changed = pc.Reconstruction(str(before))
    changed.images[image_id].name = "unrelated-image.jpg"
    destination = root.parent / "models_geolocalized"
    destination.mkdir()
    changed.write(str(destination))
    (root / "cameras.jsonl").write_text(json.dumps({"name": name, "decision": "focal"}) + "\n")
    with pytest.raises(ValueError, match="Historic research stage failed"):
        u._dense_camera_changes(workspace, config, env, tmp_path)
    assert "Accepted camera absent from new calibrated model" in (tmp_path / "camera-comparison.log").read_text()
