"""Runtime replacement races and real child timeout diagnostics."""
import json
from pathlib import Path
import sys
import zipfile

from PIL import Image
import pytest

from external_code.historic_reconstruction_runtime import upstream as u


def configured(tmp_path, monkeypatch):
    source = tmp_path / "historic_reconstruction_pipeline"
    source.mkdir()
    (source / "marker.py").write_text("VALUE=1\n")
    config = {"schema_version": 1, "enabled_stages": ["segmentation"],
              "python": {"path": sys.executable, "sha256": u.file_sha256(sys.executable)},
              "source": {"path": str(source), "sha256": u.tree_sha256(source)},
              "dependencies": [], "assets": {}, "timeout_seconds": 60}
    path = tmp_path / "operator.json"
    path.write_text(json.dumps(config))
    monkeypatch.setenv("HISTORIC_RECONSTRUCTION_UPSTREAM_CONFIG", str(path))
    return config, path, source


def test_source_and_config_replacement_cannot_publish_success(tmp_path, monkeypatch):
    config, config_path, source = configured(tmp_path, monkeypatch)
    image = tmp_path / "input.jpg"
    Image.new("RGB", (48, 32), "orange").save(image)
    archive = tmp_path / "input.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.write(image, "images/input.jpg")
    monkeypatch.setenv("WEBHDP_INPUT_DIR", str(tmp_path))
    monkeypatch.setattr(u, "_preflight", lambda *args: None)

    def stage_then_concurrent_replacement(command, installed, env, cwd, log):
        # A structurally complete stage result is followed by an operator replacing
        # both the source and its config. Neither event represents neural inference.
        masks = Path(command[command.index("--output_path_mask") + 1])
        masks.mkdir()
        Image.new("L", (48, 32), 255).save(masks / "input.png")
        log.write_text("fixture stage completed\n")
        (source / "marker.py").write_text("VALUE=2\n")
        config["source"]["sha256"] = u.tree_sha256(source)
        config_path.write_text(json.dumps(config))

    monkeypatch.setattr(u, "_execute", stage_then_concurrent_replacement)
    with pytest.raises(ValueError, match="configuration changed during execution"):
        u.run("segmentation", {"input_file": str(archive)}, {}, tmp_path / "output")
    assert not (tmp_path / "output/research-workspace.zip").exists()


def test_original_pins_are_revalidated_without_reloading_config(tmp_path, monkeypatch):
    _, _, source = configured(tmp_path, monkeypatch)
    installed = u.load_config("segmentation")
    (source / "marker.py").write_text("VALUE=2\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        u._assert_runtime_unchanged(installed)


def test_config_change_during_final_asset_validation_is_rejected(tmp_path, monkeypatch):
    config, path, _ = configured(tmp_path, monkeypatch)
    installed = u.load_config("segmentation")
    original_check = u._checked_path
    changed = False

    def change_during_check(entry, **kwargs):
        nonlocal changed
        result = original_check(entry, **kwargs)
        if not changed:
            config["timeout_seconds"] = 120
            path.write_text(json.dumps(config))
            changed = True
        return result

    monkeypatch.setattr(u, "_checked_path", change_during_check)
    with pytest.raises(ValueError, match="configuration changed during execution"):
        u._assert_runtime_unchanged(installed)


def test_real_timed_out_child_preserves_only_bounded_diagnostic_tail(tmp_path, capsys):
    log = tmp_path / "child.log"
    command = [sys.executable, "-c",
               "import time; print('prefix-' * 2000); print('LAST CHILD DIAGNOSTIC', flush=True); time.sleep(10)"]
    with pytest.raises(ValueError, match="configured time limit"):
        u._execute(command, {"timeout_seconds": 0.5}, {}, tmp_path, log)
    stderr = capsys.readouterr().err
    assert "LAST CHILD DIAGNOSTIC" in stderr
    assert len(stderr) <= 6001
    assert log.stat().st_size > 6000
