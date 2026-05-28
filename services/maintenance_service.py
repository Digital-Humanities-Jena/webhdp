"""Maintenance-mode helpers used by deployment scripts and middleware."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def maintenance_flag_path(root: str | Path | None = None) -> Path:
    configured = os.environ.get("MAINTENANCE_FLAG_PATH")
    if configured:
        path = Path(configured)
    else:
        path = Path(root or os.getcwd()) / "instance" / "maintenance.json"
    if not path.is_absolute():
        path = Path(root or os.getcwd()).resolve() / path
    return path.resolve()


def enable_maintenance(reason: str = "maintenance", root: str | Path | None = None) -> dict[str, Any]:
    path = maintenance_flag_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "enabled": True,
        "reason": reason,
        "enabled_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {**payload, "path": str(path)}


def disable_maintenance(root: str | Path | None = None) -> dict[str, Any]:
    path = maintenance_flag_path(root)
    path.unlink(missing_ok=True)
    return {"enabled": False, "path": str(path)}


def maintenance_status(root: str | Path | None = None) -> dict[str, Any]:
    env_enabled = _truthy(os.environ.get("MAINTENANCE_MODE"))
    path = maintenance_flag_path(root)
    file_payload: dict[str, Any] = {}
    if path.exists():
        try:
            file_payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            file_payload = {"enabled": True, "reason": "invalid maintenance flag json"}
    enabled = env_enabled or bool(file_payload.get("enabled") or path.exists())
    return {
        "enabled": enabled,
        "env_enabled": env_enabled,
        "flag_path": str(path),
        "reason": file_payload.get("reason") or ("environment" if env_enabled else None),
        "enabled_at": file_payload.get("enabled_at"),
    }
