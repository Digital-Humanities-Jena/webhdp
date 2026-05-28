"""Authentication endpoints."""
from __future__ import annotations

import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.auth_tokens import issue_access_token
from app.config import get_settings
from app.limiter import limiter
from app.schemas.auth import LoginRequest, LoginResponse, UserProfile
from app.security import (
    SERVICE_PRINCIPAL_ID,
    auth_store,
    get_api_key,
    get_request_user,
)

router = APIRouter(prefix="/auth", tags=["Auth"])

_login_guard_lock = threading.Lock()
_login_attempts: dict[str, list[float]] = {}
_login_lockouts: dict[str, float] = {}


def _to_user_profile(username: str) -> UserProfile:
    user = auth_store.get_user_by_username(username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    return UserProfile(
        username=user.username,
        is_admin=user.is_admin,
        invited=user.invited,
        is_active=user.is_active,
        allowed_partitions=user.allowed_partitions,
        allowed_gpu_types=user.allowed_gpu_types,
        max_duration_minutes=user.max_duration_minutes,
        max_gpu_count=user.max_gpu_count,
        last_login=user.last_login,
    )


def _login_guard_keys(request: Request, username: str) -> tuple[str, str]:
    remote_ip = request.client.host if request.client and request.client.host else "unknown"
    normalized_username = username.strip().lower()
    return (f"ip:{remote_ip}", f"user:{normalized_username}")


def _prune_login_state(now: float, settings) -> None:
    active_window = float(settings.login_attempt_window_seconds)
    for key, attempts in list(_login_attempts.items()):
        kept = [ts for ts in attempts if now - ts <= active_window]
        if kept:
            _login_attempts[key] = kept
        else:
            _login_attempts.pop(key, None)
    for key, locked_until in list(_login_lockouts.items()):
        if locked_until <= now:
            _login_lockouts.pop(key, None)


def _enforce_login_guard(request: Request, username: str) -> None:
    settings = get_settings()
    now = time.monotonic()
    keys = _login_guard_keys(request, username)
    with _login_guard_lock:
        _prune_login_state(now, settings)
        active_locks = [
            _login_lockouts[key]
            for key in keys
            if key in _login_lockouts and _login_lockouts[key] > now
        ]
    if active_locks:
        retry_after = int(max(active_locks) - now) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again later.",
            headers={"Retry-After": str(max(1, retry_after))},
        )


def _record_login_failure(request: Request, username: str) -> None:
    settings = get_settings()
    now = time.monotonic()
    keys = _login_guard_keys(request, username)
    max_attempts = max(1, int(settings.login_max_attempts_per_window))
    lockout_seconds = max(1, int(settings.login_lockout_seconds))
    with _login_guard_lock:
        _prune_login_state(now, settings)
        for key in keys:
            attempts = _login_attempts.get(key, [])
            attempts.append(now)
            _login_attempts[key] = attempts
            if len(attempts) >= max_attempts:
                _login_lockouts[key] = now + lockout_seconds
                _login_attempts.pop(key, None)


def _clear_login_guard_state(request: Request, username: str) -> None:
    keys = _login_guard_keys(request, username)
    with _login_guard_lock:
        for key in keys:
            _login_attempts.pop(key, None)
            _login_lockouts.pop(key, None)


@router.post("/login", response_model=LoginResponse)
@limiter.limit("20/minute")
async def login(request: Request, payload: LoginRequest):
    """Authenticate user and issue bearer token."""
    _enforce_login_guard(request, payload.username)

    user = auth_store.authenticate(payload.username, payload.password)
    if user is None:
        _record_login_failure(request, payload.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username/password or account is not active/invited",
        )

    _clear_login_guard_state(request, payload.username)
    settings = get_settings()
    token, expires_at = issue_access_token(user, settings.auth_token_secret, settings.auth_token_ttl_minutes)

    return LoginResponse(
        access_token=token,
        expires_at=expires_at,
        user=UserProfile(
            username=user.username,
            is_admin=user.is_admin,
            invited=user.invited,
            is_active=user.is_active,
            allowed_partitions=user.allowed_partitions,
            allowed_gpu_types=user.allowed_gpu_types,
            max_duration_minutes=user.max_duration_minutes,
            max_gpu_count=user.max_gpu_count,
            last_login=user.last_login,
        ),
    )


@router.get("/me", response_model=UserProfile, dependencies=[Depends(get_api_key)])
async def me(request: Request):
    """Return profile of the authenticated user."""
    user = get_request_user(request)
    if user.user_id == SERVICE_PRINCIPAL_ID:
        return UserProfile(
            username=user.username,
            is_admin=user.is_admin,
            invited=user.invited,
            is_active=user.is_active,
            allowed_partitions=user.allowed_partitions,
            allowed_gpu_types=user.allowed_gpu_types,
            max_duration_minutes=user.max_duration_minutes,
            max_gpu_count=user.max_gpu_count,
            last_login=user.last_login,
        )
    return _to_user_profile(user.username)
