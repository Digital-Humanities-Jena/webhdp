import json
import logging
import os
import socket
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

import requests
from flask import Blueprint, Response, current_app, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required

from api_utils import APIResponse
from database.database import db
from database.models import Session as DBSession
from database.models import SystemConfig, User
from exceptions import ResourceNotFoundError, ValidationError
from routes.admin_routes import require_admin, require_moderator_or_admin
from routes.msf_routes import (
    _build_parse_options,
    _coerce_bool,
    _is_admin_request_user,
    _list_local_msf_files,
    _resolve_local_directory_path,
    _resolve_local_input_root,
    _resolve_local_msf_path,
    _scan_directory_files,
    require_admin_and_local_mode,
)
from routes.lod_mapping_helpers import build_pipeline_aligned_lod_metadata
from routes.session_routes import _unpack_route_response, get_session_records
from services.cloud_upload_service import CloudUploadService, STORAGE_MODE_LOCAL
from services.community_moderation_history_service import (
    get_task_entry as get_community_moderation_task_entry,
    list_task_entries as list_community_moderation_task_entries,
    record_task_launch as record_community_moderation_task_launch,
    update_task_entry as update_community_moderation_task_entry,
)
from services.community_moderation_sweep_service import CommunityModerationSweepService
from services.community_migration_service import CommunityMigrationService
from services.metadata_workflow_service import get_metadata_workflow_contract
from services.pipeline_platform_service import get_pipeline_platform_contract
from services.tools_access_policy import can_author_pipelines, core_workflow_only, native_tools_enabled
from services.institution_service import InstitutionService
from services.user_service import UserService
from services.zenodo_config_service import ZenodoConfigService
from services.zenodo_credential_service import ZenodoCredentialService, normalize_environment
from services import zenodo_moderation_service
from services.zenodo_batch_history_service import get_task_entry, list_task_entries, record_task_launch, update_task_entry
from services.zenodo_account_retrieval_history_service import (
    clear_pause as clear_zenodo_retrieval_pause,
    delete_retrieval_entry,
    get_retrieval_entry,
    find_latest_successful_collection,
    list_retrieval_entries,
    new_retrieval_id,
    publicize_retrieval_entry,
    record_retrieval_launch,
    request_cancel as request_zenodo_retrieval_cancel,
    request_pause as request_zenodo_retrieval_pause,
    update_retrieval_entry,
)
from services.zenodo_account_retrieval_service import (
    DETECTOR_PRESETS,
    MAX_RECORDS_CEILING,
    build_retrieval_shard_archive,
    build_retrieval_diagnostics,
    compact_retrieval_shards,
    delete_retrieval_shards,
    delete_compacted_retrieval_shards,
    export_detector_candidates_csv,
    export_retrieval_manifest,
    export_retrieval_records_csv,
    normalize_max_records,
    normalize_retrieval_datetime,
    run_retrieval_detector,
    search_retrieval_collection,
)
from services.zenodo_oai_harvest_history_service import (
    clear_pause as clear_oai_harvest_pause,
    delete_harvest_entry,
    find_latest_successful_harvest,
    get_harvest_entry,
    list_harvest_entries,
    new_harvest_id,
    publicize_harvest_entry,
    record_harvest_launch,
    request_cancel as request_oai_harvest_cancel,
    request_pause as request_oai_harvest_pause,
    update_harvest_entry,
)
from services.zenodo_oai_harvest_service import (
    DEFAULT_OAI_BASE_URL,
    DEFAULT_OAI_METADATA_PREFIX,
    DEFAULT_OAI_PAGE_SIZE,
    DEFAULT_OAI_SET_SPEC,
    build_oai_harvest_diagnostics,
    build_oai_harvest_preflight,
    build_oai_harvest_shard_archive,
    compact_oai_harvest_shards,
    delete_oai_harvest_shards,
    export_oai_harvest_detector_csv,
    export_oai_harvest_manifest,
    export_oai_harvest_records_csv,
    normalize_oai_datetime,
    normalize_oai_max_records,
    normalize_oai_metadata_prefix,
    normalize_oai_set_spec,
    run_oai_harvest_detector,
    search_oai_harvest_collection,
)
from workflow_status import TERMINAL_SESSION_STATES, normalize_session_state

logger = logging.getLogger(__name__)
tools_bp = Blueprint("tools", __name__)
institution_service = InstitutionService()
credential_service = ZenodoCredentialService()
community_migration_service = CommunityMigrationService()
community_moderation_sweep_service = CommunityModerationSweepService()


def _http_health(url: str, timeout: float = 2.0) -> Dict[str, Any]:
    if not url:
        return {"ok": False, "message": "URL is not configured"}
    try:
        response = requests.get(url, timeout=timeout)
        return {
            "ok": response.status_code == 200,
            "status_code": response.status_code,
            "url": url,
        }
    except Exception as exc:
        return {"ok": False, "url": url, "message": str(exc)}


def _socket_health(host: str, port: int, timeout: float = 1.5) -> Dict[str, Any]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"ok": True, "host": host, "port": port}
    except Exception as exc:
        return {"ok": False, "host": host, "port": port, "message": str(exc)}


def _parse_json_object(value: Any, field_name: str) -> Tuple[Dict[str, Any], str]:
    if value is None:
        return {}, ""
    if isinstance(value, dict):
        return value, ""
    if not isinstance(value, str):
        return {}, f"{field_name} must be an object or JSON string"

    stripped = value.strip()
    if not stripped:
        return {}, ""
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        return {}, f"{field_name} JSON parse error: {exc}"
    if not isinstance(parsed, dict):
        return {}, f"{field_name} must be a JSON object"
    return parsed, ""


def _parse_iso_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_iso_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        candidate = _parse_iso_date(text)
        if candidate is None:
            return None
        return datetime.combine(candidate, datetime.min.time())


def _normalized_session_state_counts() -> dict[str, int]:
    counts: Counter[str] = Counter()
    for (raw_status,) in db.session.query(DBSession.status).all():
        counts[normalize_session_state(raw_status)] += 1
    return dict(counts)


def _parse_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _normalize_named_entries(values: Any, key: str) -> List[str]:
    if not isinstance(values, list):
        return []

    normalized: List[str] = []
    seen: set[str] = set()
    for item in values:
        if isinstance(item, dict):
            raw_value = item.get(key)
        else:
            raw_value = item
        text = str(raw_value or "").strip()
        if not text:
            continue
        signature = text.lower()
        if signature in seen:
            continue
        seen.add(signature)
        normalized.append(text)
    return normalized


def _extract_record_metadata_core(record: Dict[str, Any]) -> Dict[str, Any]:
    payload = record.get("record_metadata") if isinstance(record, dict) else {}
    if not isinstance(payload, dict):
        return {}
    metadata = payload.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _record_edit_capability(record: Dict[str, Any]) -> Dict[str, Any]:
    metadata_payload = record.get("record_metadata") if isinstance(record, dict) else {}
    metadata_payload = metadata_payload if isinstance(metadata_payload, dict) else {}
    links = metadata_payload.get("links") if isinstance(metadata_payload.get("links"), dict) else {}

    status = str(record.get("record_status") or "").strip().lower()
    if status == "draft":
        update_url = links.get("self") or links.get("latest_draft")
        if update_url:
            return {
                "eligible": True,
                "reason": "",
                "mode": "draft_update",
                "update_url": update_url,
            }
        return {
            "eligible": False,
            "reason": "Draft record is missing an editable deposition link.",
            "mode": "draft_update",
        }

    if status == "published":
        edit_url = links.get("edit")
        if edit_url:
            return {
                "eligible": True,
                "reason": "",
                "mode": "published_edit_publish",
                "edit_url": edit_url,
            }
        return {
            "eligible": False,
            "reason": "Published record does not expose a no-version edit action.",
            "mode": "published_edit_publish",
        }

    return {
        "eligible": False,
        "reason": f"Record status '{status or 'unknown'}' is not editable for community operations.",
        "mode": "unsupported",
    }


def _build_operation_eligibility(record: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    capability = _record_edit_capability(record)
    base = {
        "eligible": bool(capability.get("eligible")),
        "reason": str(capability.get("reason") or ""),
        "mode": capability.get("mode"),
    }
    return {
        "append_if_missing": dict(base),
        "remove_one": dict(base),
        "remove_all": dict(base),
    }


def _normalize_batch_record(session_row: DBSession, owner_email: str | None, record: Dict[str, Any]) -> Dict[str, Any]:
    metadata_core = _extract_record_metadata_core(record)
    creators = _normalize_named_entries(metadata_core.get("creators"), "name")
    communities = _normalize_named_entries(metadata_core.get("communities"), "identifier")
    publication_date = str(metadata_core.get("publication_date") or "").strip() or None

    return {
        **record,
        "session_id": int(session_row.id),
        "session_status": session_row.status,
        "session_created_at": session_row.created_at.isoformat() if session_row.created_at else None,
        "session_updated_at": session_row.updated_at.isoformat() if session_row.updated_at else None,
        "owner_user_id": int(session_row.user_id),
        "owner_email": owner_email,
        "creators_normalized": creators,
        "communities_normalized": communities,
        "publication_date": publication_date,
        "operation_eligibility": _build_operation_eligibility(record),
    }


def _string_matches_filter(values: List[str], filter_value: str) -> bool:
    needle = str(filter_value or "").strip().lower()
    if not needle:
        return True
    return any(needle in str(value or "").lower() for value in values)


def _record_matches_tools_filters(record: Dict[str, Any], filters: Dict[str, Any]) -> bool:
    q = str(filters.get("q") or "").strip().lower()
    if q:
        haystack = " ".join(
            [
                str(record.get("record_title") or ""),
                str(record.get("zenodo_doi") or ""),
                str(record.get("zenodo_record_id") or ""),
                str(record.get("concept_rec_id") or ""),
                str(record.get("local_record_id") or ""),
                str(record.get("session_id") or ""),
                str(record.get("owner_email") or ""),
                " ".join(record.get("creators_normalized") or []),
                " ".join(record.get("communities_normalized") or []),
            ]
        ).lower()
        if q not in haystack:
            return False

    session_id_filter = filters.get("session_id")
    if session_id_filter and int(record.get("session_id") or 0) != int(session_id_filter):
        return False

    owner_filter = filters.get("owner_user_id")
    if owner_filter and int(record.get("owner_user_id") or 0) != int(owner_filter):
        return False

    status_filter = str(filters.get("record_status") or "all").strip().lower()
    current_status = str(record.get("record_status") or "").strip().lower()
    if status_filter != "all":
        if status_filter == "other" and current_status in {"draft", "published"}:
            return False
        elif status_filter != "other" and current_status != status_filter:
            return False

    sandbox_filter = filters.get("is_sandbox")
    if sandbox_filter in {True, False} and bool(record.get("is_sandbox")) != sandbox_filter:
        return False

    creator_filter = filters.get("creator")
    if creator_filter and not _string_matches_filter(record.get("creators_normalized") or [], creator_filter):
        return False

    community_filter = filters.get("community")
    if community_filter and not _string_matches_filter(record.get("communities_normalized") or [], community_filter):
        return False

    publication_date = _parse_iso_date(record.get("publication_date"))
    publication_from = filters.get("publication_date_from")
    if publication_from and (publication_date is None or publication_date < publication_from):
        return False
    publication_to = filters.get("publication_date_to")
    if publication_to and (publication_date is None or publication_date > publication_to):
        return False

    updated_at = _parse_iso_datetime(record.get("updated_at"))
    updated_from = filters.get("updated_from")
    if updated_from and (updated_at is None or updated_at < updated_from):
        return False
    updated_to = filters.get("updated_to")
    if updated_to and (updated_at is None or updated_at > updated_to):
        return False

    return True


def _build_batch_operation_summary(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    status_counter = Counter(str(item.get("record_status") or "unknown") for item in records)
    return {
        "records_returned": len(records),
        "status_distribution": dict(status_counter),
        "draft_records": int(status_counter.get("draft", 0)),
        "published_records": int(status_counter.get("published", 0)),
        "other_records": max(len(records) - int(status_counter.get("draft", 0)) - int(status_counter.get("published", 0)), 0),
    }


def _serialize_grouped_batch_records(groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    serialized: List[Dict[str, Any]] = []
    for group in groups:
        records = list(group.get("records") or [])
        records.sort(key=lambda item: _parse_iso_datetime(item.get("updated_at")) or datetime.min, reverse=True)
        serialized.append(
            {
                "session": group.get("session"),
                "summary": _build_batch_operation_summary(records),
                "records": records,
            }
        )
    return serialized


def _normalize_record_refs(values: Any, *, max_items: int = 5000) -> List[Tuple[int, int]]:
    if not isinstance(values, list):
        return []

    normalized: List[Tuple[int, int]] = []
    seen: set[Tuple[int, int]] = set()
    for item in values:
        if not isinstance(item, dict):
            continue
        try:
            session_id = int(item.get("session_id"))
            local_record_id = int(item.get("local_record_id"))
        except (TypeError, ValueError):
            continue
        pair = (session_id, local_record_id)
        if pair in seen:
            continue
        seen.add(pair)
        normalized.append(pair)
        if len(normalized) >= max_items:
            break
    return normalized


def _task_payload_from_history(entry: Dict[str, Any]) -> Dict[str, Any]:
    result = entry.get("result") if isinstance(entry.get("result"), dict) else None
    return {
        "state": entry.get("state") or "PENDING",
        "status": entry.get("status") or "Pending...",
        "progress": entry.get("progress") if isinstance(entry.get("progress"), dict) else None,
        "result": result,
        "error": entry.get("error"),
        "history_entry": entry,
    }


def _community_moderation_task_payload_from_history(entry: Dict[str, Any]) -> Dict[str, Any]:
    result = entry.get("result") if isinstance(entry.get("result"), dict) else None
    return {
        "state": entry.get("state") or "PENDING",
        "status": entry.get("status") or "Pending...",
        "progress": entry.get("progress") if isinstance(entry.get("progress"), dict) else None,
        "result": result,
        "error": entry.get("error"),
    }


def _community_request_filters_from_args() -> Dict[str, Any]:
    return {
        "q": str(request.args.get("q") or "").strip(),
        "request_type": str(request.args.get("request_type") or "").strip().lower(),
        "created_from": _parse_iso_datetime(request.args.get("created_from")),
        "created_to": _parse_iso_datetime(request.args.get("created_to")),
        "updated_from": _parse_iso_datetime(request.args.get("updated_from")),
        "updated_to": _parse_iso_datetime(request.args.get("updated_to")),
    }


def _parse_optional_int_value(value: Any, *, field_name: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _resolve_moderation_context(*, community_identifier: Any = None, institution_id: Any = None) -> Dict[str, Any]:
    explicit_identifier = str(community_identifier or "").strip()
    selected_institution_id = _parse_optional_int_value(institution_id, field_name="institution_id")

    selected_institution = None
    selected_policy = None
    moderation_candidates: List[str] = []
    primary_submission_community = None

    if selected_institution_id:
        institution = institution_service.get_by_id(selected_institution_id)
        selected_policy = institution_service.build_community_policy(selected_institution_id)
        selected_institution = {
            **institution.to_dict(),
            "community_policy": selected_policy,
        }
        moderation_candidates = list(selected_policy.get("moderation_default_communities") or [])
        primary_submission_community = selected_policy.get("primary_submission_community")

    if explicit_identifier:
        resolved_identifier = explicit_identifier
        resolution_source = "explicit"
    elif moderation_candidates:
        resolved_identifier = moderation_candidates[0]
        resolution_source = "institution_moderation_default"
    elif primary_submission_community:
        resolved_identifier = primary_submission_community
        resolution_source = "institution_primary_submission"
    else:
        config = ZenodoConfigService.get_community_override_config()
        if config.get("enabled") and str(config.get("community") or "").strip():
            resolved_identifier = str(config["community"]).strip()
            resolution_source = "global_override"
        else:
            raise ValueError("community_identifier could not be resolved")

    return {
        "community_identifier": resolved_identifier,
        "resolution_source": resolution_source,
        "institution_id": selected_institution_id,
        "institution": selected_institution,
        "candidate_default_communities": moderation_candidates,
        "primary_submission_community": primary_submission_community,
    }


def _render_pipeline_steps() -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for pipeline_id in ["render", "metadata_only"]:
        config_key = f"pipeline_config:{pipeline_id}"
        try:
            entry = db.session.get(SystemConfig, config_key)
        except Exception:
            entry = None
        payload: Dict[str, Any] = {}
        if entry and entry.value:
            try:
                payload = json.loads(entry.value)
            except json.JSONDecodeError:
                payload = {}

        steps = payload.get("steps") if isinstance(payload, dict) else None
        if not isinstance(steps, list):
            steps = []
        result[pipeline_id] = {
            "steps": [
                {
                    "id": str(step.get("id") or ""),
                    "enabled": bool(step.get("enabled", False)),
                }
                for step in steps
                if isinstance(step, dict)
            ]
        }
    return result


def _build_service_health() -> Dict[str, Any]:
    from services.hdp_component_policy import (
        component_runtime_report,
        hpc_required_message,
        local_hdp_component_execution_allowed,
        webhdp_deployment_class,
        webhdp_deployment_label,
    )

    redis_url = os.environ.get("REDIS_URL") or os.environ.get("CELERY_BROKER_URL") or ""
    parsed_redis_url = urlparse(redis_url) if redis_url else None
    redis_host = (
        os.environ.get("REDIS_HOST")
        or current_app.config.get("REDIS_HOST")
        or (parsed_redis_url.hostname if parsed_redis_url else None)
        or "127.0.0.1"
    )
    redis_port = int(
        str(
            os.environ.get("REDIS_PORT")
            or current_app.config.get("REDIS_PORT")
            or (parsed_redis_url.port if parsed_redis_url else None)
            or 6379
        )
    )
    local_hdp_allowed = local_hdp_component_execution_allowed(current_app)
    renderer_health = (
        {
            "ok": bool(current_app.fast_renderer_service.check_health()),
            "url": current_app.fast_renderer_service.service_url,
            "hpc_required": False,
            "local_execution_allowed": True,
        }
        if local_hdp_allowed
        else {
            "ok": False,
            "url": None,
            "hpc_required": True,
            "local_execution_allowed": False,
            "message": hpc_required_message("fast_renderer"),
        }
    )
    usdz_health = (
        {
            "ok": bool(current_app.any_to_usdz_service.check_health()),
            "url": current_app.any_to_usdz_service.service_url,
            "hpc_required": False,
            "local_execution_allowed": True,
        }
        if local_hdp_allowed
        else {
            "ok": False,
            "url": None,
            "hpc_required": True,
            "local_execution_allowed": False,
            "message": hpc_required_message("any_to_usdz"),
        }
    )
    services = {
        "backend": {"ok": True, "message": "Backend API process is running."},
        "fast_renderer": renderer_health,
        "any_to_usdz": usdz_health,
        "redis": _socket_health(redis_host, redis_port),
        "deployment": {
            "class": webhdp_deployment_class(current_app),
            "label": webhdp_deployment_label(current_app),
        },
        "component_runtime": component_runtime_report(current_app),
    }
    return services


def _text_preview(value: str, max_chars: int = 4000) -> Dict[str, Any]:
    text = str(value or "")
    if len(text) <= max_chars:
        return {"text": text, "truncated": False}
    return {"text": text[:max_chars], "truncated": True}


def _build_validation_section(section_id: str, label: str, payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}
    errors = [str(item) for item in (payload.get("errors") or []) if str(item).strip()]
    warnings = [str(item) for item in (payload.get("warnings") or []) if str(item).strip()]
    infos = [str(item) for item in (payload.get("infos") or []) if str(item).strip()]
    section = {
        "id": section_id,
        "label": label,
        "valid": payload.get("valid", True),
        "skipped": bool(payload.get("skipped", False)),
        "errors": errors,
        "warnings": warnings,
        "infos": infos,
        "validation_results": payload.get("validation_results") or [],
        "problem_patterns": payload.get("problem_patterns") or [],
        "step_timings": payload.get("step_timings") or [],
        "total_duration_millis": payload.get("total_duration_millis"),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "info_count": len(infos),
    }
    message = str(payload.get("message") or "").strip()
    if message:
        section["message"] = message
    return section


def _build_validation_report(
    standard: str,
    validation: Dict[str, Any],
    *,
    minimum_viable_applied: bool = False,
    validation_scope: str = "local",
) -> Dict[str, Any]:
    validation = dict(validation or {})
    details = validation.get("details") if isinstance(validation.get("details"), dict) else {}

    if standard == "edm":
        sections = [
            _build_validation_section("basic", "Basic XML", details.get("basic")),
            _build_validation_section("xsd", "XSD", details.get("xsd")),
            _build_validation_section("schematron", "Schematron", details.get("schematron")),
            _build_validation_section("business", "Business Rules", details.get("business")),
        ]
        if details.get("remote") is not None:
            sections.append(_build_validation_section("remote", "Local EDM Validator", details.get("remote")))
    else:
        sections = [
            _build_validation_section(
                standard,
                standard.upper(),
                {
                    "valid": validation.get("valid", True),
                    "errors": validation.get("errors", []),
                    "warnings": validation.get("warnings", []),
                },
            )
        ]

    validation["sections"] = sections
    validation["summary"] = {
        "standard": standard.upper(),
        "valid": validation.get("valid", True),
        "error_count": len(validation.get("errors") or []),
        "warning_count": len(validation.get("warnings") or []),
        "minimum_viable_applied": minimum_viable_applied,
        "validation_scope": validation_scope,
    }
    return validation


CORE_TOOLS_ENDPOINTS = {"tools.tools_context", "tools.hpc_diagnostics"}
NATIVE_INSTALLER_ENDPOINTS = {
    "tools.validate_hdp_component_install",
    "tools.list_hdp_component_catalog",
    "tools.hdp_component_catalog_diagnostics",
    "tools.install_hdp_component",
    "tools.list_hdp_component_installations",
    "tools.get_hdp_component_installation",
    "tools.test_hdp_component_installation",
}
NATIVE_TOOLS_FEATURES = {"native_playground", "pipeline_constructor", "hdp_component_installer"}


@tools_bp.before_request
def enforce_core_tools_profile():
    if not core_workflow_only() or request.endpoint in CORE_TOOLS_ENDPOINTS:
        return None
    if native_tools_enabled() and request.endpoint in NATIVE_INSTALLER_ENDPOINTS:
        return None
    return APIResponse.error("FEATURE_DISABLED", "This optional tool is disabled in the core workflow profile.", 403)


@tools_bp.after_request
def filter_core_tools_context(response):
    if core_workflow_only() and request.endpoint == "tools.tools_context" and response.status_code == 200:
        payload = response.get_json()
        data = payload.get("data", {})
        data["core_only"] = True
        allowed = {"hpc_diagnostics"}
        if native_tools_enabled():
            allowed.update(NATIVE_TOOLS_FEATURES)
        for key, feature in data.get("features", {}).items():
            if key not in allowed and feature["enabled"]:
                feature.update(enabled=False, reason="Disabled in the core workflow profile")
        response.set_data(json.dumps(payload))
    return response


@tools_bp.route("/context", methods=["GET"])
@jwt_required()
def tools_context():
    try:
        user_id = get_jwt_identity()
        user = None
        if user_id is not None:
            try:
                user = db.session.get(User, int(user_id))
            except Exception:
                try:
                    user = UserService().get_by_id(int(user_id))
                except Exception:
                    user = None
        role = getattr(user, "role", None)
        role_value = getattr(role, "value", role) or "user"
        capabilities = list(getattr(user, "capabilities", []) or [])
        is_admin = role_value == "admin"
        is_moderator = role_value == "moderator"
        is_moderator_or_admin = role_value in {"moderator", "admin"}
        is_pipeline_author = can_author_pipelines(user)
        storage_mode = CloudUploadService.get_storage_mode()
        local_admin_enabled = bool(is_admin and storage_mode == STORAGE_MODE_LOCAL)
        from services.hdp_component_policy import (
            component_runtime_report,
            webhdp_deployment_class,
            webhdp_deployment_label,
        )
        hpc_link_available = False
        can_allocate_hpc = False
        active_hpc_allocation = False
        hpc_config = None
        try:
            hpc_service = current_app.hpc_allocation_service
            hpc_config = hpc_service.get_or_create_config()
            hpc_link_available = bool(hpc_config.enabled and hpc_config.base_url)
            can_allocate_hpc = bool(user and hpc_service.user_can_allocate(user, purpose="workflow"))
            session_id = request.args.get("session_id")
            if session_id not in (None, ""):
                from services.session_access_service import can_view_session

                session = db.session.get(DBSession, int(session_id))
                active_hpc_allocation = bool(session and can_view_session(session, user)
                                             and hpc_service.get_active_for_session(session.id, user_id=user.id))
        except Exception:
            hpc_link_available = False
            can_allocate_hpc = False
            active_hpc_allocation = False

        input_root = (
            current_app.project_service._translate_path(_resolve_local_input_root(), to_container=True)
            if local_admin_enabled else ""
        )
        msf_files = _list_local_msf_files(input_root) if local_admin_enabled else []

        return APIResponse.success(
            data={
                "is_admin": is_admin,
                "is_moderator": is_moderator,
                "is_moderator_or_admin": is_moderator_or_admin,
                "capabilities": capabilities,
                "storage_mode": storage_mode,
                "local_admin_enabled": local_admin_enabled,
                "input_root": input_root,
                "msf_files": msf_files,
                "deployment_class": webhdp_deployment_class(current_app),
                "deployment_label": webhdp_deployment_label(current_app),
                "hpc_link_available": hpc_link_available,
                "can_allocate_hpc": can_allocate_hpc,
                "active_hpc_allocation": active_hpc_allocation,
                "hpc_link_configured": bool(getattr(hpc_config, "base_url", None)) if hpc_config is not None else False,
                "component_runtime": component_runtime_report(
                    current_app,
                    active_hpc_allocation=active_hpc_allocation,
                    hpc_link_available=hpc_link_available,
                    can_allocate_hpc=can_allocate_hpc,
                ),
                "metadata_workflow": get_metadata_workflow_contract(),
                "pipeline_platform": get_pipeline_platform_contract(),
                "features": {
                    "pipeline_preflight": {
                        "enabled": local_admin_enabled,
                        "reason": "Requires admin and local mode",
                    },
                    "native_playground": {
                        "enabled": True,
                        "reason": "Requires authentication",
                    },
                    "pipeline_constructor": {
                        "enabled": is_pipeline_author,
                        "reason": "Requires admin or native_pipeline_author capability",
                    },
                    "msf_reference_repair": {
                        "enabled": local_admin_enabled,
                        "reason": "Requires admin and local mode",
                    },
                    "metadata_normalizer": {
                        "enabled": local_admin_enabled,
                        "reason": "Requires admin and local mode",
                    },
                    "output_preview_qa": {
                        "enabled": local_admin_enabled,
                        "reason": "Requires admin and local mode",
                    },
                    "hpc_diagnostics": {
                        "enabled": is_admin,
                        "reason": "Requires admin",
                    },
                    "hdp_component_installer": {
                        "enabled": is_admin,
                        "reason": "Requires admin",
                    },
                    "session_cleanup": {
                        "enabled": is_admin,
                        "reason": "Requires admin",
                    },
                    "zenodo_batch_operations": {
                        "enabled": is_moderator_or_admin,
                        "reason": "Requires moderator or admin",
                    },
                    "zenodo_account_retrieval": {
                        "enabled": True,
                        "reason": "Requires authentication and an accessible Zenodo credential",
                    },
                    "zenodo_oai_harvest": {
                        "enabled": True,
                        "reason": "Requires authentication",
                    },
                    "community_moderation": {
                        "enabled": is_moderator_or_admin,
                        "reason": "Requires moderator or admin",
                    },
                    "community_migration": {
                        "enabled": is_moderator_or_admin,
                        "reason": "Requires moderator or admin",
                    },
                },
            }
        )
    except Exception as exc:
        logger.error("Failed to load tools context: %s", exc, exc_info=True)
        return APIResponse.server_error(f"Failed to load tools context: {exc}")


def _current_tools_user() -> User:
    user_id = get_jwt_identity()
    if user_id is None:
        from exceptions import SecurityError

        raise SecurityError("Authentication required")
    user = db.session.get(User, int(user_id))
    if user is None:
        from exceptions import ResourceNotFoundError

        raise ResourceNotFoundError("User not found")
    return user


def _ensure_retrieval_entry_access(entry: dict[str, Any] | None, user: User) -> dict[str, Any]:
    if not isinstance(entry, dict):
        from exceptions import ResourceNotFoundError

        raise ResourceNotFoundError("Zenodo account retrieval job not found")
    requested_by = entry.get("requested_by") if isinstance(entry.get("requested_by"), dict) else {}
    role = getattr(user, "role", None)
    role_value = getattr(role, "value", role) or "user"
    if int(requested_by.get("user_id") or 0) != int(user.id) and role_value != "admin":
        from exceptions import SecurityError

        raise SecurityError("You do not have access to this retrieval job")
    return entry


def _retrieval_credential_summary(credential, user: User) -> dict[str, Any]:
    owner_relation = "unknown"
    if credential.owner_type == "user" and int(credential.owner_id) == int(user.id):
        owner_relation = "owned_by_requesting_user"
    elif credential.owner_type == "user":
        owner_relation = "shared_to_requesting_user"
    elif credential.owner_type == "institution":
        owner_relation = "institution"
    return {
        "credential_id": int(credential.id),
        "name": credential.name,
        "environment": credential.environment,
        "owner_type": credential.owner_type,
        "owner_id": int(credential.owner_id) if credential.owner_id is not None else None,
        "relation": owner_relation,
        "masked_preview": credential.masked_preview,
        "validation_status": credential.validation_status,
    }


def _public_retrieval_entry(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    return publicize_retrieval_entry(entry)


def _parse_retrieval_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _build_collection_coverage(collections: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = []
    for collection in collections:
        if not isinstance(collection, dict):
            continue
        earliest_value = collection.get("earliest_created") or collection.get("earliest_datestamp")
        latest_value = collection.get("latest_created") or collection.get("latest_modified") or collection.get("latest_datestamp")
        earliest = _parse_retrieval_dt(earliest_value)
        latest = _parse_retrieval_dt(latest_value)
        normalized.append(
            {
                **collection,
                "retrieval_id": collection.get("retrieval_id") or collection.get("harvest_id"),
                "earliest_created": earliest_value,
                "latest_created": latest_value,
                "_earliest_dt": earliest,
                "_latest_dt": latest,
            }
        )
    normalized.sort(key=lambda item: item.get("_earliest_dt") or datetime.max.replace(tzinfo=timezone.utc))
    gaps: list[dict[str, Any]] = []
    overlaps: list[dict[str, Any]] = []
    previous = None
    for collection in normalized:
        if previous and previous.get("_latest_dt") and collection.get("_earliest_dt"):
            if previous["_latest_dt"] < collection["_earliest_dt"]:
                gaps.append(
                    {
                        "after_retrieval_id": previous.get("retrieval_id"),
                        "before_retrieval_id": collection.get("retrieval_id"),
                        "start": previous["_latest_dt"].isoformat().replace("+00:00", "Z"),
                        "end": collection["_earliest_dt"].isoformat().replace("+00:00", "Z"),
                    }
                )
            elif previous["_latest_dt"] >= collection["_earliest_dt"]:
                overlaps.append(
                    {
                        "left_retrieval_id": previous.get("retrieval_id"),
                        "right_retrieval_id": collection.get("retrieval_id"),
                        "start": collection["_earliest_dt"].isoformat().replace("+00:00", "Z"),
                        "end": previous["_latest_dt"].isoformat().replace("+00:00", "Z"),
                    }
                )
        previous = collection
    timeline = [{key: value for key, value in item.items() if not key.startswith("_")} for item in normalized]
    earliest = next((item.get("earliest_created") for item in timeline if item.get("earliest_created")), None)
    latest = None
    for item in reversed(timeline):
        latest = item.get("latest_created") or item.get("latest_modified")
        if latest:
            break
    return {
        "timeline": timeline,
        "gaps": gaps,
        "overlaps": overlaps,
        "earliest_created": earliest,
        "latest_created": latest,
        "collection_count": len(timeline),
    }


def _shift_datetime(value: str, *, hours: int) -> str:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    shifted = parsed.astimezone(timezone.utc) + timedelta(hours=hours)
    return shifted.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _next_schedule_run(frequency: str) -> str:
    now = datetime.utcnow().replace(microsecond=0)
    normalized = str(frequency or "").lower()
    if normalized == "weekly":
        delta = timedelta(days=7)
    elif normalized == "monthly":
        delta = timedelta(days=30)
    else:
        delta = timedelta(days=1)
    return (now + delta).isoformat() + "Z"


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int, field_name: str) -> int:
    if value in (None, ""):
        return default
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    return max(minimum, min(normalized, maximum))


def _bounded_float(value: Any, *, default: float, minimum: float, maximum: float, field_name: str) -> float:
    if value in (None, ""):
        return default
    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc
    return max(minimum, min(normalized, maximum))


def _normalize_retrieval_mode(value: Any, *, sync_mode: str, start_datetime: str | None, end_datetime: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if sync_mode == "incremental":
        return "incremental"
    if normalized in {"full", "historical_backfill"}:
        return normalized
    if end_datetime and not start_datetime:
        return "historical_backfill"
    return "full"


def _runtime_options_from_payload(payload: dict[str, Any], *, execution_target: str) -> dict[str, Any]:
    return {
        "execution_target": execution_target,
        "initial_window_days": _bounded_int(
            payload.get("initial_window_days"),
            default=31,
            minimum=1,
            maximum=366,
            field_name="initial_window_days",
        ),
        "request_retries": _bounded_int(
            payload.get("request_retries"),
            default=2,
            minimum=0,
            maximum=10,
            field_name="request_retries",
        ),
        "request_timeout_seconds": _bounded_float(
            payload.get("request_timeout_seconds"),
            default=30.0,
            minimum=5.0,
            maximum=180.0,
            field_name="request_timeout_seconds",
        ),
        "output_root": str(payload.get("output_root") or "").strip()[:500] or None,
        "source_retrieval_id": str(payload.get("source_retrieval_id") or "").strip()[:120] or None,
        "source_tree": str(payload.get("source_tree") or "").strip()[:500] or None,
        "proxy_policy": "unset_no_proxy_on_hpc" if execution_target == "hpc_link" else "inherit_worker_environment",
    }


def _matching_collections_for_credential(*, credential_id: int, environment: str, user_id: int) -> list[dict[str, Any]]:
    collections: list[dict[str, Any]] = []
    for entry in list_retrieval_entries(limit=50, user_id=user_id):
        if int(entry.get("credential_id") or 0) != int(credential_id):
            continue
        if str(entry.get("environment") or "").lower() != str(environment or "").lower():
            continue
        public = _public_retrieval_entry(entry) or {}
        collection = public.get("collection") if isinstance(public.get("collection"), dict) else {}
        if collection:
            collections.append(collection)
    return collections


def _build_retrieval_preflight_report(
    *,
    user: User,
    credential,
    start_datetime: str | None,
    end_datetime: str | None,
    retrieval_mode: str,
    sync_mode: str,
    execution_target: str,
    runtime_options: dict[str, Any],
) -> dict[str, Any]:
    environment = normalize_environment(credential.environment)
    collections = _matching_collections_for_credential(
        credential_id=int(credential.id),
        environment=environment,
        user_id=int(user.id),
    )
    latest_collection = collections[0] if collections else None
    warnings: list[str] = []
    checks = [
        {
            "key": "credential_access",
            "status": "pass",
            "label": "Credential is accessible to the requesting user",
        },
        {
            "key": "token_handling",
            "status": "pass",
            "label": "Token is decrypted only in the worker context and kept out of shard output",
        },
    ]
    if execution_target == "hpc_link":
        warnings.append("Draco execution requires NO_PROXY/no_proxy to remain unset for Zenodo access.")
        checks.append(
            {
                "key": "hpc_proxy_policy",
                "status": "warn",
                "label": "Unset NO_PROXY/no_proxy on Draco before contacting Zenodo",
            }
        )
    else:
        checks.append(
            {
                "key": "worker_proxy_policy",
                "status": "info",
                "label": "Local/Celery worker proxy environment will be inherited",
            }
        )
    if retrieval_mode == "historical_backfill":
        if not end_datetime:
            warnings.append("Historical backfill should normally define a created-before/end datetime.")
        if latest_collection:
            warnings.append("This backfill will create a separate shard tree/collection and may overlap existing inventory.")
    if sync_mode == "incremental" and not latest_collection:
        warnings.append("No previous successful matching collection was found for incremental mode.")
    coverage = {
        "matching_collection_count": len(collections),
        "latest_collection": latest_collection,
        "requested_window": {"start": start_datetime, "end": end_datetime},
        "mode": retrieval_mode,
    }
    if latest_collection:
        coverage["latest_known_created"] = latest_collection.get("latest_created")
        coverage["earliest_known_created"] = latest_collection.get("earliest_created")
        if retrieval_mode == "historical_backfill" and end_datetime:
            coverage["relationship_to_latest_collection"] = "backfill_before_or_within_existing_inventory"
    return {
        "ok": execution_target == "celery_local",
        "queueable": execution_target == "celery_local",
        "retrieval_mode": retrieval_mode,
        "sync_mode": sync_mode,
        "execution_target": execution_target,
        "environment": environment,
        "credential": _retrieval_credential_summary(credential, user),
        "date_window": {"start": start_datetime, "end": end_datetime},
        "runtime_options": runtime_options,
        "coverage": coverage,
        "checks": checks,
        "warnings": warnings,
        "operator_notes": [
            "Dense windows, duplicate skips, rate-limit waits, and ETA movement are expected during large account inventories.",
            "Completed shard trees should be reused for curation queries instead of retrieving from Zenodo again.",
        ],
    }


def _mark_retrieval_queued_unless_finished(retrieval_id: str, *, task_id: str | None, status: str) -> dict[str, Any]:
    current_entry = get_retrieval_entry(retrieval_id) or {}
    current_state = str(current_entry.get("state") or "").upper()
    if current_state in {"SUCCESS", "FAILURE", "CANCELLED"}:
        if task_id and current_entry.get("task_id") != task_id:
            current_entry = update_retrieval_entry(retrieval_id, task_id=task_id)
        return current_entry
    return update_retrieval_entry(retrieval_id, task_id=task_id, state="PENDING", status=status)


@tools_bp.route("/zenodo-account-retrieval/context", methods=["GET"])
@jwt_required()
def zenodo_account_retrieval_context():
    try:
        user = _current_tools_user()
        available = credential_service.list_available_credentials(int(user.id))
        credentials = [
            item
            for item in (available.get("credentials") or [])
            if isinstance(item, dict) and item.get("id") and item.get("environment") in {"sandbox", "production"}
        ]
        recent_collections = [
            (_public_retrieval_entry(entry) or {}).get("collection")
            for entry in list_retrieval_entries(limit=20, user_id=int(user.id))
            if str(entry.get("state") or "").upper() == "SUCCESS"
        ]
        recent_collections = [item for item in recent_collections if isinstance(item, dict)]
        return APIResponse.success(
            data={
                "credentials": credentials,
                "active": available.get("active") or {},
                "recent_collections": recent_collections,
                "coverage": _build_collection_coverage(recent_collections),
                "detectors": list(DETECTOR_PRESETS.values()),
                "defaults": {
                    "scope": "published_and_drafts",
                    "storage_strategy": "manifest_plus_shards",
                    "retrieval_mode": "full",
                    "execution_target": "celery_local",
                    "shard_record_limit": 5000,
                    "max_records": None,
                    "max_records_ceiling": MAX_RECORDS_CEILING,
                    "start_datetime": None,
                    "end_datetime": None,
                    "initial_window_days": 31,
                    "request_retries": 2,
                    "request_timeout_seconds": 30,
                    "incremental_overlap_hours": 24,
                    "compaction_target_records": 5000,
                },
                "execution_targets": [
                    {
                        "id": "celery_local",
                        "label": "WebHDP worker",
                        "queueable": True,
                    },
                    {
                        "id": "hpc_link",
                        "label": "Draco / HPC shard tree",
                        "queueable": False,
                        "note": "Preflight only here; Draco launches must unset NO_PROXY/no_proxy.",
                    },
                ],
                "rate_limit": {
                    "max_requests_per_minute": 30,
                    "page_size": 100,
                },
            }
        )
    except Exception as exc:
        logger.error("Failed to load Zenodo account retrieval context: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to load Zenodo account retrieval context")


@tools_bp.route("/zenodo-account-retrieval/coverage", methods=["GET"])
@jwt_required()
def zenodo_account_retrieval_coverage():
    try:
        user = _current_tools_user()
        credential_id = request.args.get("credential_id", type=int)
        environment = str(request.args.get("environment") or "").strip().lower()
        role = getattr(user, "role", None)
        role_value = getattr(role, "value", role) or "user"
        user_filter = None if role_value == "admin" and request.args.get("all") in {"1", "true"} else int(user.id)
        collections: list[dict[str, Any]] = []
        for entry in list_retrieval_entries(limit=50, user_id=user_filter):
            if str(entry.get("state") or "").upper() != "SUCCESS":
                continue
            if credential_id and int(entry.get("credential_id") or 0) != int(credential_id):
                continue
            if environment and str(entry.get("environment") or "").lower() != environment:
                continue
            public = _public_retrieval_entry(entry) or {}
            collection = public.get("collection") if isinstance(public.get("collection"), dict) else {}
            if collection:
                collections.append(collection)
        return APIResponse.success(data={"coverage": _build_collection_coverage(collections)})
    except Exception as exc:
        logger.error("Failed to build Zenodo retrieval coverage: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to build Zenodo retrieval coverage")


@tools_bp.route("/zenodo-account-retrieval/preflight", methods=["POST"])
@jwt_required()
def preflight_zenodo_account_retrieval():
    try:
        user = _current_tools_user()
        payload = request.get_json(silent=True) or {}
        credential_id = payload.get("credential_id")
        if credential_id in (None, ""):
            return APIResponse.validation_error("credential_id is required")
        try:
            start_datetime = normalize_retrieval_datetime(payload.get("start_datetime") or payload.get("start_date"))
            end_datetime = normalize_retrieval_datetime(payload.get("end_datetime") or payload.get("end_date"), is_end=True)
            if start_datetime and end_datetime and start_datetime > end_datetime:
                return APIResponse.validation_error("start_datetime must be before end_datetime")
            execution_target = str(payload.get("execution_target") or "celery_local").strip().lower()
            if execution_target not in {"celery_local", "hpc_link"}:
                return APIResponse.validation_error("execution_target must be celery_local or hpc_link")
            runtime_options = _runtime_options_from_payload(payload, execution_target=execution_target)
        except (TypeError, ValueError) as exc:
            return APIResponse.validation_error(str(exc))
        credential = credential_service.require_credential_by_id(int(credential_id))
        credential_service._ensure_accessible_by_user(credential, int(user.id))
        sync_mode = "incremental" if payload.get("incremental") or payload.get("sync_mode") == "incremental" else "full"
        retrieval_mode = _normalize_retrieval_mode(
            payload.get("retrieval_mode"),
            sync_mode=sync_mode,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
        )
        report = _build_retrieval_preflight_report(
            user=user,
            credential=credential,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            retrieval_mode=retrieval_mode,
            sync_mode=sync_mode,
            execution_target=execution_target,
            runtime_options=runtime_options,
        )
        return APIResponse.success(data={"preflight": report})
    except Exception as exc:
        logger.error("Failed to preflight Zenodo account retrieval: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to preflight Zenodo account retrieval")


@tools_bp.route("/zenodo-account-retrieval/jobs", methods=["POST"])
@jwt_required()
def start_zenodo_account_retrieval():
    try:
        user = _current_tools_user()
        payload = request.get_json(silent=True) or {}
        credential_id = payload.get("credential_id")
        if credential_id in (None, ""):
            return APIResponse.validation_error("credential_id is required")
        try:
            max_records = normalize_max_records(payload.get("max_records"))
            start_datetime = normalize_retrieval_datetime(payload.get("start_datetime") or payload.get("start_date"))
            end_datetime = normalize_retrieval_datetime(payload.get("end_datetime") or payload.get("end_date"), is_end=True)
            if start_datetime and end_datetime and start_datetime > end_datetime:
                return APIResponse.validation_error("start_datetime must be before end_datetime")
            execution_target = str(payload.get("execution_target") or "celery_local").strip().lower()
            if execution_target not in {"celery_local", "hpc_link"}:
                return APIResponse.validation_error("execution_target must be celery_local or hpc_link")
            if execution_target != "celery_local":
                return APIResponse.validation_error("Only celery_local retrieval launch is supported from this UI; use preflight for Draco/HPC runs")
            runtime_options = _runtime_options_from_payload(payload, execution_target=execution_target)
        except (TypeError, ValueError) as exc:
            return APIResponse.validation_error(str(exc))
        credential = credential_service.require_credential_by_id(int(credential_id))
        credential_service._ensure_accessible_by_user(credential, int(user.id))
        environment = normalize_environment(credential.environment)
        sync_mode = "incremental" if payload.get("incremental") or payload.get("sync_mode") == "incremental" else "full"
        retrieval_mode = _normalize_retrieval_mode(
            payload.get("retrieval_mode"),
            sync_mode=sync_mode,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
        )
        parent_retrieval_id = None
        incremental_since = None
        overlap_hours = None
        if sync_mode == "incremental":
            try:
                overlap_hours = max(0, min(int(payload.get("incremental_overlap_hours", 24)), 168))
            except (TypeError, ValueError):
                return APIResponse.validation_error("incremental_overlap_hours must be an integer from 0 to 168")
            parent = None
            requested_parent_id = str(payload.get("parent_retrieval_id") or "").strip()
            if requested_parent_id:
                parent = _ensure_retrieval_entry_access(get_retrieval_entry(requested_parent_id), user)
                if int(parent.get("credential_id") or 0) != int(credential.id) or str(parent.get("environment") or "").lower() != environment:
                    return APIResponse.validation_error("parent_retrieval_id must use the same credential and environment")
            else:
                parent = find_latest_successful_collection(credential_id=int(credential.id), environment=environment, user_id=int(user.id))
            if not parent:
                return APIResponse.validation_error("No previous successful retrieval collection exists for incremental retrieval")
            parent_collection = (parent.get("collection") or {})
            parent_retrieval_id = str(parent.get("retrieval_id") or "")
            latest = parent_collection.get("latest_created") or parent_collection.get("latest_modified")
            if not latest:
                return APIResponse.validation_error("Previous retrieval has no latest record timestamp for incremental retrieval")
            incremental_since = latest
            calculated_start = _shift_datetime(latest, hours=-overlap_hours)
            if not start_datetime or calculated_start > start_datetime:
                start_datetime = calculated_start
        preflight_report = _build_retrieval_preflight_report(
            user=user,
            credential=credential,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            retrieval_mode=retrieval_mode,
            sync_mode=sync_mode,
            execution_target=execution_target,
            runtime_options=runtime_options,
        )
        retrieval_id = new_retrieval_id()
        record_retrieval_launch(
            retrieval_id=retrieval_id,
            task_id=None,
            credential_id=int(credential.id),
            environment=environment,
            requested_by_user_id=int(user.id),
            requested_by_email=user.email,
            credential_summary=_retrieval_credential_summary(credential, user),
            max_records=max_records,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            sync_mode=sync_mode,
            parent_retrieval_id=parent_retrieval_id,
            incremental_since=incremental_since,
            incremental_overlap_hours=overlap_hours,
            retrieval_mode=retrieval_mode,
            execution_target=execution_target,
            runtime_options=runtime_options,
            preflight_report=preflight_report,
        )
        from tasks import execute_zenodo_account_retrieval

        task = execute_zenodo_account_retrieval.delay(
            retrieval_id=retrieval_id,
            credential_id=int(credential.id),
            requester_user_id=int(user.id),
        )
        _mark_retrieval_queued_unless_finished(
            retrieval_id,
            task_id=getattr(task, "id", None),
            status="Queued Zenodo account retrieval",
        )
        return APIResponse.accepted(
            data={
                "retrieval_id": retrieval_id,
                "task_id": getattr(task, "id", None),
                "credential": _retrieval_credential_summary(credential, user),
                "environment": environment,
                "max_records": max_records,
                "date_window": {"start": start_datetime, "end": end_datetime},
                "retrieval_mode": retrieval_mode,
                "sync_mode": sync_mode,
                "execution_target": execution_target,
                "parent_retrieval_id": parent_retrieval_id,
                "incremental_since": incremental_since,
                "incremental_overlap_hours": overlap_hours,
                "preflight": preflight_report,
            },
            message="Zenodo account retrieval queued",
        )
    except Exception as exc:
        logger.error("Failed to queue Zenodo account retrieval: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to queue Zenodo account retrieval")


@tools_bp.route("/zenodo-account-retrieval/jobs", methods=["GET"])
@jwt_required()
def list_zenodo_account_retrieval_jobs():
    try:
        user = _current_tools_user()
        role = getattr(user, "role", None)
        role_value = getattr(role, "value", role) or "user"
        limit = max(1, min(request.args.get("limit", default=20, type=int) or 20, 50))
        user_filter = None if role_value == "admin" and request.args.get("all") in {"1", "true"} else int(user.id)
        return APIResponse.success(data={"jobs": [_public_retrieval_entry(entry) for entry in list_retrieval_entries(limit=limit, user_id=user_filter)]})
    except Exception as exc:
        logger.error("Failed to list Zenodo account retrieval jobs: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to list Zenodo account retrieval jobs")


@tools_bp.route("/zenodo-account-retrieval/jobs/<retrieval_id>", methods=["GET"])
@jwt_required()
def get_zenodo_account_retrieval_job(retrieval_id):
    try:
        user = _current_tools_user()
        entry = _ensure_retrieval_entry_access(get_retrieval_entry(retrieval_id), user)
        public = _public_retrieval_entry(entry) or {}
        public["diagnostics"] = build_retrieval_diagnostics(public)
        return APIResponse.success(data=public)
    except Exception as exc:
        logger.error("Failed to load Zenodo account retrieval job %s: %s", retrieval_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to load Zenodo account retrieval job")


@tools_bp.route("/zenodo-account-retrieval/jobs/<retrieval_id>/diagnostics", methods=["GET"])
@jwt_required()
def get_zenodo_account_retrieval_diagnostics(retrieval_id):
    try:
        user = _current_tools_user()
        entry = _public_retrieval_entry(_ensure_retrieval_entry_access(get_retrieval_entry(retrieval_id), user)) or {}
        return APIResponse.success(data={"diagnostics": build_retrieval_diagnostics(entry)})
    except Exception as exc:
        logger.error("Failed to load Zenodo retrieval diagnostics %s: %s", retrieval_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to load Zenodo retrieval diagnostics")


@tools_bp.route("/zenodo-account-retrieval/jobs/<retrieval_id>/pause", methods=["POST"])
@jwt_required()
def pause_zenodo_account_retrieval_job(retrieval_id):
    try:
        user = _current_tools_user()
        _ensure_retrieval_entry_access(get_retrieval_entry(retrieval_id), user)
        entry = request_zenodo_retrieval_pause(retrieval_id)
        return APIResponse.success(data=_public_retrieval_entry(entry), message="Pause requested")
    except Exception as exc:
        logger.error("Failed to pause Zenodo account retrieval job %s: %s", retrieval_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to pause Zenodo account retrieval job")


@tools_bp.route("/zenodo-account-retrieval/jobs/<retrieval_id>/resume", methods=["POST"])
@jwt_required()
def resume_zenodo_account_retrieval_job(retrieval_id):
    try:
        user = _current_tools_user()
        entry = _ensure_retrieval_entry_access(get_retrieval_entry(retrieval_id), user)
        credential_id = int(entry.get("credential_id") or 0)
        if not credential_id:
            return APIResponse.validation_error("Retrieval job has no credential reference")
        credential = credential_service.require_credential_by_id(credential_id)
        credential_service._ensure_accessible_by_user(credential, int(user.id))
        clear_zenodo_retrieval_pause(retrieval_id)
        update_retrieval_entry(retrieval_id, state="PENDING", status="Queued Zenodo account retrieval resume", control={"cancel_requested": False})
        from tasks import execute_zenodo_account_retrieval

        task = execute_zenodo_account_retrieval.delay(
            retrieval_id=retrieval_id,
            credential_id=credential_id,
            requester_user_id=int(user.id),
        )
        entry = _mark_retrieval_queued_unless_finished(
            retrieval_id,
            task_id=getattr(task, "id", None),
            status="Queued Zenodo account retrieval resume",
        )
        return APIResponse.accepted(data=_public_retrieval_entry(entry), message="Zenodo account retrieval resumed")
    except Exception as exc:
        logger.error("Failed to resume Zenodo account retrieval job %s: %s", retrieval_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to resume Zenodo account retrieval job")


@tools_bp.route("/zenodo-account-retrieval/jobs/<retrieval_id>/cancel", methods=["POST"])
@jwt_required()
def cancel_zenodo_account_retrieval_job(retrieval_id):
    try:
        user = _current_tools_user()
        _ensure_retrieval_entry_access(get_retrieval_entry(retrieval_id), user)
        entry = request_zenodo_retrieval_cancel(retrieval_id)
        return APIResponse.success(data=_public_retrieval_entry(entry), message="Cancel requested")
    except Exception as exc:
        logger.error("Failed to cancel Zenodo account retrieval job %s: %s", retrieval_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to cancel Zenodo account retrieval job")


@tools_bp.route("/zenodo-account-retrieval/jobs/<retrieval_id>", methods=["DELETE"])
@jwt_required()
def delete_zenodo_account_retrieval_job(retrieval_id):
    try:
        user = _current_tools_user()
        entry = _ensure_retrieval_entry_access(get_retrieval_entry(retrieval_id), user)
        deleted = delete_retrieval_shards(entry)
        delete_retrieval_entry(retrieval_id)
        return APIResponse.success(data={"retrieval_id": retrieval_id, **deleted}, message="Zenodo retrieval files deleted")
    except Exception as exc:
        logger.error("Failed to delete Zenodo account retrieval job %s: %s", retrieval_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to delete Zenodo account retrieval job")


@tools_bp.route("/zenodo-account-retrieval/jobs/<retrieval_id>/records", methods=["GET"])
@jwt_required()
def search_zenodo_account_retrieval_records(retrieval_id):
    try:
        user = _current_tools_user()
        entry = _ensure_retrieval_entry_access(get_retrieval_entry(retrieval_id), user)
        result = search_retrieval_collection(
            entry,
            query=request.args.get("q"),
            status=request.args.get("status"),
            edit_capability=request.args.get("capability"),
            limit=request.args.get("limit", default=100, type=int) or 100,
            offset=request.args.get("offset", default=0, type=int) or 0,
        )
        return APIResponse.success(data=result)
    except Exception as exc:
        logger.error("Failed to search Zenodo account retrieval %s: %s", retrieval_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to search Zenodo account retrieval records")


@tools_bp.route("/zenodo-account-retrieval/jobs/<retrieval_id>/detectors", methods=["GET"])
@jwt_required()
def run_zenodo_account_retrieval_detector(retrieval_id):
    try:
        user = _current_tools_user()
        entry = _ensure_retrieval_entry_access(get_retrieval_entry(retrieval_id), user)
        detector_id = str(request.args.get("detector") or request.args.get("detector_id") or "community_migration_candidates")
        target_community = request.args.get("target_community") or "3dbigdataspace"
        result = run_retrieval_detector(
            entry,
            detector_id=detector_id,
            target_community=target_community,
            limit=request.args.get("limit", default=250, type=int) or 250,
            offset=request.args.get("offset", default=0, type=int) or 0,
        )
        return APIResponse.success(data=result)
    except ValueError as exc:
        return APIResponse.validation_error(str(exc))
    except Exception as exc:
        logger.error("Failed to run Zenodo retrieval detector %s: %s", retrieval_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to run Zenodo retrieval detector")


@tools_bp.route("/zenodo-account-retrieval/jobs/<retrieval_id>/detectors/export", methods=["GET"])
@jwt_required()
def export_zenodo_account_retrieval_detector(retrieval_id):
    try:
        user = _current_tools_user()
        entry = _ensure_retrieval_entry_access(get_retrieval_entry(retrieval_id), user)
        detector_id = str(request.args.get("detector") or request.args.get("detector_id") or "community_migration_candidates")
        target_community = request.args.get("target_community") or "3dbigdataspace"
        return Response(
            export_detector_candidates_csv(entry, detector_id=detector_id, target_community=target_community),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=zenodo-retrieval-{retrieval_id}-{detector_id}.csv"},
        )
    except ValueError as exc:
        return APIResponse.validation_error(str(exc))
    except Exception as exc:
        logger.error("Failed to export Zenodo retrieval detector %s: %s", retrieval_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to export Zenodo retrieval detector")


@tools_bp.route("/zenodo-account-retrieval/jobs/<retrieval_id>/compact", methods=["POST"])
@jwt_required()
def compact_zenodo_account_retrieval_job(retrieval_id):
    try:
        user = _current_tools_user()
        entry = _ensure_retrieval_entry_access(get_retrieval_entry(retrieval_id), user)
        payload = request.get_json(silent=True) or {}
        target = payload.get("target_records_per_shard") or 5000
        result = compact_retrieval_shards(entry, target_records_per_shard=int(target))
        updated = _public_retrieval_entry(get_retrieval_entry(retrieval_id))
        return APIResponse.success(data={"compaction": result, "job": updated}, message="Retrieval shards compacted")
    except Exception as exc:
        logger.error("Failed to compact Zenodo account retrieval %s: %s", retrieval_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to compact Zenodo account retrieval")


@tools_bp.route("/zenodo-account-retrieval/jobs/<retrieval_id>/compacted-shards", methods=["DELETE"])
@jwt_required()
def delete_zenodo_account_retrieval_compacted_shards(retrieval_id):
    try:
        user = _current_tools_user()
        entry = _ensure_retrieval_entry_access(get_retrieval_entry(retrieval_id), user)
        result = delete_compacted_retrieval_shards(entry)
        return APIResponse.success(data=result, message="Compacted retrieval shards deleted")
    except Exception as exc:
        logger.error("Failed to delete compacted Zenodo retrieval shards %s: %s", retrieval_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to delete compacted retrieval shards")


@tools_bp.route("/zenodo-account-retrieval/jobs/<retrieval_id>/retention", methods=["PATCH"])
@jwt_required()
def update_zenodo_account_retrieval_retention(retrieval_id):
    try:
        user = _current_tools_user()
        _ensure_retrieval_entry_access(get_retrieval_entry(retrieval_id), user)
        payload = request.get_json(silent=True) or {}
        retention = {
            "keep_original_shards": bool(payload.get("keep_original_shards", True)),
            "keep_compacted_shards": bool(payload.get("keep_compacted_shards", True)),
            "notes": str(payload.get("notes") or "")[:500],
            "updated_at": datetime.utcnow().isoformat(),
            "updated_by_user_id": int(user.id),
        }
        entry = update_retrieval_entry(retrieval_id, collection={"retention": retention})
        return APIResponse.success(data=_public_retrieval_entry(entry), message="Retrieval retention policy updated")
    except Exception as exc:
        logger.error("Failed to update Zenodo retrieval retention %s: %s", retrieval_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to update retrieval retention policy")


@tools_bp.route("/zenodo-account-retrieval/jobs/<retrieval_id>/schedule", methods=["PATCH"])
@jwt_required()
def update_zenodo_account_retrieval_schedule(retrieval_id):
    try:
        user = _current_tools_user()
        entry = _ensure_retrieval_entry_access(get_retrieval_entry(retrieval_id), user)
        if str(entry.get("state") or "").upper() != "SUCCESS":
            return APIResponse.validation_error("Only completed retrieval collections can be scheduled")
        payload = request.get_json(silent=True) or {}
        frequency = str(payload.get("frequency") or "weekly").lower()
        if frequency not in {"daily", "weekly", "monthly"}:
            return APIResponse.validation_error("frequency must be daily, weekly, or monthly")
        overlap_hours = max(0, min(int(payload.get("incremental_overlap_hours", 24)), 168))
        max_records = normalize_max_records(payload.get("max_records"))
        schedule = {
            "enabled": bool(payload.get("enabled", True)),
            "frequency": frequency,
            "incremental_overlap_hours": overlap_hours,
            "max_records": max_records,
            "next_run_at": _next_schedule_run(frequency),
            "updated_at": datetime.utcnow().isoformat(),
            "updated_by_user_id": int(user.id),
        }
        updated = update_retrieval_entry(retrieval_id, collection={"schedule": schedule})
        return APIResponse.success(data=_public_retrieval_entry(updated), message="Retrieval incremental schedule updated")
    except Exception as exc:
        logger.error("Failed to update Zenodo retrieval schedule %s: %s", retrieval_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to update retrieval incremental schedule")


@tools_bp.route("/zenodo-account-retrieval/jobs/<retrieval_id>/schedule/run-now", methods=["POST"])
@jwt_required()
def run_zenodo_account_retrieval_schedule_now(retrieval_id):
    try:
        user = _current_tools_user()
        parent = _ensure_retrieval_entry_access(get_retrieval_entry(retrieval_id), user)
        if str(parent.get("state") or "").upper() != "SUCCESS":
            return APIResponse.validation_error("Only completed retrieval collections can start an incremental sync")
        credential_id = int(parent.get("credential_id") or 0)
        credential = credential_service.require_credential_by_id(credential_id)
        credential_service._ensure_accessible_by_user(credential, int(user.id))
        collection = parent.get("collection") if isinstance(parent.get("collection"), dict) else {}
        latest = collection.get("latest_created") or collection.get("latest_modified")
        if not latest:
            return APIResponse.validation_error("Parent retrieval has no latest timestamp for incremental sync")
        schedule = collection.get("schedule") if isinstance(collection.get("schedule"), dict) else {}
        overlap_hours = max(0, min(int(schedule.get("incremental_overlap_hours", 24)), 168))
        start_datetime = _shift_datetime(latest, hours=-overlap_hours)
        max_records = normalize_max_records(schedule.get("max_records"))
        child_retrieval_id = new_retrieval_id()
        record_retrieval_launch(
            retrieval_id=child_retrieval_id,
            task_id=None,
            credential_id=credential_id,
            environment=normalize_environment(credential.environment),
            requested_by_user_id=int(user.id),
            requested_by_email=user.email,
            credential_summary=_retrieval_credential_summary(credential, user),
            max_records=max_records,
            start_datetime=start_datetime,
            end_datetime=None,
            sync_mode="incremental",
            parent_retrieval_id=str(parent.get("retrieval_id") or retrieval_id),
            incremental_since=latest,
            incremental_overlap_hours=overlap_hours,
        )
        from tasks import execute_zenodo_account_retrieval

        task = execute_zenodo_account_retrieval.delay(
            retrieval_id=child_retrieval_id,
            credential_id=credential_id,
            requester_user_id=int(user.id),
        )
        entry = _mark_retrieval_queued_unless_finished(
            child_retrieval_id,
            task_id=getattr(task, "id", None),
            status="Queued scheduled Zenodo incremental retrieval",
        )
        return APIResponse.accepted(data=_public_retrieval_entry(entry), message="Scheduled incremental retrieval queued")
    except Exception as exc:
        logger.error("Failed to run Zenodo retrieval schedule now %s: %s", retrieval_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to queue scheduled incremental retrieval")


@tools_bp.route("/zenodo-account-retrieval/jobs/<retrieval_id>/export/<export_format>", methods=["GET"])
@jwt_required()
def export_zenodo_account_retrieval(retrieval_id, export_format):
    try:
        user = _current_tools_user()
        entry = _ensure_retrieval_entry_access(get_retrieval_entry(retrieval_id), user)
        normalized = str(export_format or "").lower()
        if normalized == "manifest":
            return APIResponse.success(data=export_retrieval_manifest(_public_retrieval_entry(entry) or entry))
        if normalized == "csv":
            return Response(
                export_retrieval_records_csv(entry),
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment; filename=zenodo-retrieval-{retrieval_id}.csv"},
            )
        if normalized == "archive":
            archive_dir = os.path.join(current_app.instance_path, "retrieval_exports")
            os.makedirs(archive_dir, exist_ok=True)
            archive_path = os.path.join(archive_dir, f"zenodo-retrieval-{retrieval_id}.zip")
            build_retrieval_shard_archive(entry, archive_path)
            return send_file(archive_path, as_attachment=True, download_name=f"zenodo-retrieval-{retrieval_id}.zip")
        return APIResponse.validation_error("export_format must be one of manifest, csv, or archive")
    except Exception as exc:
        logger.error("Failed to export Zenodo account retrieval %s: %s", retrieval_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to export Zenodo account retrieval")


def _ensure_oai_harvest_entry_access(entry: dict[str, Any] | None, user: User) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ResourceNotFoundError("Zenodo OAI harvest job not found")
    role = getattr(user, "role", None)
    role_value = getattr(role, "value", role) or "user"
    if role_value == "admin":
        return entry
    requested_by = entry.get("requested_by") if isinstance(entry.get("requested_by"), dict) else {}
    if int(requested_by.get("user_id") or 0) != int(user.id):
        raise ResourceNotFoundError("Zenodo OAI harvest job not found")
    return entry


def _public_oai_harvest_entry(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    return publicize_harvest_entry(entry)


def _normalize_oai_harvest_mode(value: Any, *, sync_mode: str, from_datetime: str | None, until_datetime: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"full", "historical_backfill", "incremental"}:
        return normalized
    if sync_mode == "incremental":
        return "incremental"
    if from_datetime or until_datetime:
        return "historical_backfill"
    return "full"


def _mark_oai_harvest_queued_unless_finished(harvest_id: str, *, task_id: str | None, status: str) -> dict[str, Any]:
    current_entry = get_harvest_entry(harvest_id) or {}
    current_state = str(current_entry.get("state") or "").upper()
    if current_state in {"SUCCESS", "FAILURE", "CANCELLED"}:
        if task_id and current_entry.get("task_id") != task_id:
            current_entry = update_harvest_entry(harvest_id, task_id=task_id)
        return current_entry
    return update_harvest_entry(harvest_id, task_id=task_id, state="PENDING", status=status)


@tools_bp.route("/zenodo-oai-harvest/context", methods=["GET"])
@jwt_required()
def zenodo_oai_harvest_context():
    try:
        user = _current_tools_user()
        recent_collections = [
            (_public_oai_harvest_entry(entry) or {}).get("collection")
            for entry in list_harvest_entries(limit=20, user_id=int(user.id))
            if str(entry.get("state") or "").upper() == "SUCCESS"
        ]
        recent_collections = [item for item in recent_collections if isinstance(item, dict)]
        return APIResponse.success(
            data={
                "recent_collections": recent_collections,
                "coverage": _build_collection_coverage(recent_collections),
                "detectors": list(DETECTOR_PRESETS.values()),
                "defaults": {
                    "base_url": DEFAULT_OAI_BASE_URL,
                    "set_identifier": "3dbigdataspace",
                    "set_spec": DEFAULT_OAI_SET_SPEC,
                    "metadata_prefix": DEFAULT_OAI_METADATA_PREFIX,
                    "harvest_mode": "full",
                    "execution_target": "celery_local",
                    "max_records": None,
                    "max_records_ceiling": MAX_RECORDS_CEILING,
                    "from_datetime": None,
                    "until_datetime": None,
                    "request_retries": 2,
                    "request_timeout_seconds": 30,
                    "incremental_overlap_hours": 24,
                    "compaction_target_records": 5000,
                },
                "metadata_prefixes": [
                    {"id": "oai_datacite", "label": "OAI DataCite"},
                    {"id": "dcat", "label": "DCAT"},
                    {"id": "oai_dc", "label": "OAI Dublin Core"},
                ],
                "rate_limit": {"max_requests_per_minute": 30, "page_size": DEFAULT_OAI_PAGE_SIZE},
            }
        )
    except Exception as exc:
        logger.error("Failed to load Zenodo OAI harvest context: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to load Zenodo OAI harvest context")


@tools_bp.route("/zenodo-oai-harvest/preflight", methods=["POST"])
@jwt_required()
def preflight_zenodo_oai_harvest():
    try:
        _current_tools_user()
        payload = request.get_json(silent=True) or {}
        try:
            base_url = str(payload.get("base_url") or DEFAULT_OAI_BASE_URL).strip().rstrip("/")
            set_spec = normalize_oai_set_spec(payload.get("set_spec") or payload.get("set_identifier"))
            metadata_prefix = normalize_oai_metadata_prefix(payload.get("metadata_prefix"))
            from_datetime = normalize_oai_datetime(payload.get("from_datetime") or payload.get("from_date"))
            until_datetime = normalize_oai_datetime(payload.get("until_datetime") or payload.get("until_date"), is_end=True)
            if from_datetime and until_datetime and from_datetime > until_datetime:
                return APIResponse.validation_error("from_datetime must be before until_datetime")
        except (TypeError, ValueError) as exc:
            return APIResponse.validation_error(str(exc))
        report = build_oai_harvest_preflight(base_url=base_url, set_spec=set_spec, metadata_prefix=metadata_prefix)
        report["date_window"] = {"from": from_datetime, "until": until_datetime}
        return APIResponse.success(data={"preflight": report})
    except Exception as exc:
        logger.error("Failed to preflight Zenodo OAI harvest: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to preflight Zenodo OAI harvest")


@tools_bp.route("/zenodo-oai-harvest/jobs", methods=["POST"])
@jwt_required()
def start_zenodo_oai_harvest():
    try:
        user = _current_tools_user()
        payload = request.get_json(silent=True) or {}
        try:
            base_url = str(payload.get("base_url") or DEFAULT_OAI_BASE_URL).strip().rstrip("/")
            set_spec = normalize_oai_set_spec(payload.get("set_spec") or payload.get("set_identifier"))
            metadata_prefix = normalize_oai_metadata_prefix(payload.get("metadata_prefix"))
            max_records = normalize_oai_max_records(payload.get("max_records"))
            from_datetime = normalize_oai_datetime(payload.get("from_datetime") or payload.get("from_date"))
            until_datetime = normalize_oai_datetime(payload.get("until_datetime") or payload.get("until_date"), is_end=True)
            if from_datetime and until_datetime and from_datetime > until_datetime:
                return APIResponse.validation_error("from_datetime must be before until_datetime")
            execution_target = str(payload.get("execution_target") or "celery_local").strip().lower()
            if execution_target != "celery_local":
                return APIResponse.validation_error("Only celery_local OAI harvest launch is supported")
            request_retries = max(0, min(int(payload.get("request_retries", 2)), 10))
            request_timeout_seconds = max(1.0, min(float(payload.get("request_timeout_seconds", 30)), 300.0))
        except (TypeError, ValueError) as exc:
            return APIResponse.validation_error(str(exc))
        sync_mode = "incremental" if payload.get("incremental") or payload.get("sync_mode") == "incremental" else "full"
        harvest_mode = _normalize_oai_harvest_mode(payload.get("harvest_mode"), sync_mode=sync_mode, from_datetime=from_datetime, until_datetime=until_datetime)
        parent_harvest_id = None
        incremental_since = None
        overlap_hours = None
        if sync_mode == "incremental":
            try:
                overlap_hours = max(0, min(int(payload.get("incremental_overlap_hours", 24)), 168))
            except (TypeError, ValueError):
                return APIResponse.validation_error("incremental_overlap_hours must be an integer from 0 to 168")
            requested_parent_id = str(payload.get("parent_harvest_id") or "").strip()
            if requested_parent_id:
                parent = _ensure_oai_harvest_entry_access(get_harvest_entry(requested_parent_id), user)
            else:
                parent = find_latest_successful_harvest(base_url=base_url, set_spec=set_spec, metadata_prefix=metadata_prefix, user_id=int(user.id))
            if not parent:
                return APIResponse.validation_error("No previous successful OAI harvest collection exists for incremental sync")
            parent_collection = parent.get("collection") if isinstance(parent.get("collection"), dict) else {}
            parent_harvest_id = str(parent.get("harvest_id") or "")
            latest = parent_collection.get("latest_datestamp")
            if not latest:
                return APIResponse.validation_error("Previous OAI harvest has no latest datestamp for incremental sync")
            incremental_since = latest
            calculated_from = _shift_datetime(latest, hours=-overlap_hours)
            if not from_datetime or calculated_from > from_datetime:
                from_datetime = calculated_from
        preflight_report = {
            "ok": True,
            "queueable": True,
            "base_url": base_url,
            "set_spec": set_spec,
            "metadata_prefix": metadata_prefix,
            "date_window": {"from": from_datetime, "until": until_datetime},
            "rate_limit": {"max_requests_per_minute": 30, "page_size": DEFAULT_OAI_PAGE_SIZE},
        }
        harvest_id = new_harvest_id()
        record_harvest_launch(
            harvest_id=harvest_id,
            task_id=None,
            requested_by_user_id=int(user.id),
            requested_by_email=user.email,
            base_url=base_url,
            set_spec=set_spec,
            metadata_prefix=metadata_prefix,
            max_records=max_records,
            from_datetime=from_datetime,
            until_datetime=until_datetime,
            sync_mode=sync_mode,
            parent_harvest_id=parent_harvest_id,
            incremental_since=incremental_since,
            incremental_overlap_hours=overlap_hours,
            harvest_mode=harvest_mode,
            execution_target=execution_target,
            runtime_options={"request_retries": request_retries, "request_timeout_seconds": request_timeout_seconds},
            preflight_report=preflight_report,
        )
        from tasks import execute_zenodo_oai_harvest

        task = execute_zenodo_oai_harvest.delay(harvest_id=harvest_id, requester_user_id=int(user.id))
        _mark_oai_harvest_queued_unless_finished(harvest_id, task_id=getattr(task, "id", None), status="Queued Zenodo OAI harvest")
        return APIResponse.accepted(
            data={
                "harvest_id": harvest_id,
                "task_id": getattr(task, "id", None),
                "base_url": base_url,
                "set_spec": set_spec,
                "metadata_prefix": metadata_prefix,
                "max_records": max_records,
                "date_window": {"from": from_datetime, "until": until_datetime},
                "harvest_mode": harvest_mode,
                "sync_mode": sync_mode,
                "execution_target": execution_target,
                "parent_harvest_id": parent_harvest_id,
                "incremental_since": incremental_since,
                "incremental_overlap_hours": overlap_hours,
                "preflight": preflight_report,
            },
            message="Zenodo OAI harvest queued",
        )
    except Exception as exc:
        logger.error("Failed to queue Zenodo OAI harvest: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to queue Zenodo OAI harvest")


@tools_bp.route("/zenodo-oai-harvest/jobs", methods=["GET"])
@jwt_required()
def list_zenodo_oai_harvest_jobs():
    try:
        user = _current_tools_user()
        role = getattr(user, "role", None)
        role_value = getattr(role, "value", role) or "user"
        limit = max(1, min(request.args.get("limit", default=20, type=int) or 20, 50))
        user_filter = None if role_value == "admin" and request.args.get("all") in {"1", "true"} else int(user.id)
        return APIResponse.success(data={"jobs": [_public_oai_harvest_entry(entry) for entry in list_harvest_entries(limit=limit, user_id=user_filter)]})
    except Exception as exc:
        logger.error("Failed to list Zenodo OAI harvest jobs: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to list Zenodo OAI harvest jobs")


@tools_bp.route("/zenodo-oai-harvest/jobs/<harvest_id>", methods=["GET"])
@jwt_required()
def get_zenodo_oai_harvest_job(harvest_id):
    try:
        user = _current_tools_user()
        public = _public_oai_harvest_entry(_ensure_oai_harvest_entry_access(get_harvest_entry(harvest_id), user)) or {}
        public["diagnostics"] = build_oai_harvest_diagnostics(public)
        return APIResponse.success(data=public)
    except Exception as exc:
        logger.error("Failed to load Zenodo OAI harvest job %s: %s", harvest_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to load Zenodo OAI harvest job")


@tools_bp.route("/zenodo-oai-harvest/jobs/<harvest_id>/pause", methods=["POST"])
@jwt_required()
def pause_zenodo_oai_harvest_job(harvest_id):
    try:
        user = _current_tools_user()
        _ensure_oai_harvest_entry_access(get_harvest_entry(harvest_id), user)
        return APIResponse.success(data=_public_oai_harvest_entry(request_oai_harvest_pause(harvest_id)), message="Pause requested")
    except Exception as exc:
        logger.error("Failed to pause Zenodo OAI harvest job %s: %s", harvest_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to pause Zenodo OAI harvest job")


@tools_bp.route("/zenodo-oai-harvest/jobs/<harvest_id>/resume", methods=["POST"])
@jwt_required()
def resume_zenodo_oai_harvest_job(harvest_id):
    try:
        user = _current_tools_user()
        _ensure_oai_harvest_entry_access(get_harvest_entry(harvest_id), user)
        clear_oai_harvest_pause(harvest_id)
        update_harvest_entry(harvest_id, state="PENDING", status="Queued Zenodo OAI harvest resume", control={"cancel_requested": False})
        from tasks import execute_zenodo_oai_harvest

        task = execute_zenodo_oai_harvest.delay(harvest_id=harvest_id, requester_user_id=int(user.id))
        entry = _mark_oai_harvest_queued_unless_finished(harvest_id, task_id=getattr(task, "id", None), status="Queued Zenodo OAI harvest resume")
        return APIResponse.accepted(data=_public_oai_harvest_entry(entry), message="Zenodo OAI harvest resumed")
    except Exception as exc:
        logger.error("Failed to resume Zenodo OAI harvest job %s: %s", harvest_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to resume Zenodo OAI harvest job")


@tools_bp.route("/zenodo-oai-harvest/jobs/<harvest_id>/cancel", methods=["POST"])
@jwt_required()
def cancel_zenodo_oai_harvest_job(harvest_id):
    try:
        user = _current_tools_user()
        _ensure_oai_harvest_entry_access(get_harvest_entry(harvest_id), user)
        return APIResponse.success(data=_public_oai_harvest_entry(request_oai_harvest_cancel(harvest_id)), message="Cancel requested")
    except Exception as exc:
        logger.error("Failed to cancel Zenodo OAI harvest job %s: %s", harvest_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to cancel Zenodo OAI harvest job")


@tools_bp.route("/zenodo-oai-harvest/jobs/<harvest_id>", methods=["DELETE"])
@jwt_required()
def delete_zenodo_oai_harvest_job(harvest_id):
    try:
        user = _current_tools_user()
        entry = _ensure_oai_harvest_entry_access(get_harvest_entry(harvest_id), user)
        deleted = delete_oai_harvest_shards(entry)
        delete_harvest_entry(harvest_id)
        return APIResponse.success(data={"harvest_id": harvest_id, **deleted}, message="Zenodo OAI harvest files deleted")
    except Exception as exc:
        logger.error("Failed to delete Zenodo OAI harvest job %s: %s", harvest_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to delete Zenodo OAI harvest job")


@tools_bp.route("/zenodo-oai-harvest/jobs/<harvest_id>/records", methods=["GET"])
@jwt_required()
def search_zenodo_oai_harvest_records(harvest_id):
    try:
        user = _current_tools_user()
        entry = _ensure_oai_harvest_entry_access(get_harvest_entry(harvest_id), user)
        return APIResponse.success(
            data=search_oai_harvest_collection(
                entry,
                query=request.args.get("q"),
                status=request.args.get("status"),
                limit=request.args.get("limit", default=100, type=int) or 100,
                offset=request.args.get("offset", default=0, type=int) or 0,
            )
        )
    except Exception as exc:
        logger.error("Failed to search Zenodo OAI harvest %s: %s", harvest_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to search Zenodo OAI harvest records")


@tools_bp.route("/zenodo-oai-harvest/jobs/<harvest_id>/detectors", methods=["GET"])
@jwt_required()
def run_zenodo_oai_harvest_detector(harvest_id):
    try:
        user = _current_tools_user()
        entry = _ensure_oai_harvest_entry_access(get_harvest_entry(harvest_id), user)
        detector_id = str(request.args.get("detector") or request.args.get("detector_id") or "community_migration_candidates")
        target_community = request.args.get("target_community") or "3dbigdataspace"
        return APIResponse.success(
            data=run_oai_harvest_detector(
                entry,
                detector_id=detector_id,
                target_community=target_community,
                limit=request.args.get("limit", default=250, type=int) or 250,
                offset=request.args.get("offset", default=0, type=int) or 0,
            )
        )
    except ValueError as exc:
        return APIResponse.validation_error(str(exc))
    except Exception as exc:
        logger.error("Failed to run Zenodo OAI harvest detector %s: %s", harvest_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to run Zenodo OAI harvest detector")


@tools_bp.route("/zenodo-oai-harvest/jobs/<harvest_id>/detectors/export", methods=["GET"])
@jwt_required()
def export_zenodo_oai_harvest_detector(harvest_id):
    try:
        user = _current_tools_user()
        entry = _ensure_oai_harvest_entry_access(get_harvest_entry(harvest_id), user)
        detector_id = str(request.args.get("detector") or request.args.get("detector_id") or "community_migration_candidates")
        target_community = request.args.get("target_community") or "3dbigdataspace"
        return Response(
            export_oai_harvest_detector_csv(entry, detector_id=detector_id, target_community=target_community),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=zenodo-oai-harvest-{harvest_id}-{detector_id}.csv"},
        )
    except ValueError as exc:
        return APIResponse.validation_error(str(exc))
    except Exception as exc:
        logger.error("Failed to export Zenodo OAI harvest detector %s: %s", harvest_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to export Zenodo OAI harvest detector")


@tools_bp.route("/zenodo-oai-harvest/jobs/<harvest_id>/compact", methods=["POST"])
@jwt_required()
def compact_zenodo_oai_harvest_job(harvest_id):
    try:
        user = _current_tools_user()
        entry = _ensure_oai_harvest_entry_access(get_harvest_entry(harvest_id), user)
        payload = request.get_json(silent=True) or {}
        result = compact_oai_harvest_shards(entry, target_records_per_shard=int(payload.get("target_records_per_shard") or 5000))
        return APIResponse.success(data={"compaction": result, "job": _public_oai_harvest_entry(get_harvest_entry(harvest_id))}, message="OAI harvest shards compacted")
    except Exception as exc:
        logger.error("Failed to compact Zenodo OAI harvest %s: %s", harvest_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to compact Zenodo OAI harvest")


@tools_bp.route("/zenodo-oai-harvest/jobs/<harvest_id>/schedule", methods=["PATCH"])
@jwt_required()
def update_zenodo_oai_harvest_schedule(harvest_id):
    try:
        user = _current_tools_user()
        entry = _ensure_oai_harvest_entry_access(get_harvest_entry(harvest_id), user)
        if str(entry.get("state") or "").upper() != "SUCCESS":
            return APIResponse.validation_error("Only completed OAI harvest collections can be scheduled")
        payload = request.get_json(silent=True) or {}
        frequency = str(payload.get("frequency") or "weekly").lower()
        if frequency not in {"daily", "weekly", "monthly"}:
            return APIResponse.validation_error("frequency must be daily, weekly, or monthly")
        overlap_hours = max(0, min(int(payload.get("incremental_overlap_hours", 24)), 168))
        max_records = normalize_oai_max_records(payload.get("max_records"))
        schedule = {
            "enabled": bool(payload.get("enabled", True)),
            "frequency": frequency,
            "incremental_overlap_hours": overlap_hours,
            "max_records": max_records,
            "next_run_at": _next_schedule_run(frequency),
            "updated_at": datetime.utcnow().isoformat(),
            "updated_by_user_id": int(user.id),
        }
        updated = update_harvest_entry(harvest_id, collection={"schedule": schedule})
        return APIResponse.success(data=_public_oai_harvest_entry(updated), message="OAI harvest incremental schedule updated")
    except Exception as exc:
        logger.error("Failed to update Zenodo OAI harvest schedule %s: %s", harvest_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to update OAI harvest schedule")


@tools_bp.route("/zenodo-oai-harvest/jobs/<harvest_id>/schedule/run-now", methods=["POST"])
@jwt_required()
def run_zenodo_oai_harvest_schedule_now(harvest_id):
    try:
        user = _current_tools_user()
        parent = _ensure_oai_harvest_entry_access(get_harvest_entry(harvest_id), user)
        if str(parent.get("state") or "").upper() != "SUCCESS":
            return APIResponse.validation_error("Only completed OAI harvest collections can start an incremental sync")
        collection = parent.get("collection") if isinstance(parent.get("collection"), dict) else {}
        latest = collection.get("latest_datestamp")
        if not latest:
            return APIResponse.validation_error("Parent OAI harvest has no latest datestamp for incremental sync")
        schedule = collection.get("schedule") if isinstance(collection.get("schedule"), dict) else {}
        overlap_hours = max(0, min(int(schedule.get("incremental_overlap_hours", 24)), 168))
        from_datetime = _shift_datetime(latest, hours=-overlap_hours)
        max_records = normalize_oai_max_records(schedule.get("max_records"))
        options = parent.get("options") if isinstance(parent.get("options"), dict) else {}
        child_harvest_id = new_harvest_id()
        record_harvest_launch(
            harvest_id=child_harvest_id,
            task_id=None,
            requested_by_user_id=int(user.id),
            requested_by_email=user.email,
            base_url=str(options.get("base_url") or DEFAULT_OAI_BASE_URL),
            set_spec=str(options.get("set_spec") or DEFAULT_OAI_SET_SPEC),
            metadata_prefix=str(options.get("metadata_prefix") or DEFAULT_OAI_METADATA_PREFIX),
            max_records=max_records,
            from_datetime=from_datetime,
            until_datetime=None,
            sync_mode="incremental",
            parent_harvest_id=str(parent.get("harvest_id") or harvest_id),
            incremental_since=latest,
            incremental_overlap_hours=overlap_hours,
        )
        from tasks import execute_zenodo_oai_harvest

        task = execute_zenodo_oai_harvest.delay(harvest_id=child_harvest_id, requester_user_id=int(user.id))
        entry = _mark_oai_harvest_queued_unless_finished(child_harvest_id, task_id=getattr(task, "id", None), status="Queued scheduled Zenodo OAI incremental harvest")
        return APIResponse.accepted(data=_public_oai_harvest_entry(entry), message="Scheduled incremental OAI harvest queued")
    except Exception as exc:
        logger.error("Failed to run Zenodo OAI harvest schedule now %s: %s", harvest_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to queue scheduled incremental OAI harvest")


@tools_bp.route("/zenodo-oai-harvest/jobs/<harvest_id>/export/<export_format>", methods=["GET"])
@jwt_required()
def export_zenodo_oai_harvest(harvest_id, export_format):
    try:
        user = _current_tools_user()
        entry = _ensure_oai_harvest_entry_access(get_harvest_entry(harvest_id), user)
        normalized = str(export_format or "").lower()
        if normalized == "manifest":
            return APIResponse.success(data=export_oai_harvest_manifest(_public_oai_harvest_entry(entry) or entry))
        if normalized == "csv":
            return Response(
                export_oai_harvest_records_csv(entry),
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment; filename=zenodo-oai-harvest-{harvest_id}.csv"},
            )
        if normalized == "archive":
            archive_dir = os.path.join(current_app.instance_path, "oai_harvest_exports")
            os.makedirs(archive_dir, exist_ok=True)
            archive_path = os.path.join(archive_dir, f"zenodo-oai-harvest-{harvest_id}.zip")
            build_oai_harvest_shard_archive(entry, archive_path)
            return send_file(archive_path, as_attachment=True, download_name=f"zenodo-oai-harvest-{harvest_id}.zip")
        return APIResponse.validation_error("export_format must be one of manifest, csv, or archive")
    except Exception as exc:
        logger.error("Failed to export Zenodo OAI harvest %s: %s", harvest_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to export Zenodo OAI harvest")


def _community_migration_error_response(exc: Exception):
    if isinstance(exc, ValidationError):
        return APIResponse.validation_error(str(exc))
    if isinstance(exc, ResourceNotFoundError):
        return APIResponse.not_found(str(exc))
    return None


@tools_bp.route("/community-migrations/context", methods=["GET"])
@jwt_required()
@require_moderator_or_admin
def get_community_migration_context():
    try:
        user = _current_tools_user()
        return APIResponse.success(data=community_migration_service.list_context(user))
    except Exception as exc:
        handled = _community_migration_error_response(exc)
        if handled is not None:
            return handled
        logger.error("Failed to load community migration context: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to load community migration context")


@tools_bp.route("/community-migrations/plan", methods=["POST"])
@jwt_required()
@require_moderator_or_admin
def plan_community_migration():
    try:
        user = _current_tools_user()
        payload = request.get_json(silent=True) or {}
        plan = community_migration_service.build_plan(
            user=user,
            source_retrieval_id=str(payload.get("source_retrieval_id") or ""),
            source_community=str(payload.get("source_community") or ""),
            target_community=str(payload.get("target_community") or ""),
            filters=payload.get("filters") if isinstance(payload.get("filters"), dict) else {},
            options=payload.get("options") if isinstance(payload.get("options"), dict) else {},
        )
        return APIResponse.success(data=plan, message="Community migration plan built")
    except Exception as exc:
        handled = _community_migration_error_response(exc)
        if handled is not None:
            return handled
        logger.error("Failed to plan community migration: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to plan community migration")


@tools_bp.route("/community-migrations/jobs", methods=["POST"])
@jwt_required()
@require_moderator_or_admin
def launch_community_migration_job():
    try:
        user = _current_tools_user()
        payload = request.get_json(silent=True) or {}
        job = community_migration_service.create_job(
            user=user,
            source_retrieval_id=str(payload.get("source_retrieval_id") or ""),
            source_community=str(payload.get("source_community") or ""),
            target_community=str(payload.get("target_community") or ""),
            filters=payload.get("filters") if isinstance(payload.get("filters"), dict) else {},
            options=payload.get("options") if isinstance(payload.get("options"), dict) else {},
            expected_plan_checksum=str(payload.get("plan_checksum") or "").strip() or None,
        )

        from tasks import execute_community_migration_job

        task = execute_community_migration_job.delay(job_id=job.public_id)
        community_migration_service.mark_queued(job, task_id=getattr(task, "id", None))
        return APIResponse.accepted(data=job.to_dict(), message="Community migration queued")
    except Exception as exc:
        handled = _community_migration_error_response(exc)
        if handled is not None:
            return handled
        logger.error("Failed to queue community migration: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to queue community migration")


@tools_bp.route("/community-migrations/jobs", methods=["GET"])
@jwt_required()
@require_moderator_or_admin
def list_community_migration_jobs():
    try:
        user = _current_tools_user()
        limit = max(1, min(request.args.get("limit", default=20, type=int) or 20, 50))
        return APIResponse.success(data={"jobs": community_migration_service.list_jobs(user, limit=limit)})
    except Exception as exc:
        handled = _community_migration_error_response(exc)
        if handled is not None:
            return handled
        logger.error("Failed to list community migration jobs: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to list community migration jobs")


@tools_bp.route("/community-migrations/jobs/<job_id>", methods=["GET"])
@jwt_required()
@require_moderator_or_admin
def get_community_migration_job(job_id):
    try:
        user = _current_tools_user()
        job = community_migration_service.get_job(job_id, user)
        include_records = str(request.args.get("include_records") or "").lower() in {"1", "true", "yes"}
        return APIResponse.success(data=job.to_dict(include_records=include_records))
    except Exception as exc:
        handled = _community_migration_error_response(exc)
        if handled is not None:
            return handled
        logger.error("Failed to load community migration job %s: %s", job_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to load community migration job")


@tools_bp.route("/community-migrations/jobs/<job_id>/resume", methods=["POST"])
@jwt_required()
@require_moderator_or_admin
def resume_community_migration_job(job_id):
    try:
        user = _current_tools_user()
        job = community_migration_service.resume_job(community_migration_service.get_job(job_id, user))
        from tasks import execute_community_migration_job

        task = execute_community_migration_job.delay(job_id=job.public_id)
        community_migration_service.mark_queued(job, task_id=getattr(task, "id", None))
        return APIResponse.accepted(data=job.to_dict(), message="Community migration resumed")
    except Exception as exc:
        handled = _community_migration_error_response(exc)
        if handled is not None:
            return handled
        logger.error("Failed to resume community migration job %s: %s", job_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to resume community migration")


@tools_bp.route("/community-migrations/jobs/<job_id>/cancel", methods=["POST"])
@jwt_required()
@require_moderator_or_admin
def cancel_community_migration_job(job_id):
    try:
        user = _current_tools_user()
        job = community_migration_service.request_cancel(community_migration_service.get_job(job_id, user))
        return APIResponse.accepted(data=job.to_dict(), message="Community migration cancellation requested")
    except Exception as exc:
        handled = _community_migration_error_response(exc)
        if handled is not None:
            return handled
        logger.error("Failed to cancel community migration job %s: %s", job_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to cancel community migration")


@tools_bp.route("/community-migrations/jobs/<job_id>/export", methods=["GET"])
@jwt_required()
@require_moderator_or_admin
def export_community_migration_job(job_id):
    try:
        user = _current_tools_user()
        job = community_migration_service.get_job(job_id, user)
        export_format = str(request.args.get("format") or "json").strip().lower()
        if export_format == "csv":
            return Response(
                community_migration_service.export_job_csv(job),
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment; filename=community-migration-{job.public_id}.csv"},
            )
        if export_format == "json":
            return APIResponse.success(data=community_migration_service.export_job_json(job))
        return APIResponse.validation_error("format must be json or csv")
    except Exception as exc:
        handled = _community_migration_error_response(exc)
        if handled is not None:
            return handled
        logger.error("Failed to export community migration job %s: %s", job_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to export community migration")


@tools_bp.route("/hdp-components/validate", methods=["POST"])
@jwt_required()
@require_admin
def validate_hdp_component_install():
    payload = request.get_json() or {}
    validation = current_app.component_installer_service.validate_install_payload(payload)
    return APIResponse.success(data=validation, message="HDP Component install package validated")


@tools_bp.route("/hdp-components/catalog", methods=["GET"])
@jwt_required()
@require_admin
def list_hdp_component_catalog():
    catalog = current_app.component_installer_service.list_available_catalog(
        install_strategy=request.args.get("install_strategy") or request.args.get("strategy") or "hpc_sif",
        source=request.args.get("source") or "all",
    )
    return APIResponse.success(data=catalog)


@tools_bp.route("/hdp-components/catalog/diagnostics", methods=["GET"])
@jwt_required()
@require_admin
def hdp_component_catalog_diagnostics():
    diagnostics = current_app.component_index_service.diagnostics()
    return APIResponse.success(data=diagnostics)


@tools_bp.route("/hdp-components/install", methods=["POST"])
@jwt_required()
@require_admin
def install_hdp_component():
    payload = request.get_json() or {}
    result = current_app.component_installer_service.install_component(payload, user=_current_tools_user())
    return APIResponse.created(data=result, message="HDP Component installed")


@tools_bp.route("/hdp-components/installations", methods=["GET"])
@jwt_required()
@require_admin
def list_hdp_component_installations():
    installations = current_app.component_installer_service.list_installations()
    return APIResponse.success(data={"installations": installations})


@tools_bp.route("/hdp-components/installations/<installation_id>", methods=["GET"])
@jwt_required()
@require_admin
def get_hdp_component_installation(installation_id):
    row = current_app.component_installer_service.get_installation(installation_id)
    current_app.component_installer_service.reconcile_installation(row)
    return APIResponse.success(data={"installation": current_app.component_installer_service._serialize_installation(row)})


@tools_bp.route("/hdp-components/installations/<installation_id>/test", methods=["POST"])
@jwt_required()
@require_admin
def test_hdp_component_installation(installation_id):
    payload = request.get_json() or {}
    result = current_app.component_installer_service.test_installation(installation_id, payload)
    return APIResponse.success(data=result, message="HDP Component test completed")


@tools_bp.route("/zenodo-batch-operations/records", methods=["GET"])
@jwt_required()
@require_moderator_or_admin
def zenodo_batch_operations_records():
    try:
        owner_filter = request.args.get("owner_user_id", type=int)
        session_id_filter = request.args.get("session_id", type=int)
        page = max(1, request.args.get("page", default=1, type=int) or 1)
        per_page = max(1, min(request.args.get("per_page", default=10, type=int) or 10, 50))

        filters = {
            "q": str(request.args.get("q") or "").strip(),
            "record_status": str(request.args.get("record_status") or "all").strip().lower(),
            "session_id": session_id_filter,
            "owner_user_id": owner_filter,
            "is_sandbox": _parse_optional_bool(request.args.get("is_sandbox")),
            "creator": str(request.args.get("creator") or "").strip(),
            "community": str(request.args.get("community") or "").strip(),
            "publication_date_from": _parse_iso_date(request.args.get("publication_date_from")),
            "publication_date_to": _parse_iso_date(request.args.get("publication_date_to")),
            "updated_from": _parse_iso_datetime(request.args.get("updated_from")),
            "updated_to": _parse_iso_datetime(request.args.get("updated_to")),
        }

        query = db.session.query(DBSession, User.email.label("owner_email")).join(User, DBSession.user_id == User.id)
        if owner_filter:
            query = query.filter(DBSession.user_id == owner_filter)
        if session_id_filter:
            query = query.filter(DBSession.id == session_id_filter)
        sessions = query.order_by(DBSession.created_at.desc()).all()

        grouped_records: Dict[int, Dict[str, Any]] = {}
        session_warnings: List[Dict[str, Any]] = []
        all_filtered_records: List[Dict[str, Any]] = []

        for session_row, owner_email in sessions:
            route_result = get_session_records(int(session_row.id))
            _, status_code, payload = _unpack_route_response(route_result)
            if status_code != 200:
                session_warnings.append(
                    {
                        "session_id": int(session_row.id),
                        "reason": f"Failed to load records (status {status_code})",
                        "severity": "error",
                    }
                )
                continue

            session_data = payload.get("data") or {}
            source_state = session_data.get("source_state", "ok")
            if source_state != "ok":
                warning_message = (session_data.get("warnings") or ["Record source unavailable"])[0]
                session_warnings.append(
                    {
                        "session_id": int(session_row.id),
                        "reason": warning_message,
                        "severity": "warning",
                        "source_state": source_state,
                    }
                )

            normalized_records = [
                _normalize_batch_record(session_row, owner_email, record)
                for record in (session_data.get("records") or [])
                if isinstance(record, dict)
            ]
            filtered_records = [
                record
                for record in normalized_records
                if _record_matches_tools_filters(record, filters)
            ]
            if not filtered_records:
                continue

            grouped_records[int(session_row.id)] = {
                "session": {
                    "id": int(session_row.id),
                    "status": session_row.status,
                    "created_at": session_row.created_at.isoformat() if session_row.created_at else None,
                    "updated_at": session_row.updated_at.isoformat() if session_row.updated_at else None,
                    "owner_user_id": int(session_row.user_id),
                    "owner_email": owner_email,
                },
                "records": filtered_records,
            }
            all_filtered_records.extend(filtered_records)

        ordered_groups = _serialize_grouped_batch_records(
            [
                grouped_records[session_id]
                for session_id in sorted(
                    grouped_records.keys(),
                    key=lambda item: _parse_iso_datetime(grouped_records[item]["session"].get("created_at")) or datetime.min,
                    reverse=True,
                )
            ]
        )

        total_groups = len(ordered_groups)
        total_pages = max(1, (total_groups + per_page - 1) // per_page)
        start = (page - 1) * per_page
        end = start + per_page
        paged_groups = ordered_groups[start:end]

        overall_summary = _build_batch_operation_summary(all_filtered_records)
        overall_summary.update(
            {
                "sessions_scanned": len(sessions),
                "sessions_with_matches": total_groups,
                "records_filtered": len(all_filtered_records),
                "records_on_page": sum(len(group.get("records") or []) for group in paged_groups),
                "session_warning_count": len(session_warnings),
            }
        )

        return APIResponse.success(
            data={
                "summary": overall_summary,
                "filters": {
                    "q": filters["q"],
                    "record_status": filters["record_status"],
                    "session_id": filters["session_id"],
                    "owner_user_id": filters["owner_user_id"],
                    "is_sandbox": filters["is_sandbox"],
                    "creator": filters["creator"],
                    "community": filters["community"],
                    "publication_date_from": filters["publication_date_from"].isoformat() if filters["publication_date_from"] else None,
                    "publication_date_to": filters["publication_date_to"].isoformat() if filters["publication_date_to"] else None,
                    "updated_from": filters["updated_from"].isoformat() if filters["updated_from"] else None,
                    "updated_to": filters["updated_to"].isoformat() if filters["updated_to"] else None,
                },
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total_groups": total_groups,
                    "total_pages": total_pages,
                    "has_previous": page > 1,
                    "has_next": end < total_groups,
                },
                "groups": paged_groups,
                "all_filtered_record_refs": [
                    {
                        "session_id": int(record.get("session_id") or 0),
                        "local_record_id": int(record.get("local_record_id") or 0),
                    }
                    for record in all_filtered_records
                ],
                "all_filtered_records_preview": [
                    {
                        "session_id": int(record.get("session_id") or 0),
                        "local_record_id": int(record.get("local_record_id") or 0),
                        "record_title": record.get("record_title"),
                        "record_status": record.get("record_status"),
                        "communities_normalized": list(record.get("communities_normalized") or []),
                        "operation_eligibility": record.get("operation_eligibility") or {},
                    }
                    for record in all_filtered_records
                ],
                "session_warnings": session_warnings,
            }
        )
    except Exception as exc:
        logger.error("Failed to build Zenodo batch operations record list: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to build Zenodo batch operations record list")


@tools_bp.route("/zenodo-batch-operations/community-operations", methods=["POST"])
@jwt_required()
@require_moderator_or_admin
def launch_zenodo_batch_community_operation():
    try:
        payload = request.get_json() or {}
        operation = str(payload.get("operation") or "").strip().lower()
        remove_mode = str(payload.get("remove_mode") or "").strip().lower()
        community_identifier = str(payload.get("community_identifier") or "").strip()
        record_refs = _normalize_record_refs(payload.get("record_refs"))

        if operation not in {"append_if_missing", "remove_communities"}:
            return APIResponse.validation_error("operation must be 'append_if_missing' or 'remove_communities'")
        if operation == "remove_communities" and remove_mode not in {"one", "all"}:
            return APIResponse.validation_error("remove_mode must be 'one' or 'all' for remove_communities")
        if operation == "append_if_missing" and not community_identifier:
            return APIResponse.validation_error("community_identifier is required for append_if_missing")
        if operation == "remove_communities" and remove_mode == "one" and not community_identifier:
            return APIResponse.validation_error("community_identifier is required for remove_communities with remove_mode='one'")
        if not record_refs:
            return APIResponse.validation_error("record_refs must contain at least one valid record reference")

        selected_by_session: Dict[int, set[int]] = defaultdict(set)
        for session_id, local_record_id in record_refs:
            selected_by_session[session_id].add(local_record_id)

        selected_records: List[Dict[str, Any]] = []
        missing_records: List[Dict[str, int]] = []
        for session_id, local_record_ids in selected_by_session.items():
            route_result = get_session_records(session_id)
            _, status_code, route_payload = _unpack_route_response(route_result)
            if status_code != 200:
                return APIResponse.validation_error(
                    f"Failed to validate selected records for session {session_id}",
                    details={"session_id": session_id, "status_code": status_code},
                )

            session_data = route_payload.get("data") or {}
            session_row = db.session.get(DBSession, session_id)
            owner_email = None
            if session_row:
                owner = db.session.get(User, int(session_row.user_id))
                owner_email = owner.email if owner else None

            record_map = {
                int(record.get("local_record_id")): _normalize_batch_record(session_row, owner_email, record)
                for record in (session_data.get("records") or [])
                if isinstance(record, dict) and session_row is not None
            }
            for local_record_id in sorted(local_record_ids):
                record = record_map.get(local_record_id)
                if record is None:
                    missing_records.append({"session_id": session_id, "local_record_id": local_record_id})
                    continue
                selected_records.append(record)

        if missing_records:
            return APIResponse.validation_error(
                "Some selected records could not be resolved",
                details={"missing_records": missing_records},
            )

        eligibility_key = "append_if_missing" if operation == "append_if_missing" else "remove_one" if remove_mode == "one" else "remove_all"
        eligible_count = sum(
            1
            for record in selected_records
            if bool(((record.get("operation_eligibility") or {}).get(eligibility_key) or {}).get("eligible"))
        )
        if eligible_count == 0:
            return APIResponse.validation_error("No selected records are eligible for this operation")

        from tasks import execute_zenodo_batch_community_operation

        task = execute_zenodo_batch_community_operation.delay(
            operation=operation,
            remove_mode=remove_mode or None,
            community_identifier=community_identifier or None,
            selected_records=[
                {
                    "session_id": int(record.get("session_id") or 0),
                    "local_record_id": int(record.get("local_record_id") or 0),
                    "record_title": record.get("record_title"),
                    "record_status": record.get("record_status"),
                    "zenodo_record_id": record.get("zenodo_record_id"),
                    "is_sandbox": record.get("is_sandbox"),
                    "communities_normalized": list(record.get("communities_normalized") or []),
                    "operation_eligibility": record.get("operation_eligibility") or {},
                }
                for record in selected_records
            ],
        )
        requester_id = get_jwt_identity()
        requester = db.session.get(User, int(requester_id)) if requester_id is not None else None
        record_task_launch(
            task_id=task.id,
            operation=operation,
            remove_mode=remove_mode or None,
            community_identifier=community_identifier or None,
            selected_count=len(selected_records),
            eligible_count=eligible_count,
            ineligible_count=len(selected_records) - eligible_count,
            requested_by_user_id=int(requester_id) if requester_id is not None else None,
            requested_by_email=requester.email if requester else None,
        )

        return APIResponse.accepted(
            data={
                "task_id": task.id,
                "operation": operation,
                "remove_mode": remove_mode or None,
                "community_identifier": community_identifier or None,
                "selected_count": len(selected_records),
                "eligible_count": eligible_count,
                "ineligible_count": len(selected_records) - eligible_count,
            },
            message="Zenodo community batch operation queued",
        )
    except Exception as exc:
        logger.error("Failed to queue Zenodo community operation: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to queue Zenodo community operation")


@tools_bp.route("/zenodo-batch-operations/history", methods=["GET"])
@jwt_required()
@require_moderator_or_admin
def get_zenodo_batch_operation_history():
    try:
        limit = max(1, min(request.args.get("limit", default=15, type=int) or 15, 50))
        return APIResponse.success(data={"tasks": list_task_entries(limit=limit)})
    except Exception as exc:
        logger.error("Failed to get Zenodo batch history: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to get Zenodo batch history")


@tools_bp.route("/zenodo-batch-operations/tasks/<task_id>", methods=["GET"])
@jwt_required()
@require_moderator_or_admin
def get_zenodo_batch_operation_task(task_id):
    try:
        from celery_app import celery

        task = celery.AsyncResult(task_id)
        info = task.info if isinstance(task.info, dict) else {}
        history_entry = get_task_entry(task_id)

        if task.state == "PENDING":
            data = _task_payload_from_history(history_entry) if history_entry else {
                "state": task.state,
                "status": "Pending...",
                "progress": {
                    "total_records": 0,
                    "processed": 0,
                    "percent": 0,
                },
                "result": None,
                "error": None,
            }
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
            data = (
                {
                    "state": task.state,
                    "status": result.get("status") or "completed",
                    "progress": result.get("progress"),
                    "result": result,
                    "error": None,
                }
                if result
                else _task_payload_from_history(history_entry)
                if history_entry
                else {
                    "state": task.state,
                    "status": "completed",
                    "progress": None,
                    "result": None,
                    "error": None,
                }
            )
        else:
            data = {
                "state": task.state,
                "status": info.get("status") or "Processing",
                "progress": info.get("progress") if isinstance(info.get("progress"), dict) else None,
                "result": info.get("result"),
                "error": info.get("error"),
            }

        if history_entry or task.state != "PENDING":
            update_task_entry(
                task_id,
                state=data.get("state"),
                status=data.get("status"),
                progress=data.get("progress") if isinstance(data.get("progress"), dict) else None,
                result=data.get("result") if isinstance(data.get("result"), dict) else None,
                error=data.get("error"),
            )
        return APIResponse.success(data=data)
    except Exception as exc:
        logger.error("Failed to get Zenodo batch task status: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to get Zenodo batch task status")


@tools_bp.route("/community-moderation/requests", methods=["GET"])
@jwt_required()
@require_moderator_or_admin
def get_community_moderation_requests():
    try:
        page = max(1, request.args.get("page", default=1, type=int) or 1)
        per_page = max(1, min(request.args.get("per_page", default=25, type=int) or 25, 100))
        moderation_context = _resolve_moderation_context(
            community_identifier=request.args.get("community_identifier"),
            institution_id=request.args.get("institution_id"),
        )
        community_identifier = moderation_context["community_identifier"]

        filters = _community_request_filters_from_args()
        fetched = zenodo_moderation_service.fetch_open_community_requests(community_identifier)
        requests_all = list(fetched.get("requests") or [])
        filtered_requests = [
            item
            for item in requests_all
            if zenodo_moderation_service.request_matches_filters(item, filters)
        ]
        request_types = sorted(
            {
                str(item.get("type") or "").strip()
                for item in requests_all
                if str(item.get("type") or "").strip()
            }
        )

        total_items = len(filtered_requests)
        total_pages = max(1, (total_items + per_page - 1) // per_page)
        start = (page - 1) * per_page
        end = start + per_page

        return APIResponse.success(
            data={
                "community": fetched.get("community") or {},
                "summary": {
                    "open_requests_total": int(fetched.get("open_count") or 0),
                    "requests_filtered": total_items,
                    "requests_on_page": len(filtered_requests[start:end]),
                    "request_types": request_types,
                },
                "filters": {
                    "institution_id": moderation_context.get("institution_id"),
                    "community_identifier": community_identifier,
                    "q": filters["q"],
                    "request_type": filters["request_type"],
                    "created_from": filters["created_from"].isoformat() if filters["created_from"] else None,
                    "created_to": filters["created_to"].isoformat() if filters["created_to"] else None,
                    "updated_from": filters["updated_from"].isoformat() if filters["updated_from"] else None,
                    "updated_to": filters["updated_to"].isoformat() if filters["updated_to"] else None,
                },
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total_items": total_items,
                    "total_pages": total_pages,
                    "has_previous": page > 1,
                    "has_next": end < total_items,
                },
                "moderation_context": moderation_context,
                "requests": filtered_requests[start:end],
                "all_filtered_request_ids": [item.get("request_id") for item in filtered_requests if item.get("request_id")],
                "all_filtered_requests_preview": filtered_requests,
            }
        )
    except ValueError as exc:
        return APIResponse.validation_error(str(exc))
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else 500
        logger.error("Zenodo community request fetch failed: %s", exc, exc_info=True)
        if status_code == 403:
            return APIResponse.forbidden("Zenodo denied access to this community moderation queue")
        if status_code == 404:
            return APIResponse.not_found("Zenodo community was not found")
        return APIResponse.server_error("Failed to load Zenodo community requests")
    except Exception as exc:
        logger.error("Failed to load community moderation requests: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to load Zenodo community requests")


def _community_moderation_error_response(exc: Exception):
    if isinstance(exc, ValidationError):
        return APIResponse.validation_error(str(exc))
    if isinstance(exc, ResourceNotFoundError):
        return APIResponse.not_found(str(exc))
    if isinstance(exc, ValueError):
        return APIResponse.validation_error(str(exc))
    if isinstance(exc, requests.HTTPError):
        status_code = exc.response.status_code if exc.response is not None else 500
        logger.error("Zenodo community moderation request failed: %s", exc, exc_info=True)
        if status_code == 403:
            return APIResponse.forbidden("Zenodo denied access to this community moderation queue")
        if status_code == 404:
            return APIResponse.not_found("Zenodo community was not found")
        return APIResponse.server_error("Zenodo community moderation request failed")
    return None


@tools_bp.route("/community-moderation/summary", methods=["GET"])
@jwt_required()
@require_moderator_or_admin
def get_community_moderation_summary():
    try:
        moderation_context = _resolve_moderation_context(
            community_identifier=request.args.get("community_identifier"),
            institution_id=request.args.get("institution_id"),
        )
        summary = zenodo_moderation_service.summarize_community_requests(
            moderation_context["community_identifier"],
            action=request.args.get("action") or "accept",
            status=request.args.get("status_filter") or "submitted",
            request_type=request.args.get("request_type") or None,
            preview_size=max(1, min(request.args.get("page_size", default=100, type=int) or 100, 100)),
        )
        return APIResponse.success(data={**summary, "moderation_context": moderation_context})
    except Exception as exc:
        handled = _community_moderation_error_response(exc)
        if handled is not None:
            return handled
        logger.error("Failed to load community moderation summary: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to load community moderation summary")


@tools_bp.route("/community-moderation/sweeps", methods=["GET"])
@jwt_required()
@require_moderator_or_admin
def list_community_moderation_sweeps():
    try:
        user = _current_tools_user()
        limit = max(1, min(request.args.get("limit", default=12, type=int) or 12, 50))
        return APIResponse.success(data={"jobs": community_moderation_sweep_service.list_jobs(user, limit=limit)})
    except Exception as exc:
        handled = _community_moderation_error_response(exc)
        if handled is not None:
            return handled
        logger.error("Failed to list community moderation sweeps: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to list community moderation sweeps")


@tools_bp.route("/community-moderation/sweeps/plan", methods=["POST"])
@jwt_required()
@require_moderator_or_admin
def plan_community_moderation_sweep():
    try:
        payload = request.get_json(silent=True) or {}
        moderation_context = _resolve_moderation_context(
            community_identifier=payload.get("community_identifier"),
            institution_id=payload.get("institution_id"),
        )
        plan = community_moderation_sweep_service.build_plan(
            community_identifier=moderation_context["community_identifier"],
            action=payload.get("action") or "accept",
            status_filter=payload.get("status_filter") or "submitted",
            request_type=payload.get("request_type") or None,
            note=payload.get("note") or None,
            page_size=payload.get("page_size") or 100,
            max_requests=payload.get("max_requests"),
        )
        return APIResponse.success(data={**plan, "moderation_context": moderation_context}, message="Community moderation sweep plan built")
    except Exception as exc:
        handled = _community_moderation_error_response(exc)
        if handled is not None:
            return handled
        logger.error("Failed to plan community moderation sweep: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to plan community moderation sweep")


@tools_bp.route("/community-moderation/sweeps", methods=["POST"])
@jwt_required()
@require_moderator_or_admin
def launch_community_moderation_sweep():
    try:
        user = _current_tools_user()
        payload = request.get_json(silent=True) or {}
        moderation_context = _resolve_moderation_context(
            community_identifier=payload.get("community_identifier"),
            institution_id=payload.get("institution_id"),
        )
        job = community_moderation_sweep_service.create_job(
            user=user,
            community_identifier=moderation_context["community_identifier"],
            action=payload.get("action") or "accept",
            status_filter=payload.get("status_filter") or "submitted",
            request_type=payload.get("request_type") or None,
            note=payload.get("note") or None,
            page_size=payload.get("page_size") or 100,
            max_requests=payload.get("max_requests"),
            expected_plan_checksum=str(payload.get("plan_checksum") or "").strip(),
            confirmation_text=str(payload.get("confirmation_text") or "").strip(),
        )

        from tasks import execute_community_moderation_sweep

        task = execute_community_moderation_sweep.delay(job_id=job.public_id)
        community_moderation_sweep_service.mark_queued(job, task_id=getattr(task, "id", None))
        return APIResponse.accepted(data={**job.to_dict(include_events=True), "moderation_context": moderation_context}, message="Community moderation sweep queued")
    except Exception as exc:
        handled = _community_moderation_error_response(exc)
        if handled is not None:
            return handled
        logger.error("Failed to queue community moderation sweep: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to queue community moderation sweep")


@tools_bp.route("/community-moderation/sweeps/<job_id>", methods=["GET"])
@jwt_required()
@require_moderator_or_admin
def get_community_moderation_sweep(job_id):
    try:
        user = _current_tools_user()
        event_limit = max(1, min(request.args.get("event_limit", default=50, type=int) or 50, 200))
        job = community_moderation_sweep_service.get_job(job_id, user)
        return APIResponse.success(data=job.to_dict(include_events=True, event_limit=event_limit))
    except Exception as exc:
        handled = _community_moderation_error_response(exc)
        if handled is not None:
            return handled
        logger.error("Failed to load community moderation sweep %s: %s", job_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to load community moderation sweep")


@tools_bp.route("/community-moderation/sweeps/<job_id>/cancel", methods=["POST"])
@jwt_required()
@require_moderator_or_admin
def cancel_community_moderation_sweep(job_id):
    try:
        user = _current_tools_user()
        job = community_moderation_sweep_service.request_cancel(community_moderation_sweep_service.get_job(job_id, user))
        return APIResponse.accepted(data=job.to_dict(include_events=True), message="Community moderation sweep cancellation requested")
    except Exception as exc:
        handled = _community_moderation_error_response(exc)
        if handled is not None:
            return handled
        logger.error("Failed to cancel community moderation sweep %s: %s", job_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to cancel community moderation sweep")


@tools_bp.route("/community-moderation/sweeps/<job_id>/export", methods=["GET"])
@jwt_required()
@require_moderator_or_admin
def export_community_moderation_sweep(job_id):
    try:
        user = _current_tools_user()
        job = community_moderation_sweep_service.get_job(job_id, user)
        export_format = str(request.args.get("format") or "json").strip().lower()
        if export_format == "csv":
            return Response(
                community_moderation_sweep_service.export_job_csv(job),
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment; filename=community-moderation-sweep-{job.public_id}.csv"},
            )
        if export_format == "json":
            return APIResponse.success(data=community_moderation_sweep_service.export_job_json(job))
        return APIResponse.validation_error("format must be json or csv")
    except Exception as exc:
        handled = _community_moderation_error_response(exc)
        if handled is not None:
            return handled
        logger.error("Failed to export community moderation sweep %s: %s", job_id, exc, exc_info=True)
        return APIResponse.server_error("Failed to export community moderation sweep")


@tools_bp.route("/community-moderation/actions", methods=["POST"])
@jwt_required()
@require_moderator_or_admin
def launch_community_moderation_action():
    try:
        payload = request.get_json() or {}
        action = str(payload.get("action") or "").strip().lower()
        if action not in {"accept", "decline"}:
            return APIResponse.validation_error("action must be 'accept' or 'decline'")

        moderation_context = _resolve_moderation_context(
            community_identifier=payload.get("community_identifier"),
            institution_id=payload.get("institution_id"),
        )
        community_identifier = moderation_context["community_identifier"]
        note = str(payload.get("note") or "").strip()
        request_ids = []
        seen = set()
        for item in payload.get("request_ids") or []:
            value = str(item or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            request_ids.append(value)
        if not request_ids:
            return APIResponse.validation_error("request_ids must contain at least one request id")

        fetched = zenodo_moderation_service.fetch_open_community_requests(community_identifier)
        request_map = {
            str(item.get("request_id")): item
            for item in (fetched.get("requests") or [])
            if item.get("request_id")
        }
        selected_requests = []
        missing_request_ids = []
        for request_id in request_ids:
            item = request_map.get(request_id)
            if not item:
                missing_request_ids.append(request_id)
                continue
            if not item.get("is_actionable"):
                continue
            selected_requests.append(item)

        if missing_request_ids:
            return APIResponse.validation_error(
                "Some selected requests could not be resolved from the current moderation queue",
                details={"missing_request_ids": missing_request_ids},
            )
        if not selected_requests:
            return APIResponse.validation_error("No selected requests are actionable")

        from tasks import execute_community_moderation_batch

        task = execute_community_moderation_batch.delay(
            action=action,
            community_identifier=community_identifier,
            note=note or None,
            selected_requests=selected_requests,
        )
        requester_id = get_jwt_identity()
        requester = db.session.get(User, int(requester_id)) if requester_id is not None else None
        record_community_moderation_task_launch(
            task_id=task.id,
            action=action,
            community_identifier=community_identifier,
            note=note or None,
            selected_count=len(request_ids),
            actionable_count=len(selected_requests),
            requested_by_user_id=int(requester_id) if requester_id is not None else None,
            requested_by_email=requester.email if requester else None,
        )

        return APIResponse.accepted(
            data={
                "task_id": task.id,
                "action": action,
                "community_identifier": community_identifier,
                "moderation_context": moderation_context,
                "selected_count": len(request_ids),
                "actionable_count": len(selected_requests),
                "note_present": bool(note),
            },
            message="Community moderation batch queued",
        )
    except ValueError as exc:
        return APIResponse.validation_error(str(exc))
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else 500
        logger.error("Community moderation validation fetch failed: %s", exc, exc_info=True)
        if status_code == 403:
            return APIResponse.forbidden("Zenodo denied access to this community moderation queue")
        if status_code == 404:
            return APIResponse.not_found("Zenodo community was not found")
        return APIResponse.server_error("Failed to validate selected moderation requests")
    except Exception as exc:
        logger.error("Failed to queue community moderation batch: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to queue community moderation batch")


@tools_bp.route("/community-moderation/history", methods=["GET"])
@jwt_required()
@require_moderator_or_admin
def get_community_moderation_history():
    try:
        limit = max(1, min(request.args.get("limit", default=15, type=int) or 15, 50))
        return APIResponse.success(data={"tasks": list_community_moderation_task_entries(limit=limit)})
    except Exception as exc:
        logger.error("Failed to get community moderation history: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to get community moderation history")


@tools_bp.route("/community-moderation/tasks/<task_id>", methods=["GET"])
@jwt_required()
@require_moderator_or_admin
def get_community_moderation_task(task_id):
    try:
        from celery_app import celery

        task = celery.AsyncResult(task_id)
        info = task.info if isinstance(task.info, dict) else {}
        history_entry = get_community_moderation_task_entry(task_id)

        if task.state == "PENDING":
            data = _community_moderation_task_payload_from_history(history_entry) if history_entry else {
                "state": task.state,
                "status": "Pending...",
                "progress": {
                    "total_requests": 0,
                    "processed": 0,
                    "percent": 0,
                },
                "result": None,
                "error": None,
            }
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
            data = (
                {
                    "state": task.state,
                    "status": result.get("status") or "completed",
                    "progress": result.get("progress"),
                    "result": result,
                    "error": None,
                }
                if result
                else _community_moderation_task_payload_from_history(history_entry)
                if history_entry
                else {
                    "state": task.state,
                    "status": "completed",
                    "progress": None,
                    "result": None,
                    "error": None,
                }
            )
        else:
            data = {
                "state": task.state,
                "status": info.get("status") or "Processing",
                "progress": info.get("progress") if isinstance(info.get("progress"), dict) else None,
                "result": info.get("result"),
                "error": info.get("error"),
            }

        if history_entry or task.state != "PENDING":
            update_community_moderation_task_entry(
                task_id,
                state=data.get("state"),
                status=data.get("status"),
                progress=data.get("progress") if isinstance(data.get("progress"), dict) else None,
                result=data.get("result") if isinstance(data.get("result"), dict) else None,
                error=data.get("error"),
            )
        return APIResponse.success(data=data)
    except Exception as exc:
        logger.error("Failed to get community moderation task status: %s", exc, exc_info=True)
        return APIResponse.server_error("Failed to get community moderation task status")


@tools_bp.route("/pipeline-preflight/local", methods=["POST"])
@jwt_required()
@require_admin_and_local_mode
def pipeline_preflight_local():
    try:
        data = request.get_json() or {}
        project_service = current_app.project_service
        msf_service = current_app.msf_service

        parse_options = _build_parse_options(data)
        recursive_scan = True if "recursive" not in data else _coerce_bool(data.get("recursive"))

        msf_path = _resolve_local_msf_path(data.get("msf_path"), project_service)
        directory_path = _resolve_local_directory_path(data.get("directory_path"), project_service)
        directory_files = _scan_directory_files(directory_path, recursive=recursive_scan)

        duplicate_scan_columns = data.get("duplicate_scan_columns") or []
        if duplicate_scan_columns is not None and not isinstance(duplicate_scan_columns, list):
            return APIResponse.validation_error("duplicate_scan_columns must be a list")

        operations = data.get("operations") or []
        if operations is not None and not isinstance(operations, list):
            return APIResponse.validation_error("operations must be a list")

        report = msf_service.run_local_validator(
            file_path=msf_path,
            parse_options=parse_options,
            directory_files=directory_files,
            directory_root=directory_path,
            filename_column=data.get("filename_column"),
            duplicate_scan_columns=duplicate_scan_columns,
            operations=operations,
            include_reference_check=True,
            include_dataframe=False,
        )

        services = _build_service_health()
        pipeline_steps = _render_pipeline_steps()

        readiness_blockers = list(report.get("blockers") or [])
        render_steps = {
            step.get("id"): bool(step.get("enabled", False))
            for step in (pipeline_steps.get("render", {}).get("steps") or [])
            if isinstance(step, dict)
        }
        if render_steps.get("fast_renderer") and not services.get("fast_renderer", {}).get("ok"):
            readiness_blockers.append("Fast renderer service is not healthy.")
        if render_steps.get("any_to_usdz") and not services.get("any_to_usdz", {}).get("ok"):
            readiness_blockers.append("Any-to-USDZ service is not healthy.")
        readiness = {
            "status": "ready" if not readiness_blockers else "blocked",
            "can_run": len(readiness_blockers) == 0,
            "blockers": readiness_blockers,
            "warning_count": len(report.get("warnings") or []),
        }

        return APIResponse.success(
            data={
                "readiness": readiness,
                "validator": report,
                "services": services,
                "pipeline_steps": pipeline_steps,
            },
            message="Pipeline preflight completed",
        )
    except ValueError as exc:
        return APIResponse.validation_error(str(exc))
    except Exception as exc:
        logger.error("Pipeline preflight failed: %s", exc, exc_info=True)
        return APIResponse.server_error(f"Pipeline preflight failed: {exc}")


@tools_bp.route("/metadata-normalizer/local", methods=["POST"])
@jwt_required()
@require_admin_and_local_mode
def metadata_normalizer_local():
    try:
        data = request.get_json() or {}
        project_service = current_app.project_service
        msf_service = current_app.msf_service

        parse_options = data.get("parse_options") if isinstance(data.get("parse_options"), dict) else {}
        recursive_scan = True if "recursive" not in data else _coerce_bool(data.get("recursive"))
        include_reference_check = bool(data.get("include_reference_check", False))

        msf_path = _resolve_local_msf_path(data.get("msf_path"), project_service)
        directory_path = _resolve_local_directory_path(data.get("directory_path"), project_service)
        directory_files = _scan_directory_files(directory_path, recursive=recursive_scan)

        columns = data.get("columns") or []
        if isinstance(columns, str):
            columns = [item.strip() for item in columns.split(",") if item.strip()]
        if not isinstance(columns, list) or not columns:
            return APIResponse.validation_error("columns must be a non-empty list or comma-separated string")

        operations: List[Dict[str, Any]] = [
            {
                "type": "normalize_text_columns",
                "columns": columns,
                "mode": data.get("mode", "none"),
                "collapse_whitespace": bool(data.get("collapse_whitespace", True)),
                "dedupe_delimited": bool(data.get("dedupe_delimited", False)),
                "delimiter": data.get("delimiter", ";"),
                "auto_space": bool(data.get("auto_space", True)),
            }
        ]

        if bool(data.get("trim_whitespace", False)):
            operations.append({"type": "trim_whitespace", "columns": columns})

        report = msf_service.run_local_validator(
            file_path=msf_path,
            parse_options=parse_options,
            directory_files=directory_files,
            directory_root=directory_path,
            filename_column=data.get("filename_column"),
            duplicate_scan_columns=columns,
            operations=operations,
            include_reference_check=include_reference_check,
            include_dataframe=False,
        )

        return APIResponse.success(data=report, message="Metadata normalization completed")
    except ValueError as exc:
        return APIResponse.validation_error(str(exc))
    except Exception as exc:
        logger.error("Metadata normalizer failed: %s", exc, exc_info=True)
        return APIResponse.server_error(f"Metadata normalizer failed: {exc}")


@tools_bp.route("/output-preview/local", methods=["POST"])
@jwt_required()
@require_admin_and_local_mode
def output_preview_local():
    try:
        data = request.get_json() or {}
        project_service = current_app.project_service
        msf_service = current_app.msf_service

        parse_options = _build_parse_options(data)
        recursive_scan = True if "recursive" not in data else _coerce_bool(data.get("recursive"))

        msf_path = _resolve_local_msf_path(data.get("msf_path"), project_service)
        directory_path = _resolve_local_directory_path(data.get("directory_path"), project_service)
        directory_files = _scan_directory_files(directory_path, recursive=recursive_scan)

        mapping_config, mapping_err = _parse_json_object(data.get("mapping_config"), "mapping_config")
        if mapping_err:
            return APIResponse.validation_error(mapping_err)

        zenodo_record, zenodo_err = _parse_json_object(data.get("zenodo_record"), "zenodo_record")
        if zenodo_err:
            return APIResponse.validation_error(zenodo_err)

        if not zenodo_record:
            zenodo_record = {
                "id": "local-preview",
                "metadata": {},
                "links": {"html": "https://zenodo.org/records/local-preview"},
                "files": [],
            }

        df, profile = msf_service.parse_msf_file_with_profile(msf_path, parse_options=parse_options)
        requested_row = data.get("row_index")
        if requested_row is None:
            row_index = profile.get("suggested_row_index")
            if row_index is None:
                row_index = msf_service.suggest_sample_row_index(df, profile.get("filename_column"))
        else:
            try:
                row_index = int(requested_row)
            except (TypeError, ValueError):
                return APIResponse.validation_error("row_index must be an integer")

        if row_index < 0 or row_index >= len(df):
            return APIResponse.validation_error(f"row_index {row_index} is out of bounds")

        row = df.iloc[row_index]
        metadata = build_pipeline_aligned_lod_metadata(
            msf_service=msf_service,
            row=row,
            zenodo_record=zenodo_record,
            mapping_config=mapping_config,
            msf_profile=profile,
        )

        filename_column = str(data.get("filename_column") or profile.get("filename_column") or "").strip()
        main_file_key = ""
        if filename_column and filename_column in df.columns:
            main_file_key = str(row.get(filename_column) or "").strip()

        additional_files = [
            {"key": item, "filename": item, "size": 0}
            for item in directory_files[:200]
        ]

        targets = data.get("targets") or ["edm", "iiif", "mets"]
        if not isinstance(targets, list):
            return APIResponse.validation_error("targets must be a list")
        target_set = {str(item).strip().lower() for item in targets if str(item).strip()}
        include_remote_validation = (
            _coerce_bool(data.get("include_remote_validation"))
            if "include_remote_validation" in data
            else False
        )
        validation_scope = "local+remote" if include_remote_validation else "local"

        edm_service = current_app.edm_service
        iiif_service = current_app.iiif_service
        mets_service = current_app.mets_service
        outputs: Dict[str, Any] = {}

        if "edm" in target_set:
            try:
                edm_result = edm_service.generate_edm_xml_with_report(
                    metadata=metadata,
                    zenodo_record=zenodo_record.copy(),
                    template_id=data.get("edm_template_id"),
                    main_file_key=main_file_key or None,
                    validate=False,
                    additional_files=additional_files,
                    allow_placeholder_thumbnail=True,
                )
                xml_output = edm_result["content"]
                validation = edm_service.validate_edm_document(
                    xml_output,
                    metadata=metadata,
                    include_remote=include_remote_validation,
                )
                outputs["edm"] = {
                    "ok": True,
                    "content": xml_output,
                    "preview": _text_preview(xml_output),
                    "minimum_viable_applied": edm_result["minimum_viable_applied"],
                    "adjustments": edm_result.get("adjustments", []),
                    "validation": _build_validation_report(
                        "edm",
                        validation,
                        minimum_viable_applied=edm_result["minimum_viable_applied"],
                        validation_scope=validation_scope,
                    ),
                }
            except Exception as exc:
                outputs["edm"] = {"ok": False, "error": str(exc)}

        if "iiif" in target_set:
            try:
                iiif_result = iiif_service.generate_iiif_manifest_with_report(
                    metadata=metadata,
                    zenodo_record=zenodo_record.copy(),
                    template_id=data.get("iiif_template_id"),
                    main_file_key=main_file_key or None,
                    validate=False,
                    additional_files=additional_files,
                    allow_placeholder_thumbnail=True,
                )
                json_output = iiif_result["content"]
                validation = iiif_service.validate_iiif_manifest(json_output)
                outputs["iiif"] = {
                    "ok": True,
                    "content": json_output,
                    "preview": _text_preview(json_output),
                    "minimum_viable_applied": iiif_result["minimum_viable_applied"],
                    "adjustments": iiif_result.get("adjustments", []),
                    "validation": _build_validation_report(
                        "iiif",
                        validation,
                        minimum_viable_applied=iiif_result["minimum_viable_applied"],
                    ),
                }
            except Exception as exc:
                outputs["iiif"] = {"ok": False, "error": str(exc)}

        if "mets" in target_set:
            try:
                mets_result = mets_service.generate_mets_xml_with_report(
                    metadata=metadata,
                    zenodo_record=zenodo_record.copy(),
                    template_id=data.get("mets_template_id"),
                    main_file_key=main_file_key or None,
                    validate=False,
                    additional_files=additional_files,
                    allow_placeholder_thumbnail=True,
                )
                xml_output = mets_result["content"]
                validation = mets_service.validate_mets_xml(xml_output)
                outputs["mets"] = {
                    "ok": True,
                    "content": xml_output,
                    "preview": _text_preview(xml_output),
                    "minimum_viable_applied": mets_result["minimum_viable_applied"],
                    "adjustments": mets_result.get("adjustments", []),
                    "validation": _build_validation_report(
                        "mets",
                        validation,
                        minimum_viable_applied=mets_result["minimum_viable_applied"],
                    ),
                }
            except Exception as exc:
                outputs["mets"] = {"ok": False, "error": str(exc)}

        return APIResponse.success(
            data={
                "row_index_used": int(row_index),
                "filename_column": filename_column,
                "main_file_key": main_file_key,
                "msf_profile": profile,
                "metadata": metadata,
                "outputs": outputs,
            },
            message="Output preview generated",
        )
    except ValueError as exc:
        return APIResponse.validation_error(str(exc))
    except Exception as exc:
        logger.error("Output preview failed: %s", exc, exc_info=True)
        return APIResponse.server_error(f"Output preview failed: {exc}")


@tools_bp.route("/hpc-diagnostics", methods=["GET"])
@jwt_required()
@require_admin
def hpc_diagnostics():
    try:
        storage_mode = CloudUploadService.get_storage_mode()
        services = _build_service_health()

        session_root = current_app.config.get("SHARED_SESSION_PATH", "/shared/sessions")
        local_input = current_app.config.get("LOCAL_INPUT_PATH", "/data/local_input")
        local_output = current_app.config.get("LOCAL_OUTPUT_PATH", "/data/local_output")

        path_stats: Dict[str, Any] = {}
        for path_name, path_value in {
            "session_root": session_root,
            "local_input": local_input,
            "local_output": local_output,
        }.items():
            exists = os.path.exists(path_value)
            stat_payload: Dict[str, Any] = {
                "path": path_value,
                "exists": exists,
            }
            if exists:
                try:
                    usage = os.statvfs(path_value)
                    total = usage.f_frsize * usage.f_blocks
                    free = usage.f_frsize * usage.f_bfree
                    stat_payload.update({"total_bytes": int(total), "free_bytes": int(free)})
                except Exception:
                    pass
            path_stats[path_name] = stat_payload

        session_count = DBSession.query.count()
        normalized_state_counts = _normalized_session_state_counts()
        live_count = sum(
            count
            for state, count in normalized_state_counts.items()
            if state not in TERMINAL_SESSION_STATES
        )

        db_file = current_app.config.get("SQLITE_PATH", "instance/hdp_web.db")
        if not os.path.isabs(db_file):
            db_file = os.path.join(current_app.root_path, db_file)

        return APIResponse.success(
            data={
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "storage_mode": storage_mode,
                "services": services,
                "paths": path_stats,
                "db": {
                    "path": db_file,
                    "exists": os.path.exists(db_file),
                    "size_bytes": os.path.getsize(db_file) if os.path.exists(db_file) else 0,
                },
                "sessions": {
                    "total": int(session_count),
                    "live": int(live_count),
                    # Compatibility field retained for older admin clients; value now reflects the
                    # canonical non-terminal workflow states instead of raw legacy statuses.
                    "active_or_processing": int(live_count),
                    "states": normalized_state_counts,
                },
            }
        )
    except Exception as exc:
        logger.error("Failed to load diagnostics: %s", exc, exc_info=True)
        return APIResponse.server_error(f"Failed to load diagnostics: {exc}")


@tools_bp.route("/session-cleanup/analyze", methods=["POST"])
@jwt_required()
@require_admin
def session_cleanup_analyze():
    try:
        data = request.get_json() or {}
        older_than_hours = float(data.get("older_than_hours", 72))
        if older_than_hours < 0:
            return APIResponse.validation_error("older_than_hours must be >= 0")

        now = datetime.utcnow()
        candidates: List[Dict[str, Any]] = []
        sessions = DBSession.query.order_by(DBSession.updated_at.asc()).all()
        for session in sessions:
            updated_at = session.updated_at or session.created_at or now
            age_hours = max(0.0, (now - updated_at).total_seconds() / 3600.0)
            session_dir = str(session.session_dir or "")
            dir_exists = bool(session_dir and os.path.isdir(session_dir))
            file_count = len(session.files or [])
            submission_count = len(session.submissions or [])

            reasons: List[str] = []
            if not dir_exists:
                reasons.append("missing_directory")
            if age_hours >= older_than_hours:
                reasons.append("older_than_threshold")
            if file_count == 0:
                reasons.append("no_uploaded_files")
            if submission_count == 0:
                reasons.append("no_submissions")

            is_candidate = (
                ("missing_directory" in reasons)
                or ("older_than_threshold" in reasons and file_count == 0 and submission_count == 0)
            )
            if not is_candidate:
                continue

            candidates.append(
                {
                    "session_id": int(session.id),
                    "status": session.status,
                    "session_dir": session_dir,
                    "directory_exists": dir_exists,
                    "age_hours": round(age_hours, 2),
                    "file_count": int(file_count),
                    "submission_count": int(submission_count),
                    "reasons": reasons,
                }
            )

        return APIResponse.success(
            data={
                "older_than_hours": older_than_hours,
                "candidate_count": len(candidates),
                "candidates": candidates,
            }
        )
    except Exception as exc:
        logger.error("Session cleanup analyze failed: %s", exc, exc_info=True)
        return APIResponse.server_error(f"Session cleanup analyze failed: {exc}")


@tools_bp.route("/session-cleanup/execute", methods=["POST"])
@jwt_required()
@require_admin
def session_cleanup_execute():
    try:
        data = request.get_json() or {}
        session_ids = data.get("session_ids") or []
        delete_directories = bool(data.get("delete_directories", True))

        if not isinstance(session_ids, list) or not session_ids:
            return APIResponse.validation_error("session_ids must be a non-empty list")

        normalized_ids: List[int] = []
        for item in session_ids:
            try:
                normalized_ids.append(int(item))
            except (TypeError, ValueError):
                return APIResponse.validation_error(f"Invalid session id: {item}")

        removed: List[int] = []
        missing: List[int] = []
        directory_errors: List[Dict[str, Any]] = []

        for session_id in sorted(set(normalized_ids)):
            session = db.session.get(DBSession, session_id)
            if not session:
                missing.append(session_id)
                continue

            session_dir = str(session.session_dir or "")
            if delete_directories and session_dir and os.path.isdir(session_dir):
                try:
                    import shutil

                    shutil.rmtree(session_dir)
                except Exception as exc:
                    directory_errors.append({"session_id": session_id, "error": str(exc)})

            db.session.delete(session)
            removed.append(session_id)

        db.session.commit()

        return APIResponse.success(
            data={
                "removed_session_ids": removed,
                "removed_count": len(removed),
                "missing_session_ids": missing,
                "directory_errors": directory_errors,
            },
            message="Session cleanup executed",
        )
    except Exception as exc:
        db.session.rollback()
        logger.error("Session cleanup execute failed: %s", exc, exc_info=True)
        return APIResponse.server_error(f"Session cleanup execute failed: {exc}")
