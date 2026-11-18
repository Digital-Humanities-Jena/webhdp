"""Account policy and Zenodo credentials for the guided publication workflow."""

import os
import time

from database.database import db
from database.models import SystemConfig
from services.zenodo_credential_service import ZenodoCredentialService

DEMO_CAPABILITY = "model_publication_demo"
DEMO_SECONDS = 15 * 60


def is_demo(user):
    return DEMO_CAPABILITY in user.capabilities


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


def sandbox_token(user_id, demo=False):
    if demo:
        return str(os.environ.get("ZENODO_SANDBOX_API_KEY") or "").strip()
    service = ZenodoCredentialService()
    active = service.get_active_credential(user_id, "sandbox")
    return service.decrypt_value(active) if active else ""
