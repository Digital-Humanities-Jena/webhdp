"""Runtime adapters for the native WebHDP pipeline system."""

from __future__ import annotations

import json
import hashlib
import logging
import math
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

PATH_INPUT_TYPES = {"file_path", "file_list", "dir_path"}
PRIVATE_ENVIRONMENT_KEYS = {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ"}


def _file_inputs(request):
    manifest = request.metadata.get("component_manifest") or {}
    declared = {field["name"] for field in manifest.get("inputs", []) if field.get("type") in PATH_INPUT_TYPES}
    return {name: value for name, value in request.inputs.items() if name in declared}


def _private_input(path: Path, root: Path) -> bool:
    try:
        return path.is_absolute() and path.is_relative_to(root) and path.resolve(strict=True) == path and (path.is_file() or path.is_dir())
    except (OSError, RuntimeError, ValueError):
        return False


def component_execution_timeout(manifest: dict, requested: Any = None) -> float | None:
    """Use the tighter declared/requested deadline without inventing a default."""
    declared = (manifest.get("execution") or {}).get("timeout")
    limits = []
    for value in (declared, requested):
        if value is None:
            continue
        if type(value) not in {int, float} or not math.isfinite(value) or value <= 0:
            raise ValueError("Component execution timeout must be a positive finite number")
        limits.append(value)
    return min(limits) if limits else None


def contract_file_output_error(manifest: dict, response: dict, output_dir: Path) -> str | None:
    """Check file outputs promised by a WebHDP container contract before using them."""
    values = response.get("outputs")
    values = values if isinstance(values, dict) else {}
    root = output_dir.resolve()
    for field in manifest.get("outputs") or []:
        if field.get("type") != "file_path":
            continue
        name = field["name"]
        extensions = field.get("extensions") or []
        if not field.get("required") and (name not in values or not extensions):
            continue
        value = values.get(name)
        if not isinstance(value, str) or not value.startswith("/outputs/"):
            return f"File output '{name}' must name a file under /outputs."
        relative = Path(value.removeprefix("/outputs/"))
        path = root / relative
        try:
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or path.resolve(strict=True) != path
                or not path.is_file()
            ):
                return f"File output '{name}' is missing or outside the container output directory."
        except (OSError, RuntimeError, ValueError):
            return f"File output '{name}' is missing or outside the container output directory."
        if extensions and path.suffix.lower() not in extensions:
            return f"File output '{name}' must have one of these extensions: {', '.join(extensions)}."
    return None


@dataclass
class AdapterExecutionRequest:
    step_id: str
    profile: Dict[str, Any]
    workdir: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    parameters: Dict[str, Any] = field(default_factory=dict)
    environment: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseExecutionAdapter:
    adapter_name = "base"

    def execute(self, request: AdapterExecutionRequest) -> Dict[str, Any]:
        raise NotImplementedError


class SubprocessExecutionAdapter(BaseExecutionAdapter):
    def _run_command(
        self,
        command: List[str],
        *,
        workdir: str,
        environment: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
        inherit_environment: bool = True,
    ) -> Dict[str, Any]:
        started = time.time()
        env = os.environ.copy() if inherit_environment else {key: os.environ[key] for key in PRIVATE_ENVIRONMENT_KEYS if key in os.environ}
        if environment:
            env.update({str(key): str(value) for key, value in environment.items()})

        try:
            completed = subprocess.run(
                command,
                cwd=workdir,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except Exception as exc:
            return {
                "success": False,
                "status": "failed",
                "error": str(exc),
                "command": command,
                "duration": time.time() - started,
                "logs": {"stdout": "", "stderr": str(exc)},
            }

        return {
            "success": completed.returncode == 0,
            "status": "completed" if completed.returncode == 0 else "failed",
            "return_code": completed.returncode,
            "command": command,
            "duration": time.time() - started,
            "logs": {"stdout": completed.stdout, "stderr": completed.stderr},
        }

    def _collect_declared_outputs(
        self,
        request: AdapterExecutionRequest,
        *,
        execution_cwd: str,
    ) -> Dict[str, Any]:
        outputs: Dict[str, Any] = {}
        artifacts: List[Dict[str, Any]] = []
        declarations = request.profile.get("output_collection") or []
        if not isinstance(declarations, list):
            return {"outputs": outputs, "artifacts": artifacts}

        for declaration in declarations:
            if not isinstance(declaration, dict):
                continue
            output_name = str(
                declaration.get("name")
                or declaration.get("output_name")
                or declaration.get("path")
                or declaration.get("relative_path")
                or declaration.get("glob")
                or "output"
            ).strip()
            artifact_kind = str(
                declaration.get("artifact_kind")
                or declaration.get("kind")
                or "file"
            ).strip() or "file"

            matches: List[Path] = []
            raw_path = declaration.get("path") or declaration.get("relative_path")
            if raw_path:
                candidate = Path(str(raw_path))
                if not candidate.is_absolute():
                    candidate = Path(execution_cwd) / candidate
                if candidate.exists():
                    matches = [candidate]
            else:
                raw_glob = str(declaration.get("glob") or "").strip()
                if raw_glob:
                    matches = sorted(
                        candidate
                        for candidate in Path(execution_cwd).glob(raw_glob)
                        if candidate.exists()
                    )

            if not matches:
                continue

            serialized_matches = [str(match.resolve()) for match in matches]
            outputs[output_name] = serialized_matches[0] if len(serialized_matches) == 1 else serialized_matches

            for index, match in enumerate(matches, start=1):
                resolved_kind = artifact_kind
                if resolved_kind == "file" and match.is_dir():
                    resolved_kind = "directory"
                artifact_name = output_name if len(matches) == 1 else f"{output_name}_{index}"
                artifacts.append(
                    {
                        "artifact_kind": resolved_kind,
                        "name": artifact_name,
                        "path": str(match.resolve()),
                        "metadata": {
                            "output_name": output_name,
                            **(declaration.get("metadata") or {}),
                        },
                    }
                )

        return {"outputs": outputs, "artifacts": artifacts}

    def _execute_with_output_collection(
        self,
        request: AdapterExecutionRequest,
        command: List[str],
        *,
        workdir: str,
    ) -> Dict[str, Any]:
        result = self._run_command(
            command,
            workdir=workdir,
            environment=request.environment,
            timeout=request.metadata.get("timeout_seconds"),
            inherit_environment=not request.metadata.get("private_execution_root"),
        )
        if result.get("success"):
            collected = self._collect_declared_outputs(request, execution_cwd=workdir)
            if collected["outputs"]:
                result["outputs"] = {**(result.get("outputs") or {}), **collected["outputs"]}
            if collected["artifacts"]:
                result["artifacts"] = [*(result.get("artifacts") or []), *collected["artifacts"]]
        return result


class LegacyHdpPythonAdapter(SubprocessExecutionAdapter):
    adapter_name = "legacy_hdp_python"

    def execute(self, request: AdapterExecutionRequest) -> Dict[str, Any]:
        command = list(request.profile.get("entrypoint") or ["python", "main.py"])
        command.extend(self._build_cli_arguments(request))
        execution_cwd = os.path.join(request.workdir, request.profile.get("working_directory", "."))
        return self._execute_with_output_collection(request, command, workdir=execution_cwd)

    @staticmethod
    def _build_cli_arguments(request: AdapterExecutionRequest) -> List[str]:
        arguments: List[str] = []
        combined = {**request.inputs, **request.parameters}
        for key, value in combined.items():
            flag = f"--{str(key).replace('_', '-')}"
            if isinstance(value, bool):
                if value:
                    arguments.append(flag)
            elif isinstance(value, list):
                arguments.append(flag)
                arguments.append(json.dumps(value))
            elif value is not None:
                arguments.extend([flag, str(value)])
        return arguments


class LocalCliAdapter(SubprocessExecutionAdapter):
    adapter_name = "local_cli"

    def execute(self, request: AdapterExecutionRequest) -> Dict[str, Any]:
        command = list(request.profile.get("entrypoint") or [])
        command.extend(LegacyHdpPythonAdapter._build_cli_arguments(request))
        execution_cwd = os.path.join(request.workdir, request.profile.get("working_directory", "."))
        return self._execute_with_output_collection(request, command, workdir=execution_cwd)


class ContainerCliAdapter(SubprocessExecutionAdapter):
    adapter_name = "container_cli"

    def execute(self, request: AdapterExecutionRequest) -> Dict[str, Any]:
        runtime = str(request.profile.get("runtime") or "").strip().lower()
        image = request.profile.get("image")
        entrypoint = list(request.profile.get("entrypoint") or [])
        if runtime not in {"docker", "singularity"}:
            return {
                "success": False,
                "status": "failed",
                "error": f"Unsupported container runtime: {runtime}",
                "command": [],
            }
        if not image:
            return {
                "success": False,
                "status": "failed",
                "error": "Container image is required",
                "command": [],
            }
        if runtime == "singularity" and request.profile.get("sif_sha256"):
            try:
                with Path(image).open("rb") as stream:
                    checksum = hashlib.file_digest(stream, "sha256").hexdigest()
                if checksum.lower() != str(request.profile["sif_sha256"]).lower():
                    raise ValueError("SIF checksum changed since this pipeline was published")
            except (OSError, ValueError) as exc:
                return {"success": False, "status": "failed", "error": str(exc), "command": []}
        if runtime == "docker" and bool((request.profile.get("config") or {}).get("webhdp_contract")):
            return self._execute_webhdp_contract(request, image=str(image), entrypoint=entrypoint)

        bind_mounts = request.profile.get("config", {}).get("bind_mounts") or request.profile.get("bind_mounts") or []
        command: List[str]
        if runtime == "docker":
            command = ["docker", "run", "--rm"]
            for mount in bind_mounts:
                source = mount.get("source")
                target = mount.get("target")
                if source and target:
                    command.extend(["-v", f"{source}:{target}"])
            command.append(str(image))
            command.extend(entrypoint)
        else:
            command = ["singularity", "exec"]
            for mount in bind_mounts:
                source = mount.get("source")
                target = mount.get("target")
                if source and target:
                    command.extend(["--bind", f"{source}:{target}"])
            command.append(str(image))
            command.extend(entrypoint)

        command.extend(LegacyHdpPythonAdapter._build_cli_arguments(request))
        return self._execute_with_output_collection(request, command, workdir=request.workdir)

    @staticmethod
    def _stage_contract_inputs(request: AdapterExecutionRequest, input_dir: Path) -> Dict[str, Any]:
        staged: Dict[str, Any] = {}
        used_names: set[str] = set()
        staged_sources: Dict[Path, str] = {}
        private_root = request.metadata.get("private_execution_root")
        allowed_paths = _file_inputs(request) if private_root else request.inputs
        root = Path(private_root) if private_root else None

        def stage_value(key: str, value: Any) -> Any:
            if isinstance(value, list):
                return [stage_value(key, item) for item in value]
            if not isinstance(value, str) or not value.strip():
                return value
            source = Path(value)
            if root is not None and not _private_input(source, root):
                raise ValueError("A component input is outside its private workspace")
            if not source.exists():
                return value
            identity = source.resolve()
            if identity in staged_sources:
                return staged_sources[identity]
            safe_name = source.name or str(key)
            while safe_name.casefold() in used_names:
                safe_name = f"{key}_{safe_name}"
            used_names.add(safe_name.casefold())
            target = input_dir / safe_name
            if source.is_dir():
                if root is not None and any(not _private_input(child, root) for child in source.rglob("*")):
                    raise ValueError("A component directory contains a link or nonregular file")
                shutil.copytree(source, target, dirs_exist_ok=True)
            else:
                shutil.copy2(source, target)
            staged_sources[identity] = safe_name
            return safe_name

        for key, value in request.inputs.items():
            staged[key] = stage_value(key, value) if key in allowed_paths else value
        return staged

    @staticmethod
    def _translate_container_path(value: Any, output_dir: Path) -> Any:
        if isinstance(value, str) and value.startswith("/outputs/"):
            return str((output_dir / value.removeprefix("/outputs/")).resolve())
        if isinstance(value, list):
            return [ContainerCliAdapter._translate_container_path(item, output_dir) for item in value]
        if isinstance(value, dict):
            translated = {key: ContainerCliAdapter._translate_container_path(item, output_dir) for key, item in value.items()}
            for field in ("path", "remote_path"):
                if isinstance(translated.get(field), str) and translated[field].startswith("/outputs/"):
                    translated["path"] = str((output_dir / translated[field].removeprefix("/outputs/")).resolve())
            if not translated.get("path") and isinstance(translated.get("remote_path"), str):
                translated["path"] = translated["remote_path"]
            return translated
        return value

    def _execute_webhdp_contract(
        self,
        request: AdapterExecutionRequest,
        *,
        image: str,
        entrypoint: List[str],
    ) -> Dict[str, Any]:
        manifest = request.metadata.get("component_manifest") or request.metadata.get("manifest") or {}
        try:
            timeout = component_execution_timeout(manifest, request.metadata.get("timeout_seconds"))
            resources = request.profile.get("resources") or {}
            if not isinstance(resources, dict):
                raise ValueError("Container resources must be an object")
            resource_arguments = []
            for name, option in (("cpus", "--cpus"), ("memory_mb", "--memory")):
                if name not in resources:
                    continue
                value = resources[name]
                if type(value) not in {int, float} or not math.isfinite(value) or value <= 0:
                    raise ValueError(f"Container {name} must be a positive finite number")
                if name == "memory_mb":
                    value = int(value * 1024 * 1024)
                    if value <= 0:
                        raise ValueError("Container memory_mb must represent at least one byte")
                resource_arguments.extend([option, str(value)])
        except (ValueError, TypeError, OverflowError) as exc:
            return {"success": False, "status": "failed", "error": str(exc), "command": []}
        workdir = Path(request.workdir)
        input_dir = workdir / "inputs"
        output_dir = workdir / "outputs"
        response_dir = workdir / "response"
        request_dir = workdir / "request"
        for directory in (input_dir, output_dir, response_dir, request_dir):
            directory.mkdir(parents=True, exist_ok=True)
        try:
            staged_inputs = self._stage_contract_inputs(request, input_dir)
        except (OSError, ValueError) as exc:
            return {"success": False, "status": "failed", "error": str(exc), "command": []}
        request_path = request_dir / "request.json"
        response_path = response_dir / "response.json"
        response_path.unlink(missing_ok=True)
        component_key = (manifest.get("metadata") or {}).get("name") or request.step_id
        payload = {
            "component_key": component_key,
            "inputs": staged_inputs,
            "parameters": request.parameters,
            "profile": request.profile,
            "record_context": request.metadata.get("record_context") or {},
            "batch_records": request.metadata.get("batch_records") or [],
        }
        request_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        config = request.profile.get("config") or {}
        network = str(config.get("network") or "none").strip() or "none"
        container_name = f"webhdp-contract-{uuid4().hex}"
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            network,
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
            f"WEBHDP_COMPONENT_KEY={component_key}",
        ]
        for key, value in (request.profile.get("environment") or {}).items():
            command.extend(["-e", f"{key}={value}"])
        command.extend(resource_arguments)
        command.extend(["--name", container_name])
        command.append(image)
        command.extend(entrypoint)
        result = self._run_command(
            command,
            workdir=request.workdir,
            environment=request.environment,
            timeout=timeout,
            inherit_environment=not request.metadata.get("private_execution_root"),
        )
        # Killing a timed-out Docker client alone can leave its workload alive.
        # Its invocation-unique name is available even if Docker times out
        # between daemon-side creation and writing a client-side cidfile.
        if not result.get("success"):
            result["container_name"] = container_name
            try:
                cleanup = subprocess.run(["docker", "rm", "--force", container_name], capture_output=True,
                                         text=True, timeout=15, check=False)
                result["cleanup_status"] = "removed" if cleanup.returncode == 0 else "unconfirmed"
                if cleanup.returncode:
                    # A queued daemon-side create may complete after rm/inspect
                    # report NoSuch. Absence now is not confirmed cancellation.
                    result.setdefault("warnings", []).append(
                        f"Removal of container {container_name} is unconfirmed; Docker may still create it asynchronously. "
                        "Reconcile this container name before retrying. " + cleanup.stderr[-1000:])
            except (OSError, subprocess.SubprocessError) as exc:
                result["cleanup_status"] = "unconfirmed"
                result.setdefault("warnings", []).append(f"Container cleanup failed: {exc}")
        response_payload: Dict[str, Any] = {}
        if response_path.exists():
            try:
                loaded = json.loads(response_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    response_payload = loaded
            except (OSError, ValueError) as exc:
                response_payload = {"success": False, "error": f"Could not parse component response: {exc}"}
        elif result.get("logs", {}).get("stdout"):
            try:
                loaded = json.loads(str(result["logs"]["stdout"]).strip().splitlines()[-1])
                if isinstance(loaded, dict):
                    response_payload = loaded
            except ValueError:
                response_payload = {}
        if response_payload:
            if result.get("success") is True and response_payload.get("success") is True:
                contract_error = contract_file_output_error(manifest, response_payload, output_dir)
                if contract_error:
                    response_payload = {"success": False, "error": contract_error}
            translated = self._translate_container_path(response_payload, output_dir)
            if isinstance(translated, dict):
                result.update(
                    {
                        "success": result.get("success") is True and translated.get("success") is True,
                        "status": "completed" if result.get("success") is True and translated.get("success") is True else "failed",
                        "outputs": translated.get("outputs") or {},
                        "artifacts": translated.get("artifacts") or [],
                        "response": translated,
                        "error": translated.get("error"),
                    }
                )
        elif result.get("success"):
            result.update(
                {
                    "success": False,
                    "status": "failed",
                    "error": "Container did not produce a WebHDP component response",
                }
            )
        return result


class BuiltinWebHdpAdapter(BaseExecutionAdapter):
    adapter_name = "builtin_webhdp"

    def __init__(self, handler_registry: Dict[str, Any]):
        self.handler_registry = handler_registry

    def execute(self, request: AdapterExecutionRequest) -> Dict[str, Any]:
        handler_name = request.profile.get("handler")
        handler = self.handler_registry.get(handler_name)
        if handler is None:
            return {
                "success": False,
                "status": "failed",
                "error": f"Unknown builtin handler: {handler_name}",
                "command": [],
            }
        started = time.time()
        try:
            result = handler(request)
            result = result if isinstance(result, dict) else {"success": True, "result": result}
            result.setdefault("success", True)
            result.setdefault("status", "completed" if result.get("success") else "failed")
            result.setdefault("command", ["builtin_webhdp", handler_name])
            result.setdefault("duration", time.time() - started)
            return result
        except Exception as exc:
            logger.exception("Builtin handler %s failed", handler_name)
            return {
                "success": False,
                "status": "failed",
                "error": str(exc),
                "command": ["builtin_webhdp", handler_name],
                "duration": time.time() - started,
            }


class HpcLinkExecutionAdapter(BaseExecutionAdapter):
    adapter_name = "hpc_link"

    @staticmethod
    def _collect_existing_local_paths(value: Any, paths: List[str]) -> None:
        if isinstance(value, dict):
            for nested_value in value.values():
                HpcLinkExecutionAdapter._collect_existing_local_paths(nested_value, paths)
            return
        if isinstance(value, (list, tuple, set)):
            for nested_value in value:
                HpcLinkExecutionAdapter._collect_existing_local_paths(nested_value, paths)
            return
        if not isinstance(value, str):
            return

        candidate = value.strip()
        if not candidate or not os.path.isabs(candidate):
            return
        if os.path.isfile(candidate):
            paths.append(candidate)

    @classmethod
    def _local_paths_for_request(cls, request: AdapterExecutionRequest) -> List[str]:
        paths: List[str] = []
        private_root = request.metadata.get("private_execution_root")
        cls._collect_existing_local_paths(_file_inputs(request) if private_root else request.inputs, paths)
        execution_context = request.metadata.get("execution_context") or {}
        cls._collect_existing_local_paths(execution_context.get("bucket_source_files"), paths)

        record_context = request.metadata.get("record_context") or {}
        cls._collect_existing_local_paths(record_context.get("file_path"), paths)

        for batch_record in request.metadata.get("batch_records") or []:
            if isinstance(batch_record, dict):
                cls._collect_existing_local_paths(batch_record.get("file_path"), paths)

        hdpc_path = execution_context.get("hdpc_path")
        if hdpc_path and os.path.isfile(hdpc_path):
            from services.hdpc_local_service import read_hdpc_record_inputs
            records = [record_context] + list(request.metadata.get("batch_records") or [])
            for record in records:
                if not isinstance(record, dict) or not record.get("record_id"):
                    continue
                for item in read_hdpc_record_inputs(hdpc_path, int(record["record_id"])):
                    cls._collect_existing_local_paths(item.get("absolute_path"), paths)

        deduplicated: List[str] = []
        seen: set[str] = set()
        for path in paths:
            resolved = os.path.abspath(path)
            if private_root and not _private_input(Path(path), Path(private_root)):
                raise ValueError("An HPC input is outside its private workspace")
            if resolved in seen:
                continue
            seen.add(resolved)
            deduplicated.append(resolved)
        return deduplicated

    def execute(self, request: AdapterExecutionRequest) -> Dict[str, Any]:
        from flask import current_app
        from services.hdp_component_policy import component_gpu_count

        execution_context = request.metadata.get("execution_context") or {}
        session_id = (
            execution_context.get("db_session_id")
            or request.metadata.get("session_id")
            or (request.metadata.get("record_context") or {}).get("session_id")
        )
        if not session_id:
            return {
                "success": False,
                "status": "failed",
                "error": "HPC-Link execution requires a WebHDP session_id.",
                "command": ["hpc_link", request.step_id],
            }

        user_id = execution_context.get("initiated_by_user_id") or request.metadata.get("initiated_by_user_id")
        allocation = current_app.hpc_allocation_service.get_active_for_session(
            int(session_id), user_id=user_id, purpose=execution_context.get("hpc_purpose", "workflow"))
        if allocation is None:
            return {
                "success": False,
                "status": "failed",
                "error": "No active HPC-Link allocation is available for this session.",
                "command": ["hpc_link", request.step_id],
            }

        step = request.metadata.get("step") or {}
        component_key = (
            request.profile.get("component_key")
            or request.profile.get("handler")
            or step.get("component_ref")
            or request.step_id
        )
        gpu_count = component_gpu_count(component_key, request.profile.get("resources") or {})
        if type(gpu_count) is int and gpu_count > 0 and (allocation.requested_gpu_count or 0) < gpu_count:
            return {
                "success": False,
                "status": "failed",
                "error": f"This step needs an active HPC-Link allocation with at least {gpu_count} GPU(s).",
                "command": ["hpc_link", str(component_key)],
            }
        payload = {
            "component_key": component_key,
            "component_version": step.get("component_version") or request.profile.get("version"),
            "profile": request.profile,
            "step_id": request.step_id,
            "inputs": request.inputs,
            "parameters": request.parameters,
            "workdir": request.workdir,
            "timeout_seconds": request.metadata.get("timeout_seconds") or step.get("timeout_seconds"),
            "scope": "batch" if request.metadata.get("batch_records") else "record",
            "record_context": _compact_record_context(request.metadata.get("record_context")),
            "batch_records": request.metadata.get("batch_records") or [],
        }
        try:
            staged = current_app.hpc_allocation_service.stage_local_files(
                allocation,
                self._local_paths_for_request(request),
            )
            payload["staged_files"] = staged.get("staged_files") or []
            result = current_app.hpc_allocation_service.execute_component(allocation, payload)
        except Exception as exc:
            logger.exception("HPC-Link component execution failed")
            return {
                "success": False,
                "status": "failed",
                "error": str(exc),
                "command": ["hpc_link", str(component_key)],
            }

        if isinstance(result, dict):
            result.setdefault("success", True)
            result.setdefault("status", "completed" if result.get("success") else "failed")
            result.setdefault("command", ["hpc_link", str(component_key)])
            return result
        return {
            "success": False,
            "status": "failed",
            "error": "HPC-Link returned an invalid component execution payload.",
            "command": ["hpc_link", str(component_key)],
        }


def _compact_record_context(record_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(record_context, dict):
        return {}
    return {
        "record_id": record_context.get("record_id"),
        "file_path": record_context.get("file_path"),
        "filename": record_context.get("filename"),
        "specific_output_dir": record_context.get("specific_output_dir"),
        "index": record_context.get("index"),
        "total_records": record_context.get("total_records"),
    }


def build_default_adapter_registry(handler_registry: Dict[str, Any]) -> Dict[str, BaseExecutionAdapter]:
    return {
        "legacy_hdp_python": LegacyHdpPythonAdapter(),
        "local_cli": LocalCliAdapter(),
        "container_cli": ContainerCliAdapter(),
        "builtin_webhdp": BuiltinWebHdpAdapter(handler_registry),
        "hpc_link": HpcLinkExecutionAdapter(),
    }
