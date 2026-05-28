import json
import tempfile
from pathlib import Path

from services.hdpc_local_service import inspect_hdpc_project
from services.hdpc_scan_service import create_and_scan_hdpc_project


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "test_data" / "workflow_fixtures"
MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"


def _walk_tree(nodes):
    for node in nodes or []:
        yield node
        yield from _walk_tree(node.get("children") or [])


def _bundle_filenames(root_node):
    return sorted({node["filename"] for node in _walk_tree([root_node])})


def _tree_by_primary(file_tree):
    return {node["filename"]: node for node in file_tree}


def _statuses_by_filename(file_tree):
    return {node["filename"]: node["status"] for node in _walk_tree(file_tree)}


def test_workflow_fixture_manifest_matches_scanner_contract():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory(prefix="webhdp-fixtures-") as temp_dir:
        temp_root = Path(temp_dir)

        for case in manifest["cases"]:
            case_root = FIXTURE_ROOT / case["path"]
            hdpc_path = temp_root / f"{case['id']}.hdpc"
            output_root = temp_root / f"{case['id']}_out"

            result = create_and_scan_hdpc_project(
                hdpc_path=str(hdpc_path),
                data_in_path=str(case_root),
                data_out_path=str(output_root),
                project_name=f"Fixture {case['id']}",
                short_code="WFIX",
                modalities=["3d_model", "image", "text"],
                scan_options=case["scan_options"],
                batch_entity=case["scan_options"].get("batchEntity"),
            )

            assert result["success"] is True, case["id"]

            inspect_data = inspect_hdpc_project(str(hdpc_path), show_files=True)
            file_tree = inspect_data["file_tree"]
            expected = case["expected"]

            assert len(file_tree) == expected["record_count"], case["id"]

            primary_sources = sorted(node["filename"] for node in file_tree)
            assert primary_sources == sorted(expected["primary_sources"]), case["id"]

            by_primary = _tree_by_primary(file_tree)
            for primary_name, expected_members in expected.get("bundle_members", {}).items():
                assert primary_name in by_primary, case["id"]
                assert sorted(expected_members) == _bundle_filenames(by_primary[primary_name]), case["id"]

            statuses = _statuses_by_filename(file_tree)
            for filename, expected_status in expected.get("statuses", {}).items():
                assert statuses.get(filename) == expected_status, f"{case['id']}:{filename}"

            if case["id"] == "dependency_obj_textures_archive":
                archive_path = output_root / "archives" / "test_model_textures.zip"
                assert archive_path.exists()
