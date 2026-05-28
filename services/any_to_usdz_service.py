import logging
import os
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


class AnyToUsdzService:
    """Service for interacting with the Any-to-USDZ converter container."""

    def __init__(self, service_url: str):
        self.service_url = service_url.rstrip("/")
        self.host_shared_path = os.environ.get("HOST_SHARED_PATH")
        self.container_mount_point = "/shared/sessions"

    def _translate_to_container_path(self, local_path: str) -> str:
        if self.host_shared_path and isinstance(local_path, str) and local_path.startswith(self.host_shared_path):
            rel_path = os.path.relpath(local_path, self.host_shared_path)
            return os.path.join(self.container_mount_point, rel_path)
        return local_path

    @staticmethod
    def _extract_error_message(payload: Dict[str, Any], default: str) -> str:
        if not isinstance(payload, dict):
            return default
        if isinstance(payload.get("error"), str):
            return payload["error"]
        error_obj = payload.get("error")
        if isinstance(error_obj, dict):
            return error_obj.get("message") or default
        return payload.get("message") or default

    def convert(self, input_path: str, output_dir: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {
            "input_path": self._translate_to_container_path(input_path),
            "output_dir": self._translate_to_container_path(output_dir),
        }
        if options:
            payload.update(options)

        try:
            logger.info("Calling Any-to-USDZ converter at %s/convert", self.service_url)
            response = requests.post(f"{self.service_url}/convert", json=payload, timeout=900)
            content_type = response.headers.get("Content-Type", "")
            response_payload: Dict[str, Any]
            if "application/json" in content_type:
                response_payload = response.json()
            else:
                response_payload = {"success": False, "error": response.text}

            if response.ok:
                return response_payload

            return {
                "success": False,
                "error": self._extract_error_message(response_payload, "Converter request failed"),
                "status_code": response.status_code,
                "details": response_payload.get("details", response_payload),
                "error_code": response_payload.get("error_code"),
            }
        except requests.exceptions.Timeout:
            logger.error("Any-to-USDZ conversion timed out")
            return {
                "success": False,
                "error": "Any-to-USDZ conversion timed out",
                "error_code": "CONVERTER_TIMEOUT",
                "status": "failed",
            }
        except requests.exceptions.RequestException as exc:
            logger.error("Any-to-USDZ request failed: %s", exc)
            return {
                "success": False,
                "error": str(exc),
                "error_code": "CONVERTER_REQUEST_FAILED",
                "status": "failed",
            }

    def check_health(self) -> bool:
        try:
            response = requests.get(f"{self.service_url}/health", timeout=3)
            return response.status_code == 200
        except Exception:
            return False
