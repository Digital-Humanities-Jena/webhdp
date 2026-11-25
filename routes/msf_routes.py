# routes/msf_routes.py
"""Routes for Metadata Source File (MSF) handling"""

import json
import logging
import os
import tempfile
import time
import uuid
from contextlib import nullcontext
from functools import wraps
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from flask import Blueprint, current_app, request, send_file
from flask import session as flask_session
from flask_jwt_extended import get_jwt_identity, jwt_required
from werkzeug.datastructures import FileStorage

from api_utils import APIResponse
from constants import (
    MSF_ALLOWED_EXTENSIONS,
    UPLOAD_PROGRESS_FIELD,
    UPLOAD_STORAGE_MODE_FIELD,
    UPLOAD_TASK_ID_FIELD,
)
from database.database import db
from database.lod_template_bootstrap import ensure_default_lod_templates
from database.models import File as DBFile
from database.models import Session as DBSession
from database.models import UserMetadata
from database.models import User, UserRole
from exceptions import AppException, SecurityError, ValidationError
from routes.access_helpers import get_current_user_from_jwt, get_session_with_permission
from services.session_access_service import MOUNTED_INPUT_ORIGIN, can_use_mounted_inputs
from routes.lod_mapping_helpers import build_pipeline_aligned_lod_metadata, infer_row_fallback_title, merge_non_empty_metadata
from security import resolve_child_path, sanitize_upload_filename
from services.account_upload_quota import UploadQuotaError, admit_upload, attach_upload_to_session, upload_size
from services.cloud_upload_service import CloudUploadService, STORAGE_MODE_LOCAL
from services.edm_service import EdmService
from services.iiif_service import IiifService
from services.mets_service import MetsService
from services.hdpc_local_service import _file_sha256, _guess_mime_type
from services.msf_service import MSFService
from services.registry_lock import registry_lock
from services.user_service import UserService
from services.zenodo_metadata_normalizer import normalize_zenodo_metadata
from workflow_status import normalize_session_state

logger = logging.getLogger(__name__)
msf_bp = Blueprint("msf", __name__)
msf_service = MSFService()
edm_service = EdmService()
iiif_service = IiifService()
mets_service = MetsService()
DATASET_DUPLICATE_FILE_EXTENSIONS = {".glb", ".gltf", ".obj", ".ply", ".stl", ".fbx", ".usdz"}
MSF_FILE_BYTES = 16 * 1024**2
MSF_WORKSPACE_BYTES = 64 * 1024**2
MSF_WORKSPACE_RETENTION = 24 * 3600


def _get_directory_files(directory_path: str) -> List[str]:
    """Get list of actual files (not directories) from a path"""
    files = []
    if os.path.isdir(directory_path):
        for item in os.listdir(directory_path):
            item_path = os.path.join(directory_path, item)
            if os.path.isfile(item_path):
                # Exclude MSF files and hidden files
                ext = os.path.splitext(item)[1].lower()
                if ext not in MSF_ALLOWED_EXTENSIONS and not item.startswith("."):
                    files.append(item)
    return files


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on"}


def _build_parse_options(data: Dict[str, Any]) -> Dict[str, Any]:
    options = {}
    parse_options = data.get("parse_options")
    if isinstance(parse_options, dict):
        options.update(parse_options)

    if "sheet_name" in data and data.get("sheet_name"):
        options["sheet_name"] = str(data.get("sheet_name")).strip()
    if "delimiter" in data and data.get("delimiter"):
        options["delimiter"] = str(data.get("delimiter"))
    if "use_first_row_as_header" in data:
        options["use_first_row_as_header"] = _coerce_bool(data.get("use_first_row_as_header"))

    return options


def _scan_directory_files(directory_path: str, recursive: bool = False) -> List[str]:
    if not recursive:
        return _get_directory_files(directory_path)

    files: List[str] = []
    for root, _, names in os.walk(directory_path):
        for name in names:
            ext = os.path.splitext(name)[1].lower()
            if ext in MSF_ALLOWED_EXTENSIONS or name.startswith("."):
                continue
            files.append(name)
    return files


def _scan_directory_file_paths(directory_path: str, recursive: bool = False) -> List[str]:
    if not directory_path or not os.path.isdir(directory_path):
        return []
    paths: List[str] = []
    if not recursive:
        for item in os.listdir(directory_path):
            item_path = os.path.join(directory_path, item)
            if not os.path.isfile(item_path):
                continue
            ext = os.path.splitext(item)[1].lower()
            if ext in MSF_ALLOWED_EXTENSIONS or item.startswith("."):
                continue
            paths.append(item_path)
        return paths

    for root, _, names in os.walk(directory_path):
        for name in names:
            ext = os.path.splitext(name)[1].lower()
            if ext in MSF_ALLOWED_EXTENSIONS or name.startswith("."):
                continue
            paths.append(os.path.join(root, name))
    return paths


def _build_prepared_candidate_files(
    profile: Dict[str, Any],
    directory_root: str | None,
    validation_payload: Dict[str, Any],
) -> List[Dict[str, Any]]:
    matched_files = [str(item).strip() for item in (validation_payload.get("matched_files") or []) if str(item or "").strip()]
    if not matched_files or not directory_root or not os.path.isdir(directory_root):
        return []

    recursive = _coerce_bool(profile.get("directory_recursive")) is not False
    absolute_paths = _scan_directory_file_paths(directory_root, recursive=recursive)
    basename_lookup: Dict[str, List[str]] = {}
    for absolute_path in absolute_paths:
        basename_lookup.setdefault(os.path.basename(absolute_path).lower(), []).append(absolute_path)

    candidates: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for matched_name in matched_files:
        basename = os.path.basename(matched_name).strip()
        if not basename:
            continue
        extension = os.path.splitext(basename)[1].lower()
        if extension not in DATASET_DUPLICATE_FILE_EXTENSIONS:
            continue
        options = sorted(set(basename_lookup.get(basename.lower(), [])))
        if len(options) != 1:
            continue
        source_file_path = options[0]
        dedupe_key = os.path.normcase(os.path.normpath(source_file_path))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        candidates.append(
            {
                "source_file_path": source_file_path,
                "source_file_name": basename,
                "is_sandbox": False,
                "size_bytes": os.path.getsize(source_file_path),
                "sha256_hash": _file_sha256(source_file_path),
                "mime_type": _guess_mime_type(source_file_path),
                "file_type": "source",
            }
        )
    return candidates


def _persist_session_msf_profile(session_id: int, profile: Dict[str, Any]) -> None:
    _upsert_session_metadata(session_id, "msf_profile", json.dumps(profile))
    db.session.commit()


def _is_admin_request_user() -> bool:
    user_id = get_jwt_identity()
    if user_id is None:
        return False
    user = UserService().get_by_id(int(user_id))
    return user.role == UserRole.ADMIN


def require_admin_and_local_mode(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not _is_admin_request_user():
            return APIResponse.forbidden("Admin access required")

        storage_mode = CloudUploadService.get_storage_mode()
        if storage_mode != STORAGE_MODE_LOCAL:
            return APIResponse.forbidden(
                "MSF Validator (Local) is only available when storage mode is 'local'",
            )

        return func(*args, **kwargs)

    return wrapper


def _resolve_local_input_root() -> str:
    return current_app.config.get("LOCAL_INPUT_PATH", "/data/local_input")


def _account_msf_workspace() -> Path:
    root = Path(current_app.config.get("UPLOAD_FOLDER", "/tmp/msf_uploads"))
    workspace = root / f"account-{int(get_jwt_identity())}"
    workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    return workspace


def _resolve_upload_folder_path(raw_path: Any, *, must_be_file: bool = True) -> str:
    upload_folder = _account_msf_workspace()
    try:
        resolved = resolve_child_path(upload_folder, raw_path, must_exist=True)
    except AppException as exc:
        raise ValueError(str(exc)) from exc
    if must_be_file and not resolved.is_file():
        raise ValueError("Selected path must be a file in the upload workspace")
    if not must_be_file and not resolved.is_dir():
        raise ValueError("Selected path must be a directory in the upload workspace")
    if must_be_file and resolved.stat().st_mtime < time.time() - MSF_WORKSPACE_RETENTION:
        raise ValueError("This temporary spreadsheet has expired. Please upload it again.")
    return str(resolved)


def _workflow_msf_input(raw_path, project_service, *, directory=False):
    try:
        return _resolve_upload_folder_path(project_service._translate_path(raw_path, to_container=True), must_be_file=not directory)
    except ValueError:
        if CloudUploadService.get_storage_mode() != STORAGE_MODE_LOCAL:
            raise
    resolver = _resolve_local_directory_path if directory else _resolve_local_msf_path
    return resolver(raw_path, project_service)


def _require_mounted_inputs():
    if not can_use_mounted_inputs(get_current_user_from_jwt()):
        raise SecurityError("Mounted input access is required")


def _staged_msf_size(upload):
    size = upload_size(upload)
    if not size:
        raise ValidationError("Choose a spreadsheet containing data.")
    if size > MSF_FILE_BYTES:
        raise UploadQuotaError("MSF_FILE_QUOTA", "Choose a spreadsheet of 16 MiB or smaller.", 413, {"limit_bytes": MSF_FILE_BYTES})
    return size


def _store_staged_msf(upload, filename, directory=None):
    size = _staged_msf_size(upload)
    with registry_lock(f"msf-workspace:{int(get_jwt_identity())}"):
        workspace = _account_msf_workspace()
        cutoff = time.time() - MSF_WORKSPACE_RETENTION
        stored = 0
        for item in workspace.rglob("*"):
            if item.is_file() and not item.is_symlink():
                info = item.stat()
                if info.st_mtime < cutoff:
                    item.unlink(missing_ok=True)
                else:
                    stored += info.st_size
        if stored + size > MSF_WORKSPACE_BYTES:
            raise UploadQuotaError("MSF_WORKSPACE_QUOTA", "Your temporary spreadsheet workspace is full. Try again as earlier files expire.", 413,
                                   {"used_bytes": stored, "limit_bytes": MSF_WORKSPACE_BYTES})
        destination = Path(directory or workspace) / f"msf_{uuid.uuid4().hex}_{filename}"
        try:
            upload.save(destination)
        except OSError:
            destination.unlink(missing_ok=True)
            raise
        return str(destination)


def _resolve_local_directory_path(raw_directory_path: Any, project_service) -> str:
    _require_mounted_inputs()
    base_local_path = _resolve_local_input_root()
    translated_base = project_service._translate_path(base_local_path, to_container=True)
    if not os.path.isdir(translated_base):
        raise ValueError(f"Local input directory not found: {translated_base}")

    text = str(raw_directory_path or "").strip()
    if not text:
        return translated_base

    candidate = project_service._translate_path(text, to_container=True)
    if not os.path.isabs(candidate):
        candidate = os.path.join(translated_base, text.strip("/"))

    real_base = os.path.realpath(translated_base)
    real_candidate = os.path.realpath(candidate)
    if os.path.commonpath([real_base, real_candidate]) != real_base:
        raise ValueError("Invalid directory path: Must be within local input directory")
    if not os.path.isdir(real_candidate):
        raise ValueError(f"Selected input directory not found: {real_candidate}")
    return real_candidate


def _resolve_local_msf_path(raw_msf_path: Any, project_service) -> str:
    _require_mounted_inputs()
    text = str(raw_msf_path or "").strip()
    if not text:
        raise ValueError("msf_path is required")

    base_local_path = _resolve_local_input_root()
    translated_base = project_service._translate_path(base_local_path, to_container=True)
    candidate = project_service._translate_path(text, to_container=True)
    if not os.path.isabs(candidate):
        candidate = os.path.join(translated_base, text.strip("/"))

    real_base = os.path.realpath(translated_base)
    real_candidate = os.path.realpath(candidate)
    if os.path.commonpath([real_base, real_candidate]) != real_base:
        raise ValueError("Invalid msf_path: Must be within local input directory")
    if not os.path.isfile(real_candidate):
        raise ValueError(f"MSF file not found: {real_candidate}")

    ext = os.path.splitext(real_candidate)[1].lower()
    if ext not in MSF_ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Invalid MSF extension '{ext}'. Allowed: {', '.join(MSF_ALLOWED_EXTENSIONS)}"
        )
    return real_candidate


def _list_local_msf_files(input_root: str) -> List[Dict[str, str]]:
    msf_files: List[Dict[str, str]] = []
    if not os.path.isdir(input_root):
        return msf_files

    for root, _, files in os.walk(input_root):
        for file_name in files:
            if not file_name.lower().endswith((".xlsx", ".xls", ".csv")):
                continue
            if file_name.startswith("~$"):
                continue
            full_path = os.path.join(root, file_name)
            rel_path = os.path.relpath(full_path, input_root)
            msf_files.append(
                {
                    "name": file_name,
                    "path": rel_path,
                    "full_path": full_path,
                }
            )
    msf_files.sort(key=lambda item: item.get("path", "").lower())
    return msf_files


def _upsert_session_metadata(session_id: int, field_name: str, field_value: str) -> None:
    record = UserMetadata.query.filter_by(session_id=session_id, field_name=field_name).first()
    if record:
        record.field_value = field_value
    else:
        db.session.add(UserMetadata(session_id=session_id, field_name=field_name, field_value=field_value))


def _get_session_msf_profile(session_id: int) -> Dict[str, Any]:
    record = UserMetadata.query.filter_by(session_id=session_id, field_name="msf_profile").first()
    if not record or not record.field_value:
        return {}
    try:
        payload = json.loads(record.field_value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _get_session_draft_metadata(session_id: int) -> Dict[str, Any]:
    record = UserMetadata.query.filter_by(session_id=session_id, field_name="zenodo_metadata_draft").first()
    if not record or not record.field_value:
        return {}
    try:
        payload = json.loads(record.field_value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_session_msf_path(session_row: DBSession) -> str | None:
    profile = _get_session_msf_profile(session_row.id)
    profile_path = str(profile.get("file_path") or "").strip()
    if profile_path and os.path.exists(profile_path):
        return profile_path

    candidate_dirs = []
    if session_row.session_dir:
        candidate_dirs.append(os.path.join(session_row.session_dir, "uploads"))
    if session_row.hdpc_path:
        candidate_dirs.append(os.path.join(os.path.dirname(session_row.hdpc_path), "uploads"))

    for base_dir in candidate_dirs:
        if not base_dir or not os.path.isdir(base_dir):
            continue
        for ext in (".xlsx", ".xls", ".csv"):
            candidate = os.path.join(base_dir, f"upload.msf{ext}")
            if os.path.exists(candidate):
                return candidate
        for name in os.listdir(base_dir):
            ext = os.path.splitext(name)[1].lower()
            if ext in MSF_ALLOWED_EXTENSIONS:
                candidate = os.path.join(base_dir, name)
                if os.path.isfile(candidate):
                    return candidate
    return None


def _resolve_session_directory_files(session_row: DBSession) -> tuple[list[str], str | None]:
    files: set[str] = set()
    directory_root = None
    profile = _get_session_msf_profile(session_row.id)

    profile_directory_root = str(profile.get("directory_root") or "").strip()
    if profile_directory_root and os.path.isdir(profile_directory_root):
        recursive = _coerce_bool(profile.get("directory_recursive"))
        profile_files = _scan_directory_files(profile_directory_root, recursive=recursive is not False)
        if profile_files:
            return sorted(set(profile_files), key=lambda item: item.lower()), profile_directory_root

    candidate_dirs = []
    if session_row.session_dir:
        candidate_dirs.append(os.path.join(session_row.session_dir, "uploads"))
    if session_row.hdpc_path:
        candidate_dirs.append(os.path.join(os.path.dirname(session_row.hdpc_path), "uploads"))

    for base_dir in candidate_dirs:
        if not base_dir or not os.path.isdir(base_dir):
            continue
        if directory_root is None:
            directory_root = base_dir
        for root, _, names in os.walk(base_dir):
            for name in names:
                if name.startswith("."):
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext in MSF_ALLOWED_EXTENSIONS:
                    continue
                files.add(name)

    if not files:
        rows = DBFile.query.filter_by(session_id=session_row.id).all()
        for row in rows:
            if row.filename:
                files.add(str(row.filename))

    return sorted(files, key=lambda item: item.lower()), directory_root


def _resolve_session_uploads_dir(session_row: DBSession) -> str:
    if session_row.session_dir:
        uploads_dir = os.path.join(session_row.session_dir, "uploads")
        os.makedirs(uploads_dir, exist_ok=True)
        return uploads_dir
    if session_row.hdpc_path:
        uploads_dir = os.path.join(os.path.dirname(session_row.hdpc_path), "uploads")
        os.makedirs(uploads_dir, exist_ok=True)
        return uploads_dir
    uploads_dir = tempfile.mkdtemp(prefix="workflow_uploads_")
    return uploads_dir


def _create_workflow_session_dirs(user_id: int, **workspace_options) -> tuple[DBSession, str, str, str]:
    session_manager = getattr(current_app, "session_manager", None)
    if session_manager is not None:
        hdpc_path, data_out_path, uploads_path, session_dir = session_manager.create_session_dirs()
    else:
        session_dir = tempfile.mkdtemp(prefix="hdp_session_")
        hdpc_path = os.path.join(session_dir, "session.hdpc")
        data_out_path = os.path.join(session_dir, "outputs")
        uploads_path = os.path.join(session_dir, "uploads")
        os.makedirs(data_out_path, exist_ok=True)
        os.makedirs(uploads_path, exist_ok=True)

    session_row = DBSession(
        user_id=user_id,
        institution_id=workspace_options.get("institution_id"),
        session_dir=session_dir,
        hdpc_path=hdpc_path,
        status="queued",
        sharing_scope=workspace_options.get("sharing_scope") or ("institution" if workspace_options.get("institution_id") else "private"),
        credential_preference=workspace_options.get("credential_preference") or ("institution" if workspace_options.get("institution_id") else "user"),
        publishing_user_id=workspace_options.get("publishing_user_id") or user_id,
        default_zenodo_environment=workspace_options.get("default_zenodo_environment") or "sandbox",
        use_institution_default_communities=bool(workspace_options.get("use_institution_default_communities"))
        if workspace_options.get("institution_id")
        else False,
        origin_type=workspace_options.get("origin_type", "workflow"),
        access_mode="full",
    )
    db.session.add(session_row)
    attach_upload_to_session(session_row)
    db.session.commit()

    flask_session["hdpc_path"] = hdpc_path
    flask_session["session_dir"] = session_dir
    flask_session["data_out_path"] = data_out_path
    flask_session["uploads_path"] = uploads_path
    flask_session["db_session_id"] = session_row.id
    flask_session.permanent = True

    return session_row, hdpc_path, data_out_path, uploads_path


def _get_upload_task_id(session_id: int) -> str | None:
    record = UserMetadata.query.filter_by(session_id=session_id, field_name=UPLOAD_TASK_ID_FIELD).first()
    if not record or not record.field_value:
        return None
    task_id = str(record.field_value).strip()
    return task_id or None


def _preview_row_number(profile: Dict[str, Any], row_index: int) -> int:
    header_row_index = profile.get("header_row_index")
    try:
        header_offset = int(header_row_index) + 2
    except (TypeError, ValueError):
        header_offset = 2
    return int(row_index) + header_offset


def _collect_empty_cell_locations(df, columns: List[str], profile: Dict[str, Any], limit: int = 20) -> List[Dict[str, Any]]:
    locations: List[Dict[str, Any]] = []
    valid_columns = [column for column in columns if column in df.columns]
    if not valid_columns:
        return locations

    for idx in range(len(df)):
        for column in valid_columns:
            value = str(df.iloc[idx].get(column) if column in df.columns else "").strip()
            if value:
                continue
            locations.append(
                {
                    "row_index": int(idx),
                    "row_number": _preview_row_number(profile, idx),
                    "column": column,
                    "value": value,
                    "reason": "Required value is empty.",
                }
            )
            if len(locations) >= limit:
                return locations
    return locations


def _collect_reference_locations(df, filename_column: str | None, missing_files: List[str], profile: Dict[str, Any], limit: int = 25) -> List[Dict[str, Any]]:
    if not filename_column or filename_column not in df.columns:
        return []

    missing_lookup = {str(item).strip().lower() for item in (missing_files or []) if str(item).strip()}
    locations: List[Dict[str, Any]] = []
    for idx in range(len(df)):
        raw_value = str(df.iloc[idx].get(filename_column) or "").strip()
        normalized = msf_service._normalize_filename_value(raw_value)
        if normalized.lower() not in missing_lookup:
            continue
        locations.append(
            {
                "row_index": int(idx),
                "row_number": _preview_row_number(profile, idx),
                "column": filename_column,
                "value": raw_value,
                "reason": "Referenced file could not be found in the scanned upload set.",
            }
        )
        if len(locations) >= limit:
            break
    return locations


def _collect_normalized_duplicate_locations(df, filename_column: str | None, profile: Dict[str, Any], limit: int = 25) -> List[Dict[str, Any]]:
    if not filename_column or filename_column not in df.columns:
        return []

    groups: Dict[str, List[int]] = {}
    for idx, value in enumerate(df[filename_column].tolist()):
        normalized = msf_service._normalize_filename_value(value)
        if not normalized:
            continue
        groups.setdefault(normalized.lower(), []).append(idx)

    locations: List[Dict[str, Any]] = []
    for normalized_value, indices in groups.items():
        if len(indices) < 2:
            continue
        for idx in indices:
            locations.append(
                {
                    "row_index": int(idx),
                    "row_number": _preview_row_number(profile, idx),
                    "column": filename_column,
                    "value": normalized_value,
                    "reason": "Multiple rows resolve to the same normalized filename.",
                }
            )
            if len(locations) >= limit:
                return locations
    return locations


def _count_trim_whitespace_cells(df) -> int:
    changed = 0
    for column in df.columns:
        for value in df[column].tolist():
            text = str(value if value is not None else "")
            if text != text.strip():
                changed += 1
    return int(changed)


def _count_fully_empty_rows(df) -> int:
    return int(
        sum(
            1
            for _, row in df.iterrows()
            if not any(str(value if value is not None else "").strip() for value in row.tolist())
        )
    )


def _count_filename_normalizations(df, filename_column: str | None) -> int:
    if not filename_column or filename_column not in df.columns:
        return 0
    changed = 0
    for value in df[filename_column].tolist():
        normalized = msf_service._normalize_filename_value(value)
        if str(value or "").strip() != normalized:
            changed += 1
    return int(changed)


def _build_highlight_cells(issues: List[Dict[str, Any]], preview_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    preview_row_numbers = {int(row.get("__row_number")) for row in preview_rows if row.get("__row_number") is not None}
    highlights: List[Dict[str, Any]] = []
    seen: set[tuple[int, str, str]] = set()
    for issue in issues:
        for location in issue.get("locations") or []:
            row_number = location.get("row_number")
            column = str(location.get("column") or "").strip()
            if row_number not in preview_row_numbers or not column:
                continue
            key = (int(row_number), column, str(issue.get("id")))
            if key in seen:
                continue
            seen.add(key)
            highlights.append(
                {
                    "row_number": int(row_number),
                    "column": column,
                    "issue_id": issue.get("id"),
                    "severity": issue.get("severity", "warning"),
                    "message": location.get("reason") or issue.get("description"),
                }
            )
    return highlights


def _build_issue(
    *,
    issue_id: str,
    severity: str,
    title: str,
    description: str,
    affected_lods: List[str],
    leads_to: str,
    suggested_fix: str,
    locations: List[Dict[str, Any]] | None = None,
    recommendation_ids: List[str] | None = None,
    why: str | None = None,
    context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return {
        "id": issue_id,
        "severity": severity,
        "title": title,
        "description": description,
        "affected_lods": affected_lods,
        "why": why or description,
        "leads_to": leads_to,
        "suggested_fix": suggested_fix,
        "locations": locations or [],
        "recommendation_ids": recommendation_ids or [],
        "auto_fix_supported": bool(recommendation_ids),
        "context": context or {},
    }


def _expand_recommendation_dependencies(
    selected_fix_ids: set[str],
    available_fix_map: Dict[str, Dict[str, Any]],
) -> set[str]:
    expanded = set(selected_fix_ids)
    pending = list(selected_fix_ids)

    while pending:
        fix_id = pending.pop()
        fix = available_fix_map.get(fix_id) or {}
        for dependency in fix.get("depends_on") or []:
            dep_id = str(dependency or "").strip()
            if not dep_id or dep_id in expanded:
                continue
            expanded.add(dep_id)
            pending.append(dep_id)

    return expanded


def _analyze_workflow_session_msf(
    session_row: DBSession,
    *,
    msf_path: str,
    parse_options: Dict[str, Any],
    directory_files: List[str],
    directory_root: str | None,
) -> Dict[str, Any]:
    session_profile = _get_session_msf_profile(session_row.id)
    df, parsed_profile = msf_service.parse_msf_file_with_profile(msf_path, parse_options=parse_options)
    profile = dict(session_profile or {})
    profile.update(parsed_profile or {})
    if directory_root:
        profile["directory_root"] = directory_root
    if "directory_recursive" not in profile:
        profile["directory_recursive"] = True
    filename_column = profile.get("filename_column")
    detected_confidence = float(profile.get("filename_confidence") or 0.0)
    if not filename_column:
        detected_column, detected_confidence = msf_service.detect_filename_column(df, directory_files)
        filename_column = detected_column
        if detected_column:
            profile["filename_column"] = detected_column
            profile["filename_confidence"] = round(float(detected_confidence or 0.0), 3)

    base_validator = msf_service.run_local_validator(
        file_path=msf_path,
        parse_options=parse_options,
        directory_files=directory_files,
        directory_root=directory_root,
        filename_column=filename_column,
        duplicate_scan_columns=[filename_column] if filename_column else [],
        operations=[],
        include_reference_check=True,
        include_dataframe=False,
    )
    patch_report = msf_service.patch_msf_file(
        file_path=msf_path,
        parse_options=parse_options,
        directory_files=directory_files,
        directory_root=directory_root,
        filename_column=filename_column,
        duplicate_policy="fail",
        apply=False,
    )
    validation_payload = patch_report.get("validation") or {}
    reference_payload = validation_payload or ((base_validator.get("checks") or {}).get("reference_availability") or {})
    profile["prepared_candidate_files"] = _build_prepared_candidate_files(profile, directory_root, reference_payload)

    issues: List[Dict[str, Any]] = []
    recommendations: List[Dict[str, Any]] = []

    trim_cells = _count_trim_whitespace_cells(df)
    if trim_cells > 0:
        recommendations.append(
            {
                "id": "trim_whitespace",
                "label": "Trim whitespace",
                "description": f"Remove leading and trailing whitespace from {trim_cells} cell(s).",
                "operations": [{"type": "trim_whitespace"}],
            }
        )
        issues.append(
            _build_issue(
                issue_id="whitespace_noise",
                severity="warning",
                title="Whitespace noise detected",
                description=f"{trim_cells} cell(s) contain leading or trailing whitespace.",
                affected_lods=["edm", "iiif", "mets"],
                why="Whitespace changes matching and can create visually inconsistent metadata values.",
                leads_to="Unexpected duplicate detection, mismatched file references, or untidy labels in rendered LOD outputs.",
                suggested_fix="Trim whitespace across the MSF before continuing.",
                recommendation_ids=["trim_whitespace"],
            )
        )

    empty_rows = _count_fully_empty_rows(df)
    if empty_rows > 0:
        recommendations.append(
            {
                "id": "remove_empty_rows",
                "label": "Remove empty rows",
                "description": f"Drop {empty_rows} fully empty row(s) from the MSF.",
                "operations": [{"type": "remove_empty_rows"}],
            }
        )
        issues.append(
            _build_issue(
                issue_id="empty_rows",
                severity="warning",
                title="Empty rows detected",
                description=f"{empty_rows} fully empty row(s) were found in the MSF.",
                affected_lods=["edm", "iiif", "mets"],
                leads_to="Row counting and preview selection become less reliable, and manual review becomes harder.",
                suggested_fix="Remove fully empty rows before proceeding.",
                recommendation_ids=["remove_empty_rows"],
            )
        )

    filename_normalizations = int((patch_report.get("summary") or {}).get("filename_cells_normalized") or 0)
    if filename_normalizations > 0 and filename_column:
        recommendations.append(
            {
                "id": "normalize_filename_column",
                "label": "Normalize filename references",
                "description": f"Normalize {filename_normalizations} filename cell(s) in '{filename_column}'.",
                "operations": [{"type": "normalize_filename_column", "column": filename_column}],
            }
        )
        issues.append(
            _build_issue(
                issue_id="filename_normalization",
                severity="warning",
                title="Filename references need normalization",
                description=f"{filename_normalizations} filename value(s) contain path noise or inconsistent separators.",
                affected_lods=["edm", "iiif", "mets"],
                why="LOD generation depends on stable file-to-row matching.",
                leads_to="Rows can fail to match the intended asset, producing missing-file or wrong-file validation problems.",
                suggested_fix=f"Normalize '{filename_column}' values to plain basenames.",
                recommendation_ids=["normalize_filename_column"],
            )
        )

    duplicate_groups = int((patch_report.get("summary") or {}).get("duplicate_groups_detected") or 0)
    if duplicate_groups > 0 and filename_column:
        dependency_ids = ["normalize_filename_column"] if filename_normalizations > 0 else []
        recommendations.append(
            {
                "id": "resolve_duplicates",
                "label": "Merge duplicate filename rows",
                "description": f"Resolve {duplicate_groups} duplicate filename group(s) using merge_non_empty.",
                "depends_on": dependency_ids,
                "operations": [
                    {
                        "type": "resolve_duplicates",
                        "columns": [filename_column],
                        "strategy": "merge_non_empty",
                        "normalize_as_filename": True,
                    }
                ],
            }
        )
        issues.append(
            _build_issue(
                issue_id="duplicate_filename_rows",
                severity="error",
                title="Duplicate filename rows detected",
                description=f"{duplicate_groups} duplicate group(s) were found in the filename column '{filename_column}'.",
                affected_lods=["edm", "iiif", "mets"],
                why="A single asset should not resolve to competing metadata rows.",
                leads_to="Ambiguous record generation, duplicate records, or dropped data when matching files to metadata.",
                suggested_fix="Merge duplicate rows or otherwise make filename references unique.",
                locations=_collect_normalized_duplicate_locations(df, filename_column, profile),
                recommendation_ids=["resolve_duplicates"],
                context={"depends_on": dependency_ids},
            )
        )

    duplicate_directory_files = validation_payload.get("duplicate_directory_files") or []
    duplicate_directory_details = validation_payload.get("duplicate_directory_details") or []
    suggested_directories = sorted(
        {
            str(item).strip()
            for detail in duplicate_directory_details
            for item in (detail.get("suggested_directories") or [])
            if str(item or "").strip()
        },
        key=lambda item: item.lower(),
    )
    if duplicate_directory_files:
        preview = ", ".join(duplicate_directory_files[:6])
        suffix = " ..." if len(duplicate_directory_files) > 6 else ""
        issues.append(
            _build_issue(
                issue_id="duplicate_directory_filenames",
                severity="error",
                title="Selected directory contains duplicate basenames",
                description=(
                    "At least two files in the selected directory tree share the same basename: "
                    f"{preview}{suffix}."
                ),
                affected_lods=["edm", "iiif", "mets"],
                why="The MSF matches by basename, so two different files with the same basename are ambiguous.",
                leads_to="Preflight blocks processing because the system cannot deterministically decide which asset each MSF row should use.",
                suggested_fix="Choose a narrower target directory or rename one of the conflicting files on the HPC before starting the scan.",
                context={
                    "conflicts": duplicate_directory_details,
                    "suggested_directories": suggested_directories,
                },
            )
        )

    filename_detection_confidence = float(
        detected_confidence
        if detected_confidence < 1.0
        else (validation_payload.get("filename_detection_confidence") or detected_confidence or 1.0)
    )
    if filename_column and filename_detection_confidence < 0.3:
        issues.append(
            _build_issue(
                issue_id="filename_column_detection_low_confidence",
                severity="warning",
                title="Filename column detection is low confidence",
                description=(
                    f"The system inferred '{filename_column}' as the filename column with only "
                    f"{filename_detection_confidence:.0%} confidence."
                ),
                affected_lods=["edm", "iiif", "mets"],
                why="If the wrong column is treated as the file reference, every downstream file-to-row match becomes unreliable.",
                leads_to="Validation errors, false missing-file reports, or records built from the wrong source row.",
                suggested_fix="If this is a CSV, go back and change the header-row option. Otherwise confirm that the filename column actually contains model basenames.",
            )
        )

    reference_check = validation_payload or (base_validator.get("checks") or {}).get("reference_availability") or {}
    missing_files = reference_check.get("missing_files") or []
    if missing_files and filename_column:
        recommendations.append(
            {
                "id": "repair_references",
                "label": "Repair file references",
                "description": f"Attempt to repair {len(missing_files)} missing reference(s) by basename/stem matching.",
                "operations": [
                    {
                        "type": "repair_references",
                        "column": filename_column,
                        "match_by_stem": True,
                        "keep_unresolved": True,
                    }
                ],
            }
        )
        issues.append(
            _build_issue(
                issue_id="missing_asset_references",
                severity="error",
                title="MSF references missing assets",
                description=f"{len(missing_files)} filename reference(s) in the MSF could not be matched to uploaded assets.",
                affected_lods=["edm", "iiif", "mets"],
                why="The record cannot be generated correctly when its primary asset cannot be located.",
                leads_to="Validation failures, missing links in generated LOD documents, or skipped records.",
                suggested_fix="Repair references automatically or correct the filename cells in the MSF.",
                locations=_collect_reference_locations(df, filename_column, missing_files, profile),
                recommendation_ids=["repair_references"],
            )
        )

    suggested_mapping = msf_service.suggest_column_mapping(list(df.columns))
    quality_rules = [
        {
            "id": "missing_title_values",
            "target": "title",
            "columns": [column for column, target in suggested_mapping.items() if target == "title"],
            "severity": "warning",
            "title": "Some rows have no title",
            "description": "Titles are missing for some rows.",
            "affected_lods": ["edm", "iiif", "mets"],
            "why": "Human-readable labels are expected across all downstream LOD outputs.",
            "leads_to": "Minimum-viable generation falls back to filename-based titles or placeholders, reducing metadata quality.",
            "suggested_fix": "Fill the title column for affected rows, or proceed with minimum-viable placeholders.",
        },
        {
            "id": "missing_description_values",
            "target": "description",
            "columns": [column for column, target in suggested_mapping.items() if target == "description"],
            "severity": "warning",
            "title": "Some rows have no description",
            "description": "Descriptions are missing for some rows.",
            "affected_lods": ["edm", "iiif", "mets"],
            "why": "Descriptions improve summary fields and descriptive MODS/EDM content.",
            "leads_to": "Generated outputs become technically valid but less descriptive, often relying on placeholder text.",
            "suggested_fix": "Provide descriptions for affected rows where possible.",
        },
        {
            "id": "missing_creator_values",
            "target": "_creators_raw",
            "columns": [column for column, target in suggested_mapping.items() if target == "_creators_raw"],
            "severity": "warning",
            "title": "Some rows have no creator",
            "description": "Creator values are missing for some rows.",
            "affected_lods": ["edm", "mets"],
            "why": "Creator/provenance information is central to descriptive metadata quality.",
            "leads_to": "Minimum-viable generation falls back to generic creator placeholders such as 'Unknown'.",
            "suggested_fix": "Populate creator values or accept placeholder creators in minimum-viable output.",
        },
        {
            "id": "missing_date_values",
            "target": "publication_date",
            "columns": [column for column, target in suggested_mapping.items() if target == "publication_date"],
            "severity": "warning",
            "title": "Some rows have no date",
            "description": "Publication/date values are missing for some rows.",
            "affected_lods": ["edm", "mets"],
            "why": "Date information is reused in generated descriptive sections and business-rule checks.",
            "leads_to": "Minimum-viable output falls back to today's date, which is valid but not semantically accurate.",
            "suggested_fix": "Provide correct dates for affected rows where known.",
        },
    ]

    for rule in quality_rules:
        locations = _collect_empty_cell_locations(df, rule["columns"], profile)
        if not locations:
            continue
        issues.append(
            _build_issue(
                issue_id=rule["id"],
                severity=rule["severity"],
                title=rule["title"],
                description=f"{rule['description']} {len(locations)} affected row(s) shown.",
                affected_lods=rule["affected_lods"],
                why=rule["why"],
                leads_to=rule["leads_to"],
                suggested_fix=rule["suggested_fix"],
                locations=locations,
            )
        )

    sample_row_index = profile.get("suggested_row_index")
    if sample_row_index is None:
        sample_row_index = msf_service.suggest_sample_row_index(df, filename_column)
    sample_row_index = max(0, min(int(sample_row_index or 0), max(len(df) - 1, 0)))
    sample_row = df.iloc[sample_row_index]
    sample_filename = ""
    if filename_column and filename_column in df.columns:
        sample_filename = msf_service._normalize_filename_value(sample_row.get(filename_column))
    if not sample_filename:
        sample_filename = (directory_files[0] if directory_files else "sample_model.glb")

    sample_metadata_raw = {}
    if filename_column and filename_column in df.columns and sample_filename:
        sample_metadata_raw = msf_service.get_metadata_for_file(
            df,
            sample_filename,
            filename_column,
        ) or {}
    fallback_title = infer_row_fallback_title(sample_row, profile)
    sample_metadata = normalize_zenodo_metadata(
        sample_metadata_raw,
        apply_defaults=True,
        fallback_title=fallback_title,
    )
    sample_metadata["edm_provider"] = str(sample_metadata.get("provider") or "WebHDP")
    preview_doi = str(sample_metadata.get("doi") or f"10.5072/webhdp.preview.{session_row.id}.{sample_row_index + 1}")
    sample_zenodo_record = {
        "id": 0,
        "metadata": {
            **sample_metadata,
            "prereserve_doi": {
                "doi": preview_doi,
            },
        },
        "links": {"html": "https://example.org/records/sample"},
        "files": [{"key": sample_filename, "filename": sample_filename, "size": 0}],
    }

    draft_metadata = _get_session_draft_metadata(session_row.id)
    lod_samples: Dict[str, Any] = {}
    standard_services = {
        "edm": edm_service,
        "iiif": iiif_service,
        "mets": mets_service,
    }
    ensure_default_lod_templates()
    from services.submission_pipeline_service import _extract_standard_mapping, _infer_lod_modality
    modality = _infer_lod_modality(sample_filename, sample_metadata)

    for standard, service in standard_services.items():
        mapping_config = _extract_standard_mapping(draft_metadata.get("lod_mapping"), standard, modality)
        metadata_for_standard = sample_metadata
        if mapping_config:
            metadata_for_standard = build_pipeline_aligned_lod_metadata(
                msf_service=msf_service,
                row=sample_row,
                zenodo_record=sample_zenodo_record,
                mapping_config=mapping_config,
                msf_profile=profile,
            )
            metadata_for_standard = merge_non_empty_metadata(
                metadata_for_standard,
                normalize_zenodo_metadata(metadata_for_standard, apply_defaults=True, fallback_title=fallback_title),
            )
            metadata_for_standard["edm_provider"] = str(
                draft_metadata.get("edm_provider") or metadata_for_standard.get("provider") or "WebHDP"
            )

        try:
            if standard == "edm":
                generation = service.generate_edm_xml_with_report(
                    metadata=metadata_for_standard,
                    zenodo_record=sample_zenodo_record,
                    template_id=draft_metadata.get("edm_template_id"),
                    main_file_key=sample_filename,
                    validate=False,
                    allow_placeholder_thumbnail=True,
                )
                validation = service.validate_edm_document(
                    generation["content"],
                    metadata=metadata_for_standard,
                    include_remote=current_app.config.get(
                        "LOCAL_EDM_VALIDATOR_REQUIRED",
                        False,
                    ) or current_app.config.get(
                        "ENABLE_LOCAL_EDM_VALIDATION",
                        current_app.config.get("ENABLE_METIS_VALIDATION", True),
                    ),
                )
                content_key = "xml"
            elif standard == "iiif":
                generation = service.generate_iiif_manifest_with_report(
                    metadata=metadata_for_standard,
                    zenodo_record=sample_zenodo_record,
                    template_id=draft_metadata.get("iiif_template_id"),
                    main_file_key=sample_filename,
                    validate=False,
                    allow_placeholder_thumbnail=True,
                )
                validation = service.validate_iiif_manifest(generation["content"])
                content_key = "json"
            else:
                generation = service.generate_mets_xml_with_report(
                    metadata=metadata_for_standard,
                    zenodo_record=sample_zenodo_record,
                    template_id=draft_metadata.get("mets_template_id"),
                    main_file_key=sample_filename,
                    validate=False,
                    allow_placeholder_thumbnail=True,
                )
                validation = service.validate_mets_xml(generation["content"])
                content_key = "xml"

            lod_samples[standard] = {
                "valid": bool(validation.get("valid", True)),
                "errors": validation.get("errors", []),
                "warnings": validation.get("warnings", []),
                "minimum_viable_applied": bool(generation.get("minimum_viable_applied")),
                "adjustments": generation.get("adjustments", []),
                "metadata": metadata_for_standard,
                content_key: generation["content"],
            }
            if standard == "iiif":
                lod_samples[standard]["validation"] = validation

            if generation.get("minimum_viable_applied"):
                issues.append(
                    _build_issue(
                        issue_id=f"{standard}_minimum_viable_required",
                        severity="warning",
                        title=f"{standard.upper()} currently depends on minimum-viable fallback",
                        description=f"The sampled {standard.upper()} output required placeholder or fallback data to become minimally valid.",
                        affected_lods=[standard],
                        why="The current MSF content does not fully satisfy the template's descriptive expectations.",
                        leads_to="The document can still be generated, but some values will come from placeholders, defaults, or filename-derived fallbacks.",
                        suggested_fix=f"Enrich the MSF fields for {standard.upper()} quality, or explicitly continue with minimum-viable output.",
                    )
                )
            if not validation.get("valid", True):
                issues.append(
                    _build_issue(
                        issue_id=f"{standard}_validation_errors",
                        severity="error",
                        title=f"{standard.upper()} validation errors in sampled output",
                        description="The sampled output still fails validation after generation.",
                        affected_lods=[standard],
                        why="The current mapped metadata still violates one or more validation rules.",
                        leads_to="Generated output may be rejected downstream or require manual correction.",
                        suggested_fix="Review the reported validation messages and the highlighted MSF issues before continuing.",
                    )
                )
        except Exception as exc:
            logger.warning("Failed to build %s workflow sample for session %s: %s", standard, session_row.id, exc)
            lod_samples[standard] = {
                "valid": False,
                "errors": [str(exc)],
                "warnings": [],
                "minimum_viable_applied": False,
                "metadata": metadata_for_standard,
            }
            issues.append(
                _build_issue(
                    issue_id=f"{standard}_generation_failed",
                    severity="error",
                    title=f"{standard.upper()} sample generation failed",
                    description=str(exc),
                    affected_lods=[standard],
                    leads_to="This output cannot currently be previewed from the MSF as configured.",
                    suggested_fix="Review the listed MSF and template issues, then re-run the analysis.",
                )
            )

    preview_rows = []
    for idx, row in enumerate(df.head(10).to_dict(orient="records")):
        preview_row = dict(row)
        preview_row["__row_number"] = _preview_row_number(profile, idx)
        preview_rows.append(preview_row)
    preview = {
        "columns": list(df.columns),
        "total_rows": int(len(df)),
        "preview_rows": preview_rows,
    }

    error_count = sum(1 for issue in issues if issue.get("severity") == "error")
    warning_count = sum(1 for issue in issues if issue.get("severity") != "error")
    session_file_count = DBFile.query.filter_by(session_id=session_row.id).count()
    upload_task_id = _get_upload_task_id(session_row.id)
    is_local_pre_scan = bool(profile.get("storage_mode") == STORAGE_MODE_LOCAL and session_file_count == 0)

    original_msf_path = str(profile.get("source_file_path") or "").strip() or msf_path
    active_msf_path = msf_path
    active_msf_is_repaired = os.path.realpath(active_msf_path) != os.path.realpath(original_msf_path)

    return {
        "session_id": session_row.id,
        "msf_path": msf_path,
        "msf_profile": profile,
        "filename_column": filename_column,
        "directory_root": directory_root,
        "scan_file_count": len(directory_files),
        "validator": base_validator,
        "summary": {
            "rows_total": int(len(df)),
            "issue_count": len(issues),
            "error_count": error_count,
            "warning_count": warning_count,
            "sample_row_index": int(sample_row_index),
            "sample_row_number": _preview_row_number(profile, sample_row_index),
            "sample_filename": sample_filename,
            "filename_detection_confidence": filename_detection_confidence,
        },
        "workflow_state": {
            "storage_mode": str(profile.get("storage_mode") or ""),
            "requires_scan_start": bool(is_local_pre_scan and not upload_task_id),
            "scan_started": bool(upload_task_id),
            "session_file_count": int(session_file_count),
            "target_directory": profile.get("directory_root") or directory_root,
            "directory_recursive": _coerce_bool(profile.get("directory_recursive")) is not False,
            "active_msf_path": active_msf_path,
            "source_msf_path": original_msf_path,
            "original_msf_path": original_msf_path,
            "active_msf_kind": "repaired_copy" if active_msf_is_repaired else "source",
            "refresh_uses_active_msf": True,
        },
        "issues": issues,
        "recommended_fixes": recommendations,
        "preview": preview,
        "highlight_cells": _build_highlight_cells(issues, preview_rows),
        "lod_samples": lod_samples,
        "minimum_viable_options": [
            {
                "standard": standard,
                "enabled": True,
                "required": bool((lod_samples.get(standard) or {}).get("minimum_viable_applied")),
                "label": f"{standard.upper()} minimum viable fallback",
                "description": "Allow placeholders, filename-derived labels, and default values to keep output minimally valid.",
            }
            for standard in ("edm", "iiif", "mets")
        ],
    }


@msf_bp.route("/upload", methods=["POST"])
@jwt_required()
def upload_msf():
    """
    Upload an MSF file and return its server-side path for subsequent operations.

    Returns the path that can be used for validate, parse, and other MSF endpoints.
    """
    try:
        if "file" not in request.files:
            return APIResponse.validation_error("No file provided")

        file = request.files["file"]
        if not file.filename:
            return APIResponse.validation_error("No file selected")

        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in MSF_ALLOWED_EXTENSIONS:
            return APIResponse.validation_error(
                f"Invalid file type '{ext}'. Allowed: {', '.join(MSF_ALLOWED_EXTENSIONS)}"
            )

        original_filename = sanitize_upload_filename(file.filename, allowed_extensions=MSF_ALLOWED_EXTENSIONS)
        file_path = _store_staged_msf(file, original_filename)

        logger.info(f"MSF file uploaded: {file_path}")

        return APIResponse.success(
            data={
                "msf_path": file_path,
                "filename": original_filename,
            },
            message="MSF file uploaded successfully"
        )

    except AppException:
        raise
    except Exception as e:
        logger.error(f"MSF upload failed: {e}", exc_info=True)
        return APIResponse.server_error(f"Failed to upload MSF file: {e}")


@msf_bp.route("/parse", methods=["POST"])
@jwt_required()
def parse_msf():
    """
    Parse an MSF file and return its columns and preview data.

    Accepts either:
    - File upload (multipart/form-data with 'file' field)
    - JSON with 'msf_path' for server-side files
    """
    temporary = None
    try:
        project_service = current_app.project_service

        # Check for file upload
        if "file" in request.files:
            file = request.files["file"]
            if not file.filename:
                return APIResponse.validation_error("No file provided")

            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in MSF_ALLOWED_EXTENSIONS:
                return APIResponse.validation_error(
                    f"Invalid file type. Allowed: {', '.join(MSF_ALLOWED_EXTENSIONS)}"
                )

            size = _staged_msf_size(file)
            with admit_upload(int(get_jwt_identity()), size, kind="inspect"):
                temporary = tempfile.TemporaryDirectory(prefix="parse-", dir=_account_msf_workspace())
                safe_filename = sanitize_upload_filename(file.filename, allowed_extensions=MSF_ALLOWED_EXTENSIONS)
                msf_path = os.path.join(temporary.name, safe_filename)
                file.save(msf_path)
                df, columns = msf_service.parse_msf_file(msf_path)
        else:
            # Get path from JSON
            data = request.get_json() or {}
            msf_path = data.get("msf_path")

            if not msf_path:
                return APIResponse.validation_error("No MSF file or path provided")

            msf_path = _workflow_msf_input(msf_path, project_service)
            df, columns = msf_service.parse_msf_file(msf_path)
        preview = msf_service.get_msf_preview(df)

        return APIResponse.success(
            data={
                "columns": columns,
                "total_rows": len(df),
                "preview": preview["preview_rows"],
            },
            message="MSF file parsed successfully"
        )

    except AppException:
        raise
    except ValueError as e:
        logger.warning(f"MSF parse error: {e}")
        return APIResponse.validation_error(str(e))
    except Exception as e:
        logger.error(f"MSF parse failed: {e}", exc_info=True)
        return APIResponse.server_error(f"Failed to parse MSF file: {e}")
    finally:
        if temporary:
            temporary.cleanup()


@msf_bp.route("/validate", methods=["POST"])
@jwt_required()
def validate_msf():
    """
    Validate an MSF file against a directory.
    Returns matched files, missing files, and unmapped files.

    Request body:
    {
        "msf_path": "/path/to/MSF.csv",
        "directory_path": "/path/to/directory",
        "filename_column": "Filename"  // Optional, auto-detected if not provided
    }
    """
    try:
        project_service = current_app.project_service
        data = request.get_json() or {}

        msf_path = data.get("msf_path")
        directory_path = data.get("directory_path")
        filename_column = data.get("filename_column")

        if not msf_path:
            return APIResponse.validation_error("msf_path is required")
        if not directory_path:
            return APIResponse.validation_error("directory_path is required")

        msf_path = _workflow_msf_input(msf_path, project_service)
        directory_path = _workflow_msf_input(directory_path, project_service, directory=True)

        if not os.path.exists(msf_path):
            return APIResponse.error(f"MSF file not found: {msf_path}", 404)
        if not os.path.isdir(directory_path):
            return APIResponse.error(f"Directory not found: {directory_path}", 404)

        # Parse MSF
        df, _ = msf_service.parse_msf_file(msf_path)

        # Get directory files
        directory_files = _get_directory_files(directory_path)
        logger.info(f"Found {len(directory_files)} files in directory: {directory_files}")

        # Validate
        result = msf_service.validate_msf_against_directory(
            df, directory_files, filename_column
        )

        return APIResponse.success(
            data=result.to_dict(),
            message="MSF validation completed"
        )

    except AppException:
        raise
    except ValueError as e:
        logger.warning(f"MSF validation error: {e}")
        return APIResponse.validation_error(str(e))
    except Exception as e:
        logger.error(f"MSF validation failed: {e}", exc_info=True)
        return APIResponse.server_error(f"Failed to validate MSF: {e}")


@msf_bp.route("/detect-filename-column", methods=["POST"])
@jwt_required()
def detect_filename_column():
    """
    Auto-detect which column in the MSF contains filenames.

    Request body:
    {
        "msf_path": "/path/to/MSF.csv",
        "directory_path": "/path/to/directory"
    }
    """
    try:
        project_service = current_app.project_service
        data = request.get_json() or {}

        msf_path = data.get("msf_path")
        directory_path = data.get("directory_path")

        if not msf_path:
            return APIResponse.validation_error("msf_path is required")
        if not directory_path:
            return APIResponse.validation_error("directory_path is required")

        msf_path = _workflow_msf_input(msf_path, project_service)
        directory_path = _workflow_msf_input(directory_path, project_service, directory=True)

        if not os.path.exists(msf_path):
            return APIResponse.error(f"MSF file not found: {msf_path}", 404)
        if not os.path.isdir(directory_path):
            return APIResponse.error(f"Directory not found: {directory_path}", 404)

        # Parse MSF
        df, columns = msf_service.parse_msf_file(msf_path)

        # Get directory files
        directory_files = _get_directory_files(directory_path)

        # Detect filename column
        detected_column, confidence = msf_service.detect_filename_column(df, directory_files)

        return APIResponse.success(
            data={
                "detected_column": detected_column,
                "confidence": round(confidence, 3),
                "all_columns": columns,
            },
            message="Filename column detection completed"
        )

    except AppException:
        raise
    except ValueError as exc:
        return APIResponse.validation_error(str(exc))
    except Exception as e:
        logger.error(f"Filename column detection failed: {e}", exc_info=True)
        return APIResponse.server_error(f"Failed to detect filename column: {e}")


@msf_bp.route("/default-mapping", methods=["GET"])
@jwt_required()
def get_default_mapping():
    """Get the default column-to-Zenodo field mapping configuration"""
    return APIResponse.success(
        data={
            "mapping": msf_service.get_default_column_mapping(),
        },
        message="Default column mapping retrieved"
    )


@msf_bp.route("/metadata-for-files", methods=["POST"])
@jwt_required()
def get_metadata_for_files():
    """
    Get Zenodo-formatted metadata for specific files from an MSF.

    Request body:
    {
        "msf_path": "/path/to/MSF.csv",
        "filenames": ["file1.obj", "file2.glb"],
        "filename_column": "Filename",  // Optional
        "column_mapping": {...}  // Optional custom mapping
    }
    """
    try:
        project_service = current_app.project_service
        data = request.get_json() or {}

        msf_path = data.get("msf_path")
        filenames = data.get("filenames", [])
        filename_column = data.get("filename_column")
        column_mapping = data.get("column_mapping")

        if not msf_path:
            return APIResponse.validation_error("msf_path is required")
        if not filenames:
            return APIResponse.validation_error("filenames list is required")

        msf_path = _workflow_msf_input(msf_path, project_service)

        if not os.path.exists(msf_path):
            return APIResponse.error(f"MSF file not found: {msf_path}", 404)

        # Parse MSF
        df, columns = msf_service.parse_msf_file(msf_path)

        # Auto-detect filename column if not provided
        if not filename_column:
            detected_column, _ = msf_service.detect_filename_column(df, filenames)
            if detected_column:
                filename_column = detected_column
            else:
                return APIResponse.validation_error("Could not detect filename column")

        # Get metadata for each file
        metadata_map = msf_service.get_all_file_metadata(
            df, filenames, filename_column, column_mapping
        )

        return APIResponse.success(
            data={
                "filename_column": filename_column,
                "metadata": metadata_map,
                "found_count": len(metadata_map),
                "requested_count": len(filenames),
            },
            message="Metadata retrieved successfully"
        )

    except AppException:
        raise
    except ValueError as exc:
        return APIResponse.validation_error(str(exc))
    except Exception as e:
        logger.error(f"Get metadata for files failed: {e}", exc_info=True)
        return APIResponse.server_error(f"Failed to get metadata: {e}")


@msf_bp.route("/patch", methods=["POST"])
@jwt_required()
def patch_msf():
    """
    Analyze and optionally patch an MSF file to fix common ingestion blockers.

    Request body:
    {
        "msf_path": "/path/to/msf.csv",
        "directory_path": "/optional/path/to/assets",
        "filename_column": "Filename",
        "duplicate_policy": "fail|keep_first|merge_non_empty",
        "parse_options": {"use_first_row_as_header": false, "delimiter": ","},
        "apply": false,
        "output_directory": "/optional/output/path",
        "recursive": true
    }
    """
    try:
        project_service = current_app.project_service
        data = request.get_json() or {}
        storage_mode = CloudUploadService.get_storage_mode()

        msf_path = data.get("msf_path")
        if not msf_path:
            return APIResponse.validation_error("msf_path is required")

        directory_path = data.get("directory_path")
        filename_column = data.get("filename_column")
        duplicate_policy = data.get("duplicate_policy", "fail")
        apply_patch = _coerce_bool(data.get("apply"))
        output_directory = data.get("output_directory")
        recursive_scan = True if "recursive" not in data else _coerce_bool(data.get("recursive"))
        parse_options = _build_parse_options(data)

        msf_path = _workflow_msf_input(msf_path, project_service)

        translated_directory_path = None
        directory_files: List[str] = []
        if directory_path:
            translated_directory_path = _workflow_msf_input(directory_path, project_service, directory=True)
            if not os.path.isdir(translated_directory_path):
                return APIResponse.error(f"Directory not found: {translated_directory_path}", 404)
            directory_files = _scan_directory_files(translated_directory_path, recursive=recursive_scan)

        admin_local = storage_mode == STORAGE_MODE_LOCAL and _is_admin_request_user()
        if output_directory:
            if admin_local:
                output_directory = _resolve_local_directory_path(output_directory, project_service)
            else:
                output_directory = _resolve_upload_folder_path(
                    project_service._translate_path(output_directory, to_container=True),
                    must_be_file=False,
                )

        generated_in_scratch = apply_patch and not admin_local
        context = tempfile.TemporaryDirectory(prefix="webhdp-msf-patch-") if generated_in_scratch else nullcontext(output_directory)
        with context as output_dir:
            report = msf_service.patch_msf_file(
                file_path=msf_path,
                parse_options=parse_options,
                directory_files=directory_files,
                directory_root=translated_directory_path,
                filename_column=filename_column,
                duplicate_policy=duplicate_policy,
                apply=apply_patch,
                output_dir=output_dir,
            )
            generated = report.get("patched_msf_path")
            if generated_in_scratch and generated:
                with open(generated, "rb") as stream:
                    file = FileStorage(stream=stream, filename=Path(generated).name)
                    saved = _store_staged_msf(file, file.filename, output_directory)
                report["patched_msf_path"] = saved
                report["actions"] = [action.replace(generated, saved) for action in report.get("actions", [])]

        message = "MSF patch analysis completed"
        if apply_patch and report.get("patched_msf_path"):
            message = "MSF patch applied successfully"
        elif apply_patch and not report.get("patched_msf_path"):
            message = "MSF patch apply requested, but blockers remain"

        return APIResponse.success(data=report, message=message)
    except AppException:
        raise
    except ValueError as exc:
        logger.warning(f"MSF patch validation error: {exc}")
        return APIResponse.validation_error(str(exc))
    except Exception as exc:
        logger.error(f"MSF patch failed: {exc}", exc_info=True)
        return APIResponse.server_error(f"Failed to patch MSF: {exc}")


@msf_bp.route("/workflow/session/<int:session_id>/analyze", methods=["POST"])
@jwt_required()
def analyze_workflow_session_msf(session_id: int):
    """Analyze the session MSF for workflow readiness and optionally apply fixes."""
    try:
        session_row, _, error_response = get_session_with_permission(
            session_id,
            permission="edit",
            require_mutable=True,
        )
        if error_response:
            return error_response

        data = request.get_json() or {}
        apply_selected_fixes = _coerce_bool(data.get("apply_selected_fixes"))
        selected_fix_ids = {
            str(item).strip()
            for item in (data.get("selected_fix_ids") or [])
            if str(item or "").strip()
        }

        profile = _get_session_msf_profile(session_id)
        parse_options = _build_parse_options(data)
        if not parse_options and isinstance(profile.get("parse_options"), dict):
            parse_options = dict(profile.get("parse_options") or {})

        if str(profile.get("storage_mode") or "") == STORAGE_MODE_LOCAL:
            project_service = current_app.project_service
            has_parse_option_update = any(
                key in data for key in ("parse_options", "sheet_name", "delimiter", "use_first_row_as_header")
            )
            has_directory_update = "directory_path" in data
            has_msf_update = bool(str(data.get("msf_path") or "").strip())
            if has_parse_option_update or has_directory_update or has_msf_update:
                updated_profile = dict(profile or {})
                if has_directory_update:
                    updated_profile["directory_root"] = _resolve_local_directory_path(
                        data.get("directory_path"),
                        project_service,
                    )
                if "recursive" in data:
                    recursive = _coerce_bool(data.get("recursive"))
                    if recursive is not None:
                        updated_profile["directory_recursive"] = bool(recursive)
                if has_msf_update:
                    resolved_msf_path = _resolve_local_msf_path(data.get("msf_path"), project_service)
                    updated_profile["source_file_path"] = resolved_msf_path
                    updated_profile["file_path"] = resolved_msf_path
                    updated_profile["filename_column"] = None
                if has_parse_option_update:
                    updated_profile["parse_options"] = parse_options
                    updated_profile["file_path"] = updated_profile.get("source_file_path") or updated_profile.get("file_path")
                    updated_profile["filename_column"] = None
                updated_profile["scan_started"] = False
                _persist_session_msf_profile(session_id, updated_profile)
                profile = updated_profile
                parse_options = dict(updated_profile.get("parse_options") or {})

        msf_path = _resolve_session_msf_path(session_row)
        if not msf_path or not os.path.exists(msf_path):
            return APIResponse.validation_error("No session MSF file could be resolved")

        directory_files, directory_root = _resolve_session_directory_files(session_row)
        analysis = _analyze_workflow_session_msf(
            session_row,
            msf_path=msf_path,
            parse_options=parse_options,
            directory_files=directory_files,
            directory_root=directory_root,
        )

        apply_result = {
            "requested": bool(apply_selected_fixes),
            "applied": False,
            "selected_fix_ids": sorted(selected_fix_ids),
            "actions": [],
            "patched_msf_path": None,
        }

        if apply_selected_fixes:
            available_fix_map = {
                str(item.get("id")): item
                for item in (analysis.get("recommended_fixes") or [])
                if item.get("id")
            }
            if not selected_fix_ids:
                selected_fix_ids = set(available_fix_map.keys())
                apply_result["selected_fix_ids"] = sorted(selected_fix_ids)
            else:
                selected_fix_ids = _expand_recommendation_dependencies(selected_fix_ids, available_fix_map)
                apply_result["selected_fix_ids"] = sorted(selected_fix_ids)

            operations: List[Dict[str, Any]] = []
            for fix_id in selected_fix_ids:
                fix = available_fix_map.get(fix_id)
                if not fix:
                    continue
                for operation in fix.get("operations") or []:
                    if isinstance(operation, dict):
                        operations.append(operation)

            if operations:
                apply_report = msf_service.run_local_validator(
                    file_path=msf_path,
                    parse_options=parse_options,
                    directory_files=directory_files,
                    directory_root=directory_root,
                    filename_column=analysis.get("filename_column"),
                    duplicate_scan_columns=[analysis.get("filename_column")] if analysis.get("filename_column") else [],
                    operations=operations,
                    include_reference_check=True,
                    include_dataframe=True,
                )
                if apply_report.get("_dataframe") is not None:
                    export_format = os.path.splitext(msf_path)[1].lstrip(".").lower() or "csv"
                    if export_format not in {"csv", "xlsx"}:
                        export_format = "xlsx"
                    patched_path = msf_service.write_dataframe_export(
                        apply_report["_dataframe"],
                        msf_path,
                        export_format,
                        parse_options=apply_report.get("_export_parse_options") or parse_options,
                        output_dir=_resolve_session_uploads_dir(session_row),
                    )

                    updated_profile = dict(profile or {})
                    updated_profile.update(
                        {
                            "file_path": patched_path,
                            "filename_column": apply_report.get("filename_column") or analysis.get("filename_column"),
                            "parse_options": apply_report.get("parse_options") or parse_options,
                            "sheet_name": apply_report.get("sheet_name") or updated_profile.get("sheet_name"),
                            "available_sheets": apply_report.get("available_sheets") or updated_profile.get("available_sheets", []),
                            "header_row_index": apply_report.get("header_row_index"),
                            "suggested_row_index": (analysis.get("summary") or {}).get("sample_row_index"),
                        }
                    )
                    _upsert_session_metadata(session_id, "msf_profile", json.dumps(updated_profile))
                    db.session.commit()

                    apply_result.update(
                        {
                            "applied": True,
                            "actions": (apply_report.get("actions") or []) + (apply_report.get("blockers") or []),
                            "patched_msf_path": patched_path,
                        }
                    )

                    analysis = _analyze_workflow_session_msf(
                        session_row,
                        msf_path=patched_path,
                        parse_options=updated_profile.get("parse_options") or parse_options,
                        directory_files=directory_files,
                        directory_root=directory_root,
                    )
                else:
                    apply_result["actions"] = apply_report.get("blockers") or ["Selected fixes could not be applied."]

        _persist_session_msf_profile(session_id, analysis.get("msf_profile") or profile)

        return APIResponse.success(
            data={
                "analysis": analysis,
                "apply_result": apply_result,
            },
            message="Workflow MSF analysis completed",
        )
    except AppException:
        raise
    except Exception as exc:
        logger.error("Workflow MSF analysis failed: %s", exc, exc_info=True)
        return APIResponse.server_error(f"Failed to analyze workflow MSF: {exc}")


@msf_bp.route("/workflow/local/prepare", methods=["POST"])
@jwt_required()
def prepare_local_workflow_session():
    """Create a lightweight workflow session so local MSF issues can be repaired before scanning."""
    try:
        if CloudUploadService.get_storage_mode() != STORAGE_MODE_LOCAL:
            return APIResponse.forbidden("Local MSF workflow preparation is only available in local storage mode")

        project_service = current_app.project_service
        user_id = int(get_jwt_identity())
        data = request.get_json() or {}
        from routes.session_routes import _normalize_session_workspace_options

        msf_path = _resolve_local_msf_path(data.get("msf_path"), project_service)
        directory_root = _resolve_local_directory_path(data.get("directory_path"), project_service)
        parse_options = _build_parse_options(data)
        duplicate_policy = str(data.get("duplicate_policy") or "merge_non_empty").strip().lower()
        recursive = _coerce_bool(data.get("recursive"))
        if recursive is None:
            recursive = True
        current_user = db.session.get(User, user_id)
        workspace_options = _normalize_session_workspace_options(user=current_user, payload=data or {})

        with admit_upload(user_id, 0):
            session_row, _, _, _ = _create_workflow_session_dirs(user_id, origin_type=MOUNTED_INPUT_ORIGIN, **workspace_options)
        scanned_files = _scan_directory_files(directory_root, recursive=recursive)
        preflight = msf_service.patch_msf_file(
            file_path=msf_path,
            parse_options=parse_options,
            directory_files=scanned_files,
            directory_root=directory_root,
            duplicate_policy=duplicate_policy,
            apply=False,
        )

        profile = {
            "file_path": msf_path,
            "source_file_path": msf_path,
            "parse_options": parse_options,
            "directory_root": directory_root,
            "directory_recursive": bool(recursive),
            "storage_mode": STORAGE_MODE_LOCAL,
            "duplicate_policy": duplicate_policy,
            "filename_column": preflight.get("filename_column"),
            "scan_started": False,
        }
        _persist_session_msf_profile(session_row.id, profile)

        analysis = _analyze_workflow_session_msf(
            session_row,
            msf_path=msf_path,
            parse_options=parse_options,
            directory_files=scanned_files,
            directory_root=directory_root,
        )
        _persist_session_msf_profile(session_row.id, analysis.get("msf_profile") or profile)

        return APIResponse.success(
            data={
                "session_id": session_row.id,
                "analysis": analysis,
                "msf_profile": analysis.get("msf_profile") or profile,
                "msf_preflight": preflight,
            },
            message="Local MSF workflow session prepared",
        )
    except ValueError as exc:
        logger.warning("Local MSF workflow preparation failed: %s", exc)
        return APIResponse.validation_error(str(exc))
    except AppException:
        raise
    except Exception as exc:
        logger.error("Local MSF workflow preparation failed: %s", exc, exc_info=True)
        return APIResponse.server_error(f"Failed to prepare local MSF workflow: {exc}")


@msf_bp.route("/workflow/session/<int:session_id>/start-local-scan", methods=["POST"])
@jwt_required()
def start_local_workflow_scan(session_id: int):
    """Run the real local directory scan after guided MSF repair has completed."""
    try:
        if CloudUploadService.get_storage_mode() != STORAGE_MODE_LOCAL:
            return APIResponse.forbidden("Local workflow scanning is only available in local storage mode")

        session_row, actor, error_response = get_session_with_permission(
            session_id,
            permission="edit",
            require_mutable=True,
        )
        if error_response:
            return error_response

        existing_task_id = _get_upload_task_id(session_id)
        if existing_task_id and normalize_session_state(session_row.status) == "queued":
            return APIResponse.accepted(
                message="Local scan is already running.",
                data={
                    "session_id": session_id,
                    "task_id": existing_task_id,
                    "reused": True,
                },
            )

        profile = _get_session_msf_profile(session_id)
        if str(profile.get("storage_mode") or "") != STORAGE_MODE_LOCAL:
            return APIResponse.validation_error("Session is not configured for local workflow scanning")

        msf_path = _resolve_session_msf_path(session_row)
        if not msf_path or not os.path.exists(msf_path):
            return APIResponse.validation_error("No session MSF file could be resolved")

        parse_options = profile.get("parse_options") if isinstance(profile.get("parse_options"), dict) else {}
        directory_root = str(profile.get("directory_root") or "").strip()
        if not directory_root or not os.path.isdir(directory_root):
            return APIResponse.validation_error("The selected local target directory is missing")

        recursive = _coerce_bool(profile.get("directory_recursive"))
        scanned_files = _scan_directory_files(directory_root, recursive=recursive is not False)
        uploads_dir = _resolve_session_uploads_dir(session_row)
        duplicate_policy = str(profile.get("duplicate_policy") or "merge_non_empty").strip().lower()

        preflight = msf_service.patch_msf_file(
            file_path=msf_path,
            parse_options=parse_options,
            directory_files=scanned_files,
            directory_root=directory_root,
            duplicate_policy=duplicate_policy,
            apply=True,
            output_dir=uploads_dir,
        )
        if not preflight.get("is_valid", False):
            return APIResponse.validation_error("MSF preflight failed", details=preflight)

        patched_msf_path = preflight.get("patched_msf_path")
        final_msf_path = patched_msf_path if patched_msf_path and os.path.exists(patched_msf_path) else msf_path
        final_parse_options = preflight.get("parse_options") or parse_options

        updated_profile = dict(profile)
        updated_profile.update(
            {
                "file_path": final_msf_path,
                "parse_options": final_parse_options,
                "filename_column": preflight.get("filename_column") or profile.get("filename_column"),
                "scan_started": True,
            }
        )
        _upsert_session_metadata(session_id, "msf_profile", json.dumps(updated_profile))

        from tasks import start_upload_coordinator

        task = start_upload_coordinator.delay(
            session_id=session_id,
            zip_path=None,
            msf_path=final_msf_path,
            storage_mode=STORAGE_MODE_LOCAL,
            msf_parse_options=final_parse_options,
            input_directory_path=directory_root,
            requested_by_user_id=actor.id,
        )

        queued_progress = {
            "current_stage": "queued",
            "status_message": "Local directory scan queued",
            "current_index": 0,
            "total_files": 0,
            "processed_count": 0,
            "failed_count": 0,
            "percent": 0,
            "updated_at": datetime.utcnow().isoformat(),
        }
        session_row.status = normalize_session_state("queued")
        _upsert_session_metadata(session_id, UPLOAD_TASK_ID_FIELD, task.id)
        _upsert_session_metadata(session_id, UPLOAD_STORAGE_MODE_FIELD, STORAGE_MODE_LOCAL)
        _upsert_session_metadata(session_id, UPLOAD_PROGRESS_FIELD, json.dumps(queued_progress))
        db.session.commit()

        return APIResponse.accepted(
            message="Local directory scan started in background.",
            data={
                "session_id": session_id,
                "task_id": task.id,
                "reused": False,
                "msf_preflight": {
                    "is_valid": preflight.get("is_valid"),
                    "actions": preflight.get("actions", []),
                    "warnings": preflight.get("warnings", []),
                    "summary": preflight.get("summary", {}),
                    "patched_msf_path": patched_msf_path,
                },
            },
        )
    except ValueError as exc:
        logger.warning("Starting local workflow scan failed: %s", exc)
        return APIResponse.validation_error(str(exc))
    except Exception as exc:
        logger.error("Starting local workflow scan failed: %s", exc, exc_info=True)
        return APIResponse.server_error(f"Failed to start local workflow scan: {exc}")


@msf_bp.route("/tools/local/context", methods=["GET"])
@jwt_required()
def local_validator_context():
    """Return availability metadata for the MSF Validator (Local) page."""
    try:
        project_service = current_app.project_service
        storage_mode = CloudUploadService.get_storage_mode()
        is_admin = _is_admin_request_user()
        enabled = bool(is_admin and storage_mode == STORAGE_MODE_LOCAL)

        input_root = project_service._translate_path(_resolve_local_input_root(), to_container=True)
        msf_files = _list_local_msf_files(input_root) if enabled else []
        reasons: List[str] = []
        if not is_admin:
            reasons.append("Admin role required")
        if storage_mode != STORAGE_MODE_LOCAL:
            reasons.append("HPC local mode required")
        if enabled and not msf_files:
            reasons.append("No MSF files found in local input directory")

        return APIResponse.success(
            data={
                "enabled": enabled,
                "is_admin": is_admin,
                "storage_mode": storage_mode,
                "input_root": input_root,
                "reasons": reasons,
                "msf_files": msf_files,
            }
        )
    except Exception as exc:
        logger.error("Failed to load MSF local validator context: %s", exc, exc_info=True)
        return APIResponse.server_error(f"Failed to load MSF validator context: {exc}")


@msf_bp.route("/tools/local/validate", methods=["POST"])
@jwt_required()
@require_admin_and_local_mode
def validate_local_msf_tools():
    """Run local MSF validator checks and operations."""
    try:
        project_service = current_app.project_service
        data = request.get_json() or {}
        parse_options = _build_parse_options(data)
        recursive_scan = True if "recursive" not in data else _coerce_bool(data.get("recursive"))

        msf_path = _resolve_local_msf_path(data.get("msf_path"), project_service)
        directory_path = _resolve_local_directory_path(data.get("directory_path"), project_service)
        directory_files = _scan_directory_files(directory_path, recursive=recursive_scan)

        duplicate_scan_columns = data.get("duplicate_scan_columns") or []
        if not isinstance(duplicate_scan_columns, list):
            return APIResponse.validation_error("duplicate_scan_columns must be a list")

        operations = data.get("operations") or []
        if operations is not None and not isinstance(operations, list):
            return APIResponse.validation_error("operations must be a list")

        include_reference_check = True if "include_reference_check" not in data else _coerce_bool(
            data.get("include_reference_check")
        )

        report = msf_service.run_local_validator(
            file_path=msf_path,
            parse_options=parse_options,
            directory_files=directory_files,
            directory_root=directory_path,
            filename_column=data.get("filename_column"),
            duplicate_scan_columns=duplicate_scan_columns,
            operations=operations,
            include_reference_check=include_reference_check,
            include_dataframe=False,
        )

        return APIResponse.success(
            data=report,
            message="MSF local validator run completed",
        )
    except ValueError as exc:
        logger.warning("MSF local validator validation error: %s", exc)
        return APIResponse.validation_error(str(exc))
    except Exception as exc:
        logger.error("MSF local validator failed: %s", exc, exc_info=True)
        return APIResponse.server_error(f"Failed to run local MSF validator: {exc}")


@msf_bp.route("/tools/local/export", methods=["POST"])
@jwt_required()
@require_admin_and_local_mode
def export_local_msf_tools():
    """Export local MSF validator output as CSV or XLSX."""
    try:
        project_service = current_app.project_service
        data = request.get_json() or {}
        parse_options = _build_parse_options(data)
        recursive_scan = True if "recursive" not in data else _coerce_bool(data.get("recursive"))
        export_format = str(data.get("format") or "xlsx").strip().lower()
        if export_format not in {"csv", "xlsx"}:
            return APIResponse.validation_error("format must be 'csv' or 'xlsx'")

        msf_path = _resolve_local_msf_path(data.get("msf_path"), project_service)
        directory_path = _resolve_local_directory_path(data.get("directory_path"), project_service)
        directory_files = _scan_directory_files(directory_path, recursive=recursive_scan)

        duplicate_scan_columns = data.get("duplicate_scan_columns") or []
        if not isinstance(duplicate_scan_columns, list):
            return APIResponse.validation_error("duplicate_scan_columns must be a list")

        operations = data.get("operations") or []
        if operations is not None and not isinstance(operations, list):
            return APIResponse.validation_error("operations must be a list")

        include_reference_check = True if "include_reference_check" not in data else _coerce_bool(
            data.get("include_reference_check")
        )
        allow_export_with_blockers = True if "allow_export_with_blockers" not in data else _coerce_bool(
            data.get("allow_export_with_blockers")
        )

        report = msf_service.run_local_validator(
            file_path=msf_path,
            parse_options=parse_options,
            directory_files=directory_files,
            directory_root=directory_path,
            filename_column=data.get("filename_column"),
            duplicate_scan_columns=duplicate_scan_columns,
            operations=operations,
            include_reference_check=include_reference_check,
            include_dataframe=True,
        )
        blockers = report.get("blockers") or []
        if blockers and not allow_export_with_blockers:
            return APIResponse.validation_error(
                "Export blocked because validation blockers remain",
                details={"blockers": blockers, "summary": report.get("summary", {})},
            )

        working_df = report.pop("_dataframe", None)
        export_parse_options = report.pop("_export_parse_options", {})
        if working_df is None:
            return APIResponse.server_error("MSF export failed: missing transformed DataFrame")

        output_directory = current_app.config.get("UPLOAD_FOLDER", "/tmp")
        exported_path = msf_service.write_dataframe_export(
            df=working_df,
            source_path=msf_path,
            file_format=export_format,
            parse_options=export_parse_options,
            output_dir=output_directory,
        )

        source_base = os.path.splitext(os.path.basename(msf_path))[0]
        download_name = f"{source_base}.validator.{export_format}"
        mime_type = (
            "text/csv"
            if export_format == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        return send_file(
            exported_path,
            as_attachment=True,
            download_name=download_name,
            mimetype=mime_type,
        )
    except ValueError as exc:
        logger.warning("MSF local validator export validation error: %s", exc)
        return APIResponse.validation_error(str(exc))
    except Exception as exc:
        logger.error("MSF local validator export failed: %s", exc, exc_info=True)
        return APIResponse.server_error(f"Failed to export local MSF validator output: {exc}")
