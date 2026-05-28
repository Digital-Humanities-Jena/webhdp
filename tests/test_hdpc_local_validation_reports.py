import json
import sqlite3

from services.hdpc_local_service import add_local_source_files


def test_add_local_source_files_persists_validation_report_json(tmp_path):
    hdpc_path = str(tmp_path / "session.hdpc")
    edm_path = tmp_path / "edm.xml"
    edm_path.write_text("<rdf:RDF />", encoding="utf-8")

    report = {
        "valid": False,
        "errors": ["[Local EDM Validator] missing edm:rights"],
        "warnings": ["[Local EDM Validator] short description"],
        "details": {
            "remote": {
                "validator": "local-edm-validator",
                "raw": {"validationResults": [{"step": "VALIDATE_INTERNAL", "status": "FAILED"}]},
            }
        },
    }

    result = add_local_source_files(
        hdpc_path,
        absolute_file_paths=[str(edm_path)],
        pipeline_name="lod_generation",
        step_name="xml_generator",
        validation_reports={str(edm_path): report},
    )

    assert result["success"] is True

    conn = sqlite3.connect(hdpc_path)
    try:
        row = conn.execute(
            "SELECT validation_report_json, error_message FROM source_files WHERE filename = ?",
            ("edm.xml",),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    persisted = json.loads(row[0])
    assert persisted["details"]["remote"]["validator"] == "local-edm-validator"
    assert persisted["details"]["remote"]["raw"]["validationResults"][0]["step"] == "VALIDATE_INTERNAL"
    assert row[1] == "[Local EDM Validator] missing edm:rights"
