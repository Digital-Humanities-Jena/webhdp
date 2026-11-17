"""Fixed-entrypoint and parent-environment guards for learned HPC execution."""
import importlib.util
import ast
from pathlib import Path

import pytest

SOURCE = Path(__file__).parents[1] / "external_code/historic_reconstruction_runtime/learned_entrypoint.py"
spec = importlib.util.spec_from_file_location("learned_entrypoint", SOURCE)
entrypoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entrypoint)


def test_launcher_stage_keys_match_actual_component_runner_contract():
    tree = ast.parse((SOURCE.parent / "component_runner.py").read_text())
    stages = next(ast.literal_eval(node.value) for node in tree.body
                  if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "UPSTREAM_STAGES"
                                                         for target in node.targets))
    assert set(entrypoint.STAGES.values()) <= set(stages)
    assert all(command == "upstream-" + stage for command, stage in entrypoint.STAGES.items())


@pytest.mark.parametrize("command,stage", entrypoint.STAGES.items())
def test_fixed_stage_preserves_contract_arguments(command, stage):
    config = f"/opt/historic-learned/{stage}-operator-config.json"
    tail = ["--request", "/data/request.json", "--result", "/data/result.json"]
    result = entrypoint.stage_command(["env", "HISTORIC_RECONSTRUCTION_UPSTREAM_CONFIG=" + config,
                                       "python", "/app/component_runner.py", command, *tail])
    assert result == (stage, config, ["/app/component_runner.py", command, *tail])


@pytest.mark.parametrize("arguments", [
    ["sh", "-c", "arbitrary"],
    ["env", "HISTORIC_RECONSTRUCTION_UPSTREAM_CONFIG=/tmp/changed.json", "python", "/app/component_runner.py", "upstream-geolocalization"],
    ["env", "HISTORIC_RECONSTRUCTION_UPSTREAM_CONFIG=/opt/historic-learned/geolocalization-operator-config.json", "python", "/tmp/replaced.py", "upstream-geolocalization"],
])
def test_rejects_changed_executable_or_configuration(arguments):
    with pytest.raises(ValueError):
        entrypoint.stage_command(arguments)


def test_refuses_non_container_before_creating_private_home(monkeypatch):
    called = []
    monkeypatch.setattr(entrypoint.tempfile, "mkdtemp", lambda **kwargs: called.append(kwargs))
    parent = {"HOME": "/unchanged/home", "PATH": "/usr/bin"}
    with pytest.raises(RuntimeError, match="contained Singularity"):
        entrypoint.child_environment("geolocalization", "/fixed/config.json", python=Path("/opt/test/bin/python"),
                                     parent_environment=parent)
    assert not called and parent == {"HOME": "/unchanged/home", "PATH": "/usr/bin"}
