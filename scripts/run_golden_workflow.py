#!/usr/bin/env python3
"""Run the local golden sample workflow for developer onboarding."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.hdpc_local_service import inspect_hdpc_project
from services.hdpc_scan_service import create_and_scan_hdpc_project
from services.msf_service import MSFService


FIXTURE_ROOT = ROOT / "test_data" / "workflow_fixtures"
MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"
DEFAULT_CASE_ID = "root_stem_mixed"
DEFAULT_MSF_PATH = FIXTURE_ROOT / "msf" / "workflow_minimal.csv"


def _walk_tree(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for node in nodes or []:
        flattened.append(node)
        flattened.extend(_walk_tree(node.get("children") or []))
    return flattened


def _load_case(case_id: str) -> dict[str, Any]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for case in manifest.get("cases", []):
        if case.get("id") == case_id:
            return case
    raise ValueError(f"Golden workflow case not found: {case_id}")


def _assert_equal(label: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def run_golden_workflow(case_id: str = DEFAULT_CASE_ID, output_dir: str | None = None) -> dict[str, Any]:
    """Run scan and MSF checks against the curated golden fixture."""
    case = _load_case(case_id)
    case_root = FIXTURE_ROOT / case["path"]
    msf_path = DEFAULT_MSF_PATH
    expected = case["expected"]

    cleanup_output = output_dir is None
    work_root = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="webhdp-golden-"))
    if work_root.exists() and cleanup_output is False:
        shutil.rmtree(work_root)
    work_root.mkdir(parents=True, exist_ok=True)

    try:
        hdpc_path = work_root / f"{case_id}.hdpc"
        data_out_path = work_root / f"{case_id}_out"

        scan_result = create_and_scan_hdpc_project(
            hdpc_path=str(hdpc_path),
            data_in_path=str(case_root),
            data_out_path=str(data_out_path),
            project_name=f"Golden Workflow {case_id}",
            short_code="GOLD",
            modalities=["3d_model", "image", "text"],
            scan_options=case["scan_options"],
            batch_entity=case["scan_options"].get("batchEntity"),
        )
        if not scan_result.get("success"):
            raise AssertionError(f"Scan failed: {scan_result}")

        inspect_data = inspect_hdpc_project(str(hdpc_path), show_files=True)
        file_tree = inspect_data["file_tree"]
        flattened = _walk_tree(file_tree)
        primary_sources = sorted(node["filename"] for node in file_tree)

        _assert_equal("record_count", len(file_tree), expected["record_count"])
        _assert_equal("primary_sources", primary_sources, sorted(expected["primary_sources"]))

        statuses = {node["filename"]: node["status"] for node in flattened}
        for filename, expected_status in expected.get("statuses", {}).items():
            _assert_equal(f"status:{filename}", statuses.get(filename), expected_status)

        msf_service = MSFService()
        msf_df, _columns = msf_service.parse_msf_file(str(msf_path))
        msf_validation = msf_service.validate_msf_against_directory(
            msf_df,
            primary_sources,
            filename_column="Filename",
            directory_root=str(case_root),
        ).to_dict()

        expected_msf_rows = {
            "temple_column.obj",
            "ceramic_bowl.fbx",
            "bronze_helmet.glb",
        }
        matched = set(msf_validation["matched_files"])
        if not expected_msf_rows.issubset(matched):
            raise AssertionError(
                "MSF did not match all golden primary files: "
                f"missing {sorted(expected_msf_rows - matched)}"
            )

        summary = {
            "success": True,
            "case_id": case_id,
            "fixture_path": str(case_root.relative_to(ROOT)),
            "msf_path": str(msf_path.relative_to(ROOT)),
            "output_dir": str(work_root),
            "record_count": len(file_tree),
            "primary_sources": primary_sources,
            "msf_matched_count": len(expected_msf_rows.intersection(matched)),
            "msf_missing_files": sorted(set(msf_validation["missing_files"]).intersection(expected_msf_rows)),
            "hdpc_created": hdpc_path.exists(),
        }
        return summary
    finally:
        if cleanup_output:
            shutil.rmtree(work_root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the WebHDP golden sample workflow.")
    parser.add_argument("--case-id", default=DEFAULT_CASE_ID, help="Fixture case ID to run.")
    parser.add_argument("--output-dir", default=None, help="Optional output directory to keep generated .hdpc artifacts.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only.")
    args = parser.parse_args()

    summary = run_golden_workflow(case_id=args.case_id, output_dir=args.output_dir)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print("Golden workflow completed successfully.")
        print(f"- Case: {summary['case_id']}")
        print(f"- Records: {summary['record_count']}")
        print(f"- Primary files: {', '.join(summary['primary_sources'])}")
        print(f"- MSF matched golden files: {summary['msf_matched_count']}")
        if args.output_dir:
            print(f"- Output kept at: {summary['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
