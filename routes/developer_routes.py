"""Developer-mode diagnostics for authenticated contributors."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app
from flask_jwt_extended import get_jwt_identity, jwt_required

from api_utils import APIResponse
from database.database import db
from database.models import User


developer_bp = Blueprint("developer", __name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _current_user() -> User | None:
    identity = get_jwt_identity()
    try:
        return db.session.get(User, int(identity))
    except (TypeError, ValueError):
        return None


def _can_access_developer_mode(user: User | None) -> bool:
    if user is None:
        return False
    role = getattr(getattr(user, "role", None), "value", getattr(user, "role", None))
    if role in {"admin", "moderator"}:
        return True
    return bool(user.has_capability("developer_access"))


def _read_version_info() -> dict[str, Any]:
    version_path = PROJECT_ROOT / "version.json"
    if not version_path.exists():
        return {}
    try:
        return json.loads(version_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _file_exists(relative_path: str) -> bool:
    return (PROJECT_ROOT / relative_path).exists()


@developer_bp.route("/status", methods=["GET"])
@jwt_required()
def developer_status():
    """Return read-only developer onboarding diagnostics."""
    user = _current_user()
    if not _can_access_developer_mode(user):
        return APIResponse.forbidden("Developer mode requires admin, moderator, or developer_access capability")

    config = current_app.config
    feature_flags = {
        "enable_renderer": bool(config.get("ENABLE_RENDERER")),
        "enable_usdz_conversion": bool(config.get("ENABLE_USDZ_CONVERSION")),
        "enable_local_edm_validation": bool(config.get("ENABLE_LOCAL_EDM_VALIDATION")),
        "local_edm_validator_continue_on_error": bool(config.get("LOCAL_EDM_VALIDATOR_CONTINUE_ON_ERROR")),
        "notification_sse_enabled": bool(config.get("NOTIFICATION_SSE_ENABLED")),
        "backup_enabled": bool(config.get("BACKUP_ENABLED")),
    }
    runtime = {
        "flask_env": os.environ.get("FLASK_ENV", "development"),
        "storage_mode": config.get("STORAGE_MODE"),
        "inline_tasks_requested": os.environ.get("WEBHDP_INLINE_TASKS", "").lower() in {"1", "true", "yes", "on"},
        "database_configured": bool(config.get("SQLALCHEMY_DATABASE_URI")),
        "redis_broker_configured": bool(config.get("CELERY_BROKER_URL")),
    }
    docs = [
        {"label": "Developer Onboarding", "path": "/docs/developer-onboarding", "file": "docs/development/onboarding.md"},
        {"label": "Devcontainer Setup", "path": "/docs/devcontainer", "file": "docs/development/devcontainer.md"},
        {"label": "First PR Walkthrough", "path": "/docs/first-pr-walkthrough", "file": "docs/development/first_pr_walkthrough.md"},
        {"label": "Troubleshooting Decision Tree", "path": "/docs/developer-troubleshooting", "file": "docs/development/troubleshooting_decision_tree.md"},
        {"label": "Contributor Architecture Map", "path": "/docs/contributor-architecture-map", "file": "docs/development/architecture_map.md"},
        {"label": "Developer Glossary", "path": "/docs/developer-glossary", "file": "docs/development/developer_glossary.md"},
        {"label": "PR Size And Scope Examples", "path": "/docs/pr-scope-examples", "file": "docs/development/pr_scope_examples.md"},
        {"label": "Known Development Warnings", "path": "/docs/known-development-warnings", "file": "docs/development/known_warnings.md"},
        {"label": "Contributor Handbook", "path": "/docs/contributor-handbook", "file": "docs/development/contributor_handbook.md"},
        {"label": "Developer Examples", "path": "/docs/developer-examples", "file": "docs/development/examples.md"},
        {"label": "Good First Changes", "path": "/docs/good-first-changes", "file": "docs/development/good_first_changes.md"},
        {"label": "Golden Sample Workflow", "path": "/docs/golden-workflow", "file": "docs/development/golden_workflow.md"},
        {"label": "API Reference", "path": "/docs/api-reference", "file": "docs/api/webhdp_api_reference.md"},
    ]
    commands = [
        {"label": "Install dependencies", "command": "make setup"},
        {"label": "Run environment doctor", "command": "make doctor"},
        {"label": "Run docs checks", "command": "make docs-check"},
        {"label": "Build devcontainer", "command": "make devcontainer-check"},
        {"label": "Run golden workflow", "command": "make golden-workflow"},
        {"label": "Regenerate API contract", "command": "make api-contract"},
        {"label": "Run backend tests", "command": "make test-backend"},
        {"label": "Run frontend tests", "command": "make test-frontend"},
        {"label": "Validate onboarding", "command": "make verify-onboarding"},
    ]

    role = getattr(getattr(user, "role", None), "value", getattr(user, "role", None)) or "user"
    return APIResponse.success(
        data={
            "developer_mode": True,
            "version": _read_version_info(),
            "user": {
                "id": user.id,
                "email": user.email,
                "role": role,
                "capabilities": user.capabilities,
                "groups": user.groups,
            },
            "runtime": runtime,
            "feature_flags": feature_flags,
            "api_contract": {
                "path": "docs/api/openapi.json",
                "exists": _file_exists("docs/api/openapi.json"),
                "regenerate_command": "make api-contract",
            },
            "docs": [{**entry, "exists": _file_exists(entry["file"])} for entry in docs],
            "commands": commands,
        }
    )
