#!/usr/bin/env python3
"""Build the local HMSM component image from an explicit Git worktree."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


RUNTIME_DIR = Path(__file__).resolve().parents[1] / "external_code" / "hmsm_component_runtime"
IMAGE = "webhdp-hmsm-studio:local"
SOURCE_FILES = (
    "LICENSE",
    "requirements.txt",
    "backend/__init__.py",
    "backend/data/carrier-operational-evidence.json",
    "backend/data/models.json",
    "backend/vendor/HMSM-LICENSE",
    "docs/ATTRIBUTION.md",
)
STUDIO_FILES = "backend/studio/*.py"
REQUIRED_MODULES = (
    "backend/studio/__init__.py",
    "backend/studio/cli.py",
    "backend/studio/interpretation.py",
    "backend/studio/reconstruct_cli.py",
    "backend/studio/scan_artifacts.py",
)


def git(source: Path, *args: str) -> bytes:
    return subprocess.check_output(
        ["git", "--no-optional-locks", "-C", str(source), *args],
    )


def git_state(source: Path) -> tuple[str, dict[str, str]]:
    commit = git(source, "rev-parse", "HEAD").decode("ascii").strip()
    status = git(
        source,
        "status",
        "--porcelain=v1",
        "--no-renames",
        "--untracked-files=all",
        "-z",
        "--",
        *SOURCE_FILES,
        f":(glob){STUDIO_FILES}",
    )
    changes = {}
    for record in filter(None, status.split(b"\0")):
        relative = os.fsdecode(record[3:])
        if not Path(relative).name.startswith("."):
            changes[relative] = record[:2].decode("ascii").strip()
    return commit, changes


def packaged_files(source: Path) -> list[Path]:
    module_files = git(
        source, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--",
        f":(glob){STUDIO_FILES}",
    )
    paths = {source / relative for relative in SOURCE_FILES}
    for name in filter(None, module_files.split(b"\0")):
        path = source / os.fsdecode(name)
        if not path.name.startswith(".") and (path.exists() or path.is_symlink()):
            paths.add(path)
    return sorted(paths)


def stage_context(source: Path, context: Path) -> dict:
    source = source.resolve(strict=True)
    repo_root = Path(os.fsdecode(git(source, "rev-parse", "--show-toplevel")).removesuffix("\n"))
    if repo_root.resolve() != source:
        raise ValueError("--source must be the root of the HMSM Studio worktree.")
    for relative in (*SOURCE_FILES, *REQUIRED_MODULES):
        if not (source / relative).is_file():
            raise ValueError(f"Missing HMSM Studio source file {relative}")

    commit, changes = git_state(source)
    paths = packaged_files(source)
    file_digests = {}
    for path in paths:
        relative = path.relative_to(source).as_posix()
        if path.is_symlink() or path.resolve() != path or not path.is_file():
            raise ValueError(f"Expected an ordinary source file at {relative}")
        contents = path.read_bytes()
        target = context / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
        file_digests[relative] = hashlib.sha256(contents).hexdigest()

    current_digests = {}
    for path in packaged_files(source):
        if path.is_file() and not path.is_symlink() and path.resolve() == path:
            with path.open("rb") as stream:
                current_digests[path.relative_to(source).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
    if current_digests != file_digests or git_state(source) != (commit, changes):
        raise ValueError("HMSM Studio changed during staging. Build again from a stable worktree.")

    snapshot_sha256 = hashlib.sha256(
        json.dumps(file_digests, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest = {
        "schema_version": "hmsm-component-source/1",
        "license": "GPL-3.0-or-later",
        "commit": commit,
        "dirty": bool(changes),
        "source_changes": changes,
        "snapshot_sha256": snapshot_sha256,
        "files": file_digests,
    }
    (context / "hmsm-source.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for name in ("Dockerfile", "component_runner.py"):
        shutil.copyfile(RUNTIME_DIR / name, context / name)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Path to the HMSM Studio Git worktree")
    parser.add_argument("--docker-context", help="Use this Docker context instead of the active one")
    args = parser.parse_args()
    docker = ["docker"]
    if args.docker_context:
        docker.extend(["--context", args.docker_context])

    try:
        with tempfile.TemporaryDirectory(prefix="webhdp-hmsm-build-") as temporary:
            context = Path(temporary)
            snapshot = stage_context(args.source, context)
            print(
                f"HMSM Studio {snapshot['commit']} ({'dirty' if snapshot['dirty'] else 'clean'} packaged source), "
                f"snapshot SHA-256 {snapshot['snapshot_sha256']}",
                flush=True,
            )
            subprocess.run(
                [
                    *docker,
                    "build",
                    "--tag",
                    IMAGE,
                    "--label",
                    f"org.opencontainers.image.revision={snapshot['commit']}",
                    "--label",
                    f"org.webhdp.hmsm.snapshot-sha256={snapshot['snapshot_sha256']}",
                    "--label",
                    f"org.webhdp.hmsm.source-dirty={str(snapshot['dirty']).lower()}",
                    str(context),
                ],
                check=True,
            )
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Could not build {IMAGE}: {exc}\n")


if __name__ == "__main__":
    main()
