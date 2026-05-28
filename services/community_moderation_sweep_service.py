import csv
import hashlib
import io
import json
from datetime import datetime
from typing import Any

from database.database import db
from database.models import CommunityModerationSweepEvent, CommunityModerationSweepJob, User
from exceptions import ResourceNotFoundError, ValidationError
from services import zenodo_moderation_service


TERMINAL_STATES = {"SUCCESS", "FAILURE", "CANCELLED"}
ACTIVE_STATES = {"PENDING", "PROGRESS", "CANCEL_REQUESTED"}
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 100
MAX_CONSECUTIVE_FAILURES = 25


def _utc_now() -> datetime:
    return datetime.utcnow()


def _json_dumps(value: Any) -> str:
    return json.dumps(value or {}, sort_keys=True)


def _normalize_action(value: Any) -> str:
    action = str(value or "").strip().lower()
    if action not in {"accept", "decline"}:
        raise ValidationError("action must be 'accept' or 'decline'")
    return action


def _normalize_status(value: Any) -> str:
    status = str(value or "submitted").strip().lower()
    if status != "submitted":
        raise ValidationError("status_filter must be submitted")
    return status


def _normalize_optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_page_size(value: Any) -> int:
    try:
        page_size = int(value or DEFAULT_PAGE_SIZE)
    except (TypeError, ValueError):
        raise ValidationError("page_size must be an integer")
    return max(1, min(page_size, MAX_PAGE_SIZE))


def _normalize_max_requests(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        max_requests = int(value)
    except (TypeError, ValueError):
        raise ValidationError("max_requests must be an integer")
    if max_requests < 1:
        raise ValidationError("max_requests must be greater than zero")
    return max_requests


def _community_identifier(value: Any) -> str:
    identifier = str(value or "").strip()
    if not identifier:
        raise ValidationError("community_identifier is required")
    return identifier


def _confirmation_phrase(action: str, count: int, community_identifier: str) -> str:
    verb = "ACCEPT" if action == "accept" else "DECLINE"
    return f"{verb} {int(count or 0)} REQUESTS FOR {community_identifier}"


def _plan_checksum(seed: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(seed, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _community_from_summary(summary: dict[str, Any]) -> dict[str, Any]:
    community = summary.get("community") if isinstance(summary.get("community"), dict) else {}
    return {
        "uuid": community.get("id"),
        "slug": community.get("slug"),
        "title": community.get("title"),
        "links": community.get("links") if isinstance(community.get("links"), dict) else {},
    }


def _request_record_id(item: dict[str, Any]) -> str | None:
    value = item.get("topic_record")
    if value is None:
        return None
    return str(value)


class CommunityModerationSweepService:
    def build_plan(
        self,
        *,
        community_identifier: str,
        action: str,
        status_filter: str = "submitted",
        request_type: str | None = None,
        note: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_requests: int | None = None,
    ) -> dict[str, Any]:
        community_value = _community_identifier(community_identifier)
        normalized_action = _normalize_action(action)
        normalized_status = _normalize_status(status_filter)
        normalized_request_type = _normalize_optional_text(request_type)
        normalized_page_size = _normalize_page_size(page_size)
        normalized_max = _normalize_max_requests(max_requests)
        note_text = str(note or "").strip()

        summary = zenodo_moderation_service.summarize_community_requests(
            community_value,
            action=normalized_action,
            status=normalized_status,
            request_type=normalized_request_type,
            preview_size=normalized_page_size,
        )
        total_matching = int(summary.get("total") or 0)
        planned_count = min(total_matching, normalized_max) if normalized_max else total_matching
        confirmation_text = _confirmation_phrase(normalized_action, planned_count, community_value)
        checksum = _plan_checksum(
            {
                "community_identifier": community_value,
                "action": normalized_action,
                "status_filter": normalized_status,
                "request_type": normalized_request_type,
                "note_present": bool(note_text),
                "page_size": normalized_page_size,
                "max_requests": normalized_max,
                "total_matching": total_matching,
                "planned_count": planned_count,
                "preview_ids": [item.get("request_id") for item in list(summary.get("preview") or [])[:10]],
            }
        )

        return {
            "community_identifier": community_value,
            "action": normalized_action,
            "status_filter": normalized_status,
            "request_type": normalized_request_type,
            "note_present": bool(note_text),
            "page_size": normalized_page_size,
            "max_requests": normalized_max,
            "community": summary.get("community") or {},
            "api_key_context": summary.get("api_key_context") or {},
            "summary": {
                "total_matching": total_matching,
                "planned_requests": planned_count,
                "preview_count": int(summary.get("preview_count") or 0),
                "preview_actionable_count": int(summary.get("preview_actionable_count") or 0),
            },
            "preview": list(summary.get("preview") or []),
            "plan_checksum": checksum,
            "confirmation_text": confirmation_text,
        }

    def _active_duplicate(self, *, community_identifier: str, action: str, status_filter: str, request_type: str | None) -> CommunityModerationSweepJob | None:
        query = CommunityModerationSweepJob.query.filter(
            CommunityModerationSweepJob.community_identifier == community_identifier,
            CommunityModerationSweepJob.action == action,
            CommunityModerationSweepJob.status_filter == status_filter,
            CommunityModerationSweepJob.state.in_(ACTIVE_STATES),
        )
        if request_type:
            query = query.filter(CommunityModerationSweepJob.request_type == request_type)
        else:
            query = query.filter(CommunityModerationSweepJob.request_type.is_(None))
        return query.order_by(CommunityModerationSweepJob.created_at.desc()).first()

    def create_job(
        self,
        *,
        user: User,
        community_identifier: str,
        action: str,
        status_filter: str = "submitted",
        request_type: str | None = None,
        note: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_requests: int | None = None,
        expected_plan_checksum: str,
        confirmation_text: str,
    ) -> CommunityModerationSweepJob:
        plan = self.build_plan(
            community_identifier=community_identifier,
            action=action,
            status_filter=status_filter,
            request_type=request_type,
            note=note,
            page_size=page_size,
            max_requests=max_requests,
        )
        if not expected_plan_checksum or str(expected_plan_checksum).strip() != plan["plan_checksum"]:
            raise ValidationError("Sweep plan changed since dry-run review. Rebuild the plan before queueing.")
        if str(confirmation_text or "").strip() != plan["confirmation_text"]:
            raise ValidationError("confirmation_text must exactly match the required confirmation phrase")
        if int(plan["summary"].get("planned_requests") or 0) <= 0:
            raise ValidationError("No submitted requests match this sweep plan")
        if int(plan["summary"].get("preview_actionable_count") or 0) <= 0:
            raise ValidationError("No actionable requests were found in the preview page")

        duplicate = self._active_duplicate(
            community_identifier=plan["community_identifier"],
            action=plan["action"],
            status_filter=plan["status_filter"],
            request_type=plan["request_type"],
        )
        if duplicate is not None:
            raise ValidationError(f"A matching moderation sweep is already active: {duplicate.public_id}")

        community = _community_from_summary(plan)
        now = _utc_now()
        job = CommunityModerationSweepJob(
            requested_by_user_id=int(user.id),
            community_identifier=plan["community_identifier"],
            community_uuid=community.get("uuid"),
            community_title=community.get("title"),
            community_links_json=_json_dumps(community.get("links") or {}),
            action=plan["action"],
            status_filter=plan["status_filter"],
            request_type=plan["request_type"],
            note_present=bool(plan["note_present"]),
            note_json=_json_dumps({"content": str(note or "").strip()}),
            page_size=int(plan["page_size"]),
            max_requests=plan["max_requests"],
            plan_checksum=plan["plan_checksum"],
            confirmation_text=plan["confirmation_text"],
            state="PENDING",
            phase="queued",
            summary_json=_json_dumps(
                {
                    **plan["summary"],
                    "processed": 0,
                    "accepted": 0,
                    "declined": 0,
                    "failed": 0,
                    "skipped": 0,
                    "rate_limit_waits": 0,
                    "submitted_remaining": plan["summary"]["total_matching"],
                }
            ),
            progress_json=_json_dumps(
                {
                    "total_requests": plan["summary"]["planned_requests"],
                    "processed": 0,
                    "accepted": 0,
                    "declined": 0,
                    "failed": 0,
                    "skipped": 0,
                    "rate_limit_waits": 0,
                    "submitted_remaining": plan["summary"]["total_matching"],
                    "percent": 0,
                    "current_request": None,
                }
            ),
            control_json=_json_dumps({"cancel_requested": False}),
            created_at=now,
            updated_at=now,
        )
        db.session.add(job)
        db.session.commit()
        return job

    def mark_queued(self, job: CommunityModerationSweepJob, *, task_id: str | None) -> CommunityModerationSweepJob:
        job.task_id = str(task_id) if task_id else None
        job.state = "PENDING"
        job.phase = "queued"
        job.updated_at = _utc_now()
        db.session.commit()
        return job

    def get_job(self, job_id: str, user: User | None = None) -> CommunityModerationSweepJob:
        job = CommunityModerationSweepJob.query.filter_by(public_id=str(job_id or "").strip()).first()
        if job is None:
            raise ResourceNotFoundError("Community moderation sweep not found")
        if user is not None:
            role = getattr(user, "role", None)
            role_value = getattr(role, "value", role) or "user"
            if int(job.requested_by_user_id) != int(user.id) and role_value != "admin":
                raise ValidationError("You do not have access to this moderation sweep")
        return job

    def list_jobs(self, user: User, *, limit: int = 20) -> list[dict[str, Any]]:
        role = getattr(user, "role", None)
        role_value = getattr(role, "value", role) or "user"
        query = CommunityModerationSweepJob.query
        if role_value != "admin":
            query = query.filter_by(requested_by_user_id=int(user.id))
        rows = query.order_by(CommunityModerationSweepJob.updated_at.desc()).limit(max(1, min(int(limit or 20), 50))).all()
        return [row.to_dict(include_events=True, event_limit=10) for row in rows]

    def request_cancel(self, job: CommunityModerationSweepJob) -> CommunityModerationSweepJob:
        if str(job.state or "").upper() not in TERMINAL_STATES:
            control = dict(job.control)
            control["cancel_requested"] = True
            job.control_json = _json_dumps(control)
            job.state = "CANCEL_REQUESTED"
            job.phase = "cancel_requested"
            job.updated_at = _utc_now()
            db.session.commit()
        return job

    def _add_event(
        self,
        job: CommunityModerationSweepJob,
        *,
        item: dict[str, Any] | None,
        event: str,
        status: str | None = None,
        message: str | None = None,
        rate_limit_reason: str | None = None,
    ) -> CommunityModerationSweepEvent:
        item = item or {}
        row = CommunityModerationSweepEvent(
            job_id=job.id,
            request_id=str(item.get("request_id") or "").strip() or None,
            request_number=str(item.get("number") or "").strip() or None,
            record_id=_request_record_id(item),
            title=str(item.get("title") or "").strip() or None,
            request_type=str(item.get("type") or "").strip() or None,
            event=event,
            status=status,
            message=message,
            rate_limit_reason=rate_limit_reason,
            created_at=_utc_now(),
        )
        db.session.add(row)
        return row

    def _update_progress(self, job: CommunityModerationSweepJob, progress: dict[str, Any], *, phase: str | None = None, status: str | None = None) -> None:
        total = int(progress.get("total_requests") or 0)
        processed = int(progress.get("processed") or 0)
        progress["percent"] = int(round((processed / total) * 100)) if total else 100
        summary = dict(job.summary)
        summary.update(
            {
                "processed": processed,
                "accepted": int(progress.get("accepted") or 0),
                "declined": int(progress.get("declined") or 0),
                "failed": int(progress.get("failed") or 0),
                "skipped": int(progress.get("skipped") or 0),
                "rate_limit_waits": int(progress.get("rate_limit_waits") or 0),
                "submitted_remaining": int(progress.get("submitted_remaining") or 0),
            }
        )
        job.progress_json = _json_dumps(progress)
        job.summary_json = _json_dumps(summary)
        if phase is not None:
            job.phase = phase
        if status is not None:
            job.state = status
        job.updated_at = _utc_now()
        db.session.commit()

    def execute_job(self, job_id: str, *, task_self=None) -> dict[str, Any]:
        job = self.get_job(job_id)
        job.state = "PROGRESS"
        job.phase = "running"
        job.started_at = job.started_at or _utc_now()
        job.error = None
        job.last_error = None
        db.session.commit()

        progress = dict(job.progress)
        consecutive_failures = 0
        note = str(job.note_payload.get("content") or "").strip() or None

        try:
            while True:
                db.session.refresh(job)
                if job.control.get("cancel_requested") or str(job.state or "").upper() == "CANCEL_REQUESTED":
                    job.state = "CANCELLED"
                    job.phase = "cancelled"
                    job.completed_at = _utc_now()
                    self._update_progress(job, progress, phase="cancelled", status="CANCELLED")
                    return job.to_dict(include_events=True, event_limit=100)

                if job.max_requests is not None and int(progress.get("processed") or 0) >= int(job.max_requests):
                    job.phase = "completed_max_requests"
                    job.completed_at = _utc_now()
                    final_state = "SUCCESS" if int(progress.get("failed") or 0) == 0 else "FAILURE"
                    self._update_progress(job, progress, phase=job.phase, status=final_state)
                    return job.to_dict(include_events=True, event_limit=100)

                page_waits: list[tuple[str, float]] = []

                def _page_wait(reason: str, sleep_time: float, response=None):
                    page_waits.append((reason, sleep_time))

                page = zenodo_moderation_service.fetch_community_request_page(
                    job.community_identifier,
                    status=job.status_filter,
                    page=1,
                    size=int(job.page_size or DEFAULT_PAGE_SIZE),
                    request_type=job.request_type,
                    wait_callback=_page_wait,
                )
                for reason, _sleep_time in page_waits:
                    progress["rate_limit_waits"] = int(progress.get("rate_limit_waits") or 0) + 1
                    self._add_event(job, item=None, event="rate_limit_wait", status="waited", message="Zenodo request listing waited for rate limiting", rate_limit_reason=reason)

                submitted_remaining = int(page.get("total") or 0)
                progress["submitted_remaining"] = submitted_remaining
                self._update_progress(job, progress, phase="fetching")
                if task_self is not None:
                    task_self.update_state(state="PROGRESS", meta={"status": job.phase, "progress": dict(progress)})

                if submitted_remaining == 0:
                    job.phase = "completed"
                    job.completed_at = _utc_now()
                    final_state = "SUCCESS" if int(progress.get("failed") or 0) == 0 else "FAILURE"
                    self._update_progress(job, progress, phase="completed", status=final_state)
                    return job.to_dict(include_events=True, event_limit=100)

                page_items = [dict(item) for item in (page.get("requests") or []) if isinstance(item, dict)]
                if not page_items:
                    raise RuntimeError(f"submitted_remaining={submitted_remaining}, but Zenodo returned an empty page")

                actionable = [item for item in page_items if zenodo_moderation_service.request_is_actionable_for(item, job.action)]
                if not actionable:
                    raise RuntimeError("Submitted page contains no actionable requests; stopping to avoid a spin loop")

                for item in actionable:
                    db.session.refresh(job)
                    if job.control.get("cancel_requested") or str(job.state or "").upper() == "CANCEL_REQUESTED":
                        break
                    if job.max_requests is not None and int(progress.get("processed") or 0) >= int(job.max_requests):
                        break

                    progress["current_request"] = {
                        "request_id": item.get("request_id"),
                        "number": item.get("number"),
                        "title": item.get("title"),
                        "record": item.get("topic_record"),
                        "type": item.get("type"),
                    }
                    wait_stats = {"count": 0}

                    def _wait_callback(reason: str, sleep_time: float, response=None):
                        wait_stats["count"] += 1
                        self._add_event(job, item=item, event="rate_limit_wait", status="waited", message="Zenodo action waited for rate limiting", rate_limit_reason=reason)
                        db.session.commit()

                    try:
                        updated = zenodo_moderation_service.perform_request_action(
                            str(item.get("request_id") or ""),
                            job.action,
                            note=note,
                            wait_callback=_wait_callback,
                        )
                        event_name = "accepted" if job.action == "accept" else "declined"
                        progress["processed"] = int(progress.get("processed") or 0) + 1
                        progress["rate_limit_waits"] = int(progress.get("rate_limit_waits") or 0) + int(wait_stats["count"])
                        if job.action == "accept":
                            progress["accepted"] = int(progress.get("accepted") or 0) + 1
                        else:
                            progress["declined"] = int(progress.get("declined") or 0) + 1
                        consecutive_failures = 0
                        self._add_event(job, item=item, event=event_name, status=str(updated.get("status") or event_name), message=f"Request {job.action}ed successfully.")
                    except Exception as exc:
                        consecutive_failures += 1
                        progress["processed"] = int(progress.get("processed") or 0) + 1
                        progress["failed"] = int(progress.get("failed") or 0) + 1
                        progress["rate_limit_waits"] = int(progress.get("rate_limit_waits") or 0) + int(wait_stats["count"])
                        job.last_error = str(exc)
                        self._add_event(job, item=item, event="failed", status="failed", message=str(exc))
                        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                            raise RuntimeError(f"{consecutive_failures} consecutive moderation failures")
                    finally:
                        self._update_progress(job, progress, phase="processing")
                        if task_self is not None:
                            task_self.update_state(state="PROGRESS", meta={"status": job.phase, "progress": dict(progress)})

        except Exception as exc:
            job.state = "FAILURE"
            job.phase = "failed"
            job.error = str(exc)
            job.last_error = str(exc)
            job.completed_at = _utc_now()
            self._add_event(job, item=None, event="failed", status="failed", message=str(exc))
            self._update_progress(job, progress, phase="failed", status="FAILURE")
            raise

    def export_job_json(self, job: CommunityModerationSweepJob) -> dict[str, Any]:
        return job.to_dict(include_events=True, event_limit=None)

    def export_job_csv(self, job: CommunityModerationSweepJob) -> str:
        output = io.StringIO()
        fieldnames = [
            "created_at",
            "event",
            "status",
            "request_id",
            "request_number",
            "record_id",
            "title",
            "request_type",
            "message",
            "rate_limit_reason",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for event in job.events:
            payload = event.to_dict()
            writer.writerow({key: payload.get(key) for key in fieldnames})
        return output.getvalue()
