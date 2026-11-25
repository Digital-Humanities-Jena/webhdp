"""Publish dereferenceable IIIF manifest URLs for public Zenodo attachments."""
import json
import os
import re
from urllib.parse import urlsplit

import requests
from flask import current_app, has_app_context
from werkzeug.http import parse_options_header

from services.dataset_integrity_service import build_zenodo_direct_file_url, extract_file_objects, record_base
from services.iiif_validation import CONTEXT, V3_CONTEXT
from services.lod_reliability import assert_public_document, public_url

ENVIRONMENTS = {"zenodo": False, "sandbox": True}
RECORD_ID = re.compile(r"[0-9]{1,20}")
MANIFEST_NAME = "iiif.json"
MAX_PUBLIC_JSON_BYTES = 2 * 1024 * 1024


def public_base_url():
    configured = os.environ.get("IIIF_PUBLIC_BASE_URL", "")
    if has_app_context():
        configured = current_app.config.get("IIIF_PUBLIC_BASE_URL", configured)
    value = str(configured or "").strip().rstrip("/")
    if not value:
        return None
    uri = urlsplit(value)
    if (not public_url(value) or uri.scheme != "https" or uri.path or uri.query or uri.fragment
            or any(character.isspace() for character in uri.netloc) or uri.port not in (None, 443)):
        raise ValueError("IIIF_PUBLIC_BASE_URL must be a public HTTPS origin.")
    return value


def published_manifest_id(record_id, is_sandbox):
    record_id = str(record_id)
    base = public_base_url()
    if base and RECORD_ID.fullmatch(record_id):
        environment = "sandbox" if is_sandbox else "zenodo"
        return f"{base}/api/v1/iiif/{environment}/{record_id}/manifest.json"
    return build_zenodo_direct_file_url(is_sandbox, record_id, MANIFEST_NAME)


def manifest_content_type(profile, accept):
    profiled = f'application/ld+json; profile="{profile}"'
    offers = [(profiled, "application/ld+json", {"profile": profile}),
              ("application/json", "application/json", {})]
    if accept is None:
        return profiled
    ranked = []
    for content_type, media_type, options in offers:
        supported = {**options, "charset": "utf-8"}
        ranges = []
        for accept_range, quality in accept:
            mime, parameters = parse_options_header(accept_range)
            media_match = {"*/*": 0, "application/*": 1, media_type: 2}.get(mime.lower())
            if "charset" in parameters:
                parameters["charset"] = parameters["charset"].lower()
            if media_match is not None and all(supported.get(key) == value for key, value in parameters.items()):
                ranges.append((media_match, len(parameters), quality))
        if ranges:
            specificity, parameter_count, quality = max(ranges)
            if quality > 0:
                ranked.append(((quality, specificity, parameter_count), content_type))
    return max(ranked, key=lambda item: item[0])[1] if ranked else None


def _get_public_bytes(session, url, *, accept):
    with session.get(url, headers={"Accept": accept}, allow_redirects=False, stream=True,
                     timeout=(3, 8)) as response:
        if response.status_code in {401, 403, 404, 410}:
            return None
        if response.status_code != 200:
            raise ValueError("Unexpected response from the public Zenodo API.")
        content = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            if len(content) + len(chunk) > MAX_PUBLIC_JSON_BYTES:
                raise ValueError("The public JSON document is too large.")
            content.extend(chunk)
        return bytes(content)


def _has_open_attachment(payload, record_id):
    if not isinstance(payload, dict) or str(payload.get("id")) != record_id:
        return False
    status = payload.get("status")
    published = payload.get("is_published")
    if (status is not None and status != "published") or (published is not None and published is not True):
        return False
    if status is None and published is None:
        return False
    metadata = payload.get("metadata")
    legacy_visibility = metadata.get("access_right") if isinstance(metadata, dict) else None
    if legacy_visibility is not None and legacy_visibility != "open":
        return False
    access = payload.get("access")
    if access is None:
        if legacy_visibility != "open":
            return False
    elif not isinstance(access, dict) or access.get("files") != "public" or access.get("record") != "public":
        return False
    files = payload.get("files")
    if isinstance(files, dict):
        entries = files.get("entries")
        return files.get("enabled") is True and isinstance(entries, dict) and isinstance(entries.get(MANIFEST_NAME), dict)
    return any((item.get("key") or item.get("filename")) == MANIFEST_NAME for item in extract_file_objects(payload))


def _manifest_profile(content):
    raw = content.decode("utf-8")
    document = json.loads(raw)
    if (not isinstance(document, dict) or document.get("type") != "Manifest"
            or not public_url(document.get("id"))):
        raise ValueError("The public attachment is not a IIIF Manifest.")
    context = document.get("@context")
    if isinstance(context, list) and context:
        context = context[-1]
    for profile in (CONTEXT, V3_CONTEXT):
        if context in (profile, profile.replace("http:", "https:", 1)):
            assert_public_document(raw)
            return profile
    raise ValueError("The public attachment does not identify Presentation 3 or 4.")


def fetch_published_manifest(environment, record_id):
    """Return exact bytes and the declared profile after an anonymous public-access check."""
    if environment not in ENVIRONMENTS or not RECORD_ID.fullmatch(record_id):
        return None
    is_sandbox = ENVIRONMENTS[environment]
    record_url = f"{record_base(is_sandbox)}/api/records/{record_id}"
    with requests.Session() as session:
        session.trust_env = False  # Never use ambient credentials for public requests.
        record = _get_public_bytes(session, record_url, accept="application/json")
        if record is None or not _has_open_attachment(json.loads(record), record_id):
            return None
        manifest = _get_public_bytes(
            session, build_zenodo_direct_file_url(is_sandbox, record_id, MANIFEST_NAME), accept="application/json",
        )
        if manifest is None:
            return None
        return manifest, _manifest_profile(manifest)
