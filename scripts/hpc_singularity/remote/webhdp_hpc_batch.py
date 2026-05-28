#!/usr/bin/env python3
"""Generic Draco/HPC batch orchestrator for large WebHDP local-mode datasets.

The script is intentionally state-file driven.  Slurm jobs may time out or be
cancelled; the next invocation resumes from chunk state rather than relying on
shell history, tmux state, or an interactive operator.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import stat
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RETRYABLE_SLURM_STATES = {
    "TIMEOUT",
    "CANCELLED",
    "CANCELLED+",
    "NODE_FAIL",
    "PREEMPTED",
    "BOOT_FAIL",
    "OUT_OF_MEMORY",
    "FAILED",
    "QUEUE_TIMEOUT",
}
ACTIVE_SLURM_STATES = {"PENDING", "CONFIGURING", "RUNNING", "COMPLETING", "SUSPENDED"}
DEFAULT_DRACO_PARTITIONS = ["vascunet", "vis", "gpu", "gpu-test"]
TERMINAL_RUN_STATES = {"completed", "failed", "cancelled"}
TERMINAL_TASK_STATES = {"SUCCESS", "FAILURE", "REVOKED"}
STALE_ALLOCATION_STATES = {"prepared", "scanning", "executing", "running", "publishing"}
RECOVERY_STATUSES = {"needs_recovery", "quarantined"}
DEFAULT_REQUIRED_ARTIFACTS = {
    "source_model": True,
    "usdz": True,
    "png_renders": 5,
    "edm_xml": True,
    "mets_mods_xml": True,
    "iiif_json": True,
    "edm_validation": True,
}


@dataclass
class BatchConfig:
    raw: dict[str, Any]
    config_path: Path

    @property
    def root(self) -> Path:
        return Path(self.raw.get("root") or "/home/webhdp-user/webhdp").expanduser()

    @property
    def output_dir(self) -> Path:
        return Path(self.raw.get("output_dir") or self.root / "data/local_input/webhdp_batch").expanduser()

    @property
    def state_dir(self) -> Path:
        return Path(self.raw.get("state_dir") or self.root / "run/webhdp_batch_state").expanduser()

    @property
    def logs_dir(self) -> Path:
        return Path(self.raw.get("logs_dir") or self.root / "logs").expanduser()

    @property
    def event_log(self) -> Path:
        return self.state_dir / "events.jsonl"

    @property
    def report_path(self) -> Path:
        return Path(self.raw.get("report") or self.output_dir / "preparation_report.json").expanduser()

    @property
    def env_file(self) -> Path:
        return Path(self.raw.get("env_file") or self.root / ".env.hpc.singularity").expanduser()

    @property
    def container_input_root(self) -> str:
        return str(self.raw.get("container_input_root") or "/data/local_input/webhdp_batch").rstrip("/")

    @property
    def base_url(self) -> str:
        api = self.raw.get("api") if isinstance(self.raw.get("api"), dict) else {}
        return str(api.get("base_url") or os.environ.get("WEBHDP_BASE_URL") or "http://127.0.0.1:5600/api/v1").rstrip("/")

    @property
    def base_url_v2(self) -> str:
        api = self.raw.get("api") if isinstance(self.raw.get("api"), dict) else {}
        return str(api.get("base_url_v2") or os.environ.get("WEBHDP_BASE_URL_V2") or "http://127.0.0.1:5600/api/v2").rstrip("/")

    @property
    def partitions(self) -> list[str]:
        values = self.raw.get("partitions") or self.raw.get("partition") or DEFAULT_DRACO_PARTITIONS
        if isinstance(values, str):
            values = [part.strip() for part in values.split(",")]
        return [str(part).strip() for part in values if str(part).strip()]

    @property
    def max_parallel_jobs(self) -> int:
        return max(1, int(self.raw.get("max_parallel_jobs") or 2))

    @property
    def partition_strategy(self) -> str:
        return str(self.raw.get("partition_strategy") or "round_robin_parallel").strip().lower()

    @property
    def queue_timeout_seconds(self) -> int:
        if "partition_queue_timeout_seconds" in self.raw and self.raw.get("partition_queue_timeout_seconds") is not None:
            return int(self.raw["partition_queue_timeout_seconds"])
        if "queue_timeout_seconds" in self.raw and self.raw.get("queue_timeout_seconds") is not None:
            return int(self.raw["queue_timeout_seconds"])
        return 3600

    @property
    def required_artifacts(self) -> dict[str, Any]:
        value = self.raw.get("required_artifacts")
        if isinstance(value, dict):
            return {**DEFAULT_REQUIRED_ARTIFACTS, **value}
        return dict(DEFAULT_REQUIRED_ARTIFACTS)

    @property
    def path_mappings(self) -> list[tuple[str, Path]]:
        configured = self.raw.get("path_mappings")
        mappings: list[tuple[str, Path]] = []
        if isinstance(configured, dict):
            for container_prefix, host_prefix in configured.items():
                mappings.append((str(container_prefix).rstrip("/"), Path(str(host_prefix)).expanduser()))
        elif isinstance(configured, list):
            for item in configured:
                if not isinstance(item, dict):
                    continue
                container_prefix = item.get("container") or item.get("container_prefix")
                host_prefix = item.get("host") or item.get("host_prefix")
                if container_prefix and host_prefix:
                    mappings.append((str(container_prefix).rstrip("/"), Path(str(host_prefix)).expanduser()))
        mappings.extend(
            [
                ("/data/local_input", self.root / "data/local_input"),
                ("/data/local_output", self.root / "data/local_output"),
                ("/hdp-shared", self.root / "hdp-shared"),
            ]
        )
        return mappings


def load_config(path: str | Path) -> BatchConfig:
    config_path = Path(path).expanduser()
    text = config_path.read_text(encoding="utf-8")
    if config_path.suffix.lower() in {".yaml", ".yml"}:
        import yaml

        raw = yaml.safe_load(text) or {}
    else:
        raw = json.loads(text)
    if not isinstance(raw, dict):
        raise RuntimeError("Batch config must be a JSON/YAML object")
    return BatchConfig(raw=raw, config_path=config_path)


def load_env_file(path: Path) -> dict[str, str]:
    env = os.environ.copy()
    if not path.is_file():
        return env
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            env[key] = value
    return env


def emit_event(config: BatchConfig, event: dict[str, Any]) -> None:
    config.state_dir.mkdir(parents=True, exist_ok=True)
    payload = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **event}
    with config.event_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
    print(json.dumps(payload, sort_keys=True), flush=True)


def current_allocation_id() -> str:
    return os.environ.get("SLURM_JOB_ID") or os.environ.get("WEBHDP_ALLOCATION_ID") or "local"


def run(command: list[str], *, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check, env=env)


def int_config(config: BatchConfig, key: str, default: int) -> int:
    return int(config.raw[key]) if key in config.raw and config.raw.get(key) is not None else default


def read_table(path: Path, *, sheet_name: str | None = None, delimiter: str = ",") -> list[dict[str, str]]:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        import pandas as pd

        df = pd.read_excel(path, sheet_name=sheet_name or 0, dtype=str).fillna("")
        return [{str(key): str(value) for key, value in row.items()} for row in df.to_dict(orient="records")]
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [{str(key): str(value or "") for key, value in row.items()} for row in csv.DictReader(handle, delimiter=delimiter)]


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def discover_files(dataset_dir: Path, extensions: list[str]) -> dict[str, Path]:
    normalized = {ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in extensions}
    files: dict[str, Path] = {}
    duplicates: dict[str, list[str]] = {}
    for path in sorted(dataset_dir.rglob("*"), key=lambda item: str(item).lower()):
        if path.is_file() and path.suffix.lower() in normalized:
            key = path.name.lower()
            if key in files:
                duplicates.setdefault(key, [str(files[key])]).append(str(path))
                continue
            files[key] = path
    if duplicates:
        examples = {key: value[:5] for key, value in list(duplicates.items())[:10]}
        raise RuntimeError(f"Dataset filenames must be unique; duplicate basenames found: {examples}")
    return files


def prepare_chunks(config: BatchConfig) -> dict[str, Any]:
    dataset_dir = Path(config.raw["dataset_dir"]).expanduser()
    msf_path = Path(config.raw["msf_path"]).expanduser()
    chunk_size = int(config.raw.get("chunk_size") or 1000)
    extensions = list(config.raw.get("file_extensions") or [".ply"])
    filename_column = str(config.raw.get("filename_column") or "Filename")
    source_path_column = str(config.raw.get("source_path_column") or "Source_File_Path")
    delimiter = str((config.raw.get("parse_options") or {}).get("delimiter") or ",")
    sheet_name = (config.raw.get("parse_options") or {}).get("sheet_name")

    files_by_name = discover_files(dataset_dir, extensions)
    rows = read_table(msf_path, sheet_name=sheet_name, delimiter=delimiter)
    if not rows:
        raise RuntimeError(f"MSF has no rows: {msf_path}")

    fieldnames = list(rows[0].keys())
    if filename_column not in fieldnames:
        raise RuntimeError(f"filename_column '{filename_column}' is not present in {msf_path}")
    if source_path_column not in fieldnames:
        fieldnames.append(source_path_column)

    matched: list[dict[str, str]] = []
    missing: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        filename = Path(str(row.get(filename_column) or "").strip()).name
        if not filename:
            missing.append({"row": index, "reason": "missing filename"})
            continue
        file_path = files_by_name.get(filename.lower())
        if file_path is None:
            missing.append({"row": index, "filename": filename, "reason": "file not found"})
            continue
        if filename.lower() in seen:
            missing.append({"row": index, "filename": filename, "reason": "duplicate filename skipped"})
            continue
        seen.add(filename.lower())
        output_row = {key: str(row.get(key) or "") for key in fieldnames}
        output_row[filename_column] = file_path.name
        output_row[source_path_column] = str(file_path)
        matched.append(output_row)

    chunks_dir = config.output_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    expanded_csv = config.output_dir / "expanded_msf.csv"
    write_csv(expanded_csv, matched, fieldnames)

    chunks: list[dict[str, Any]] = []
    for ordinal, start in enumerate(range(0, len(matched), chunk_size), start=1):
        chunk_rows = matched[start : start + chunk_size]
        chunk_id = f"chunk_{ordinal:04d}"
        chunk_dir = chunks_dir / chunk_id
        files_dir = chunk_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        chunk_csv = chunk_dir / f"{chunk_id}_msf.csv"
        for row in chunk_rows:
            source = Path(row[source_path_column])
            link = files_dir / source.name
            if link.exists() or link.is_symlink():
                continue
            os.symlink(source, link)
        write_csv(chunk_csv, chunk_rows, fieldnames)
        payload = {
            "chunk_id": chunk_id,
            "ordinal": ordinal,
            "record_count": len(chunk_rows),
            "chunk_dir": str(chunk_dir),
            "files_dir": str(files_dir),
            "msf_csv": str(chunk_csv),
            "container_files_dir": f"{config.container_input_root}/chunks/{chunk_id}/files",
            "container_msf_csv": f"{config.container_input_root}/chunks/{chunk_id}/{chunk_id}_msf.csv",
            "first_index": start + 1,
            "last_index": start + len(chunk_rows),
        }
        (chunk_dir / "chunk.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        chunks.append(payload)

    report = {
        "dataset_dir": str(dataset_dir),
        "msf_path": str(msf_path),
        "output_dir": str(config.output_dir),
        "file_extensions": extensions,
        "source_msf_rows": len(rows),
        "disk_candidate_files": len(files_by_name),
        "matched_records": len(matched),
        "missing_records": len(missing),
        "missing_examples": missing[:50],
        "chunk_size": chunk_size,
        "chunk_count": len(chunks),
        "expanded_csv": str(expanded_csv),
        "chunks": chunks,
    }
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    emit_event(config, {"event": "prepared", "matched_records": len(matched), "chunk_count": len(chunks)})
    return report


def request_json(method: str, url: str, token: str | None = None, payload: dict[str, Any] | None = None, timeout: int = 120) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with HTTP {exc.code}: {body[:1000]}") from exc


def api_data(response: dict[str, Any]) -> Any:
    return response.get("data", response)


def login(config: BatchConfig) -> str:
    env = load_env_file(config.env_file)
    token = env.get("WEBHDP_TOKEN")
    if token:
        return token
    email = env.get("WEBHDP_EMAIL") or env.get("DEFAULT_ADMIN_EMAIL")
    password = env.get("WEBHDP_PASSWORD") or env.get("DEFAULT_ADMIN_PASSWORD")
    if not email or not password:
        raise RuntimeError("Set WEBHDP_TOKEN or WEBHDP_EMAIL/WEBHDP_PASSWORD in the protected env file")
    payload = api_data(request_json("POST", f"{config.base_url}/auth/login", payload={"email": email, "password": password}, timeout=60))
    token = payload.get("access_token") or payload.get("token")
    if not token:
        raise RuntimeError("Login did not return an access token")
    return str(token)


def wait_task(config: BatchConfig, token: str, task_id: str, *, interval: int = 10, timeout: int = 0) -> dict[str, Any]:
    deadline = time.time() + timeout if timeout > 0 else None
    while True:
        data = api_data(request_json("GET", f"{config.base_url}/sessions/tasks/{task_id}", token=token, timeout=120))
        state = str(data.get("state") or "").upper()
        emit_event(config, {"event": "task_poll", "task_id": task_id, "state": state, "status": data.get("status")})
        if state == "SUCCESS":
            return data
        if state in {"FAILURE", "REVOKED"}:
            raise RuntimeError(f"Task {task_id} failed: {data}")
        if deadline is not None and time.time() >= deadline:
            raise RuntimeError(f"Timed out waiting for task {task_id}")
        time.sleep(interval)


def wait_session_batch_operation(config: BatchConfig, token: str, session_id: int, task_id: str, *, interval: int = 15, timeout: int = 0) -> dict[str, Any]:
    deadline = time.time() + timeout if timeout > 0 else None
    while True:
        data = api_data(
            request_json(
                "GET",
                f"{config.base_url}/sessions/{session_id}/batch-operations/{task_id}",
                token=token,
                timeout=120,
            )
        )
        state = str(data.get("state") or "").upper()
        status = str(data.get("status") or "")
        emit_event(config, {"event": "publish_poll", "session_id": session_id, "task_id": task_id, "state": state, "status": status})
        if state in TERMINAL_TASK_STATES:
            if state != "SUCCESS":
                raise RuntimeError(f"Session batch operation {task_id} failed: {data}")
            return data
        if deadline is not None and time.time() >= deadline:
            raise RuntimeError(f"Timed out waiting for session batch operation {task_id}")
        time.sleep(interval)


def publish_operations_for_mode(config: BatchConfig) -> list[str]:
    explicit = config.raw.get("publish_operations")
    if isinstance(explicit, list):
        return [str(item).strip().lower() for item in explicit if str(item).strip()]
    mode = str(config.raw.get("publish_mode") or "none").strip().lower()
    if mode in {"none", "off", "disabled", ""}:
        return []
    if mode in {"draft", "drafts", "create_drafts"}:
        return ["create_drafts"]
    if mode in {"upload", "upload_files"}:
        return ["create_drafts", "upload_files"]
    if mode in {"publish", "published", "full"}:
        return ["create_drafts", "upload_files", "publish_records"]
    raise RuntimeError(f"Unsupported publish_mode: {mode}")


def run_publish_operations(config: BatchConfig, token: str, session_id: int, target_ids: list[int]) -> list[dict[str, Any]]:
    operations = publish_operations_for_mode(config)
    if not operations:
        return []
    if not target_ids:
        raise RuntimeError("Publication requested but no completed record IDs were available")
    results: list[dict[str, Any]] = []
    options = {"is_sandbox": bool(config.raw.get("is_sandbox", False))}
    options.update(config.raw.get("publish_options") or {})
    for operation in operations:
        summary_payload = api_data(
            request_json(
                "GET",
                f"{config.base_url}/sessions/{session_id}/operations/summary?is_sandbox={'true' if options.get('is_sandbox') else 'false'}",
                token=token,
                timeout=120,
            )
        )
        operation_payload = (summary_payload.get("actionable_operations") or {}).get(operation) or {}
        eligible_ids = {
            int(item)
            for item in operation_payload.get("target_ids") or []
            if str(item).isdigit()
        }
        operation_target_ids = [item for item in target_ids if item in eligible_ids]
        if not operation_target_ids:
            emit_event(
                config,
                {
                    "event": "publish_operation_skipped",
                    "session_id": session_id,
                    "operation": operation,
                    "reason": "no_eligible_records",
                },
            )
            results.append({"operation": operation, "status": "skipped", "reason": "no_eligible_records"})
            continue
        payload = {"operation_type": operation, "target_ids": operation_target_ids, "options": options}
        queued = api_data(
            request_json(
                "POST",
                f"{config.base_url}/sessions/{session_id}/batch-operations",
                token=token,
                payload=payload,
                timeout=120,
            )
        )
        task_id = str(queued.get("task_id") or "")
        if not task_id:
            raise RuntimeError(f"Publication operation {operation} did not return a task_id: {queued}")
        result = wait_session_batch_operation(
            config,
            token,
            session_id,
            task_id,
            interval=int_config(config, "publish_poll_seconds", 15),
            timeout=int_config(config, "publish_timeout_seconds", 0),
        )
        operation_result = result.get("result") if isinstance(result.get("result"), dict) else {}
        summary = operation_result.get("summary") if isinstance(operation_result, dict) else {}
        if int((summary or {}).get("failed") or 0) > 0:
            raise RuntimeError(f"Publication operation {operation} completed with failed records: {summary}")
        results.append({"operation": operation, "task_id": task_id, "result": operation_result or result})
    return results


def record_file_entries(record: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for key in ("source_file_path", "absolute_path", "file_path", "path"):
        if record.get(key):
            value = str(record[key])
            entries.append({"filename": os.path.basename(value), "path": value, "source": key})
    for item in record.get("files") or []:
        if not isinstance(item, dict):
            continue
        path_value = None
        for key in ("absolute_path", "path", "file_path", "mapped_file_path"):
            if item.get(key):
                path_value = str(item[key])
                break
        filename = str(item.get("filename") or item.get("name") or os.path.basename(path_value or "")).strip()
        if filename or path_value:
            entries.append({"filename": filename or os.path.basename(str(path_value)), "path": path_value, "source": "files"})
    return [entry for entry in entries if entry.get("filename")]


def record_file_names(record: dict[str, Any]) -> list[str]:
    return [str(entry["filename"]).lower() for entry in record_file_entries(record)]


def resolve_artifact_path(config: BatchConfig | None, raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    path = Path(str(raw_path))
    if path.exists():
        return path
    if config is None:
        return path
    raw = str(raw_path)
    for container_prefix, host_prefix in config.path_mappings:
        if raw == container_prefix or raw.startswith(container_prefix + "/"):
            mapped = host_prefix / raw[len(container_prefix) :].lstrip("/")
            return mapped
    return path


def file_is_nonempty(config: BatchConfig | None, raw_path: str | None) -> bool:
    resolved = resolve_artifact_path(config, raw_path)
    if resolved is None:
        return False
    try:
        return resolved.is_file() and resolved.stat().st_size > 0
    except OSError:
        return False


def validation_report_ok(config: BatchConfig | None, raw_path: str | None) -> bool:
    resolved = resolve_artifact_path(config, raw_path)
    if resolved is None:
        return False
    try:
        if not resolved.is_file() or resolved.stat().st_size <= 0:
            return False
        payload = json.loads(resolved.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, json.JSONDecodeError):
        return False
    if isinstance(payload, dict):
        for key in ("valid", "is_valid", "success"):
            if key in payload:
                return bool(payload[key])
        status = str(payload.get("status") or "").lower()
        if status:
            return status in {"ok", "valid", "passed", "success", "successful"}
        errors = payload.get("errors")
        if isinstance(errors, list):
            return len(errors) == 0
    return True


def artifact_audit(records_payload: dict[str, Any], required: dict[str, Any], config: BatchConfig | None = None) -> dict[str, Any]:
    data = api_data(records_payload)
    records = data.get("records") if isinstance(data, dict) else []
    if not isinstance(records, list):
        records = []
    results: list[dict[str, Any]] = []
    complete_count = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        entries = record_file_entries(record)
        names = [str(entry.get("filename") or "").lower() for entry in entries]

        def matching_entries(*suffixes: str, contains: tuple[str, ...] = ()) -> list[dict[str, Any]]:
            matches = []
            for entry, name in zip(entries, names):
                if suffixes and not name.endswith(suffixes):
                    continue
                if contains and not any(fragment in name for fragment in contains):
                    continue
                matches.append(entry)
            return matches

        def present(matches: list[dict[str, Any]]) -> bool:
            if not matches:
                return False
            if required.get("require_existing_files", True):
                return any(file_is_nonempty(config, item.get("path")) for item in matches)
            return True

        png_matches = matching_entries(".png")
        png_existing = [item for item in png_matches if file_is_nonempty(config, item.get("path"))]
        edm_validation_matches = matching_entries(".json", contains=("edm.validation",))
        checks = {
            "source_model": present(matching_entries(".glb", ".gltf", ".obj", ".fbx", ".ply", ".stl", ".dae", ".3ds", ".blend")),
            "usdz": present(matching_entries(".usdz")),
            "png_renders": (len(png_existing) if required.get("require_existing_files", True) else len(png_matches)) >= int(required.get("png_renders") or 0),
            "edm_xml": present(matching_entries(".xml", contains=("edm",))),
            "mets_mods_xml": present(matching_entries(".xml", contains=("mets", "mods"))),
            "iiif_json": present(matching_entries(".json", ".jsonld", contains=("iiif", "manifest"))),
            "edm_validation": bool(edm_validation_matches) and (
                any(validation_report_ok(config, item.get("path")) for item in edm_validation_matches)
                if required.get("require_existing_files", True)
                else True
            ),
        }
        missing = [key for key in DEFAULT_REQUIRED_ARTIFACTS if required.get(key) and not checks.get(key)]
        complete = not missing
        complete_count += 1 if complete else 0
        results.append(
            {
                "record_id": record.get("record_id") or record.get("id"),
                "status": record.get("record_status") or record.get("status"),
                "complete": complete,
                "missing": missing,
                "reason_code": None if complete else "missing_required_artifacts",
                "file_count": len(entries),
            }
        )
    return {
        "ok": complete_count == len(results),
        "summary": {"records": len(results), "complete": complete_count, "incomplete": len(results) - complete_count},
        "records": results,
    }


def state_file_for(config: BatchConfig, chunk_id: str) -> Path:
    return config.state_dir / f"{chunk_id}.json"


def load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def update_chunk_state(config: BatchConfig, chunk_id: str, **updates: Any) -> dict[str, Any]:
    path = state_file_for(config, chunk_id)
    state = load_state(path)
    state.update(updates)
    state.setdefault("chunk_id", chunk_id)
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_state(path, state)
    return state


def recovery_queue_path(config: BatchConfig, chunk_id: str) -> Path:
    return config.state_dir / f"{chunk_id}.recovery.json"


def write_recovery_queue(config: BatchConfig, chunk_id: str, *, status: str, reason_code: str, audit: dict[str, Any] | None = None, retryable: bool = False) -> None:
    records = []
    if audit:
        for item in audit.get("records") or []:
            if isinstance(item, dict) and not item.get("complete"):
                records.append(
                    {
                        "record_id": item.get("record_id"),
                        "status": item.get("status"),
                        "reason_code": item.get("reason_code") or reason_code,
                        "missing": item.get("missing") or [],
                    }
                )
    payload = {
        "chunk_id": chunk_id,
        "status": status,
        "reason_code": reason_code,
        "retryable": retryable,
        "record_count": len(records),
        "records": records,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path = recovery_queue_path(config, chunk_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def reset_stale_allocation_state(config: BatchConfig, chunk_id: str, state: dict[str, Any]) -> dict[str, Any]:
    allocation_id = current_allocation_id()
    previous_allocation = state.get("allocation_id")
    status = str(state.get("status") or "")
    if previous_allocation and previous_allocation != allocation_id and status in STALE_ALLOCATION_STATES:
        emit_event(
            config,
            {
                "event": "stale_chunk_state_reset",
                "chunk_id": chunk_id,
                "previous_status": status,
                "previous_allocation_id": previous_allocation,
                "allocation_id": allocation_id,
            },
        )
        state = {
            "chunk_id": chunk_id,
            "status": "not_started",
            "previous_session_id": state.get("session_id"),
            "previous_run_id": state.get("run_id"),
            "stale_reset_from": status,
            "allocation_id": allocation_id,
        }
        write_state(state_file_for(config, chunk_id), state)
    return state


def scan_is_complete(records_payload: dict[str, Any], expected_count: int) -> bool:
    data = api_data(records_payload)
    records = data.get("records") if isinstance(data, dict) else []
    return isinstance(records, list) and len(records) >= expected_count


def run_chunk(config: BatchConfig, chunk: dict[str, Any]) -> dict[str, Any]:
    chunk_id = chunk["chunk_id"]
    state_path = state_file_for(config, chunk_id)
    state = reset_stale_allocation_state(config, chunk_id, load_state(state_path))
    if state.get("status") == "completed":
        emit_event(config, {"event": "chunk_already_completed", "chunk_id": chunk_id})
        return state
    if state.get("status") == "quarantined" and not state.get("retryable", False):
        emit_event(config, {"event": "chunk_quarantined", "chunk_id": chunk_id, "reason_code": state.get("reason_code")})
        return state
    if state.get("status") == "needs_recovery":
        if state.get("retryable", False):
            emit_event(config, {"event": "retryable_recovery_reset", "chunk_id": chunk_id, "reason_code": state.get("reason_code")})
            state = {"chunk_id": chunk_id, "status": "not_started", "previous_session_id": state.get("session_id"), "previous_run_id": state.get("run_id")}
            write_state(state_path, state)
        else:
            emit_event(config, {"event": "chunk_needs_manual_recovery", "chunk_id": chunk_id, "reason_code": state.get("reason_code")})
            return state

    token = login(config)
    allocation_id = current_allocation_id()
    session_id = int(state.get("session_id") or 0)
    run_id = state.get("run_id")
    if session_id <= 0:
        prep_payload = {
            "msf_path": chunk["container_msf_csv"],
            "directory_path": chunk["container_files_dir"],
            "parse_options": config.raw.get("parse_options") or {"delimiter": ",", "use_first_row_as_header": True},
            "recursive": True,
            "duplicate_policy": config.raw.get("duplicate_policy", "merge_non_empty"),
            "default_zenodo_environment": config.raw.get("default_zenodo_environment", "production"),
            "credential_preference": config.raw.get("credential_preference", "user"),
        }
        prep = api_data(request_json("POST", f"{config.base_url}/msf/workflow/local/prepare", token=token, payload=prep_payload, timeout=600))
        session_id = int(prep["session_id"])
        update_chunk_state(config, chunk_id, session_id=session_id, status="prepared", allocation_id=allocation_id, attempts=int(state.get("attempts") or 0) + 1)
        emit_event(config, {"event": "chunk_prepared", "chunk_id": chunk_id, "session_id": session_id})

        metadata = dict(config.raw.get("metadata") or {})
        metadata.setdefault("msf_path", chunk["container_msf_csv"])
        if config.raw.get("lod_mapping"):
            metadata.setdefault("lod_mapping", config.raw["lod_mapping"])
        if metadata:
            request_json("PUT", f"{config.base_url}/metadata/user/{session_id}/draft", token=token, payload=metadata, timeout=120)

    if str(load_state(state_path).get("status") or "") in {"prepared", "not_started"}:
        scan = api_data(request_json("POST", f"{config.base_url}/msf/workflow/session/{session_id}/start-local-scan", token=token, payload={}, timeout=120))
        scan_task_id = scan.get("task_id")
        update_chunk_state(config, chunk_id, session_id=session_id, status="scanning", allocation_id=allocation_id, scan_task_id=scan_task_id)
        if scan.get("task_id"):
            wait_task(config, token, str(scan["task_id"]), timeout=int_config(config, "scan_timeout_seconds", 0))
        records_after_scan = request_json("GET", f"{config.base_url}/sessions/{session_id}/records", token=token, timeout=300)
        if not scan_is_complete(records_after_scan, int(chunk.get("record_count") or 0)):
            update_chunk_state(config, chunk_id, session_id=session_id, status="needs_recovery", reason_code="scan_incomplete", retryable=True, allocation_id=allocation_id)
            raise RuntimeError(f"Chunk {chunk_id} scan did not produce the expected records")
        update_chunk_state(config, chunk_id, session_id=session_id, status="scanned", allocation_id=allocation_id)

    if not run_id:
        records = api_data(request_json("GET", f"{config.base_url}/sessions/{session_id}/records", token=token, timeout=300))
        if not scan_is_complete({"data": records}, int(chunk.get("record_count") or 0)):
            update_chunk_state(config, chunk_id, session_id=session_id, status="needs_recovery", reason_code="scan_incomplete", retryable=True, allocation_id=allocation_id)
            raise RuntimeError(f"Chunk {chunk_id} has incomplete records before pipeline execution")
        local_paths = []
        for item in records.get("records") or records.get("files") or []:
            if not isinstance(item, dict):
                continue
            for key in ("source_file_path", "absolute_path", "file_path", "path"):
                if item.get(key):
                    local_paths.append(str(item[key]))
                    break
        if not local_paths:
            local_paths = [f"{chunk['container_files_dir']}/{path.name}" for path in sorted(Path(chunk["files_dir"]).iterdir()) if path.is_file() or path.is_symlink()]
        execute_payload = {
            "session_id": session_id,
            "local_file_paths": local_paths,
            "record_ids": [],
            "is_sandbox": bool(config.raw.get("is_sandbox", False)),
            "async_execution": True,
            "abort_on_critical_error": bool(config.raw.get("abort_on_critical_error", False)),
        }
        run_data = api_data(request_json("POST", f"{config.base_url_v2}/pipelines/{config.raw.get('pipeline', 'render')}/execute", token=token, payload=execute_payload, timeout=120))
        run_id = run_data["run_id"]
        update_chunk_state(config, chunk_id, session_id=session_id, run_id=run_id, status="executing", allocation_id=allocation_id)
        emit_event(config, {"event": "chunk_run_started", "chunk_id": chunk_id, "session_id": session_id, "run_id": run_id})

    while True:
        run_payload = api_data(request_json("GET", f"{config.base_url_v2}/runs/{run_id}", token=token, timeout=120))
        run = run_payload.get("run") if isinstance(run_payload, dict) else {}
        status = str((run or {}).get("status") or "unknown")
        emit_event(config, {"event": "run_poll", "chunk_id": chunk_id, "run_id": run_id, "status": status})
        update_chunk_state(config, chunk_id, session_id=session_id, run_id=run_id, status="executing", run_status=status, allocation_id=allocation_id)
        if status in TERMINAL_RUN_STATES:
            if status != "completed":
                write_recovery_queue(config, chunk_id, status="needs_recovery", reason_code=f"pipeline_{status}", retryable=False)
                update_chunk_state(config, chunk_id, session_id=session_id, run_id=run_id, status="needs_recovery", run_status=status, reason_code=f"pipeline_{status}", retryable=False, allocation_id=allocation_id)
                raise RuntimeError(f"Pipeline run {run_id} ended with status {status}")
            break
        time.sleep(int_config(config, "run_poll_seconds", 30))

    final_records = request_json("GET", f"{config.base_url}/sessions/{session_id}/records", token=token, timeout=300)
    update_chunk_state(config, chunk_id, session_id=session_id, run_id=run_id, status="auditing", allocation_id=allocation_id)
    audit = artifact_audit(final_records, config.required_artifacts, config)
    final_status = "completed" if audit["ok"] else "needs_recovery"
    if final_status != "completed":
        write_recovery_queue(config, chunk_id, status="quarantined", reason_code="artifact_audit_failed", audit=audit, retryable=False)
    publish_results: list[dict[str, Any]] = []
    if audit["ok"]:
        completed_record_ids = [
            int(item["record_id"])
            for item in audit.get("records") or []
            if item.get("complete") and str(item.get("record_id") or "").isdigit()
        ]
        update_chunk_state(config, chunk_id, session_id=session_id, run_id=run_id, status="publishing", allocation_id=allocation_id)
        try:
            publish_results = run_publish_operations(config, token, session_id, completed_record_ids)
        except Exception as exc:
            write_recovery_queue(config, chunk_id, status="needs_recovery", reason_code="publication_failed", audit=audit, retryable=True)
            update_chunk_state(
                config,
                chunk_id,
                session_id=session_id,
                run_id=run_id,
                status="needs_recovery",
                reason_code="publication_failed",
                retryable=True,
                artifact_audit=audit,
                allocation_id=allocation_id,
                error=str(exc),
            )
            raise
    state = update_chunk_state(
        config,
        chunk_id,
        session_id=session_id,
        run_id=run_id,
        status="completed" if audit["ok"] else "quarantined",
        reason_code=None if audit["ok"] else "artifact_audit_failed",
        retryable=False,
        artifact_audit=audit,
        publish_results=publish_results,
        allocation_id=allocation_id,
    )
    emit_event(config, {"event": "chunk_finished", "chunk_id": chunk_id, "status": final_status, "audit": audit["summary"]})
    if final_status != "completed":
        raise RuntimeError(f"Chunk {chunk_id} did not pass artifact audit")
    return state


def normalize_slurm_state(raw_state: str) -> str:
    state = str(raw_state or "UNKNOWN").strip().upper()
    if not state:
        return "UNKNOWN"
    state = state.split("|", 1)[0].strip()
    state = state.split()[0].strip()
    state = state.split("+", 1)[0].strip()
    state = state.split("(", 1)[0].strip()
    if state.startswith("CANCELLED"):
        return "CANCELLED"
    return state or "UNKNOWN"


def choose_slurm_state(states: list[str]) -> str:
    normalized = [normalize_slurm_state(state) for state in states if str(state or "").strip()]
    if not normalized:
        return "UNKNOWN"
    priority = [
        "OUT_OF_MEMORY",
        "NODE_FAIL",
        "TIMEOUT",
        "BOOT_FAIL",
        "PREEMPTED",
        "FAILED",
        "CANCELLED",
        "RUNNING",
        "CONFIGURING",
        "PENDING",
        "COMPLETING",
        "SUSPENDED",
        "COMPLETED",
    ]
    for candidate in priority:
        if candidate in normalized:
            return candidate
    return normalized[0]


def job_state(job_id: str) -> str:
    queued = run(["squeue", "-h", "-j", job_id, "-o", "%T"], check=False)
    if queued.stdout.strip():
        return choose_slurm_state(queued.stdout.splitlines())
    acct = run(["sacct", "-X", "-n", "-j", job_id, "-o", "State", "-P"], check=False)
    return choose_slurm_state(acct.stdout.splitlines())


def wait_for_job(config: BatchConfig, job_id: str, poll_seconds: int) -> str:
    queued_started_at = time.time()
    while True:
        state = job_state(job_id)
        emit_event(config, {"event": "slurm_poll", "job_id": job_id, "state": state})
        if state in {"PENDING", "CONFIGURING"} and config.queue_timeout_seconds > 0:
            if time.time() - queued_started_at >= config.queue_timeout_seconds:
                run(["scancel", job_id], check=False)
                emit_event(
                    config,
                    {
                        "event": "slurm_queue_timeout",
                        "job_id": job_id,
                        "state": state,
                        "timeout_seconds": config.queue_timeout_seconds,
                    },
                )
                return "QUEUE_TIMEOUT"
        elif state not in {"PENDING", "CONFIGURING"}:
            queued_started_at = time.time()
        if state not in ACTIVE_SLURM_STATES:
            return state
        time.sleep(poll_seconds)


def active_chunk_job_id(chunk_id: str) -> str | None:
    job_name = f"webhdp-batch-{chunk_id}"
    queued = run(["squeue", "-h", "-n", job_name, "-o", "%i|%T"], check=False)
    for line in queued.stdout.splitlines():
        parts = [part.strip() for part in line.split("|", 1)]
        if len(parts) == 2 and normalize_slurm_state(parts[1]) in ACTIVE_SLURM_STATES:
            return parts[0]
    return None


def build_sbatch_command(config: BatchConfig, chunk: dict[str, Any], partition: str) -> list[str]:
    slurm = config.raw.get("slurm") if isinstance(config.raw.get("slurm"), dict) else {}
    log_dir = config.logs_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    export_arg = ",".join(
        [
            "ALL",
            f"ROOT={config.root}",
            f"ENV_FILE={config.env_file}",
            f"WEBHDP_BATCH_CONFIG={config.config_path}",
            f"WEBHDP_BATCH_CHUNK_JSON={Path(chunk['chunk_dir']) / 'chunk.json'}",
        ]
    )
    return [
        "sbatch",
        "--parsable",
        "--partition",
        partition,
        "--time",
        str(config.raw.get("time_limit") or "02:00:00"),
        "--gres",
        str(slurm.get("gres") or "gpu:1"),
        "--cpus-per-task",
        str(slurm.get("cpus_per_task") or 8),
        "--mem",
        str(slurm.get("mem") or "32G"),
        "--job-name",
        f"webhdp-batch-{chunk['chunk_id']}",
        "--output",
        str(log_dir / f"slurm-batch-{chunk['chunk_id']}-%j.out"),
        "--error",
        str(log_dir / f"slurm-batch-{chunk['chunk_id']}-%j.err"),
        "--export",
        export_arg,
        str(config.root / "scripts/hpc_singularity/remote/webhdp.sbatch"),
    ]


def submit_chunk_job(config: BatchConfig, chunk: dict[str, Any], partition: str, attempt: int) -> str:
    command = build_sbatch_command(config, chunk, partition)
    submitted = run(command)
    job_id = submitted.stdout.strip().split(";", 1)[0]
    update_chunk_state(
        config,
        chunk["chunk_id"],
        status="queued",
        slurm_job_id=job_id,
        partition=partition,
        slurm_attempt=attempt,
        submitted_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    emit_event(config, {"event": "chunk_submitted", "chunk_id": chunk["chunk_id"], "job_id": job_id, "partition": partition, "attempt": attempt})
    return job_id


def submit_chunk_once(config: BatchConfig, chunk: dict[str, Any], partition: str) -> str:
    job_id = submit_chunk_job(config, chunk, partition, int(load_state(state_file_for(config, chunk["chunk_id"])).get("slurm_attempt") or 0) + 1)
    return wait_for_job(config, job_id, int_config(config, "poll_seconds", 120))


def chunk_completed(config: BatchConfig, chunk_id: str) -> bool:
    return load_state(state_file_for(config, chunk_id)).get("status") == "completed"


def chunk_nonretryable_recovery(config: BatchConfig, chunk_id: str) -> dict[str, Any] | None:
    state = load_state(state_file_for(config, chunk_id))
    if state.get("status") in RECOVERY_STATUSES and not state.get("retryable", False):
        return state
    return None


def submit_chunk(config: BatchConfig, chunk: dict[str, Any]) -> None:
    max_attempts = int(config.raw.get("max_attempts_per_chunk") or 0)
    attempt = 0
    last_state = "UNKNOWN"
    while not chunk_completed(config, chunk["chunk_id"]):
        recovery_state = chunk_nonretryable_recovery(config, chunk["chunk_id"])
        if recovery_state:
            raise RuntimeError(
                f"{chunk['chunk_id']} requires manual recovery: "
                f"{recovery_state.get('reason_code') or recovery_state.get('status')}"
            )
        active_job = active_chunk_job_id(chunk["chunk_id"])
        if active_job:
            last_state = wait_for_job(config, active_job, int_config(config, "poll_seconds", 120))
        else:
            if max_attempts > 0 and attempt >= max_attempts:
                raise RuntimeError(f"{chunk['chunk_id']} did not complete after {attempt} attempts; last state {last_state}")
            partition = config.partitions[attempt % len(config.partitions)]
            attempt += 1
            last_state = submit_chunk_once(config, chunk, partition)
        if chunk_completed(config, chunk["chunk_id"]):
            return
        normalized = str(last_state or "").split()[0]
        if normalized not in RETRYABLE_SLURM_STATES:
            raise RuntimeError(f"{chunk['chunk_id']} did not complete; Slurm final state {last_state}")
        emit_event(config, {"event": "chunk_retrying", "chunk_id": chunk["chunk_id"], "last_state": last_state})
        time.sleep(min(300, max(10, int_config(config, "poll_seconds", 120))))


def partition_for_attempt(config: BatchConfig, attempt: int, chunk_index: int = 0) -> str:
    partitions = config.partitions or DEFAULT_DRACO_PARTITIONS
    strategy = config.partition_strategy
    if strategy in {"sequential_retry", "sequential"}:
        return partitions[(attempt - 1) % len(partitions)]
    if strategy in {"round_robin_parallel", "round_robin", "parallel"}:
        return partitions[(chunk_index + attempt - 1) % len(partitions)]
    if strategy in {"first_available", "first"}:
        return partitions[(attempt - 1) % len(partitions)]
    raise RuntimeError(f"Unsupported partition_strategy: {strategy}")


def should_retry_slurm_state(state: str) -> bool:
    return normalize_slurm_state(state) in RETRYABLE_SLURM_STATES


def selected_chunk_active_job(config: BatchConfig, chunk_id: str) -> dict[str, Any] | None:
    job_id = active_chunk_job_id(chunk_id)
    if not job_id:
        return None
    state = load_state(state_file_for(config, chunk_id))
    return {
        "chunk_id": chunk_id,
        "job_id": job_id,
        "attempt": int(state.get("slurm_attempt") or 1),
        "partition": state.get("partition"),
        "submitted_monotonic": time.time(),
    }


def submit_chunks_parallel(config: BatchConfig, chunks: list[dict[str, Any]]) -> None:
    pending = [chunk for chunk in chunks if not chunk_completed(config, chunk["chunk_id"])]
    active: dict[str, dict[str, Any]] = {}
    attempts: dict[str, int] = {
        chunk["chunk_id"]: int(load_state(state_file_for(config, chunk["chunk_id"])).get("slurm_attempt") or 0)
        for chunk in pending
    }
    poll_seconds = int_config(config, "poll_seconds", 120)
    max_attempts = int(config.raw.get("max_attempts_per_chunk") or 0)

    while pending or active:
        for chunk in list(pending):
            if len(active) >= config.max_parallel_jobs:
                break
            chunk_id = chunk["chunk_id"]
            if chunk_completed(config, chunk_id):
                pending.remove(chunk)
                continue
            recovery_state = chunk_nonretryable_recovery(config, chunk_id)
            if recovery_state:
                raise RuntimeError(f"{chunk_id} requires manual recovery: {recovery_state.get('reason_code') or recovery_state.get('status')}")
            existing = selected_chunk_active_job(config, chunk_id)
            if existing:
                active[chunk_id] = {"chunk": chunk, **existing}
                pending.remove(chunk)
                continue
            next_attempt = attempts.get(chunk_id, 0) + 1
            if max_attempts > 0 and next_attempt > max_attempts:
                raise RuntimeError(f"{chunk_id} did not complete after {attempts.get(chunk_id, 0)} attempts")
            partition = partition_for_attempt(config, next_attempt, int(chunk.get("ordinal") or 1) - 1)
            job_id = submit_chunk_job(config, chunk, partition, next_attempt)
            attempts[chunk_id] = next_attempt
            active[chunk_id] = {
                "chunk": chunk,
                "chunk_id": chunk_id,
                "job_id": job_id,
                "partition": partition,
                "attempt": next_attempt,
                "submitted_monotonic": time.time(),
                "queued_since_monotonic": time.time(),
            }
            pending.remove(chunk)

        if not active:
            continue

        time.sleep(poll_seconds)
        for chunk_id, info in list(active.items()):
            state = job_state(str(info["job_id"]))
            emit_event(
                config,
                {
                    "event": "slurm_poll",
                    "chunk_id": chunk_id,
                    "job_id": info["job_id"],
                    "state": state,
                    "partition": info.get("partition"),
                    "attempt": info.get("attempt"),
                },
            )
            if state in {"PENDING", "CONFIGURING"} and config.queue_timeout_seconds > 0:
                queued_since = float(info.get("queued_since_monotonic") or time.time())
                if time.time() - queued_since >= config.queue_timeout_seconds:
                    run(["scancel", str(info["job_id"])], check=False)
                    state = "QUEUE_TIMEOUT"
                    emit_event(
                        config,
                        {
                            "event": "slurm_queue_timeout",
                            "chunk_id": chunk_id,
                            "job_id": info["job_id"],
                            "partition": info.get("partition"),
                            "timeout_seconds": config.queue_timeout_seconds,
                        },
                    )
            elif state not in {"PENDING", "CONFIGURING"}:
                info["queued_since_monotonic"] = time.time()

            if state in ACTIVE_SLURM_STATES:
                continue

            active.pop(chunk_id, None)
            chunk = info["chunk"]
            if chunk_completed(config, chunk_id):
                continue
            recovery_state = chunk_nonretryable_recovery(config, chunk_id)
            if recovery_state:
                raise RuntimeError(f"{chunk_id} requires manual recovery: {recovery_state.get('reason_code') or recovery_state.get('status')}")
            if should_retry_slurm_state(state):
                emit_event(config, {"event": "chunk_retrying", "chunk_id": chunk_id, "last_state": state})
                pending.append(chunk)
                continue
            raise RuntimeError(f"{chunk_id} did not complete; Slurm final state {state}")


def load_report(config: BatchConfig) -> dict[str, Any]:
    if not config.report_path.is_file():
        raise RuntimeError(f"Preparation report not found: {config.report_path}. Run prepare first.")
    return json.loads(config.report_path.read_text(encoding="utf-8"))


def selected_chunks(config: BatchConfig, *, start_chunk: int = 1, max_chunks: int = 0) -> list[dict[str, Any]]:
    chunks = load_report(config).get("chunks") or []
    selected = [chunk for chunk in chunks if int(chunk.get("ordinal") or 0) >= start_chunk]
    if max_chunks > 0:
        selected = selected[:max_chunks]
    return selected


def preflight(config: BatchConfig) -> dict[str, Any]:
    sif_dir = Path(config.raw.get("sif_dir") or config.root / "images/sif")
    required_sifs = list(config.raw.get("required_sifs") or ["backend.sif", "fast-renderer.sif", "any-to-usdz.sif", "redis.sif"])
    env_mode = None
    if config.env_file.exists():
        env_mode = stat.S_IMODE(config.env_file.stat().st_mode)
    min_free_gb = float(config.raw.get("min_free_disk_gb") or 25)
    disk_path = config.output_dir.parent
    while not disk_path.exists() and disk_path != disk_path.parent:
        disk_path = disk_path.parent
    disk_usage = shutil.disk_usage(disk_path)
    free_gb = disk_usage.free / (1024**3)
    env = load_env_file(config.env_file)
    zenodo_token_present = any(
        bool(env.get(key))
        for key in (
            "ZENODO_API_KEY",
            "ZENODO_ACCESS_TOKEN",
            "WEBHDP_ZENODO_API_KEY",
            "WEBHDP_ZENODO_ACCESS_TOKEN",
            "ZENODO_SANDBOX_API_KEY",
        )
    )
    proxy_env = {key: bool(env.get(key) or os.environ.get(key)) for key in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy")}
    checks: dict[str, Any] = {
        "root": {"ok": config.root.is_dir(), "path": str(config.root)},
        "env_file": {
            "ok": config.env_file.is_file() and env_mode is not None and env_mode & 0o077 == 0,
            "path": str(config.env_file),
            "mode": oct(env_mode) if env_mode is not None else None,
            "private": env_mode is not None and env_mode & 0o077 == 0,
        },
        "dataset_dir": {"ok": Path(config.raw.get("dataset_dir", "")).expanduser().is_dir(), "path": str(config.raw.get("dataset_dir", ""))},
        "msf_path": {"ok": Path(config.raw.get("msf_path", "")).expanduser().is_file(), "path": str(config.raw.get("msf_path", ""))},
        "sifs": {name: (sif_dir / name).is_file() for name in required_sifs},
        "commands": {name: shutil.which(name) is not None for name in ("sbatch", "squeue", "sacct", "singularity", "tmux", "ffmpeg", "ffprobe", "nvidia-smi")},
        "disk": {"ok": free_gb >= min_free_gb, "free_gb": round(free_gb, 2), "min_free_gb": min_free_gb, "path": str(disk_path)},
        "zenodo_auth": {"ok": zenodo_token_present or bool(env.get("WEBHDP_TOKEN") or env.get("WEBHDP_EMAIL")), "token_present": zenodo_token_present},
        "proxy": {"ok": bool(proxy_env.get("NO_PROXY") or proxy_env.get("no_proxy")) if (proxy_env.get("HTTP_PROXY") or proxy_env.get("HTTPS_PROXY") or proxy_env.get("http_proxy") or proxy_env.get("https_proxy")) else True, "configured": proxy_env},
    }
    edm_validator_url = str(config.raw.get("local_edm_validator_url") or env.get("LOCAL_EDM_VALIDATOR_URL") or "").rstrip("/")
    if edm_validator_url:
        try:
            with urllib.request.urlopen(f"{edm_validator_url}/actuator/health", timeout=10) as response:
                checks["local_edm_validator"] = {"ok": response.status < 400, "url": edm_validator_url, "status": response.status}
        except Exception as exc:
            checks["local_edm_validator"] = {"ok": False, "url": edm_validator_url, "error": str(exc)}
    for path_name, path in {
        "output_dir_parent": config.output_dir.parent,
        "state_dir_parent": config.state_dir.parent,
        "logs_dir": config.logs_dir,
    }.items():
        path.mkdir(parents=True, exist_ok=True)
        checks[path_name] = {"ok": os.access(path, os.W_OK), "path": str(path)}
    ok = all(value.get("ok", True) for value in checks.values() if isinstance(value, dict) and "ok" in value)
    ok = ok and all(checks["sifs"].values()) and all(checks["commands"].values())
    return {"ok": bool(ok), "checks": checks}


def summary(config: BatchConfig) -> dict[str, Any]:
    report = load_report(config) if config.report_path.exists() else {"chunks": []}
    states = []
    counts: dict[str, int] = {}
    for chunk in report.get("chunks") or []:
        state = load_state(state_file_for(config, chunk["chunk_id"]))
        status = str(state.get("status") or "not_started")
        counts[status] = counts.get(status, 0) + 1
        states.append(
            {
                "chunk_id": chunk["chunk_id"],
                "status": status,
                "session_id": state.get("session_id"),
                "run_id": state.get("run_id"),
                "reason_code": state.get("reason_code"),
                "retryable": state.get("retryable"),
                "recovery_queue": str(recovery_queue_path(config, chunk["chunk_id"])) if status in RECOVERY_STATUSES else None,
            }
        )
    return {
        "report": {key: report.get(key) for key in ("matched_records", "chunk_count", "missing_records")},
        "configuration": {
            "partitions": config.partitions,
            "max_parallel_jobs": config.max_parallel_jobs,
            "partition_strategy": config.partition_strategy,
            "queue_timeout_seconds": config.queue_timeout_seconds,
            "pipeline": config.raw.get("pipeline", "render"),
            "publish_mode": config.raw.get("publish_mode", "none"),
        },
        "counts": counts,
        "chunks": states,
    }


def event_tail(config: BatchConfig, limit: int = 50) -> list[dict[str, Any]]:
    if not config.event_log.is_file():
        return []
    lines = config.event_log.read_text(encoding="utf-8", errors="ignore").splitlines()[-limit:]
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def diagnose(config: BatchConfig) -> dict[str, Any]:
    payload = summary(config)
    issues: list[dict[str, Any]] = []
    for chunk in payload.get("chunks") or []:
        status = chunk.get("status")
        if status == "quarantined":
            issues.append(
                {
                    "severity": "error",
                    "chunk_id": chunk.get("chunk_id"),
                    "reason_code": chunk.get("reason_code"),
                    "action": f"Inspect {chunk.get('recovery_queue')} and fix or exclude failed records before rerunning.",
                }
            )
        elif status == "needs_recovery":
            action = "Rerun resume; this chunk is marked retryable." if chunk.get("retryable") else "Inspect recovery queue before rerunning."
            issues.append(
                {
                    "severity": "warning" if chunk.get("retryable") else "error",
                    "chunk_id": chunk.get("chunk_id"),
                    "reason_code": chunk.get("reason_code"),
                    "action": action,
                }
            )
        elif status in {"queued", "prepared", "scanning", "executing", "auditing", "publishing"}:
            issues.append(
                {
                    "severity": "info",
                    "chunk_id": chunk.get("chunk_id"),
                    "reason_code": status,
                    "action": "Leave the tmux orchestrator running or reattach to monitor progress.",
                }
            )
    recent_events = event_tail(config, 100)
    queue_timeouts = [event for event in recent_events if event.get("event") == "slurm_queue_timeout"]
    if queue_timeouts:
        issues.append(
            {
                "severity": "warning",
                "reason_code": "queue_timeout",
                "count": len(queue_timeouts),
                "action": "Queue timeout occurred; verify partition order and consider increasing partition_queue_timeout_seconds.",
            }
        )
    payload["issues"] = issues
    payload["recent_events"] = recent_events[-20:]
    return payload


def write_run_report(config: BatchConfig) -> dict[str, Any]:
    payload = diagnose(config)
    report_json = config.state_dir / "run_report.json"
    report_csv = config.state_dir / "run_report.csv"
    config.state_dir.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    fieldnames = ["chunk_id", "status", "session_id", "run_id", "reason_code", "retryable", "recovery_queue"]
    with report_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for chunk in payload.get("chunks") or []:
            writer.writerow({key: chunk.get(key) for key in fieldnames})
    return {"ok": True, "json": str(report_json), "csv": str(report_csv), "summary": payload.get("counts", {})}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["preflight", "prepare", "start", "resume", "monitor", "recover", "summary", "diagnose", "report", "run-chunk"])
    parser.add_argument("--config", required=True)
    parser.add_argument("--chunk-json")
    parser.add_argument("--start-chunk", type=int, default=1)
    parser.add_argument("--max-chunks", type=int, default=0)
    parser.add_argument("--fail", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.command == "preflight":
        payload = preflight(config)
        print(json.dumps(payload, indent=2, sort_keys=True))
        if args.fail and not payload["ok"]:
            raise SystemExit(1)
        return
    if args.command == "prepare":
        print(json.dumps(prepare_chunks(config), indent=2, ensure_ascii=False))
        return
    if args.command in {"start", "resume"}:
        chunks = selected_chunks(config, start_chunk=args.start_chunk, max_chunks=args.max_chunks)
        submit_chunks_parallel(config, chunks)
        emit_event(config, {"event": "orchestrator_completed", "chunks_considered": len(chunks), "max_parallel_jobs": config.max_parallel_jobs})
        return
    if args.command == "monitor":
        print(json.dumps(summary(config), indent=2, sort_keys=True))
        return
    if args.command == "recover":
        submit_chunks_parallel(config, selected_chunks(config, start_chunk=args.start_chunk, max_chunks=args.max_chunks))
        return
    if args.command == "summary":
        print(json.dumps(summary(config), indent=2, sort_keys=True))
        return
    if args.command == "diagnose":
        print(json.dumps(diagnose(config), indent=2, sort_keys=True))
        return
    if args.command == "report":
        print(json.dumps(write_run_report(config), indent=2, sort_keys=True))
        return
    if args.command == "run-chunk":
        if not args.chunk_json:
            raise RuntimeError("--chunk-json is required for run-chunk")
        chunk = json.loads(Path(args.chunk_json).read_text(encoding="utf-8"))
        print(json.dumps(run_chunk(config, chunk), indent=2, sort_keys=True))
        return


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr, flush=True)
        raise
