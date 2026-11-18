"""Run HMSM Studio's portable processors through the WebHDP file contract."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import traceback


SOURCE = Path(__file__).resolve().with_name("hmsm-source.json")
DEFAULT_MODEL = "generic_65_no_dynamics"


def staged_file(inputs, name, *, required=False):
    value = inputs.get(name)
    if not value and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required.")
    root = Path(os.environ["WEBHDP_INPUT_DIR"]).resolve()
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"{name} must be a staged input file.")
    return path


def load_model(inputs, parameters, data):
    from backend.studio.models import MediaModel, all_models, get_model
    from backend.studio.settings import write_json

    profile = staged_file(inputs, "model_file")
    if profile is None:
        return get_model(parameters.get("model_id") or DEFAULT_MODEL)
    model = MediaModel.model_validate_json(profile.read_bytes())
    # A supplied snapshot stays in this run's isolated registry. A built-in ID
    # must not silently resolve to a different model in the extraction CLI.
    registered = next((item for item in all_models() if item.id == model.id), None)
    if registered is not None:
        if registered.public()["digest"] != model.public()["digest"]:
            raise ValueError("The supplied profile differs from the built-in model with that ID. Use a distinct model ID.")
        return registered
    write_json(data / "models" / f"{model.id}.json", model.model_dump(exclude_unset=True))
    return model


def options_path(inputs, parameters, data):
    file = staged_file(inputs, "options_file")
    inline = parameters.get("options_json") or ""
    if not isinstance(inline, str):
        raise ValueError("Options JSON must be provided as text.")
    if not inline.strip():
        return file
    if file is not None:
        raise ValueError("Choose either a staged options file or inline options JSON.")
    path = data / "options.json"
    path.write_text(inline, encoding="utf-8")
    return path


def sealed_scan_file(folder, filename, receipt):
    path = folder / "artifacts" / filename
    if receipt.get("file") != filename or path.is_symlink() or not path.is_file():
        raise ValueError(f"The declared optical evidence file {filename} is missing or unsafe.")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if receipt.get("bytes") != path.stat().st_size or receipt.get("sha256") != digest:
        raise ValueError(f"Optical evidence fixity failed for {filename}.")
    return path


def scan(source, inputs, parameters, data):
    from backend.studio.extract import ExtractionOptions
    from backend.studio.scan_artifacts import FILES, declaration

    model = load_model(inputs, parameters, data)
    options = options_path(inputs, parameters, data)
    classifier = staged_file(inputs, "classifier_file")
    settings = ExtractionOptions.model_validate_json(options.read_bytes()) if options else ExtractionOptions()
    if bool(settings.learned_model_id) != (classifier is not None):
        raise ValueError("Supply a frozen classifier and its matching ID and SHA-256 in the extraction options together.")
    command = [
        sys.executable, "-m", "backend.studio.cli", str(source),
        "--model", model.id, "--output-name", "scan",
    ]
    if options is not None:
        command.extend(["--options-json", str(options)])
    if classifier is not None:
        command.extend(["--classifier-json", str(classifier)])
    # Preserve native optical stages, published MIDI and the sealed worker
    # bundle, using the same path HMSM uses for local and compute CLI runs.
    if subprocess.run(command, cwd=SOURCE.parent, check=False).returncode:
        raise ValueError("HMSM scan digitization failed. See the component logs for details.")
    folder = data / "projects" / "scan"
    result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    files = {
        "midi_file": folder / "result.mid",
        "result_file": folder / "result.json",
        "project_file": folder / "project.json",
        "evidence_bundle": folder / "worker-bundle.zip",
        "source_preview": folder / "artifacts" / "source.webp",
        "track_preview": folder / "artifacts" / "tracks.webp",
        "validation_preview": folder / "artifacts" / "validation.webp",
    }
    for kind in ("physical-observations", "interpretation-decisions", "source-coverage", "source-coverage-mask"):
        receipt = declaration(result, kind)
        if receipt:
            files[kind.replace("-", "_")] = sealed_scan_file(folder, FILES[kind][0], receipt)
    substrate = result["geometry"].get("substrate_support_artifact")
    if substrate:
        files["substrate_support"] = sealed_scan_file(folder, "roll-substrate-support.json", substrate)
    return files, {
        "model_id": model.id,
        "media_type": model.media_type,
        "note_count": result["metrics"]["note_count"],
        "control_count": result["metrics"]["control_count"],
        "duration_seconds": result["duration"],
    }


def reconstruct(source, inputs, parameters, data):
    from backend.studio.reconstruction import generate
    from backend.studio.reconstruction_input import GenerationOptions, read_input

    model = load_model(inputs, parameters, data)
    options_file = options_path(inputs, parameters, data)
    options = GenerationOptions.model_validate_json(options_file.read_bytes()) if options_file else GenerationOptions()
    midi = read_input(source, sequence_track=options.sequence_track)
    if midi["source"]["requires_sequence"]:
        raise ValueError("Choose an independent Type-2 sequence using sequence_track in the options JSON.")
    result = generate(
        midi["notes"], model,
        title=parameters.get("title") or "Untitled reconstruction study",
        roll_speed_fpm=parameters.get("roll_speed", 6),
        disc_duration=parameters.get("revolution", 60),
        source_controls=midi["controls"],
        generation_options=options.model_dump(),
        source=midi["source"], source_path=source,
    )
    folder = data / "transforms" / result["id"]
    files = {
        "result_file": folder / "manifest.json",
        "transform_file": folder / "transform.json",
        "events_file": folder / "events.json",
        "performance_file": folder / "performance.json",
        "evidence_bundle": folder / "bundle.zip",
        "source_midi": folder / "source.mid",
        "midi_file": folder / "playback.mid",
        "medium_svg": folder / "medium.svg",
        "physical_svg": folder / "physical.svg",
        "cutting_svg": folder / "cutting.svg",
        "source_preview": folder / "preview.webp",
    }
    if result.get("print_pdf"):
        files["print_pdf"] = folder / "print.pdf"
    if result.get("punching_json"):
        files["punching_file"] = folder / "punching.json"
    return files, {
        "model_id": model.id,
        "media_type": model.media_type,
        "represented_notes": result["represented_notes"],
        "omitted_notes": result["omitted_notes"],
        "validation": result["validation"]["status"],
        "fabrication_ready": result["validation"]["fabrication_ready"],
    }


def interpret(source, inputs, parameters, data):
    from backend.studio.interpretation import AnalysisOptions, analyze
    from backend.studio.settings import write_json

    options_file = options_path(inputs, parameters, data)
    options = AnalysisOptions.model_validate_json(options_file.read_bytes()) if options_file else AnalysisOptions()
    score = staged_file(inputs, "score_file")
    try:
        report = analyze(source, options, score)
    except IndexError as exc:
        # This HMSM score_features failure occurs when its match list is empty.
        if (
            score is not None
            and traceback.extract_tb(exc.__traceback__)[-1].name == "score_features"
            and str(exc).startswith("boolean index did not match indexed array")
        ):
            raise ValueError("The written-score MIDI could not be aligned to any performance notes.") from exc
        raise
    path = data / "analysis.json"
    write_json(path, report)
    return {"report_file": path}, {
        "summary": report["summary"],
        "alignment_status": report["alignment"]["status"],
        "features_sha256": report["features_sha256"],
    }


def run_component(process, request):
    inputs = request.get("inputs") or {}
    parameters = request.get("parameters") or {}
    source = staged_file(inputs, "input_file", required=True)
    output = Path(os.environ["WEBHDP_OUTPUT_DIR"]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="hmsm-webhdp-") as directory:
        data = Path(directory)
        os.environ["HMSM_DATA_DIR"] = str(data)
        files, summary = process(source, inputs, parameters, data)
        files["runtime_manifest"] = SOURCE
        for path in files.values():
            if not path.is_file():
                raise ValueError(f"HMSM did not produce the expected file {path.name}.")
        outputs = {}
        artifacts = []
        for key, path in files.items():
            target = output / path.name
            shutil.copyfile(path, target)
            outputs[key] = str(target)
            artifacts.append({
                "name": target.name,
                "artifact_kind": "file",
                "path": str(target),
                "metadata": {"role": key},
            })
    return {"success": True, "status": "completed", "outputs": outputs, "artifacts": artifacts, "summary": summary}


def main():
    processes = {"scan": scan, "reconstruct": reconstruct, "interpret": interpret}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("processor", choices=processes)
    args = parser.parse_args()
    response = Path(os.environ["WEBHDP_COMPONENT_RESPONSE"])
    try:
        request = json.loads(Path(os.environ["WEBHDP_COMPONENT_REQUEST"]).read_text(encoding="utf-8"))
        result = run_component(processes[args.processor], request)
    except Exception as exc:
        traceback.print_exc()
        result = {"success": False, "status": "failed", "error": str(exc)}
    response.parent.mkdir(parents=True, exist_ok=True)
    response.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
