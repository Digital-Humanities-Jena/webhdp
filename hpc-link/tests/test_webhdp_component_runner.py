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
    assert env["SINGULARITYENV_WEBHDP_COMPONENT_REQUEST"] == str(request_path.with_name("request.container.json").resolve())
    assert env["SINGULARITYENV_WEBHDP_OUTPUT_DIR"] == "/outputs"
    assert result["outputs"]["report"] == str(output_dir.resolve() / "report.json")
    assert result["artifacts"][0]["remote_path"] == str(output_dir.resolve() / "report.json")
    scratch_bind = next(command[i + 1] for i, arg in enumerate(command[:-1]) if arg == '--bind' and command[i + 1].endswith(':/tmp'))
    assert not Path(scratch_bind.removesuffix(':/tmp')).exists()


def test_staged_mapping_preserves_duplicate_names_and_rejects_escape(tmp_path):
    import pytest
    from app.schemas.apps import WebHdpComponentRunRequest
    runner = _load_runner()
    inputs = tmp_path / 'inputs'
    paths = []
    for folder in ['first', 'second']:
        path = inputs / folder / 'model.gltf'
        path.parent.mkdir(parents=True)
        path.write_text('{}')
        paths.append(path)
    mappings = [{'local_path': '/source/' + str(i) + '/model.gltf', 'remote_path': str(path)} for i, path in enumerate(paths)]
    request = WebHdpComponentRunRequest(component_key='fast_renderer', inputs={'input_files':[m['local_path'] for m in mappings]}, staged_files=mappings).model_dump()
    originals, remotes = runner._collect_render_inputs(request, inputs)
    assert remotes == paths
    assert len(originals) == 2
    request['staged_files'][0]['remote_path'] = str(tmp_path / 'private')
    with pytest.raises(ValueError):
        runner._collect_render_inputs(request, inputs)


def test_changed_sif_is_rejected_before_process_start(tmp_path):
    import pytest
    runner = _load_runner()
    image = tmp_path / 'changed.sif'
    image.write_bytes(b'changed content')
    with patch.object(runner.subprocess, 'run') as process:
        with pytest.raises(ValueError, match='checksum changed'):
            runner._generic_singularity_component('validator', {'profile': {'image': str(image), 'sif_sha256': '0' * 64}})
    process.assert_not_called()


def test_explicit_optimized_inputs_do_not_render_originals(tmp_path):
    runner = _load_runner()
    model = tmp_path / 'optimized.glb'
    model.write_bytes(b'model')
    originals, paths = runner._collect_render_inputs({
        'inputs': {'input_files': str(model)},
        'batch_records': [{'file_path': '/original/source.glb'}],
    }, tmp_path)
    assert originals == [str(model)]
    assert paths == [model]


def test_repeated_render_steps_do_not_overwrite_remote_artifacts(tmp_path):
    runner = _load_runner()
    request = {'remote_output_dir': str(tmp_path), 'step_id': 'fast_renderer'}
    first = runner._component_output_dir('fast_renderer', request)
    second = runner._component_output_dir('fast_renderer', request)
    assert first != second
    assert first.parent == second.parent == tmp_path


def test_gpu_container_maps_nested_inputs_and_rejects_stale_response(tmp_path, monkeypatch):
    runner = _load_runner()
    inputs = tmp_path / 'inputs'; inputs.mkdir()
    nested = inputs / 'second' / 'model.glb'; nested.parent.mkdir(); nested.write_bytes(b'model')
    request_path = tmp_path / 'request.json'; request_path.write_text('{}')
    response_path = tmp_path / 'response.json'; response_path.write_text('{"success":true}')
    monkeypatch.setenv('WEBHDP_COMPONENT_REQUEST', str(request_path))
    monkeypatch.setenv('WEBHDP_COMPONENT_RESPONSE', str(response_path))
    monkeypatch.setenv('SINGULARITY_BIN', '/usr/bin/singularity')
    request = {'profile': {'image': '/image.sif', 'entrypoint': ['python3', '/runner.py'], 'resources': {'gpu_count': 1}},
               'inputs': {'input_file': '/local/second/model.glb'},
               'staged_files': [{'local_path': '/local/second/model.glb', 'remote_path': str(nested)}],
               'remote_input_dir': str(inputs), 'remote_output_dir': str(tmp_path / 'outputs')}
    with patch.object(runner.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as process:
        result = runner._generic_singularity_component('mesh_optimizer', request)
    assert '--nv' in process.call_args.args[0]
    assert not result['success']
    staged_request = json.loads((tmp_path / 'request.container.json').read_text())
    assert staged_request['inputs']['input_file'] == '/inputs/second/model.glb'
