"""Schemas for authentication and user administration."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class UserProfile(BaseModel):
    username: str
    is_admin: bool
    invited: bool
    is_active: bool
    allowed_partitions: list[str]
    allowed_gpu_types: list[str]
    max_duration_minutes: int
    max_gpu_count: int
    last_login: str | None = None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserProfile


class InviteUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    allowed_partitions: list[str] = Field(default_factory=list, min_length=1)
    allowed_gpu_types: list[str] = Field(default_factory=list)
    max_duration_minutes: int = Field(default=30, ge=1, le=24 * 7 * 60)
    max_gpu_count: int = Field(default=1, ge=1, le=16)
    is_active: bool = True


class UpdateUserPolicyRequest(BaseModel):
    allowed_partitions: list[str] | None = None
    allowed_gpu_types: list[str] | None = None
    max_duration_minutes: int | None = Field(default=None, ge=1, le=24 * 7 * 60)
    max_gpu_count: int | None = Field(default=None, ge=1, le=16)
    is_active: bool | None = None


class ResetUserPasswordRequest(BaseModel):
    password: str = Field(min_length=8, max_length=256)
