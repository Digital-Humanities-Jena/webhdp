import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENT_DIR = ROOT / "external_code" / "image_metadata_extractor"
EXTRACTOR = COMPONENT_DIR / "extractor.py"
MINIMAL_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x02"
    b"\x00\x00\x00\x03"
    b"\x08\x02\x00\x00\x00"
    b"\x00\x00\x00\x00"
)


def test_image_metadata_extractor_cli_writes_png_report(tmp_path):
    image_path = tmp_path / "tiny.png"
    output_path = tmp_path / "report.json"
    image_path.write_bytes(MINIMAL_PNG)

    result = subprocess.run(
        [
            sys.executable,
            str(EXTRACTOR),
            "--input-file",
            str(image_path),
            "--output-path",
            str(output_path),
            "--no-include-hash",
        ],
        cwd=COMPONENT_DIR,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert result.returncode == 0
    assert report["success"] is True
    assert report["image"]["format"] == "png"
    assert report["image"]["width"] == 2
    assert report["image"]["height"] == 3
    assert "sha256" not in report["input"]


def test_image_metadata_extractor_component_request_response(tmp_path):
    image_path = tmp_path / "tiny.png"
    request_path = tmp_path / "request.json"
    response_path = tmp_path / "response.json"
    report_path = tmp_path / "component-report.json"
    image_path.write_bytes(MINIMAL_PNG)
    request_path.write_text(
        json.dumps(
            {
                "inputs": {"input_file": str(image_path)},
                "parameters": {
                    "output_path": str(report_path),
                    "include_hash": True,
                    "probe_bytes": 128,
                },
            }
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["WEBHDP_COMPONENT_REQUEST"] = str(request_path)
    env["WEBHDP_COMPONENT_RESPONSE"] = str(response_path)
    result = subprocess.run(
        [sys.executable, str(EXTRACTOR)],
        cwd=COMPONENT_DIR,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    response = json.loads(response_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert result.returncode == 0
    assert response["success"] is True
    assert response["outputs"]["metadata_report"] == str(report_path.resolve())
    assert report["image"]["mime_type"] == "image/png"
    assert "sha256" in report["input"]
