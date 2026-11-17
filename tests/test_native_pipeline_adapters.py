import subprocess
from unittest.mock import patch
from flask import Flask

from services.native_pipeline_adapters import (
    AdapterExecutionRequest,
    BuiltinWebHdpAdapter,
    ContainerCliAdapter,
    HpcLinkExecutionAdapter,
    LegacyHdpPythonAdapter,
    LocalCliAdapter,
)


@patch("subprocess.run")
def test_legacy_adapter_builds_cli_arguments(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=["python", "main.py"],
        returncode=0,
        stdout="ok",
        stderr="",
    )
    adapter = LegacyHdpPythonAdapter()
    request = AdapterExecutionRequest(
        step_id="legacy_step",
        profile={"entrypoint": ["python", "main.py"], "working_directory": "."},
        workdir="/tmp",
        inputs={"input_file": "/tmp/model.glb", "flags": ["a", "b"]},
        parameters={"dry_run": True, "count": 3},
    )

    result = adapter.execute(request)

    assert result["success"] is True
    command = mock_run.call_args.kwargs["args"] if "args" in mock_run.call_args.kwargs else mock_run.call_args.args[0]
    assert command[:2] == ["python", "main.py"]
    assert "--input-file" in command
    assert "--flags" in command
    assert "--dry-run" in command
    assert "--count" in command


@patch("subprocess.run")
def test_local_cli_adapter_uses_declared_entrypoint(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=["local-tool"],
        returncode=0,
        stdout="done",
        stderr="",
    )
    adapter = LocalCliAdapter()
    request = AdapterExecutionRequest(
        step_id="local_step",
        profile={"entrypoint": ["local-tool", "run"], "working_directory": "."},
        workdir="/tmp",
        inputs={"input_path": "/tmp/in.txt"},
        parameters={"mode": "fast"},
    )

    adapter.execute(request)

    command = mock_run.call_args.kwargs["args"] if "args" in mock_run.call_args.kwargs else mock_run.call_args.args[0]
    assert command[:2] == ["local-tool", "run"]
    assert "--input-path" in command
    assert "--mode" in command


@patch("subprocess.run")
def test_container_cli_adapter_builds_docker_command(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=["docker"],
        returncode=0,
        stdout="container ok",
        stderr="",
    )
    adapter = ContainerCliAdapter()
    request = AdapterExecutionRequest(
        step_id="container_step",
        profile={
            "runtime": "docker",
            "image": "example/image:latest",
            "entrypoint": ["python", "/app/main.py"],
            "config": {"bind_mounts": [{"source": "/tmp/in", "target": "/data/in"}]},
        },
        workdir="/tmp",
        inputs={"input_path": "/data/in/model.glb"},
        parameters={"quality": "preview"},
    )

    adapter.execute(request)

    command = mock_run.call_args.kwargs["args"] if "args" in mock_run.call_args.kwargs else mock_run.call_args.args[0]
    assert command[:5] == ["docker", "run", "--rm", "-v", "/tmp/in:/data/in"]
    assert "example/image:latest" in command
    assert "--input-path" in command
    assert "--quality" in command


@patch("subprocess.run")
def test_container_cli_adapter_can_execute_webhdp_contract(mock_run, tmp_path):
    input_file = tmp_path / "model.glb"
    input_file.write_bytes(b"glTF")

    def fake_run(command, cwd=None, env=None, capture_output=None, text=None, timeout=None, check=None):
        response_mount = next(command[index + 1] for index, item in enumerate(command) if item == "-v" and command[index + 1].endswith(":/tmp/webhdp/response"))
        response_dir = response_mount.split(":", 1)[0]
        output_mount = next(command[index + 1] for index, item in enumerate(command) if item == "-v" and command[index + 1].endswith(":/outputs"))
        output_dir = output_mount.split(":", 1)[0]
        report_path = f"{output_dir}/report.json"
        with open(report_path, "w", encoding="utf-8") as handle:
            handle.write("{}")
        with open(f"{response_dir}/response.json", "w", encoding="utf-8") as handle:
            handle.write('{"success": true, "outputs": {"report": "/outputs/report.json"}, "artifacts": [{"name": "report", "remote_path": "/outputs/report.json"}]}')
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

    mock_run.side_effect = fake_run
    adapter = ContainerCliAdapter()
    request = AdapterExecutionRequest(
        step_id="model_profiler",
        profile={
            "runtime": "docker",
            "image": "webhdp-model-profiler:local",
            "entrypoint": ["python", "/app/component_runner.py"],
            "config": {"webhdp_contract": True},
        },
        workdir=str(tmp_path / "work"),
        inputs={"input_file": str(input_file)},
        parameters={"include_geometry": True},
    )

    result = adapter.execute(request)

    assert result["success"] is True
    assert result["outputs"]["report"].endswith("outputs/report.json")
    assert result["artifacts"][0]["path"].endswith("outputs/report.json")
    command = mock_run.call_args.args[0]
    assert command[:4] == ["docker", "run", "--rm", "--network"]
    assert "WEBHDP_COMPONENT_REQUEST=/tmp/webhdp/request.json" in command
    assert "WEBHDP_COMPONENT_KEY=model_profiler" in command


@patch("subprocess.run")
def test_container_cli_adapter_builds_singularity_command(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=["singularity"],
        returncode=0,
        stdout="container ok",
        stderr="",
    )
    adapter = ContainerCliAdapter()
    request = AdapterExecutionRequest(
        step_id="container_step",
        profile={
            "runtime": "singularity",
            "image": "/containers/component.sif",
            "entrypoint": ["python", "/app/main.py"],
            "config": {"bind_mounts": [{"source": "/tmp/in", "target": "/data/in"}]},
        },
        workdir="/tmp",
        inputs={"input_path": "/data/in/model.glb"},
        parameters={},
    )

    adapter.execute(request)

    command = mock_run.call_args.kwargs["args"] if "args" in mock_run.call_args.kwargs else mock_run.call_args.args[0]
    assert command[:4] == ["singularity", "exec", "--bind", "/tmp/in:/data/in"]
    assert "/containers/component.sif" in command
    assert "--input-path" in command


def test_builtin_adapter_reports_unknown_handler():
    adapter = BuiltinWebHdpAdapter({})
    request = AdapterExecutionRequest(
        step_id="builtin_step",
        profile={"handler": "missing"},
        workdir="/tmp",
    )

    result = adapter.execute(request)

    assert result["success"] is False
    assert result["status"] == "failed"
    assert "Unknown builtin handler" in result["error"]


def test_hpc_link_adapter_forwards_component_payload_to_allocation_service():
    class FakeHpcAllocationService:
        def __init__(self):
            self.payload = None

        def get_active_for_session(self, session_id, *, user_id=None):
            assert session_id == 42 and user_id == 88
            return {"allocation_id": "alloc-1"}

        def stage_local_files(self, allocation, paths):
            assert allocation == {"allocation_id": "alloc-1"}
            return {"staged_files": [{"local_path": path, "remote_path": f"/remote/{path.split('/')[-1]}"} for path in paths]}

        def execute_component(self, allocation, payload):
            assert allocation == {"allocation_id": "alloc-1"}
            self.payload = payload
            return {"success": True, "artifacts": [{"path": "/remote/out.png"}]}

    app = Flask(__name__)
    app.hpc_allocation_service = FakeHpcAllocationService()
    adapter = HpcLinkExecutionAdapter()
    request = AdapterExecutionRequest(
        step_id="fast_renderer",
        profile={"handler": "fast_renderer"},
        workdir="/tmp/run",
        inputs={"input_path": "/data/model.glb"},
        parameters={"width": 512},
        metadata={
            "session_id": 42,
            "initiated_by_user_id": 88,
            "record_context": {"record_id": 7, "file_path": "/data/model.glb", "secret": "ignored"},
        },
    )

    with app.app_context():
        result = adapter.execute(request)

    assert result["success"] is True
    assert result["status"] == "completed"
    assert app.hpc_allocation_service.payload["component_key"] == "fast_renderer"
    assert app.hpc_allocation_service.payload["record_context"] == {
        "record_id": 7,
        "file_path": "/data/model.glb",
        "filename": None,
        "specific_output_dir": None,
        "index": None,
        "total_records": None,
    }


def test_hpc_staging_includes_nested_archived_texture_without_other_records(tmp_path):
    import sqlite3
    hdpc = tmp_path / 'inputs.hdpc'
    model = tmp_path / 'model.obj'
    archive = tmp_path / 'textures.zip'
    texture = tmp_path / 'textures' / 'albedo.jpg'
    other = tmp_path / 'other.obj'
    texture.parent.mkdir()
    for path in (model, archive, texture, other):
        path.write_bytes(b'input')
    with sqlite3.connect(hdpc) as conn:
        conn.execute('CREATE TABLE source_files (file_id INTEGER, parent_file_id INTEGER, absolute_path TEXT, pipeline_source TEXT)')
        conn.execute('CREATE TABLE record_files_map (record_id INTEGER, file_id INTEGER)')
        conn.executemany('INSERT INTO source_files VALUES (?, ?, ?, ?)', [
            (1, None, str(model), 'scan'), (2, 1, str(archive), 'scan'),
            (3, 2, str(texture), 'scan'), (4, None, str(other), 'scan'),
        ])
        conn.executemany('INSERT INTO record_files_map VALUES (?, ?)', [(1, 1), (1, 2), (2, 4)])
    request = AdapterExecutionRequest(
        step_id='fast_renderer', profile={}, workdir=str(tmp_path), inputs={}, parameters={},
        metadata={'execution_context': {'hdpc_path': str(hdpc)}, 'record_context': {'record_id': 1}},
    )
    assert set(HpcLinkExecutionAdapter._local_paths_for_request(request)) == {str(model), str(archive), str(texture)}


@patch("subprocess.run")
def test_local_sif_checksum_mismatch_never_starts_container(mock_run, tmp_path):
    image = tmp_path / "component.sif"
    image.write_bytes(b"replacement image")
    request = AdapterExecutionRequest(step_id="verified", profile={"runtime": "singularity", "image": str(image), "sif_sha256": "0" * 64}, workdir=str(tmp_path))
    result = ContainerCliAdapter().execute(request)
    assert result["success"] is False
    assert "checksum changed" in result["error"]
    mock_run.assert_not_called()
