#!/usr/bin/env python3
"""Run a contributor-oriented WebHDP environment health report."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FRONTEND_ROOT = ROOT / "frontend"
PYTHON_VERSION_FILE = ROOT / ".python-version"
NODE_VERSION_FILE = ROOT / ".nvmrc"


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str
    remedy: str = ""


def _run(command: list[str], *, cwd: Path = ROOT, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(command, 127, stdout=f"{command[0]} was not found on PATH\n")
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout if isinstance(exc.stdout, str) else ""
        return subprocess.CompletedProcess(command, 124, stdout=f"{output}\nCommand timed out after {timeout}s\n")


def _parse_semver(value: str) -> tuple[int, int, int] | None:
    match = re.search(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", value)
    if not match:
        return None
    return tuple(int(part or "0") for part in match.groups())


def _meets_min_version(actual: str, minimum: str) -> bool:
    actual_version = _parse_semver(actual)
    minimum_version = _parse_semver(minimum)
    if actual_version is None or minimum_version is None:
        return False
    return actual_version >= minimum_version


def _command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _status_line(result: CheckResult) -> str:
    base = f"[{result.status}] {result.name}: {result.detail}"
    if result.remedy:
        return f"{base}\n      -> {result.remedy}"
    return base


def _check_python() -> CheckResult:
    expected = PYTHON_VERSION_FILE.read_text(encoding="utf-8").strip() if PYTHON_VERSION_FILE.exists() else "3.11"
    actual = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    expected_major_minor = ".".join(expected.split(".")[:2])
    actual_major_minor = f"{sys.version_info.major}.{sys.version_info.minor}"
    if actual_major_minor == expected_major_minor:
        return CheckResult("Python", "OK", f"{actual} matches .python-version {expected}")
    return CheckResult("Python", "FAIL", f"{actual} does not match .python-version {expected}", "Use Python 3.11 or open the devcontainer.")


def _check_command_version(name: str, command: list[str], minimum: str | None = None) -> CheckResult:
    if not _command_exists(command[0]):
        return CheckResult(name, "FAIL", f"{command[0]} is not on PATH", "Run make setup or use the devcontainer.")
    result = _run(command, timeout=10)
    output = result.stdout.strip().splitlines()[0] if result.stdout.strip() else "installed"
    if result.returncode != 0:
        return CheckResult(name, "FAIL", output, f"Check that {command[0]} works on PATH.")
    if minimum and not _meets_min_version(output, minimum):
        return CheckResult(name, "FAIL", output, f"Install {name} {minimum} or newer.")
    return CheckResult(name, "OK", output)


def _node_minimum() -> str:
    package_json = json.loads((FRONTEND_ROOT / "package.json").read_text(encoding="utf-8"))
    engine = package_json.get("engines", {}).get("node", ">=22.12.0")
    match = re.search(r"(\d+(?:\.\d+){0,2})", engine)
    return match.group(1) if match else "22.12.0"


def _check_backend_deps() -> CheckResult:
    result = _run(["uv", "run", "python", "-c", "import flask, pytest, sqlalchemy; print('backend imports ok')"], timeout=45)
    if result.returncode == 0:
        return CheckResult("Backend dependencies", "OK", result.stdout.strip())
    return CheckResult("Backend dependencies", "FAIL", result.stdout.strip() or "backend imports failed", "Run uv sync --group dev.")


def _check_frontend_deps() -> CheckResult:
    node_modules = FRONTEND_ROOT / "node_modules"
    vite_package = node_modules / "vite" / "package.json"
    if not node_modules.exists() or not vite_package.exists():
        return CheckResult("Frontend dependencies", "FAIL", "frontend/node_modules is incomplete", "Run cd frontend && npm ci.")
    try:
        vite_version = json.loads(vite_package.read_text(encoding="utf-8")).get("version", "unknown")
    except json.JSONDecodeError:
        return CheckResult("Frontend dependencies", "FAIL", "could not read local Vite package metadata", "Run cd frontend && npm ci.")
    vite = _run(["npm", "exec", "vite", "--", "--version"], cwd=FRONTEND_ROOT, timeout=20)
    if vite.returncode != 0:
        return CheckResult(
            "Frontend dependencies",
            "FAIL",
            vite.stdout.strip() or "local frontend toolchain failed",
            "Run cd frontend && npm ci. If optional native packages are stale, remove frontend/node_modules first.",
        )
    return CheckResult("Frontend dependencies", "OK", f"node_modules present; Vite {vite_version}; {vite.stdout.strip()}")


def _check_env_file() -> CheckResult:
    if not (ROOT / ".env.example").exists():
        return CheckResult("Environment template", "FAIL", ".env.example is missing", "Restore .env.example.")
    if not (ROOT / ".env").exists():
        return CheckResult("Local environment file", "WARN", ".env is not present", "Run cp .env.example .env before Compose/full-stack work.")
    return CheckResult("Local environment file", "OK", ".env present")


def _check_docker() -> list[CheckResult]:
    if not _command_exists("docker"):
        return [CheckResult("Docker", "WARN", "docker is not on PATH", "Install Docker Desktop for Compose/devcontainer workflows.")]

    results = [_check_command_version("Docker CLI", ["docker", "--version"])]
    info = _run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=15)
    if info.returncode != 0:
        results.append(
            CheckResult(
                "Docker daemon",
                "WARN",
                (info.stdout.strip() or "daemon is not reachable"),
                "Start Docker Desktop before running make compose-check or devcontainer checks.",
            )
        )
        return results

    results.append(CheckResult("Docker daemon", "OK", f"server {info.stdout.strip()}"))
    compose = _run(["docker", "compose", "version"], timeout=15)
    if compose.returncode == 0:
        results.append(CheckResult("Docker Compose", "OK", compose.stdout.strip()))
    else:
        results.append(CheckResult("Docker Compose", "WARN", compose.stdout.strip() or "compose unavailable", "Install Docker Compose v2."))

    if (ROOT / ".env").exists():
        config = _run(["docker", "compose", "config", "--quiet"], timeout=30)
        if config.returncode == 0:
            results.append(CheckResult("Compose config", "OK", "docker-compose.yml validates"))
        else:
            results.append(CheckResult("Compose config", "FAIL", config.stdout.strip() or "compose config failed", "Run make compose-check for details."))
    else:
        results.append(CheckResult("Compose config", "WARN", "skipped because .env is missing", "Run cp .env.example .env."))
    return results


def _check_devcontainer_config() -> CheckResult:
    config_path = ROOT / ".devcontainer" / "devcontainer.json"
    dockerfile_path = ROOT / ".devcontainer" / "Dockerfile"
    if not config_path.exists() or not dockerfile_path.exists():
        return CheckResult("Devcontainer config", "FAIL", ".devcontainer files are missing", "Restore .devcontainer/devcontainer.json and Dockerfile.")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return CheckResult("Devcontainer config", "FAIL", f"invalid JSON: {exc}", "Fix .devcontainer/devcontainer.json.")
    features = config.get("features", {})
    if "ghcr.io/devcontainers/features/node:1" not in features:
        return CheckResult("Devcontainer config", "FAIL", "Node feature is missing", "Add the Node 22 devcontainer feature.")
    if config.get("containerEnv", {}).get("UV_PROJECT_ENVIRONMENT") != "/home/vscode/.venv/webhdp":
        return CheckResult(
            "Devcontainer config",
            "FAIL",
            "UV_PROJECT_ENVIRONMENT is not isolated from the mounted repository",
            "Set it to /home/vscode/.venv/webhdp.",
        )
    mounts = config.get("mounts", [])
    expected_mount = "target=/workspaces/webhdp_clean/frontend/node_modules"
    if not any(expected_mount in mount for mount in mounts):
        return CheckResult(
            "Devcontainer config",
            "FAIL",
            "frontend/node_modules is not isolated from the mounted repository",
            "Mount frontend/node_modules as a named volume in devcontainer.json.",
        )
    return CheckResult("Devcontainer config", "OK", "JSON, Dockerfile, Node feature, isolated uv env, and node_modules volume are present")


def _check_script(name: str, command: list[str], remedy: str, timeout: int = 60) -> CheckResult:
    result = _run(command, timeout=timeout)
    output = result.stdout.strip().splitlines()
    detail = output[-1] if output else "completed"
    if result.returncode == 0:
        return CheckResult(name, "OK", detail)
    return CheckResult(name, "FAIL", result.stdout.strip() or f"{name} failed", remedy)


def _check_golden_workflow() -> CheckResult:
    command = ["uv", "run", "python", "scripts/run_golden_workflow.py", "--json"]
    result = _run(command, timeout=90)
    if result.returncode != 0:
        return CheckResult("Golden workflow", "FAIL", result.stdout.strip() or "golden workflow failed", "Run make golden-workflow.")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return CheckResult("Golden workflow", "OK", "completed")
    return CheckResult(
        "Golden workflow",
        "OK",
        f"{payload.get('case_id')} produced {payload.get('record_count')} records and {payload.get('msf_matched_count')} MSF matches",
    )


def collect_checks() -> list[CheckResult]:
    results: list[CheckResult] = [
        _check_python(),
        _check_command_version("uv", ["uv", "--version"]),
        _check_command_version("Node.js", ["node", "--version"], minimum=_node_minimum()),
        _check_command_version("npm", ["npm", "--version"]),
        _check_command_version("Git", ["git", "--version"]),
        _check_command_version("Make", ["make", "--version"]),
        _check_backend_deps(),
        _check_frontend_deps(),
        _check_env_file(),
        _check_devcontainer_config(),
    ]
    results.extend(_check_docker())
    results.extend(
        [
            _check_script("Developer docs", ["uv", "run", "python", "scripts/check_developer_docs.py"], "Run make docs-check.", timeout=60),
            _check_script("API contract freshness", ["uv", "run", "python", "scripts/check_openapi_fresh.py"], "Run make api-contract.", timeout=60),
            _check_golden_workflow(),
            _check_script("Whitespace", ["git", "diff", "--check"], "Remove trailing whitespace or conflict markers.", timeout=30),
        ]
    )
    return results


def main() -> int:
    os.chdir(ROOT)
    print("WebHDP developer environment doctor")
    print(f"Repository: {ROOT}")
    print("")

    results = collect_checks()
    for result in results:
        print(_status_line(result))

    failures = [result for result in results if result.status == "FAIL"]
    warnings = [result for result in results if result.status == "WARN"]
    print("")
    print(f"Summary: {len(failures)} failure(s), {len(warnings)} warning(s), {len(results)} check(s)")
    if failures:
        print("Doctor found blocking onboarding issues.")
        return 1
    if warnings:
        print("Doctor passed with warnings. Review them before full-stack or Devcontainer work.")
        return 0
    print("Doctor passed. This workspace is ready for WebHDP development.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
