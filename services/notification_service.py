from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Iterable

from flask import current_app, has_app_context
from sqlalchemy import and_, func, or_

from database.database import db
from database.models import Notification, NotificationDelivery, NotificationPreference, User, UserRole
from exceptions import ResourceNotFoundError, SecurityError, ValidationError


VALID_SEVERITIES = {"info", "success", "warning", "error"}
VALID_STATES = {"all", "unread", "archived"}
NOTIFICATION_CATEGORIES = {
    "issues": "Issues",
    "credentials": "Credential shares",
    "jobs": "Jobs and pipelines",
    "hpc": "HPC allocations",
    "datasets": "Dataset integrity",
    "profiles": "Profiles and institutions",
    "zenodo": "Zenodo retrieval",
    "admin": "Admin observability",
    "system": "System",
}
TYPE_CATEGORY_PREFIXES = (
    ("issue.", "issues"),
    ("credential.", "credentials"),
    ("pipeline.", "jobs"),
    ("session_batch.", "jobs"),
    ("hpc.", "hpc"),
    ("dataset.", "datasets"),
    ("profile.", "profiles"),
    ("institution.", "profiles"),
    ("zenodo.", "zenodo"),
    ("admin.", "admin"),
)

NOTIFICATION_CONFIG_BOUNDS = {
    "poll_interval_seconds": ("NOTIFICATION_POLL_INTERVAL_SECONDS", 120, 30, 600),
    "dropdown_limit": ("NOTIFICATION_DROPDOWN_LIMIT", 10, 1, 50),
    "page_limit": ("NOTIFICATION_PAGE_LIMIT", 50, 1, 100),
    "digest_max_per_user": ("NOTIFICATION_DIGEST_MAX_PER_USER", 10, 1, 50),
    "digest_user_batch_size": ("NOTIFICATION_DIGEST_USER_BATCH_SIZE", 25, 1, 100),
    "delivery_audit_retention_days": ("NOTIFICATION_DELIVERY_AUDIT_RETENTION_DAYS", 90, 1, 3650),
    "read_retention_days": ("NOTIFICATION_READ_RETENTION_DAYS", 180, 1, 3650),
    "archived_retention_days": ("NOTIFICATION_ARCHIVED_RETENTION_DAYS", 90, 1, 3650),
}


def _config_int(config_key: str, default: int, minimum: int, maximum: int) -> int:
    value = current_app.config.get(config_key, default) if has_app_context() else default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def notification_runtime_config() -> dict[str, Any]:
    payload = {
        key: _config_int(config_key, default, minimum, maximum)
        for key, (config_key, default, minimum, maximum) in NOTIFICATION_CONFIG_BOUNDS.items()
    }
    payload["sse_enabled"] = bool(current_app.config.get("NOTIFICATION_SSE_ENABLED", False)) if has_app_context() else False
    return payload


def _normalize_text(value: Any, *, max_length: int | None = None, required: bool = False) -> str | None:
    text = str(value or "").strip()
    if not text:
        if required:
            raise ValidationError("Notification title is required")
        return None
    return text[:max_length] if max_length is not None else text


def _normalize_severity(value: Any) -> str:
    severity = str(value or "info").strip().lower()
    return severity if severity in VALID_SEVERITIES else "info"


def _normalize_payload(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _notification_category(notification_type: str | None, category: str | None = None) -> str:
    category_text = str(category or "").strip().lower()
    if category_text in NOTIFICATION_CATEGORIES:
        return category_text
    type_text = str(notification_type or "").strip().lower()
    for prefix, mapped_category in TYPE_CATEGORY_PREFIXES:
        if type_text.startswith(prefix):
            return mapped_category
    return "system"


def _normalize_category(value: Any) -> str | None:
    category = str(value or "").strip().lower()
    return category if category in NOTIFICATION_CATEGORIES else None


def _serialize_user(user: User | None) -> dict[str, Any] | None:
    if not user:
        return None
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "full_name": user.full_name,
        "role": user.role.value if user.role else "user",
    }


def serialize_notification(notification: Notification) -> dict[str, Any]:
    payload = notification.to_dict()
    payload["category_label"] = NOTIFICATION_CATEGORIES.get(notification.category or "system", "System")
    payload["actor"] = _serialize_user(notification.actor)
    payload["recipient"] = _serialize_user(notification.recipient)
    payload["is_read"] = notification.read_at is not None
    payload["is_archived"] = notification.archived_at is not None
    return payload


def serialize_delivery(delivery: NotificationDelivery) -> dict[str, Any]:
    payload = delivery.to_dict()
    payload["notification"] = serialize_notification(delivery.notification) if delivery.notification else None
    payload["recipient"] = _serialize_user(delivery.recipient)
    return payload


def _default_preference(category: str) -> dict[str, Any]:
    return {
        "category": category,
        "label": NOTIFICATION_CATEGORIES.get(category, category.title()),
        "in_app_enabled": True,
        "email_enabled": False,
        "digest_enabled": False,
    }


def _serialize_preference(preference: NotificationPreference | None, category: str) -> dict[str, Any]:
    payload = _default_preference(category)
    if preference:
        payload.update(preference.to_dict())
        payload["label"] = NOTIFICATION_CATEGORIES.get(category, category.title())
    return payload


def _preference_for(user_id: int, category: str) -> NotificationPreference | None:
    return NotificationPreference.query.filter_by(user_id=int(user_id), category=category).first()


def get_preferences(*, user_id: int) -> dict[str, Any]:
    rows = {row.category: row for row in NotificationPreference.query.filter_by(user_id=int(user_id)).all()}
    return {
        "categories": [
            _serialize_preference(rows.get(category), category)
            for category in NOTIFICATION_CATEGORIES
        ],
    }


def update_preferences(*, user_id: int, preferences: Iterable[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(preferences, list):
        raise ValidationError("Preferences must be a list")

    for item in preferences:
        if not isinstance(item, dict):
            continue
        category = _normalize_category(item.get("category"))
        if not category:
            continue
        preference = _preference_for(user_id, category)
        if preference is None:
            preference = NotificationPreference(user_id=int(user_id), category=category)
            db.session.add(preference)
        if "in_app_enabled" in item:
            preference.in_app_enabled = bool(item.get("in_app_enabled"))
        if "email_enabled" in item:
            preference.email_enabled = bool(item.get("email_enabled"))
        if "digest_enabled" in item:
            preference.digest_enabled = bool(item.get("digest_enabled"))
        preference.updated_at = datetime.utcnow()

    db.session.commit()
    return get_preferences(user_id=user_id)


def _delivery_preferences(*, user_id: int, category: str) -> dict[str, bool]:
    preference = _preference_for(user_id, category)
    if not preference:
        return {"in_app_enabled": True, "email_enabled": False, "digest_enabled": False}
    return {
        "in_app_enabled": bool(preference.in_app_enabled),
        "email_enabled": bool(preference.email_enabled),
        "digest_enabled": bool(preference.digest_enabled),
    }


def _record_delivery(
    *,
    notification: Notification,
    channel: str,
    status: str,
    batch_key: str | None = None,
    provider_message_id: str | None = None,
    error: str | None = None,
) -> NotificationDelivery:
    now = datetime.utcnow()
    delivery = NotificationDelivery(
        notification_id=notification.id,
        recipient_user_id=notification.recipient_user_id,
        channel=str(channel or "").strip().lower(),
        status=str(status or "").strip().lower(),
        batch_key=_normalize_text(batch_key, max_length=120),
        provider_message_id=_normalize_text(provider_message_id, max_length=255),
        error=_normalize_text(error),
        sent_at=now if status == "sent" else None,
    )
    db.session.add(delivery)
    return delivery


def _send_notification_email(notification: Notification) -> None:
    if not has_app_context() or not getattr(current_app, "email_service", None):
        notification.email_status = "skipped"
        _record_delivery(notification=notification, channel="email", status="skipped", error="Mail service not initialized")
        return

    recipient = notification.recipient or db.session.get(User, notification.recipient_user_id)
    if not recipient or not recipient.email:
        notification.email_status = "skipped"
        _record_delivery(notification=notification, channel="email", status="skipped", error="Recipient email is missing")
        return

    try:
        sent = current_app.email_service.send_notification_email(recipient.email, serialize_notification(notification))
    except Exception as exc:  # pragma: no cover - defensive guard around pluggable mail backends
        notification.email_status = "failed"
        notification.email_error = str(exc)[:1000]
        _record_delivery(notification=notification, channel="email", status="failed", error=notification.email_error)
        return

    if sent:
        notification.email_status = "sent"
        notification.emailed_at = datetime.utcnow()
        notification.email_error = None
        _record_delivery(notification=notification, channel="email", status="sent")
    else:
        notification.email_status = "failed"
        notification.email_error = "Email service returned false"
        _record_delivery(notification=notification, channel="email", status="failed", error=notification.email_error)


def notify_user(
    *,
    recipient_user_id: int | None,
    notification_type: str,
    title: str,
    body: str | None = None,
    severity: str = "info",
    actor_user_id: int | None = None,
    institution_id: int | None = None,
    session_id: int | None = None,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    category: str | None = None,
    action_url: str | None = None,
    payload: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> Notification | None:
    if recipient_user_id is None:
        return None

    notification_type_text = _normalize_text(notification_type, max_length=120, required=True)
    title_text = _normalize_text(title, max_length=255, required=True)
    category_text = _notification_category(notification_type_text, category)
    preferences = _delivery_preferences(user_id=int(recipient_user_id), category=category_text)
    if not preferences["in_app_enabled"] and not preferences["email_enabled"]:
        return None

    dedupe_text = _normalize_text(dedupe_key, max_length=255)
    notification = None
    if dedupe_text:
        notification = Notification.query.filter_by(dedupe_key=dedupe_text).first()

    if notification is None:
        notification = Notification(
            recipient_user_id=int(recipient_user_id),
            dedupe_key=dedupe_text,
        )
        db.session.add(notification)

    notification.recipient_user_id = int(recipient_user_id)
    notification.actor_user_id = int(actor_user_id) if actor_user_id is not None else None
    notification.institution_id = int(institution_id) if institution_id is not None else None
    notification.session_id = int(session_id) if session_id is not None else None
    notification.entity_type = _normalize_text(entity_type, max_length=120)
    notification.entity_id = str(entity_id)[:120] if entity_id is not None else None
    notification.notification_type = notification_type_text
    notification.category = category_text
    notification.severity = _normalize_severity(severity)
    notification.title = title_text
    notification.body = _normalize_text(body)
    notification.action_url = _normalize_text(action_url, max_length=512)
    notification.payload_json = json.dumps(_normalize_payload(payload), sort_keys=True)
    notification.archived_at = None if preferences["in_app_enabled"] else datetime.utcnow()
    notification.email_status = "pending" if preferences["email_enabled"] else None
    notification.emailed_at = None
    notification.email_error = None
    db.session.flush()
    if preferences["email_enabled"]:
        _send_notification_email(notification)
    return notification


def notify_users(*, recipient_user_ids: Iterable[int], **kwargs) -> list[Notification]:
    notifications: list[Notification] = []
    seen: set[int] = set()
    for recipient_user_id in recipient_user_ids or []:
        if recipient_user_id is None:
            continue
        normalized_id = int(recipient_user_id)
        if normalized_id in seen:
            continue
        seen.add(normalized_id)
        notification = notify_user(recipient_user_id=normalized_id, **kwargs)
        if notification:
            notifications.append(notification)
    return notifications


def notify_admins(*, exclude_user_id: int | None = None, **kwargs) -> list[Notification]:
    query = User.query.filter(User.role == UserRole.ADMIN)
    if exclude_user_id is not None:
        query = query.filter(User.id != int(exclude_user_id))
    admin_ids = [int(row.id) for row in query.with_entities(User.id).all()]
    return notify_users(recipient_user_ids=admin_ids, **kwargs)


def list_notifications(*, user_id: int, state: str = "all", limit: int | None = None, category: str | None = None) -> dict[str, Any]:
    normalized_state = str(state or "all").strip().lower()
    if normalized_state not in VALID_STATES:
        normalized_state = "all"
    default_limit = notification_runtime_config()["dropdown_limit"]
    max_limit = notification_runtime_config()["page_limit"]
    normalized_limit = max(1, min(int(limit or default_limit), max_limit))
    normalized_category = _normalize_category(category)

    query = Notification.query.filter(Notification.recipient_user_id == int(user_id))
    if normalized_state == "unread":
        query = query.filter(Notification.read_at.is_(None), Notification.archived_at.is_(None))
    elif normalized_state == "archived":
        query = query.filter(Notification.archived_at.isnot(None))
    else:
        query = query.filter(Notification.archived_at.is_(None))
    if normalized_category:
        query = query.filter(Notification.category == normalized_category)

    rows = query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(normalized_limit).all()
    return {
        "notifications": [serialize_notification(row) for row in rows],
        "unread_count": unread_count(user_id=user_id),
        "filters": {"state": normalized_state, "limit": normalized_limit, "category": normalized_category},
        "categories": [{"value": key, "label": label} for key, label in NOTIFICATION_CATEGORIES.items()],
        "client_config": notification_runtime_config(),
    }


def unread_count(*, user_id: int) -> int:
    return int(
        Notification.query.filter(
            Notification.recipient_user_id == int(user_id),
            Notification.read_at.is_(None),
            Notification.archived_at.is_(None),
        ).count()
    )


def _get_owned_notification(notification_id: int, user_id: int) -> Notification:
    notification = db.session.get(Notification, int(notification_id))
    if not notification:
        raise ResourceNotFoundError("Notification not found")
    if int(notification.recipient_user_id) != int(user_id):
        raise SecurityError("Notification not found")
    return notification


def mark_read(*, notification_id: int, user_id: int, read: bool | None = None, archived: bool | None = None) -> Notification:
    notification = _get_owned_notification(notification_id, user_id)
    now = datetime.utcnow()
    if read is not None:
        notification.read_at = now if bool(read) else None
    if archived is not None:
        notification.archived_at = now if bool(archived) else None
    db.session.commit()
    return notification


def mark_all_read(*, user_id: int) -> int:
    now = datetime.utcnow()
    rows = Notification.query.filter(
        Notification.recipient_user_id == int(user_id),
        Notification.read_at.is_(None),
        Notification.archived_at.is_(None),
    ).all()
    for row in rows:
        row.read_at = now
    db.session.commit()
    return len(rows)


def _has_digest_delivery(notification_id: int) -> bool:
    return (
        NotificationDelivery.query.filter_by(notification_id=int(notification_id), channel="digest", status="sent").first()
        is not None
    )


def _digest_enabled_categories(user_id: int) -> set[str]:
    return {
        row.category
        for row in NotificationPreference.query.filter_by(user_id=int(user_id), digest_enabled=True).all()
        if row.category in NOTIFICATION_CATEGORIES
    }


def send_notification_digests(
    *,
    user_id: int | None = None,
    max_per_user: int | None = None,
    user_batch_size: int | None = None,
) -> dict[str, Any]:
    if not has_app_context() or not getattr(current_app, "email_service", None):
        raise ValidationError("Mail service is not initialized")

    config = notification_runtime_config()
    normalized_limit = max(1, min(int(max_per_user or config["digest_max_per_user"]), config["digest_max_per_user"]))
    normalized_user_batch_size = max(1, min(int(user_batch_size or config["digest_user_batch_size"]), config["digest_user_batch_size"]))
    user_query = User.query.filter(User.is_verified.is_(True))
    if user_id is not None:
        user_query = user_query.filter(User.id == int(user_id))

    batch_key = f"digest:{datetime.utcnow().strftime('%Y%m%d%H%M%S')}:{uuid.uuid4().hex[:8]}"
    sent_users = 0
    skipped_users = 0
    failed_users = 0
    delivered_notifications = 0
    processed_users = 0

    for user in user_query.order_by(User.id.asc()).limit(normalized_user_batch_size).all():
        processed_users += 1
        categories = _digest_enabled_categories(user.id)
        if not categories:
            skipped_users += 1
            continue
        rows = (
            Notification.query.filter(
                Notification.recipient_user_id == user.id,
                Notification.archived_at.is_(None),
                Notification.category.in_(list(categories)),
            )
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(normalized_limit)
            .all()
        )
        digest_rows = [row for row in rows if not _has_digest_delivery(row.id)]
        if not digest_rows:
            skipped_users += 1
            continue

        try:
            sent = current_app.email_service.send_notification_digest_email(
                user.email,
                [serialize_notification(row) for row in digest_rows],
            )
        except Exception as exc:  # pragma: no cover - defensive guard around pluggable mail backends
            sent = False
            error = str(exc)[:1000]
        else:
            error = None if sent else "Email service returned false"

        status = "sent" if sent else "failed"
        for row in digest_rows:
            _record_delivery(notification=row, channel="digest", status=status, batch_key=batch_key, error=error)
        if sent:
            sent_users += 1
            delivered_notifications += len(digest_rows)
        else:
            failed_users += 1

    db.session.commit()
    return {
        "batch_key": batch_key,
        "sent_users": sent_users,
        "skipped_users": skipped_users,
        "failed_users": failed_users,
        "processed_users": processed_users,
        "delivered_notifications": delivered_notifications,
    }


def _parse_datetime(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def _delivery_query(
    *,
    channel: str | None = None,
    status: str | None = None,
    recipient_user_id: int | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
):
    query = NotificationDelivery.query
    if str(channel or "").strip():
        query = query.filter(NotificationDelivery.channel == str(channel).strip().lower())
    if str(status or "").strip():
        query = query.filter(NotificationDelivery.status == str(status).strip().lower())
    if recipient_user_id is not None:
        query = query.filter(NotificationDelivery.recipient_user_id == int(recipient_user_id))
    if start_at is not None:
        query = query.filter(NotificationDelivery.created_at >= start_at)
    if end_at is not None:
        query = query.filter(NotificationDelivery.created_at <= end_at)
    return query


def list_notification_deliveries(
    *,
    channel: str | None = None,
    status: str | None = None,
    recipient_user_id: int | None = None,
    limit: int = 100,
    start_at: str | None = None,
    end_at: str | None = None,
) -> dict[str, Any]:
    normalized_limit = max(1, min(int(limit or 100), 250))
    parsed_start = _parse_datetime(start_at)
    parsed_end = _parse_datetime(end_at)
    if parsed_start is None and parsed_end is None:
        parsed_start = datetime.utcnow() - timedelta(days=7)
    query = _delivery_query(
        channel=channel,
        status=status,
        recipient_user_id=recipient_user_id,
        start_at=parsed_start,
        end_at=parsed_end,
    )

    rows = query.order_by(NotificationDelivery.created_at.desc(), NotificationDelivery.id.desc()).limit(normalized_limit).all()
    channels = dict(query.with_entities(NotificationDelivery.channel, func.count(NotificationDelivery.id)).group_by(NotificationDelivery.channel).all())
    statuses = dict(query.with_entities(NotificationDelivery.status, func.count(NotificationDelivery.id)).group_by(NotificationDelivery.status).all())
    total = int(query.with_entities(func.count(NotificationDelivery.id)).scalar() or 0)
    return {
        "deliveries": [serialize_delivery(row) for row in rows],
        "summary": {
            "total": total,
            "channels": dict(channels),
            "statuses": dict(statuses),
        },
        "filters": {
            "channel": channel or "",
            "status": status or "",
            "recipient_user_id": recipient_user_id,
            "limit": normalized_limit,
            "start_at": parsed_start.isoformat() if parsed_start else None,
            "end_at": parsed_end.isoformat() if parsed_end else None,
        },
    }


def cleanup_notifications(*, batch_size: int = 1000) -> dict[str, int]:
    config = notification_runtime_config()
    now = datetime.utcnow()
    normalized_batch_size = max(1, min(int(batch_size or 1000), 5000))
    delivery_cutoff = now - timedelta(days=config["delivery_audit_retention_days"])
    read_cutoff = now - timedelta(days=config["read_retention_days"])
    archived_cutoff = now - timedelta(days=config["archived_retention_days"])

    old_delivery_ids = [
        row.id
        for row in NotificationDelivery.query.with_entities(NotificationDelivery.id)
        .filter(NotificationDelivery.created_at < delivery_cutoff)
        .order_by(NotificationDelivery.id.asc())
        .limit(normalized_batch_size)
        .all()
    ]
    deleted_deliveries = 0
    if old_delivery_ids:
        deleted_deliveries = NotificationDelivery.query.filter(NotificationDelivery.id.in_(old_delivery_ids)).delete(synchronize_session=False)

    old_notification_ids = [
        row.id
        for row in Notification.query.with_entities(Notification.id)
        .filter(
            or_(
                and_(
                    Notification.archived_at.isnot(None),
                    Notification.archived_at < archived_cutoff,
                ),
                and_(
                    Notification.read_at.isnot(None),
                    Notification.archived_at.is_(None),
                    Notification.read_at < read_cutoff,
                ),
            )
        )
        .order_by(Notification.id.asc())
        .limit(normalized_batch_size)
        .all()
    ]
    deleted_notifications = 0
    if old_notification_ids:
        deleted_deliveries += NotificationDelivery.query.filter(NotificationDelivery.notification_id.in_(old_notification_ids)).delete(synchronize_session=False)
        deleted_notifications = Notification.query.filter(Notification.id.in_(old_notification_ids)).delete(synchronize_session=False)

    db.session.commit()
    return {
        "deleted_deliveries": int(deleted_deliveries),
        "deleted_notifications": int(deleted_notifications),
        "delivery_audit_retention_days": config["delivery_audit_retention_days"],
        "read_retention_days": config["read_retention_days"],
        "archived_retention_days": config["archived_retention_days"],
    }
