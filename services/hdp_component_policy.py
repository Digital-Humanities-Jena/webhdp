"""Execution policy for computationally heavy HDP components."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

HPC_REQUIRED_COMPONENTS = {"fast_renderer", "any_to_usdz"}
HPC_ONLY_COMPONENTS: set[str] = set()
HPC_REQUIRED_COMPONENT_LABELS = {
    "fast_renderer": "Fast Renderer",
    "any_to_usdz": "USDZ Converter",
    "gltf_validator": "glTF/GLB Validator",
}
COMPONENT_FEATURE_FLAGS = {
    "fast_renderer": "ENABLE_RENDERER",
    "any_to_usdz": "ENABLE_USDZ_CONVERSION",
}
DEPLOYMENT_CLASS_WORKSTATION_LOCAL = "workstation-local"
DEPLOYMENT_CLASS_SERVER = "server"
DEPLOYMENT_CLASS_HPC = "hpc"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_MANIFEST_RUNTIME_KEYS = (
    ("runtime_policy", "class"),
    ("runtime_policy", "runtime_class"),
    ("runtime_policy", "execution_class"),
    ("execution", "runtime_policy", "class"),
    ("execution", "runtime_policy", "runtime_class"),
    ("compatibility", "runtime_policy", "class"),
)


def _env_bool(name: str, default: bool = False) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}


def webhdp_deployment_mode() -> str:
    return str(os.environ.get("WEBHDP_DEPLOYMENT_MODE", "server") or "server").strip().lower()


def _deployment_mode_from_app(app: Any = None) -> str:
    mode = webhdp_deployment_mode()
    if app is not None:
        mode = str(app.config.get("WEBHDP_DEPLOYMENT_MODE", mode) or mode).strip().lower()
    return mode


def _allow_local_from_app(app: Any = None) -> bool:
    allow_local = _env_bool("WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS", False)
    if app is not None:
        allow_local = bool(app.config.get("WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS", allow_local))
    return allow_local


def webhdp_deployment_class(app: Any = None) -> str:
    mode = _deployment_mode_from_app(app)
    allow_local = _allow_local_from_app(app)
    if mode in {"hpc", "cluster"}:
        return DEPLOYMENT_CLASS_HPC
    if mode in {"local", "workstation", DEPLOYMENT_CLASS_WORKSTATION_LOCAL} and allow_local:
        return DEPLOYMENT_CLASS_WORKSTATION_LOCAL
    return DEPLOYMENT_CLASS_SERVER


def webhdp_deployment_label(app: Any = None) -> str:
    deployment_class = webhdp_deployment_class(app)
    if deployment_class == DEPLOYMENT_CLASS_WORKSTATION_LOCAL:
        return "Local workstation"
    if deployment_class == DEPLOYMENT_CLASS_HPC:
        return "HPC"
    return "Server/VPS"


def local_hdp_component_execution_allowed(app: Any = None) -> bool:
    return webhdp_deployment_class(app) == DEPLOYMENT_CLASS_WORKSTATION_LOCAL


def _nested_value(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _runtime_class_from_manifest(manifest: dict[str, Any]) -> str:
    for path in _MANIFEST_RUNTIME_KEYS:
        value = _nested_value(manifest, path)
        if value not in (None, ""):
            return str(value).strip().lower().replace("-", "_")
    return ""


@lru_cache(maxsize=128)
def component_manifest(component_key: str) -> dict[str, Any]:
    key = str(component_key or "").strip()
    if not key:
        return {}
    path = _REPO_ROOT / "external_code" / key / "component.yaml"
    if not path.is_file():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _manifest_execution_profiles(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    profiles = (manifest.get("execution") or {}).get("profiles") if isinstance(manifest.get("execution"), dict) else None
    if not isinstance(profiles, list):
        return []
    return [profile for profile in profiles if isinstance(profile, dict)]


def component_runtime_traits(component_key: Any) -> dict[str, Any]:
    """Return runtime traits from built-in policy plus component manifests.

    Manifests may explicitly declare a runtime class via ``runtime_policy`` or
    imply HPC-only execution by shipping only ``adapter: hpc_link`` profiles.
    """

    key = str(component_key or "").strip()
    manifest = component_manifest(key)
    metadata = manifest.get("metadata") if isinstance(manifest.get("metadata"), dict) else {}
    label = str(metadata.get("label") or HPC_REQUIRED_COMPONENT_LABELS.get(key) or key or "HDP component").strip()
    runtime_class = _runtime_class_from_manifest(manifest)
    profiles = _manifest_execution_profiles(manifest)
    adapters = {str(profile.get("adapter") or "").strip().lower() for profile in profiles if profile.get("adapter")}
    has_hpc_profile = "hpc_link" in adapters
    has_non_hpc_profile = bool(adapters - {"hpc_link"})
    hpc_install = manifest.get("hpc") if isinstance(manifest.get("hpc"), dict) else {}
    hpc_install_block = hpc_install.get("install") if isinstance(hpc_install.get("install"), dict) else {}
    sif_required = bool(hpc_install_block.get("sif_required"))

    hpc_only = key in HPC_ONLY_COMPONENTS
    requires_compute_runtime = key in HPC_REQUIRED_COMPONENTS

    if runtime_class in {"hpc_only", "hpc"}:
        hpc_only = True
        requires_compute_runtime = True
    elif runtime_class in {"hpc_required", "remote_required", "compute_heavy"}:
        requires_compute_runtime = True
    elif runtime_class in {"local_capable", "local_allowed", "workstation_local", "workstation"}:
        requires_compute_runtime = False

    if profiles and has_hpc_profile and not has_non_hpc_profile:
        hpc_only = True
        requires_compute_runtime = True
    elif has_hpc_profile:
        requires_compute_runtime = True
    if sif_required and not has_non_hpc_profile:
        hpc_only = True
        requires_compute_runtime = True

    return {
        "component_key": key,
        "label": label,
        "runtime_class": runtime_class,
        "requires_compute_runtime": requires_compute_runtime,
        "hpc_only": hpc_only,
        "manifest_available": bool(manifest),
        "adapters": sorted(adapters),
    }


def hpc_required_component(component_key: Any) -> bool:
    return bool(component_runtime_traits(component_key)["requires_compute_runtime"])


def hpc_only_component(component_key: Any) -> bool:
    return bool(component_runtime_traits(component_key)["hpc_only"])


def hpc_required_component_label(component_key: Any) -> str:
    key = str(component_key or "").strip()
    return component_runtime_traits(key)["label"]


def default_component_runtime_keys() -> list[str]:
    keys = set(HPC_REQUIRED_COMPONENTS) | set(HPC_ONLY_COMPONENTS)
    external_root = _REPO_ROOT / "external_code"
    if external_root.is_dir():
        for manifest_path in external_root.glob("*/component.yaml"):
            key = manifest_path.parent.name
            traits = component_runtime_traits(key)
            if traits["requires_compute_runtime"] or traits["hpc_only"]:
                keys.add(key)
    return sorted(keys)


def hpc_required_message(component_key: Any | None = None) -> str:
    if component_key:
        label = hpc_required_component_label(component_key)
        return f"{label} must run through an active HPC-Link allocation on this WebHDP deployment."
    return "Renderer and USDZ conversion must run through an active HPC-Link allocation on this WebHDP deployment."


def _component_enabled(component_key: Any, app: Any = None) -> bool:
    key = str(component_key or "").strip()
    flag = COMPONENT_FEATURE_FLAGS.get(key)
    if not flag:
        return True
    default = True
    if app is not None and flag in app.config:
        return bool(app.config.get(flag))
    return _env_bool(flag, default)


def _component_local_health(component_key: Any, app: Any = None) -> bool:
    key = str(component_key or "").strip()
    if app is None:
        return False
    try:
        if key == "fast_renderer":
            return bool(app.fast_renderer_service.check_health())
        if key == "any_to_usdz":
            return bool(app.any_to_usdz_service.check_health())
    except Exception:
        return False
    return True


def component_runtime_status(
    component_key: Any,
    app: Any = None,
    *,
    active_hpc_allocation: bool = False,
    hpc_link_available: bool = False,
    can_allocate_hpc: bool = False,
    hpc_only: bool | None = None,
) -> dict[str, Any]:
    key = str(component_key or "").strip()
    label = hpc_required_component_label(key)
    deployment_class = webhdp_deployment_class(app)
    local_allowed = local_hdp_component_execution_allowed(app)
    enabled = _component_enabled(key, app)
    local_healthy = _component_local_health(key, app) if local_allowed and enabled else False
    requires_compute_runtime = hpc_required_component(key)
    is_hpc_only = hpc_only_component(key) if hpc_only is None else bool(hpc_only)

    if not enabled:
        status = "disabled"
        message = f"{label} is disabled by configuration."
    elif is_hpc_only and active_hpc_allocation:
        status = "hpc_only"
        message = f"{label} will run through the active HPC-Link allocation."
    elif is_hpc_only:
        status = "hpc_only"
        message = f"{label} is HPC-only and requires an active HPC-Link allocation."
    elif local_allowed and local_healthy:
        status = "local_allowed"
        message = f"{label} will run through local workstation execution."
    elif active_hpc_allocation:
        status = "hpc_required"
        message = f"{label} will run through the active HPC-Link allocation."
    elif local_allowed:
        status = "unavailable"
        message = f"{label} is configured for local workstation execution, but its local service is not reachable."
    elif requires_compute_runtime:
        status = "hpc_required"
        message = hpc_required_message(key)
    else:
        status = "local_allowed"
        message = f"{label} can run on this WebHDP instance."

    return {
        "component_key": key,
        "label": label,
        "status": status,
        "enabled": enabled,
        "deployment_class": deployment_class,
        "deployment_label": webhdp_deployment_label(app),
        "local_execution_allowed": local_allowed,
        "local_healthy": local_healthy,
        "hpc_required": status in {"hpc_required", "hpc_only"},
        "hpc_only": is_hpc_only,
        "hpc_link_available": bool(hpc_link_available),
        "can_allocate_hpc": bool(can_allocate_hpc),
        "active_hpc_allocation": bool(active_hpc_allocation),
        "allocation_required": bool(status in {"hpc_required", "hpc_only"} and not active_hpc_allocation),
        "message": message,
    }


def component_runtime_report(
    app: Any = None,
    *,
    component_keys: list[str] | None = None,
    active_hpc_allocation: bool = False,
    hpc_link_available: bool = False,
    can_allocate_hpc: bool = False,
    hpc_only_component_keys: set[str] | None = None,
) -> dict[str, Any]:
    keys = component_keys or default_component_runtime_keys()
    hpc_only_keys = hpc_only_component_keys or set()
    return {
        key: component_runtime_status(
            key,
            app,
            active_hpc_allocation=active_hpc_allocation,
            hpc_link_available=hpc_link_available,
            can_allocate_hpc=can_allocate_hpc,
            hpc_only=(key in hpc_only_keys) if hpc_only_component_keys is not None else None,
        )
        for key in keys
    }
