"""Installer service for installable HDP Components.

The original implementation only handled HPC-Link/Singularity installs.  The
service now keeps that path as the default while also supporting local
workstation container installs for manifests that declare a ``container_cli``
Docker profile.
"""

from __future__ import annotations

import base64
import binascii
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from uuid import UUID
from services.registry_lock import serialize_registry, OperationConflict
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import yaml
from flask import current_app

from database.database import db
from database.models import ComponentDefinition, ComponentVersion, HpcComponentInstallation, PipelineStep, User
from exceptions import ResourceNotFoundError, ValidationError, APITimeoutError, APIConnectionError
from services.native_pipeline_adapters import contract_file_output_error


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_STRATEGY_HPC_SIF = "hpc_sif"
INSTALL_STRATEGY_LOCAL_CONTAINER = "local_container"
SUPPORTED_INSTALL_STRATEGIES = {INSTALL_STRATEGY_HPC_SIF, INSTALL_STRATEGY_LOCAL_CONTAINER}
INSTALL_TIER_EXTERNAL = "external_installable"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _json_loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _sha256(value: Any) -> str:
    return hashlib.sha256(_json_dumps(value).encode("utf-8")).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _clean_sha256(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ValidationError("SHA-256 values must be 64 lowercase hexadecimal characters")
    return text


def _config_or_env(name: str, default: Any = None) -> Any:
    try:
        if current_app and name in current_app.config:
            return current_app.config.get(name)
    except RuntimeError:
        pass
    return os.environ.get(name, default)


def _config_bool(name: str, default: bool = False) -> bool:
    value = _config_or_env(name, default)
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


class HpcComponentInstallerService:
    """Validates, installs, and tracks installable HDP Components."""

    @staticmethod
    def _install_strategy(payload: Dict[str, Any]) -> str:
        raw = (
            payload.get("install_strategy")
            or payload.get("strategy")
            or payload.get("target")
            or INSTALL_STRATEGY_HPC_SIF
        )
        strategy = str(raw or "").strip().lower().replace("-", "_")
        aliases = {
            "hpc": INSTALL_STRATEGY_HPC_SIF,
            "hpc_link": INSTALL_STRATEGY_HPC_SIF,
            "sif": INSTALL_STRATEGY_HPC_SIF,
            "hpc_singularity": INSTALL_STRATEGY_HPC_SIF,
            "local": INSTALL_STRATEGY_LOCAL_CONTAINER,
            "docker": INSTALL_STRATEGY_LOCAL_CONTAINER,
            "local_docker": INSTALL_STRATEGY_LOCAL_CONTAINER,
            "container": INSTALL_STRATEGY_LOCAL_CONTAINER,
        }
        strategy = aliases.get(strategy, strategy)
        if strategy not in SUPPORTED_INSTALL_STRATEGIES:
            raise ValidationError(
                "Unsupported HDP Component install strategy",
                details={"install_strategy": raw, "supported": sorted(SUPPORTED_INSTALL_STRATEGIES)},
            )
        return strategy

    @staticmethod
    def _parse_manifest_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        manifest = payload.get("manifest")
        manifest_text = payload.get("manifest_text") or payload.get("component_yaml")
        if isinstance(manifest, dict):
            return manifest
        if not manifest_text:
            raise ValidationError("component.yaml content is required")
        try:
            parsed = yaml.safe_load(str(manifest_text))
        except yaml.YAMLError as exc:
            raise ValidationError(f"component.yaml could not be parsed: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValidationError("component.yaml must contain a YAML object")
        return parsed

    @staticmethod
    def _validate_sif_source(value: Any) -> Dict[str, str]:
        source = str(value or "").strip()
        if not source:
            raise ValidationError("sif_source is required")
        if "\x00" in source:
            raise ValidationError("sif_source contains an invalid character")
        try:
            parsed = urlparse(source)
            port = parsed.port
        except ValueError as exc:
            raise ValidationError("Invalid SIF source") from exc
        if parsed.scheme:
            if (parsed.scheme != "https" or not parsed.hostname or port not in (None, 443)
                    or parsed.username is not None or parsed.password is not None
                    or parsed.params or ";" in parsed.path or "#" in source or "\\" in source
                    or any(ord(char) <= 32 or ord(char) == 127 for char in source)):
                raise ValidationError("Use a public HTTPS SIF URL without credentials or an absolute HPC path")
            if parsed.query and not (parsed.hostname in {"zenodo.org", "sandbox.zenodo.org"} and parsed.query == "download=1"):
                raise ValidationError("SIF URLs cannot contain query parameters. Stage private SIFs on HPC and use the absolute path")
            if not parsed.path.lower().endswith(".sif"):
                raise ValidationError("SIF URLs must end with .sif")
            return {"source_type": "https_url", "sif_source": source}

        path = PurePosixPath(source)
        if parsed.netloc or not source.startswith("/") or ".." in path.parts or not source.lower().endswith(".sif"):
            raise ValidationError("Remote SIF paths must be absolute .sif paths without traversal")
        return {"source_type": "remote_path", "sif_source": source}

    @staticmethod
    def _hpc_profile(manifest: Dict[str, Any]) -> Dict[str, Any]:
        profiles = ((manifest.get("execution") or {}).get("profiles") or [])
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            if str(profile.get("adapter") or "").strip() != "hpc_link":
                continue
            if str(profile.get("handler") or "").strip() != "generic_singularity_component":
                continue
            if str(profile.get("runtime") or "").strip() != "singularity":
                continue
            entrypoint = profile.get("entrypoint")
            if not isinstance(entrypoint, list) or not all(str(item).strip() for item in entrypoint):
                raise ValidationError("generic_singularity_component profiles require a non-empty entrypoint")
            return profile
        raise ValidationError(
            "Installed HPC components require an execution profile with adapter=hpc_link, "
            "handler=generic_singularity_component, and runtime=singularity"
        )

    @staticmethod
    def _local_container_profile(manifest: Dict[str, Any]) -> Dict[str, Any]:
        profiles = ((manifest.get("execution") or {}).get("profiles") or [])
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            if str(profile.get("adapter") or "").strip() != "container_cli":
                continue
            if str(profile.get("runtime") or "").strip().lower() != "docker":
                continue
            image = str(profile.get("image") or "").strip()
            entrypoint = profile.get("entrypoint")
            if not image:
                raise ValidationError("Local container profiles require a Docker image")
            if not isinstance(entrypoint, list) or not all(str(item).strip() for item in entrypoint):
                raise ValidationError("Local container profiles require a non-empty entrypoint")
            return profile
        raise ValidationError(
            "Local container installs require an execution profile with adapter=container_cli "
            "and runtime=docker"
        )

    @classmethod
    def _profile_for_strategy(cls, manifest: Dict[str, Any], strategy: str) -> Dict[str, Any]:
        if strategy == INSTALL_STRATEGY_LOCAL_CONTAINER:
            return cls._local_container_profile(manifest)
        return cls._hpc_profile(manifest)

    @staticmethod
    def _declares_install_profile(manifest: Dict[str, Any], strategy: str) -> bool:
        profiles = ((manifest.get("execution") or {}).get("profiles") or [])
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            adapter = str(profile.get("adapter") or "").strip()
            runtime = str(profile.get("runtime") or "").strip().lower()
            handler = str(profile.get("handler") or "").strip()
            if strategy == INSTALL_STRATEGY_LOCAL_CONTAINER:
                if adapter == "container_cli" and runtime == "docker":
                    return True
            else:
                if adapter == "hpc_link" and handler == "generic_singularity_component" and runtime == "singularity":
                    return True
        return False

    @staticmethod
    def _safe_catalog_source_path(path: Path) -> str:
        try:
            return str(path.resolve().relative_to(REPO_ROOT))
        except ValueError:
            return str(path.resolve())

    def list_available_catalog(
        self,
        catalog_root: Optional[Path] = None,
        *,
        install_strategy: str = INSTALL_STRATEGY_HPC_SIF,
        source: str = "all",
    ) -> Dict[str, Any]:
        """Return installable component manifests available to admins."""
        strategy = self._install_strategy({"install_strategy": install_strategy})
        source_filter = str(source or "all").strip().lower()
        if source_filter not in {"all", "local", "remote"}:
            raise ValidationError("Catalog source must be one of: local, remote, all")
        root = Path(catalog_root) if catalog_root is not None else REPO_ROOT / "external_code"
        components: list[Dict[str, Any]] = []
        warnings: list[Dict[str, Any]] = []

        if source_filter in {"all", "local"}:
            local_catalog = self._list_local_catalog(root, strategy)
            components.extend(local_catalog["components"])
            warnings.extend(local_catalog["warnings"])

        if source_filter in {"all", "remote"} and catalog_root is None:
            remote_catalog = self._list_remote_catalog(strategy)
            components.extend(remote_catalog["components"])
            warnings.extend(remote_catalog["warnings"])

        components.sort(key=lambda item: (str(item.get("category") or ""), str(item.get("label") or "")))
        return {
            "components": components,
            "summary": {
                "total": len(components),
                "installable": len([item for item in components if item.get("installable")]),
                "source": source_filter,
                "warnings": warnings,
            },
        }

    def _list_local_catalog(self, root: Path, strategy: str) -> Dict[str, Any]:
        components: list[Dict[str, Any]] = []
        warnings: list[Dict[str, Any]] = []
        if not root.exists():
            return {
                "components": [],
                "warnings": [{"source_path": str(root), "message": "Catalog root does not exist"}],
            }

        for manifest_path in sorted(root.glob("*/component.yaml")):
            source_path = self._safe_catalog_source_path(manifest_path)
            try:
                manifest_text = manifest_path.read_text(encoding="utf-8")
                raw_manifest = yaml.safe_load(manifest_text) or {}
                if not isinstance(raw_manifest, dict):
                    raise ValidationError("component.yaml must contain a YAML object")
                if not self._declares_install_profile(raw_manifest, strategy):
                    continue
                manifest = current_app.native_pipeline_service._normalize_manifest(
                    raw_manifest,
                    source_dir=manifest_path.parent,
                    source_type="local_catalog",
                )
                profile = self._profile_for_strategy(manifest, strategy)
            except Exception as exc:
                warnings.append({"source_path": source_path, "message": str(exc)})
                continue

            components.append(
                self._catalog_entry_from_manifest(
                    manifest=manifest,
                    manifest_text=manifest_text,
                    profile=profile,
                    strategy=strategy,
                    source_path=source_path,
                    catalog_source="local",
                    label_fallback=manifest_path.parent.name,
                )
            )
        return {"components": components, "warnings": warnings}

    def _list_remote_catalog(self, strategy: str) -> Dict[str, Any]:
        components: list[Dict[str, Any]] = []
        warnings: list[Dict[str, Any]] = []
        index_service = getattr(current_app, "component_index_service", None)
        if index_service is None:
            return {"components": components, "warnings": warnings}
        remote = index_service.list_index_entries()
        warnings.extend(remote.get("summary", {}).get("warnings") or [])
        for entry in remote.get("components") or []:
            try:
                manifest_ref = index_service.fetch_manifest_text(
                    str(entry.get("manifest_url") or ""),
                    expected_sha256=str(entry.get("manifest_sha256") or ""),
                )
                manifest_text = manifest_ref["manifest_text"]
                raw_manifest = yaml.safe_load(manifest_text) or {}
                if not isinstance(raw_manifest, dict):
                    raise ValidationError("component.yaml must contain a YAML object")
                manifest = current_app.native_pipeline_service._normalize_manifest(
                    raw_manifest,
                    source_dir=None,
                    source_type="remote_index",
                )
                self._apply_remote_artifacts_to_manifest(manifest, entry)
                if not self._declares_install_profile(manifest, strategy):
                    continue
                profile = self._profile_for_strategy(manifest, strategy)
                catalog_entry = self._catalog_entry_from_manifest(
                    manifest=manifest,
                    manifest_text=manifest_text,
                    profile=profile,
                    strategy=strategy,
                    source_path=str(entry.get("manifest_url") or ""),
                    catalog_source="remote_index",
                    label_fallback=str(entry.get("label") or entry.get("component_key") or ""),
                    extra=entry,
                )
                catalog_entry["manifest_sha256"] = manifest_ref["manifest_sha256"]
                components.append(catalog_entry)
            except Exception as exc:
                warnings.append(
                    {
                        "source_path": str(entry.get("manifest_url") or entry.get("catalog_ref", {}).get("source") or "remote"),
                        "message": str(exc),
                    }
                )
        return {"components": components, "warnings": warnings}

    @staticmethod
    def _apply_remote_artifacts_to_manifest(manifest: Dict[str, Any], entry: Dict[str, Any]) -> None:
        artifacts = entry.get("artifacts") if isinstance(entry.get("artifacts"), dict) else {}
        docker = artifacts.get("docker") if isinstance(artifacts.get("docker"), dict) else {}
        image = str(docker.get("image") or "").strip()
        if not image:
            return
        for profile in manifest.get("execution", {}).get("profiles", []):
            if isinstance(profile, dict) and profile.get("adapter") == "container_cli" and profile.get("runtime") == "docker":
                profile["image"] = profile.get("image") or image

    @staticmethod
    def _catalog_entry_from_manifest(
        *,
        manifest: Dict[str, Any],
        manifest_text: str,
        profile: Dict[str, Any],
        strategy: str,
        source_path: str,
        catalog_source: str,
        label_fallback: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        metadata = manifest.get("metadata") or {}
        distribution = manifest.get("distribution") if isinstance(manifest.get("distribution"), dict) else {}
        hpc = manifest.get("hpc") if isinstance(manifest.get("hpc"), dict) else {}
        install = manifest.get("install") if isinstance(manifest.get("install"), dict) else {}
        install_strategies = install.get("strategies") if isinstance(install.get("strategies"), list) else []
        local_test = install.get("test") if isinstance(install.get("test"), dict) else None
        component_warnings: list[str] = []
        has_smoke_test = bool(hpc.get("test") if strategy == INSTALL_STRATEGY_HPC_SIF else local_test)
        if not has_smoke_test:
            if strategy == INSTALL_STRATEGY_HPC_SIF:
                component_warnings.append("No hpc.test smoke-test metadata is declared.")
            else:
                component_warnings.append("No install.test smoke-test metadata is declared.")
        extra = extra or {}
        sources = manifest.get("sources") if isinstance(manifest.get("sources"), dict) else {}
        zenodo = extra.get("zenodo") or {}
        if not zenodo:
            doi = str(sources.get("doi") or "")
            match = re.fullmatch(r"10\.5281/zenodo\.(\d+)", doi)
            if match:
                zenodo = {"doi": doi, "record_url": f"https://zenodo.org/records/{match.group(1)}"}
        artifacts = extra.get("artifacts") if isinstance(extra.get("artifacts"), dict) else {}
        docker = artifacts.get("docker") if isinstance(artifacts.get("docker"), dict) else {}
        sif = artifacts.get("sif") if isinstance(artifacts.get("sif"), dict) else {}
        if catalog_source == "remote_index" and strategy == INSTALL_STRATEGY_LOCAL_CONTAINER and docker.get("image"):
            if not any(item.get("id") == INSTALL_STRATEGY_LOCAL_CONTAINER for item in install_strategies if isinstance(item, dict)):
                install_strategies = [
                    *install_strategies,
                    {
                        "id": INSTALL_STRATEGY_LOCAL_CONTAINER,
                        "runtime": "docker",
                        "profile": profile.get("id"),
                        "image": docker.get("image"),
                    },
                ]
        return {
            "component_key": str(metadata.get("name") or extra.get("component_key") or ""),
            "version": str(metadata.get("version") or extra.get("version") or ""),
            "label": metadata.get("label") or extra.get("label") or metadata.get("name") or label_fallback,
            "description": metadata.get("description") or extra.get("description") or "",
            "category": metadata.get("category") or extra.get("category") or "",
            "tags": metadata.get("tags") if isinstance(metadata.get("tags"), list) else extra.get("tags") or [],
            "distribution_tier": distribution.get("tier") or INSTALL_TIER_EXTERNAL,
            "manifest": manifest,
            "manifest_text": manifest_text,
            "manifest_sha256": extra.get("manifest_sha256") or _sha256_text(manifest_text),
            "profile": profile,
            "install_strategy": strategy,
            "install_strategies": install_strategies,
            "has_smoke_test": has_smoke_test,
            "source_path": source_path,
            "catalog_source": catalog_source,
            "catalog_ref": extra.get("catalog_ref"),
            "trust_level": extra.get("trust_level") or ("local" if catalog_source == "local" else "unknown"),
            "git": extra.get("git") or {},
            "release": extra.get("release") or {},
            "zenodo": zenodo,
            "compatibility": extra.get("compatibility") or {},
            "license": extra.get("license"),
            "citation": extra.get("citation"),
            "artifacts": artifacts,
            "container_image": docker.get("image") or profile.get("image"),
            "docker_digest": docker.get("digest") or "",
            "sif_source": sif.get("source") or "",
            "sif_sha256": sif.get("sha256") or "",
            "sbom_url": extra.get("sbom_url") or docker.get("sbom_url") or sif.get("sbom_url") or "",
            "provenance_url": extra.get("provenance_url") or docker.get("provenance_url") or sif.get("provenance_url") or "",
            "installable": True,
            "warnings": component_warnings,
        }

    @staticmethod
    def _component_version_exists(component_key: str, version: str) -> bool:
        definition = ComponentDefinition.query.filter_by(key=component_key).first()
        if definition is None:
            return False
        return (
            ComponentVersion.query.filter_by(
                component_definition_id=definition.id,
                version=version,
            ).first()
            is not None
        )

    @staticmethod
    def _duplicate_installation_exists(component_key: str, version: str, strategy: str) -> bool:
        rows = HpcComponentInstallation.query.filter(
            HpcComponentInstallation.component_key == component_key,
            HpcComponentInstallation.version == version,
            HpcComponentInstallation.status.in_(["installing", "installed", "unknown"]),
        ).all()
        for row in rows:
            checks = _json_loads(row.checks_json, {})
            row_strategy = checks.get("install_strategy") or INSTALL_STRATEGY_HPC_SIF
            if row_strategy == strategy:
                return True
        return False

    def _normalize_manifest(self, raw_manifest: Dict[str, Any]) -> Dict[str, Any]:
        # Reuse the native pipeline manifest contract so installed components appear
        # consistently in Playground and Pipeline Constructor.
        return current_app.native_pipeline_service._normalize_manifest(
            raw_manifest,
            source_dir=None,
            source_type="external",
        )

    @staticmethod
    def _validate_local_image_source(payload: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, str]:
        image = str(payload.get("image") or payload.get("container_image") or profile.get("image") or "").strip()
        if not image:
            raise ValidationError("container_image is required for local container installs")
        if "\x00" in image or image.startswith("-"):
            raise ValidationError("container_image contains an invalid value")
        return {"source_type": "docker_image", "image": image, "runtime": "docker"}

    @staticmethod
    def _catalog_metadata_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        catalog_ref = payload.get("catalog_ref") if isinstance(payload.get("catalog_ref"), dict) else None
        metadata = payload.get("catalog_metadata") if isinstance(payload.get("catalog_metadata"), dict) else {}
        if not catalog_ref and not metadata:
            return {}
        return {
            "success": True,
            "catalog_ref": catalog_ref or metadata.get("catalog_ref") or {},
            "catalog_source": payload.get("catalog_source") or metadata.get("catalog_source") or "",
            "trust_level": payload.get("trust_level") or metadata.get("trust_level") or "",
            "git": payload.get("git") if isinstance(payload.get("git"), dict) else metadata.get("git") or {},
            "release": payload.get("release") if isinstance(payload.get("release"), dict) else metadata.get("release") or {},
            "zenodo": payload.get("zenodo") if isinstance(payload.get("zenodo"), dict) else metadata.get("zenodo") or {},
            "compatibility": (
                payload.get("compatibility")
                if isinstance(payload.get("compatibility"), dict)
                else metadata.get("compatibility") or {}
            ),
            "license": payload.get("license") or metadata.get("license"),
            "citation": payload.get("citation") or metadata.get("citation"),
            "sbom_url": payload.get("sbom_url") or metadata.get("sbom_url") or "",
            "provenance_url": payload.get("provenance_url") or metadata.get("provenance_url") or "",
        }

    @staticmethod
    def _local_image_policy_checks(image: str) -> Dict[str, Any]:
        raw_allowlist = _config_or_env("WEBHDP_LOCAL_COMPONENT_IMAGE_ALLOWLIST", "")
        patterns = [
            item.strip()
            for item in str(raw_allowlist or "").replace("\n", ",").split(",")
            if item.strip()
        ]
        require_digest = _config_bool("WEBHDP_REQUIRE_PINNED_LOCAL_COMPONENT_IMAGES", False)
        digest_pinned = "@sha256:" in image
        warnings: list[str] = []
        if not digest_pinned:
            warnings.append("Docker image is tag-based; digest-pinned images are recommended for repeatable installs.")

        if patterns and not any(fnmatch.fnmatchcase(image, pattern) for pattern in patterns):
            return {
                "success": False,
                "allowlist_configured": True,
                "allowlist": patterns,
                "digest_pinned": digest_pinned,
                "warnings": warnings,
                "error": "Docker image is not permitted by the configured allowlist.",
            }
        if require_digest and not digest_pinned:
            return {
                "success": False,
                "allowlist_configured": bool(patterns),
                "allowlist": patterns,
                "digest_pinned": False,
                "warnings": warnings,
                "error": "Docker image must be digest-pinned because WEBHDP_REQUIRE_PINNED_LOCAL_COMPONENT_IMAGES is enabled.",
            }
        return {
            "success": True,
            "allowlist_configured": bool(patterns),
            "allowlist": patterns,
            "digest_pinned": digest_pinned,
            "warnings": warnings,
        }

    @staticmethod
    def _local_container_checks(image: str) -> Dict[str, Any]:
        policy = HpcComponentInstallerService._local_image_policy_checks(image)
        docker_path = shutil.which("docker")
        if not docker_path:
            return {
                "checked": True,
                "success": False,
                "policy": policy,
                "error": "Docker CLI is not available to the WebHDP backend/worker process.",
            }
        if policy.get("success") is not True:
            return {
                "checked": True,
                "success": False,
                "runtime": "docker",
                "image": image,
                "docker_path": docker_path,
                "policy": policy,
                "error": policy.get("error") or "Docker image policy check failed.",
            }
        try:
            completed = subprocess.run(
                [docker_path, "image", "inspect", image],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except Exception as exc:
            return {"checked": True, "success": False, "error": str(exc)}
        try:
            image_id = json.loads(completed.stdout)[0]["Id"] if completed.returncode == 0 else None
        except (ValueError, KeyError, IndexError, TypeError):
            image_id = None
        return {
            "image_id": image_id,
            "checked": True,
            "success": completed.returncode == 0 and bool(image_id),
            "runtime": "docker",
            "image": image,
            "docker_path": docker_path,
            "policy": policy,
            "logs": {"stdout": completed.stdout[-2000:], "stderr": completed.stderr[-2000:]},
            **({} if completed.returncode == 0 else {"error": "Docker image is not available locally."}),
        }

    @staticmethod
    def _retain_local_container_image(image_id: str, docker_path: str) -> Dict[str, Any]:
        """Keep the inspected image addressable when its original build tag moves.

        Docker's containerd image store can discard an unreferenced OCI index
        even though component profiles still contain its immutable ID. Retain
        a deterministic local tag, while keeping execution pinned to the ID.
        Retention tags are never pushed or automatically removed.
        """
        if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise ValidationError("Docker did not report a valid immutable image ID")
        retention_tag = "webhdp-component-runtime:sha256-" + image_id.removeprefix("sha256:")
        try:
            tagged = subprocess.run(
                [docker_path, "image", "tag", image_id, retention_tag],
                capture_output=True, text=True, timeout=30, check=False,
            )
            if tagged.returncode != 0:
                raise ValidationError(
                    "Could not preserve the local Docker image before registration",
                    details={"image_id": image_id, "retention_tag": retention_tag,
                             "stderr": tagged.stderr[-2000:]},
                )
            verified = subprocess.run(
                [docker_path, "image", "inspect", retention_tag],
                capture_output=True, text=True, timeout=15, check=False,
            )
            try:
                retained_id = json.loads(verified.stdout)[0]["Id"] if verified.returncode == 0 else None
            except (ValueError, KeyError, IndexError, TypeError):
                retained_id = None
            if retained_id != image_id:
                raise ValidationError(
                    "Retained Docker image verification failed before registration",
                    details={"image_id": image_id, "retention_tag": retention_tag,
                             "retained_image_id": retained_id, "stderr": verified.stderr[-2000:]},
                )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValidationError(
                "Could not preserve the local Docker image before registration",
                details={"image_id": image_id, "retention_tag": retention_tag, "error": str(exc)},
            ) from exc
        return {"success": True, "image_id": image_id, "retention_tag": retention_tag}

    def validate_install_payload(self, payload: Dict[str, Any], *, check_duplicate: bool = True) -> Dict[str, Any]:
        strategy = self._install_strategy(payload)
        raw_manifest = self._parse_manifest_payload(payload)
        manifest = self._normalize_manifest(raw_manifest)
        profile = self._profile_for_strategy(manifest, strategy)
        metadata = manifest["metadata"]
        component_key = str(metadata["name"])
        version = str(metadata["version"])
        duplicate = self._duplicate_installation_exists(component_key, version, strategy)
        if check_duplicate and duplicate:
            raise ValidationError(
                "Component version is already installed for this strategy",
                details={"component_key": component_key, "version": version, "install_strategy": strategy},
            )

        catalog_metadata = self._catalog_metadata_from_payload(payload)
        checks: Dict[str, Any] = {
            "manifest_schema": {"success": True},
            "profile": {"success": True, "profile_id": profile.get("id"), "adapter": profile.get("adapter")},
        }
        if catalog_metadata:
            checks["catalog"] = catalog_metadata
        source: Dict[str, Any]
        if strategy == INSTALL_STRATEGY_LOCAL_CONTAINER:
            source = self._validate_local_image_source(payload, profile)
            docker_digest = str(payload.get("docker_digest") or "").strip()
            checks["container_image"] = {"success": True, **source, "digest": docker_digest}
            checks["local_container"] = self._local_container_checks(source["image"])
        else:
            source = self._validate_sif_source(payload.get("sif_source") or payload.get("sif_remote_path"))
            sif_sha256 = _clean_sha256(payload.get("sif_sha256") or "")
            if sif_sha256:
                source["sha256"] = sif_sha256
            hpc_checks: Dict[str, Any] = {"checked": False}
            hpc_payload = {
                "component_key": component_key,
                "version": version,
                "sif_source": source["sif_source"],
                "source_type": source["source_type"],
                "manifest": manifest,
            }
            if sif_sha256:
                hpc_payload["sif_sha256"] = sif_sha256
            try:
                response = current_app.hpc_allocation_service.client().post(
                    "/api/apps/webhdp/components/validate-install",
                    hpc_payload,
                    # Large GPU images must finish their remote checksum check.
                    timeout=930,
                )
                hpc_checks = response if isinstance(response, dict) else {"checked": True, "raw": response}
            except Exception as exc:
                hpc_checks = {"checked": False, "success": False, "error": str(exc)}
            checks["sif_source"] = {"success": True, **source}
            checks["hpc_link"] = hpc_checks

        return {
            "valid": True,
            "component_key": component_key,
            "version": version,
            "install_strategy": strategy,
            "manifest_hash": _sha256(manifest),
            "manifest": manifest,
            "profile": profile,
            "source": source,
            "sif": source if strategy == INSTALL_STRATEGY_HPC_SIF else None,
            "container": source if strategy == INSTALL_STRATEGY_LOCAL_CONTAINER else None,
            "catalog": catalog_metadata,
            "duplicate": duplicate,
            "registered": self._component_version_exists(component_key, version),
            "checks": checks,
            "playground_schema": manifest.get("playground_schema"),
            "constructor_schema": manifest.get("constructor_schema"),
        }

    @staticmethod
    def _serialize_installation(row: HpcComponentInstallation) -> Dict[str, Any]:
        checks = _json_loads(row.checks_json, {})
        catalog = checks.get("catalog") if isinstance(checks.get("catalog"), dict) else {}
        container_image = (checks.get("container_image") or {}) if isinstance(checks.get("container_image"), dict) else {}
        sif_source = (checks.get("sif_source") or {}) if isinstance(checks.get("sif_source"), dict) else {}
        return {
            "installation_id": row.public_id,
            "component_key": row.component_key,
            "version": row.version,
            "component_version_id": row.component_version_id,
            "status": row.status,
            "install_strategy": (checks.get("install_strategy") or INSTALL_STRATEGY_HPC_SIF),
            "sif_remote_path": row.sif_remote_path,
            "sif_sha256": sif_source.get("sha256") or "",
            "container_image": container_image.get("image"),
            "docker_digest": container_image.get("digest") or "",
            "remote_install_dir": row.remote_install_dir,
            "manifest_hash": row.manifest_hash,
            "manifest": _json_loads(row.manifest_json, {}),
            "catalog": catalog,
            "catalog_ref": catalog.get("catalog_ref") or {},
            "catalog_source": catalog.get("catalog_source") or "",
            "trust_level": catalog.get("trust_level") or "",
            "checks": checks,
            "logs": _json_loads(row.logs_json, {}),
            "error": row.error,
            "created_by": row.created_by,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "installed_at": row.installed_at.isoformat() if row.installed_at else None,
            "last_tested_at": row.last_tested_at.isoformat() if row.last_tested_at else None,
        }

    @staticmethod
    def _with_installed_image(manifest: Dict[str, Any], sif_path: str) -> Dict[str, Any]:
        manifest = json.loads(json.dumps(manifest))
        for profile in manifest.get("execution", {}).get("profiles", []):
            if isinstance(profile, dict) and profile.get("handler") == "generic_singularity_component":
                profile["image"] = sif_path
                profile["runtime"] = "singularity"
                profile["adapter"] = "hpc_link"
        return manifest

    @staticmethod
    def _with_local_container_image(manifest: Dict[str, Any], image: str) -> Dict[str, Any]:
        manifest = json.loads(json.dumps(manifest))
        for profile in manifest.get("execution", {}).get("profiles", []):
            if isinstance(profile, dict) and profile.get("adapter") == "container_cli" and profile.get("runtime") == "docker":
                profile["image"] = image
        return manifest

    @serialize_registry("native-registry")
    def _register_installed_component(
        self,
        installed_manifest: Dict[str, Any],
        *,
        component_key: str,
        version: str,
        source_path: str,
        source_type: str,
    ) -> Dict[str, Any]:
        definition = ComponentDefinition.query.filter_by(key=component_key).first()
        version_row = None
        if definition is not None:
            version_row = ComponentVersion.query.filter_by(
                component_definition_id=definition.id,
                version=version,
            ).first()
        if definition is None or version_row is None:
            return current_app.native_pipeline_service.import_component_from_manifest(
                installed_manifest,
                source_path=source_path,
                source_type=source_type,
                already_normalized=True,
            )

        if PipelineStep.query.filter_by(component_version_id=version_row.id).first():
            if version_row.manifest_hash != _sha256(installed_manifest):
                raise OperationConflict("This component version is used by a saved pipeline. Install a new version instead of replacing it.")
        merged_manifest = _json_loads(version_row.manifest_json, {})
        if not isinstance(merged_manifest, dict) or not merged_manifest:
            merged_manifest = json.loads(json.dumps(installed_manifest))
        merged_profiles = (merged_manifest.setdefault("execution", {}).setdefault("profiles", []))
        if not isinstance(merged_profiles, list):
            merged_profiles = []
            merged_manifest["execution"]["profiles"] = merged_profiles
        by_id = {
            str(profile.get("id") or ""): index
            for index, profile in enumerate(merged_profiles)
            if isinstance(profile, dict)
        }
        for profile in installed_manifest.get("execution", {}).get("profiles", []):
            if not isinstance(profile, dict):
                continue
            profile_id = str(profile.get("id") or "").strip()
            if profile_id and profile_id in by_id:
                merged_profiles[by_id[profile_id]] = profile
            else:
                merged_profiles.append(profile)

        version_row.manifest_json = _json_dumps(merged_manifest)
        version_row.manifest_hash = _sha256(merged_manifest)
        version_row.source_path = source_path
        if definition.source_type != source_type:
            definition.source_type = "multi_strategy_installed"
        current_app.native_pipeline_service._replace_component_profiles(version_row, merged_profiles)
        db.session.commit()
        current_app.native_pipeline_service.ensure_hmsm_pipeline_templates(component_key=component_key)
        current_app.native_pipeline_service.ensure_historic_pipeline_templates(component_key=component_key)
        current_app.native_pipeline_service.ensure_zenodo_pipeline_templates(component_key=component_key)
        return current_app.native_pipeline_service._serialize_component_version(definition, version_row)

    @staticmethod
    def _component_test_block(manifest: Dict[str, Any], strategy: str) -> Dict[str, Any]:
        install = manifest.get("install") if isinstance(manifest.get("install"), dict) else {}
        local_test = install.get("test") if isinstance(install.get("test"), dict) else None
        hpc = manifest.get("hpc") if isinstance(manifest.get("hpc"), dict) else {}
        hpc_test = hpc.get("test") if isinstance(hpc.get("test"), dict) else None
        if strategy == INSTALL_STRATEGY_LOCAL_CONTAINER:
            return local_test or hpc_test or {}
        return hpc_test or {}

    @staticmethod
    def _safe_test_file_name(name: Any) -> str:
        text = str(name or "").strip()
        if not text or "/" in text or "\\" in text or text in {".", ".."}:
            raise ValidationError("Smoke-test file names must be simple relative file names")
        return text

    @staticmethod
    def _write_test_files(input_dir: Path, files: Any) -> list[str]:
        written: list[str] = []
        for entry in files if isinstance(files, list) else []:
            if not isinstance(entry, dict):
                continue
            name = HpcComponentInstallerService._safe_test_file_name(entry.get("name"))
            target = input_dir / name
            if "content_base64" in entry:
                try:
                    content = base64.b64decode(str(entry.get("content_base64") or ""), validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise ValidationError(f"Smoke-test fixture {name} is not valid base64") from exc
                target.write_bytes(content)
            else:
                target.write_text(str(entry.get("content") or ""), encoding="utf-8")
            written.append(name)
        return written

    def _run_local_container_smoke_test(
        self,
        manifest: Dict[str, Any],
        image: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = payload or {}
        readiness = self._local_container_checks(image)
        if readiness.get("success") is not True:
            return {
                "success": False,
                "status": "failed",
                "phase": "readiness",
                "error": readiness.get("error") or "Local container readiness check failed.",
                "checks": readiness,
            }

        test_block = payload.get("test") if isinstance(payload.get("test"), dict) else self._component_test_block(
            manifest,
            INSTALL_STRATEGY_LOCAL_CONTAINER,
        )
        if not test_block:
            return {
                "success": None,
                "status": "skipped",
                "readiness_confirmed": True,
                "phase": "smoke_test",
                "checks": readiness,
                "warnings": ["No install.test smoke-test metadata is declared; only image readiness was checked."],
            }

        profile = self._local_container_profile(manifest)
        entrypoint = list(profile.get("entrypoint") or [])
        docker_path = str(readiness.get("docker_path") or shutil.which("docker") or "docker")
        timeout_seconds = int(float(payload.get("timeout_seconds") or test_block.get("timeout_seconds") or 300))

        with tempfile.TemporaryDirectory(prefix="webhdp-local-component-test-") as tmp:
            root = Path(tmp)
            input_dir = root / "inputs"
            output_dir = root / "outputs"
            response_dir = root / "response"
            request_dir = root / "request"
            for directory in (input_dir, output_dir, response_dir, request_dir):
                directory.mkdir(parents=True, exist_ok=True)
            written_files = self._write_test_files(input_dir, test_block.get("files") or [])
            request_path = request_dir / "request.json"
            response_path = response_dir / "response.json"
            request_payload = {
                "component_key": (manifest.get("metadata") or {}).get("name"),
                "version": (manifest.get("metadata") or {}).get("version"),
                "inputs": test_block.get("inputs") if isinstance(test_block.get("inputs"), dict) else {},
                "parameters": test_block.get("parameters") if isinstance(test_block.get("parameters"), dict) else {},
                "metadata": {"install_strategy": INSTALL_STRATEGY_LOCAL_CONTAINER, "smoke_test": True},
            }
            request_path.write_text(_json_dumps(request_payload), encoding="utf-8")

            command = [
                docker_path,
                "run",
                "--rm",
                "--network",
                "none",
                "-v",
                f"{input_dir}:/inputs:ro",
                "-v",
                f"{output_dir}:/outputs",
                "-v",
                f"{request_path}:/tmp/webhdp/request.json:ro",
                "-v",
                f"{response_dir}:/tmp/webhdp/response",
                "-e",
                "WEBHDP_INPUT_DIR=/inputs",
                "-e",
                "WEBHDP_OUTPUT_DIR=/outputs",
                "-e",
                "WEBHDP_COMPONENT_REQUEST=/tmp/webhdp/request.json",
                "-e",
                "WEBHDP_COMPONENT_RESPONSE=/tmp/webhdp/response/response.json",
                "-e",
                f"WEBHDP_COMPONENT_KEY={request_payload['component_key']}",
                image,
                *entrypoint,
            ]
            started = datetime.utcnow()
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    check=False,
                )
            except Exception as exc:
                return {
                    "success": False,
                    "status": "failed",
                    "phase": "smoke_test",
                    "error": str(exc),
                    "checks": readiness,
                    "command": command,
                    "files": written_files,
                }

            response_payload: Dict[str, Any] = {}
            if response_path.exists():
                try:
                    parsed = json.loads(response_path.read_text(encoding="utf-8"))
                    if isinstance(parsed, dict):
                        response_payload = parsed
                except (OSError, ValueError) as exc:
                    response_payload = {"parse_error": str(exc)}
            elif completed.stdout.strip():
                try:
                    parsed = json.loads(completed.stdout.strip().splitlines()[-1])
                    if isinstance(parsed, dict):
                        response_payload = parsed
                except ValueError:
                    response_payload = {}
            success = completed.returncode == 0 and bool(response_payload) and response_payload.get("success") is True
            contract_error = contract_file_output_error(manifest, response_payload, output_dir) if success else None
            success = success and not contract_error
            return {
                "success": success,
                "status": "completed" if success else "failed",
                "phase": "smoke_test",
                "return_code": completed.returncode,
                "duration_seconds": (datetime.utcnow() - started).total_seconds(),
                "checks": readiness,
                "command": command,
                "files": written_files,
                "response": response_payload,
                "logs": {"stdout": completed.stdout[-4000:], "stderr": completed.stderr[-4000:]},
                **({} if success else {"error": contract_error or response_payload.get("error") or "Local container smoke test did not produce a successful response."}),
            }

    @serialize_registry("component-installation")
    def install_component(self, payload: Dict[str, Any], *, user: User) -> Dict[str, Any]:
        try:
            request_id = str(UUID(payload["request_id"])) if payload.get("request_id") else None
        except (ValueError, TypeError, AttributeError):
            raise ValidationError("request_id must be a UUID")
        fingerprint = _sha256({key: value for key, value in payload.items() if key != "request_id"})
        if request_id:
            existing = HpcComponentInstallation.query.filter_by(public_id=request_id).first()
            if existing:
                if existing.created_by != user.id or _json_loads(existing.checks_json, {}).get("request_fingerprint") != fingerprint:
                    raise OperationConflict("This request identifier already belongs to another installation.")
                self.reconcile_installation(existing)
                return {"installation": self._serialize_installation(existing), "reused": True}
        validation = self.validate_install_payload(payload)
        validation["checks"]["request_fingerprint"] = fingerprint
        strategy = validation["install_strategy"]
        required_check_name = "local_container" if strategy == INSTALL_STRATEGY_LOCAL_CONTAINER else "hpc_link"
        required_check = (validation.get("checks") or {}).get(required_check_name) or {}
        if not isinstance(required_check, dict) or required_check.get("success") is not True:
            message = (
                "Local container validation did not confirm install readiness"
                if strategy == INSTALL_STRATEGY_LOCAL_CONTAINER
                else "HPC-Link validation did not confirm install readiness"
            )
            raise ValidationError(
                message,
                details={
                    "component_key": validation.get("component_key"),
                    "version": validation.get("version"),
                    "install_strategy": strategy,
                    required_check_name: required_check,
                },
            )
        manifest = validation["manifest"]
        component_key = validation["component_key"]
        version = validation["version"]
        row = HpcComponentInstallation(
            **({"public_id": request_id} if request_id else {}),
            component_key=component_key,
            version=version,
            status="installing",
            manifest_hash=validation["manifest_hash"],
            manifest_json=_json_dumps(manifest),
            checks_json=_json_dumps({"install_strategy": strategy, **validation["checks"]}),
            logs_json="{}",
            created_by=user.id,
        )
        db.session.add(row)
        db.session.commit()

        try:
            if strategy == INSTALL_STRATEGY_LOCAL_CONTAINER:
                image = validation["container"]["image"]
                image_id = validation["checks"]["local_container"].get("image_id")
                if not image_id:
                    raise ValidationError("Docker did not report an immutable image ID")
                retention = self._retain_local_container_image(
                    image_id, validation["checks"]["local_container"]["docker_path"],
                )
                validation["checks"]["image_retention"] = retention
                row.checks_json = _json_dumps({"install_strategy": strategy, **validation["checks"]})
                installed_manifest = self._with_local_container_image(manifest, image_id)
                imported = self._register_installed_component(
                    installed_manifest,
                    component_key=component_key,
                    version=version,
                    source_path=image,
                    source_type="local_container_installed",
                )
                version_row = (
                    ComponentVersion.query.join(ComponentDefinition)
                    .filter(ComponentDefinition.key == component_key, ComponentVersion.version == version)
                    .first()
                )
                row.status = "installed"
                row.component_version_id = version_row.id if version_row else None
                row.sif_remote_path = None
                row.remote_install_dir = image
                row.manifest_json = _json_dumps(installed_manifest)
                row.logs_json = _json_dumps({"install": {"message": "Registered local Docker image component."}})
                row.error = None
                row.installed_at = datetime.utcnow()
                db.session.commit()
                return {"installation": self._serialize_installation(row), "component": imported}

            hpc_payload = {
                "request_id": row.public_id,
                "component_key": component_key,
                "version": version,
                "sif_source": validation["sif"]["sif_source"],
                "source_type": validation["sif"]["source_type"],
                "manifest": manifest,
                "manifest_hash": validation["manifest_hash"],
            }
            if validation["sif"].get("sha256"):
                hpc_payload["sif_sha256"] = validation["sif"]["sha256"]
            remote = current_app.hpc_allocation_service.client().post(
                "/api/apps/webhdp/components/install",
                hpc_payload,
                timeout=float(payload.get("timeout_seconds") or 7200),
            )
            sif_path = str(remote.get("sif_remote_path") or validation["sif"]["sif_source"])
            checksum = remote.get("sif_sha256") or validation["sif"].get("sha256")
            if not checksum:
                raise ValidationError("HPC-Link did not report the installed SIF checksum. Upgrade the adapter before registering this component.")
            installed_manifest = self._with_installed_image(manifest, sif_path)
            for profile in installed_manifest.get("execution", {}).get("profiles", []):
                if profile.get("handler") == "generic_singularity_component":
                    profile["sif_sha256"] = checksum
                    profile["version"] = version
            imported = self._register_installed_component(
                installed_manifest,
                component_key=component_key,
                version=version,
                source_path=str(remote.get("remote_install_dir") or ""),
                source_type="hpc_installed",
            )
            version_row = (
                ComponentVersion.query.join(ComponentDefinition)
                .filter(ComponentDefinition.key == component_key, ComponentVersion.version == version)
                .first()
            )
            row.status = "installed"
            row.component_version_id = version_row.id if version_row else None
            row.sif_remote_path = sif_path
            row.remote_install_dir = str(remote.get("remote_install_dir") or "")
            row.manifest_json = _json_dumps(installed_manifest)
            row.checks_json = _json_dumps(
                {
                    "install_strategy": strategy,
                    **validation["checks"],
                    **(remote.get("checks") or {}),
                }
            )
            row.logs_json = _json_dumps(remote.get("logs") or {})
            row.error = None
            row.installed_at = datetime.utcnow()
            db.session.commit()
            return {"installation": self._serialize_installation(row), "component": imported}
        except Exception as exc:
            uncertain = strategy == INSTALL_STRATEGY_HPC_SIF and isinstance(exc, (APITimeoutError, APIConnectionError)) and ((getattr(exc, "details", {}) or {}).get("http_status") or 500) >= 500
            row.status = "unknown" if uncertain else "failed"
            row.error = "Remote installation outcome is unknown. Reconnect before retrying. " + str(exc) if uncertain else str(exc)
            db.session.commit()
            raise

    @serialize_registry("native-registry")
    def reconcile_installation(self, row):
        checks = _json_loads(row.checks_json, {})
        if row.status not in {"unknown", "installing"} or checks.get("install_strategy") != INSTALL_STRATEGY_HPC_SIF:
            return
        try:
            remote = current_app.hpc_allocation_service.client().get(f"/api/apps/webhdp/components/{row.component_key}/{row.version}", timeout=30)
        except (APIConnectionError, APITimeoutError):
            return
        if remote.get("request_id") != row.public_id or remote.get("manifest_hash") != row.manifest_hash or not remote.get("sif_sha256"):
            return
        manifest = self._with_installed_image(_json_loads(row.manifest_json, {}), remote["sif_remote_path"])
        for profile in manifest.get("execution", {}).get("profiles", []):
            if profile.get("handler") == "generic_singularity_component":
                profile.update(sif_sha256=remote["sif_sha256"], version=row.version)
        self._register_installed_component(manifest, component_key=row.component_key, version=row.version, source_path=remote["sif_remote_path"], source_type="hpc_installed")
        version = ComponentVersion.query.join(ComponentDefinition).filter(ComponentDefinition.key == row.component_key, ComponentVersion.version == row.version).one()
        row.component_version_id = version.id
        row.status = "installed"
        row.error = None
        row.installed_at = datetime.utcnow()
        row.sif_remote_path = remote["sif_remote_path"]
        row.remote_install_dir = remote["remote_install_dir"]
        row.manifest_json = _json_dumps(manifest)
        db.session.commit()

    def list_installations(self) -> list[Dict[str, Any]]:
        rows = HpcComponentInstallation.query.order_by(HpcComponentInstallation.created_at.desc()).limit(100).all()
        return [self._serialize_installation(row) for row in rows]

    def get_installation(self, public_id: str) -> HpcComponentInstallation:
        row = HpcComponentInstallation.query.filter_by(public_id=public_id).first()
        if row is None:
            raise ResourceNotFoundError("HPC component installation not found")
        return row

    def test_installation(self, public_id: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        row = self.get_installation(public_id)
        payload = payload or {}
        if row.status != "installed":
            raise ValidationError("Only installed components can be tested")
        manifest = _json_loads(row.manifest_json, {})
        checks = _json_loads(row.checks_json, {})
        strategy = checks.get("install_strategy") or INSTALL_STRATEGY_HPC_SIF
        if strategy == INSTALL_STRATEGY_LOCAL_CONTAINER:
            image = str(self._local_container_profile(manifest).get("image") or row.remote_install_dir or "").strip()
            response = self._run_local_container_smoke_test(manifest, image, payload=payload)
            row.last_tested_at = datetime.utcnow()
            checks["last_test"] = response
            row.checks_json = _json_dumps(checks)
            row.error = None if response.get("success") else response.get("error")
            db.session.commit()
            return {"installation": self._serialize_installation(row), "test": response}
        try:
            response = current_app.hpc_allocation_service.client().post(
                "/api/apps/webhdp/components/test",
                {
                    "component_key": row.component_key,
                    "version": row.version,
                    "manifest": manifest,
                    "sif_remote_path": row.sif_remote_path,
                    "test": payload.get("test") or ((manifest.get("hpc") or {}).get("test") or {}),
                },
                timeout=float(payload.get("timeout_seconds") or 7200),
            )
            row.last_tested_at = datetime.utcnow()
            checks = _json_loads(row.checks_json, {})
            checks["last_test"] = response
            row.checks_json = _json_dumps(checks)
            db.session.commit()
            return {"installation": self._serialize_installation(row), "test": response}
        except Exception as exc:
            row.last_tested_at = datetime.utcnow()
            row.error = str(exc)
            db.session.commit()
            raise


# Neutral alias for new code.  The historical class/module/table names remain
# for migration compatibility with existing WebHDP installations.
ComponentInstallerService = HpcComponentInstallerService
