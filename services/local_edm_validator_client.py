"""
Client for the local-edm-validator REST API.

The local validator is a WebHDP-tailored fork of METIS Sandbox. It keeps the
same record validation endpoint while adding a fast direct validation path and
full workflow reports.
"""
import io
import logging
import time
from typing import Any, Dict, Optional

import requests
from flask import current_app

logger = logging.getLogger(__name__)


class LocalEdmValidatorClientError(Exception):
    """Raised when the local EDM validator request cannot be completed."""


class LocalEdmValidatorClient:
    """Client for validating EDM RDF/XML records with local-edm-validator."""

    DEFAULT_BASE_URL = "http://localhost:18080"

    def __init__(self, base_url: Optional[str] = None):
        if base_url:
            self.base_url = base_url.rstrip("/")
        else:
            try:
                configured_url = current_app.config.get("LOCAL_EDM_VALIDATOR_URL")
                legacy_url = (
                    current_app.config.get("METIS_SANDBOX_URL")
                    or current_app.config.get("METIS_SANDBOX_API_URL")
                )
                if legacy_url and (
                    not configured_url
                    or str(configured_url).rstrip("/") == self.DEFAULT_BASE_URL
                ):
                    configured_url = legacy_url
                configured_url = configured_url or self.DEFAULT_BASE_URL
                self.base_url = str(configured_url).rstrip("/")
            except RuntimeError:
                self.base_url = self.DEFAULT_BASE_URL

        self.session = requests.Session()
        self.session.headers.update({"accept": "application/json"})

    def validate_record(
        self,
        xml_content: str,
        country: str = "Europe",
        language: str = "Multilingual Content",
        *,
        continue_on_error: Optional[bool] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Validate one EDM RDF/XML record.

        local-edm-validator expects a multipart file named ``recordToValidate``
        plus form fields for country, language, and continueOnError.
        """
        url = f"{self.base_url}/record/validation"
        try:
            if continue_on_error is None:
                continue_on_error = bool(
                    current_app.config.get("LOCAL_EDM_VALIDATOR_CONTINUE_ON_ERROR", True)
                )
            request_timeout = int(timeout or current_app.config.get("API_TIMEOUT", 60))
        except RuntimeError:
            continue_on_error = True if continue_on_error is None else continue_on_error
            request_timeout = int(timeout or 60)

        data = {
            "country": country,
            "language": language,
            "continueOnError": "true" if continue_on_error else "false",
        }
        files = {
            "recordToValidate": (
                "record.xml",
                io.BytesIO(xml_content.encode("utf-8")),
                "application/xml",
            )
        }

        try:
            response = self.session.post(url, data=data, files=files, timeout=request_timeout)
            if response.status_code == 429:
                raise LocalEdmValidatorClientError(
                    "Local EDM Validator rate limit exceeded. Please try again later."
                )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as exc:
            logger.error("Local EDM Validator HTTP error: %s", exc)
            try:
                error_data = response.json()
                message = error_data.get("message") or error_data.get("error") or str(exc)
            except Exception:
                message = response.text[:300] if "response" in locals() else str(exc)
            raise LocalEdmValidatorClientError(f"Local EDM Validator error: {message}") from exc
        except requests.exceptions.RequestException as exc:
            logger.error("Local EDM Validator request error: %s", exc)
            raise LocalEdmValidatorClientError(
                f"Failed to connect to Local EDM Validator: {exc}"
            ) from exc
        except ValueError as exc:
            logger.error("Local EDM Validator returned invalid JSON: %s", exc)
            raise LocalEdmValidatorClientError(
                f"Local EDM Validator returned invalid JSON: {exc}"
            ) from exc

    def check_health(self, timeout: float = 2.0) -> Dict[str, Any]:
        """Return reachability details for the local validator REST service."""
        url = f"{self.base_url}/actuator/health"
        started = time.monotonic()
        try:
            response = self.session.get(url, timeout=timeout)
            elapsed_ms = round((time.monotonic() - started) * 1000)
            payload: Dict[str, Any] = {}
            try:
                payload = response.json()
            except ValueError:
                payload = {"raw": response.text[:300]}
            status_text = str(payload.get("status") or "").upper()
            return {
                "ok": response.status_code == 200 and status_text in {"UP", "OK", "HEALTHY"},
                "status_code": response.status_code,
                "status": payload.get("status"),
                "url": url,
                "response_time_millis": elapsed_ms,
                "details": payload,
            }
        except requests.exceptions.RequestException as exc:
            return {
                "ok": False,
                "url": url,
                "message": str(exc),
            }

    def get_info(self, timeout: float = 2.0) -> Dict[str, Any]:
        """Return build/source metadata exposed by the validator Actuator info endpoint."""
        url = f"{self.base_url}/actuator/info"
        started = time.monotonic()
        try:
            response = self.session.get(url, timeout=timeout)
            elapsed_ms = round((time.monotonic() - started) * 1000)
            payload: Dict[str, Any] = {}
            try:
                payload = response.json()
            except ValueError:
                payload = {"raw": response.text[:300]}

            return {
                "ok": response.status_code == 200,
                "status_code": response.status_code,
                "url": url,
                "response_time_millis": elapsed_ms,
                "details": payload,
                "summary": self._summarize_info(payload),
            }
        except requests.exceptions.RequestException as exc:
            return {
                "ok": False,
                "url": url,
                "message": str(exc),
                "summary": {},
            }

    @staticmethod
    def _summarize_info(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize common Spring Boot Actuator info fields for WebHDP UI/API use."""
        app = payload.get("app") if isinstance(payload.get("app"), dict) else {}
        build = payload.get("build") if isinstance(payload.get("build"), dict) else {}
        git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
        commit = git.get("commit") if isinstance(git.get("commit"), dict) else {}
        source = app.get("source") if isinstance(app.get("source"), dict) else {}
        image = app.get("image") if isinstance(app.get("image"), dict) else {}

        commit_id = commit.get("id") or git.get("commit.id") or source.get("ref")
        short_commit = (
            commit.get("id.abbrev")
            or git.get("commit.id.abbrev")
            or (str(commit_id)[:12] if commit_id else None)
        )

        return {
            "title": app.get("title") or build.get("artifact"),
            "description": app.get("description"),
            "version": app.get("version") or build.get("version"),
            "repository": app.get("repository") or source.get("repository"),
            "source_ref": source.get("ref"),
            "image_tag": app.get("image-tag") or app.get("imageTag") or image.get("tag"),
            "build_time": build.get("time"),
            "git_branch": git.get("branch"),
            "git_commit": commit_id,
            "git_commit_short": short_commit,
            "git_commit_time": commit.get("time") or git.get("commit.time"),
        }
