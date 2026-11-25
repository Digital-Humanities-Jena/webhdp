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
from flask import current_app, has_app_context

logger = logging.getLogger(__name__)

VALIDATOR_IDENTITY_FIELDS = {
    "edm_schema_version": "edmSchemaVersion",
    "metis_schema_version": "metisSchemaVersion",
    "source_ref": "sourceRef",
    "build_version": "buildVersion",
}


def expected_validator_identity(config):
    return {
        field: value
        for field in ("edm_schema_version", "metis_schema_version", "source_ref")
        if (value := str(config.get(f"LOCAL_EDM_VALIDATOR_EXPECTED_{field.upper()}") or "").strip())
    }


def normalize_validator_identity(payload):
    if not isinstance(payload, dict):
        return {}
    return {
        field: str(value).strip()
        for field, response_key in VALIDATOR_IDENTITY_FIELDS.items()
        if isinstance(value := payload.get(response_key), (str, int))
        and not isinstance(value, bool) and str(value).strip()
    }


def validator_identity_mismatches(expected, actual, *, allow_short_source_ref=False):
    actual = actual if isinstance(actual, dict) else {}
    mismatches = []
    for field, version in expected.items():
        reported = actual.get(field)
        if reported == version:
            continue
        if (field == "source_ref" and allow_short_source_ref and isinstance(reported, str)
                and len(reported) >= 7 and version.startswith(reported)):
            continue
        mismatches.append(f"{field} expected {version}, reported {reported or 'missing'}")
    return mismatches


class LocalEdmValidatorClientError(Exception):
    """Raised when the local EDM validator request cannot be completed."""

    def __init__(self, message, *, remote_status="unavailable"):
        super().__init__(message)
        self.remote_status = remote_status


class LocalEdmValidatorClient:
    """Client for validating EDM RDF/XML records with local-edm-validator."""

    DEFAULT_BASE_URL = "http://localhost:18080"

    def __init__(self, base_url: Optional[str] = None, *, config=None):
        if base_url:
            self.base_url = base_url.rstrip("/")
        else:
            if config is None:
                config = current_app.config if has_app_context() else {}
            configured_url = config.get("LOCAL_EDM_VALIDATOR_URL")
            legacy_url = config.get("METIS_SANDBOX_URL") or config.get("METIS_SANDBOX_API_URL")
            if legacy_url and (
                not configured_url or str(configured_url).rstrip("/") == self.DEFAULT_BASE_URL
            ):
                configured_url = legacy_url
            self.base_url = str(configured_url or self.DEFAULT_BASE_URL).rstrip("/")

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
                    "Local EDM Validator rate limit exceeded. Please try again later.",
                    remote_status="rate_limited",
                )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as exc:
            logger.error("Local EDM Validator HTTP error: %s", exc)
            try:
                error_data = exc.response.json()
                message = error_data.get("message") or error_data.get("error") or str(exc)
            except Exception:
                message = exc.response.text[:300] if exc.response is not None else str(exc)
            raise LocalEdmValidatorClientError(
                f"Local EDM Validator error: {message}",
                remote_status=exc.response.status_code if exc.response is not None else "unavailable",
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise LocalEdmValidatorClientError(
                f"Local EDM Validator timed out: {exc}", remote_status="timeout",
            ) from exc
        except requests.exceptions.JSONDecodeError as exc:
            raise LocalEdmValidatorClientError(
                f"Local EDM Validator returned invalid JSON: {exc}", remote_status="invalid_response",
            ) from exc
        except requests.exceptions.RequestException as exc:
            logger.error("Local EDM Validator request error: %s", exc)
            raise LocalEdmValidatorClientError(
                f"Failed to connect to Local EDM Validator: {exc}", remote_status="connection_failed",
            ) from exc
        except ValueError as exc:
            logger.error("Local EDM Validator returned invalid JSON: %s", exc)
            raise LocalEdmValidatorClientError(
                f"Local EDM Validator returned invalid JSON: {exc}", remote_status="invalid_response",
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
            if not isinstance(payload, dict):
                payload = {}
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
            if not isinstance(payload, dict):
                payload = {}

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

        summary = {
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
        if edm_schema_version := app.get("edm-schema-version"):
            summary["edm_schema_version"] = str(edm_schema_version)
        if metis_schema_version := build.get("metis-schema-version"):
            summary["metis_schema_version"] = str(metis_schema_version)
        return summary
