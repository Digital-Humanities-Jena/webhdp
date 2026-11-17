"""Application gateway endpoints for pre-specified app integrations."""
from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.limiter import limiter
from app.schemas.apps import (
    ApplicationDescriptor,
    ChatRequest,
    ChatResponse,
    MarkerArtifactDownloadResponse,
    MarkerArtifactsResponse,
    MarkerConvertRequest,
    MarkerConvertResponse,
    MarkerDocumentUploadRequest,
    MarkerDocumentUploadResponse,
    MarkerSessionCreateRequest,
    MarkerSessionCreateResponse,
    MarkerSessionStatusResponse,
    Pi3ArtifactDownloadResponse,
    Pi3ArtifactsResponse,
    Pi3ImageUploadRequest,
    Pi3ImageUploadResponse,
    Pi3ProcessRequest,
    Pi3ProcessResponse,
    Pi3SessionCreateRequest,
    Pi3SessionCreateResponse,
    Pi3SessionStatusResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionLogsResponse,
    SessionStatusResponse,
    SessionStopResponse,
    VllmModelDescriptor,
    WebHdpCloudStageRequest,
    WebHdpCloudStageResponse,
    WebHdpComponentInstallRequest,
    WebHdpComponentInstallResponse,
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
)
from app.services.apps_gateway import hpc_application_service
from app.security import get_request_user, require_admin_user

router = APIRouter(prefix="/apps", tags=["Applications"])


@router.get("", response_model=list[ApplicationDescriptor])
async def list_applications():
    """List available HPC-linked applications."""
    return await hpc_application_service.list_applications()


@router.get("/vllm/models", response_model=list[VllmModelDescriptor])
async def list_vllm_models():
    """List selectable vLLM models and whether they appear installed."""
    return await hpc_application_service.list_vllm_models()


@router.post("/vllm/sessions", response_model=SessionCreateResponse)
@limiter.limit("5/minute")
async def create_vllm_session(request: Request, payload: SessionCreateRequest):
    """Create a time-bounded GPU session for a vLLM runtime."""
    return await hpc_application_service.create_vllm_session(payload, get_request_user(request))


@router.get("/vllm/sessions/{session_id}", response_model=SessionStatusResponse)
async def get_vllm_session_status(request: Request, session_id: str):
    """Inspect scheduler state and remaining time for a session."""
    return await hpc_application_service.get_vllm_session_status(session_id, get_request_user(request))


@router.get("/vllm/sessions/{session_id}/logs", response_model=SessionLogsResponse)
async def get_vllm_session_logs(
    request: Request,
    session_id: str,
    tail_lines: int = Query(default=200, ge=20, le=2000),
):
    """Tail the latest SLURM stdout/stderr for a session."""
    return await hpc_application_service.get_vllm_session_logs(
        session_id,
        get_request_user(request),
        tail_lines=tail_lines,
    )


@router.post("/vllm/sessions/{session_id}/chat", response_model=ChatResponse)
@limiter.limit("30/minute")
async def chat_vllm_session(request: Request, session_id: str, payload: ChatRequest):
    """Send one chat turn to the vLLM runtime in the allocated session."""
    return await hpc_application_service.chat_vllm_session(
        session_id,
        payload,
        get_request_user(request),
    )


@router.delete("/vllm/sessions/{session_id}", response_model=SessionStopResponse)
async def stop_vllm_session(request: Request, session_id: str):
    """Cancel the session's SLURM job."""
    return await hpc_application_service.stop_vllm_session(session_id, get_request_user(request))


@router.post("/pi3/sessions", response_model=Pi3SessionCreateResponse)
@limiter.limit("5/minute")
async def create_pi3_session(request: Request, payload: Pi3SessionCreateRequest):
    """Create a time-bounded GPU session for Pi3 image reconstruction."""
    return await hpc_application_service.create_pi3_session(payload, get_request_user(request))


@router.get("/pi3/sessions/{session_id}", response_model=Pi3SessionStatusResponse)
async def get_pi3_session_status(request: Request, session_id: str):
    """Inspect scheduler state and remaining time for a Pi3 session."""
    return await hpc_application_service.get_pi3_session_status(session_id, get_request_user(request))


@router.get("/pi3/sessions/{session_id}/logs", response_model=SessionLogsResponse)
async def get_pi3_session_logs(
    request: Request,
    session_id: str,
    tail_lines: int = Query(default=200, ge=20, le=2000),
):
    """Tail the latest SLURM stdout/stderr for a Pi3 session."""
    return await hpc_application_service.get_pi3_session_logs(
        session_id,
        get_request_user(request),
        tail_lines=tail_lines,
    )


@router.post("/pi3/sessions/{session_id}/images", response_model=Pi3ImageUploadResponse)
@limiter.limit("40/minute")
async def upload_pi3_image(request: Request, session_id: str, payload: Pi3ImageUploadRequest):
    """Upload one input image for a Pi3 session."""
    return await hpc_application_service.upload_pi3_image(
        session_id,
        payload,
        get_request_user(request),
    )


@router.post("/pi3/sessions/{session_id}/process", response_model=Pi3ProcessResponse)
@limiter.limit("6/hour")
async def process_pi3_session(request: Request, session_id: str, payload: Pi3ProcessRequest):
    """Run Pi3 on uploaded images and generate a 3D artifact."""
    return await hpc_application_service.process_pi3_session(
        session_id,
        payload,
        get_request_user(request),
    )


@router.get("/pi3/sessions/{session_id}/artifacts", response_model=Pi3ArtifactsResponse)
async def list_pi3_artifacts(request: Request, session_id: str):
    """List generated Pi3 artifacts for the session."""
    return await hpc_application_service.list_pi3_artifacts(session_id, get_request_user(request))


@router.get(
    "/pi3/sessions/{session_id}/artifacts/{artifact_name}",
    response_model=Pi3ArtifactDownloadResponse,
)
@limiter.limit("20/minute")
async def download_pi3_artifact(request: Request, session_id: str, artifact_name: str):
    """Download one generated Pi3 artifact as base64 payload."""
    return await hpc_application_service.download_pi3_artifact(
        session_id,
        artifact_name,
        get_request_user(request),
    )


@router.delete("/pi3/sessions/{session_id}", response_model=SessionStopResponse)
async def stop_pi3_session(request: Request, session_id: str):
    """Cancel the Pi3 session's SLURM job."""
    return await hpc_application_service.stop_pi3_session(session_id, get_request_user(request))


@router.post("/marker/sessions", response_model=MarkerSessionCreateResponse)
@limiter.limit("5/minute")
async def create_marker_session(request: Request, payload: MarkerSessionCreateRequest):
    """Create a time-bounded conversion session for Marker document processing."""
    return await hpc_application_service.create_marker_session(payload, get_request_user(request))


@router.get("/marker/sessions/{session_id}", response_model=MarkerSessionStatusResponse)
async def get_marker_session_status(request: Request, session_id: str):
    """Inspect scheduler state and remaining time for a Marker session."""
    return await hpc_application_service.get_marker_session_status(session_id, get_request_user(request))


@router.get("/marker/sessions/{session_id}/logs", response_model=SessionLogsResponse)
async def get_marker_session_logs(
    request: Request,
    session_id: str,
    tail_lines: int = Query(default=200, ge=20, le=2000),
):
    """Tail the latest SLURM stdout/stderr for a Marker session."""
    return await hpc_application_service.get_marker_session_logs(
        session_id,
        get_request_user(request),
        tail_lines=tail_lines,
    )


@router.post("/marker/sessions/{session_id}/documents", response_model=MarkerDocumentUploadResponse)
@limiter.limit("30/minute")
async def upload_marker_document(request: Request, session_id: str, payload: MarkerDocumentUploadRequest):
    """Upload one source document for Marker conversion."""
    return await hpc_application_service.upload_marker_document(
        session_id,
        payload,
        get_request_user(request),
    )


@router.post("/marker/sessions/{session_id}/convert", response_model=MarkerConvertResponse)
@limiter.limit("10/hour")
async def convert_marker_document(request: Request, session_id: str, payload: MarkerConvertRequest):
    """Run Marker conversion for one uploaded source document."""
    return await hpc_application_service.convert_marker_document(
        session_id,
        payload,
        get_request_user(request),
    )


@router.get("/marker/sessions/{session_id}/artifacts", response_model=MarkerArtifactsResponse)
async def list_marker_artifacts(request: Request, session_id: str):
    """List generated conversion artifacts for the session."""
    return await hpc_application_service.list_marker_artifacts(session_id, get_request_user(request))


@router.get(
    "/marker/sessions/{session_id}/artifacts/{artifact_name}",
    response_model=MarkerArtifactDownloadResponse,
)
@limiter.limit("20/minute")
async def download_marker_artifact(request: Request, session_id: str, artifact_name: str):
    """Download one generated conversion artifact as base64 payload."""
    return await hpc_application_service.download_marker_artifact(
        session_id,
        artifact_name,
        get_request_user(request),
    )


@router.delete("/marker/sessions/{session_id}", response_model=SessionStopResponse)
async def stop_marker_session(request: Request, session_id: str):
    """Cancel the Marker session's SLURM job."""
    return await hpc_application_service.stop_marker_session(session_id, get_request_user(request))


@router.post("/webhdp/sessions", response_model=WebHdpSessionCreateResponse)
@limiter.limit("5/minute")
async def create_webhdp_session(request: Request, payload: WebHdpSessionCreateRequest):
    """Create a reusable allocation for WebHDP component execution."""
    return await hpc_application_service.create_webhdp_session(payload, get_request_user(request))


@router.post("/webhdp/reservations/inspect", response_model=WebHdpReservationFacts)
@limiter.limit("10/minute")
async def inspect_webhdp_reservation(request: Request, payload: WebHdpReservationInspectRequest):
    """Read scheduler facts for an existing job owned by the gateway's SSH account."""
    actor = get_request_user(request)
    require_admin_user(actor)
    return await hpc_application_service.inspect_webhdp_reservation(payload, actor)


@router.post("/webhdp/reservations", response_model=WebHdpReservationResponse)
@limiter.limit("10/minute")
async def register_webhdp_reservation(request: Request, payload: WebHdpReservationRegisterRequest):
    """Delegate an existing running GPU allocation to one HPC-Link account."""
    actor = get_request_user(request)
    require_admin_user(actor)
    return await hpc_application_service.register_webhdp_reservation(payload, actor)


@router.get("/webhdp/reservations/{reservation_id}", response_model=WebHdpReservationResponse)
async def get_webhdp_reservation(request: Request, reservation_id: UUID):
    """Inspect one registered reservation without revealing its private claim workspace."""
    return await hpc_application_service.get_webhdp_reservation(str(reservation_id), get_request_user(request))


@router.delete("/webhdp/reservations/{reservation_id}", status_code=204)
async def revoke_webhdp_reservation(request: Request, reservation_id: UUID):
    """Revoke idle delegation of a GPU reservation without affecting Slurm."""
    actor = get_request_user(request)
    require_admin_user(actor)
    await hpc_application_service.revoke_webhdp_reservation(str(reservation_id), actor)


@router.post("/webhdp/sessions/adopt", response_model=WebHdpSessionCreateResponse)
@limiter.limit("10/minute")
async def adopt_webhdp_session(request: Request, payload: WebHdpSessionAdoptRequest):
    """Claim a registered reservation with a new private workflow workspace."""
    return await hpc_application_service.adopt_webhdp_session(payload, get_request_user(request))


@router.delete("/webhdp/reservations/{reservation_id}/claims/{claim_id}", response_model=SessionStopResponse)
async def detach_webhdp_claim(request: Request, reservation_id: UUID, claim_id: UUID):
    """Detach by a known claim ID, including recovery after a lost response."""
    return await hpc_application_service.detach_webhdp_claim(str(reservation_id), str(claim_id), get_request_user(request))


@router.get("/webhdp/sessions/{session_id}", response_model=WebHdpSessionStatusResponse)
async def get_webhdp_session_status(request: Request, session_id: str):
    """Inspect scheduler state for a WebHDP component allocation."""
    return await hpc_application_service.get_webhdp_session_status(session_id, get_request_user(request))


@router.get("/webhdp/sessions/{session_id}/logs", response_model=SessionLogsResponse)
async def get_webhdp_session_logs(
    request: Request,
    session_id: str,
    tail_lines: int = Query(default=200, ge=20, le=2000),
):
    """Tail WebHDP allocation logs."""
    return await hpc_application_service.get_webhdp_session_logs(
        session_id,
        get_request_user(request),
        tail_lines=tail_lines,
    )


@router.post("/webhdp/sessions/{session_id}/stage/cloud", response_model=WebHdpCloudStageResponse)
@limiter.limit("20/minute")
async def stage_webhdp_cloud_files(request: Request, session_id: str, payload: WebHdpCloudStageRequest):
    """Download scoped cloud URLs directly into the HPC-side WebHDP workspace."""
    return await hpc_application_service.stage_webhdp_cloud_files(
        session_id,
        payload,
        get_request_user(request),
    )


@router.post("/webhdp/sessions/{session_id}/stage/upload", response_model=WebHdpCloudStageResponse)
@limiter.limit("20/minute")
async def stage_webhdp_uploaded_files(request: Request, session_id: str, payload: WebHdpUploadStageRequest):
    """Stage trusted WebHDP backend uploads directly into the HPC-side workspace."""
    return await hpc_application_service.stage_webhdp_uploaded_files(
        session_id,
        payload,
        get_request_user(request),
    )


@router.put("/webhdp/sessions/{session_id}/stage/file")
async def stream_webhdp_file(request: Request, session_id: str, path: str):
    return await hpc_application_service.stream_webhdp_file(
        session_id, path, request.stream(), get_request_user(request),
        expected_size=request.headers.get("content-length"),
    )


@router.post("/webhdp/sessions/{session_id}/components/preflight", response_model=WebHdpPreflightResponse)
@limiter.limit("10/minute")
async def preflight_webhdp_components(request: Request, session_id: str, payload: WebHdpPreflightRequest):
    """Verify that requested WebHDP component runtimes are reachable in this allocation."""
    return await hpc_application_service.preflight_webhdp_components(
        session_id,
        payload,
        get_request_user(request),
    )


@router.post("/webhdp/sessions/{session_id}/components/run")
@limiter.limit("30/hour")
async def run_webhdp_component(request: Request, session_id: str, payload: WebHdpComponentRunRequest):
    """Run one WebHDP component inside an existing allocation."""
    return await hpc_application_service.run_webhdp_component(
        session_id,
        payload,
        get_request_user(request),
    )


@router.get("/webhdp/sessions/{session_id}/artifacts/download")
async def download_webhdp_artifact(request: Request, session_id: str, path: str = Query(...)):
    return await hpc_application_service.download_webhdp_artifact(session_id, path, get_request_user(request))


@router.post("/webhdp/components/validate-install")
@limiter.limit("20/minute")
async def validate_webhdp_component_install(request: Request, payload: WebHdpComponentInstallValidateRequest):
    """Validate a SIF-backed WebHDP component install package."""
    current_user = get_request_user(request)
    require_admin_user(current_user)
    return await hpc_application_service.validate_webhdp_component_install(
        payload,
        current_user,
    )


@router.post("/webhdp/components/install", response_model=WebHdpComponentInstallResponse)
@limiter.limit("10/hour")
async def install_webhdp_component(request: Request, payload: WebHdpComponentInstallRequest):
    """Install a SIF-backed WebHDP component into the remote WebHDP registry."""
    current_user = get_request_user(request)
    require_admin_user(current_user)
    return await hpc_application_service.install_webhdp_component(
        payload,
        current_user,
    )


@router.get("/webhdp/components/{component_key}/{version}")
async def get_webhdp_component_installation(request: Request, component_key: str, version: str):
    require_admin_user(get_request_user(request))
    return await hpc_application_service.get_webhdp_component_installation(component_key, version)


@router.post("/webhdp/components/test")
@limiter.limit("10/hour")
async def test_webhdp_component(request: Request, payload: WebHdpComponentTestRequest):
    """Run a smoke test for an installed SIF-backed WebHDP component."""
    current_user = get_request_user(request)
    require_admin_user(current_user)
    return await hpc_application_service.test_webhdp_component(
        payload,
        current_user,
    )


@router.post("/webhdp/sessions/{session_id}/zenodo/upload-draft", response_model=WebHdpZenodoDraftUploadResponse)
@limiter.limit("10/hour")
async def upload_webhdp_zenodo_draft(request: Request, session_id: str, payload: WebHdpZenodoDraftUploadRequest):
    """Upload WebHDP remote artifacts into a Zenodo draft without publishing."""
    return await hpc_application_service.upload_webhdp_zenodo_draft(
        session_id,
        payload,
        get_request_user(request),
    )


@router.delete("/webhdp/sessions/{session_id}", response_model=SessionStopResponse)
async def stop_webhdp_session(request: Request, session_id: str):
    """Release a WebHDP allocation or detach a claim on an independently held job."""
    return await hpc_application_service.stop_webhdp_session(session_id, get_request_user(request))
