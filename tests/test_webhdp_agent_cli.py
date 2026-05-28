import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("webhdp_agent_cli", ROOT / "scripts" / "webhdp_agent_cli.py")
webhdp_agent_cli = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(webhdp_agent_cli)


def test_build_artifact_audit_reports_complete_record():
    payload = {
        "data": {
            "records": [
                {
                    "record_id": 1,
                    "record_status": "published",
                    "source_file_path": "/data/model.ply",
                    "files": [
                        {"filename": "model.usdz"},
                        {"filename": "view_1.png"},
                        {"filename": "view_2.png"},
                        {"filename": "view_3.png"},
                        {"filename": "view_4.png"},
                        {"filename": "view_5.png"},
                        {"filename": "edm.xml"},
                        {"filename": "mets.xml"},
                        {"filename": "iiif.json"},
                        {"filename": "edm.validation.json"},
                    ],
                }
            ]
        }
    }

    audit = webhdp_agent_cli.build_artifact_audit(payload)

    assert audit["ok"] is True
    assert audit["summary"]["complete"] == 1
    assert audit["records"][0]["missing"] == []


def test_build_artifact_audit_reports_missing_outputs():
    payload = {"data": {"records": [{"record_id": 1, "source_file_path": "/data/model.ply", "files": []}]}}

    audit = webhdp_agent_cli.build_artifact_audit(payload)

    assert audit["ok"] is False
    assert audit["summary"]["incomplete"] == 1
    assert "usdz" in audit["records"][0]["missing"]
    assert "png_renders" in audit["records"][0]["missing"]


def test_build_artifact_audit_can_require_real_files(tmp_path):
    files = []
    for name in [
        "model.ply",
        "model.usdz",
        "view_1.png",
        "view_2.png",
        "view_3.png",
        "view_4.png",
        "view_5.png",
        "edm.xml",
        "mets.xml",
        "iiif.json",
    ]:
        path = tmp_path / name
        path.write_text("x", encoding="utf-8")
        files.append({"filename": name, "absolute_path": str(path)})
    validation = tmp_path / "edm.validation.json"
    validation.write_text('{"valid": true}', encoding="utf-8")
    files.append({"filename": "edm.validation.json", "absolute_path": str(validation)})
    payload = {"data": {"records": [{"record_id": 1, "files": files}]}}

    audit = webhdp_agent_cli.build_artifact_audit(payload, require_existing_files=True)

    assert audit["ok"] is True


def test_secret_scan_detects_redacted_sensitive_patterns(tmp_path):
    log_path = tmp_path / "job.log"
    log_path.write_text("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456\n", encoding="utf-8")

    result = webhdp_agent_cli.scan_secret_paths([str(log_path)])

    assert result["ok"] is False
    assert result["finding_count"] == 1
    assert result["findings"][0]["pattern"] == "bearer_token"
