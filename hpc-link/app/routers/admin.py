"""Administrator endpoints for invite-only user management."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request

from app.schemas.auth import (
    InviteUserRequest,
    ResetUserPasswordRequest,
    UpdateUserPolicyRequest,
    UserProfile,
)
from app.security import auth_store, get_api_key, get_request_user, require_admin_user

router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(get_api_key)])


def _to_profile(username: str) -> UserProfile:
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


@router.get("/users", response_model=list[UserProfile])
async def list_users(request: Request):
    """List all users and their allocation policies."""
    require_admin_user(get_request_user(request))

    users = auth_store.list_users()
    return [
        UserProfile(
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
        for user in users
    ]


@router.post("/users", response_model=UserProfile, status_code=201)
async def invite_user(request: Request, payload: InviteUserRequest):
    """Invite a new user with explicit node/time limits."""
    require_admin_user(get_request_user(request))

    try:
        created = auth_store.create_invited_user(
            username=payload.username,
            password=payload.password,
            allowed_partitions=payload.allowed_partitions,
            allowed_gpu_types=payload.allowed_gpu_types,
            max_duration_minutes=payload.max_duration_minutes,
            max_gpu_count=payload.max_gpu_count,
            is_active=payload.is_active,
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="User already exists") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return UserProfile(
        username=created.username,
        is_admin=created.is_admin,
        invited=created.invited,
        is_active=created.is_active,
        allowed_partitions=created.allowed_partitions,
        allowed_gpu_types=created.allowed_gpu_types,
        max_duration_minutes=created.max_duration_minutes,
        max_gpu_count=created.max_gpu_count,
        last_login=created.last_login,
    )


@router.patch("/users/{username}", response_model=UserProfile)
async def update_user_policy(request: Request, username: str, payload: UpdateUserPolicyRequest):
    """Update one user's policy and account status."""
    require_admin_user(get_request_user(request))

    try:
        updated = auth_store.update_user_policy(
            username=username,
            allowed_partitions=payload.allowed_partitions,
            allowed_gpu_types=payload.allowed_gpu_types,
            max_duration_minutes=payload.max_duration_minutes,
            max_gpu_count=payload.max_gpu_count,
            is_active=payload.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")

    return _to_profile(updated.username)


@router.post("/users/{username}/password", response_model=UserProfile)
async def reset_user_password(request: Request, username: str, payload: ResetUserPasswordRequest):
    """Reset password for one user account."""
    require_admin_user(get_request_user(request))

    try:
        updated = auth_store.set_user_password(username=username, password=payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")

    return _to_profile(updated.username)
