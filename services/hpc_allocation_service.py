"""HPC-Link configuration, queue, and allocation lifecycle service."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import or_

from database.database import db
from database.models import HpcAllocation, HpcArtifact, HpcLinkConfig, PipelineRun, PipelineRunStatus, PlaygroundRun, Session as DBSession, User, UserRole
from database.webhdp_link_models import LinkRun
from exceptions import APIConnectionError, AppException, ResourceNotFoundError, SecurityError, ValidationError
from services.credential_crypto import decrypt_secret, encrypt_secret
from services.cloud_upload_service import STORAGE_DROPBOX, STORAGE_GDRIVE, STORAGE_SERVER, CloudUploadService
from services.hpc_link_client import HpcLinkClient
from services.notification_service import notify_user
from services.registry_lock import OperationConflict, registry_lock, serialize_registry
from services.session_access_service import can_edit_session, is_session_mutable


TERMINAL_ALLOCATION_STATES = {"failed", "released", "expired", "cancelled"}
ACTIVE_ALLOCATION_STATES = {"allocating", "running"}
QUEUEABLE_ALLOCATION_STATES = {"queued", "allocating", "running"}
ALLOCATION_PURPOSES = {"workflow", "playground"}
MAX_SESSION_ID = 2**63 - 1
PARTITION_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
DEFAULT_PARTITION_PLACEHOLDER = "partition-a"
PARTITION_SEQUENCE_ENV = "HPC_LINK_PARTITION_SEQUENCE"
PARTITION_ATTEMPT_TIMEOUT_ENV = "HPC_LINK_PARTITION_ATTEMPT_TIMEOUT_SECONDS"
KEYED_SUBMISSION_PENDING = "CONFIRMING_SUBMISSION"
LEGACY_SUBMISSION_PENDING = "CONFIRMING_LEGACY_SUBMISSION"
SUBMISSION_RETRY_DELAY = timedelta(seconds=30)


def _utc_now_naive() -> datetime:
    return datetime.utcnow()


def _parse_datetime(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def mask_secret(value: str) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    if len(token) <= 8:
        return f"{token[:2]}***{token[-2:]}"
    return f"{token[:4]}...{token[-4:]}"


def _env_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value in (None, ""):
        return default
    return int(raw_value)


def _json_list(value: Any) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


class HpcQuotaExceeded(AppException):
    status_code = 429
    error_code = "HPC_QUOTA_EXCEEDED"


def parse_allocation_integer(value: Any, *, name: str, minimum: int, maximum: Optional[int] = None) -> int:
    if type(value) in (int, str):
        try:
            number = int(value)
        except ValueError:
            pass
        else:
            if number >= minimum and (maximum is None or number <= maximum):
                return number
    if maximum is not None:
        raise ValidationError(f"{name} must be a whole number from {minimum} to {maximum}.")
    raise ValidationError(f"{name} must be a non-negative integer" if minimum == 0 else f"{name} must be a positive integer.")


def validate_allocation_purpose(purpose: str) -> str:
    if purpose not in ALLOCATION_PURPOSES:
        raise ValidationError("Select workflow or playground as the allocation purpose.")
    return purpose


class HpcAllocationService:
    """Coordinates WebHDP-side allocation permissions and HPC-Link API calls."""

    def _notify_allocation(self, allocation: HpcAllocation, *, notification_type: str, title: str, body: str, severity: str = "info") -> None:
        notify_user(
            recipient_user_id=allocation.user_id,
            notification_type=notification_type,
            category="hpc",
            severity=severity,
            title=title,
            body=body,
            session_id=allocation.session_id,
            entity_type="hpc_allocation",
            entity_id=allocation.public_id,
            action_url="/tools/hpc-diagnostics",
            dedupe_key=f"hpc:{allocation.public_id}:{notification_type}",
        )

    def get_or_create_config(self) -> HpcLinkConfig:
        config = HpcLinkConfig.query.order_by(HpcLinkConfig.id.asc()).first()
        if config is None:
            config = HpcLinkConfig(
                enabled=False,
                base_url=os.environ.get("HPC_LINK_BASE_URL"),
                encrypted_token=encrypt_secret(os.environ.get("HPC_LINK_API_KEY", "")) if os.environ.get("HPC_LINK_API_KEY") else None,
                masked_token_preview=mask_secret(os.environ.get("HPC_LINK_API_KEY", "")),
                default_partition=os.environ.get("HPC_LINK_DEFAULT_PARTITION", DEFAULT_PARTITION_PLACEHOLDER),
                default_gpu_type=os.environ.get("HPC_LINK_DEFAULT_GPU_TYPE") or None,
                default_gpu_count=_env_int("HPC_LINK_DEFAULT_GPU_COUNT", 1),
                default_duration_minutes=_env_int("HPC_LINK_DEFAULT_DURATION_MINUTES", 30),
                max_active_allocations=_env_int("HPC_LINK_MAX_ACTIVE_ALLOCATIONS", 3),
                max_active_allocations_per_user=_env_int("HPC_LINK_MAX_ACTIVE_ALLOCATIONS_PER_USER", 1),
            )
            db.session.add(config)
            db.session.commit()
        return config

    def serialize_config(self, config: Optional[HpcLinkConfig] = None) -> Dict[str, Any]:
        config = config or self.get_or_create_config()
        return {
            "enabled": bool(config.enabled),
            "require_for_components": bool(config.require_for_components),
            "base_url": config.base_url or "",
            "has_token": bool(config.encrypted_token) or bool(
                os.environ.get("HPC_LINK_USERNAME") and os.environ.get("HPC_LINK_PASSWORD")
                and str(config.base_url or "").rstrip("/") == os.environ.get("HPC_LINK_BASE_URL", "").rstrip("/")
            ),
            "masked_token_preview": config.masked_token_preview or "",
            "default_partition": config.default_partition,
            "partition_sequence_configured": bool(self._env_partition_sequence()),
            "partition_attempt_timeout_seconds": self.partition_attempt_timeout_seconds(),
            "default_gpu_type": config.default_gpu_type,
            "default_gpu_count": int(config.default_gpu_count if config.default_gpu_count is not None else 1),
            "default_duration_minutes": int(config.default_duration_minutes or 30),
            "max_active_allocations": int(config.max_active_allocations or 3),
            "max_active_allocations_per_user": int(config.max_active_allocations_per_user or 1),
            "remote_data_root": config.remote_data_root or "",
            "remote_apps_root": config.remote_apps_root or "",
            "last_validation_status": config.last_validation_status,
            "last_validation_error": config.last_validation_error,
            "last_validated_at": config.last_validated_at.isoformat() if config.last_validated_at else None,
        }

    def update_config(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        config = self.get_or_create_config()
        for field in (
            "enabled",
            "require_for_components",
            "base_url",
            "default_partition",
            "default_gpu_type",
            "remote_data_root",
            "remote_apps_root",
        ):
            if field in payload:
                setattr(config, field, payload.get(field))

        for field in (
            "default_gpu_count",
            "default_duration_minutes",
            "max_active_allocations",
            "max_active_allocations_per_user",
        ):
            if field in payload:
                value = int(payload.get(field) if payload.get(field) not in (None, "") else 0)
                if field == "default_gpu_count":
                    if value < 0:
                        raise ValidationError("default_gpu_count must be zero or positive")
                elif value <= 0:
                    raise ValidationError(f"{field} must be positive")
                setattr(config, field, value)

        if "token" in payload:
            token = str(payload.get("token") or "").strip()
            if token:
                config.encrypted_token = encrypt_secret(token)
                config.masked_token_preview = mask_secret(token)
            elif payload.get("clear_token") is True:
                config.encrypted_token = None
                config.masked_token_preview = None

        config.updated_at = _utc_now_naive()
        db.session.commit()
        return self.serialize_config(config)

    def _token(self, config: HpcLinkConfig) -> str:
        if not config.encrypted_token:
            return ""
        return decrypt_secret(config.encrypted_token)

    def client(self, config: Optional[HpcLinkConfig] = None) -> HpcLinkClient:
        config = config or self.get_or_create_config()
        if not config.enabled:
            raise ValidationError("HPC-Link is disabled")
        return HpcLinkClient(base_url=config.base_url or "", token=self._token(config))

    def validate_config(self) -> Dict[str, Any]:
        config = self.get_or_create_config()
        try:
            apps = self.client(config).get("/api/apps", timeout=10)
            app_ids = {str(item.get("app_id")) for item in apps if isinstance(item, dict)}
            if "webhdp" not in app_ids:
                raise ValidationError("HPC-Link is reachable, but the webhdp app adapter is not registered")
            config.last_validation_status = "valid"
            config.last_validation_error = None
        except Exception as exc:
            config.last_validation_status = "invalid"
            config.last_validation_error = str(exc)
        config.last_validated_at = _utc_now_naive()
        db.session.commit()
        return self.serialize_config(config)

    @staticmethod
    def user_can_allocate(user: User, *, purpose: str = "workflow") -> bool:
        if not user:
            return False
        if user.role == UserRole.ADMIN:
            return True
        return bool(user.is_verified and (user.has_capability("hpc_link_access")
                    or purpose == "playground" and user.role == UserRole.MODERATOR))

    def require_allocation_access(self, user: User, *, purpose: str = "workflow") -> None:
        if not user.is_verified and user.role != UserRole.ADMIN:
            raise SecurityError("Verified account required for HPC-Link allocations")
        if not self.user_can_allocate(user, purpose=purpose):
            raise SecurityError("HPC-Link access is not enabled for this account")

    def serialize_allocation(self, allocation: HpcAllocation) -> Dict[str, Any]:
        return {
            "allocation_id": allocation.public_id,
            "reservation_id": allocation.reservation.public_id if allocation.reservation_id else None,
            "user_id": allocation.user_id,
            "session_id": allocation.session_id,
            "purpose": allocation.purpose,
            "status": allocation.status,
            "can_release": (allocation.status in QUEUEABLE_ALLOCATION_STATES
                            and not self._awaiting_submission_confirmation(allocation)
                            and not self.allocation_is_in_use(allocation)),
            "awaiting_confirmation": self._awaiting_submission_confirmation(allocation),
            "requested_partition": allocation.requested_partition,
            "partition_attempt_index": int(allocation.partition_attempt_index or 0),
            "partition_attempt_started_at": allocation.partition_attempt_started_at.isoformat()
            if allocation.partition_attempt_started_at
            else None,
            "partition_attempt_history": _json_list(allocation.partition_attempt_history_json),
            "requested_gpu_type": allocation.requested_gpu_type,
            "requested_gpu_count": allocation.requested_gpu_count,
            "requested_duration_minutes": allocation.requested_duration_minutes,
            "remote_session_id": allocation.remote_session_id,
            "remote_job_id": allocation.remote_job_id,
            "remote_session_dir": allocation.remote_session_dir,
            "remote_input_dir": allocation.remote_input_dir,
            "remote_output_dir": allocation.remote_output_dir,
            "scheduler_state": allocation.scheduler_state,
            "scheduler_reason": allocation.scheduler_reason,
            "node_name": allocation.node_name,
            "last_health": json.loads(allocation.last_health_json or "{}"),
            "last_error": allocation.last_error,
            "requested_at": allocation.requested_at.isoformat() if allocation.requested_at else None,
            "allocated_at": allocation.allocated_at.isoformat() if allocation.allocated_at else None,
            "expires_at": allocation.expires_at.isoformat() if allocation.expires_at else None,
            "released_at": allocation.released_at.isoformat() if allocation.released_at else None,
        }

    @staticmethod
    def parse_partition_sequence(value: Any) -> list[str]:
        if isinstance(value, (list, tuple)):
            raw_items = value
        else:
            raw_items = str(value or "").split(",")
        partitions: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            partition = str(item or "").strip()
            if not partition:
                continue
            if not PARTITION_TOKEN_RE.match(partition):
                raise ValidationError(f"Invalid HPC partition token: {partition}")
            if partition not in seen:
                partitions.append(partition)
                seen.add(partition)
        return partitions

    def _env_partition_sequence(self) -> list[str]:
        return self.parse_partition_sequence(os.environ.get(PARTITION_SEQUENCE_ENV, ""))

    def partition_attempt_timeout_seconds(self) -> int:
        try:
            return max(1, _env_int(PARTITION_ATTEMPT_TIMEOUT_ENV, 300))
        except (TypeError, ValueError):
            return 300

    def _partition_sequence_for_request(self, config: HpcLinkConfig, payload: Dict[str, Any]) -> list[str]:
        env_sequence = self._env_partition_sequence()
        if env_sequence:
            return env_sequence
        explicit_partition = str(payload.get("partition") or "").strip()
        configured_partition = str(config.default_partition or "").strip()
        return self.parse_partition_sequence(explicit_partition or configured_partition or DEFAULT_PARTITION_PLACEHOLDER)

    def _allocation_partition_sequence(self, allocation: HpcAllocation) -> list[str]:
        sequence = self.parse_partition_sequence(_json_list(allocation.partition_sequence_json))
        if sequence:
            return sequence
        return self.parse_partition_sequence(allocation.requested_partition or DEFAULT_PARTITION_PLACEHOLDER)

    def _allocation_attempt_history(self, allocation: HpcAllocation) -> list[Dict[str, Any]]:
        history = _json_list(allocation.partition_attempt_history_json)
        return [item for item in history if isinstance(item, dict)]

    def _append_attempt_history(
        self,
        allocation: HpcAllocation,
        *,
        status: str,
        message: Optional[str] = None,
        remote_cancelled: Optional[bool] = None,
    ) -> None:
        started_at = allocation.partition_attempt_started_at
        elapsed_seconds = None
        if started_at is not None:
            elapsed_seconds = max(0, int((_utc_now_naive() - started_at).total_seconds()))
        history = self._allocation_attempt_history(allocation)
        entry: Dict[str, Any] = {
            "partition": allocation.requested_partition,
            "attempt_index": int(allocation.partition_attempt_index or 0),
            "status": status,
            "remote_session_id": allocation.remote_session_id,
            "remote_job_id": allocation.remote_job_id,
            "scheduler_state": allocation.scheduler_state,
            "scheduler_reason": allocation.scheduler_reason,
            "started_at": started_at.isoformat() if started_at else None,
            "finished_at": _utc_now_naive().isoformat(),
            "elapsed_seconds": elapsed_seconds,
        }
        if message:
            entry["message"] = message
        if remote_cancelled is not None:
            entry["remote_cancelled"] = bool(remote_cancelled)
        history.append(entry)
        allocation.partition_attempt_history_json = json.dumps(history, sort_keys=True, default=str)

    def _clear_remote_attempt_fields(self, allocation: HpcAllocation) -> None:
        allocation.remote_session_id = None
        allocation.remote_job_id = None
        allocation.remote_session_dir = None
        allocation.remote_input_dir = None
        allocation.remote_output_dir = None
        allocation.scheduler_state = None
        allocation.scheduler_reason = None
        allocation.node_name = None
        allocation.expires_at = None
        allocation.allocated_at = None
        allocation.last_health_json = None

    def _active_count(self, *, user_id: Optional[int] = None) -> int:
        query = HpcAllocation.query.filter(HpcAllocation.status.in_(ACTIVE_ALLOCATION_STATES),
            or_(HpcAllocation.reservation_id.is_(None), HpcAllocation.expires_at.is_(None),
                HpcAllocation.expires_at > _utc_now_naive()))
        if user_id is not None:
            query = query.filter(HpcAllocation.user_id == int(user_id))
        return int(query.count())

    def _queued_count(self, *, user_id: Optional[int] = None) -> int:
        query = HpcAllocation.query.filter_by(status="queued")
        if user_id is not None:
            query = query.filter_by(user_id=user_id)
        return query.count()

    @staticmethod
    def allocation_is_in_use(allocation: HpcAllocation) -> bool:
        if allocation.status != "running" or allocation.session_id is None:
            return False
        if any(model.query.filter(model.session_id == allocation.session_id,
                model.status.in_({PipelineRunStatus.PENDING, PipelineRunStatus.RUNNING})).first()
                for model in (PipelineRun, PlaygroundRun)):
            return True
        return LinkRun.query.filter(LinkRun.session_id == allocation.session_id,
                                    LinkRun.status.in_({"queued", "running"})).first() is not None

    @staticmethod
    def _request_limits() -> Dict[str, int]:
        return {
            "queued_limit": max(1, _env_int("HPC_LINK_MAX_QUEUED_ALLOCATIONS_PER_USER", 2)),
            "global_queued_limit": max(1, _env_int("HPC_LINK_MAX_QUEUED_ALLOCATIONS", 24)),
            "max_gpu_count": min(4, max(0, _env_int("HPC_LINK_MAX_GPUS_PER_ALLOCATION", 4))),
            "max_duration_minutes": min(10080, max(5, _env_int("HPC_LINK_MAX_DURATION_MINUTES_PER_ALLOCATION", 10080))),
        }

    def allocation_quota(self, user: User, config: HpcLinkConfig) -> Dict[str, int]:
        limits = self._request_limits()
        return {
            "active": self._active_count(user_id=user.id),
            "active_limit": min(int(config.max_active_allocations_per_user or 1), int(config.max_active_allocations or 1)),
            "queued": self._queued_count(user_id=user.id),
            **{key: limits[key] for key in ("queued_limit", "max_gpu_count", "max_duration_minutes")},
        }

    def list_user_allocations(self, user: User) -> list[Dict[str, Any]]:
        rows = (HpcAllocation.query.filter(HpcAllocation.user_id == user.id,
                HpcAllocation.status.in_(QUEUEABLE_ALLOCATION_STATES))
                .order_by(HpcAllocation.requested_at.desc(), HpcAllocation.id.desc()).all())
        return [self.serialize_allocation(row) for row in rows]

    def _can_start_next(self, config: HpcLinkConfig, allocation: HpcAllocation) -> bool:
        if self._active_count() >= int(config.max_active_allocations or 1):
            return False
        if self._active_count(user_id=allocation.user_id) >= int(config.max_active_allocations_per_user or 1):
            return False
        return True

    @serialize_registry("hpc-allocation-queue")
    def request_allocation(self, *, user: User, session_id: Optional[int], purpose: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        config = self.get_or_create_config()
        if not config.enabled:
            raise ValidationError("HPC-Link is not enabled on this WebHDP instance")
        validate_allocation_purpose(purpose)
        self.require_allocation_access(user, purpose=purpose)

        if session_id is not None:
            session_id = parse_allocation_integer(session_id, name="Session ID", minimum=1, maximum=MAX_SESSION_ID)
            session_row = db.session.get(DBSession, session_id)
            if session_row is None:
                raise ResourceNotFoundError("Session not found")
            if session_row.user_id != user.id and user.role != UserRole.ADMIN:
                raise SecurityError("Access denied for this workflow session")
            if not is_session_mutable(session_row):
                raise SecurityError("This read-only session cannot request an HPC allocation")
        elif purpose == "playground":
            raise ValidationError("Select an upload session before requesting a Playground allocation.")

        limits = self._request_limits()
        raw_gpu_count = payload.get("gpu_count")
        explicit_gpu_count = raw_gpu_count not in (None, "")
        requested_gpu_count = parse_allocation_integer(
            raw_gpu_count if explicit_gpu_count else config.default_gpu_count if config.default_gpu_count is not None else 1,
            name="GPU count", minimum=0,
        )
        if requested_gpu_count > limits["max_gpu_count"]:
            raise HpcQuotaExceeded(f"An allocation can request at most {limits['max_gpu_count']} GPUs.")
        raw_duration = payload.get("duration_minutes")
        requested_duration = parse_allocation_integer(
            raw_duration if raw_duration not in (None, "") else config.default_duration_minutes or 30,
            name="Allocation duration in minutes", minimum=5, maximum=10080,
        )
        if requested_duration > limits["max_duration_minutes"]:
            raise HpcQuotaExceeded(f"An allocation can request at most {limits['max_duration_minutes']} minutes.")
        gpu_type = str(payload.get("gpu_type") or config.default_gpu_type or "").strip() or None
        if gpu_type and not PARTITION_TOKEN_RE.fullmatch(gpu_type):
            raise ValidationError("GPU type must be a Slurm resource name.")

        existing = HpcAllocation.query.filter_by(session_id=session_id).filter(
            HpcAllocation.status.in_(QUEUEABLE_ALLOCATION_STATES))
        if session_id is not None:
            existing = existing.filter(or_(HpcAllocation.purpose == purpose, HpcAllocation.reservation_id.is_not(None)))
        else:
            existing = existing.filter_by(user_id=user.id, purpose=purpose)
        existing = existing.order_by(HpcAllocation.requested_at.desc(), HpcAllocation.id.desc()).first()
        if existing is not None:
            if existing.user_id != user.id:
                raise OperationConflict("This upload session already has an HPC allocation owned by another account.")
            self.process_queue()
            if existing.status in QUEUEABLE_ALLOCATION_STATES:
                if explicit_gpu_count and existing.requested_gpu_count < requested_gpu_count:
                    raise ValidationError(f"The existing allocation has {existing.requested_gpu_count} GPU(s). Release it before requesting {requested_gpu_count} GPU(s).")
                return self.serialize_allocation(existing)

        self.process_queue()
        if self._queued_count(user_id=user.id) >= limits["queued_limit"]:
            raise HpcQuotaExceeded("Your HPC queue is full. Cancel a queued request or wait for it to start.")
        if self._queued_count() >= limits["global_queued_limit"]:
            raise HpcQuotaExceeded("The WebHDP HPC queue is full. Try again when a request starts or finishes.")

        partition_sequence = self._partition_sequence_for_request(config, payload)
        allocation = HpcAllocation(
            user_id=user.id,
            session_id=session_id,
            purpose=purpose,
            status="queued",
            requested_partition=partition_sequence[0],
            requested_gpu_type=gpu_type,
            requested_gpu_count=requested_gpu_count,
            requested_duration_minutes=requested_duration,
            partition_sequence_json=json.dumps(partition_sequence),
            partition_attempt_index=0,
        )
        db.session.add(allocation)
        db.session.commit()
        self._notify_allocation(
            allocation,
            notification_type="hpc.allocation_queued",
            title="HPC allocation queued",
            body=f"Your {allocation.purpose} allocation is waiting for an available slot.",
        )
        db.session.commit()
        self.process_queue()
        return self.serialize_allocation(allocation)

    def process_queue(self) -> None:
        try:
            with registry_lock('hpc-allocation-queue'):
                db.session.expire_all()
                self._process_queue()
        except OperationConflict:
            return  # Another request is already advancing the shared queue.

    def poll_allocation(self, allocation: HpcAllocation) -> Dict[str, Any]:
        try:
            with registry_lock('hpc-allocation-queue'):
                db.session.expire_all()
                self._process_queue()
                return self.refresh_allocation(allocation)
        except OperationConflict:
            db.session.refresh(allocation)
            return self.serialize_allocation(allocation)

    def _process_queue(self) -> None:
        config = self.get_or_create_config()
        if not config.enabled:
            return
        for allocation in HpcAllocation.query.filter(
            HpcAllocation.status.in_(list(ACTIVE_ALLOCATION_STATES))
        ).order_by(HpcAllocation.requested_at.asc()).all():
            self.refresh_allocation(allocation)
        queue_deadline = _utc_now_naive() - timedelta(minutes=max(1, _env_int("HPC_LINK_QUEUED_REQUEST_TTL_MINUTES", 1440)))
        queued = HpcAllocation.query.filter_by(status="queued").order_by(HpcAllocation.requested_at.asc(), HpcAllocation.id.asc()).all()
        for allocation in queued:
            if allocation.requested_at <= queue_deadline:
                allocation.status = "expired"
                allocation.last_error = "The queued request expired before receiving an allocation."
                db.session.commit()
                continue
            if allocation.purpose not in ALLOCATION_PURPOSES or not self.user_can_allocate(allocation.user, purpose=allocation.purpose):
                allocation.status = "cancelled"
                allocation.last_error = "HPC access is no longer enabled for this account."
                db.session.commit()
                continue
            if not self._can_start_next(config, allocation):
                continue
            self._start_allocation(allocation, config)

    @staticmethod
    def _awaiting_submission_confirmation(allocation: HpcAllocation) -> bool:
        return (allocation.reservation_id is None and allocation.status == "allocating"
                and not allocation.remote_session_id and allocation.partition_attempt_started_at is not None)

    @staticmethod
    def _submission_request_id(allocation: HpcAllocation) -> str:
        return str(uuid5(NAMESPACE_URL, f"webhdp-allocation:{allocation.public_id}:{allocation.partition_attempt_index or 0}"))

    def _record_submission(self, allocation: HpcAllocation, response: Any) -> None:
        if not isinstance(response, dict) or not response.get("session_id") or not response.get("job_id"):
            raise APIConnectionError("HPC-Link did not return an allocation handle")
        allocation.remote_session_id = response["session_id"]
        allocation.remote_job_id = response["job_id"]
        allocation.remote_session_dir = response.get("remote_session_dir")
        allocation.remote_input_dir = response.get("input_dir")
        allocation.remote_output_dir = response.get("output_dir")
        allocation.scheduler_state = response.get("scheduler_state") or response.get("status")
        allocation.status = "running" if str(response.get("status") or "").lower() == "running" else "allocating"
        allocation.expires_at = _parse_datetime(response.get("expires_at"))
        allocation.last_health_json = json.dumps(response, sort_keys=True, default=str)
        allocation.last_error = None
        if allocation.status == "running":
            allocation.allocated_at = _utc_now_naive()
            self._notify_allocation(
                allocation,
                notification_type="hpc.allocation_running",
                title="HPC allocation is running",
                body="Your HPC allocation is ready for workflow operations.",
                severity="success",
            )

    def _start_allocation(self, allocation: HpcAllocation, config: HpcLinkConfig, *, retry: bool = False) -> None:
        allocation.status = "allocating"
        allocation.scheduler_state = KEYED_SUBMISSION_PENDING
        allocation.partition_attempt_started_at = _utc_now_naive()
        allocation.last_error = None
        db.session.commit()
        try:
            payload = {
                "request_id": self._submission_request_id(allocation),
                "partition": allocation.requested_partition,
                "gpu_type": allocation.requested_gpu_type,
                "gpu_count": allocation.requested_gpu_count,
                "duration_minutes": allocation.requested_duration_minutes,
                "webhdp_session_id": allocation.session_id,
                "purpose": allocation.purpose,
            }
            client = self.client(config)
            try:
                response = client.post("/api/apps/webhdp/sessions/requests", payload, timeout=60)
            except APIConnectionError as exc:
                if retry or exc.details.get("http_status") not in {404, 405}:
                    raise
                # Older gateways understand only the unkeyed route. Record that
                # this attempt cannot be replayed even after the gateway upgrades.
                allocation.scheduler_state = LEGACY_SUBMISSION_PENDING
                db.session.commit()
                payload.pop("request_id")
                response = client.post("/api/apps/webhdp/sessions", payload, timeout=60)
            self._record_submission(allocation, response)
        except Exception as exc:
            allocation.last_error = str(exc)
            http_status = exc.details.get("http_status") if isinstance(exc, APIConnectionError) else None
            if not retry and (isinstance(exc, ValidationError) or http_status in {400, 401, 403, 422, 429}):
                allocation.status = "failed"
                self._append_attempt_history(allocation, status="failed", message=str(exc))
                self._notify_allocation(
                    allocation,
                    notification_type="hpc.allocation_failed",
                    title="HPC allocation failed",
                    body="HPC-Link rejected the allocation request. Contact an administrator if this keeps happening.",
                    severity="error",
                )
            elif allocation.remote_session_id is None:
                self._notify_allocation(
                    allocation,
                    notification_type="hpc.allocation_unconfirmed",
                    title="Waiting for HPC submission confirmation",
                    body="HPC-Link has not confirmed the request yet. It still counts towards your allocation limit.",
                    severity="warning",
                )
        db.session.commit()

    def _recover_submission(self, allocation: HpcAllocation, *, retry_missing: bool = False) -> None:
        if allocation.scheduler_state != KEYED_SUBMISSION_PENDING:
            return
        request_id = self._submission_request_id(allocation)
        try:
            response = self.client().get(f"/api/apps/webhdp/sessions/requests/{request_id}", timeout=10)
            if isinstance(response, dict) and response.get("session_id") == request_id:
                self._record_submission(allocation, response)
                db.session.commit()
                return
        except AppException:
            return
        # Only a gateway that supports request identity can return a successful null.
        if (response is None and retry_missing
                and _utc_now_naive() - allocation.partition_attempt_started_at >= SUBMISSION_RETRY_DELAY
                and self.user_can_allocate(allocation.user, purpose=allocation.purpose)):
            config = self.get_or_create_config()
            if config.enabled and (allocation.session_id is None or
                    (can_edit_session(allocation.session, allocation.user) and is_session_mutable(allocation.session))):
                self._start_allocation(allocation, config, retry=True)

    def _cancel_remote_attempt(self, allocation: HpcAllocation) -> tuple[bool, str]:
        if not allocation.remote_session_id:
            return False, "No remote session was created for this attempt"
        try:
            response = self.client().delete(f"/api/apps/webhdp/sessions/{allocation.remote_session_id}", timeout=30)
            if response and response.get("cancelled") is True:
                return True, "Remote HPC-Link session cancelled"
            return False, "HPC-Link could not confirm cancellation."
        except Exception as exc:
            allocation.last_error = str(exc)
            return False, str(exc)

    def _attempt_timed_out(self, allocation: HpcAllocation) -> bool:
        if allocation.status != "allocating" or allocation.partition_attempt_started_at is None:
            return False
        elapsed = (_utc_now_naive() - allocation.partition_attempt_started_at).total_seconds()
        return elapsed >= self.partition_attempt_timeout_seconds()

    def _advance_partition_attempt(self, allocation: HpcAllocation, config: Optional[HpcLinkConfig] = None) -> bool:
        sequence = self._allocation_partition_sequence(allocation)
        current_index = int(allocation.partition_attempt_index or 0)
        cancelled, cancel_message = self._cancel_remote_attempt(allocation)
        self._append_attempt_history(
            allocation,
            status="timed_out",
            message=cancel_message,
            remote_cancelled=cancelled,
        )
        next_index = current_index + 1
        if not cancelled:
            allocation.last_error = "HPC-Link could not confirm cancellation. The request still uses an allocation slot."
            allocation.partition_attempt_started_at = _utc_now_naive()
            db.session.commit()
            return False
        if next_index >= len(sequence):
            allocation.status = "failed"
            allocation.last_error = (
                "HPC allocation timed out on all configured partitions before resources became available."
            )
            db.session.commit()
            self._notify_allocation(
                allocation,
                notification_type="hpc.allocation_failed",
                title="HPC allocation failed",
                body=allocation.last_error,
                severity="error",
            )
            return False

        allocation.partition_attempt_index = next_index
        allocation.requested_partition = sequence[next_index]
        allocation.status = "queued"
        allocation.last_error = None
        self._clear_remote_attempt_fields(allocation)
        db.session.commit()
        self._start_allocation(allocation, config or self.get_or_create_config())
        return True

    def get_allocation(self, public_id: str, user: Optional[User] = None) -> HpcAllocation:
        allocation = HpcAllocation.query.filter_by(public_id=public_id).first()
        if allocation is None:
            raise ResourceNotFoundError("HPC allocation not found")
        if user and user.role != UserRole.ADMIN and allocation.user_id != user.id:
            raise SecurityError("Access denied for this HPC allocation")
        return allocation

    def get_allocation_for_compute(self, public_id: str, user: User) -> HpcAllocation:
        allocation = self.get_allocation(public_id, user)
        self.require_allocation_access(user, purpose=allocation.purpose)
        if allocation.reservation_id and allocation.user_id != user.id:
            raise SecurityError("Only the account holding this reserved GPU claim can use it")
        if allocation.session_id is not None and (
            not is_session_mutable(allocation.session) or not can_edit_session(allocation.session, user)
        ):
            raise SecurityError("Editing access to the allocation's upload session is required")
        if (allocation.status != "running" or not allocation.remote_session_id
                or allocation.expires_at and allocation.expires_at <= _utc_now_naive()):
            raise ValidationError("An active HPC allocation is required for this operation.")
        return allocation

    def get_active_for_session(self, session_id: int, *, user_id: Optional[int] = None, purpose: str = "workflow") -> Optional[HpcAllocation]:
        now = _utc_now_naive()
        candidates = (
            HpcAllocation.query.filter(
                HpcAllocation.session_id == int(session_id),
                HpcAllocation.status == "running",
                HpcAllocation.remote_session_id.is_not(None),
                HpcAllocation.remote_session_id != "",
                or_(HpcAllocation.expires_at.is_(None), HpcAllocation.expires_at > now),
            )
            .order_by(HpcAllocation.allocated_at.desc(), HpcAllocation.id.desc())
            .all()
        )
        actor = db.session.get(User, int(user_id)) if user_id is not None else None
        if user_id is not None and (not actor or not self.user_can_allocate(actor, purpose=purpose)):
            return None
        for allocation in candidates:
            if not allocation.user or not self.user_can_allocate(allocation.user, purpose=allocation.purpose):
                continue
            if allocation.reservation_id is None:
                if actor is None or (can_edit_session(allocation.session, actor) and is_session_mutable(allocation.session)):
                    return allocation
                continue
            if (allocation.user_id == user_id and allocation.expires_at and allocation.reservation.enabled
                    and is_session_mutable(allocation.session)):
                from services.hpc_reservation_service import HpcReservationService

                if HpcReservationService(self).can_use(allocation.reservation, allocation.user):
                    return allocation
        return None

    def session_allocation_status(self, session_id: int, user: User, purpose: str) -> Dict[str, Any]:
        """Describe the caller's latest request without polling or allocating."""
        active = self.get_active_for_session(session_id, user_id=user.id, purpose=purpose)
        visible = active if active is not None and active.user_id == user.id else None
        if visible is None:
            visible = (HpcAllocation.query.filter(
                HpcAllocation.session_id == session_id,
                HpcAllocation.user_id == user.id,
                or_(HpcAllocation.purpose == purpose, HpcAllocation.reservation_id.is_not(None)),
            ).order_by(HpcAllocation.requested_at.desc(), HpcAllocation.id.desc()).first())
        status = visible.status if visible else None
        if status == "running" and visible is not active:
            # The recorded request may have expired or lost its reservation grant.
            status = "expired" if visible.expires_at and visible.expires_at <= _utc_now_naive() else None
        return {
            "active_hpc_allocation": active is not None,
            "active_hpc_gpu_count": active.requested_gpu_count if active is not None else None,
            "gpu_allocation_status": status,
            "gpu_allocation_id": visible.public_id if status else None,
            "gpu_allocation_gpu_count": visible.requested_gpu_count if status else None,
            "gpu_allocation_scheduler_reason": visible.scheduler_reason if status else None,
        }

    def _reservation_client(self, allocation: HpcAllocation, *, for_compute=True) -> HpcLinkClient:
        if getattr(allocation, "reservation_id", None) is None:
            if for_compute and isinstance(allocation, HpcAllocation) and allocation.id is not None:
                db.session.refresh(allocation)
                db.session.refresh(allocation.user)
                self.require_allocation_access(allocation.user, purpose=allocation.purpose)
                if allocation.status != "running" or (allocation.expires_at and allocation.expires_at <= _utc_now_naive()):
                    raise ValidationError("An active HPC allocation is required for this operation.")
                if allocation.session_id is not None and not is_session_mutable(allocation.session):
                    raise SecurityError("This read-only session cannot use an HPC allocation")
            return self.client()
        from services.hpc_reservation_service import HpcReservationService

        reservations = HpcReservationService(self)
        if for_compute:
            db.session.refresh(allocation)
            if allocation.status != "running" or not allocation.expires_at or allocation.expires_at <= _utc_now_naive():
                raise ValidationError("This reserved GPU claim has ended")
            db.session.refresh(allocation.user)
            if not is_session_mutable(allocation.session):
                raise SecurityError("This read-only session cannot use an HPC allocation")
            if not allocation.reservation.enabled or not reservations.can_use(allocation.reservation, allocation.user):
                raise SecurityError("Access to this reserved GPU is no longer enabled")
        return reservations.client_for(allocation.reservation)

    @serialize_registry("hpc-allocation-queue")
    def attach_allocation_to_session(self, public_id: str, user: User, session_id: int) -> Dict[str, Any]:
        allocation = self.get_allocation(public_id, user)
        self.require_allocation_access(user, purpose=allocation.purpose)
        session_row = db.session.get(DBSession, int(session_id))
        if session_row is None:
            raise ResourceNotFoundError("Session not found")
        if session_row.user_id != user.id and user.role != UserRole.ADMIN:
            raise SecurityError("Access denied for this workflow session")
        if not is_session_mutable(session_row):
            raise SecurityError("This read-only session cannot use an HPC allocation")
        if allocation.session_id not in (None, int(session_id)):
            raise ValidationError("HPC allocation is already attached to another workflow session")
        if HpcAllocation.query.filter(
            HpcAllocation.session_id == int(session_id), HpcAllocation.status.in_(QUEUEABLE_ALLOCATION_STATES),
            or_(HpcAllocation.purpose == allocation.purpose, HpcAllocation.reservation_id.is_not(None)), HpcAllocation.id != allocation.id,
        ).first():
            raise OperationConflict("This upload session already has an HPC allocation")
        allocation.session_id = int(session_id)
        db.session.commit()
        return self.serialize_allocation(allocation)

    def refresh_allocation(self, allocation: HpcAllocation) -> Dict[str, Any]:
        if allocation.reservation_id is not None and allocation.status in ACTIVE_ALLOCATION_STATES:
            if allocation.expires_at and allocation.expires_at <= _utc_now_naive():
                allocation.status = "expired"
                db.session.commit()
                return self.serialize_allocation(allocation)
            if allocation.status == "allocating" and not allocation.remote_session_id:
                from services.hpc_reservation_service import HpcReservationService

                HpcReservationService(self).complete_claim(allocation)
                return self.serialize_allocation(allocation)
        if self._awaiting_submission_confirmation(allocation):
            self._recover_submission(allocation, retry_missing=True)
        if not allocation.remote_session_id or allocation.status in TERMINAL_ALLOCATION_STATES:
            return self.serialize_allocation(allocation)
        previous_status = allocation.status
        try:
            response = self._reservation_client(allocation, for_compute=False).get(
                f"/api/apps/webhdp/sessions/{allocation.remote_session_id}", timeout=20,
            )
            allocation.scheduler_state = response.get("scheduler_state")
            allocation.scheduler_reason = response.get("scheduler_reason")
            allocation.node_name = response.get("node_name")
            allocation.expires_at = _parse_datetime(response.get("expires_at")) or allocation.expires_at
            allocation.last_health_json = json.dumps(response, sort_keys=True, default=str)
            remote_status = str(response.get("status") or "").lower()
            if remote_status == "running":
                allocation.status = "running"
                allocation.allocated_at = allocation.allocated_at or _utc_now_naive()
            elif remote_status in {"finished", "expired", "failed", "cancelled"}:
                allocation.status = "expired"
            elif remote_status in {"queued", "allocating"}:
                if allocation.status == "running":
                    allocation.partition_attempt_started_at = _utc_now_naive()
                allocation.status = "allocating"
            if response.get("scheduler_state") in {"CANCELLED", "FAILED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL"}:
                allocation.status = "expired"
        except Exception as exc:
            allocation.last_error = str(exc)
        if self._attempt_timed_out(allocation):
            self._advance_partition_attempt(allocation)
            return self.serialize_allocation(allocation)
        if previous_status != allocation.status and allocation.status in TERMINAL_ALLOCATION_STATES:
            self._notify_allocation(
                allocation,
                notification_type=f"hpc.allocation_{allocation.status}",
                title="HPC allocation ended",
                body=f"Your HPC allocation is now {allocation.status}.",
                severity="warning" if allocation.status == "expired" else "info",
            )
        db.session.commit()
        return self.serialize_allocation(allocation)

    def preflight(self, allocation: HpcAllocation, components: Optional[list[str]] = None) -> Dict[str, Any]:
        if not allocation.remote_session_id:
            raise ValidationError("Allocation has no remote HPC-Link session")
        payload = {"components": components or ["fast_renderer", "any_to_usdz"]}
        response = self._reservation_client(allocation).post(
            f"/api/apps/webhdp/sessions/{allocation.remote_session_id}/components/preflight",
            payload,
            timeout=120,
        )
        allocation.last_health_json = json.dumps(response, sort_keys=True, default=str)
        if not response.get("success", True):
            allocation.last_error = response.get("error") or "HPC component preflight failed"
        else:
            allocation.last_error = None
        db.session.commit()
        return response

    def stage_cloud_files(self, allocation: HpcAllocation, files: list[Dict[str, Any]]) -> Dict[str, Any]:
        if not allocation.remote_session_id:
            raise ValidationError("Allocation has no remote HPC-Link session")
        sanitized_files = []
        for item in files or []:
            url = str(item.get("url") or "").strip()
            name = str(item.get("name") or "").strip()
            if not url or not name:
                raise ValidationError("Each staged cloud file requires url and name")
            sanitized_files.append(
                {
                    "url": url,
                    "name": name,
                    "relative_dir": str(item.get("relative_dir") or "").strip().strip("/"),
                }
            )
        response = self._reservation_client(allocation).post(
            f"/api/apps/webhdp/sessions/{allocation.remote_session_id}/stage/cloud",
            {"files": sanitized_files},
            timeout=7200,
        )
        allocation.last_health_json = json.dumps(response, sort_keys=True, default=str)
        db.session.commit()
        return response

    def stage_cloud_references(self, allocation: HpcAllocation, files: list[Dict[str, Any]]) -> Dict[str, Any]:
        if not allocation.remote_session_id:
            raise ValidationError("Allocation has no remote HPC-Link session")
        resolved_files: list[Dict[str, Any]] = []
        for item in files or []:
            cloud_path = str(
                item.get("cloud_path")
                or item.get("cloud_path_or_id")
                or item.get("file_id")
                or item.get("remote_path")
                or ""
            ).strip()
            if not cloud_path:
                raise ValidationError("Each cloud reference requires cloud_path or file_id")

            storage_type = str(item.get("storage_type") or item.get("provider") or "").strip().lower()
            if not storage_type:
                storage_type, _ = CloudUploadService.get_available_storage()
            if storage_type == STORAGE_SERVER:
                raise ValidationError("Server-only storage cannot be staged through cloud-to-HPC URLs")
            if storage_type not in {STORAGE_DROPBOX, STORAGE_GDRIVE}:
                raise ValidationError("Cloud staging requires Dropbox or Google Drive storage")

            download_url = CloudUploadService.get_file_download_url(cloud_path, storage_type)
            if not download_url:
                raise ValidationError(f"Could not create a scoped download URL for {storage_type} file")
            name = str(item.get("name") or os.path.basename(cloud_path.rstrip("/")) or "").strip()
            if not name:
                raise ValidationError("Each cloud reference requires a file name")
            resolved_files.append(
                {
                    "url": download_url,
                    "name": name,
                    "relative_dir": str(item.get("relative_dir") or "").strip().strip("/"),
                }
            )
        return self.stage_cloud_files(allocation, resolved_files)

    def stage_local_files(self, allocation: HpcAllocation, file_paths: list[str]) -> Dict[str, Any]:
        if not allocation.remote_session_id:
            raise ValidationError("Allocation has no remote HPC-Link session")
        if not allocation.remote_input_dir:
            raise ValidationError("Allocation has no remote HPC input directory")

        staged_files: list[Dict[str, Any]] = []
        staging_namespace = "invocation-" + uuid4().hex
        seen: set[str] = set()
        normalized_paths = [os.path.abspath(str(path)) for path in file_paths or [] if str(path).strip()]
        common_root = os.path.commonpath([os.path.dirname(path) for path in normalized_paths]) if normalized_paths else ""

        for raw_path in file_paths or []:
            local_path = os.path.abspath(str(raw_path or "").strip())
            if not local_path or local_path in seen:
                continue
            seen.add(local_path)
            if not os.path.isfile(local_path):
                raise ValidationError(f"Cannot stage missing local file for HPC-Link: {raw_path}")

            remote_name = os.path.basename(local_path)
            relative_dir = os.path.relpath(os.path.dirname(local_path), common_root)
            if relative_dir == ".":
                relative_dir = ""
            relative_dir = "/".join(part for part in [staging_namespace, relative_dir] if part)
            relative_path = "/".join(part for part in [relative_dir, remote_name] if part)
            uploaded = self._reservation_client(allocation).upload_file(
                f"/api/apps/webhdp/sessions/{allocation.remote_session_id}/stage/file?path={quote(relative_path, safe='')}",
                local_path,
            )
            if uploaded.get("size_bytes") != os.path.getsize(local_path) or not uploaded.get("remote_path"):
                raise ValidationError("HPC-Link did not confirm the complete staged file")
            staged_files.append({**uploaded, "local_path": local_path, "relative_dir": relative_dir})

        if staged_files:
            allocation.last_health_json = json.dumps(
                {"stage_local_files": staged_files},
                sort_keys=True,
                default=str,
            )
            db.session.commit()
        return {"session_id": allocation.remote_session_id, "staged_files": staged_files}

    def upload_zenodo_draft(self, allocation: HpcAllocation, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not allocation.remote_session_id:
            raise ValidationError("Allocation has no remote HPC-Link session")
        environment = str(payload.get("environment") or "sandbox").strip().lower()
        if environment not in {"sandbox", "production"}:
            raise ValidationError("Zenodo environment must be sandbox or production")
        if environment == "production" and payload.get("allow_production") is not True:
            raise ValidationError("Zenodo production upload through HPC-Link requires explicit allow_production=true")
        if payload.get("publish") is True:
            raise ValidationError("Publishing through HPC-Link is disabled; upload drafts only")
        access_token = str(payload.get("access_token") or payload.get("token") or "").strip()
        if not access_token:
            raise ValidationError("Zenodo access token is required for HPC draft upload")
        files = payload.get("files") if isinstance(payload.get("files"), list) else []
        if not files:
            raise ValidationError("At least one remote artifact is required for Zenodo draft upload")

        request_payload = {
            "environment": environment,
            "access_token": access_token,
            "deposition_id": payload.get("deposition_id"),
            "metadata": payload.get("metadata") or {},
            "files": files,
            "publish": False,
            "allow_production": payload.get("allow_production") is True,
        }
        response = self._reservation_client(allocation).post(
            f"/api/apps/webhdp/sessions/{allocation.remote_session_id}/zenodo/upload-draft",
            request_payload,
            timeout=float(payload.get("timeout_seconds") or 7200),
        )
        allocation.last_health_json = json.dumps(response, sort_keys=True, default=str)
        db.session.commit()
        return response

    @serialize_registry("hpc-allocation-queue")
    def release(self, allocation: HpcAllocation, *, protect_running: bool = False) -> Dict[str, Any]:
        db.session.refresh(allocation)
        if protect_running and self.allocation_is_in_use(allocation):
            raise OperationConflict("Wait for this session's active run before releasing its HPC allocation.")
        if allocation.reservation_id is not None:
            from services.hpc_reservation_service import HpcReservationService

            response = HpcReservationService(self).detach(allocation)
            allocation.status = "released"
            allocation.released_at = allocation.released_at or _utc_now_naive()
            db.session.commit()
            self.process_queue()
            return {"allocation": self.serialize_allocation(allocation), "remote": response}
        response: Dict[str, Any] = {"cancelled": False}
        if allocation.status in TERMINAL_ALLOCATION_STATES:
            return {"allocation": self.serialize_allocation(allocation), "remote": response}
        if self._awaiting_submission_confirmation(allocation):
            self._recover_submission(allocation)
            if not allocation.remote_session_id:
                raise OperationConflict("HPC-Link has not confirmed the scheduler request. It still counts towards your limit.")
        if allocation.remote_session_id:
            response = self.client().delete(f"/api/apps/webhdp/sessions/{allocation.remote_session_id}", timeout=30) or {}
            if response.get("cancelled") is not True:
                raise OperationConflict("HPC-Link could not confirm release. The allocation still counts towards your limit.")
        allocation.status = "released"
        allocation.released_at = _utc_now_naive()
        self._notify_allocation(
            allocation,
            notification_type="hpc.allocation_released",
            title="HPC allocation released",
            body="Your HPC allocation has been released.",
        )
        db.session.commit()
        self.process_queue()
        return {"allocation": self.serialize_allocation(allocation), "remote": response}

    def execute_component(self, allocation: HpcAllocation, request_payload: Dict[str, Any]) -> Dict[str, Any]:
        if not allocation.remote_session_id:
            raise ValidationError("Allocation has no remote HPC-Link session")
        # HPC-Link resolves executable settings from its installed registry.
        # Send identity and the expected digest, never a client-supplied command.
        profile = request_payload.get("profile") or {}
        payload = {
            **request_payload,
            "component_version": request_payload.get("component_version") or profile.get("version"),
            "profile": {key: profile[key] for key in ("version", "sif_sha256") if profile.get(key)},
        }
        return self._reservation_client(allocation).post(
            f"/api/apps/webhdp/sessions/{allocation.remote_session_id}/components/run",
            payload,
            timeout=float(request_payload.get("timeout_seconds") or 7200) + 60,
        )

    def download_remote_file(self, allocation: HpcAllocation, remote_path: str, local_path: str) -> Dict[str, Any]:
        remote_path = str(remote_path or "").strip()
        local_path = str(local_path or "").strip()
        if not remote_path:
            raise ValidationError("Remote artifact path is required")
        if not local_path:
            raise ValidationError("Local artifact destination is required")
        session_dir = str(allocation.remote_session_dir or "").rstrip("/")
        if session_dir and remote_path != session_dir and not remote_path.startswith(f"{session_dir}/"):
            raise SecurityError("Remote artifact is outside the active HPC allocation directory")
        bytes_written = self._reservation_client(allocation).download_to_file(
            f"/api/apps/webhdp/sessions/{allocation.remote_session_id}/artifacts/download?path={quote(remote_path, safe='')}",
            local_path,
            timeout=900,
        )
        return {
            "remote_path": remote_path,
            "local_path": local_path,
            "size_bytes": os.path.getsize(local_path) if os.path.exists(local_path) else bytes_written,
        }

    def register_remote_artifacts(
        self,
        allocation: HpcAllocation,
        *,
        component_key: str,
        artifacts: list[Dict[str, Any]],
        pipeline_run_id: Optional[int] = None,
        step_run_id: Optional[int] = None,
        playground_run_id: Optional[int] = None,
        record_id: Optional[int] = None,
    ) -> None:
        for artifact in artifacts or []:
            remote_path = str(artifact.get("remote_path") or artifact.get("path") or "").strip()
            if not remote_path:
                continue
            db.session.add(
                HpcArtifact(
                    allocation_id=allocation.id,
                    pipeline_run_id=pipeline_run_id,
                    step_run_id=step_run_id,
                    playground_run_id=playground_run_id,
                    record_id=record_id,
                    component_key=component_key,
                    artifact_kind=str(artifact.get("artifact_kind") or "file"),
                    name=str(artifact.get("name") or os.path.basename(remote_path)),
                    remote_path=remote_path,
                    size_bytes=artifact.get("size_bytes"),
                    metadata_json=json.dumps(artifact.get("metadata") or {}, sort_keys=True),
                )
            )
        db.session.commit()
