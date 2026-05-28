import html
import os
import re
from typing import Any
from urllib.parse import quote, urlparse

from services.dataset_integrity_service import (
    INLINE_MODEL_FILE_EXTENSIONS,
    THUMBNAIL_IMAGE_EXTENSIONS,
    ZenodoPublicCache,
    build_model_preview,
    build_zenodo_direct_file_url,
    choose_model_file,
    extract_file_objects,
    is_valid_zenodo_direct_file_url,
    record_base,
)


PUBLIC_ENVIRONMENTS = {"zenodo": False, "sandbox": True}
DEFAULT_OEMBED_WIDTH = 640
DEFAULT_OEMBED_HEIGHT = 480
MAX_OEMBED_WIDTH = 1200
MAX_OEMBED_HEIGHT = 900


class PublicRecordError(ValueError):
    pass


def normalize_public_environment(environment: Any) -> tuple[str, bool]:
    normalized = str(environment or "").strip().lower()
    if normalized not in PUBLIC_ENVIRONMENTS:
        raise PublicRecordError("environment must be either 'zenodo' or 'sandbox'")
    return normalized, PUBLIC_ENVIRONMENTS[normalized]


def normalize_zenodo_record_id(record_id: Any) -> str:
    normalized = str(record_id or "").strip()
    if not normalized or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", normalized):
        raise PublicRecordError("zenodoRecordId is invalid")
    return normalized


def normalize_public_base_url(base_url: Any) -> str:
    normalized = str(base_url or "").strip().rstrip("/")
    return normalized or "http://localhost"


def public_record_url(base_url: str, environment: str, record_id: str) -> str:
    return f"{normalize_public_base_url(base_url)}/p/records/{quote(environment, safe='')}/{quote(record_id, safe='')}"


def embed_record_url(base_url: str, environment: str, record_id: str) -> str:
    return f"{normalize_public_base_url(base_url)}/embed/records/{quote(environment, safe='')}/{quote(record_id, safe='')}"


def oembed_endpoint_url(base_url: str, public_url: str) -> str:
    return f"{normalize_public_base_url(base_url)}/api/v1/oembed?url={quote(public_url, safe='')}&format=json"


def _metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _normalize_public_files(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_files = payload.get("files")
    if isinstance(raw_files, dict) and isinstance(raw_files.get("entries"), dict):
        return [
            {"key": key, **value}
            for key, value in raw_files["entries"].items()
            if isinstance(value, dict)
        ]
    if isinstance(raw_files, dict) and isinstance(raw_files.get("entries"), list):
        raw_files = raw_files.get("entries")
    if isinstance(raw_files, list):
        return [item for item in raw_files if isinstance(item, dict)]
    return []


def _file_name(file_obj: dict[str, Any] | None) -> str:
    if not isinstance(file_obj, dict):
        return ""
    return str(file_obj.get("filename") or file_obj.get("key") or file_obj.get("name") or file_obj.get("id") or "").strip()


def _file_extension(file_obj: dict[str, Any] | None) -> str:
    return os.path.splitext(_file_name(file_obj).lower())[1]


def _direct_file_url(is_sandbox: bool, record_id: str, file_obj: dict[str, Any] | None) -> str:
    if not isinstance(file_obj, dict):
        return ""
    links = file_obj.get("links") if isinstance(file_obj.get("links"), dict) else {}
    for key in ("content", "download", "self"):
        value = str(links.get(key) or "").strip()
        if not value:
            continue
        if key == "self" and not value.endswith("/content"):
            value = value.rstrip("/") + "/content"
        if is_valid_zenodo_direct_file_url(value):
            return value
    return build_zenodo_direct_file_url(is_sandbox, record_id, _file_name(file_obj))


def _creator_names(metadata: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for item in metadata.get("creators") or []:
        if isinstance(item, dict):
            person = item.get("person_or_org") if isinstance(item.get("person_or_org"), dict) else {}
            candidate = person.get("name") or item.get("name")
        else:
            candidate = item
        text = str(candidate or "").strip()
        if text:
            names.append(text)
    return names


def _doi(payload: dict[str, Any], metadata: dict[str, Any]) -> str:
    pids = payload.get("pids") if isinstance(payload.get("pids"), dict) else {}
    doi_pid = pids.get("doi") if isinstance(pids.get("doi"), dict) else {}
    for candidate in [doi_pid.get("identifier"), payload.get("doi"), metadata.get("doi")]:
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


def _choose_thumbnail(files: list[dict[str, Any]]) -> dict[str, Any] | None:
    image_files = [item for item in files if _file_extension(item) in THUMBNAIL_IMAGE_EXTENSIONS]
    if not image_files:
        return None
    return sorted(
        image_files,
        key=lambda item: (
            0 if re.search(r"(thumb|thumbnail|preview|render)", _file_name(item), re.IGNORECASE) else 1,
            _file_name(item).lower(),
        ),
    )[0]


def build_public_record(
    environment: Any,
    zenodo_record_id: Any,
    *,
    public_base_url: str,
    cache: ZenodoPublicCache | None = None,
) -> dict[str, Any] | None:
    environment_name, is_sandbox = normalize_public_environment(environment)
    record_id = normalize_zenodo_record_id(zenodo_record_id)
    public_cache = cache or ZenodoPublicCache()
    payload = public_cache.fetch(is_sandbox=is_sandbox, record_id=record_id)
    if not isinstance(payload, dict):
        return None

    metadata = _metadata(payload)
    files = _normalize_public_files(payload)
    record_metadata = {**payload, "files": files}
    model_file = choose_model_file("", extract_file_objects(record_metadata), allowed_extensions=INLINE_MODEL_FILE_EXTENSIONS) or choose_model_file("", files)
    source_file_name = _file_name(model_file)
    title = str(metadata.get("title") or payload.get("title") or f"Zenodo record {record_id}").strip()
    creators = _creator_names(metadata)
    thumbnail_file = _choose_thumbnail(files)
    thumbnail_url = _direct_file_url(is_sandbox, record_id, thumbnail_file) if thumbnail_file else ""
    links = payload.get("links") if isinstance(payload.get("links"), dict) else {}
    record_url = str(links.get("html") or f"{record_base(is_sandbox)}/records/{record_id}")
    canonical_public_url = public_record_url(public_base_url, environment_name, record_id)
    canonical_embed_url = embed_record_url(public_base_url, environment_name, record_id)

    record_for_preview = {
        "source_file_name": source_file_name,
        "record_status": "published",
        "zenodo_record_id": record_id,
        "is_sandbox": is_sandbox,
        "record_metadata": record_metadata,
    }

    return {
        "environment": environment_name,
        "is_sandbox": is_sandbox,
        "zenodo_record_id": record_id,
        "title": title,
        "creators": creators,
        "author_name": ", ".join(creators),
        "description": str(metadata.get("description") or "").strip(),
        "publication_date": str(metadata.get("publication_date") or payload.get("publication_date") or "").strip(),
        "doi": _doi(payload, metadata),
        "record_url": record_url,
        "zenodo_url": record_url,
        "public_url": canonical_public_url,
        "embed_url": canonical_embed_url,
        "oembed_url": oembed_endpoint_url(public_base_url, canonical_public_url),
        "provider_name": "WebHDP",
        "provider_url": normalize_public_base_url(public_base_url),
        "thumbnail_url": thumbnail_url,
        "thumbnail_filename": _file_name(thumbnail_file),
        "file_count": len(files),
        "files": [{"filename": _file_name(item), "size": item.get("size"), "links": item.get("links")} for item in files],
        "model_preview": build_model_preview(record_for_preview, public_cache=public_cache),
    }


def parse_public_record_url(url: Any) -> tuple[str, str]:
    parsed = urlparse(str(url or "").strip())
    path = parsed.path.rstrip("/")
    match = re.fullmatch(r"/(?:p|embed)/records/([^/]+)/([^/]+)", path)
    if not match:
        raise PublicRecordError("url must point to a WebHDP public record page")
    environment = match.group(1)
    record_id = match.group(2)
    normalize_public_environment(environment)
    normalize_zenodo_record_id(record_id)
    return environment, record_id


def calculate_oembed_size(maxwidth: Any = None, maxheight: Any = None) -> tuple[int, int]:
    width = DEFAULT_OEMBED_WIDTH
    height = DEFAULT_OEMBED_HEIGHT

    def parse_positive(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise PublicRecordError("maxwidth and maxheight must be positive integers") from exc
        if parsed <= 0:
            raise PublicRecordError("maxwidth and maxheight must be positive integers")
        return parsed

    requested_width = parse_positive(maxwidth)
    requested_height = parse_positive(maxheight)

    if requested_width:
        width = min(width, requested_width, MAX_OEMBED_WIDTH)
        height = round(width * 0.75)
    else:
        width = min(width, MAX_OEMBED_WIDTH)

    if requested_height:
        max_allowed_height = min(requested_height, MAX_OEMBED_HEIGHT)
        if height > max_allowed_height:
            height = max_allowed_height
            width = round(height / 0.75)

    return max(1, width), max(1, min(height, MAX_OEMBED_HEIGHT))


def build_oembed_response(public_record: dict[str, Any], *, maxwidth: Any = None, maxheight: Any = None) -> dict[str, Any]:
    width, height = calculate_oembed_size(maxwidth=maxwidth, maxheight=maxheight)
    title = str(public_record.get("title") or "WebHDP record").strip()
    embed_url = str(public_record.get("embed_url") or "").strip()
    escaped_title = html.escape(title, quote=True)
    escaped_src = html.escape(embed_url, quote=True)
    iframe_html = (
        f'<iframe src="{escaped_src}" width="{width}" height="{height}" '
        f'title="{escaped_title}" loading="lazy" allowfullscreen '
        f'style="border:0;max-width:100%;aspect-ratio:{width}/{height};"></iframe>'
    )
    response = {
        "version": "1.0",
        "type": "rich",
        "title": title,
        "provider_name": public_record.get("provider_name") or "WebHDP",
        "provider_url": public_record.get("provider_url") or "",
        "author_name": public_record.get("author_name") or "",
        "html": iframe_html,
        "width": width,
        "height": height,
    }
    thumbnail_url = str(public_record.get("thumbnail_url") or "").strip()
    if thumbnail_url:
        response.update(
            {
                "thumbnail_url": thumbnail_url,
                "thumbnail_width": 640,
                "thumbnail_height": 480,
            }
        )
    return response
