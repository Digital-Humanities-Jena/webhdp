"""Locate files emitted into a native pipeline step's isolated output directory."""

import os
from pathlib import Path


def pipeline_artifact_location(session, step, artifact) -> Path | None:
    if (
        not session or not session.session_dir or not step or not step.record_path
        or step.record_id is None or not artifact.path
        or step.pipeline_run_id != artifact.pipeline_run_id
        or step.id != artifact.step_run_id or step.record_id != artifact.record_id
    ):
        return None

    candidate = Path(artifact.path)
    if not candidate.is_absolute() or ".." in candidate.parts:
        return None

    try:
        session_path = Path(session.session_dir).expanduser().absolute()
        session_root = session_path.resolve()
        if candidate.is_relative_to(session_path):
            candidate = session_root / candidate.relative_to(session_path)
        source_stem = os.path.splitext(os.path.basename(step.record_path))[0]
        output_root = session_root / "outputs" / f"record-{step.record_id}" / source_stem / f"step-{step.id}" / "outputs"
        if not candidate.is_relative_to(output_root) or candidate.resolve(strict=True) != candidate:
            return None
        if candidate.is_file():
            return candidate
    except (OSError, RuntimeError, ValueError):
        return None
    return None
