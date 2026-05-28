"""Mode-aware administrator setup guidance."""

from __future__ import annotations

import os
from typing import Any

from database.models import SystemConfig, User, UserRole
from services.cloud_upload_service import (
    STORAGE_MODE_CLOUD_BACKUP,
    STORAGE_MODE_LOCAL,
    STORAGE_MODE_PURE_CLOUD,
    CloudUploadService,
)
from services.hdp_component_policy import (
    DEPLOYMENT_CLASS_HPC,
    DEPLOYMENT_CLASS_SERVER,
    DEPLOYMENT_CLASS_WORKSTATION_LOCAL,
    local_hdp_component_execution_allowed,
    webhdp_deployment_class,
    webhdp_deployment_label,
    webhdp_deployment_mode,
)
from services.readiness_service import build_readiness_report


MANDATORY = "Mandatory"
RECOMMENDED = "Recommended"
OPTIONAL = "Optional"


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _configured(value: Any) -> bool:
    return bool(str(value or "").strip())


def _real_secret(value: Any) -> bool:
    text = str(value or "").strip()
    if len(text) < 16:
        return False
    lowered = text.lower()
    return not any(marker in lowered for marker in ("change-me", "your-secret", "placeholder", "secret-key-here"))


def _status(ok: bool, *, optional: bool = False) -> str:
    if ok:
        return "complete"
    return "optional" if optional else "action_required"


def _severity(status: str, required_level: str) -> str:
    if status == "complete":
        return "success"
    if required_level == MANDATORY:
        return "error"
    if required_level == RECOMMENDED:
        return "warning"
    return "info"


def _item(
    *,
    section: str,
    item_id: str,
    label: str,
    required_level: str,
    complete: bool,
    message: str,
    route: str | None = None,
) -> dict[str, Any]:
    status = _status(complete, optional=required_level == OPTIONAL)
    return {
        "section": section,
        "id": item_id,
        "label": label,
        "required_level": required_level,
        "status": status,
        "severity": _severity(status, required_level),
        "route": route,
        "message": message,
    }


def _safe_readiness(app: Any = None) -> dict[str, Any]:
    try:
        return build_readiness_report(app)
    except Exception as exc:
        return {
            "ready": False,
            "blockers": ["readiness"],
            "checks": {
                "readiness": {
                    "ok": False,
                    "error": str(exc),
                }
            },
        }


def _cloud_status() -> dict[str, Any]:
    dropbox_available, dropbox_message = CloudUploadService.check_dropbox_available()
    gdrive_available, gdrive_message = CloudUploadService.check_gdrive_available()
    active_storage, active_message = CloudUploadService.get_available_storage()
    return {
        "active_storage": active_storage,
        "active_message": active_message,
        "services": {
            "dropbox": {"available": dropbox_available, "message": dropbox_message},
            "gdrive": {"available": gdrive_available, "message": gdrive_message},
        },
    }


def _hpc_config(app: Any = None) -> dict[str, Any]:
    service = getattr(app, "hpc_allocation_service", None) if app is not None else None
    if service is None:
        return {
            "enabled": _truthy(os.environ.get("HPC_LINK_ENABLED")),
            "require_for_components": _truthy(os.environ.get("HPC_LINK_REQUIRE_FOR_COMPONENTS")),
            "has_token": _configured(os.environ.get("HPC_LINK_API_KEY")),
            "base_url": os.environ.get("HPC_LINK_BASE_URL") or "",
            "last_validation_status": "unknown",
        }
    try:
        return service.serialize_config()
    except Exception as exc:
        return {
            "enabled": False,
            "require_for_components": False,
            "has_token": False,
            "base_url": "",
            "last_validation_status": "unknown",
            "last_validation_error": str(exc),
        }


def _local_component_health(app: Any, component: str, enabled: bool, runtime_checks: dict[str, Any] | None) -> bool:
    if not enabled:
        return True
    if runtime_checks and component in runtime_checks:
        return bool(runtime_checks[component])
    if app is None:
        return False
    try:
        if component == "fast_renderer":
            return bool(app.fast_renderer_service.check_health())
        if component == "any_to_usdz":
            return bool(app.any_to_usdz_service.check_health())
    except Exception:
        return False
    return False


def build_admin_setup_guidance(
    app: Any = None,
    *,
    readiness_report: dict[str, Any] | None = None,
    cloud_status: dict[str, Any] | None = None,
    hpc_config: dict[str, Any] | None = None,
    runtime_checks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build mode-aware administrator setup guidance without active HPC calls."""

    config = app.config if app is not None else {}
    deployment_mode = str(config.get("WEBHDP_DEPLOYMENT_MODE") or webhdp_deployment_mode()).strip().lower()
    deployment_class = webhdp_deployment_class(app)
    deployment_label = webhdp_deployment_label(app)
    local_components_allowed = local_hdp_component_execution_allowed(app)
    storage_mode = CloudUploadService.get_storage_mode()
    renderer_enabled = bool(config.get("ENABLE_RENDERER", True))
    usdz_enabled = bool(config.get("ENABLE_USDZ_CONVERSION", True))
    readiness = readiness_report or _safe_readiness(app)
    cloud = cloud_status or _cloud_status()
    hpc = hpc_config or _hpc_config(app)

    checks = readiness.get("checks") or {}
    checklist: list[dict[str, Any]] = []
    admin_exists = User.query.filter_by(role=UserRole.ADMIN).first() is not None
    setup_completed = False
    try:
        from database.database import db
        setup_row = db.session.get(SystemConfig, "setup_completed")
        setup_completed = bool(setup_row and setup_row.value == "true")
    except Exception:
        setup_completed = False

    server_like = deployment_class in {DEPLOYMENT_CLASS_SERVER, DEPLOYMENT_CLASS_HPC}
    workstation = deployment_class == DEPLOYMENT_CLASS_WORKSTATION_LOCAL
    cloud_required = storage_mode in {STORAGE_MODE_PURE_CLOUD, STORAGE_MODE_CLOUD_BACKUP}
    cloud_available = any(
        bool((cloud.get("services") or {}).get(provider, {}).get("available"))
        for provider in ("dropbox", "gdrive")
    )
    compute_enabled = renderer_enabled or usdz_enabled
    hpc_static_ready = bool(
        hpc.get("enabled")
        and hpc.get("base_url")
        and hpc.get("has_token")
        and hpc.get("last_validation_status") == "valid"
    )
    local_renderer_ready = _local_component_health(app, "fast_renderer", renderer_enabled, runtime_checks)
    local_usdz_ready = _local_component_health(app, "any_to_usdz", usdz_enabled, runtime_checks)
    local_compute_ready = local_renderer_ready and local_usdz_ready

    secret_ok = _real_secret(config.get("SECRET_KEY") or os.environ.get("SECRET_KEY"))
    credential_secret_ok = _real_secret(
        config.get("CREDENTIAL_ENCRYPTION_KEY") or os.environ.get("CREDENTIAL_ENCRYPTION_KEY")
    )
    if deployment_class == DEPLOYMENT_CLASS_SERVER:
        secrets_level = MANDATORY
    else:
        secrets_level = RECOMMENDED

    checklist.append(_item(
        section="Identity & Security",
        item_id="initial_admin",
        label="Initial administrator account",
        required_level=MANDATORY,
        complete=admin_exists and setup_completed,
        route="/setup" if not setup_completed else "/admin/dashboard",
        message="Create and verify the first administrator before opening workflows to users.",
    ))
    checklist.append(_item(
        section="Identity & Security",
        item_id="application_secrets",
        label="Production application secrets",
        required_level=secrets_level,
        complete=secret_ok and credential_secret_ok,
        route="/docs/docker-deployment-guide",
        message="Use strong SECRET_KEY and CREDENTIAL_ENCRYPTION_KEY values for deployed instances.",
    ))
    checklist.append(_item(
        section="Identity & Security",
        item_id="login_mfa",
        label="Login MFA and mail delivery policy",
        required_level=RECOMMENDED,
        complete=False,
        route="/settings/mfa",
        message="Review email MFA behaviour and provider bypasses for your administrator population.",
    ))

    checklist.append(_item(
        section="Storage",
        item_id="runtime_paths",
        label="Database and runtime paths",
        required_level=MANDATORY,
        complete=bool(readiness.get("ready") or not any(name in readiness.get("blockers", []) for name in ("database", "sessions_path", "local_input", "local_output"))),
        route="/admin/dashboard",
        message="Database, sessions, input, and output paths must exist and be writable for this deployment.",
    ))
    checklist.append(_item(
        section="Storage",
        item_id="storage_mode",
        label="Storage mode policy",
        required_level=MANDATORY,
        complete=storage_mode in {STORAGE_MODE_PURE_CLOUD, STORAGE_MODE_CLOUD_BACKUP, "server_only", STORAGE_MODE_LOCAL}
        and (storage_mode != STORAGE_MODE_LOCAL or workstation or deployment_class == DEPLOYMENT_CLASS_HPC),
        route="/settings/storage",
        message=f"Current storage mode is {storage_mode}. Use cloud-backed modes for server uploads and local only for intentional mounted-folder workflows.",
    ))
    checklist.append(_item(
        section="Storage",
        item_id="cloud_storage",
        label="Cloud storage availability",
        required_level=MANDATORY if cloud_required else OPTIONAL,
        complete=(cloud_available if cloud_required else True),
        route="/settings/cloud-testing",
        message="Dropbox or Google Drive must be reachable when pure cloud or cloud backup storage is selected.",
    ))
    checklist.append(_item(
        section="Storage",
        item_id="local_folder_workflows",
        label="Local mounted-folder workflows",
        required_level=MANDATORY if storage_mode == STORAGE_MODE_LOCAL else OPTIONAL,
        complete=storage_mode != STORAGE_MODE_LOCAL or bool(checks.get("local_input", {}).get("ok") and checks.get("local_output", {}).get("ok")),
        route="/settings/storage",
        message="Use mounted local input/output folders only for workstation-local or HPC-attached storage workflows.",
    ))

    if workstation:
        compute_complete = not compute_enabled or local_compute_ready
        compute_message = "Enabled renderer and USDZ steps must pass local health checks on workstation-local deployments."
    elif server_like:
        compute_complete = not compute_enabled or hpc_static_ready
        compute_message = "Enabled compute-heavy HDP Components require validated HPC-Link config, or the features must be disabled."
    else:
        compute_complete = not compute_enabled
        compute_message = "Review compute-heavy HDP Component runtime policy for this deployment."
    checklist.append(_item(
        section="Compute",
        item_id="compute_runtime",
        label="HDP Component compute runtime",
        required_level=MANDATORY if compute_enabled else OPTIONAL,
        complete=compute_complete,
        route="/admin/dashboard" if server_like else "/settings/pipelines",
        message=compute_message,
    ))
    checklist.append(_item(
        section="Compute",
        item_id="hpc_link",
        label="HPC-Link configuration",
        required_level=MANDATORY if deployment_class == DEPLOYMENT_CLASS_HPC else (RECOMMENDED if deployment_class == DEPLOYMENT_CLASS_SERVER and compute_enabled else OPTIONAL),
        complete=hpc_static_ready if deployment_class in {DEPLOYMENT_CLASS_SERVER, DEPLOYMENT_CLASS_HPC} and compute_enabled else True,
        route="/admin/dashboard",
        message="HPC-Link status is read from saved configuration only; setup guidance does not start allocations or remote validation.",
    ))

    zenodo_ready = _configured(os.environ.get("ZENODO_SANDBOX_API_KEY") or os.environ.get("ZENODO_API_KEY"))
    checklist.append(_item(
        section="Publishing",
        item_id="zenodo_credentials",
        label="Zenodo publishing credentials",
        required_level=RECOMMENDED,
        complete=zenodo_ready,
        route="/account/configuration",
        message="Configure sandbox or production Zenodo credentials before publishing records.",
    ))
    checklist.append(_item(
        section="Publishing",
        item_id="pipeline_policy",
        label="Pipeline and metadata policy",
        required_level=RECOMMENDED,
        complete=True,
        route="/settings/pipelines",
        message="Review enabled pipeline steps, EDM templates, modality detection, and validation policy.",
    ))

    backup = checks.get("backup") or {}
    checklist.append(_item(
        section="Backups",
        item_id="backup_policy",
        label="Backup policy and latest backup",
        required_level=RECOMMENDED,
        complete=bool(backup.get("ok") and backup.get("backup_count", 0) > 0),
        route="/admin/dashboard",
        message="Create encrypted backups and verify the latest backup age before production use.",
    ))
    checklist.append(_item(
        section="Observability",
        item_id="operational_observability",
        label="Operational observability",
        required_level=RECOMMENDED,
        complete=bool((checks.get("redis") or {}).get("ok")) and not bool((checks.get("maintenance") or {}).get("enabled")),
        route="/settings/observability/credentials",
        message="Review credential visibility, API activity, notification delivery, Redis, and maintenance status.",
    ))

    sections = []
    for name in ("Identity & Security", "Storage", "Compute", "Publishing", "Backups", "Observability"):
        items = [item for item in checklist if item["section"] == name]
        sections.append({
            "id": name.lower().replace(" & ", "-").replace(" ", "-"),
            "title": name,
            "items": items,
        })

    mandatory_open = [item["id"] for item in checklist if item["required_level"] == MANDATORY and item["status"] != "complete"]
    recommended_open = [item["id"] for item in checklist if item["required_level"] == RECOMMENDED and item["status"] != "complete"]
    return {
        "deployment_mode": deployment_mode,
        "deployment_class": deployment_class,
        "deployment_label": deployment_label,
        "storage_mode": storage_mode,
        "local_hdp_components_allowed": local_components_allowed,
        "features": {
            "renderer_enabled": renderer_enabled,
            "usdz_conversion_enabled": usdz_enabled,
        },
        "readiness": readiness,
        "cloud": cloud,
        "hpc": hpc,
        "checklist": checklist,
        "sections": sections,
        "summary": {
            "mandatory_open": mandatory_open,
            "recommended_open": recommended_open,
            "ready_for_basic_use": not mandatory_open,
            "ready_for_production": not mandatory_open and not recommended_open,
        },
    }
