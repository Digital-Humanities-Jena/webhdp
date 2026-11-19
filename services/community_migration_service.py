import csv
import hashlib
import io
import json
import os
from datetime import date, datetime
from typing import Any, Iterable

from flask import current_app

from database.database import db
from database.models import CommunityMigrationJob, CommunityMigrationRecord, Session as DBSession, User
from exceptions import ResourceNotFoundError, ValidationError
from services.hdpc_schema_service import connect_hdpc
from services.publishing_context_service import PublishingContextService
from services.zenodo_account_retrieval_history_service import get_retrieval_entry, list_retrieval_entries, publicize_retrieval_entry
from services.zenodo_account_retrieval_service import iter_retrieval_records
from services.zenodo_credential_service import ZenodoCredentialService


TERMINAL_STATES = {"SUCCESS", "FAILURE", "CANCELLED"}
DEFAULT_PROGRESS = {
    "total_records": 0,
    "processed": 0,
    "succeeded": 0,
    "unchanged": 0,
    "ineligible": 0,
    "failed": 0,
    "percent": 0,
    "current_record": None,
}
TARGET_ACCEPTANCE_POLICIES = {"direct", "moderated"}


def _utc_now() -> datetime:
    return datetime.utcnow()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _normalize_identifier(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationError(f"{field_name} is required")
    return text


def _normalize_date_value(value: Any, *, field_name: str) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        raise ValidationError(f"{field_name} must be an ISO date")


def _normalize_filters(value: Any) -> dict[str, Any]:
    filters = dict(value or {}) if isinstance(value, dict) else {}
    normalized = {
        "record_status": str(filters.get("record_status") or "all").strip().lower(),
        "editable_only": bool(filters.get("editable_only", True)),
        "q": str(filters.get("q") or "").strip(),
        "created_from": _normalize_date_value(filters.get("created_from"), field_name="created_from"),
        "created_to": _normalize_date_value(filters.get("created_to"), field_name="created_to"),
        "updated_from": _normalize_date_value(filters.get("updated_from"), field_name="updated_from"),
        "updated_to": _normalize_date_value(filters.get("updated_to"), field_name="updated_to"),
    }
    if normalized["record_status"] not in {"all", "draft", "published"}:
        raise ValidationError("record_status must be one of all, draft, or published")
    return normalized


def _normalize_options(value: Any) -> dict[str, Any]:
    options = dict(value or {}) if isinstance(value, dict) else {}
    target_acceptance_policy = str(options.get("target_acceptance_policy") or "direct").strip().lower()
    if target_acceptance_policy not in TARGET_ACCEPTANCE_POLICIES:
        raise ValidationError("target_acceptance_policy must be one of direct or moderated")
    return {
        "remove_source_after_verify": bool(options.get("remove_source_after_verify", False)),
        "target_acceptance_policy": target_acceptance_policy,
    }


def _extract_communities(metadata: dict[str, Any]) -> list[str]:
    core = metadata.get("metadata") if isinstance(metadata.get("metadata"), dict) else {}
    communities = core.get("communities") if isinstance(core, dict) else []
    values: list[str] = []
    if isinstance(communities, list):
        for item in communities:
            if isinstance(item, dict):
                text = str(item.get("identifier") or "").strip()
            else:
                text = str(item or "").strip()
            if text and text.lower() not in {value.lower() for value in values}:
                values.append(text)
    return values


def _contains_community(values: Iterable[str], identifier: str) -> bool:
    target = str(identifier or "").strip().lower()
    return bool(target) and target in {str(item or "").strip().lower() for item in values}


def _parse_record_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _matches_date(value: Any, start: str | None, end: str | None) -> bool:
    if not start and not end:
        return True
    parsed = _parse_record_date(value)
    if parsed is None:
        return False
    start_date = date.fromisoformat(start) if start else None
    end_date = date.fromisoformat(end) if end else None
    if start_date and parsed < start_date:
        return False
    if end_date and parsed > end_date:
        return False
    return True


def _record_matches_filters(record: dict[str, Any], filters: dict[str, Any]) -> bool:
    status_filter = filters.get("record_status") or "all"
    if status_filter != "all" and str(record.get("status") or "").lower() != status_filter:
        return False
    if filters.get("editable_only") and not bool((record.get("capabilities") or {}).get("had_edit_rights")):
        return False
    query = str(filters.get("q") or "").strip().lower()
    if query:
        haystack = " ".join(
            str(record.get(key) or "")
            for key in ("title", "zenodo_record_id", "doi", "concept_rec_id", "created", "modified")
        ).lower()
        communities = " ".join(_extract_communities(record.get("metadata") if isinstance(record.get("metadata"), dict) else {})).lower()
        if query not in haystack and query not in communities:
            return False
    if not _matches_date(record.get("created"), filters.get("created_from"), filters.get("created_to")):
        return False
    if not _matches_date(record.get("modified"), filters.get("updated_from"), filters.get("updated_to")):
        return False
    return True


def _candidate_from_record(record: dict[str, Any], *, source_community: str, target_community: str) -> dict[str, Any] | None:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    communities = _extract_communities(metadata)
    if not _contains_community(communities, source_community):
        return None
    editable = bool((record.get("capabilities") or {}).get("had_edit_rights"))
    already_target = _contains_community(communities, target_community)
    return {
        "session_id": int(record.get("session_id") or 0),
        "local_record_id": int(record.get("local_record_id") or 0),
        "zenodo_record_id": record.get("zenodo_record_id"),
        "concept_rec_id": record.get("concept_rec_id"),
        "record_title": record.get("title"),
        "record_status": record.get("status"),
        "record_origin": record.get("record_origin"),
        "is_editable": editable,
        "ineligibility_reason": "" if editable else "Record does not expose an editable Zenodo action.",
        "before_communities": communities,
        "after_communities": communities,
        "already_target": already_target,
        "append_needed": editable and not already_target,
        "removable": editable and already_target,
    }


def _moderation_note(target_acceptance_policy: str) -> str:
    if target_acceptance_policy == "moderated":
        return "Target-community moderation may be required in Zenodo after append."
    return "Target community accepts direct additions; no Community B owner token is required."


def _summary_from_candidates(
    candidates: list[dict[str, Any]],
    *,
    remove_source_after_verify: bool = False,
    target_acceptance_policy: str = "direct",
) -> dict[str, Any]:
    editable = sum(1 for item in candidates if item.get("is_editable"))
    already_target = sum(1 for item in candidates if item.get("already_target"))
    append_needed = sum(1 for item in candidates if item.get("append_needed"))
    ineligible = max(len(candidates) - editable, 0)
    policy = target_acceptance_policy if target_acceptance_policy in TARGET_ACCEPTANCE_POLICIES else "direct"
    return {
        "total_records": len(candidates),
        "editable": editable,
        "ineligible": ineligible,
        "already_in_target": already_target,
        "append_needed": append_needed,
        "removable": editable if remove_source_after_verify else 0,
        "failed": 0,
        "remove_source_after_verify": bool(remove_source_after_verify),
        "target_acceptance_policy": policy,
        "target_owner_token_required": False,
        "target_owner_token_status": "Not used by migration" if policy == "moderated" else "Not required",
        "credential_strategy": "source_record_edit_token",
        "pending_moderation_note": _moderation_note(policy),
    }


def _empty_summary(
    *,
    remove_source_after_verify: bool = False,
    target_acceptance_policy: str = "direct",
) -> dict[str, Any]:
    return _summary_from_candidates(
        [],
        remove_source_after_verify=remove_source_after_verify,
        target_acceptance_policy=target_acceptance_policy,
    )


def _add_candidate_to_summary(summary: dict[str, Any], candidate: dict[str, Any]) -> None:
    summary["total_records"] = int(summary.get("total_records") or 0) + 1
    if candidate.get("is_editable"):
        summary["editable"] = int(summary.get("editable") or 0) + 1
    else:
        summary["ineligible"] = int(summary.get("ineligible") or 0) + 1
    if candidate.get("already_target"):
        summary["already_in_target"] = int(summary.get("already_in_target") or 0) + 1
    if candidate.get("append_needed"):
        summary["append_needed"] = int(summary.get("append_needed") or 0) + 1
    if summary.get("remove_source_after_verify") and candidate.get("is_editable"):
        summary["removable"] = int(summary.get("removable") or 0) + 1


def _plan_digest_seed(plan_fields: dict[str, Any]) -> Any:
    digest = hashlib.sha256()
    digest.update(json.dumps(plan_fields, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return digest


def _update_plan_digest(digest: Any, candidate: dict[str, Any]) -> None:
    fingerprint = {
        "session_id": candidate.get("session_id"),
        "local_record_id": candidate.get("local_record_id"),
        "zenodo_record_id": candidate.get("zenodo_record_id"),
        "concept_rec_id": candidate.get("concept_rec_id"),
        "record_status": candidate.get("record_status"),
        "is_editable": bool(candidate.get("is_editable")),
        "before_communities": candidate.get("before_communities") or [],
        "already_target": bool(candidate.get("already_target")),
        "append_needed": bool(candidate.get("append_needed")),
    }
    digest.update(json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode("utf-8"))


class CommunityMigrationService:
    def __init__(self):
        self.publishing_context_service = PublishingContextService()
        self.credential_service = ZenodoCredentialService()

    def list_context(self, user: User) -> dict[str, Any]:
        role = getattr(user, "role", None)
        role_value = getattr(role, "value", role) or "user"
        user_filter = None if role_value == "admin" else int(user.id)
        retrievals = [
            publicize_retrieval_entry(entry)
            for entry in list_retrieval_entries(limit=50, user_id=user_filter)
            if str(entry.get("state") or "").upper() == "SUCCESS"
        ]
        return {
            "retrievals": retrievals,
            "credentials": self.credential_service.list_available_credentials(int(user.id)),
            "defaults": {
                "record_status": "all",
                "editable_only": True,
                "remove_source_after_verify": False,
                "target_acceptance_policy": "direct",
            },
        }

    def require_retrieval_access(self, retrieval_id: str, user: User) -> dict[str, Any]:
        entry = get_retrieval_entry(str(retrieval_id or "").strip())
        if not isinstance(entry, dict):
            raise ResourceNotFoundError("Source retrieval collection not found")
        requested_by = entry.get("requested_by") if isinstance(entry.get("requested_by"), dict) else {}
        role = getattr(user, "role", None)
        role_value = getattr(role, "value", role) or "user"
        if int(requested_by.get("user_id") or 0) != int(user.id) and role_value != "admin":
            raise ValidationError("You do not have access to this retrieval collection")
        if str(entry.get("state") or "").upper() != "SUCCESS":
            raise ValidationError("source_retrieval_id must reference a successful retrieval collection")
        return entry

    def build_plan(
        self,
        *,
        user: User,
        source_retrieval_id: str,
        source_community: str,
        target_community: str,
        filters: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source_identifier = _normalize_identifier(source_community, field_name="source_community")
        target_identifier = _normalize_identifier(target_community, field_name="target_community")
        if source_identifier.lower() == target_identifier.lower():
            raise ValidationError("source_community and target_community must be different")
        entry = self.require_retrieval_access(source_retrieval_id, user)
        normalized_filters = _normalize_filters(filters)
        normalized_options = _normalize_options(options)
        environment = str(entry.get("environment") or "production").strip().lower()
        digest = _plan_digest_seed(
            {
                "source_retrieval_id": str(source_retrieval_id),
                "source_community": source_identifier,
                "target_community": target_identifier,
                "environment": environment,
                "filters": normalized_filters,
                "options": normalized_options,
            }
        )

        records_preview: list[dict[str, Any]] = []
        summary = _empty_summary(
            remove_source_after_verify=normalized_options.get("remove_source_after_verify"),
            target_acceptance_policy=normalized_options.get("target_acceptance_policy"),
        )
        for record in iter_retrieval_records(entry, include_compacted=False):
            if not _record_matches_filters(record, normalized_filters):
                continue
            candidate = _candidate_from_record(
                record,
                source_community=source_identifier,
                target_community=target_identifier,
            )
            if candidate is not None:
                _add_candidate_to_summary(summary, candidate)
                _update_plan_digest(digest, candidate)
                if len(records_preview) < 100:
                    records_preview.append(candidate)
        plan_checksum = digest.hexdigest()
        summary["plan_checksum"] = plan_checksum

        return {
            "source_retrieval_id": str(source_retrieval_id),
            "source_community": source_identifier,
            "target_community": target_identifier,
            "environment": environment,
            "filters": normalized_filters,
            "options": normalized_options,
            "summary": summary,
            "plan_checksum": plan_checksum,
            "records_preview": records_preview,
        }

    def create_job(
        self,
        *,
        user: User,
        source_retrieval_id: str,
        source_community: str,
        target_community: str,
        filters: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        expected_plan_checksum: str | None = None,
    ) -> CommunityMigrationJob:
        plan = self.build_plan(
            user=user,
            source_retrieval_id=source_retrieval_id,
            source_community=source_community,
            target_community=target_community,
            filters=filters,
            options=options,
        )
        expected_checksum = str(expected_plan_checksum or "").strip()
        if expected_checksum and expected_checksum != str(plan.get("plan_checksum") or ""):
            raise ValidationError("Migration plan changed since dry-run review. Rebuild the plan before queueing.")
        if int(plan["summary"].get("total_records") or 0) == 0:
            raise ValidationError("No records match the migration plan")
        if int(plan["summary"].get("append_needed") or 0) == 0 and int(plan["summary"].get("already_in_target") or 0) == 0:
            raise ValidationError("No actionable records match the migration plan")

        now = _utc_now()
        job = CommunityMigrationJob(
            requested_by_user_id=int(user.id),
            source_retrieval_id=plan["source_retrieval_id"],
            source_community=plan["source_community"],
            target_community=plan["target_community"],
            environment=plan["environment"],
            filters_json=_json_dumps(plan["filters"]),
            options_json=_json_dumps(plan["options"]),
            state="PENDING",
            phase="planned",
            summary_json=_json_dumps(plan["summary"]),
            progress_json=_json_dumps({**DEFAULT_PROGRESS, "total_records": plan["summary"]["total_records"]}),
            created_at=now,
            updated_at=now,
        )
        db.session.add(job)
        db.session.flush()
        for record in self._iter_plan_candidates(plan, user):
            db.session.add(
                CommunityMigrationRecord(
                    job_id=job.id,
                    session_id=int(record["session_id"]),
                    local_record_id=int(record["local_record_id"]),
                    zenodo_record_id=record.get("zenodo_record_id"),
                    concept_rec_id=record.get("concept_rec_id"),
                    record_title=record.get("record_title"),
                    record_status=record.get("record_status"),
                    record_origin=record.get("record_origin"),
                    is_editable=bool(record.get("is_editable")),
                    ineligibility_reason=record.get("ineligibility_reason") or None,
                    before_communities_json=_json_dumps(record.get("before_communities") or []),
                    after_communities_json=_json_dumps(record.get("after_communities") or []),
                    append_status="unchanged" if record.get("already_target") else "pending",
                    verify_status="succeeded" if record.get("already_target") else "pending",
                    remove_status="pending" if plan["options"].get("remove_source_after_verify") else "skipped",
                    final_status="pending",
                    created_at=now,
                    updated_at=now,
                )
            )
        db.session.commit()
        return job

    def _iter_plan_candidates(self, plan: dict[str, Any], user: User):
        entry = self.require_retrieval_access(plan["source_retrieval_id"], user)
        for record in iter_retrieval_records(entry, include_compacted=False):
            if not _record_matches_filters(record, plan["filters"]):
                continue
            candidate = _candidate_from_record(
                record,
                source_community=plan["source_community"],
                target_community=plan["target_community"],
            )
            if candidate is not None:
                yield candidate

    def get_job(self, job_id: str, user: User) -> CommunityMigrationJob:
        job = CommunityMigrationJob.query.filter_by(public_id=str(job_id or "").strip()).first()
        if job is None:
            raise ResourceNotFoundError("Community migration job not found")
        role = getattr(user, "role", None)
        role_value = getattr(role, "value", role) or "user"
        if int(job.requested_by_user_id) != int(user.id) and role_value != "admin":
            raise ValidationError("You do not have access to this community migration job")
        return job

    def list_jobs(self, user: User, *, limit: int = 20) -> list[dict[str, Any]]:
        role = getattr(user, "role", None)
        role_value = getattr(role, "value", role) or "user"
        query = CommunityMigrationJob.query
        if role_value != "admin":
            query = query.filter_by(requested_by_user_id=int(user.id))
        rows = query.order_by(CommunityMigrationJob.updated_at.desc()).limit(max(1, min(int(limit or 20), 50))).all()
        return [row.to_dict() for row in rows]

    def mark_queued(self, job: CommunityMigrationJob, *, task_id: str | None) -> CommunityMigrationJob:
        job.task_id = str(task_id) if task_id else None
        job.state = "PENDING"
        job.phase = "queued"
        job.updated_at = _utc_now()
        db.session.commit()
        return job

    def request_cancel(self, job: CommunityMigrationJob) -> CommunityMigrationJob:
        if str(job.state or "").upper() not in TERMINAL_STATES:
            job.state = "CANCEL_REQUESTED"
            job.phase = "cancel_requested"
            job.updated_at = _utc_now()
            db.session.commit()
        return job

    def resume_job(self, job: CommunityMigrationJob) -> CommunityMigrationJob:
        if str(job.state or "").upper() == "CANCELLED":
            raise ValidationError("Cancelled migrations cannot be resumed")
        job.state = "PENDING"
        job.phase = "queued"
        job.error = None
        job.updated_at = _utc_now()
        db.session.commit()
        return job

    def _refresh_record_communities(self, record: CommunityMigrationRecord) -> list[str]:
        session = db.session.get(DBSession, int(record.session_id))
        if not session or not session.hdpc_path or not os.path.exists(str(session.hdpc_path)):
            return record.after_communities
        conn = connect_hdpc(str(session.hdpc_path), readonly=True, timeout=30)
        try:
            row = conn.execute(
                "SELECT record_metadata_json FROM zenodo_records WHERE record_id = ?",
                (int(record.local_record_id),),
            ).fetchone()
            if not row:
                return record.after_communities
            payload = json.loads(row[0] or "{}")
            return _extract_communities(payload if isinstance(payload, dict) else {})
        except Exception:
            return record.after_communities
        finally:
            conn.close()

    def _update_job_progress(self, job: CommunityMigrationJob, *, current_record: dict[str, Any] | None = None) -> None:
        records = CommunityMigrationRecord.query.filter_by(job_id=job.id)
        total = records.count()
        processed = records.filter(CommunityMigrationRecord.final_status.in_(("succeeded", "failed", "skipped"))).count()
        failed = records.filter_by(final_status="failed").count()
        ineligible = records.filter_by(is_editable=False).count()
        succeeded = records.filter_by(final_status="succeeded").count()
        unchanged = records.filter_by(append_status="unchanged").count()
        target_verified = records.filter_by(verify_status="succeeded").count()
        source_removed = records.filter_by(remove_status="succeeded").count()
        progress = {
            "total_records": total,
            "processed": processed,
            "succeeded": succeeded,
            "unchanged": unchanged,
            "ineligible": ineligible,
            "failed": failed,
            "percent": int(round((processed / total) * 100)) if total else 100,
            "current_record": current_record,
        }
        summary = dict(job.summary)
        summary.update(
            {
                "processed": processed,
                "succeeded": succeeded,
                "failed": failed,
                "ineligible": ineligible,
                "target_verified": target_verified,
                "source_removed": source_removed,
            }
        )
        job.progress_json = _json_dumps(progress)
        job.summary_json = _json_dumps(summary)
        job.updated_at = _utc_now()
        db.session.commit()

    def execute_job(self, job_id: str, *, task_self=None) -> dict[str, Any]:
        job = CommunityMigrationJob.query.filter_by(public_id=str(job_id)).first()
        if job is None:
            raise ResourceNotFoundError("Community migration job not found")
        job.state = "PROGRESS"
        job.phase = "append_target"
        job.started_at = job.started_at or _utc_now()
        job.error = None
        db.session.commit()

        records = (
            CommunityMigrationRecord.query.filter_by(job_id=job.id)
            .order_by(CommunityMigrationRecord.id.asc())
            .yield_per(100)
        )
        remove_source = bool(job.options.get("remove_source_after_verify"))
        for record in records:
            db.session.refresh(job)
            if str(job.state or "").upper() == "CANCEL_REQUESTED":
                job.state = "CANCELLED"
                job.phase = "cancelled"
                job.completed_at = _utc_now()
                self._update_job_progress(job)
                return job.to_dict(include_records=True)
            if record.final_status == "succeeded":
                continue
            if not record.is_editable:
                record.final_status = "skipped"
                record.append_status = "ineligible"
                record.verify_status = "skipped"
                record.remove_status = "skipped"
                record.last_message = record.ineligibility_reason
                db.session.commit()
                self._update_job_progress(job, current_record=record.to_dict())
                continue

            session = db.session.get(DBSession, int(record.session_id))
            if session is None:
                record.final_status = "failed"
                record.last_error = "Session not found"
                db.session.commit()
                self._update_job_progress(job, current_record=record.to_dict())
                continue
            try:
                token_context = self.publishing_context_service.resolve_token_for_session(
                    session, job.environment, actor_user_id=job.requested_by_user_id, require_credential=True,
                )
                if record.append_status not in {"succeeded", "unchanged"}:
                    api_response = current_app.project_service.append_community_to_record(
                        local_record_id=int(record.local_record_id),
                        community_identifier=job.target_community,
                        hdpc_path=session.hdpc_path,
                        access_token=token_context.get("token"),
                    )
                    api_result = api_response.get("result") if isinstance(api_response, dict) else {}
                    status = str((api_result or {}).get("status") or "failed").lower()
                    record.append_status = status
                    record.after_communities_json = _json_dumps((api_result or {}).get("communities_after") or record.after_communities)
                    record.last_message = str((api_result or {}).get("message") or "")
                    if status not in {"succeeded", "unchanged"}:
                        raise RuntimeError(record.last_message or "Target community append failed")

                job.phase = "verify_target"
                communities = self._refresh_record_communities(record)
                if _contains_community(communities, job.target_community):
                    record.verify_status = "succeeded"
                    record.after_communities_json = _json_dumps(communities)
                else:
                    record.verify_status = "pending_moderation"
                    record.final_status = "failed"
                    if job.options.get("target_acceptance_policy") == "direct":
                        record.last_error = (
                            "Target community is not present after append. "
                            "Verify whether the target community accepts direct additions."
                        )
                    else:
                        record.last_error = "Target community is not present after append; moderation may be pending."
                    db.session.commit()
                    self._update_job_progress(job, current_record=record.to_dict())
                    continue

                if remove_source:
                    job.phase = "remove_source_if_verified"
                    if record.remove_status not in {"succeeded", "unchanged"}:
                        api_response = current_app.project_service.remove_community_from_record(
                            local_record_id=int(record.local_record_id),
                            community_identifier=job.source_community,
                            remove_all=False,
                            hdpc_path=session.hdpc_path,
                            access_token=token_context.get("token"),
                        )
                        api_result = api_response.get("result") if isinstance(api_response, dict) else {}
                        status = str((api_result or {}).get("status") or "failed").lower()
                        record.remove_status = status
                        record.after_communities_json = _json_dumps((api_result or {}).get("communities_after") or record.after_communities)
                        record.last_message = str((api_result or {}).get("message") or record.last_message or "")
                        if status not in {"succeeded", "unchanged"}:
                            raise RuntimeError(record.last_message or "Source community removal failed")
                else:
                    record.remove_status = "skipped"

                job.phase = "final_verify"
                final_communities = self._refresh_record_communities(record)
                target_ok = _contains_community(final_communities, job.target_community)
                source_removed_ok = True if not remove_source else not _contains_community(final_communities, job.source_community)
                record.after_communities_json = _json_dumps(final_communities)
                record.final_status = "succeeded" if target_ok and source_removed_ok else "failed"
                if record.final_status == "failed":
                    record.last_error = "Final verification failed"
            except Exception as exc:
                record.retry_count = int(record.retry_count or 0) + 1
                record.final_status = "failed"
                record.last_error = str(exc)
            finally:
                record.updated_at = _utc_now()
                db.session.commit()
                self._update_job_progress(job, current_record=record.to_dict())
                if task_self is not None:
                    task_self.update_state(state="PROGRESS", meta={"status": job.phase, "progress": job.progress})

        job.state = "SUCCESS" if int(job.summary.get("failed") or 0) == 0 else "FAILURE"
        job.phase = "completed"
        job.completed_at = _utc_now()
        if job.state == "FAILURE":
            job.error = "One or more records failed migration"
        self._update_job_progress(job)
        return job.to_dict(include_records=True)

    def export_job_json(self, job: CommunityMigrationJob) -> dict[str, Any]:
        return job.to_dict(include_records=True)

    def export_job_csv(self, job: CommunityMigrationJob) -> str:
        output = io.StringIO()
        fieldnames = [
            "session_id",
            "local_record_id",
            "zenodo_record_id",
            "record_title",
            "record_status",
            "append_status",
            "verify_status",
            "remove_status",
            "final_status",
            "before_communities",
            "after_communities",
            "last_error",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for record in job.records:
            payload = record.to_dict()
            writer.writerow(
                {
                    key: json.dumps(payload[key]) if key in {"before_communities", "after_communities"} else payload.get(key)
                    for key in fieldnames
                }
            )
        return output.getvalue()
