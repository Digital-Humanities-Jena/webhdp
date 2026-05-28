import json
import os
import re
from copy import deepcopy

from database.database import db
from database.models import SystemConfig


MFA_PROVIDER_BYPASS_CONFIG_KEY = "mfa_provider_bypass"
DEFAULT_MFA_PROVIDER_BYPASS_DOMAINS = ["gmail.com", "googlemail.com"]
DEFAULT_MFA_PROVIDER_BYPASS_CONFIG = {
    "enabled": False,
    "domains": DEFAULT_MFA_PROVIDER_BYPASS_DOMAINS,
}
_DOMAIN_PATTERN = re.compile(r"^(?:\*\.)?[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")


def _default_config() -> dict:
    config = deepcopy(DEFAULT_MFA_PROVIDER_BYPASS_CONFIG)
    enabled = str(os.environ.get("MFA_PROVIDER_BYPASS_ENABLED", "")).strip().lower()
    domains = os.environ.get("MFA_PROVIDER_BYPASS_DOMAINS")
    if enabled in {"1", "true", "yes", "on"}:
        config["enabled"] = True
    elif enabled in {"0", "false", "no", "off"}:
        config["enabled"] = False
    if domains:
        config["domains"] = normalize_mfa_bypass_domains(domains)
    return config


def normalize_mfa_bypass_domains(domains) -> list[str]:
    if domains is None:
        return []
    if isinstance(domains, str):
        raw_domains = re.split(r"[\s,;]+", domains)
    elif isinstance(domains, (list, tuple, set)):
        raw_domains = domains
    else:
        raise ValueError("Domains must be a list or text value")

    normalized = []
    seen = set()
    for raw_domain in raw_domains:
        domain = str(raw_domain or "").strip().lower()
        if not domain:
            continue
        if domain.startswith("@"):
            domain = domain[1:]
        domain = domain.rstrip(".")
        if not _DOMAIN_PATTERN.match(domain):
            raise ValueError(f"Invalid email provider domain: {raw_domain}")
        if domain not in seen:
            normalized.append(domain)
            seen.add(domain)
    if len(normalized) > 50:
        raise ValueError("At most 50 MFA bypass domains can be configured")
    return normalized


def normalize_mfa_provider_bypass_config(raw_config: dict | None) -> dict:
    config = _default_config()
    if isinstance(raw_config, dict):
        if "enabled" in raw_config:
            config["enabled"] = bool(raw_config.get("enabled"))
        elif "provider_bypass_enabled" in raw_config:
            config["enabled"] = bool(raw_config.get("provider_bypass_enabled"))

        if "domains" in raw_config:
            config["domains"] = normalize_mfa_bypass_domains(raw_config.get("domains"))
        elif "bypass_email_domains" in raw_config:
            config["domains"] = normalize_mfa_bypass_domains(raw_config.get("bypass_email_domains"))
    config["domains"] = normalize_mfa_bypass_domains(config["domains"])
    return config


def get_mfa_provider_bypass_config() -> dict:
    row = db.session.get(SystemConfig, MFA_PROVIDER_BYPASS_CONFIG_KEY)
    if not row or not row.value:
        return _default_config()
    try:
        raw_config = json.loads(row.value)
    except (TypeError, ValueError):
        return _default_config()
    return normalize_mfa_provider_bypass_config(raw_config)


def save_mfa_provider_bypass_config(config: dict) -> dict:
    normalized = normalize_mfa_provider_bypass_config(config)
    row = db.session.get(SystemConfig, MFA_PROVIDER_BYPASS_CONFIG_KEY)
    if not row:
        row = SystemConfig(key=MFA_PROVIDER_BYPASS_CONFIG_KEY)
        db.session.add(row)
    row.value = json.dumps(normalized, sort_keys=True)
    return normalized


def get_email_domain(email: str) -> str:
    _, separator, domain = str(email or "").strip().lower().rpartition("@")
    if not separator:
        return ""
    return domain.rstrip(".")


def email_domain_matches_config(email: str, config: dict | None = None) -> bool:
    current_config = normalize_mfa_provider_bypass_config(config) if config is not None else get_mfa_provider_bypass_config()
    if not current_config.get("enabled"):
        return False
    email_domain = get_email_domain(email)
    if not email_domain:
        return False
    for domain in current_config.get("domains", []):
        if domain.startswith("*."):
            suffix = domain[2:]
            if email_domain.endswith(f".{suffix}"):
                return True
        elif email_domain == domain:
            return True
    return False
