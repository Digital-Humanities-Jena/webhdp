"""Shared deployment and account checks for the native Tools workspace."""

import os

from database.models import UserRole


def core_workflow_only() -> bool:
    return os.environ.get("WEBHDP_CORE_ONLY", "").strip().lower() == "true"


def native_tools_enabled() -> bool:
    return not core_workflow_only() or os.environ.get("WEBHDP_ENABLE_NATIVE_TOOLS", "").strip().lower() == "true"


def can_author_pipelines(user) -> bool:
    if not user:
        return False
    return getattr(user, "role", None) in (UserRole.ADMIN, UserRole.ADMIN.value) or "native_pipeline_author" in {
        value.lower() for value in (getattr(user, "capabilities", None) or ())
    }
