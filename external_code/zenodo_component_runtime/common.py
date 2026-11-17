"""Shared portable file contract for the GPL-3.0-or-later community adapters."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return path


def staged_file(inputs, name="input_file", required=True):
    value = inputs.get(name)
    if value in (None, "") and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a staged file path")
    root = Path(os.environ.get("WEBHDP_INPUT_DIR", "/inputs")).resolve(strict=True)
    path = root / value
    resolved = path.resolve(strict=True)
    if path.is_symlink() or not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(f"{name} is outside the staged input directory or not a regular file")
    return resolved


def safe_unpack(source, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    seen, size = set(), 0
    with zipfile.ZipFile(source) as archive:
        if len(archive.infolist()) > 20000:
            raise ValueError("Archive has too many entries")
        for item in archive.infolist():
            name = item.filename
            pure = PurePosixPath(name)
            mode = item.external_attr >> 16
            if (not name or pure.is_absolute() or "\\" in name or "\0" in name
                    or ":" in pure.parts[0] or any(p in {"", ".", ".."} for p in name.rstrip("/").split("/"))
                    or name.rstrip("/").casefold() in seen
                    or stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}
                    or item.flag_bits & 1):
                raise ValueError("Unsafe, duplicate, encrypted or linked archive member")
            seen.add(name.rstrip("/").casefold())
            size += item.file_size
            if size > 4 * 1024**3 or item.file_size > 2 * 1024**3:
                raise ValueError("Archive exceeds the unpacked size limit")
            target = destination.joinpath(*pure.parts)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as src, target.open("xb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
    return destination


def checked_parameters(raw, spec):
    if not isinstance(raw, dict) or set(raw) - set(spec):
        raise ValueError("Unknown component parameter")
    result = {}
    for name, (default, kind, bounds) in spec.items():
        value = raw.get(name, default)
        if type(value) is not kind:
            raise ValueError(f"{name} must be {kind.__name__}")
        if isinstance(bounds, set) and value not in bounds:
            raise ValueError(f"Unsupported {name}")
        if isinstance(bounds, tuple) and not bounds[0] <= value <= bounds[1]:
            raise ValueError(f"{name} is outside the supported range")
        result[name] = value
    return result
