"""Authentication, authorization, and filesystem security helpers."""
from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import Optional

from fastapi import HTTPException, Request, Security, WebSocket, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.auth_store import AuthStore, AuthenticatedUser
from app.auth_tokens import TokenError, parse_access_token
from app.config import get_settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_auth = HTTPBearer(auto_error=False)

_settings = get_settings()
auth_store = AuthStore(_settings.auth_db_path)


SERVICE_PRINCIPAL_ID = -1
LEGACY_API_KEY_ALLOWED_ROUTES = (
    ("GET", re.compile(r"^/api/apps$")),
    ("POST", re.compile(r"^/api/apps/webhdp/sessions$")),
    ("POST", re.compile(r"^/api/apps/webhdp/sessions/requests$")),
    ("GET", re.compile(r"^/api/apps/webhdp/sessions/requests/[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")),
    ("GET", re.compile(r"^/api/apps/webhdp/sessions/[^/]+$")),
    ("GET", re.compile(r"^/api/apps/webhdp/sessions/[^/]+/logs$")),
    ("POST", re.compile(r"^/api/apps/webhdp/sessions/[^/]+/stage/cloud$")),
    ("POST", re.compile(r"^/api/apps/webhdp/sessions/[^/]+/stage/upload$")),
    ("POST", re.compile(r"^/api/apps/webhdp/sessions/[^/]+/components/preflight$")),
    ("POST", re.compile(r"^/api/apps/webhdp/sessions/[^/]+/components/run$")),
    ("POST", re.compile(r"^/api/apps/webhdp/sessions/[^/]+/zenodo/upload-draft$")),
    ("DELETE", re.compile(r"^/api/apps/webhdp/sessions/[^/]+$")),
)
SLURM_RESOURCE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def _service_principal() -> AuthenticatedUser:
    """Synthetic service principal used for legacy API key integrations."""
    settings = get_settings()
    return AuthenticatedUser(
        user_id=SERVICE_PRINCIPAL_ID,
        username="service-api-key",
        is_admin=False,
        invited=True,
        is_active=True,
        allowed_partitions=list(settings.legacy_api_key_allowed_partitions),
        allowed_gpu_types=list(settings.legacy_api_key_allowed_gpu_types),
        max_duration_minutes=max(1, int(settings.legacy_api_key_max_duration_minutes)),
        max_gpu_count=max(1, int(settings.legacy_api_key_max_gpu_count)),
    )


def _legacy_api_key_path_allowed(scope_obj: Request | WebSocket) -> bool:
    path = getattr(getattr(scope_obj, "url", None), "path", "") or scope_obj.scope.get("path", "")
    method = str(scope_obj.scope.get("method") or "GET").upper()
    return any(route_method == method and pattern.fullmatch(path) for route_method, pattern in LEGACY_API_KEY_ALLOWED_ROUTES)


async def get_api_key(
    request: Request,
    header_key: str | None = Security(api_key_header),
    bearer: HTTPAuthorizationCredentials | None = Security(bearer_auth),
):
    """
    Resolve authentication for HTTP endpoints.

    Priority:
    1. Bearer token (invited user)
    2. Legacy API key (service integrations, optional)
    """
    settings = get_settings()

    if bearer and bearer.scheme.lower() == "bearer":
        payload = _parse_bearer_token(bearer.credentials, settings.auth_token_secret)
        user = _resolve_token_user(payload)
        request.state.current_user = user
        return bearer.credentials

    if settings.legacy_api_key_auth_enabled:
        return _authenticate_legacy_api_key(request, header_key, settings.api_key)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


async def get_ws_api_key(websocket: WebSocket):
    """
    Resolve authentication for WebSocket endpoints.

    Accepts either:
    - `Authorization: Bearer <token>`
    - `Sec-WebSocket-Protocol: bearer.<token>`
    - `X-API-Key: <legacy-api-key>` when legacy mode is enabled.
    """
    settings = get_settings()

    token = _extract_ws_bearer_token(websocket, settings.allow_ws_query_token_auth)
    if token:
        payload = _parse_bearer_token(token, settings.auth_token_secret)
        websocket.state.current_user = _resolve_token_user(payload)
        return token

    if settings.legacy_api_key_auth_enabled:
        return _authenticate_legacy_api_key(
            websocket,
            websocket.headers.get("X-API-Key"),
            settings.api_key,
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


def _extract_ws_bearer_token(websocket: WebSocket, allow_query_token: bool) -> str | None:
    auth_header = (websocket.headers.get("authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        if token:
            return token

    ws_protocol_header = websocket.headers.get("sec-websocket-protocol") or ""
    for item in ws_protocol_header.split(","):
        candidate = item.strip()
        if candidate.lower().startswith("bearer."):
            token = candidate[7:].strip()
            if token:
                return token

    if allow_query_token:
        token = websocket.query_params.get("token")
        if token:
            return token

    return None


def _authenticate_legacy_api_key(
    scope_obj: Request | WebSocket,
    header_key: str | None,
    expected_key: str | None,
) -> str:
    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Server misconfiguration: API Key not set",
        )

    provided = header_key
    if provided != expected_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )

    if not _legacy_api_key_path_allowed(scope_obj):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Legacy API key access is limited to WebHDP service integration endpoints",
        )

    scope_obj.state.current_user = _service_principal()
    return provided


def _parse_bearer_token(token: str, secret: str) -> dict:
    try:
        return parse_access_token(token, secret)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {exc}",
        ) from exc


def _resolve_token_user(payload: dict) -> AuthenticatedUser:
    user_id = payload.get("sub")
    if not isinstance(user_id, int):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token: malformed subject",
        )

    user = auth_store.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token references unknown user",
        )
    if not user.is_active or not user.invited:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled or not invited",
        )
    return user


def get_request_user(request: Request) -> AuthenticatedUser:
    """Extract the authenticated user from request state."""
    user = getattr(request.state, "current_user", None)
    if isinstance(user, AuthenticatedUser):
        return user
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication context missing",
    )


def get_ws_request_user(websocket: WebSocket) -> AuthenticatedUser:
    """Extract the authenticated user from WebSocket state."""
    user = getattr(websocket.state, "current_user", None)
    if isinstance(user, AuthenticatedUser):
        return user
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication context missing",
    )


def require_admin_user(user: AuthenticatedUser) -> None:
    """Raise if the authenticated principal is not admin."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges required",
        )


def parse_slurm_time_to_minutes(time_value: str) -> int:
    """Parse SLURM time strings (`HH:MM:SS` or `D-HH:MM:SS`) to minutes."""
    text = time_value.strip()
    if not text:
        raise HTTPException(status_code=400, detail="time_limit cannot be empty")

    days = 0
    if "-" in text:
        day_token, text = text.split("-", maxsplit=1)
        if not day_token.isdigit():
            raise HTTPException(status_code=400, detail="Invalid SLURM time format")
        days = int(day_token)

    parts = text.split(":")
    if len(parts) == 3:
        hh, mm, ss = parts
    elif len(parts) == 2:
        hh, mm = parts
        ss = "0"
    else:
        raise HTTPException(status_code=400, detail="Invalid SLURM time format")

    if not (hh.isdigit() and mm.isdigit() and ss.isdigit()):
        raise HTTPException(status_code=400, detail="Invalid SLURM time format")

    total_seconds = (days * 24 * 3600) + (int(hh) * 3600) + (int(mm) * 60) + int(ss)
    return max(1, (total_seconds + 59) // 60)


def validate_slurm_resource_token(value: str | None, field: str) -> str | None:
    """Validate SLURM resource identifiers before they reach a shell command."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or not SLURM_RESOURCE_TOKEN_RE.fullmatch(text):
        raise HTTPException(status_code=400, detail=f"Invalid SLURM {field}")
    return text


def validate_slurm_time_string(value: str, field: str = "time_limit") -> str:
    """Validate a SLURM time string and return its stripped representation."""
    text = str(value or "").strip()
    parse_slurm_time_to_minutes(text)
    return text


def enforce_allocation_policy(
    user: AuthenticatedUser,
    *,
    partition: str,
    gpu_type: Optional[str],
    gpu_count: int,
    duration_minutes: int,
) -> None:
    """Enforce per-user GPU node and time constraints."""
    partition = validate_slurm_resource_token(partition, "partition") or ""
    gpu_type = validate_slurm_resource_token(gpu_type, "GPU type")
    if user.is_admin:
        return

    allowed_partitions = set(user.allowed_partitions)
    if partition not in allowed_partitions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"User '{user.username}' is not allowed to use partition '{partition}'. "
                f"Allowed partitions: {sorted(allowed_partitions)}"
            ),
        )

    requested_gpu = (gpu_type or "").strip()
    if requested_gpu and not user.allowed_gpu_types:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User '{user.username}' is not allowed to request typed GPUs",
        )

    if user.allowed_gpu_types:
        allowed_gpu_types = set(user.allowed_gpu_types)
        if requested_gpu and requested_gpu not in allowed_gpu_types:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"User '{user.username}' is not allowed to use GPU type '{requested_gpu}'. "
                    f"Allowed GPU types: {sorted(allowed_gpu_types)}"
                ),
            )

    if gpu_count > user.max_gpu_count:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"User '{user.username}' may request at most {user.max_gpu_count} GPU(s), "
                f"requested: {gpu_count}"
            ),
        )

    if duration_minutes > user.max_duration_minutes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"User '{user.username}' may request at most {user.max_duration_minutes} minutes, "
                f"requested: {duration_minutes}"
            ),
        )


def validate_path(path: str, base_path: str = None) -> str:
    """
    Validate that a path is within the allowed base path and free of traversal attacks.
    """
    if base_path is None:
        base_path = get_settings().hpc_data_root

    if not base_path:
        raise ValueError("base_path must be provided or configured")

    clean_base = PurePosixPath(base_path)
    if not clean_base.is_absolute():
        raise ValueError("base_path must be absolute")

    normalized_base = _normalize_posix_path(clean_base)
    input_path = PurePosixPath(path)

    if input_path.is_absolute():
        candidate_path = input_path
    else:
        candidate_path = normalized_base / input_path

    normalized_path = _normalize_posix_path(candidate_path)

    if normalized_path != normalized_base and normalized_base not in normalized_path.parents:
        raise HTTPException(status_code=403, detail="Access denied: Path outside allowed directory")

    return str(normalized_path)


def _normalize_posix_path(path: PurePosixPath) -> PurePosixPath:
    """Normalize a POSIX path without filesystem access."""
    parts: list[str] = []
    for part in path.parts:
        if part in ("", ".", "/"):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return PurePosixPath("/", *parts)
