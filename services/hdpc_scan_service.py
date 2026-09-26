"""Local-first .hdpc project bootstrap and file scanning helpers."""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
from urllib.parse import unquote, urlsplit

from exceptions import SecurityError
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from services.hdpc_local_service import _file_sha256, _guess_mime_type, _upsert_project_config
from services.hdpc_schema_service import HDPC_SCHEMA_VERSION, connect_hdpc, ensure_hdpc_schema, write_hdpc_provenance

logger = logging.getLogger(__name__)

EXCLUDED_DIR_NAMES = {"__macosx", "__pycache__"}
TEXTURE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".webp", ".tga", ".dds", ".ktx", ".ktx2"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validation_report(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    is_valid = True

    if not path.exists():
        is_valid = False
        errors.append("File does not exist at the specified path.")
    elif path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(path, "r") as archive:
                bad_file = archive.testzip()
            if bad_file:
                is_valid = False
                errors.append(f"ZIP archive is corrupted at member: {bad_file}")
        except zipfile.BadZipFile:
            is_valid = False
            errors.append("ZIP archive is invalid.")

    return {
        "file_path": str(path),
        "is_valid": is_valid,
        "errors": errors,
        "details": {
            "mime_type": _guess_mime_type(str(path)),
            "file_extension": path.suffix.lower(),
        },
    }


def _extract_bundling_key(filename: str, bundling_config: Dict[str, Any]) -> Optional[str]:
    strategy = str((bundling_config or {}).get("strategy") or "stem").strip().lower()
    stem = Path(filename).stem

    if strategy in {"stem", "stem_match"}:
        return stem

    if strategy == "pattern":
        pattern_str = str((bundling_config or {}).get("pattern") or "").strip()
        if not pattern_str:
            return None
        try:
            match = re.search(pattern_str, stem)
        except re.error:
            match = None
        if match:
            return match.group(1) if match.groups() else match.group(0)
        return pattern_str if pattern_str in stem else None

    if strategy == "prefix_suffix":
        prefix = str((bundling_config or {}).get("prefix") or "")
        suffix = str((bundling_config or {}).get("suffix") or "")
        value = stem
        if prefix and value.startswith(prefix):
            value = value[len(prefix) :]
        if suffix and value.endswith(suffix):
            value = value[: -len(suffix)]
        return value or None

    return stem


def _is_excluded_path(path: Path) -> bool:
    return any(part.lower() in EXCLUDED_DIR_NAMES for part in path.parts)


def _dependency_path(base: Path, reference: str, root: Path | None) -> Path:
    candidate = (base / reference.replace("\\", "/")).resolve()
    if root is not None and candidate != root and root not in candidate.parents:
        raise SecurityError("A model dependency points outside the uploaded dataset")
    return candidate


def _texture_reference(line: str) -> str:
    tokens = shlex.split(line.replace("\\", "/"), comments=False)[1:]
    arities = {"-blendu": 1, "-blendv": 1, "-boost": 1, "-mm": 2, "-texres": 1,
               "-clamp": 1, "-bm": 1, "-imfchan": 1, "-type": 1, "-cc": 1}
    while tokens and tokens[0].startswith("-"):
        option = tokens.pop(0)
        if option in {"-o", "-s", "-t"}:
            for _ in range(3):
                if not tokens:
                    break
                try:
                    float(tokens[0])
                except ValueError:
                    break
                tokens.pop(0)
        else:
            count = arities.get(option)
            if count is None:
                return ""
            del tokens[:count]
    return " ".join(tokens)


def _find_mtl_files_for_obj(obj_path: Path, root: Path | None = None) -> list[Path]:
    results: list[Path] = []
    try:
        with open(obj_path, "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped.startswith("mtllib"):
                    continue
                parts = stripped.split(None, 1)
                if len(parts) != 2:
                    continue
                reference = parts[1].strip().strip('"')
                candidate = _dependency_path(obj_path.parent, reference, root)
                candidates = [candidate] if candidate.is_file() else [
                    _dependency_path(obj_path.parent, ref, root)
                    for ref in shlex.split(parts[1].replace("\\", "/"))
                ]
                results.extend(path for path in candidates if path.is_file() and not _is_excluded_path(path))
    except SecurityError:
        raise
    except Exception as exc:
        logger.warning("Failed to read OBJ dependencies for %s: %s", obj_path, exc)
    return results


def _find_texture_files_for_mtl(mtl_path: Path, root: Path | None = None) -> Tuple[list[Path], list[str]]:
    found: list[Path] = []
    missing: list[str] = []
    seen_found: set[str] = set()
    seen_missing: set[str] = set()
    texture_pattern = re.compile(r"^\s*(map_|bump|refl)")
    try:
        with open(mtl_path, "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if not texture_pattern.match(line):
                    continue
                parts = line.strip().split()
                if not parts:
                    continue
                texture_ref = _texture_reference(line)
                if not texture_ref:
                    continue
                candidate = _dependency_path(mtl_path.parent, texture_ref, root)
                if candidate.is_file() and not _is_excluded_path(candidate):
                    key = str(candidate)
                    if key not in seen_found:
                        seen_found.add(key)
                        found.append(candidate)
                    continue
                basename_candidate = _dependency_path(mtl_path.parent, Path(texture_ref).name, root)
                if basename_candidate.is_file() and not _is_excluded_path(basename_candidate):
                    key = str(basename_candidate)
                    if key not in seen_found:
                        seen_found.add(key)
                        found.append(basename_candidate)
                    continue
                missing_key = Path(texture_ref).name or texture_ref
                if missing_key not in seen_missing:
                    seen_missing.add(missing_key)
                    missing.append(missing_key)
    except SecurityError:
        raise
    except Exception as exc:
        logger.warning("Failed to read MTL dependencies for %s: %s", mtl_path, exc)
    return found, missing


def _find_gltf_external_files(gltf_path: Path, root: Path | None = None) -> Tuple[list[Path], list[str]]:
    found: list[Path] = []
    missing: list[str] = []
    try:
        with open(gltf_path, "r", encoding="utf-8") as handle:
            gltf_data = json.load(handle)
    except Exception as exc:
        logger.warning("Failed to read GLTF dependencies for %s: %s", gltf_path, exc)
        return found, missing

    references: list[str] = []
    for key in ("buffers", "images"):
        for item in gltf_data.get(key, []) if isinstance(gltf_data, dict) else []:
            if not isinstance(item, dict):
                continue
            uri = str(item.get("uri") or "").strip()
            if not uri or uri.startswith("data:"):
                continue
            references.append(uri)

    seen_found: set[str] = set()
    seen_missing: set[str] = set()
    for uri in references:
        parsed = urlsplit(uri)
        if parsed.scheme or parsed.netloc:
            missing.append(uri)
            continue
        candidate = _dependency_path(gltf_path.parent, unquote(parsed.path), root)
        if candidate.is_file() and not _is_excluded_path(candidate):
            key = str(candidate)
            if key not in seen_found:
                seen_found.add(key)
                found.append(candidate)
        else:
            name = Path(uri).name or uri
            if name not in seen_missing:
                seen_missing.add(name)
                missing.append(name)
    return found, missing


def _find_fbx_texture_files(fbx_path: Path) -> list[Path]:
    results: list[Path] = []
    candidate_dirs = [
        fbx_path.parent / "textures",
        fbx_path.parent / "Textures",
        fbx_path.parent / "materials",
        fbx_path.parent / "Materials",
        fbx_path.parent / f"{fbx_path.stem}_textures",
    ]
    seen: set[str] = set()
    for directory in candidate_dirs:
        if not directory.is_dir() or _is_excluded_path(directory):
            continue
        for path in directory.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXTURE_EXTENSIONS or _is_excluded_path(path):
                continue
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            results.append(path.resolve())
    return results


def _generic_node(path: Path, node_type: str = "source") -> dict[str, Any]:
    return {
        "name": path.name,
        "path": str(path.resolve()),
        "type": node_type,
        "status": "Pending",
        "children": [],
    }


def _scan_associated_files(source_file: Path, scan_options: Dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    suffix = source_file.suffix.lower()
    obj_options = scan_options.get("obj_options") or {}

    if suffix == ".obj":
        node = _generic_node(source_file)
        if not obj_options.get("add_mtl"):
            return node
        for mtl_path in _find_mtl_files_for_obj(source_file, root):
            mtl_node = _generic_node(mtl_path, "primary")
            found_textures, missing_textures = _find_texture_files_for_mtl(mtl_path, root) if obj_options.get("add_textures") else ([], [])
            if missing_textures:
                mtl_node["missing_textures"] = missing_textures
            for texture_path in found_textures:
                mtl_node["children"].append(_generic_node(texture_path, "secondary"))
            node["children"].append(mtl_node)
        return node

    if suffix == ".gltf":
        node = _generic_node(source_file)
        if not obj_options.get("add_textures"):
            return node
        found_files, missing_files = _find_gltf_external_files(source_file, root)
        if missing_files:
            node["missing_textures"] = missing_files
        for child_path in found_files:
            child_type = "secondary" if child_path.suffix.lower() in TEXTURE_EXTENSIONS else "primary"
            node["children"].append(_generic_node(child_path, child_type))
        return node

    if suffix == ".fbx":
        node = _generic_node(source_file)
        if not obj_options.get("add_textures"):
            return node
        for texture_path in _find_fbx_texture_files(source_file):
            node["children"].append(_generic_node(texture_path, "secondary"))
        return node

    return _generic_node(source_file)


def _all_paths_in_tree(node: dict[str, Any]) -> set[str]:
    values = {str(Path(node["path"]).resolve())}
    for child in node.get("children", []):
        values.update(_all_paths_in_tree(child))
    return values


def _promote_primary_source(file_structure: dict[str, Any], primary_source_file: Path) -> dict[str, Any]:
    if Path(file_structure["path"]).resolve() == primary_source_file.resolve():
        file_structure["type"] = "primary_source"
        return file_structure

    root_children = list(file_structure.get("children") or [])
    matched_index = None
    for index, child_node in enumerate(root_children):
        if Path(child_node["path"]).resolve() == primary_source_file.resolve():
            matched_index = index
            break

    if matched_index is not None:
        primary_node = dict(root_children[matched_index])
        demoted_root_children = root_children[:matched_index] + root_children[matched_index + 1 :]
    else:
        primary_node = _generic_node(primary_source_file)
        demoted_root_children = root_children

    demoted_root = dict(file_structure)
    demoted_root["children"] = demoted_root_children

    promoted = dict(primary_node)
    promoted["type"] = "primary_source"
    promoted["children"] = [demoted_root] + list(primary_node.get("children") or [])
    return promoted


def _apply_archive_subdirectories(file_structure: dict[str, Any], data_out_path: Path, base_dir: Path, group_key: str, batch_entity: str) -> None:
    written_archives: set[str] = set()

    def recurse(node: dict[str, Any]) -> None:
        for child in list(node.get("children") or []):
            recurse(child)

        if node.get("type") != "primary":
            return

        secondaries = [child for child in list(node.get("children") or []) if child.get("type") == "secondary"]
        if not secondaries:
            return

        grouped: dict[str, list[dict[str, Any]]] = {}
        keep_children: list[dict[str, Any]] = []
        for child in node.get("children") or []:
            if child.get("type") != "secondary":
                keep_children.append(child)
                continue
            child_path = Path(child["path"]).resolve()
            try:
                rel_path = child_path.relative_to(base_dir)
            except ValueError:
                keep_children.append(child)
                continue
            if len(rel_path.parts) < 2:
                keep_children.append(child)
                continue
            grouped.setdefault(rel_path.parts[0], []).append(child)

        if not grouped:
            return

        archive_dir = data_out_path / "archives"
        archive_dir.mkdir(parents=True, exist_ok=True)
        base_stem = Path(group_key).name if batch_entity in {"subdirectory", "hybrid"} else Path(file_structure["name"]).stem

        new_children = list(keep_children)
        for folder_name, archived_nodes in grouped.items():
            zip_filename = f"{base_stem}_{folder_name}.zip"
            zip_path = archive_dir / zip_filename
            mode = "a" if str(zip_path) in written_archives else "w"
            written_archives.add(str(zip_path))
            with zipfile.ZipFile(zip_path, mode, zipfile.ZIP_DEFLATED) as archive:
                existing_members = set(archive.namelist())
                for archived_node in archived_nodes:
                    archived_path = Path(archived_node["path"]).resolve()
                    arcname = archived_path.relative_to(base_dir)
                    if str(arcname) not in existing_members:
                        archive.write(archived_path, arcname=str(arcname))
                        existing_members.add(str(arcname))
                    archived_node["type"] = "archived_file"
                    archived_node["archive_name"] = zip_filename
            archive_node = _generic_node(zip_path, "archive")
            archive_node["children"] = archived_nodes
            new_children.append(archive_node)
        node["children"] = new_children

    recurse(file_structure)


def _set_statuses(node: dict[str, Any]) -> None:
    validation = _validation_report(Path(node["path"]))
    node["validation_report"] = validation
    node["status"] = "Valid" if validation.get("is_valid") else "Invalid"
    if node.get("type") == "primary" and node.get("missing_textures"):
        node["status"] = "Textures Missing"
        node["validation_report"]["errors"].insert(
            0,
            f"Missing {len(node['missing_textures'])} referenced texture file(s).",
        )
    if node.get("type") in {"source", "primary_source"} and Path(node["path"]).suffix.lower() == ".obj":
        if not any(child.get("type") == "primary" for child in node.get("children") or []):
            node["status"] = "MTL Missing"
            node["validation_report"]["errors"].insert(0, "The referenced MTL file was not found in the same directory.")
    for child in node.get("children") or []:
        _set_statuses(child)


def _validation_error_message(validation_report: dict[str, Any] | None) -> str | None:
    if not isinstance(validation_report, dict):
        return None
    errors = validation_report.get("errors")
    if not isinstance(errors, list) or not errors:
        return None
    text = str(errors[0] or "").strip()
    return text or None


def _store_tree(
    cursor: sqlite3.Cursor,
    *,
    project_id: int,
    data_in_path: Path,
    data_out_path: Path,
    node: dict[str, Any],
    parent_id: int | None = None,
) -> int:
    path = Path(node["path"]).resolve()
    abs_path = str(path)
    try:
        rel_path = str(path.relative_to(data_in_path))
    except ValueError:
        try:
            rel_path = str(path.relative_to(data_out_path))
        except ValueError:
            rel_path = path.name

    validation_report = node.get("validation_report") or {}
    validation_report_json = json.dumps(validation_report)
    validation_error = _validation_error_message(validation_report)
    file_type = str(node.get("type") or "source")
    status = str(node.get("status") or "pending")
    is_primary_source = 1 if file_type == "primary_source" else 0

    row = cursor.execute(
        "SELECT file_id FROM source_files WHERE absolute_path = ? AND parent_file_id IS ? LIMIT 1",
        (abs_path, parent_id),
    ).fetchone()
    if row:
        file_id = int(row[0])
        cursor.execute(
            """
            UPDATE source_files
            SET project_id = ?,
                relative_path = ?,
                filename = ?,
                size_bytes = ?,
                sha256_hash = ?,
                mime_type = ?,
                file_type = ?,
                parent_file_id = ?,
                status = ?,
                error_message = ?,
                validation_report_json = ?,
                is_primary_source = ?,
                pipeline_source = COALESCE(pipeline_source, 'scan'),
                step_source = COALESCE(step_source, 'bootstrap_scan')
            WHERE file_id = ?
            """,
            (
                project_id,
                rel_path,
                path.name,
                path.stat().st_size if path.exists() else 0,
                _file_sha256(abs_path) if path.is_file() else "",
                _guess_mime_type(abs_path),
                file_type,
                parent_id,
                status,
                validation_error,
                validation_report_json,
                is_primary_source,
                file_id,
            ),
        )
    else:
        cursor.execute(
            """
            INSERT INTO source_files (
                project_id,
                absolute_path,
                relative_path,
                filename,
                size_bytes,
                sha256_hash,
                mime_type,
                file_type,
                parent_file_id,
                status,
                added_timestamp,
                error_message,
                validation_report_json,
                is_primary_source,
                pipeline_source,
                step_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                abs_path,
                rel_path,
                path.name,
                path.stat().st_size if path.exists() else 0,
                _file_sha256(abs_path) if path.is_file() else "",
                _guess_mime_type(abs_path),
                file_type,
                parent_id,
                status,
                _utc_now_iso(),
                validation_error,
                validation_report_json,
                is_primary_source,
                "scan",
                "bootstrap_scan",
            ),
        )
        file_id = int(cursor.lastrowid)

    node["file_id"] = file_id
    node["relative_path"] = rel_path
    for child in node.get("children") or []:
        _store_tree(
            cursor,
            project_id=project_id,
            data_in_path=data_in_path,
            data_out_path=data_out_path,
            node=child,
            parent_id=file_id,
        )
    return file_id


def _select_primary_source(
    files_in_group: Iterable[Path],
    primary_source_ext: str | None,
    preferred_primary_files: Dict[str, int],
) -> Path:
    files = list(files_in_group)
    preferred = [item for item in files if item.name.lower() in preferred_primary_files]
    if preferred:
        preferred.sort(key=lambda item: (preferred_primary_files.get(item.name.lower(), len(preferred_primary_files)), item.name.lower()))
        return preferred[0]
    if primary_source_ext:
        for item in files:
            if item.name.lower().endswith(str(primary_source_ext).lower()):
                return item
    return files[0]


def _build_file_groups(data_in_path: Path, batch_entity: str, extensions_to_scan: list[str], bundling_config: dict[str, Any]) -> dict[str, list[Path]]:
    def include(path: Path) -> bool:
        if not path.is_file() or _is_excluded_path(path):
            return False
        return any(path.name.lower().endswith(ext.lower()) for ext in extensions_to_scan)

    groups: dict[str, list[Path]] = {}
    bundling_enabled = bool((bundling_config or {}).get("enabled"))

    if batch_entity == "root":
        for path in data_in_path.glob("*"):
            if not include(path):
                continue
            if bundling_enabled:
                key = _extract_bundling_key(path.name, bundling_config) or str(path.resolve())
                groups.setdefault(key, []).append(path.resolve())
            else:
                groups[str(path.resolve())] = [path.resolve()]
        return groups

    if batch_entity == "subdirectory":
        for subdir in data_in_path.iterdir():
            if not subdir.is_dir() or _is_excluded_path(subdir):
                continue
            files = [path.resolve() for path in subdir.rglob("*") if include(path)]
            if files:
                groups[str(subdir.resolve())] = files
        return groups

    for path in data_in_path.glob("*"):
        if not include(path):
            continue
        if bundling_enabled:
            key = _extract_bundling_key(path.name, bundling_config) or str(path.resolve())
            groups.setdefault(key, []).append(path.resolve())
        else:
            groups[str(path.resolve())] = [path.resolve()]
    for subdir in data_in_path.iterdir():
        if not subdir.is_dir() or _is_excluded_path(subdir):
            continue
        files = [path.resolve() for path in subdir.rglob("*") if include(path)]
        if files:
            groups[str(subdir.resolve())] = files
    return groups


def create_and_scan_hdpc_project(
    *,
    hdpc_path: str,
    data_in_path: str,
    data_out_path: str,
    project_name: str,
    short_code: str = "WEBHDP",
    modalities: list[str] | None = None,
    scan_options: dict[str, Any] | None = None,
    batch_entity: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hdpc = Path(hdpc_path).expanduser().resolve()
    data_in = Path(data_in_path).expanduser().resolve()
    data_out = Path(data_out_path).expanduser().resolve()
    modalities = list(modalities or ["3d_model", "image", "text"])
    scan_options = dict(scan_options or {})
    batch_entity = str(batch_entity or scan_options.get("batchEntity") or "root")

    if not data_in.is_dir():
        raise FileNotFoundError(f"The specified Input Data Directory does not exist: {data_in}")

    hdpc.parent.mkdir(parents=True, exist_ok=True)
    data_out.mkdir(parents=True, exist_ok=True)
    if hdpc.exists():
        hdpc.unlink()

    conn = connect_hdpc(str(hdpc), timeout=60)
    try:
        conn.row_factory = sqlite3.Row
        project_id = ensure_hdpc_schema(conn, str(hdpc))
        cursor = conn.cursor()

        now_iso = _utc_now_iso()
        cursor.execute(
            """
            UPDATE project_info
            SET project_name = ?,
                project_short_code = ?,
                description = ?,
                hdpc_schema_version = ?,
                last_modified_timestamp = ?
            WHERE project_id = ?
            """,
            (
                project_name,
                short_code or "WEBHDP",
                "Locally managed WebHDP project context",
                HDPC_SCHEMA_VERSION,
                now_iso,
                project_id,
            ),
        )

        _upsert_project_config(cursor, project_id, "core.modality", modalities, "Modality Template")
        _upsert_project_config(cursor, project_id, "paths.data_in", str(data_in), "Input data directory")
        _upsert_project_config(cursor, project_id, "paths.data_out", str(data_out), "Output data directory")
        _upsert_project_config(cursor, project_id, "core.batch_entity", batch_entity, "File processing mode")

        cursor.execute("DELETE FROM file_scan_settings WHERE project_id = ?", (project_id,))
        for modality in modalities:
            cursor.execute(
                """
                INSERT INTO file_scan_settings (project_id, modality, scan_options)
                VALUES (?, ?, ?)
                """,
                (project_id, str(modality), json.dumps(scan_options)),
            )
        write_hdpc_provenance(conn, provenance)

        extensions_to_scan = list(scan_options.get("extensions") or [])
        primary_source_ext = scan_options.get("primarysourceext")
        preferred_primary_files = {
            str(name).strip().lower(): index
            for index, name in enumerate(scan_options.get("preferred_primary_files") or [])
            if isinstance(name, str) and str(name).strip()
        }
        bundling_config = scan_options.get("bundling") or {}
        archive_subdirectories = bool((scan_options.get("obj_options") or {}).get("archive_subdirectories"))

        file_groups = _build_file_groups(data_in, batch_entity, extensions_to_scan, bundling_config)
        # An MSF row identifies a record, even when several records share a
        # wrapper directory. Keep explicitly listed sources as separate roots.
        if batch_entity == "hybrid" and preferred_primary_files:
            split_groups = {}
            for group_key, files in file_groups.items():
                primaries = [path for path in files if (
                    path.name.lower() in preferred_primary_files
                    or path.relative_to(data_in).as_posix().lower() in preferred_primary_files
                )]
                if len(primaries) < 2:
                    split_groups[group_key] = files
                    continue
                for primary in primaries:
                    split_groups[str(primary)] = [primary]
                for path in files:
                    if path in primaries:
                        continue
                    # Associate siblings and alternate formats with the closest
                    # source; referenced dependencies are also scanned below.
                    owner = max(primaries, key=lambda primary: (
                        len(os.path.commonpath([str(path.parent), str(primary.parent)])),
                        path.stem.lower() == primary.stem.lower(),
                    ))
                    split_groups[str(owner)].append(path)
            file_groups = split_groups
        found_files: list[dict[str, Any]] = []
        files_added = 0

        for group_key, files_in_group in file_groups.items():
            if not files_in_group:
                continue

            primary_source = _select_primary_source(files_in_group, primary_source_ext, preferred_primary_files)
            scan_root = primary_source
            file_structure = _scan_associated_files(scan_root, scan_options, data_in)

            paths_in_tree = _all_paths_in_tree(file_structure)
            for file_path in files_in_group:
                resolved = str(Path(file_path).resolve())
                if resolved in paths_in_tree:
                    continue
                child_structure = _scan_associated_files(Path(file_path).resolve(), scan_options, data_in)
                file_structure.setdefault("children", []).append(child_structure)
                paths_in_tree.update(_all_paths_in_tree(child_structure))

            file_structure = _promote_primary_source(file_structure, primary_source)
            if archive_subdirectories:
                _apply_archive_subdirectories(file_structure, data_out, scan_root.parent, group_key, batch_entity)
            _set_statuses(file_structure)

            before_count = cursor.execute("SELECT COUNT(*) FROM source_files").fetchone()[0]
            _store_tree(
                cursor,
                project_id=project_id,
                data_in_path=data_in,
                data_out_path=data_out,
                node=file_structure,
            )
            after_count = cursor.execute("SELECT COUNT(*) FROM source_files").fetchone()[0]
            files_added += max(int(after_count) - int(before_count), 0)
            found_files.append(file_structure)

        conn.commit()
        return {
            "success": True,
            "message": f"Project created and {files_added} files scanned.",
            "projectId": project_id,
            "filesAdded": files_added,
            "foundFiles": found_files,
        }
    except Exception:
        conn.rollback()
        if hdpc.exists():
            hdpc.unlink()
        raise
    finally:
        conn.close()
