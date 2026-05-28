"""Remote HDP Component index discovery.

The index is a discovery layer only. WebHDP still installs validated manifests
through the native component installer and never imports remote code directly.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from exceptions import ValidationError


INDEX_SCHEMA = "webhdp.component-index.v1"
TRUST_ORDER = {"unknown": 0, "experimental": 1, "community-reviewed": 2, "trusted": 3}
TRUST_LEVELS = set(TRUST_ORDER)
REPO_ROOT = Path(__file__).resolve().parents[1]


def _config_value(name: str, default: Any = None) -> Any:
    try:
        from flask import current_app

        if current_app and name in current_app.config:
            return current_app.config.get(name)
    except RuntimeError:
        pass
    return os.environ.get(name, default)


def _config_int(name: str, default: int) -> int:
    try:
        return int(_config_value(name, default))
    except (TypeError, ValueError):
        return default


def _split_sources(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "")
    return [item.strip() for item in text.replace("\n", ",").split(",") if item.strip()]


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _looks_like_sha256(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


class ComponentIndexService:
    """Loads configured WebHDP component indexes and referenced manifests."""

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self._manifest_cache: dict[str, dict[str, Any]] = {}

    def configured_sources(self) -> list[str]:
        return _split_sources(_config_value("WEBHDP_COMPONENT_INDEX_SOURCES", ""))

    def timeout_seconds(self) -> int:
        return max(1, _config_int("WEBHDP_COMPONENT_INDEX_TIMEOUT_SECONDS", 15))

    def cache_ttl_seconds(self) -> int:
        return max(0, _config_int("WEBHDP_COMPONENT_INDEX_CACHE_TTL_SECONDS", 900))

    def min_trust_level(self) -> str:
        value = str(_config_value("WEBHDP_COMPONENT_INDEX_MIN_TRUST", "unknown") or "unknown").strip().lower()
        return value if value in TRUST_LEVELS else "unknown"

    def current_webhdp_version(self) -> str:
        configured = str(_config_value("WEBHDP_VERSION", "") or "").strip()
        if configured:
            return configured
        version_path = REPO_ROOT / "version.json"
        try:
            payload = json.loads(version_path.read_text(encoding="utf-8"))
            return str(payload.get("version") or "unknown").strip() or "unknown"
        except (OSError, ValueError):
            return "unknown"

    def list_index_entries(self, *, refresh: bool = False) -> dict[str, Any]:
        components: list[dict[str, Any]] = []
        warnings: list[dict[str, str]] = []
        for source in self.configured_sources():
            try:
                payload = self._load_index(source, refresh=refresh)
                normalized = self._normalize_entries(payload, source)
                components.extend(normalized["components"])
                warnings.extend(normalized["warnings"])
            except Exception as exc:
                warnings.append({"source": source, "message": str(exc)})
        return {
            "components": components,
            "summary": {
                "sources": len(self.configured_sources()),
                "remote_components": len(components),
                "warnings": warnings,
                "min_trust_level": self.min_trust_level(),
                "current_webhdp_version": self.current_webhdp_version(),
            },
        }

    def diagnostics(self) -> dict[str, Any]:
        now = time.time()
        sources = self.configured_sources()
        source_entries: list[dict[str, Any]] = []
        for source in sources:
            try:
                normalized = self._validate_read_url(source, field_name="index_source")
            except Exception as exc:
                source_entries.append({"source": source, "valid": False, "message": str(exc)})
                continue
            cached = self._cache.get(normalized)
            payload = cached.get("payload") if isinstance(cached, dict) else {}
            loaded_at = float(cached.get("loaded_at") or 0) if isinstance(cached, dict) else None
            source_entries.append(
                {
                    "source": source,
                    "normalized_source": normalized,
                    "valid": True,
                    "cached": bool(cached),
                    "cache_valid": bool(cached and self._cache_valid(loaded_at)),
                    "loaded_at": loaded_at,
                    "age_seconds": round(now - loaded_at, 3) if loaded_at else None,
                    "schema": payload.get("schema") or payload.get("schema_version") if isinstance(payload, dict) else None,
                    "component_count": len(payload.get("components") or []) if isinstance(payload, dict) else 0,
                }
            )
        return {
            "schema": INDEX_SCHEMA,
            "configured": bool(sources),
            "sources": source_entries,
            "source_count": len(sources),
            "manifest_cache_entries": len(self._manifest_cache),
            "cache_ttl_seconds": self.cache_ttl_seconds(),
            "timeout_seconds": self.timeout_seconds(),
            "min_trust_level": self.min_trust_level(),
            "current_webhdp_version": self.current_webhdp_version(),
        }

    def fetch_manifest_text(self, manifest_url: str, *, expected_sha256: str = "") -> dict[str, Any]:
        url = self._validate_read_url(manifest_url, field_name="manifest_url")
        cache_key = f"{url}|{expected_sha256}"
        cached = self._manifest_cache.get(cache_key)
        if cached and self._cache_valid(cached.get("loaded_at", 0)):
            return dict(cached["payload"])
        text = self._read_text(url)
        actual_sha256 = _sha256_text(text)
        if expected_sha256 and actual_sha256.lower() != expected_sha256.lower():
            raise ValidationError(
                "Remote component manifest SHA-256 mismatch",
                details={"manifest_url": url, "expected_sha256": expected_sha256, "actual_sha256": actual_sha256},
            )
        payload = {"manifest_url": url, "manifest_text": text, "manifest_sha256": actual_sha256}
        self._manifest_cache[cache_key] = {"loaded_at": time.time(), "payload": payload}
        return dict(payload)

    def _load_index(self, source: str, *, refresh: bool = False) -> dict[str, Any]:
        source = self._validate_read_url(source, field_name="index_source")
        cached = self._cache.get(source)
        if not refresh and cached and self._cache_valid(cached.get("loaded_at", 0)):
            return dict(cached["payload"])
        text = self._read_text(source)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Component index is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValidationError("Component index must contain a JSON object")
        if str(payload.get("schema") or payload.get("schema_version") or "").strip() != INDEX_SCHEMA:
            raise ValidationError(f"Unsupported component index schema; expected {INDEX_SCHEMA}")
        if not isinstance(payload.get("components"), list):
            raise ValidationError("Component index must contain a components list")
        self._cache[source] = {"loaded_at": time.time(), "payload": payload}
        return dict(payload)

    def _normalize_entries(self, payload: dict[str, Any], source: str) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        warnings: list[dict[str, str]] = []
        for index, raw in enumerate(payload.get("components") or []):
            try:
                if not isinstance(raw, dict):
                    raise ValidationError(f"Component index entry {index} must be an object")
                entry = self._normalize_entry(raw, source, index)
                entries.append(entry)
            except Exception as exc:
                key = raw.get("component_key") if isinstance(raw, dict) else index
                warnings.append({"source": source, "component_key": str(key), "message": str(exc)})
        return {"components": entries, "warnings": warnings}

    def _normalize_entry(self, raw: dict[str, Any], source: str, index: int) -> dict[str, Any]:
        manifest_block = raw.get("manifest") if isinstance(raw.get("manifest"), dict) else {}
        artifacts = raw.get("artifacts") if isinstance(raw.get("artifacts"), dict) else {}
        docker = artifacts.get("docker") if isinstance(artifacts.get("docker"), dict) else {}
        sif = artifacts.get("sif") if isinstance(artifacts.get("sif"), dict) else {}

        component_key = str(raw.get("component_key") or raw.get("name") or "").strip()
        version = str(raw.get("version") or "").strip()
        manifest_url = str(manifest_block.get("url") or raw.get("manifest_url") or "").strip()
        manifest_url = self._resolve_relative_url(source, manifest_url)
        manifest_sha256 = str(manifest_block.get("sha256") or raw.get("manifest_sha256") or "").strip().lower()
        sif_sha256 = str(sif.get("sha256") or raw.get("sif_sha256") or "").strip().lower()
        if not component_key or not version or not manifest_url:
            raise ValidationError(f"Component index entry {index} is missing component_key, version, or manifest URL")
        if manifest_sha256 and not _looks_like_sha256(manifest_sha256):
            raise ValidationError(f"Component index entry {component_key} has an invalid manifest SHA-256")
        if sif_sha256 and not _looks_like_sha256(sif_sha256):
            raise ValidationError(f"Component index entry {component_key} has an invalid SIF SHA-256")

        trust_level = str(raw.get("trust_level") or "unknown").strip().lower()
        if trust_level not in TRUST_LEVELS:
            trust_level = "unknown"
        min_trust = self.min_trust_level()
        if TRUST_ORDER[trust_level] < TRUST_ORDER[min_trust]:
            raise ValidationError(
                f"Component index entry {component_key} trust level {trust_level} is below configured minimum {min_trust}"
            )

        source_block = raw.get("source") if isinstance(raw.get("source"), dict) else {}
        zenodo = raw.get("zenodo") if isinstance(raw.get("zenodo"), dict) else {}
        compatibility = raw.get("compatibility") if isinstance(raw.get("compatibility"), dict) else {}
        compatibility = self._normalize_compatibility(compatibility)
        compatibility_status = self._compatibility_status(compatibility)
        if compatibility_status.get("compatible") is False:
            raise ValidationError(
                f"Component index entry {component_key} is not compatible with WebHDP {self.current_webhdp_version()}"
            )
        license_info = raw.get("license") if isinstance(raw.get("license"), dict) else raw.get("license")
        citation = raw.get("citation") if isinstance(raw.get("citation"), dict) else raw.get("citation")
        sbom_url = str(docker.get("sbom_url") or sif.get("sbom_url") or raw.get("sbom_url") or "").strip()
        provenance_url = str(
            docker.get("provenance_url") or sif.get("provenance_url") or raw.get("provenance_url") or ""
        ).strip()
        release = raw.get("release") if isinstance(raw.get("release"), dict) else {}
        release_url = str(release.get("url") or raw.get("release_url") or "").strip()
        release_assets = release.get("assets") if isinstance(release.get("assets"), list) else raw.get("release_assets")
        if not isinstance(release_assets, list):
            release_assets = []

        docker_sbom_url = self._validate_optional_https_url(docker.get("sbom_url"), field_name="docker.sbom_url")
        docker_provenance_url = self._validate_optional_https_url(
            docker.get("provenance_url"),
            field_name="docker.provenance_url",
        )
        sif_sbom_url = self._validate_optional_https_url(sif.get("sbom_url"), field_name="sif.sbom_url")
        sif_provenance_url = self._validate_optional_https_url(
            sif.get("provenance_url"),
            field_name="sif.provenance_url",
        )
        sbom_url = self._validate_optional_https_url(sbom_url, field_name="sbom_url")
        provenance_url = self._validate_optional_https_url(provenance_url, field_name="provenance_url")
        release_url = self._validate_optional_https_url(release_url, field_name="release.url")
        normalized_assets = [
            self._normalize_release_asset(asset, component_key=component_key)
            for asset in release_assets
        ]

        return {
            "catalog_ref": {
                "source": source,
                "component_key": component_key,
                "version": version,
                "manifest_url": manifest_url,
            },
            "catalog_source": "remote_index",
            "component_key": component_key,
            "version": version,
            "label": raw.get("label") or component_key,
            "description": raw.get("description") or "",
            "category": raw.get("category") or "",
            "tags": raw.get("tags") if isinstance(raw.get("tags"), list) else [],
            "trust_level": trust_level,
            "manifest_url": manifest_url,
            "manifest_sha256": manifest_sha256,
            "git": {
                "url": source_block.get("url") or raw.get("git_url") or "",
                "tag": source_block.get("tag") or raw.get("git_tag") or "",
                "commit": source_block.get("commit") or raw.get("git_commit") or "",
            },
            "release": {
                "url": release_url,
                "tag": release.get("tag") or raw.get("release_tag") or source_block.get("tag") or "",
                "assets": normalized_assets,
            },
            "zenodo": {
                "doi": zenodo.get("doi") or raw.get("doi") or "",
                "concept_doi": zenodo.get("concept_doi") or raw.get("concept_doi") or "",
                "record_url": zenodo.get("record_url") or raw.get("record_url") or "",
            },
            "compatibility": {**compatibility, "status": compatibility_status},
            "license": license_info,
            "citation": citation,
            "artifacts": {
                "docker": {
                    "image": docker.get("image") or raw.get("container_image") or "",
                    "digest": docker.get("digest") or "",
                    "sbom_url": docker_sbom_url,
                    "provenance_url": docker_provenance_url,
                },
                "sif": {
                    "source": sif.get("source") or raw.get("sif_source") or "",
                    "sha256": sif_sha256,
                    "sbom_url": sif_sbom_url,
                    "provenance_url": sif_provenance_url,
                },
            },
            "sbom_url": sbom_url,
            "provenance_url": provenance_url,
        }

    def _cache_valid(self, loaded_at: Any) -> bool:
        ttl = self.cache_ttl_seconds()
        return ttl > 0 and time.time() - float(loaded_at or 0) <= ttl

    def _read_text(self, source: str) -> str:
        parsed = urlparse(source)
        if parsed.scheme == "https":
            response = requests.get(source, timeout=self.timeout_seconds())
            response.raise_for_status()
            return response.text
        path = Path(source)
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _version_tuple(value: Any) -> tuple[int, ...]:
        text = str(value or "").strip()
        if not text or text == "unknown":
            return ()
        numeric = []
        for part in text.replace("-", ".").split("."):
            digits = "".join(char for char in part if char.isdigit())
            if digits == "":
                break
            numeric.append(int(digits))
        return tuple(numeric)

    @staticmethod
    def _compare_versions(left: Any, right: Any) -> int:
        left_tuple = ComponentIndexService._version_tuple(left)
        right_tuple = ComponentIndexService._version_tuple(right)
        if not left_tuple or not right_tuple:
            return 0
        length = max(len(left_tuple), len(right_tuple))
        left_tuple = left_tuple + (0,) * (length - len(left_tuple))
        right_tuple = right_tuple + (0,) * (length - len(right_tuple))
        return (left_tuple > right_tuple) - (left_tuple < right_tuple)

    @staticmethod
    def _normalize_compatibility(value: dict[str, Any]) -> dict[str, Any]:
        return {
            **value,
            "webhdp_min": value.get("webhdp_min") or value.get("webhdp_min_version") or value.get("min_webhdp") or "",
            "webhdp_max": value.get("webhdp_max") or value.get("webhdp_max_version") or value.get("max_webhdp") or "",
        }

    def _compatibility_status(self, compatibility: dict[str, Any]) -> dict[str, Any]:
        current = self.current_webhdp_version()
        min_version = str(compatibility.get("webhdp_min") or "").strip()
        max_version = str(compatibility.get("webhdp_max") or "").strip()
        compatible = True
        reason = ""
        if min_version and self._compare_versions(current, min_version) < 0:
            compatible = False
            reason = f"requires WebHDP >= {min_version}"
        if compatible and max_version and self._compare_versions(current, max_version) > 0:
            compatible = False
            reason = f"requires WebHDP <= {max_version}"
        return {
            "compatible": compatible,
            "current_webhdp_version": current,
            "webhdp_min": min_version,
            "webhdp_max": max_version,
            "reason": reason,
        }

    @staticmethod
    def _validate_optional_https_url(value: Any, *, field_name: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        parsed = urlparse(text)
        if parsed.scheme != "https":
            raise ValidationError(f"{field_name} must use HTTPS")
        return text

    def _normalize_release_asset(self, asset: Any, *, component_key: str) -> dict[str, Any]:
        if isinstance(asset, str):
            return {"url": self._validate_optional_https_url(asset, field_name="release.assets.url")}
        if not isinstance(asset, dict):
            raise ValidationError(f"Component index entry {component_key} release asset must be a URL string or object")
        url = self._validate_optional_https_url(asset.get("url"), field_name="release.assets.url")
        sha256 = str(asset.get("sha256") or "").strip().lower()
        if sha256 and not _looks_like_sha256(sha256):
            raise ValidationError(f"Component index entry {component_key} release asset has an invalid SHA-256")
        return {
            "name": str(asset.get("name") or "").strip(),
            "url": url,
            "media_type": str(asset.get("media_type") or asset.get("content_type") or "").strip(),
            "sha256": sha256,
        }

    @staticmethod
    def _validate_read_url(value: str, *, field_name: str) -> str:
        text = str(value or "").strip()
        if not text or "\x00" in text:
            raise ValidationError(f"{field_name} is required")
        parsed = urlparse(text)
        if parsed.scheme:
            if parsed.scheme != "https":
                raise ValidationError(f"{field_name} must use HTTPS or an absolute local path")
            return text
        path = Path(text)
        if not path.is_absolute():
            raise ValidationError(f"{field_name} local paths must be absolute")
        return str(path)

    @staticmethod
    def _resolve_relative_url(base: str, value: str) -> str:
        if not value:
            return ""
        parsed = urlparse(value)
        if parsed.scheme or Path(value).is_absolute():
            return value
        base_parsed = urlparse(base)
        if base_parsed.scheme:
            return urljoin(base, value)
        return str((Path(base).parent / value).resolve())
