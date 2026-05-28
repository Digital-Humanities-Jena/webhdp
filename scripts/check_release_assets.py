#!/usr/bin/env python3
"""Validate curated binary/media assets for the public release tree."""

from __future__ import annotations

import re
import subprocess
import sys
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIDEO_DIR = Path("docs/assets/screen_recordings/raw")
SUBTITLE_DIR = Path("docs/assets/screen_recordings/subtitles")
MANIFEST_PATH = Path("docs/assets/screen_recordings/manifest.json")
MAX_VIDEO_BYTES = 5 * 1024 * 1024


def load_manifest() -> tuple[set[Path], set[Path], set[Path], list[str]]:
    manifest_file = ROOT / MANIFEST_PATH
    if not manifest_file.exists():
        return set(), set(), set(), [f"{MANIFEST_PATH} is missing."]

    errors: list[str] = []
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return set(), set(), set(), [f"{MANIFEST_PATH} is not valid JSON: {exc}"]

    entries = manifest.get("entries")
    if not isinstance(entries, list):
        return set(), set(), set(), [f"{MANIFEST_PATH} must contain an entries list."]

    webms: set[Path] = set()
    videos: set[Path] = set()
    subtitles: set[Path] = set()
    ids: list[str] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            errors.append(f"Manifest entry {index} is not an object.")
            continue

        entry_id = entry.get("id")
        webm = entry.get("webm")
        video = entry.get("video")
        subtitle = entry.get("subtitles")
        title = entry.get("title")
        source_document = entry.get("source_document")

        if not isinstance(entry_id, str) or not entry_id:
            errors.append(f"Manifest entry {index} has no id.")
        else:
            ids.append(entry_id)
        if not isinstance(title, str) or not title:
            errors.append(f"Manifest entry {entry_id or index} has no title.")
        if not isinstance(source_document, str) or not (ROOT / source_document).exists():
            errors.append(f"Manifest entry {entry_id or index} references missing source document: {source_document}")
        if not isinstance(webm, str):
            errors.append(f"Manifest entry {entry_id or index} has no WebM fallback path.")
        else:
            webms.add(Path(webm))
        if not isinstance(video, str):
            errors.append(f"Manifest entry {entry_id or index} has no video path.")
        else:
            videos.add(Path(video))
        if not isinstance(subtitle, str):
            errors.append(f"Manifest entry {entry_id or index} has no subtitle path.")
        else:
            subtitles.add(Path(subtitle))

    duplicate_ids = sorted({entry_id for entry_id in ids if ids.count(entry_id) > 1})
    if duplicate_ids:
        errors.append("Duplicate screen-recording manifest IDs:\n  " + "\n  ".join(duplicate_ids))

    return webms, videos, subtitles, errors


def git_release_files() -> set[Path]:
    try:
        output = subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
        )
        return {path for item in output.split(b"\0") if item and (ROOT / (path := Path(item.decode()))).exists()}
    except (subprocess.CalledProcessError, FileNotFoundError):
        ignored_dirs = {
            ".git",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            "__pycache__",
            "dist",
            "node_modules",
        }
        return {
            path.relative_to(ROOT)
            for path in ROOT.rglob("*")
            if path.is_file() and not any(part in ignored_dirs for part in path.relative_to(ROOT).parts)
        }


def referenced_media(extension: str) -> set[Path]:
    pattern = re.compile(rf"/api/v1/docs/assets/(screen_recordings/raw/[^\"'<>\s]+\.{extension})")
    refs: set[Path] = set()
    for path in (ROOT / "docs").rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        refs.update(Path("docs/assets") / match for match in pattern.findall(text))
    return refs


def referenced_videos() -> set[Path]:
    return referenced_media("mp4")


def referenced_webms() -> set[Path]:
    return referenced_media("webm")


def referenced_subtitles() -> set[Path]:
    pattern = re.compile(r"/api/v1/docs/assets/(screen_recordings/subtitles/[^\"'<>\s]+\.vtt)")
    refs: set[Path] = set()
    for path in (ROOT / "docs").rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        refs.update(Path("docs/assets") / match for match in pattern.findall(text))
    return refs


def main() -> int:
    release_files = git_release_files()
    errors: list[str] = []
    expected_webms, expected_videos, expected_subtitles, manifest_errors = load_manifest()
    errors.extend(manifest_errors)

    os_metadata = sorted(path for path in release_files if path.name == ".DS_Store" or path.name.startswith("._"))
    if os_metadata:
        errors.append("OS metadata files are publishable:\n  " + "\n  ".join(str(path) for path in os_metadata))

    shipped_webms = {path for path in release_files if path.parent == VIDEO_DIR and path.suffix == ".webm"}
    if shipped_webms != expected_webms:
        missing = sorted(expected_webms - shipped_webms)
        unexpected = sorted(shipped_webms - expected_webms)
        if missing:
            errors.append("Expected documentation WebM fallbacks are missing:\n  " + "\n  ".join(str(path) for path in missing))
        if unexpected:
            errors.append("Unexpected documentation WebM fallbacks are publishable:\n  " + "\n  ".join(str(path) for path in unexpected))

    shipped_videos = {path for path in release_files if path.parent == VIDEO_DIR and path.suffix == ".mp4"}
    if shipped_videos != expected_videos:
        missing = sorted(expected_videos - shipped_videos)
        unexpected = sorted(shipped_videos - expected_videos)
        if missing:
            errors.append("Expected documentation videos are missing:\n  " + "\n  ".join(str(path) for path in missing))
        if unexpected:
            errors.append("Unexpected documentation videos are publishable:\n  " + "\n  ".join(str(path) for path in unexpected))

    shipped_subtitles = {path for path in release_files if path.parent == SUBTITLE_DIR and path.suffix == ".vtt"}
    if shipped_subtitles != expected_subtitles:
        missing = sorted(expected_subtitles - shipped_subtitles)
        unexpected = sorted(shipped_subtitles - expected_subtitles)
        if missing:
            errors.append("Expected documentation subtitles are missing:\n  " + "\n  ".join(str(path) for path in missing))
        if unexpected:
            errors.append("Unexpected documentation subtitles are publishable:\n  " + "\n  ".join(str(path) for path in unexpected))

    webm_refs = referenced_webms()
    if webm_refs != expected_webms:
        missing_refs = sorted(expected_webms - webm_refs)
        stale_refs = sorted(webm_refs - expected_webms)
        if missing_refs:
            errors.append("Documentation WebM fallbacks are not referenced by guide pages:\n  " + "\n  ".join(str(path) for path in missing_refs))
        if stale_refs:
            errors.append("Guide pages reference unmanaged WebM fallbacks:\n  " + "\n  ".join(str(path) for path in stale_refs))

    refs = referenced_videos()
    if refs != expected_videos:
        missing_refs = sorted(expected_videos - refs)
        stale_refs = sorted(refs - expected_videos)
        if missing_refs:
            errors.append("Documentation videos are not referenced by guide pages:\n  " + "\n  ".join(str(path) for path in missing_refs))
        if stale_refs:
            errors.append("Guide pages reference unmanaged videos:\n  " + "\n  ".join(str(path) for path in stale_refs))

    subtitle_refs = referenced_subtitles()
    if subtitle_refs != expected_subtitles:
        missing_refs = sorted(expected_subtitles - subtitle_refs)
        stale_refs = sorted(subtitle_refs - expected_subtitles)
        if missing_refs:
            errors.append("Documentation subtitles are not referenced by guide pages:\n  " + "\n  ".join(str(path) for path in missing_refs))
        if stale_refs:
            errors.append("Guide pages reference unmanaged subtitles:\n  " + "\n  ".join(str(path) for path in stale_refs))

    for video in sorted(expected_videos):
        video_file = ROOT / video
        if not video_file.exists():
            continue
        size = video_file.stat().st_size
        if size > MAX_VIDEO_BYTES:
            errors.append(f"{video} is {size} bytes; move large media to release assets or Git LFS.")

    for webm in sorted(expected_webms):
        webm_file = ROOT / webm
        if not webm_file.exists():
            continue
        size = webm_file.stat().st_size
        if size > MAX_VIDEO_BYTES:
            errors.append(f"{webm} is {size} bytes; move large media to release assets or Git LFS.")

    for subtitle in sorted(expected_subtitles):
        subtitle_file = ROOT / subtitle
        if not subtitle_file.exists():
            continue
        text = subtitle_file.read_text(encoding="utf-8")
        if not text.startswith("WEBVTT"):
            errors.append(f"{subtitle} is not a WebVTT subtitle file.")

    docs_assets = {path for path in release_files if path.parts[:2] == ("docs", "assets")}
    allowed_docs_assets = (
        expected_webms
        | expected_videos
        | expected_subtitles
        | {Path("docs/assets/screen_recordings/README.md"), MANIFEST_PATH}
    )
    unexpected_docs_assets = sorted(docs_assets - allowed_docs_assets)
    if unexpected_docs_assets:
        errors.append("Unexpected docs/assets files are publishable:\n  " + "\n  ".join(str(path) for path in unexpected_docs_assets))

    if errors:
        print("Release asset check failed.", file=sys.stderr)
        for error in errors:
            print(f"\n{error}", file=sys.stderr)
        return 1

    print(
        "Release asset check passed: "
        f"{len(expected_webms)} WebM fallback(s), "
        f"{len(expected_videos)} curated documentation video(s), "
        f"{len(expected_subtitles)} subtitle file(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
