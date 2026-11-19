"""Email addresses used for authentication and verified invitations."""

import re

from exceptions import ValidationError


_LOCAL_PART = re.compile(r"[a-zA-Z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-zA-Z0-9!#$%&'*+/=?^_`{|}~-]+)*")
_DOMAIN_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def email_for_delivery(value: object) -> str:
    """Validate a mailbox and preserve the spelling of its local part for SMTP."""
    if not isinstance(value, str) or not 1 <= len(value) <= 320:
        raise ValidationError("Enter a valid email address.")
    local, separator, domain = value.strip().rpartition("@")
    try:
        domain = domain.lower().encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValidationError("Enter a valid email address.") from exc
    labels = domain.split(".")
    if (
        not separator or len(local) > 64 or not _LOCAL_PART.fullmatch(local)
        or len(labels) < 2 or not all(_DOMAIN_LABEL.fullmatch(label) for label in labels)
        or len(local) + len(domain) + 1 > 254
    ):
        raise ValidationError("Enter a valid email address.")
    return f"{local}@{domain}"


def normalize_email(value: object) -> str:
    """Return the case-insensitive WebHDP account key for a valid mailbox."""
    return email_for_delivery(value).lower()
