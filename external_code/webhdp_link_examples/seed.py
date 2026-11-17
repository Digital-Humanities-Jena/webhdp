"""Explicit operator installation of the three WebHDP-Link example pipelines.

Call seed(app.native_pipeline_service, hmsm_source=..., hmsm_python=...) from
an application context. The returned allowlisted publication payloads can be
passed to WebHDP-Link's administrator publication endpoint/service.
"""

from copy import deepcopy
import os
from pathlib import Path
import sys

import yaml

from .runner import digest, hmsm_source_digest


ROOT = Path(__file__).resolve().parent

PUBLICATIONS = [
    {
        "id": "link-photo-preparation", "name": "Photo set preparation", "pipeline_identifier": "link_photo_preparation",
        "description": "Inspect photographs and create a contact sheet with a checksummed reconstruction handoff. No photogrammetry is performed.",
        "pipeline_version": "1.0.0", "enabled": True, "execution_mode": "bundle",
        "input": {"min_files": 1, "max_files": 30, "extensions": [".jpg", ".jpeg", ".png", ".webp"]},
        "parameters": {"max_side": {"step_id": "process", "parameter": "max_side", "type": "integer", "minimum": 64, "maximum": 1024, "default": 320, "label": "Contact sheet image size"}},
    },
    {
        "id": "link-piano-roll", "name": "HMSM piano-roll digitization", "pipeline_identifier": "link_piano_roll",
        "description": "Extract candidate notes and MIDI from a scan using the actual HMSM optical processor and a declared generic 65-note profile.",
        "pipeline_version": "1.0.0", "enabled": True, "execution_mode": "record",
        "input": {"min_files": 1, "max_files": 10, "extensions": [".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"]},
        "parameters": {
            "model_id": {"step_id": "process", "parameter": "model_id", "type": "string", "enum": ["generic_65_no_dynamics"], "default": "generic_65_no_dynamics", "label": "Carrier profile"},
            "roll_speed": {"step_id": "process", "parameter": "roll_speed", "type": "number", "minimum": 0.2, "maximum": 30, "default": 6, "label": "Roll speed (feet/minute)"},
        },
    },
    {
        "id": "link-model-deposit", "name": "3D model preparation", "pipeline_identifier": "link_model_package",
        "description": "Check triangular geometry-only OBJ, normalize it to GLB, and prepare a checksummed repository package. No Zenodo upload or publication.",
        "pipeline_version": "1.0.0", "enabled": True, "execution_mode": "record",
        "input": {"min_files": 1, "max_files": 10, "extensions": [".obj"]},
        "parameters": {
            "title": {"step_id": "process", "parameter": "title", "type": "string", "minLength": 1, "maxLength": 200, "default": "Model preparation", "label": "Dataset title"},
            "target_extent": {"step_id": "process", "parameter": "target_extent", "type": "number", "minimum": 0.01, "maximum": 1000, "default": 1, "label": "Normalized largest extent"},
        },
    },
]

COMPONENT_KEYS = ("link_photo_inspector", "link_hmsm_digitizer", "link_mesh_packager")


def definitions(*, hmsm_source=None, hmsm_python=None, python_executable=None):
    """Resolve trusted runtime paths; none of these fields are client parameters."""
    python = str(Path(python_executable or sys.executable).absolute())
    source = hmsm_source or os.environ.get("WEBHDP_LINK_HMSM_SOURCE")
    interpreter = hmsm_python or os.environ.get("WEBHDP_LINK_HMSM_PYTHON")
    if not source or not interpreter:
        raise ValueError("Provide the trusted HMSM source checkout and its installed Python runtime.")
    source, interpreter = Path(source).resolve(), Path(interpreter).absolute()
    if not (source / "backend/studio/cli.py").is_file() or not interpreter.is_file():
        raise ValueError("The configured HMSM source or Python runtime is unavailable.")
    result = []
    for key, publication in zip(COMPONENT_KEYS, PUBLICATIONS):
        manifest = yaml.safe_load((ROOT / key / "component.yaml").read_text())
        profile = manifest["execution"]["profiles"][0]
        operation = profile["entrypoint"][-1]
        profile["entrypoint"] = [python, str(ROOT / "runner.py"), operation,
                                 "--expected-runner-sha256", digest(ROOT / "runner.py")]
        if key == "link_hmsm_digitizer":
            profile["entrypoint"] += ["--hmsm-source", str(source), "--hmsm-python", str(interpreter),
                                       "--hmsm-source-sha256", hmsm_source_digest(source)]
        definition = {
            "identifier": publication["pipeline_identifier"], "name": publication["name"],
            "description": publication["description"], "version": publication["pipeline_version"], "status": "active",
            "processingMode": "root", "tags": ["webhdp-link", "reference-application"],
            "steps": [{"id": "process", "name": publication["name"], "component_ref": key,
                       "execution_profile_ref": "local", "scope": "record",
                       "parameters": {name: field["default"] for name, field in publication["parameters"].items()},
                       "input_bindings": [{"kind": "input", "target": "input_files" if key == "link_photo_inspector" else "input_file",
                                           "type": "pipeline_source_files" if key == "link_photo_inspector" else "pipeline_source_file"}]}],
        }
        result.append((manifest, definition, deepcopy(publication)))
    return result


def seed(service, *, hmsm_source=None, hmsm_python=None, python_executable=None):
    """Install fixed component/pipeline versions and return Link publication data.

    Repeated calls with identical source are idempotent. A changed executable
    fails version immutability; deliberately issue a new version when upgrading.
    """
    publications = []
    for manifest, definition, publication in definitions(hmsm_source=hmsm_source, hmsm_python=hmsm_python, python_executable=python_executable):
        service.import_component_from_manifest(manifest, source_path=str(ROOT / manifest["metadata"]["name"]), source_type="external")
        service.create_pipeline_version_from_config(definition["identifier"], definition, activate=True)
        publications.append(publication)
    return publications
