import json
import os
from datetime import datetime
from typing import Any, Dict

from database.database import db
from database.models import SystemConfig
from services.api_activity_service import list_api_activity, summarize_api_activity
from services.cloud_storage_service import CloudStorageService
from services.fast_renderer_service import FastRendererService


class AdminObservabilityService:
    CHECK_RESULTS_KEY = "admin_observability_check_results"

    @classmethod
    def _load_check_results(cls) -> Dict[str, Any]:
        entry = db.session.get(SystemConfig, cls.CHECK_RESULTS_KEY)
        if not entry or not entry.value:
            return {}
        try:
            payload = json.loads(entry.value)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @classmethod
    def _save_check_results(cls, payload: Dict[str, Any]) -> None:
        entry = db.session.get(SystemConfig, cls.CHECK_RESULTS_KEY)
        serialized = json.dumps(payload)
        if entry is None:
            entry = SystemConfig(key=cls.CHECK_RESULTS_KEY, value=serialized)
            db.session.add(entry)
        else:
            entry.value = serialized
        db.session.commit()

    @staticmethod
    def _mask_secret(value: str | None) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        if len(text) <= 8:
            return "*" * len(text)
        return f"{text[:4]}…{text[-4:]}"

    @staticmethod
    def _path_status(path_value: str | None) -> Dict[str, Any]:
        text = str(path_value or "").strip()
        if not text:
            return {"configured": False, "path": None, "exists": False}
        return {
            "configured": True,
            "path": text,
            "exists": os.path.exists(text),
        }

    @classmethod
    def get_credentials_status(cls) -> Dict[str, Any]:
        check_results = cls._load_check_results()
        google_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        dropbox_refresh = os.environ.get("DROPBOX_REFRESH_TOKEN")
        zenodo_sandbox = os.environ.get("ZENODO_SANDBOX_API_KEY")
        zenodo_prod = os.environ.get("ZENODO_API_KEY")

        return {
            "integrations": [
                {
                    "id": "zenodo_sandbox",
                    "label": "Zenodo Sandbox",
                    "configured": bool(str(zenodo_sandbox or "").strip()),
                    "masked_value": cls._mask_secret(zenodo_sandbox),
                    "details": {
                        "base_url": "https://sandbox.zenodo.org/api",
                    },
                    "last_check": check_results.get("zenodo_sandbox"),
                },
                {
                    "id": "zenodo_production",
                    "label": "Zenodo Production",
                    "configured": bool(str(zenodo_prod or "").strip()),
                    "masked_value": cls._mask_secret(zenodo_prod),
                    "details": {
                        "base_url": "https://zenodo.org/api",
                    },
                    "last_check": check_results.get("zenodo_production"),
                },
                {
                    "id": "google_drive",
                    "label": "Google Drive",
                    "configured": bool(str(google_path or "").strip()),
                    "masked_value": cls._mask_secret(google_path),
                    "details": cls._path_status(google_path),
                    "last_check": check_results.get("google_drive"),
                },
                {
                    "id": "dropbox",
                    "label": "Dropbox",
                    "configured": bool(str(dropbox_refresh or "").strip()),
                    "masked_value": cls._mask_secret(dropbox_refresh),
                    "details": {
                        "refresh_token_present": bool(str(dropbox_refresh or "").strip()),
                    },
                    "last_check": check_results.get("dropbox"),
                },
            ]
        }

    @staticmethod
    def get_api_activity(
        *,
        route_family: str | None = None,
        service: str | None = None,
        status_class: str | None = None,
        hours: int | None = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        entries = list_api_activity(
            route_family=route_family,
            service=service,
            status_class=status_class,
            hours=hours,
            limit=limit,
        )
        return {
            "entries": entries,
            "summary": summarize_api_activity(entries),
            "filters": {
                "route_family": route_family,
                "service": service,
                "status_class": status_class,
                "hours": hours,
                "limit": limit,
            },
        }

    @classmethod
    def run_check(cls, check_id: str, *, app=None) -> Dict[str, Any]:
        normalized = str(check_id or "").strip().lower()
        result: Dict[str, Any]
        if normalized == "zenodo_sandbox":
            from routes.setup_routes import _check_zenodo_connectivity

            status = _check_zenodo_connectivity(os.environ.get("ZENODO_SANDBOX_API_KEY"), sandbox=True)
            result = {"status": status, "ok": status == "Reachable"}
        elif normalized == "zenodo_production":
            from routes.setup_routes import _check_zenodo_connectivity

            status = _check_zenodo_connectivity(os.environ.get("ZENODO_API_KEY"), sandbox=False)
            result = {"status": status, "ok": status == "Reachable"}
        elif normalized == "google_drive":
            result = CloudStorageService.test_gdrive_connection()
            result = {"status": result.get("message"), "ok": bool(result.get("success")), "details": result.get("details", {})}
        elif normalized == "dropbox":
            result = CloudStorageService.test_dropbox_connection()
            result = {"status": result.get("message"), "ok": bool(result.get("success")), "details": result.get("details", {})}
        elif normalized == "renderer":
            renderer = app.fast_renderer_service if app is not None else FastRendererService(os.environ.get("FAST_RENDERER_URL", "http://localhost:5005"))
            ok = bool(renderer.check_health())
            result = {"status": "Reachable" if ok else "Unavailable", "ok": ok}
        else:
            raise ValueError("Unsupported check_id")

        stored = cls._load_check_results()
        stored[normalized] = {
            **result,
            "checked_at": datetime.utcnow().isoformat(),
        }
        cls._save_check_results(stored)
        return stored[normalized]
