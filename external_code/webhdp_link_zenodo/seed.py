"""Install an immutable model-to-unpublished-Sandbox-draft Link pipeline.

Install the example link_mesh_packager component first. Credentials are never
part of this definition: the Link worker resolves the initiating user's active
Sandbox credential immediately before invoking the approved local component.
"""
from copy import deepcopy
from pathlib import Path
import sys

import yaml

from .runner import VERSION, checksum

ROOT = Path(__file__).resolve().parent
PUBLICATION = {
    "id": "link-model-sandbox-draft", "name": "3D model to unpublished Zenodo Sandbox draft",
    "description": "Validate and convert OBJ to GLB, prepare repository files, create an unpublished Zenodo Sandbox draft, and verify every uploaded file by downloading it. No publication or production repository access.",
    "pipeline_identifier": "link_model_sandbox_draft", "pipeline_version": VERSION,
    "enabled": True, "execution_mode": "record", "step_timeout_seconds": 1800,
    "input": {"min_files": 1, "max_files": 10, "extensions": [".obj"]},
    "parameters": {
        "title": {"step_id": "prepare", "parameter": "title", "type": "string", "minLength": 1, "maxLength": 200,
                  "default": "WebHDP-Link Sandbox model validation", "label": "Dataset title"},
        "target_extent": {"step_id": "prepare", "parameter": "target_extent", "type": "number", "minimum": 0.01,
                          "maximum": 1000, "default": 1, "label": "Normalized largest extent"},
        "creator_name": {"step_id": "deposit", "parameter": "creator_name", "type": "string", "minLength": 1,
                         "maxLength": 200, "default": "WebHDP-Link validation", "label": "Creator name"},
    },
}


def definitions(*, python_executable=None):
    manifest = yaml.safe_load((ROOT / "component.yaml").read_text())
    manifest["execution"]["profiles"][0]["entrypoint"] = [str(Path(python_executable or sys.executable).absolute()),
        str(ROOT / "runner.py"), "--expected-runner-sha256", checksum(ROOT / "runner.py")]
    definition = {
        "identifier": PUBLICATION["pipeline_identifier"], "name": PUBLICATION["name"],
        "description": PUBLICATION["description"], "version": VERSION, "status": "active",
        "processingMode": "root", "tags": ["webhdp-link", "sandbox-validation"],
        "steps": [
            {"id": "prepare", "name": "Validate model and prepare files", "component_ref": "link_mesh_packager",
             "component_version": "1.0.0", "execution_profile_ref": "local", "scope": "record",
             "parameters": {"title": PUBLICATION["parameters"]["title"]["default"], "target_extent": 1},
             "input_bindings": [{"kind": "input", "target": "input_file", "type": "pipeline_source_file"}]},
            {"id": "deposit", "name": "Upload and verify unpublished Sandbox draft", "component_ref": "link_zenodo_sandbox_draft",
             "component_version": VERSION, "execution_profile_ref": "local", "scope": "record",
             "parameters": {"creator_name": PUBLICATION["parameters"]["creator_name"]["default"]},
             "input_bindings": [
                 *[{"kind": "input", "target": target, "type": "artifact_file", "source_step": "prepare", "source_output": output}
                   for target, output in [("metadata_file", "zenodo_metadata"), ("model_file", "model_file"),
                                          ("mesh_report", "mesh_report"), ("package_file", "evidence_bundle")]],
                 {"kind": "input", "target": "source", "type": "pipeline_source_file"},
             ]},
        ],
    }
    return manifest, definition, deepcopy(PUBLICATION)


def seed(service, *, python_executable=None):
    manifest, definition, publication = definitions(python_executable=python_executable)
    service.import_component_from_manifest(manifest, source_path=str(ROOT), source_type="external")
    service.create_pipeline_version_from_config(definition["identifier"], definition, activate=True)
    return publication
