import json
from typing import Any

from database.database import db
from database.models import AuditEvent


def record_audit_event(
    *,
    actor_user_id: int | None,
    event_type: str,
    entity_type: str,
    entity_id: str | int | None = None,
    institution_id: int | None = None,
    session_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_user_id=actor_user_id,
        institution_id=institution_id,
        session_id=session_id,
        event_type=str(event_type or "").strip(),
        entity_type=str(entity_type or "").strip(),
        entity_id=str(entity_id) if entity_id is not None else None,
        details_json=json.dumps(details or {}, sort_keys=True),
    )
    db.session.add(event)
    return event


def serialize_audit_event(event: AuditEvent) -> dict[str, Any]:
    payload = event.to_dict()
    actor = getattr(event, "actor", None)
    payload["actor"] = (
        {
            "id": actor.id,
            "email": actor.email,
            "display_name": actor.display_name,
            "full_name": actor.full_name,
            "role": actor.role.value if actor.role else None,
        }
        if actor
        else None
    )
    return payload


def list_audit_events(
    *,
    institution_id: int | None = None,
    session_id: int | None = None,
    event_type: str | None = None,
    entity_type: str | None = None,
    page: int = 1,
    per_page: int = 25,
) -> dict[str, Any]:
    normalized_page = max(int(page or 1), 1)
    normalized_per_page = min(max(int(per_page or 25), 1), 100)

    query = AuditEvent.query
    if institution_id is not None:
        query = query.filter(AuditEvent.institution_id == int(institution_id))
    if session_id is not None:
        query = query.filter(AuditEvent.session_id == int(session_id))
    normalized_event_type = str(event_type or "").strip()
    if normalized_event_type:
        query = query.filter(AuditEvent.event_type == normalized_event_type)
    normalized_entity_type = str(entity_type or "").strip()
    if normalized_entity_type:
        query = query.filter(AuditEvent.entity_type == normalized_entity_type)

    total = query.count()
    rows = (
        query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .offset((normalized_page - 1) * normalized_per_page)
        .limit(normalized_per_page)
        .all()
    )
    return {
        "audit_events": [serialize_audit_event(row) for row in rows],
        "pagination": {
            "page": normalized_page,
            "per_page": normalized_per_page,
            "total": total,
            "pages": max((total + normalized_per_page - 1) // normalized_per_page, 1),
        },
        "filters": {
            "institution_id": int(institution_id) if institution_id is not None else None,
            "session_id": int(session_id) if session_id is not None else None,
            "event_type": normalized_event_type or None,
            "entity_type": normalized_entity_type or None,
        },
    }
