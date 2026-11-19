#!/usr/bin/env python3
"""Generate a lightweight OpenAPI contract from the Flask route map."""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "docs" / "api" / "openapi.json"
LINK_OUTPUT_PATH = ROOT / "docs" / "api" / "webhdp-link.openapi.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


PUBLIC_PATH_PREFIXES = (
    "/api/v1/docs/",
    "/api/v1/public/",
    "/api/v1/oembed",
    "/api/v1/profiles/",
    "/api/v1/p/records/",
    "/api/v1/model-publication/samples/",
)
PUBLIC_EXACT_PATHS = {
    "/api/v1/health",
    "/api/v1/auth/register",
    "/api/v1/auth/resend-verification",
    "/api/v1/auth/verify-email",
    "/api/v1/auth/verify-email/{token}",
    "/api/v1/auth/login",
    "/api/v1/auth/login/verify-code",
    "/api/v1/auth/login/verify-recovery-code",
    "/api/v1/auth/login/resend-code",
    "/api/v1/docs/index",
    "/api/v1/model-publication/samples",
    "/api/v1/link/discovery",
    "/api/v1/link/openapi.json",
    "/api/v1/link/oauth/request",
    "/api/v1/link/oauth/token",
    "/api/v1/link/oauth/revoke",
}


def _load_project_metadata() -> dict[str, str]:
    pyproject_path = ROOT / "pyproject.toml"
    version_path = ROOT / "version.json"
    name = "webhdp"
    version = "0.0.0"

    if pyproject_path.exists():
        with pyproject_path.open("rb") as handle:
            project = tomllib.load(handle).get("project", {})
            name = str(project.get("name") or name)
            version = str(project.get("version") or version)

    if version_path.exists():
        try:
            payload = json.loads(version_path.read_text(encoding="utf-8"))
            version = str(payload.get("version") or version)
        except json.JSONDecodeError:
            pass

    return {"name": name, "version": version}


def _flask_rule_to_openapi_path(rule: str) -> tuple[str, list[dict[str, Any]]]:
    parameters: list[dict[str, Any]] = []

    def replace(match: re.Match[str]) -> str:
        converter = match.group("converter")
        name = match.group("name")
        schema: dict[str, Any] = {"type": "string"}
        if converter == "int":
            schema = {"type": "integer"}
        elif converter == "float":
            schema = {"type": "number"}
        elif converter == "path":
            schema = {"type": "string", "description": "Path segment"}
        parameters.append(
            {
                "name": name,
                "in": "path",
                "required": True,
                "schema": schema,
            }
        )
        return "{" + name + "}"

    path = re.sub(r"<(?:(?P<converter>[a-zA-Z_][\w]*):)?(?P<name>[a-zA-Z_][\w]*)>", replace, rule)
    return path, parameters


def _tag_for_path(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 3 and parts[0] == "api":
        return parts[2]
    return parts[0] if parts else "root"


def _is_public(path: str) -> bool:
    if path in PUBLIC_EXACT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES)


def _operation_id(endpoint: str, method: str) -> str:
    normalized = re.sub(r"[^0-9a-zA-Z_]+", "_", endpoint).strip("_")
    return f"{method.lower()}_{normalized}"


def _build_spec() -> dict[str, Any]:
    os.environ.setdefault("SKIP_DB_CREATE_ALL", "1")
    os.environ.setdefault("WEBHDP_INLINE_TASKS", "true")
    os.environ.setdefault("FLASK_ENV", "development")

    from app import app

    metadata = _load_project_metadata()
    paths: dict[str, dict[str, Any]] = {}

    for rule in sorted(app.url_map.iter_rules(), key=lambda item: item.rule):
        if not rule.rule.startswith("/api/"):
            continue
        methods = sorted(method for method in rule.methods if method not in {"HEAD", "OPTIONS"})
        if not methods:
            continue

        path, parameters = _flask_rule_to_openapi_path(rule.rule)
        path_item = paths.setdefault(path, {})

        for method in methods:
            operation: dict[str, Any] = {
                "operationId": _operation_id(rule.endpoint, method),
                "tags": [_tag_for_path(path)],
                "summary": rule.endpoint.replace(".", " "),
                "responses": {
                    "200": {
                        "description": "Successful response. WebHDP API responses generally use {success, data, message, metadata}.",
                    },
                    "400": {"description": "Validation error"},
                    "401": {"description": "Authentication required or token invalid"},
                    "403": {"description": "Authenticated user is not authorized for this resource"},
                    "404": {"description": "Resource not found"},
                    "500": {"description": "Unexpected server error"},
                },
            }
            if parameters:
                operation["parameters"] = parameters
            if not _is_public(path):
                operation["security"] = [{"bearerAuth": []}]
            if path.startswith("/api/v1/link/"):
                operation["description"] = "WebHDP-Link uses raw JSON successes and RFC 9457 Problem Details. See the complete OpenAPI 3.1 contract at /api/v1/link/openapi.json."
                operation["responses"]["200"]["description"] = "See the dedicated WebHDP-Link contract for precise success status, response schema, and headers."
                internal = path.startswith(("/api/v1/link/admin/", "/api/v1/link/grants", "/api/v1/link/jobs")) or path == "/api/v1/link/oauth/authorize"
                if not internal and not _is_public(path):
                    operation["security"] = [{"linkBearer": []}]
            path_item[method.lower()] = operation

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "WebHDP API",
            "version": metadata["version"],
            "description": (
                "Generated from the Flask route map. This contract is an onboarding aid and route inventory; "
                "endpoint-specific request and response examples remain documented in docs/api/webhdp_api_reference.md "
                "and docs/api/webhdp_api_examples.md."
            ),
        },
        "servers": [
            {"url": "http://localhost:5000", "description": "Local Flask development server"},
            {"url": "http://localhost:8080", "description": "Docker/Vite proxied development server"},
        ],
        "components": {
            "securitySchemes": {
                "linkBearer": {"type": "http", "scheme": "bearer", "bearerFormat": "opaque WebHDP-Link token"},
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                }
            }
        },
        "paths": paths,
        "x-generated-by": "scripts/generate_openapi.py",
    }


def contracts() -> dict[Path, dict[str, Any]]:
    from services.webhdp_link_openapi import document

    return {
        OUTPUT_PATH: _build_spec(),
        LINK_OUTPUT_PATH: document("https://webhdp.example"),
    }


def main() -> int:
    for path, spec in contracts().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Wrote {path.relative_to(ROOT)} with {len(spec['paths'])} paths.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
