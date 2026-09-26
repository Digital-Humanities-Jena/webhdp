# routes/session_routes.py
import json
import logging
import os
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, Response, redirect, request, send_file, current_app
from flask import session as flask_session
from flask_jwt_extended import get_jwt_identity, jwt_required, verify_jwt_in_request
from sqlalchemy import func

from api_utils import APIResponse
from constants import (
    MSF_ALLOWED_EXTENSIONS,
    RECORD_RESOLUTION_STATE_FIELD,
    SHARED_SCAN_OPTIONS,
    UPLOAD_PROGRESS_FIELD,
    UPLOAD_STORAGE_MODE_FIELD,
    UPLOAD_SUBMIT_TOKEN_FIELD,
    UPLOAD_TASK_ID_FIELD,
    UPLOAD_WORKER_GROUP_ID_FIELD,
    WORKFLOW_STATE_FIELD,
)
from database.database import db
from database.models import BatchFileMetadata, CloudMirrorObject, File, Institution, Session as DBSession, Submission, User, UserMetadata
from exceptions import SecurityError, ValidationError
from routes.access_helpers import get_current_user_from_jwt, get_session_with_permission
from security import resolve_child_path, safe_extract_zip, sanitize_upload_filename
from services.audit_service import list_audit_events, record_audit_event
from services.notification_service import notify_admins
from services.institution_service import InstitutionService
from services.hdpc_import_service import import_hdpc_for_user
from services.hdpc_local_service import (
    classify_hdpc_record_inventory,
    is_canonical_hdpc_record,
    inspect_hdpc_project,
    match_hdpc_files_for_versioning,
    normalize_hdpc_record_origin,
    read_hdpc_file_hierarchy,
    read_hdpc_latest_published_record_files,
    read_hdpc_operations_summary,
    read_hdpc_project_info,
    read_hdpc_project_stats,
    read_hdpc_published_records,
    read_hdpc_record_context,
    read_hdpc_record_lineage,
    read_hdpc_record_files,
    read_hdpc_record_traceability,
    read_hdpc_record_zenodo_status,
    read_hdpc_source_files,
    read_hdpc_uploadable_files,
    read_hdpc_uploads_by_tab,
    read_hdpc_workspace_summary,
)
from services.hdpc_shared_export_service import (
    SHARED_EXPORT_ARTIFACT_KIND,
    create_sanitized_shared_export,
)
from services.hdpc_provenance_service import build_hdpc_provenance
from services.hdpc_zenodo_service import discard_draft as discard_local_zenodo_draft
from services.session_batch_history_service import (
    get_task_entry as get_session_batch_task_entry,
    list_task_entries as list_session_batch_task_entries,
    record_task_launch as record_session_batch_task_launch,
    update_task_entry as update_session_batch_task_entry,
)
from services.dataset_integrity_service import (
    DatasetIntegrityConflictError,
    analyze_session_record_resolution,
    build_model_preview,
    ensure_record_operation_allowed,
    extract_dataset_key,
    normalize_dataset_key,
    read_session_record_inventory,
    save_session_record_resolution_state,
    validate_record_resolution_decisions,
)
from services.publishing_context_service import PublishingContextService
from services.session_access_service import (
    build_session_permissions,
    can_download_hdpc,
    can_download_shared_hdpc,
    can_view_session,
    get_accessible_sessions,
    is_platform_moderator_or_admin,
)
from services.cloud_mirror_service import build_session_cloud_download_payload
from workflow_status import (
    RUNNING_UPLOAD_STAGES,
    is_downloadable_session_state,
    normalize_session_state,
    normalize_source_upload_state,
    normalize_source_validation_state,
    normalize_upload_file_counts,
)

logger = logging.getLogger(__name__)
session_bp = Blueprint("sessions", __name__)
publishing_context_service = PublishingContextService()
institution_service = InstitutionService()

INTERNAL_ZENODO_KEYS = {"lod_mapping", "msf_path"}
WORKFLOW_PHASE_TO_STEP = {
    "upload": 1,
    "msf_analysis": 2,
    "files": 3,
    "metadata": 4,
    "edm_selection": 5,
    "pipeline": 6,
    "submit": 7,
    "processing": 7,
    "completed": 7,
    "failed": 7,
}
WORKFLOW_PHASE_TO_ROUTE = {
    "upload": "/workflow/upload",
    "msf_analysis": "/workflow/msf-analysis",
    "files": "/workflow/files",
    "metadata": "/workflow/metadata",
    "edm_selection": "/workflow/edm-selection",
    "pipeline": "/workflow/pipeline",
    "submit": "/workflow/submit",
    "processing": "/workflow/submit",
}
WORKFLOW_PHASE_TO_LABEL = {
    "msf_analysis": "Resume MSF Repair",
    "files": "Resume File Review",
    "metadata": "Resume Metadata",
    "edm_selection": "Resume EDM Setup",
    "pipeline": "Resume Pipeline Selection",
    "submit": "Resume Submission Review",
    "processing": "Open Processing",
}
TERMINAL_WORKFLOW_PHASES = {"completed", "failed"}
THUMBNAIL_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
THREE_D_FILE_EXTENSIONS = {".glb", ".gltf", ".obj", ".ply", ".stl", ".fbx", ".usdz"}
THREE_D_MIME_PREFIXES = (
    "model/",
    "application/octet-stream",
)
VALID_SHARING_SCOPES = {"private", "institution"}
VALID_CREDENTIAL_PREFERENCES = {"user", "institution"}


def _inspect_session_hdpc(session_row: DBSession, *, show_files: bool = True) -> dict:
    if not session_row.hdpc_path:
        raise ValidationError("Project file not found for this session")

    return inspect_hdpc_project(session_row.hdpc_path, show_files=show_files)


def _parse_json(raw_value, fallback):
    if raw_value is None:
        return fallback
    if isinstance(raw_value, (dict, list)):
        return raw_value
    try:
        return json.loads(raw_value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _session_origin_metadata(session_row: DBSession) -> dict[str, Any] | None:
    origin_metadata = getattr(session_row, "origin_metadata", None)
    return origin_metadata if isinstance(origin_metadata, dict) else None


def _build_hdpc_download_policy(session_row: DBSession, user: User | None) -> dict[str, Any]:
    return {
        "scope": "owner_only",
        "can_download": can_download_hdpc(session_row, user),
        "message": "Only the session owner can download raw .hdpc files.",
    }


def _build_shared_hdpc_download_policy(session_row: DBSession, user: User | None) -> dict[str, Any]:
    return {
        "scope": "institution_reader_plus",
        "enabled": bool(getattr(session_row, "institution_id", None))
        and str(getattr(session_row, "sharing_scope", None) or "private").strip().lower() != "private",
        "can_download": can_download_shared_hdpc(session_row, user),
        "message": "Institution readers and above can download the sanitized shared .hdpc export for institution-shared sessions.",
        "artifact_kind": SHARED_EXPORT_ARTIFACT_KIND,
    }


def _coerce_bool(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _normalize_choice(value, *, allowed: set[str], default: str, field_name: str) -> str:
    text = str(value or default).strip().lower()
    if text not in allowed:
        raise ValidationError(f"{field_name} must be one of: {', '.join(sorted(allowed))}")
    return text


def _parse_positive_int_arg(name: str, default: int) -> int:
    raw_value = request.args.get(name, default)
    try:
        normalized_value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be an integer") from exc
    if normalized_value < 1:
        raise ValidationError(f"{name} must be greater than 0")
    return normalized_value


def _serialize_user_workspace_option(
    user: User,
    *,
    institution_role: str | None = None,
    eligible: bool = True,
    reason: str | None = None,
    is_current: bool = False,
) -> dict[str, Any]:
    return {
        "id": user.id,
        "public_id": user.public_id,
        "slug": user.slug,
        "email": user.email,
        "display_name": user.display_name,
        "full_name": user.full_name,
        "affiliation": user.affiliation,
        "institution_role": institution_role,
        "eligible": bool(eligible),
        "reason": reason,
        "is_current": bool(is_current),
    }


def _serialize_institution_workspace_option(institution, *, role: str | None = None, eligible: bool = True) -> dict[str, Any]:
    return {
        **institution.to_dict(),
        "role": role,
        "eligible": bool(eligible),
    }


def _list_workspace_institution_candidates(user: User, session_row: DBSession | None = None) -> list[dict[str, Any]]:
    if is_platform_moderator_or_admin(user):
        institution_rows = Institution.query.order_by(Institution.name.asc()).all()
        return [_serialize_institution_workspace_option(institution) for institution in institution_rows]

    candidates = [
        _serialize_institution_workspace_option(
            membership.institution,
            role=membership.role.value if membership.role else None,
        )
        for membership in institution_service.list_manageable_for_user(user.id, required_role="curator")
        if membership.institution
    ]
    if session_row and getattr(session_row, "institution", None):
        current_id = int(session_row.institution_id or 0)
        if current_id and not any(int(item["id"]) == current_id for item in candidates):
            membership = institution_service.get_membership(current_id, user.id)
            candidates.append(
                _serialize_institution_workspace_option(
                    session_row.institution,
                    role=membership.role.value if membership and membership.role else None,
                    eligible=bool(membership and institution_service.has_role(membership, "curator")),
                )
            )
    return candidates


def _resolve_workspace_preview_institution(
    session_row: DBSession,
    user: User,
    requested_institution_id: str | None,
):
    raw_value = requested_institution_id
    if raw_value in (None, ""):
        institution_id = session_row.institution_id
    else:
        try:
            institution_id = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValidationError("institution_id must be an integer") from exc

    if not institution_id:
        return None, None

    institution = institution_service.get_by_id(int(institution_id))
    if is_platform_moderator_or_admin(user):
        return int(institution_id), institution
    if int(session_row.user_id) == int(user.id) and int(session_row.institution_id or 0) == int(institution_id):
        return int(institution_id), institution

    membership = institution_service.get_membership(int(institution_id), int(user.id))
    if not institution_service.has_role(membership, "curator"):
        raise SecurityError("Institution curator access required to manage shared sessions")
    return int(institution_id), institution


def _list_publishing_user_candidates(
    session_row: DBSession,
    preview_institution_id: int | None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_user_ids: set[int] = set()
    current_publishing_user_id = int(getattr(session_row, "publishing_user_id", None) or getattr(session_row, "user_id", 0) or 0)

    if preview_institution_id:
        memberships = institution_service.list_members(int(preview_institution_id))
        for membership in memberships:
            if not membership.user:
                continue
            seen_user_ids.add(int(membership.user.id))
            candidates.append(
                _serialize_user_workspace_option(
                    membership.user,
                    institution_role=membership.role.value if membership.role else None,
                    is_current=int(membership.user.id) == current_publishing_user_id,
                )
            )
    else:
        owner = db.session.get(User, int(session_row.user_id))
        if owner:
            seen_user_ids.add(int(owner.id))
            candidates.append(
                _serialize_user_workspace_option(
                    owner,
                    institution_role="owner",
                    is_current=int(owner.id) == current_publishing_user_id,
                )
            )

    current_publishing_user = db.session.get(User, current_publishing_user_id) if current_publishing_user_id else None
    if current_publishing_user and int(current_publishing_user.id) not in seen_user_ids:
        candidates.insert(
            0,
            _serialize_user_workspace_option(
                current_publishing_user,
                institution_role=None,
                eligible=False if preview_institution_id else True,
                reason="Current publishing user is not available for the selected workspace."
                if preview_institution_id
                else None,
                is_current=True,
            ),
        )
    return candidates


def _build_session_workspace_payload(
    session_row: DBSession,
    user: User,
    *,
    requested_institution_id: str | None = None,
) -> dict[str, Any]:
    preview_institution_id, preview_institution = _resolve_workspace_preview_institution(
        session_row,
        user,
        requested_institution_id,
    )
    session_payload = _serialize_session_context(session_row, acting_user=user)
    owner_user = db.session.get(User, int(session_row.user_id))
    current_publishing_user = db.session.get(
        User,
        int(getattr(session_row, "publishing_user_id", None) or getattr(session_row, "user_id", 0) or 0),
    )
    return {
        "session": session_payload,
        "owner_user": _serialize_user_workspace_option(owner_user, institution_role="owner") if owner_user else None,
        "current_publishing_user": _serialize_user_workspace_option(
            current_publishing_user,
            is_current=True,
        )
        if current_publishing_user
        else None,
        "current_workspace": {
            "institution_id": session_row.institution_id,
            "sharing_scope": session_row.sharing_scope,
            "credential_preference": session_row.credential_preference,
            "publishing_user_id": session_row.publishing_user_id,
            "default_zenodo_environment": session_row.default_zenodo_environment,
            "use_institution_default_communities": bool(session_row.use_institution_default_communities),
        },
        "preview_institution_id": preview_institution_id,
        "preview_institution": preview_institution.to_dict() if preview_institution else None,
        "target_institutions": _list_workspace_institution_candidates(user, session_row=session_row),
        "publishing_user_candidates": _list_publishing_user_candidates(session_row, preview_institution_id),
        "options": {
            "sharing_scopes": [
                {"value": "private", "label": "Private"},
                {"value": "institution", "label": "Institution"},
            ],
            "credential_preferences": [
                {"value": "user", "label": "User"},
                {"value": "institution", "label": "Institution"},
            ],
            "default_zenodo_environments": [
                {"value": "sandbox", "label": "Sandbox"},
                {"value": "production", "label": "Production"},
            ],
        },
        "hdpc_download_policy": _build_hdpc_download_policy(session_row, user),
        "shared_hdpc_download_policy": _build_shared_hdpc_download_policy(session_row, user),
    }


def _serialize_session_context(
    session_row: DBSession,
    metadata_fields: dict[str, Any] | None = None,
    *,
    acting_user: User | None = None,
    publishing_context: dict[str, Any] | None = None,
    file_count: int | None = None,
    display_name: str | None = None,
    institution_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    publishing_context = publishing_context or publishing_context_service.describe_session(session_row)
    if institution_payload is None and getattr(session_row, "institution", None):
        institution_payload = session_row.institution.to_dict()
    acting_user = acting_user or get_current_user_from_jwt()
    session_state, workflow_phase, upload_stage = _resolve_session_state(session_row, metadata_fields)
    payload = {
        "id": session_row.id,
        "name": display_name or f"Session {session_row.id}",
        "status": session_state,
        "legacy_status": session_row.status,
        "origin_type": str(getattr(session_row, "origin_type", None) or "workflow"),
        "access_mode": str(getattr(session_row, "access_mode", None) or "full"),
        "origin_metadata": _session_origin_metadata(session_row),
        "created_at": session_row.created_at.isoformat() if session_row.created_at else None,
        "updated_at": session_row.updated_at.isoformat() if session_row.updated_at else None,
        "file_count": int(file_count) if file_count is not None else len(session_row.files),
        "timings": _parse_json(session_row.timings, {}),
        "workspace": {
            "type": publishing_context.get("workspace_type"),
            "sharing_scope": publishing_context.get("sharing_scope"),
            "institution_id": publishing_context.get("institution_id"),
            "institution": institution_payload,
        },
        "publishing_context": publishing_context,
        "owner_user_id": session_row.user_id,
        "publishing_user_id": session_row.publishing_user_id,
        "workflow_phase": workflow_phase,
        "upload_stage": upload_stage,
        "permissions": build_session_permissions(session_row, acting_user) if acting_user else None,
        "hdpc_download_policy": _build_hdpc_download_policy(session_row, acting_user) if acting_user else None,
        "shared_hdpc_download_policy": _build_shared_hdpc_download_policy(session_row, acting_user)
        if acting_user
        else None,
    }
    if metadata_fields is not None:
        payload["workflow_hint"] = _build_session_workflow_hint(session_row, metadata_fields)
    return payload


def _get_session_file_counts(session_ids: list[int]) -> dict[int, int]:
    normalized_ids = [int(item) for item in session_ids or [] if item]
    if not normalized_ids:
        return {}

    counts = {session_id: 0 for session_id in normalized_ids}
    rows = (
        db.session.query(File.session_id, func.count(File.id))
        .filter(File.session_id.in_(normalized_ids))
        .group_by(File.session_id)
        .all()
    )
    for session_id, file_count in rows:
        counts[int(session_id)] = int(file_count or 0)
    return counts


def _latest_submission_status(session_row: DBSession) -> str | None:
    submissions = list(getattr(session_row, "submissions", []) or [])
    if not submissions:
        return None

    latest = max(
        submissions,
        key=lambda item: (
            item.created_at or datetime.min.replace(tzinfo=None),
            int(item.id or 0),
        ),
    )
    status = str(getattr(latest, "status", None) or "").strip().lower()
    return status or None


def _resolve_session_state(
    session_row: DBSession,
    metadata_fields: dict[str, Any] | None = None,
) -> tuple[str, str | None, str | None]:
    metadata_fields = metadata_fields or {}
    workflow_state = _parse_workflow_state(metadata_fields.get(WORKFLOW_STATE_FIELD))
    upload_progress = _parse_json(metadata_fields.get(UPLOAD_PROGRESS_FIELD), {})
    upload_stage = None
    if isinstance(upload_progress, dict):
        upload_stage = str(upload_progress.get("current_stage") or "").strip().lower() or None

    workflow_phase = str(workflow_state.get("phase") or "").strip().lower() or None
    if not workflow_phase:
        submission_status = _latest_submission_status(session_row)
        if submission_status == "processing":
            workflow_phase = "processing"
        elif submission_status in {"completed", "failed"}:
            workflow_phase = submission_status

    session_state = normalize_session_state(
        session_row.status,
        workflow_phase=workflow_phase,
        upload_stage=upload_stage,
    )
    return session_state, workflow_phase, upload_stage


def _normalize_session_workspace_options(
    *,
    user: User,
    payload: dict[str, Any],
    allow_publishing_user_override: bool = False,
    existing_session: DBSession | None = None,
) -> dict[str, Any]:
    raw_institution_id = payload.get("institution_id")
    institution_id = None
    institution = None
    if raw_institution_id not in (None, ""):
        try:
            institution_id = int(raw_institution_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError("institution_id must be an integer") from exc
        institution = institution_service.get_by_id(institution_id)
        if user.role.value not in {"moderator", "admin"}:
            membership = institution_service.get_membership(institution_id, user.id)
            if not institution_service.has_role(membership, "curator"):
                raise SecurityError("Institution curator access required to create or update shared sessions")

    default_scope = "institution" if institution_id else "private"
    sharing_scope = _normalize_choice(
        payload.get("sharing_scope"),
        allowed=VALID_SHARING_SCOPES,
        default=default_scope,
        field_name="sharing_scope",
    )
    if not institution_id:
        sharing_scope = "private"

    credential_preference = _normalize_choice(
        payload.get("credential_preference"),
        allowed=VALID_CREDENTIAL_PREFERENCES,
        default="institution" if institution_id else "user",
        field_name="credential_preference",
    )
    if not institution_id and credential_preference == "institution":
        raise ValidationError("credential_preference='institution' requires institution_id")

    default_zenodo_environment = _normalize_choice(
        payload.get("default_zenodo_environment"),
        allowed={"sandbox", "production"},
        default="sandbox",
        field_name="default_zenodo_environment",
    )

    use_institution_default_communities = _coerce_bool(payload.get("use_institution_default_communities"))
    if use_institution_default_communities is None:
        use_institution_default_communities = bool(institution_id)
    if not institution_id:
        use_institution_default_communities = False

    publishing_user_id = existing_session.publishing_user_id if existing_session else user.id
    raw_publishing_user_id = payload.get("publishing_user_id")
    if raw_publishing_user_id not in (None, ""):
        if not allow_publishing_user_override:
            raise ValidationError("publishing_user_id cannot be set in this request")
        try:
            publishing_user_id = int(raw_publishing_user_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError("publishing_user_id must be an integer") from exc
        publishing_user = db.session.get(User, publishing_user_id)
        if not publishing_user:
            raise ValidationError("publishing_user_id must reference an existing user")
        if institution_id and publishing_user_id != user.id:
            membership = institution_service.get_membership(institution_id, publishing_user_id)
            if not membership:
                raise ValidationError("publishing_user_id must belong to the selected institution")
        if not institution_id and publishing_user_id != (existing_session.user_id if existing_session else user.id):
            raise ValidationError("Personal sessions can only publish using the session owner")

    return {
        "institution_id": institution_id,
        "institution": institution,
        "sharing_scope": sharing_scope,
        "credential_preference": credential_preference,
        "publishing_user_id": publishing_user_id,
        "default_zenodo_environment": default_zenodo_environment,
        "use_institution_default_communities": bool(use_institution_default_communities),
    }


def _apply_session_workspace_options(session_row: DBSession, options: dict[str, Any]) -> None:
    session_row.institution_id = options.get("institution_id")
    session_row.sharing_scope = options.get("sharing_scope") or "private"
    session_row.credential_preference = options.get("credential_preference") or "user"
    session_row.publishing_user_id = options.get("publishing_user_id") or session_row.user_id
    session_row.default_zenodo_environment = options.get("default_zenodo_environment") or "sandbox"
    session_row.use_institution_default_communities = bool(options.get("use_institution_default_communities"))


def _normalize_string_list(values, *, max_items: int = 5000, max_length: int = 1000) -> list[str]:
    if not isinstance(values, list):
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        if not isinstance(raw_value, str):
            continue
        value = raw_value.strip()
        if not value or len(value) > max_length or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
        if len(normalized) >= max_items:
            break
    return normalized


def _list_local_subdirectories(input_dir: str, *, max_entries: int = 5000) -> list[dict[str, object]]:
    if not input_dir or not os.path.isdir(input_dir):
        return []

    directory_meta: dict[str, dict[str, object]] = {}
    walk_order: list[str] = []

    for root, dirs, files in os.walk(input_dir, topdown=True):
        dirs[:] = [
            name
            for name in dirs
            if name
            and not name.startswith(".")
            and name not in {"__pycache__", ".ipynb_checkpoints"}
        ]
        direct_file_count = sum(
            1
            for file_name in files
            if file_name
            and not file_name.startswith(".")
            and os.path.splitext(file_name)[1].lower() not in MSF_ALLOWED_EXTENSIONS
        )
        relative_path = os.path.relpath(root, input_dir)
        directory_meta[root] = {
            "name": os.path.basename(root),
            "relative_path": "" if relative_path == "." else relative_path,
            "full_path": root,
            "direct_file_count": int(direct_file_count),
            "file_count": int(direct_file_count),
            "depth": 0 if relative_path == "." else relative_path.count(os.sep) + 1,
            "children": [os.path.join(root, child) for child in dirs],
        }
        walk_order.append(root)

    for root in reversed(walk_order):
        node = directory_meta[root]
        node["file_count"] = int(node["direct_file_count"]) + sum(
            int(directory_meta[child]["file_count"])
            for child in node["children"]
            if child in directory_meta
        )

    entries = [
        {
            "name": str(item["name"]),
            "relative_path": str(item["relative_path"]),
            "full_path": str(item["full_path"]),
            "file_count": int(item["file_count"]),
            "direct_file_count": int(item["direct_file_count"]),
            "depth": int(item["depth"]),
        }
        for item in directory_meta.values()
        if item["relative_path"]
    ]
    entries.sort(key=lambda item: item["relative_path"].lower())
    return entries[:max_entries]


def _normalize_workflow_state_payload(payload: dict | None, existing_state: dict | None = None) -> dict:
    base_state = existing_state if isinstance(existing_state, dict) else {}
    raw_payload = payload if isinstance(payload, dict) else {}

    phase_candidate = raw_payload.get("phase", base_state.get("phase", "upload"))
    if not isinstance(phase_candidate, str) or phase_candidate not in WORKFLOW_PHASE_TO_STEP:
        phase_candidate = base_state.get("phase") if isinstance(base_state.get("phase"), str) else "upload"
    phase = phase_candidate if phase_candidate in WORKFLOW_PHASE_TO_STEP else "upload"

    current_step = raw_payload.get("current_step")
    if current_step is None and phase != base_state.get("phase"):
        current_step = WORKFLOW_PHASE_TO_STEP.get(phase, 1)
    elif current_step is None:
        current_step = base_state.get("current_step")

    if not isinstance(current_step, int) or current_step < 1 or current_step > 7:
        current_step = WORKFLOW_PHASE_TO_STEP.get(phase, 1)

    is_batch_mode = _coerce_bool(raw_payload.get("is_batch_mode"))
    if is_batch_mode is None:
        is_batch_mode = _coerce_bool(base_state.get("is_batch_mode"))
    is_batch_mode = bool(is_batch_mode)

    msf_path = raw_payload.get("msf_path", base_state.get("msf_path"))
    if not isinstance(msf_path, str) or not msf_path.strip():
        msf_path = None
    else:
        msf_path = msf_path.strip()

    selected_file_keys = _normalize_string_list(
        raw_payload.get("selected_file_keys", base_state.get("selected_file_keys", []))
    )

    raw_pipeline = raw_payload.get("selected_pipeline", base_state.get("selected_pipeline"))
    selected_pipeline = None
    if isinstance(raw_pipeline, dict):
        identifier = raw_pipeline.get("identifier") or raw_pipeline.get("id")
        name = raw_pipeline.get("name")
        description = raw_pipeline.get("description")
        if isinstance(identifier, str) and identifier.strip():
            selected_pipeline = {
                "identifier": identifier.strip(),
                "name": name.strip() if isinstance(name, str) and name.strip() else None,
                "description": description.strip() if isinstance(description, str) and description.strip() else None,
            }

    msf_mapping = raw_payload.get("msf_mapping", base_state.get("msf_mapping", {}))
    if not isinstance(msf_mapping, dict):
        msf_mapping = {}

    lod_minimum_viable = raw_payload.get("lod_minimum_viable", base_state.get("lod_minimum_viable", {}))
    if not isinstance(lod_minimum_viable, dict):
        lod_minimum_viable = {}
    lod_minimum_viable = {
        "edm": lod_minimum_viable.get("edm") is not False,
        "iiif": lod_minimum_viable.get("iiif") is not False,
        "mets": lod_minimum_viable.get("mets") is not False,
    }

    submission_id = raw_payload.get("submission_id", base_state.get("submission_id"))
    if isinstance(submission_id, bool):
        submission_id = None
    elif isinstance(submission_id, str):
        submission_id = submission_id.strip()
        if submission_id.isdigit():
            submission_id = int(submission_id)
        else:
            submission_id = None
    elif not isinstance(submission_id, int) or submission_id <= 0:
        submission_id = None

    pipeline_run_id = raw_payload.get("pipeline_run_id", base_state.get("pipeline_run_id"))
    if isinstance(pipeline_run_id, bool):
        pipeline_run_id = None
    elif pipeline_run_id is None:
        pipeline_run_id = None
    else:
        pipeline_run_id = str(pipeline_run_id).strip() or None

    return {
        "phase": phase,
        "current_step": current_step,
        "is_batch_mode": is_batch_mode,
        "selected_file_keys": selected_file_keys,
        "selected_pipeline": selected_pipeline,
        "msf_path": msf_path,
        "msf_mapping": msf_mapping,
        "lod_minimum_viable": lod_minimum_viable,
        "submission_id": submission_id,
        "pipeline_run_id": pipeline_run_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _parse_workflow_state(raw_value) -> dict:
    parsed = _parse_json(raw_value, {})
    if not isinstance(parsed, dict):
        return _normalize_workflow_state_payload({})
    return _normalize_workflow_state_payload(parsed)


def _build_msf_parse_options(payload: dict, form_data) -> dict:
    options = {}
    use_first = payload.get("use_first_row_as_header")
    if use_first is None:
        use_first = form_data.get("use_first_row_as_header")
    coerced = _coerce_bool(use_first)
    if coerced is not None:
        options["use_first_row_as_header"] = coerced

    sheet_name = payload.get("sheet_name")
    if sheet_name is None:
        sheet_name = form_data.get("sheet_name")
    if sheet_name:
        options["sheet_name"] = str(sheet_name).strip()

    delimiter = payload.get("delimiter")
    if delimiter is None:
        delimiter = form_data.get("delimiter")
    if delimiter:
        options["delimiter"] = str(delimiter)

    return options


def _derive_nested_step_outcome(step_data: dict) -> str | None:
    has_success = False
    has_failure = False

    results = step_data.get("results")
    if isinstance(results, dict):
        for value in results.values():
            if not isinstance(value, dict):
                continue
            outcome = value.get("success")
            if outcome is True:
                has_success = True
            elif outcome is False:
                has_failure = True

    processed_count = step_data.get("processed_count")
    success_count = step_data.get("success_count")
    if isinstance(processed_count, int) and processed_count > 0 and isinstance(success_count, int):
        if success_count <= 0:
            has_failure = True
        elif success_count < processed_count:
            has_success = True
            has_failure = True
        else:
            has_success = True

    if has_success and has_failure:
        return "partial"
    if has_failure:
        return "failed"
    if has_success:
        return "completed"
    return None


def _extract_processing_step_status(detail: dict, step_key: str) -> str | None:
    if not isinstance(detail, dict):
        return None
    step_data = detail.get(step_key)
    if not isinstance(step_data, dict):
        return None

    raw_status = step_data.get("status")
    if isinstance(raw_status, str) and raw_status.strip():
        normalized = raw_status.strip().lower()
        if normalized.startswith("skipped"):
            return normalized
        if normalized in {"failed", "error"}:
            return "failed"
        if normalized in {"generated", "completed", "success"}:
            return "completed"
        return normalized

    nested_outcome = _derive_nested_step_outcome(step_data)
    if nested_outcome:
        return nested_outcome

    success_flag = step_data.get("success")
    if success_flag is True:
        return "completed"
    if success_flag is False:
        return "failed"
    return None


def _build_local_scan_file_list(directory_path: str) -> list[str]:
    files: list[str] = []
    for root, _, names in os.walk(directory_path):
        for name in names:
            if name.startswith("."):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext in {".xlsx", ".xls", ".csv"}:
                continue
            files.append(name)
    return files


def _normalize_submit_token(raw_token) -> str | None:
    if raw_token is None:
        return None
    token = str(raw_token).strip()
    if not token:
        return None
    if len(token) > 128:
        raise ValidationError("submit_token is too long")
    if not re.fullmatch(r"[A-Za-z0-9._:-]+", token):
        raise ValidationError("submit_token contains invalid characters")
    return token


def _get_upload_submission_context(user_id: int, submit_token: str) -> dict | None:
    if not submit_token:
        return None

    token_row = (
        db.session.query(UserMetadata, DBSession)
        .join(DBSession, DBSession.id == UserMetadata.session_id)
        .filter(
            DBSession.user_id == user_id,
            UserMetadata.field_name == UPLOAD_SUBMIT_TOKEN_FIELD,
            UserMetadata.field_value == submit_token,
        )
        .order_by(UserMetadata.created_at.desc())
        .first()
    )
    if not token_row:
        return None

    _, session_row = token_row
    task_meta = (
        UserMetadata.query.filter_by(session_id=session_row.id, field_name=UPLOAD_TASK_ID_FIELD)
        .order_by(UserMetadata.created_at.desc())
        .first()
    )
    task_id = (task_meta.field_value or "").strip() if task_meta and task_meta.field_value else None
    if task_id == "":
        task_id = None

    return {
        "submit_token": submit_token,
        "session_id": session_row.id,
        "task_id": task_id,
        "session_status": normalize_session_state(session_row.status),
        "legacy_session_status": session_row.status,
        "created_at": session_row.created_at.isoformat() if session_row.created_at else None,
        "updated_at": session_row.updated_at.isoformat() if session_row.updated_at else None,
    }


def _upsert_session_metadata(session_id: int, field_name: str, field_value: str) -> None:
    record = UserMetadata.query.filter_by(session_id=session_id, field_name=field_name).first()
    if record:
        record.field_value = field_value
    else:
        db.session.add(UserMetadata(session_id=session_id, field_name=field_name, field_value=field_value))


def _get_session_metadata_map(session_ids: list[int], field_names: set[str]) -> dict[int, dict[str, str]]:
    if not session_ids or not field_names:
        return {}

    rows = (
        UserMetadata.query.filter(
            UserMetadata.session_id.in_(session_ids),
            UserMetadata.field_name.in_(list(field_names)),
        )
        .order_by(UserMetadata.created_at.desc())
        .all()
    )

    metadata_map: dict[int, dict[str, str]] = {}
    for row in rows:
        session_fields = metadata_map.setdefault(int(row.session_id), {})
        session_fields.setdefault(row.field_name, row.field_value or "")
    return metadata_map


def _record_resolution_visible_session_ids(user: User | None) -> set[int]:
    if not user:
        return set()
    if is_platform_moderator_or_admin(user):
        return {session_row.id for session_row in DBSession.query.all()}
    return {session_row.id for session_row in get_accessible_sessions(user, scope="all")}


def _sanitize_record_resolution_candidate(candidate: dict[str, Any], visible_session_ids: set[int]) -> dict[str, Any]:
    matched_records = candidate.get("matched_records") or []
    visible_matches = [
        item
        for item in matched_records
        if isinstance(item, dict) and int(item.get("session_id") or 0) in visible_session_ids
    ]
    hidden_count = max(len(matched_records) - len(visible_matches), 0)

    sanitized = dict(candidate)
    sanitized["matched_records"] = visible_matches
    sanitized["visible_matched_record_count"] = len(visible_matches)
    sanitized["hidden_matched_record_count"] = hidden_count

    recommended_target = sanitized.get("recommended_target")
    if isinstance(recommended_target, dict) and int(recommended_target.get("session_id") or 0) not in visible_session_ids:
        sanitized["recommended_target"] = None

    selected_target = sanitized.get("selected_target")
    if isinstance(selected_target, dict) and int(selected_target.get("session_id") or 0) not in visible_session_ids:
        sanitized["selected_target"] = None

    allowed_actions = [
        action
        for action in (sanitized.get("allowed_actions") or [])
        if action != "create_version" or sanitized.get("recommended_target") is not None
    ]
    sanitized["allowed_actions"] = allowed_actions

    if sanitized.get("recommended_action") == "create_version" and sanitized.get("recommended_target") is None:
        sanitized["recommended_action"] = "skip"
        if "skip" not in sanitized["allowed_actions"]:
            sanitized["allowed_actions"] = ["skip", *sanitized["allowed_actions"]]
        sanitized["explanation"] = (
            "A matching lineage exists outside your visible scope. Contact an administrator if you need to version "
            "against that record."
        )

    selected_action = sanitized.get("selected_action")
    if selected_action == "create_version" and sanitized.get("selected_target") is None:
        sanitized["selected_action"] = sanitized.get("recommended_action")
        sanitized["resolved"] = False

    return sanitized


def _sanitize_record_resolution_payload(payload: dict[str, Any], user: User | None) -> dict[str, Any]:
    visible_session_ids = _record_resolution_visible_session_ids(user)
    sanitized = dict(payload)
    sanitized["candidates"] = [
        _sanitize_record_resolution_candidate(item, visible_session_ids)
        for item in (payload.get("candidates") or [])
        if isinstance(item, dict)
    ]
    summary = dict(sanitized.get("summary") or {})
    resolved_count = sum(
        1
        for item in sanitized["candidates"]
        if bool(item.get("resolved")) or str(item.get("severity") or "clean") == "clean"
    )
    summary["resolved_count"] = resolved_count
    summary["unresolved_count"] = max(len(sanitized["candidates"]) - resolved_count, 0)
    summary["can_continue"] = summary["unresolved_count"] == 0
    sanitized["summary"] = summary
    return sanitized


def _get_upload_file_counts(session_ids: list[int]) -> dict[int, dict[str, int]]:
    if not session_ids:
        return {}

    from sqlalchemy import func
    from database.models import File as DBFile

    rows = (
        db.session.query(DBFile.session_id, DBFile.status, func.count(DBFile.id))
        .filter(DBFile.session_id.in_(session_ids))
        .group_by(DBFile.session_id, DBFile.status)
        .all()
    )

    counts_by_session: dict[int, dict[str, int]] = {}
    for session_id, status, count in rows:
        session_counts = counts_by_session.setdefault(int(session_id), {})
        session_counts[str(status or "unknown")] = int(count or 0)
    return counts_by_session


def _get_batch_file_metadata_map(session_id: int) -> dict[str, dict]:
    rows = BatchFileMetadata.query.filter_by(session_id=session_id).all()
    metadata_map: dict[str, dict] = {}
    for row in rows:
        metadata = _parse_json(row.metadata_json, {})
        if isinstance(metadata, dict):
            metadata_map[row.filename] = metadata
    return metadata_map


def _build_session_workflow_hint(session_row: DBSession, metadata_fields: dict[str, str]) -> dict:
    msf_profile = _parse_json(metadata_fields.get("msf_profile"), {})
    workflow_state = _parse_workflow_state(metadata_fields.get(WORKFLOW_STATE_FIELD))
    task_id = (metadata_fields.get(UPLOAD_TASK_ID_FIELD) or "").strip() or None
    session_state, _, _ = _resolve_session_state(session_row, metadata_fields)
    storage_mode = (
        metadata_fields.get(UPLOAD_STORAGE_MODE_FIELD)
        or (msf_profile.get("storage_mode") if isinstance(msf_profile, dict) else None)
    )
    scan_started = bool((msf_profile or {}).get("scan_started"))
    requires_msf_repair = bool(
        storage_mode == "local"
        and not scan_started
        and not task_id
        and len(session_row.files) == 0
        and str((msf_profile or {}).get("file_path") or "").strip()
    )

    hint = {
        "requires_msf_repair": requires_msf_repair,
        "storage_mode": storage_mode,
        "target_directory": (msf_profile or {}).get("directory_root"),
        "msf_path": (msf_profile or {}).get("source_file_path") or (msf_profile or {}).get("file_path"),
        "scan_started": scan_started,
        "is_explorer_only": str(getattr(session_row, "access_mode", None) or "full").strip().lower() == "explorer_only",
        "can_resume_workflow": False,
        "resume_phase": None,
        "resume_step": None,
        "resume_route": None,
        "resume_label": None,
        "submission_id": workflow_state.get("submission_id"),
        "pipeline_run_id": workflow_state.get("pipeline_run_id"),
        "session_status": session_state,
    }

    if hint["is_explorer_only"]:
        return hint

    if requires_msf_repair:
        hint.update(
            {
                "can_resume_workflow": True,
                "resume_phase": "msf_analysis",
                "resume_step": WORKFLOW_PHASE_TO_STEP["msf_analysis"],
                "resume_route": WORKFLOW_PHASE_TO_ROUTE["msf_analysis"],
                "resume_label": WORKFLOW_PHASE_TO_LABEL["msf_analysis"],
            }
        )
        return hint

    phase = workflow_state.get("phase")
    if (
        isinstance(phase, str)
        and phase in WORKFLOW_PHASE_TO_ROUTE
        and phase not in TERMINAL_WORKFLOW_PHASES
        and session_state not in {"completed", "failed"}
    ):
        hint.update(
            {
                "can_resume_workflow": True,
                "resume_phase": phase,
                "resume_step": workflow_state.get("current_step") or WORKFLOW_PHASE_TO_STEP.get(phase),
                "resume_route": WORKFLOW_PHASE_TO_ROUTE.get(phase),
                "resume_label": WORKFLOW_PHASE_TO_LABEL.get(phase, "Resume Workflow"),
            }
        )

    return hint


def _normalize_upload_progress_payload(session_row: DBSession, metadata_fields: dict[str, str], file_counts: dict[str, int]) -> dict:
    progress = _parse_json(metadata_fields.get(UPLOAD_PROGRESS_FIELD), {})
    if not isinstance(progress, dict):
        progress = {}
    msf_profile = _parse_json(metadata_fields.get("msf_profile"), {})
    session_state, _, _ = _resolve_session_state(session_row, metadata_fields)

    uploaded = int(file_counts.get("uploaded", 0))
    failed = int(file_counts.get("failed", 0))
    pending = int(file_counts.get("pending", 0))
    actual_total = uploaded + failed + pending
    reported_total = int(progress.get("total_files", 0) or 0)
    total_files = max(actual_total, reported_total)
    processed_count = max(int(progress.get("processed_count", 0) or 0), uploaded + failed)
    failed_count = max(int(progress.get("failed_count", 0) or 0), failed)
    pending_count = max(total_files - processed_count, pending)

    current_stage = str(progress.get("current_stage") or "queued")
    if (
        not progress
        and isinstance(msf_profile, dict)
        and str(msf_profile.get("storage_mode") or "").strip().lower() == "local"
        and not _coerce_bool(msf_profile.get("scan_started"))
        and not metadata_fields.get(UPLOAD_TASK_ID_FIELD)
    ):
        current_stage = "awaiting_scan_start"
    if session_state == "failed":
        current_stage = "failed"
    elif (
        session_state in {"scanned", "submitting", "completed"}
        and current_stage not in {"completed", "failed", "awaiting_scan_start"}
        and total_files > 0
        and pending_count == 0
        and processed_count >= total_files
    ):
        current_stage = "completed"

    status_message = str(progress.get("status_message") or "").strip()
    if not status_message:
        if current_stage == "awaiting_scan_start":
            status_message = "MSF repair is available. Start the local scan after reviewing or applying fixes."
        elif current_stage == "completed":
            status_message = "Upload scan and metadata registration completed."
        elif current_stage == "failed":
            status_message = "Upload scan failed."
        else:
            status_message = "Upload scan and metadata registration in progress."

    percent = float(progress.get("percent", 0) or 0)
    if total_files > 0:
        percent = round(min(100.0, (processed_count / total_files) * 100), 1)
    elif current_stage == "completed":
        percent = 100.0

    return {
        "current_stage": current_stage,
        "status_message": status_message,
        "current_file_name": progress.get("current_file_name"),
        "current_index": int(progress.get("current_index", processed_count) or 0),
        "total_files": total_files,
        "processed_count": processed_count,
        "uploaded_count": uploaded,
        "failed_count": failed_count,
        "pending_count": pending_count,
        "percent": percent,
        "matched_files": int(progress.get("matched_files", reported_total) or 0),
        "warning_message": progress.get("warning_message"),
        "updated_at": progress.get("updated_at") or (session_row.updated_at.isoformat() if session_row.updated_at else None),
        "task_id": metadata_fields.get(UPLOAD_TASK_ID_FIELD) or None,
        "worker_group_id": metadata_fields.get(UPLOAD_WORKER_GROUP_ID_FIELD) or None,
        "storage_mode": metadata_fields.get(UPLOAD_STORAGE_MODE_FIELD) or None,
        "session_status": session_state,
        "legacy_session_status": session_row.status,
        "workflow_file_counts": normalize_upload_file_counts(file_counts),
    }


def _build_upload_operation_payload(
    session_row: DBSession,
    *,
    metadata_fields: dict[str, str] | None = None,
    file_counts: dict[str, int] | None = None,
    user_email: str | None = None,
    session_context: dict[str, Any] | None = None,
) -> dict:
    metadata_fields = metadata_fields or {}
    file_counts = file_counts or {}
    progress = _normalize_upload_progress_payload(session_row, metadata_fields, file_counts)
    session_context = session_context or _serialize_session_context(session_row, metadata_fields)
    workflow_hint = _build_session_workflow_hint(session_row, metadata_fields)

    payload = {
        "session_id": session_row.id,
        "submit_token": metadata_fields.get(UPLOAD_SUBMIT_TOKEN_FIELD) or None,
        "task_id": metadata_fields.get(UPLOAD_TASK_ID_FIELD) or None,
        "worker_group_id": metadata_fields.get(UPLOAD_WORKER_GROUP_ID_FIELD) or None,
        "status": session_context.get("status") or normalize_session_state(session_row.status),
        "legacy_status": session_row.status,
        "created_at": session_row.created_at.isoformat() if session_row.created_at else None,
        "updated_at": session_row.updated_at.isoformat() if session_row.updated_at else None,
        "session_dir": session_row.session_dir,
        "hdpc_path": session_row.hdpc_path,
        "storage_mode": metadata_fields.get(UPLOAD_STORAGE_MODE_FIELD)
        or (_parse_json(metadata_fields.get("msf_profile"), {}).get("storage_mode") if metadata_fields.get("msf_profile") else None),
        "progress": progress,
        "file_counts": {
            "uploaded": int(file_counts.get("uploaded", 0)),
            "failed": int(file_counts.get("failed", 0)),
            "pending": int(file_counts.get("pending", 0)),
            "total": int(file_counts.get("uploaded", 0)) + int(file_counts.get("failed", 0)) + int(file_counts.get("pending", 0)),
        },
        "workspace": session_context.get("workspace"),
        "publishing_context": session_context.get("publishing_context"),
        "workflow_hint": workflow_hint,
        "is_running": (session_context.get("status") or normalize_session_state(session_row.status)) == "queued"
        or progress["current_stage"] in RUNNING_UPLOAD_STAGES,
    }
    if user_email:
        payload["user_email"] = user_email
    return payload


def _build_upload_recovery_payload(context: dict, include_task_state: bool = False) -> dict:
    payload = {
        "submit_token": context.get("submit_token"),
        "session_id": context.get("session_id"),
        "task_id": context.get("task_id"),
        "session_status": context.get("session_status"),
        "legacy_session_status": context.get("legacy_session_status"),
        "created_at": context.get("created_at"),
        "updated_at": context.get("updated_at"),
        "reused": True,
    }
    if include_task_state and context.get("task_id"):
        try:
            from celery_app import celery

            task = celery.AsyncResult(context["task_id"])
            payload["task_state"] = task.state
        except Exception:
            payload["task_state"] = None
    return payload


def _is_moderator_or_admin(user_id: int) -> bool:
    user = db.session.get(User, user_id)
    if not user or not user.role:
        return False
    return user.role.value in ("moderator", "admin")


def _resolve_existing_hdpc_path(raw_path: str) -> str | None:
    if not raw_path:
        return None

    candidates = [raw_path]
    project_service = getattr(current_app, "project_service", None)
    if project_service:
        try:
            translated = project_service._translate_path(raw_path)
            if translated and translated not in candidates:
                candidates.append(translated)
        except Exception:
            pass

    shared_base = os.environ.get("SHARED_SESSION_PATH")
    if shared_base and raw_path.startswith("/shared/sessions"):
        local_candidate = raw_path.replace("/shared/sessions", shared_base, 1)
        if local_candidate not in candidates:
            candidates.append(local_candidate)

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def _get_session_with_hdpc_access(session_id: int, user_id: int):
    session = db.session.get(DBSession, session_id)
    if not session:
        return None, None, APIResponse.not_found("Session not found")
    user = db.session.get(User, int(user_id))
    if not can_view_session(session, user):
        return None, None, APIResponse.not_found("Session not found")
    resolved_hdpc_path = _resolve_existing_hdpc_path(session.hdpc_path)
    if not resolved_hdpc_path:
        return session, None, APIResponse.error(
            "SOURCE_UNAVAILABLE",
            "Session project file (.hdpc) is not available on this backend instance.",
            503,
            details={"session_id": session_id, "source_state": "hdpc_unavailable"},
        )
    return session, resolved_hdpc_path, None


def _session_batch_task_payload_from_history(entry: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {
            "state": "PENDING",
            "status": "Pending...",
            "progress": {
                "total_items": 0,
                "processed": 0,
                "completed": 0,
                "skipped": 0,
                "failed": 0,
                "percent": 0,
            },
            "result": None,
            "error": None,
        }
    return {
        "state": entry.get("state") or "PENDING",
        "status": entry.get("status") or "Pending...",
        "progress": entry.get("progress") if isinstance(entry.get("progress"), dict) else None,
        "result": entry.get("result") if isinstance(entry.get("result"), dict) else None,
        "error": entry.get("error"),
    }


def _table_exists(cursor: sqlite3.Cursor, table_name: str) -> bool:
    row = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(cursor: sqlite3.Cursor, table_name: str) -> set[str]:
    if not _table_exists(cursor, table_name):
        return set()
    rows = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in rows}


def _normalize_record_status(raw_status: str, metadata_payload: dict) -> str:
    status = (raw_status or "").strip().lower()
    if status in {"draft", "published", "prepared", "preparation_failed", "discarded"}:
        return status
    if metadata_payload.get("submitted") is True:
        return "published"
    if metadata_payload.get("links"):
        return "draft"
    return "unknown"


def _normalize_path_signature(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = os.path.normpath(text).replace("\\", "/").lower()
    return f"path:{normalized}" if normalized else None


def _normalize_name_signature(value) -> str | None:
    if value is None:
        return None
    text = os.path.basename(str(value).strip())
    if not text:
        return None
    return f"name:{text.lower()}"


def _record_signature_candidates(*, source_file_id=None, source_file=None, file_items=None, detail=None) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(value) -> None:
        if not value or value in seen:
            return
        seen.add(value)
        candidates.append(value)

    if source_file_id is not None:
        _add(f"source_id:{int(source_file_id)}")

    source_file = source_file if isinstance(source_file, dict) else {}
    detail = detail if isinstance(detail, dict) else {}
    file_items = file_items if isinstance(file_items, list) else []

    for item in file_items:
        if not isinstance(item, dict):
            continue
        _add(_normalize_path_signature(item.get("absolute_path")))
        _add(_normalize_path_signature(item.get("mapped_file_path")))
        _add(_normalize_path_signature(item.get("relative_path")))
        _add(_normalize_name_signature(item.get("filename")))

    _add(_normalize_path_signature(source_file.get("absolute_path")))
    _add(_normalize_path_signature(source_file.get("relative_path")))
    _add(_normalize_name_signature(source_file.get("filename")))
    _add(_normalize_path_signature(detail.get("file_path")))
    _add(_normalize_name_signature(detail.get("file_path")))

    return candidates


def _is_image_filename(value) -> bool:
    if value is None:
        return False
    extension = os.path.splitext(os.path.basename(str(value)))[1].lower()
    return extension in THUMBNAIL_IMAGE_EXTENSIONS


def _is_3d_asset(source_file_name=None, source_file_path=None, files=None) -> bool:
    candidates = [source_file_name, source_file_path]
    for file_item in files or []:
        if not isinstance(file_item, dict):
            continue
        candidates.extend(
            [
                file_item.get("filename"),
                file_item.get("absolute_path"),
                file_item.get("mapped_file_path"),
            ]
        )
        mime_type = str(file_item.get("mime_type") or "").strip().lower()
        if any(mime_type.startswith(prefix) for prefix in THREE_D_MIME_PREFIXES):
            return True

    for candidate in candidates:
        if candidate is None:
            continue
        extension = os.path.splitext(os.path.basename(str(candidate)))[1].lower()
        if extension in THREE_D_FILE_EXTENSIONS:
            return True
    return False


def _discover_record_output_dir(session_dir: str, source_file_name: str) -> str | None:
    if not session_dir or not source_file_name:
        return None

    stem = os.path.splitext(os.path.basename(source_file_name))[0]
    if not stem:
        return None

    output_dir = os.path.join(session_dir, "outputs", stem)
    return output_dir if os.path.isdir(output_dir) else None


def _collect_output_directory_files(output_dir: str | None) -> list[str]:
    if not output_dir or not os.path.isdir(output_dir):
        return []

    discovered: list[str] = []
    for entry_name in sorted(os.listdir(output_dir)):
        entry_path = os.path.join(output_dir, entry_name)
        if os.path.isfile(entry_path):
            discovered.append(entry_path)
    return discovered


def _collect_unique_existing_paths(paths: list[str]) -> list[str]:
    unique_paths: list[str] = []
    seen: set[str] = set()
    for raw_path in paths or []:
        if not isinstance(raw_path, str):
            continue
        path = raw_path.strip()
        if not path or not os.path.isfile(path):
            continue
        normalized = os.path.normpath(path)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_paths.append(path)
    return unique_paths


def _collect_record_version_file_paths(session_row: DBSession, record: dict) -> list[str]:
    files = record.get("files") if isinstance(record, dict) else []
    candidate_paths: list[str] = []

    source_path = record.get("source_file_path") if isinstance(record, dict) else None
    if isinstance(source_path, str) and source_path.strip():
        candidate_paths.append(source_path)

    for file_item in files or []:
        if not isinstance(file_item, dict):
            continue
        for key in ("absolute_path", "mapped_file_path"):
            value = file_item.get(key)
            if isinstance(value, str) and value.strip():
                candidate_paths.append(value)

    output_dir = _discover_record_output_dir(getattr(session_row, "session_dir", None), record.get("source_file_name"))
    candidate_paths.extend(_collect_output_directory_files(output_dir))
    return _collect_unique_existing_paths(candidate_paths)


def _build_thumbnail_health(session_row: DBSession, record: dict, metadata_payload: dict) -> dict:
    files = record.get("files") if isinstance(record, dict) else []
    record_files = files if isinstance(files, list) else []
    output_dir = _discover_record_output_dir(getattr(session_row, "session_dir", None), record.get("source_file_name"))
    output_files = _collect_output_directory_files(output_dir)
    uploaded_files = metadata_payload.get("files") if isinstance(metadata_payload, dict) else []
    uploaded_files = uploaded_files if isinstance(uploaded_files, list) else []

    local_rendered_thumbnail_paths = [path for path in output_files if _is_image_filename(path)]
    linked_thumbnail_files = [
        file_item
        for file_item in record_files
        if _is_image_filename(file_item.get("filename") or file_item.get("absolute_path") or file_item.get("mapped_file_path"))
    ]
    uploaded_thumbnail_files = []
    for file_obj in uploaded_files:
        if not isinstance(file_obj, dict):
            continue
        filename = (
            file_obj.get("filename")
            or file_obj.get("key")
            or file_obj.get("name")
            or file_obj.get("id")
        )
        if _is_image_filename(filename):
            uploaded_thumbnail_files.append(filename)

    is_3d_record = _is_3d_asset(
        record.get("source_file_name"),
        record.get("source_file_path"),
        record_files,
    )
    zenodo_record_exists = str(record.get("record_status") or "").strip().lower() in {"draft", "published"}
    missing_uploaded_thumbnails = bool(is_3d_record and zenodo_record_exists and not uploaded_thumbnail_files)

    return {
        "is_3d_record": is_3d_record,
        "output_directory": output_dir,
        "local_rendered_thumbnail_count": len(local_rendered_thumbnail_paths),
        "linked_thumbnail_count": len(linked_thumbnail_files),
        "uploaded_thumbnail_count": len(uploaded_thumbnail_files),
        "local_rendered_thumbnails_present": bool(local_rendered_thumbnail_paths),
        "missing_uploaded_thumbnails": missing_uploaded_thumbnails,
        "can_create_new_version": bool(
            record.get("record_status") == "published"
            and record.get("concept_rec_id")
            and record.get("source_file_path")
            and record.get("zenodo_record_id")
        ),
        "can_repair_missing_thumbnails": bool(
            record.get("record_status") == "published"
            and record.get("concept_rec_id")
            and record.get("source_file_path")
            and local_rendered_thumbnail_paths
        ),
    }


def _serialize_submission_summary(latest_submission: Submission | None) -> dict[str, Any] | None:
    if not latest_submission:
        return None
    return {
        "id": latest_submission.id,
        "status": latest_submission.status,
        "pipeline_id": latest_submission.pipeline_id,
        "created_at": latest_submission.created_at.isoformat() if latest_submission.created_at else None,
        "completed_at": latest_submission.completed_at.isoformat() if latest_submission.completed_at else None,
    }


def _build_session_record_common_context(session_row: DBSession) -> dict[str, Any]:
    latest_submission = (
        Submission.query.filter_by(session_id=session_row.id).order_by(Submission.created_at.desc()).first()
    )
    submission_result = _parse_json(latest_submission.result, {}) if latest_submission else {}
    workflow_state_record = db.session.query(UserMetadata).filter_by(
        session_id=session_row.id,
        field_name=WORKFLOW_STATE_FIELD,
    ).first()
    workflow_state = _parse_workflow_state(workflow_state_record.field_value if workflow_state_record else None)
    selected_file_ids = {
        int(file_id)
        for file_id in (workflow_state.get("selected_file_keys") or [])
        if str(file_id).isdigit()
    }
    session_file_rows = File.query.filter_by(session_id=session_row.id).all()
    selected_file_signatures = set()
    for file_row in session_file_rows:
        if file_row.id not in selected_file_ids:
            continue
        selected_file_signatures.add(_normalize_path_signature(file_row.path))
        selected_file_signatures.add(_normalize_name_signature(file_row.filename))
    selected_file_signatures.discard(None)

    details_by_record: dict[str, dict[str, Any]] = {}
    processed_file_signatures = set()
    if isinstance(submission_result, dict):
        for detail in submission_result.get("details", []):
            if isinstance(detail, dict) and detail.get("record_id") is not None:
                details_by_record[str(detail["record_id"])] = detail
            if isinstance(detail, dict):
                processed_file_signatures.add(_normalize_path_signature(detail.get("file_path")))
                processed_file_signatures.add(_normalize_name_signature(detail.get("file_path")))
    processed_file_signatures.discard(None)

    metadata_record = db.session.query(UserMetadata).filter_by(
        session_id=session_row.id,
        field_name="zenodo_metadata_draft",
    ).first()
    shared_metadata = _parse_json(metadata_record.field_value if metadata_record else None, {})
    shared_metadata = shared_metadata if isinstance(shared_metadata, dict) else {}
    lod_mapping = shared_metadata.get("lod_mapping") if isinstance(shared_metadata.get("lod_mapping"), dict) else {}
    msf_path = shared_metadata.get("msf_path")
    session_dataset_key = normalize_dataset_key(extract_dataset_key(msf_path))
    mapping_fields = sorted(lod_mapping.keys())
    shared_zenodo_keys = sorted(
        [
            key
            for key in shared_metadata.keys()
            if not str(key).startswith("_")
            and not str(key).startswith("edm_")
            and key not in INTERNAL_ZENODO_KEYS
        ]
    )

    batch_metadata_by_filename: dict[str, dict[str, Any]] = {}
    for row in BatchFileMetadata.query.filter_by(session_id=session_row.id).all():
        parsed = _parse_json(row.metadata_json, {})
        if isinstance(parsed, dict):
            batch_metadata_by_filename[row.filename.lower()] = parsed

    return {
        "submission": _serialize_submission_summary(latest_submission),
        "details_by_record": details_by_record,
        "processed_file_signatures": processed_file_signatures,
        "selected_file_signatures": selected_file_signatures,
        "session_file_rows": session_file_rows,
        "batch_metadata_by_filename": batch_metadata_by_filename,
        "msf_path": msf_path,
        "session_dataset_key": session_dataset_key,
        "mapping_fields": mapping_fields,
        "shared_zenodo_keys": shared_zenodo_keys,
    }


def _build_empty_session_records_payload(
    session_row: DBSession,
    context: dict[str, Any],
    *,
    source_state: str,
    warning_message: str,
) -> dict[str, Any]:
    return {
        "source_state": source_state,
        "session": _serialize_session_context(session_row),
        "submission": context.get("submission"),
        "summary": {
            "total_records": 0,
            "published_records": 0,
            "draft_records": 0,
            "other_records": 0,
            "total_included_files": 0,
            "records_with_warnings": 0,
        },
        "provenance": {
            "msf_path": context.get("msf_path"),
            "mapping_field_count": len(context.get("mapping_fields") or []),
            "mapping_fields": context.get("mapping_fields") or [],
            "shared_metadata_keys": context.get("shared_zenodo_keys") or [],
            "batch_metadata_file_count": len(context.get("batch_metadata_by_filename") or {}),
        },
        "records": [],
        "warnings": [warning_message],
    }


def _build_record_file_items(base_record: dict[str, Any]) -> tuple[list[dict[str, Any]], set[tuple[str, str]], dict[str, Any]]:
    source_file = {
        "file_id": base_record.get("source_file_id"),
        "filename": base_record.get("source_file_name"),
        "absolute_path": base_record.get("source_file_path"),
        "relative_path": base_record.get("source_relative_path"),
        "file_type": base_record.get("source_file_type"),
        "status": base_record.get("source_status"),
        "size_bytes": base_record.get("source_size_bytes"),
        "mime_type": base_record.get("source_mime_type"),
        "pipeline_source": base_record.get("source_pipeline_source"),
        "step_source": base_record.get("source_step_source"),
        "added_timestamp": base_record.get("source_added_timestamp"),
    }
    mapped_files = list(base_record.get("record_files") or [])
    if not mapped_files and source_file.get("filename"):
        mapped_files = [
            {
                "record_id": base_record.get("local_record_id"),
                "file_id": source_file.get("file_id"),
                "file_purpose": "main",
                "upload_status": None,
                "upload_timestamp": None,
                "mapped_file_path": source_file.get("absolute_path"),
                "filename": source_file.get("filename"),
                "absolute_path": source_file.get("absolute_path"),
                "relative_path": source_file.get("relative_path"),
                "file_type": source_file.get("file_type"),
                "source_status": source_file.get("status"),
                "size_bytes": source_file.get("size_bytes"),
                "mime_type": source_file.get("mime_type"),
                "pipeline_source": source_file.get("pipeline_source"),
                "step_source": source_file.get("step_source"),
                "added_timestamp": source_file.get("added_timestamp"),
            }
        ]

    file_items: list[dict[str, Any]] = []
    lineage: set[tuple[str, str]] = set()
    for file_row in mapped_files:
        pipeline_source = file_row.get("pipeline_source")
        step_source = file_row.get("step_source")
        if pipeline_source or step_source:
            lineage.add((pipeline_source or "unknown", step_source or "unknown"))
        file_items.append(
            {
                "file_id": file_row.get("file_id"),
                "filename": file_row.get("filename"),
                "absolute_path": file_row.get("absolute_path"),
                "relative_path": file_row.get("relative_path"),
                "file_type": file_row.get("file_type"),
                "status": file_row.get("source_status"),
                "size_bytes": file_row.get("size_bytes"),
                "mime_type": file_row.get("mime_type"),
                "file_purpose": file_row.get("file_purpose"),
                "upload_status": file_row.get("upload_status"),
                "upload_timestamp": file_row.get("upload_timestamp"),
                "pipeline_source": pipeline_source,
                "step_source": step_source,
                "added_timestamp": file_row.get("added_timestamp"),
                "mapped_file_path": file_row.get("mapped_file_path"),
            }
        )
    file_items.sort(key=lambda item: (0 if item.get("file_purpose") == "main" else 1, item.get("filename") or ""))
    return file_items, lineage, source_file


def _build_session_record_payload(session_row: DBSession, base_record: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    metadata_payload = base_record.get("record_metadata")
    metadata_payload = metadata_payload if isinstance(metadata_payload, dict) else {}
    metadata_core = metadata_payload.get("metadata") if isinstance(metadata_payload.get("metadata"), dict) else {}
    links = metadata_payload.get("links") if isinstance(metadata_payload.get("links"), dict) else {}
    local_record_id = int(base_record.get("local_record_id") or 0)
    status = str(base_record.get("record_status") or _normalize_record_status("", metadata_payload)).strip().lower() or "unknown"
    file_items, lineage, source_file = _build_record_file_items(base_record)
    detail = context.get("details_by_record", {}).get(str(local_record_id), {})

    mapped_filename = None
    for candidate in [
        (file_items[0] if file_items else {}).get("filename"),
        source_file.get("filename"),
        os.path.basename(detail.get("file_path", "")),
    ]:
        if candidate and candidate.lower() in (context.get("batch_metadata_by_filename") or {}):
            mapped_filename = candidate
            break

    mapped_metadata = (
        (context.get("batch_metadata_by_filename") or {}).get(mapped_filename.lower())
        if mapped_filename
        else {}
    )
    mapped_metadata = mapped_metadata if isinstance(mapped_metadata, dict) else {}
    mapped_metadata_keys = sorted(mapped_metadata.keys())
    detail_warnings = detail.get("warnings") if isinstance(detail.get("warnings"), list) else []
    processing_error = detail.get("error")

    signature_candidates = _record_signature_candidates(
        source_file_id=base_record.get("source_file_id"),
        source_file=source_file,
        file_items=file_items,
        detail=detail,
    )
    processed_in_latest_submission = str(local_record_id) in (context.get("details_by_record") or {}) or any(
        item in (context.get("processed_file_signatures") or set()) for item in signature_candidates
    )
    selected_for_submission = processed_in_latest_submission or any(
        item in (context.get("selected_file_signatures") or set()) for item in signature_candidates
    )
    available_not_selected = status == "prepared" and not selected_for_submission
    zenodo_id = base_record.get("zenodo_record_id") or metadata_payload.get("id")
    is_sandbox = base_record.get("is_sandbox") if base_record.get("is_sandbox") is not None else None
    record_link = base_record.get("record_link") or links.get("html")
    if not record_link and zenodo_id:
        record_base = "https://sandbox.zenodo.org/records" if is_sandbox else "https://zenodo.org/records"
        record_link = f"{record_base}/{zenodo_id}"
    record_dataset_key = base_record.get("dataset_key") or normalize_dataset_key(
        extract_dataset_key(
            source_file.get("absolute_path"),
            source_file.get("filename"),
            context.get("msf_path"),
            context.get("session_dataset_key"),
        )
    )
    record_payload = {
        "local_record_id": local_record_id,
        "record_title": base_record.get("record_title") or metadata_core.get("title") or "Untitled record",
        "record_status": status,
        "is_published": status == "published",
        "is_sandbox": is_sandbox,
        "zenodo_record_id": zenodo_id,
        "concept_rec_id": base_record.get("concept_rec_id") or metadata_payload.get("conceptrecid"),
        "zenodo_doi": base_record.get("zenodo_doi") or metadata_payload.get("doi") or metadata_core.get("doi"),
        "record_link": record_link,
        "draft_link": links.get("latest_draft") or links.get("self"),
        "created_at": base_record.get("created_at"),
        "updated_at": base_record.get("updated_at"),
        "record_origin": base_record.get("record_origin"),
        "canonical_submit_flow": base_record.get("canonical_submit_flow", True),
        "source_file_id": base_record.get("source_file_id"),
        "source_file_name": source_file.get("filename"),
        "source_file_path": source_file.get("absolute_path"),
        "dataset_key": record_dataset_key or None,
        "file_count": len(file_items),
        "files": file_items,
        "provenance": {
            "msf_path": context.get("msf_path"),
            "dataset_key": record_dataset_key or context.get("session_dataset_key") or None,
            "mapped_from_filename": mapped_filename,
            "mapped_metadata_keys": mapped_metadata_keys,
            "mapped_metadata": mapped_metadata,
            "mapping_field_count": len(mapped_metadata_keys),
            "pipeline_lineage": [
                {"pipeline": pipeline_name, "step": step_name}
                for pipeline_name, step_name in sorted(lineage)
            ],
        },
        "processing": {
            "render_status": _extract_processing_step_status(detail, "render"),
            "usdz_status": _extract_processing_step_status(detail, "usdz"),
            "edm_status": _extract_processing_step_status(detail, "edm"),
            "iiif_status": _extract_processing_step_status(detail, "iiif"),
            "mets_status": _extract_processing_step_status(detail, "mets"),
            "draft_success": (detail.get("zenodo") or {}).get("draft_success") if isinstance(detail, dict) else None,
            "upload_success": (detail.get("zenodo") or {}).get("upload_success") if isinstance(detail, dict) else None,
            "error": processing_error,
            "warnings": detail_warnings,
        },
        "record_metadata": metadata_payload,
        "selected_for_submission": bool(selected_for_submission),
        "processed_in_latest_submission": bool(processed_in_latest_submission),
        "available_not_selected": bool(available_not_selected),
        "display_status": (
            "processed"
            if processed_in_latest_submission
            else "available_not_selected"
            if available_not_selected
            else "selected_not_processed"
            if selected_for_submission
            else "record_only"
        ),
    }
    record_payload["thumbnail_health"] = _build_thumbnail_health(session_row, record_payload, metadata_payload)
    record_payload["model_preview"] = build_model_preview(record_payload)
    return record_payload, bool(detail_warnings or processing_error)


def _build_session_records_payload(session_row: DBSession, inventory: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    visible_records = inventory.get("visible_records") or []
    records_payload: list[dict[str, Any]] = []
    records_with_warnings = 0
    for base_record in visible_records:
        record_payload, has_warnings = _build_session_record_payload(session_row, base_record, context)
        records_payload.append(record_payload)
        if has_warnings:
            records_with_warnings += 1
    records_payload.sort(key=lambda item: int(item.get("local_record_id") or 0), reverse=True)

    hidden_summary = inventory.get("summary") or {}
    published_count = sum(1 for record in records_payload if record.get("record_status") == "published")
    draft_count = sum(1 for record in records_payload if record.get("record_status") == "draft")
    other_count = max(len(records_payload) - published_count - draft_count, 0)
    total_file_count = sum(int(record.get("file_count") or 0) for record in records_payload)
    processed_count = sum(1 for record in records_payload if record.get("processed_in_latest_submission"))
    available_not_selected_count = sum(1 for record in records_payload if record.get("available_not_selected"))
    selected_record_count = sum(1 for record in records_payload if record.get("selected_for_submission"))
    missing_thumbnail_count = sum(
        1 for record in records_payload if bool((record.get("thumbnail_health") or {}).get("missing_uploaded_thumbnails"))
    )
    repairable_thumbnail_count = sum(
        1 for record in records_payload if bool((record.get("thumbnail_health") or {}).get("can_repair_missing_thumbnails"))
    )
    response_dataset_key = context.get("session_dataset_key") or next(
        (
            record.get("dataset_key") or (record.get("provenance") or {}).get("dataset_key")
            for record in records_payload
            if record.get("dataset_key") or (record.get("provenance") or {}).get("dataset_key")
        ),
        None,
    )
    return {
        "source_state": "ok",
        "session": _serialize_session_context(session_row),
        "submission": context.get("submission"),
        "summary": {
            "total_records": len(records_payload),
            "published_records": published_count,
            "draft_records": draft_count,
            "other_records": other_count,
            "total_included_files": total_file_count,
            "records_with_warnings": records_with_warnings,
            "processed_records": processed_count,
            "selected_records": selected_record_count,
            "available_not_selected_records": available_not_selected_count,
            "hidden_duplicate_records": int(hidden_summary.get("hidden_duplicate_records") or 0),
            "hidden_noncanonical_records": int(hidden_summary.get("hidden_noncanonical_records") or 0),
            "hidden_legacy_placeholder_records": int(hidden_summary.get("hidden_legacy_placeholder_records") or 0),
            "session_file_count": len(context.get("session_file_rows") or []),
            "records_missing_uploaded_thumbnails": missing_thumbnail_count,
            "repairable_thumbnail_records": repairable_thumbnail_count,
        },
        "provenance": {
            "msf_path": context.get("msf_path"),
            "dataset_key": response_dataset_key,
            "mapping_field_count": len(context.get("mapping_fields") or []),
            "mapping_fields": context.get("mapping_fields") or [],
            "shared_metadata_keys": context.get("shared_zenodo_keys") or [],
            "batch_metadata_file_count": len(context.get("batch_metadata_by_filename") or {}),
        },
        "records": records_payload,
    }


def _unpack_route_response(route_result):
    """
    Normalize Flask route return value into (response_obj, status_code, payload_dict).
    Supports response objects and (response, status) tuples.
    """
    if isinstance(route_result, tuple):
        response_obj = route_result[0]
        status_code = route_result[1] if len(route_result) > 1 else getattr(response_obj, "status_code", 200)
    else:
        response_obj = route_result
        status_code = getattr(response_obj, "status_code", 200)

    payload = response_obj.get_json(silent=True) if hasattr(response_obj, "get_json") else None
    if not isinstance(payload, dict):
        payload = {}

    try:
        status_code = int(status_code)
    except (TypeError, ValueError):
        status_code = getattr(response_obj, "status_code", 200)

    return response_obj, status_code, payload


@session_bp.route("/<int:session_id>", methods=["GET"])
@jwt_required()
def get_session(session_id):
    """Get session details"""
    session, user, error_response = get_session_with_permission(session_id, permission="view")
    if error_response:
        return error_response

    return APIResponse.success(
        data={"session": _serialize_session_context(session, acting_user=user)}
    )


@session_bp.route("/<int:session_id>/audit-events", methods=["GET"])
@jwt_required()
def get_session_audit_events(session_id):
    session_row, _, error_response = get_session_with_permission(session_id, permission="manage")
    if error_response:
        return error_response

    payload = list_audit_events(
        session_id=session_row.id,
        event_type=request.args.get("event_type"),
        entity_type=request.args.get("entity_type"),
        page=_parse_positive_int_arg("page", 1),
        per_page=_parse_positive_int_arg("per_page", 25),
    )
    return APIResponse.success(data=payload)


@session_bp.route("/<int:session_id>/workspace", methods=["GET"])
@jwt_required()
def get_session_workspace(session_id):
    session_row, user, error_response = get_session_with_permission(session_id, permission="manage")
    if error_response:
        return error_response

    return APIResponse.success(
        data=_build_session_workspace_payload(
            session_row,
            user,
            requested_institution_id=request.args.get("institution_id"),
        )
    )


@session_bp.route("/<int:session_id>/workspace", methods=["PUT"])
@jwt_required()
def update_session_workspace(session_id):
    session_row, user, error_response = get_session_with_permission(session_id, permission="manage")
    if error_response:
        return error_response

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return APIResponse.validation_error("Invalid workspace payload")

    options = _normalize_session_workspace_options(
        user=user,
        payload=payload,
        allow_publishing_user_override=True,
        existing_session=session_row,
    )
    _apply_session_workspace_options(session_row, options)
    db.session.commit()

    record_audit_event(
        actor_user_id=user.id,
        institution_id=session_row.institution_id,
        session_id=session_row.id,
        event_type="session_workspace_updated",
        entity_type="session",
        entity_id=session_row.id,
        details=publishing_context_service.describe_session(session_row),
    )
    db.session.commit()

    return APIResponse.success(
        data={"session": _serialize_session_context(session_row, acting_user=user)},
        message="Session workspace updated successfully",
    )


@session_bp.route("", methods=["GET"])
@jwt_required()
def list_sessions():
    """List all sessions for current user"""
    user = get_current_user_from_jwt()
    if not user:
        return APIResponse.unauthorized()
    scope = (request.args.get("scope") or "all").strip().lower()
    sessions = list(get_accessible_sessions(user, scope=scope))
    session_ids = [session.id for session in sessions]
    institution_ids = sorted({int(session.institution_id) for session in sessions if session.institution_id})
    metadata_map = _get_session_metadata_map(
        session_ids,
        {
            "msf_profile",
            UPLOAD_TASK_ID_FIELD,
            UPLOAD_PROGRESS_FIELD,
            UPLOAD_STORAGE_MODE_FIELD,
            WORKFLOW_STATE_FIELD,
        },
    )
    file_count_map = _get_session_file_counts(session_ids)
    first_filename_map = dict(db.session.query(File.session_id, func.min(File.filename)).filter(File.session_id.in_(session_ids)).group_by(File.session_id).all()) if session_ids else {}
    publishing_context_map = publishing_context_service.describe_sessions(sessions)
    institution_payload_map = {
        row.id: row.to_dict()
        for row in Institution.query.filter(Institution.id.in_(institution_ids)).all()
    } if institution_ids else {}

    session_payloads = []
    for session_row in sessions:
        metadata_fields = metadata_map.get(session_row.id, {})
        session_payloads.append(
            _serialize_session_context(
                session_row,
                metadata_fields,
                acting_user=user,
                publishing_context=publishing_context_map.get(session_row.id),
                file_count=file_count_map.get(session_row.id, 0),
                display_name=first_filename_map.get(session_row.id),
                institution_payload=institution_payload_map.get(session_row.institution_id),
            )
        )

    return APIResponse.success(
        data={
            "sessions": session_payloads
        }
    )


@session_bp.route("/<int:session_id>/workflow-state", methods=["GET"])
@jwt_required()
def get_workflow_state(session_id):
    session_row, _, error_response = get_session_with_permission(session_id, permission="view")
    if error_response:
        return error_response

    metadata_map = _get_session_metadata_map([session_id], {WORKFLOW_STATE_FIELD, "msf_profile", "zenodo_metadata_draft"})
    metadata_fields = metadata_map.get(session_id, {})
    workflow_state = _parse_workflow_state(metadata_fields.get(WORKFLOW_STATE_FIELD))
    msf_profile = _parse_json(metadata_fields.get("msf_profile"), {})
    draft_metadata = _parse_json(metadata_fields.get("zenodo_metadata_draft"), {})
    file_metadata_map = _get_batch_file_metadata_map(session_id) if workflow_state.get("is_batch_mode") else {}

    return APIResponse.success(
        data={
            "state": workflow_state,
            "msf_profile": msf_profile if isinstance(msf_profile, dict) else {},
            "draft_metadata": draft_metadata if isinstance(draft_metadata, dict) else {},
            "file_metadata_map": file_metadata_map,
            "workflow_hint": _build_session_workflow_hint(session_row, metadata_fields),
            "session": _serialize_session_context(session_row, metadata_fields),
        }
    )


@session_bp.route("/<int:session_id>/workflow-state", methods=["PUT"])
@jwt_required()
def update_workflow_state(session_id):
    session_row, _, error_response = get_session_with_permission(
        session_id,
        permission="edit",
        require_mutable=True,
    )
    if error_response:
        return error_response

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return APIResponse.error("Invalid workflow state payload", 400)

    existing_record = UserMetadata.query.filter_by(session_id=session_id, field_name=WORKFLOW_STATE_FIELD).first()
    existing_state = _parse_workflow_state(existing_record.field_value if existing_record else None)
    workflow_state = _normalize_workflow_state_payload(payload, existing_state)

    _upsert_session_metadata(session_id, WORKFLOW_STATE_FIELD, json.dumps(workflow_state))
    db.session.commit()

    return APIResponse.success(data={"state": workflow_state}, message="Workflow state updated")


@session_bp.route("/<int:session_id>/record-resolution", methods=["GET"])
@jwt_required()
def get_record_resolution(session_id):
    session_row, user, error_response = get_session_with_permission(session_id, permission="view")
    if error_response:
        return error_response

    try:
        payload = analyze_session_record_resolution(session_row)
        return APIResponse.success(data=_sanitize_record_resolution_payload(payload, user))
    except DatasetIntegrityConflictError as exc:
        return APIResponse.validation_error(str(exc), details=exc.details)
    except Exception as exc:
        logger.error("Failed to load record resolution for session %s: %s", session_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to load record resolution")


@session_bp.route("/<int:session_id>/record-resolution/analyze", methods=["POST"])
@jwt_required()
def analyze_record_resolution(session_id):
    session_row, user, error_response = get_session_with_permission(
        session_id,
        permission="edit",
        require_mutable=True,
    )
    if error_response:
        return error_response

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return APIResponse.validation_error("Invalid record resolution payload")

    try:
        policy_override = payload.get("policy_override")
        existing_state = analyze_session_record_resolution(session_row)
        state_payload = {
            "policy_override": policy_override if policy_override is not None else existing_state.get("state", {}).get("policy_override"),
            "decisions": existing_state.get("state", {}).get("decisions") or [],
        }
        save_session_record_resolution_state(session_row.id, state_payload)
        analysis = analyze_session_record_resolution(session_row, policy_override=policy_override)
        return APIResponse.success(data=_sanitize_record_resolution_payload(analysis, user))
    except DatasetIntegrityConflictError as exc:
        return APIResponse.validation_error(str(exc), details=exc.details)
    except Exception as exc:
        logger.error("Failed to analyze record resolution for session %s: %s", session_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to analyze record resolution")


@session_bp.route("/<int:session_id>/record-resolution", methods=["PUT"])
@jwt_required()
def update_record_resolution(session_id):
    session_row, user, error_response = get_session_with_permission(
        session_id,
        permission="edit",
        require_mutable=True,
    )
    if error_response:
        return error_response

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return APIResponse.validation_error("Invalid record resolution payload")

    try:
        validated = validate_record_resolution_decisions(session_row, payload)
        save_session_record_resolution_state(session_row.id, validated)
        analysis = analyze_session_record_resolution(session_row, policy_override=validated.get("policy_override"))
        return APIResponse.success(
            data=_sanitize_record_resolution_payload(analysis, user),
            message="Record resolution updated",
        )
    except DatasetIntegrityConflictError as exc:
        return APIResponse.validation_error(str(exc), details=exc.details)
    except Exception as exc:
        logger.error("Failed to update record resolution for session %s: %s", session_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to update record resolution")


def _load_upload_operation_rows(*, user: User | None = None):
    upload_session_ids = [
        row[0]
        for row in (
            db.session.query(UserMetadata.session_id)
            .filter(
                UserMetadata.field_name.in_(
                    [
                        UPLOAD_SUBMIT_TOKEN_FIELD,
                        UPLOAD_TASK_ID_FIELD,
                        UPLOAD_PROGRESS_FIELD,
                        "msf_profile",
                    ]
                )
            )
            .distinct()
            .all()
        )
    ]
    if not upload_session_ids:
        return []

    if user is None:
        return []

    accessible_sessions = list(get_accessible_sessions(user, scope="all"))
    accessible_ids = {session.id for session in accessible_sessions}
    allowed_ids = [session_id for session_id in upload_session_ids if session_id in accessible_ids]
    if not allowed_ids:
        return []

    return DBSession.query.filter(DBSession.id.in_(allowed_ids)).order_by(DBSession.created_at.desc()).all()


@session_bp.route("/upload-operations", methods=["GET"])
@jwt_required()
def list_upload_operations():
    user = get_current_user_from_jwt()
    if not user:
        return APIResponse.unauthorized()
    sessions = _load_upload_operation_rows(user=user)
    session_ids = [session.id for session in sessions]
    institution_ids = sorted({int(session.institution_id) for session in sessions if session.institution_id})
    metadata_map = _get_session_metadata_map(
        session_ids,
        {
            UPLOAD_SUBMIT_TOKEN_FIELD,
            UPLOAD_TASK_ID_FIELD,
            UPLOAD_STORAGE_MODE_FIELD,
            UPLOAD_PROGRESS_FIELD,
            UPLOAD_WORKER_GROUP_ID_FIELD,
            "msf_profile",
        },
    )
    file_counts = _get_upload_file_counts(session_ids)
    session_file_counts = _get_session_file_counts(session_ids)
    publishing_context_map = publishing_context_service.describe_sessions(sessions)
    institution_payload_map = {
        row.id: row.to_dict()
        for row in Institution.query.filter(Institution.id.in_(institution_ids)).all()
    } if institution_ids else {}

    operations = [
        _build_upload_operation_payload(
            session,
            metadata_fields=metadata_map.get(session.id, {}),
            file_counts=file_counts.get(session.id, {}),
            session_context=_serialize_session_context(
                session,
                metadata_map.get(session.id, {}),
                acting_user=user,
                publishing_context=publishing_context_map.get(session.id),
                file_count=session_file_counts.get(session.id, 0),
                institution_payload=institution_payload_map.get(session.institution_id),
            ),
        )
        for session in sessions
    ]
    return APIResponse.success(data={"operations": operations})


@session_bp.route("/upload-operations/<int:session_id>", methods=["GET"])
@jwt_required()
def get_upload_operation_detail(session_id):
    session, _, error_response = get_session_with_permission(session_id, permission="view")
    if error_response:
        return APIResponse.not_found("Upload operation not found")

    metadata_map = _get_session_metadata_map(
        [session_id],
        {
            UPLOAD_SUBMIT_TOKEN_FIELD,
            UPLOAD_TASK_ID_FIELD,
            UPLOAD_STORAGE_MODE_FIELD,
            UPLOAD_PROGRESS_FIELD,
            UPLOAD_WORKER_GROUP_ID_FIELD,
            "msf_profile",
        },
    )
    if not metadata_map.get(session_id):
        return APIResponse.not_found("Upload operation not found")

    file_counts = _get_upload_file_counts([session_id])
    operation = _build_upload_operation_payload(
        session,
        metadata_fields=metadata_map.get(session_id, {}),
        file_counts=file_counts.get(session_id, {}),
    )
    return APIResponse.success(data={"operation": operation})


@session_bp.route("/import-hdpc", methods=["POST"])
@jwt_required()
def import_hdpc():
    """Import a .hdpc project file into a new session for the current user."""
    try:
        user_id = int(get_jwt_identity())
        uploaded_file = request.files.get("hdpc_file")
        result = import_hdpc_for_user(user_id=user_id, uploaded_file=uploaded_file, actor_user_id=user_id)
        return APIResponse.created(
            data=result,
            message="HDPC file imported successfully. Records are now available in Records Explorer.",
        )
    except ValidationError as exc:
        return APIResponse.validation_error(str(exc))
    except Exception as exc:
        logger.error("Failed to import .hdpc for current user: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to import .hdpc file")


@session_bp.route("/local-msf", methods=["GET"])
@jwt_required()
def list_local_msf():
    """List available MSF files in the local input directory."""
    from services.cloud_upload_service import CloudUploadService, STORAGE_MODE_LOCAL

    if CloudUploadService.get_storage_mode() != STORAGE_MODE_LOCAL:
        return APIResponse.error("Local storage mode is not active", 403)

    input_dir = current_app.config.get("LOCAL_INPUT_PATH", "/data/local_input")
    if not os.path.exists(input_dir):
        return APIResponse.error(f"Local input directory not found: {input_dir}", 500)

    msf_files = []
    for root, dirs, files in os.walk(input_dir):
        for file in files:
            if file.lower().endswith((".xlsx", ".xls", ".csv")) and not file.startswith('~$'):
                # Get relative path for easier handling
                rel_path = os.path.relpath(os.path.join(root, file), input_dir)
                msf_files.append({
                    "name": file,
                    "path": rel_path,
                })

    try:
        subdirectories = _list_local_subdirectories(input_dir)
    except Exception as exc:
        logger.warning("Failed to list local input subdirectories: %s", exc)
        subdirectories = []
    msf_files.sort(key=lambda item: item["path"].lower())

    return APIResponse.success(
        data={
            "msf_files": msf_files,
            "subdirectories": subdirectories,
            "input_root": input_dir,
        }
    )


@session_bp.route("/directory", methods=["POST"])
@jwt_required()
def start_session_directory():
    """
    Start a session by uploading a ZIP file containing model files with MSF (Metadata Source File).

    Accepts multipart/form-data with:
    - 'zip_file': ZIP file containing 3D model files (required)
    - 'msf_file': Excel or CSV metadata source file (required)

    Alternatively, accepts JSON with paths (for backward compatibility):
    - 'input_directory_path': Path to directory (legacy)
    - 'msf_path': Path to MSF file (legacy)
    """
    import zipfile
    import tempfile
    import shutil
    import uuid

    project_service = current_app.project_service

    logger = logging.getLogger(__name__)
    logger.info("Handling directory/ZIP scan request with MSF.")
    user_id = int(get_jwt_identity())

    is_json = request.is_json
    data = {}
    if is_json:
        data = request.get_json() or {}
    submit_token_raw = data.get("submit_token")
    if submit_token_raw is None:
        submit_token_raw = request.form.get("submit_token")
    if submit_token_raw is None:
        submit_token_raw = request.headers.get("X-Upload-Submit-Token")
    try:
        submit_token = _normalize_submit_token(submit_token_raw)
    except ValidationError as exc:
        return APIResponse.validation_error(str(exc))

    if submit_token:
        existing_context = _get_upload_submission_context(user_id=user_id, submit_token=submit_token)
        if existing_context:
            return APIResponse.accepted(
                message="Upload request already accepted. Reusing existing session.",
                data=_build_upload_recovery_payload(existing_context),
            )

    # Check cloud storage availability and get storage mode
    from services.cloud_upload_service import (
        CloudUploadService,
        STORAGE_DROPBOX,
        STORAGE_GDRIVE,
        STORAGE_MODE_PURE_CLOUD,
        STORAGE_MODE_CLOUD_BACKUP,
        STORAGE_MODE_SERVER_ONLY,
        STORAGE_MODE_LOCAL,
        STORAGE_SERVER
    )

    storage_mode = CloudUploadService.get_storage_mode()
    storage_type, storage_message = CloudUploadService.get_available_storage()

    # For pure_cloud and cloud_backup modes, cloud storage must be available
    if storage_mode in [STORAGE_MODE_PURE_CLOUD, STORAGE_MODE_CLOUD_BACKUP]:
        if storage_type is None or storage_type == STORAGE_SERVER:
            logger.error(f"Cloud storage required but not available: {storage_message}")
            return APIResponse.error(
                f"Cloud storage is required but not available. {storage_message}",
                503,
                details={"storage_error": storage_message, "storage_mode": storage_mode}
            )

    # Handle LOCAL storage mode initialization
    if storage_mode == STORAGE_MODE_LOCAL:
        logger.info("[LOCAL_MODE] Using local storage mode paths.")
        # Override paths from environment/config
        input_directory_path = current_app.config.get("LOCAL_INPUT_PATH", "/data/local_input")
        data_out_base_path = current_app.config.get("LOCAL_OUTPUT_PATH", "/data/local_output")

        # Verify directories exist in container
        if not os.path.isdir(input_directory_path):
             return APIResponse.error(f"Local input directory not found at {input_directory_path}", 500)

        os.makedirs(data_out_base_path, exist_ok=True)

        # In Local Mode, MSF must be in the input directory or provided
        # If it's a file upload, we'll save it to a temp location for validation, but scan the local input dir.
        # But wait, the user said "scanned within the local drives".
        # If they still upload an MSF via the UI, we should use it.

    logger.info(f"Storage check passed: mode={storage_mode}, type={storage_type}")

    # Track original ZIP path for cloud upload (used in cloud_backup mode)
    original_zip_path = None

    # NOTE: JSON request can now also contain cloud_path for streamed uploads
    current_user = db.session.get(User, user_id)
    session_workspace_payload = dict(data or {})
    for key in (
        "institution_id",
        "sharing_scope",
        "credential_preference",
        "default_zenodo_environment",
        "use_institution_default_communities",
    ):
        if key not in session_workspace_payload and request.form.get(key) is not None:
            session_workspace_payload[key] = request.form.get(key)
    session_workspace_options = _normalize_session_workspace_options(
        user=current_user,
        payload=session_workspace_payload,
    )

    msf_parse_options = _build_msf_parse_options(data, request.form)
    raw_msf_auto_patch = data.get("msf_auto_patch")
    if raw_msf_auto_patch is None:
        raw_msf_auto_patch = request.form.get("msf_auto_patch")
    msf_auto_patch = _coerce_bool(raw_msf_auto_patch)
    if msf_auto_patch is None:
        msf_auto_patch = True

    msf_duplicate_policy = (
        data.get("msf_duplicate_policy")
        or request.form.get("msf_duplicate_policy")
        or "merge_non_empty"
    )

    # Get cloud_path from JSON or Form Data
    cloud_path = data.get("cloud_path") or request.form.get("cloud_path")
    cloud_original_filename = data.get("cloud_original_filename") or request.form.get("cloud_original_filename")
    cloud_storage_type = str(data.get("cloud_storage_type") or request.form.get("cloud_storage_type") or "").strip().lower()
    if cloud_storage_type and cloud_storage_type not in {STORAGE_DROPBOX, STORAGE_GDRIVE}:
        return APIResponse.validation_error("cloud_storage_type must be dropbox or gdrive")
    hpc_allocation_id = str(data.get("hpc_allocation_id") or request.form.get("hpc_allocation_id") or "").strip()

    # Determine input sources based on storage mode and provided data
    input_directory_path = None
    msf_path = None
    original_zip_path = None
    extract_dir_to_cleanup = None
    msf_uploaded = False
    msf_preflight_report = None

    try:
        # 1. Handle Remote/Streamed Upload (Pure Cloud)
        if cloud_path and storage_mode == STORAGE_MODE_PURE_CLOUD:
            logger.info(f"Processing remote cloud file: {cloud_path}")

            if 'msf_file' in request.files:
                msf_file = request.files.get('msf_file')
            else:
                 return APIResponse.error("MSF file is required for remote zip processing", 400)

            shared_base = os.environ.get("SHARED_SESSION_PATH", tempfile.gettempdir())
            extract_dir = os.path.join(shared_base, f"hdp_zip_{uuid.uuid4().hex[:8]}")
            os.makedirs(extract_dir, exist_ok=True)
            os.chmod(extract_dir, 0o700)
            extract_dir_to_cleanup = extract_dir

            # Save and parse MSF
            msf_filename = sanitize_upload_filename(str(msf_file.filename or ""), allowed_extensions=MSF_ALLOWED_EXTENSIONS)
            msf_path = os.path.join(extract_dir, f"msf_{msf_filename}")
            msf_file.save(msf_path)

            from services.msf_service import MSFService
            msf_service = MSFService()

            download_url = CloudUploadService.get_file_download_url(cloud_path, cloud_storage_type or storage_type)
            if not download_url:
                raise ValueError("Could not get download URL for cloud file")

            from utils.remote_storage import RemoteStorageFile
            remote_file = RemoteStorageFile(download_url)

            with zipfile.ZipFile(remote_file, 'r') as zip_ref:
                all_zip_paths = zip_ref.namelist()
                file_map = {os.path.basename(p): p for p in all_zip_paths if not p.endswith('/') and not p.startswith('__MACOSX')}
                zip_filenames = list(file_map.keys())

                preflight_policy = msf_duplicate_policy if msf_auto_patch else "fail"
                msf_preflight_report = msf_service.patch_msf_file(
                    file_path=msf_path,
                    parse_options=msf_parse_options,
                    directory_files=zip_filenames,
                    duplicate_policy=preflight_policy,
                    apply=bool(msf_auto_patch),
                    output_dir=extract_dir,
                )
                if not msf_preflight_report.get("is_valid", False):
                    return APIResponse.validation_error(
                        "MSF preflight failed",
                        details=msf_preflight_report,
                    )

                patched_msf_path = msf_preflight_report.get("patched_msf_path")
                if patched_msf_path and os.path.exists(patched_msf_path):
                    msf_path = patched_msf_path
                    msf_uploaded = True
                    msf_parse_options = {}

                validation_payload = msf_preflight_report.get("validation") or {}
                matched_filenames = validation_payload.get("matched_files") or []
                if matched_filenames:
                    # Extract the full bundle to preserve dependencies (OBJ/MTL/textures, etc.).
                    safe_extract_zip(zip_ref, extract_dir)

            input_directory_path = extract_dir

        # 2. Handle Local ZIP Upload or Local Storage Mode
        elif 'zip_file' in request.files or storage_mode == STORAGE_MODE_LOCAL:
            zip_file = request.files.get('zip_file')
            msf_file = request.files.get('msf_file')

            if storage_mode == STORAGE_MODE_LOCAL:
                msf_path_rel = data.get("msf_path") or request.form.get("msf_path")
                if msf_path_rel:
                    input_dir = current_app.config.get("LOCAL_INPUT_PATH", "/data/local_input")
                    try:
                        msf_candidate = resolve_child_path(input_dir, msf_path_rel, must_exist=True)
                    except Exception as exc:
                        return APIResponse.validation_error(str(exc))
                    if msf_candidate.suffix.lower() not in MSF_ALLOWED_EXTENSIONS or not msf_candidate.is_file():
                        return APIResponse.validation_error("Selected MSF path must be an MSF file under the local input directory")
                    msf_path = str(msf_candidate)

                # Handling Directory Selection for HPC/Local Mode
                # The user can specify a relative path within LOCAL_INPUT_PATH to scan.
                relative_input_path = data.get("directory_path") or request.form.get("directory_path")

                base_local_path = current_app.config.get("LOCAL_INPUT_PATH", "/data/local_input")
                if relative_input_path:
                    try:
                        potential_path = resolve_child_path(base_local_path, relative_input_path, must_exist=True)
                    except Exception as exc:
                        return APIResponse.validation_error(str(exc))
                    if not potential_path.is_dir():
                         return APIResponse.validation_error("Selected input path must be a directory")

                    input_directory_path = str(potential_path)
                    logger.info(f"[LOCAL_MODE] User selected specific input directory: {input_directory_path}")
                else:
                    # Default to base path if not specified
                    input_directory_path = base_local_path

            # Validation
            if storage_mode != STORAGE_MODE_LOCAL:
                if not zip_file or not zip_file.filename:
                    return APIResponse.error("No ZIP file provided", 400)
                if not msf_file or not msf_file.filename:
                    return APIResponse.error("No MSF file provided", 400)
            else:
                if not msf_file and not msf_path:
                     return APIResponse.error("MSF file or path is required in local mode", 400)

            # Create temp directory for processing
            shared_base = os.environ.get("SHARED_SESSION_PATH", tempfile.gettempdir())
            extract_dir = os.path.join(shared_base, f"hdp_zip_{uuid.uuid4().hex[:8]}")
            os.makedirs(extract_dir, exist_ok=True)
            os.chmod(extract_dir, 0o700)
            extract_dir_to_cleanup = extract_dir

            if msf_file:
                msf_uploaded = True
                msf_filename = sanitize_upload_filename(str(msf_file.filename or ""), allowed_extensions=MSF_ALLOWED_EXTENSIONS)
                msf_path = os.path.join(extract_dir, msf_filename)
                msf_file.save(msf_path)

            if zip_file:
                zip_filename = sanitize_upload_filename(str(zip_file.filename or ""), allowed_extensions={".zip"})
                zip_save_path = os.path.join(extract_dir, zip_filename)
                zip_file.save(zip_save_path)
                original_zip_path = zip_save_path

            # Check for validate_only flag
            if request.args.get('validate_only', 'false').lower() == 'true':
                try:
                    from services.msf_service import MSFService
                    msf_service = MSFService()
                    if not zip_file or not zip_save_path:
                        return APIResponse.validation_error("ZIP file is required for validate_only mode")

                    with zipfile.ZipFile(zip_save_path, 'r') as zip_ref:
                        safe_extract_zip(zip_ref, extract_dir, validate_only=True)
                        all_zip_paths = zip_ref.namelist()
                        zip_filenames = [
                            os.path.basename(path)
                            for path in (name.replace('\\', '/') for name in all_zip_paths)
                            if not path.endswith('/') and not path.startswith('__MACOSX')
                        ]
                        preflight_policy = msf_duplicate_policy if msf_auto_patch else "fail"
                        msf_preflight_report = msf_service.patch_msf_file(
                            file_path=msf_path,
                            parse_options=msf_parse_options,
                            directory_files=zip_filenames,
                            duplicate_policy=preflight_policy,
                            apply=bool(msf_auto_patch),
                            output_dir=extract_dir,
                        )
                        if not msf_preflight_report.get("is_valid", False):
                            return APIResponse.validation_error(
                                "MSF preflight failed",
                                details=msf_preflight_report,
                            )

                        patched_msf_path = msf_preflight_report.get("patched_msf_path")
                        if patched_msf_path and os.path.exists(patched_msf_path):
                            msf_path = patched_msf_path
                            msf_uploaded = True
                            msf_parse_options = {}

                        safe_extract_zip(zip_ref, extract_dir)

                    df, msf_profile = msf_service.parse_msf_file_with_profile(
                        msf_path,
                        parse_options=msf_parse_options,
                    )
                    columns = list(df.columns)

                    file_list = []
                    for root, _, files in os.walk(extract_dir):
                        for filename in files:
                            if filename.startswith('.'):
                                continue
                            ext = os.path.splitext(filename)[1].lower()
                            if ext in {'.xlsx', '.xls', '.csv'}:
                                continue
                            file_list.append(filename)

                    validation_result = msf_service.validate_msf_against_directory(
                        df,
                        file_list,
                        directory_root=extract_dir,
                    )
                    detected_col, detected_confidence = msf_service.detect_filename_column(df, file_list)
                    suggested_row_index = msf_service.suggest_sample_row_index(
                        df,
                        validation_result.filename_column or detected_col,
                    )
                    mapping_suggestions = msf_service.suggest_column_mapping(columns)
                    file_metadata_map = msf_service.get_all_file_metadata(
                        df,
                        validation_result.matched_files,
                        validation_result.filename_column,
                        column_mapping=mapping_suggestions or None,
                    )
                    msf_profile.update(
                        {
                            "filename_column": validation_result.filename_column or detected_col,
                            "filename_confidence": round(detected_confidence, 3),
                            "data_start_row": suggested_row_index,
                            "suggested_row_index": suggested_row_index,
                            "parse_options": msf_parse_options or msf_profile.get("parse_options", {}),
                        }
                    )
                    return APIResponse.success(
                        data={
                            "msf_validation": validation_result.to_dict(),
                            "msf_preview": msf_service.get_msf_preview(df),
                            "filename_column": validation_result.filename_column,
                            "msf_mapping": mapping_suggestions,
                            "msf_mapping_suggestions": mapping_suggestions,
                            "file_metadata_map": file_metadata_map,
                            "file_metadata_map_sample": dict(list(file_metadata_map.items())[:5]),
                            "msf_profile": msf_profile,
                            "msf_preflight": msf_preflight_report,
                        }
                    )
                finally:
                     shutil.rmtree(extract_dir, ignore_errors=True)
                     extract_dir_to_cleanup = None

            if storage_mode != STORAGE_MODE_LOCAL:
                from services.msf_service import MSFService
                msf_service = MSFService()
                zip_filenames = []
                if zip_file and zip_save_path and os.path.exists(zip_save_path):
                    with zipfile.ZipFile(zip_save_path, 'r') as zip_ref:
                        safe_extract_zip(zip_ref, extract_dir, validate_only=True)
                        zip_filenames = [
                            os.path.basename(path)
                            for path in (name.replace('\\', '/') for name in zip_ref.namelist())
                            if not path.endswith('/') and not path.startswith('__MACOSX')
                        ]
                preflight_policy = msf_duplicate_policy if msf_auto_patch else "fail"
                msf_preflight_report = msf_service.patch_msf_file(
                    file_path=msf_path,
                    parse_options=msf_parse_options,
                    directory_files=zip_filenames,
                    duplicate_policy=preflight_policy,
                    apply=bool(msf_auto_patch),
                    output_dir=extract_dir,
                )
                if not msf_preflight_report.get("is_valid", False):
                    return APIResponse.validation_error(
                        "MSF preflight failed",
                        details=msf_preflight_report,
                    )

                patched_msf_path = msf_preflight_report.get("patched_msf_path")
                if patched_msf_path and os.path.exists(patched_msf_path):
                    msf_path = patched_msf_path
                    msf_uploaded = True
                    msf_parse_options = {}

            if storage_mode == STORAGE_MODE_LOCAL:
                from services.msf_service import MSFService
                msf_service = MSFService()
                local_input_dir = current_app.config.get("LOCAL_INPUT_PATH", "/data/local_input")
                scan_directory_root = input_directory_path or local_input_dir
                if not os.path.isdir(scan_directory_root):
                    return APIResponse.validation_error(
                        f"Selected input directory not found: {scan_directory_root}"
                    )
                scanned_files = _build_local_scan_file_list(scan_directory_root)
                preflight_policy = msf_duplicate_policy if msf_auto_patch else "fail"

                try:
                    msf_preflight_report = msf_service.patch_msf_file(
                        file_path=msf_path,
                        parse_options=msf_parse_options,
                        directory_files=scanned_files,
                        directory_root=scan_directory_root,
                        duplicate_policy=preflight_policy,
                        apply=bool(msf_auto_patch),
                        output_dir=extract_dir,
                    )
                except ValueError as exc:
                    return APIResponse.validation_error(str(exc))

                if not msf_preflight_report.get("is_valid", False):
                    return APIResponse.validation_error(
                        "MSF preflight failed",
                        details=msf_preflight_report,
                    )

                patched_msf_path = msf_preflight_report.get("patched_msf_path")
                if patched_msf_path and os.path.exists(patched_msf_path):
                    msf_path = patched_msf_path
                    msf_uploaded = True
                    msf_parse_options = {}

        else:
            return APIResponse.error("Invalid request parameters: No ZIP file or cloud path provided", 400)

        # 3. Create Session and Start Background Task
        # Import late so idempotent retry paths do not initialize the global app.
        from app import _create_session_dirs

        hdpc_path, data_out_path, uploads_path = _create_session_dirs(
            institution_id=session_workspace_options["institution_id"],
            sharing_scope=session_workspace_options["sharing_scope"],
            credential_preference=session_workspace_options["credential_preference"],
            publishing_user_id=session_workspace_options["publishing_user_id"],
            default_zenodo_environment=session_workspace_options["default_zenodo_environment"],
            use_institution_default_communities=session_workspace_options["use_institution_default_communities"],
        )
        db_session_id = flask_session.get("db_session_id")
        if not db_session_id:
             raise Exception("Failed to create session record")
        created_session = db.session.get(DBSession, int(db_session_id))
        attached_hpc_allocation = None
        if hpc_allocation_id and hasattr(current_app, "hpc_allocation_service"):
            attached_hpc_allocation = current_app.hpc_allocation_service.attach_allocation_to_session(
                hpc_allocation_id,
                current_user,
                int(db_session_id),
            )
        if created_session:
            record_audit_event(
                actor_user_id=user_id,
                institution_id=created_session.institution_id,
                session_id=created_session.id,
                event_type="session_workspace_created",
                entity_type="session",
                entity_id=created_session.id,
                details=publishing_context_service.describe_session(created_session),
            )
            notify_admins(
                exclude_user_id=user_id,
                notification_type="admin.session_started",
                category="admin",
                severity="info",
                title="New session started",
                body=f"{current_user.email if current_user else 'A user'} started workflow session #{created_session.id}.",
                actor_user_id=user_id,
                institution_id=created_session.institution_id,
                session_id=created_session.id,
                entity_type="session",
                entity_id=created_session.id,
                action_url=f"/admin/session-monitoring?session_id={created_session.id}",
                payload={"session_id": created_session.id, "user_id": user_id},
                dedupe_key=f"admin:session_started:{created_session.id}",
            )
            db.session.commit()

        # Move uploaded files to persistent storage for background workers.
        if original_zip_path and os.path.exists(original_zip_path):
            final_zip_path = os.path.join(uploads_path, "upload.zip")
            shutil.move(original_zip_path, final_zip_path)
            original_zip_path = final_zip_path

        # In local mode, keep explicit msf_path selections in LOCAL_INPUT_PATH unchanged.
        if msf_path and os.path.exists(msf_path) and (storage_mode != STORAGE_MODE_LOCAL or msf_uploaded):
            ext = os.path.splitext(msf_path)[1].lower()
            if ext not in {".xlsx", ".xls", ".csv"}:
                ext = ".xlsx"
            final_msf_path = os.path.join(uploads_path, f"upload.msf{ext}")
            shutil.move(msf_path, final_msf_path)
            msf_path = final_msf_path

        try:
            from services.cloud_mirror_service import (
                ARTIFACT_BATCH_ZIP,
                ARTIFACT_MSF,
                mirror_local_artifact,
                register_existing_cloud_reference,
                should_mirror_for_storage_mode,
            )

            if should_mirror_for_storage_mode(storage_mode):
                if cloud_path:
                    zip_name = (
                        os.path.basename(str(cloud_original_filename or "").strip())
                        or os.path.basename(str(cloud_path).rstrip("/"))
                        or "upload.zip"
                    )
                    register_existing_cloud_reference(
                        session_id=db_session_id,
                        artifact_kind=ARTIFACT_BATCH_ZIP,
                        original_filename=zip_name,
                        storage_provider=cloud_storage_type or storage_type,
                        cloud_path=cloud_path,
                    )
                elif original_zip_path:
                    mirror_local_artifact(
                        session_id=db_session_id,
                        local_path=original_zip_path,
                        original_filename=os.path.basename(original_zip_path),
                        artifact_kind=ARTIFACT_BATCH_ZIP,
                        storage_mode=storage_mode,
                    )

                if msf_path and os.path.exists(msf_path):
                    mirror_local_artifact(
                        session_id=db_session_id,
                        local_path=msf_path,
                        original_filename=os.path.basename(msf_path),
                        artifact_kind=ARTIFACT_MSF,
                        storage_mode=storage_mode,
                    )
        except Exception as mirror_exc:
            db.session.rollback()
            logger.warning("Failed to persist Cloud Storage mirror metadata for session %s: %s", db_session_id, mirror_exc)

        # Start Coordinator Task
        from tasks import start_upload_coordinator
        task = start_upload_coordinator.delay(
            session_id=db_session_id,
            zip_path=original_zip_path,
            msf_path=msf_path,
            storage_mode=storage_mode,
            msf_parse_options=msf_parse_options,
            input_directory_path=input_directory_path  # Pass the resolved directory path
        )

        metadata_persisted = True
        try:
            queued_progress = {
                "current_stage": "queued",
                "status_message": "Upload job queued",
                "current_index": 0,
                "total_files": 0,
                "processed_count": 0,
                "failed_count": 0,
                "percent": 0,
                "updated_at": datetime.utcnow().isoformat(),
            }
            if submit_token:
                _upsert_session_metadata(db_session_id, UPLOAD_SUBMIT_TOKEN_FIELD, submit_token)
            _upsert_session_metadata(db_session_id, UPLOAD_STORAGE_MODE_FIELD, str(storage_mode))
            _upsert_session_metadata(db_session_id, UPLOAD_TASK_ID_FIELD, task.id)
            _upsert_session_metadata(db_session_id, UPLOAD_PROGRESS_FIELD, json.dumps(queued_progress))
            db.session.commit()
        except Exception as meta_exc:
            metadata_persisted = False
            db.session.rollback()
            logger.error(
                "Failed to persist upload idempotency metadata for session %s: %s",
                db_session_id,
                meta_exc,
                exc_info=True,
            )

        return APIResponse.accepted(
            message="Upload processing started in background.",
            data={
                "task_id": task.id,
                "session_id": db_session_id,
                "submit_token": submit_token,
                "reused": False,
                "idempotency_metadata_saved": metadata_persisted,
                "hpc_allocation": attached_hpc_allocation,
                "session": _serialize_session_context(created_session) if created_session else None,
                "msf_preflight": {
                    "is_valid": msf_preflight_report.get("is_valid"),
                    "actions": msf_preflight_report.get("actions", []),
                    "warnings": msf_preflight_report.get("warnings", []),
                    "summary": msf_preflight_report.get("summary", {}),
                    "patched_msf_path": msf_preflight_report.get("patched_msf_path"),
                } if isinstance(msf_preflight_report, dict) else None,
            }
        )

    except (SecurityError, ValidationError, zipfile.BadZipFile) as e:
        logger.warning(f"Rejected unsafe session upload: {e}")
        if extract_dir_to_cleanup:
            shutil.rmtree(extract_dir_to_cleanup, ignore_errors=True)
        return APIResponse.validation_error(str(e))
    except Exception as e:
        logger.error(f"Error initiating session: {e}", exc_info=True)
        if extract_dir_to_cleanup:
            shutil.rmtree(extract_dir_to_cleanup, ignore_errors=True)
        return APIResponse.error(str(e), 500)
    finally:
        # Final cleanup of empty temp directory after files were moved
        if extract_dir_to_cleanup and os.path.exists(extract_dir_to_cleanup):
            shutil.rmtree(extract_dir_to_cleanup, ignore_errors=True)

    # Fallback if no conditions matched
    return APIResponse.error("Invalid request parameters", 400)


@session_bp.route("/tasks/<task_id>", methods=["GET"])
@jwt_required()
def get_task_status(task_id):
    """
    Get the status of a background task.
    """
    from celery_app import celery
    task = celery.AsyncResult(task_id)

    if task.state == 'PENDING':
        response = {
            'state': task.state,
            'progress': 0,
            'status': 'Pending...'
        }
    elif task.state != 'FAILURE':
        response = {
            'state': task.state,
            'progress': task.info.get('progress', 0) if task.info else 0,
            'status': task.info.get('status', '') if task.info else '',
            'error': task.info.get('error', '') if task.info else None,
            'result': task.info.get('result', '') if 'result' in task.info else None
        }
        if 'result' in task.info:
            response['result'] = task.info['result']
    else:
        # something went wrong in the background job
        response = {
            'state': task.state,
            'progress': 100,
            'status': str(task.info),  # this is the exception raised
            'error': str(task.info)
        }

    return APIResponse.success(data=response)


@session_bp.route("/directory/recover", methods=["POST"])
@jwt_required()
def recover_directory_submission():
    """
    Recover an in-flight directory upload context from an idempotency submit token.
    """
    payload = request.get_json(silent=True) or {}
    token_raw = payload.get("submit_token") or request.headers.get("X-Upload-Submit-Token")
    try:
        submit_token = _normalize_submit_token(token_raw)
    except ValidationError as exc:
        return APIResponse.validation_error(str(exc))

    if not submit_token:
        return APIResponse.validation_error("submit_token is required")

    user_id = int(get_jwt_identity())
    context = _get_upload_submission_context(user_id=user_id, submit_token=submit_token)
    if not context:
        return APIResponse.not_found("No upload submission found for submit_token")

    return APIResponse.success(
        data=_build_upload_recovery_payload(context, include_task_state=True),
        message="Recovered upload submission context.",
    )


@session_bp.route("/<int:session_id>/cloud-downloads", methods=["GET"])
@jwt_required()
def list_session_cloud_downloads(session_id):
    """List owner-only Cloud Storage downloads for uploaded source artifacts."""
    try:
        session, user, error_response = get_session_with_permission(session_id, permission="view")
        if error_response:
            return error_response
        if not can_download_hdpc(session, user):
            return APIResponse.not_found("Session not found")

        metadata_fields = _get_session_metadata_map([session_id], {UPLOAD_STORAGE_MODE_FIELD}).get(session_id, {})
        storage_mode = metadata_fields.get(UPLOAD_STORAGE_MODE_FIELD)
        payload = build_session_cloud_download_payload(session, storage_mode=storage_mode, check_availability=True)
        db.session.commit()
        return APIResponse.success(data=payload)
    except Exception as exc:
        db.session.rollback()
        logger.error("Failed to list cloud downloads for session %s: %s", session_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to check Cloud Storage downloads")


@session_bp.route("/<int:session_id>/cloud-downloads/<int:mirror_id>", methods=["GET"])
@jwt_required()
def download_session_cloud_mirror(session_id, mirror_id):
    """Redirect the owner to a temporary provider download URL for a mirrored artifact."""
    try:
        session, user, error_response = get_session_with_permission(session_id, permission="view")
        if error_response:
            return error_response
        if not can_download_hdpc(session, user):
            return APIResponse.not_found("Session not found")

        mirror = CloudMirrorObject.query.filter_by(id=mirror_id, session_id=session_id).first()
        if not mirror:
            return APIResponse.not_found("Cloud download not found")
        if mirror.status != "available" or not mirror.storage_provider or not mirror.cloud_path:
            return APIResponse.error(
                "CLOUD_DOWNLOAD_UNAVAILABLE",
                mirror.error or "Cloud download is not available for this artifact.",
                409,
            )

        from services.cloud_upload_service import CloudUploadService

        available, availability_message = CloudUploadService.check_cloud_object_available(
            mirror.cloud_path,
            mirror.storage_provider,
        )
        if not available:
            return APIResponse.error(
                "CLOUD_DOWNLOAD_UNAVAILABLE",
                availability_message,
                503,
                details={"mirror_id": mirror.id, "storage_provider": mirror.storage_provider},
            )

        download_url = CloudUploadService.get_file_download_url(mirror.cloud_path, mirror.storage_provider)
        if not download_url:
            return APIResponse.error(
                "CLOUD_DOWNLOAD_UNAVAILABLE",
                "Could not create a provider download URL for this artifact.",
                503,
                details={"mirror_id": mirror.id, "storage_provider": mirror.storage_provider},
            )

        record_audit_event(
            actor_user_id=user.id,
            institution_id=session.institution_id,
            session_id=session.id,
            event_type="cloud_mirror_downloaded",
            entity_type="cloud_mirror_object",
            entity_id=mirror.id,
            details={
                "artifact_kind": mirror.artifact_kind,
                "original_filename": mirror.original_filename,
                "storage_provider": mirror.storage_provider,
            },
        )
        db.session.commit()

        if str(request.args.get("as_json") or "").strip().lower() in {"1", "true", "yes"}:
            return APIResponse.success(
                data={
                    "download_url": download_url,
                    "mirror": mirror.to_dict(),
                }
            )
        return redirect(download_url, code=302)
    except Exception as exc:
        db.session.rollback()
        logger.error("Failed to create cloud download for session %s mirror %s: %s", session_id, mirror_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to create Cloud Storage download")


@session_bp.route("/<int:session_id>/hdpc", methods=["GET"])
@jwt_required()
def download_hdpc_file(session_id):
    """Securely download the .hdpc file for a user's session"""
    try:
        session, user, error_response = get_session_with_permission(session_id, permission="view")
        if error_response:
            return error_response
        if not can_download_hdpc(session, user):
            return APIResponse.not_found("Session not found")

        metadata_fields = _get_session_metadata_map([session_id], {WORKFLOW_STATE_FIELD, UPLOAD_PROGRESS_FIELD}).get(session_id, {})
        session_state, _, _ = _resolve_session_state(session, metadata_fields)
        if not is_downloadable_session_state(session_state):
            logger.warning(
                f"User {user.id} tried to download .hdpc for session {session_id} with status {session.status}"
            )
            return APIResponse.error(
                "DOWNLOAD_NOT_ALLOWED", f"File cannot be downloaded. Session status is '{session.status}'.", 400
            )

        hdpc_full_path = session.hdpc_path
        if not hdpc_full_path:
            return APIResponse.not_found(".hdpc file path not recorded for this session")

        # Add a check to make sure the file actually exists before serving
        if not os.path.exists(hdpc_full_path):
            logger.error(
                f"File not found on disk for session {session_id}: {hdpc_full_path}. Status was '{session.status}'."
            )
            # If status was active/completed, this is a server error.
            return APIResponse.server_error(
                "File not found on server disk, though session was marked as valid. Please contact support."
            )

        logger.info(f"User {user.id} downloading .hdpc file: {hdpc_full_path}")

        # Use send_file, which takes the full, absolute path.
        return send_file(hdpc_full_path, as_attachment=True, download_name=f"session_{session_id}.hdpc")

    except Exception as e:
        logger.error(f"Failed to download .hdpc for session {session_id}: {e}", exc_info=True)
        return APIResponse.server_error("Failed to download file")


@session_bp.route("/<int:session_id>/hdpc/shared", methods=["GET"])
@jwt_required()
def download_shared_hdpc_file(session_id):
    """Download a sanitized institution-safe .hdpc export for a shared session."""
    export_path = None
    try:
        session, user, error_response = get_session_with_permission(session_id, permission="view")
        if error_response:
            return error_response
        if not can_download_shared_hdpc(session, user):
            return APIResponse.not_found("Session not found")

        metadata_fields = _get_session_metadata_map([session_id], {WORKFLOW_STATE_FIELD, UPLOAD_PROGRESS_FIELD}).get(session_id, {})
        session_state, _, _ = _resolve_session_state(session, metadata_fields)
        if not is_downloadable_session_state(session_state):
            return APIResponse.error(
                "DOWNLOAD_NOT_ALLOWED",
                f"Shared export cannot be downloaded while session status is '{session.status}'.",
                400,
            )

        resolved_hdpc_path = _resolve_existing_hdpc_path(session.hdpc_path)
        if not resolved_hdpc_path:
            return APIResponse.error(
                "SOURCE_UNAVAILABLE",
                "Session project file (.hdpc) is not available on this backend instance.",
                503,
                details={"session_id": session_id, "source_state": "hdpc_unavailable"},
            )

        provenance = build_hdpc_provenance(
            user=session.user,
            session=session,
            institution=session.institution if getattr(session, "institution", None) else None,
        )
        export_path = create_sanitized_shared_export(
            resolved_hdpc_path,
            source_session_id=session.id,
            source_institution_id=int(session.institution_id or 0),
            source_owner_user_id=int(session.user_id),
            source_owner_user_public_id=provenance.get("creator_user_public_id"),
            source_owner_profile_url=provenance.get("creator_profile_url"),
            source_institution_public_id=provenance.get("institution_public_id"),
            source_institution_profile_url=provenance.get("institution_profile_url"),
        )
        record_audit_event(
            actor_user_id=user.id,
            institution_id=session.institution_id,
            session_id=session.id,
            event_type="hdpc_shared_export_downloaded",
            entity_type="session",
            entity_id=session.id,
            details={
                "artifact_kind": SHARED_EXPORT_ARTIFACT_KIND,
                "access_mode": str(getattr(session, "access_mode", None) or "full"),
            },
        )
        db.session.commit()

        response = send_file(
            export_path,
            as_attachment=True,
            download_name=f"session_{session_id}_shared.hdpc",
        )

        @response.call_on_close
        def _cleanup_export() -> None:
            try:
                if export_path and os.path.exists(export_path):
                    os.remove(export_path)
            except OSError:
                logger.warning("Failed to remove temporary shared export %s", export_path)

        return response
    except Exception as exc:
        if export_path and os.path.exists(export_path):
            try:
                os.remove(export_path)
            except OSError:
                logger.warning("Failed to remove temporary shared export %s", export_path)
        logger.error("Failed to download shared .hdpc export for session %s: %s", session_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to download shared export")


@session_bp.route("/<int:session_id>/project-summary", methods=["GET"])
@jwt_required()
def get_session_project_summary(session_id):
    try:
        user_id = int(get_jwt_identity())
        _, resolved_hdpc_path, error_response = _get_session_with_hdpc_access(session_id, user_id)
        if error_response is not None:
            return error_response

        inspect_data = inspect_hdpc_project(resolved_hdpc_path, show_files=False)
        return APIResponse.success(
            data={
                "project_info": read_hdpc_project_info(resolved_hdpc_path) or {},
                "project_statistics": read_hdpc_project_stats(resolved_hdpc_path),
                "file_scan_settings": inspect_data.get("file_scan_settings") or [],
                "configuration": inspect_data.get("configuration") or [],
                "published_records": inspect_data.get("published_records") or [],
            }
        )
    except Exception as exc:
        logger.error("Failed to retrieve project summary for session %s: %s", session_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to retrieve session project summary")


@session_bp.route("/<int:session_id>/published-records", methods=["GET"])
@jwt_required()
def get_session_published_records(session_id):
    try:
        user_id = int(get_jwt_identity())
        _, resolved_hdpc_path, error_response = _get_session_with_hdpc_access(session_id, user_id)
        if error_response is not None:
            return error_response
        return APIResponse.success(data={"records": read_hdpc_published_records(resolved_hdpc_path)})
    except Exception as exc:
        logger.error("Failed to retrieve published records for session %s: %s", session_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to retrieve published records")


@session_bp.route("/<int:session_id>/files", methods=["GET"])
@jwt_required()
def list_session_project_files(session_id):
    try:
        user_id = int(get_jwt_identity())
        _, resolved_hdpc_path, error_response = _get_session_with_hdpc_access(session_id, user_id)
        if error_response is not None:
            return error_response
        page = request.args.get("page", default=1, type=int)
        limit = request.args.get("limit", default=25, type=int)
        search = request.args.get("search", default=None, type=str)
        payload = read_hdpc_source_files(resolved_hdpc_path, page=page, limit=limit, search=search)
        return APIResponse.success(data=payload)
    except Exception as exc:
        logger.error("Failed to list source files for session %s: %s", session_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to list source files")


@session_bp.route("/<int:session_id>/files/<int:file_id>/hierarchy", methods=["GET"])
@jwt_required()
def get_session_file_hierarchy(session_id, file_id):
    try:
        user_id = int(get_jwt_identity())
        _, resolved_hdpc_path, error_response = _get_session_with_hdpc_access(session_id, user_id)
        if error_response is not None:
            return error_response
        hierarchy = read_hdpc_file_hierarchy(resolved_hdpc_path, file_id)
        if hierarchy is None:
            return APIResponse.not_found("File not found in this session")
        return APIResponse.success(data={"hierarchy": hierarchy})
    except Exception as exc:
        logger.error(
            "Failed to retrieve file hierarchy for session %s file %s: %s",
            session_id,
            file_id,
            exc,
            exc_info=True,
        )
        return APIResponse.server_error("Failed to retrieve file hierarchy")


@session_bp.route("/<int:session_id>/records/<int:local_record_id>/files", methods=["GET"])
@jwt_required()
def get_session_record_files(session_id, local_record_id):
    try:
        user_id = int(get_jwt_identity())
        _, resolved_hdpc_path, error_response = _get_session_with_hdpc_access(session_id, user_id)
        if error_response is not None:
            return error_response
        files = read_hdpc_record_files(resolved_hdpc_path, local_record_id)
        return APIResponse.success(data={"record_id": local_record_id, "files": files})
    except Exception as exc:
        logger.error(
            "Failed to retrieve record files for session %s record %s: %s",
            session_id,
            local_record_id,
            exc,
            exc_info=True,
        )
        return APIResponse.server_error("Failed to retrieve record files")


@session_bp.route("/<int:session_id>/records/<int:local_record_id>/traceability", methods=["GET"])
@jwt_required()
def get_session_record_traceability(session_id, local_record_id):
    try:
        user_id = int(get_jwt_identity())
        _, resolved_hdpc_path, error_response = _get_session_with_hdpc_access(session_id, user_id)
        if error_response is not None:
            return error_response
        traceability = read_hdpc_record_traceability(resolved_hdpc_path, local_record_id)
        if traceability is None:
            return APIResponse.not_found("Record not found in this session")
        return APIResponse.success(data=traceability)
    except Exception as exc:
        logger.error(
            "Failed to retrieve traceability for session %s record %s: %s",
            session_id,
            local_record_id,
            exc,
            exc_info=True,
        )
        return APIResponse.server_error("Failed to retrieve record traceability")


@session_bp.route("/<int:session_id>/versioning/match-files", methods=["POST"])
@jwt_required()
def match_session_files_for_versioning(session_id):
    try:
        session_row, _, error_response = get_session_with_permission(
            session_id,
            permission="edit",
            require_mutable=True,
        )
        if error_response is not None:
            return error_response
        resolved_hdpc_path = _resolve_existing_hdpc_path(session_row.hdpc_path)
        if not resolved_hdpc_path:
            return APIResponse.error(
                "SOURCE_UNAVAILABLE",
                "Session project file (.hdpc) is not available on this backend instance.",
                503,
                details={"session_id": session_id, "source_state": "hdpc_unavailable"},
            )

        payload = request.get_json(silent=True) or {}
        directory_path = payload.get("directory_path")
        match_method = str(payload.get("match_method") or "filename").strip().lower() or "filename"
        if match_method not in {"filename", "hashcode"}:
            return APIResponse.validation_error("match_method must be either 'filename' or 'hashcode'")
        try:
            matches = match_hdpc_files_for_versioning(
                resolved_hdpc_path,
                directory_path=directory_path,
                match_method=match_method,
            )
        except ValueError as exc:
            return APIResponse.validation_error(str(exc))
        except FileNotFoundError:
            return APIResponse.not_found(f"Directory not found: {directory_path}")
        return APIResponse.success(data={"matches": matches})
    except Exception as exc:
        logger.error("Failed to match files for versioning in session %s: %s", session_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to match files for versioning")


@session_bp.route("/<int:session_id>/concepts/<concept_rec_id>/latest-files", methods=["GET"])
@jwt_required()
def get_session_latest_concept_files(session_id, concept_rec_id):
    try:
        user_id = int(get_jwt_identity())
        _, resolved_hdpc_path, error_response = _get_session_with_hdpc_access(session_id, user_id)
        if error_response is not None:
            return error_response
        is_sandbox = request.args.get("is_sandbox", "true").strip().lower() == "true"
        payload = read_hdpc_latest_published_record_files(
            resolved_hdpc_path,
            concept_rec_id=concept_rec_id,
            is_sandbox=is_sandbox,
        )
        if payload is None:
            return APIResponse.not_found("No published record found for this concept")
        return APIResponse.success(data=payload)
    except Exception as exc:
        logger.error(
            "Failed to retrieve latest files for session %s concept %s: %s",
            session_id,
            concept_rec_id,
            exc,
            exc_info=True,
        )
        return APIResponse.server_error("Failed to retrieve latest concept files")


@session_bp.route("/<int:session_id>/zenodo/uploadable-files", methods=["GET"])
@jwt_required()
def get_session_uploadable_files(session_id):
    try:
        user_id = int(get_jwt_identity())
        _, resolved_hdpc_path, error_response = _get_session_with_hdpc_access(session_id, user_id)
        if error_response is not None:
            return error_response
        is_sandbox_for_drafts = request.args.get("is_sandbox_for_drafts", "true").strip().lower() == "true"
        items = read_hdpc_uploadable_files(
            resolved_hdpc_path,
            is_sandbox_for_drafts=is_sandbox_for_drafts,
        )
        return APIResponse.success(data={"items": items})
    except Exception as exc:
        logger.error("Failed to retrieve uploadable files for session %s: %s", session_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to retrieve uploadable files")


@session_bp.route("/<int:session_id>/zenodo/uploads-by-tab", methods=["GET"])
@jwt_required()
def get_session_uploads_by_tab(session_id):
    try:
        user_id = int(get_jwt_identity())
        _, resolved_hdpc_path, error_response = _get_session_with_hdpc_access(session_id, user_id)
        if error_response is not None:
            return error_response

        tab_id = request.args.get("tab_id", "pending_preparation")
        is_sandbox = request.args.get("is_sandbox", "true").strip().lower() == "true"
        search_term = request.args.get("search")
        title_pattern = request.args.get("title_pattern")
        date_since = request.args.get("date_since")
        date_until = request.args.get("date_until")

        try:
            items = read_hdpc_uploads_by_tab(
                resolved_hdpc_path,
                tab_id=tab_id,
                is_sandbox=is_sandbox,
                search_term=search_term,
                title_pattern=title_pattern,
                date_since=date_since,
                date_until=date_until,
            )
        except ValueError as exc:
            return APIResponse.validation_error(str(exc))

        return APIResponse.success(data={"tab_id": tab_id, "items": items})
    except Exception as exc:
        logger.error("Failed to retrieve uploads-by-tab for session %s: %s", session_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to retrieve uploads by tab")


@session_bp.route("/<int:session_id>/records/<int:local_record_id>/discard-draft", methods=["POST"])
@jwt_required()
def discard_session_draft(session_id, local_record_id):
    try:
        session, _, error_response = get_session_with_permission(
            session_id,
            permission="edit",
            require_mutable=True,
        )
        if error_response is not None:
            return error_response
        resolved_hdpc_path = _resolve_existing_hdpc_path(session.hdpc_path)
        if not resolved_hdpc_path:
            return APIResponse.error(
                "SOURCE_UNAVAILABLE",
                "Session project file (.hdpc) is not available on this backend instance.",
                503,
                details={"session_id": session_id, "source_state": "hdpc_unavailable"},
            )

        environment = session.default_zenodo_environment or "sandbox"
        raw_is_sandbox = request.args.get("is_sandbox")
        if raw_is_sandbox is not None:
            environment = "sandbox" if str(raw_is_sandbox).strip().lower() == "true" else "production"
        token_context = publishing_context_service.resolve_token_for_session(session, environment)
        result = discard_local_zenodo_draft(
            resolved_hdpc_path,
            local_record_id,
            access_token=token_context.get("token"),
        )
        if not result.get("success"):
            error_code = str(result.get("error_code") or "").strip().lower()
            if error_code == "not_found":
                return APIResponse.not_found(result.get("error") or "Record not found in this session")
            if error_code == "invalid_state":
                return APIResponse.validation_error(result.get("error") or "Record is not an active draft")
            return APIResponse.server_error(result.get("error") or "Failed to discard draft")

        return APIResponse.success(data=result)
    except Exception as exc:
        logger.error(
            "Failed to discard draft for session %s record %s: %s",
            session_id,
            local_record_id,
            exc,
            exc_info=True,
        )
        return APIResponse.server_error("Failed to discard draft")


@session_bp.route("/<int:session_id>/workspace-summary", methods=["GET"])
@jwt_required()
def get_session_workspace_summary(session_id):
    try:
        user_id = int(get_jwt_identity())
        session, resolved_hdpc_path, error_response = _get_session_with_hdpc_access(session_id, user_id)
        if error_response is not None:
            return error_response

        is_sandbox = request.args.get("is_sandbox", "true").strip().lower() == "true"
        summary = read_hdpc_workspace_summary(resolved_hdpc_path, is_sandbox=is_sandbox)
        latest_submission = Submission.query.filter_by(session_id=session_id).order_by(Submission.created_at.desc()).first()
        workflow_state_record = db.session.query(UserMetadata).filter_by(
            session_id=session_id,
            field_name=WORKFLOW_STATE_FIELD,
        ).first()
        workflow_state = _parse_workflow_state(workflow_state_record.field_value if workflow_state_record else None)
        metadata_record = db.session.query(UserMetadata).filter_by(
            session_id=session_id,
            field_name="zenodo_metadata_draft",
        ).first()
        shared_metadata = _parse_json(metadata_record.field_value if metadata_record else None, {})
        shared_metadata = shared_metadata if isinstance(shared_metadata, dict) else {}
        lod_mapping = shared_metadata.get("lod_mapping") if isinstance(shared_metadata.get("lod_mapping"), dict) else {}

        return APIResponse.success(
            data={
                "session": {
                    **_serialize_session_context(session),
                    "hdpc_path": resolved_hdpc_path,
                },
                "submission": {
                    "id": latest_submission.id,
                    "status": latest_submission.status,
                    "pipeline_id": latest_submission.pipeline_id,
                    "created_at": latest_submission.created_at.isoformat() if latest_submission.created_at else None,
                    "completed_at": latest_submission.completed_at.isoformat() if latest_submission.completed_at else None,
                }
                if latest_submission
                else None,
                "workflow": workflow_state,
                "provenance": {
                    "msf_path": shared_metadata.get("msf_path"),
                    "mapping_field_count": len(lod_mapping),
                    "mapping_fields": sorted(lod_mapping.keys()),
                    "shared_metadata_keys": sorted(
                        [
                            key
                            for key in shared_metadata.keys()
                            if not str(key).startswith("_")
                            and not str(key).startswith("edm_")
                            and key not in INTERNAL_ZENODO_KEYS
                        ]
                    ),
                },
                **summary,
            }
        )
    except Exception as exc:
        logger.error("Failed to retrieve workspace summary for session %s: %s", session_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to retrieve session workspace summary")


@session_bp.route("/<int:session_id>/records/<int:local_record_id>/lineage", methods=["GET"])
@jwt_required()
def get_session_record_lineage(session_id, local_record_id):
    try:
        user_id = int(get_jwt_identity())
        session, resolved_hdpc_path, error_response = _get_session_with_hdpc_access(session_id, user_id)
        if error_response is not None:
            return error_response
        lineage = read_hdpc_record_lineage(resolved_hdpc_path, local_record_id)
        if lineage is None:
            return APIResponse.not_found("Record not found in this session")
        return APIResponse.success(
            data={
                "session": _serialize_session_context(session),
                "lineage": lineage,
            }
        )
    except Exception as exc:
        logger.error("Failed to retrieve lineage for session %s record %s: %s", session_id, local_record_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to retrieve record lineage")


@session_bp.route("/<int:session_id>/records/<int:local_record_id>/zenodo-status", methods=["GET"])
@jwt_required()
def get_session_record_zenodo_status(session_id, local_record_id):
    try:
        user_id = int(get_jwt_identity())
        session, resolved_hdpc_path, error_response = _get_session_with_hdpc_access(session_id, user_id)
        if error_response is not None:
            return error_response
        status_payload = read_hdpc_record_zenodo_status(resolved_hdpc_path, local_record_id)
        if status_payload is None:
            return APIResponse.not_found("Record not found in this session")
        return APIResponse.success(
            data={
                "session": _serialize_session_context(session),
                "zenodo_status": status_payload,
            }
        )
    except Exception as exc:
        logger.error("Failed to retrieve Zenodo status for session %s record %s: %s", session_id, local_record_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to retrieve record Zenodo status")


@session_bp.route("/<int:session_id>/operations/summary", methods=["GET"])
@jwt_required()
def get_session_operations_summary(session_id):
    try:
        user_id = int(get_jwt_identity())
        session, resolved_hdpc_path, error_response = _get_session_with_hdpc_access(session_id, user_id)
        if error_response is not None:
            return error_response
        is_sandbox = request.args.get("is_sandbox", "true").strip().lower() == "true"
        payload = read_hdpc_operations_summary(resolved_hdpc_path, is_sandbox=is_sandbox)
        return APIResponse.success(
            data={
                "session": _serialize_session_context(session),
                **payload,
            }
        )
    except Exception as exc:
        logger.error("Failed to retrieve operations summary for session %s: %s", session_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to retrieve session operations summary")


@session_bp.route("/<int:session_id>/batch-operations", methods=["POST"])
@jwt_required()
def create_session_batch_operation(session_id):
    try:
        session, user, error_response = get_session_with_permission(
            session_id,
            permission="edit",
            require_mutable=True,
        )
        if error_response is not None:
            return error_response
        resolved_hdpc_path = _resolve_existing_hdpc_path(session.hdpc_path)
        if not resolved_hdpc_path:
            return APIResponse.error(
                "SOURCE_UNAVAILABLE",
                "Session project file (.hdpc) is not available on this backend instance.",
                503,
                details={"session_id": session_id, "source_state": "hdpc_unavailable"},
            )

        payload = request.get_json(silent=True) or {}
        operation_type = str(payload.get("operation_type") or "").strip().lower()
        options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
        requested_ids = payload.get("target_ids") if isinstance(payload.get("target_ids"), list) else []
        is_sandbox = bool(options.get("is_sandbox", True))
        summary = read_hdpc_operations_summary(resolved_hdpc_path, is_sandbox=is_sandbox)
        operation_payload = (summary.get("actionable_operations") or {}).get(operation_type) or {}
        eligible_ids = [int(item) for item in operation_payload.get("target_ids") or [] if str(item).isdigit()]
        target_ids = [int(item) for item in requested_ids if str(item).isdigit()] if requested_ids else eligible_ids

        if operation_type not in {"create_drafts", "discard_drafts", "upload_files", "publish_records", "remove_files"}:
            return APIResponse.validation_error("Unsupported operation_type")
        if not target_ids:
            return APIResponse.validation_error("No eligible target_ids available for this operation")
        invalid_ids = sorted(set(target_ids) - set(eligible_ids))
        if invalid_ids:
            return APIResponse.validation_error(
                "Some target_ids are not eligible for this operation",
                details={"invalid_target_ids": invalid_ids},
            )

        from tasks import execute_session_batch_operation_task

        task = execute_session_batch_operation_task.delay(
            session_id=session.id,
            operation_type=operation_type,
            target_ids=target_ids,
            options=options,
            requested_by_user_id=user.id,
        )
        record_session_batch_task_launch(
            task_id=task.id,
            session_id=session.id,
            operation_type=operation_type,
            target_ids=target_ids,
            options=options,
            requested_by_user_id=user.id,
            requested_by_email=getattr(user, "email", None),
        )
        return APIResponse.accepted(
            data={
                "task_id": task.id,
                "session_id": session.id,
                "operation_type": operation_type,
                "target_ids": target_ids,
                "eligible_count": len(eligible_ids),
            },
            message="Session batch operation queued",
        )
    except Exception as exc:
        logger.error("Failed to queue session batch operation for session %s: %s", session_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to queue session batch operation")


@session_bp.route("/<int:session_id>/batch-operations", methods=["GET"])
@jwt_required()
def list_session_batch_operations(session_id):
    try:
        user_id = int(get_jwt_identity())
        session, _, error_response = _get_session_with_hdpc_access(session_id, user_id)
        if error_response is not None and getattr(error_response, "status_code", None) != 503:
            return error_response
        limit = request.args.get("limit", default=20, type=int)
        return APIResponse.success(
            data={
                "session": _serialize_session_context(session) if session else {"id": session_id},
                "tasks": list_session_batch_task_entries(session_id=session_id, limit=limit),
            }
        )
    except Exception as exc:
        logger.error("Failed to list batch operations for session %s: %s", session_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to list session batch operations")


@session_bp.route("/<int:session_id>/batch-operations/<task_id>", methods=["GET"])
@jwt_required()
def get_session_batch_operation_task(session_id, task_id):
    try:
        user_id = int(get_jwt_identity())
        session, _, error_response = _get_session_with_hdpc_access(session_id, user_id)
        if error_response is not None and getattr(error_response, "status_code", None) != 503:
            return error_response

        history_entry = get_session_batch_task_entry(task_id)
        if history_entry and int(history_entry.get("session_id") or 0) != int(session_id):
            return APIResponse.not_found("Batch task not found in this session")

        from celery_app import celery

        task = celery.AsyncResult(task_id)
        info = task.info if isinstance(task.info, dict) else {}
        if task.state == "PENDING":
            data = _session_batch_task_payload_from_history(history_entry)
        elif task.state == "FAILURE":
            data = {
                "state": task.state,
                "status": str(task.info),
                "progress": info.get("progress") if isinstance(info.get("progress"), dict) else None,
                "result": None,
                "error": str(task.info),
            }
        elif task.state == "SUCCESS":
            result = task.result if isinstance(task.result, dict) else {}
            data = {
                "state": task.state,
                "status": result.get("status") or "completed",
                "progress": result.get("progress"),
                "result": result or (history_entry.get("result") if history_entry else None),
                "error": None,
            }
        else:
            data = {
                "state": task.state,
                "status": info.get("status") or "Processing",
                "progress": info.get("progress") if isinstance(info.get("progress"), dict) else None,
                "result": info.get("result"),
                "error": info.get("error"),
            }

        if history_entry or task.state != "PENDING":
            update_session_batch_task_entry(
                task_id,
                state=data.get("state"),
                status=data.get("status"),
                progress=data.get("progress") if isinstance(data.get("progress"), dict) else None,
                result=data.get("result") if isinstance(data.get("result"), dict) else None,
                error=data.get("error"),
            )
        return APIResponse.success(
            data={
                "session": _serialize_session_context(session) if session else {"id": session_id},
                **data,
            }
        )
    except Exception as exc:
        logger.error("Failed to retrieve batch task %s for session %s: %s", task_id, session_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to retrieve session batch task")


@session_bp.route("/<int:session_id>/records", methods=["GET"])
@jwt_required()
def get_session_records(session_id):
    """
    Return all Zenodo records created in a session with file inclusion and provenance details.
    Accessible to session owner, moderators, and admins.
    """
    try:
        user_id = int(get_jwt_identity())
        session = db.session.get(DBSession, session_id)
        if not session:
            return APIResponse.not_found("Session not found")

        user = db.session.get(User, user_id)
        if not can_view_session(session, user):
            return APIResponse.not_found("Session not found")
        context = _build_session_record_common_context(session)
        resolved_hdpc_path = _resolve_existing_hdpc_path(session.hdpc_path)
        if not resolved_hdpc_path:
            return APIResponse.success(
                data=_build_empty_session_records_payload(
                    session,
                    context,
                    source_state="hdpc_unavailable",
                    warning_message="Session project file (.hdpc) is not available on this backend instance.",
                )
            )

        inventory = read_session_record_inventory(session)
        source_state = str(inventory.get("source_state") or "ok")
        if source_state == "zenodo_table_missing":
            return APIResponse.success(
                data=_build_empty_session_records_payload(
                    session,
                    context,
                    source_state="zenodo_table_missing",
                    warning_message="No zenodo_records table found in project database.",
                )
            )

        return APIResponse.success(data=_build_session_records_payload(session, inventory, context))
    except sqlite3.Error as exc:
        logger.error(f"SQLite error reading session records for {session_id}: {exc}", exc_info=True)
        return APIResponse.server_error(f"Database error while reading .hdpc file: {exc}")
    except Exception as exc:
        logger.error(f"Failed to retrieve session records for {session_id}: {exc}", exc_info=True)
        return APIResponse.server_error("Failed to retrieve session records")


@session_bp.route("/<int:session_id>/records/<int:local_record_id>", methods=["GET"])
@jwt_required()
def get_session_record_detail(session_id, local_record_id):
    """
    Get detailed view of a single local Zenodo record within a session.
    """
    try:
        user_id = int(get_jwt_identity())
        session, resolved_hdpc_path, error_response = _get_session_with_hdpc_access(session_id, user_id)
        if error_response is not None:
            return error_response

        context = _build_session_record_common_context(session)
        inventory = read_session_record_inventory(session)
        source_state = str(inventory.get("source_state") or "ok")
        if source_state != "ok":
            message = (
                "No zenodo_records table found in project database."
                if source_state == "zenodo_table_missing"
                else "Session project file (.hdpc) is not available on this backend instance."
            )
            return APIResponse.error(
                "SOURCE_UNAVAILABLE",
                message,
                503,
                details={"source_state": source_state, "session_id": session_id},
            )

        base_record = next(
            (
                item
                for item in (inventory.get("visible_records") or [])
                if int(item.get("local_record_id") or 0) == int(local_record_id)
            ),
            None,
        )
        if base_record is None:
            return APIResponse.not_found("Record not found in this session")
        record, _ = _build_session_record_payload(session, base_record, context)

        sibling_records = [
            item
            for item in (inventory.get("visible_records") or [])
            if int(item.get("local_record_id") or 0) != int(local_record_id)
        ]
        same_concept = [
            {
                "local_record_id": int(item.get("local_record_id") or 0),
                "record_title": item.get("record_title"),
                "record_status": item.get("record_status"),
                "zenodo_record_id": item.get("zenodo_record_id"),
            }
            for item in sibling_records
            if record.get("concept_rec_id")
            and item.get("concept_rec_id")
                and str(item.get("concept_rec_id")) == str(record.get("concept_rec_id"))
        ]

        files = record.get("files") or []
        uploaded_files = [f for f in files if (f.get("upload_status") or "").lower() in {"uploaded", "success"}]
        record_context = read_hdpc_record_context(resolved_hdpc_path, local_record_id)
        if record_context is None:
            return APIResponse.not_found("Record not found in this session")

        return APIResponse.success(
            data={
                "session": _serialize_session_context(session),
                "submission": context.get("submission"),
                "record": record,
                "lineage": record_context.get("lineage"),
                "zenodo_status": record_context.get("zenodo_status"),
                "related_records": {
                    "same_concept": same_concept,
                    "total_siblings": len(sibling_records),
                },
                "health": {
                    "has_record_link": bool(record.get("record_link")),
                    "has_doi": bool(record.get("zenodo_doi")),
                    "has_source_file": bool(record.get("source_file_name")),
                    "has_mapped_metadata": bool((record.get("provenance") or {}).get("mapping_field_count", 0) > 0),
                    "total_files": len(files),
                    "uploaded_files": len(uploaded_files),
                    "has_processing_error": bool((record.get("processing") or {}).get("error")),
                    "has_processing_warnings": bool((record.get("processing") or {}).get("warnings")),
                    "is_3d_record": bool((record.get("thumbnail_health") or {}).get("is_3d_record")),
                    "missing_uploaded_thumbnails": bool((record.get("thumbnail_health") or {}).get("missing_uploaded_thumbnails")),
                    "local_rendered_thumbnail_count": int((record.get("thumbnail_health") or {}).get("local_rendered_thumbnail_count") or 0),
                    "uploaded_thumbnail_count": int((record.get("thumbnail_health") or {}).get("uploaded_thumbnail_count") or 0),
                    "linked_thumbnail_count": int((record.get("thumbnail_health") or {}).get("linked_thumbnail_count") or 0),
                    "can_create_new_version": bool((record.get("thumbnail_health") or {}).get("can_create_new_version")),
                    "can_repair_missing_thumbnails": bool((record.get("thumbnail_health") or {}).get("can_repair_missing_thumbnails")),
                },
            }
        )
    except Exception as exc:
        logger.error(
            f"Failed to retrieve record detail for session {session_id}, record {local_record_id}: {exc}",
            exc_info=True,
        )
        return APIResponse.server_error("Failed to retrieve record detail")


@session_bp.route("/<int:session_id>/records/<int:local_record_id>/create-version", methods=["POST"])
@jwt_required()
def create_session_record_version(session_id, local_record_id):
    """Create a new Zenodo version for a published session record using the complete local file set."""
    try:
        session, _, error_response = get_session_with_permission(
            session_id,
            permission="edit",
            require_mutable=True,
        )
        if error_response:
            return error_response

        resolved_hdpc_path = _resolve_existing_hdpc_path(session.hdpc_path)
        if not resolved_hdpc_path:
            return APIResponse.error(
                "SOURCE_UNAVAILABLE",
                "Session project file (.hdpc) is not available on this backend instance.",
                503,
                details={"source_state": "hdpc_unavailable", "session_id": session_id},
            )

        inventory = read_session_record_inventory(session)
        source_state = str(inventory.get("source_state") or "ok")
        if source_state != "ok":
            message = (
                "No zenodo_records table found in project database."
                if source_state == "zenodo_table_missing"
                else "Session record source is unavailable."
            )
            return APIResponse.error(
                "SOURCE_UNAVAILABLE",
                message,
                503,
                details={"source_state": source_state, "session_id": session_id},
            )

        context = _build_session_record_common_context(session)
        base_record = next(
            (
                item
                for item in (inventory.get("visible_records") or [])
                if int(item.get("local_record_id") or 0) == int(local_record_id)
            ),
            None,
        )
        if base_record is None:
            return APIResponse.not_found("Record not found in this session")
        record, _ = _build_session_record_payload(session, base_record, context)

        if record.get("record_status") != "published":
            return APIResponse.validation_error("Only published records can be versioned")

        if not record.get("concept_rec_id"):
            return APIResponse.validation_error("Record has no concept record ID for versioning")

        if not record.get("source_file_path"):
            return APIResponse.validation_error("Record has no local source file path")

        try:
            ensure_record_operation_allowed(
                session,
                local_record_id=local_record_id,
                allow_allowed_versioning=True,
                exclude_current_record=False,
            )
        except DatasetIntegrityConflictError as exc:
            return APIResponse.validation_error(str(exc), details=exc.details)

        file_paths = _collect_record_version_file_paths(session, record)
        if not file_paths:
            return APIResponse.validation_error("No local files were found to build the new version")

        request_payload = request.get_json(silent=True) or {}
        publish = bool(request_payload.get("publish", False))
        token_context = publishing_context_service.resolve_token_for_session(
            session,
            "sandbox" if bool(record.get("is_sandbox")) else "production",
        )

        version_result = current_app.project_service.create_new_version_with_files(
            concept_rec_id=str(record.get("concept_rec_id")),
            is_sandbox=bool(record.get("is_sandbox")) if record.get("is_sandbox") is not None else False,
            source_file_path=str(record.get("source_file_path")),
            absolute_file_paths=file_paths,
            publish=publish,
            hdpc_path=session.hdpc_path,
            access_token=token_context.get("token"),
        )

        return APIResponse.success(
            data={
                "session_id": session_id,
                "source_local_record_id": local_record_id,
                "new_version": version_result,
                "file_count": len(file_paths),
                "file_paths": file_paths,
            },
            message="New Zenodo version created successfully" if version_result.get("success") else "Version creation completed with warnings",
        )
    except Exception as exc:
        logger.error(
            "Failed to create new version for session %s record %s: %s",
            session_id,
            local_record_id,
            exc,
            exc_info=True,
        )
        return APIResponse.server_error("Failed to create new Zenodo version")


@session_bp.route("/<int:session_id>/provenance-report", methods=["GET"])
@jwt_required()
def get_session_provenance_report(session_id):
    """
    Build a session-level provenance report focused on mapping usage and processing lineage.
    """
    try:
        records_result = get_session_records(session_id)
        _, status_code, payload = _unpack_route_response(records_result)
        if status_code != 200:
            return records_result

        data = payload.get("data") or {}
        source_state = data.get("source_state", "ok")
        if source_state != "ok":
            warnings = data.get("warnings") or []
            message = warnings[0] if warnings else "Session provenance source is unavailable."
            return APIResponse.error(
                "SOURCE_UNAVAILABLE",
                message,
                503,
                details={"source_state": source_state, "session_id": session_id},
            )

        records = data.get("records") or []

        mapped_field_counter = Counter()
        lineage_counter = Counter()
        file_type_counter = Counter()
        file_purpose_counter = Counter()
        processing_status_counter = Counter()

        for record in records:
            record_status = record.get("record_status") or "unknown"
            processing_status_counter[record_status] += 1

            provenance = record.get("provenance") or {}
            for field in provenance.get("mapped_metadata_keys") or []:
                mapped_field_counter[str(field)] += 1

            for lineage in provenance.get("pipeline_lineage") or []:
                pipeline = lineage.get("pipeline") or "unknown"
                step = lineage.get("step") or "unknown"
                lineage_counter[(pipeline, step)] += 1

            for file_item in record.get("files") or []:
                file_type_counter[(file_item.get("file_type") or "unknown")] += 1
                file_purpose_counter[(file_item.get("file_purpose") or "unknown")] += 1

        mapped_fields = [
            {"field": field, "record_count": count}
            for field, count in mapped_field_counter.most_common()
        ]
        lineage_items = [
            {"pipeline": pipeline, "step": step, "occurrences": count}
            for (pipeline, step), count in lineage_counter.most_common()
        ]
        file_type_items = [
            {"file_type": key, "count": value}
            for key, value in file_type_counter.most_common()
        ]
        file_purpose_items = [
            {"file_purpose": key, "count": value}
            for key, value in file_purpose_counter.most_common()
        ]

        records_with_mapping = sum(
            1 for record in records if ((record.get("provenance") or {}).get("mapping_field_count", 0) > 0)
        )
        records_with_lineage = sum(
            1 for record in records if bool((record.get("provenance") or {}).get("pipeline_lineage"))
        )
        records_with_errors = sum(
            1 for record in records if bool((record.get("processing") or {}).get("error"))
        )

        snapshots = [
            {
                "local_record_id": record.get("local_record_id"),
                "record_title": record.get("record_title"),
                "record_status": record.get("record_status"),
                "file_count": record.get("file_count"),
                "mapping_field_count": (record.get("provenance") or {}).get("mapping_field_count", 0),
                "pipeline_lineage_count": len((record.get("provenance") or {}).get("pipeline_lineage") or []),
                "has_error": bool((record.get("processing") or {}).get("error")),
                "warning_count": len((record.get("processing") or {}).get("warnings") or []),
                "updated_at": record.get("updated_at"),
            }
            for record in records
        ]

        return APIResponse.success(
            data={
                "session": data.get("session"),
                "submission": data.get("submission"),
                "summary": data.get("summary"),
                "provenance_overview": data.get("provenance"),
                "report": {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "records_total": len(records),
                    "records_with_mapped_metadata": records_with_mapping,
                    "records_with_pipeline_lineage": records_with_lineage,
                    "records_with_errors": records_with_errors,
                    "status_distribution": dict(processing_status_counter),
                    "mapped_fields": mapped_fields,
                    "pipeline_lineage": lineage_items,
                    "file_type_distribution": file_type_items,
                    "file_purpose_distribution": file_purpose_items,
                    "record_snapshots": snapshots,
                },
            }
        )
    except Exception as exc:
        logger.error(f"Failed to build provenance report for session {session_id}: {exc}", exc_info=True)
        return APIResponse.server_error("Failed to build provenance report")


@session_bp.route("/records/explorer", methods=["GET"])
@jwt_required()
def get_cross_session_records_explorer():
    """
    Explore records across sessions.
    - Users see their own sessions.
    - Moderators/admins can see all sessions and filter by owner.
    """
    try:
        user_id = int(get_jwt_identity())
        user = db.session.get(User, user_id)
        is_privileged = _is_moderator_or_admin(user_id)

        accessible_session_ids = [session.id for session in get_accessible_sessions(user, scope="all")]
        if not accessible_session_ids:
            accessible_session_ids = [-1]
        query = DBSession.query.filter(DBSession.id.in_(accessible_session_ids))

        session_id_filter = request.args.get("session_id", type=int)
        if session_id_filter:
            query = query.filter(DBSession.id == session_id_filter)

        owner_filter = request.args.get("owner_user_id", type=int)
        if is_privileged and owner_filter:
            query = query.filter(DBSession.user_id == owner_filter)

        limit_sessions = request.args.get("limit_sessions", default=25, type=int)
        limit_sessions = max(1, min(limit_sessions or 25, 100))
        max_records = request.args.get("max_records", default=500, type=int)
        max_records = max(1, min(max_records or 500, 2000))

        search_query = (request.args.get("q") or "").strip().lower()
        status_filter = (request.args.get("status") or "all").strip().lower()
        sort_by = (request.args.get("sort") or "updated_desc").strip().lower()

        sessions = query.order_by(DBSession.created_at.desc()).limit(limit_sessions).all()
        owner_ids = {session.user_id for session in sessions}
        owners = {}
        if owner_ids:
            owner_rows = User.query.filter(User.id.in_(owner_ids)).all()
            owners = {owner.id: owner.email for owner in owner_rows}

        explorer_records = []
        session_warnings = []
        failed_sessions = 0
        degraded_sessions = 0

        for session in sessions:
            route_result = get_session_records(session.id)
            _, status_code, payload = _unpack_route_response(route_result)
            if status_code != 200:
                failed_sessions += 1
                session_warnings.append(
                    {
                        "session_id": session.id,
                        "reason": f"Failed to load records (status {status_code})",
                        "severity": "error",
                    }
                )
                continue

            session_data = payload.get("data") or {}
            source_state = session_data.get("source_state", "ok")
            if source_state != "ok":
                degraded_sessions += 1
                warning_message = (session_data.get("warnings") or ["Record source unavailable"])[0]
                session_warnings.append(
                    {
                        "session_id": session.id,
                        "reason": warning_message,
                        "severity": "warning",
                        "source_state": source_state,
                    }
                )

            session_records = session_data.get("records") or []
            for record in session_records:
                combined = {
                    "session_id": session.id,
                    "session_status": session.status,
                    "session_created_at": session.created_at.isoformat() if session.created_at else None,
                    "owner_user_id": session.user_id,
                    "owner_email": owners.get(session.user_id),
                    **record,
                }
                explorer_records.append(combined)

        def status_matches(record_status: str) -> bool:
            current = (record_status or "unknown").lower()
            if status_filter == "all":
                return True
            if status_filter in {"published", "draft"}:
                return current == status_filter
            if status_filter == "other":
                return current not in {"published", "draft"}
            return True

        filtered = []
        for record in explorer_records:
            if not status_matches(record.get("record_status")):
                continue

            if search_query:
                haystack = " ".join(
                    [
                        str(record.get("record_title") or ""),
                        str(record.get("zenodo_doi") or ""),
                        str(record.get("zenodo_record_id") or ""),
                        str(record.get("concept_rec_id") or ""),
                        str(record.get("local_record_id") or ""),
                        str(record.get("session_id") or ""),
                        str(record.get("owner_email") or ""),
                    ]
                ).lower()
                if search_query not in haystack:
                    continue

            filtered.append(record)

        if sort_by == "updated_asc":
            filtered.sort(key=lambda item: str(item.get("updated_at") or ""))
        elif sort_by == "title_asc":
            filtered.sort(key=lambda item: str(item.get("record_title") or "").lower())
        elif sort_by == "title_desc":
            filtered.sort(key=lambda item: str(item.get("record_title") or "").lower(), reverse=True)
        else:
            filtered.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)

        limited_records = filtered[:max_records]
        status_counter = Counter((record.get("record_status") or "unknown") for record in limited_records)

        return APIResponse.success(
            data={
                "summary": {
                    "sessions_scanned": len(sessions),
                    "records_found": len(explorer_records),
                    "records_filtered": len(filtered),
                    "records_returned": len(limited_records),
                    "status_distribution": dict(status_counter),
                    "failed_sessions": failed_sessions,
                    "degraded_sessions": degraded_sessions,
                    "incomplete_results": bool(failed_sessions or degraded_sessions),
                },
                "filters": {
                    "q": search_query,
                    "status": status_filter,
                    "session_id": session_id_filter,
                    "owner_user_id": owner_filter,
                    "limit_sessions": limit_sessions,
                    "max_records": max_records,
                    "sort": sort_by,
                },
                "records": limited_records,
                "session_warnings": session_warnings,
            }
        )
    except Exception as exc:
        logger.error(f"Failed to build cross-session records explorer: {exc}", exc_info=True)
        return APIResponse.server_error("Failed to build cross-session records explorer")


@session_bp.route("/<int:session_id>/zenodo_metadata", methods=["GET"])
@jwt_required()
def download_zenodo_metadata(session_id):
    """
    Securely downloads all Zenodo record metadata from the session's
    .hdpc file as a beautified JSON array.
    """
    conn = None
    try:
        session, _, error_response = get_session_with_permission(session_id, permission="view")
        if error_response:
            return error_response

        metadata_fields = _get_session_metadata_map([session_id], {WORKFLOW_STATE_FIELD, UPLOAD_PROGRESS_FIELD}).get(session_id, {})
        session_state, _, _ = _resolve_session_state(session, metadata_fields)
        if not is_downloadable_session_state(session_state):
            return APIResponse.error(
                "DOWNLOAD_NOT_ALLOWED", f"File not available. Session status is '{session.status}'.", 400
            )

        hdpc_full_path = session.hdpc_path
        if not hdpc_full_path or not os.path.exists(hdpc_full_path):
            logger.error(f"File not found on disk for session {session_id}: {hdpc_full_path}")
            return APIResponse.server_error("File not found on server disk")

        # 3. Connect to the .hdpc file (SQLite) and query it
        all_metadata = []
        conn = sqlite3.connect(hdpc_full_path, timeout=30)
        # Use row_factory to get dict-like rows
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Query for all non-null metadata JSONs in the zenodo_records table
        cursor.execute("SELECT record_metadata_json FROM zenodo_records WHERE record_metadata_json IS NOT NULL;")
        rows = cursor.fetchall()

        for row in rows:
            json_string = row["record_metadata_json"]
            try:
                # Parse the JSON string from the DB
                data = json.loads(json_string)
                all_metadata.append(data)
            except json.JSONDecodeError:
                logger.warning(f"Session {session_id} has invalid JSON in zenodo_records: {json_string[:50]}...")
                # Append the raw string or an error placeholder
                all_metadata.append({"error": "Invalid JSON data in database", "raw_data": json_string})

        # 4. "Beautify" the JSON list
        beautified_json = json.dumps(all_metadata, indent=2)

        # 5. Create and send the Response
        return Response(
            beautified_json,
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment;filename=session_{session_id}_zenodo_metadata.json"},
        )

    except sqlite3.Error as e:
        logger.error(f"SQLite error querying {session.hdpc_path}: {e}", exc_info=True)
        return APIResponse.server_error(f"Database error while reading .hdpc file: {e}")
    except Exception as e:
        logger.error(f"Failed to get zenodo metadata for session {session_id}: {e}", exc_info=True)
        return APIResponse.server_error("Failed to retrieve Zenodo metadata")
    finally:
        if conn:
            conn.close()

@session_bp.route("/<int:session_id>/progress", methods=["GET"])
@jwt_required()
def get_session_progress(session_id):
    """
    Get real-time progress for a session by counting file statuses.
    """
    session, _, error_response = get_session_with_permission(session_id, permission="view")
    if error_response:
        return error_response

    # Count files
    from sqlalchemy import func
    from database.models import File as DBFile

    # Assuming 'uploaded' is the success status based on tasks.py
    stats = db.session.query(
        DBFile.status, func.count(DBFile.id)
    ).filter_by(session_id=session_id).group_by(DBFile.status).all()

    counts = {s: c for s, c in stats}
    total = sum(counts.values())
    completed = counts.get('uploaded', 0)
    failed = counts.get('failed', 0)
    pending = counts.get('pending', 0)

    metadata_map = _get_session_metadata_map(
        [session_id],
        {
            UPLOAD_PROGRESS_FIELD,
            UPLOAD_TASK_ID_FIELD,
            UPLOAD_STORAGE_MODE_FIELD,
            UPLOAD_WORKER_GROUP_ID_FIELD,
        },
    )
    upload_progress = _normalize_upload_progress_payload(
        session,
        metadata_map.get(session_id, {}),
        {"uploaded": completed, "failed": failed, "pending": pending},
    )

    return APIResponse.success(data={
        "total": total,
        "completed": completed,
        "failed": failed,
        "pending": pending,
        "percent": round((completed + failed) / total * 100, 1) if total > 0 else upload_progress.get("percent", 0),
        "upload_progress": upload_progress,
        "workflow_file_counts": upload_progress.get("workflow_file_counts"),
        "status_message": upload_progress.get("status_message"),
        "current_stage": upload_progress.get("current_stage"),
    })

@session_bp.route("/<int:session_id>/resume", methods=["POST"])
@jwt_required()
def resume_session(session_id):
    """
    Resume a session by reconciling any unresolved upload file entries.
    """
    session, _, error_response = get_session_with_permission(
        session_id,
        permission="edit",
        require_mutable=True,
    )
    if error_response:
        return error_response

    from database.models import File as DBFile
    from tasks import (
        _delete_session_metadata,
        _persist_upload_operation_progress,
    )

    retry_files = DBFile.query.filter(
        DBFile.session_id == session_id,
        DBFile.status.in_(["failed", "pending"])
    ).all()

    if not retry_files:
        return APIResponse.success(message="No upload work to resume", data={"count": 0, "worker_group_id": None})

    reconciled_count = 0
    recovered_count = 0
    failed_files = []
    for file_row in retry_files:
        reconciled_count += 1
        if os.path.isfile(file_row.path):
            file_row.status = "uploaded"
            recovered_count += 1
        else:
            file_row.status = "failed"
            failed_files.append(file_row.filename)

    session.status = "scanned"
    db.session.commit()

    warning_message = None
    if failed_files:
        preview = ", ".join(failed_files[:3])
        if len(failed_files) > 3:
            preview = f"{preview}, and {len(failed_files) - 3} more"
        warning_message = f"Missing or unreadable files: {preview}."

    _persist_upload_operation_progress(
        session_id,
        {
            "current_stage": "completed",
            "status_message": (
                f"Upload scan completed with {len(failed_files)} unavailable file(s)."
                if failed_files
                else "Upload scan and metadata registration completed."
            ),
            "current_index": reconciled_count,
            "total_files": reconciled_count,
            "processed_count": reconciled_count,
            "failed_count": len(failed_files),
            "warning_message": warning_message,
        },
        update_session_status="scanned",
    )
    _delete_session_metadata(session_id, UPLOAD_WORKER_GROUP_ID_FIELD)
    db.session.commit()

    return APIResponse.success(
        message=f"Revalidated {reconciled_count} files",
        data={
            "count": reconciled_count,
            "resumed_count": recovered_count,
            "failed_count": len(failed_files),
            "worker_group_id": None,
        },
    )


@session_bp.route("/<int:session_id>/nodes", methods=["GET"])
@jwt_required()
def get_session_nodes(session_id):
    """
    Get the file tree (nodes) for a session.
    Retrieves the structure from the HDP project and merges in statuses from our DB.
    """
    session, _, error_response = get_session_with_permission(session_id, permission="view")
    if error_response:
        return error_response

    if not session.hdpc_path:
        return APIResponse.error("Project file not found for this session", 404)

    try:
        project_service = current_app.project_service
        inspect_data = _inspect_session_hdpc(session, show_files=True)
        nodes = inspect_data.get("file_tree", [])

        # Merge statuses from our File model
        from database.models import File as DBFile
        db_files = DBFile.query.filter_by(session_id=session_id).all()
        status_map = {f.filename: f.status for f in db_files}

        excluded_names = {"__macosx", "__pycache__"}

        def _path_has_excluded_segment(value):
            if not isinstance(value, str) or not value:
                return False
            normalized = value.replace("\\", "/")
            return any(segment.lower() in excluded_names for segment in normalized.split("/") if segment)

        def _should_exclude(node):
            for key in ("name", "filename", "relative_path", "absolute_path", "path"):
                if _path_has_excluded_segment(node.get(key)):
                    return True
            return False

        def _parse_validation_report(raw_report):
            if isinstance(raw_report, dict):
                return raw_report
            if isinstance(raw_report, str):
                report_text = raw_report.strip()
                if not report_text:
                    return {}
                try:
                    parsed = json.loads(report_text)
                    return parsed if isinstance(parsed, dict) else {}
                except json.JSONDecodeError:
                    return {"is_valid": False, "errors": [report_text]}
            return {}

        # Recursive helper to filter and annotate nodes
        def process_nodes(node_list):
            processed = []
            for node in node_list:
                if _should_exclude(node):
                    continue

                name = node.get("name") or node.get("filename")
                legacy_validation_status = node.get("status", "scanned")
                legacy_upload_status = status_map.get(name)
                validation_status = normalize_source_validation_state(legacy_validation_status)
                upload_status = normalize_source_upload_state(legacy_upload_status) if legacy_upload_status else None

                node["validation_status"] = validation_status
                node["legacy_validation_status"] = legacy_validation_status
                if upload_status:
                    node["upload_status"] = upload_status
                    node["legacy_upload_status"] = legacy_upload_status
                    if validation_status and validation_status.lower() != upload_status.lower():
                        node["status"] = f"{validation_status} / {upload_status}"
                    else:
                        node["status"] = upload_status
                else:
                    node["status"] = validation_status

                if not isinstance(node.get("validation_report"), dict):
                    if node.get("validation_report") is not None:
                        node["validation_report"] = _parse_validation_report(node.get("validation_report"))
                    elif node.get("validation_report_json") is not None:
                        node["validation_report"] = _parse_validation_report(node.get("validation_report_json"))
                    elif node.get("error_message") is not None:
                        node["validation_report"] = _parse_validation_report(node.get("error_message"))
                    else:
                        node["validation_report"] = {}

                # Ensure absolute_path is present and translated for main backend container
                # (fallback HDP server inspection may return host-visible paths)
                if "absolute_path" in node:
                    node["absolute_path"] = project_service._translate_path(node["absolute_path"], to_container=True)

                children = node.get("children") or []
                node["children"] = process_nodes(children)
                processed.append(node)

            return processed

        nodes = process_nodes(nodes)

        return APIResponse.success(data={"nodes": nodes})

    except Exception as e:
        logger.error(f"Failed to retrieve nodes for session {session_id}: {e}", exc_info=True)
        return APIResponse.error(f"Failed to retrieve file nodes: {str(e)}", 500)


@session_bp.route('/<int:session_id>/records/<int:local_record_id>/lod', methods=['GET', 'POST'])
@jwt_required()
def record_lod_recovery(session_id, local_record_id):
    """Inspect or retry local metadata generation without remote side effects."""
    from pathlib import Path
    from contextlib import nullcontext
    from services.lod_artifact_service import generate_artifacts, suspend_previous_artifacts, FILENAMES, complete_format_states, record_lod_readiness
    from services.lod_reliability import digest
    from flask import send_file
    import io
    from services.hdpc_local_service import add_local_source_files
    from services.pipeline_execution_lock import session_pipeline_lock
    from routes.access_helpers import get_session_with_permission
    session, _, error = get_session_with_permission(session_id, permission='edit' if request.method == 'POST' else 'view', require_mutable=request.method == 'POST')
    if error is not None:
        return error
    if not session.hdpc_path:
        return APIResponse.validation_error('The session project is unavailable')
    root = Path(session.hdpc_path).resolve().parent / 'outputs' / f'record-{local_record_id}'
    paths = list(root.glob('*/lod-generation.json'))
    if not paths:
        return APIResponse.success(data={'formats': {}, 'available': False})
    if len(paths) != 1 or not paths[0].resolve().is_relative_to(root.resolve()):
        return APIResponse.validation_error('Ambiguous metadata recovery state')
    with session_pipeline_lock(session.hdpc_path) if request.method == 'POST' else nullcontext():
        with paths[0].open(encoding='utf-8') as stream:
            manifest = complete_format_states(json.load(stream))
        requested_format = request.args.get('format')
        if request.method == 'GET' and requested_format:
            status = (manifest.get('formats') or {}).get(requested_format) or {}
            if requested_format not in FILENAMES or status.get('status') != 'generated' or (status.get('validation') or {}).get('valid') is not True:
                return APIResponse.validation_error('Only validated metadata exports can be downloaded')
            artifact = paths[0].parent / FILENAMES[requested_format]
            if not artifact.resolve().is_relative_to(root.resolve()):
                return APIResponse.validation_error('The metadata export is outside this record')
            try:
                content = artifact.read_bytes()
            except OSError:
                return APIResponse.validation_error('The export is missing. Retry generation.')
            if digest(content) != status.get('sha256'):
                return APIResponse.validation_error('The export changed after validation. Retry generation.')
            return send_file(io.BytesIO(content), as_attachment=True, download_name=artifact.name, mimetype='application/octet-stream')
        if request.method == 'POST':
            from services.hdpc_schema_service import connect_hdpc
            with connect_hdpc(session.hdpc_path) as conn:
                row = conn.execute('SELECT record_status FROM zenodo_records WHERE record_id = ?', (local_record_id,)).fetchone()
            if not row or str(row[0]).lower() in ('published', 'done', 'submitted'):
                return APIResponse.validation_error('Only an existing unpublished draft can regenerate metadata')
            suspend_previous_artifacts(session.hdpc_path, local_record_id)
            def register(path, validation):
                result = add_local_source_files(session.hdpc_path, absolute_file_paths=[path], record_id_to_associate=local_record_id, pipeline_name='lod_generation', step_name='metadata_generator', validation_reports={path: validation})
                if not result.get('success') or result.get('errors_count'):
                    raise ValueError('Could not register the validated artifact')
            _, manifest = generate_artifacts(str(paths[0].parent), manifest['request'], register)
    for standard, status in manifest['formats'].items():
        if status.get('status') == 'generated' and standard in FILENAMES:
            artifact = paths[0].parent / FILENAMES[standard]
            try:
                intact = artifact.resolve().is_relative_to(root.resolve()) and digest(artifact.read_bytes()) == status.get('sha256')
            except OSError:
                intact = False
            if not intact:
                status.update(success=False, status='failed', error='The export is missing or changed after validation. Retry generation.')
                status['validation'] = {'valid': False, 'errors': ['Stored artifact integrity check failed']}
    # Do not expose the private request or local paths in the report.
    formats = {key: {field: value for field, value in status.items() if field not in ('path',)} for key, status in manifest['formats'].items()}
    return APIResponse.success(data={'formats': formats, 'available': True, 'readiness': record_lod_readiness(session.hdpc_path, local_record_id)})
