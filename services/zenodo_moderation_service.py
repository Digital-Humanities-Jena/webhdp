import os
import time
from datetime import date, datetime
from typing import Any, Dict, List

import requests
from flask import current_app


ZENODO_PRODUCTION_BASE_URL = "https://zenodo.org"
MAX_COMMUNITY_REQUESTS = 500
REQUESTS_PAGE_SIZE = 100


def get_zenodo_production_access_token() -> str:
    token = str(os.environ.get("ZENODO_API_KEY") or "").strip()
    if token:
        return token
    raise ValueError("Zenodo production API key (ZENODO_API_KEY) is not configured.")


def get_zenodo_production_api_params() -> Dict[str, str]:
    return {"access_token": get_zenodo_production_access_token()}


def make_rate_limited_request(method: str, url: str, wait_callback=None, **kwargs):
    max_retries = 5
    retry_count = 0

    while retry_count < max_retries:
        try:
            response = requests.request(method, url, **kwargs)

            remaining = int(response.headers.get("X-RateLimit-Remaining", -1))
            limit = int(response.headers.get("X-RateLimit-Limit", -1))
            reset = int(response.headers.get("X-RateLimit-Reset", 0))

            if remaining > -1 and remaining < 5:
                now = time.time()
                sleep_time = max(reset - now, 1)
                current_app.logger.warning(
                    "Approaching Zenodo rate limit (%s/%s). Sleeping for %.2fs.",
                    remaining,
                    limit,
                    sleep_time,
                )
                if wait_callback:
                    wait_callback("low_remaining", sleep_time, response=response)
                time.sleep(sleep_time)

            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 60))
                current_app.logger.warning("Zenodo rate limit hit. Retrying after %ss.", retry_after)
                if wait_callback:
                    wait_callback("retry_after", retry_after, response=response)
                time.sleep(retry_after)
                retry_count += 1
                continue

            if 500 <= response.status_code < 600:
                wait_time = 2 ** retry_count
                current_app.logger.warning(
                    "Zenodo server error %s. Retrying in %ss.",
                    response.status_code,
                    wait_time,
                )
                if wait_callback:
                    wait_callback("server_backoff", wait_time, response=response)
                time.sleep(wait_time)
                retry_count += 1
                continue

            return response
        except requests.exceptions.RequestException as exc:
            wait_time = 2 ** retry_count
            current_app.logger.warning("Zenodo network error: %s. Retrying in %ss.", exc, wait_time)
            if wait_callback:
                wait_callback("network_backoff", wait_time, response=None)
            time.sleep(wait_time)
            retry_count += 1

    raise requests.exceptions.RetryError(f"Max retries ({max_retries}) exceeded for {url}")


def _parse_iso_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed_date = _parse_iso_date(text)
        return datetime.combine(parsed_date, datetime.min.time()) if parsed_date else None


def _request_topic_record(topic: Any) -> Any:
    if isinstance(topic, dict):
        record = topic.get("record")
        if isinstance(record, dict):
            return record.get("id") or record.get("record")
        return record
    return None


def normalize_request_payload(item: Dict[str, Any]) -> Dict[str, Any]:
    item = item if isinstance(item, dict) else {}
    links = item.get("links") if isinstance(item.get("links"), dict) else {}
    actions = links.get("actions") if isinstance(links.get("actions"), dict) else {}
    request_id = str(item.get("id") or "").strip()
    status = str(item.get("status") or "").strip().lower()
    is_open = bool(item.get("is_open"))
    is_actionable = bool(
        request_id
        and is_open
        and actions.get("accept")
        and actions.get("decline")
    )

    return {
        "request_id": request_id,
        "number": str(item.get("number") or "").strip() or None,
        "title": str(item.get("title") or "").strip() or "Untitled request",
        "type": str(item.get("type") or "").strip() or "unknown",
        "status": status or "unknown",
        "created": item.get("created"),
        "updated": item.get("updated"),
        "topic_record": _request_topic_record(item.get("topic")),
        "created_by": item.get("created_by") if isinstance(item.get("created_by"), dict) else {},
        "receiver": item.get("receiver") if isinstance(item.get("receiver"), dict) else {},
        "links": {
            "self": links.get("self"),
            "actions": {
                "accept": actions.get("accept"),
                "decline": actions.get("decline"),
            },
        },
        "is_open": is_open,
        "is_actionable": is_actionable,
    }


def request_is_actionable_for(item: Dict[str, Any], action: str) -> bool:
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"accept", "decline"}:
        return False
    links = item.get("links") if isinstance(item.get("links"), dict) else {}
    actions = links.get("actions") if isinstance(links.get("actions"), dict) else {}
    return bool(item.get("request_id") and item.get("is_open") and actions.get(normalized_action))


def resolve_community(identifier: str | None) -> Dict[str, Any]:
    value = str(identifier or "").strip()
    if not value:
        raise ValueError("community_identifier is required")

    response = make_rate_limited_request(
        "GET",
        f"{ZENODO_PRODUCTION_BASE_URL}/api/communities/{value}",
        params=get_zenodo_production_api_params(),
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Unexpected Zenodo community response format")
    return payload


def _community_payload(community: Dict[str, Any], community_identifier: str) -> Dict[str, Any]:
    community_links = community.get("links") if isinstance(community.get("links"), dict) else {}
    return {
        "id": community.get("id"),
        "slug": community.get("slug"),
        "title": ((community.get("metadata") or {}).get("title") if isinstance(community.get("metadata"), dict) else None),
        "identifier_used": community_identifier,
        "links": {
            "self": community_links.get("self"),
            "self_html": community_links.get("self_html"),
            "requests": community_links.get("requests"),
        },
    }


def fetch_community_request_page(
    community_identifier: str,
    *,
    status: str = "submitted",
    page: int = 1,
    size: int = REQUESTS_PAGE_SIZE,
    request_type: str | None = None,
    wait_callback=None,
) -> Dict[str, Any]:
    community = resolve_community(community_identifier)
    community_links = community.get("links") if isinstance(community.get("links"), dict) else {}
    requests_url = str(community_links.get("requests") or "").strip()
    if not requests_url:
        raise ValueError("Zenodo community does not expose a requests endpoint")

    params: Dict[str, Any] = {
        **get_zenodo_production_api_params(),
        "page": max(1, int(page or 1)),
        "size": max(1, min(int(size or REQUESTS_PAGE_SIZE), REQUESTS_PAGE_SIZE)),
    }
    status_value = str(status or "").strip().lower()
    if status_value:
        params["status"] = status_value
    request_type_value = str(request_type or "").strip()
    if request_type_value:
        params["type"] = request_type_value

    response = make_rate_limited_request(
        "GET",
        requests_url,
        params=params,
        timeout=60,
        wait_callback=wait_callback,
    )
    response.raise_for_status()
    payload = response.json()
    hits = payload.get("hits") if isinstance(payload, dict) else {}
    raw_items = hits.get("hits") if isinstance(hits, dict) else []
    items = [normalize_request_payload(item) for item in raw_items if isinstance(item, dict)]
    if request_type_value:
        items = [item for item in items if str(item.get("type") or "").strip().lower() == request_type_value.lower()]

    return {
        "community": _community_payload(community, community_identifier),
        "requests": items,
        "total": int(hits.get("total") or 0) if isinstance(hits, dict) else len(items),
        "page": params["page"],
        "size": params["size"],
        "status": status_value or None,
        "request_type": request_type_value or None,
    }


def summarize_community_requests(
    community_identifier: str,
    *,
    action: str = "accept",
    status: str = "submitted",
    request_type: str | None = None,
    preview_size: int = REQUESTS_PAGE_SIZE,
) -> Dict[str, Any]:
    page_payload = fetch_community_request_page(
        community_identifier,
        status=status,
        page=1,
        size=preview_size,
        request_type=request_type,
    )
    preview = list(page_payload.get("requests") or [])
    normalized_action = str(action or "accept").strip().lower()
    return {
        "community": page_payload.get("community") or {},
        "status": page_payload.get("status"),
        "request_type": page_payload.get("request_type"),
        "total": int(page_payload.get("total") or 0),
        "preview": preview,
        "preview_count": len(preview),
        "preview_actionable_count": sum(1 for item in preview if request_is_actionable_for(item, normalized_action)),
        "action": normalized_action,
        "api_key_context": {
            "environment": "production",
            "source": "ZENODO_API_KEY",
            "configured": bool(str(os.environ.get("ZENODO_API_KEY") or "").strip()),
        },
    }


def fetch_open_community_requests(community_identifier: str, *, max_items: int = MAX_COMMUNITY_REQUESTS) -> Dict[str, Any]:
    community = resolve_community(community_identifier)
    community_links = community.get("links") if isinstance(community.get("links"), dict) else {}
    requests_url = str(community_links.get("requests") or "").strip()
    if not requests_url:
        raise ValueError("Zenodo community does not expose a requests endpoint")

    fetched_items: List[Dict[str, Any]] = []
    page = 1
    while len(fetched_items) < max_items:
        response = make_rate_limited_request(
            "GET",
            requests_url,
            params={
                **get_zenodo_production_api_params(),
                "page": page,
                "size": min(REQUESTS_PAGE_SIZE, max_items - len(fetched_items)),
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        hits = payload.get("hits") if isinstance(payload, dict) else {}
        page_items = hits.get("hits") if isinstance(hits, dict) else []
        if not isinstance(page_items, list) or not page_items:
            break

        fetched_items.extend(item for item in page_items if isinstance(item, dict))
        if len(page_items) < REQUESTS_PAGE_SIZE:
            break
        page += 1

    normalized = [normalize_request_payload(item) for item in fetched_items]
    open_requests = [item for item in normalized if item.get("is_open")]

    return {
        "community": _community_payload(community, community_identifier),
        "requests": open_requests[:max_items],
        "total_fetched": len(fetched_items),
        "open_count": len(open_requests[:max_items]),
    }


def request_matches_filters(item: Dict[str, Any], filters: Dict[str, Any]) -> bool:
    q = str(filters.get("q") or "").strip().lower()
    if q:
        haystack = " ".join(
            [
                str(item.get("request_id") or ""),
                str(item.get("number") or ""),
                str(item.get("title") or ""),
                str(item.get("type") or ""),
                str(item.get("status") or ""),
                str(item.get("topic_record") or ""),
                str((item.get("created_by") or {}).get("user") or ""),
                str((item.get("receiver") or {}).get("user") or ""),
            ]
        ).lower()
        if q not in haystack:
            return False

    request_type = str(filters.get("request_type") or "").strip().lower()
    if request_type and str(item.get("type") or "").strip().lower() != request_type:
        return False

    created_from = filters.get("created_from")
    created_at = _parse_iso_datetime(item.get("created"))
    if created_from and (created_at is None or created_at < created_from):
        return False

    created_to = filters.get("created_to")
    if created_to and (created_at is None or created_at > created_to):
        return False

    updated_from = filters.get("updated_from")
    updated_at = _parse_iso_datetime(item.get("updated"))
    if updated_from and (updated_at is None or updated_at < updated_from):
        return False

    updated_to = filters.get("updated_to")
    if updated_to and (updated_at is None or updated_at > updated_to):
        return False

    return bool(item.get("is_open")) and bool(item.get("is_actionable"))


def perform_request_action(request_id: str, action: str, *, note: str | None = None, wait_callback=None) -> Dict[str, Any]:
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"accept", "decline"}:
        raise ValueError("action must be 'accept' or 'decline'")

    request_identifier = str(request_id or "").strip()
    if not request_identifier:
        raise ValueError("request_id is required")

    payload = None
    note_text = str(note or "").strip()
    if note_text:
        payload = {"payload": {"content": note_text, "format": "html"}}

    response = make_rate_limited_request(
        "POST",
        f"{ZENODO_PRODUCTION_BASE_URL}/api/requests/{request_identifier}/actions/{normalized_action}",
        params=get_zenodo_production_api_params(),
        json=payload,
        timeout=60,
        wait_callback=wait_callback,
    )
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise ValueError("Unexpected Zenodo action response format")
    return normalize_request_payload(result)
