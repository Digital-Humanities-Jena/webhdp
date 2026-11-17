"""Install-gated historic reconstruction recipes for the native constructor.

Each record is a portable ZIP representing one scene, not one photograph.
Manifests remain in the installable catalog; importing an unpinned manifest must
never make a recipe runnable. Native validation supplies that gate.
"""

from copy import deepcopy
import math


def _source(stage, profile, **parameters):
    return {
        "id": stage,
        "name": stage.replace("_", " ").capitalize(),
        "component_ref": f"historic_{stage}",
        "execution_profile_ref": profile,
        "scope": "record",
        "parameters": parameters,
        "input_bindings": [{"kind": "input", "target": "input_file", "type": "pipeline_source_file"}],
    }


def _after(stage, profile, previous, output, **parameters):
    step = _source(stage, profile, **parameters)
    step["input_bindings"] = [{
        "kind": "input", "target": "input_file", "type": "artifact_file",
        "source_step": previous, "source_output": output,
    }]
    return step


def _recipe(identifier, name, description, steps):
    return {
        "identifier": identifier, "name": name, "description": description,
        "version": "1.0.0", "status": "active", "modality": "Photogrammetry",
        "processingMode": "root", "tags": ["historic-reconstruction", "photogrammetry"],
        "steps": deepcopy(steps),
    }


HISTORIC_PIPELINE_DEFINITIONS = {}
for suffix, profile in (("", "local_docker"), ("_hpc", "hpc_singularity")):
    label = " (HPC)" if suffix else " (local CPU)"
    prepare = _source("prepare", profile)
    pairs = _after("pairs", profile, "prepare", "dataset")
    sparse = _after("sparse", profile, "pairs", "dataset", use_gpu=bool(suffix))
    for key, title, steps in (
        ("prepare_images", "Historic image preparation", [prepare]),
        ("prepare_pairs", "Historic image preparation and pairs", [prepare, pairs]),
        ("sparse_reconstruction", "Historic sparse reconstruction", [prepare, pairs, sparse]),
        ("georeference", "Historic control-point georeferencing", [_source("georeference", profile)]),
    ):
        identifier = f"historic_{key}{suffix}"
        HISTORIC_PIPELINE_DEFINITIONS[identifier] = _recipe(
            identifier, title + label,
            "Process one photograph ZIP per scene. Preserve source identities and checksummed stage artifacts.", steps,
        )
    if suffix:
        identifier = "historic_dense_reconstruction_hpc"
        HISTORIC_PIPELINE_DEFINITIONS[identifier] = _recipe(
            identifier, "Historic sparse-to-dense reconstruction (HPC)",
            "Prepare a photograph ZIP, select pairs, reconstruct sparse cameras, then fuse dense depth and mesh on CUDA.",
            [prepare, pairs, sparse, _after("dense", profile, "sparse", "reconstruction")],
        )

for stage, label in (
    ("segmentation", "Semantic masks"),
    ("original_sfm", "Learned-feature sparse reconstruction"),
    ("geolocalization", "Historic and panorama geolocalization"),
    ("dense_intrinsics", "Dense intrinsic refinement"),
    ("refine_keypoints", "Tracked keypoint refinement"),
    ("mvs", "MVS Anywhere meshing"),
):
    identifier = f"historic_research_{stage}_hpc"
    HISTORIC_PIPELINE_DEFINITIONS[identifier] = _recipe(
        identifier, f"Historic research: {label}",
        "Run the separately provisioned, source-pinned upstream research stage on an image or workspace ZIP. "
        "Requires the research runtime, model weights and the stage-specific input layout.",
        [_source(stage, "hpc_singularity")],
    )

HISTORIC_COMPONENT_KEYS = frozenset(
    step["component_ref"] for recipe in HISTORIC_PIPELINE_DEFINITIONS.values() for step in recipe["steps"]
) | {"historic_georeference"}


def parameter_errors(step_id, definitions, parameters):
    """Check bounded scientific settings before reserving remote compute."""
    errors = []
    for name, value in parameters.items():
        field = definitions.get(name)
        label = f"Step '{step_id}' parameter '{name}'"
        if field is None:
            errors.append(f"{label} is not declared by the component.")
            continue
        kind = field.get("type")
        valid = (
            type(value) is bool if kind == "boolean" else
            type(value) is int if kind == "integer" else
            type(value) in (int, float) and math.isfinite(value) if kind == "number" else
            isinstance(value, str) if kind in {"string", "string_dropdown", "text"} else True
        )
        if not valid:
            errors.append(f"{label} must be a valid {kind}.")
            continue
        choices = field.get("enum") or field.get("options")
        if choices and value not in choices:
            errors.append(f"{label} must be one of {', '.join(map(str, choices))}.")
        if kind in {"integer", "number"}:
            for bound, symbol, compare in (
                ("minimum", ">=", lambda a, b: a >= b),
                ("maximum", "<=", lambda a, b: a <= b),
                ("exclusiveMinimum", ">", lambda a, b: a > b),
            ):
                if bound in field and not compare(value, field[bound]):
                    errors.append(f"{label} must be {symbol} {field[bound]}.")
    return errors
