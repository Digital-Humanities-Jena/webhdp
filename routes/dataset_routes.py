from collections import defaultdict
from dataclasses import replace

from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from api_utils import APIResponse
from database.database import db
from database.models import Session as DBSession, User
from routes.access_helpers import get_current_user_from_jwt
from services.dataset_integrity_service import (
    CandidateFile,
    PRIMARY_CSV_COLUMNS,
    build_dataset_export_bundle,
    build_dataset_summary,
    build_duplicate_check_payload,
    build_duplicate_groups,
    collect_dataset_records,
    collect_dataset_workspaces,
    collect_records_for_dataset,
    extract_dataset_key,
    filter_records_by_environment,
    normalize_dataset_key,
    normalize_dataset_key_lower,
    normalize_environment,
    normalize_source_path,
    scan_candidate_files_for_session,
    scope_dataset_workspace,
)
from services.session_access_service import can_view_session, get_accessible_sessions


dataset_bp = Blueprint("datasets", __name__)


def _is_privileged(user: User | None) -> bool:
    return bool(user and getattr(user, "role", None) and getattr(user.role, "value", None) in {"admin", "moderator"})


def _load_user_session_or_404(user: User | None, session_id: int, *, include_privileged: bool = True) -> DBSession | None:
    session_row = db.session.get(DBSession, session_id)
    if not session_row:
        return None
    if not user:
        return None
    if session_row.user_id == user.id:
        return session_row
    if include_privileged and can_view_session(session_row, user):
        return session_row
    return None


def _visible_session_ids_for_user(user: User | None) -> set[int]:
    if not user:
        return set()
    if _is_privileged(user):
        return {session_row.id for session_row in DBSession.query.all()}
    return {session_row.id for session_row in get_accessible_sessions(user, scope="all")}


def _build_dataset_catalog(user_id: int, *, include_all_sessions: bool) -> list[dict]:
    environment = normalize_environment(request.args.get("environment"), default="production")
    workspaces = collect_dataset_workspaces(
        None if include_all_sessions else user_id,
        include_all_sessions=include_all_sessions,
    )
    catalog = []
    for workspace in workspaces.values():
        if environment != "all" and environment not in workspace["available_environments"]:
            continue
        scoped = scope_dataset_workspace(workspace, environment)
        summary = build_dataset_summary(scoped["dataset_key"], scoped["records"], sessions=scoped["sessions"])
        summary["available_environments"] = scoped["available_environments"]
        summary["empty_reason"] = scoped["empty_reason"]
        catalog.append(summary)
    catalog.sort(
        key=lambda item: (
            item.get("published_source_path_count", 0),
            item.get("source_path_count", 0),
            normalize_dataset_key_lower(item.get("dataset_key")),
        ),
        reverse=True,
    )
    return catalog


def _load_dataset_workspace(user: User, dataset_key: str, environment: str) -> dict | None:
    workspaces = collect_dataset_workspaces(
        None if _is_privileged(user) else user.id,
        include_all_sessions=_is_privileged(user),
    )
    workspace = workspaces.get(normalize_dataset_key_lower(dataset_key))
    return scope_dataset_workspace(workspace, environment) if workspace is not None else None


def _parse_int_arg(value: object, *, default: int, minimum: int = 1, maximum: int = 100) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def _normalize_path_filter(dataset_key: str, raw_path: object) -> str:
    text = str(raw_path or "").strip()
    if not text:
        return ""
    return normalize_source_path(text, dataset_key)


def _filter_duplicate_groups_by_path(
    dataset_key: str,
    groups: list[dict[str, object]],
    raw_path: object,
) -> tuple[list[dict[str, object]], str]:
    normalized_path = _normalize_path_filter(dataset_key, raw_path)
    if not normalized_path:
        return groups, ""
    filtered = [
        group
        for group in groups
        if str(group.get("normalized_source_file_path") or "").strip().lower() == normalized_path.lower()
    ]
    return filtered, normalized_path


def _attach_owner_context(groups: list[dict[str, object]]) -> list[dict[str, object]]:
    user_ids: set[int] = set()
    for group in groups:
        for record in group.get("records") or []:
            if not isinstance(record, dict):
                continue
            try:
                user_ids.add(int(record.get("session_user_id") or 0))
            except (TypeError, ValueError):
                continue

    user_map = {
        user.id: {"email": user.email, "role": user.role.value if getattr(user, "role", None) else None}
        for user in User.query.filter(User.id.in_(user_ids)).all()
    } if user_ids else {}

    enriched_groups: list[dict[str, object]] = []
    for group in groups:
        enriched_group = dict(group)
        affected_users: dict[int, dict[str, object]] = {}
        enriched_records = []
        for record in group.get("records") or []:
            if not isinstance(record, dict):
                continue
            enriched_record = dict(record)
            try:
                owner_id = int(record.get("session_user_id") or 0)
            except (TypeError, ValueError):
                owner_id = 0
            if owner_id and owner_id in user_map:
                owner_meta = user_map[owner_id]
                enriched_record["session_owner_email"] = owner_meta.get("email")
                enriched_record["session_owner_role"] = owner_meta.get("role")
                affected_users[owner_id] = {
                    "user_id": owner_id,
                    "email": owner_meta.get("email"),
                    "role": owner_meta.get("role"),
                }
            enriched_records.append(enriched_record)
        enriched_group["records"] = enriched_records
        enriched_group["affected_users"] = sorted(affected_users.values(), key=lambda item: str(item.get("email") or ""))
        enriched_group["affected_user_count"] = len(affected_users)
        enriched_groups.append(enriched_group)
    return enriched_groups


def _can_view_duplicate_record(user: User | None, visible_session_ids: set[int], record: dict[str, object]) -> bool:
    if _is_privileged(user):
        return True
    try:
        return int(record.get("session_id") or 0) in visible_session_ids
    except (TypeError, ValueError):
        return False


def _sanitize_duplicate_result(
    user: User | None,
    visible_session_ids: set[int],
    result: dict[str, object],
) -> dict[str, object]:
    matched_records = result.get("matched_records") or []
    visible_matches = [
        item
        for item in matched_records
        if isinstance(item, dict) and _can_view_duplicate_record(user, visible_session_ids, item)
    ]
    hidden_count = max(len(matched_records) - len(visible_matches), 0)
    sanitized_matches = []
    for item in visible_matches:
        sanitized_matches.append(
            {
                "session_id": item.get("session_id"),
                "local_record_id": item.get("local_record_id"),
                "record_status": item.get("record_status"),
                "zenodo_doi": item.get("zenodo_doi"),
                "record_link": item.get("record_link"),
                "concept_rec_id": item.get("concept_rec_id"),
                "record_title": item.get("record_title"),
                "normalized_source_file_path": item.get("normalized_source_file_path"),
                "is_sandbox": item.get("is_sandbox"),
            }
        )

    recommended_action = result.get("recommended_action")
    if hidden_count and not sanitized_matches and result.get("classification") != "clean":
        recommended_action = "A conflicting record exists outside your visible scope. Contact an administrator if you need lineage details."

    sanitized = dict(result)
    sanitized["matched_records"] = sanitized_matches
    sanitized["visible_matched_record_count"] = len(sanitized_matches)
    sanitized["hidden_matched_record_count"] = hidden_count
    sanitized["recommended_action"] = recommended_action
    return sanitized


def _sanitize_duplicate_payload(user: User | None, payload: dict[str, object]) -> dict[str, object]:
    visible_session_ids = _visible_session_ids_for_user(user)
    sanitized = dict(payload)
    sanitized["results"] = [
        _sanitize_duplicate_result(user, visible_session_ids, item)
        for item in (payload.get("results") or [])
        if isinstance(item, dict)
    ]
    return sanitized


@dataset_bp.route("", methods=["GET"])
@jwt_required()
def list_datasets():
    user = get_current_user_from_jwt()
    if not user:
        return APIResponse.unauthorized()
    catalog = _build_dataset_catalog(user.id, include_all_sessions=_is_privileged(user))
    return APIResponse.success(
        data={
            "datasets": catalog,
            "environment": normalize_environment(request.args.get("environment"), default="production"),
        }
    )


@dataset_bp.route("/conflict-review", methods=["GET"])
@jwt_required()
def get_conflict_review():
    user = get_current_user_from_jwt()
    if not user:
        return APIResponse.unauthorized()
    if not _is_privileged(user):
        return APIResponse.forbidden("Administrator or moderator access is required")

    environment = normalize_environment(request.args.get("environment"), default="production")
    dataset_filter = normalize_dataset_key(request.args.get("dataset_key"))
    raw_path_filter = request.args.get("path")
    limit = _parse_int_arg(request.args.get("limit"), default=25, maximum=100)
    preview_group_limit = _parse_int_arg(request.args.get("group_limit"), default=3, maximum=10)

    all_records, _ = collect_dataset_records(None, include_all_sessions=True)
    scoped_records = filter_records_by_environment(all_records, environment)
    by_dataset: dict[str, list[dict]] = defaultdict(list)
    for record in scoped_records:
        dataset_key = normalize_dataset_key(record.get("dataset_key"))
        if not dataset_key:
            continue
        if dataset_filter and normalize_dataset_key_lower(dataset_key) != normalize_dataset_key_lower(dataset_filter):
            continue
        by_dataset[dataset_key].append(record)

    dataset_items = []
    total_group_count = 0
    for current_dataset_key, dataset_records in by_dataset.items():
        groups = build_duplicate_groups(current_dataset_key, dataset_records)
        groups, normalized_path_filter = _filter_duplicate_groups_by_path(current_dataset_key, groups, raw_path_filter)
        if not groups:
            continue
        groups = _attach_owner_context(groups)
        summary = build_dataset_summary(current_dataset_key, dataset_records)
        total_group_count += len(groups)

        affected_users: dict[int, dict[str, object]] = {}
        for group in groups:
            for user_meta in group.get("affected_users") or []:
                if not isinstance(user_meta, dict):
                    continue
                try:
                    affected_users[int(user_meta.get("user_id") or 0)] = user_meta
                except (TypeError, ValueError):
                    continue

        dataset_items.append(
            {
                "dataset_key": current_dataset_key,
                "environment": environment,
                "authoritative_session_id": summary.get("authoritative_session_id"),
                "duplicate_group_count": len(groups),
                "duplicate_published_source_path_count": summary.get("duplicate_published_source_path_count", 0),
                "affected_users": sorted(affected_users.values(), key=lambda item: str(item.get("email") or "")),
                "affected_user_count": len(affected_users),
                "path_filter": normalized_path_filter or None,
                "groups_preview": groups[:preview_group_limit],
                "has_more_groups": len(groups) > preview_group_limit,
            }
        )

    dataset_items.sort(
        key=lambda item: (
            int(item.get("duplicate_published_source_path_count") or 0),
            int(item.get("duplicate_group_count") or 0),
            normalize_dataset_key_lower(item.get("dataset_key")),
        ),
        reverse=True,
    )
    return APIResponse.success(
        data={
            "environment": environment,
            "dataset_count": len(dataset_items),
            "duplicate_group_count": total_group_count,
            "datasets": dataset_items[:limit],
            "path_filter": raw_path_filter or None,
        }
    )


@dataset_bp.route("/<path:dataset_key>/summary", methods=["GET"])
@jwt_required()
def get_dataset_summary(dataset_key: str):
    user = get_current_user_from_jwt()
    if not user:
        return APIResponse.unauthorized()
    normalized_dataset_key = normalize_dataset_key(dataset_key)
    environment = normalize_environment(request.args.get("environment"), default="production")
    workspace = _load_dataset_workspace(user, normalized_dataset_key, environment)
    if workspace is None:
        return APIResponse.not_found("Dataset not found")
    summary = build_dataset_summary(normalized_dataset_key, workspace["records"], sessions=workspace["sessions"])
    summary["environment"] = environment
    summary["available_environments"] = workspace["available_environments"]
    summary["empty_reason"] = workspace["empty_reason"]
    return APIResponse.success(data=summary)


@dataset_bp.route("/<path:dataset_key>/duplicates", methods=["GET"])
@jwt_required()
def get_dataset_duplicates(dataset_key: str):
    user = get_current_user_from_jwt()
    if not user:
        return APIResponse.unauthorized()
    normalized_dataset_key = normalize_dataset_key(dataset_key)
    environment = normalize_environment(request.args.get("environment"), default="production")
    workspace = _load_dataset_workspace(user, normalized_dataset_key, environment)
    if workspace is None:
        return APIResponse.not_found("Dataset not found")
    records = workspace["records"]
    groups = build_duplicate_groups(normalized_dataset_key, records)
    groups, normalized_path_filter = _filter_duplicate_groups_by_path(
        normalized_dataset_key,
        groups,
        request.args.get("path"),
    )
    if _is_privileged(user):
        groups = _attach_owner_context(groups)
    summary = build_dataset_summary(normalized_dataset_key, records)
    return APIResponse.success(
        data={
            "dataset_key": normalized_dataset_key,
            "environment": environment,
            "available_environments": workspace["available_environments"],
            "empty_reason": workspace["empty_reason"],
            "authoritative_session_id": summary.get("authoritative_session_id"),
            "path_filter": normalized_path_filter or None,
            "group_count": len(groups),
            "groups": groups,
        }
    )


@dataset_bp.route("/duplicate-check", methods=["POST"])
@jwt_required()
def duplicate_check():
    user = get_current_user_from_jwt()
    if not user:
        return APIResponse.unauthorized()
    data = request.get_json() or {}
    session_id = data.get("session_id")
    is_sandbox = bool(data.get("is_sandbox", False))
    environment = normalize_environment(data.get("environment"), default="sandbox" if is_sandbox else "production")
    dataset_key = normalize_dataset_key(data.get("dataset_key"))
    concept_rec_id = str(data.get("concept_rec_id") or "").strip()

    candidates: list[CandidateFile] = []
    if session_id is not None:
        session_row = _load_user_session_or_404(user, int(session_id))
        if not session_row:
            return APIResponse.not_found("Session not found")
        inferred_candidates = scan_candidate_files_for_session(session_row)
        if "is_sandbox" in data or "environment" in data:
            inferred_candidates = [
                replace(candidate, is_sandbox=environment == "sandbox")
                for candidate in inferred_candidates
            ]
        if not dataset_key and inferred_candidates:
            dataset_key = normalize_dataset_key(inferred_candidates[0].dataset_key)
        candidates.extend(inferred_candidates)

    raw_candidates = data.get("candidate_files") or []
    if raw_candidates and not isinstance(raw_candidates, list):
        return APIResponse.validation_error("candidate_files must be a list")

    for item in raw_candidates:
        if not isinstance(item, dict):
            continue
        source_file_path = str(item.get("source_file_path") or item.get("path") or "").strip()
        if not source_file_path:
            continue
        candidate_dataset_key = normalize_dataset_key(
            item.get("dataset_key") or dataset_key or extract_dataset_key(source_file_path)
        )
        if not candidate_dataset_key:
            continue
        candidates.append(
            CandidateFile(
                source_file_path=source_file_path,
                source_file_name=str(item.get("source_file_name") or item.get("filename") or source_file_path.split("/")[-1]),
                dataset_key=candidate_dataset_key,
                normalized_source_file_path=normalize_source_path(source_file_path, candidate_dataset_key),
                is_sandbox=bool(item.get("is_sandbox", environment == "sandbox" or is_sandbox)),
                concept_rec_id=str(item.get("concept_rec_id") or concept_rec_id).strip(),
                sha256_hash=str(item.get("sha256_hash") or "").strip(),
            )
        )

    if not candidates:
        return APIResponse.validation_error(
            "No candidate files were supplied and no candidate files could be inferred from the prepared session."
        )

    if not dataset_key:
        dataset_key = normalize_dataset_key(candidates[0].dataset_key)
    if not dataset_key:
        return APIResponse.validation_error("dataset_key could not be inferred for duplicate detection")

    records, _ = collect_records_for_dataset(dataset_key, include_all_sessions=True, environment=environment)
    payload = build_duplicate_check_payload(candidates, records)
    payload["dataset_key"] = dataset_key
    payload["environment"] = environment
    return APIResponse.success(data=_sanitize_duplicate_payload(user, payload))


@dataset_bp.route("/<path:dataset_key>/export", methods=["POST"])
@jwt_required()
def export_dataset(dataset_key: str):
    user = get_current_user_from_jwt()
    if not user:
        return APIResponse.unauthorized()
    normalized_dataset_key = normalize_dataset_key(dataset_key)
    data = request.get_json() or {}
    environment = normalize_environment(data.get("environment"), default="production")
    export_format = str(data.get("format") or "bundle").strip().lower()
    if export_format not in {"bundle", "json", "csv"}:
        return APIResponse.validation_error("format must be one of bundle, json, or csv")

    authoritative_session_id = data.get("authoritative_session_id")
    if authoritative_session_id is not None:
        try:
            authoritative_session_id = int(authoritative_session_id)
        except (TypeError, ValueError):
            return APIResponse.validation_error("authoritative_session_id must be an integer")

    workspace = _load_dataset_workspace(user, normalized_dataset_key, environment)
    if workspace is None:
        return APIResponse.not_found("Dataset not found")
    records = workspace["records"]

    bundle = build_dataset_export_bundle(
        normalized_dataset_key,
        records,
        authoritative_session_id=authoritative_session_id,
    )
    response_data = {
        "dataset_key": normalized_dataset_key,
        "environment": environment,
        "available_environments": workspace["available_environments"],
        "empty_reason": workspace["empty_reason"],
        "authoritative_session_id": bundle["authoritative_session_id"],
    }
    if export_format in {"bundle", "json"}:
        response_data["primary_json"] = bundle["primary"]["json_payload"]
        response_data["secondary_json"] = bundle["secondary"]["json_payload"]
    if export_format in {"bundle", "csv"}:
        response_data["primary_csv"] = bundle["primary"]["csv_text"]
        response_data["secondary_csv"] = bundle["secondary"]["csv_text"]
        response_data["csv_columns"] = list(PRIMARY_CSV_COLUMNS)
    response_data["primary_record_count"] = bundle["primary"]["record_count"]
    response_data["secondary_record_count"] = bundle["secondary"]["record_count"]
    return APIResponse.success(data=response_data)
