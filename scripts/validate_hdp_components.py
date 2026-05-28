#!/usr/bin/env python3
"""Validate local HDP Component manifests for developer workflows."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml
from pydantic import ValidationError as PydanticValidationError

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from exceptions import ValidationError  # noqa: E402
from services.native_pipeline_system import NativePipelineSystemService  # noqa: E402


DEFAULT_COMPONENT_ROOT = ROOT / "external_code"
COMPONENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
SEMVERISH_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


@dataclass
class ComponentCheck:
    path: Path
    component_key: str = ""
    version: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.errors:
            return "FAIL"
        if self.warnings:
            return "WARN"
        return "OK"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": _display_path(self.path),
            "component_key": self.component_key,
            "version": self.version,
            "status": self.status,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _manifest_paths(paths: Iterable[str]) -> list[Path]:
    selected: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = ROOT / path
        if path.is_file():
            selected.append(path)
            continue
        if path.is_dir():
            direct_manifest = path / "component.yaml"
            if direct_manifest.exists():
                selected.append(direct_manifest)
            else:
                selected.extend(sorted(path.glob("*/component.yaml")))
            continue
        selected.append(path)
    return sorted(dict.fromkeys(path.resolve() for path in selected))


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidationError("component.yaml was not found") from exc
    except yaml.YAMLError as exc:
        raise ValidationError(f"component.yaml could not be parsed: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValidationError("component.yaml must contain a YAML object")
    return loaded


def _validate_metadata(manifest: dict[str, Any], check: ComponentCheck) -> None:
    metadata = manifest.get("metadata") if isinstance(manifest.get("metadata"), dict) else {}
    name = str(metadata.get("name") or "").strip()
    version = str(metadata.get("version") or "").strip()
    check.component_key = name
    check.version = version

    if not name:
        check.errors.append("metadata.name is required")
    elif not COMPONENT_NAME_RE.match(name):
        check.errors.append("metadata.name must use lowercase snake_case and start with a letter")

    if not version:
        check.errors.append("metadata.version is required")
    elif not SEMVERISH_RE.match(version):
        check.warnings.append("metadata.version should be semantic-version-like, e.g. 1.0.0")

    if not str(metadata.get("description") or "").strip():
        check.warnings.append("metadata.description is empty")

    if name and check.path.parent.name != name:
        check.warnings.append(
            f"component directory '{check.path.parent.name}' differs from metadata.name '{name}'"
        )


def _validate_structure(manifest: dict[str, Any], source_dir: Path, check: ComponentCheck) -> None:
    structure = manifest.get("structure") or {}
    if not isinstance(structure, dict):
        check.errors.append("structure must be an object when declared")
        return

    for relative in _as_list(structure.get("required_files")):
        relative_path = str(relative or "").strip()
        if not relative_path:
            continue
        candidate = (source_dir / relative_path).resolve()
        try:
            candidate.relative_to(source_dir.resolve())
        except ValueError:
            check.errors.append(f"structure.required_files entry escapes the component directory: {relative_path}")
            continue
        if not candidate.is_file():
            check.errors.append(f"required file is missing: {relative_path}")


def _builtin_component_key_for_path(path: Path, service: NativePipelineSystemService) -> str | None:
    try:
        resolved = path.resolve()
        specs = service._builtin_file_component_specs()
    except Exception:
        return None
    for component_key, spec in specs.items():
        source_dir = spec.get("source_dir")
        if isinstance(source_dir, Path) and resolved == (source_dir / "component.yaml").resolve():
            return str(component_key)
    return None


def _validate_execution(
    manifest: dict[str, Any],
    source_dir: Path,
    check: ComponentCheck,
    *,
    builtin: bool = False,
) -> None:
    execution = manifest.get("execution") or {}
    profiles = execution.get("profiles") if isinstance(execution, dict) else None
    if execution and not profiles and not builtin:
        check.errors.append("execution.profiles is required when execution is declared")
        return
    if not profiles:
        return
    if not isinstance(profiles, list):
        check.errors.append("execution.profiles must be an array")
        return

    seen_ids: set[str] = set()
    for index, profile in enumerate(profiles):
        if not isinstance(profile, dict):
            check.errors.append(f"execution.profiles[{index}] must be an object")
            continue
        profile_id = str(profile.get("id") or "").strip()
        if profile_id in seen_ids:
            check.errors.append(f"duplicate execution profile id: {profile_id}")
        seen_ids.add(profile_id)

        adapter = str(profile.get("adapter") or "").strip()
        handler = str(profile.get("handler") or "").strip()
        runtime = str(profile.get("runtime") or "").strip()
        entrypoint = profile.get("entrypoint")
        if adapter in {"local_cli", "legacy_hdp_python"} and isinstance(entrypoint, list):
            working_directory = str(profile.get("working_directory") or ".").strip() or "."
            for entry in entrypoint:
                entry_text = str(entry or "").strip()
                if not entry_text.endswith(".py") or Path(entry_text).is_absolute():
                    continue
                candidate = (source_dir / working_directory / entry_text).resolve()
                try:
                    candidate.relative_to(source_dir.resolve())
                except ValueError:
                    check.errors.append(f"{profile_id or index}: entrypoint script escapes the component directory")
                    continue
                if not candidate.is_file():
                    check.errors.append(f"{profile_id or index}: entrypoint script is missing: {entry_text}")
        if adapter == "hpc_link" and handler == "generic_singularity_component":
            if runtime != "singularity":
                check.errors.append(f"{profile_id or index}: generic_singularity_component requires runtime=singularity")
            if not isinstance(entrypoint, list) or not entrypoint or not all(str(item).strip() for item in entrypoint):
                check.errors.append(f"{profile_id or index}: generic_singularity_component requires a non-empty entrypoint")
            resources = profile.get("resources") or {}
            if isinstance(resources, dict):
                for field_name in ("gpu_count", "cpus", "memory_mb"):
                    value = resources.get(field_name)
                    if value is not None and (not isinstance(value, int) or value < 0):
                        check.errors.append(f"{profile_id or index}: resources.{field_name} must be a non-negative integer")
        if adapter == "container_cli":
            if runtime != "docker":
                check.errors.append(f"{profile_id or index}: container_cli install profiles require runtime=docker")
            if not str(profile.get("image") or "").strip():
                check.errors.append(f"{profile_id or index}: container_cli profiles require image")
            if not isinstance(entrypoint, list) or not entrypoint or not all(str(item).strip() for item in entrypoint):
                check.errors.append(f"{profile_id or index}: container_cli profiles require a non-empty entrypoint")


def _validate_smoke_test_metadata(test: Any, check: ComponentCheck, prefix: str) -> None:
    if test is None:
        return
    if not isinstance(test, dict):
        check.errors.append(f"{prefix} must be an object when declared")
        return

    file_names: set[str] = set()
    for index, entry in enumerate(_as_list(test.get("files"))):
        if not isinstance(entry, dict):
            check.errors.append(f"{prefix}.files[{index}] must be an object")
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            check.errors.append(f"{prefix}.files[{index}].name is required")
            continue
        if "/" in name or "\\" in name or name in {".", ".."}:
            check.errors.append(f"{prefix}.files[{index}].name must be a simple file name")
        file_names.add(name)
        content_base64 = entry.get("content_base64")
        content = entry.get("content")
        if content_base64 is None and content is None:
            check.errors.append(f"{prefix}.files[{index}] requires content_base64 or content")
            continue
        if content_base64 is not None:
            try:
                base64.b64decode(str(content_base64), validate=True)
            except (binascii.Error, ValueError):
                check.errors.append(f"{prefix}.files[{index}].content_base64 is not valid base64")

    inputs = test.get("inputs") or {}
    if inputs and not isinstance(inputs, dict):
        check.errors.append(f"{prefix}.inputs must be an object")
    elif file_names:
        for input_name, input_value in inputs.items():
            if isinstance(input_value, str) and input_value and input_value not in file_names:
                check.warnings.append(
                    f"{prefix}.inputs.{input_name} references '{input_value}', which is not declared in {prefix}.files"
                )


def _validate_hpc_metadata(manifest: dict[str, Any], check: ComponentCheck) -> None:
    hpc = manifest.get("hpc")
    if hpc is None:
        return
    if not isinstance(hpc, dict):
        check.errors.append("hpc must be an object when declared")
        return

    install = hpc.get("install") or {}
    if install and not isinstance(install, dict):
        check.errors.append("hpc.install must be an object when declared")
    elif install.get("runtime") and str(install.get("runtime")).strip() != "singularity":
        check.errors.append("hpc.install.runtime must be singularity")

    test = hpc.get("test")
    if test is None and install.get("sif_required"):
        check.warnings.append("hpc.install.sif_required is true but no hpc.test smoke test is declared")
    _validate_smoke_test_metadata(test, check, "hpc.test")


def _validate_install_metadata(manifest: dict[str, Any], check: ComponentCheck) -> None:
    install = manifest.get("install")
    if install is None:
        return
    if not isinstance(install, dict):
        check.errors.append("install must be an object when declared")
        return
    strategies = install.get("strategies") or []
    if strategies and not isinstance(strategies, list):
        check.errors.append("install.strategies must be an array")
        strategies = []
    seen_ids: set[str] = set()
    profile_ids = {
        str(profile.get("id") or "").strip()
        for profile in ((manifest.get("execution") or {}).get("profiles") or [])
        if isinstance(profile, dict)
    }
    for index, strategy in enumerate(strategies):
        if not isinstance(strategy, dict):
            check.errors.append(f"install.strategies[{index}] must be an object")
            continue
        strategy_id = str(strategy.get("id") or "").strip()
        if strategy_id in seen_ids:
            check.errors.append(f"duplicate install strategy id: {strategy_id}")
        seen_ids.add(strategy_id)
        if strategy_id not in {"local_container", "hpc_sif"}:
            check.errors.append(f"install.strategies[{index}].id must be local_container or hpc_sif")
        profile_id = str(strategy.get("profile") or "").strip()
        if profile_id and profile_id not in profile_ids:
            check.errors.append(f"install.strategies[{index}].profile references unknown execution profile '{profile_id}'")
        if strategy_id == "local_container" and not str(strategy.get("image") or "").strip():
            check.errors.append(f"install.strategies[{index}].image is required for local_container")
    _validate_smoke_test_metadata(install.get("test"), check, "install.test")


def validate_manifest(path: Path, service: NativePipelineSystemService | None = None) -> ComponentCheck:
    check = ComponentCheck(path=path)
    service = service or NativePipelineSystemService()
    try:
        manifest = _load_manifest(path)
        builtin_component_key = _builtin_component_key_for_path(path, service)
        _validate_metadata(manifest, check)
        _validate_structure(manifest, path.parent, check)
        _validate_execution(manifest, path.parent, check, builtin=bool(builtin_component_key))
        _validate_install_metadata(manifest, check)
        _validate_hpc_metadata(manifest, check)
        if builtin_component_key:
            spec = service._builtin_file_component_specs()[builtin_component_key]
            normalized = service._load_builtin_component_manifest_from_file(builtin_component_key, **spec)
        else:
            normalized = service._normalize_manifest(manifest, source_dir=path.parent, source_type="local_catalog")
        metadata = normalized.get("metadata") or {}
        check.component_key = str(metadata.get("name") or check.component_key)
        check.version = str(metadata.get("version") or check.version)
    except ValidationError as exc:
        details = getattr(exc, "details", None)
        suffix = f" ({json.dumps(details, sort_keys=True)})" if details else ""
        check.errors.append(f"{exc}{suffix}")
    except PydanticValidationError as exc:
        check.errors.extend(f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors())
    except Exception as exc:  # Keep the dev script resilient and actionable.
        check.errors.append(f"unexpected validation error: {exc}")
    return check


def validate_components(paths: Iterable[Path]) -> list[ComponentCheck]:
    service = NativePipelineSystemService()
    checks = [validate_manifest(path, service) for path in paths]

    seen_versions: dict[tuple[str, str], Path] = {}
    for check in checks:
        if check.errors or not check.component_key or not check.version:
            continue
        key = (check.component_key, check.version)
        previous_path = seen_versions.get(key)
        if previous_path is not None:
            check.errors.append(
                f"duplicate component metadata.name/version also declared by {_display_path(previous_path)}"
            )
        else:
            seen_versions[key] = check.path
    return checks


def _print_human_report(checks: list[ComponentCheck]) -> None:
    print("HDP Component validation")
    print(f"Checked {len(checks)} component manifest(s)")
    print("")

    for check in checks:
        label = check.component_key or check.path.parent.name
        version = f" {check.version}" if check.version else ""
        print(f"[{check.status}] {label}{version} - {_display_path(check.path)}")
        for error in check.errors:
            print(f"      error: {error}")
        for warning in check.warnings:
            print(f"      warning: {warning}")

    failures = sum(1 for check in checks if check.errors)
    warnings = sum(1 for check in checks if check.warnings)
    print("")
    print(f"Summary: {failures} failure(s), {warnings} warning-bearing component(s)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate local HDP Component component.yaml manifests.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Component directories, component.yaml files, or catalog roots. Defaults to external_code/.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON report.",
    )
    parser.add_argument(
        "--strict-warnings",
        action="store_true",
        help="Return a non-zero exit code when warnings are present.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    selected_paths = _manifest_paths(args.paths or [str(DEFAULT_COMPONENT_ROOT)])
    if not selected_paths:
        print("No component.yaml manifests found.", file=sys.stderr)
        return 1

    checks = validate_components(selected_paths)
    if args.json:
        print(
            json.dumps(
                {
                    "summary": {
                        "checked": len(checks),
                        "failures": sum(1 for check in checks if check.errors),
                        "warnings": sum(1 for check in checks if check.warnings),
                    },
                    "components": [check.to_dict() for check in checks],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        _print_human_report(checks)

    has_errors = any(check.errors for check in checks)
    has_warnings = any(check.warnings for check in checks)
    if has_errors or (args.strict_warnings and has_warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
