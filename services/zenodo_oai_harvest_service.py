from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import shutil
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from flask import current_app

from database.database import db
from database.models import Session as DBSession, User
from services.hdpc_schema_service import connect_hdpc, ensure_hdpc_schema
from services.notification_service import notify_user
from services.zenodo_account_retrieval_service import (
    DEFAULT_SHARD_RECORD_LIMIT,
    DETECTOR_PRESETS,
    MODEL_FILE_EXTENSIONS,
)
from services.zenodo_oai_harvest_history_service import get_harvest_entry, update_harvest_entry

logger = logging.getLogger(__name__)

OAI_HARVEST_RECORD_ORIGIN = "zenodo_oai_harvest"
OAI_HARVEST_SESSION_ORIGIN = "zenodo_oai_harvest"
DEFAULT_OAI_BASE_URL = "https://zenodo.org/oai2d"
DEFAULT_OAI_SET_SPEC = "user-3dbigdataspace"
DEFAULT_OAI_METADATA_PREFIX = "oai_datacite"
DEFAULT_OAI_REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_OAI_REQUEST_RETRIES = 2
DEFAULT_OAI_MIN_INTERVAL_SECONDS = 2.05
DEFAULT_OAI_PAGE_SIZE = 50
MAX_RECORDS_CEILING = 1_000_000

OAI_NS = "http://www.openarchives.org/OAI/2.0/"


class ZenodoOaiHarvestPaused(Exception):
    pass


class ZenodoOaiHarvestCancelled(Exception):
    pass


class _SyntheticOaiResponse:
    def __init__(self, *, status_code: int, text: str, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Zenodo OAI request failed: {self.text}", response=self)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _local_name(tag: str) -> str:
    return str(tag or "").split("}", 1)[-1]


def _text(element: ET.Element | None) -> str:
    return "".join(element.itertext()).strip() if element is not None else ""


def _first_text(root: ET.Element | None, name: str) -> str:
    if root is None:
        return ""
    for element in root.iter():
        if _local_name(element.tag) == name:
            return _text(element)
    return ""


def _children_by_local(root: ET.Element | None, name: str) -> list[ET.Element]:
    if root is None:
        return []
    return [element for element in root.iter() if _local_name(element.tag) == name]


def _child_text(parent: ET.Element | None, name: str) -> str:
    if parent is None:
        return ""
    for child in list(parent):
        if _local_name(child.tag) == name:
            return _text(child)
    return ""


def _xml_string(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return ET.tostring(element, encoding="unicode")


def _parse_dt(value: Any, fallback: datetime | None = None) -> datetime:
    text = str(value or "").strip()
    if not text:
        return fallback or datetime(1970, 1, 1, tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.fromisoformat(f"{text[:10]}T00:00:00+00:00")
        except ValueError:
            return fallback or datetime(1970, 1, 1, tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_query_dt(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _max_iso(left: Any, right: Any) -> str | None:
    left_dt = _parse_dt(left, None) if left else None
    right_dt = _parse_dt(right, None) if right else None
    if left_dt and right_dt:
        return _format_query_dt(max(left_dt, right_dt))
    if right_dt:
        return _format_query_dt(right_dt)
    if left_dt:
        return _format_query_dt(left_dt)
    return None


def _min_iso(left: Any, right: Any) -> str | None:
    left_dt = _parse_dt(left, None) if left else None
    right_dt = _parse_dt(right, None) if right else None
    if left_dt and right_dt:
        return _format_query_dt(min(left_dt, right_dt))
    if right_dt:
        return _format_query_dt(right_dt)
    if left_dt:
        return _format_query_dt(left_dt)
    return None


def normalize_oai_datetime(value: Any, *, is_end: bool = False) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        text = f"{text}{'T23:59:59Z' if is_end else 'T00:00:00Z'}"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception as exc:
        raise ValueError("OAI date window values must be ISO dates or datetimes") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return _format_query_dt(parsed)


def normalize_oai_max_records(value: Any) -> int | None:
    if value in (None, ""):
        return None
    normalized = int(value)
    if normalized < 1:
        raise ValueError("max_records must be at least 1")
    if normalized > MAX_RECORDS_CEILING:
        raise ValueError(f"max_records must be {MAX_RECORDS_CEILING} or lower")
    return normalized


def normalize_oai_set_spec(value: Any) -> str:
    text = str(value or DEFAULT_OAI_SET_SPEC).strip()
    if not text:
        return DEFAULT_OAI_SET_SPEC
    if not text.startswith("user-"):
        text = f"user-{text}"
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", text):
        raise ValueError("set_spec contains unsupported characters")
    return text


def normalize_oai_metadata_prefix(value: Any) -> str:
    text = str(value or DEFAULT_OAI_METADATA_PREFIX).strip()
    if text not in {"oai_datacite", "oai_datacite4", "datacite", "datacite4", "oai_dc", "dcat"}:
        raise ValueError("metadata_prefix must be one of oai_datacite, oai_datacite4, datacite, datacite4, oai_dc, or dcat")
    return text


def community_identifier_from_set_spec(value: str) -> str:
    text = str(value or "").strip()
    return text[5:] if text.startswith("user-") else text


class RateLimitedOaiClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_OAI_BASE_URL,
        http: Any = requests,
        sleep_func: Any = time.sleep,
        min_interval_seconds: float = DEFAULT_OAI_MIN_INTERVAL_SECONDS,
        request_timeout_seconds: float = DEFAULT_OAI_REQUEST_TIMEOUT_SECONDS,
        request_retries: int = DEFAULT_OAI_REQUEST_RETRIES,
    ):
        self.base_url = str(base_url or DEFAULT_OAI_BASE_URL).rstrip("/")
        self.http = http
        self.sleep_func = sleep_func
        self.min_interval_seconds = float(min_interval_seconds)
        self.request_timeout_seconds = max(1.0, float(request_timeout_seconds or DEFAULT_OAI_REQUEST_TIMEOUT_SECONDS))
        self.request_retries = max(0, int(request_retries or 0))
        self._last_request_at = 0.0
        self.rate_limited_waits = 0
        self.wait_seconds = 0.0

    def _wait(self, seconds: float) -> None:
        seconds = max(float(seconds or 0), 0)
        if seconds <= 0:
            return
        self.rate_limited_waits += 1
        self.wait_seconds += seconds
        self.sleep_func(seconds)

    def request(self, params: dict[str, Any]):
        elapsed = time.monotonic() - self._last_request_at
        if self.min_interval_seconds > 0 and self._last_request_at and elapsed < self.min_interval_seconds:
            self._wait(self.min_interval_seconds - elapsed)
        last_error = ""
        clean_params = {key: value for key, value in params.items() if value not in (None, "")}
        for attempt in range(self.request_retries + 1):
            try:
                response = self.http.get(self.base_url, params=clean_params, timeout=self.request_timeout_seconds)
            except (requests.Timeout, requests.ConnectionError) as exc:
                self._last_request_at = time.monotonic()
                last_error = str(exc)
                if attempt < self.request_retries:
                    self._wait(min(10, 1 + attempt * 2))
                    continue
                return _SyntheticOaiResponse(status_code=504, text=last_error or "Zenodo OAI request timed out")
            self._last_request_at = time.monotonic()
            if response.status_code == 429:
                self._wait(_to_int(response.headers.get("Retry-After"), 60))
                continue
            if response.status_code >= 500 and attempt < self.request_retries:
                self._wait(min(10, 1 + attempt * 2))
                continue
            return response
        return _SyntheticOaiResponse(status_code=504, text=last_error or "Zenodo OAI request failed after retries")


def parse_oai_response(xml_text: str) -> dict[str, Any]:
    root = ET.fromstring(xml_text)
    errors = []
    for error in root.findall(f".//{{{OAI_NS}}}error"):
        errors.append({"code": error.attrib.get("code"), "message": _text(error)})
    records = []
    for record in root.findall(f".//{{{OAI_NS}}}ListRecords/{{{OAI_NS}}}record"):
        records.append(parse_oai_record(record))
    token_el = root.find(f".//{{{OAI_NS}}}ListRecords/{{{OAI_NS}}}resumptionToken")
    token = _text(token_el)
    return {
        "errors": errors,
        "records": records,
        "resumption_token": token or None,
        "complete_list_size": _to_int(token_el.attrib.get("completeListSize"), 0) if token_el is not None else 0,
        "cursor": _to_int(token_el.attrib.get("cursor"), 0) if token_el is not None else 0,
    }


def parse_oai_record(record_el: ET.Element) -> dict[str, Any]:
    header = record_el.find(f"{{{OAI_NS}}}header")
    metadata_el = record_el.find(f"{{{OAI_NS}}}metadata")
    metadata_payload = next(iter(list(metadata_el)), metadata_el) if metadata_el is not None and list(metadata_el) else metadata_el
    identifier = _child_text(header, "identifier")
    datestamp = _child_text(header, "datestamp")
    set_specs = [_text(item) for item in list(header or []) if _local_name(item.tag) == "setSpec"]
    deleted = header is not None and str(header.attrib.get("status") or "").lower() == "deleted"
    normalized_metadata = normalize_oai_metadata_payload(metadata_payload, set_specs=set_specs, identifier=identifier, datestamp=datestamp)
    return {
        "oai_identifier": identifier,
        "oai_datestamp": datestamp,
        "oai_set_specs": set_specs,
        "deleted": deleted,
        "metadata": normalized_metadata,
        "raw_xml": _xml_string(record_el),
    }


def _attribute(element: ET.Element | None, name: str) -> str:
    if element is None:
        return ""
    for key, value in element.attrib.items():
        if _local_name(key) == name:
            return str(value or "").strip()
    return ""


def _element_value(element: ET.Element | None) -> str:
    text = _text(element)
    if text:
        return text
    for key, value in (element.attrib.items() if element is not None else []):
        if _local_name(key) in {"resource", "about"} and str(value or "").strip():
            return str(value).strip()
    return ""


def _first_value(root: ET.Element | None, name: str) -> str:
    if root is None:
        return ""
    for element in root.iter():
        if _local_name(element.tag) == name:
            return _element_value(element)
    return ""


def normalize_oai_metadata_payload(
    metadata_el: ET.Element | None,
    *,
    set_specs: list[str],
    identifier: str,
    datestamp: str,
) -> dict[str, Any]:
    title = _first_text(metadata_el, "title") or identifier
    descriptions = [_text(item) for item in _children_by_local(metadata_el, "description") if _text(item)]
    subjects = [_text(item) for item in _children_by_local(metadata_el, "subject") if _text(item)]
    creators = []
    for creator in _children_by_local(metadata_el, "creator"):
        name = _first_text(creator, "creatorName") or _first_text(creator, "name") or _text(creator)
        if name:
            creators.append({"name": name})
    if not creators:
        for creator in _children_by_local(metadata_el, "creatorName"):
            name = _text(creator)
            if name:
                creators.append({"name": name})
    identifier_value = ""
    for item in _children_by_local(metadata_el, "identifier"):
        if _attribute(item, "identifierType").upper() == "DOI":
            identifier_value = _text(item)
            break
    if not identifier_value:
        identifier_value = _first_text(metadata_el, "identifier")
    rights = []
    for item in _children_by_local(metadata_el, "rights"):
        text = _text(item)
        if not text:
            continue
        rights.append(
            {
                "title": text,
                "rights_uri": _attribute(item, "rightsURI"),
                "rights_identifier": _attribute(item, "rightsIdentifier"),
            }
        )
    related_identifiers = []
    for item in _children_by_local(metadata_el, "relatedIdentifier"):
        text = _text(item)
        if text:
            related_identifiers.append(
                {
                    "identifier": text,
                    "relation_type": _attribute(item, "relationType"),
                    "identifier_type": _attribute(item, "relatedIdentifierType"),
                }
            )
    resource_type_el = _children_by_local(metadata_el, "resourceType")
    resource_type = _text(resource_type_el[0]) if resource_type_el else ""
    resource_type_general = _attribute(resource_type_el[0], "resourceTypeGeneral") if resource_type_el else ""
    communities = [{"identifier": community_identifier_from_set_spec(item)} for item in set_specs if item.startswith("user-")]
    files = extract_dcat_files(metadata_el)
    metadata = {
        "title": title,
        "creators": creators,
        "description": descriptions[0] if descriptions else "",
        "descriptions": descriptions,
        "keywords": subjects,
        "subjects": subjects,
        "doi": identifier_value if identifier_value.lower().startswith("10.") else "",
        "publication_date": _first_text(metadata_el, "publicationYear") or datestamp[:10],
        "publisher": _first_text(metadata_el, "publisher"),
        "upload_type": "dataset",
        "resource_type": {
            "title": resource_type,
            "type": resource_type_general,
        },
        "rights": rights,
        "license": rights[0] if rights else None,
        "related_identifiers": related_identifiers,
        "communities": communities,
    }
    return {
        "id": _extract_zenodo_recid(identifier) or identifier,
        "oai_identifier": identifier,
        "oai_datestamp": datestamp,
        "oai_set_specs": set_specs,
        "doi": metadata.get("doi") or None,
        "title": title,
        "metadata": metadata,
        "files": files,
        "links": {
            "html": f"https://zenodo.org/records/{_extract_zenodo_recid(identifier)}" if _extract_zenodo_recid(identifier) else "",
        },
    }


def extract_dcat_files(metadata_el: ET.Element | None) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    if metadata_el is None:
        return files
    for distribution in _children_by_local(metadata_el, "Distribution"):
        access_url = _first_value(distribution, "accessURL") or _first_value(distribution, "downloadURL")
        title = _first_text(distribution, "title") or os.path.basename(str(access_url).rstrip("/")) or f"distribution_{len(files) + 1}"
        if access_url:
            files.append(
                {
                    "filename": title,
                    "key": title,
                    "links": {"content": access_url},
                    "type": _first_value(distribution, "mediaType") or _first_value(distribution, "format"),
                    "size": _to_int(_first_text(distribution, "byteSize"), 0),
                }
            )
    return files


def _extract_zenodo_recid(identifier: str) -> str | None:
    match = re.search(r"(\d+)$", str(identifier or ""))
    return match.group(1) if match else None


def _record_seen_key(record: dict[str, Any], metadata_prefix: str) -> str:
    return f"{metadata_prefix}:{record.get('oai_identifier')}:{record.get('oai_datestamp')}"


def _update_summary_temporal_bounds(summary: dict[str, Any], records: list[dict[str, Any]]) -> None:
    for record in records:
        datestamp = record.get("oai_datestamp")
        summary["latest_datestamp"] = _max_iso(summary.get("latest_datestamp"), datestamp)
        summary["earliest_datestamp"] = _min_iso(summary.get("earliest_datestamp"), datestamp)


def _coverage_summary(summary: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "earliest_datestamp": summary.get("earliest_datestamp"),
        "latest_datestamp": summary.get("latest_datestamp"),
        "record_count": int(summary.get("harvested_records") or 0),
        "shard_count": len([item for item in (manifest.get("shards") or []) if isinstance(item, dict)]),
        "duplicate_records_skipped": int(summary.get("duplicate_records_skipped") or 0),
        "rate_limited_waits": int(summary.get("rate_limited_waits") or 0),
    }


class ZenodoOaiHarvestRunner:
    def __init__(
        self,
        *,
        harvest_id: str,
        requester: User,
        http: Any = requests,
        sleep_func: Any = time.sleep,
        request_timeout_seconds: float = DEFAULT_OAI_REQUEST_TIMEOUT_SECONDS,
        request_retries: int = DEFAULT_OAI_REQUEST_RETRIES,
    ):
        self.harvest_id = harvest_id
        self.requester = requester
        self.http = http
        self.sleep_func = sleep_func
        self.request_timeout_seconds = request_timeout_seconds
        self.request_retries = request_retries
        self.client: RateLimitedOaiClient | None = None
        self.current_shard_records: list[dict[str, Any]] = []

    def run(self, *, task_self: Any = None) -> dict[str, Any]:
        entry = get_harvest_entry(self.harvest_id) or {}
        options = entry.get("options") if isinstance(entry.get("options"), dict) else {}
        base_url = str(options.get("base_url") or DEFAULT_OAI_BASE_URL).rstrip("/")
        set_spec = normalize_oai_set_spec(options.get("set_spec"))
        metadata_prefix = normalize_oai_metadata_prefix(options.get("metadata_prefix"))
        max_records = normalize_oai_max_records(options.get("max_records"))
        from_datetime = options.get("from_datetime")
        until_datetime = options.get("until_datetime")
        checkpoint = entry.get("checkpoint") if isinstance(entry.get("checkpoint"), dict) else {}
        manifest = entry.get("manifest") if isinstance(entry.get("manifest"), dict) else {"harvest_id": self.harvest_id, "shards": []}
        manifest.update({"base_url": base_url, "set_spec": set_spec, "metadata_prefix": metadata_prefix})
        seen_keys = {str(item) for item in (checkpoint.get("seen_keys") or []) if str(item or "").strip()}
        resumption_token = checkpoint.get("resumption_token")
        summary = dict(entry.get("summary") or {})
        summary.setdefault("harvested_records", 0)
        summary.setdefault("created_shards", len(manifest.get("shards") or []))
        summary.setdefault("pages_retrieved", 0)
        summary.setdefault("failed_pages", 0)
        summary.setdefault("duplicate_records_skipped", 0)
        summary.setdefault("rate_limited_waits", 0)
        summary.setdefault("wait_seconds", 0)
        summary.setdefault("latest_datestamp", None)
        summary.setdefault("earliest_datestamp", None)
        summary["max_records"] = max_records
        summary.setdefault("limit_reached", False)
        self.client = RateLimitedOaiClient(
            base_url=base_url,
            http=self.http,
            sleep_func=self.sleep_func,
            request_timeout_seconds=self.request_timeout_seconds,
            request_retries=self.request_retries,
        )
        update_harvest_entry(
            self.harvest_id,
            runtime={"process": {"pid": os.getpid(), "status": "running", "started_at": _utc_now_iso()}},
            heartbeat=True,
        )
        try:
            while True:
                self._check_control()
                if max_records is not None and int(summary.get("harvested_records") or 0) >= max_records:
                    summary["limit_reached"] = True
                    break
                params = {"verb": "ListRecords"}
                if resumption_token:
                    params["resumptionToken"] = resumption_token
                else:
                    params.update({"metadataPrefix": metadata_prefix, "set": set_spec, "from": from_datetime, "until": until_datetime})
                response = self.client.request(params)
                if response.status_code == 422 and resumption_token:
                    resumption_token = None
                    summary["expired_resumption_tokens"] = int(summary.get("expired_resumption_tokens") or 0) + 1
                    self._persist(task_self, manifest, summary, resumption_token, seen_keys, "Restarting expired OAI resumption token")
                    continue
                response.raise_for_status()
                parsed = parse_oai_response(response.text)
                if parsed["errors"]:
                    codes = {str(item.get("code") or "") for item in parsed["errors"]}
                    if "noRecordsMatch" in codes:
                        break
                    raise ValueError(f"Zenodo OAI error: {parsed['errors']}")
                fetched: list[dict[str, Any]] = []
                for record in parsed["records"]:
                    if record.get("deleted"):
                        continue
                    key = _record_seen_key(record, metadata_prefix)
                    if key in seen_keys:
                        summary["duplicate_records_skipped"] = int(summary.get("duplicate_records_skipped") or 0) + 1
                        continue
                    if max_records is not None and int(summary.get("harvested_records") or 0) + len(fetched) >= max_records:
                        break
                    seen_keys.add(key)
                    fetched.append(record)
                if fetched:
                    _update_summary_temporal_bounds(summary, fetched)
                    self.current_shard_records.extend(fetched)
                    summary["harvested_records"] = int(summary.get("harvested_records") or 0) + len(fetched)
                    shard = self._flush_shard(
                        manifest,
                        {
                            "base_url": base_url,
                            "set_spec": set_spec,
                            "metadata_prefix": metadata_prefix,
                            "from": from_datetime,
                            "until": until_datetime,
                            "resumption_cursor": parsed.get("cursor"),
                            "artifact_granularity": "oai_page_checkpoint",
                        },
                    )
                    if shard:
                        summary["created_shards"] = len(manifest.get("shards") or [])
                summary["pages_retrieved"] = int(summary.get("pages_retrieved") or 0) + 1
                summary["rate_limited_waits"] = self.client.rate_limited_waits
                resumption_token = parsed.get("resumption_token")
                self._persist(task_self, manifest, summary, resumption_token, seen_keys, "Harvesting Zenodo OAI records")
                if not resumption_token:
                    break
            if self.current_shard_records:
                self._flush_shard(manifest, {"base_url": base_url, "set_spec": set_spec, "metadata_prefix": metadata_prefix})
            summary["created_shards"] = len(manifest.get("shards") or [])
            summary["rate_limited_waits"] = self.client.rate_limited_waits
            summary["wait_seconds"] = round(float(self.client.wait_seconds), 3)
            summary["coverage_summary"] = _coverage_summary(summary, manifest)
            progress = self._progress(summary, resumption_token)
            update_harvest_entry(
                self.harvest_id,
                state="SUCCESS",
                status="completed: maximum record limit reached" if summary.get("limit_reached") else "completed",
                progress=progress,
                checkpoint={"resumption_token": None, "seen_count": len(seen_keys)},
                manifest=manifest,
                summary=summary,
                error="",
                runtime={"process": {"pid": os.getpid(), "status": "exited", "exit_code": 0, "finished_at": _utc_now_iso()}},
                collection={"coverage_summary": summary["coverage_summary"]},
                heartbeat=True,
            )
            result = {"status": "completed", "harvest_id": self.harvest_id, "progress": progress, "summary": summary, "manifest": manifest}
            if task_self is not None:
                task_self.update_state(state="SUCCESS", meta={"status": "completed", "progress": progress, "result": result})
            self._notify_final_state(status="completed", title="Zenodo OAI harvest completed", body=f"Harvested {summary.get('harvested_records')} OAI records.", severity="success", summary=summary)
            db.session.commit()
            return result
        except ZenodoOaiHarvestPaused:
            summary["coverage_summary"] = _coverage_summary(summary, manifest)
            update_harvest_entry(
                self.harvest_id,
                state="PAUSED",
                status="paused",
                progress=self._progress(summary, resumption_token),
                checkpoint={"resumption_token": resumption_token, "seen_keys": sorted(seen_keys), "seen_count": len(seen_keys)},
                manifest=manifest,
                summary=summary,
                runtime={"process": {"pid": os.getpid(), "status": "paused", "updated_at": _utc_now_iso()}},
                heartbeat=True,
            )
            return {"status": "paused", "harvest_id": self.harvest_id, "summary": summary, "manifest": manifest}
        except ZenodoOaiHarvestCancelled:
            summary["coverage_summary"] = _coverage_summary(summary, manifest)
            update_harvest_entry(self.harvest_id, state="CANCELLED", status="cancelled", checkpoint={"resumption_token": resumption_token, "seen_keys": sorted(seen_keys), "seen_count": len(seen_keys)}, manifest=manifest, summary=summary, heartbeat=True)
            self._notify_final_state(status="cancelled", title="Zenodo OAI harvest cancelled", body="The Zenodo OAI harvest was cancelled.", severity="warning", summary=summary)
            db.session.commit()
            return {"status": "cancelled", "harvest_id": self.harvest_id, "summary": summary, "manifest": manifest}
        except Exception as exc:
            logger.error("Zenodo OAI harvest %s failed: %s", self.harvest_id, exc, exc_info=True)
            summary["coverage_summary"] = _coverage_summary(summary, manifest)
            update_harvest_entry(self.harvest_id, state="FAILURE", status=str(exc), checkpoint={"resumption_token": resumption_token, "seen_keys": sorted(seen_keys), "seen_count": len(seen_keys)}, manifest=manifest, summary=summary, error=str(exc), runtime={"process": {"pid": os.getpid(), "status": "exited", "exit_code": 1, "finished_at": _utc_now_iso()}}, heartbeat=True)
            self._notify_final_state(status="failed", title="Zenodo OAI harvest failed", body=str(exc), severity="error", summary=summary)
            db.session.commit()
            raise

    def _check_control(self) -> None:
        entry = get_harvest_entry(self.harvest_id) or {}
        control = entry.get("control") if isinstance(entry.get("control"), dict) else {}
        if control.get("cancel_requested"):
            raise ZenodoOaiHarvestCancelled()
        if control.get("pause_requested"):
            raise ZenodoOaiHarvestPaused()

    def _persist(self, task_self: Any, manifest: dict[str, Any], summary: dict[str, Any], resumption_token: str | None, seen_keys: set[str], status: str) -> None:
        if self.client:
            summary["wait_seconds"] = round(float(self.client.wait_seconds), 3)
        progress = self._progress(summary, resumption_token)
        update_harvest_entry(
            self.harvest_id,
            state="PROGRESS",
            status=status,
            progress=progress,
            checkpoint={"resumption_token": resumption_token, "seen_keys": sorted(seen_keys), "seen_count": len(seen_keys)},
            manifest=manifest,
            summary=summary,
            heartbeat=True,
        )
        if task_self is not None:
            task_self.update_state(state="PROGRESS", meta={"status": status, "progress": progress})

    def _progress(self, summary: dict[str, Any], resumption_token: str | None) -> dict[str, Any]:
        entry = get_harvest_entry(self.harvest_id) or {}
        started_at = _parse_dt(entry.get("created_at"), _utc_now())
        elapsed_seconds = max((_utc_now() - started_at).total_seconds(), 1)
        harvested = int(summary.get("harvested_records") or 0)
        pages = int(summary.get("pages_retrieved") or 0)
        max_records = summary.get("max_records")
        percent = 100 if not resumption_token else 0
        if max_records:
            percent = int(min(99 if resumption_token else 100, round((harvested / max(int(max_records), 1)) * 100)))
        return {
            "total_records": harvested,
            "harvested_records": harvested,
            "pages_retrieved": pages,
            "created_shards": int(summary.get("created_shards") or 0),
            "duplicate_records_skipped": int(summary.get("duplicate_records_skipped") or 0),
            "rate_limited_waits": self.client.rate_limited_waits if self.client else int(summary.get("rate_limited_waits") or 0),
            "percent": percent,
            "current_resumption_token": bool(resumption_token),
            "max_records": max_records,
            "limit_reached": bool(summary.get("limit_reached")),
            "wait_seconds": float(summary.get("wait_seconds") or 0),
            "records_per_hour": int((harvested / elapsed_seconds) * 3600),
            "pages_per_hour": int((pages / elapsed_seconds) * 3600),
            "latest_datestamp": summary.get("latest_datestamp"),
        }

    def _flush_shard(self, manifest: dict[str, Any], window: dict[str, Any]) -> dict[str, Any] | None:
        if not self.current_shard_records:
            return None
        shard_index = len(manifest.get("shards") or []) + 1
        records = list(self.current_shard_records)
        self.current_shard_records = []
        shard = write_oai_harvest_shard(
            harvest_id=self.harvest_id,
            shard_index=shard_index,
            records=records,
            requested_by=self.requester,
            window=window,
            manifest_summary={
                "harvest_id": self.harvest_id,
                "shard_index": shard_index,
                "record_count": len(records),
                "base_url": window.get("base_url"),
                "set_spec": window.get("set_spec"),
                "metadata_prefix": window.get("metadata_prefix"),
                "sync_mode": manifest.get("sync_mode") or "full",
                "parent_harvest_id": manifest.get("parent_harvest_id"),
            },
        )
        manifest.setdefault("shards", []).append(shard)
        return shard

    def _notify_final_state(self, *, status: str, title: str, body: str, severity: str, summary: dict[str, Any] | None = None) -> None:
        notify_user(
            recipient_user_id=self.requester.id,
            notification_type=f"zenodo.oai_harvest_{status}",
            category="zenodo",
            severity=severity,
            title=title,
            body=body,
            entity_type="zenodo_oai_harvest",
            entity_id=self.harvest_id,
            action_url="/tools/zenodo-oai-harvest",
            payload={"summary": summary or {}},
            dedupe_key=f"zenodo-oai-harvest:{self.harvest_id}:{status}",
        )


def write_oai_harvest_shard(
    *,
    harvest_id: str,
    shard_index: int,
    records: list[dict[str, Any]],
    requested_by: User,
    window: dict[str, Any],
    manifest_summary: dict[str, Any],
) -> dict[str, Any]:
    session_manager = getattr(current_app, "session_manager", None)
    if session_manager is None:
        raise ValueError("Session manager is not configured")
    hdpc_path, _, _, session_dir = session_manager.create_session_dirs()
    conn = connect_hdpc(hdpc_path, timeout=60)
    try:
        project_id = ensure_hdpc_schema(conn, hdpc_path)
        cursor = conn.cursor()
        now = _utc_now_iso()
        _upsert_project_config(cursor, project_id, "oai.kind", "zenodo_oai_harvest")
        _upsert_project_config(cursor, project_id, "oai.harvest_id", harvest_id)
        _upsert_project_config(cursor, project_id, "oai.shard_index", str(shard_index))
        _upsert_project_config(cursor, project_id, "oai.base_url", str(window.get("base_url") or DEFAULT_OAI_BASE_URL))
        _upsert_project_config(cursor, project_id, "oai.set_spec", str(window.get("set_spec") or ""))
        _upsert_project_config(cursor, project_id, "oai.metadata_prefix", str(window.get("metadata_prefix") or ""))
        _upsert_project_config(cursor, project_id, "oai.from", str(window.get("from") or ""))
        _upsert_project_config(cursor, project_id, "oai.until", str(window.get("until") or ""))
        _upsert_project_config(cursor, project_id, "oai.manifest", json.dumps(manifest_summary, sort_keys=True))
        for record_index, raw_record in enumerate(records, start=1):
            record = dict(raw_record)
            payload = dict(record.get("metadata") or {})
            payload["webhdp_oai_harvest"] = {
                "harvest_id": harvest_id,
                "harvest_kind": "zenodo_oai_harvest",
                "shard_index": shard_index,
                "base_url": window.get("base_url"),
                "set_spec": window.get("set_spec"),
                "metadata_prefix": window.get("metadata_prefix"),
                "oai_identifier": record.get("oai_identifier"),
                "oai_datestamp": record.get("oai_datestamp"),
                "oai_set_specs": record.get("oai_set_specs") or [],
                "requested_by": {
                    "user_id": int(requested_by.id),
                    "public_id": requested_by.public_id,
                    "email": requested_by.email,
                    "display_name": requested_by.display_name,
                },
                "retrieved_at": now,
            }
            recid = str(payload.get("id") or record.get("oai_identifier") or "").strip()
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            cursor.execute(
                """
                INSERT INTO zenodo_records (
                    project_id, source_file_id, record_title, record_status, record_metadata_json,
                    creation_api_response, last_publish_api_response, zenodo_record_id, concept_rec_id,
                    zenodo_doi, concept_doi, is_sandbox, created_timestamp, last_updated_timestamp,
                    version, version_rank, previous_record_id, record_origin, last_api_error
                ) VALUES (?, NULL, ?, 'published', ?, ?, ?, ?, NULL, ?, NULL, 0, ?, ?, ?, ?, NULL, ?, NULL)
                """,
                (
                    project_id,
                    str(metadata.get("title") or payload.get("title") or record.get("oai_identifier") or "Untitled OAI record"),
                    json.dumps(payload, sort_keys=True),
                    json.dumps({"harvest_id": harvest_id, "harvested_at": now}, sort_keys=True),
                    json.dumps(payload, sort_keys=True),
                    recid,
                    str(metadata.get("doi") or payload.get("doi") or "") or None,
                    str(record.get("oai_datestamp") or now),
                    str(record.get("oai_datestamp") or now),
                    str(metadata.get("version") or ""),
                    record_index,
                    OAI_HARVEST_RECORD_ORIGIN,
                ),
            )
            local_record_id = int(cursor.lastrowid)
            _upsert_project_config(cursor, project_id, f"oai.identifier.{local_record_id}", str(record.get("oai_identifier") or ""))
            _upsert_project_config(cursor, project_id, f"oai.datestamp.{local_record_id}", str(record.get("oai_datestamp") or ""))
            cursor.execute(
                """
                INSERT INTO zenodo_record_snapshots (record_id, snapshot_stage, http_status, payload_json, created_timestamp)
                VALUES (?, 'oai_pmh_record', 200, ?, ?)
                """,
                (local_record_id, json.dumps({"record": payload, "raw_xml": record.get("raw_xml") or ""}, sort_keys=True), now),
            )
            links = payload.get("links") if isinstance(payload.get("links"), dict) else {}
            for rel, url in links.items():
                if not rel or not url:
                    continue
                cursor.execute(
                    """
                    INSERT INTO zenodo_record_links (record_id, link_rel, link_url, created_timestamp, updated_timestamp)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(record_id, link_rel) DO UPDATE SET link_url = excluded.link_url, updated_timestamp = excluded.updated_timestamp
                    """,
                    (local_record_id, str(rel), str(url), now, now),
                )
            _write_oai_files(cursor, project_id, local_record_id, payload, now)
        conn.commit()
    finally:
        conn.close()

    session = DBSession(
        user_id=int(requested_by.id),
        session_dir=session_dir,
        hdpc_path=hdpc_path,
        status="completed",
        sharing_scope="private",
        credential_preference="user",
        publishing_user_id=int(requested_by.id),
        default_zenodo_environment="production",
        origin_type=OAI_HARVEST_SESSION_ORIGIN,
        access_mode="explorer_only",
        origin_metadata_json=json.dumps(
            {
                "harvest_id": harvest_id,
                "shard_index": shard_index,
                "record_count": len(records),
                "base_url": window.get("base_url"),
                "set_spec": window.get("set_spec"),
                "metadata_prefix": window.get("metadata_prefix"),
                "artifact_kind": "zenodo_oai_harvest_shard",
                "sync_mode": manifest_summary.get("sync_mode") or "full",
                "parent_harvest_id": manifest_summary.get("parent_harvest_id"),
            },
            sort_keys=True,
        ),
        timings="{}",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.session.add(session)
    db.session.commit()
    return {
        "shard_index": shard_index,
        "session_id": int(session.id),
        "hdpc_path": hdpc_path,
        "record_count": len(records),
        "base_url": window.get("base_url"),
        "set_spec": window.get("set_spec"),
        "metadata_prefix": window.get("metadata_prefix"),
        "created_at": session.created_at.isoformat() if session.created_at else None,
    }


def _upsert_project_config(cursor, project_id: int, key: str, value: str) -> None:
    cursor.execute(
        """
        INSERT INTO project_configuration (project_id, config_key, config_value, description)
        VALUES (?, ?, ?, 'Zenodo OAI harvest metadata')
        ON CONFLICT(project_id, config_key) DO UPDATE SET config_value = excluded.config_value
        """,
        (int(project_id), key, value),
    )


def _write_oai_files(cursor, project_id: int, local_record_id: int, payload: dict[str, Any], now: str) -> None:
    files = payload.get("files") if isinstance(payload.get("files"), list) else []
    for index, file_obj in enumerate([item for item in files if isinstance(item, dict)], start=1):
        filename = os.path.basename(str(file_obj.get("filename") or file_obj.get("key") or f"oai_file_{index}").strip()) or f"oai_file_{index}"
        size_value = file_obj.get("size") if file_obj.get("size") is not None else file_obj.get("filesize")
        links = file_obj.get("links") if isinstance(file_obj.get("links"), dict) else {}
        cursor.execute(
            """
            INSERT INTO source_files (
                project_id, absolute_path, relative_path, filename, size_bytes, sha256_hash,
                mime_type, file_type, status, added_timestamp, last_processed_timestamp,
                is_primary_source, pipeline_source, step_source
            ) VALUES (?, NULL, ?, ?, ?, NULL, ?, 'retrieved_file', 'retrieved_metadata_only', ?, ?, 0, 'zenodo_oai_harvest', 'oai_pmh')
            """,
            (project_id, filename, filename, _to_int(size_value, 0), str(file_obj.get("type") or "").strip() or None, now, now),
        )
        file_id = int(cursor.lastrowid)
        cursor.execute(
            """
            INSERT INTO record_files_map (
                record_id, file_id, file_path, file_purpose, zenodo_file_id, zenodo_file_key,
                zenodo_file_checksum, zenodo_file_size, zenodo_file_links_json,
                upload_status, upload_timestamp, upload_response_json
            ) VALUES (?, ?, ?, ?, NULL, ?, NULL, ?, ?, 'retrieved_metadata_only', ?, ?)
            """,
            (
                local_record_id,
                file_id,
                filename,
                "main" if index == 1 else "attached",
                filename,
                _to_int(size_value, 0),
                json.dumps(links, sort_keys=True),
                now,
                json.dumps(file_obj, sort_keys=True),
            ),
        )


def delete_oai_harvest_shards(entry: dict[str, Any]) -> dict[str, Any]:
    manifest = entry.get("manifest") if isinstance(entry.get("manifest"), dict) else {}
    deleted_sessions = 0
    deleted_files = 0
    for shard in list(manifest.get("shards") or []) + list(manifest.get("compacted_shards") or []):
        if not isinstance(shard, dict):
            continue
        session = db.session.get(DBSession, _to_int(shard.get("session_id"), 0))
        if session is None:
            continue
        session_dir = Path(session.session_dir)
        db.session.delete(session)
        deleted_sessions += 1
        db.session.flush()
        if session_dir.is_dir():
            shutil.rmtree(session_dir, ignore_errors=True)
            deleted_files += 1
    db.session.commit()
    return {"deleted_sessions": deleted_sessions, "deleted_files": deleted_files}


def iter_oai_harvest_records(entry: dict[str, Any], *, include_compacted: bool = True):
    manifest = entry.get("manifest") if isinstance(entry.get("manifest"), dict) else {}
    shard_groups = list(manifest.get("shards") or [])
    if include_compacted:
        shard_groups.extend(manifest.get("compacted_shards") or [])
    for shard in shard_groups:
        if not isinstance(shard, dict):
            continue
        hdpc_path = shard.get("hdpc_path")
        if not hdpc_path or not os.path.exists(str(hdpc_path)):
            continue
        conn = connect_hdpc(str(hdpc_path), timeout=30)
        try:
            cursor = conn.cursor()
            rows = cursor.execute(
                """
                SELECT record_id, record_title, record_status, zenodo_record_id, zenodo_doi,
                       concept_rec_id, record_metadata_json, created_timestamp, last_updated_timestamp,
                       record_origin
                FROM zenodo_records
                ORDER BY record_id ASC
                """
            ).fetchall()
            for row in rows:
                metadata = {}
                try:
                    metadata = json.loads(row[6] or "{}")
                except json.JSONDecodeError:
                    metadata = {}
                oai_meta = metadata.get("webhdp_oai_harvest") if isinstance(metadata.get("webhdp_oai_harvest"), dict) else {}
                yield {
                    "local_record_id": row[0],
                    "title": row[1],
                    "status": row[2],
                    "zenodo_record_id": row[3],
                    "doi": row[4],
                    "concept_rec_id": row[5],
                    "created": row[7],
                    "modified": row[8],
                    "record_origin": row[9],
                    "retrieval": oai_meta,
                    "capabilities": {"had_edit_rights": False, "had_version_rights": False},
                    "session_id": shard.get("session_id"),
                    "shard_index": shard.get("shard_index"),
                    "hdpc_path": str(hdpc_path),
                    "metadata": metadata,
                }
        finally:
            conn.close()


def search_oai_harvest_collection(
    entry: dict[str, Any],
    *,
    query: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    normalized_query = str(query or "").strip().lower()
    normalized_status = str(status or "").strip().lower()
    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, int(offset or 0))
    total = 0
    records: list[dict[str, Any]] = []
    for record in iter_oai_harvest_records(entry, include_compacted=False):
        if normalized_status and str(record.get("status") or "").lower() != normalized_status:
            continue
        haystack = " ".join(str(record.get(key) or "") for key in ("title", "zenodo_record_id", "doi", "created", "modified")).lower()
        if normalized_query and normalized_query not in haystack and normalized_query not in json.dumps(record.get("metadata") or {}).lower():
            continue
        total += 1
        if total <= offset:
            continue
        if len(records) < limit:
            public_record = dict(record)
            public_record.pop("metadata", None)
            public_record.pop("hdpc_path", None)
            records.append(public_record)
    return {"records": records, "total": total, "limit": limit, "offset": offset}


def _record_metadata_text(metadata: dict[str, Any]) -> str:
    payload = dict(metadata or {})
    payload.pop("webhdp_oai_harvest", None)
    return json.dumps(payload, sort_keys=True).lower()


def _file_match_names(metadata: dict[str, Any]) -> list[str]:
    matches: list[str] = []
    for file_obj in metadata.get("files") if isinstance(metadata.get("files"), list) else []:
        if not isinstance(file_obj, dict):
            continue
        name = str(file_obj.get("filename") or file_obj.get("key") or "").strip()
        if Path(name).suffix.lower() in MODEL_FILE_EXTENSIONS:
            matches.append(name)
    return matches


def _community_identifiers(metadata: dict[str, Any]) -> list[str]:
    record_metadata = metadata.get("metadata") if isinstance(metadata.get("metadata"), dict) else {}
    communities = record_metadata.get("communities") or metadata.get("communities") or []
    identifiers: list[str] = []
    if isinstance(communities, list):
        for item in communities:
            if isinstance(item, dict) and str(item.get("identifier") or "").strip():
                identifiers.append(str(item.get("identifier")).strip())
            elif str(item or "").strip():
                identifiers.append(str(item).strip())
    return identifiers


def run_oai_harvest_detector(
    entry: dict[str, Any],
    *,
    detector_id: str,
    target_community: str | None = "3dbigdataspace",
    limit: int = 250,
    offset: int = 0,
) -> dict[str, Any]:
    normalized_detector = str(detector_id or "community_migration_candidates").strip().lower()
    if normalized_detector not in DETECTOR_PRESETS:
        raise ValueError("detector must be one of objaverse, 3d_model_files, missing_target_community, or community_migration_candidates")
    normalized_target = str(target_community or "").strip().lower()
    limit = max(1, min(int(limit or 250), 1000))
    offset = max(0, int(offset or 0))
    total = 0
    candidates: list[dict[str, Any]] = []
    for record in iter_oai_harvest_records(entry, include_compacted=False):
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        text = _record_metadata_text(metadata)
        file_matches = _file_match_names(metadata)
        communities = _community_identifiers(metadata)
        community_set = {item.lower() for item in communities}
        has_objaverse = "objaverse" in text
        has_model_file = bool(file_matches)
        missing_target = bool(normalized_target) and normalized_target not in community_set
        reason = ""
        if normalized_detector == "objaverse" and has_objaverse:
            reason = "Metadata mentions Objaverse."
        elif normalized_detector == "3d_model_files" and has_model_file:
            reason = "Record has 3D model file metadata."
        elif normalized_detector == "missing_target_community" and missing_target:
            reason = f"Record is missing target community {normalized_target}."
        elif normalized_detector == "community_migration_candidates" and missing_target and (has_objaverse or has_model_file):
            signals = []
            if has_objaverse:
                signals.append("Objaverse metadata")
            if has_model_file:
                signals.append("3D model files")
            reason = f"{' and '.join(signals)}; missing target community {normalized_target}."
        if not reason:
            continue
        total += 1
        if total <= offset:
            continue
        if len(candidates) < limit:
            candidates.append(
                {
                    "session_id": record.get("session_id"),
                    "shard_index": record.get("shard_index"),
                    "local_record_id": record.get("local_record_id"),
                    "zenodo_record_id": record.get("zenodo_record_id"),
                    "title": record.get("title"),
                    "status": record.get("status"),
                    "doi": record.get("doi"),
                    "concept_rec_id": record.get("concept_rec_id"),
                    "created": record.get("created"),
                    "modified": record.get("modified"),
                    "had_edit_rights": False,
                    "had_version_rights": False,
                    "reason": reason,
                    "file_matches": file_matches,
                    "communities": communities,
                }
            )
    return {"detector": DETECTOR_PRESETS[normalized_detector], "target_community": normalized_target or None, "candidates": candidates, "total": total, "limit": limit, "offset": offset, "source": "local_oai_harvest_shards"}


def export_oai_harvest_manifest(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "harvest_id": entry.get("harvest_id"),
        "state": entry.get("state"),
        "status": entry.get("status"),
        "options": entry.get("options") or {},
        "summary": entry.get("summary") or {},
        "collection": entry.get("collection") or {},
        "manifest": entry.get("manifest") or {},
    }


def export_oai_harvest_records_csv(entry: dict[str, Any]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["harvest_id", "session_id", "shard_index", "zenodo_record_id", "title", "status", "doi", "created", "modified"])
    writer.writeheader()
    for record in iter_oai_harvest_records(entry, include_compacted=False):
        writer.writerow(
            {
                "harvest_id": entry.get("harvest_id"),
                "session_id": record.get("session_id"),
                "shard_index": record.get("shard_index"),
                "zenodo_record_id": record.get("zenodo_record_id"),
                "title": record.get("title"),
                "status": record.get("status"),
                "doi": record.get("doi"),
                "created": record.get("created"),
                "modified": record.get("modified"),
            }
        )
    return output.getvalue()


def export_oai_harvest_detector_csv(entry: dict[str, Any], *, detector_id: str, target_community: str | None = "3dbigdataspace") -> str:
    result = run_oai_harvest_detector(entry, detector_id=detector_id, target_community=target_community, limit=1000)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["harvest_id", "detector", "target_community", "session_id", "shard_index", "zenodo_record_id", "title", "doi", "created", "modified", "reason", "file_matches", "communities"])
    writer.writeheader()
    for record in result["candidates"]:
        writer.writerow(
            {
                "harvest_id": entry.get("harvest_id"),
                "detector": result["detector"]["id"],
                "target_community": result.get("target_community"),
                "session_id": record.get("session_id"),
                "shard_index": record.get("shard_index"),
                "zenodo_record_id": record.get("zenodo_record_id"),
                "title": record.get("title"),
                "doi": record.get("doi"),
                "created": record.get("created"),
                "modified": record.get("modified"),
                "reason": record.get("reason"),
                "file_matches": ";".join(record.get("file_matches") or []),
                "communities": ";".join(record.get("communities") or []),
            }
        )
    return output.getvalue()


def build_oai_harvest_shard_archive(entry: dict[str, Any], destination_path: str) -> dict[str, Any]:
    manifest = entry.get("manifest") if isinstance(entry.get("manifest"), dict) else {}
    shard_count = 0
    with zipfile.ZipFile(destination_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(export_oai_harvest_manifest(entry), indent=2, sort_keys=True))
        archive.writestr("records.csv", export_oai_harvest_records_csv(entry))
        for shard in manifest.get("shards") or []:
            if not isinstance(shard, dict) or not shard.get("hdpc_path"):
                continue
            hdpc_path = str(shard.get("hdpc_path"))
            if not os.path.exists(hdpc_path):
                continue
            shard_count += 1
            archive.write(hdpc_path, f"shards/shard_{int(shard.get('shard_index') or shard_count):05d}.hdpc")
    return {"archive_path": destination_path, "shard_count": shard_count}


def compact_oai_harvest_shards(entry: dict[str, Any], *, target_records_per_shard: int = DEFAULT_SHARD_RECORD_LIMIT) -> dict[str, Any]:
    if str(entry.get("state") or "").upper() != "SUCCESS":
        raise ValueError("Only completed OAI harvests can be compacted")
    target_records_per_shard = max(100, min(int(target_records_per_shard or DEFAULT_SHARD_RECORD_LIMIT), DEFAULT_SHARD_RECORD_LIMIT))
    harvest_id = str(entry.get("harvest_id") or "")
    requested_by = entry.get("requested_by") if isinstance(entry.get("requested_by"), dict) else {}
    user = db.session.get(User, int(requested_by.get("user_id") or 0))
    if user is None:
        raise ValueError("Cannot compact OAI harvest without user context")
    manifest = dict(entry.get("manifest") or {})
    if manifest.get("compacted_shards"):
        return {"created_compacted_shards": 0, "compacted_shards": manifest.get("compacted_shards") or [], "already_compacted": True}
    batch: list[dict[str, Any]] = []
    compacted: list[dict[str, Any]] = []
    source_count = 0

    def flush() -> None:
        nonlocal batch
        if not batch:
            return
        shard_index = len(compacted) + 1
        shard = write_oai_harvest_shard(
            harvest_id=harvest_id,
            shard_index=shard_index,
            records=batch,
            requested_by=user,
            window={
                "base_url": (entry.get("options") or {}).get("base_url"),
                "set_spec": (entry.get("options") or {}).get("set_spec"),
                "metadata_prefix": (entry.get("options") or {}).get("metadata_prefix"),
                "artifact_granularity": "post_completion_compaction",
            },
            manifest_summary={"harvest_id": harvest_id, "shard_index": shard_index, "record_count": len(batch), "derived_from": "post_completion_compaction"},
        )
        shard["artifact_kind"] = "zenodo_oai_harvest_compacted_shard"
        compacted.append(shard)
        batch = []

    for record in iter_oai_harvest_records(entry, include_compacted=False):
        metadata = dict(record.get("metadata") or {})
        oai_meta = metadata.get("webhdp_oai_harvest") if isinstance(metadata.get("webhdp_oai_harvest"), dict) else {}
        batch.append(
            {
                "oai_identifier": oai_meta.get("oai_identifier") or record.get("zenodo_record_id"),
                "oai_datestamp": record.get("modified") or record.get("created"),
                "oai_set_specs": oai_meta.get("oai_set_specs") or [],
                "metadata": metadata,
                "raw_xml": "",
            }
        )
        source_count += 1
        if len(batch) >= target_records_per_shard:
            flush()
    flush()
    manifest["compacted_shards"] = compacted
    manifest["compaction"] = {"created_at": _utc_now_iso(), "source_record_count": source_count, "target_records_per_shard": target_records_per_shard, "compacted_shard_count": len(compacted)}
    update_harvest_entry(harvest_id, manifest=manifest, status=str(entry.get("status") or "completed"))
    return {"created_compacted_shards": len(compacted), "compacted_shards": compacted, "source_record_count": source_count}


def build_oai_harvest_diagnostics(entry: dict[str, Any]) -> dict[str, Any]:
    runtime = entry.get("runtime") if isinstance(entry.get("runtime"), dict) else {}
    process = runtime.get("process") if isinstance(runtime.get("process"), dict) else {}
    progress = entry.get("progress") if isinstance(entry.get("progress"), dict) else {}
    summary = entry.get("summary") if isinstance(entry.get("summary"), dict) else {}
    return {
        "state": entry.get("state"),
        "status": entry.get("status"),
        "execution_target": runtime.get("execution_target") or "celery_local",
        "process": process,
        "heartbeat_at": entry.get("heartbeat_at"),
        "stale": bool(entry.get("stale")),
        "records": {
            "harvested": int(summary.get("harvested_records") or progress.get("harvested_records") or 0),
            "duplicates": int(summary.get("duplicate_records_skipped") or progress.get("duplicate_records_skipped") or 0),
        },
        "throughput": {
            "records_per_hour": progress.get("records_per_hour"),
            "pages_per_hour": progress.get("pages_per_hour"),
            "wait_seconds": summary.get("wait_seconds"),
        },
        "oai": {
            "base_url": (entry.get("options") or {}).get("base_url"),
            "set_spec": (entry.get("options") or {}).get("set_spec"),
            "metadata_prefix": (entry.get("options") or {}).get("metadata_prefix"),
            "current_resumption_token": bool(progress.get("current_resumption_token")),
        },
    }


def build_oai_harvest_preflight(*, base_url: str, set_spec: str, metadata_prefix: str, http: Any = requests) -> dict[str, Any]:
    client = RateLimitedOaiClient(base_url=base_url, http=http, min_interval_seconds=0, request_timeout_seconds=10, request_retries=0)
    identify = client.request({"verb": "Identify"})
    formats = client.request({"verb": "ListMetadataFormats"})
    sample = client.request({"verb": "ListRecords", "metadataPrefix": metadata_prefix, "set": set_spec})
    ok = identify.status_code == 200 and formats.status_code == 200 and sample.status_code == 200
    format_names: list[str] = []
    try:
        root = ET.fromstring(formats.text)
        format_names = [_text(item) for item in root.findall(f".//{{{OAI_NS}}}metadataPrefix")]
    except Exception:
        format_names = []
    sample_result: dict[str, Any] = {}
    try:
        parsed = parse_oai_response(sample.text)
        sample_result = {
            "records_seen": len(parsed.get("records") or []),
            "has_resumption_token": bool(parsed.get("resumption_token")),
            "complete_list_size": parsed.get("complete_list_size") or None,
            "errors": parsed.get("errors") or [],
        }
    except Exception as exc:
        sample_result = {"parse_error": str(exc)}
    return {
        "ok": ok,
        "queueable": True,
        "base_url": base_url,
        "set_spec": set_spec,
        "metadata_prefix": metadata_prefix,
        "identify_status": identify.status_code,
        "metadata_formats_status": formats.status_code,
        "sample_status": sample.status_code,
        "available_metadata_prefixes": format_names,
        "sample": sample_result,
        "rate_limit": {"max_requests_per_minute": 30, "page_size": DEFAULT_OAI_PAGE_SIZE},
    }
