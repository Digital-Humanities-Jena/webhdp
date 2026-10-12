"""HPC-Link configuration, queue, and allocation lifecycle service."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote

from database.database import db
from database.models import HpcAllocation, HpcArtifact, HpcLinkConfig, Session as DBSession, User, UserRole
from exceptions import ResourceNotFoundError, SecurityError, ValidationError
from services.credential_crypto import decrypt_secret, encrypt_secret
from services.cloud_upload_service import STORAGE_DROPBOX, STORAGE_GDRIVE, STORAGE_SERVER, CloudUploadService
from services.hpc_link_client import HpcLinkClient
from services.notification_service import notify_user
from services.registry_lock import OperationConflict, registry_lock


TERMINAL_ALLOCATION_STATES = {"failed", "released", "expired", "cancelled"}
ACTIVE_ALLOCATION_STATES = {"allocating", "running"}
QUEUEABLE_ALLOCATION_STATES = {"queued", "allocating", "running"}
PARTITION_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
DEFAULT_PARTITION_PLACEHOLDER = "partition-a"
PARTITION_SEQUENCE_ENV = "HPC_LINK_PARTITION_SEQUENCE"
PARTITION_ATTEMPT_TIMEOUT_ENV = "HPC_LINK_PARTITION_ATTEMPT_TIMEOUT_SECONDS"


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
        if user.role == UserRole.ADMIN:
            return True
        if purpose == "playground" and user.role == UserRole.MODERATOR:
            return True
        return bool(user.is_verified and user.has_capability("hpc_link_access"))

    def require_allocation_access(self, user: User, *, purpose: str = "workflow") -> None:
        if not user.is_verified and user.role != UserRole.ADMIN:
            raise SecurityError("Verified account required for HPC-Link allocations")
        if not self.user_can_allocate(user, purpose=purpose):
            raise SecurityError("HPC-Link access is not enabled for this account")

    def serialize_allocation(self, allocation: HpcAllocation) -> Dict[str, Any]:
        return {
            "allocation_id": allocation.public_id,
            "user_id": allocation.user_id,
            "session_id": allocation.session_id,
            "purpose": allocation.purpose,
            "status": allocation.status,
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
        query = HpcAllocation.query.filter(HpcAllocation.status.in_(list(ACTIVE_ALLOCATION_STATES)))
        if user_id is not None:
            query = query.filter(HpcAllocation.user_id == int(user_id))
        return int(query.count())

    def _can_start_next(self, config: HpcLinkConfig, allocation: HpcAllocation) -> bool:
        if self._active_count() >= int(config.max_active_allocations or 1):
            return False
        if self._active_count(user_id=allocation.user_id) >= int(config.max_active_allocations_per_user or 1):
            return False
        return True

    def request_allocation(self, *, user: User, session_id: Optional[int], purpose: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        config = self.get_or_create_config()
        if not config.enabled:
            raise ValidationError("HPC-Link is not enabled on this WebHDP instance")
        self.require_allocation_access(user, purpose=purpose)

        if session_id is not None:
            session_row = db.session.get(DBSession, int(session_id))
            if session_row is None:
                raise ResourceNotFoundError("Session not found")
            if session_row.user_id != user.id and user.role != UserRole.ADMIN:
                raise SecurityError("Access denied for this workflow session")

        existing = None
        if session_id is not None:
            existing = (
                HpcAllocation.query.filter(
                    HpcAllocation.session_id == int(session_id),
                    HpcAllocation.purpose == purpose,
                    HpcAllocation.status.in_(list(QUEUEABLE_ALLOCATION_STATES)),
                )
                .order_by(HpcAllocation.requested_at.desc())
                .first()
            )
        if existing is not None:
            self.process_queue()
            if existing.status in QUEUEABLE_ALLOCATION_STATES:
                return self.serialize_allocation(existing)

        requested_gpu_count = payload.get("gpu_count")
        if requested_gpu_count in (None, ""):
            requested_gpu_count = config.default_gpu_count if config.default_gpu_count is not None else 1

        partition_sequence = self._partition_sequence_for_request(config, payload)
        allocation = HpcAllocation(
            user_id=user.id,
            session_id=session_id,
            purpose=purpose,
            status="queued",
            requested_partition=partition_sequence[0],
            requested_gpu_type=str(payload.get("gpu_type") or config.default_gpu_type or "").strip() or None,
            requested_gpu_count=int(requested_gpu_count),
            requested_duration_minutes=int(payload.get("duration_minutes") or config.default_duration_minutes or 30),
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
        queued = HpcAllocation.query.filter_by(status="queued").order_by(HpcAllocation.requested_at.asc()).all()
        for allocation in queued:
            if not self._can_start_next(config, allocation):
                continue
            self._start_allocation(allocation, config)

    def _start_allocation(self, allocation: HpcAllocation, config: HpcLinkConfig) -> None:
        allocation.status = "allocating"
        allocation.partition_attempt_started_at = _utc_now_naive()
        allocation.last_error = None
        db.session.commit()
        try:
            payload = {
                "partition": allocation.requested_partition,
                "gpu_type": allocation.requested_gpu_type,
                "gpu_count": allocation.requested_gpu_count,
                "duration_minutes": allocation.requested_duration_minutes,
                "webhdp_session_id": allocation.session_id,
                "purpose": allocation.purpose,
            }
            response = self.client(config).post("/api/apps/webhdp/sessions", payload, timeout=60)
            allocation.remote_session_id = response.get("session_id")
            allocation.remote_job_id = response.get("job_id")
            allocation.remote_session_dir = response.get("remote_session_dir")
            allocation.remote_input_dir = response.get("input_dir")
            allocation.remote_output_dir = response.get("output_dir")
            allocation.scheduler_state = response.get("scheduler_state") or response.get("status")
            remote_status = str(response.get("status") or "").lower()
            allocation.status = "running" if remote_status == "running" else "allocating"
            if allocation.status == "running":
                allocation.allocated_at = _utc_now_naive()
            allocation.expires_at = _parse_datetime(response.get("expires_at"))
            allocation.last_health_json = json.dumps(response, sort_keys=True, default=str)
            if allocation.status == "running":
                self._notify_allocation(
                    allocation,
                    notification_type="hpc.allocation_running",
                    title="HPC allocation is running",
                    body="Your HPC allocation is ready for workflow operations.",
                    severity="success",
                )
        except Exception as exc:
            allocation.status = "failed"
            allocation.last_error = str(exc)
            self._append_attempt_history(allocation, status="failed", message=str(exc))
            self._notify_allocation(
                allocation,
                notification_type="hpc.allocation_failed",
                title="HPC allocation failed",
                body=str(exc),
                severity="error",
            )
        db.session.commit()

    def _cancel_remote_attempt(self, allocation: HpcAllocation) -> tuple[bool, str]:
        if not allocation.remote_session_id:
            return False, "No remote session was created for this attempt"
        try:
            self.client().delete(f"/api/apps/webhdp/sessions/{allocation.remote_session_id}", timeout=30)
            return True, "Remote HPC-Link session cancelled"
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

    def get_active_for_session(self, session_id: int) -> Optional[HpcAllocation]:
        return (
            HpcAllocation.query.filter(
                HpcAllocation.session_id == int(session_id),
                HpcAllocation.status.in_(list(ACTIVE_ALLOCATION_STATES)),
            )
            .order_by(HpcAllocation.allocated_at.desc())
            .first()
        )

    def attach_allocation_to_session(self, public_id: str, user: User, session_id: int) -> Dict[str, Any]:
        allocation = self.get_allocation(public_id, user)
        session_row = db.session.get(DBSession, int(session_id))
        if session_row is None:
            raise ResourceNotFoundError("Session not found")
        if session_row.user_id != user.id and user.role != UserRole.ADMIN:
            raise SecurityError("Access denied for this workflow session")
        if allocation.session_id not in (None, int(session_id)):
            raise ValidationError("HPC allocation is already attached to another workflow session")
        allocation.session_id = int(session_id)
        db.session.commit()
        return self.serialize_allocation(allocation)

    def refresh_allocation(self, allocation: HpcAllocation) -> Dict[str, Any]:
        if not allocation.remote_session_id or allocation.status in TERMINAL_ALLOCATION_STATES:
            return self.serialize_allocation(allocation)
        previous_status = allocation.status
        try:
            response = self.client().get(f"/api/apps/webhdp/sessions/{allocation.remote_session_id}", timeout=20)
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
            elif remote_status in {"queued", "allocating"} and allocation.status not in {"running", "expired"}:
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
        response = self.client().post(
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
        response = self.client().post(
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
            relative_path = "/".join(part for part in [relative_dir, remote_name] if part)
            uploaded = self.client().upload_file(
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
        response = self.client().post(
            f"/api/apps/webhdp/sessions/{allocation.remote_session_id}/zenodo/upload-draft",
            request_payload,
            timeout=float(payload.get("timeout_seconds") or 7200),
        )
        allocation.last_health_json = json.dumps(response, sort_keys=True, default=str)
        db.session.commit()
        return response

    def release(self, allocation: HpcAllocation) -> Dict[str, Any]:
        response: Dict[str, Any] = {"cancelled": False}
        if allocation.remote_session_id and allocation.status not in TERMINAL_ALLOCATION_STATES:
            response = self.client().delete(f"/api/apps/webhdp/sessions/{allocation.remote_session_id}", timeout=30) or {}
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
        return self.client().post(
            f"/api/apps/webhdp/sessions/{allocation.remote_session_id}/components/run",
            payload,
            timeout=float(request_payload.get("timeout_seconds") or 7200),
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
        bytes_written = self.client().download_to_file(
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
