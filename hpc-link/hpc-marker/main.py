from __future__ import annotations

import base64
import binascii
from functools import lru_cache
from typing import Any

import httpx
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    hpc_link_base_url: str = "http://app-core:8000"
    request_timeout_seconds: float = 240.0


@lru_cache
def get_settings() -> Settings:
    return Settings()


app = FastAPI(
    title="HPC-Marker",
    version="0.1.0",
    description="Standalone containerized demo app for Marker document conversion via HPC-Link APIs.",
)


templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


class MarkerSessionCreateRequest(BaseModel):
    partition: str = "partition-a"
    gpu_count: int = Field(default=1, ge=1, le=4)
    duration_minutes: int = Field(default=30, ge=5, le=240)
    cuda_module: str | None = Field(default=None, min_length=1, max_length=64)
    torch_device: str | None = Field(default=None, pattern="^(auto|cuda|cpu|mps)$")


class MarkerConvertRequest(BaseModel):
    input_filename: str = Field(min_length=1, max_length=255)
    output_format: str = Field(default="markdown", pattern="^(markdown|json|html|chunks)$")
    page_range: str | None = Field(default=None, min_length=1, max_length=128)
    force_ocr: bool = False
    use_llm: bool = False
    strip_existing_ocr: bool = False
    disable_image_extraction: bool = False
    debug: bool = False


async def _call_hpc_link(
    method: str,
    path: str,
    authorization: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    settings = get_settings()
    base = settings.hpc_link_base_url.rstrip("/")
    url = f"{base}/api{path}"

    headers: dict[str, str] = {
        "Accept": "application/json",
        "Authorization": authorization,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.request(method=method, url=url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach HPC-Link API: {exc}") from exc

    if response.status_code >= 400:
        detail: Any
        try:
            data = response.json()
            detail = data.get("detail", data)
        except ValueError:
            detail = response.text or response.reason_phrase
        raise HTTPException(status_code=response.status_code, detail=detail)

    if not response.content:
        return {}

    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}


def _require_bearer_authorization(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return f"Bearer {token.strip()}"


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "hpc_link_base_url": get_settings().hpc_link_base_url,
        },
    )


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "hpc-marker"}


@app.get("/api/hpc-link/health")
async def hpc_link_health(request: Request) -> Any:
    return await _call_hpc_link("GET", "/health", _require_bearer_authorization(request))


@app.get("/api/apps")
async def list_apps(request: Request) -> Any:
    return await _call_hpc_link("GET", "/apps", _require_bearer_authorization(request))


@app.post("/api/marker/sessions")
async def create_marker_session(payload: MarkerSessionCreateRequest, request: Request) -> Any:
    return await _call_hpc_link(
        "POST",
        "/apps/marker/sessions",
        _require_bearer_authorization(request),
        payload.model_dump(exclude_none=True),
    )


@app.get("/api/marker/sessions/{session_id}")
async def get_marker_session(session_id: str, request: Request) -> Any:
    return await _call_hpc_link(
        "GET",
        f"/apps/marker/sessions/{session_id}",
        _require_bearer_authorization(request),
    )


@app.get("/api/marker/sessions/{session_id}/logs")
async def get_marker_session_logs(
    session_id: str,
    request: Request,
    tail_lines: int = Query(default=200, ge=20, le=2000),
) -> Any:
    return await _call_hpc_link(
        "GET",
        f"/apps/marker/sessions/{session_id}/logs?tail_lines={tail_lines}",
        _require_bearer_authorization(request),
    )


@app.post("/api/marker/sessions/{session_id}/documents")
async def upload_marker_document(session_id: str, request: Request, file: UploadFile = File(...)) -> Any:
    filename = file.filename or "upload.pdf"
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    payload = {
        "filename": filename,
        "content_base64": base64.b64encode(content).decode("ascii"),
    }
    return await _call_hpc_link(
        "POST",
        f"/apps/marker/sessions/{session_id}/documents",
        _require_bearer_authorization(request),
        payload,
    )


@app.post("/api/marker/sessions/{session_id}/convert")
async def convert_marker_document(session_id: str, payload: MarkerConvertRequest, request: Request) -> Any:
    return await _call_hpc_link(
        "POST",
        f"/apps/marker/sessions/{session_id}/convert",
        _require_bearer_authorization(request),
        payload.model_dump(exclude_none=True),
    )


@app.get("/api/marker/sessions/{session_id}/artifacts")
async def list_marker_artifacts(session_id: str, request: Request) -> Any:
    return await _call_hpc_link(
        "GET",
        f"/apps/marker/sessions/{session_id}/artifacts",
        _require_bearer_authorization(request),
    )


@app.get("/api/marker/sessions/{session_id}/artifacts/{artifact_name}/download")
async def download_marker_artifact(session_id: str, artifact_name: str, request: Request) -> Response:
    result = await _call_hpc_link(
        "GET",
        f"/apps/marker/sessions/{session_id}/artifacts/{artifact_name}",
        _require_bearer_authorization(request),
    )

    b64 = result.get("content_base64")
    if not isinstance(b64, str):
        raise HTTPException(status_code=502, detail="Invalid artifact payload from HPC-Link")

    try:
        content = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Artifact payload is not valid base64") from exc

    media_type = result.get("media_type") or "application/octet-stream"
    headers = {
        "Content-Disposition": f'attachment; filename="{artifact_name}"',
    }
    return Response(content=content, media_type=media_type, headers=headers)


@app.delete("/api/marker/sessions/{session_id}")
async def stop_marker_session(session_id: str, request: Request) -> Any:
    return await _call_hpc_link(
        "DELETE",
        f"/apps/marker/sessions/{session_id}",
        _require_bearer_authorization(request),
    )


@app.post("/api/allocations/marker")
async def allocate_marker(payload: MarkerSessionCreateRequest, request: Request) -> Any:
    """Allocation endpoint exposed for other applications/services."""
    return await create_marker_session(payload, request)


@app.get("/api/allocations/marker/{session_id}")
async def check_marker_allocation(session_id: str, request: Request) -> Any:
    """Allocation status endpoint exposed for other applications/services."""
    return await get_marker_session(session_id, request)
