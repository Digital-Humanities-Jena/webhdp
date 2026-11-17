"""Native catalog, immutable installation gates and community recipe bindings."""
from copy import deepcopy
from pathlib import Path

from flask import Flask
import pytest
import yaml

from database.database import db
from database.models import PipelineDefinition, PipelineVersion, Session, User, UserRole
from services.hpc_component_installer_service import HpcComponentInstallerService
from services.native_pipeline_system import NativePipelineSystemService
from services.zenodo_component_templates import ZENODO_COMPONENT_KEYS, ZENODO_PIPELINE_DEFINITIONS
from services.historic_reconstruction_templates import HISTORIC_COMPONENT_KEYS
from services.submission_pipeline_service import pipeline_requires_record_metadata


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def registry():
    app = Flask(__name__)
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite://", SQLALCHEMY_TRACK_MODIFICATIONS=False,
                      SECRET_KEY="community-tests", WEBHDP_DEPLOYMENT_MODE="local", WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=True)
    db.init_app(app)
    app.native_pipeline_service = NativePipelineSystemService()
    with app.app_context():
        db.create_all()
        yield app.native_pipeline_service
        db.session.remove()
        db.drop_all()


def load(key, *, pinned=True, version="1.0.0"):
    result = yaml.safe_load((ROOT / "external_code" / key / "component.yaml").read_text())
    result["metadata"]["version"] = version
    if pinned:
        for profile in result["execution"]["profiles"]:
            if profile["runtime"] == "docker":
                profile["image"] = "sha256:" + "a" * 64
            else:
                profile.update(image="/isolated/community.sif", sif_sha256="b" * 64)
    return result


@pytest.mark.parametrize("strategy", ["local_container", "hpc_sif"])
def test_all_seven_published_cpu_components_are_in_both_catalogs(registry, strategy):
    catalog = HpcComponentInstallerService().list_available_catalog(install_strategy=strategy, source="local")
    keys = {row["component_key"] for row in catalog["components"]}
    assert len(ZENODO_COMPONENT_KEYS) == 7
    assert ZENODO_COMPONENT_KEYS <= keys
    for row in catalog["components"]:
        if row["component_key"] in ZENODO_COMPONENT_KEYS:
            assert row["zenodo"]["record_url"].startswith("https://zenodo.org/records/")
            assert row["zenodo"]["doi"].startswith("10.5281/zenodo.")


def test_eight_recipes_wait_for_pins_and_preserve_user_versions(registry):
    for key in sorted(ZENODO_COMPONENT_KEYS):
        registry.import_component_from_manifest(load(key, pinned=False, version="0.1.0"))
    assert not PipelineDefinition.query.filter(PipelineDefinition.identifier.like("zenodo_obj_%")).count()
    for identifier in ZENODO_PIPELINE_DEFINITIONS:
        assert PipelineDefinition.query.filter_by(identifier=identifier).first() is None
    for key in sorted(ZENODO_COMPONENT_KEYS):
        registry.import_component_from_manifest(load(key))
    assert len(ZENODO_PIPELINE_DEFINITIONS) == 8
    for identifier in ZENODO_PIPELINE_DEFINITIONS:
        assert PipelineDefinition.query.filter_by(identifier=identifier).first() is not None
    identifier = "zenodo_obj_to_glb_and_inspect"
    saved = registry.get_pipeline(identifier)
    edited = registry.create_pipeline_version_from_config(identifier, {**saved["config"], "name": "My conversion workflow"})
    count = PipelineVersion.query.count()
    registry.import_component_from_manifest(load("obj_to_glb_converter", version="1.1.0"))
    registry.ensure_zenodo_pipeline_templates()
    current = registry.get_pipeline(identifier)
    assert current["active_version"] == edited["active_version"]
    assert current["name"] == "My conversion workflow"
    assert current["config"]["steps"][0]["component_version"] == "1.0.0"
    assert PipelineVersion.query.count() == count


@pytest.mark.parametrize("key,parameter,value", [
    ("obj_to_glb_converter", "optimize_geometry", "true"),
    ("obj_statistics_extractor", "calculate_detailed_geometry", 1),
    ("glb_metadata_extractor", "calculate_volume", "yes"),
    ("validate_file_integrity", "include_hash", 0),
    ("hdpc_exporter", "export_mode", "execute_sql"),
    ("hdpc_exporter", "max_rows", 0),
    ("hdpc_exporter", "max_rows", 100001),
    ("hdpc_exporter", "max_rows", True),
    ("obj_statistics_extractor", "script", "arbitrary"),
])
def test_constructor_rejects_invalid_parameters(registry, key, parameter, value):
    registry.import_component_from_manifest(load(key))
    config = deepcopy(ZENODO_PIPELINE_DEFINITIONS["zenodo_" + key])
    config["steps"][0]["parameters"] = {parameter: value}
    result = registry.validate_pipeline_config(config)
    assert not result["valid"], result
    assert any(parameter in error for error in result["errors"])


def test_conversion_chain_uses_glb_artifact_and_rejects_report_binding(registry):
    for key in ("obj_to_glb_converter", "glb_metadata_extractor"):
        registry.import_component_from_manifest(load(key))
    pipeline = registry.get_pipeline("zenodo_obj_to_glb_and_inspect")
    assert set(pipeline["guidance"]["source_extensions"]) == {".obj", ".zip"}
    config = pipeline["config"]
    binding = config["steps"][1]["input_bindings"][0]
    assert binding["type"] == "artifact_file"
    assert binding["source_output"] == "model_file"
    assert registry.validate_pipeline_config(config)["valid"]
    invalid = deepcopy(config)
    invalid["steps"][1]["input_bindings"][0]["source_output"] = "report"
    result = registry.validate_pipeline_config(invalid)
    assert not result["valid"]
    assert any(".json" in error and ".glb" in error for error in result["errors"])


def test_manifests_expose_published_options_and_separate_dependency_files(registry):
    converted = registry.validate_component_manifest_path(str(ROOT / "external_code/obj_to_glb_converter"))
    schema = converted["playground_schema"]
    assert {item["name"] for item in schema["inputs"]} == {"input_file", "dependency_files"}
    options = {field["name"]: field for group in schema["parameter_groups"] for field in group["fields"]}
    assert options["optimize_geometry"]["widget"] == "checkbox"
    assert options["ignore_missing_textures"]["default"] is False
    assert {port["name"] for port in schema["outputs"]} == {"model_file", "report"}


@pytest.mark.parametrize("key", ["obj_to_glb_converter", "obj_statistics_extractor"])
@pytest.mark.parametrize("extension", [".obj", ".zip"])
def test_native_preflight_does_not_bind_source_as_optional_dependencies(registry, tmp_path, key, extension):
    registry.import_component_from_manifest(load(key))
    user = User(email="community-preflight@example.test", role=UserRole.ADMIN, is_verified=True)
    user.set_password("isolated-tests-only")
    db.session.add(user)
    db.session.flush()
    session = Session(user_id=user.id, session_dir=str(tmp_path), hdpc_path=str(tmp_path / "scene.hdpc"), status="processing")
    db.session.add(session)
    db.session.commit()
    # Constructor preflight validates bindings/extensions; execution validates file structure.
    source = tmp_path / ("scene" + extension)
    source.write_text("fixture")
    config = registry.get_pipeline("zenodo_" + key)["config"]
    checked = registry.preflight_pipeline_constructor({"pipeline_definition": config, "session_id": session.id,
                                                       "local_file_paths": [str(source)]}, user.id)
    assert checked["valid"], checked
    inputs = checked["steps"][0]["records"][0]["resolved_inputs"]
    assert inputs["input_file"] == str(source)
    assert "dependency_files" not in inputs
    manifest = registry._get_component_manifest_by_key(key)
    explicit = registry._apply_default_input_bindings(manifest["inputs"], {"input_file": str(source), "dependency_files": ["material.mtl"]}, {"file_path": str(source)}, {})
    assert explicit["dependency_files"] == ["material.mtl"]


@pytest.mark.parametrize("key", sorted(ZENODO_COMPONENT_KEYS | HISTORIC_COMPONENT_KEYS))
def test_local_scientific_processing_does_not_require_publication_metadata(key):
    assert pipeline_requires_record_metadata([{"id": key, "component_ref": key}]) is False


@pytest.mark.parametrize("change", [
    {"input_bindings": [{"type": "record_metadata_field", "target": "input_file", "source": "title"}]},
    {"parameter_bindings": [{"type": "record_metadata_field", "target": "table", "source": "title"}]},
    {"output_actions": [{"action_type": "record_metadata_field"}]},
    {"output_actions": [{"action_type": "zenodo_metadata_field"}]},
    {"output_actions": [{"action_type": "edm_metadata_field"}]},
])
def test_metadata_dependent_community_steps_still_require_metadata(change):
    assert pipeline_requires_record_metadata([{"id": "inspect", "component_ref": "obj_statistics_extractor", **change}]) is True


@pytest.mark.parametrize("key", ["zenodo_draft", "zenodo_upload", "unreviewed_external_component"])
def test_publication_and_unknown_components_keep_metadata_requirement(key):
    assert pipeline_requires_record_metadata([{"id": "inspect", "component_ref": "obj_statistics_extractor"}, {"id": key}]) is True


def test_empty_workflow_does_not_bypass_metadata_requirement():
    assert pipeline_requires_record_metadata([]) is True
    assert pipeline_requires_record_metadata([{"id": "obj_statistics_extractor", "enabled": False}]) is True
