import json
import subprocess
import sys
from pathlib import Path

from scripts.validate_hdp_components import _manifest_paths, validate_components


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_hdp_components.py"


def _write_component(base: Path, name: str, body: str) -> Path:
    component_dir = base / name
    component_dir.mkdir(parents=True)
    manifest_path = component_dir / "component.yaml"
    manifest_path.write_text(body, encoding="utf-8")
    return manifest_path


def test_validate_components_accepts_valid_local_manifest(tmp_path):
    manifest_path = _write_component(
        tmp_path,
        "sample_component",
        """
metadata:
  name: sample_component
  version: "1.0.0"
  description: Test component.
inputs:
  - name: input_file
    type: file_path
    required: true
outputs:
  - name: report
    type: json
parameter_groups:
  - title: Options
    parameters:
      - name: strict
        type: boolean
        default: false
execution:
  profiles:
    - id: local_default
      adapter: local_cli
      entrypoint: [python, run.py]
""",
    )
    (manifest_path.parent / "run.py").write_text("print('ok')\n", encoding="utf-8")

    checks = validate_components([manifest_path])

    assert len(checks) == 1
    assert checks[0].status == "OK"
    assert checks[0].component_key == "sample_component"


def test_validate_components_reports_missing_required_structure_file(tmp_path):
    manifest_path = _write_component(
        tmp_path,
        "broken_component",
        """
metadata:
  name: broken_component
  version: "1.0.0"
  description: Test component.
structure:
  required_files:
    - run.py
inputs: []
outputs: []
parameter_groups: []
execution:
  profiles:
    - id: local_default
      adapter: local_cli
      entrypoint: [python, run.py]
""",
    )

    check = validate_components([manifest_path])[0]

    assert check.status == "FAIL"
    assert "required file is missing: run.py" in check.errors


def test_validate_components_reports_hpc_smoke_test_base64_errors(tmp_path):
    manifest_path = _write_component(
        tmp_path,
        "hpc_component",
        """
metadata:
  name: hpc_component
  version: "1.0.0"
  description: Test component.
inputs:
  - name: input_file
    type: file_path
outputs: []
parameter_groups: []
execution:
  profiles:
    - id: hpc_singularity
      adapter: hpc_link
      handler: generic_singularity_component
      runtime: singularity
      entrypoint: [python, /app/component.py]
hpc:
  install:
    runtime: singularity
    sif_required: true
  test:
    files:
      - name: sample.glb
        content_base64: "not base64!"
    inputs:
      input_file: missing.glb
""",
    )

    check = validate_components([manifest_path])[0]

    assert check.status == "FAIL"
    assert "hpc.test.files[0].content_base64 is not valid base64" in check.errors
    assert any("hpc.test.inputs.input_file references 'missing.glb'" in warning for warning in check.warnings)


def test_validate_components_checks_local_container_install_metadata(tmp_path):
    manifest_path = _write_component(
        tmp_path,
        "container_component",
        """
metadata:
  name: container_component
  version: "1.0.0"
  description: Test component.
inputs:
  - name: input_file
    type: file_path
outputs: []
parameter_groups: []
execution:
  profiles:
    - id: local_docker
      adapter: container_cli
      runtime: docker
      image: ghcr.io/hdp-components/container-component:1.0.0
      entrypoint: [python, /app/component.py]
install:
  strategies:
    - id: local_container
      runtime: docker
      profile: local_docker
      image: ghcr.io/hdp-components/container-component:1.0.0
  test:
    files:
      - name: sample.glb
        content_base64: "SGVsbG8="
    inputs:
      input_file: sample.glb
""",
    )

    check = validate_components([manifest_path])[0]

    assert check.status == "OK"


def test_validate_components_reports_broken_local_container_metadata(tmp_path):
    manifest_path = _write_component(
        tmp_path,
        "broken_container",
        """
metadata:
  name: broken_container
  version: "1.0.0"
  description: Test component.
inputs: []
outputs: []
parameter_groups: []
execution:
  profiles:
    - id: local_docker
      adapter: container_cli
      runtime: podman
      entrypoint: []
install:
  strategies:
    - id: local_container
      runtime: docker
      profile: missing_profile
  test:
    files:
      - name: bad/name.glb
        content_base64: "not base64!"
""",
    )

    check = validate_components([manifest_path])[0]

    assert check.status == "FAIL"
    assert "local_docker: container_cli install profiles require runtime=docker" in check.errors
    assert "local_docker: container_cli profiles require image" in check.errors
    assert "local_docker: container_cli profiles require a non-empty entrypoint" in check.errors
    assert "install.strategies[0].profile references unknown execution profile 'missing_profile'" in check.errors
    assert "install.strategies[0].image is required for local_container" in check.errors
    assert "install.test.files[0].name must be a simple file name" in check.errors
    assert "install.test.files[0].content_base64 is not valid base64" in check.errors


def test_validate_components_reports_duplicate_component_versions(tmp_path):
    manifest = """
metadata:
  name: duplicate_component
  version: "1.0.0"
  description: Test component.
inputs: []
outputs: []
parameter_groups: []
execution:
  profiles:
    - id: local_default
      adapter: local_cli
      entrypoint: [python, run.py]
"""
    first = _write_component(tmp_path, "duplicate_component", manifest)
    second = _write_component(tmp_path, "duplicate_component_copy", manifest)
    (first.parent / "run.py").write_text("print('ok')\n", encoding="utf-8")
    (second.parent / "run.py").write_text("print('ok')\n", encoding="utf-8")

    checks = validate_components([first, second])

    assert [check.status for check in checks] == ["OK", "FAIL"]
    assert "duplicate component metadata.name/version" in checks[1].errors[0]


def test_validate_components_reports_missing_local_python_entrypoint(tmp_path):
    manifest_path = _write_component(
        tmp_path,
        "missing_entrypoint",
        """
metadata:
  name: missing_entrypoint
  version: "1.0.0"
  description: Test component.
inputs: []
outputs: []
parameter_groups: []
execution:
  profiles:
    - id: local_default
      adapter: local_cli
      entrypoint: [python, missing.py]
""",
    )

    check = validate_components([manifest_path])[0]

    assert check.status == "FAIL"
    assert "local_default: entrypoint script is missing: missing.py" in check.errors


def test_validate_components_uses_backend_builtin_loader_for_physical_builtin_manifests():
    manifest_path = ROOT / "external_code" / "fast_renderer" / "component.yaml"

    check = validate_components([manifest_path])[0]

    assert check.status == "OK"
    assert check.component_key == "fast_renderer"


def test_manifest_paths_accepts_catalog_roots_and_component_directories(tmp_path):
    first = _write_component(tmp_path, "one", "metadata: {name: one, version: '1.0.0'}\n")
    second = _write_component(tmp_path, "two", "metadata: {name: two, version: '1.0.0'}\n")

    assert _manifest_paths([str(tmp_path)]) == [first.resolve(), second.resolve()]
    assert _manifest_paths([str(first.parent)]) == [first.resolve()]


def test_cli_json_report_returns_nonzero_for_invalid_manifest(tmp_path):
    manifest_path = _write_component(
        tmp_path,
        "invalid",
        """
metadata:
  name: Invalid Name
  version: nope
inputs: []
outputs: []
parameter_groups: []
execution:
  profiles:
    - id: local_default
      adapter: local_cli
      entrypoint: [python, run.py]
""",
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json", str(manifest_path)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["summary"]["failures"] == 1
    assert payload["components"][0]["status"] == "FAIL"
