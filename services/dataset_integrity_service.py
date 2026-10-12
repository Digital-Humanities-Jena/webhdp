import csv
import io
import json
import os
import re
import sqlite3
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlparse

import requests
from flask import current_app

from constants import RECORD_RESOLUTION_STATE_FIELD
from database.database import db
from database.models import BatchFileMetadata, Session as DBSession, User, UserMetadata
from services.hdpc_local_service import (
    _file_sha256,
    classify_hdpc_record_inventory,
    is_canonical_hdpc_record,
    normalize_hdpc_record_origin,
)
from services.session_access_service import get_accessible_sessions
from services.version_detection_policy_service import VersionDetectionPolicyService


PRIMARY_CSV_COLUMNS = [
    "original_filename",
    "zenodo_doi",
    "glb_direct_link",
    "record_link",
    "zenodo_record_id",
    "record_status",
    "session_id",
    "local_record_id",
]
THREE_D_FILE_EXTENSIONS = {".glb", ".gltf", ".obj", ".ply", ".stl", ".fbx", ".usdz"}
INLINE_MODEL_FILE_EXTENSIONS = {".glb", ".gltf"}
THUMBNAIL_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
PREFERRED_DATASET_SUFFIX = "_dataset"
VALID_ENVIRONMENTS = {"all", "production", "sandbox"}
GENERATED_RENDER_MARKERS = {
    "derived",
    "generated",
    "preview",
    "render",
    "rendered",
    "thumbnail",
    "fast_renderer",
}
SESSION_RECORD_CACHE_LIMIT = 128
_SESSION_RECORD_CACHE: "OrderedDict[tuple[Any, ...], dict[str, Any]]" = OrderedDict()
VALID_RESOLUTION_ACTIONS = {
    "create_fresh_record",
    "create_version",
    "skip",
    "force_create_fresh",
}
VALID_RESOLUTION_PRESETS = {"strict", "balanced", "permissive"}


class DatasetIntegrityConflictError(Exception):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


@dataclass(frozen=True)
class CandidateFile:
    source_file_path: str
    source_file_name: str
    dataset_key: str
    normalized_source_file_path: str
    is_sandbox: bool
    concept_rec_id: str = ""
    sha256_hash: str = ""
    size_bytes: int | None = None
    mime_type: str = ""
    file_type: str = ""
    file_purpose: str = ""
    pipeline_source: str = ""
    step_source: str = ""
    session_id: int | None = None
    local_record_id: int | None = None
    metadata: dict[str, Any] | None = None


def build_record_resolution_decision_key(dataset_key: Any, normalized_source_file_path: Any) -> str:
    dataset_part = normalize_dataset_key_lower(dataset_key)
    path_part = str(normalized_source_file_path or "").strip().lower()
    return f"{dataset_part}::{path_part}"


def normalize_record_resolution_action(raw_value: Any) -> str | None:
    action = str(raw_value or "").strip().lower()
    return action if action in VALID_RESOLUTION_ACTIONS else None


def normalize_record_resolution_preset(raw_value: Any) -> str | None:
    preset = str(raw_value or "").strip().lower()
    return preset if preset in VALID_RESOLUTION_PRESETS else None


def normalize_candidate_metadata(raw_value: Any) -> dict[str, Any]:
    if not isinstance(raw_value, dict):
        return {}
    return {
        key: value
        for key, value in raw_value.items()
        if not str(key).startswith("_internal_")
    }


def merge_candidate_metadata(*payloads: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key, value in payload.items():
            if value in (None, "", [], {}):
                continue
            merged[key] = value
    return merged


def _word_tokens(value: Any) -> list[str]:
    text = str(value or "").strip().lower()
    if not text:
        return []
    return [token for token in re.split(r"[^a-z0-9]+", text) if token]


def _string_similarity(left: Any, right: Any) -> float:
    left_tokens = set(_word_tokens(left))
    right_tokens = set(_word_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    if left_tokens == right_tokens:
        return 1.0
    intersection = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    if union <= 0:
        return 0.0
    return round(intersection / union, 3)


def _normalize_creator_names(raw_value: Any) -> list[str]:
    names: list[str] = []
    values = raw_value if isinstance(raw_value, list) else [raw_value]
    for item in values:
        if isinstance(item, dict):
            candidate = item.get("name")
        else:
            candidate = item
        text = str(candidate or "").strip()
        if text:
            names.append(text)
    return names


def _metadata_identity_view(metadata: dict[str, Any]) -> dict[str, Any]:
    normalized = metadata if isinstance(metadata, dict) else {}
    nested = normalized.get("metadata") if isinstance(normalized.get("metadata"), dict) else normalized
    publication_date = str(
        nested.get("publication_date")
        or normalized.get("publication_date")
        or nested.get("date")
        or normalized.get("date")
        or ""
    ).strip()
    publication_year = publication_date[:4] if len(publication_date) >= 4 and publication_date[:4].isdigit() else ""

    identifiers: set[str] = set()
    for candidate in [
        nested.get("doi"),
        normalized.get("doi"),
        nested.get("_external_identifier"),
        normalized.get("_external_identifier"),
        nested.get("identifier"),
        normalized.get("identifier"),
    ]:
        text = str(candidate or "").strip()
        if text:
            identifiers.add(text.lower())
    related_identifiers = nested.get("related_identifiers") if isinstance(nested.get("related_identifiers"), list) else []
    for item in related_identifiers:
        if not isinstance(item, dict):
            continue
        text = str(item.get("identifier") or "").strip()
        if text:
            identifiers.add(text.lower())

    creators = _normalize_creator_names(nested.get("creators") or normalized.get("creators"))
    title = str(nested.get("title") or normalized.get("title") or "").strip()
    return {
        "title": title,
        "creators": creators,
        "publication_date": publication_date,
        "publication_year": publication_year,
        "identifiers": sorted(identifiers),
    }


def _record_identity_metadata(record: dict[str, Any]) -> dict[str, Any]:
    metadata = record.get("record_metadata") if isinstance(record.get("record_metadata"), dict) else {}
    base = _metadata_identity_view(metadata)
    if not base.get("title"):
        base["title"] = str(record.get("record_title") or "").strip()
    return base


def _candidate_identity_metadata(candidate: CandidateFile) -> dict[str, Any]:
    return _metadata_identity_view(candidate.metadata or {})


def _shared_candidate_metadata_for_session(session_row: DBSession) -> dict[str, Any]:
    metadata_fields = get_session_metadata_map(session_row.id, {"zenodo_metadata_draft"})
    draft_metadata = parse_json(metadata_fields.get("zenodo_metadata_draft"), {})
    if not isinstance(draft_metadata, dict):
        return {}
    return {
        key: value
        for key, value in draft_metadata.items()
        if not str(key).startswith("_")
        and key not in {"lod_mapping", "msf_path"}
    }


def _batch_candidate_metadata_by_filename(session_row: DBSession) -> dict[str, dict[str, Any]]:
    by_filename: dict[str, dict[str, Any]] = {}
    for row in BatchFileMetadata.query.filter_by(session_id=session_row.id).all():
        parsed = parse_json(row.metadata_json, {})
        if isinstance(parsed, dict):
            by_filename[row.filename.lower()] = parsed
    return by_filename


def _record_uploaded_filenames(record: dict[str, Any]) -> set[str]:
    filenames: set[str] = set()
    for item in record.get("record_files") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("upload_status") or "").strip().lower() != "uploaded":
            continue
        filename = str(item.get("filename") or item.get("mapped_file_path") or "").strip()
        if filename:
            filenames.add(os.path.basename(filename).lower())
    return filenames


def _record_is_missing_repair_assets(record: dict[str, Any]) -> bool:
    if str(record.get("record_status") or "").strip().lower() != "published":
        return False
    if not str(record.get("concept_rec_id") or "").strip():
        return False
    source_name = str(record.get("source_file_name") or record.get("source_file_path") or "").strip().lower()
    if not source_name or os.path.splitext(source_name)[1].lower() not in THREE_D_FILE_EXTENSIONS:
        return False
    uploaded_filenames = _record_uploaded_filenames(record)
    return not any(os.path.splitext(name)[1].lower() in THUMBNAIL_IMAGE_EXTENSIONS for name in uploaded_filenames)


def _hash_collision_policy(config: dict[str, Any] | None) -> dict[str, Any]:
    raw_policy = (config or {}).get("hash_collision_policy")
    defaults = VersionDetectionPolicyService.DEFAULT_HASH_COLLISION_POLICY
    if not isinstance(raw_policy, dict):
        raw_policy = {}

    raw_extensions = raw_policy.get("excluded_extensions", defaults["excluded_extensions"])
    if isinstance(raw_extensions, str):
        raw_extensions = [item.strip() for item in raw_extensions.split(",")]
    if not isinstance(raw_extensions, list):
        raw_extensions = defaults["excluded_extensions"]

    excluded_extensions = {
        extension if extension.startswith(".") else f".{extension}"
        for extension in (str(item or "").strip().lower() for item in raw_extensions)
        if extension
    }

    return {
        "enabled": bool(raw_policy.get("enabled", defaults["enabled"])),
        "min_size_bytes": max(parse_int(raw_policy.get("min_size_bytes"), defaults["min_size_bytes"]), 0),
        "excluded_extensions": excluded_extensions,
        "exclude_generated_renders": bool(
            raw_policy.get("exclude_generated_renders", defaults["exclude_generated_renders"])
        ),
    }


def _metadata_has_generated_render_marker(*values: Any) -> bool:
    for value in values:
        text = str(value or "").strip().lower()
        if not text:
            continue
        if any(marker in text for marker in GENERATED_RENDER_MARKERS):
            return True
    return False


def _candidate_is_hash_collision_exempt(candidate: CandidateFile, policy: dict[str, Any]) -> bool:
    extension = os.path.splitext(candidate.source_file_name or candidate.source_file_path or "")[1].lower()
    if extension and extension in policy.get("excluded_extensions", set()):
        return True

    if candidate.size_bytes is not None and int(candidate.size_bytes or 0) < int(policy.get("min_size_bytes") or 0):
        return True

    if policy.get("exclude_generated_renders") and _metadata_has_generated_render_marker(
        candidate.file_type,
        candidate.file_purpose,
        candidate.pipeline_source,
        candidate.step_source,
    ):
        return True

    return False


def _record_is_hash_collision_exempt(record: dict[str, Any], policy: dict[str, Any]) -> bool:
    extension = os.path.splitext(str(record.get("source_file_name") or record.get("source_file_path") or ""))[1].lower()
    if extension and extension in policy.get("excluded_extensions", set()):
        return True

    size_value = record.get("source_size_bytes")
    if size_value not in (None, "") and parse_int(size_value) < int(policy.get("min_size_bytes") or 0):
        return True

    if policy.get("exclude_generated_renders"):
        record_files = record.get("record_files") if isinstance(record.get("record_files"), list) else []
        file_purposes = [item.get("file_purpose") for item in record_files if isinstance(item, dict)]
        if _metadata_has_generated_render_marker(
            record.get("source_file_type"),
            record.get("source_pipeline_source"),
            record.get("source_step_source"),
            *file_purposes,
        ):
            return True

    return False


def find_global_hash_collision_records(
    candidate: CandidateFile,
    records: list[dict[str, Any]],
    *,
    config: dict[str, Any] | None = None,
    exclude_record: tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    policy = _hash_collision_policy(config)
    candidate_hash = str(candidate.sha256_hash or "").strip()
    if not policy.get("enabled") or not candidate_hash or _candidate_is_hash_collision_exempt(candidate, policy):
        return []

    matches: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for record in records:
        record_ref = (int(record.get("session_id") or 0), int(record.get("local_record_id") or 0))
        if exclude_record and record_ref == exclude_record:
            continue
        if record_ref in seen:
            continue
        if str(record.get("source_sha256_hash") or "").strip() != candidate_hash:
            continue
        if _record_is_hash_collision_exempt(record, policy):
            continue
        matches.append(record)
        seen.add(record_ref)

    matches.sort(
        key=lambda item: (
            1 if str(item.get("record_status") or "").strip().lower() == "published" else 0,
            normalized_version_rank(item),
            parse_timestamp(item.get("updated_at")),
            parse_int(item.get("local_record_id")),
        ),
        reverse=True,
    )
    return matches


def _soft_match_score(
    candidate: CandidateFile,
    record: dict[str, Any],
    *,
    config: dict[str, Any],
) -> dict[str, Any]:
    candidate_meta = _candidate_identity_metadata(candidate)
    record_meta = _record_identity_metadata(record)
    enabled_signals = config.get("enabled_signals") if isinstance(config.get("enabled_signals"), dict) else {}

    exact_hash = bool(
        enabled_signals.get("hash_matching", True)
        and candidate.sha256_hash
        and str(record.get("source_sha256_hash") or "").strip()
        and str(record.get("source_sha256_hash") or "").strip() == str(candidate.sha256_hash).strip()
    )
    exact_filename = bool(
        candidate.source_file_name
        and normalize_filename(record.get("source_file_name")) == normalize_filename(candidate.source_file_name)
    )

    title_similarity = 0.0
    creator_overlap: list[str] = []
    publication_year_match = False
    identifier_overlap: list[str] = []
    if enabled_signals.get("metadata_similarity", True):
        title_similarity = _string_similarity(candidate_meta.get("title"), record_meta.get("title"))
        candidate_creators = {item.lower() for item in candidate_meta.get("creators") or []}
        record_creators = {item.lower() for item in record_meta.get("creators") or []}
        creator_overlap = sorted(candidate_creators & record_creators)
        publication_year_match = bool(
            candidate_meta.get("publication_year")
            and record_meta.get("publication_year")
            and candidate_meta.get("publication_year") == record_meta.get("publication_year")
        )
        identifier_overlap = sorted(
            set(candidate_meta.get("identifiers") or []) & set(record_meta.get("identifiers") or [])
        )

    score = 0.0
    if exact_hash:
        score += 0.75
    if exact_filename:
        score += 0.20
    if title_similarity >= 0.95:
        score += 0.10
    elif title_similarity >= 0.50:
        score += 0.05
    if creator_overlap:
        score += 0.05
    if publication_year_match:
        score += 0.03
    if identifier_overlap:
        score += 0.05
    if str(record.get("record_status") or "").strip().lower() == "published":
        score += 0.05
    score = min(round(score, 3), 1.0)

    reason_codes: list[str] = []
    if exact_hash:
        reason_codes.append("exact_source_hash_match")
    if exact_filename:
        reason_codes.append("exact_filename_match")
    if title_similarity >= 0.50:
        reason_codes.append("metadata_title_similarity")
    if creator_overlap:
        reason_codes.append("metadata_creators_overlap")
    if publication_year_match:
        reason_codes.append("metadata_publication_year_match")
    if identifier_overlap:
        reason_codes.append("metadata_identifier_overlap")

    return {
        "score": score,
        "reason_codes": reason_codes,
        "signals": {
            "exact_source_hash": {
                "matched": exact_hash,
                "weight": 0.75,
            },
            "exact_filename": {
                "matched": exact_filename,
                "weight": 0.20,
            },
            "metadata_similarity": {
                "enabled": bool(enabled_signals.get("metadata_similarity", True)),
                "title_similarity": title_similarity,
                "creator_overlap": creator_overlap,
                "publication_year_match": publication_year_match,
                "identifier_overlap": identifier_overlap,
            },
            "record_state": {
                "published": str(record.get("record_status") or "").strip().lower() == "published",
                "same_environment": bool(record.get("is_sandbox")) == bool(candidate.is_sandbox),
            },
        },
    }


def _confidence_label(score: float, *, version_threshold: float, warning_threshold: float) -> str:
    if score >= version_threshold + 0.08:
        return "high"
    if score >= version_threshold:
        return "medium"
    if score >= warning_threshold + 0.15:
        return "medium"
    if score >= warning_threshold:
        return "low"
    return "low"


def parse_record_resolution_state(raw_value: Any) -> dict[str, Any]:
    parsed = parse_json(raw_value, {})
    if not isinstance(parsed, dict):
        parsed = {}
    policy_override = normalize_record_resolution_preset(parsed.get("policy_override"))
    normalized_decisions: list[dict[str, Any]] = []
    for item in parsed.get("decisions") or []:
        if not isinstance(item, dict):
            continue
        decision_key = str(item.get("decision_key") or "").strip()
        action = normalize_record_resolution_action(item.get("action"))
        if not decision_key or not action:
            continue
        normalized_decisions.append(
            {
                "decision_key": decision_key,
                "action": action,
                "resolved": bool(item.get("resolved", False)),
                "target_session_id": parse_int(item.get("target_session_id")) or None,
                "target_local_record_id": parse_int(item.get("target_local_record_id")) or None,
                "target_concept_rec_id": str(item.get("target_concept_rec_id") or "").strip() or None,
                "forced_override_reason": str(item.get("forced_override_reason") or "").strip() or None,
                "updated_at": str(item.get("updated_at") or "").strip() or None,
            }
        )
    return {
        "policy_override": policy_override,
        "decisions": normalized_decisions,
    }


def get_session_record_resolution_state(session_id: int) -> dict[str, Any]:
    metadata_fields = get_session_metadata_map(session_id, {RECORD_RESOLUTION_STATE_FIELD})
    return parse_record_resolution_state(metadata_fields.get(RECORD_RESOLUTION_STATE_FIELD))


def save_session_record_resolution_state(session_id: int, state: dict[str, Any]) -> dict[str, Any]:
    normalized = parse_record_resolution_state(state)
    record = UserMetadata.query.filter_by(session_id=session_id, field_name=RECORD_RESOLUTION_STATE_FIELD).first()
    payload = json.dumps(normalized)
    if record:
        record.field_value = payload
    else:
        db.session.add(
            UserMetadata(
                session_id=session_id,
                field_name=RECORD_RESOLUTION_STATE_FIELD,
                field_value=payload,
            )
        )
    db.session.commit()
    return normalized


def parse_json(raw_value: Any, fallback: Any = None) -> Any:
    fallback_value = {} if fallback is None else fallback
    if raw_value is None:
        return fallback_value
    if isinstance(raw_value, (dict, list)):
        return raw_value
    try:
        return json.loads(raw_value)
    except (TypeError, json.JSONDecodeError):
        return fallback_value


def parse_timestamp(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return 0.0


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def version_sort_key(value: Any) -> tuple[int, ...]:
    text = str(value or "").strip()
    if not text:
        return tuple()
    parts: list[int] = []
    for raw_part in text.split("."):
        parts.append(int(raw_part) if raw_part.isdigit() else 0)
    return tuple(parts)


def normalized_version_rank(record: dict[str, Any]) -> int:
    raw_rank = str(record.get("version_rank") or "").strip()
    if raw_rank:
        try:
            return max(1, int(raw_rank))
        except ValueError:
            pass
    version = str(record.get("version") or "").strip()
    if version.isdigit():
        return max(1, int(version))
    version_parts = version_sort_key(version)
    if version_parts:
        return max(1, version_parts[-1])
    return 0


def record_version_sort_key(record: dict[str, Any]) -> tuple[int, tuple[int, ...], float, float, int]:
    return (
        normalized_version_rank(record),
        version_sort_key(record.get("version")),
        parse_timestamp(record.get("updated_at")),
        parse_timestamp(record.get("created_at")),
        parse_int(record.get("local_record_id")),
    )


def is_privileged_user(user) -> bool:
    return bool(user and getattr(user, "role", None) and getattr(user.role, "value", None) in {"admin", "moderator"})


def record_base(is_sandbox: bool) -> str:
    return "https://sandbox.zenodo.org" if is_sandbox else "https://zenodo.org"


def extract_dataset_key(*values: Any) -> str | None:
    for raw_value in values:
        text = str(raw_value or "").strip()
        if not text:
            continue
        for segment in [part for part in text.replace("\\", "/").split("/") if part]:
            if segment.lower().endswith(PREFERRED_DATASET_SUFFIX):
                return segment
    return None


def normalize_dataset_key(dataset_key: Any) -> str:
    return str(dataset_key or "").strip()


def normalize_dataset_key_lower(dataset_key: Any) -> str:
    return normalize_dataset_key(dataset_key).lower()


def normalize_environment(environment: Any, *, default: str = "all") -> str:
    text = str(environment or "").strip().lower()
    if text in VALID_ENVIRONMENTS:
        return text
    return default


def environment_to_is_sandbox(environment: str, *, fallback: bool = False) -> bool:
    normalized = normalize_environment(environment, default="all")
    if normalized == "sandbox":
        return True
    if normalized == "production":
        return False
    return bool(fallback)


def record_matches_environment(record: dict[str, Any], environment: str) -> bool:
    normalized = normalize_environment(environment, default="all")
    if normalized == "all":
        return True
    is_sandbox = bool(record.get("is_sandbox"))
    return is_sandbox if normalized == "sandbox" else not is_sandbox


def filter_records_by_environment(records: list[dict[str, Any]], environment: str) -> list[dict[str, Any]]:
    normalized = normalize_environment(environment, default="all")
    if normalized == "all":
        return records
    return [record for record in records if record_matches_environment(record, normalized)]


def normalize_source_path(path: Any, dataset_key: str | None = None) -> str:
    text = str(path or "").strip()
    if not text:
        return ""
    normalized = os.path.normpath(text).replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    lookup_key = normalize_dataset_key_lower(dataset_key)
    if not lookup_key:
        inferred = extract_dataset_key(text)
        lookup_key = normalize_dataset_key_lower(inferred)
    if lookup_key:
        for index, part in enumerate(parts):
            if part.lower() == lookup_key:
                return "/".join(parts[index:])
    return normalized


def normalize_filename(value: Any) -> str:
    return os.path.basename(str(value or "").strip()).lower()


def normalize_record_status(raw_status: Any, metadata_payload: dict[str, Any]) -> str:
    status = str(raw_status or "").strip().lower()
    if status in {"draft", "published", "prepared", "preparation_failed", "discarded"}:
        return status
    if metadata_payload.get("submitted") is True:
        return "published"
    if metadata_payload.get("links"):
        return "draft"
    return "unknown"


def resolve_existing_hdpc_path(raw_path: str | None) -> str | None:
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


def table_exists(cursor: sqlite3.Cursor, table_name: str) -> bool:
    row = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def table_columns(cursor: sqlite3.Cursor, table_name: str) -> set[str]:
    if not table_exists(cursor, table_name):
        return set()
    rows = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in rows}


def get_session_metadata_map(session_id: int, field_names: set[str] | None = None) -> dict[str, str]:
    query = UserMetadata.query.filter_by(session_id=session_id)
    if field_names:
        query = query.filter(UserMetadata.field_name.in_(field_names))
    return {row.field_name: row.field_value for row in query.all()}


def get_session_dataset_context(session_row: DBSession) -> dict[str, Any]:
    metadata_fields = get_session_metadata_map(session_row.id, {"msf_profile", "zenodo_metadata_draft"})
    msf_profile = parse_json(metadata_fields.get("msf_profile"), {})
    draft_metadata = parse_json(metadata_fields.get("zenodo_metadata_draft"), {})
    msf_path = str(
        (msf_profile or {}).get("source_file_path")
        or (msf_profile or {}).get("file_path")
        or (draft_metadata or {}).get("msf_path")
        or ""
    ).strip()
    directory_root = str((msf_profile or {}).get("directory_root") or "").strip()
    if not directory_root or not os.path.isdir(directory_root):
        candidate_roots = []
        if getattr(session_row, "session_dir", None):
            candidate_roots.append(os.path.join(str(session_row.session_dir), "uploads"))
        if getattr(session_row, "hdpc_path", None):
            candidate_roots.append(os.path.join(os.path.dirname(str(session_row.hdpc_path)), "uploads"))
        directory_root = next((path for path in candidate_roots if path and os.path.isdir(path)), "")
    dataset_key = extract_dataset_key(msf_path, directory_root)
    recursive = (msf_profile or {}).get("directory_recursive")
    return {
        "msf_path": msf_path or None,
        "directory_root": directory_root or None,
        "dataset_key": dataset_key or None,
        "directory_recursive": False if recursive is False else True,
        "prepared_candidate_files": (
            (msf_profile or {}).get("prepared_candidate_files")
            if isinstance((msf_profile or {}).get("prepared_candidate_files"), list)
            else []
        ),
    }


def infer_session_dataset_key(session_row: DBSession) -> str:
    return f"session_{int(getattr(session_row, 'id', 0) or 0)}_dataset"


def get_all_accessible_sessions(user_id: int | None = None, *, include_all_sessions: bool = False) -> list[DBSession]:
    if include_all_sessions:
        return DBSession.query.filter(DBSession.hdpc_path.isnot(None)).order_by(DBSession.created_at.desc()).all()

    if user_id is None:
        return []

    user = db.session.get(User, int(user_id))
    if not user:
        return []

    return [session_row for session_row in get_accessible_sessions(user, scope="all") if session_row.hdpc_path]


def is_three_d_candidate(path: str) -> bool:
    extension = os.path.splitext(path or "")[1].lower()
    return extension in THREE_D_FILE_EXTENSIONS


def scan_candidate_files_for_session(session_row: DBSession) -> list[CandidateFile]:
    context = get_session_dataset_context(session_row)
    directory_root = context.get("directory_root")
    dataset_key = normalize_dataset_key(context.get("dataset_key"))
    fallback_dataset_key = infer_session_dataset_key(session_row)
    is_recursive = bool(context.get("directory_recursive", True))
    prepared_candidate_files = context.get("prepared_candidate_files") or []
    default_is_sandbox = str(getattr(session_row, "default_zenodo_environment", "sandbox") or "sandbox").strip().lower() != "production"
    shared_candidate_metadata = _shared_candidate_metadata_for_session(session_row)
    batch_candidate_metadata = _batch_candidate_metadata_by_filename(session_row)
    if prepared_candidate_files:
        candidates: list[CandidateFile] = []
        seen: set[str] = set()
        for item in prepared_candidate_files:
            if not isinstance(item, dict):
                continue
            source_file_path = str(item.get("source_file_path") or "").strip()
            if not source_file_path:
                continue
            candidate_dataset_key = normalize_dataset_key(
                item.get("dataset_key") or dataset_key or extract_dataset_key(source_file_path, directory_root) or fallback_dataset_key
            )
            if not candidate_dataset_key:
                continue
            normalized_source_file_path = normalize_source_path(source_file_path, candidate_dataset_key)
            dedupe_key = f"{normalize_dataset_key_lower(candidate_dataset_key)}::{normalized_source_file_path.lower()}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            candidate_filename = str(item.get("source_file_name") or os.path.basename(source_file_path))
            candidate_metadata = merge_candidate_metadata(
                shared_candidate_metadata,
                batch_candidate_metadata.get(candidate_filename.lower()) or {},
                normalize_candidate_metadata(item.get("metadata")),
            )
            candidates.append(
                CandidateFile(
                    source_file_path=source_file_path,
                    source_file_name=candidate_filename,
                    dataset_key=candidate_dataset_key,
                    normalized_source_file_path=normalized_source_file_path,
                    is_sandbox=bool(item.get("is_sandbox", default_is_sandbox)),
                    concept_rec_id=str(item.get("concept_rec_id") or "").strip(),
                    sha256_hash=str(item.get("sha256_hash") or "").strip(),
                    size_bytes=parse_int(item.get("size_bytes")) if item.get("size_bytes") not in (None, "") else None,
                    mime_type=str(item.get("mime_type") or "").strip(),
                    file_type=str(item.get("file_type") or "").strip(),
                    file_purpose=str(item.get("file_purpose") or "").strip(),
                    pipeline_source=str(item.get("pipeline_source") or "").strip(),
                    step_source=str(item.get("step_source") or "").strip(),
                    session_id=session_row.id,
                    metadata=candidate_metadata,
                )
            )
        if candidates:
            return candidates

    if not directory_root or not os.path.isdir(directory_root):
        return []
    candidates: list[CandidateFile] = []
    seen: set[str] = set()
    walker = os.walk(directory_root)
    for root, dirs, files in walker:
        if not is_recursive:
            dirs[:] = []
        dirs[:] = [name for name in dirs if name and not name.startswith(".")]
        for filename in sorted(files):
            if filename.startswith("."):
                continue
            absolute_path = os.path.join(root, filename)
            if not os.path.isfile(absolute_path) or not is_three_d_candidate(absolute_path):
                continue
            inferred_dataset_key = normalize_dataset_key(
                extract_dataset_key(dataset_key, absolute_path, directory_root) or dataset_key or fallback_dataset_key
            )
            if not inferred_dataset_key:
                continue
            normalized_source_file_path = normalize_source_path(absolute_path, inferred_dataset_key)
            dedupe_key = f"{normalize_dataset_key_lower(inferred_dataset_key)}::{normalized_source_file_path.lower()}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            candidates.append(
                CandidateFile(
                    source_file_path=absolute_path,
                    source_file_name=os.path.basename(absolute_path),
                    dataset_key=inferred_dataset_key,
                    normalized_source_file_path=normalized_source_file_path,
                    is_sandbox=default_is_sandbox,
                    sha256_hash=_file_sha256(absolute_path),
                    size_bytes=os.path.getsize(absolute_path),
                    mime_type="",
                    file_type="source",
                    session_id=session_row.id,
                    metadata=shared_candidate_metadata,
                )
            )
    return candidates


def extract_doi(row: sqlite3.Row | dict[str, Any], metadata: dict[str, Any]) -> str:
    candidates = [
        (row.get("zenodo_doi") if isinstance(row, dict) else row["zenodo_doi"]),
        metadata.get("doi"),
        (metadata.get("metadata") or {}).get("doi") if isinstance(metadata.get("metadata"), dict) else None,
        ((metadata.get("metadata") or {}).get("prereserve_doi") or {}).get("doi")
        if isinstance((metadata.get("metadata") or {}).get("prereserve_doi"), dict)
        else None,
        (metadata.get("prereserve_doi") or {}).get("doi") if isinstance(metadata.get("prereserve_doi"), dict) else None,
    ]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


def extract_record_link(record_status: str, zenodo_record_id: Any, metadata: dict[str, Any], is_sandbox: bool) -> str:
    links = metadata.get("links") if isinstance(metadata.get("links"), dict) else {}
    for key in ("html", "latest_draft_html", "latest_draft", "self"):
        value = str(links.get(key) or "").strip()
        if value:
            if key == "html" and record_status == "published":
                return value.replace("/deposit/", "/records/")
            return value
    record_id = str(zenodo_record_id or metadata.get("id") or "").strip()
    if not record_id:
        return ""
    if record_status == "published":
        return f"{record_base(is_sandbox)}/records/{record_id}"
    return f"{record_base(is_sandbox)}/deposit/{record_id}"


def extract_file_objects(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    files = metadata.get("files")
    if not isinstance(files, list):
        return []
    return [item for item in files if isinstance(item, dict)]


def _model_filename(file_obj: dict[str, Any] | None) -> str:
    if not isinstance(file_obj, dict):
        return ""
    return str(file_obj.get("filename") or file_obj.get("key") or file_obj.get("name") or file_obj.get("id") or "").strip()


def _model_extension(filename: Any) -> str:
    return os.path.splitext(os.path.basename(str(filename or "").strip()))[1].lower()


def _model_format(filename: Any) -> str:
    extension = _model_extension(filename)
    return extension.lstrip(".")


def choose_model_file(
    source_file_name: str | None,
    metadata_files: list[dict[str, Any]],
    *,
    allowed_extensions: set[str] | None = None,
) -> dict[str, Any] | None:
    model_files = []
    expected = str(source_file_name or "").strip().lower()
    allowed = allowed_extensions or THREE_D_FILE_EXTENSIONS
    for item in metadata_files:
        filename = _model_filename(item)
        if _model_extension(filename) not in allowed:
            continue
        model_files.append(item)
        if expected and filename.lower() == expected:
            return item
    return model_files[0] if model_files else None


def choose_glb_file(source_file_name: str | None, metadata_files: list[dict[str, Any]]) -> dict[str, Any] | None:
    return choose_model_file(source_file_name, metadata_files, allowed_extensions={".glb"})


class ZenodoPublicCache:
    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.cache: dict[tuple[bool, str], dict[str, Any] | None] = {}

    def fetch(self, is_sandbox: bool, record_id: Any) -> dict[str, Any] | None:
        record_key = str(record_id or "").strip()
        if not record_key:
            return None
        cache_key = (is_sandbox, record_key)
        if cache_key in self.cache:
            return self.cache[cache_key]
        url = f"{record_base(is_sandbox)}/api/records/{record_key}"
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
            self.cache[cache_key] = payload if isinstance(payload, dict) else None
        except requests.RequestException:
            self.cache[cache_key] = None
        return self.cache[cache_key]


def build_zenodo_direct_file_url(is_sandbox: bool, record_id: Any, filename: Any) -> str:
    record_key = str(record_id or "").strip()
    filename_text = str(filename or "").strip()
    if not record_key or not filename_text:
        return ""
    encoded_filename = quote(filename_text, safe="")
    return f"{record_base(is_sandbox)}/api/records/{quote(record_key, safe='')}/files/{encoded_filename}/content"


def is_valid_zenodo_direct_file_url(url: Any) -> bool:
    text = str(url or "").strip()
    if not text:
        return False
    parsed = urlparse(text)
    if parsed.scheme != "https" or parsed.netloc not in {"zenodo.org", "sandbox.zenodo.org"}:
        return False
    return bool(re.match(r"^/api/records/[^/]+/files/.+/content/?$", parsed.path))


def _direct_file_url_from_links(file_obj: dict[str, Any]) -> str:
    links = file_obj.get("links") if isinstance(file_obj.get("links"), dict) else {}
    for key in ("content", "download", "self"):
        url = str(links.get(key) or "").strip()
        if not url:
            continue
        if key == "self" and not url.endswith("/content"):
            url = url.rstrip("/") + "/content"
        if is_valid_zenodo_direct_file_url(url):
            return url
    return ""


def resolve_model_direct_link(record: dict[str, Any], public_cache: ZenodoPublicCache | None = None) -> str:
    metadata = record.get("record_metadata") or {}
    source_file_name = record.get("source_file_name")
    zenodo_record_id = record.get("zenodo_record_id")
    is_sandbox = bool(record.get("is_sandbox"))
    record_status = str(record.get("record_status") or "").lower()

    metadata_files = extract_file_objects(metadata)
    model_file = choose_model_file(source_file_name, metadata_files, allowed_extensions=INLINE_MODEL_FILE_EXTENSIONS)
    if model_file:
        filename = _model_filename(model_file) or str(source_file_name or "").strip()
        if record_status == "published" and zenodo_record_id and filename:
            return build_zenodo_direct_file_url(is_sandbox, zenodo_record_id, filename)
        linked_url = _direct_file_url_from_links(model_file)
        if linked_url:
            return linked_url

    if public_cache:
        public_payload = public_cache.fetch(is_sandbox=is_sandbox, record_id=zenodo_record_id)
        if isinstance(public_payload, dict):
            public_model = choose_model_file(source_file_name, extract_file_objects(public_payload), allowed_extensions=INLINE_MODEL_FILE_EXTENSIONS)
            if public_model:
                filename = _model_filename(public_model) or str(source_file_name or "").strip()
                if zenodo_record_id and filename:
                    return build_zenodo_direct_file_url(is_sandbox, zenodo_record_id, filename)

    if record_status == "published" and zenodo_record_id and _model_extension(source_file_name) in INLINE_MODEL_FILE_EXTENSIONS:
        return build_zenodo_direct_file_url(is_sandbox, zenodo_record_id, source_file_name)
    return ""


def resolve_glb_direct_link(record: dict[str, Any], public_cache: ZenodoPublicCache | None = None) -> str:
    return resolve_model_direct_link(record, public_cache)


def _record_model_candidates(record: dict[str, Any], metadata_files: list[dict[str, Any]]) -> list[str]:
    candidates = [
        record.get("source_file_name"),
        record.get("source_file_path"),
    ]
    for file_item in record.get("files") or record.get("record_files") or []:
        if not isinstance(file_item, dict):
            continue
        candidates.extend(
            [
                file_item.get("filename"),
                file_item.get("absolute_path"),
                file_item.get("mapped_file_path"),
                file_item.get("file_path"),
            ]
        )
    candidates.extend(_model_filename(item) for item in metadata_files)
    return [str(item).strip() for item in candidates if str(item or "").strip()]


def _record_has_3d_mime(record: dict[str, Any]) -> bool:
    mime_candidates = [record.get("source_mime_type"), record.get("mime_type")]
    for file_item in record.get("files") or record.get("record_files") or []:
        if isinstance(file_item, dict):
            mime_candidates.extend([file_item.get("mime_type"), file_item.get("source_mime_type")])
    for mime_type in mime_candidates:
        normalized = str(mime_type or "").strip().lower()
        if normalized.startswith("model/") or normalized == "application/octet-stream":
            return True
    return False


def build_model_preview(record: dict[str, Any], public_cache: ZenodoPublicCache | None = None) -> dict[str, Any]:
    metadata = record.get("record_metadata") if isinstance(record.get("record_metadata"), dict) else {}
    metadata_files = extract_file_objects(metadata)
    model_candidates = _record_model_candidates(record, metadata_files)
    candidate_filename = next((item for item in model_candidates if _model_extension(item) in THREE_D_FILE_EXTENSIONS), "")
    metadata_model = (
        choose_model_file(record.get("source_file_name"), metadata_files, allowed_extensions=INLINE_MODEL_FILE_EXTENSIONS)
        or choose_model_file(record.get("source_file_name"), metadata_files)
    )
    metadata_filename = _model_filename(metadata_model)
    filename = metadata_filename or os.path.basename(candidate_filename)
    extension = _model_extension(filename or candidate_filename)
    is_3d_record = bool(extension in THREE_D_FILE_EXTENSIONS or _record_has_3d_mime(record))

    preview = {
        "is_3d_record": is_3d_record,
        "can_inline_preview": False,
        "url": "",
        "filename": filename or os.path.basename(candidate_filename) or None,
        "format": _model_format(filename or candidate_filename) or None,
        "source": None,
        "reason": None,
    }
    if not is_3d_record:
        preview["reason"] = "not_3d_record"
        return preview
    if not filename:
        preview["reason"] = "missing_model_file"
        return preview
    if extension not in INLINE_MODEL_FILE_EXTENSIONS:
        preview["reason"] = "inline_preview_unsupported_format"
        return preview
    if str(record.get("record_status") or "").strip().lower() != "published":
        preview["reason"] = "record_not_published"
        return preview
    if not str(record.get("zenodo_record_id") or "").strip():
        preview["reason"] = "missing_zenodo_record_id"
        return preview

    url = resolve_model_direct_link(record, public_cache)
    if not is_valid_zenodo_direct_file_url(url):
        preview["reason"] = "missing_valid_zenodo_direct_url"
        return preview

    preview.update(
        {
            "can_inline_preview": True,
            "url": url,
            "source": "zenodo_direct_file",
            "reason": None,
        }
    )
    return preview


def clone_cached_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cloned: list[dict[str, Any]] = []
    for record in records:
        copied = dict(record)
        copied["record_files"] = [dict(item) for item in (record.get("record_files") or [])]
        cloned.append(copied)
    return cloned


def clone_cached_inventory(inventory: dict[str, Any]) -> dict[str, Any]:
    return {
        "visible_records": clone_cached_records(inventory.get("visible_records") or []),
        "hidden_records": clone_cached_records(inventory.get("hidden_records") or []),
        "summary": dict(inventory.get("summary") or {}),
        "source_state": str(inventory.get("source_state") or "ok"),
    }


def session_record_cache_key(
    session_row: DBSession,
    resolved_hdpc_path: str,
    session_context: dict[str, Any],
) -> tuple[Any, ...]:
    revisions = []
    # Committed WAL writes can leave the main database unchanged until checkpointing.
    for suffix in ('', '-wal'):
        try:
            stat = os.stat(resolved_hdpc_path + suffix)
            revisions.append((stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino))
        except OSError:
            revisions.append(None)
    context_signature = json.dumps(session_context, sort_keys=True, default=str)
    return (
        session_row.id,
        resolved_hdpc_path,
        tuple(revisions),
        context_signature,
        getattr(session_row, 'status', None),
        getattr(session_row, 'user_id', None),
        getattr(session_row, 'created_at', None),
    )


def get_cached_session_record_inventory(cache_key: tuple[Any, ...]) -> dict[str, Any] | None:
    cached = _SESSION_RECORD_CACHE.get(cache_key)
    if cached is None:
        return None
    _SESSION_RECORD_CACHE.move_to_end(cache_key)
    return clone_cached_inventory(cached)


def store_cached_session_record_inventory(cache_key: tuple[Any, ...], inventory: dict[str, Any]) -> None:
    _SESSION_RECORD_CACHE[cache_key] = clone_cached_inventory(inventory)
    _SESSION_RECORD_CACHE.move_to_end(cache_key)
    while len(_SESSION_RECORD_CACHE) > SESSION_RECORD_CACHE_LIMIT:
        _SESSION_RECORD_CACHE.popitem(last=False)


def get_cached_session_records(cache_key: tuple[Any, ...]) -> list[dict[str, Any]] | None:
    cached = get_cached_session_record_inventory(cache_key)
    if cached is None:
        return None
    return cached.get("visible_records") or []


def store_cached_session_records(cache_key: tuple[Any, ...], records: list[dict[str, Any]]) -> None:
    store_cached_session_record_inventory(
        cache_key,
        {
            "visible_records": records,
            "hidden_records": [],
            "summary": {},
            "source_state": "ok",
        },
    )


def read_session_record_inventory(session_row: DBSession) -> dict[str, Any]:
    resolved_hdpc_path = resolve_existing_hdpc_path(session_row.hdpc_path)
    if not resolved_hdpc_path:
        return {"visible_records": [], "hidden_records": [], "summary": {}, "source_state": "hdpc_unavailable"}

    session_context = get_session_dataset_context(session_row)
    cache_key = session_record_cache_key(session_row, resolved_hdpc_path, session_context)
    cached_inventory = get_cached_session_record_inventory(cache_key)
    if cached_inventory is not None:
        return cached_inventory

    session_dataset_key = normalize_dataset_key(session_context.get("dataset_key"))
    conn = sqlite3.connect(resolved_hdpc_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        if not table_exists(cursor, "zenodo_records"):
            return {"visible_records": [], "hidden_records": [], "summary": {}, "source_state": "zenodo_table_missing"}

        source_files_by_id: dict[int, dict[str, Any]] = {}
        source_columns = table_columns(cursor, "source_files")
        if source_columns and "file_id" in source_columns:
            for row in cursor.execute("SELECT * FROM source_files").fetchall():
                source_files_by_id[int(row["file_id"])] = dict(row)

        files_by_record: dict[int, list[dict[str, Any]]] = defaultdict(list)
        rfm_columns = table_columns(cursor, "record_files_map")
        if rfm_columns and {"record_id", "file_id"}.issubset(rfm_columns):
            source_field_map = {
                "filename": "sf.filename",
                "absolute_path": "sf.absolute_path",
                "relative_path": "sf.relative_path",
                "file_type": "sf.file_type",
                "source_status": "sf.status",
                "size_bytes": "sf.size_bytes",
                "mime_type": "sf.mime_type",
                "pipeline_source": "sf.pipeline_source",
                "step_source": "sf.step_source",
                "added_timestamp": "sf.added_timestamp",
                "sha256_hash": "sf.sha256_hash",
            }
            select_fields = [
                "rfm.record_id AS record_id",
                "rfm.file_id AS file_id",
                "rfm.file_purpose AS file_purpose",
                "rfm.upload_status AS upload_status",
                "rfm.upload_timestamp AS upload_timestamp",
                "rfm.file_path AS mapped_file_path",
            ]
            for alias, expression in source_field_map.items():
                column_name = expression.split(".", 1)[1]
                if column_name in source_columns:
                    select_fields.append(f"{expression} AS {alias}")
                else:
                    select_fields.append(f"NULL AS {alias}")
            joined_rows = cursor.execute(
                f"""
                SELECT
                    {", ".join(select_fields)}
                FROM record_files_map rfm
                LEFT JOIN source_files sf ON sf.file_id = rfm.file_id
                """
            ).fetchall()
            for row in joined_rows:
                files_by_record[int(row["record_id"])].append(dict(row))

        records: list[dict[str, Any]] = []
        for row in cursor.execute("SELECT * FROM zenodo_records ORDER BY record_id ASC").fetchall():
            row_dict = dict(row)
            record_origin = normalize_hdpc_record_origin(row_dict.get("record_origin"))
            if not is_canonical_hdpc_record({"record_origin": record_origin}):
                continue
            source_file = source_files_by_id.get(int(row_dict.get("source_file_id") or 0)) or {}
            source_file_path = str(source_file.get("absolute_path") or "").strip()
            source_file_name = str(source_file.get("filename") or "").strip()
            metadata_payload = parse_json(row_dict.get("record_metadata_json"), {})
            metadata_payload = metadata_payload if isinstance(metadata_payload, dict) else {}
            status = normalize_record_status(row_dict.get("record_status"), metadata_payload)
            dataset_key = normalize_dataset_key(
                extract_dataset_key(
                    session_dataset_key,
                    source_file_path,
                    source_file_name,
                    session_context.get("msf_path"),
                    session_context.get("directory_root"),
                )
            )
            dataset_key = dataset_key or infer_session_dataset_key(session_row)
            normalized_source_file_path = normalize_source_path(source_file_path, dataset_key)
            zenodo_record_id = row_dict.get("zenodo_record_id") or metadata_payload.get("id")
            is_sandbox = bool(row_dict.get("is_sandbox")) if row_dict.get("is_sandbox") is not None else False
            mapped_files = files_by_record.get(int(row_dict["record_id"]), [])
            uploaded_file_count = sum(1 for item in mapped_files if str(item.get("upload_status") or "").lower() == "uploaded")
            record = {
                "session_id": session_row.id,
                "session_user_id": session_row.user_id,
                "session_status": session_row.status,
                "session_created_at": session_row.created_at.isoformat() if session_row.created_at else None,
                "local_record_id": int(row_dict["record_id"]),
                "source_file_id": row_dict.get("source_file_id"),
                "source_file_name": source_file_name or None,
                "source_file_path": source_file_path or None,
                "source_relative_path": str(source_file.get("relative_path") or "").strip() or None,
                "source_file_type": str(source_file.get("file_type") or "").strip() or None,
                "source_status": str(source_file.get("status") or "").strip() or None,
                "source_size_bytes": source_file.get("size_bytes"),
                "source_mime_type": str(source_file.get("mime_type") or "").strip() or None,
                "source_pipeline_source": str(source_file.get("pipeline_source") or "").strip() or None,
                "source_step_source": str(source_file.get("step_source") or "").strip() or None,
                "source_added_timestamp": source_file.get("added_timestamp"),
                "source_sha256_hash": str(source_file.get("sha256_hash") or "").strip(),
                "normalized_source_file_path": normalized_source_file_path or None,
                "dataset_key": dataset_key or None,
                "dataset_key_lower": normalize_dataset_key_lower(dataset_key),
                "record_status": status,
                "zenodo_record_id": zenodo_record_id,
                "concept_rec_id": str(row_dict.get("concept_rec_id") or metadata_payload.get("conceptrecid") or "").strip(),
                "version": row_dict.get("version"),
                "version_rank": row_dict.get("version_rank"),
                "zenodo_doi": extract_doi(row_dict, metadata_payload),
                "record_link": extract_record_link(status, zenodo_record_id, metadata_payload, is_sandbox),
                "is_sandbox": is_sandbox,
                "created_at": row_dict.get("created_timestamp"),
                "updated_at": row_dict.get("last_updated_timestamp"),
                "last_api_error": row_dict.get("last_api_error"),
                "record_title": row_dict.get("record_title"),
                "record_metadata": metadata_payload,
                "record_files": mapped_files,
                "record_file_count": len(mapped_files),
                "uploaded_file_count": uploaded_file_count,
                "record_origin": record_origin,
                "canonical_submit_flow": is_canonical_hdpc_record({"record_origin": record_origin}),
            }
            records.append(record)
        inventory = classify_hdpc_record_inventory(records)
        inventory["source_state"] = "ok"
        store_cached_session_record_inventory(cache_key, inventory)
        return clone_cached_inventory(inventory)
    finally:
        conn.close()


def read_session_records(session_row: DBSession) -> list[dict[str, Any]]:
    return read_session_record_inventory(session_row).get("visible_records", [])


def collect_dataset_records(user_id: int | None = None, *, include_all_sessions: bool = False) -> tuple[list[dict[str, Any]], list[DBSession]]:
    sessions = get_all_accessible_sessions(user_id, include_all_sessions=include_all_sessions)
    all_records: list[dict[str, Any]] = []
    for session_row in sessions:
        all_records.extend(read_session_records(session_row))
    return all_records, sessions


class RecordInventorySnapshot:
    """One request's inventory, indexed without weakening mutation-time checks."""

    def __init__(self, records=None):
        self.records = collect_dataset_records(include_all_sessions=True)[0] if records is None else records
        self.by_dataset = {}
        self.by_session = {}
        for record in self.records:
            key = (record.get('dataset_key_lower'), bool(record.get('is_sandbox')))
            self.by_dataset.setdefault(key, []).append(record)
            self.by_session.setdefault(int(record.get('session_id') or 0), {})[int(record.get('local_record_id') or 0)] = record

    def matching(self, candidate):
        return self.by_dataset.get((normalize_dataset_key_lower(candidate.dataset_key), bool(candidate.is_sandbox)), [])


def collect_records_for_dataset(
    dataset_key: str,
    user_id: int | None = None,
    *,
    include_all_sessions: bool = False,
    environment: str = "all",
) -> tuple[list[dict[str, Any]], list[DBSession]]:
    normalized_dataset_key = normalize_dataset_key_lower(dataset_key)
    all_records, sessions = collect_dataset_records(user_id, include_all_sessions=include_all_sessions)
    filtered = [
        record
        for record in all_records
        if record.get("dataset_key_lower") == normalized_dataset_key and record_matches_environment(record, environment)
    ]
    return filtered, sessions


def get_session_dataset_keys(session_row: DBSession, records: list[dict[str, Any]]) -> set[str]:
    """Retain dataset identity before a session has prepared any records."""
    context = get_session_dataset_context(session_row)
    keys = {
        normalize_dataset_key(record.get("dataset_key"))
        for record in records
        if normalize_dataset_key(record.get("dataset_key"))
    }
    context_key = normalize_dataset_key(context.get("dataset_key"))
    if context_key:
        keys.add(context_key)
    for candidate in context.get("prepared_candidate_files") or []:
        if not isinstance(candidate, dict):
            continue
        candidate_key = normalize_dataset_key(
            candidate.get("dataset_key") or extract_dataset_key(candidate.get("source_file_path"))
        )
        if candidate_key:
            keys.add(candidate_key)
    return keys or {infer_session_dataset_key(session_row)}


def collect_dataset_workspaces(
    user_id: int | None = None,
    *,
    include_all_sessions: bool = False,
) -> dict[str, dict[str, Any]]:
    """Build dataset existence and environment information within the caller's session scope."""
    records, sessions = collect_dataset_records(user_id, include_all_sessions=include_all_sessions)
    records_by_session: dict[int, list[dict[str, Any]]] = defaultdict(list)
    workspaces: dict[str, dict[str, Any]] = {}
    for record in records:
        records_by_session[int(record["session_id"])].append(record)
    for session_row in sessions:
        session_records = records_by_session.get(session_row.id, [])
        seen_dataset_keys: set[str] = set()
        for dataset_key in sorted(get_session_dataset_keys(session_row, session_records)):
            key = normalize_dataset_key_lower(dataset_key)
            if key in seen_dataset_keys:
                continue
            seen_dataset_keys.add(key)
            workspace = workspaces.setdefault(
                key,
                {
                    "dataset_key": dataset_key,
                    "records": [],
                    "sessions": [],
                    "session_environments": {},
                    "available_environments": set(),
                },
            )
            dataset_records = [record for record in session_records if record.get("dataset_key_lower") == key]
            environments = {
                "sandbox" if bool(record.get("is_sandbox")) else "production"
                for record in dataset_records
            }
            if not environments:
                default_environment = getattr(session_row, "default_zenodo_environment", None)
                environments.add("production" if default_environment == "production" else "sandbox")
            workspace["records"].extend(dataset_records)
            workspace["sessions"].append(session_row)
            workspace["session_environments"][session_row.id] = environments
            workspace["available_environments"].update(environments)
    return workspaces


def scope_dataset_workspace(workspace: dict[str, Any], environment: str) -> dict[str, Any]:
    """An empty environment selection does not make an accessible dataset nonexistent."""
    normalized_environment = normalize_environment(environment, default="production")
    records = filter_records_by_environment(workspace["records"], normalized_environment)
    sessions = [
        session_row for session_row in workspace["sessions"]
        if normalized_environment == "all"
        or normalized_environment in workspace["session_environments"][session_row.id]
    ]
    return {
        "dataset_key": workspace["dataset_key"],
        "records": records,
        "sessions": sessions,
        "available_environments": sorted(workspace["available_environments"]),
        "empty_reason": None if records else (
            "no_records_in_environment"
            if normalized_environment != "all" and normalized_environment not in workspace["available_environments"]
            else "no_records"
        ),
    }


def choose_authoritative_session_id(records: list[dict[str, Any]]) -> int | None:
    by_session: dict[int, dict[str, Any]] = {}
    for record in records:
        session_id = int(record["session_id"])
        summary = by_session.setdefault(
            session_id,
            {
                "published_rows": 0,
                "published_paths": set(),
                "last_ts": 0.0,
            },
        )
        if record.get("record_status") == "published":
            summary["published_rows"] += 1
            normalized_path = str(record.get("normalized_source_file_path") or "").strip().lower()
            if normalized_path:
                summary["published_paths"].add(normalized_path)
        summary["last_ts"] = max(summary["last_ts"], parse_timestamp(record.get("created_at")))
    if not by_session:
        return None
    return max(
        by_session,
        key=lambda session_id: (
            len(by_session[session_id]["published_paths"]),
            by_session[session_id]["published_rows"],
            by_session[session_id]["last_ts"],
            session_id,
        ),
    )


def choose_latest_record(records: list[dict[str, Any]]) -> dict[str, Any]:
    return max(records, key=record_version_sort_key)


def classify_draft_kind(record: dict[str, Any], records_for_path: list[dict[str, Any]]) -> str:
    status = str(record.get("record_status") or "").lower()
    if status == "prepared":
        return "prepared_only"
    if status != "draft":
        return "not_draft"
    if record.get("concept_rec_id") and any(
        other.get("record_status") == "published"
        and bool(other.get("is_sandbox")) == bool(record.get("is_sandbox"))
        and other.get("concept_rec_id")
        and other.get("concept_rec_id") == record.get("concept_rec_id")
        for other in records_for_path
    ):
        return "repair_version_draft"
    if int(record.get("record_file_count") or 0) > 0 and int(record.get("uploaded_file_count") or 0) >= int(record.get("record_file_count") or 0):
        return "complete_draft"
    return "partial_draft"


def build_dataset_summary(
    dataset_key: str,
    records: list[dict[str, Any]],
    *,
    sessions: list[DBSession] | None = None,
) -> dict[str, Any]:
    authoritative_session_id = choose_authoritative_session_id(records)
    by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    environment_breakdown: dict[str, dict[str, int]] = {
        "sandbox": {"record_count": 0, "source_path_count": 0, "published_source_path_count": 0},
        "production": {"record_count": 0, "source_path_count": 0, "published_source_path_count": 0},
    }
    for record in records:
        normalized_path = str(record.get("normalized_source_file_path") or "").strip().lower()
        if normalized_path:
            by_path[normalized_path].append(record)
            environment_key = "sandbox" if bool(record.get("is_sandbox")) else "production"
            environment_breakdown[environment_key]["record_count"] += 1

    for records_for_path in by_path.values():
        environments_for_path = {("sandbox" if bool(record.get("is_sandbox")) else "production") for record in records_for_path}
        published_environments = {
            ("sandbox" if bool(record.get("is_sandbox")) else "production")
            for record in records_for_path
            if record.get("record_status") == "published"
        }
        for environment_key in environments_for_path:
            environment_breakdown[environment_key]["source_path_count"] += 1
        for environment_key in published_environments:
            environment_breakdown[environment_key]["published_source_path_count"] += 1

    primary_records: list[dict[str, Any]] = []
    if authoritative_session_id is not None:
        authoritative_published = [
            record
            for record in records
            if record.get("session_id") == authoritative_session_id and record.get("record_status") == "published"
        ]
        authoritative_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in authoritative_published:
            authoritative_by_path[str(record.get("normalized_source_file_path") or "").strip().lower()].append(record)
        for normalized_path in sorted(authoritative_by_path):
            chosen = choose_latest_record(authoritative_by_path[normalized_path])
            enriched = dict(chosen)
            enriched["glb_direct_link"] = resolve_glb_direct_link(enriched, None)
            primary_records.append(enriched)

    duplicate_published_paths = sum(
        1
        for records_for_path in by_path.values()
        if any(
            sum(1 for record in records_for_path if record.get("record_status") == "published" and bool(record.get("is_sandbox")) == is_sandbox) > 1
            for is_sandbox in (False, True)
        )
    )
    unpublished_paths = sum(
        1
        for records_for_path in by_path.values()
        if not any(record.get("record_status") == "published" for record in records_for_path)
    )
    draft_kind_counter = Counter()
    for records_for_path in by_path.values():
        for record in records_for_path:
            draft_kind = classify_draft_kind(record, records_for_path)
            if draft_kind != "not_draft":
                draft_kind_counter[draft_kind] += 1

    session_summaries: dict[int, dict[str, Any]] = {}
    for session_row in sessions or []:
        session_summaries[session_row.id] = {
            "session_id": session_row.id,
            "published_records": 0,
            "published_source_paths": set(),
            "draft_records": 0,
            "prepared_records": 0,
            "total_records": 0,
            "latest_activity": session_row.created_at.isoformat() if session_row.created_at else None,
        }
    for record in records:
        summary = session_summaries.setdefault(
            int(record["session_id"]),
            {
                "session_id": int(record["session_id"]),
                "published_records": 0,
                "published_source_paths": set(),
                "draft_records": 0,
                "prepared_records": 0,
                "total_records": 0,
                "latest_activity": None,
            },
        )
        summary["total_records"] += 1
        if record.get("record_status") == "published":
            summary["published_records"] += 1
            normalized_path = str(record.get("normalized_source_file_path") or "").strip().lower()
            if normalized_path:
                summary["published_source_paths"].add(normalized_path)
        elif record.get("record_status") == "draft":
            summary["draft_records"] += 1
        elif record.get("record_status") == "prepared":
            summary["prepared_records"] += 1
        current_ts = record.get("updated_at") or record.get("created_at")
        if current_ts and (summary["latest_activity"] is None or str(current_ts) > str(summary["latest_activity"])):
            summary["latest_activity"] = current_ts

    return {
        "dataset_key": dataset_key,
        "authoritative_session_id": authoritative_session_id,
        "session_count": len(session_summaries),
        "record_count": len(records),
        "source_path_count": len(by_path),
        "published_source_path_count": sum(
            1 for records_for_path in by_path.values() if any(record.get("record_status") == "published" for record in records_for_path)
        ),
        "unpublished_source_path_count": unpublished_paths,
        "duplicate_published_source_path_count": duplicate_published_paths,
        "primary_record_count": len(primary_records),
        "primary_missing_doi_count": sum(1 for record in primary_records if not record.get("zenodo_doi")),
        "primary_missing_glb_link_count": sum(1 for record in primary_records if not record.get("glb_direct_link")),
        "draft_breakdown": dict(draft_kind_counter),
        "environment_breakdown": environment_breakdown,
        "sessions": sorted(
            [
                {
                    "session_id": item["session_id"],
                    "published_records": item["published_records"],
                    "published_source_path_count": len(item["published_source_paths"]),
                    "draft_records": item["draft_records"],
                    "prepared_records": item["prepared_records"],
                    "total_records": item["total_records"],
                    "latest_activity": item["latest_activity"],
                }
                for item in session_summaries.values()
            ],
            key=lambda item: (
                item["published_source_path_count"],
                item["published_records"],
                item["latest_activity"] or "",
            ),
            reverse=True,
        ),
    }


def classify_candidate(
    candidate: CandidateFile,
    records: list[dict[str, Any]],
    *,
    exclude_record: tuple[int, int] | None = None,
) -> dict[str, Any]:
    relevant_records = [
        record
        for record in records
        if record.get("dataset_key_lower") == normalize_dataset_key_lower(candidate.dataset_key)
        and bool(record.get("is_sandbox")) == bool(candidate.is_sandbox)
    ]
    same_path_records = []
    filename_matches = []
    hash_matches = []
    for record in relevant_records:
        record_ref = (int(record.get("session_id") or 0), int(record.get("local_record_id") or 0))
        if exclude_record and record_ref == exclude_record:
            continue
        record_path = str(record.get("normalized_source_file_path") or "").strip().lower()
        if record_path and record_path == candidate.normalized_source_file_path.lower():
            same_path_records.append(record)
            continue
        if candidate.source_file_name and normalize_filename(record.get("source_file_name")) == normalize_filename(candidate.source_file_name):
            filename_matches.append(record)
        if candidate.sha256_hash and str(record.get("source_sha256_hash") or "").strip() == candidate.sha256_hash:
            hash_matches.append(record)

    if same_path_records:
        matching_lineage = [
            record
            for record in same_path_records
            if candidate.concept_rec_id and record.get("concept_rec_id") == candidate.concept_rec_id
        ]
        conflicting_lineage = [
            record
            for record in same_path_records
            if not candidate.concept_rec_id or record.get("concept_rec_id") != candidate.concept_rec_id
        ]
        if conflicting_lineage:
            classification = "blocker"
            matched_records = conflicting_lineage + [record for record in matching_lineage if record not in conflicting_lineage]
            recommended_action = "Reuse the existing record lineage or resolve the duplicate source path before continuing."
        elif matching_lineage:
            classification = "allowed_versioning"
            matched_records = matching_lineage
            recommended_action = "Use the versioning path instead of creating a fresh record."
        else:
            classification = "blocker"
            matched_records = same_path_records
            recommended_action = "Reuse the existing record lineage or resolve the duplicate source path before continuing."
    elif hash_matches or filename_matches:
        classification = "warning"
        matched_records = hash_matches + [record for record in filename_matches if record not in hash_matches]
        recommended_action = "Review the matching records before continuing; the source path differs but the identity signals overlap."
    else:
        classification = "clean"
        matched_records = []
        recommended_action = "No duplicate conflicts were detected."

    matched_payload = []
    for record in matched_records[:20]:
        matched_payload.append(
            {
                "session_id": record.get("session_id"),
                "session_user_id": record.get("session_user_id"),
                "local_record_id": record.get("local_record_id"),
                "record_status": record.get("record_status"),
                "zenodo_doi": record.get("zenodo_doi"),
                "record_link": record.get("record_link"),
                "concept_rec_id": record.get("concept_rec_id"),
                "record_title": record.get("record_title"),
                "normalized_source_file_path": record.get("normalized_source_file_path"),
                "is_sandbox": bool(record.get("is_sandbox")),
            }
        )

    return {
        "candidate_source_file": candidate.source_file_path,
        "candidate_filename": candidate.source_file_name,
        "dataset_key": candidate.dataset_key,
        "normalized_source_file_path": candidate.normalized_source_file_path,
        "classification": classification,
        "matched_record_count": len(matched_records),
        "matched_records": matched_payload,
        "recommended_action": recommended_action,
    }


def _build_record_resolution_match_payload(record: dict[str, Any], *, score: float | None = None) -> dict[str, Any]:
    payload = {
        "session_id": record.get("session_id"),
        "session_user_id": record.get("session_user_id"),
        "local_record_id": record.get("local_record_id"),
        "record_status": record.get("record_status"),
        "zenodo_doi": record.get("zenodo_doi"),
        "record_link": record.get("record_link"),
        "zenodo_record_id": record.get("zenodo_record_id"),
        "concept_rec_id": record.get("concept_rec_id"),
        "record_title": record.get("record_title"),
        "normalized_source_file_path": record.get("normalized_source_file_path"),
        "source_file_name": record.get("source_file_name"),
        "source_size_bytes": record.get("source_size_bytes"),
        "source_sha256_hash": record.get("source_sha256_hash"),
        "dataset_key": record.get("dataset_key"),
        "is_sandbox": bool(record.get("is_sandbox")),
        "environment": "sandbox" if bool(record.get("is_sandbox")) else "production",
        "version": record.get("version"),
        "version_rank": record.get("version_rank"),
        "updated_at": record.get("updated_at"),
        "created_at": record.get("created_at"),
        "missing_repair_assets": _record_is_missing_repair_assets(record),
    }
    if score is not None:
        payload["match_score"] = score
    return payload


def _select_best_version_target(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        item
        for item in records
        if str(item.get("record_status") or "").strip().lower() == "published"
        and str(item.get("concept_rec_id") or "").strip()
    ]
    if not candidates:
        return None
    return max(candidates, key=record_version_sort_key)


def _ordered_actions(recommended_action: str, allowed_actions: list[str]) -> list[str]:
    ordered: list[str] = []
    for action in [recommended_action] + list(allowed_actions):
        normalized = normalize_record_resolution_action(action)
        if normalized and normalized not in ordered:
            ordered.append(normalized)
    return ordered


def analyze_candidate_record_resolution(
    candidate: CandidateFile,
    records: list[dict[str, Any]],
    *,
    config: dict[str, Any] | None = None,
    exclude_record: tuple[int, int] | None = None,
) -> dict[str, Any]:
    effective_config = config or VersionDetectionPolicyService.get_effective_config()
    thresholds = effective_config.get("thresholds") if isinstance(effective_config.get("thresholds"), dict) else {}
    version_threshold = float(thresholds.get("version_recommendation_score", 0.9) or 0.9)
    warning_threshold = float(thresholds.get("warning_score", 0.35) or 0.35)
    relevant_records = [
        record
        for record in records
        if record.get("dataset_key_lower") == normalize_dataset_key_lower(candidate.dataset_key)
        and bool(record.get("is_sandbox")) == bool(candidate.is_sandbox)
    ]

    same_path_records: list[dict[str, Any]] = []
    other_records: list[dict[str, Any]] = []
    for record in relevant_records:
        record_ref = (int(record.get("session_id") or 0), int(record.get("local_record_id") or 0))
        if exclude_record and record_ref == exclude_record:
            continue
        record_path = str(record.get("normalized_source_file_path") or "").strip().lower()
        if record_path and record_path == candidate.normalized_source_file_path.lower():
            same_path_records.append(record)
        else:
            other_records.append(record)

    matched_records: list[dict[str, Any]] = []
    recommended_target = None
    allowed_actions: list[str] = []
    recommended_action = "create_fresh_record"
    severity = "clean"
    reason_codes: list[str] = []
    evidence: dict[str, Any] = {
        "hard_rule": None,
        "soft_match": None,
    }
    explanation = "No record conflicts were detected for this candidate."
    score = 0.0

    if same_path_records:
        same_lineage = [
            record
            for record in same_path_records
            if candidate.concept_rec_id and str(record.get("concept_rec_id") or "").strip() == candidate.concept_rec_id
        ]
        conflicting_lineage = [
            record
            for record in same_path_records
            if not candidate.concept_rec_id or str(record.get("concept_rec_id") or "").strip() != candidate.concept_rec_id
        ]
        if conflicting_lineage:
            matched_records = conflicting_lineage + [record for record in same_lineage if record not in conflicting_lineage]
            recommended_action = "force_create_fresh"
            severity = "blocker"
            reason_codes = ["exact_path_conflicting_lineage"]
            allowed_actions = ["skip"]
            if effective_config.get("allow_force_create_fresh", True):
                allowed_actions.insert(0, "force_create_fresh")
            evidence["hard_rule"] = {
                "rule": "exact_path_conflicting_lineage",
                "matched_record_count": len(matched_records),
            }
            explanation = (
                "This source path already exists in another record lineage. Versioning is not allowed; "
                "either skip the candidate or force a fresh record with an explicit override."
            )
            score = 1.0
        elif same_lineage:
            matched_records = list(same_lineage)
            recommended_target_record = _select_best_version_target(same_lineage)
            recommended_target = _build_record_resolution_match_payload(recommended_target_record) if recommended_target_record else None
            severity = "version"
            recommended_action = "create_version" if recommended_target else "skip"
            allowed_actions = ["create_version", "skip"] if recommended_target else ["skip"]
            score = 1.0
            if any(_record_is_missing_repair_assets(record) for record in same_lineage):
                reason_codes = ["exact_path_same_lineage", "repair_missing_uploaded_assets"]
                explanation = (
                    "This source path matches the same published lineage and the existing record is missing expected "
                    "derived assets. The default action is to create a repair version draft."
                )
            else:
                reason_codes = ["exact_path_same_lineage"]
                explanation = (
                    "This source path matches an existing published lineage exactly. The default action is to create "
                    "a new version instead of a fresh record."
                )
            evidence["hard_rule"] = {
                "rule": "exact_path_same_lineage",
                "matched_record_count": len(matched_records),
                "repair_recommended": "repair_missing_uploaded_assets" in reason_codes,
            }
        else:
            matched_records = list(same_path_records)
            recommended_action = "force_create_fresh"
            severity = "blocker"
            reason_codes = ["exact_path_missing_lineage"]
            allowed_actions = ["skip"]
            if effective_config.get("allow_force_create_fresh", True):
                allowed_actions.insert(0, "force_create_fresh")
            evidence["hard_rule"] = {
                "rule": "exact_path_missing_lineage",
                "matched_record_count": len(matched_records),
            }
            explanation = (
                "This source path already exists, but the candidate has no lineage reference. Creating a fresh record "
                "requires an explicit override."
            )
            score = 1.0
    else:
        global_hash_matches = find_global_hash_collision_records(
            candidate,
            records,
            config=effective_config,
            exclude_record=exclude_record,
        )
        scored_matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for record in other_records:
            soft_match = _soft_match_score(candidate, record, config=effective_config)
            if soft_match["score"] <= 0:
                continue
            scored_matches.append((record, soft_match))
        scored_matches.sort(
            key=lambda item: (
                item[1]["score"],
                1 if str(item[0].get("record_status") or "").strip().lower() == "published" else 0,
                normalized_version_rank(item[0]),
                parse_timestamp(item[0].get("updated_at")),
                parse_int(item[0].get("local_record_id")),
            ),
            reverse=True,
        )
        matched_records = [item[0] for item in scored_matches[:10]]
        best_record, best_soft_match = scored_matches[0] if scored_matches else (None, None)
        if best_record and best_soft_match:
            score = float(best_soft_match["score"] or 0.0)
            recommended_target_record = _select_best_version_target([best_record])
            recommended_target = (
                _build_record_resolution_match_payload(recommended_target_record, score=score)
                if recommended_target_record
                else None
            )
            evidence["soft_match"] = {
                "matched_record_count": len(scored_matches),
                "best_match": _build_record_resolution_match_payload(best_record, score=score),
                "signals": best_soft_match["signals"],
            }
            if (
                score >= version_threshold
                and recommended_target_record is not None
            ):
                recommended_action = "create_version"
                severity = "version"
                reason_codes = list(best_soft_match["reason_codes"]) + ["weighted_version_recommendation"]
                allowed_actions = ["create_version", "create_fresh_record", "skip"]
                explanation = (
                    "The strongest existing match shares enough stable identity signals to recommend versioning, "
                    "but the match should still be reviewed before processing."
                )
            elif score >= warning_threshold:
                recommended_action = "create_fresh_record"
                severity = "warning"
                reason_codes = list(best_soft_match["reason_codes"]) or ["weighted_warning_match"]
                allowed_actions = ["create_fresh_record", "skip"]
                if recommended_target_record is not None:
                    allowed_actions.append("create_version")
                explanation = (
                    "This candidate overlaps with an existing record on secondary identity signals such as hash, "
                    "filename, or metadata. Review the match before deciding whether to version or create fresh."
                )
            else:
                recommended_action = "create_fresh_record"
                severity = "clean"
                reason_codes = []
                allowed_actions = ["create_fresh_record", "skip"]
                explanation = "No strong duplicate or versioning signal was detected for this candidate."
        else:
            allowed_actions = ["create_fresh_record", "skip"]

        if global_hash_matches:
            existing_refs = {
                (int(item.get("session_id") or 0), int(item.get("local_record_id") or 0))
                for item in matched_records
            }
            global_only_matches = [
                item
                for item in global_hash_matches
                if (int(item.get("session_id") or 0), int(item.get("local_record_id") or 0)) not in existing_refs
            ]
            matched_records = list(global_hash_matches) + [
                item
                for item in matched_records
                if (int(item.get("session_id") or 0), int(item.get("local_record_id") or 0))
                not in {
                    (int(match.get("session_id") or 0), int(match.get("local_record_id") or 0))
                    for match in global_hash_matches
                }
            ]
            evidence["global_hash_collision"] = {
                "matched_record_count": len(global_hash_matches),
                "global_only_record_count": len(global_only_matches),
                "policy": {
                    "min_size_bytes": _hash_collision_policy(effective_config).get("min_size_bytes"),
                    "exclude_generated_renders": _hash_collision_policy(effective_config).get("exclude_generated_renders"),
                },
                "matches": [_build_record_resolution_match_payload(record) for record in global_hash_matches[:10]],
            }
            if "global_hash_collision" not in reason_codes:
                reason_codes.insert(0, "global_hash_collision")
            if severity == "clean":
                severity = "warning"
                recommended_action = "create_fresh_record"
                allowed_actions = ["create_fresh_record", "skip"]
                score = max(score, warning_threshold)
                explanation = (
                    "This file has the same content hash as an existing Zenodo record. Review the matching records "
                    "before deciding whether to continue with a fresh record."
                )
            elif severity == "warning":
                explanation = (
                    f"{explanation} A global content-hash collision was also found across known WebHDP records."
                )

    confidence = {
        "label": _confidence_label(score, version_threshold=version_threshold, warning_threshold=warning_threshold),
        "score": round(float(score or 0.0), 3),
    }
    decision_key = build_record_resolution_decision_key(candidate.dataset_key, candidate.normalized_source_file_path)
    matched_payload = [_build_record_resolution_match_payload(record) for record in matched_records[:20]]
    if not recommended_target and recommended_action == "create_version":
        recommended_action = "skip"
    allowed_actions = _ordered_actions(recommended_action, allowed_actions)

    return {
        "decision_key": decision_key,
        "candidate_source_file": candidate.source_file_path,
        "candidate_filename": candidate.source_file_name,
        "dataset_key": candidate.dataset_key,
        "normalized_source_file_path": candidate.normalized_source_file_path,
        "candidate_identity": _candidate_identity_metadata(candidate),
        "severity": severity,
        "recommended_action": recommended_action,
        "allowed_actions": allowed_actions,
        "confidence": confidence,
        "reason_codes": reason_codes,
        "explanation": explanation,
        "review_required": severity != "clean",
        "matched_record_count": len(matched_records),
        "matched_records": matched_payload,
        "recommended_target": recommended_target,
        "selected_action": recommended_action,
        "selected_target": recommended_target,
        "resolved": severity == "clean",
        "evidence": evidence,
    }


def _apply_saved_resolution_decisions(
    candidates: list[dict[str, Any]],
    saved_state: dict[str, Any],
) -> list[dict[str, Any]]:
    decisions_by_key = {
        str(item.get("decision_key") or "").strip(): item
        for item in (saved_state.get("decisions") or [])
        if isinstance(item, dict) and str(item.get("decision_key") or "").strip()
    }
    merged: list[dict[str, Any]] = []
    for candidate in candidates:
        decision_key = str(candidate.get("decision_key") or "").strip()
        saved_decision = decisions_by_key.get(decision_key)
        enriched = dict(candidate)
        if saved_decision:
            chosen_action = normalize_record_resolution_action(saved_decision.get("action"))
            if chosen_action and chosen_action in (candidate.get("allowed_actions") or []):
                enriched["selected_action"] = chosen_action
                enriched["resolved"] = bool(saved_decision.get("resolved", False) or candidate.get("severity") == "clean")
                target_matches = [
                    item
                    for item in ([candidate.get("recommended_target")] + list(candidate.get("matched_records") or []))
                    if isinstance(item, dict)
                    and (
                        parse_int(item.get("session_id")) == parse_int(saved_decision.get("target_session_id"))
                        and parse_int(item.get("local_record_id")) == parse_int(saved_decision.get("target_local_record_id"))
                    )
                ]
                if target_matches:
                    enriched["selected_target"] = dict(target_matches[0])
                enriched["forced_override_reason"] = saved_decision.get("forced_override_reason")
            else:
                enriched["resolved"] = candidate.get("severity") == "clean"
        merged.append(enriched)
    return merged


def _record_resolution_summary(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    severity_counter = Counter(str(item.get("severity") or "clean") for item in candidates)
    recommended_counter = Counter(str(item.get("recommended_action") or "") for item in candidates)
    selected_counter = Counter(str(item.get("selected_action") or "") for item in candidates)
    affected_count = sum(1 for item in candidates if str(item.get("severity") or "clean") != "clean")
    resolved_count = sum(
        1
        for item in candidates
        if bool(item.get("resolved")) or str(item.get("severity") or "clean") == "clean"
    )
    unresolved_count = max(len(candidates) - resolved_count, 0)
    return {
        "candidate_count": len(candidates),
        "affected_count": affected_count,
        "clean": int(severity_counter.get("clean", 0)),
        "warning": int(severity_counter.get("warning", 0)),
        "version": int(severity_counter.get("version", 0)),
        "blocker": int(severity_counter.get("blocker", 0)),
        "resolved_count": resolved_count,
        "unresolved_count": unresolved_count,
        "recommended_action_counts": {
            key: int(recommended_counter.get(key, 0))
            for key in VALID_RESOLUTION_ACTIONS
        },
        "selected_action_counts": {
            key: int(selected_counter.get(key, 0))
            for key in VALID_RESOLUTION_ACTIONS
        },
        "can_continue": unresolved_count == 0,
    }


def analyze_session_record_resolution(
    session_row: DBSession,
    *,
    policy_override: Any = None,
    include_all_sessions: bool = True,
    inventory: RecordInventorySnapshot | None = None,
) -> dict[str, Any]:
    saved_state = get_session_record_resolution_state(session_row.id)
    effective_preset = normalize_record_resolution_preset(policy_override) or saved_state.get("policy_override")
    effective_config = VersionDetectionPolicyService.get_effective_config(effective_preset)
    candidates = scan_candidate_files_for_session(session_row)
    inventory = inventory or RecordInventorySnapshot(collect_dataset_records(None, include_all_sessions=include_all_sessions)[0])
    analyzed_candidates = [
        analyze_candidate_record_resolution(
            candidate,
            inventory.matching(candidate),
            config=effective_config,
            exclude_record=(session_row.id, int(candidate.local_record_id))
            if candidate.local_record_id is not None
            else None,
        )
        for candidate in candidates
    ]
    merged_candidates = _apply_saved_resolution_decisions(analyzed_candidates, saved_state)
    return {
        "policy_preset": effective_config.get("preset"),
        "policy": effective_config,
        "state": {
            "policy_override": effective_preset,
            "decisions": saved_state.get("decisions") or [],
        },
        "summary": _record_resolution_summary(merged_candidates),
        "candidates": merged_candidates,
    }


def validate_record_resolution_decisions(
    session_row: DBSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    analysis = analyze_session_record_resolution(
        session_row,
        policy_override=payload.get("policy_override"),
    )
    candidates_by_key = {
        str(item.get("decision_key") or "").strip(): item
        for item in analysis.get("candidates") or []
        if isinstance(item, dict)
    }
    normalized_decisions: list[dict[str, Any]] = []
    for item in payload.get("decisions") or []:
        if not isinstance(item, dict):
            continue
        decision_key = str(item.get("decision_key") or "").strip()
        action = normalize_record_resolution_action(item.get("action"))
        candidate = candidates_by_key.get(decision_key)
        if not decision_key or not action or candidate is None:
            continue
        if action not in (candidate.get("allowed_actions") or []):
            raise DatasetIntegrityConflictError(
                "The requested record resolution action is not allowed for this candidate.",
                details={"decision_key": decision_key, "allowed_actions": candidate.get("allowed_actions") or []},
            )
        target_session_id = parse_int(item.get("target_session_id")) or None
        target_local_record_id = parse_int(item.get("target_local_record_id")) or None
        target_concept_rec_id = str(item.get("target_concept_rec_id") or "").strip() or None
        if action == "create_version":
            target = candidate.get("recommended_target") if isinstance(candidate.get("recommended_target"), dict) else None
            matched_target = next(
                (
                    record
                    for record in ([target] + list(candidate.get("matched_records") or []))
                    if isinstance(record, dict)
                    and parse_int(record.get("session_id")) == target_session_id
                    and parse_int(record.get("local_record_id")) == target_local_record_id
                ),
                None,
            )
            if matched_target is None:
                matched_target = target
            if matched_target is None:
                raise DatasetIntegrityConflictError(
                    "Versioning requires a resolvable published target record.",
                    details={"decision_key": decision_key},
                )
            target_session_id = parse_int(matched_target.get("session_id")) or None
            target_local_record_id = parse_int(matched_target.get("local_record_id")) or None
            target_concept_rec_id = str(
                matched_target.get("concept_rec_id") or target_concept_rec_id or ""
            ).strip() or None
            if not target_concept_rec_id:
                raise DatasetIntegrityConflictError(
                    "Versioning requires a target concept record ID.",
                    details={"decision_key": decision_key},
                )
        forced_override_reason = str(item.get("forced_override_reason") or "").strip() or None
        if action == "force_create_fresh" and not forced_override_reason:
            raise DatasetIntegrityConflictError(
                "Force-create overrides require an audit reason.",
                details={"decision_key": decision_key},
            )
        normalized_decisions.append(
            {
                "decision_key": decision_key,
                "action": action,
                "resolved": bool(item.get("resolved", False) or candidate.get("severity") == "clean"),
                "target_session_id": target_session_id,
                "target_local_record_id": target_local_record_id,
                "target_concept_rec_id": target_concept_rec_id,
                "forced_override_reason": forced_override_reason,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return {
        "policy_override": normalize_record_resolution_preset(payload.get("policy_override")),
        "decisions": normalized_decisions,
    }


def build_duplicate_check_payload(
    candidates: list[CandidateFile],
    records: list[dict[str, Any]],
    *,
    exclude_record: tuple[int, int] | None = None,
) -> dict[str, Any]:
    results = [classify_candidate(candidate, records, exclude_record=exclude_record) for candidate in candidates]
    classification_counter = Counter(item["classification"] for item in results)
    return {
        "candidate_count": len(results),
        "summary": {
            "clean": int(classification_counter.get("clean", 0)),
            "warning": int(classification_counter.get("warning", 0)),
            "allowed_versioning": int(classification_counter.get("allowed_versioning", 0)),
            "blocker": int(classification_counter.get("blocker", 0)),
        },
        "results": results,
    }


def build_duplicate_groups(dataset_key: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, bool], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        path_key = str(record.get("normalized_source_file_path") or "").strip().lower()
        if not path_key:
            continue
        grouped[(path_key, bool(record.get("is_sandbox")))].append(record)

    groups: list[dict[str, Any]] = []
    for (path_key, is_sandbox), records_for_path in grouped.items():
        published_count = sum(1 for record in records_for_path if record.get("record_status") == "published")
        if len(records_for_path) < 2 and published_count < 2:
            continue
        sorted_records = sorted(
            records_for_path,
            key=lambda record: (
                1 if record.get("record_status") == "published" else 0,
                1 if record.get("record_status") == "draft" else 0,
                parse_timestamp(record.get("updated_at")),
                int(record.get("local_record_id") or 0),
            ),
            reverse=True,
        )
        classifications = Counter(classify_draft_kind(record, records_for_path) for record in records_for_path)
        groups.append(
            {
                "dataset_key": dataset_key,
                "environment": "sandbox" if is_sandbox else "production",
                "normalized_source_file_path": sorted_records[0].get("normalized_source_file_path"),
                "conflict_class": "published_duplicate" if published_count > 1 else "draft_or_prepared_overlap",
                "record_count": len(records_for_path),
                "published_record_count": published_count,
                "lineage_count": len(
                    {
                        str(record.get("concept_rec_id") or "").strip()
                        for record in records_for_path
                        if str(record.get("concept_rec_id") or "").strip()
                    }
                ),
                "draft_breakdown": {key: value for key, value in classifications.items() if key != "not_draft"},
                "recommended_action": (
                    "Collapse duplicates into a single lineage or keep only same-lineage repair drafts."
                    if published_count > 1
                    else "Review the prepared and draft rows before publishing."
                ),
                "records": [
                    {
                        "session_id": record.get("session_id"),
                        "session_user_id": record.get("session_user_id"),
                        "local_record_id": record.get("local_record_id"),
                        "record_status": record.get("record_status"),
                        "record_title": record.get("record_title"),
                        "zenodo_doi": record.get("zenodo_doi"),
                        "record_link": record.get("record_link"),
                        "concept_rec_id": record.get("concept_rec_id"),
                        "is_sandbox": bool(record.get("is_sandbox")),
                        "updated_at": record.get("updated_at"),
                        "can_create_version": bool(
                            record.get("record_status") == "published" and str(record.get("concept_rec_id") or "").strip()
                        ),
                    }
                    for record in sorted_records
                ],
            }
        )
    groups.sort(key=lambda item: (item["published_record_count"], item["record_count"], item["normalized_source_file_path"]), reverse=True)
    return groups


def csv_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "original_filename": record.get("source_file_name") or "",
        "zenodo_doi": record.get("zenodo_doi") or "",
        "glb_direct_link": record.get("glb_direct_link") or "",
        "record_link": record.get("record_link") or "",
        "zenodo_record_id": record.get("zenodo_record_id") or "",
        "record_status": record.get("record_status") or "",
        "session_id": record.get("session_id") or "",
        "local_record_id": record.get("local_record_id") or "",
    }


def records_to_csv_text(records: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=PRIMARY_CSV_COLUMNS)
    writer.writeheader()
    writer.writerows([csv_row(record) for record in records])
    return output.getvalue()


def json_payload(records: list[dict[str, Any]], authoritative_session_id: int | None, dataset_key: str) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_key": dataset_key,
        "authoritative_session_id": authoritative_session_id,
        "record_count": len(records),
        "records": [
            {
                "authority_classification": record.get("authority_classification"),
                "session_id": record.get("session_id"),
                "local_record_id": record.get("local_record_id"),
                "source_file_id": record.get("source_file_id"),
                "source_file_name": record.get("source_file_name"),
                "source_file_path": record.get("source_file_path"),
                "normalized_source_file_path": record.get("normalized_source_file_path"),
                "record_status": record.get("record_status"),
                "record_title": record.get("record_title"),
                "zenodo_record_id": record.get("zenodo_record_id"),
                "concept_rec_id": record.get("concept_rec_id"),
                "version": record.get("version"),
                "version_rank": record.get("version_rank"),
                "zenodo_doi": record.get("zenodo_doi"),
                "record_link": record.get("record_link"),
                "glb_direct_link": record.get("glb_direct_link"),
                "is_sandbox": record.get("is_sandbox"),
                "created_at": record.get("created_at"),
                "updated_at": record.get("updated_at"),
                "last_api_error": record.get("last_api_error"),
                "record_file_count": record.get("record_file_count"),
            }
            for record in records
        ],
    }


def build_dataset_export_bundle(
    dataset_key: str,
    records: list[dict[str, Any]],
    *,
    authoritative_session_id: int | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    chosen_authoritative_session_id = authoritative_session_id if authoritative_session_id is not None else choose_authoritative_session_id(records)
    if chosen_authoritative_session_id is None:
        return {
            "dataset_key": dataset_key,
            "authoritative_session_id": None,
            "primary": {
                "record_count": 0,
                "json_payload": json_payload([], None, dataset_key),
                "csv_text": records_to_csv_text([]),
            },
            "secondary": {
                "record_count": 0,
                "json_payload": json_payload([], None, dataset_key),
                "csv_text": records_to_csv_text([]),
            },
        }

    authoritative_published = [
        record
        for record in records
        if record.get("session_id") == chosen_authoritative_session_id and record.get("record_status") == "published"
    ]
    published_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in authoritative_published:
        path_key = str(record.get("normalized_source_file_path") or "").strip().lower()
        if path_key:
            published_by_path[path_key].append(record)

    public_cache = ZenodoPublicCache(timeout=timeout)
    primary_records: list[dict[str, Any]] = []
    for path_key in sorted(published_by_path):
        chosen = dict(choose_latest_record(published_by_path[path_key]))
        chosen["authority_classification"] = "authoritative_published"
        chosen["glb_direct_link"] = resolve_glb_direct_link(chosen, public_cache)
        primary_records.append(chosen)

    primary_refs = {(record.get("session_id"), record.get("local_record_id")) for record in primary_records}
    secondary_records: list[dict[str, Any]] = []
    for record in records:
        record_ref = (record.get("session_id"), record.get("local_record_id"))
        if record_ref in primary_refs:
            continue
        enriched = dict(record)
        enriched["authority_classification"] = "superseded_or_draft"
        enriched["glb_direct_link"] = resolve_glb_direct_link(enriched, public_cache)
        secondary_records.append(enriched)

    secondary_records.sort(
        key=lambda record: (
            int(record.get("session_id") or 0),
            parse_timestamp(record.get("updated_at")),
            int(record.get("local_record_id") or 0),
        ),
        reverse=True,
    )

    primary_paths = {str(record.get("normalized_source_file_path") or "").strip().lower() for record in primary_records}
    if len(primary_paths) != len(primary_records):
        raise ValueError("Primary export contains duplicate normalized source paths.")

    return {
        "dataset_key": dataset_key,
        "authoritative_session_id": chosen_authoritative_session_id,
        "primary": {
            "record_count": len(primary_records),
            "json_payload": json_payload(primary_records, chosen_authoritative_session_id, dataset_key),
            "csv_text": records_to_csv_text(primary_records),
        },
        "secondary": {
            "record_count": len(secondary_records),
            "json_payload": json_payload(secondary_records, chosen_authoritative_session_id, dataset_key),
            "csv_text": records_to_csv_text(secondary_records),
        },
    }


def ensure_fresh_record_creation_allowed(
    session_row: DBSession,
    *,
    source_file_path: str,
    is_sandbox: bool,
    concept_rec_id: str = "",
    inventory: RecordInventorySnapshot | None = None,
) -> None:
    dataset_key = normalize_dataset_key(extract_dataset_key(source_file_path, *(get_session_dataset_context(session_row).values())))
    # Arbitrary uploaded filenames have no named dataset root. Give them the
    # same session-scoped identity as candidate scans and persisted records.
    dataset_key = dataset_key or infer_session_dataset_key(session_row)
    candidate = CandidateFile(
        source_file_path=source_file_path,
        source_file_name=os.path.basename(source_file_path),
        dataset_key=dataset_key,
        normalized_source_file_path=normalize_source_path(source_file_path, dataset_key),
        is_sandbox=is_sandbox,
        concept_rec_id=str(concept_rec_id or "").strip(),
        session_id=session_row.id,
    )
    all_records = inventory.matching(candidate) if inventory else collect_dataset_records(include_all_sessions=True)[0]
    result = classify_candidate(candidate, all_records)
    if result["classification"] in {"blocker", "allowed_versioning"}:
        raise DatasetIntegrityConflictError(
            "Duplicate dataset source detected. Fresh record creation is blocked.",
            details=result,
        )


def ensure_record_operation_allowed(
    session_row: DBSession,
    *,
    local_record_id: int,
    allow_allowed_versioning: bool = False,
    exclude_current_record: bool = True,
    inventory: RecordInventorySnapshot | None = None,
) -> None:
    record = (inventory.by_session.get(session_row.id, {}).get(int(local_record_id)) if inventory else
              next((item for item in read_session_records(session_row) if int(item.get("local_record_id") or 0) == int(local_record_id)), None))
    if not record:
        raise DatasetIntegrityConflictError(
            "Record could not be found for duplicate detection.",
            details={"session_id": session_row.id, "local_record_id": local_record_id},
        )
    dataset_key = normalize_dataset_key(record.get("dataset_key"))
    source_file_path = str(record.get("source_file_path") or "").strip()
    if not dataset_key or not source_file_path:
        if allow_allowed_versioning and record.get("concept_rec_id") and source_file_path:
            return
        # Sandbox/session-local uploads may not expose a stable dataset root.
        # In that case we match fresh-record policy and skip duplicate scanning.
        if bool(record.get("is_sandbox")) and source_file_path and not dataset_key:
            return
        raise DatasetIntegrityConflictError(
            "Record has no dataset-aware source path for duplicate detection.",
            details={"session_id": session_row.id, "local_record_id": local_record_id},
        )
    candidate = CandidateFile(
        source_file_path=source_file_path,
        source_file_name=str(record.get("source_file_name") or os.path.basename(source_file_path)),
        dataset_key=dataset_key,
        normalized_source_file_path=str(record.get("normalized_source_file_path") or ""),
        is_sandbox=bool(record.get("is_sandbox")),
        concept_rec_id=str(record.get("concept_rec_id") or "").strip(),
        sha256_hash=str(record.get("source_sha256_hash") or "").strip(),
        session_id=session_row.id,
        local_record_id=int(local_record_id),
    )
    all_records = inventory.matching(candidate) if inventory else collect_dataset_records(include_all_sessions=True)[0]
    result = classify_candidate(
        candidate,
        all_records,
        exclude_record=(session_row.id, int(local_record_id)) if exclude_current_record else None,
    )
    if result["classification"] == "blocker":
        raise DatasetIntegrityConflictError(
            "Duplicate dataset source detected. The requested record operation is blocked.",
            details=result,
        )
    if result["classification"] == "allowed_versioning" and not allow_allowed_versioning:
        raise DatasetIntegrityConflictError(
            "This source path is only valid as a same-lineage versioning operation.",
            details=result,
        )
