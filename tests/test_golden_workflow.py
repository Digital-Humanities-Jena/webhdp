from scripts.run_golden_workflow import run_golden_workflow


def test_golden_workflow_runs_fixture_scan_and_msf_match(tmp_path):
    summary = run_golden_workflow(output_dir=str(tmp_path / "golden"))

    assert summary["success"] is True
    assert summary["case_id"] == "root_stem_mixed"
    assert summary["record_count"] == 3
    assert summary["msf_matched_count"] == 3
    assert summary["msf_missing_files"] == []
    assert summary["hdpc_created"] is True
    assert summary["primary_sources"] == [
        "bronze_helmet.glb",
        "ceramic_bowl.fbx",
        "temple_column.obj",
    ]
