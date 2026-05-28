#!/usr/bin/env python3
"""
Small agent-facing CLI for WebHDP API operations.

Intended use:
- inspect health, sessions, workflow state, mappings, records, and submissions
- monitor ingestion/submission progress
- retry failed upload operations
- re-run the render pipeline for a session without using the UI
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import requests


DEFAULT_BASE_URL = os.environ.get("WEBHDP_BASE_URL", "http://127.0.0.1:5000/api/v1")
DEFAULT_BASE_URL_V2 = os.environ.get("WEBHDP_BASE_URL_V2", "http://127.0.0.1:5000/api/v2")
DEFAULT_EMAIL = os.environ.get("WEBHDP_EMAIL")
DEFAULT_PASSWORD = os.environ.get("WEBHDP_PASSWORD")
DEFAULT_TOKEN = os.environ.get("WEBHDP_TOKEN")
DEFAULT_TIMEOUT = float(os.environ.get("WEBHDP_TIMEOUT", "60"))

SECRET_PATTERNS = {
    "bearer_token": re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    "zenodo_token": re.compile(r"(?i)\bZENODO(?:_SANDBOX)?_API_KEY\s*=\s*[^\s#]+"),
    "access_token": re.compile(r"(?i)\baccess_token\s*[=:]\s*[A-Za-z0-9._~+/=-]{12,}"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
}


def _json_dump(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


def _extract_response_payload(response: requests.Response) -> Any:
    try:
        data = response.json()
    except ValueError:
        response.raise_for_status()
        return response.text
    if response.status_code >= 400:
        raise RuntimeError(json.dumps(data, ensure_ascii=False))
    return data


class WebHDPClient:
    def __init__(
        self,
        *,
        base_url: str,
        base_url_v2: str = DEFAULT_BASE_URL_V2,
        token: str | None = None,
        email: str | None = None,
        password: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.base_url_v2 = base_url_v2.rstrip("/")
        self.email = email
        self.password = password
        self.timeout = timeout
        self.session = requests.Session()
        self.token = token

    def ensure_token(self) -> str:
        if self.token:
            return self.token
        if not self.email or not self.password:
            raise RuntimeError(
                "Authentication required. Provide --token or set/provide --email and --password."
            )
        response = self.session.post(
            f"{self.base_url}/auth/login",
            json={"email": self.email, "password": self.password},
            timeout=self.timeout,
        )
        payload = _extract_response_payload(response)
        token = payload.get("data", {}).get("access_token")
        if not token:
            raise RuntimeError(f"Login succeeded but no access token returned: {payload}")
        self.token = token
        return token

    def request(
        self,
        method: str,
        path: str,
        *,
        auth: bool = True,
        params: Dict[str, Any] | None = None,
        json_body: Dict[str, Any] | None = None,
    ) -> Any:
        headers: Dict[str, str] = {}
        if auth:
            headers["Authorization"] = f"Bearer {self.ensure_token()}"
        response = self.session.request(
            method=method.upper(),
            url=f"{self.base_url}{path}",
            headers=headers,
            params=params,
            json=json_body,
            timeout=self.timeout,
        )
        return _extract_response_payload(response)

    def request_v2(
        self,
        method: str,
        path: str,
        *,
        auth: bool = True,
        params: Dict[str, Any] | None = None,
        json_body: Dict[str, Any] | None = None,
    ) -> Any:
        headers: Dict[str, str] = {}
        if auth:
            headers["Authorization"] = f"Bearer {self.ensure_token()}"
        response = self.session.request(
            method=method.upper(),
            url=f"{self.base_url_v2}{path}",
            headers=headers,
            params=params,
            json=json_body,
            timeout=self.timeout,
        )
        return _extract_response_payload(response)


def _paths_from_records(records_payload: Dict[str, Any]) -> list[str]:
    records = records_payload.get("data", {}).get("records") or records_payload.get("records") or []
    file_paths: list[str] = []
    for record in records:
        source_path = record.get("source_file_path")
        if source_path and source_path not in file_paths:
            file_paths.append(source_path)
            continue

        record_files = record.get("files") or []
        for file_entry in record_files:
            if str(file_entry.get("file_purpose") or "").lower() != "main":
                continue
            path = file_entry.get("absolute_path") or file_entry.get("path")
            if path and path not in file_paths:
                file_paths.append(path)
    return file_paths


def _payload_data(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def _load_env_file(path: str | None) -> None:
    if not path:
        return
    env_path = Path(path).expanduser()
    if not env_path.is_file():
        raise RuntimeError(f"Env file not found: {env_path}")
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def _load_json_arg(*, json_text: str | None = None, json_file: str | None = None) -> dict[str, Any]:
    if json_file:
        with open(json_file, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    elif json_text:
        payload = json.loads(json_text)
    else:
        payload = {}
    if not isinstance(payload, dict):
        raise RuntimeError("Expected a JSON object")
    return payload


def _record_file_names(record: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("source_file_path", "absolute_path", "file_path", "path"):
        value = record.get(key)
        if value:
            names.append(os.path.basename(str(value)))
    for item in record.get("files") or []:
        if not isinstance(item, dict):
            continue
        for key in ("filename", "name", "file_path", "absolute_path", "path", "mapped_file_path"):
            value = item.get(key)
            if value:
                names.append(os.path.basename(str(value)))
                break
    return [name for name in names if name]


def _artifact_path_exists(path: str | None) -> bool:
    if not path:
        return False
    try:
        return Path(path).is_file() and Path(path).stat().st_size > 0
    except OSError:
        return False


def _validation_report_ok(path: str | None) -> bool:
    if not _artifact_path_exists(path):
        return False
    try:
        payload = json.loads(Path(str(path)).read_text(encoding="utf-8", errors="ignore"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return True
    for key in ("valid", "is_valid", "success"):
        if key in payload:
            return bool(payload[key])
    if isinstance(payload.get("errors"), list):
        return len(payload["errors"]) == 0
    status = str(payload.get("status") or "").lower()
    return not status or status in {"ok", "valid", "passed", "success", "successful"}


def _record_file_entries(record: dict[str, Any]) -> list[dict[str, str | None]]:
    entries: list[dict[str, str | None]] = []
    for key in ("source_file_path", "absolute_path", "file_path", "path"):
        value = record.get(key)
        if value:
            text = str(value)
            entries.append({"filename": os.path.basename(text), "path": text})
    for item in record.get("files") or []:
        if not isinstance(item, dict):
            continue
        path = item.get("absolute_path") or item.get("path") or item.get("file_path") or item.get("mapped_file_path")
        filename = item.get("filename") or item.get("name") or (os.path.basename(str(path)) if path else None)
        if filename:
            entries.append({"filename": str(filename), "path": str(path) if path else None})
    return entries


def build_artifact_audit(records_payload: dict[str, Any], *, required_pngs: int = 5, require_existing_files: bool = False) -> dict[str, Any]:
    data = _payload_data(records_payload)
    records = data.get("records") if isinstance(data, dict) else []
    if not isinstance(records, list):
        records = []
    results = []
    summary = {
        "records": len(records),
        "complete": 0,
        "incomplete": 0,
        "published": 0,
        "draft": 0,
        "quarantined": 0,
    }
    for record in records:
        if not isinstance(record, dict):
            continue
        status = str(record.get("record_status") or record.get("status") or "").lower()
        if status in summary:
            summary[status] += 1
        entries = _record_file_entries(record)
        names = [str(entry.get("filename") or "").lower() for entry in entries]

        def matching(*suffixes: str, contains: tuple[str, ...] = ()) -> list[dict[str, str | None]]:
            found = []
            for entry, name in zip(entries, names):
                if suffixes and not name.endswith(suffixes):
                    continue
                if contains and not any(fragment in name for fragment in contains):
                    continue
                found.append(entry)
            return found

        def present(items: list[dict[str, str | None]]) -> bool:
            if not items:
                return False
            return any(_artifact_path_exists(item.get("path")) for item in items) if require_existing_files else True

        png_items = matching(".png")
        png_count = sum(1 for item in png_items if _artifact_path_exists(item.get("path"))) if require_existing_files else len(png_items)
        edm_validation_items = matching(".json", contains=("edm.validation",))
        checks = {
            "source_model": present(matching(".glb", ".gltf", ".obj", ".fbx", ".ply", ".stl", ".dae", ".3ds", ".blend")),
            "usdz": present(matching(".usdz")),
            "png_renders": png_count >= required_pngs,
            "edm_xml": present(matching(".xml", contains=("edm",))),
            "mets_mods_xml": present(matching(".xml", contains=("mets", "mods"))),
            "iiif_json": present(matching(".json", ".jsonld", contains=("iiif", "manifest"))),
            "edm_validation": bool(edm_validation_items)
            and (any(_validation_report_ok(item.get("path")) for item in edm_validation_items) if require_existing_files else True),
        }
        missing = [key for key, ok in checks.items() if not ok]
        complete = not missing
        summary["complete" if complete else "incomplete"] += 1
        results.append(
            {
                "record_id": record.get("record_id") or record.get("id") or record.get("local_record_id"),
                "title": record.get("title") or record.get("record_title"),
                "status": status or None,
                "complete": complete,
                "missing": missing,
                "checks": checks,
                "file_count": len(entries),
            }
        )
    return {"ok": summary["incomplete"] == 0, "summary": summary, "records": results}


def scan_secret_paths(paths: list[str]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    scanned_files = 0
    for raw_path in paths:
        root = Path(raw_path).expanduser()
        candidates = [root]
        if root.is_dir():
            candidates = [path for path in root.rglob("*") if path.is_file()]
        for path in candidates:
            if not path.is_file():
                continue
            scanned_files += 1
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for line_number, line in enumerate(lines, start=1):
                for name, pattern in SECRET_PATTERNS.items():
                    if pattern.search(line):
                        findings.append({"path": str(path), "line": line_number, "pattern": name})
    return {"ok": not findings, "scanned_files": scanned_files, "finding_count": len(findings), "findings": findings}


def cmd_login(client: WebHDPClient, _args: argparse.Namespace) -> None:
    print(client.ensure_token())


def cmd_health(client: WebHDPClient, _args: argparse.Namespace) -> None:
    _json_dump(client.request("GET", "/health", auth=False))


def cmd_local_msf(client: WebHDPClient, _args: argparse.Namespace) -> None:
    _json_dump(client.request("GET", "/sessions/local-msf"))


def cmd_sessions(client: WebHDPClient, _args: argparse.Namespace) -> None:
    _json_dump(client.request("GET", "/sessions"))


def cmd_session(client: WebHDPClient, args: argparse.Namespace) -> None:
    _json_dump(client.request("GET", f"/sessions/{args.session_id}"))


def cmd_workflow_state(client: WebHDPClient, args: argparse.Namespace) -> None:
    _json_dump(client.request("GET", f"/sessions/{args.session_id}/workflow-state"))


def cmd_metadata(client: WebHDPClient, args: argparse.Namespace) -> None:
    _json_dump(client.request("GET", f"/metadata/user/{args.session_id}"))


def cmd_upload_operations(client: WebHDPClient, args: argparse.Namespace) -> None:
    route = "/admin/upload-operations" if args.admin else "/sessions/upload-operations"
    params = {"status": args.status} if args.admin and args.status else None
    _json_dump(client.request("GET", route, params=params))


def cmd_upload_operation(client: WebHDPClient, args: argparse.Namespace) -> None:
    _json_dump(client.request("GET", f"/sessions/upload-operations/{args.session_id}"))


def cmd_resume_session(client: WebHDPClient, args: argparse.Namespace) -> None:
    _json_dump(client.request("POST", f"/sessions/{args.session_id}/resume", json_body={}))


def cmd_records(client: WebHDPClient, args: argparse.Namespace) -> None:
    _json_dump(client.request("GET", f"/sessions/{args.session_id}/records"))


def cmd_record(client: WebHDPClient, args: argparse.Namespace) -> None:
    _json_dump(client.request("GET", f"/sessions/{args.session_id}/records/{args.record_id}"))


def cmd_provenance(client: WebHDPClient, args: argparse.Namespace) -> None:
    _json_dump(client.request("GET", f"/sessions/{args.session_id}/provenance-report"))


def cmd_submissions(client: WebHDPClient, args: argparse.Namespace) -> None:
    route = "/admin/submissions" if args.admin else "/submissions"
    _json_dump(client.request("GET", route))


def cmd_submission(client: WebHDPClient, args: argparse.Namespace) -> None:
    route = f"/admin/submissions/{args.submission_id}" if args.admin else f"/submissions/{args.submission_id}"
    _json_dump(client.request("GET", route))


def cmd_submission_progress(client: WebHDPClient, args: argparse.Namespace) -> None:
    _json_dump(client.request("GET", f"/submissions/{args.submission_id}/progress"))


def cmd_monitor_submission(client: WebHDPClient, args: argparse.Namespace) -> None:
    deadline = time.time() + args.timeout if args.timeout > 0 else None
    while True:
        payload = client.request("GET", f"/submissions/{args.submission_id}/progress")
        data = _payload_data(payload)
        status = str(data.get("status") or "unknown")
        progress = data.get("progress") or {}
        summary = {
            "submission_id": data.get("submission_id"),
            "status": status,
            "current_stage": progress.get("current_stage"),
            "status_message": progress.get("status_message"),
            "processed_count": progress.get("processed_count"),
            "failed_count": progress.get("failed_count"),
            "completed_at": data.get("completed_at"),
            "error": data.get("error"),
        }
        _json_dump(summary)
        if status in {"completed", "failed"}:
            return
        if deadline is not None and time.time() >= deadline:
            raise RuntimeError(f"Timed out while waiting for submission {args.submission_id}")
        time.sleep(args.interval)


def cmd_renderer_status(client: WebHDPClient, _args: argparse.Namespace) -> None:
    _json_dump(client.request("GET", "/admin/pipelines/render/status"))


def cmd_storage_status(client: WebHDPClient, _args: argparse.Namespace) -> None:
    _json_dump(client.request("GET", "/admin/storage-status"))


def cmd_prepare_local_msf(client: WebHDPClient, args: argparse.Namespace) -> None:
    payload = {
        "msf_path": args.msf_path,
        "directory_path": args.directory_path,
        "parse_options": {"delimiter": args.delimiter, "use_first_row_as_header": True},
        "recursive": args.recursive,
        "duplicate_policy": args.duplicate_policy,
        "default_zenodo_environment": args.zenodo_environment,
        "credential_preference": args.credential_preference,
    }
    if args.sheet_name:
        payload["parse_options"]["sheet_name"] = args.sheet_name
    _json_dump(client.request("POST", "/msf/workflow/local/prepare", json_body=payload))


def cmd_update_metadata_draft(client: WebHDPClient, args: argparse.Namespace) -> None:
    payload = _load_json_arg(json_text=args.metadata_json, json_file=args.metadata_file)
    _json_dump(client.request("PUT", f"/metadata/user/{args.session_id}/draft", json_body=payload))


def cmd_start_local_scan(client: WebHDPClient, args: argparse.Namespace) -> None:
    payload = client.request("POST", f"/msf/workflow/session/{args.session_id}/start-local-scan", json_body={})
    _json_dump(payload)
    data = _payload_data(payload)
    task_id = data.get("task_id") if isinstance(data, dict) else None
    if args.wait and task_id:
        _monitor_task(client, task_id, interval=args.interval, timeout=args.timeout)


def cmd_task(client: WebHDPClient, args: argparse.Namespace) -> None:
    _json_dump(client.request("GET", f"/sessions/tasks/{args.task_id}"))


def _monitor_task(client: WebHDPClient, task_id: str, *, interval: float, timeout: float) -> None:
    deadline = time.time() + timeout if timeout > 0 else None
    while True:
        payload = client.request("GET", f"/sessions/tasks/{task_id}")
        data = _payload_data(payload)
        _json_dump(data)
        state = str((data or {}).get("state") or "").upper() if isinstance(data, dict) else ""
        if state in {"SUCCESS", "FAILURE", "REVOKED"}:
            if state != "SUCCESS":
                raise RuntimeError(f"Task {task_id} ended with state {state}")
            return
        if deadline is not None and time.time() >= deadline:
            raise RuntimeError(f"Timed out while waiting for task {task_id}")
        time.sleep(interval)


def cmd_monitor_task(client: WebHDPClient, args: argparse.Namespace) -> None:
    _monitor_task(client, args.task_id, interval=args.interval, timeout=args.timeout)


def cmd_execute_render(client: WebHDPClient, args: argparse.Namespace) -> None:
    local_file_paths = list(args.file or [])
    if args.from_records:
        records_payload = client.request("GET", f"/sessions/{args.session_id}/records")
        local_file_paths = _paths_from_records(records_payload)
    if not local_file_paths:
        raise RuntimeError("No local file paths provided. Use --file or --from-records.")

    payload = {
        "session_id": args.session_id,
        "local_file_paths": local_file_paths,
        "is_sandbox": args.sandbox,
        "async_execution": True,
        "abort_on_critical_error": args.abort_on_critical_error,
    }
    response = client.request("POST", "/pipelines/render/execute_on_local_files", json_body=payload)
    _json_dump(response)


def cmd_execute_native_pipeline(client: WebHDPClient, args: argparse.Namespace) -> None:
    local_file_paths = list(args.file or [])
    if args.from_records:
        records_payload = client.request("GET", f"/sessions/{args.session_id}/records")
        local_file_paths = _paths_from_records(records_payload)
    payload = {
        "session_id": args.session_id,
        "local_file_paths": local_file_paths,
        "record_ids": args.record_id or [],
        "is_sandbox": args.sandbox,
        "async_execution": args.async_execution,
        "abort_on_critical_error": args.abort_on_critical_error,
    }
    if args.execution_items_file:
        items = json.loads(Path(args.execution_items_file).read_text(encoding="utf-8"))
        if not isinstance(items, list):
            raise RuntimeError("execution-items-file must contain a JSON array")
        payload["execution_items"] = items
    response = client.request_v2("POST", f"/pipelines/{args.pipeline}/execute", json_body=payload)
    _json_dump(response)


def cmd_run_status(client: WebHDPClient, args: argparse.Namespace) -> None:
    _json_dump(client.request_v2("GET", f"/runs/{args.run_id}"))


def cmd_monitor_run(client: WebHDPClient, args: argparse.Namespace) -> None:
    deadline = time.time() + args.timeout if args.timeout > 0 else None
    while True:
        payload = client.request_v2("GET", f"/runs/{args.run_id}")
        data = _payload_data(payload)
        run = (data or {}).get("run") if isinstance(data, dict) else {}
        summary = {
            "run_id": args.run_id,
            "status": (run or {}).get("status"),
            "progress": ((run or {}).get("result") or {}).get("progress"),
            "error": (run or {}).get("error"),
        }
        _json_dump(summary)
        if summary["status"] in {"completed", "failed", "cancelled"}:
            if summary["status"] != "completed":
                raise RuntimeError(f"Run {args.run_id} ended with status {summary['status']}")
            return
        if deadline is not None and time.time() >= deadline:
            raise RuntimeError(f"Timed out while waiting for run {args.run_id}")
        time.sleep(args.interval)


def cmd_artifact_audit(client: WebHDPClient, args: argparse.Namespace) -> None:
    records_payload = client.request("GET", f"/sessions/{args.session_id}/records")
    audit = build_artifact_audit(
        records_payload,
        required_pngs=args.required_pngs,
        require_existing_files=args.require_existing_files,
    )
    _json_dump(audit)
    if args.fail_on_incomplete and not audit["ok"]:
        raise RuntimeError("Artifact audit failed")


def cmd_secret_scan(_client: WebHDPClient, args: argparse.Namespace) -> None:
    _json_dump(scan_secret_paths(args.path))


def cmd_hpc_readiness(_client: WebHDPClient, args: argparse.Namespace) -> None:
    root = Path(args.root).expanduser()
    env_file = Path(args.env_file).expanduser() if args.env_file else root / ".env.hpc.singularity"
    sif_dir = Path(args.sif_dir).expanduser() if args.sif_dir else root / "images" / "sif"
    required_sifs = ["backend.sif", "fast-renderer.sif", "any-to-usdz.sif", "redis.sif"]
    disk_path = root
    while not disk_path.exists() and disk_path != disk_path.parent:
        disk_path = disk_path.parent
    free_gb = shutil.disk_usage(disk_path).free / (1024**3)
    checks: dict[str, Any] = {}
    checks["root"] = {"ok": root.is_dir(), "path": str(root)}
    checks["env_file"] = {"ok": env_file.is_file(), "path": str(env_file)}
    if env_file.exists():
        mode = env_file.stat().st_mode & 0o777
        checks["env_file"]["mode"] = oct(mode)
        checks["env_file"]["private"] = mode & 0o077 == 0
        checks["env_file"]["ok"] = checks["env_file"]["ok"] and checks["env_file"]["private"]
    checks["sif_dir"] = {"ok": sif_dir.is_dir(), "path": str(sif_dir)}
    checks["sifs"] = {name: (sif_dir / name).is_file() for name in required_sifs}
    checks["disk"] = {"ok": free_gb >= args.min_free_disk_gb, "free_gb": round(free_gb, 2), "min_free_gb": args.min_free_disk_gb, "path": str(disk_path)}
    for path_name in ("logs", "logs-sing", "run", "hdp-shared/sessions", "data/local_input", "data/local_output"):
        path = root / path_name
        checks[path_name] = {"ok": path.exists() and os.access(path, os.W_OK), "path": str(path)}
    checks["commands"] = {
        name: _command_exists(name)
        for name in ("sbatch", "squeue", "sacct", "singularity", "tmux", "nvidia-smi", "ffmpeg", "ffprobe")
    }
    checks["proxy"] = {
        "ok": bool(os.environ.get("NO_PROXY") or os.environ.get("no_proxy"))
        if any(os.environ.get(key) for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"))
        else True,
        "http_proxy": bool(os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")),
        "https_proxy": bool(os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")),
        "no_proxy": bool(os.environ.get("NO_PROXY") or os.environ.get("no_proxy")),
    }
    if args.health:
        try:
            response = requests.get(args.health, timeout=args.timeout)
            checks["health"] = {"ok": response.ok, "status_code": response.status_code, "url": args.health}
        except requests.RequestException as exc:
            checks["health"] = {"ok": False, "error": str(exc), "url": args.health}
    ok = all(
        value.get("ok", all(value.values()) if isinstance(value, dict) else bool(value))
        for key, value in checks.items()
        if key not in {"commands", "sifs"}
    ) and all(checks["sifs"].values()) and all(checks["commands"].values())
    payload = {"ok": bool(ok), "checks": checks}
    _json_dump(payload)
    if args.fail and not payload["ok"]:
        raise RuntimeError("HPC readiness failed")


def _command_exists(name: str) -> bool:
    return any((Path(part) / name).exists() for part in os.environ.get("PATH", "").split(os.pathsep) if part)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agent-oriented WebHDP API CLI")
    parser.add_argument("--env-file", help="Load WEBHDP_* credentials/settings from a chmod-600 env file")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API base URL, e.g. http://127.0.0.1:18081/api/v1")
    parser.add_argument("--base-url-v2", default=DEFAULT_BASE_URL_V2, help="API v2 base URL, e.g. http://127.0.0.1:18081/api/v2")
    parser.add_argument("--token", default=DEFAULT_TOKEN, help="JWT token")
    parser.add_argument("--token-file", help="Read JWT token from a chmod-600 file")
    parser.add_argument("--email", default=DEFAULT_EMAIL, help="Login email")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Login password")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="HTTP timeout in seconds")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("login").set_defaults(func=cmd_login)
    subparsers.add_parser("health").set_defaults(func=cmd_health)
    subparsers.add_parser("local-msf").set_defaults(func=cmd_local_msf)
    subparsers.add_parser("sessions").set_defaults(func=cmd_sessions)

    session_parser = subparsers.add_parser("session")
    session_parser.add_argument("session_id", type=int)
    session_parser.set_defaults(func=cmd_session)

    workflow_parser = subparsers.add_parser("workflow-state")
    workflow_parser.add_argument("session_id", type=int)
    workflow_parser.set_defaults(func=cmd_workflow_state)

    metadata_parser = subparsers.add_parser("metadata")
    metadata_parser.add_argument("session_id", type=int)
    metadata_parser.set_defaults(func=cmd_metadata)

    upload_ops_parser = subparsers.add_parser("upload-operations")
    upload_ops_parser.add_argument("--admin", action="store_true", help="Use admin upload operations route")
    upload_ops_parser.add_argument("--status", help="Admin status filter: running/completed/failed")
    upload_ops_parser.set_defaults(func=cmd_upload_operations)

    upload_op_parser = subparsers.add_parser("upload-operation")
    upload_op_parser.add_argument("session_id", type=int)
    upload_op_parser.set_defaults(func=cmd_upload_operation)

    resume_parser = subparsers.add_parser("resume-session")
    resume_parser.add_argument("session_id", type=int)
    resume_parser.set_defaults(func=cmd_resume_session)

    records_parser = subparsers.add_parser("records")
    records_parser.add_argument("session_id", type=int)
    records_parser.set_defaults(func=cmd_records)

    record_parser = subparsers.add_parser("record")
    record_parser.add_argument("session_id", type=int)
    record_parser.add_argument("record_id", type=int)
    record_parser.set_defaults(func=cmd_record)

    provenance_parser = subparsers.add_parser("provenance")
    provenance_parser.add_argument("session_id", type=int)
    provenance_parser.set_defaults(func=cmd_provenance)

    submissions_parser = subparsers.add_parser("submissions")
    submissions_parser.add_argument("--admin", action="store_true")
    submissions_parser.set_defaults(func=cmd_submissions)

    submission_parser = subparsers.add_parser("submission")
    submission_parser.add_argument("submission_id", type=int)
    submission_parser.add_argument("--admin", action="store_true")
    submission_parser.set_defaults(func=cmd_submission)

    progress_parser = subparsers.add_parser("submission-progress")
    progress_parser.add_argument("submission_id", type=int)
    progress_parser.set_defaults(func=cmd_submission_progress)

    monitor_parser = subparsers.add_parser("monitor-submission")
    monitor_parser.add_argument("submission_id", type=int)
    monitor_parser.add_argument("--interval", type=float, default=5.0)
    monitor_parser.add_argument("--timeout", type=float, default=0.0, help="0 means wait indefinitely")
    monitor_parser.set_defaults(func=cmd_monitor_submission)

    renderer_parser = subparsers.add_parser("renderer-status")
    renderer_parser.set_defaults(func=cmd_renderer_status)

    storage_parser = subparsers.add_parser("storage-status")
    storage_parser.set_defaults(func=cmd_storage_status)

    prepare_parser = subparsers.add_parser("prepare-local-msf")
    prepare_parser.add_argument("--msf-path", required=True)
    prepare_parser.add_argument("--directory-path", required=True)
    prepare_parser.add_argument("--delimiter", default=",")
    prepare_parser.add_argument("--sheet-name")
    prepare_parser.add_argument("--recursive", action=argparse.BooleanOptionalAction, default=True)
    prepare_parser.add_argument("--duplicate-policy", default="merge_non_empty")
    prepare_parser.add_argument("--zenodo-environment", default="production", choices=["sandbox", "production"])
    prepare_parser.add_argument("--credential-preference", default="user")
    prepare_parser.set_defaults(func=cmd_prepare_local_msf)

    metadata_update_parser = subparsers.add_parser("update-metadata-draft")
    metadata_update_parser.add_argument("session_id", type=int)
    metadata_update_parser.add_argument("--metadata-json")
    metadata_update_parser.add_argument("--metadata-file")
    metadata_update_parser.set_defaults(func=cmd_update_metadata_draft)

    scan_parser = subparsers.add_parser("start-local-scan")
    scan_parser.add_argument("session_id", type=int)
    scan_parser.add_argument("--wait", action="store_true")
    scan_parser.add_argument("--interval", type=float, default=10.0)
    scan_parser.add_argument("--timeout", type=float, default=0.0)
    scan_parser.set_defaults(func=cmd_start_local_scan)

    task_parser = subparsers.add_parser("task")
    task_parser.add_argument("task_id")
    task_parser.set_defaults(func=cmd_task)

    monitor_task_parser = subparsers.add_parser("monitor-task")
    monitor_task_parser.add_argument("task_id")
    monitor_task_parser.add_argument("--interval", type=float, default=10.0)
    monitor_task_parser.add_argument("--timeout", type=float, default=0.0)
    monitor_task_parser.set_defaults(func=cmd_monitor_task)

    execute_parser = subparsers.add_parser("execute-render")
    execute_parser.add_argument("session_id", type=int)
    execute_parser.add_argument("--file", action="append", help="Absolute local file path to process", default=[])
    execute_parser.add_argument("--from-records", action="store_true", help="Resolve file paths from /sessions/<id>/records")
    execute_parser.add_argument("--sandbox", action=argparse.BooleanOptionalAction, default=True)
    execute_parser.add_argument("--abort-on-critical-error", action="store_true")
    execute_parser.set_defaults(func=cmd_execute_render)

    native_parser = subparsers.add_parser("execute-native-pipeline")
    native_parser.add_argument("session_id", type=int)
    native_parser.add_argument("--pipeline", default="render")
    native_parser.add_argument("--file", action="append", default=[])
    native_parser.add_argument("--from-records", action="store_true")
    native_parser.add_argument("--record-id", action="append", type=int, default=[])
    native_parser.add_argument("--execution-items-file")
    native_parser.add_argument("--sandbox", action=argparse.BooleanOptionalAction, default=True)
    native_parser.add_argument("--async-execution", action=argparse.BooleanOptionalAction, default=True)
    native_parser.add_argument("--abort-on-critical-error", action="store_true")
    native_parser.set_defaults(func=cmd_execute_native_pipeline)

    run_parser = subparsers.add_parser("run-status")
    run_parser.add_argument("run_id")
    run_parser.set_defaults(func=cmd_run_status)

    monitor_run_parser = subparsers.add_parser("monitor-run")
    monitor_run_parser.add_argument("run_id")
    monitor_run_parser.add_argument("--interval", type=float, default=30.0)
    monitor_run_parser.add_argument("--timeout", type=float, default=0.0)
    monitor_run_parser.set_defaults(func=cmd_monitor_run)

    audit_parser = subparsers.add_parser("artifact-audit")
    audit_parser.add_argument("session_id", type=int)
    audit_parser.add_argument("--required-pngs", type=int, default=5)
    audit_parser.add_argument("--require-existing-files", action="store_true")
    audit_parser.add_argument("--fail-on-incomplete", action="store_true")
    audit_parser.set_defaults(func=cmd_artifact_audit)

    secret_parser = subparsers.add_parser("secret-scan")
    secret_parser.add_argument("path", nargs="+")
    secret_parser.set_defaults(func=cmd_secret_scan)

    readiness_parser = subparsers.add_parser("hpc-readiness")
    readiness_parser.add_argument("--root", default="/home/webhdp-user/webhdp")
    readiness_parser.add_argument("--env-file")
    readiness_parser.add_argument("--sif-dir")
    readiness_parser.add_argument("--health")
    readiness_parser.add_argument("--min-free-disk-gb", type=float, default=25.0)
    readiness_parser.add_argument("--fail", action="store_true")
    readiness_parser.set_defaults(func=cmd_hpc_readiness)

    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    _load_env_file(args.env_file)
    base_url = args.base_url
    if base_url == DEFAULT_BASE_URL and os.environ.get("WEBHDP_BASE_URL"):
        base_url = os.environ["WEBHDP_BASE_URL"]
    base_url_v2 = args.base_url_v2
    if base_url_v2 == DEFAULT_BASE_URL_V2 and os.environ.get("WEBHDP_BASE_URL_V2"):
        base_url_v2 = os.environ["WEBHDP_BASE_URL_V2"]
    token = args.token
    if args.token_file:
        token = Path(args.token_file).expanduser().read_text(encoding="utf-8").strip()
    token = token or os.environ.get("WEBHDP_TOKEN")
    client = WebHDPClient(
        base_url=base_url,
        base_url_v2=base_url_v2,
        token=token,
        email=args.email or os.environ.get("WEBHDP_EMAIL"),
        password=args.password or os.environ.get("WEBHDP_PASSWORD"),
        timeout=args.timeout,
    )
    try:
        args.func(client, args)
    except requests.RequestException as exc:
        print(f"HTTP error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
