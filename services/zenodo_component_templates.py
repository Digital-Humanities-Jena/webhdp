"""Install-gated recipes for the published Zenodo HDP community adapters."""
from copy import deepcopy

ZENODO_COMPONENT_KEYS = frozenset({
    "validate_file_integrity", "hdpc_exporter", "obj_to_glb_converter",
    "obj_statistics_extractor", "mtl_metadata_extractor", "glb_metadata_extractor",
    "image_metadata_extractor",
})
LABELS = {
    "validate_file_integrity": "File integrity validation",
    "hdpc_exporter": "HDPC CSV export",
    "obj_to_glb_converter": "OBJ to GLB conversion",
    "obj_statistics_extractor": "OBJ geometry statistics",
    "mtl_metadata_extractor": "Material metadata extraction",
    "glb_metadata_extractor": "GLB metadata extraction",
    "image_metadata_extractor": "Image metadata extraction",
}


def step(key):
    return {"id": key, "name": LABELS[key], "component_ref": key,
            "execution_profile_ref": "local_docker", "scope": "record", "parameters": {},
            "input_bindings": [{"kind": "input", "target": "input_file", "type": "pipeline_source_file"}]}


def recipe(identifier, name, steps):
    return {"identifier": identifier, "name": name, "version": "1.0.0", "status": "active",
            "description": "Published Zenodo community functionality through verified WebHDP file contracts.",
            "modality": "General", "processingMode": "root", "tags": ["zenodo-community"],
            "steps": deepcopy(steps)}


ZENODO_PIPELINE_DEFINITIONS = {
    "zenodo_" + key: recipe("zenodo_" + key, "Zenodo: " + LABELS[key], [step(key)])
    for key in sorted(ZENODO_COMPONENT_KEYS)
}
inspect = step("glb_metadata_extractor")
inspect["input_bindings"] = [{"kind": "input", "target": "input_file", "type": "artifact_file",
                              "source_step": "obj_to_glb_converter", "source_output": "model_file"}]
ZENODO_PIPELINE_DEFINITIONS["zenodo_obj_to_glb_and_inspect"] = recipe(
    "zenodo_obj_to_glb_and_inspect", "Zenodo: Convert OBJ and inspect GLB",
    [step("obj_to_glb_converter"), inspect],
)
