import json
import logging
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from flask import current_app

from constants import (
    LEGACY_PIPELINE_ALIASES,
    PIPELINE_DEFINITION,
    PREDEFINED_PIPELINE_ID,
    METADATA_ONLY_PIPELINE_DEFINITION,
    METADATA_ONLY_PIPELINE_ID,
    MSF_ALLOWED_EXTENSIONS,
)
from database.database import db
from database.models import BatchFileMetadata, Session as DBSession, SystemConfig, UserMetadata
from exceptions import FileProcessingError
from services.pipeline_execution_lock import guard_submission_execution
from services.source_bundle_service import create_source_bundle
from services.audit_service import record_audit_event
from services.dataset_integrity_service import (
    analyze_session_record_resolution,
    ensure_fresh_record_creation_allowed,
    ensure_record_operation_allowed,
    read_session_records,
)
from services.hdpc_local_service import (
    add_local_source_files,
    create_local_record_with_metadata,
    get_hdpc_file_id_map,
    inspect_hdpc_project,
)
from services.publishing_context_service import PublishingContextService
from services.zenodo_metadata_normalizer import normalize_zenodo_metadata
from services.zenodo_config_service import ZenodoConfigService

logger = logging.getLogger(__name__)
publishing_context_service = PublishingContextService()

ProgressCallback = Callable[[Dict[str, Any]], None]
INTERNAL_ZENODO_KEYS = {"lod_mapping", "msf_path", "msf_parse_options", "edm_template_id", "iiif_template_id", "mets_template_id"}
EXCLUDED_PATH_SEGMENTS = {"__macosx", "__pycache__"}
SUPPORTED_RENDER_ENGINES = {"BLENDER_EEVEE", "BLENDER_WORKBENCH", "CYCLES"}
RENDER_ENGINE_ALIASES = {
    "BLENDER_EEVEE_NEXT": "BLENDER_EEVEE",
}
ITEM_SPECIFIC_ZENODO_FIELDS = {"title", "description", "creators"}
CREATOR_FALLBACK_HINT_KEYS = (
    "_affiliations_raw",
    "creator_affiliation",
    "creator affiliation",
    "affiliation",
)
IDENTIFIER_FALLBACK_HINT_KEYS = (
    "_external_identifier",
    "identifier",
    "dc_identifier",
)
NEUTRAL_ITEM_DESCRIPTION = "No item-specific description provided."
RENDERED_THUMBNAIL_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


def _emit_progress(callback: Optional[ProgressCallback], payload: Dict[str, Any]) -> None:
    """Best-effort progress emission that never interrupts execution."""
    if not callback:
        return
    try:
        callback(payload)
    except Exception as exc:
        logger.warning(f"Progress callback failed: {exc}")


def _resolve_lod_msf_candidates(hdpc_path: str, configured_path: str | None = None) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add_candidate(path: str | None) -> None:
        normalized = str(path or "").strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        candidates.append(normalized)

    add_candidate(configured_path)
    uploads_dir = os.path.join(os.path.dirname(hdpc_path), "uploads")
    for ext in (".xlsx", ".xls", ".csv"):
        add_candidate(os.path.join(uploads_dir, f"upload.msf{ext}"))
    if os.path.isdir(uploads_dir):
        for name in os.listdir(uploads_dir):
            ext = os.path.splitext(name)[1].lower()
            if ext in MSF_ALLOWED_EXTENSIONS:
                add_candidate(os.path.join(uploads_dir, name))
    return candidates


def _get_merged_pipeline_config(identifier: str) -> Dict[str, Any]:
    config_key = f"pipeline_config:{identifier}"
    config_entry = db.session.get(SystemConfig, config_key)

    if config_entry and config_entry.value:
        try:
            parsed = json.loads(config_entry.value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            logger.warning(f"Invalid pipeline config JSON for {identifier}. Falling back to defaults.")

    if identifier == METADATA_ONLY_PIPELINE_ID:
        return METADATA_ONLY_PIPELINE_DEFINITION.copy()

    return PIPELINE_DEFINITION.copy()


def _extract_zenodo_draft_id(draft_result: Dict[str, Any]) -> Optional[str]:
    if not isinstance(draft_result, dict):
        return None

    zenodo_response = draft_result.get("zenodo_response")
    if isinstance(zenodo_response, dict):
        return str(
            zenodo_response.get("id")
            or zenodo_response.get("record_id")
            or zenodo_response.get("conceptrecid")
            or ""
        ) or None

    return str(draft_result.get("id") or draft_result.get("record_id") or "") or None


def _extract_usdz_failure_details(usdz_result: Dict[str, Any]) -> Dict[str, Any]:
    details = usdz_result.get("details")
    if isinstance(details, dict):
        nested = details.get("details")
        if isinstance(nested, dict):
            details = nested
    return details if isinstance(details, dict) else {}


def _build_usdz_failure_message(filename: str, usdz_result: Dict[str, Any]) -> Dict[str, Any]:
    details = _extract_usdz_failure_details(usdz_result)
    error_code = usdz_result.get("error_code") or details.get("error_code") or "USDZ_CONVERSION_FAILED"
    error_message = usdz_result.get("error") or "Unknown USDZ conversion error"
    hint = details.get("diagnostic_hint")
    message = f"USDZ conversion failed for {filename}: {error_message}"
    if hint:
        message = f"{message} Hint: {hint}"

    return {
        "message": message,
        "error_message": error_message,
        "error_code": error_code,
        "hint": hint,
        "details": details,
    }


def _extract_error_from_service_result(result: Dict[str, Any], default_message: str) -> str:
    if not isinstance(result, dict):
        return default_message

    candidates = [
        result.get("error"),
        result.get("message"),
    ]
    details = result.get("details")
    if isinstance(details, dict):
        candidates.extend([details.get("error"), details.get("message")])

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

    return default_message


def _format_pipeline_exception(exc: Exception) -> str:
    base_message = str(exc).strip() or exc.__class__.__name__
    details = getattr(exc, "details", None)
    if not isinstance(details, dict):
        return base_message

    detail_error = details.get("error") or details.get("message")
    endpoint = details.get("endpoint")

    if isinstance(detail_error, str) and detail_error.strip():
        if detail_error not in base_message:
            base_message = f"{base_message}: {detail_error.strip()}"

    if isinstance(endpoint, str) and endpoint.strip():
        endpoint_label = endpoint.strip()
        if endpoint_label not in base_message:
            base_message = f"{base_message} ({endpoint_label})"

    return base_message


def _normalize_render_engine(raw_engine: Any) -> Tuple[str, Optional[str]]:
    force_cycles_raw = os.environ.get(
        "FAST_RENDERER_FORCE_CYCLES",
        os.environ.get("FAST_RENDERER_REQUIRE_GPU", os.environ.get("REQUIRE_GPU", "false")),
    )
    force_cycles = str(force_cycles_raw).strip().lower() in {"1", "true", "yes", "on"}

    if raw_engine is None:
        return "CYCLES", None

    normalized = str(raw_engine).strip().upper()
    if not normalized:
        return "CYCLES", None

    normalized = RENDER_ENGINE_ALIASES.get(normalized, normalized)
    if force_cycles and normalized == "BLENDER_EEVEE":
        warning = (
            "BLENDER_EEVEE configured while GPU-optimized mode is active; "
            "coercing engine to CYCLES."
        )
        return "CYCLES", warning
    if normalized in SUPPORTED_RENDER_ENGINES:
        return normalized, None

    warning = (
        f"Unsupported render engine '{raw_engine}' configured; "
        "falling back to CYCLES for GPU rendering."
    )
    return "CYCLES", warning


def _append_unique_paths(target: List[str], candidate_paths: List[str]) -> None:
    """Append filesystem paths while preserving order and avoiding duplicates."""
    if not candidate_paths:
        return

    seen = {os.path.normpath(path) for path in target if isinstance(path, str) and path.strip()}
    for raw_path in candidate_paths:
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        normalized = os.path.normpath(raw_path)
        if normalized in seen:
            continue
        target.append(raw_path)
        seen.add(normalized)


def _collect_generated_output_files(output_dir: str) -> List[str]:
    """Discover generated files from a record-specific output directory."""
    if not isinstance(output_dir, str) or not output_dir.strip() or not os.path.isdir(output_dir):
        return []

    collected: List[str] = []
    for entry_name in sorted(os.listdir(output_dir)):
        entry_path = os.path.join(output_dir, entry_name)
        if os.path.isfile(entry_path):
            collected.append(entry_path)
    return collected


def _collect_rendered_thumbnail_files(output_dir: str) -> List[str]:
    """Return image outputs that can be used as rendered thumbnails."""
    return [
        path
        for path in _collect_generated_output_files(output_dir)
        if os.path.splitext(path)[1].lower() in RENDERED_THUMBNAIL_EXTENSIONS
    ]


def _coerce_seconds(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None

    normalized = value.strip().lower()
    if normalized.endswith("s"):
        normalized = normalized[:-1].strip()
    if not normalized:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def _normalize_subprocess_timings(raw_timings: Any) -> Dict[str, float]:
    if not isinstance(raw_timings, dict):
        return {}

    normalized: Dict[str, float] = {}
    for key, value in raw_timings.items():
        if not isinstance(key, str) or not key.strip():
            continue
        seconds = _coerce_seconds(value)
        if seconds is None:
            continue
        normalized[key] = seconds
    return normalized


def _looks_like_tag_mapping(node: Any) -> bool:
    if not isinstance(node, dict):
        return False
    return any(isinstance(value, dict) and "source" in value for value in node.values())


def _extract_standard_mapping(lod_mapping: Any, standard_id: str, modality_id: str) -> Dict[str, Any]:
    """
    Supports both:
    1) Flat mapping: {"dc:title": {...}}
    2) Nested mapping: {"iiif": {"3d": {"iiif:sceneId": {...}}}}
    """
    if not isinstance(lod_mapping, dict):
        return {}

    if _looks_like_tag_mapping(lod_mapping):
        return lod_mapping

    standard_node = lod_mapping.get(standard_id, {})
    if standard_id == "cidoc_crm" and not standard_node:
        standard_node = lod_mapping.get("jsonld", {})
    if _looks_like_tag_mapping(standard_node):
        return standard_node
    if not isinstance(standard_node, dict):
        return {}

    modality_candidates = [str(modality_id or "").strip().lower()]
    modality_aliases = {
        "3d": ["3d_model", "3dmodel", "model_3d"],
        "image": ["img"],
        "sound": ["audio"],
        "text": ["document", "doc"],
        "video": [],
    }
    modality_candidates.extend(modality_aliases.get(modality_candidates[0], []))

    seen = set()
    for candidate in modality_candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        modality_node = standard_node.get(candidate)
        if _looks_like_tag_mapping(modality_node):
            return modality_node

    fallback_3d = standard_node.get("3d")
    if _looks_like_tag_mapping(fallback_3d):
        return fallback_3d

    return {}


def _infer_lod_modality(filename: str, metadata: Dict[str, Any]) -> str:
    edm_type = str((metadata or {}).get("edm_type_override", "")).strip().upper()
    edm_map = {
        "3D": "3d",
        "IMAGE": "image",
        "SOUND": "sound",
        "VIDEO": "video",
        "TEXT": "text",
    }
    if edm_type in edm_map:
        return edm_map[edm_type]

    ext = os.path.splitext(filename)[1].lower()
    if ext in {".glb", ".gltf", ".obj", ".fbx", ".stl", ".ply", ".dae", ".3ds", ".blend"}:
        return "3d"
    if ext in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".svg"}:
        return "image"
    if ext in {".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a"}:
        return "sound"
    if ext in {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv"}:
        return "video"
    if ext in {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt"}:
        return "text"

    upload_type = (metadata or {}).get("upload_type")
    resource_type = (metadata or {}).get("resource_type")
    if isinstance(resource_type, dict):
        upload_type = resource_type.get("type", upload_type)
    upload_type = str(upload_type or "").strip().lower()
    upload_map = {
        "image": "image",
        "video": "video",
        "audio": "sound",
        "publication": "text",
        "presentation": "text",
    }
    return upload_map.get(upload_type, "3d")


def _has_non_empty_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) > 0
    return True


def _merge_non_empty_metadata(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base or {})
    for key, value in (overrides or {}).items():
        if _has_non_empty_value(value):
            merged[key] = value
    return merged


def _normalize_text_value(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    return candidate or None


def _normalize_creator_list(value: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    seen = set()

    if isinstance(value, dict):
        candidates = [value]
    elif isinstance(value, list):
        candidates = value
    elif isinstance(value, tuple):
        candidates = list(value)
    elif isinstance(value, str):
        candidates = [token.strip() for token in re.split(r"[;,]", value) if token.strip()]
    elif value is None:
        candidates = []
    else:
        text = str(value).strip()
        candidates = [text] if text else []

    for candidate in candidates:
        if isinstance(candidate, dict):
            name = _normalize_text_value(candidate.get("name"))
            if not name:
                continue
            entry = {"name": name}
            affiliation = _normalize_text_value(candidate.get("affiliation"))
            if affiliation:
                entry["affiliation"] = affiliation
            dedupe_key = (entry["name"], entry.get("affiliation"))
        else:
            name = _normalize_text_value(candidate)
            if not name:
                continue
            entry = {"name": name}
            dedupe_key = (name, None)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(entry)

    return normalized


def _has_meaningful_creators(value: Any) -> bool:
    creators = _normalize_creator_list(value)
    if not creators:
        return False
    return any(str(entry.get("name") or "").strip().lower() != "unknown" for entry in creators)


def _split_batch_shared_zenodo_metadata(shared_metadata: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    batch_shared_metadata: Dict[str, Any] = {}
    item_defaults: Dict[str, Any] = {}

    for key, value in (shared_metadata or {}).items():
        if key == "edm_main_file_key":
            continue  # A batch preview selection is never a shared record identity.
        if key in ITEM_SPECIFIC_ZENODO_FIELDS:
            item_defaults[key] = value
        else:
            batch_shared_metadata[key] = value

    return batch_shared_metadata, item_defaults


def _derive_batch_fallback_title(metadata: Dict[str, Any], filename: str) -> str:
    title = _normalize_text_value((metadata or {}).get("title"))
    if title:
        return title

    for key in IDENTIFIER_FALLBACK_HINT_KEYS:
        identifier = _normalize_text_value((metadata or {}).get(key))
        if identifier:
            return identifier

    file_stem = os.path.splitext(os.path.basename(filename or ""))[0].strip()
    return file_stem or "Untitled"


def _derive_batch_fallback_creators(
    metadata: Dict[str, Any],
    shared_item_defaults: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    creators = _normalize_creator_list((metadata or {}).get("creators"))
    if creators and _has_meaningful_creators(creators):
        return creators

    for key in CREATOR_FALLBACK_HINT_KEYS:
        fallback_creators = _normalize_creator_list((metadata or {}).get(key))
        if fallback_creators:
            return fallback_creators

    shared_creators = _normalize_creator_list((shared_item_defaults or {}).get("creators"))
    if shared_creators and _has_meaningful_creators(shared_creators):
        return shared_creators

    return []


def _normalize_rel_path(path: str) -> str:
    if not isinstance(path, str):
        return ""
    return os.path.normpath(path).replace("\\", "/")


def _has_excluded_segment(path: str) -> bool:
    if not isinstance(path, str):
        return False
    normalized = _normalize_rel_path(path)
    return any(segment.lower() in EXCLUDED_PATH_SEGMENTS for segment in normalized.split("/") if segment)


def _iter_file_nodes(file_nodes: List[Dict[str, Any]]):
    stack = list(file_nodes or [])
    while stack:
        node = stack.pop()
        yield node
        children = node.get("children") or []
        if children:
            stack.extend(children)


def _build_bundle_file_paths_by_relative(file_tree: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """
    Build a lookup where every file relative path points to all absolute file paths in its bundle subtree.
    """
    bundle_map: Dict[str, List[str]] = {}
    for root in file_tree or []:
        entries: List[Tuple[str, str]] = []
        stack = [root]
        while stack:
            node = stack.pop()
            relative_path = _normalize_rel_path(node.get("relative_path"))
            absolute_path = node.get("absolute_path") or node.get("path")
            node_type = str(node.get("type") or node.get("file_type") or "").strip().lower()
            # Archived files are represented separately and also bundled into a .zip archive node.
            # Upload only the archive to avoid duplicate payloads.
            if node_type == "archived_file":
                children = node.get("children") or []
                if children:
                    stack.extend(children)
                continue
            if relative_path and isinstance(absolute_path, str) and absolute_path and not _has_excluded_segment(relative_path):
                entries.append((relative_path, absolute_path))
            children = node.get("children") or []
            if children:
                stack.extend(children)

        if not entries:
            continue

        deduped_bundle_paths: List[str] = []
        seen_abs_paths = set()
        for _, abs_path in entries:
            normalized_abs = os.path.normpath(abs_path)
            if normalized_abs in seen_abs_paths:
                continue
            seen_abs_paths.add(normalized_abs)
            deduped_bundle_paths.append(abs_path)

        for relative_path, _ in entries:
            bundle_map[relative_path] = deduped_bundle_paths

    return bundle_map


def _file_type_rank(filename: str) -> int:
    ext = os.path.splitext((filename or "").lower())[1]
    if ext == ".glb":
        return 0
    if ext == ".fbx":
        return 1
    if ext == ".obj":
        return 2
    if ext == ".gltf":
        return 3
    return 10


def _resolve_metadata_linked_asset(
    *,
    selected_file_path: str,
    selected_file_id: Any,
    batch_metadata_map: Dict[str, Dict[str, Any]],
    basename_to_relative_paths: Dict[str, List[str]],
    normalized_file_id_map: Dict[str, Any],
    relative_to_absolute_path: Dict[str, str],
) -> Tuple[Any, str, Optional[Dict[str, Any]]]:
    """
    Resolve a selected file to the best batch-metadata-linked asset.
    Returns: (resolved_file_id, resolved_absolute_path, resolved_metadata_or_none)
    """
    selected_filename = os.path.basename(selected_file_path).lower()
    selected_relative = next((path for path, file_id in normalized_file_id_map.items() if str(file_id) == str(selected_file_id)), selected_filename)
    file_metadata = batch_metadata_map.get(selected_relative)
    if file_metadata:
        return selected_file_id, selected_file_path, file_metadata

    selected_stem = os.path.splitext(selected_filename)[0]
    candidate_metadata_names = [
        meta_filename
        for meta_filename in batch_metadata_map.keys()
        if os.path.splitext(meta_filename)[0] == selected_stem
    ]
    candidate_metadata_names.sort(key=lambda name: (_file_type_rank(name), name))

    for meta_filename in candidate_metadata_names:
        candidate_relative_paths = basename_to_relative_paths.get(meta_filename, [])
        if not candidate_relative_paths:
            continue

        if len(candidate_relative_paths) > 1:
            raise FileProcessingError(f"Ambiguous metadata-linked source {meta_filename}. Use its relative path.")
        candidate_relative_paths = sorted(
            candidate_relative_paths,
            key=lambda rel: (_file_type_rank(rel), len(rel), rel),
        )
        candidate_relative_path = candidate_relative_paths[0]
        candidate_file_id = normalized_file_id_map.get(candidate_relative_path)
        if not candidate_file_id:
            continue

        resolved_path = relative_to_absolute_path.get(candidate_relative_path) or selected_file_path
        return candidate_file_id, resolved_path, batch_metadata_map.get(meta_filename)

    return selected_file_id, selected_file_path, None


def _normalize_execution_items(execution_items: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in execution_items or []:
        if not isinstance(item, dict):
            continue
        decision_key = str(item.get("decision_key") or "").strip()
        action = str(item.get("action") or "").strip().lower()
        source_file_path = str(item.get("source_file_path") or "").strip()
        if not decision_key or not action or not source_file_path:
            continue
        normalized.append(
            {
                "decision_key": decision_key,
                "action": action,
                "source_file_path": source_file_path,
                "source_file_name": str(item.get("source_file_name") or os.path.basename(source_file_path)).strip(),
                "target_session_id": int(item.get("target_session_id")) if item.get("target_session_id") is not None else None,
                "target_local_record_id": int(item.get("target_local_record_id"))
                if item.get("target_local_record_id") is not None
                else None,
                "target_concept_rec_id": str(item.get("target_concept_rec_id") or "").strip() or None,
                "forced_override_reason": str(item.get("forced_override_reason") or "").strip() or None,
            }
        )
    return normalized


def _validate_execution_items_against_resolution_state(
    session_row: DBSession,
    execution_items: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    analysis = analyze_session_record_resolution(session_row)
    candidates_by_key = {
        str(item.get("decision_key") or "").strip(): item
        for item in analysis.get("candidates") or []
        if isinstance(item, dict)
    }
    validated: Dict[str, Dict[str, Any]] = {}
    for item in execution_items:
        decision_key = str(item.get("decision_key") or "").strip()
        candidate = candidates_by_key.get(decision_key)
        if candidate is None:
            raise FileProcessingError(f"Record resolution decision '{decision_key}' is no longer valid for this session.")
        selected_action = str(candidate.get("selected_action") or "").strip().lower()
        if selected_action != str(item.get("action") or "").strip().lower():
            raise FileProcessingError(f"Record resolution decision '{decision_key}' no longer matches the saved session plan.")
        if candidate.get("severity") != "clean" and not bool(candidate.get("resolved")):
            raise FileProcessingError(f"Record resolution decision '{decision_key}' must be reviewed before processing.")
        if selected_action == "create_version":
            selected_target = candidate.get("selected_target") if isinstance(candidate.get("selected_target"), dict) else {}
            if int(selected_target.get("session_id") or 0) != int(item.get("target_session_id") or 0):
                raise FileProcessingError(f"Version target for '{decision_key}' no longer matches the saved session plan.")
            if int(selected_target.get("local_record_id") or 0) != int(item.get("target_local_record_id") or 0):
                raise FileProcessingError(f"Version target for '{decision_key}' no longer matches the saved session plan.")
        if selected_action == "force_create_fresh":
            saved_reason = str(candidate.get("forced_override_reason") or "").strip()
            if saved_reason != str(item.get("forced_override_reason") or "").strip():
                raise FileProcessingError(f"Force-create override for '{decision_key}' must include the saved audit reason.")
        validated[decision_key] = candidate
    return validated


def _resolve_version_target_record(target_session_id: int, target_local_record_id: int) -> Dict[str, Any]:
    target_session = db.session.get(DBSession, int(target_session_id))
    if target_session is None:
        raise FileProcessingError(f"Version target session {target_session_id} was not found.")
    target_records = read_session_records(target_session)
    target_record = next(
        (
            item
            for item in target_records
            if int(item.get("local_record_id") or 0) == int(target_local_record_id)
        ),
        None,
    )
    if target_record is None:
        raise FileProcessingError(
            f"Version target record {target_local_record_id} was not found in session {target_session_id}."
        )
    return target_record


@guard_submission_execution
def execute_submission_pipeline(
    identifier: str,
    local_file_paths: Optional[List[str]],
    db_session_id: int,
    is_sandbox: bool = True,
    abort_on_critical_error: bool = False,
    progress_callback: Optional[ProgressCallback] = None,
    record_ids: Optional[List[int]] = None,
    execution_items: Optional[List[Dict[str, Any]]] = None,
    precreated_run_public_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute a submission pipeline and emit optional progress updates.

    Returns:
        Dict with keys: result, timings, progress_summary
    """
    project_service = current_app.project_service
    local_file_paths = list(local_file_paths or [])
    record_ids = [int(record_id) for record_id in (record_ids or []) if record_id is not None]
    execution_items = _normalize_execution_items(execution_items)

    pipeline_timings = {
        "project_loading": 0,
        "record_registration": 0,
        "batch_render": 0,
        "record_processing": [],
        "total_execution": 0,
    }
    main_start = time.time()

    db_session = db.session.get(DBSession, db_session_id)
    if not db_session:
        raise FileProcessingError("Session not found in database")

    hdpc_path = db_session.hdpc_path
    if not hdpc_path:
        raise FileProcessingError("Session has no .hdpc file path")
    using_execution_items = bool(execution_items)
    using_existing_record_ids = bool(record_ids) and not using_execution_items
    session_default_environment = str(getattr(db_session, "default_zenodo_environment", "sandbox") or "sandbox").strip().lower()
    session_default_is_sandbox = session_default_environment != "production"
    effective_is_sandbox = session_default_is_sandbox if using_execution_items else bool(is_sandbox)
    if using_execution_items and bool(is_sandbox) != effective_is_sandbox:
        raise FileProcessingError(
            "Batch record-resolution plans must run in the session's default Zenodo environment.",
            details={
                "session_id": db_session.id,
                "session_default_environment": session_default_environment,
                "requested_environment": "sandbox" if bool(is_sandbox) else "production",
            },
        )
    zenodo_environment = "sandbox" if effective_is_sandbox else "production"
    token_context = publishing_context_service.resolve_token_for_session(db_session, zenodo_environment)
    access_token = token_context.get("token")
    session_description = publishing_context_service.describe_session(db_session)
    publishing_context = {
        "environment": token_context.get("environment") or zenodo_environment,
        "credential_source": token_context.get("source") or session_description.get("effective_credential_source"),
        "owner_type": token_context.get("owner_type"),
        "owner_id": token_context.get("owner_id"),
        "credential_id": token_context.get("credential_id"),
        "masked_preview": token_context.get("masked_preview"),
        "workspace_type": session_description.get("workspace_type"),
        "credential_preference": session_description.get("credential_preference"),
        "institution_id": session_description.get("institution_id"),
        "publishing_user_id": session_description.get("publishing_user_id"),
        "community_policy": {
            "default_communities": session_description.get("default_communities", []),
            "primary_submission_community": session_description.get("primary_submission_community"),
            "moderation_default_communities": session_description.get("moderation_default_communities", []),
            "use_institution_default_communities": bool(
                session_description.get("use_institution_default_communities", False)
            ),
        },
    }

    total_requested = (
        len(execution_items)
        if using_execution_items
        else len(record_ids)
        if using_existing_record_ids
        else len(local_file_paths)
    )
    _emit_progress(
        progress_callback,
        {
            "current_stage": "loading_project",
            "status_message": "Loading project context",
            "current_index": 0,
            "total_files": total_requested,
            "processed_count": 0,
            "failed_count": 0,
        },
    )

    load_start = time.time()
    try:
        inspect_data = inspect_hdpc_project(hdpc_path, show_files=True)
        file_id_map = get_hdpc_file_id_map(hdpc_path)
    except Exception as exc:
        raise FileProcessingError(f"Could not read local project .hdpc at {hdpc_path}: {exc}") from exc

    pipeline_timings["project_loading"] = time.time() - load_start

    if not file_id_map:
        raise FileProcessingError("Could not find any files in the project .hdpc")
    normalized_file_id_map = {
        _normalize_rel_path(relative_path): file_id
        for relative_path, file_id in file_id_map.items()
        if not _has_excluded_segment(relative_path)
    }
    file_id_to_relative_path = {str(file_id): relative_path for relative_path, file_id in normalized_file_id_map.items()}
    bundle_file_paths_by_relative = _build_bundle_file_paths_by_relative(inspect_data.get("file_tree", []))
    basename_to_relative_paths: Dict[str, List[str]] = {}
    relative_to_absolute_path: Dict[str, str] = {}
    absolute_to_relative_path: Dict[str, str] = {}
    for node in _iter_file_nodes(inspect_data.get("file_tree", [])):
        relative_path = _normalize_rel_path(node.get("relative_path"))
        absolute_path = node.get("absolute_path")
        if not relative_path or _has_excluded_segment(relative_path):
            continue
        relative_to_absolute_path[relative_path] = absolute_path
        if isinstance(absolute_path, str) and absolute_path:
            absolute_to_relative_path[os.path.normpath(absolute_path)] = relative_path
        basename = os.path.basename(relative_path).lower()
        basename_to_relative_paths.setdefault(basename, []).append(relative_path)

    from services.lod_reliability import capture_session_lod, MetadataRows
    lod_snapshot = None
    if precreated_run_public_id:
        from database.models import PipelineRun
        queued_run = PipelineRun.query.filter_by(public_id=precreated_run_public_id).first()
        if queued_run:
            lod_snapshot = json.loads(queued_run.request_json or '{}').get('lod_snapshot')
    lod_snapshot = lod_snapshot or capture_session_lod(db_session_id)
    shared_zenodo_metadata = lod_snapshot['metadata']
    batch_metadata_map = MetadataRows(lod_snapshot['batch'].items(), normalized_file_id_map)
    has_batch_metadata = bool(batch_metadata_map)

    batch_shared_zenodo_metadata, batch_item_defaults = _split_batch_shared_zenodo_metadata(shared_zenodo_metadata)

    lod_mapping_config = shared_zenodo_metadata.get("lod_mapping") if isinstance(shared_zenodo_metadata, dict) else None
    lod_msf_path = shared_zenodo_metadata.get("msf_path") or lod_snapshot["profile"].get("file_path")
    lod_msf_candidates = _resolve_lod_msf_candidates(
        hdpc_path,
        lod_msf_path if isinstance(lod_msf_path, str) else None,
    )
    resolved_lod_msf_path = next((path for path in lod_msf_candidates if os.path.exists(path)), None)
    msf_rows_by_filename: Dict[str, Any] = {}
    if lod_mapping_config:
        if not resolved_lod_msf_path:
            raise FileProcessingError(
                "LOD mapping is configured but no MSF source was found. Expected one of: "
                + ", ".join(lod_msf_candidates)
            )
        try:
            if lod_snapshot.get("msf_sha256"):
                from services.lod_reliability import digest
                with open(resolved_lod_msf_path, "rb") as stream:
                    if digest(stream.read()) != lod_snapshot["msf_sha256"]:
                        raise FileProcessingError("The MSF changed after this run was queued. Repeat preflight and start a new run.")
            msf_service = current_app.msf_service
            msf_df, _ = msf_service.parse_msf_file(resolved_lod_msf_path, parse_options=shared_zenodo_metadata.get("msf_parse_options") or lod_snapshot["profile"].get("parse_options") or {})
            candidate_filenames_for_detection = list(normalized_file_id_map) + [os.path.basename(path) for path in local_file_paths]
            if not candidate_filenames_for_detection and execution_items:
                candidate_filenames_for_detection = [
                    str(item.get("source_file_name") or os.path.basename(str(item.get("source_file_path") or ""))).strip()
                    for item in execution_items
                    if str(item.get("source_file_path") or "").strip()
                ]
            filename_col, _ = msf_service.detect_filename_column(
                msf_df,
                candidate_filenames_for_detection,
            )
            if not filename_col:
                raise FileProcessingError(
                    f"LOD mapping MSF source '{resolved_lod_msf_path}' does not contain a usable filename column."
                )
            msf_rows_by_filename = MetadataRows(
                ((row.get(filename_col, ""), row) for _, row in msf_df.iterrows()),
                normalized_file_id_map,
            )
            logger.info(
                "Loaded LOD mapping source MSF for %s rows using filename column '%s'.",
                len(msf_rows_by_filename),
                filename_col,
            )
        except FileProcessingError:
            raise
        except Exception as exc:
            raise FileProcessingError(
                f"Failed to load LOD mapping MSF source '{resolved_lod_msf_path}': {exc}"
            ) from exc

    has_per_file_msf_rows = bool(lod_mapping_config and msf_rows_by_filename)
    uses_per_file_metadata = has_batch_metadata or has_per_file_msf_rows

    if not uses_per_file_metadata and not shared_zenodo_metadata and not record_ids and not execution_items:
        raise FileProcessingError("No metadata found. Please fill in metadata before running the pipeline.")

    _emit_progress(
        progress_callback,
        {
            "current_stage": "registering_records",
            "status_message": "Registering records",
            "current_index": 0,
            "total_files": total_requested,
            "processed_count": 0,
            "failed_count": 0,
        },
    )

    record_ids_to_process: List[int] = []
    record_info_list: List[Tuple[int, str, Dict[str, Any]]] = []
    skipped_files: List[str] = []
    record_resolution_by_record_id: Dict[int, Dict[str, Any]] = {}

    uploads_dir = os.path.join(os.path.dirname(hdpc_path), "uploads")
    input_dir = None
    for config_item in inspect_data.get("configuration", []):
        if config_item.get("config_key") == "paths.data_in":
            input_dir = config_item.get("config_value")
            break

    def resolve_execution_source(file_path: str) -> Dict[str, Any] | None:
        if not file_path:
            return None
        filename = os.path.basename(file_path)
        if file_path.startswith(uploads_dir):
            relative_path = _normalize_rel_path(os.path.relpath(file_path, uploads_dir))
        elif input_dir and file_path.startswith(input_dir):
            relative_path = _normalize_rel_path(os.path.relpath(file_path, input_dir))
        else:
            relative_path = _normalize_rel_path(os.path.basename(file_path))

        file_id = normalized_file_id_map.get(relative_path)
        if not file_id:
            absolute_match = absolute_to_relative_path.get(os.path.normpath(file_path))
            if absolute_match:
                relative_path = absolute_match
                file_id = normalized_file_id_map.get(relative_path)
        if not file_id:
            matches = basename_to_relative_paths.get(os.path.basename(file_path).lower(), [])
            if len(matches) == 1:
                relative_path = matches[0]
                file_id = normalized_file_id_map.get(relative_path)
        if not file_id:
            return None

        effective_file_path = file_path
        resolved_relative_path = relative_path
        filename_lower = filename.lower()
        file_metadata = None
        if uses_per_file_metadata:
            original_file_id = file_id
            if has_batch_metadata:
                file_id, effective_file_path, file_metadata = _resolve_metadata_linked_asset(
                    selected_file_path=file_path,
                    selected_file_id=file_id,
                    batch_metadata_map=batch_metadata_map,
                    basename_to_relative_paths=basename_to_relative_paths,
                    normalized_file_id_map=normalized_file_id_map,
                    relative_to_absolute_path=relative_to_absolute_path,
                )
                if file_id != original_file_id or effective_file_path != file_path:
                    current_app.logger.info(
                        "Resolved selected file %s to metadata-linked asset %s for record registration.",
                        file_path,
                        effective_file_path,
                    )
                    filename = os.path.basename(effective_file_path)
                    filename_lower = filename.lower()
                    resolved_relative_path = (
                        file_id_to_relative_path.get(str(file_id))
                        or absolute_to_relative_path.get(os.path.normpath(effective_file_path))
                        or resolved_relative_path
                    )

            if file_metadata:
                zenodo_metadata = _merge_non_empty_metadata(batch_shared_zenodo_metadata, file_metadata)
            else:
                zenodo_metadata = dict(batch_shared_zenodo_metadata)
        else:
            zenodo_metadata = dict(shared_zenodo_metadata)

        lod_row = msf_rows_by_filename.get(resolved_relative_path or filename)
        if lod_mapping_config and lod_row is None:
            raise FileProcessingError(f"No metadata row matches {resolved_relative_path or filename}. Use the exact relative source path in the MSF.")
        if lod_row is not None and lod_mapping_config:
            modality = _infer_lod_modality(filename, zenodo_metadata)
            zenodo_mapping_for_modality = _extract_standard_mapping(
                lod_mapping_config,
                "zenodo",
                modality,
            )
            if zenodo_mapping_for_modality:
                zenodo_record_for_mapping = {
                    "metadata": zenodo_metadata,
                }
                mapped_zenodo_values = current_app.msf_service.apply_lod_mapping(
                    lod_row,
                    zenodo_record_for_mapping,
                    zenodo_mapping_for_modality,
                    include_defaults=False,
                )
                zenodo_metadata = _merge_non_empty_metadata(zenodo_metadata, mapped_zenodo_values)

        if uses_per_file_metadata:
            zenodo_metadata["edm_main_file_key"] = os.path.basename(effective_file_path)
        zenodo_metadata = publishing_context_service.apply_community_policy(db_session, zenodo_metadata)
        raw_submission_metadata = {
            k: v
            for k, v in zenodo_metadata.items()
            if not k.startswith("edm_")
            and not k.startswith("_")
            and k not in INTERNAL_ZENODO_KEYS
        }
        zenodo_submission_metadata = normalize_zenodo_metadata(
            raw_submission_metadata,
            apply_defaults=True,
            fallback_title=_derive_batch_fallback_title(zenodo_metadata, filename),
            fallback_description=NEUTRAL_ITEM_DESCRIPTION if uses_per_file_metadata else None,
            fallback_creators=(
                _derive_batch_fallback_creators(zenodo_metadata, batch_item_defaults)
                if uses_per_file_metadata
                else None
            ),
        )
        lod_base_metadata = _merge_non_empty_metadata(zenodo_metadata, zenodo_submission_metadata)

        bundle_paths = bundle_file_paths_by_relative.get(resolved_relative_path, [])
        paths_to_associate: List[str] = []
        seen_paths = set()
        for candidate_path in [effective_file_path] + list(bundle_paths):
            if not isinstance(candidate_path, str) or not candidate_path:
                continue
            normalized = os.path.normpath(candidate_path)
            if normalized in seen_paths:
                continue
            seen_paths.add(normalized)
            paths_to_associate.append(candidate_path)
        if not paths_to_associate:
            paths_to_associate = [effective_file_path]

        source_bundle = create_source_bundle(
            effective_file_path, inspect_data.get("file_tree", []),
            os.path.join(os.path.dirname(hdpc_path), "outputs", "source-bundles"),
        )
        if source_bundle:
            names = [os.path.basename(path).casefold() for path in paths_to_associate]
            if len(names) != len(set(names)):
                paths_to_associate = [effective_file_path]
            paths_to_associate.append(source_bundle)

        return {
            "file_id": file_id,
            "filename": filename,
            "effective_file_path": effective_file_path,
            "resolved_relative_path": resolved_relative_path,
            "zenodo_submission_metadata": zenodo_submission_metadata,
            "lod_base_metadata": lod_base_metadata,
            "paths_to_associate": paths_to_associate,
        }

    reg_start = time.time()
    if using_execution_items:
        validated_resolution_candidates = _validate_execution_items_against_resolution_state(db_session, execution_items)
        for idx, item in enumerate(execution_items):
            action = str(item.get("action") or "").strip().lower()
            file_path = str(item.get("source_file_path") or "").strip()
            filename = str(item.get("source_file_name") or os.path.basename(file_path)).strip() or os.path.basename(file_path)
            _emit_progress(
                progress_callback,
                {
                    "current_stage": "registering_records",
                    "status_message": f"Applying record resolution for {filename}",
                    "current_file_name": filename,
                    "current_index": idx + 1,
                    "total_files": total_requested,
                    "processed_count": 0,
                    "failed_count": 0,
                },
            )
            if action == "skip":
                skipped_files.append(file_path or filename)
                continue

            source_context = resolve_execution_source(file_path)
            if source_context is None:
                skipped_files.append(file_path or filename)
                continue

            candidate_resolution = validated_resolution_candidates.get(str(item.get("decision_key") or "").strip(), {})
            try:
                if action in {"create_fresh_record", "force_create_fresh"}:
                    if action == "create_fresh_record":
                        ensure_fresh_record_creation_allowed(
                            db_session,
                            source_file_path=source_context["effective_file_path"],
                            is_sandbox=effective_is_sandbox,
                        )
                    created_record = create_local_record_with_metadata(
                        hdpc_path,
                        file_id=source_context["file_id"],
                        metadata=source_context["zenodo_submission_metadata"],
                        is_sandbox=effective_is_sandbox,
                        access_token=access_token,
                    )
                    local_record_id = created_record.get("local_record_db_id")
                    if not local_record_id:
                        skipped_files.append(file_path)
                        continue
                    add_local_source_files(
                        hdpc_path,
                        absolute_file_paths=source_context["paths_to_associate"],
                        record_id_to_associate=local_record_id,
                        pipeline_name="ingestion",
                        step_name="source_file_registration",
                    )
                    if action == "force_create_fresh":
                        record_audit_event(
                            actor_user_id=db_session.user_id,
                            institution_id=db_session.institution_id,
                            session_id=db_session.id,
                            event_type="record_resolution_force_create_fresh",
                            entity_type="session",
                            entity_id=db_session.id,
                            details={
                                "decision_key": item.get("decision_key"),
                                "source_file_path": source_context["effective_file_path"],
                                "reason": item.get("forced_override_reason"),
                            },
                        )
                        db.session.commit()
                elif action == "create_version":
                    target_session_id = int(item.get("target_session_id") or 0)
                    target_local_record_id = int(item.get("target_local_record_id") or 0)
                    target_record = _resolve_version_target_record(target_session_id, target_local_record_id)
                    prepared_version = current_app.project_service.prepare_new_version_draft(
                        concept_rec_id=str(item.get("target_concept_rec_id") or target_record.get("concept_rec_id") or ""),
                        is_sandbox=effective_is_sandbox,
                        source_file_path=source_context["effective_file_path"],
                        absolute_file_paths=source_context["paths_to_associate"],
                        hdpc_path=hdpc_path,
                        access_token=access_token,
                        reference_record=target_record,
                    )
                    local_record_id = prepared_version.get("new_local_record_id") or prepared_version.get("local_record_db_id")
                    if not local_record_id:
                        skipped_files.append(file_path)
                        continue
                    record_resolution_by_record_id[int(local_record_id)] = {
                        "decision_key": item.get("decision_key"),
                        "action": "create_version",
                        "prepared_draft_result": prepared_version,
                        "target_session_id": target_session_id,
                        "target_local_record_id": target_local_record_id,
                        "target_concept_rec_id": str(item.get("target_concept_rec_id") or "") or None,
                    }
                else:
                    skipped_files.append(file_path or filename)
                    continue

                record_ids_to_process.append(int(local_record_id))
                record_info_list.append((int(local_record_id), source_context["effective_file_path"], source_context["lod_base_metadata"]))
                record_resolution_by_record_id.setdefault(
                    int(local_record_id),
                    {
                        "decision_key": item.get("decision_key"),
                        "action": action,
                        "severity": candidate_resolution.get("severity"),
                    },
                )
            except Exception as exc:
                details = getattr(exc, "details", None)
                current_app.logger.error(
                    "Failed to apply record resolution for %s: %s%s",
                    file_path,
                    exc,
                    f" | details={details}" if details else "",
                )
                skipped_files.append(file_path)
    elif using_existing_record_ids:
        session_records = {
            int(record.get("local_record_id")): record
            for record in read_session_records(db_session)
            if record.get("local_record_id") is not None
        }
        for idx, record_id in enumerate(record_ids):
            session_record = session_records.get(int(record_id))
            if not session_record:
                skipped_files.append(str(record_id))
                continue
            source_file_path = str(session_record.get("source_file_path") or "").strip()
            if not source_file_path:
                skipped_files.append(str(record_id))
                continue
            source_bundle = create_source_bundle(
                source_file_path, inspect_data.get("file_tree", []),
                os.path.join(os.path.dirname(hdpc_path), "outputs", "source-bundles"),
            )
            if source_bundle:
                add_local_source_files(
                    hdpc_path, absolute_file_paths=[source_bundle],
                    record_id_to_associate=int(record_id),
                    pipeline_name="ingestion", step_name="source_bundle",
                )
            source_metadata = session_record.get("record_metadata") if isinstance(session_record.get("record_metadata"), dict) else {}
            record_ids_to_process.append(int(record_id))
            record_info_list.append((int(record_id), source_file_path, _merge_non_empty_metadata({}, source_metadata)))
            _emit_progress(
                progress_callback,
                {
                    "current_stage": "registering_records",
                    "status_message": f"Resolved existing record {record_id}",
                    "current_file_name": os.path.basename(source_file_path),
                    "current_index": idx + 1,
                    "total_files": total_requested,
                    "processed_count": 0,
                    "failed_count": 0,
                },
            )
    else:
        for idx, file_path in enumerate(local_file_paths):
            if not file_path:
                logger.warning("Received null file_path in pipeline execution request. Skipping.")
                continue

            filename = os.path.basename(file_path)
            _emit_progress(
                progress_callback,
                {
                    "current_stage": "registering_records",
                    "status_message": f"Registering {filename}",
                    "current_file_name": filename,
                    "current_index": idx + 1,
                    "total_files": total_requested,
                    "processed_count": 0,
                    "failed_count": 0,
                },
            )
            source_context = resolve_execution_source(file_path)
            if source_context is None:
                skipped_files.append(file_path)
                continue
            try:
                ensure_fresh_record_creation_allowed(
                    db_session,
                    source_file_path=source_context["effective_file_path"],
                    is_sandbox=effective_is_sandbox,
                )
                created_record = create_local_record_with_metadata(
                    hdpc_path,
                    file_id=source_context["file_id"],
                    metadata=source_context["zenodo_submission_metadata"],
                    is_sandbox=effective_is_sandbox,
                    access_token=access_token,
                )
                local_record_id = created_record.get("local_record_db_id")
                if not local_record_id:
                    skipped_files.append(file_path)
                    continue

                record_ids_to_process.append(local_record_id)
                record_info_list.append((local_record_id, source_context["effective_file_path"], source_context["lod_base_metadata"]))

                add_local_source_files(
                    hdpc_path,
                    absolute_file_paths=source_context["paths_to_associate"],
                    record_id_to_associate=local_record_id,
                    pipeline_name="ingestion",
                    step_name="source_file_registration",
                )
            except Exception as exc:
                details = getattr(exc, "details", None)
                current_app.logger.error(
                    "Failed to create record for %s: %s%s",
                    file_path,
                    exc,
                    f" | details={details}" if details else "",
                )
                skipped_files.append(file_path)

    pipeline_timings["record_registration"] = time.time() - reg_start

    if not record_ids_to_process:
        if using_existing_record_ids:
            raise FileProcessingError("Could not resolve any existing records for processing")
        if using_execution_items:
            raise FileProcessingError("Could not resolve any record-resolution execution targets for processing")
        raise FileProcessingError("Could not create any records for processing")

    total_records = len(record_info_list)
    processed_count = 0
    failed_count = 0
    successful_count = 0

    processed_results: List[Dict[str, Any]] = []
    converter_failures: List[Dict[str, Any]] = []

    session_dir = os.path.dirname(hdpc_path)
    outputs_dir = os.path.join(session_dir, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)

    pipeline_config = current_app.native_pipeline_service.get_pipeline(identifier).get("config", {})
    steps_map = {step["id"]: step for step in pipeline_config.get("steps", [])}
    if not current_app.config.get("ENABLE_RENDERER", True) and steps_map.get("fast_renderer"):
        steps_map["fast_renderer"]["enabled"] = False
    if not current_app.config.get("ENABLE_USDZ_CONVERSION", True) and steps_map.get("any_to_usdz"):
        steps_map["any_to_usdz"]["enabled"] = False

    execution_context = {
        "identifier": identifier,
        "canonical_identifier": current_app.native_pipeline_service.resolve_pipeline_identifier(identifier),
        "local_file_paths": [] if (using_existing_record_ids or using_execution_items) else local_file_paths,
        "record_ids": record_ids_to_process,
        "execution_items": execution_items,
        "db_session_id": db_session_id,
        "db_session": db_session,
        "hdpc_path": hdpc_path,
        "is_sandbox": effective_is_sandbox,
        "access_token": access_token,
        "zenodo_environment": publishing_context["environment"],
        "credential_source": publishing_context["credential_source"],
        "publishing_context": publishing_context,
        "abort_on_critical_error": abort_on_critical_error,
        "progress_callback": progress_callback,
        "pipeline_timings": pipeline_timings,
        "record_info_list": record_info_list,
        "skipped_files": skipped_files,
        "record_resolution_by_record_id": record_resolution_by_record_id,
        "outputs_dir": outputs_dir,
        "batch_metadata_map": batch_metadata_map,
        "shared_zenodo_metadata": shared_zenodo_metadata,
        "batch_shared_zenodo_metadata": batch_shared_zenodo_metadata,
        "batch_item_defaults": batch_item_defaults,
        "lod_mapping_config": lod_mapping_config,
        "resolved_lod_msf_path": resolved_lod_msf_path,
        "msf_rows_by_filename": msf_rows_by_filename,
        "lod_source_paths": absolute_to_relative_path,
        "lod_templates": lod_snapshot["templates"],
        "normalized_file_id_map": normalized_file_id_map,
        "file_id_to_relative_path": file_id_to_relative_path,
        "bundle_file_paths_by_relative": bundle_file_paths_by_relative,
        "basename_to_relative_paths": basename_to_relative_paths,
        "relative_to_absolute_path": relative_to_absolute_path,
        "absolute_to_relative_path": absolute_to_relative_path,
        "steps_map": steps_map,
    }
    exec_data = current_app.native_pipeline_service.execute_registered_submission(
        identifier,
        execution_context,
        existing_run_public_id=precreated_run_public_id,
    )
    summary = exec_data.get("summary", {})
    successful_count = int(summary.get("successful_count", 0) or 0)
    failed_count = int(summary.get("failed_count", 0) or 0)
    processed_count = int(summary.get("processed_count", 0) or 0)

    pipeline_timings["total_execution"] = time.time() - main_start

    _emit_progress(
        progress_callback,
        {
            "current_stage": "completed",
            "status_message": "Pipeline execution completed",
            "current_index": total_records,
            "total_files": total_records,
            "processed_count": processed_count,
            "failed_count": failed_count,
            "converter_failed_count": len(converter_failures),
        },
    )

    return {
        "result": exec_data,
        "timings": pipeline_timings,
        "progress_summary": {
            "total_files": total_records,
            "processed_count": processed_count,
            "failed_count": failed_count,
            "successful_count": successful_count,
            "skipped_count": len(skipped_files),
            "converter_failed_count": len(converter_failures),
        },
    }
