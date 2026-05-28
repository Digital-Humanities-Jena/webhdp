"""HMAC-signed bearer tokens for API authentication."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.auth_store import AuthenticatedUser


class TokenError(ValueError):
    """Raised when a token cannot be validated."""


def issue_access_token(user: AuthenticatedUser, secret: str, ttl_minutes: int) -> tuple[str, datetime]:
    """Create a signed access token for one user."""
    if not secret:
        raise TokenError("token secret is not configured")
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=ttl_minutes)

    payload = {
        "sub": user.user_id,
        "usr": user.username,
        "adm": bool(user.is_admin),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    encoded = _encode_payload(payload, secret)
    return encoded, expires_at


def parse_access_token(token: str, secret: str) -> dict[str, Any]:
    """Validate a token and return its payload."""
    if not secret:
        raise TokenError("token secret is not configured")

    try:
        header_b64, payload_b64, signature_b64 = token.split(".", maxsplit=2)
    except ValueError as exc:
        raise TokenError("token format is invalid") from exc

    signed = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_sig = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).digest()
    given_sig = _b64url_decode(signature_b64)

    if not hmac.compare_digest(expected_sig, given_sig):
        raise TokenError("token signature is invalid")

    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception as exc:
        raise TokenError("token payload is invalid") from exc

    exp = payload.get("exp")
    if not isinstance(exp, int):
        raise TokenError("token expiry claim is invalid")

    now_ts = int(datetime.now(timezone.utc).timestamp())
    if now_ts >= exp:
        raise TokenError("token has expired")

    return payload


def _encode_payload(payload: dict[str, Any], secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signed = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).digest()
    signature_b64 = _b64url_encode(signature)
    return f"{header_b64}.{payload_b64}.{signature_b64}"


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(raw + padding)
