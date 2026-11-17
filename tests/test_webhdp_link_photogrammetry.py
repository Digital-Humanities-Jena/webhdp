"""Photogrammetry boundaries and scientific packaging, without fake reconstruction."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest

from external_code.webhdp_link_photogrammetry import runner
from external_code.webhdp_link_photogrammetry.seed import definitions, prepare_installation, seed


def config():
    return {"runtime_python": "/opt/science/bin/python", "runtime_colmap": "/opt/science/bin/colmap",
            "remote_component_root": "/opt/webhdp/components/link_reprojector_photogrammetry/1.0.0",
            "colmap_sha256": "a" * 64, "reprojector_source_sha256": "b" * 64,
            "partition": "gpu", "gpu_type": "test-gpu"}


@pytest.mark.parametrize("parameters", [{"max_image_size": 639}, {"max_image_size": True},
    {"max_image_size": 2401}, {"mesher": "command"}, {"command": "example"},
    {"max_image_size": 960.0}])
def test_parameters_cannot_change_runtime_or_bypass_limits(parameters):
    with pytest.raises(ValueError):
        runner.bounded_parameters(parameters)


def test_publication_pins_runtime_and_uses_central_allocation_only():
    manifest, pipeline, publication = definitions(**config())
    profile = manifest["execution"]["profiles"][0]
    assert profile["adapter"] == "hpc_link" and profile["handler"] == "trusted_host_component"
    assert profile["entrypoint"][0] == "/usr/bin/env"
    assert "--colmap-sha256" in profile["entrypoint"] and "--expected-runner-sha256" in profile["entrypoint"]
    assert set(publication["parameters"]) == {"max_image_size", "mesher"}
    assert publication["execution_mode"] == "bundle"
    assert publication["hpc"]["walltime_hours"] == 12 and publication["hpc"]["retain_allocation"] is True
    assert pipeline["steps"][0]["input_bindings"][0]["type"] == "pipeline_source_files"
    assert "runtime_python" not in json.dumps(publication)


def test_native_registration_accepts_component_and_pipeline(tmp_path):
    from flask import Flask
    from database.database import db
    from services.native_pipeline_system import NativePipelineSystemService
    from services.webhdp_link_service import save_publication

    app = Flask(__name__)
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite://", SQLALCHEMY_TRACK_MODIFICATIONS=False,
                      WEBHDP_DEPLOYMENT_MODE="local", WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=True)
    db.init_app(app)
    app.native_pipeline_service = NativePipelineSystemService()
    with app.test_request_context("/"):
        db.create_all()
        publications = seed(app.native_pipeline_service, **config())
        saved = save_publication(publications[0])
        assert saved.id == "link-photogrammetry"
        assert json.loads(saved.config_json)["hpc"]["walltime_hours"] == 12
        db.session.remove()
        db.drop_all()


def test_install_payload_contains_only_explicit_scientific_modules_and_pins_bytes(tmp_path):
    source = tmp_path / "checkout/python/reprojector"
    source.mkdir(parents=True)
    for name in runner.SOURCE_FILES:
        (source / name).write_text('"""Scientific source fixture."""\n')
    (source / "unrelated.txt").write_text("do not copy")
    options = config()
    del options["reprojector_source_sha256"]
    output = tmp_path / "installation"
    settings = prepare_installation(output, reprojector_source=tmp_path / "checkout", **options)
    assert settings["reprojector_source_sha256"] == runner.source_digest(output / "source")
    assert {path.name for path in (output / "source/reprojector").iterdir()} == set(runner.SOURCE_FILES)
    registry = json.loads((output / "component.json").read_text())
    assert registry["manifest_sha256"] == runner.sha256(output / "manifest.json")
    assert registry["manifest_path"] == options["remote_component_root"] + "/manifest.json"
    (output / "source/reprojector/recipes.py").write_text("changed")
    assert runner.source_digest(output / "source") != settings["reprojector_source_sha256"]


def test_uploaded_photographs_keep_fixity_and_reject_escape(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    paths = []
    for number in range(3):
        path = inputs / f"photo-{number}.png"
        Image.new("RGB", (40, 30), (number * 50, 30, 60)).save(path)
        paths.append(str(path))
    captures = runner.stage_inputs({"inputs": {"input_files": paths}}, inputs, tmp_path / "workspace")
    assert [item["sha256"] for item in captures] == [runner.sha256(path) for path in paths]
    assert {item["name"] for item in captures} == {"0000.png", "0001.png", "0002.png"}
    assert str(tmp_path) not in json.dumps(captures)
    outside = tmp_path / "outside.png"
    shutil.copyfile(paths[0], outside)
    with pytest.raises(ValueError, match="outside"):
        runner.stage_inputs({"inputs": {"input_files": [str(outside), *paths[1:]]}}, inputs, tmp_path / "escape")
    (inputs / "alias.png").symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        runner.stage_inputs({"inputs": {"input_files": [str(inputs / "alias.png"), *paths[1:]]}}, inputs, tmp_path / "symlink")


def test_execute_requires_actual_allocation_and_unchanged_runtime(tmp_path, monkeypatch):
    source = tmp_path / "source/reprojector"
    source.mkdir(parents=True)
    for name in runner.SOURCE_FILES:
        (source / name).write_text("")
    colmap = tmp_path / "colmap"
    colmap.write_text("test executable bytes only; never invoked")
    args = dict(input_root=tmp_path, output_root=tmp_path, source=source.parent,
                expected_source_sha256=runner.source_digest(source.parent), colmap=colmap,
                expected_colmap_sha256=runner.sha256(colmap))
    monkeypatch.delenv("SLURM_JOB_ID", raising=False)
    with pytest.raises(ValueError, match="Slurm allocation"):
        runner.execute({}, **args)
    colmap.write_text("changed")
    with pytest.raises(ValueError, match="runtime changed"):
        runner.execute({}, **args)


def test_preview_depicts_supplied_cloud_and_rejects_empty_geometry(tmp_path):
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")
    cloud = SimpleNamespace(vertices=np.array([[x, y, x * y / 50] for x in range(20) for y in range(20)]),
                            colors=np.tile([250, 25, 35, 255], (400, 1)))
    runner.render_preview(cloud, tmp_path / "preview.png")
    image = Image.open(tmp_path / "preview.png")
    assert image.size == (1080, 430)
    assert sum(count for count, color in image.getcolors(image.width * image.height) if color == (250, 25, 35)) > 400
    with pytest.raises(ValueError, match="empty"):
        runner.render_preview(SimpleNamespace(vertices=np.empty((0, 3))), tmp_path / "empty.png")


def test_optional_actual_reprojector_bundle_is_validated_and_packaged(tmp_path):
    """Exercise authentic retained data; this does not claim a new GPU run."""
    source = os.environ.get("WEBHDP_LINK_REPROJECTOR_SOURCE")
    interpreter = os.environ.get("WEBHDP_LINK_REPROJECTOR_PYTHON")
    bundle = os.environ.get("WEBHDP_LINK_REPROJECTOR_BUNDLE")
    if not source or not interpreter or not bundle:
        pytest.skip("Set source, Python and existing real bundle paths to test actual scientific packaging.")
    code = '''
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]+'/python')
from external_code.webhdp_link_photogrammetry.runner import publish_bundle,sha256
bundle,out=Path(sys.argv[2]),Path(sys.argv[3])
data=json.loads((bundle/'reconstruction-bundle.json').read_text())
captures=[{'name':f['cameraName'],'originalName':f['cameraName'],'sha256':f['original']['sha256'],'width':f['original']['width'],'height':f['original']['height']} for f in data['frames']]
complete={'bundleSHA256':sha256(bundle/'reconstruction-bundle.json'),'receiptSHA256':sha256(bundle/'pipeline/receipt.json'),'elapsedSeconds':0}
publish_bundle(bundle,out,complete,captures,{'max_image_size':1600,'mesher':'poisson'},{'test':'retained authentic prior reconstruction; no new GPU run'},'a'*64,'b'*64)
'''
    subprocess.run([interpreter, "-c", code, source, bundle, str(tmp_path)], check=True, timeout=120)
    report = json.loads((tmp_path / "reconstruction-report.json").read_text())
    assert report["registeredImages"] == report["inputImages"] == 11
    assert report["sparsePoints"] > 100 and report["densePoints"] > 1000 and report["meshTriangles"] > 1000
    assert report["qa"]["status"] == "passed"
    assert str(Path(bundle).parent) not in json.dumps(report)
    with zipfile.ZipFile(tmp_path / "reconstruction-package.zip") as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert all(hashlib.sha256(archive.read(name)).hexdigest() == item["sha256"] for name, item in manifest["files"].items())
        assert "model.glb" in manifest["files"] and "sparse/cameras.bin" in manifest["files"]
        assert not any("log" in name or "stage-receipts" in name for name in archive.namelist())
