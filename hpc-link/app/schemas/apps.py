"""Schemas for HPC application gateway endpoints."""
from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.security import validate_slurm_resource_token


def _validated_slurm_token(value: Optional[str], field: str) -> Optional[str]:
    try:
        return validate_slurm_resource_token(value, field)
    except Exception as exc:
        raise ValueError(str(getattr(exc, "detail", exc))) from exc


class ApplicationDescriptor(BaseModel):
    """Describes one available HPC application integration."""
    app_id: str
    name: str
    description: str


class VllmModelDescriptor(BaseModel):
    """Describes one selectable vLLM model."""
    model_id: str
    label: str
    path: str
    max_model_len: Optional[int] = None
    installed: Optional[bool] = None


class SessionCreateRequest(BaseModel):
    """Create a new app-backed compute session."""
    model_id: str
    partition: Optional[str] = None
    gpu_type: Optional[str] = None
    gpu_count: int = Field(default=1, ge=1, le=8)
    duration_minutes: int = Field(default=30, ge=5, le=180)

    @field_validator("partition", "gpu_type")
    @classmethod
    def validate_slurm_token(cls, value: Optional[str], info):
        return _validated_slurm_token(value, info.field_name)


class SessionCreateResponse(BaseModel):
    """Session allocation response."""
    session_id: str
    app_id: str
    model_id: str
    model_label: str
    job_id: str
    remote_session_dir: str
    status: str
    created_at: datetime
    expires_at: datetime


class SessionStatusResponse(BaseModel):
    """Current session status."""
    session_id: str
    app_id: str
    model_id: str
    model_label: str
    job_id: str
    status: str
    scheduler_state: str
    scheduler_reason: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    remaining_seconds: int


class SessionLogsResponse(BaseModel):
    """Recent runtime log content for a session."""
    session_id: str
    job_id: str
    tail_lines: int
    stdout_path: str
    stderr_path: str
    stdout_exists: bool
    stderr_exists: bool
    stdout_tail: str
    stderr_tail: str


class ChatRequest(BaseModel):
    """Chat request for a running model session."""
    message: str = Field(min_length=1, max_length=4000)
    temperature: float = Field(default=0.2, ge=0.0, le=1.5)
    max_tokens: int = Field(default=256, ge=32, le=2048)


class ChatResponse(BaseModel):
    """Model chat completion result."""
    session_id: str
    model_id: str
    reply: str
    usage_prompt_tokens: Optional[int] = None
    usage_completion_tokens: Optional[int] = None


class SessionStopResponse(BaseModel):
    """Response returned after cancelling a session."""
    session_id: str
    job_id: str
    cancelled: bool
    message: str
    detached: bool = False


class Pi3SessionCreateRequest(BaseModel):
    """Create a new Pi3 GPU-backed processing session."""
    partition: Optional[str] = None
    gpu_count: int = Field(default=1, ge=1, le=4)
    duration_minutes: int = Field(default=30, ge=5, le=240)
    cuda_module: Optional[str] = Field(default=None, min_length=1, max_length=64)

    @field_validator("partition", "cuda_module")
    @classmethod
    def validate_pi3_tokens(cls, value: Optional[str], info):
        return _validated_slurm_token(value, info.field_name)


class Pi3SessionCreateResponse(BaseModel):
    """Pi3 session allocation response."""
    session_id: str
    app_id: str
    job_id: str
    partition: str
    gpu_count: int
    remote_session_dir: str
    input_dir: str
    output_dir: str
    status: str
    created_at: datetime
    expires_at: datetime


class Pi3SessionStatusResponse(BaseModel):
    """Current Pi3 session status."""
    session_id: str
    app_id: str
    job_id: str
    partition: str
    gpu_count: int
    status: str
    scheduler_state: str
    scheduler_reason: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    remaining_seconds: int


class Pi3ImageUploadRequest(BaseModel):
    """One image upload payload for Pi3 processing."""
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1)


class Pi3ImageUploadResponse(BaseModel):
    """Pi3 image upload result."""
    session_id: str
    filename: str
    remote_path: str
    size_bytes: int


class Pi3ProcessRequest(BaseModel):
    """Trigger Pi3 processing for images uploaded to a session."""
    output_name: str = Field(default="result.ply", min_length=1, max_length=255)
    interval: int = Field(default=1, ge=1, le=120)
    ckpt_path: Optional[str] = None


class Pi3ProcessResponse(BaseModel):
    """Pi3 processing result metadata."""
    session_id: str
    job_id: str
    output_name: str
    artifact_path: str
    size_bytes: int
    command_stdout_tail: str
    command_stderr_tail: str


class Pi3ArtifactDescriptor(BaseModel):
    """One downloadable output artifact produced by Pi3."""
    name: str
    path: str
    size_bytes: int
    mtime_epoch: int


class Pi3ArtifactsResponse(BaseModel):
    """List of output artifacts for one Pi3 session."""
    session_id: str
    artifacts: list[Pi3ArtifactDescriptor]


class Pi3ArtifactDownloadResponse(BaseModel):
    """Artifact payload encoded for proxy/download by a client app."""
    session_id: str
    artifact_name: str
    content_base64: str
    size_bytes: int
    media_type: str


class MarkerSessionCreateRequest(BaseModel):
    """Create a new Marker conversion session on HPC."""
    partition: Optional[str] = None
    gpu_count: int = Field(default=1, ge=1, le=4)
    duration_minutes: int = Field(default=30, ge=5, le=240)
    cuda_module: Optional[str] = Field(default=None, min_length=1, max_length=64)
    torch_device: Optional[Literal["auto", "cuda", "cpu", "mps"]] = None

    @field_validator("partition", "cuda_module")
    @classmethod
    def validate_slurm_token(cls, value: Optional[str], info):
        return _validated_slurm_token(value, info.field_name)


class MarkerSessionCreateResponse(BaseModel):
    """Marker session allocation response."""
    session_id: str
    app_id: str
    job_id: str
    partition: str
    gpu_count: int
    remote_session_dir: str
    input_dir: str
    output_dir: str
    status: str
    created_at: datetime
    expires_at: datetime


class MarkerSessionStatusResponse(BaseModel):
    """Current Marker session status."""
    session_id: str
    app_id: str
    job_id: str
    partition: str
    gpu_count: int
    status: str
    scheduler_state: str
    scheduler_reason: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    remaining_seconds: int


class MarkerDocumentUploadRequest(BaseModel):
    """One source document upload payload for Marker conversion."""
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1)


class MarkerDocumentUploadResponse(BaseModel):
    """Marker document upload result."""
    session_id: str
    filename: str
    remote_path: str
    size_bytes: int


class MarkerArtifactDescriptor(BaseModel):
    """One conversion artifact produced by Marker."""
    name: str
    path: str
    size_bytes: int
    mtime_epoch: int


class MarkerConvertRequest(BaseModel):
    """Trigger Marker conversion for one uploaded document."""
    input_filename: str = Field(min_length=1, max_length=255)
    output_format: Literal["markdown", "json", "html", "chunks"] = "markdown"
    page_range: Optional[str] = Field(default=None, min_length=1, max_length=128)
    force_ocr: bool = False
    use_llm: bool = False
    strip_existing_ocr: bool = False
    disable_image_extraction: bool = False
    debug: bool = False


class MarkerConvertResponse(BaseModel):
    """Marker conversion result metadata."""
    session_id: str
    job_id: str
    input_filename: str
    output_format: str
    artifact_count: int
    artifacts: list[MarkerArtifactDescriptor]
    command_stdout_tail: str
    command_stderr_tail: str


class MarkerArtifactsResponse(BaseModel):
    """List of conversion artifacts for one Marker session."""
    session_id: str
    artifacts: list[MarkerArtifactDescriptor]


class MarkerArtifactDownloadResponse(BaseModel):
    """Artifact payload encoded for proxy/download by a client app."""
    session_id: str
    artifact_name: str
    content_base64: str
    size_bytes: int
    media_type: str


class WebHdpSessionCreateRequest(BaseModel):
    """Create a reusable WebHDP component execution allocation."""
    request_id: UUID | None = None
    partition: Optional[str] = None
    gpu_type: Optional[str] = None
    gpu_count: int = Field(default=1, ge=0, le=4)
    # The authenticated principal's policy applies the operational limit. Allow
    # multi-day reservations here so an explicitly authorized 12-hour hold is
    # not rejected by an unrelated historical eight-hour schema ceiling.
    duration_minutes: int = Field(default=30, ge=5, le=10080)
    cuda_module: Optional[str] = Field(default=None, min_length=1, max_length=64)
    webhdp_session_id: Optional[int] = None
    purpose: str = Field(default="workflow", min_length=1, max_length=32)

    @field_validator("partition", "gpu_type", "cuda_module")
    @classmethod
    def validate_slurm_token(cls, value: Optional[str], info):
        return _validated_slurm_token(value, info.field_name)


class WebHdpReservationInspectRequest(BaseModel):
    """Identify an existing single-node Slurm job on this gateway's cluster."""

    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")


class WebHdpReservationRegisterRequest(WebHdpReservationInspectRequest):
    """Delegate one verified reservation to an existing HPC-Link account."""

    owner_username: str = Field(min_length=1, max_length=128)


class WebHdpReservationFacts(BaseModel):
    job_id: str
    partition: str
    gpu_type: str | None = None
    gpu_count: int
    cpus: int
    memory_mb: int
    node_name: str
    started_at: datetime
    expires_at: datetime


class WebHdpReservationResponse(WebHdpReservationFacts):
    reservation_id: str
    status: Literal["available", "in_use", "expired", "unavailable"]


class WebHdpSessionAdoptRequest(BaseModel):
    """Open a private, idempotent claim on an operator-registered reservation."""

    model_config = ConfigDict(extra="forbid")
    reservation_id: UUID
    claim_id: UUID


class WebHdpSessionCreateResponse(BaseModel):
    """WebHDP allocation response."""
    session_id: str
    app_id: str
    job_id: str
    partition: str
    gpu_count: int
    remote_session_dir: str
    input_dir: str
    output_dir: str
    status: str
    created_at: datetime
    expires_at: datetime
    externally_managed: bool = False
    reservation_id: str | None = None
    node_name: str | None = None
    gpu_type: str | None = None
    cpus: int | None = None
    memory_mb: int | None = None


class WebHdpSessionStatusResponse(BaseModel):
    """Current WebHDP allocation status."""
    session_id: str
    app_id: str
    job_id: str
    partition: str
    gpu_count: int
    status: str
    scheduler_state: str
    scheduler_reason: Optional[str] = None
    node_name: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    remaining_seconds: int
    externally_managed: bool = False
    reservation_id: str | None = None
    gpu_type: str | None = None
    cpus: int | None = None
    memory_mb: int | None = None


class WebHdpCloudStageFile(BaseModel):
    """One cloud object to download directly from the HPC node."""
    url: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=255)
    relative_dir: str = ""


class WebHdpCloudStageRequest(BaseModel):
    """Stage files from scoped temporary cloud URLs into the remote workspace."""
    files: list[WebHdpCloudStageFile] = Field(default_factory=list, max_length=100)


class WebHdpCloudStageResponse(BaseModel):
    """Cloud staging result."""
    session_id: str
    staged_files: list[dict[str, Any]]


class WebHdpUploadStageFile(BaseModel):
    """One WebHDP-owned local file payload to stage into the remote workspace."""
    name: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1)
    relative_dir: str = ""


class WebHdpUploadStageRequest(BaseModel):
    """Stage files uploaded by the trusted WebHDP backend into the remote workspace."""
    files: list[WebHdpUploadStageFile] = Field(default_factory=list, max_length=20)


class WebHdpPreflightRequest(BaseModel):
    """Preflight one or more WebHDP components."""
    components: list[str] = Field(default_factory=list)


class WebHdpPreflightResponse(BaseModel):
    """Preflight response."""
    session_id: str
    success: bool
    checks: dict[str, Any]
    error: Optional[str] = None


class WebHdpComponentRunRequest(BaseModel):
    """Run one WebHDP component in an existing allocation."""
    component_key: str = Field(min_length=1, max_length=120)
    component_version: Optional[str] = Field(default=None, min_length=1, max_length=64)
    step_id: Optional[str] = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    profile: dict[str, Any] = Field(default_factory=dict)
    workdir: Optional[str] = None
    timeout_seconds: Optional[int] = Field(default=None, ge=1)
    scope: str = "record"
    record_context: dict[str, Any] = Field(default_factory=dict)
    batch_records: list[dict[str, Any]] = Field(default_factory=list)
    staged_files: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("profile")
    @classmethod
    def reject_client_executable_profile(cls, value: dict[str, Any]) -> dict[str, Any]:
        profile = value or {}
        forbidden = {"image", "sif_remote_path", "entrypoint"}
        if forbidden.intersection(profile):
            raise ValueError("component executable profile is resolved server-side")
        return profile

    @field_validator("component_version")
    @classmethod
    def validate_component_version(cls, value: Optional[str]) -> Optional[str]:
        return _validated_slurm_token(value, "component_version")


class WebHdpComponentInstallValidateRequest(BaseModel):
    """Validate a SIF-backed WebHDP component install request."""
    component_key: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=64)
    sif_source: str = Field(min_length=1)
    sif_sha256: Optional[str] = Field(default=None, min_length=64, max_length=64)
    source_type: Literal["remote_path", "https_url"]
    manifest: dict[str, Any] = Field(default_factory=dict)


class WebHdpComponentInstallRequest(WebHdpComponentInstallValidateRequest):
    """Install a SIF-backed WebHDP component under the HPC app registry."""
    manifest_hash: str = Field(min_length=1, max_length=128)
    request_id: Optional[str] = Field(default=None, min_length=1, max_length=36)


class WebHdpComponentInstallResponse(BaseModel):
    """Installed component registry response."""
    success: bool
    component_key: str
    version: str
    remote_install_dir: str
    sif_remote_path: str
    manifest_path: str
    registry_path: str
    sif_sha256: str
    checks: dict[str, Any] = Field(default_factory=dict)
    logs: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class WebHdpComponentTestRequest(BaseModel):
    """Run a login-node smoke test for an installed SIF-backed component."""
    component_key: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=64)
    manifest: dict[str, Any] = Field(default_factory=dict)
    sif_remote_path: str = Field(min_length=1)
    test: dict[str, Any] = Field(default_factory=dict)


class WebHdpZenodoDraftFile(BaseModel):
    """One remote WebHDP artifact to upload into a Zenodo draft."""
    remote_path: str = Field(min_length=1)
    name: Optional[str] = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WebHdpZenodoDraftUploadRequest(BaseModel):
    """Upload remote WebHDP artifacts into a Zenodo draft without publishing it."""
    environment: Literal["sandbox", "production"] = "sandbox"
    access_token: str = Field(min_length=1)
    deposition_id: Optional[str | int] = None
    bucket_url: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    files: list[WebHdpZenodoDraftFile] = Field(default_factory=list)
    publish: bool = False
    allow_production: bool = False


class WebHdpZenodoUploadedFile(BaseModel):
    """One Zenodo file upload result."""
    name: str
    remote_path: str
    size_bytes: int = 0
    response: dict[str, Any] = Field(default_factory=dict)


class WebHdpZenodoDraftUploadResponse(BaseModel):
    """Zenodo draft upload result."""
    session_id: str
    success: bool
    environment: str
    deposition_id: Optional[str] = None
    bucket_url: Optional[str] = None
    uploaded_files: list[WebHdpZenodoUploadedFile] = Field(default_factory=list)
    publish_requested: bool = False
    error: Optional[str] = None
