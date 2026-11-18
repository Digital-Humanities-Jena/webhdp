"""Account policy and Zenodo credentials for the guided publication workflow."""

import os
import re
import time

from flask import request

from api_utils import APIResponse
from database.database import db
from database.models import SystemConfig, User, UserRole
from services.zenodo_credential_service import ZenodoCredentialService

DEMO_CAPABILITY = "model_publication_demo"
DEMO_SECONDS = 15 * 60
DEMO_EMAIL = re.compile(r"model-demo-[a-f0-9]{8}@webhdp\.invalid", re.IGNORECASE)
DEMO_CLAIM = "model_publication_only"

_READ = frozenset({"GET", "HEAD"})
DEMO_ENDPOINTS = {
    "auth.get_current_user": _READ,
    "auth.logout": frozenset({"POST"}),
    "model_publication.availability": _READ,
    "model_publication.queue_status": _READ,
    "model_publication.jobs": _READ,
    "model_publication.job_status": _READ,
    "model_publication.job_file": _READ,
    "model_publication.submit_job": frozenset({"POST"}),
}


def is_demo(user):
    return DEMO_CAPABILITY in user.capabilities or DEMO_EMAIL.fullmatch(user.email or "") is not None


def demo_config_key(user_id):
    return f"model_publication_demo:{user_id}"


def demo_expiry(user_id):
    policy = db.session.get(SystemConfig, demo_config_key(user_id))
    try:
        return int(policy.value) if policy else 0
    except (TypeError, ValueError):
        return 0


def demo_open(user_id):
    return demo_expiry(user_id) > time.time()


def demo_sign_in_allowed(user):
    return user.role == UserRole.USER and user.is_verified and not user.force_password_change and demo_open(user.id)


def register_demo_jwt_scope(jwt):
    """Apply the same restrictions anywhere a WebHDP JWT is accepted."""
    @jwt.token_verification_loader
    def verify_scope(_header, payload):
        try:
            user = db.session.get(User, int(payload.get("sub")))
        except (ValueError, TypeError):
            return False
        if not user:
            return False
        if not is_demo(user):
            return payload.get(DEMO_CLAIM) is not True
        return demo_sign_in_allowed(user) and request.method in DEMO_ENDPOINTS.get(request.endpoint, ())

    @jwt.token_verification_failed_loader
    def scope_denied(_header, _payload):
        response, status = APIResponse.error(
            "DEMO_WORKFLOW_ONLY",
            "This account is limited to the model publication demonstration.",
            403,
        )
        response.headers["Cache-Control"] = "private, no-store"
        return response, status


def sandbox_token(user_id, demo=False):
    if demo:
        return str(os.environ.get("ZENODO_SANDBOX_API_KEY") or "").strip()
    service = ZenodoCredentialService()
    active = service.get_active_credential(user_id, "sandbox")
    return service.decrypt_value(active) if active else ""
