"""Preserve dependency paths when a model is downloaded from a flat record."""

import hashlib
import os
from pathlib import Path
import zipfile


def create_source_bundle(source_path, file_tree, output_dir):
    source = Path(source_path).resolve()
    if source.suffix.lower() not in {".gltf", ".obj"}:
        return None

    def walk(nodes):
        for node in nodes or []:
            yield node
            yield from walk(node.get("children"))

    root = next(
        (
            node
            for node in walk(file_tree)
            if node.get("absolute_path")
            and Path(node["absolute_path"]).resolve() == source
        ),
        None,
    )
    if root is None:
        return None
    paths = {source}
    for node in walk(root.get("children")):
        raw_path = node.get("absolute_path") or node.get("path")
        if not raw_path:
            continue
        path = Path(raw_path).resolve()
        # Include the original files inside an existing texture archive.
        if path.suffix.lower() == ".zip" and node.get("children"):
            continue
        if path.is_file():
            paths.add(path)
    if all(path.parent == source.parent for path in paths):
        return None

    common_root = Path(os.path.commonpath([str(path.parent) for path in paths]))
    identity = hashlib.sha256(str(source).encode()).hexdigest()[:16]
    destination = Path(output_dir) / identity / (source.name + ".sources.zip")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".zip.tmp")
    try:
        with zipfile.ZipFile(
            temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=1
        ) as archive:
            for path in sorted(paths):
                archive.write(path, path.relative_to(common_root).as_posix())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return str(destination)
