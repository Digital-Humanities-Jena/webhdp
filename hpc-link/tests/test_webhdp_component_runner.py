import importlib.util
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch


def _load_runner():
    runner_path = Path(__file__).resolve().parents[1] / "scripts" / "webhdp_component_runner.py"
    spec = importlib.util.spec_from_file_location("webhdp_component_runner", runner_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generic_singularity_component_builds_command_and_reads_response(tmp_path, monkeypatch):
    runner = _load_runner()
    request_path = tmp_path / "request.json"
    response_path = tmp_path / "response.json"
    input_dir = tmp_path / "inputs"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    output_dir.mkdir()
    request = {
        "component_key": "gltf_validator",
        "remote_input_dir": str(input_dir),
        "remote_output_dir": str(output_dir),
        "profile": {
            "image": "/work/components/gltf_validator.sif",
            "entrypoint": ["python", "/app/validator.py"],
        },
    }
    request_path.write_text(json.dumps(request), encoding="utf-8")
    monkeypatch.setenv("WEBHDP_COMPONENT_REQUEST", str(request_path))
    monkeypatch.setenv("WEBHDP_COMPONENT_RESPONSE", str(response_path))
    monkeypatch.setenv("SINGULARITY_BIN", "/usr/bin/singularity")

    def fake_run(cmd, **kwargs):
        response_path.write_text(
            json.dumps(
                {
                    "success": True,
                    "outputs": {"report": "/outputs/report.json"},
                    "artifacts": [{"remote_path": "/outputs/report.json"}],
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="ok", stderr="")

    with patch("subprocess.run", side_effect=fake_run) as mock_run:
        result = runner._generic_singularity_component("gltf_validator", request)

    command = mock_run.call_args.args[0]
    assert command[:7] == ["/usr/bin/singularity", "exec", "--cleanenv", "--containall", "--no-home", "--pwd", "/outputs"]
    assert "/work/components/gltf_validator.sif" in command
    assert command[-2:] == ["python", "/app/validator.py"]
    assert result["success"] is True
    env = mock_run.call_args.kwargs["env"]
    assert env["SINGULARITYENV_WEBHDP_COMPONENT_REQUEST"] == str(request_path.resolve())
    assert env["SINGULARITYENV_WEBHDP_OUTPUT_DIR"] == "/outputs"
    assert result["outputs"]["report"] == str(output_dir.resolve() / "report.json")
    assert result["artifacts"][0]["remote_path"] == str(output_dir.resolve() / "report.json")
