from __future__ import annotations

from functools import lru_cache
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    hpc_link_base_url: str = "http://app-core:8000"
    request_timeout_seconds: float = 120.0


@lru_cache
def get_settings() -> Settings:
    return Settings()


app = FastAPI(
    title="HPC-Linktest",
    version="0.1.0",
    description="Standalone containerized demo app that uses HPC-Link APIs.",
)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


class VllmSessionCreateRequest(BaseModel):
    model_id: str
    partition: str = "partition-a"
    gpu_type: str | None = None
    gpu_count: int = Field(default=1, ge=1, le=8)
    duration_minutes: int = Field(default=30, ge=5, le=180)


class VllmChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    temperature: float = Field(default=0.2, ge=0.0, le=1.5)
    max_tokens: int = Field(default=256, ge=32, le=2048)


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
    return {"status": "ok", "service": "hpc-linktest"}


@app.get("/api/hpc-link/health")
async def hpc_link_health(request: Request) -> Any:
    return await _call_hpc_link("GET", "/health", _require_bearer_authorization(request))


@app.get("/api/apps")
async def list_apps(request: Request) -> Any:
    return await _call_hpc_link("GET", "/apps", _require_bearer_authorization(request))


@app.get("/api/vllm/models")
async def list_vllm_models(request: Request) -> Any:
    return await _call_hpc_link("GET", "/apps/vllm/models", _require_bearer_authorization(request))


@app.post("/api/vllm/sessions")
async def create_vllm_session(payload: VllmSessionCreateRequest, request: Request) -> Any:
    return await _call_hpc_link(
        "POST",
        "/apps/vllm/sessions",
        _require_bearer_authorization(request),
        payload.model_dump(exclude_none=True),
    )


@app.get("/api/vllm/sessions/{session_id}")
async def get_vllm_session(session_id: str, request: Request) -> Any:
    return await _call_hpc_link(
        "GET",
        f"/apps/vllm/sessions/{session_id}",
        _require_bearer_authorization(request),
    )


@app.get("/api/vllm/sessions/{session_id}/logs")
async def get_vllm_session_logs(
    session_id: str,
    request: Request,
    tail_lines: int = Query(default=200, ge=20, le=2000),
) -> Any:
    return await _call_hpc_link(
        "GET",
        f"/apps/vllm/sessions/{session_id}/logs?tail_lines={tail_lines}",
        _require_bearer_authorization(request),
    )


@app.post("/api/vllm/sessions/{session_id}/chat")
async def chat_vllm_session(session_id: str, payload: VllmChatRequest, request: Request) -> Any:
    return await _call_hpc_link(
        "POST",
        f"/apps/vllm/sessions/{session_id}/chat",
        _require_bearer_authorization(request),
        payload.model_dump(exclude_none=True),
    )


@app.delete("/api/vllm/sessions/{session_id}")
async def stop_vllm_session(session_id: str, request: Request) -> Any:
    return await _call_hpc_link(
        "DELETE",
        f"/apps/vllm/sessions/{session_id}",
        _require_bearer_authorization(request),
    )


@app.post("/api/allocations/vllm")
async def allocate_vllm(payload: VllmSessionCreateRequest, request: Request) -> Any:
    """Allocation endpoint exposed for other applications/services."""
    return await create_vllm_session(payload, request)


@app.get("/api/allocations/vllm/{session_id}")
async def check_vllm_allocation(session_id: str, request: Request) -> Any:
    """Allocation status endpoint exposed for other applications/services."""
    return await get_vllm_session(session_id, request)
