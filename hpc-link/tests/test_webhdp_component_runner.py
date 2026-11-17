import importlib.util
import json
import os
import subprocess
import pytest
from pathlib import Path
from unittest.mock import patch


def _load_runner():
    runner_path = Path(__file__).resolve().parents[1] / "scripts" / "webhdp_component_runner.py"
    spec = importlib.util.spec_from_file_location("webhdp_component_runner", runner_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_renderer_inputs_cannot_escape_claim(tmp_path):
    runner = _load_runner()
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    staged = inputs / 'model.obj'
    staged.write_text('allowed')
    other = tmp_path / 'other-account.obj'
    other.write_text('private')
    alias = inputs / 'alias.obj'
    alias.symlink_to(other)
    assert runner._resolve_staged_input('/backend/own/model.obj', {'staged_files': [
        {'local_path': '/backend/own/model.obj', 'remote_path': str(staged)},
    ]}, inputs) == staged
    for disallowed in (str(other), '../other-account.obj', str(alias)):
        with pytest.raises(ValueError):
            runner._resolve_staged_input(disallowed, {}, inputs)
    assert runner._collect_render_inputs({'inputs': {'input_dir': str(inputs)}}, inputs)[1] == [staged]
    mapped = {'inputs': {'input_dir': '/backend/own'}, 'staged_files': [
        {'local_path': '/backend/own/model.obj', 'remote_path': str(staged)},
        {'local_path': '/backend/unrelated/model.obj', 'remote_path': str(other)},
    ]}
    assert runner._collect_render_inputs(mapped, inputs) == (['/backend/own/model.obj'], [staged])


def test_installed_host_runtime_maps_inputs_and_confines_artifacts(tmp_path, monkeypatch):
    import sys
    runner = _load_runner()
    inputs, outputs = tmp_path / 'inputs', tmp_path / 'outputs' / 'invocation-1'
    inputs.mkdir()
    staged = inputs / 'photo.jpg'
    staged.write_bytes(b'photo')
    request_file, response_file = tmp_path / 'request.json', tmp_path / 'response.json'
    monkeypatch.setenv('WEBHDP_COMPONENT_REQUEST', str(request_file))
    monkeypatch.setenv('WEBHDP_COMPONENT_RESPONSE', str(response_file))
    script = tmp_path / 'approved.py'
    script.write_text("import os,json,pathlib\nr=json.loads(pathlib.Path(os.environ['WEBHDP_COMPONENT_REQUEST']).read_text())\np=pathlib.Path(os.environ['WEBHDP_OUTPUT_DIR'])/'report.json'\np.write_text(json.dumps(r['inputs']))\npathlib.Path(os.environ['WEBHDP_COMPONENT_RESPONSE']).write_text(json.dumps({'success':True,'artifacts':[{'path':str(p)}]}))\n")
    request = {'remote_input_dir': str(inputs), 'remote_output_dir': str(outputs),
               'profile': {'handler':'trusted_host_component','entrypoint':[sys.executable,str(script)]},
               'staged_files':[{'local_path':'/private/photo.jpg','remote_path':str(staged)}],
               'inputs': {'input_files':['/private/photo.jpg']},
               'parameters': {'entrypoint':['/bin/false']}}
    result = runner._trusted_host_component('installed_photo', request)
    assert result['success'] is True
    report = outputs / 'report.json'
    assert json.loads(report.read_text()) == {'input_files':[str(staged)]}
    assert result['artifacts'][0]['remote_path'] == str(report)
    import pytest
    request['inputs']['input_files'] = ['/etc/passwd']
    with pytest.raises(ValueError, match='exact staged'):
        runner._trusted_host_component('installed_photo', request)
    request['inputs']['input_files'] = ['/private/photo.jpg']
    script.write_text("import os,json,pathlib\np=pathlib.Path(os.environ['WEBHDP_OUTPUT_DIR'])/'escape'\np.symlink_to('/etc/passwd')\npathlib.Path(os.environ['WEBHDP_COMPONENT_RESPONSE']).write_text(json.dumps({'success':True,'artifacts':[{'path':str(p)}]}))\n")
    with pytest.raises(ValueError, match='escaped'):
        runner._trusted_host_component('installed_photo', request)


def test_host_registry_requires_pinned_manifest_and_absolute_operator_entrypoint():
    import asyncio
    import hashlib
    from unittest.mock import AsyncMock
    from fastapi import HTTPException
    from app.services.apps_gateway import HpcApplicationGatewayService
    import pytest
    manifest = json.dumps({'execution':{'profiles':[{'handler':'trusted_host_component','entrypoint':['/usr/bin/python3','/work/approved.py']}]}})
    registry = {'manifest_path':'/work/approved/component.json', 'manifest_sha256':hashlib.sha256(manifest.encode()).hexdigest()}
    with patch('app.services.apps_gateway.ssh_manager') as ssh:
        ssh.run_command = AsyncMock(side_effect=[(json.dumps(registry),'',0),(manifest,'',0)])
        result = asyncio.run(HpcApplicationGatewayService()._load_webhdp_component_profile('approved','1.0.0'))
        assert result['profile']['handler'] == 'trusted_host_component'
        assert result['profile']['entrypoint'] == ['/usr/bin/python3','/work/approved.py']
        registry['manifest_sha256'] = '0' * 64
        ssh.run_command = AsyncMock(side_effect=[(json.dumps(registry),'',0),(manifest,'',0)])
        with pytest.raises(HTTPException) as error:
            asyncio.run(HpcApplicationGatewayService()._load_webhdp_component_profile('approved','1.0.0'))
        assert error.value.status_code == 409


def test_host_timeout_terminates_child_processes_without_touching_allocation(tmp_path, monkeypatch):
    import sys
    import time
    import pytest
    runner = _load_runner()
    marker = tmp_path / 'orphan-finished'
    script = tmp_path / 'spawn.py'
    child = "import time,pathlib; time.sleep(2); pathlib.Path(" + repr(str(marker)) + ").write_text('orphan')"
    script.write_text('import subprocess,sys,time\nsubprocess.Popen([sys.executable,"-c",' + repr(child) + '])\ntime.sleep(60)\n')
    monkeypatch.setenv('WEBHDP_COMPONENT_REQUEST', str(tmp_path / 'request.json'))
    monkeypatch.setenv('WEBHDP_COMPONENT_RESPONSE', str(tmp_path / 'response.json'))
    request = {'remote_input_dir': str(tmp_path / 'inputs'), 'remote_output_dir': str(tmp_path / 'outputs'),
        'profile': {'handler':'trusted_host_component','entrypoint':[sys.executable,str(script)]},
        'timeout_seconds':1}
    with pytest.raises(subprocess.TimeoutExpired):
        runner._trusted_host_component('installed_photo', request)
    time.sleep(1.5)
    assert not marker.exists()


def test_webhdp_walltime_is_based_on_start_and_scheduler_state_not_queue_estimate():
    import asyncio
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.services.apps_gateway import HpcApplicationGatewayService, _WebHdpSession
    service = HpcApplicationGatewayService()
    now = datetime.now(timezone.utc)
    session = _WebHdpSession(session_id='held', partition='gpu', gpu_type='a100', gpu_count=1,
        duration_minutes=720, time_limit='12:00:00', job_id='123', remote_session_dir='/work/session',
        remote_input_dir='/work/session/inputs', remote_output_dir='/work/session/outputs',
        cuda_module=None, created_at=now - timedelta(hours=13), expires_at=now - timedelta(hours=1), owner_username='tester')
    service._webhdp_sessions['held'] = session
    service._scheduler_state_for_job = AsyncMock(return_value=('RUNNING',None))
    with patch.object(service, '_save_webhdp_sessions_to_registry'), patch('app.services.apps_gateway.ssh_manager') as ssh:
        ssh.run_command = AsyncMock(return_value=('gpu001\n'+now.isoformat(),' ',0))
        result = asyncio.run(service.get_webhdp_session_status('held',SimpleNamespace(username='tester',is_admin=False)))
        assert result.expires_at == now + timedelta(hours=12)
        assert result.node_name == 'gpu001' and result.status == 'running'
        assert 43195 <= result.remaining_seconds <= 43200
        session.expires_at = now - timedelta(hours=1)
        ssh.run_command.return_value = ('','',0)
        for state, expected in [('PENDING','queued'),('UNKNOWN','unknown'),('TIMEOUT','finished')]:
            service._scheduler_state_for_job.return_value = (state,None)
            result = asyncio.run(service.get_webhdp_session_status('held',SimpleNamespace(username='tester',is_admin=False)))
            assert result.status == expected
        assert '#SBATCH --time=12:00:00' in service._render_webhdp_hold_batch_script(session)


def test_twelve_hour_schema_retains_principal_resource_policy():
    from types import SimpleNamespace
    import pytest
    from fastapi import HTTPException
    from app.schemas.apps import WebHdpSessionCreateRequest
    from app.security import enforce_allocation_policy
    request = WebHdpSessionCreateRequest(partition='gpu',gpu_type='a100',gpu_count=1,duration_minutes=720)
    actor = SimpleNamespace(username='test',is_admin=False,allowed_partitions=['gpu'],allowed_gpu_types=['a100'],max_gpu_count=1,max_duration_minutes=720)
    policy = dict(partition=request.partition,gpu_type=request.gpu_type,gpu_count=request.gpu_count,duration_minutes=request.duration_minutes)
    enforce_allocation_policy(actor, **policy)
    with pytest.raises(HTTPException) as error:
        enforce_allocation_policy(actor, **{**policy,'duration_minutes':721})
    assert error.value.status_code == 403


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
    monkeypatch.setenv('CUDA_VISIBLE_DEVICES', '2')
    request = {'profile': {'image': '/image.sif', 'entrypoint': ['python3', '/runner.py'], 'resources': {'gpu_count': 1}},
               'inputs': {'input_file': '/local/second/model.glb'},
               'staged_files': [{'local_path': '/local/second/model.glb', 'remote_path': str(nested)}],
               'remote_input_dir': str(inputs), 'remote_output_dir': str(tmp_path / 'outputs')}
    with patch.object(runner.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as process:
        result = runner._generic_singularity_component('mesh_optimizer', request)
    assert '--nv' in process.call_args.args[0]
    assert process.call_args.kwargs['env']['SINGULARITYENV_CUDA_VISIBLE_DEVICES'] == '2'
    assert process.call_args.kwargs['env']['APPTAINERENV_CUDA_VISIBLE_DEVICES'] == '2'
    assert not result['success']
    staged_request = json.loads((tmp_path / 'request.container.json').read_text())
    assert staged_request['inputs']['input_file'] == '/inputs/second/model.glb'
