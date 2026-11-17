"""Protect retained runtime snapshots while making root-owned SIF files readable."""
import importlib.util
import os
from pathlib import Path
import json

import pytest

spec = importlib.util.spec_from_file_location("packaging", Path(__file__).parents[1] /
    "scripts/historic_reconstruction/finalize_learned_runtime.py")
packaging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packaging)


def test_permission_preparation_preserves_retained_hardlinked_file(tmp_path):
    prior = tmp_path / "retained-checkpoint"
    prior.write_bytes(b"retained scientific asset")
    prior.chmod(0o600)
    sandbox = tmp_path / "rootfs"
    sandbox.mkdir(mode=0o700)
    target = sandbox / "model.bin"
    os.link(prior, target)
    result = packaging.readable_copy_permissions(sandbox)
    assert prior.read_bytes() == target.read_bytes() == b"retained scientific asset"
    assert prior.stat().st_mode & 0o777 == 0o600
    assert target.stat().st_mode & 0o777 == 0o644
    assert not target.samefile(prior)
    assert result["linked_files_copied_before_chmod"] == 1
    assert result["shared_inodes_modified"] is False


def test_readable_executable_and_external_symlink_are_unchanged(tmp_path):
    source = tmp_path / "interpreter"
    source.write_bytes(b"executable fixture")
    source.chmod(0o755)
    external = tmp_path / "external-private-file"
    external.write_bytes(b"untouched")
    external.chmod(0o600)
    sandbox = tmp_path / "rootfs"
    sandbox.mkdir()
    os.link(source, sandbox / "python")
    (sandbox / "external").symlink_to(external)
    result = packaging.readable_copy_permissions(sandbox)
    assert (sandbox / "python").samefile(source)
    assert source.stat().st_mode & 0o777 == 0o755
    assert external.stat().st_mode & 0o777 == 0o600
    assert result["linked_files_copied_before_chmod"] == 0


def test_old_cuda_acceptance_cannot_gate_new_runtime_image(tmp_path):
    sandbox = tmp_path / "rootfs"
    config_path = sandbox / "opt/historic-learned/original_sfm-operator-config.json"
    config_path.parent.mkdir(parents=True)
    config = {"source": {"sha256": "source"}, "python": {"sha256": "python"},
              "assets": {"cuda_runtime": {"sha256": "cuda129"}}}
    config_path.write_text(json.dumps(config))
    summary = {"stage": "original_sfm", "upstream_execution": True, "models": [{"points3D": 120}]}
    report_path = tmp_path / "research-report.json"
    report = {"metrics": summary, "source_sha256": "source", "runtime_pins": {
        "python_sha256": "python", "dependencies": [], "assets": {"cuda_runtime": "cuda126"}}}
    report_path.write_text(json.dumps(report))
    result_path = tmp_path / "result.json"
    result = {"success": True, "status": "completed", "summary": summary, "artifacts": [{"metadata": {
        "role": "report", "sha256": packaging.sha(report_path), "bytes": report_path.stat().st_size}}]}
    result_path.write_text(json.dumps(result))
    with pytest.raises(AssertionError, match="different runtime revision"):
        packaging.check_direct_acceptance(result_path, report_path, sandbox)
    earlier = packaging.check_direct_acceptance(result_path, report_path, sandbox, allow_runtime_revision=True)
    assert earlier["runtime_pins_match"] is False
    assert earlier["runtime_revision"]["earlier_direct_pins"]["assets"]["cuda_runtime"] == "cuda126"
    assert earlier["runtime_revision"]["candidate_image_pins"]["assets"]["cuda_runtime"] == "cuda129"
    report["runtime_pins"]["assets"]["cuda_runtime"] = "cuda129"
    report_path.write_text(json.dumps(report))
    # Merely editing the downloaded report must still fail its response checksum.
    with pytest.raises(AssertionError):
        packaging.check_direct_acceptance(result_path, report_path, sandbox)
    result["artifacts"][0]["metadata"].update(sha256=packaging.sha(report_path), bytes=report_path.stat().st_size)
    result_path.write_text(json.dumps(result))
    assert packaging.check_direct_acceptance(result_path, report_path, sandbox)["matches_staged_runtime_pins"] is True
