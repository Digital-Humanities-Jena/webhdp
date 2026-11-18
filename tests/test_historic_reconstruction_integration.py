"""Catalog, publication, pinning and real CPU artifact-chain integration."""

from copy import deepcopy
from pathlib import Path
import base64
import io
import json
import os
import sqlite3
import subprocess
import zipfile

from flask import Flask
import pytest
import yaml

from database.database import db
from database.models import ExecutionArtifact, PipelineDefinition, PipelineVersion, Session, User, UserRole
from services.historic_reconstruction_templates import HISTORIC_PIPELINE_DEFINITIONS
from services.hpc_component_installer_service import HpcComponentInstallerService
from services.native_pipeline_system import NativePipelineSystemService


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def registry():
    app = Flask(__name__)
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite://",
                      SQLALCHEMY_TRACK_MODIFICATIONS=False, SECRET_KEY="historic-tests",
                      WEBHDP_DEPLOYMENT_MODE="local", WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=True)
    db.init_app(app)
    app.native_pipeline_service = NativePipelineSystemService()
    with app.app_context():
        db.create_all()
        yield app.native_pipeline_service
        db.session.remove()
        db.drop_all()


def load(stage, *, pinned=True, version="1.0.0"):
    manifest = yaml.safe_load((ROOT / "external_code" / f"historic_{stage}" / "component.yaml").read_text())
    manifest["metadata"]["version"] = version
    if pinned:
        for profile in manifest["execution"]["profiles"]:
            if profile["runtime"] == "docker":
                profile["image"] = "sha256:" + "a" * 64
            else:
                profile.update(image="/isolated/test/historic.sif", sif_sha256="b" * 64)
    return manifest


def test_all_components_are_discoverable_for_their_supported_installation(registry):
    installer = HpcComponentInstallerService()
    hpc = installer.list_available_catalog(install_strategy="hpc_sif", source="local")
    local = installer.list_available_catalog(install_strategy="local_container", source="local")
    # Catalog entry field is intentionally inspected here: this is the same
    # payload used by the existing HDP Components installation UI.
    hpc_keys = {row["component_key"] for row in hpc["components"]}
    local_keys = {row["component_key"] for row in local["components"]}
    assert {"historic_" + stage for stage in (
        "prepare", "pairs", "sparse", "dense", "georeference", "segmentation",
        "original_sfm", "geolocalization", "dense_intrinsics", "refine_keypoints", "mvs",
    )} <= hpc_keys
    assert {"historic_prepare", "historic_pairs", "historic_sparse", "historic_georeference"} <= local_keys
    assert "historic_dense" not in local_keys


def test_templates_wait_for_pinned_profiles_and_preserve_saved_versions(registry):
    registry.import_component_from_manifest(load("prepare", pinned=False))
    assert not PipelineDefinition.query.filter(PipelineDefinition.identifier.like("historic_%")).count()
    registry.import_component_from_manifest(load("prepare", version="1.0.1"))
    assert {row.identifier for row in PipelineDefinition.query.all() if row.identifier.startswith("historic_")} == {
        "historic_prepare_images", "historic_prepare_images_hpc"}
    for stage in ("pairs", "sparse", "dense", "georeference", "segmentation", "original_sfm",
                  "geolocalization", "dense_intrinsics", "refine_keypoints", "mvs"):
        registry.import_component_from_manifest(load(stage))
    assert set(HISTORIC_PIPELINE_DEFINITIONS) == {row.identifier for row in PipelineDefinition.query.all() if row.identifier.startswith("historic_")}
    identifier = "historic_sparse_reconstruction_hpc"
    saved = registry.get_pipeline(identifier)
    assert [step["parameters"].get("use_gpu") for step in saved["config"]["steps"]][-1] is True
    edited = registry.create_pipeline_version_from_config(identifier, {**saved["config"], "name": "My reconstruction"})
    count = PipelineVersion.query.count()
    registry.import_component_from_manifest(load("sparse", version="1.1.0"))
    registry.ensure_historic_pipeline_templates()
    current = registry.get_pipeline(identifier)
    assert current["active_version"] == edited["active_version"]
    assert current["name"] == "My reconstruction"
    assert current["config"]["steps"][-1]["component_version"] == "1.0.0"
    assert PipelineVersion.query.count() == count


def test_hpc_only_install_seeds_the_hpc_recipe(registry):
    manifest = load("prepare")
    manifest["execution"]["profiles"] = [
        profile for profile in manifest["execution"]["profiles"] if profile["id"] == "hpc_singularity"
    ]
    registry.import_component_from_manifest(manifest)
    assert {row.identifier for row in PipelineDefinition.query.all() if row.identifier.startswith("historic_")} == {
        "historic_prepare_images_hpc"
    }
    validation = registry.validate_pipeline_config(HISTORIC_PIPELINE_DEFINITIONS["historic_prepare_images"])
    assert not validation["valid"]
    assert any("local_docker" in error for error in validation["errors"])


@pytest.mark.parametrize("stage,parameter,value", [
    ("prepare", "max_image_size", 0), ("prepare", "max_image_size", True),
    ("pairs", "method", "shell"), ("pairs", "radius_m", float("inf")),
    ("sparse", "use_gpu", "true"), ("sparse", "camera_model", "invalid"),
    ("sparse", "command", "arbitrary"),
])
def test_constructor_rejects_invalid_scientific_settings(registry, stage, parameter, value):
    registry.import_component_from_manifest(load(stage))
    config = deepcopy(HISTORIC_PIPELINE_DEFINITIONS["historic_prepare_images"])
    config["steps"][0].update(component_ref="historic_" + stage, parameters={parameter: value})
    result = registry.validate_pipeline_config(config)
    assert not result["valid"]
    assert any(parameter in error for error in result["errors"])


def test_artifact_bindings_and_defaults_are_published_correctly(registry):
    for stage in ("prepare", "pairs", "sparse"):
        registry.import_component_from_manifest(load(stage))
    pipeline = registry.get_pipeline("historic_sparse_reconstruction")
    assert ".zip" in pipeline["guidance"]["source_extensions"]
    config = pipeline["config"]
    assert registry.validate_pipeline_config(config)["valid"]
    assert config["steps"][1]["input_bindings"][0]["source_output"] == "dataset"
    assert config["steps"][2]["input_bindings"][0]["source_step"] == "pairs"
    invalid = deepcopy(config)
    invalid["steps"][1]["input_bindings"][0]["source_output"] = "report"
    assert not registry.validate_pipeline_config(invalid)["valid"]
    manifest = registry._get_component_manifest_by_key("historic_prepare")
    assert registry._hmsm_parameters(manifest, {})["max_image_size"] == 1600


@pytest.mark.parametrize("stage", ["prepare", "pairs"])
def test_declared_installation_smoke_fixtures_run_real_processing(stage, tmp_path, monkeypatch):
    from external_code.historic_reconstruction_runtime.component_runner import run_component

    fixture = load(stage)["install"]["test"]
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for entry in fixture["files"]:
        (inputs / entry["name"]).write_bytes(base64.b64decode(entry["content_base64"], validate=True))
    monkeypatch.setenv("WEBHDP_INPUT_DIR", str(inputs))
    result = run_component(stage, fixture, tmp_path / "outputs")
    assert result["success"]
    report = json.loads(Path(result["outputs"]["report"]).read_text())
    assert report["image_count" if stage == "prepare" else "pair_count"] == 3


@pytest.mark.skipif(os.environ.get("WEBHDP_TEST_HISTORIC_DOCKER") != "1", reason="Requires the built historic Docker image")
def test_real_docker_pipeline_preserves_records_and_passes_dataset_artifacts(registry, tmp_path):
    """No processing mocks: exercise native registry, Docker, ZIPs and artifacts."""
    from PIL import Image

    image_id = subprocess.check_output([
        "docker", "image", "inspect", "webhdp-historic-reconstruction:local", "--format", "{{.Id}}",
    ], text=True).strip()
    for stage in ("prepare", "pairs"):
        manifest = load(stage, pinned=False)
        manifest["execution"]["profiles"][0]["image"] = image_id
        registry.import_component_from_manifest(manifest)
    source = tmp_path / "uploads" / "historic scene.zip"
    source.parent.mkdir()
    with zipfile.ZipFile(source, "w") as archive:
        for number, name in enumerate(("A/photo.png", "B/photo.png", "Straße.jpg")):
            stream = io.BytesIO()
            Image.new("RGB", (400 + number, 300), (30 * number, 100, 70)).save(stream, format="PNG")
            archive.writestr(name, stream.getvalue())
    hdpc = tmp_path / "scene.hdpc"
    with sqlite3.connect(hdpc) as connection:
        connection.execute("CREATE TABLE source_files (file_id INTEGER PRIMARY KEY, filename TEXT, absolute_path TEXT, relative_path TEXT, file_type TEXT, status TEXT, size_bytes INTEGER, mime_type TEXT, pipeline_source TEXT, step_source TEXT, added_timestamp TEXT)")
        connection.execute("INSERT INTO source_files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            77, source.name, str(source), source.name, "primary_source", "ready", source.stat().st_size,
            "application/zip", "ingestion", "scan", "2026-11-06T00:00:00Z",
        ))
    user = User(email="historic-native@example.test", role=UserRole.ADMIN, is_verified=True)
    user.set_password("isolated-test-only")
    db.session.add(user)
    db.session.flush()
    session = Session(user_id=user.id, session_dir=str(tmp_path), hdpc_path=str(hdpc), status="processing")
    db.session.add(session)
    db.session.commit()
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    context = dict(
        identifier="historic_prepare_pairs", canonical_identifier="historic_prepare_pairs",
        local_file_paths=[str(source)], db_session_id=session.id, db_session=session, hdpc_path=str(hdpc),
        is_sandbox=True, abort_on_critical_error=True, progress_callback=None,
        pipeline_timings=dict(project_loading=0, record_registration=0, batch_render=0, record_processing=[], total_execution=0),
        record_info_list=[(77, str(source), {"title": "Historic scene"})], skipped_files=[], outputs_dir=str(outputs),
        batch_metadata_map={}, shared_zenodo_metadata={}, batch_shared_zenodo_metadata={}, batch_item_defaults={},
        lod_mapping_config=None, resolved_lod_msf_path=None, msf_rows_by_filename={}, normalized_file_id_map={},
        file_id_to_relative_path={}, bundle_file_paths_by_relative={}, basename_to_relative_paths={},
        relative_to_absolute_path={}, absolute_to_relative_path={}, steps_map={},
    )
    result = registry.execute_registered_submission("historic_prepare_pairs", context)
    assert result["success"], result
    artifacts = ExecutionArtifact.query.all()
    reports = [json.loads(Path(artifact.path).read_text()) for artifact in artifacts if artifact.name.endswith("-report.json")]
    assert {report["stage"] for report in reports} == {"prepare", "pairs"}
    pairs_report = next(report for report in reports if report["stage"] == "pairs")
    assert pairs_report["pair_count"] == 3
    assert all(Path(artifact.path).is_relative_to(tmp_path) and Path(artifact.path).is_file() for artifact in artifacts)
    assert source.exists()
