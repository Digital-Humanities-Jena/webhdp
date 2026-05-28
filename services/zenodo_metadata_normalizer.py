import json
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

ZENODO_ALLOWED_METADATA_FIELDS = {
    "upload_type",
    "publication_type",
    "image_type",
    "publication_date",
    "title",
    "creators",
    "description",
    "access_right",
    "license",
    "embargo_date",
    "access_conditions",
    "doi",
    "prereserve_doi",
    "keywords",
    "notes",
    "related_identifiers",
    "contributors",
    "references",
    "communities",
    "grants",
    "journal_title",
    "journal_volume",
    "journal_issue",
    "journal_pages",
    "conference_title",
    "conference_acronym",
    "conference_dates",
    "conference_place",
    "conference_url",
    "conference_session",
    "conference_session_part",
    "imprint_publisher",
    "imprint_isbn",
    "imprint_place",
    "partof_title",
    "partof_pages",
    "thesis_supervisors",
    "thesis_university",
    "subjects",
    "version",
    "language",
    "locations",
    "dates",
    "method",
}
ZENODO_LIST_FIELDS = {
    "creators",
    "contributors",
    "subjects",
    "related_identifiers",
    "communities",
    "grants",
    "keywords",
    "references",
    "locations",
    "dates",
    "thesis_supervisors",
}
ZENODO_UPLOAD_TYPES = {
    "publication",
    "poster",
    "presentation",
    "dataset",
    "image",
    "video",
    "software",
    "lesson",
    "physicalobject",
    "other",
}
ZENODO_ACCESS_RIGHTS = {"open", "embargoed", "restricted", "closed"}


def normalize_publication_date(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        return value

    candidate = value.strip()
    if not candidate:
        return candidate

    if re.match(r"^\d{4}-\d{2}-\d{2}$", candidate):
        return candidate

    match = re.match(r"^(\d{4}-\d{2}-\d{2})(?:[T\s].*)?$", candidate)
    if match:
        return match.group(1)

    try:
        return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return candidate


def _is_valid_yyyy_mm_dd(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _coerce_json_string(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return value
    if not (stripped.startswith("[") or stripped.startswith("{")):
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def _to_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        parsed = _coerce_json_string(value)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
        return [token.strip() for token in re.split(r"[;,]", value) if token.strip()]
    return [value]


def _as_named_objects(values: List[Any], key: str) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for item in values:
        if isinstance(item, dict):
            if item.get(key):
                result.append(item)
            continue
        text = str(item).strip()
        if text:
            result.append({key: text})
    return result


def _normalize_list_field(field: str, value: Any) -> Any:
    value = _coerce_json_string(value)
    if field not in ZENODO_LIST_FIELDS:
        return value

    as_list = _to_list(value)
    if field in {"creators", "contributors", "thesis_supervisors"}:
        return _as_named_objects(as_list, "name")
    if field == "communities":
        return _as_named_objects(as_list, "identifier")
    if field == "subjects":
        return _as_named_objects(as_list, "term")
    if field == "locations":
        return _as_named_objects(as_list, "place")
    if field == "grants":
        return _as_named_objects(as_list, "id")
    return [item for item in as_list if item not in (None, "", [])]


def normalize_zenodo_metadata(
    metadata: Dict[str, Any],
    *,
    apply_defaults: bool = False,
    fallback_title: Optional[str] = None,
    fallback_description: Optional[str] = None,
    fallback_creators: Optional[Any] = None,
) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}

    for key, value in (metadata or {}).items():
        if key not in ZENODO_ALLOWED_METADATA_FIELDS:
            continue
        normalized[key] = _normalize_list_field(key, value)

    if "publication_date" in normalized:
        normalized["publication_date"] = normalize_publication_date(normalized["publication_date"])

    if "access_right" in normalized and isinstance(normalized["access_right"], str):
        normalized["access_right"] = normalized["access_right"].strip().lower()
    if "upload_type" in normalized and isinstance(normalized["upload_type"], str):
        normalized["upload_type"] = normalized["upload_type"].strip().lower()

    creators = normalized.get("creators")
    if isinstance(creators, list):
        normalized["creators"] = _as_named_objects(creators, "name")

    communities = normalized.get("communities")
    if isinstance(communities, list):
        normalized["communities"] = _as_named_objects(communities, "identifier")

    if apply_defaults:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if not normalized.get("title"):
            normalized["title"] = fallback_title or "Untitled"
        if not normalized.get("description"):
            normalized["description"] = fallback_description or "No description provided."
        if normalized.get("upload_type") not in ZENODO_UPLOAD_TYPES:
            normalized["upload_type"] = "dataset"
        if not _is_valid_yyyy_mm_dd(normalized.get("publication_date")):
            normalized["publication_date"] = today
        if normalized.get("access_right") not in ZENODO_ACCESS_RIGHTS:
            normalized["access_right"] = "open"
        if not normalized.get("creators"):
            fallback_named_creators = _as_named_objects(_to_list(fallback_creators), "name")
            normalized["creators"] = fallback_named_creators or [{"name": "Unknown"}]

        if normalized.get("access_right") in {"open", "embargoed"} and not normalized.get("license"):
            normalized["license"] = "cc-by-4.0"
        if "embargo_date" in normalized:
            normalized["embargo_date"] = normalize_publication_date(normalized.get("embargo_date"))
        if normalized.get("access_right") == "embargoed":
            embargo_date = normalized.get("embargo_date")
            if not _is_valid_yyyy_mm_dd(embargo_date):
                normalized["access_right"] = "open"
                normalized.pop("embargo_date", None)
            else:
                if datetime.strptime(embargo_date, "%Y-%m-%d").date() <= datetime.utcnow().date():
                    normalized["access_right"] = "open"
                    normalized.pop("embargo_date", None)
        if normalized.get("access_right") == "restricted" and not normalized.get("access_conditions"):
            normalized["access_conditions"] = "Available upon request."
        if normalized.get("upload_type") == "publication" and not normalized.get("publication_type"):
            normalized["publication_type"] = "article"
        if normalized.get("upload_type") == "image" and not normalized.get("image_type"):
            normalized["image_type"] = "figure"

    return normalized
