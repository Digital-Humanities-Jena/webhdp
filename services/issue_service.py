from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from database.database import db
from database.models import Issue, IssueComment, User
from exceptions import ResourceNotFoundError, SecurityError, ValidationError
from services.audit_service import record_audit_event
from services.issue_access_service import (
    can_assign_issues,
    can_comment_on_issue,
    can_edit_issue_internal_fields,
    can_view_issue,
    can_view_issue_queue,
    reporter_can_edit_issue,
)
from services.notification_service import notify_user, notify_users

logger = logging.getLogger(__name__)


ISSUE_TYPE_CHOICES = (
    {"value": "general", "label": "General bug"},
    {"value": "ui", "label": "UI / layout"},
    {"value": "workflow", "label": "Workflow / navigation"},
    {"value": "validation", "label": "Validation / data quality"},
    {"value": "data", "label": "Incorrect data"},
    {"value": "performance", "label": "Performance"},
    {"value": "auth", "label": "Authentication / access"},
    {"value": "docs", "label": "Documentation"},
    {"value": "feature_request", "label": "Feature request"},
)
REPORTER_IMPACT_CHOICES = (
    {"value": "low", "label": "Low"},
    {"value": "medium", "label": "Medium"},
    {"value": "high", "label": "High"},
    {"value": "blocking", "label": "Blocking"},
)
INTERNAL_PRIORITY_CHOICES = (
    {"value": "low", "label": "Low"},
    {"value": "medium", "label": "Medium"},
    {"value": "high", "label": "High"},
    {"value": "urgent", "label": "Urgent"},
)
STATUS_CHOICES = (
    {"value": "new", "label": "New"},
    {"value": "needs_info", "label": "Needs info"},
    {"value": "triaged", "label": "Triaged"},
    {"value": "in_progress", "label": "In progress"},
    {"value": "blocked", "label": "Blocked"},
    {"value": "resolved", "label": "Resolved"},
    {"value": "closed", "label": "Closed"},
)

_ISSUE_TYPE_VALUES = {item["value"] for item in ISSUE_TYPE_CHOICES}
_REPORTER_IMPACT_VALUES = {item["value"] for item in REPORTER_IMPACT_CHOICES}
_INTERNAL_PRIORITY_VALUES = {item["value"] for item in INTERNAL_PRIORITY_CHOICES}
_STATUS_VALUES = {item["value"] for item in STATUS_CHOICES}

_PUBLIC_EDITABLE_FIELDS = {
    "title",
    "issue_type",
    "reporter_impact",
    "page_key",
    "page_label",
    "route_name",
    "route_path",
    "current_url",
    "public_description",
    "expected_behavior",
    "technical_details",
    "reproduction_steps",
    "console_notes",
    "api_notes",
    "suspected_subsystem",
}
_REPORTER_EDITABLE_FIELDS = {
    "title",
    "issue_type",
    "reporter_impact",
    "page_key",
    "public_description",
    "expected_behavior",
    "technical_details",
    "reproduction_steps",
    "console_notes",
    "api_notes",
    "suspected_subsystem",
}
_JSON_FIELD_SETTERS = {
    "route_context": "set_route_context",
    "related_entity_ids": "set_related_entity_ids",
    "environment_context": "set_environment_context",
    "user_context": "set_user_context",
    "capture_context": "set_capture_context",
}
_INTERNAL_FIELDS = {"internal_priority", "status", "assignee_user_id"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _normalize_choice(value: Any, allowed: set[str], default: str) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return default
    if normalized not in allowed:
        raise ValidationError(f"Unsupported value: {value}")
    return normalized


def _normalize_optional_text(value: Any, *, max_length: int | None = None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if max_length is not None:
        return normalized[:max_length]
    return normalized


def _normalize_json_dict(value: Any) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return value
    raise ValidationError("Expected an object payload")


def get_application_version_info() -> dict[str, str]:
    version_file = _repo_root() / "version.json"
    if not version_file.exists():
        return {"version": "unknown", "timestamp": "unknown"}
    try:
        with version_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to read version.json: %s", exc)
        return {"version": "error", "timestamp": "error"}
    return {
        "version": str(payload.get("version") or "unknown"),
        "timestamp": str(payload.get("timestamp") or "unknown"),
    }


@lru_cache(maxsize=1)
def _load_registry_payload() -> dict[str, Any]:
    registry_path = _repo_root() / "shared" / "issues" / "page_registry.json"
    with registry_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    pages = payload.get("pages")
    if not isinstance(pages, list):
        raise ValidationError("Issue page registry is invalid")
    return payload


def list_registry_pages() -> list[dict[str, Any]]:
    payload = _load_registry_payload()
    pages = []
    for entry in payload.get("pages") or []:
        pages.append(
            {
                "page_key": entry.get("page_key"),
                "label": entry.get("label"),
                "route_name": entry.get("route_name"),
                "route_templates": list(entry.get("route_templates") or []),
                "allow_actual_route": bool(entry.get("allow_actual_route")),
            }
        )
    return sorted(pages, key=lambda item: str(item.get("label") or "").lower())


def list_assignable_issue_users(viewer: User) -> list[dict[str, Any]]:
    if not can_assign_issues(viewer):
        return []

    def _sort_key(user: User) -> tuple[int, str]:
        role_order = {
            "admin": 0,
            "moderator": 1,
            "user": 2,
        }
        role_value = user.role.value if user.role else "user"
        return (
            role_order.get(role_value, 99),
            str(user.email or "").lower(),
        )

    rows = [candidate for candidate in User.query.all() if can_view_issue_queue(candidate)]
    rows.sort(key=_sort_key)
    return [serialize_user_summary(candidate) for candidate in rows]


def _route_template_matches(template: str, route_path: str) -> bool:
    normalized_template = str(template or "").strip()
    normalized_route = str(route_path or "").strip()
    if not normalized_template or not normalized_route:
        return False
    pattern = re.sub(r":[A-Za-z0-9_]+", r"[^/]+", normalized_template)
    return re.fullmatch(pattern, normalized_route) is not None


def find_page_entry(*, page_key: str | None = None, route_name: str | None = None, route_path: str | None = None) -> dict[str, Any] | None:
    pages = _load_registry_payload().get("pages") or []
    normalized_page_key = str(page_key or "").strip().lower()
    normalized_route_name = str(route_name or "").strip()
    normalized_route_path = str(route_path or "").strip()

    if normalized_page_key:
        for entry in pages:
            if str(entry.get("page_key") or "").strip().lower() == normalized_page_key:
                return entry

    if normalized_route_name:
        for entry in pages:
            if str(entry.get("route_name") or "").strip() == normalized_route_name:
                return entry

    if normalized_route_path:
        for entry in pages:
            for template in entry.get("route_templates") or []:
                if _route_template_matches(str(template), normalized_route_path):
                    return entry
    return None


def _build_reference_item(*, label: str, kind: str, path_or_endpoint: str, score: int, reason: str) -> dict[str, Any]:
    return {
        "label": label,
        "kind": kind,
        "path_or_endpoint": path_or_endpoint,
        "score": int(score),
        "reason": reason,
    }


def _base_issue_payload(issue: Issue) -> dict[str, Any]:
    return {
        "title": issue.title,
        "issue_type": issue.issue_type,
        "page_key": issue.page_key,
        "route_name": issue.route_name,
        "route_path": issue.route_path,
        "public_description": issue.public_description,
        "expected_behavior": issue.expected_behavior,
        "technical_details": issue.technical_details,
        "reproduction_steps": issue.reproduction_steps,
        "console_notes": issue.console_notes,
        "api_notes": issue.api_notes,
        "suspected_subsystem": issue.suspected_subsystem,
        "route_context": issue.route_context,
        "related_entity_ids": issue.related_entity_ids,
    }


def build_code_references(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    entry = find_page_entry(
        page_key=payload.get("page_key"),
        route_name=payload.get("route_name"),
        route_path=payload.get("route_path"),
    )
    if not entry:
        return {"first_order": [], "second_order": [], "third_order": []}

    combined_text = " ".join(
        [
            str(payload.get("title") or ""),
            str(payload.get("public_description") or ""),
            str(payload.get("expected_behavior") or ""),
            str(payload.get("technical_details") or ""),
            str(payload.get("reproduction_steps") or ""),
            str(payload.get("console_notes") or ""),
            str(payload.get("api_notes") or ""),
            str(payload.get("suspected_subsystem") or ""),
            str(payload.get("route_path") or ""),
        ]
    ).lower()
    normalized_issue_type = str(payload.get("issue_type") or "general").strip().lower()
    route_context = payload.get("route_context") if isinstance(payload.get("route_context"), dict) else {}
    related_entity_ids = payload.get("related_entity_ids") if isinstance(payload.get("related_entity_ids"), dict) else {}
    route_params = route_context.get("params") if isinstance(route_context.get("params"), dict) else {}

    page_match_score = 35
    if str(entry.get("page_key") or "").strip().lower() == str(payload.get("page_key") or "").strip().lower():
        page_match_score = 50
    elif str(entry.get("route_name") or "").strip() == str(payload.get("route_name") or "").strip():
        page_match_score = 42

    issue_type_match = normalized_issue_type in {
        str(item or "").strip().lower() for item in (entry.get("issue_type_tags") or [])
    }
    keyword_matches = [
        keyword
        for keyword in (entry.get("keywords") or [])
        if str(keyword or "").strip().lower() in combined_text
    ]
    context_bonus = 0
    if entry.get("allow_actual_route") and str(payload.get("route_path") or "").strip():
        context_bonus += 4
    if route_params:
        context_bonus += min(len(route_params), 3) * 2
    if related_entity_ids:
        context_bonus += min(len(related_entity_ids), 3) * 2

    base_score = page_match_score + (15 if issue_type_match else 0) + min(len(keyword_matches) * 4, 16) + context_bonus
    shared_reason_parts = [f"Matched page '{entry.get('label')}'"]
    if issue_type_match:
        shared_reason_parts.append(f"issue type '{normalized_issue_type}' aligns with registry tags")
    if keyword_matches:
        shared_reason_parts.append(f"matched keywords: {', '.join(keyword_matches[:4])}")
    if route_params or related_entity_ids:
        shared_reason_parts.append("route/entity context matched dynamic page parameters")
    shared_reason = "; ".join(shared_reason_parts)

    seen: set[tuple[str, str]] = set()

    def _collect(items: list[dict[str, Any]], *, label_prefix: str, kind: str, values: list[str], score_offset: int) -> None:
        for value in values:
            normalized_value = str(value or "").strip()
            if not normalized_value:
                continue
            key = (kind, normalized_value)
            if key in seen:
                continue
            seen.add(key)
            if kind == "route" or normalized_value.startswith(("GET ", "POST ", "PUT ", "PATCH ", "DELETE ")):
                label_value = normalized_value
            elif "/" in normalized_value:
                label_value = Path(normalized_value).name
            else:
                label_value = normalized_value
            items.append(
                _build_reference_item(
                    label=f"{label_prefix}: {label_value}",
                    kind=kind,
                    path_or_endpoint=normalized_value,
                    score=base_score + score_offset,
                    reason=shared_reason,
                )
            )

    first_order: list[dict[str, Any]] = []
    second_order: list[dict[str, Any]] = []
    third_order: list[dict[str, Any]] = []

    actual_route = str(payload.get("route_path") or "").strip()
    route_reference = actual_route if actual_route and entry.get("allow_actual_route") else ", ".join(entry.get("route_templates") or [])
    if route_reference:
        _collect(first_order, label_prefix="Route", kind="route", values=[route_reference], score_offset=14)
    _collect(first_order, label_prefix="Frontend view", kind="frontend_view", values=list(entry.get("view_components") or []), score_offset=12)
    _collect(first_order, label_prefix="Frontend service", kind="frontend_service", values=list(entry.get("frontend_services") or []), score_offset=10)
    _collect(first_order, label_prefix="Frontend store", kind="frontend_store", values=list(entry.get("frontend_stores") or []), score_offset=9)
    _collect(first_order, label_prefix="API endpoint", kind="api_endpoint", values=list(entry.get("api_endpoints") or []), score_offset=11)

    second_order_values = list(entry.get("backend_route_modules") or []) + list(entry.get("backend_service_modules") or [])
    if ("sessionId" in route_params or "session_id" in related_entity_ids or "recordId" in route_params) and "routes/access_helpers.py" not in second_order_values:
        second_order_values.append("routes/access_helpers.py")
    if normalized_issue_type == "auth" and "routes/auth_routes.py" not in second_order_values:
        second_order_values.append("routes/auth_routes.py")
    _collect(
        second_order,
        label_prefix="Backend module",
        kind="backend_module",
        values=second_order_values,
        score_offset=7,
    )

    third_order_values = list(entry.get("related_tests") or []) + list(entry.get("adjacent_modules") or [])
    if related_entity_ids or route_params:
        third_order_values.append("database/models.py")
    _collect(third_order, label_prefix="Related asset", kind="related_asset", values=third_order_values, score_offset=3)

    return {
        "first_order": sorted(first_order, key=lambda item: (-int(item.get("score") or 0), str(item.get("path_or_endpoint") or ""))),
        "second_order": sorted(second_order, key=lambda item: (-int(item.get("score") or 0), str(item.get("path_or_endpoint") or ""))),
        "third_order": sorted(third_order, key=lambda item: (-int(item.get("score") or 0), str(item.get("path_or_endpoint") or ""))),
    }


def refresh_issue_code_references(issue: Issue) -> Issue:
    issue.set_code_references(build_code_references(_base_issue_payload(issue)))
    return issue


def serialize_user_summary(user: User | None) -> dict[str, Any] | None:
    if not user:
        return None
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "full_name": user.full_name,
        "role": user.role.value if user.role else "user",
        "groups": list(user.groups or []),
    }


def serialize_issue_comment(comment: IssueComment) -> dict[str, Any]:
    payload = comment.to_dict()
    payload["author"] = serialize_user_summary(comment.author)
    return payload


def serialize_issue(issue: Issue, viewer: User, *, include_comments: bool = False) -> dict[str, Any]:
    payload = issue.to_dict()
    triage_access = can_view_issue_queue(viewer)
    if not triage_access:
        payload["internal_priority"] = None
        payload["code_references"] = {"first_order": [], "second_order": [], "third_order": []}
    payload["reporter"] = serialize_user_summary(issue.reporter)
    payload["assignee"] = serialize_user_summary(issue.assignee)
    payload["permissions"] = {
        "can_view_issue_queue": triage_access,
        "can_edit_internal_fields": can_edit_issue_internal_fields(viewer),
        "can_assign_issues": can_assign_issues(viewer),
        "can_reporter_edit": reporter_can_edit_issue(issue, viewer),
        "can_comment_public": can_comment_on_issue(issue, viewer, is_internal=False),
        "can_comment_internal": can_comment_on_issue(issue, viewer, is_internal=True),
        "is_reporter": int(issue.reporter_user_id) == int(viewer.id),
    }
    if include_comments:
        payload["comments"] = [
            serialize_issue_comment(comment)
            for comment in (issue.comments or [])
            if triage_access or not comment.is_internal
        ]
    return payload


def _apply_public_fields(
    issue: Issue,
    payload: dict[str, Any],
    *,
    allowed_fields: set[str] | None = None,
    allowed_json_fields: set[str] | None = None,
) -> list[str]:
    allowed_public_fields = allowed_fields if allowed_fields is not None else _PUBLIC_EDITABLE_FIELDS
    allowed_context_fields = allowed_json_fields if allowed_json_fields is not None else set(_JSON_FIELD_SETTERS)
    changed_fields: list[str] = []
    for field in allowed_public_fields:
        if field not in payload:
            continue
        value = payload.get(field)
        if field == "title":
            normalized_value = _normalize_optional_text(value, max_length=255)
            if not normalized_value:
                raise ValidationError("title is required")
        elif field == "issue_type":
            normalized_value = _normalize_choice(value, _ISSUE_TYPE_VALUES, "general")
        elif field == "reporter_impact":
            normalized_value = _normalize_choice(value, _REPORTER_IMPACT_VALUES, "medium")
        elif field in {"page_key", "route_name", "suspected_subsystem"}:
            normalized_value = _normalize_optional_text(value, max_length=120)
        elif field == "page_label":
            normalized_value = _normalize_optional_text(value, max_length=255)
        elif field == "route_path":
            normalized_value = _normalize_optional_text(value, max_length=255)
        elif field == "current_url":
            normalized_value = _normalize_optional_text(value, max_length=512)
        else:
            normalized_value = _normalize_optional_text(value)

        if getattr(issue, field) != normalized_value:
            setattr(issue, field, normalized_value)
            changed_fields.append(field)

    for payload_field, setter_name in _JSON_FIELD_SETTERS.items():
        if payload_field not in allowed_context_fields:
            continue
        if payload_field not in payload:
            continue
        normalized_value = _normalize_json_dict(payload.get(payload_field))
        current_value = getattr(issue, payload_field, None)
        if current_value != normalized_value:
            getattr(issue, setter_name)(normalized_value)
            changed_fields.append(payload_field)

    page_entry = find_page_entry(page_key=issue.page_key, route_name=issue.route_name, route_path=issue.route_path)
    if page_entry:
        if issue.page_key != page_entry.get("page_key"):
            issue.page_key = page_entry.get("page_key")
            changed_fields.append("page_key")
        if issue.page_label != page_entry.get("label"):
            issue.page_label = page_entry.get("label")
            changed_fields.append("page_label")

    return changed_fields


def _apply_internal_fields(issue: Issue, payload: dict[str, Any]) -> list[str]:
    changed_fields: list[str] = []
    if "internal_priority" in payload:
        normalized_priority = _normalize_choice(payload.get("internal_priority"), _INTERNAL_PRIORITY_VALUES, issue.internal_priority or "medium")
        if issue.internal_priority != normalized_priority:
            issue.internal_priority = normalized_priority
            changed_fields.append("internal_priority")

    if "status" in payload:
        previous_status = str(issue.status or "new").strip().lower()
        normalized_status = _normalize_choice(payload.get("status"), _STATUS_VALUES, previous_status or "new")
        if issue.status != normalized_status:
            issue.status = normalized_status
            changed_fields.append("status")
            now = datetime.utcnow()
            if normalized_status == "resolved":
                issue.resolved_at = now
                issue.closed_at = None
            elif normalized_status == "closed":
                issue.closed_at = now
                issue.resolved_at = issue.resolved_at or now
            else:
                issue.resolved_at = None
                issue.closed_at = None

    if "assignee_user_id" in payload:
        raw_assignee = payload.get("assignee_user_id")
        if raw_assignee in ("", None):
            normalized_assignee = None
        else:
            try:
                normalized_assignee = int(raw_assignee)
            except (TypeError, ValueError) as exc:
                raise ValidationError("assignee_user_id must be an integer") from exc
            assignee_user = db.session.get(User, normalized_assignee)
            if not assignee_user:
                raise ValidationError("Assignee user was not found")
            if not can_view_issue_queue(assignee_user):
                raise ValidationError("Assignee must have issue triage access")
        if issue.assignee_user_id != normalized_assignee:
            issue.assignee_user_id = normalized_assignee
            changed_fields.append("assignee_user_id")

    return changed_fields


def create_issue(reporter: User, payload: dict[str, Any]) -> Issue:
    issue = Issue(
        reporter_user_id=int(reporter.id),
        status="new",
        internal_priority="medium",
        issue_type="general",
        reporter_impact="medium",
    )
    public_changes = _apply_public_fields(issue, payload or {})
    if not issue.title:
        raise ValidationError("title is required")
    if not issue.public_description:
        raise ValidationError("public_description is required")
    if not issue.page_key and not issue.route_path:
        raise ValidationError("page_key or route_path is required")

    issue.set_user_context(
        {
            **issue.user_context,
            "reporter_id": int(reporter.id),
            "reporter_role": reporter.role.value if reporter.role else "user",
            "reporter_groups": list(reporter.groups or []),
        }
    )
    refresh_issue_code_references(issue)

    db.session.add(issue)
    db.session.flush()
    record_audit_event(
        actor_user_id=reporter.id,
        event_type="issue_created",
        entity_type="issue",
        entity_id=issue.id,
        details={
            "title": issue.title,
            "page_key": issue.page_key,
            "changed_fields": public_changes,
        },
    )
    db.session.commit()
    return issue


def get_issue_or_404(issue_id: int, viewer: User) -> Issue:
    issue = db.session.get(Issue, int(issue_id))
    if not issue or not can_view_issue(issue, viewer):
        raise ResourceNotFoundError("Issue not found")
    return issue


def list_issues(viewer: User, *, scope: str = "my", status: str | None = None, page_key: str | None = None) -> dict[str, Any]:
    normalized_scope = str(scope or "my").strip().lower()
    query = Issue.query

    if can_view_issue_queue(viewer):
        if normalized_scope == "my":
            query = query.filter(Issue.reporter_user_id == int(viewer.id))
        elif normalized_scope not in {"queue", "all"}:
            normalized_scope = "queue"
    else:
        normalized_scope = "my"
        query = query.filter(Issue.reporter_user_id == int(viewer.id))

    if status:
        normalized_status = _normalize_choice(status, _STATUS_VALUES, "new")
        query = query.filter(Issue.status == normalized_status)
    if page_key:
        query = query.filter(Issue.page_key == str(page_key).strip())

    rows = query.order_by(Issue.updated_at.desc(), Issue.id.desc()).all()
    return {
        "issues": [serialize_issue(issue, viewer, include_comments=False) for issue in rows],
        "filters": {
            "scope": normalized_scope,
            "status": str(status or "").strip().lower() or None,
            "page_key": str(page_key or "").strip() or None,
        },
        "permissions": {
            "can_view_issue_queue": can_view_issue_queue(viewer),
            "can_edit_internal_fields": can_edit_issue_internal_fields(viewer),
            "can_assign_issues": can_assign_issues(viewer),
        },
    }


def update_issue(issue: Issue, actor: User, payload: dict[str, Any]) -> Issue:
    if not isinstance(payload, dict):
        raise ValidationError("Invalid issue update payload")

    triage_access = can_edit_issue_internal_fields(actor)
    reporter_access = reporter_can_edit_issue(issue, actor)
    if not triage_access and not reporter_access:
        raise SecurityError("You cannot update this issue")

    if not triage_access and any(field in payload for field in _INTERNAL_FIELDS):
        raise SecurityError("Only triage users can update internal issue fields")
    if not triage_access:
        restricted_public_fields = (_PUBLIC_EDITABLE_FIELDS - _REPORTER_EDITABLE_FIELDS) | set(_JSON_FIELD_SETTERS)
        if any(field in payload for field in restricted_public_fields):
            raise SecurityError("Only triage users can update captured context fields")

    public_changes = _apply_public_fields(
        issue,
        payload,
        allowed_fields=_PUBLIC_EDITABLE_FIELDS if triage_access else _REPORTER_EDITABLE_FIELDS,
        allowed_json_fields=set(_JSON_FIELD_SETTERS) if triage_access else set(),
    )
    internal_changes = _apply_internal_fields(issue, payload) if triage_access else []

    if not public_changes and not internal_changes:
        return issue

    refresh_issue_code_references(issue)
    db.session.flush()

    if "status" in internal_changes:
        record_audit_event(
            actor_user_id=actor.id,
            event_type="issue_status_changed",
            entity_type="issue",
            entity_id=issue.id,
            details={"status": issue.status},
        )
    if "assignee_user_id" in internal_changes:
        record_audit_event(
            actor_user_id=actor.id,
            event_type="issue_assigned",
            entity_type="issue",
            entity_id=issue.id,
            details={"assignee_user_id": issue.assignee_user_id},
        )
        if issue.assignee_user_id and int(issue.assignee_user_id) != int(actor.id):
            notify_user(
                recipient_user_id=issue.assignee_user_id,
                actor_user_id=actor.id,
                notification_type="issue.assigned",
                severity="info",
                title="Issue assigned to you",
                body=issue.title,
                entity_type="issue",
                entity_id=issue.id,
                action_url=f"/issues/{issue.id}",
                payload={"issue_id": issue.id, "status": issue.status},
            )
    if "status" in internal_changes and int(issue.reporter_user_id) != int(actor.id):
        notify_user(
            recipient_user_id=issue.reporter_user_id,
            actor_user_id=actor.id,
            notification_type="issue.status_changed",
            severity="info",
            title=f"Issue status changed to {issue.status.replace('_', ' ')}",
            body=issue.title,
            entity_type="issue",
            entity_id=issue.id,
            action_url=f"/issues/{issue.id}",
            payload={"issue_id": issue.id, "status": issue.status},
        )
    if public_changes or internal_changes:
        record_audit_event(
            actor_user_id=actor.id,
            event_type="issue_updated",
            entity_type="issue",
            entity_id=issue.id,
            details={"changed_fields": public_changes + internal_changes},
        )

    db.session.commit()
    return issue


def add_issue_comment(issue: Issue, actor: User, *, body: Any, is_internal: Any = False) -> IssueComment:
    normalized_body = _normalize_optional_text(body)
    if not normalized_body:
        raise ValidationError("body is required")
    internal_flag = bool(is_internal)
    if not can_comment_on_issue(issue, actor, is_internal=internal_flag):
        raise SecurityError("You cannot comment on this issue")

    comment = IssueComment(
        issue_id=int(issue.id),
        author_user_id=int(actor.id),
        body=normalized_body,
        is_internal=internal_flag,
    )
    db.session.add(comment)
    issue.updated_at = datetime.utcnow()
    db.session.flush()
    record_audit_event(
        actor_user_id=actor.id,
        event_type="issue_comment_added",
        entity_type="issue",
        entity_id=issue.id,
        details={"comment_id": comment.id, "is_internal": internal_flag},
    )
    recipient_ids = []
    for candidate in (issue.reporter, issue.assignee):
        if not candidate or int(candidate.id) == int(actor.id):
            continue
        if internal_flag and not can_view_issue_queue(candidate):
            continue
        recipient_ids.append(candidate.id)
    notify_users(
        recipient_user_ids=recipient_ids,
        actor_user_id=actor.id,
        notification_type="issue.commented",
        severity="info",
        title="New issue comment",
        body=issue.title,
        entity_type="issue",
        entity_id=issue.id,
        action_url=f"/issues/{issue.id}",
        payload={"issue_id": issue.id, "comment_id": comment.id, "is_internal": internal_flag},
    )
    db.session.commit()
    return comment


def refresh_issue_references(issue: Issue, actor: User) -> Issue:
    if not can_edit_issue_internal_fields(actor):
        raise SecurityError("Only triage users can refresh code references")
    refresh_issue_code_references(issue)
    issue.updated_at = datetime.utcnow()
    db.session.flush()
    record_audit_event(
        actor_user_id=actor.id,
        event_type="issue_code_references_refreshed",
        entity_type="issue",
        entity_id=issue.id,
        details={"page_key": issue.page_key},
    )
    db.session.commit()
    return issue
