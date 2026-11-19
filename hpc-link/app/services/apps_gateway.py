"""Service layer for app-style HPC integrations (vLLM and Pi3)."""
from __future__ import annotations

import asyncio
import base64
import binascii
import ipaddress
import hashlib
import json
import os
import re
import shlex
import socket
import stat as stat_module
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
import asyncssh

from app.auth_store import AuthenticatedUser
from app.config import get_settings
from app.schemas.apps import (
    ApplicationDescriptor,
    ChatRequest,
    ChatResponse,
    MarkerArtifactDescriptor,
    MarkerArtifactDownloadResponse,
    MarkerArtifactsResponse,
    MarkerConvertRequest,
    MarkerConvertResponse,
    MarkerDocumentUploadRequest,
    MarkerDocumentUploadResponse,
    MarkerSessionCreateRequest,
    MarkerSessionCreateResponse,
    MarkerSessionStatusResponse,
    Pi3SessionCreateRequest,
    Pi3SessionCreateResponse,
    Pi3SessionStatusResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionLogsResponse,
    SessionStatusResponse,
    SessionStopResponse,
    VllmModelDescriptor,
    Pi3ImageUploadRequest,
    Pi3ImageUploadResponse,
    Pi3ProcessRequest,
    Pi3ProcessResponse,
    Pi3ArtifactsResponse,
    Pi3ArtifactDescriptor,
    Pi3ArtifactDownloadResponse,
    WebHdpCloudStageRequest,
    WebHdpCloudStageResponse,
    WebHdpComponentInstallRequest,
    WebHdpComponentInstallValidateRequest,
    WebHdpComponentRunRequest,
    WebHdpComponentTestRequest,
    WebHdpPreflightRequest,
    WebHdpPreflightResponse,
    WebHdpReservationFacts,
    WebHdpReservationInspectRequest,
    WebHdpReservationRegisterRequest,
    WebHdpReservationResponse,
    WebHdpSessionAdoptRequest,
    WebHdpSessionCreateRequest,
    WebHdpSessionCreateResponse,
    WebHdpSessionStatusResponse,
    WebHdpUploadStageRequest,
    WebHdpZenodoDraftUploadRequest,
    WebHdpZenodoDraftUploadResponse,
    WebHdpZenodoUploadedFile,
)
from app.ssh_manager import ssh_manager
from app.security import auth_store, enforce_allocation_policy, require_admin_user


TERMINAL_STATES = {
    "COMPLETED",
    "CANCELLED",
    "FAILED",
    "TIMEOUT",
    "OUT_OF_MEMORY",
    "NODE_FAIL",
}

PI3_ALLOWED_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".webp",
    ".tif",
    ".tiff",
}

PI3_ALLOWED_ARTIFACT_EXTENSIONS = {
    ".ply",
    ".obj",
    ".glb",
    ".gltf",
    ".npz",
}

MARKER_ALLOWED_INPUT_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".html",
    ".htm",
    ".epub",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
}

MARKER_ALLOWED_ARTIFACT_EXTENSIONS = {
    ".md",
    ".markdown",
    ".json",
    ".html",
    ".txt",
    ".csv",
    ".xml",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
}

DEFAULT_STAGE_ALLOWED_HOSTS = {
    "zenodo.org",
    "sandbox.zenodo.org",
    "www.googleapis.com",
    "drive.google.com",
    "docs.google.com",
    "*.googleusercontent.com",
    "dl.dropbox.com",
    "www.dropbox.com",
    "*.dropboxusercontent.com",
}


@dataclass
class _VllmSession:
    """In-memory state for one allocated vLLM session."""
    session_id: str
    model_id: str
    model_label: str
    model_path: str
    partition: str
    gpu_type: str | None
    gpu_count: int
    duration_minutes: int
    time_limit: str
    max_model_len: int
    job_id: str
    remote_session_dir: str
    port: int
    created_at: datetime
    expires_at: datetime
    status: str = "queued"
    owner_username: str = ""
    history: list[dict[str, str]] = field(default_factory=list)


@dataclass
class _Pi3Session:
    """In-memory state for one allocated Pi3 session."""

    session_id: str
    partition: str
    gpu_count: int
    duration_minutes: int
    time_limit: str
    job_id: str
    remote_session_dir: str
    remote_input_dir: str
    remote_output_dir: str
    cuda_module: str | None
    created_at: datetime
    expires_at: datetime
    status: str = "queued"
    owner_username: str = ""


@dataclass
class _MarkerSession:
    """In-memory state for one allocated Marker session."""

    session_id: str
    partition: str
    gpu_count: int
    duration_minutes: int
    time_limit: str
    job_id: str
    remote_session_dir: str
    remote_input_dir: str
    remote_output_dir: str
    cuda_module: str | None
    torch_device: str
    created_at: datetime
    expires_at: datetime
    status: str = "queued"
    owner_username: str = ""


@dataclass
class _WebHdpSession:
    """In-memory state for one reusable WebHDP component allocation."""

    session_id: str
    partition: str
    gpu_type: str | None
    gpu_count: int
    duration_minutes: int
    time_limit: str
    job_id: str
    remote_session_dir: str
    remote_input_dir: str
    remote_output_dir: str
    cuda_module: str | None
    created_at: datetime
    expires_at: datetime
    status: str = "queued"
    owner_username: str = ""
    reservation_id: str | None = None
    claim_id: str | None = None


@dataclass
class _WebHdpReservation:
    reservation_id: str
    owner_username: str
    facts: WebHdpReservationFacts
    submit_time: int
    owner_uid: int
    closed_claims: dict[str, str] = field(default_factory=dict)
    revoked: bool = False


class HpcApplicationGatewayService:
    """Orchestrates application sessions on the HPC."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._sessions: dict[str, _VllmSession] = {}
        self._pi3_sessions: dict[str, _Pi3Session] = {}
        self._marker_sessions: dict[str, _MarkerSession] = {}
        self._webhdp_sessions: dict[str, _WebHdpSession] = {}
        self._webhdp_reservations: dict[str, _WebHdpReservation] = {}
        self._closed_webhdp_requests: dict[str, dict[str, str]] = {}
        self._active_webhdp_steps: set[str] = set()
        self._reserved_ports: set[int] = set()
        self._lock = asyncio.Lock()
        self._models = self._parse_vllm_models(self._settings.vllm_models_json)
        self._load_webhdp_sessions_from_registry()

    @staticmethod
    def _parse_datetime(value: Any) -> datetime:
        text = str(value or "").strip()
        if not text:
            return datetime.now(timezone.utc)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _webhdp_registry_path(self) -> Path:
        return Path(self._settings.webhdp_sessions_registry_path).expanduser()

    def _load_webhdp_sessions_from_registry(self) -> None:
        path = self._webhdp_registry_path()
        if not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        sessions = payload.get("sessions", [])
        reservations = payload.get("reservations", [])
        if not isinstance(sessions, list) or not isinstance(reservations, list):
            return
        loaded: dict[str, _WebHdpSession] = {}
        for item in sessions:
            if not isinstance(item, dict) or not item.get("session_id"):
                continue
            try:
                session = _WebHdpSession(
                    session_id=str(item["session_id"]),
                    partition=str(item.get("partition") or self._settings.webhdp_default_partition),
                    gpu_type=item.get("gpu_type"),
                    gpu_count=int(item.get("gpu_count") or 0),
                    duration_minutes=int(item.get("duration_minutes") or 30),
                    time_limit=str(item.get("time_limit") or self._minutes_to_slurm_time(int(item.get("duration_minutes") or 30))),
                    job_id=str(item.get("job_id") or ""),
                    remote_session_dir=str(item.get("remote_session_dir") or ""),
                    remote_input_dir=str(item.get("remote_input_dir") or ""),
                    remote_output_dir=str(item.get("remote_output_dir") or ""),
                    cuda_module=item.get("cuda_module"),
                    created_at=self._parse_datetime(item.get("created_at")),
                    expires_at=self._parse_datetime(item.get("expires_at")),
                    status=str(item.get("status") or "queued"),
                    owner_username=str(item.get("owner_username") or ""),
                    reservation_id=item.get("reservation_id"),
                    claim_id=item.get("claim_id"),
                )
            except (TypeError, ValueError):
                continue
            loaded[session.session_id] = session
        self._webhdp_sessions.update(loaded)
        closed_requests = payload.get("closed_requests", {})
        if isinstance(closed_requests, dict):
            self._closed_webhdp_requests.update({
                request_id: receipt for request_id, receipt in closed_requests.items()
                if isinstance(receipt, dict) and {"owner_username", "job_id"} <= receipt.keys()
            })
        for item in reservations:
            try:
                reservation = _WebHdpReservation(
                    reservation_id=str(uuid.UUID(item["reservation_id"])),
                    owner_username=item["owner_username"],
                    facts=WebHdpReservationFacts.model_validate(item["facts"]),
                    submit_time=int(item["submit_time"]),
                    owner_uid=int(item["owner_uid"]),
                    closed_claims={str(uuid.UUID(claim)): str(uuid.UUID(session)) if session else ""
                                   for claim, session in item.get("closed_claims", {}).items()},
                    revoked=item.get("revoked") is True,
                )
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            self._webhdp_reservations[reservation.reservation_id] = reservation

    def _save_webhdp_sessions_to_registry(self, *, required: bool = False) -> None:
        path = self._webhdp_registry_path()
        temporary_path = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            sessions = []
            for session in self._webhdp_sessions.values():
                sessions.append(
                    {
                        "session_id": session.session_id,
                        "partition": session.partition,
                        "gpu_type": session.gpu_type,
                        "gpu_count": session.gpu_count,
                        "duration_minutes": session.duration_minutes,
                        "time_limit": session.time_limit,
                        "job_id": session.job_id,
                        "remote_session_dir": session.remote_session_dir,
                        "remote_input_dir": session.remote_input_dir,
                        "remote_output_dir": session.remote_output_dir,
                        "cuda_module": session.cuda_module,
                        "created_at": session.created_at.isoformat(),
                        "expires_at": session.expires_at.isoformat(),
                        "status": session.status,
                        "owner_username": session.owner_username,
                        "reservation_id": session.reservation_id,
                        "claim_id": session.claim_id,
                    }
                )
            reservations = [
                {
                    "reservation_id": reservation.reservation_id,
                    "owner_username": reservation.owner_username,
                    "facts": reservation.facts.model_dump(mode="json"),
                    "submit_time": reservation.submit_time,
                    "owner_uid": reservation.owner_uid,
                    "closed_claims": reservation.closed_claims,
                    "revoked": reservation.revoked,
                }
                for reservation in self._webhdp_reservations.values()
            ]
            with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".webhdp-sessions-",
                                             encoding="utf-8", delete=False) as stream:
                temporary_path = Path(stream.name)
                json.dump({"sessions": sessions, "reservations": reservations,
                           "closed_requests": self._closed_webhdp_requests}, stream, indent=2, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            temporary_path.replace(path)
        except OSError as exc:
            if required:
                raise HTTPException(status_code=503, detail="WebHDP session registry is not writable") from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _parse_vllm_models(raw_json: str) -> dict[str, VllmModelDescriptor]:
        fallback = {
            "qwen2.5-0.5b": VllmModelDescriptor(
                model_id="qwen2.5-0.5b",
                label="Qwen2.5 0.5B Instruct",
                path="/srv/hpc-link/apps/models/Qwen2.5-0.5B-Instruct",
                max_model_len=4096,
            ),
            "tinyllama-1.1b": VllmModelDescriptor(
                model_id="tinyllama-1.1b",
                label="TinyLlama 1.1B Chat",
                path="/srv/hpc-link/apps/models/TinyLlama-1.1B-Chat-v1.0",
                max_model_len=2048,
            ),
        }

        try:
            parsed = json.loads(raw_json)
            models: dict[str, VllmModelDescriptor] = {}
            for item in parsed:
                descriptor = VllmModelDescriptor(
                    model_id=item["id"],
                    label=item["label"],
                    path=item["path"],
                    max_model_len=item.get("max_model_len"),
                )
                models[descriptor.model_id] = descriptor
            return models or fallback
        except Exception:
            return fallback

    @staticmethod
    def _minutes_to_slurm_time(total_minutes: int) -> str:
        hours, minutes = divmod(total_minutes, 60)
        return f"{hours:02d}:{minutes:02d}:00"

    @staticmethod
    def _extract_job_id(sbatch_output: str) -> str | None:
        text = sbatch_output.strip()
        if not text:
            return None
        # sbatch --parsable usually returns "<jobid>[;cluster]"
        job = text.split(";")[0]
        if job.isdigit():
            return job
        match = re.search(r"\b(\d+)\b", text)
        if match:
            return match.group(1)
        return None

    def _next_available_port(self) -> int:
        used_ports = {session.port for session in self._sessions.values()} | self._reserved_ports
        for candidate in range(self._settings.vllm_base_port, self._settings.vllm_base_port + 500):
            if candidate not in used_ports:
                return candidate
        raise HTTPException(status_code=500, detail="No free vLLM session ports available")

    @staticmethod
    def _ensure_owner_access(owner_username: str, actor: AuthenticatedUser) -> None:
        if actor.is_admin:
            return
        if owner_username != actor.username:
            raise HTTPException(status_code=403, detail="Access denied for this session")

    async def list_applications(self) -> list[ApplicationDescriptor]:
        return [
            ApplicationDescriptor(
                app_id="vllm",
                name="vLLM Chat Runtime",
                description="Allocate a time-bounded GPU session and chat through an OpenAI-compatible endpoint.",
            ),
            ApplicationDescriptor(
                app_id="pi3",
                name="Pi3 Image-to-3D Runtime",
                description="Allocate a GPU session, upload images, run Pi3 reconstruction, and download 3D artifacts.",
            ),
            ApplicationDescriptor(
                app_id="marker",
                name="Marker Document Conversion Runtime",
                description="Allocate a conversion session, upload documents, convert with Marker, and download artifacts.",
            ),
            ApplicationDescriptor(
                app_id="webhdp",
                name="WebHDP Component Runtime",
                description="Allocate reusable GPU resources for WebHDP HDP Components such as rendering and USDZ conversion.",
            ),
        ]

    async def list_vllm_models(self) -> list[VllmModelDescriptor]:
        models = list(self._models.values())
        checks: list[str] = []
        for model in models:
            checks.append(
                f"if [ -e {shlex.quote(model.path)} ]; then echo {shlex.quote(model.model_id + '|1')}; "
                f"else echo {shlex.quote(model.model_id + '|0')}; fi"
            )

        command = "; ".join(checks)
        installed_map: dict[str, bool] = {}
        stdout, _, exit_code = await ssh_manager.run_command(command, timeout=30)
        if exit_code == 0:
            for line in stdout.strip().splitlines():
                parts = line.split("|")
                if len(parts) == 2:
                    installed_map[parts[0]] = parts[1] == "1"

        result: list[VllmModelDescriptor] = []
        for model in models:
            result.append(
                VllmModelDescriptor(
                    model_id=model.model_id,
                    label=model.label,
                    path=model.path,
                    max_model_len=model.max_model_len,
                    installed=installed_map.get(model.model_id),
                )
            )
        return result

    def _render_vllm_batch_script(self, session: _VllmSession) -> str:
        gres = f"gpu:{session.gpu_count}"
        if session.gpu_type:
            gres = f"gpu:{session.gpu_type}:{session.gpu_count}"

        return f"""#!/bin/bash
#SBATCH --job-name=hpc-link-vllm-{session.session_id[:8]}
#SBATCH --partition={session.partition}
#SBATCH --gres={gres}
#SBATCH --time={session.time_limit}
#SBATCH --output={session.remote_session_dir}/slurm-%j.out
#SBATCH --error={session.remote_session_dir}/slurm-%j.err

set -euo pipefail

echo "$(hostname)" > {session.remote_session_dir}/node.txt
echo "$(date -Iseconds)" > {session.remote_session_dir}/started_at.txt
echo "{session.model_id}" > {session.remote_session_dir}/model_id.txt
echo "{session.port}" > {session.remote_session_dir}/port.txt

{self._settings.vllm_binary} serve {shlex.quote(session.model_path)} \\
  --host 127.0.0.1 \\
  --port {session.port} \\
  --served-model-name {shlex.quote(session.model_id)} \\
  --max-model-len {session.max_model_len}
"""

    async def create_vllm_session(
        self,
        request: SessionCreateRequest,
        actor: AuthenticatedUser,
    ) -> SessionCreateResponse:
        model = self._models.get(request.model_id)
        if model is None:
            raise HTTPException(status_code=404, detail=f"Unknown model_id '{request.model_id}'")

        partition = request.partition or self._settings.default_partition
        gpu_type = request.gpu_type or self._settings.default_gpu_type
        enforce_allocation_policy(
            actor,
            partition=partition,
            gpu_type=gpu_type,
            gpu_count=request.gpu_count,
            duration_minutes=request.duration_minutes,
        )

        async with self._lock:
            session_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
            port = self._next_available_port()
            self._reserved_ports.add(port)
            now = datetime.now(timezone.utc)
            remote_dir = f"{self._settings.hpc_apps_root}/vllm/sessions/{session_id}"

            session = _VllmSession(
                session_id=session_id,
                model_id=model.model_id,
                model_label=model.label,
                model_path=model.path,
                partition=partition,
                gpu_type=gpu_type,
                gpu_count=request.gpu_count,
                duration_minutes=request.duration_minutes,
                time_limit=self._minutes_to_slurm_time(request.duration_minutes),
                max_model_len=model.max_model_len or 4096,
                job_id="",
                remote_session_dir=remote_dir,
                port=port,
                created_at=now,
                expires_at=now + timedelta(minutes=request.duration_minutes),
                owner_username=actor.username,
            )

        try:
            mkdir_cmd = f"mkdir -p {shlex.quote(session.remote_session_dir)}"
            _, stderr, exit_code = await ssh_manager.run_command(mkdir_cmd)
            if exit_code != 0:
                raise HTTPException(status_code=500, detail=f"Could not create session directory: {stderr}")

            script_content = self._render_vllm_batch_script(session)
            script_path = f"{session.remote_session_dir}/launch_vllm.sbatch"
            async with await ssh_manager.open_sftp() as sftp:
                async with sftp.open(script_path, "w") as handle:
                    await handle.write(script_content)
        except Exception as exc:
            async with self._lock:
                self._reserved_ports.discard(port)
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(status_code=500, detail=f"Failed to upload launch script: {exc}") from exc

        try:
            stdout, stderr, exit_code = await ssh_manager.run_command(
                f"sbatch --parsable {shlex.quote(script_path)}"
            )
            if exit_code != 0:
                raise HTTPException(status_code=500, detail=f"sbatch failed: {stderr or stdout}")

            job_id = self._extract_job_id(stdout)
            if not job_id:
                raise HTTPException(status_code=500, detail=f"Could not parse job ID from: {stdout}")

            session.job_id = job_id
            session.status = "queued"
            async with self._lock:
                self._reserved_ports.discard(port)
                self._sessions[session.session_id] = session
        except Exception:
            async with self._lock:
                self._reserved_ports.discard(port)
            raise

        return SessionCreateResponse(
            session_id=session.session_id,
            app_id="vllm",
            model_id=session.model_id,
            model_label=session.model_label,
            job_id=session.job_id,
            remote_session_dir=session.remote_session_dir,
            status=session.status,
            created_at=session.created_at,
            expires_at=session.expires_at,
        )

    async def _scheduler_state_for_job(self, job_id: str) -> tuple[str, str | None]:
        cmd = f"squeue -j {shlex.quote(job_id)} -h -o '%T|%R'"
        stdout, _, exit_code = await ssh_manager.run_command(cmd)
        if exit_code != 0:
            return "UNKNOWN", None
        line = stdout.strip()
        if not line:
            return "COMPLETED_OR_UNKNOWN", None
        parts = line.split("|", maxsplit=1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return parts[0], None

    @staticmethod
    def _remaining_seconds(expires_at: datetime) -> int:
        delta = expires_at - datetime.now(timezone.utc)
        return max(0, int(delta.total_seconds()))

    async def get_vllm_session_status(
        self,
        session_id: str,
        actor: AuthenticatedUser,
    ) -> SessionStatusResponse:
        async with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        self._ensure_owner_access(session.owner_username, actor)

        scheduler_state, scheduler_reason = await self._scheduler_state_for_job(session.job_id)
        remaining_seconds = self._remaining_seconds(session.expires_at)

        if scheduler_state == "RUNNING":
            session.status = "running"
        elif scheduler_state in ("PENDING", "CONFIGURING", "COMPLETING"):
            session.status = "queued"
        elif scheduler_state in TERMINAL_STATES or remaining_seconds == 0:
            session.status = "finished"
        else:
            session.status = "unknown"

        return SessionStatusResponse(
            session_id=session.session_id,
            app_id="vllm",
            model_id=session.model_id,
            model_label=session.model_label,
            job_id=session.job_id,
            status=session.status,
            scheduler_state=scheduler_state,
            scheduler_reason=scheduler_reason,
            created_at=session.created_at,
            expires_at=session.expires_at,
            remaining_seconds=remaining_seconds,
        )

    async def _tail_remote_file(self, path: str, tail_lines: int) -> tuple[bool, str]:
        exists_cmd = f"test -f {shlex.quote(path)}"
        _, _, exists_exit = await ssh_manager.run_command(exists_cmd, timeout=20)
        if exists_exit != 0:
            return False, ""

        stdout, stderr, exit_code = await ssh_manager.run_command(
            f"tail -n {tail_lines} {shlex.quote(path)}",
            timeout=30,
        )
        if exit_code != 0:
            missing_markers = ("No such file", "cannot open")
            if any(marker in stderr for marker in missing_markers):
                return False, ""
            raise HTTPException(status_code=502, detail=f"Could not read log file {path}: {stderr or stdout}")
        return True, stdout

    async def get_vllm_session_logs(
        self,
        session_id: str,
        actor: AuthenticatedUser,
        tail_lines: int = 200,
    ) -> SessionLogsResponse:
        async with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        self._ensure_owner_access(session.owner_username, actor)

        stdout_path = f"{session.remote_session_dir}/slurm-{session.job_id}.out"
        stderr_path = f"{session.remote_session_dir}/slurm-{session.job_id}.err"

        stdout_exists, stdout_tail = await self._tail_remote_file(stdout_path, tail_lines)
        stderr_exists, stderr_tail = await self._tail_remote_file(stderr_path, tail_lines)

        return SessionLogsResponse(
            session_id=session.session_id,
            job_id=session.job_id,
            tail_lines=tail_lines,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            stdout_exists=stdout_exists,
            stderr_exists=stderr_exists,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
        )

    async def chat_vllm_session(
        self,
        session_id: str,
        request: ChatRequest,
        actor: AuthenticatedUser,
    ) -> ChatResponse:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="Session not found")
            self._ensure_owner_access(session.owner_username, actor)
            history = list(session.history[-12:])
            model_id = session.model_id
            job_id = session.job_id
            port = session.port

        status = await self.get_vllm_session_status(session_id, actor)
        if status.scheduler_state != "RUNNING":
            raise HTTPException(
                status_code=409,
                detail=f"Session is not ready yet (state={status.scheduler_state})",
            )

        prompt_messages = history + [{"role": "user", "content": request.message}]
        payload = {
            "model": model_id,
            "messages": prompt_messages,
            "temperature": request.temperature,
            "max_tokens": min(request.max_tokens, self._settings.vllm_max_tokens),
        }
        payload_b64 = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")

        python_code = (
            "import base64,sys,urllib.request;"
            f"data=base64.b64decode('{payload_b64}');"
            f"req=urllib.request.Request('http://127.0.0.1:{port}/v1/chat/completions',"
            "data=data,headers={'Content-Type':'application/json'});"
            "resp=urllib.request.urlopen(req,timeout=180);"
            "sys.stdout.write(resp.read().decode('utf-8'))"
        )
        command = (
            f"srun --jobid={shlex.quote(job_id)} --overlap --ntasks=1 --nodes=1 "
            f"python3 -c {shlex.quote(python_code)}"
        )
        response_data: dict | None = None
        last_error = ""
        for _ in range(30):
            stdout, stderr, exit_code = await ssh_manager.run_command(command, timeout=120)
            if exit_code == 0:
                try:
                    response_data = json.loads(stdout)
                    break
                except Exception as exc:
                    last_error = f"Unexpected response from vLLM backend: {exc}"
            else:
                last_error = stderr or stdout

            transient_markers = (
                "Connection refused",
                "URLError",
                "timed out",
                "Failed to establish",
            )
            if any(marker in last_error for marker in transient_markers):
                await asyncio.sleep(2)
                continue
            break

        if response_data is None:
            raise HTTPException(
                status_code=502,
                detail=f"Could not query vLLM session: {last_error}",
            )

        try:
            reply = response_data["choices"][0]["message"]["content"]
            usage = response_data.get("usage", {})
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Unexpected response schema from vLLM backend: {exc}",
            ) from exc

        async with self._lock:
            stored = self._sessions.get(session_id)
            if stored is not None:
                stored.history.extend(
                    [
                        {"role": "user", "content": request.message},
                        {"role": "assistant", "content": reply},
                    ]
                )
                if len(stored.history) > 24:
                    stored.history = stored.history[-24:]

        return ChatResponse(
            session_id=session_id,
            model_id=model_id,
            reply=reply,
            usage_prompt_tokens=usage.get("prompt_tokens"),
            usage_completion_tokens=usage.get("completion_tokens"),
        )

    async def stop_vllm_session(self, session_id: str, actor: AuthenticatedUser) -> SessionStopResponse:
        async with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        self._ensure_owner_access(session.owner_username, actor)

        async with self._lock:
            self._sessions.pop(session_id, None)

        _, stderr, exit_code = await ssh_manager.run_command(f"scancel {shlex.quote(session.job_id)}")
        cancelled = exit_code == 0
        message = "Session cancelled" if cancelled else f"scancel failed: {stderr}"
        return SessionStopResponse(
            session_id=session.session_id,
            job_id=session.job_id,
            cancelled=cancelled,
            message=message,
        )

    @staticmethod
    def _sanitize_filename(filename: str, field_name: str) -> str:
        cleaned = filename.strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail=f"{field_name} cannot be empty")
        if cleaned != PurePosixPath(cleaned).name:
            raise HTTPException(status_code=400, detail=f"{field_name} must not contain path separators")
        if cleaned in (".", ".."):
            raise HTTPException(status_code=400, detail=f"{field_name} is invalid")
        return cleaned

    @staticmethod
    def _validate_extension(filename: str, allowed_extensions: set[str], detail: str) -> None:
        suffix = PurePosixPath(filename).suffix.lower()
        if suffix not in allowed_extensions:
            raise HTTPException(status_code=400, detail=detail)

    @staticmethod
    def _tail_text(text: str, max_chars: int = 2000) -> str:
        if len(text) <= max_chars:
            return text
        return text[-max_chars:]

    @staticmethod
    def _allowed_stage_hosts() -> set[str]:
        configured = str(os.environ.get("HPC_LINK_ALLOWED_STAGE_HOSTS") or "").strip()
        if not configured:
            return set(DEFAULT_STAGE_ALLOWED_HOSTS)
        return {item.strip().lower() for item in configured.split(",") if item.strip()}

    @staticmethod
    def _host_matches_allowlist(host: str, allowed_hosts: set[str]) -> bool:
        normalized = host.strip().lower().rstrip(".")
        for allowed in allowed_hosts:
            item = allowed.strip().lower().rstrip(".")
            if not item:
                continue
            if item == normalized:
                return True
            if item.startswith("*.") and normalized.endswith(item[1:]) and normalized != item[2:]:
                return True
        return False

    @staticmethod
    def _reject_private_resolved_addresses(host: str, port: int) -> list[str]:
        try:
            address_info = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise HTTPException(status_code=400, detail=f"Could not resolve staging URL host '{host}'") from exc

        addresses = []
        for item in address_info:
            ip_text = item[4][0]
            try:
                ip = ipaddress.ip_address(ip_text)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Staging URL host resolved to an invalid address: {ip_text}")
            if not ip.is_global or ip.is_multicast or ip.is_reserved or '%' in ip_text:
                raise HTTPException(status_code=400, detail="Staging URL resolves to a non-public network address")
            addresses.append(f'[{ip}]' if ip.version == 6 else str(ip))
        if not addresses:
            raise HTTPException(status_code=400, detail="Staging URL has no public network address")
        return list(dict.fromkeys(addresses))

    def _validate_stage_url(self, url: str) -> str:
        return self._validated_stage_target(url)[0]

    def _validated_stage_target(self, url: str) -> tuple[str, str, list[str]]:
        value = str(url or '').strip()
        try:
            parsed = urlparse(value)
            port = parsed.port
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid cloud staging URL") from exc
        if (parsed.scheme != 'https' or not parsed.hostname or port not in (None, 443)
                or parsed.username is not None or parsed.password is not None or parsed.fragment
                or any(ord(c) <= 32 or ord(c) == 127 for c in value) or '\\' in value):
            raise HTTPException(status_code=400, detail="Cloud staging URLs must use HTTPS on port 443 with no user information or fragment")
        host = parsed.hostname.lower()
        if not re.fullmatch(r'[a-z0-9.-]+', host):
            raise HTTPException(status_code=400, detail="Invalid cloud staging hostname")
        if not self._host_matches_allowlist(host, self._allowed_stage_hosts()):
            raise HTTPException(status_code=400, detail=f"Cloud staging URL host is not allowed: {host}")
        return value, host, self._reject_private_resolved_addresses(host, 443)

    @staticmethod
    def _max_bytes_arg(value: int) -> int:
        return max(1, int(value))

    def _validate_sif_download_url(self, url: str) -> str:
        value = str(url or '').strip()
        try:
            parsed = urlparse(value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid SIF source") from exc
        if parsed.params or ";" in parsed.path or "#" in value:
            raise HTTPException(status_code=400, detail="Use a public HTTPS SIF URL without credentials or an absolute HPC path")
        if parsed.query and not (parsed.hostname in {"zenodo.org", "sandbox.zenodo.org"} and parsed.query == "download=1"):
            raise HTTPException(status_code=400, detail="SIF URLs cannot contain query parameters. Stage private SIFs on HPC and use the absolute path")
        if not parsed.path.lower().endswith(".sif"):
            raise HTTPException(status_code=400, detail="Only HTTPS .sif URLs are supported")
        return self._validate_stage_url(value)

    def _render_pi3_hold_batch_script(self, session: _Pi3Session) -> str:
        cuda_module_block = ""
        if session.cuda_module:
            module_name = shlex.quote(session.cuda_module)
            cuda_module_block = (
                "if command -v module >/dev/null 2>&1; then\n"
                f"  module load {module_name}\n"
                "fi\n"
            )

        return f"""#!/bin/bash
#SBATCH --job-name=hpc-link-pi3-{session.session_id[:8]}
#SBATCH --partition={session.partition}
#SBATCH --gres=gpu:{session.gpu_count}
#SBATCH --time={session.time_limit}
#SBATCH --output={session.remote_session_dir}/slurm-%j.out
#SBATCH --error={session.remote_session_dir}/slurm-%j.err

set -euo pipefail
{cuda_module_block}
mkdir -p {shlex.quote(session.remote_input_dir)} {shlex.quote(session.remote_output_dir)}
echo "$(hostname)" > {shlex.quote(session.remote_session_dir)}/node.txt
echo "$(date -Iseconds)" > {shlex.quote(session.remote_session_dir)}/started_at.txt
echo "{session.partition}" > {shlex.quote(session.remote_session_dir)}/partition.txt
echo "{session.gpu_count}" > {shlex.quote(session.remote_session_dir)}/gpu_count.txt
echo "Pi3 session ready. Waiting for processing commands..."
while true; do sleep 120; done
"""

    async def create_pi3_session(
        self,
        request: Pi3SessionCreateRequest,
        actor: AuthenticatedUser,
    ) -> Pi3SessionCreateResponse:
        partition = request.partition or self._settings.pi3_default_partition
        enforce_allocation_policy(
            actor,
            partition=partition,
            gpu_type=None,
            gpu_count=request.gpu_count,
            duration_minutes=request.duration_minutes,
        )

        async with self._lock:
            session_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
            now = datetime.now(timezone.utc)
            remote_dir = f"{self._settings.hpc_apps_root}/pi3/sessions/{session_id}"
            input_dir = f"{remote_dir}/input_images"
            output_dir = f"{remote_dir}/outputs"

            session = _Pi3Session(
                session_id=session_id,
                partition=partition,
                gpu_count=request.gpu_count,
                duration_minutes=request.duration_minutes,
                time_limit=self._minutes_to_slurm_time(request.duration_minutes),
                job_id="",
                remote_session_dir=remote_dir,
                remote_input_dir=input_dir,
                remote_output_dir=output_dir,
                cuda_module=request.cuda_module or self._settings.pi3_cuda_module,
                created_at=now,
                expires_at=now + timedelta(minutes=request.duration_minutes),
                owner_username=actor.username,
            )

        mkdir_cmd = (
            f"mkdir -p {shlex.quote(session.remote_session_dir)} "
            f"{shlex.quote(session.remote_input_dir)} {shlex.quote(session.remote_output_dir)}"
        )
        _, stderr, exit_code = await ssh_manager.run_command(mkdir_cmd)
        if exit_code != 0:
            raise HTTPException(status_code=500, detail=f"Could not create Pi3 session directories: {stderr}")

        script_content = self._render_pi3_hold_batch_script(session)
        script_path = f"{session.remote_session_dir}/hold_pi3.sbatch"
        try:
            async with await ssh_manager.open_sftp() as sftp:
                async with sftp.open(script_path, "w") as handle:
                    await handle.write(script_content)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to upload Pi3 launch script: {exc}") from exc

        stdout, stderr, exit_code = await ssh_manager.run_command(f"sbatch --parsable {shlex.quote(script_path)}")
        if exit_code != 0:
            raise HTTPException(status_code=500, detail=f"sbatch failed for Pi3: {stderr or stdout}")

        job_id = self._extract_job_id(stdout)
        if not job_id:
            raise HTTPException(status_code=500, detail=f"Could not parse job ID from: {stdout}")

        session.job_id = job_id
        session.status = "queued"
        async with self._lock:
            self._pi3_sessions[session.session_id] = session

        return Pi3SessionCreateResponse(
            session_id=session.session_id,
            app_id="pi3",
            job_id=session.job_id,
            partition=session.partition,
            gpu_count=session.gpu_count,
            remote_session_dir=session.remote_session_dir,
            input_dir=session.remote_input_dir,
            output_dir=session.remote_output_dir,
            status=session.status,
            created_at=session.created_at,
            expires_at=session.expires_at,
        )

    async def get_pi3_session_status(
        self,
        session_id: str,
        actor: AuthenticatedUser,
    ) -> Pi3SessionStatusResponse:
        async with self._lock:
            session = self._pi3_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Pi3 session not found")
        self._ensure_owner_access(session.owner_username, actor)

        scheduler_state, scheduler_reason = await self._scheduler_state_for_job(session.job_id)
        remaining_seconds = self._remaining_seconds(session.expires_at)

        if scheduler_state == "RUNNING":
            session.status = "running"
        elif scheduler_state in ("PENDING", "CONFIGURING", "COMPLETING"):
            session.status = "queued"
        elif scheduler_state in TERMINAL_STATES or remaining_seconds == 0:
            session.status = "finished"
        else:
            session.status = "unknown"

        return Pi3SessionStatusResponse(
            session_id=session.session_id,
            app_id="pi3",
            job_id=session.job_id,
            partition=session.partition,
            gpu_count=session.gpu_count,
            status=session.status,
            scheduler_state=scheduler_state,
            scheduler_reason=scheduler_reason,
            created_at=session.created_at,
            expires_at=session.expires_at,
            remaining_seconds=remaining_seconds,
        )

    async def get_pi3_session_logs(
        self,
        session_id: str,
        actor: AuthenticatedUser,
        tail_lines: int = 200,
    ) -> SessionLogsResponse:
        async with self._lock:
            session = self._pi3_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Pi3 session not found")
        self._ensure_owner_access(session.owner_username, actor)

        stdout_path = f"{session.remote_session_dir}/slurm-{session.job_id}.out"
        stderr_path = f"{session.remote_session_dir}/slurm-{session.job_id}.err"

        stdout_exists, stdout_tail = await self._tail_remote_file(stdout_path, tail_lines)
        stderr_exists, stderr_tail = await self._tail_remote_file(stderr_path, tail_lines)

        return SessionLogsResponse(
            session_id=session.session_id,
            job_id=session.job_id,
            tail_lines=tail_lines,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            stdout_exists=stdout_exists,
            stderr_exists=stderr_exists,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
        )

    async def upload_pi3_image(
        self,
        session_id: str,
        request: Pi3ImageUploadRequest,
        actor: AuthenticatedUser,
    ) -> Pi3ImageUploadResponse:
        async with self._lock:
            session = self._pi3_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Pi3 session not found")
        self._ensure_owner_access(session.owner_username, actor)

        filename = self._sanitize_filename(request.filename, "filename")
        self._validate_extension(
            filename,
            PI3_ALLOWED_IMAGE_EXTENSIONS,
            "Unsupported file extension. Allowed: .jpg, .jpeg, .png, .bmp, .webp, .tif, .tiff",
        )
        try:
            content = base64.b64decode(request.content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=400, detail="content_base64 is not valid base64") from exc

        size_bytes = len(content)
        if size_bytes == 0:
            raise HTTPException(status_code=400, detail="Uploaded image is empty")
        if size_bytes > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Image is too large (max 20 MB)")

        remote_path = f"{session.remote_input_dir}/{filename}"
        try:
            async with await ssh_manager.open_sftp() as sftp:
                async with sftp.open(remote_path, "wb") as handle:
                    await handle.write(content)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not upload image to HPC: {exc}") from exc

        return Pi3ImageUploadResponse(
            session_id=session_id,
            filename=filename,
            remote_path=remote_path,
            size_bytes=size_bytes,
        )

    async def process_pi3_session(
        self,
        session_id: str,
        request: Pi3ProcessRequest,
        actor: AuthenticatedUser,
    ) -> Pi3ProcessResponse:
        async with self._lock:
            session = self._pi3_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Pi3 session not found")
        self._ensure_owner_access(session.owner_username, actor)

        status = await self.get_pi3_session_status(session_id, actor)
        if status.scheduler_state != "RUNNING":
            raise HTTPException(
                status_code=409,
                detail=f"Pi3 session is not ready yet (state={status.scheduler_state})",
            )

        output_name = self._sanitize_filename(request.output_name, "output_name")
        self._validate_extension(
            output_name,
            PI3_ALLOWED_ARTIFACT_EXTENSIONS,
            "Unsupported output extension. Allowed: .ply, .obj, .glb, .gltf, .npz",
        )

        count_cmd = (
            "bash -lc "
            + shlex.quote(
                f"find {shlex.quote(session.remote_input_dir)} -maxdepth 1 -type f "
                "\\( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.bmp' "
                "-o -iname '*.webp' -o -iname '*.tif' -o -iname '*.tiff' \\) | wc -l"
            )
        )
        stdout, stderr, exit_code = await ssh_manager.run_command(count_cmd, timeout=30)
        if exit_code != 0:
            raise HTTPException(status_code=500, detail=f"Could not inspect Pi3 input directory: {stderr or stdout}")

        try:
            image_count = int(stdout.strip() or "0")
        except ValueError:
            image_count = 0
        if image_count < 1:
            raise HTTPException(status_code=400, detail="No uploaded images found in this Pi3 session")

        output_path = f"{session.remote_output_dir}/{output_name}"
        python_cmd = (
            f"{shlex.quote(self._settings.pi3_python)} example.py "
            f"--data_path {shlex.quote(session.remote_input_dir)} "
            f"--save_path {shlex.quote(output_path)} "
            f"--interval {request.interval} "
            "--device cuda"
        )
        if request.ckpt_path:
            python_cmd += f" --ckpt {shlex.quote(request.ckpt_path)}"

        shell_parts = ["set -euo pipefail"]
        if session.cuda_module:
            shell_parts.append(
                f"if command -v module >/dev/null 2>&1; then module load {shlex.quote(session.cuda_module)}; fi"
            )
        shell_parts.append(f"cd {shlex.quote(self._settings.pi3_repo_path)}")
        shell_parts.append(python_cmd)
        inner_cmd = "; ".join(shell_parts)
        command = (
            f"srun --jobid={shlex.quote(session.job_id)} --overlap --ntasks=1 --nodes=1 "
            f"bash -lc {shlex.quote(inner_cmd)}"
        )

        stdout, stderr, exit_code = await ssh_manager.run_command(command, timeout=7200)
        if exit_code != 0:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Pi3 processing command failed: "
                    f"{self._tail_text(stderr or stdout, max_chars=1200)}"
                ),
            )

        stat_cmd = f"stat -c%s {shlex.quote(output_path)}"
        size_stdout, size_stderr, stat_exit = await ssh_manager.run_command(stat_cmd, timeout=30)
        if stat_exit != 0:
            raise HTTPException(status_code=500, detail=f"Pi3 output file missing: {size_stderr or size_stdout}")

        try:
            size_bytes = int(size_stdout.strip())
        except ValueError as exc:
            raise HTTPException(status_code=500, detail="Could not parse Pi3 output file size") from exc

        return Pi3ProcessResponse(
            session_id=session.session_id,
            job_id=session.job_id,
            output_name=output_name,
            artifact_path=output_path,
            size_bytes=size_bytes,
            command_stdout_tail=self._tail_text(stdout),
            command_stderr_tail=self._tail_text(stderr),
        )

    async def list_pi3_artifacts(self, session_id: str, actor: AuthenticatedUser) -> Pi3ArtifactsResponse:
        async with self._lock:
            session = self._pi3_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Pi3 session not found")
        self._ensure_owner_access(session.owner_username, actor)

        cmd = (
            "bash -lc "
            + shlex.quote(
                f"if [ ! -d {shlex.quote(session.remote_output_dir)} ]; then exit 0; fi; "
                f"for f in {shlex.quote(session.remote_output_dir)}/*; do "
                "[ -f \"$f\" ] || continue; "
                "name=$(basename \"$f\"); "
                "size=$(stat -c%s \"$f\" 2>/dev/null || stat -f%z \"$f\"); "
                "mtime=$(stat -c%Y \"$f\" 2>/dev/null || stat -f%m \"$f\"); "
                "printf '%s|%s|%s\\n' \"$name\" \"$size\" \"$mtime\"; "
                "done"
            )
        )
        stdout, stderr, exit_code = await ssh_manager.run_command(cmd, timeout=30)
        if exit_code != 0:
            raise HTTPException(status_code=500, detail=f"Could not list Pi3 artifacts: {stderr or stdout}")

        artifacts: list[Pi3ArtifactDescriptor] = []
        for line in stdout.splitlines():
            parts = line.strip().split("|")
            if len(parts) != 3:
                continue
            name, size_raw, mtime_raw = parts
            if PurePosixPath(name).suffix.lower() not in PI3_ALLOWED_ARTIFACT_EXTENSIONS:
                continue
            try:
                size_bytes = int(size_raw)
                mtime_epoch = int(float(mtime_raw))
            except ValueError:
                continue
            artifacts.append(
                Pi3ArtifactDescriptor(
                    name=name,
                    path=f"{session.remote_output_dir}/{name}",
                    size_bytes=size_bytes,
                    mtime_epoch=mtime_epoch,
                )
            )

        artifacts.sort(key=lambda item: item.mtime_epoch, reverse=True)
        return Pi3ArtifactsResponse(session_id=session_id, artifacts=artifacts)

    async def download_pi3_artifact(
        self,
        session_id: str,
        artifact_name: str,
        actor: AuthenticatedUser,
    ) -> Pi3ArtifactDownloadResponse:
        async with self._lock:
            session = self._pi3_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Pi3 session not found")
        self._ensure_owner_access(session.owner_username, actor)

        safe_name = self._sanitize_filename(artifact_name, "artifact_name")
        self._validate_extension(
            safe_name,
            PI3_ALLOWED_ARTIFACT_EXTENSIONS,
            "Unsupported artifact extension",
        )
        remote_path = f"{session.remote_output_dir}/{safe_name}"

        try:
            async with await ssh_manager.open_sftp() as sftp:
                attrs = await sftp.stat(remote_path)
                size_bytes = attrs.size or 0
                if size_bytes > 200 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail="Artifact too large to proxy (max 200 MB)")
                async with sftp.open(remote_path, "rb") as handle:
                    content = await handle.read()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"Artifact not found: {safe_name}") from exc

        media_type = "application/octet-stream"
        suffix = PurePosixPath(safe_name).suffix.lower()
        if suffix == ".ply":
            media_type = "application/octet-stream"
        elif suffix in {".obj", ".gltf", ".glb"}:
            media_type = "model/gltf-binary" if suffix == ".glb" else "text/plain"
        elif suffix == ".npz":
            media_type = "application/octet-stream"

        return Pi3ArtifactDownloadResponse(
            session_id=session_id,
            artifact_name=safe_name,
            content_base64=base64.b64encode(content).decode("ascii"),
            size_bytes=len(content),
            media_type=media_type,
        )

    async def stop_pi3_session(self, session_id: str, actor: AuthenticatedUser) -> SessionStopResponse:
        async with self._lock:
            session = self._pi3_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Pi3 session not found")
        self._ensure_owner_access(session.owner_username, actor)

        async with self._lock:
            self._pi3_sessions.pop(session_id, None)

        _, stderr, exit_code = await ssh_manager.run_command(f"scancel {shlex.quote(session.job_id)}")
        cancelled = exit_code == 0
        message = "Pi3 session cancelled" if cancelled else f"scancel failed: {stderr}"
        return SessionStopResponse(
            session_id=session.session_id,
            job_id=session.job_id,
            cancelled=cancelled,
            message=message,
        )

    def _render_marker_hold_batch_script(self, session: _MarkerSession) -> str:
        cuda_module_block = ""
        if session.cuda_module:
            module_name = shlex.quote(session.cuda_module)
            cuda_module_block = (
                "if command -v module >/dev/null 2>&1; then\n"
                f"  module load {module_name}\n"
                "fi\n"
            )

        return f"""#!/bin/bash
#SBATCH --job-name=hpc-link-marker-{session.session_id[:8]}
#SBATCH --partition={session.partition}
#SBATCH --gres=gpu:{session.gpu_count}
#SBATCH --time={session.time_limit}
#SBATCH --output={session.remote_session_dir}/slurm-%j.out
#SBATCH --error={session.remote_session_dir}/slurm-%j.err

set -euo pipefail
{cuda_module_block}
mkdir -p {shlex.quote(session.remote_input_dir)} {shlex.quote(session.remote_output_dir)}
echo "$(hostname)" > {shlex.quote(session.remote_session_dir)}/node.txt
echo "$(date -Iseconds)" > {shlex.quote(session.remote_session_dir)}/started_at.txt
echo "{session.partition}" > {shlex.quote(session.remote_session_dir)}/partition.txt
echo "{session.gpu_count}" > {shlex.quote(session.remote_session_dir)}/gpu_count.txt
echo "{session.torch_device}" > {shlex.quote(session.remote_session_dir)}/torch_device.txt
echo "Marker session ready. Waiting for conversion commands..."
while true; do sleep 120; done
"""

    async def create_marker_session(
        self,
        request: MarkerSessionCreateRequest,
        actor: AuthenticatedUser,
    ) -> MarkerSessionCreateResponse:
        partition = request.partition or self._settings.marker_default_partition or self._settings.default_partition
        enforce_allocation_policy(
            actor,
            partition=partition,
            gpu_type=None,
            gpu_count=request.gpu_count,
            duration_minutes=request.duration_minutes,
        )

        torch_device = (request.torch_device or self._settings.marker_torch_device or "auto").strip().lower()
        if torch_device not in {"auto", "cuda", "cpu", "mps"}:
            raise HTTPException(status_code=400, detail="torch_device must be one of: auto, cuda, cpu, mps")

        async with self._lock:
            session_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
            now = datetime.now(timezone.utc)
            remote_dir = f"{self._settings.hpc_apps_root}/marker/sessions/{session_id}"
            input_dir = f"{remote_dir}/input_documents"
            output_dir = f"{remote_dir}/outputs"

            session = _MarkerSession(
                session_id=session_id,
                partition=partition,
                gpu_count=request.gpu_count,
                duration_minutes=request.duration_minutes,
                time_limit=self._minutes_to_slurm_time(request.duration_minutes),
                job_id="",
                remote_session_dir=remote_dir,
                remote_input_dir=input_dir,
                remote_output_dir=output_dir,
                cuda_module=request.cuda_module or self._settings.marker_cuda_module,
                torch_device=torch_device,
                created_at=now,
                expires_at=now + timedelta(minutes=request.duration_minutes),
                owner_username=actor.username,
            )

        mkdir_cmd = (
            f"mkdir -p {shlex.quote(session.remote_session_dir)} "
            f"{shlex.quote(session.remote_input_dir)} {shlex.quote(session.remote_output_dir)}"
        )
        _, stderr, exit_code = await ssh_manager.run_command(mkdir_cmd)
        if exit_code != 0:
            raise HTTPException(status_code=500, detail=f"Could not create Marker session directories: {stderr}")

        script_content = self._render_marker_hold_batch_script(session)
        script_path = f"{session.remote_session_dir}/hold_marker.sbatch"
        try:
            async with await ssh_manager.open_sftp() as sftp:
                async with sftp.open(script_path, "w") as handle:
                    await handle.write(script_content)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to upload Marker launch script: {exc}") from exc

        stdout, stderr, exit_code = await ssh_manager.run_command(f"sbatch --parsable {shlex.quote(script_path)}")
        if exit_code != 0:
            raise HTTPException(status_code=500, detail=f"sbatch failed for Marker: {stderr or stdout}")

        job_id = self._extract_job_id(stdout)
        if not job_id:
            raise HTTPException(status_code=500, detail=f"Could not parse job ID from: {stdout}")

        session.job_id = job_id
        session.status = "queued"
        async with self._lock:
            self._marker_sessions[session.session_id] = session

        return MarkerSessionCreateResponse(
            session_id=session.session_id,
            app_id="marker",
            job_id=session.job_id,
            partition=session.partition,
            gpu_count=session.gpu_count,
            remote_session_dir=session.remote_session_dir,
            input_dir=session.remote_input_dir,
            output_dir=session.remote_output_dir,
            status=session.status,
            created_at=session.created_at,
            expires_at=session.expires_at,
        )

    async def get_marker_session_status(
        self,
        session_id: str,
        actor: AuthenticatedUser,
    ) -> MarkerSessionStatusResponse:
        async with self._lock:
            session = self._marker_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Marker session not found")
        self._ensure_owner_access(session.owner_username, actor)

        scheduler_state, scheduler_reason = await self._scheduler_state_for_job(session.job_id)
        remaining_seconds = self._remaining_seconds(session.expires_at)

        if scheduler_state == "RUNNING":
            session.status = "running"
        elif scheduler_state in ("PENDING", "CONFIGURING", "COMPLETING"):
            session.status = "queued"
        elif scheduler_state in TERMINAL_STATES or remaining_seconds == 0:
            session.status = "finished"
        else:
            session.status = "unknown"

        return MarkerSessionStatusResponse(
            session_id=session.session_id,
            app_id="marker",
            job_id=session.job_id,
            partition=session.partition,
            gpu_count=session.gpu_count,
            status=session.status,
            scheduler_state=scheduler_state,
            scheduler_reason=scheduler_reason,
            created_at=session.created_at,
            expires_at=session.expires_at,
            remaining_seconds=remaining_seconds,
        )

    async def get_marker_session_logs(
        self,
        session_id: str,
        actor: AuthenticatedUser,
        tail_lines: int = 200,
    ) -> SessionLogsResponse:
        async with self._lock:
            session = self._marker_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Marker session not found")
        self._ensure_owner_access(session.owner_username, actor)

        stdout_path = f"{session.remote_session_dir}/slurm-{session.job_id}.out"
        stderr_path = f"{session.remote_session_dir}/slurm-{session.job_id}.err"

        stdout_exists, stdout_tail = await self._tail_remote_file(stdout_path, tail_lines)
        stderr_exists, stderr_tail = await self._tail_remote_file(stderr_path, tail_lines)

        return SessionLogsResponse(
            session_id=session.session_id,
            job_id=session.job_id,
            tail_lines=tail_lines,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            stdout_exists=stdout_exists,
            stderr_exists=stderr_exists,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
        )

    async def upload_marker_document(
        self,
        session_id: str,
        request: MarkerDocumentUploadRequest,
        actor: AuthenticatedUser,
    ) -> MarkerDocumentUploadResponse:
        async with self._lock:
            session = self._marker_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Marker session not found")
        self._ensure_owner_access(session.owner_username, actor)

        filename = self._sanitize_filename(request.filename, "filename")
        self._validate_extension(
            filename,
            MARKER_ALLOWED_INPUT_EXTENSIONS,
            (
                "Unsupported file extension. Allowed: .pdf, .docx, .pptx, .xlsx, .html, .htm, "
                ".epub, .png, .jpg, .jpeg, .tif, .tiff, .bmp, .webp"
            ),
        )
        try:
            content = base64.b64decode(request.content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=400, detail="content_base64 is not valid base64") from exc

        size_bytes = len(content)
        if size_bytes == 0:
            raise HTTPException(status_code=400, detail="Uploaded document is empty")
        if size_bytes > 100 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Document is too large (max 100 MB)")

        remote_path = f"{session.remote_input_dir}/{filename}"
        try:
            async with await ssh_manager.open_sftp() as sftp:
                async with sftp.open(remote_path, "wb") as handle:
                    await handle.write(content)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not upload document to HPC: {exc}") from exc

        return MarkerDocumentUploadResponse(
            session_id=session_id,
            filename=filename,
            remote_path=remote_path,
            size_bytes=size_bytes,
        )

    async def _collect_marker_artifacts(self, session: _MarkerSession) -> list[MarkerArtifactDescriptor]:
        cmd = (
            "bash -lc "
            + shlex.quote(
                f"if [ ! -d {shlex.quote(session.remote_output_dir)} ]; then exit 0; fi; "
                f"find {shlex.quote(session.remote_output_dir)} -type f | while IFS= read -r f; do "
                "name=$(basename \"$f\"); "
                "size=$(stat -c%s \"$f\" 2>/dev/null || stat -f%z \"$f\"); "
                "mtime=$(stat -c%Y \"$f\" 2>/dev/null || stat -f%m \"$f\"); "
                "printf '%s|%s|%s|%s\\n' \"$name\" \"$size\" \"$mtime\" \"$f\"; "
                "done"
            )
        )
        stdout, stderr, exit_code = await ssh_manager.run_command(cmd, timeout=30)
        if exit_code != 0:
            raise HTTPException(status_code=500, detail=f"Could not list Marker artifacts: {stderr or stdout}")

        artifacts: list[MarkerArtifactDescriptor] = []
        for line in stdout.splitlines():
            parts = line.strip().split("|", maxsplit=3)
            if len(parts) != 4:
                continue
            name, size_raw, mtime_raw, path = parts
            if PurePosixPath(name).suffix.lower() not in MARKER_ALLOWED_ARTIFACT_EXTENSIONS:
                continue
            try:
                size_bytes = int(size_raw)
                mtime_epoch = int(float(mtime_raw))
            except ValueError:
                continue
            artifacts.append(
                MarkerArtifactDescriptor(
                    name=name,
                    path=path,
                    size_bytes=size_bytes,
                    mtime_epoch=mtime_epoch,
                )
            )

        artifacts.sort(key=lambda item: item.mtime_epoch, reverse=True)
        return artifacts

    async def convert_marker_document(
        self,
        session_id: str,
        request: MarkerConvertRequest,
        actor: AuthenticatedUser,
    ) -> MarkerConvertResponse:
        async with self._lock:
            session = self._marker_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Marker session not found")
        self._ensure_owner_access(session.owner_username, actor)

        status = await self.get_marker_session_status(session_id, actor)
        if status.scheduler_state != "RUNNING":
            raise HTTPException(
                status_code=409,
                detail=f"Marker session is not ready yet (state={status.scheduler_state})",
            )

        input_filename = self._sanitize_filename(request.input_filename, "input_filename")
        self._validate_extension(
            input_filename,
            MARKER_ALLOWED_INPUT_EXTENSIONS,
            "Unsupported input extension for marker conversion",
        )
        input_path = f"{session.remote_input_dir}/{input_filename}"

        marker_cmd_parts = [
            shlex.quote(self._settings.marker_binary),
            shlex.quote(input_path),
            "--output_dir",
            shlex.quote(session.remote_output_dir),
            "--output_format",
            shlex.quote(request.output_format),
        ]
        if request.page_range:
            marker_cmd_parts.extend(["--page_range", shlex.quote(request.page_range)])
        if request.force_ocr:
            marker_cmd_parts.append("--force_ocr")
        if request.use_llm:
            marker_cmd_parts.append("--use_llm")
        if request.strip_existing_ocr:
            marker_cmd_parts.append("--strip_existing_ocr")
        if request.disable_image_extraction:
            marker_cmd_parts.append("--disable_image_extraction")
        if request.debug:
            marker_cmd_parts.append("--debug")

        shell_parts = ["set -euo pipefail"]
        if session.cuda_module:
            shell_parts.append(
                f"if command -v module >/dev/null 2>&1; then module load {shlex.quote(session.cuda_module)}; fi"
            )
        shell_parts.extend(
            [
                f"test -f {shlex.quote(input_path)}",
                f"mkdir -p {shlex.quote(session.remote_output_dir)}",
            ]
        )
        if session.torch_device and session.torch_device != "auto":
            shell_parts.append(f"export TORCH_DEVICE={shlex.quote(session.torch_device)}")
        shell_parts.append(" ".join(marker_cmd_parts))
        inner_cmd = "; ".join(shell_parts)
        command = (
            f"srun --jobid={shlex.quote(session.job_id)} --overlap --ntasks=1 --nodes=1 "
            f"bash -lc {shlex.quote(inner_cmd)}"
        )

        stdout, stderr, exit_code = await ssh_manager.run_command(command, timeout=7200)
        if exit_code != 0:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Marker conversion command failed: "
                    f"{self._tail_text(stderr or stdout, max_chars=1200)}"
                ),
            )

        artifacts = await self._collect_marker_artifacts(session)
        if not artifacts:
            raise HTTPException(status_code=500, detail="Marker conversion finished but no output artifacts were found")

        return MarkerConvertResponse(
            session_id=session.session_id,
            job_id=session.job_id,
            input_filename=input_filename,
            output_format=request.output_format,
            artifact_count=len(artifacts),
            artifacts=artifacts,
            command_stdout_tail=self._tail_text(stdout),
            command_stderr_tail=self._tail_text(stderr),
        )

    async def list_marker_artifacts(
        self,
        session_id: str,
        actor: AuthenticatedUser,
    ) -> MarkerArtifactsResponse:
        async with self._lock:
            session = self._marker_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Marker session not found")
        self._ensure_owner_access(session.owner_username, actor)

        artifacts = await self._collect_marker_artifacts(session)
        return MarkerArtifactsResponse(session_id=session_id, artifacts=artifacts)

    async def download_marker_artifact(
        self,
        session_id: str,
        artifact_name: str,
        actor: AuthenticatedUser,
    ) -> MarkerArtifactDownloadResponse:
        async with self._lock:
            session = self._marker_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Marker session not found")
        self._ensure_owner_access(session.owner_username, actor)

        safe_name = self._sanitize_filename(artifact_name, "artifact_name")
        self._validate_extension(
            safe_name,
            MARKER_ALLOWED_ARTIFACT_EXTENSIONS,
            "Unsupported artifact extension",
        )
        remote_path = f"{session.remote_output_dir}/{safe_name}"
        _, _, exists_exit = await ssh_manager.run_command(f"test -f {shlex.quote(remote_path)}", timeout=20)
        if exists_exit != 0:
            find_cmd = (
                "bash -lc "
                + shlex.quote(
                    f"find {shlex.quote(session.remote_output_dir)} -type f -name {shlex.quote(safe_name)}"
                )
            )
            matches_stdout, matches_stderr, matches_exit = await ssh_manager.run_command(find_cmd, timeout=30)
            if matches_exit != 0:
                raise HTTPException(status_code=500, detail=f"Could not resolve artifact path: {matches_stderr or matches_stdout}")
            matches = [line.strip() for line in matches_stdout.splitlines() if line.strip()]
            if not matches:
                raise HTTPException(status_code=404, detail=f"Artifact not found: {safe_name}")
            if len(matches) > 1:
                raise HTTPException(
                    status_code=409,
                    detail=f"Artifact name '{safe_name}' is ambiguous; found {len(matches)} matches",
                )
            remote_path = matches[0]

        try:
            async with await ssh_manager.open_sftp() as sftp:
                attrs = await sftp.stat(remote_path)
                size_bytes = attrs.size or 0
                if size_bytes > 100 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail="Artifact too large to proxy (max 100 MB)")
                async with sftp.open(remote_path, "rb") as handle:
                    content = await handle.read()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"Artifact not found: {safe_name}") from exc

        suffix = PurePosixPath(safe_name).suffix.lower()
        media_type = "application/octet-stream"
        if suffix in {".md", ".markdown", ".txt"}:
            media_type = "text/markdown" if suffix in {".md", ".markdown"} else "text/plain"
        elif suffix == ".json":
            media_type = "application/json"
        elif suffix == ".html":
            media_type = "text/html"
        elif suffix == ".csv":
            media_type = "text/csv"
        elif suffix == ".xml":
            media_type = "application/xml"
        elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            media_type = "image/jpeg" if suffix in {".jpg", ".jpeg"} else f"image/{suffix[1:]}"

        return MarkerArtifactDownloadResponse(
            session_id=session_id,
            artifact_name=safe_name,
            content_base64=base64.b64encode(content).decode("ascii"),
            size_bytes=len(content),
            media_type=media_type,
        )

    async def stop_marker_session(self, session_id: str, actor: AuthenticatedUser) -> SessionStopResponse:
        async with self._lock:
            session = self._marker_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Marker session not found")
        self._ensure_owner_access(session.owner_username, actor)

        async with self._lock:
            self._marker_sessions.pop(session_id, None)

        _, stderr, exit_code = await ssh_manager.run_command(f"scancel {shlex.quote(session.job_id)}")
        cancelled = exit_code == 0
        message = "Marker session cancelled" if cancelled else f"scancel failed: {stderr}"
        return SessionStopResponse(
            session_id=session.session_id,
            job_id=session.job_id,
            cancelled=cancelled,
            message=message,
        )

    def _render_webhdp_hold_batch_script(self, session: _WebHdpSession) -> str:
        job_identity = session.session_id if "-" in session.session_id else session.session_id[:8]
        cuda_module_block = ""
        if session.cuda_module:
            module_name = shlex.quote(session.cuda_module)
            cuda_module_block = (
                "if command -v module >/dev/null 2>&1; then\n"
                f"  module load {module_name}\n"
                "fi\n"
            )
        gres_line = ""
        if session.gpu_count > 0:
            gres = f"gpu:{session.gpu_count}"
            if session.gpu_type:
                gres = f"gpu:{session.gpu_type}:{session.gpu_count}"
            gres_line = f"#SBATCH --gres={gres}\n"
        return f"""#!/bin/bash
#SBATCH --job-name=hpc-link-webhdp-{job_identity}
#SBATCH --partition={session.partition}
#SBATCH --cpus-per-task={self._settings.webhdp_cpus_per_task}
#SBATCH --mem={self._settings.webhdp_memory_mb}M
{gres_line.rstrip()}
#SBATCH --time={session.time_limit}
#SBATCH --output={session.remote_session_dir}/slurm-%j.out
#SBATCH --error={session.remote_session_dir}/slurm-%j.err

set -euo pipefail
{cuda_module_block}
mkdir -p {shlex.quote(session.remote_input_dir)} {shlex.quote(session.remote_output_dir)}
echo "$(hostname)" > {shlex.quote(session.remote_session_dir)}/node.txt
echo "$(date -Iseconds)" > {shlex.quote(session.remote_session_dir)}/started_at.txt
echo "{session.partition}" > {shlex.quote(session.remote_session_dir)}/partition.txt
echo "{session.gpu_count}" > {shlex.quote(session.remote_session_dir)}/gpu_count.txt
echo "WebHDP component session ready. Waiting for component commands..."
while true; do sleep 120; done
"""

    async def _inspect_running_webhdp_job(self, job_id: str) -> tuple[WebHdpReservationFacts, int, int]:
        """Read scheduler-owned structured fields instead of trusting a caller or job output."""
        if not re.fullmatch(r"[1-9][0-9]{0,18}", job_id):
            raise HTTPException(status_code=400, detail="Invalid Slurm job ID")
        try:
            stdout, _, code = await ssh_manager.run_command(f"scontrol --json show job {shlex.quote(job_id)}", timeout=20)
        except (OSError, TimeoutError, asyncssh.Error) as exc:
            raise HTTPException(status_code=503, detail="Could not reach the Slurm scheduler") from exc

        try:
            document = json.loads(stdout)
            jobs = document["jobs"]
        except (TypeError, json.JSONDecodeError, KeyError) as exc:
            raise HTTPException(status_code=503, detail="Slurm did not return structured job information") from exc
        if code or document.get("errors") or not isinstance(jobs, list) or len(jobs) != 1:
            raise HTTPException(status_code=404, detail="Slurm job was not found as a single allocation")
        job = jobs[0]
        if not isinstance(job, dict) or str(job.get("job_id")) != job_id:
            raise HTTPException(status_code=404, detail="Slurm did not return the requested job")
        if job.get("user_name") != self._settings.hpc_user:
            raise HTTPException(status_code=403, detail="The Slurm job is not owned by this gateway's SSH account")
        if job.get("job_state") not in ("RUNNING", ["RUNNING"]):
            raise HTTPException(status_code=409, detail="The Slurm job is not running")
        try:
            # Epoch timestamps avoid the login node's local timezone. Job ID,
            # owner UID and submission/start times pin the actual allocation.
            submitted = int(job["submit_time"])
            started = datetime.fromtimestamp(int(job["start_time"]), timezone.utc)
            expires = datetime.fromtimestamp(int(job["end_time"]), timezone.utc)
            owner_uid = int(job["user_id"])
            allocated = dict(value.split("=", maxsplit=1) for value in job["tres_alloc_str"].split(","))
            memory = re.fullmatch(r"(\d+)([KMGT]?)", allocated["mem"])
            if memory is None:
                raise ValueError("Unsupported memory unit")
            amount, unit = memory.groups()
            memory_mb = int(amount) * {"": 1, "K": 1 / 1024, "M": 1, "G": 1024, "T": 1024**2}[unit]
            partition, node = job["partition"], job["nodes"]
            gpu_count, cpus = int(allocated["gres/gpu"]), int(allocated["cpu"])
            gpu_types = [(key.removeprefix("gres/gpu:"), int(value)) for key, value in allocated.items()
                         if key.startswith("gres/gpu:") and int(value) > 0]
            gpu_type = gpu_types[0][0] if len(gpu_types) == 1 and gpu_types[0][1] == gpu_count else None
            if (int(allocated["node"]) != 1 or not re.fullmatch(r"[A-Za-z0-9_.-]+", node)
                    or not re.fullmatch(r"[A-Za-z0-9_.-]+", partition)
                    or gpu_count < 1 or cpus < 1 or memory_mb < 1 or submitted < 1 or owner_uid < 1
                    or started.timestamp() < submitted or expires <= datetime.now(timezone.utc)):
                raise ValueError("Invalid or exhausted allocation")
        except (KeyError, ValueError, TypeError, OverflowError, AttributeError, OSError) as exc:
            raise HTTPException(status_code=409, detail="Expected a running single-node allocation with an allocated GPU, CPU and memory") from exc
        return WebHdpReservationFacts(job_id=job_id, partition=partition, node_name=node, gpu_count=gpu_count,
                                      gpu_type=gpu_type, cpus=cpus, memory_mb=int(memory_mb),
                                      started_at=started, expires_at=expires), submitted, owner_uid

    async def inspect_webhdp_reservation(self, request: WebHdpReservationInspectRequest,
                                        actor: AuthenticatedUser) -> WebHdpReservationFacts:
        require_admin_user(actor)
        facts, _, _ = await self._inspect_running_webhdp_job(request.job_id)
        return facts

    @staticmethod
    def _reservation_payload(reservation: _WebHdpReservation, facts: WebHdpReservationFacts,
                             status: str) -> WebHdpReservationResponse:
        return WebHdpReservationResponse(**facts.model_dump(), reservation_id=reservation.reservation_id, status=status)

    @staticmethod
    def _check_reservation_identity(reservation: _WebHdpReservation, facts: WebHdpReservationFacts,
                                    submitted: int, owner_uid: int) -> None:
        if (submitted != reservation.submit_time or owner_uid != reservation.owner_uid
                or facts.model_dump(exclude={"expires_at"}) != reservation.facts.model_dump(exclude={"expires_at"})):
            raise HTTPException(status_code=409, detail="The registered Slurm allocation has changed")

    async def _current_reservation_facts(self, reservation: _WebHdpReservation) -> WebHdpReservationFacts:
        facts, submitted, owner_uid = await self._inspect_running_webhdp_job(reservation.facts.job_id)
        self._check_reservation_identity(reservation, facts, submitted, owner_uid)
        return facts

    def _get_reservation(self, reservation_id: str, actor: AuthenticatedUser) -> _WebHdpReservation:
        reservation = self._webhdp_reservations.get(reservation_id)
        if reservation is None:
            raise HTTPException(status_code=404, detail="WebHDP reservation not found")
        self._ensure_owner_access(reservation.owner_username, actor)
        return reservation

    def _active_claim(self, reservation_id: str) -> _WebHdpSession | None:
        return next((row for row in self._webhdp_sessions.values() if row.reservation_id == reservation_id), None)

    async def register_webhdp_reservation(self, request: WebHdpReservationRegisterRequest,
                                         actor: AuthenticatedUser) -> WebHdpReservationResponse:
        require_admin_user(actor)
        owner = auth_store.get_user_by_username(request.owner_username)
        if owner is None or not owner.is_active or not owner.invited:
            raise HTTPException(status_code=400, detail="Select an active HPC-Link account")
        facts, submitted, owner_uid = await self._inspect_running_webhdp_job(request.job_id)
        async with self._lock:
            for existing in self._webhdp_reservations.values():
                if existing.facts.job_id != facts.job_id or existing.revoked:
                    continue
                if existing.owner_username != owner.username:
                    raise HTTPException(status_code=409, detail="This job ID already has a different reservation registration")
                self._check_reservation_identity(existing, facts, submitted, owner_uid)
                return self._reservation_payload(existing, facts, "in_use" if self._active_claim(existing.reservation_id) else "available")
            if any(row.job_id == facts.job_id for row in self._webhdp_sessions.values()):
                raise HTTPException(status_code=409, detail="This Slurm job already belongs to a WebHDP session")
            reservation_id = str(uuid.uuid4())
            reservation = _WebHdpReservation(reservation_id, owner.username, facts, submitted, owner_uid)
            self._webhdp_reservations[reservation_id] = reservation
            try:
                self._save_webhdp_sessions_to_registry(required=True)
            except HTTPException:
                del self._webhdp_reservations[reservation_id]
                raise
        return self._reservation_payload(reservation, facts, "available")

    async def get_webhdp_reservation(self, reservation_id: str, actor: AuthenticatedUser) -> WebHdpReservationResponse:
        async with self._lock:
            reservation = self._get_reservation(reservation_id, actor)
            if reservation.revoked:
                raise HTTPException(status_code=404, detail="WebHDP reservation was revoked")
        try:
            facts = await self._current_reservation_facts(reservation)
        except HTTPException:
            status = "expired" if self._remaining_seconds(reservation.facts.expires_at) == 0 else "unavailable"
            return self._reservation_payload(reservation, reservation.facts, status)
        async with self._lock:
            if reservation.revoked:
                raise HTTPException(status_code=404, detail="WebHDP reservation was revoked")
            status = "in_use" if self._active_claim(reservation_id) else "available"
        return self._reservation_payload(reservation, facts, status)

    async def revoke_webhdp_reservation(self, reservation_id: str, actor: AuthenticatedUser) -> None:
        require_admin_user(actor)
        async with self._lock:
            reservation = self._get_reservation(reservation_id, actor)
            if self._active_claim(reservation_id):
                raise HTTPException(status_code=409, detail="Detach the active WebHDP claim before revoking the reservation")
            if reservation.revoked:
                return
            reservation.revoked = True
            try:
                self._save_webhdp_sessions_to_registry(required=True)
            except HTTPException:
                reservation.revoked = False
                raise

    @staticmethod
    def _adopted_session_payload(session: _WebHdpSession, facts: WebHdpReservationFacts) -> WebHdpSessionCreateResponse:
        return WebHdpSessionCreateResponse(
            session_id=session.session_id, app_id="webhdp", job_id=facts.job_id, partition=facts.partition,
            gpu_count=facts.gpu_count, remote_session_dir=session.remote_session_dir, input_dir=session.remote_input_dir,
            output_dir=session.remote_output_dir, status="running", created_at=session.created_at, expires_at=facts.expires_at,
            externally_managed=True, reservation_id=session.reservation_id, node_name=facts.node_name,
            gpu_type=facts.gpu_type, cpus=facts.cpus, memory_mb=facts.memory_mb,
        )

    async def adopt_webhdp_session(self, request: WebHdpSessionAdoptRequest,
                                  actor: AuthenticatedUser) -> WebHdpSessionCreateResponse:
        reservation_id, claim_id = str(request.reservation_id), str(request.claim_id)
        async with self._lock:
            reservation = self._get_reservation(reservation_id, actor)
            if reservation.revoked:
                raise HTTPException(status_code=404, detail="WebHDP reservation was revoked")
            if claim_id in reservation.closed_claims:
                raise HTTPException(status_code=409, detail="This WebHDP claim was already detached")
            facts = await self._current_reservation_facts(reservation)
            active = self._active_claim(reservation_id)
            if active is not None:
                if active.claim_id != claim_id:
                    raise HTTPException(status_code=409, detail="This GPU reservation already has an active WebHDP claim")
                return self._adopted_session_payload(active, facts)
            session_id = str(uuid.uuid4())
            remote_dir = f"{self._settings.hpc_apps_root.rstrip('/')}/webhdp/sessions/{session_id}"
            duration_minutes = max(1, int((facts.expires_at - facts.started_at).total_seconds() / 60))
            session = _WebHdpSession(
                session_id=session_id, partition=facts.partition, gpu_type=facts.gpu_type, gpu_count=facts.gpu_count,
                duration_minutes=duration_minutes, time_limit=self._minutes_to_slurm_time(duration_minutes),
                job_id=facts.job_id, remote_session_dir=remote_dir, remote_input_dir=f"{remote_dir}/inputs",
                remote_output_dir=f"{remote_dir}/outputs", cuda_module=None, created_at=datetime.now(timezone.utc),
                expires_at=facts.expires_at, status="running", owner_username=reservation.owner_username,
                reservation_id=reservation_id, claim_id=claim_id,
            )
            command = (f"umask 077; mkdir -p {shlex.quote(str(PurePosixPath(remote_dir).parent))} && "
                       f"mkdir {shlex.quote(remote_dir)} && "
                       f"mkdir {shlex.quote(session.remote_input_dir)} {shlex.quote(session.remote_output_dir)}")
            _, _, code = await ssh_manager.run_command(command, timeout=20)
            if code:
                raise HTTPException(status_code=503, detail="Could not create a private WebHDP reservation workspace")
            self._webhdp_sessions[session_id] = session
            try:
                self._save_webhdp_sessions_to_registry(required=True)
            except HTTPException:
                del self._webhdp_sessions[session_id]
                raise
        return self._adopted_session_payload(session, facts)

    async def create_webhdp_session(
        self,
        request: WebHdpSessionCreateRequest,
        actor: AuthenticatedUser,
    ) -> WebHdpSessionCreateResponse:
        partition = request.partition or self._settings.webhdp_default_partition
        enforce_allocation_policy(
            actor,
            partition=partition,
            gpu_type=request.gpu_type,
            gpu_count=request.gpu_count,
            duration_minutes=request.duration_minutes,
        )
        request_id = str(request.request_id) if request.request_id else None
        cuda_module = request.cuda_module or self._settings.webhdp_cuda_module
        async with self._lock:
            closed = self._closed_webhdp_requests.get(request_id) if request_id else None
            if closed:
                self._ensure_owner_access(closed["owner_username"], actor)
                raise HTTPException(status_code=409, detail="This allocation request was already released")
            existing = self._webhdp_sessions.get(request_id) if request_id else None
            if existing:
                self._ensure_owner_access(existing.owner_username, actor)
                if (existing.reservation_id is not None or existing.partition != partition
                        or existing.gpu_type != request.gpu_type or existing.gpu_count != request.gpu_count
                        or existing.duration_minutes != request.duration_minutes or existing.cuda_module != cuda_module):
                    raise HTTPException(status_code=409, detail="This allocation request has different resource settings")
                return self._ordinary_session_response(existing)
            session_id = request_id or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
            now = datetime.now(timezone.utc)
            remote_dir = f"{self._settings.hpc_apps_root}/webhdp/sessions/{session_id}"
            session = _WebHdpSession(
                session_id=session_id,
                partition=partition,
                gpu_type=request.gpu_type,
                gpu_count=request.gpu_count,
                duration_minutes=request.duration_minutes,
                time_limit=self._minutes_to_slurm_time(request.duration_minutes),
                job_id="",
                remote_session_dir=remote_dir,
                remote_input_dir=f"{remote_dir}/inputs",
                remote_output_dir=f"{remote_dir}/outputs",
                cuda_module=cuda_module,
                created_at=now,
                expires_at=now + timedelta(minutes=request.duration_minutes),
                owner_username=actor.username,
            )
            if request_id:
                self._webhdp_sessions[session_id] = session
                try:
                    # A crash during sbatch leaves an intent behind. Replaying the
                    # same request can recover the job but cannot submit another one.
                    self._save_webhdp_sessions_to_registry(required=True)
                except HTTPException:
                    del self._webhdp_sessions[session_id]
                    raise

        script_path = f"{session.remote_session_dir}/hold_webhdp.sbatch"
        try:
            mkdir_cmd = (f"umask 077; mkdir -p {shlex.quote(session.remote_session_dir)} "
                         f"{shlex.quote(session.remote_input_dir)} {shlex.quote(session.remote_output_dir)}")
            _, _, exit_code = await ssh_manager.run_command(mkdir_cmd)
            if exit_code != 0:
                raise HTTPException(status_code=500, detail="Could not create WebHDP session directories")
            async with await ssh_manager.open_sftp() as sftp:
                async with sftp.open(script_path, "w") as handle:
                    await handle.write(self._render_webhdp_hold_batch_script(session))
        except BaseException:
            if request_id:
                async with self._lock:
                    self._webhdp_sessions.pop(session_id, None)
                    self._save_webhdp_sessions_to_registry(required=True)
            raise

        stdout, _, exit_code = await ssh_manager.run_command(f"sbatch --parsable {shlex.quote(script_path)}")
        if exit_code != 0:
            raise HTTPException(status_code=500, detail="Could not confirm the scheduler submission")
        job_id = self._extract_job_id(stdout)
        if not job_id:
            raise HTTPException(status_code=500, detail="Could not confirm the scheduler job ID")
        async with self._lock:
            session.job_id = job_id
            self._webhdp_sessions[session.session_id] = session
            self._save_webhdp_sessions_to_registry(required=bool(request_id))
        return self._ordinary_session_response(session)

    async def get_webhdp_session_request(self, request_id: str, actor: AuthenticatedUser) -> WebHdpSessionCreateResponse | None:
        async with self._lock:
            closed = self._closed_webhdp_requests.get(request_id)
            if closed:
                self._ensure_owner_access(closed["owner_username"], actor)
                raise HTTPException(status_code=409, detail="This allocation request was already released")
            session = self._webhdp_sessions.get(request_id)
            if session is None or session.reservation_id is not None:
                return None
            self._ensure_owner_access(session.owner_username, actor)
            return self._ordinary_session_response(session)

    @staticmethod
    def _ordinary_session_response(session: _WebHdpSession) -> WebHdpSessionCreateResponse:
        if not session.job_id:
            raise HTTPException(status_code=409, detail="This allocation's scheduler submission is still unconfirmed")
        return WebHdpSessionCreateResponse(
            session_id=session.session_id,
            app_id="webhdp",
            job_id=session.job_id,
            partition=session.partition,
            gpu_count=session.gpu_count,
            remote_session_dir=session.remote_session_dir,
            input_dir=session.remote_input_dir,
            output_dir=session.remote_output_dir,
            status=session.status,
            created_at=session.created_at,
            expires_at=session.expires_at,
        )

    async def get_webhdp_session_status(
        self,
        session_id: str,
        actor: AuthenticatedUser,
    ) -> WebHdpSessionStatusResponse:
        async with self._lock:
            session = self._webhdp_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="WebHDP session not found")
        self._ensure_owner_access(session.owner_username, actor)
        if session.reservation_id is not None:
            return await self._get_adopted_session_status(session, actor)
        if not session.job_id:
            raise HTTPException(status_code=409, detail="This allocation's scheduler submission is still unconfirmed")
        scheduler_state, scheduler_reason = await self._scheduler_state_for_job(session.job_id)
        if scheduler_state == "RUNNING":
            session.status = "running"
        elif scheduler_state in ("PENDING", "CONFIGURING", "COMPLETING"):
            session.status = "queued"
        elif scheduler_state in TERMINAL_STATES:
            session.status = "finished"
        else:
            session.status = "unknown"
        node_stdout, _, _ = await ssh_manager.run_command(
            f"cat {shlex.quote(session.remote_session_dir + '/node.txt')} "
            f"{shlex.quote(session.remote_session_dir + '/started_at.txt')} 2>/dev/null || true",
            timeout=10,
        )
        node_lines = node_stdout.strip().splitlines()
        if len(node_lines) > 1:
            try:
                started_at = self._parse_datetime(node_lines[1])
                # Walltime begins when the hold job actually starts, not when
                # it joins the scheduler queue. Only Slurm decides termination.
                session.expires_at = started_at + timedelta(minutes=session.duration_minutes)
            except ValueError:
                pass
        remaining_seconds = self._remaining_seconds(session.expires_at)
        async with self._lock:
            if self._webhdp_sessions.get(session.session_id) is not session:
                raise HTTPException(status_code=404, detail="WebHDP session was released")
            self._webhdp_sessions[session.session_id] = session
            self._save_webhdp_sessions_to_registry()
        return WebHdpSessionStatusResponse(
            session_id=session.session_id,
            app_id="webhdp",
            job_id=session.job_id,
            partition=session.partition,
            gpu_count=session.gpu_count,
            status=session.status,
            scheduler_state=scheduler_state,
            scheduler_reason=scheduler_reason,
            node_name=node_lines[0] if node_lines else None,
            created_at=session.created_at,
            expires_at=session.expires_at,
            remaining_seconds=remaining_seconds,
        )

    async def _get_adopted_session_status(self, session: _WebHdpSession,
                                          actor: AuthenticatedUser) -> WebHdpSessionStatusResponse:
        reservation = await self.get_webhdp_reservation(session.reservation_id, actor)
        async with self._lock:
            if self._webhdp_sessions.get(session.session_id) is not session:
                raise HTTPException(status_code=404, detail="WebHDP session was detached")
        usable = reservation.status == "in_use"
        return WebHdpSessionStatusResponse(
            session_id=session.session_id, app_id="webhdp", job_id=reservation.job_id,
            partition=reservation.partition, gpu_count=reservation.gpu_count, status="running" if usable else "finished",
            scheduler_state="RUNNING" if usable else ("COMPLETED_OR_UNKNOWN" if reservation.status == "expired" else "UNKNOWN"),
            scheduler_reason=None if usable else reservation.status, node_name=reservation.node_name,
            created_at=session.created_at, expires_at=reservation.expires_at,
            remaining_seconds=self._remaining_seconds(reservation.expires_at), externally_managed=True,
            reservation_id=session.reservation_id, gpu_type=reservation.gpu_type, cpus=reservation.cpus,
            memory_mb=reservation.memory_mb,
        )

    async def get_webhdp_session_logs(
        self,
        session_id: str,
        actor: AuthenticatedUser,
        tail_lines: int = 200,
    ) -> SessionLogsResponse:
        async with self._lock:
            session = self._webhdp_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="WebHDP session not found")
        self._ensure_owner_access(session.owner_username, actor)
        stdout_path = f"{session.remote_session_dir}/slurm-{session.job_id}.out"
        stderr_path = f"{session.remote_session_dir}/slurm-{session.job_id}.err"
        stdout_exists, stdout_tail = await self._tail_remote_file(stdout_path, tail_lines)
        stderr_exists, stderr_tail = await self._tail_remote_file(stderr_path, tail_lines)
        return SessionLogsResponse(
            session_id=session.session_id,
            job_id=session.job_id,
            tail_lines=tail_lines,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            stdout_exists=stdout_exists,
            stderr_exists=stderr_exists,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
        )

    async def download_webhdp_artifact(self, session_id: str, path: str, actor: AuthenticatedUser):
        """Stream only artifacts inside an owned allocation's output directory."""
        from app.security import validate_path

        async with self._lock:
            session = self._webhdp_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="WebHDP session not found")
        self._ensure_owner_access(session.owner_username, actor)
        root = session.remote_output_dir
        safe_path = validate_path(path, base_path=root)
        try:
            async with await ssh_manager.open_sftp() as sftp:
                resolved = validate_path(str(await sftp.realpath(safe_path)), base_path=root)
                attrs = await sftp.stat(resolved)
                if not stat_module.S_ISREG(attrs.permissions or 0):
                    raise HTTPException(status_code=400, detail="Artifact must be a regular file")
                size = attrs.size or 0
        except asyncssh.SFTPError:
            raise HTTPException(status_code=404, detail="Artifact not found")

        async def chunks():
            async with await ssh_manager.open_sftp() as sftp:
                resolved = validate_path(str(await sftp.realpath(safe_path)), base_path=root)
                async with sftp.open(resolved, "rb") as handle:
                    remaining = size
                    while remaining:
                        chunk = await handle.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise IOError("Artifact ended before the declared file size")
                        remaining -= len(chunk)
                        yield chunk

        return StreamingResponse(chunks(), media_type="application/octet-stream", headers={"Content-Length": str(size)})

    async def stage_webhdp_cloud_files(
        self,
        session_id: str,
        request: WebHdpCloudStageRequest,
        actor: AuthenticatedUser,
    ) -> WebHdpCloudStageResponse:
        async with self._lock:
            session = self._webhdp_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="WebHDP session not found")
        self._ensure_owner_access(session.owner_username, actor)
        max_files = max(1, int(self._settings.webhdp_cloud_stage_max_files))
        max_file_bytes = self._max_bytes_arg(self._settings.webhdp_cloud_stage_max_file_bytes)
        if len(request.files) > max_files:
            raise HTTPException(status_code=413, detail=f"Too many files to stage (max {max_files})")
        staged: list[dict[str, object]] = []
        for file_item in request.files:
            filename = self._sanitize_filename(file_item.name, "name")
            relative = (PurePosixPath(str(file_item.relative_dir or '').strip().strip('/')) / filename).as_posix()
            target_path = self._staged_input_target(session, relative)
            temporary = target_path + '.part-' + uuid.uuid4().hex
            async with await ssh_manager.open_sftp() as sftp:
                await self._prepare_staged_input_parent(sftp, session, relative)
                try:
                    async with sftp.open(temporary, 'xb', attrs=asyncssh.SFTPAttrs(permissions=0o600)):
                        pass
                    await self._fetch_webhdp_cloud_file(file_item.url, temporary, max_file_bytes)
                    attrs = await sftp.lstat(temporary)
                    if not stat_module.S_ISREG(attrs.permissions or 0):
                        raise HTTPException(status_code=502, detail='Cloud staging did not produce a regular file')
                    size_bytes = attrs.size or 0
                    if size_bytes > max_file_bytes:
                        raise HTTPException(status_code=413, detail=f'Staged file too large (max {max_file_bytes} bytes)')
                    await sftp.posix_rename(temporary, target_path)
                finally:
                    try:
                        await sftp.remove(temporary)
                    except asyncssh.SFTPNoSuchFile:
                        pass
            staged.append({"name": filename, "remote_path": target_path, "size_bytes": size_bytes})
        return WebHdpCloudStageResponse(session_id=session_id, staged_files=staged)

    async def _fetch_webhdp_cloud_file(self, url: str, temporary: str, max_file_bytes: int) -> None:
        # Revalidate and pin every redirect. The login node's DNS (and proxy
        # environment) must not replace the address checked by the gateway.
        for _ in range(6):
            value, host, addresses = await asyncio.to_thread(self._validated_stage_target, url)
            config = 'url = "' + value.replace('"', '\\"') + '"\n'
            pin = shlex.quote(f"{host}:443:{','.join(addresses)}")
            command = (
                "curl -q --config - --silent --globoff --noproxy '*' --proto '=https' "
                f"--resolve {pin} --connect-timeout 20 --max-time 1200 "
                f"--max-filesize {max_file_bytes} --output {shlex.quote(temporary)} "
                "--write-out '%{http_code}\\n%{redirect_url}\\n'"
            )
            stdout, _, code = await ssh_manager.run_command(command, timeout=1210, stdin=config)
            if code == 63:
                raise HTTPException(status_code=413, detail=f'Staged file too large (max {max_file_bytes} bytes)')
            status, _, redirect = stdout.partition('\n')
            if code or not status.isdecimal():
                raise HTTPException(status_code=502, detail='Cloud staging download failed')
            if 200 <= int(status) < 300:
                return
            if 300 <= int(status) < 400 and redirect.strip():
                url = redirect.strip()
                continue
            raise HTTPException(status_code=502, detail='Cloud staging host did not return a file')
        raise HTTPException(status_code=502, detail='Cloud staging exceeded the redirect limit')

    async def stage_webhdp_uploaded_files(
        self,
        session_id: str,
        request: WebHdpUploadStageRequest,
        actor: AuthenticatedUser,
    ) -> WebHdpCloudStageResponse:
        async with self._lock:
            session = self._webhdp_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="WebHDP session not found")
        self._ensure_owner_access(session.owner_username, actor)

        max_files = max(1, int(self._settings.webhdp_cloud_stage_max_files))
        max_file_bytes = self._max_bytes_arg(self._settings.webhdp_cloud_stage_max_file_bytes)
        if len(request.files) > max_files:
            raise HTTPException(status_code=413, detail=f'Too many files to stage (max {max_files})')
        staged: list[dict[str, object]] = []
        for file_item in request.files:
            filename = self._sanitize_filename(file_item.name, "name")
            if len(file_item.content_base64) > 4 * ((max_file_bytes + 2) // 3):
                raise HTTPException(status_code=413, detail='Staged file exceeds the file limit')
            try:
                data = base64.b64decode(file_item.content_base64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise HTTPException(status_code=400, detail=f"Invalid base64 payload for {filename}") from exc

            async def chunks():
                yield data

            relative = (PurePosixPath(str(file_item.relative_dir or '').strip().strip('/')) / filename).as_posix()
            staged.append(await self.stream_webhdp_file(session_id, relative, chunks(), actor, expected_size=len(data)))

        return WebHdpCloudStageResponse(session_id=session_id, staged_files=staged)

    async def stream_webhdp_file(self, session_id, path, chunks, actor, *, expected_size=None):
        """Atomically stage one owned input, preserving relative directories."""
        async with self._lock:
            session = self._webhdp_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="WebHDP session not found")
        self._ensure_owner_access(session.owner_username, actor)
        target = self._staged_input_target(session, path)
        temporary = target + ".part-" + uuid.uuid4().hex
        size = 0
        max_file_bytes = self._max_bytes_arg(self._settings.webhdp_cloud_stage_max_file_bytes)
        if expected_size is not None:
            try:
                expected_size = int(expected_size)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail='Invalid file length') from exc
            if not 0 <= expected_size <= max_file_bytes:
                raise HTTPException(status_code=413, detail='Staged file exceeds the file limit')
        async with await ssh_manager.open_sftp() as sftp:
            await self._prepare_staged_input_parent(sftp, session, path)
            try:
                async with sftp.open(temporary, "xb", attrs=asyncssh.SFTPAttrs(permissions=0o600)) as handle:
                    async for chunk in chunks:
                        size += len(chunk)
                        if size > max_file_bytes:
                            raise HTTPException(status_code=413, detail='Staged file exceeds the file limit')
                        await handle.write(chunk)
                if expected_size is not None and size != expected_size:
                    raise HTTPException(status_code=400, detail="Incomplete file upload")
                await sftp.posix_rename(temporary, target)
            except BaseException:
                try:
                    await sftp.remove(temporary)
                except asyncssh.SFTPError:
                    pass
                raise
        return {"name": PurePosixPath(path).name, "remote_path": target, "size_bytes": size}

    @staticmethod
    def _staged_input_target(session: _WebHdpSession, path: str) -> str:
        from app.security import validate_path
        relative = PurePosixPath(path)
        if not relative.parts or relative.is_absolute() or '..' in relative.parts or '\\' in path:
            raise HTTPException(status_code=400, detail='A safe relative input path is required')
        root = session.remote_input_dir
        return validate_path(f'{root}/{relative}', base_path=root)

    @staticmethod
    async def _prepare_staged_input_parent(sftp, session: _WebHdpSession, path: str) -> None:
        parent = session.remote_input_dir
        attrs = await sftp.lstat(parent)
        if not stat_module.S_ISDIR(attrs.permissions or 0):
            raise HTTPException(status_code=400, detail='Input root must be a directory, not a link')
        for part in PurePosixPath(path).parts[:-1]:
            parent += '/' + part
            try:
                attrs = await sftp.lstat(parent)
            except asyncssh.SFTPNoSuchFile:
                try:
                    await sftp.mkdir(parent, attrs=asyncssh.SFTPAttrs(permissions=0o700))
                except asyncssh.SFTPFileAlreadyExists:
                    pass
                attrs = await sftp.lstat(parent)
            if not stat_module.S_ISDIR(attrs.permissions or 0):
                raise HTTPException(status_code=400, detail='Input parent must be a directory, not a link')

    async def preflight_webhdp_components(
        self,
        session_id: str,
        request: WebHdpPreflightRequest,
        actor: AuthenticatedUser,
    ) -> WebHdpPreflightResponse:
        async with self._lock:
            session = self._webhdp_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="WebHDP session not found")
        self._ensure_owner_access(session.owner_username, actor)
        status = await self.get_webhdp_session_status(session_id, actor)
        if status.scheduler_state != "RUNNING":
            raise HTTPException(status_code=409, detail=f"WebHDP session is not ready yet (state={status.scheduler_state})")
        components = request.components or ["fast_renderer", "any_to_usdz"]
        checks: dict[str, object] = {}
        success = True
        for component in components:
            command = self._component_command(component)
            if not command:
                checks[component] = {"success": False, "error": "No command configured for component"}
                success = False
                continue
            check_command = (
                self._settings.webhdp_preflight_command or "true"
                if component in {"fast_renderer", "any_to_usdz"}
                else "command -v singularity"
            )
            stdout, stderr, exit_code = await self._run_in_webhdp_allocation(session, check_command, timeout=120)
            checks[component] = {
                "success": exit_code == 0,
                "stdout_tail": self._tail_text(stdout, 1200),
                "stderr_tail": self._tail_text(stderr, 1200),
            }
            if exit_code != 0:
                success = False
        return WebHdpPreflightResponse(
            session_id=session_id,
            success=success,
            checks=checks,
            error=None if success else "One or more WebHDP component preflight checks failed",
        )

    def _component_command(self, component_key: str) -> str | None:
        if component_key == "fast_renderer":
            return self._settings.webhdp_fast_renderer_command
        if component_key == "any_to_usdz":
            return self._settings.webhdp_any_to_usdz_command
        return (
            f"WEBHDP_COMPONENT_RUNTIME_ROOT={shlex.quote(self._settings.webhdp_component_runtime_root)} "
            f"python3 {shlex.quote(self._settings.webhdp_component_runner)}"
        )

    async def _run_in_webhdp_allocation(self, session: _WebHdpSession, inner_cmd: str, *, timeout: int | float = 7200,
                                       stdin: str | None = None):
        if session.reservation_id is not None:
            return await self._run_in_adopted_allocation(session, inner_cmd, timeout, stdin=stdin)
        command = (
            f"srun --jobid={shlex.quote(session.job_id)} --overlap --ntasks=1 --nodes=1 "
            f"bash -lc {shlex.quote(inner_cmd)}"
        )
        options = {'stdin': stdin} if stdin is not None else {}
        return await ssh_manager.run_command(command, timeout=timeout, **options)

    @staticmethod
    def _adopted_step_name(session: _WebHdpSession) -> str:
        return f"webhdp-{session.session_id}"

    @staticmethod
    def _adopted_guard_command(session: _WebHdpSession, command: str) -> str:
        # The lock also covers the interval before Slurm reports the named
        # step, including when the API process is restarted during launch.
        lock_path = shlex.quote(session.remote_session_dir + "/.claim-execution.lock")
        return f"flock -n -E 75 {lock_path} /bin/sh -c {shlex.quote(command)}"

    async def _adopted_step_is_running(self, session: _WebHdpSession) -> bool:
        # Slurm tracks active steps independently of this API process. That also
        # detects an orphaned SSH client or a gateway restart during an execution.
        job = shlex.quote(session.job_id)
        try:
            stdout, _, code = await ssh_manager.run_command(
                f"squeue --steps --jobs={job} --noheader --format '%i|%j'", timeout=20,
            )
        except (OSError, TimeoutError, asyncssh.Error) as exc:
            raise HTTPException(status_code=503, detail="Could not verify whether a WebHDP job step is still active") from exc
        if code:
            raise HTTPException(status_code=503, detail="Could not verify whether a WebHDP job step is still active")
        marker = self._adopted_step_name(session)
        return any(line.strip().split("|", maxsplit=1)[-1] == marker for line in stdout.splitlines())

    async def _run_in_adopted_allocation(self, session: _WebHdpSession, inner_cmd: str, timeout: int | float,
                                         *, stdin: str | None = None):
        async with self._lock:
            if self._webhdp_sessions.get(session.session_id) is not session:
                raise HTTPException(status_code=404, detail="WebHDP session was detached")
            reservation = self._webhdp_reservations.get(session.reservation_id)
            if reservation is None or reservation.revoked:
                raise HTTPException(status_code=409, detail="WebHDP reservation is unavailable")
            await self._current_reservation_facts(reservation)
            if session.session_id in self._active_webhdp_steps or await self._adopted_step_is_running(session):
                raise HTTPException(status_code=409, detail="This WebHDP reservation already has an active job step")
            self._active_webhdp_steps.add(session.session_id)
        command = (f"srun --jobid={shlex.quote(session.job_id)} --overlap --ntasks=1 --nodes=1 --immediate=15 "
                   f"--job-name={shlex.quote(self._adopted_step_name(session))} bash -lc {shlex.quote(inner_cmd)}")
        detached_marker = shlex.quote(session.remote_session_dir + "/.claim-detached")
        guarded = self._adopted_guard_command(session, f"test ! -e {detached_marker} || exit 76; exec {command}")
        try:
            options = {'stdin': stdin} if stdin is not None else {}
            result = await ssh_manager.run_command(guarded, timeout=timeout, **options)
            if result[2] == 75:
                raise HTTPException(status_code=409, detail="This WebHDP reservation already has an active job step")
            if result[2] == 76:
                raise HTTPException(status_code=409, detail="This WebHDP claim has been detached")
            return result
        finally:
            async with self._lock:
                self._active_webhdp_steps.discard(session.session_id)

    @staticmethod
    def _safe_component_segment(value: str, field: str) -> str:
        text = str(value or "").strip()
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$", text):
            raise HTTPException(status_code=400, detail=f"Invalid {field}")
        return text

    @staticmethod
    def _ensure_remote_sif_path(path: str) -> str:
        text = str(path or "").strip()
        parts = PurePosixPath(text).parts
        if not text.startswith("/") or ".." in parts or "\x00" in text or not text.lower().endswith(".sif"):
            raise HTTPException(status_code=400, detail="SIF path must be an absolute .sif path without traversal")
        return text

    @staticmethod
    def _clean_sha256(value: str | None) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return ""
        if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
            raise HTTPException(status_code=400, detail="sif_sha256 must be a 64-character hexadecimal SHA-256")
        return text

    def _webhdp_component_install_dir(self, component_key: str, version: str) -> str:
        key = self._safe_component_segment(component_key, "component_key")
        safe_version = self._safe_component_segment(version, "version")
        return f"{self._settings.hpc_apps_root}/webhdp/components/{key}/{safe_version}"

    async def _latest_webhdp_component_version(self, component_key: str) -> str:
        key = self._safe_component_segment(component_key, "component_key")
        base_dir = f"{self._settings.hpc_apps_root}/webhdp/components/{key}"
        command = (
            "bash -lc "
            + shlex.quote(
                f"if [ ! -d {shlex.quote(base_dir)} ]; then exit 4; fi; "
                f"find {shlex.quote(base_dir)} -mindepth 1 -maxdepth 1 -type d -printf '%f\\n' | sort -V | tail -n 1"
            )
        )
        stdout, stderr, exit_code = await ssh_manager.run_command(command, timeout=30)
        if exit_code != 0:
            raise HTTPException(status_code=404, detail=f"Component '{key}' is not installed: {stderr or stdout}")
        version = stdout.strip().splitlines()[-1] if stdout.strip() else ""
        return self._safe_component_segment(version, "version")

    async def _load_webhdp_component_profile(self, component_key: str, version: str | None) -> dict[str, Any]:
        key = self._safe_component_segment(component_key, "component_key")
        safe_version = self._safe_component_segment(version, "version") if version else await self._latest_webhdp_component_version(key)
        install_dir = self._webhdp_component_install_dir(key, safe_version)
        registry_path = f"{install_dir}/component.json"
        stdout, stderr, exit_code = await ssh_manager.run_command(f"cat {shlex.quote(registry_path)}", timeout=30)
        if exit_code != 0:
            raise HTTPException(status_code=404, detail=f"Component registry not found for {key}:{safe_version}: {stderr or stdout}")
        try:
            registry = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=500, detail=f"Component registry is invalid for {key}:{safe_version}") from exc

        manifest_path = str(registry.get("manifest_path") or f"{install_dir}/component.yaml")
        manifest_stdout, manifest_stderr, manifest_exit = await ssh_manager.run_command(
            f"cat {shlex.quote(manifest_path)}",
            timeout=30,
        )
        if manifest_exit != 0:
            raise HTTPException(status_code=404, detail=f"Component manifest not found: {manifest_stderr or manifest_stdout}")
        try:
            manifest = json.loads(manifest_stdout)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=500, detail=f"Component manifest is invalid for {key}:{safe_version}") from exc

        profile = {}
        for candidate in (manifest.get("execution") or {}).get("profiles") or []:
            if isinstance(candidate, dict) and candidate.get("handler") in {"generic_singularity_component", "trusted_host_component"}:
                profile = dict(candidate)
                break
        if not profile:
            raise HTTPException(status_code=400, detail=f"Component '{key}:{safe_version}' has no runnable installed profile")
        if not isinstance(profile.get("entrypoint"), list) or not profile["entrypoint"]:
            raise HTTPException(status_code=400, detail=f"Component '{key}:{safe_version}' has no entrypoint")
        sif_path = None
        if profile.get('handler') == 'trusted_host_component':
            # Host execution is reserved for operator-installed registry entries.
            # The public install API remains SIF-only; caller profiles are ignored.
            expected = registry.get('manifest_sha256')
            if not expected or hashlib.sha256(manifest_stdout.encode()).hexdigest() != expected:
                raise HTTPException(status_code=409, detail='Trusted host manifest checksum could not be verified')
            if not str(profile['entrypoint'][0]).startswith('/'):
                raise HTTPException(status_code=400, detail='Trusted host entrypoint must be absolute')
        else:
            sif_path = self._ensure_remote_sif_path(str(registry.get('sif_remote_path') or f'{install_dir}/component.sif'))
            profile['image'] = sif_path
            profile['sif_remote_path'] = sif_path
            profile['sif_sha256'] = registry.get('sif_sha256')
        return {
            "component_key": key,
            "component_version": safe_version,
            "profile": profile,
            "manifest_path": manifest_path,
            "sif_remote_path": sif_path,
        }

    async def get_webhdp_component_installation(self, component_key: str, version: str) -> dict[str, Any]:
        install_dir = self._webhdp_component_install_dir(component_key, version)
        stdout, stderr, code = await ssh_manager.run_command(f"cat {shlex.quote(install_dir + '/component.json')}", timeout=30)
        if code != 0:
            raise HTTPException(status_code=404, detail="Installation is not yet confirmed")
        registry = json.loads(stdout)
        if registry.get('manifest_sha256') and not registry.get('sif_remote_path'):
            runtime = await self._load_webhdp_component_profile(component_key, version)
            if runtime['profile'].get('handler') != 'trusted_host_component':
                raise HTTPException(status_code=409, detail='Installed host runtime could not be verified')
            return {**registry, 'remote_install_dir': install_dir, 'runtime': 'trusted_host_component', 'status': 'installed'}
        sif_path = self._ensure_remote_sif_path(registry["sif_remote_path"])
        stdout, stderr, code = await ssh_manager.run_command(f"sha256sum {shlex.quote(sif_path)} | awk '{{print $1}}'", timeout=300)
        if code != 0 or stdout.strip() != registry.get("sif_sha256"):
            raise HTTPException(status_code=409, detail="Installed SIF checksum could not be confirmed")
        return {**registry, "remote_install_dir": install_dir, "status": "installed"}

    async def validate_webhdp_component_install(
        self,
        request: WebHdpComponentInstallValidateRequest,
        actor: AuthenticatedUser,
    ) -> dict[str, Any]:
        component_key = self._safe_component_segment(request.component_key, "component_key")
        version = self._safe_component_segment(request.version, "version")
        if any(profile.get('handler') == 'trusted_host_component'
               for profile in (request.manifest.get('execution') or {}).get('profiles', []) if isinstance(profile, dict)):
            raise HTTPException(status_code=400, detail='Host runtime profiles require operator installation; this API accepts container components only')
        checks: dict[str, Any] = {
            "component_key": {"success": True, "value": component_key},
            "version": {"success": True, "value": version},
        }
        stdout, stderr, exit_code = await ssh_manager.run_command("command -v singularity", timeout=20)
        checks["singularity"] = {
            "success": exit_code == 0,
            "path": stdout.strip(),
            "stderr_tail": self._tail_text(stderr, 1000),
        }
        expected_sif_sha256 = self._clean_sha256(request.sif_sha256)

        if request.source_type == "remote_path":
            remote_path = self._ensure_remote_sif_path(request.sif_source)
            stdout, stderr, exit_code = await ssh_manager.run_command(
                (
                    f"test -f {shlex.quote(remote_path)} && "
                    f"stat -c%s {shlex.quote(remote_path)} && "
                    f"sha256sum {shlex.quote(remote_path)} | awk '{{print $1}}'"
                ),
                timeout=900,
            )
            lines = stdout.strip().splitlines()
            actual_sha256 = lines[-1].strip().lower() if exit_code == 0 and lines else ""
            checks["sif"] = {
                "success": exit_code == 0,
                "source_type": "remote_path",
                "path": remote_path,
                "size_bytes": int(lines[0]) if exit_code == 0 and lines and lines[0].isdigit() else None,
                "sha256": actual_sha256,
                "stderr_tail": self._tail_text(stderr, 1000),
            }
            if expected_sif_sha256:
                checks["sif_checksum"] = {
                    "success": exit_code == 0 and actual_sha256 == expected_sif_sha256,
                    "expected_sha256": expected_sif_sha256,
                    "actual_sha256": actual_sha256,
                }
        else:
            sif_url = self._validate_sif_download_url(request.sif_source)
            stdout, stderr, exit_code = await ssh_manager.run_command(
                (
                    "curl -fIL --proto '=https' --proto-redir '=https' "
                    f"--connect-timeout 20 --max-time 60 {shlex.quote(sif_url)} >/dev/null && echo ok"
                ),
                timeout=90,
            )
            checks["sif"] = {
                "success": exit_code == 0,
                "source_type": "https_url",
                "url": sif_url,
                "stdout_tail": self._tail_text(stdout, 1000),
                "stderr_tail": self._tail_text(stderr, 1000),
            }
            if expected_sif_sha256:
                checks["sif_checksum"] = {
                    "success": True,
                    "expected_sha256": expected_sif_sha256,
                    "actual_sha256": "",
                    "phase": "validated_after_download",
                }

        success = all(bool(item.get("success")) for item in checks.values() if isinstance(item, dict))
        return {"success": success, "checks": checks, "error": None if success else "One or more install checks failed"}

    async def install_webhdp_component(
        self,
        request: WebHdpComponentInstallRequest,
        actor: AuthenticatedUser,
    ):
        validation = await self.validate_webhdp_component_install(request, actor)
        if not validation.get("success"):
            raise HTTPException(status_code=400, detail=validation.get("error") or "Install validation failed")

        install_dir = self._webhdp_component_install_dir(request.component_key, request.version)
        manifest_path = f"{install_dir}/component.yaml"
        registry_path = f"{install_dir}/component.json"
        sif_path = f"{install_dir}/component.sif"
        logs: dict[str, Any] = {}
        expected_sif_sha256 = self._clean_sha256(request.sif_sha256)
        parent_dir = str(PurePosixPath(install_dir).parent)
        mkdir_stdout, mkdir_stderr, mkdir_exit = await ssh_manager.run_command(
            f"mkdir -p {shlex.quote(parent_dir)} && mkdir -m 700 {shlex.quote(install_dir)}", timeout=30
        )
        logs["mkdir"] = {"stdout": mkdir_stdout, "stderr": mkdir_stderr, "exit_code": mkdir_exit}
        if mkdir_exit != 0:
            raise HTTPException(status_code=409, detail="Component version directory already exists or could not be created. Existing artifacts are never overwritten; use a new component version after checking directory permissions.")

        if request.source_type == "remote_path":
            source_path = self._ensure_remote_sif_path(request.sif_source)
            if source_path != sif_path:
                stdout, stderr, exit_code = await ssh_manager.run_command(
                    f"cp {shlex.quote(source_path)} {shlex.quote(sif_path)}",
                    timeout=7200,
                )
                logs["copy_sif"] = {"stdout": stdout, "stderr": stderr, "exit_code": exit_code}
                if exit_code != 0:
                    raise HTTPException(status_code=502, detail=f"Could not copy SIF: {stderr or stdout}")
        else:
            sif_url = self._validate_sif_download_url(request.sif_source)
            max_sif_bytes = self._max_bytes_arg(self._settings.webhdp_component_sif_max_bytes)
            stdout, stderr, exit_code = await ssh_manager.run_command(
                (
                    f"curl -fL --proto '=https' --proto-redir '=https' --retry 3 --connect-timeout 30 "
                    f"--max-filesize {max_sif_bytes} -o {shlex.quote(sif_path)} {shlex.quote(sif_url)} && "
                    f"stat -c%s {shlex.quote(sif_path)}"
                ),
                timeout=7200,
            )
            logs["download_sif"] = {"stdout": stdout, "stderr": stderr, "exit_code": exit_code}
            if exit_code != 0:
                await ssh_manager.run_command(f"rm -f {shlex.quote(sif_path)}", timeout=20)
                raise HTTPException(status_code=502, detail=f"Could not download SIF: {stderr or stdout}")
            try:
                sif_size = int(stdout.strip().splitlines()[-1])
            except (IndexError, ValueError):
                sif_size = 0
            if sif_size > max_sif_bytes:
                await ssh_manager.run_command(f"rm -f {shlex.quote(sif_path)}", timeout=20)
                raise HTTPException(status_code=413, detail=f"SIF is too large (max {max_sif_bytes} bytes)")

        installed_sif_sha256 = ""
        # Always fingerprint installed artifacts, including sources without a supplied checksum.
        stdout, stderr, exit_code = await ssh_manager.run_command(
            f"sha256sum {shlex.quote(sif_path)} | awk '{{print $1}}'",
            timeout=900,
        )
        installed_sif_sha256 = stdout.strip().splitlines()[-1].strip().lower() if exit_code == 0 and stdout.strip() else ""
        logs["sif_checksum"] = {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "expected_sha256": expected_sif_sha256,
            "actual_sha256": installed_sif_sha256,
        }
        if exit_code != 0 or not installed_sif_sha256 or (expected_sif_sha256 and installed_sif_sha256 != expected_sif_sha256):
            await ssh_manager.run_command(f"rm -f {shlex.quote(sif_path)}", timeout=20)
            raise HTTPException(status_code=400, detail="Installed SIF SHA-256 did not match expected checksum")

        manifest_json = json.dumps(request.manifest, sort_keys=True)
        registry = {
            "request_id": request.request_id,
            "component_key": request.component_key,
            "version": request.version,
            "manifest_hash": request.manifest_hash,
            "sif_remote_path": sif_path,
            "sif_sha256": expected_sif_sha256 or installed_sif_sha256,
            "manifest_path": manifest_path,
        }
        try:
            async with await ssh_manager.open_sftp() as sftp:
                async with sftp.open(manifest_path, "w") as handle:
                    await handle.write(manifest_json)
                async with sftp.open(registry_path, "w") as handle:
                    await handle.write(json.dumps(registry, sort_keys=True))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not write component registry files: {exc}") from exc

        chmod_stdout, chmod_stderr, chmod_exit = await ssh_manager.run_command(
            f"chmod 700 {shlex.quote(install_dir)} && chmod 600 {shlex.quote(manifest_path)} {shlex.quote(registry_path)} {shlex.quote(sif_path)}",
            timeout=30,
        )
        logs["chmod"] = {"stdout": chmod_stdout, "stderr": chmod_stderr, "exit_code": chmod_exit}
        return {
            "success": True,
            "component_key": request.component_key,
            "version": request.version,
            "remote_install_dir": install_dir,
            "sif_remote_path": sif_path,
            "manifest_path": manifest_path,
            "registry_path": registry_path,
            "sif_sha256": installed_sif_sha256,
            "checks": validation.get("checks") or {},
            "logs": logs,
            "error": None,
        }

    async def test_webhdp_component(
        self,
        request: WebHdpComponentTestRequest,
        actor: AuthenticatedUser,
    ) -> dict[str, Any]:
        sif_path = self._ensure_remote_sif_path(request.sif_remote_path)
        if not request.test:
            return {"success": None, "status": "skipped", "warnings": ["No smoke test is declared. The workload was not executed."]}
        test_id = uuid.uuid4().hex
        test_dir = f"{self._settings.hpc_apps_root}/webhdp/test-runs/{test_id}"
        input_dir = f"{test_dir}/inputs"
        output_dir = f"{test_dir}/outputs"
        request_path = f"{test_dir}/request.json"
        response_path = f"{test_dir}/response.json"
        profile = {}
        for candidate in (request.manifest.get("execution") or {}).get("profiles") or []:
            if isinstance(candidate, dict) and candidate.get("handler") == "generic_singularity_component":
                profile = candidate
                break
        payload = {
            "component_key": request.component_key,
            "step_id": "hpc_component_smoke_test",
            "inputs": request.test.get("inputs") or {},
            "parameters": request.test.get("parameters") or {},
            "profile": {**profile, "image": sif_path},
            "remote_input_dir": input_dir,
            "remote_output_dir": output_dir,
        }
        await ssh_manager.run_command(f"mkdir -p {shlex.quote(input_dir)} {shlex.quote(output_dir)}", timeout=30)
        try:
            async with await ssh_manager.open_sftp() as sftp:
                for file_item in request.test.get("files") or []:
                    if not isinstance(file_item, dict):
                        continue
                    filename = self._sanitize_filename(str(file_item.get("name") or ""), "name")
                    content_base64 = str(file_item.get("content_base64") or "")
                    if not content_base64:
                        continue
                    try:
                        content = base64.b64decode(content_base64, validate=True)
                    except binascii.Error as exc:
                        raise HTTPException(status_code=400, detail=f"Invalid smoke-test fixture {filename}: {exc}") from exc
                    async with sftp.open(f"{input_dir}/{filename}", "wb") as handle:
                        await handle.write(content)
                async with sftp.open(request_path, "w") as handle:
                    await handle.write(json.dumps(payload, sort_keys=True))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not write smoke-test request: {exc}") from exc
        command = (
            f"WEBHDP_COMPONENT_RUNTIME_ROOT={shlex.quote(self._settings.webhdp_component_runtime_root)} "
            f"WEBHDP_COMPONENT_REQUEST={shlex.quote(request_path)} "
            f"WEBHDP_COMPONENT_RESPONSE={shlex.quote(response_path)} "
            f"WEBHDP_INPUT_DIR={shlex.quote(input_dir)} "
            f"WEBHDP_OUTPUT_DIR={shlex.quote(output_dir)} "
            f"python3 {shlex.quote(self._settings.webhdp_component_runner)}"
        )
        stdout, stderr, exit_code = await ssh_manager.run_command(command, timeout=7200)
        response_stdout, _, _ = await ssh_manager.run_command(f"cat {shlex.quote(response_path)} 2>/dev/null || true", timeout=30)
        parsed = None
        if response_stdout.strip():
            try:
                parsed = json.loads(response_stdout)
            except json.JSONDecodeError:
                parsed = None
        return {
            "success": exit_code == 0 and bool((parsed or {}).get("success", exit_code == 0)),
            "status": "completed" if exit_code == 0 else "failed",
            "remote_test_dir": test_dir,
            "response": parsed,
            "logs": {"stdout": stdout, "stderr": stderr},
            "error": None if exit_code == 0 else self._tail_text(stderr or stdout, 1600),
        }

    async def run_webhdp_component(
        self,
        session_id: str,
        request: WebHdpComponentRunRequest,
        actor: AuthenticatedUser,
    ) -> dict:
        async with self._lock:
            session = self._webhdp_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="WebHDP session not found")
        self._ensure_owner_access(session.owner_username, actor)
        status = await self.get_webhdp_session_status(session_id, actor)
        if status.scheduler_state != "RUNNING":
            raise HTTPException(status_code=409, detail=f"WebHDP session is not ready yet (state={status.scheduler_state})")

        command_template = self._component_command(request.component_key)
        if not command_template:
            raise HTTPException(status_code=400, detail=f"No WebHDP command configured for component '{request.component_key}'")
        request_path = f"{session.remote_session_dir}/request-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}.json"
        response_path = f"{session.remote_session_dir}/response-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}.json"
        payload = request.model_dump(mode="json")
        payload["remote_input_dir"] = session.remote_input_dir
        payload["remote_output_dir"] = session.remote_output_dir + "/invocation-" + uuid.uuid4().hex
        if request.component_key not in {"fast_renderer", "any_to_usdz"}:
            version = request.component_version or str(request.profile.get("version") or request.parameters.get("component_version") or "").strip() or None
            component_runtime = await self._load_webhdp_component_profile(request.component_key, version)
            payload["component_key"] = component_runtime["component_key"]
            payload["component_version"] = component_runtime["component_version"]
            expected_checksum = request.profile.get("sif_sha256")
            if expected_checksum and expected_checksum != component_runtime["profile"].get("sif_sha256"):
                raise HTTPException(status_code=409, detail="Installed component checksum changed; refusing to execute a different artifact")
            payload["profile"] = component_runtime["profile"]
        else:
            payload["profile"] = {}
        try:
            async with await ssh_manager.open_sftp() as sftp:
                async with sftp.open(request_path, "w") as handle:
                    await handle.write(json.dumps(payload, sort_keys=True))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to stage component request: {exc}") from exc

        inner_cmd = (
            "set -euo pipefail; "
            f"export WEBHDP_COMPONENT_REQUEST={shlex.quote(request_path)}; "
            f"export WEBHDP_COMPONENT_RESPONSE={shlex.quote(response_path)}; "
            f"export WEBHDP_INPUT_DIR={shlex.quote(session.remote_input_dir)}; "
            f"export WEBHDP_OUTPUT_DIR={shlex.quote(payload['remote_output_dir'])}; "
            f"{command_template}"
        )
        stdout, stderr, exit_code = await self._run_in_webhdp_allocation(
            session,
            inner_cmd,
            # Leave the component runner time to stop its process group and
            # write the failure response before the SSH transport expires.
            timeout=(request.timeout_seconds or 7200) + 30,
        )
        result: dict[str, Any] = {
            "success": exit_code == 0,
            "status": "completed" if exit_code == 0 else "failed",
            "command": ["hpc_link", request.component_key],
            "logs": {"stdout": stdout, "stderr": stderr},
            "remote_request_path": request_path,
            "remote_response_path": response_path,
        }
        response_stdout = stdout.strip()
        parsed = None
        if response_stdout.startswith("{") and response_stdout.endswith("}"):
            try:
                parsed = json.loads(response_stdout)
            except json.JSONDecodeError:
                parsed = None
        if parsed is None:
            cat_stdout, _, cat_exit = await ssh_manager.run_command(f"cat {shlex.quote(response_path)} 2>/dev/null || true", timeout=30)
            if cat_exit == 0 and cat_stdout.strip():
                try:
                    parsed = json.loads(cat_stdout)
                except json.JSONDecodeError:
                    parsed = None
        if isinstance(parsed, dict):
            result.update(parsed)
            result.setdefault("logs", {"stdout": stdout, "stderr": stderr})
        if exit_code != 0:
            result["success"] = False
            result["status"] = "failed"
            result.setdefault("error", self._tail_text(stderr or stdout, 1600) or "WebHDP component command failed")
        return result

    @staticmethod
    def _zenodo_api_base(environment: str) -> str:
        return "https://sandbox.zenodo.org" if environment == "sandbox" else "https://zenodo.org"

    @staticmethod
    def _ensure_webhdp_session_path(session: _WebHdpSession, remote_path: str) -> str:
        path = str(remote_path or "").strip()
        root = session.remote_output_dir.rstrip("/") + "/"
        if not path.startswith(root):
            raise HTTPException(status_code=400, detail="Zenodo upload paths must stay inside the WebHDP output workspace")
        if "\x00" in path or ".." in PurePosixPath(path).parts:
            raise HTTPException(status_code=400, detail="Zenodo upload path is invalid")
        return path

    async def _ensure_webhdp_session_regular_file(self, sftp, session: _WebHdpSession, remote_path: str) -> tuple[str, int]:
        path = self._ensure_webhdp_session_path(session, remote_path)
        root = session.remote_output_dir.rstrip("/") + "/"
        try:
            attrs = await sftp.lstat(path)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"Zenodo upload file not found: {path}") from exc
        permissions = attrs.permissions or 0
        if stat_module.S_ISLNK(permissions):
            raise HTTPException(status_code=400, detail="Zenodo upload files must not be symbolic links")
        if not stat_module.S_ISREG(permissions):
            raise HTTPException(status_code=400, detail="Zenodo upload path must be a regular file")
        real_path = await sftp.realpath(path)
        if not isinstance(real_path, str) or not real_path.startswith(root) or real_path != path:
            raise HTTPException(status_code=400, detail="Zenodo upload file realpath escapes the WebHDP session workspace")
        return real_path, attrs.size or 0

    def _render_zenodo_upload_script(self) -> str:
        return r'''#!/usr/bin/env python3
import json
import os
import sys
import urllib.parse

try:
    import requests
except Exception as exc:
    raise RuntimeError(f"Python requests package is required for Zenodo upload: {exc}") from exc


def main():
    payload = json.load(sys.stdin)
    token = payload["access_token"]
    api_base = payload["api_base"].rstrip("/")
    environment = payload.get("environment") or "sandbox"
    session = requests.Session()
    session.trust_env = False
    session.headers["Authorization"] = f"Bearer {token}"
    deposition = {}
    deposition_id = payload.get("deposition_id")

    if deposition_id:
        response = session.get(
            f"{api_base}/api/deposit/depositions/{deposition_id}",
            allow_redirects=False,
            timeout=60,
        )
        if not 200 <= response.status_code < 300:
            raise RuntimeError("Zenodo rejected the draft lookup")
        deposition = response.json()
        bucket_url = (deposition.get("links") or {}).get("bucket")
        deposition_id = str(deposition.get("id") or deposition_id)
    else:
        response = session.post(
            f"{api_base}/api/deposit/depositions",
            allow_redirects=False,
            json={"metadata": payload.get("metadata") or {}},
            timeout=60,
        )
        if not 200 <= response.status_code < 300:
            raise RuntimeError("Zenodo rejected the draft creation")
        deposition = response.json()
        deposition_id = str(deposition.get("id") or "")
        bucket_url = (deposition.get("links") or {}).get("bucket")

    bucket = urllib.parse.urlsplit(bucket_url or "")
    expected_host = urllib.parse.urlsplit(api_base).netloc
    if (bucket.scheme != "https" or bucket.netloc != expected_host or bucket.query or bucket.fragment
            or not bucket.path.startswith("/api/files/")):
        raise RuntimeError("Zenodo did not return an approved draft bucket URL")

    uploaded = []
    for item in payload.get("files") or []:
        remote_path = item["remote_path"]
        filename = item["name"]
        size_bytes = os.path.getsize(remote_path)
        upload_url = bucket_url.rstrip("/") + "/" + urllib.parse.quote(filename, safe="")
        with open(remote_path, "rb") as file_handle:
            response = session.put(upload_url, allow_redirects=False, data=file_handle, timeout=7200)
        if not 200 <= response.status_code < 300:
            raise RuntimeError("Zenodo rejected an artifact upload")
        uploaded.append(
            {
                "name": filename,
                "remote_path": remote_path,
                "size_bytes": size_bytes,
                "response": {"status": response.status_code},
            }
        )

    result = {
        "success": True,
        "environment": environment,
        "deposition_id": str(deposition_id or ""),
        "bucket_url": bucket_url,
        "uploaded_files": uploaded,
        "publish_requested": False,
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print(json.dumps({"success": False, "error": "Zenodo draft upload could not be completed"}))
        raise SystemExit(1)
'''

    async def upload_webhdp_zenodo_draft(
        self,
        session_id: str,
        request: WebHdpZenodoDraftUploadRequest,
        actor: AuthenticatedUser,
    ) -> WebHdpZenodoDraftUploadResponse:
        async with self._lock:
            session = self._webhdp_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="WebHDP session not found")
        self._ensure_owner_access(session.owner_username, actor)
        if request.publish:
            raise HTTPException(status_code=400, detail="Publishing through HPC-Link is disabled; upload drafts only")
        if request.environment == "production" and not request.allow_production:
            raise HTTPException(status_code=400, detail="Production upload requires allow_production=true")
        if request.bucket_url:
            raise HTTPException(status_code=400, detail="bucket_url is resolved by Zenodo and cannot be supplied by clients")
        if request.deposition_id is not None and not re.fullmatch(r'[1-9][0-9]{0,18}', str(request.deposition_id)):
            raise HTTPException(status_code=400, detail='Invalid Zenodo deposition ID')
        status = await self.get_webhdp_session_status(session_id, actor)
        if status.scheduler_state != "RUNNING":
            raise HTTPException(status_code=409, detail=f"WebHDP session is not ready yet (state={status.scheduler_state})")
        if not request.files:
            raise HTTPException(status_code=400, detail="At least one remote artifact is required")

        files: list[dict[str, Any]] = []
        try:
            async with await ssh_manager.open_sftp() as sftp:
                for file_item in request.files:
                    remote_path, size_bytes = await self._ensure_webhdp_session_regular_file(
                        sftp,
                        session,
                        file_item.remote_path,
                    )
                    filename = file_item.name or PurePosixPath(remote_path).name
                    filename = self._sanitize_filename(filename, "name")
                    files.append(
                        {
                            "remote_path": remote_path,
                            "name": filename,
                            "metadata": file_item.metadata,
                            "size_bytes": size_bytes,
                        }
                    )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not validate Zenodo upload files: {exc}") from exc

        upload_payload = {
            "environment": request.environment,
            "api_base": self._zenodo_api_base(request.environment),
            "access_token": request.access_token,
            "deposition_id": str(request.deposition_id) if request.deposition_id is not None else None,
            "metadata": request.metadata,
            "files": files,
        }

        # srun forwards stdin to the single task. The bearer token never needs
        # to enter the remote filesystem, process argv, environment, or logs.
        inner_cmd = f'python3 -c {shlex.quote(self._render_zenodo_upload_script())}'
        stdout, _, exit_code = await self._run_in_webhdp_allocation(
            session, inner_cmd, timeout=7200, stdin=json.dumps(upload_payload, sort_keys=True),
        )
        parsed: dict[str, Any] | None = None
        if stdout.strip():
            try:
                response = json.loads(stdout)
                if isinstance(response, dict):
                    parsed = response
            except json.JSONDecodeError:
                parsed = None
        if parsed is None:
            parsed = {
                "success": False,
                "environment": request.environment,
                "uploaded_files": [],
                "publish_requested": False,
                "error": "Zenodo upload did not produce a response",
            }
        if exit_code != 0:
            parsed["success"] = False
            parsed.setdefault("error", "Zenodo upload failed")
        parsed["session_id"] = session_id
        parsed.setdefault("environment", request.environment)
        parsed.setdefault("uploaded_files", [])
        parsed.setdefault("publish_requested", False)
        return WebHdpZenodoDraftUploadResponse(
            session_id=session_id,
            success=bool(parsed.get("success")),
            environment=str(parsed.get("environment") or request.environment),
            deposition_id=str(parsed.get("deposition_id")) if parsed.get("deposition_id") else None,
            bucket_url=parsed.get("bucket_url"),
            uploaded_files=[
                WebHdpZenodoUploadedFile(
                    name=str(item.get("name") or ""),
                    remote_path=str(item.get("remote_path") or ""),
                    size_bytes=int(item.get("size_bytes") or 0),
                    response=item.get("response") if isinstance(item.get("response"), dict) else {},
                )
                for item in parsed.get("uploaded_files", [])
                if isinstance(item, dict)
            ],
            publish_requested=False,
            error=parsed.get("error"),
        )

    @staticmethod
    def _detached_claim_response(reservation: _WebHdpReservation, session_id: str) -> SessionStopResponse:
        return SessionStopResponse(session_id=session_id, job_id=reservation.facts.job_id, cancelled=False,
                                   detached=True, message="WebHDP claim detached. The Slurm allocation was kept.")

    async def _detach_webhdp_claim_locked(self, reservation: _WebHdpReservation, claim_id: str) -> SessionStopResponse:
        if claim_id in reservation.closed_claims:
            return self._detached_claim_response(reservation, reservation.closed_claims[claim_id])
        active = self._active_claim(reservation.reservation_id)
        session = active if active is not None and active.claim_id == claim_id else None
        if session is not None:
            if session.session_id in self._active_webhdp_steps or await self._adopted_step_is_running(session):
                raise HTTPException(status_code=409, detail="This WebHDP claim has an active job step")
            detached_marker = shlex.quote(session.remote_session_dir + "/.claim-detached")
            command = self._adopted_guard_command(session, f"umask 077; touch {detached_marker}")
            try:
                _, _, code = await ssh_manager.run_command(command, timeout=20)
            except (OSError, TimeoutError, asyncssh.Error) as exc:
                raise HTTPException(status_code=503, detail="Could not close the remote WebHDP claim") from exc
            if code == 75:
                raise HTTPException(status_code=409, detail="This WebHDP claim is launching a job step")
            if code:
                raise HTTPException(status_code=503, detail="Could not close the remote WebHDP claim")
            del self._webhdp_sessions[session.session_id]
        session_id = session.session_id if session else ""
        reservation.closed_claims[claim_id] = session_id
        try:
            self._save_webhdp_sessions_to_registry(required=True)
        except HTTPException:
            del reservation.closed_claims[claim_id]
            if session is not None:
                self._webhdp_sessions[session_id] = session
            raise
        return self._detached_claim_response(reservation, session_id)

    async def detach_webhdp_claim(self, reservation_id: str, claim_id: str, actor: AuthenticatedUser) -> SessionStopResponse:
        async with self._lock:
            reservation = self._get_reservation(reservation_id, actor)
            return await self._detach_webhdp_claim_locked(reservation, claim_id)

    async def stop_webhdp_session(self, session_id: str, actor: AuthenticatedUser) -> SessionStopResponse:
        async with self._lock:
            session = self._webhdp_sessions.get(session_id)
            if session is None:
                closed = self._closed_webhdp_requests.get(session_id)
                if closed:
                    self._ensure_owner_access(closed["owner_username"], actor)
                    self._save_webhdp_sessions_to_registry(required=True)
                    return SessionStopResponse(session_id=session_id, job_id=closed["job_id"], cancelled=True,
                                               message="WebHDP session released")
                for reservation in self._webhdp_reservations.values():
                    if session_id and session_id in reservation.closed_claims.values():
                        self._ensure_owner_access(reservation.owner_username, actor)
                        return self._detached_claim_response(reservation, session_id)
                raise HTTPException(status_code=404, detail="WebHDP session not found")
            self._ensure_owner_access(session.owner_username, actor)
            if session.reservation_id is not None:
                reservation = self._get_reservation(session.reservation_id, actor)
                return await self._detach_webhdp_claim_locked(reservation, session.claim_id)
            if not session.job_id:
                raise HTTPException(status_code=409, detail="This allocation's scheduler submission is still unconfirmed")
            _, _, exit_code = await ssh_manager.run_command(f"scancel {shlex.quote(session.job_id)}", timeout=20)
            if exit_code != 0:
                scheduler_state, _ = await self._scheduler_state_for_job(session.job_id)
                if scheduler_state not in TERMINAL_STATES | {"COMPLETED_OR_UNKNOWN"}:
                    return SessionStopResponse(session_id=session.session_id, job_id=session.job_id, cancelled=False,
                                               message="Slurm has not confirmed that the allocation ended")
            self._webhdp_sessions.pop(session_id, None)
            keyed_request = "-" in session_id  # Ordinary legacy session IDs were numeric timestamps.
            if keyed_request:
                self._closed_webhdp_requests[session_id] = {"owner_username": session.owner_username, "job_id": session.job_id}
            self._save_webhdp_sessions_to_registry(required=keyed_request)
        return SessionStopResponse(
            session_id=session.session_id,
            job_id=session.job_id,
            cancelled=True,
            message="WebHDP session released",
        )


hpc_application_service = HpcApplicationGatewayService()
