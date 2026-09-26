"""Server-side client for the external HPC-Link API."""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import requests

from exceptions import APIConnectionError, APITimeoutError, ValidationError

logger = logging.getLogger(__name__)
_service_tokens = {}
_service_token_lock = threading.Lock()


class HpcLinkClient:
    """Small, redaction-aware HTTP client for backend-to-backend HPC-Link calls."""

    def __init__(self, *, base_url: str, token: Optional[str] = None, timeout: float = 30.0):
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.token = str(token or "").strip()
        self.timeout = float(timeout or 30.0)
        if not self.base_url:
            raise ValidationError("HPC-Link base URL is not configured")

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        token = self._service_token() or self.token
        if token:
            if token.lower().startswith("bearer "):
                headers["Authorization"] = token
            elif token.count(".") == 2:
                headers["Authorization"] = f"Bearer {token}"
            else:
                # Older HPC-Link deployments document X-API-Key for service integrations.
                headers["X-API-Key"] = token
        return headers

    def _service_token(self) -> str:
        """Renew an invited service user's bearer token before it expires.

        Environment credentials are sent only to the operator-configured URL,
        never to an alternative endpoint entered in the admin interface.
        """
        username = os.environ.get("HPC_LINK_USERNAME", "")
        password = os.environ.get("HPC_LINK_PASSWORD", "")
        trusted_url = os.environ.get("HPC_LINK_BASE_URL", "").strip().rstrip("/")
        if not username or not password or self.base_url != trusted_url:
            return ""
        key = (self.base_url, username)
        with _service_token_lock:
            cached = _service_tokens.get(key)
            if cached and cached[1] > time.time() + 60:
                return cached[0]
            try:
                response = requests.post(
                    self._url("/api/auth/login"),
                    json={"username": username, "password": password},
                    timeout=self.timeout, allow_redirects=False,
                )
                if response.status_code != 200:
                    raise ValueError("Login rejected")
                payload = response.json()
                token = payload["access_token"]
                expires = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00")).timestamp()
                if not token or expires <= time.time() + 60:
                    raise ValueError("Invalid token lifetime")
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                raise APIConnectionError("HPC-Link service account authentication failed") from exc
            _service_tokens[key] = (token, expires)
            return token

    def _url(self, path: str) -> str:
        normalized = str(path or "").lstrip("/")
        return urljoin(f"{self.base_url}/", normalized)

    @staticmethod
    def _safe_error_text(response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:1000]
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if isinstance(detail, str):
            return detail
        return str(payload)[:1000]

    def request(self, method: str, path: str, *, json: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> Any:
        url = self._url(path)
        try:
            response = requests.request(
                method=str(method or "GET").upper(),
                url=url,
                headers=self._headers(),
                json=json,
                timeout=float(timeout or self.timeout),
            )
        except requests.Timeout as exc:
            raise APITimeoutError(f"HPC-Link request timed out: {path}") from exc
        except requests.RequestException as exc:
            raise APIConnectionError(f"HPC-Link request failed: {path}") from exc

        if response.status_code >= 400:
            raise APIConnectionError(
                f"HPC-Link returned HTTP {response.status_code}: {self._safe_error_text(response)}"
            )
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise APIConnectionError(f"HPC-Link returned non-JSON response for {path}") from exc

    def put_bytes(self, path: str, data: bytes, *, timeout: Optional[float] = None) -> Any:
        url = self._url(path)
        headers = {**self._headers(), "Content-Type": "application/octet-stream"}
        try:
            response = requests.put(
                url=url,
                headers=headers,
                data=data,
                timeout=float(timeout or self.timeout),
            )
        except requests.Timeout as exc:
            raise APITimeoutError(f"HPC-Link upload chunk timed out: {path}") from exc
        except requests.RequestException as exc:
            raise APIConnectionError(f"HPC-Link upload chunk failed: {path}") from exc

        if response.status_code >= 400:
            raise APIConnectionError(
                f"HPC-Link returned HTTP {response.status_code}: {self._safe_error_text(response)}"
            )
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise APIConnectionError(f"HPC-Link returned non-JSON response for {path}") from exc

    def upload_file(self, path: str, source_path: str, *, timeout: float = 7200) -> Any:
        """Stream a file without retaining its contents in application memory."""
        try:
            with open(source_path, "rb") as handle:
                response = requests.put(self._url(path), data=handle,
                    headers={**self._headers(), "Content-Type": "application/octet-stream"},
                    timeout=timeout, allow_redirects=False)
            if response.status_code != 200:
                raise APIConnectionError(f"HPC-Link upload returned HTTP {response.status_code}")
            return response.json()
        except requests.Timeout as exc:
            raise APITimeoutError("HPC-Link file upload timed out") from exc
        except (requests.RequestException, ValueError) as exc:
            raise APIConnectionError("HPC-Link file upload failed") from exc

    def download_to_file(self, path: str, destination_path: str, *, timeout: Optional[float] = None) -> int:
        url = self._url(path)
        os.makedirs(os.path.dirname(destination_path), exist_ok=True)
        try:
            with requests.get(
                url=url,
                headers=self._headers(),
                stream=True,
                timeout=float(timeout or self.timeout),
            ) as response:
                if response.status_code >= 400:
                    raise APIConnectionError(
                        f"HPC-Link returned HTTP {response.status_code}: {self._safe_error_text(response)}"
                    )
                bytes_written = 0
                with open(destination_path, "wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        bytes_written += len(chunk)
                return bytes_written
        except APIConnectionError:
            raise
        except requests.Timeout as exc:
            raise APITimeoutError(f"HPC-Link download timed out: {path}") from exc
        except requests.RequestException as exc:
            raise APIConnectionError(f"HPC-Link download failed: {path}") from exc

    def get(self, path: str, *, timeout: Optional[float] = None) -> Any:
        return self.request("GET", path, timeout=timeout)

    def post(self, path: str, payload: Optional[Dict[str, Any]] = None, *, timeout: Optional[float] = None) -> Any:
        return self.request("POST", path, json=payload or {}, timeout=timeout)

    def delete(self, path: str, *, timeout: Optional[float] = None) -> Any:
        return self.request("DELETE", path, timeout=timeout)
