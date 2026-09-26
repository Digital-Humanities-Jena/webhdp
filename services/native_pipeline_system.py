"""Native WebHDP pipeline registry, validator, and execution engine."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import mimetypes
import os
import re
import time
from uuid import UUID
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml
from flask import current_app
from itsdangerous import URLSafeTimedSerializer, BadSignature
from services.registry_lock import serialize_registry, OperationConflict

from constants import (
    LEGACY_PIPELINE_ALIASES,
    METADATA_ONLY_PIPELINE_DEFINITION,
    METADATA_ONLY_PIPELINE_ID,
    OPTIONAL_3D_PIPELINE_DEFINITIONS,
    PIPELINE_DEFINITION,
    PREDEFINED_PIPELINE_ID,
)
from database.database import db
from database.models import (
    ComponentDefinition,
    ComponentProfile,
    ComponentVersion,
    ExecutionArtifact,
    PipelineBinding,
    PipelineDefinition,
    PipelineOutputAction,
    PipelinePublicationRequest,
    PipelineRun,
    PipelineRunStatus,
    PipelineStep,
    PipelineVersion,
    PipelineVersionStatus,
    PlaygroundRun,
    Session as DBSession,
    StepRun,
    SystemConfig,
    User,
    UserRole,
)
from exceptions import FileProcessingError, ResourceNotFoundError, ValidationError
from schemas.native_pipeline_schemas import (
    ComponentManifestSchema,
    PipelineConstructorPreflightRequestSchema,
    PipelineDefinitionSchema,
    PlaygroundExecutionRequestSchema,
)
from services.native_pipeline_adapters import AdapterExecutionRequest, build_default_adapter_registry
from services.hdpc_local_service import add_local_source_files
from services.hdpc_zenodo_service import create_api_draft as create_local_zenodo_draft
from services.hdpc_zenodo_service import upload_files_for_deposition as upload_local_zenodo_files
from services.hdp_component_policy import (
    component_runtime_status,
    hpc_required_component,
    hpc_required_message,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_PLAYGROUND_FIELD_TYPES = {
    "file_path",
    "dir_path",
    "file_list",
    "boolean",
    "integer",
    "number",
    "string_dropdown",
    "string",
    "text",
    "json",
    "array[string]",
    "array[number]",
    "array[integer]",
}
PLAYGROUND_FIELD_TYPE_ALIASES = {
    "file": "file_path",
    "directory": "dir_path",
    "dropdown": "string_dropdown",
}

LOD_POLICY_VALUES = {"required", "optional", "disabled"}
PLAYGROUND_WIDGET_BY_TYPE = {
    "file_path": "file_picker",
    "dir_path": "directory_picker",
    "file_list": "file_list_picker",
    "boolean": "checkbox",
    "integer": "number_input",
    "number": "number_input",
    "string_dropdown": "select",
    "string": "text_input",
    "text": "textarea",
    "json": "json_editor",
    "array[string]": "array_editor",
    "array[number]": "array_editor",
    "array[integer]": "array_editor",
}
CONSTRUCTOR_WIDGET_BY_TYPE = {
    **PLAYGROUND_WIDGET_BY_TYPE,
    "file_path": "file_picker",
    "dir_path": "directory_picker",
    "file_list": "file_list_picker",
    "json": "json_selector",
}
CONSTRUCTOR_SUPPORTED_SOURCE_KINDS_BY_TYPE = {
    "file_path": ["pipeline_source_file", "artifact_file"],
    "dir_path": ["pipeline_source_directory", "artifact_directory"],
    "file_list": ["pipeline_source_files", "artifact_file", "artifact_directory"],
    "json": ["artifact_json_value"],
    "boolean": ["literal", "artifact_json_value", "record_metadata_field"],
    "integer": ["literal", "artifact_json_value", "record_metadata_field"],
    "number": ["literal", "artifact_json_value", "record_metadata_field"],
    "string_dropdown": ["literal", "artifact_json_value", "record_metadata_field"],
    "string": ["literal", "artifact_json_value", "record_metadata_field"],
    "text": ["literal", "artifact_json_value", "record_metadata_field"],
    "array[string]": ["literal", "artifact_json_value", "record_metadata_field"],
    "array[number]": ["literal", "artifact_json_value", "record_metadata_field"],
    "array[integer]": ["literal", "artifact_json_value", "record_metadata_field"],
}
ALLOWED_PLAYGROUND_WIDGETS = {
    "text_input",
    "textarea",
    "number_input",
    "checkbox",
    "select",
    "json_editor",
    "file_picker",
    "directory_picker",
    "file_list_picker",
    "array_editor",
    "image_input",
    "model_input",
}
ALLOWED_CONSTRUCTOR_TRIGGER_OPERATORS = {"eq", "neq", "in", "not_in", "gte", "lte", "between", "exists", "truthy"}
CONSTRUCTOR_FILE_FACT_FIELDS = {
    "extension": {"label": "File Extension", "value_type": "string", "operators": ["eq", "neq", "in", "not_in", "exists", "truthy"]},
    "mime_type": {"label": "MIME Type", "value_type": "string", "operators": ["eq", "neq", "in", "not_in", "exists", "truthy"]},
    "size_bytes": {"label": "File Size (bytes)", "value_type": "number", "operators": ["eq", "neq", "gte", "lte", "between", "exists"]},
    "is_3d_model": {"label": "Is 3D Model", "value_type": "boolean", "operators": ["eq", "neq", "exists", "truthy"]},
}
SUPPORTED_ZENODO_OVERWRITE_POLICIES = {"overwrite", "skip_if_present", "append", "append_unique", "merge"}
MODEL_FILE_EXTENSIONS = {
    ".glb",
    ".gltf",
    ".obj",
    ".fbx",
    ".stl",
    ".dae",
    ".usdz",
    ".usd",
    ".usda",
    ".usdc",
    ".abc",
    ".ply",
    ".x3d",
    ".wrl",
}
DEFAULT_ARTIFACT_VIEWS = [
    {
        "id": "images",
        "label": "Image Outputs",
        "widget": "image_gallery",
        "extensions": [".png", ".jpg", ".jpeg", ".webp", ".gif"],
    },
    {
        "id": "models",
        "label": "3D Outputs",
        "widget": "model_viewer",
        "extensions": [".glb", ".gltf", ".usdz", ".obj", ".fbx", ".ply", ".stl", ".usd", ".usda", ".usdc", ".dae", ".abc"],
    },
    {
        "id": "structured-data",
        "label": "Structured Outputs",
        "widget": "file_download",
        "extensions": [".json", ".xml", ".txt", ".csv", ".md"],
    },
]

SUPPORTED_OUTPUT_ACTION_TYPES = {
    "zenodo_metadata_field",
    "edm_metadata_field",
    "record_metadata_field",
    "record_status_field",
    "record_warning",
}
SUPPORTED_OUTPUT_ACTION_TRANSFORMS = {
    "identity",
    "first",
    "ensure_list",
    "join",
    "json_stringify",
    "trim",
    "lowercase",
    "uppercase",
    "dedupe_list",
    "length",
    "coerce_string",
}

EDM_METADATA_TARGET_PATHS = [
    {"path": "edm_type_override", "label": "EDM type", "value_type": "string", "action_type": "edm_metadata_field"},
    {"path": "resource_type", "label": "EDM dc:type", "value_type": "string", "action_type": "edm_metadata_field"},
    {"path": "model_type", "label": "3D model type", "value_type": "string", "action_type": "edm_metadata_field"},
    {"path": "digital_source_type", "label": "3D digital source type", "value_type": "string", "action_type": "edm_metadata_field"},
    {"path": "intended_usage", "label": "3D intended usage", "value_type": "string", "action_type": "edm_metadata_field"},
    {"path": "vertex_count", "label": "3D vertex count", "value_type": "integer", "action_type": "edm_metadata_field"},
    {"path": "polygon_count", "label": "3D polygon count", "value_type": "integer", "action_type": "edm_metadata_field"},
    {"path": "point_count", "label": "3D point count", "value_type": "integer", "action_type": "edm_metadata_field"},
    {"path": "format", "label": "EDM dc:format", "value_type": "string", "action_type": "edm_metadata_field"},
    {"path": "language", "label": "EDM language", "value_type": "string", "action_type": "edm_metadata_field"},
    {"path": "country", "label": "EDM country", "value_type": "string", "action_type": "edm_metadata_field"},
]


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _json_loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return copy.deepcopy(default)
    if isinstance(value, (dict, list)):
        return copy.deepcopy(value)
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return copy.deepcopy(default)
    return parsed


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(_json_dumps(value).encode("utf-8")).hexdigest()


def _deepcopy(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _listify(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _collect_files_recursively(root_path: str) -> List[str]:
    if not isinstance(root_path, str) or not root_path.strip() or not os.path.isdir(root_path):
        return []
    collected: List[str] = []
    for current_root, _, filenames in os.walk(root_path):
        for filename in sorted(filenames):
            collected.append(os.path.join(current_root, filename))
    return collected


def _path_is_within(root_path: Path, candidate_path: Path) -> bool:
    try:
        candidate_path.resolve().relative_to(root_path.resolve())
        return True
    except ValueError:
        return False


def _increment_semver(version: str) -> str:
    parts = str(version or "1.0.0").split(".")
    numeric = []
    for part in parts[:3]:
        try:
            numeric.append(int(part))
        except ValueError:
            numeric.append(0)
    while len(numeric) < 3:
        numeric.append(0)
    numeric[2] += 1
    return ".".join(str(part) for part in numeric[:3])


class NativePipelineSystemService:
    """Registry, validation, execution, and compatibility services for native pipelines."""

    def __init__(self) -> None:
        self._seed_state = "idle"
        self._adapter_registry = build_default_adapter_registry(
            {
                "fast_renderer": self._builtin_fast_renderer_handler,
                "any_to_usdz": self._builtin_any_to_usdz_handler,
                "input_file_classification": self._builtin_input_file_classification_handler,
                "zenodo_draft": self._builtin_zenodo_draft_handler,
                "lod_generation": self._builtin_lod_generation_handler,
                "zenodo_upload": self._builtin_zenodo_upload_handler,
            }
        )

    @staticmethod
    def _repo_root() -> Path:
        return REPO_ROOT

    def _builtin_file_component_specs(self) -> Dict[str, Dict[str, Any]]:
        return {
            "fast_renderer": {
                "source_dir": self._repo_root() / "external_code" / "fast_renderer",
                "handler": "fast_renderer",
                "playground_enabled": True,
            },
            "any_to_usdz": {
                "source_dir": self._repo_root() / "external_code" / "any_to_usdz",
                "handler": "any_to_usdz",
                "playground_enabled": True,
            },
            "input_file_classification": {
                "source_dir": self._repo_root() / "external_code" / "input_file_classification",
                "handler": "input_file_classification",
                "playground_enabled": True,
            },
            "zenodo_draft": {
                "source_dir": self._repo_root() / "external_code" / "zenodo_draft",
                "handler": "zenodo_draft",
                "playground_enabled": False,
                "playground_reason": "This built-in component depends on pipeline record context and cannot run as a standalone Playground component.",
            },
            "lod_generation": {
                "source_dir": self._repo_root() / "external_code" / "lod_generation",
                "handler": "lod_generation",
                "playground_enabled": False,
                "playground_reason": "This built-in component depends on pipeline record context and cannot run as a standalone Playground component.",
            },
            "zenodo_upload": {
                "source_dir": self._repo_root() / "external_code" / "zenodo_upload",
                "handler": "zenodo_upload",
                "playground_enabled": False,
                "playground_reason": "This built-in component depends on pipeline record context and cannot run as a standalone Playground component.",
            },
        }

    def _load_yaml_manifest_file(self, manifest_path: Path) -> Dict[str, Any]:
        if not manifest_path.exists():
            raise ValidationError(
                "component.yaml not found",
                details={"component_path": str(manifest_path)},
            )
        with open(manifest_path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    def _load_builtin_component_manifest_from_file(
        self,
        component_key: str,
        *,
        source_dir: Path,
        handler: str,
        playground_enabled: bool = True,
        playground_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        manifest_path = source_dir / "component.yaml"
        raw_manifest = self._load_yaml_manifest_file(manifest_path)
        metadata = raw_manifest.setdefault("metadata", {})
        manifest_name = str(metadata.get("name") or "").strip()
        if manifest_name and manifest_name != component_key:
            raise ValidationError(
                "Builtin component manifest metadata.name does not match component key",
                details={
                    "component_key": component_key,
                    "manifest_name": manifest_name,
                    "manifest_path": str(manifest_path),
                },
            )
        metadata["name"] = component_key
        raw_manifest["execution"] = {
            "profiles": [
                {
                    "id": "builtin_default",
                    "adapter": "builtin_webhdp",
                    "handler": handler,
                }
            ]
        }
        compatibility = _deepcopy(raw_manifest.get("compatibility") or {})
        compatibility["builtin"] = True
        compatibility["manifest_source"] = str(manifest_path)
        compatibility["playground"] = {
            "enabled": bool(playground_enabled),
            "reason": playground_reason if not playground_enabled else None,
        }
        raw_manifest["compatibility"] = compatibility
        return self._normalize_manifest(raw_manifest, source_dir=source_dir, source_type="builtin")

    @staticmethod
    def resolve_pipeline_identifier(identifier: str) -> str:
        text = str(identifier or "").strip()
        return LEGACY_PIPELINE_ALIASES.get(text, text)

    def ensure_seeded(self) -> None:
        if self._seed_state == "complete":
            return
        if self._seed_state == "running":
            return
        self._seed_state = "running"
        try:
            self._ensure_builtin_components_seeded()
            self._ensure_builtin_pipelines_seeded()
            self._seed_state = "complete"
        except Exception:
            self._seed_state = "idle"
            raise

    def validate_component_manifest_path(self, component_path: str, *, source_type: str = "external") -> Dict[str, Any]:
        path = Path(component_path).expanduser().resolve()
        if path.is_dir():
            manifest_path = path / "component.yaml"
        else:
            manifest_path = path
            path = manifest_path.parent
        raw_manifest = self._load_yaml_manifest_file(manifest_path)
        normalized = self._normalize_manifest(raw_manifest, source_dir=path, source_type=source_type)
        return {
            "component_path": str(path),
            "manifest_path": str(manifest_path),
            "manifest": normalized,
            "playground_schema": self._build_playground_schema(normalized),
            "constructor_schema": self._build_constructor_schema(normalized),
        }

    def import_component_from_path(self, component_path: str, *, source_type: str = "external") -> Dict[str, Any]:
        validation = self.validate_component_manifest_path(component_path, source_type=source_type)
        return self.import_component_from_manifest(
            validation["manifest"],
            source_path=validation["component_path"],
            source_type=source_type,
            already_normalized=True,
        )

    @serialize_registry("native-registry")
    def import_component_from_manifest(
        self,
        manifest: Dict[str, Any],
        *,
        source_path: Optional[str] = None,
        source_type: str = "external",
        already_normalized: bool = False,
    ) -> Dict[str, Any]:
        manifest = _deepcopy(manifest or {})
        if not already_normalized:
            manifest = self._normalize_manifest(manifest, source_dir=None, source_type=source_type)
        metadata = manifest["metadata"]
        component_key = metadata["name"]
        component_version = metadata["version"]
        manifest_hash = _hash_payload(manifest)

        component_definition = ComponentDefinition.query.filter_by(key=component_key).first()
        if component_definition is None:
            component_definition = ComponentDefinition(
                key=component_key,
                name=metadata.get("label") or metadata["name"],
                description=metadata.get("description", ""),
                source_type=source_type,
                is_active=True,
            )
            db.session.add(component_definition)
            db.session.flush()

        existing_version = ComponentVersion.query.filter_by(
            component_definition_id=component_definition.id,
            version=component_version,
        ).first()
        if existing_version and existing_version.manifest_hash == manifest_hash:
            return self._serialize_component_version(component_definition, existing_version)

        if existing_version is not None:
            raise ValidationError(
                "Component version already exists with different manifest content",
                details={"component_key": component_key, "version": component_version},
            )

        version_row = ComponentVersion(
            component_definition_id=component_definition.id,
            version=component_version,
            manifest_json=_json_dumps(manifest),
            source_path=source_path,
            manifest_hash=manifest_hash,
            is_active=True,
        )
        db.session.add(version_row)
        db.session.flush()
        self._replace_component_profiles(version_row, manifest["execution"]["profiles"])
        db.session.commit()
        return self._serialize_component_version(component_definition, version_row)

    def list_components(self, *, playground_only: bool = False) -> List[Dict[str, Any]]:
        self.ensure_seeded()
        definitions = ComponentDefinition.query.filter_by(is_active=True).order_by(ComponentDefinition.key.asc()).all()
        serialized: List[Dict[str, Any]] = []
        for definition in definitions:
            latest = (
                ComponentVersion.query.filter_by(component_definition_id=definition.id, is_active=True)
                .order_by(ComponentVersion.created_at.desc())
                .first()
            )
            if latest is None:
                continue
            payload = self._serialize_component_version(definition, latest)
            if playground_only and not payload.get("playground", {}).get("enabled"):
                continue
            serialized.append(payload)
        return serialized

    def list_pipelines(self, *, include_hidden: bool = False, status: Optional[str] = None) -> List[Dict[str, Any]]:
        self.ensure_seeded()
        query = PipelineDefinition.query.filter_by(is_active=True)
        if not include_hidden:
            query = query.filter_by(is_public=True)
        if status:
            query = query.filter_by(status=status)
        if os.environ.get("WEBHDP_CORE_ONLY", "false").lower() == "true":
            query = query.filter(PipelineDefinition.identifier.in_(["render", METADATA_ONLY_PIPELINE_ID]))
        definitions = query.order_by(PipelineDefinition.identifier.asc()).all()
        return [self._serialize_pipeline_summary(definition) for definition in definitions]

    def get_pipeline(self, identifier: str) -> Dict[str, Any]:
        self.ensure_seeded()
        requested_identifier = str(identifier or "").strip()
        canonical_identifier = self.resolve_pipeline_identifier(requested_identifier)
        if os.environ.get("WEBHDP_CORE_ONLY", "false").lower() == "true" and canonical_identifier not in {"render", METADATA_ONLY_PIPELINE_ID}:
            raise ValidationError("This optional pipeline is disabled in the core workflow profile")
        definition = PipelineDefinition.query.filter_by(identifier=canonical_identifier, is_active=True).first()
        if definition is None:
            raise ResourceNotFoundError("Pipeline not found", details={"identifier": identifier})
        payload = self._serialize_pipeline_definition(definition)
        if requested_identifier and requested_identifier != canonical_identifier:
            payload["identifier"] = requested_identifier
            payload["canonical_identifier"] = canonical_identifier
        return payload

    def get_pipeline_run(self, run_public_id: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        run = PipelineRun.query.filter_by(public_id=run_public_id).first()
        if run is None:
            raise ResourceNotFoundError("Pipeline run not found", details={"run_id": run_public_id})
        if user_id is not None:
            session = db.session.get(DBSession, run.session_id) if run.session_id else None
            if session is None:
                raise ResourceNotFoundError("Run session is unavailable")
            self._assert_user_can_access_session(session, user_id)
        return self._serialize_pipeline_run(run)

    def get_playground_run(self, run_public_id: str) -> Dict[str, Any]:
        run = PlaygroundRun.query.filter_by(public_id=run_public_id).first()
        if run is None:
            raise ResourceNotFoundError("Playground run not found", details={"run_id": run_public_id})
        return self._serialize_playground_run(run)

    def get_pipeline_constructor_support(self) -> Dict[str, Any]:
        zenodo_target_paths = self._flatten_zenodo_target_paths()
        metadata_target_paths = self._flatten_metadata_target_paths()
        return {
            "trigger_operators": [
                {
                    "id": operator_id,
                    "label": operator_id.replace("_", " "),
                }
                for operator_id in ["eq", "neq", "in", "not_in", "gte", "lte", "between", "exists", "truthy"]
            ],
            "file_facts": [
                {
                    "field": field,
                    **_deepcopy(metadata),
                }
                for field, metadata in CONSTRUCTOR_FILE_FACT_FIELDS.items()
            ],
            "transforms": [{"id": transform, "label": transform.replace("_", " ")} for transform in sorted(SUPPORTED_OUTPUT_ACTION_TRANSFORMS)],
            "overwrite_policies": [
                {"id": policy, "label": policy.replace("_", " ")}
                for policy in ["overwrite", "skip_if_present", "append", "append_unique", "merge"]
            ],
            "zenodo_target_paths": zenodo_target_paths,
            "edm_metadata_target_paths": self._flatten_edm_metadata_target_paths(),
            "metadata_target_paths": metadata_target_paths,
        }

    def preflight_pipeline_constructor(self, payload: Dict[str, Any], user_id: Optional[int] = None) -> Dict[str, Any]:
        request_model = PipelineConstructorPreflightRequestSchema.model_validate(payload)
        pipeline_definition = request_model.pipeline_definition.model_dump(mode="python")
        validation = self.validate_pipeline_config(pipeline_definition)
        if not validation.get("valid"):
            raise ValidationError("Pipeline constructor preflight requires a valid pipeline definition", details={"errors": validation.get("errors", [])})

        session_row = db.session.get(DBSession, int(request_model.session_id))
        if session_row is None:
            raise ResourceNotFoundError("Session not found", details={"session_id": request_model.session_id})
        self._assert_user_can_access_session(session_row, user_id)

        resolved_paths = [
            str(self._resolve_constructor_preflight_file_path(session_row, candidate_path))
            for candidate_path in request_model.local_file_paths
        ]

        normalized = validation["normalized"]
        record_contexts = [
            self._build_record_context_for_preflight(index, path)
            for index, path in enumerate(resolved_paths, start=1)
        ]
        steps = [step for step in normalized.get("steps", []) if step.get("enabled", True)]
        summary_steps: List[Dict[str, Any]] = []

        for step in steps:
            step_component = self._get_component_manifest_by_key(step.get("component_ref") or step.get("id"), step.get("component_version"))
            step_resolution_rows = []
            if step.get("scope") == "batch":
                input_definitions = self._field_definition_map(step_component.get("inputs") or [])
                buckets: Dict[str, Dict[str, Any]] = {}
                for record_context in record_contexts:
                    trigger_resolution = self._resolve_step_trigger(step, record_context)
                    resolved_inputs, resolved_parameters = self._resolve_step_bindings(
                        step,
                        record_context,
                        {"record_info_list": [], "outputs_dir": str(Path(session_row.session_dir) / "outputs")},
                    )
                    base_parameters = {**(step.get("parameters") or {})}
                    effective_parameters = {
                        **base_parameters,
                        **resolved_parameters,
                        **_deepcopy(trigger_resolution.get("parameter_overrides") or {}),
                    }
                    resolved_inputs = self._apply_default_input_bindings(
                        step_component.get("inputs") or [],
                        resolved_inputs,
                        record_context,
                        {"scope": "batch"},
                    )
                    step_resolution_rows.append(
                        {
                            "record_path": record_context["file_path"],
                            "action": trigger_resolution["action"],
                            "matched_rule_id": trigger_resolution.get("matched_rule_id"),
                            "resolved_inputs": _deepcopy(resolved_inputs),
                            "effective_parameters": _deepcopy(effective_parameters),
                        }
                    )
                    if trigger_resolution["action"] != "run":
                        continue
                    signature_inputs, file_inputs, source_files = self._prepare_batch_input_state(input_definitions, resolved_inputs)
                    bucket_key = _hash_payload({"inputs": signature_inputs, "parameters": effective_parameters})
                    bucket = buckets.setdefault(
                        bucket_key,
                        {
                            "bucket_key": bucket_key,
                            "record_paths": [],
                            "parameters": effective_parameters,
                            "inputs": signature_inputs,
                            "file_inputs": file_inputs,
                            "source_files": source_files,
                        },
                    )
                    bucket["record_paths"].append(record_context["file_path"])
                    for field_name, state in file_inputs.items():
                        bucket_state = bucket["file_inputs"].setdefault(field_name, _deepcopy(state))
                        if state.get("type") == "file_list":
                            values = bucket_state.setdefault("values", [])
                            for file_path in state.get("values") or []:
                                if file_path not in values:
                                    values.append(file_path)
                                if file_path not in bucket["source_files"]:
                                    bucket["source_files"].append(file_path)
                        elif state.get("type") == "file_path":
                            value = state.get("value")
                            if value and not bucket_state.get("value"):
                                bucket_state["value"] = value
                            if value and value not in bucket["source_files"]:
                                bucket["source_files"].append(value)
                        elif state.get("type") == "dir_path":
                            value = state.get("value")
                            if value and not bucket_state.get("value"):
                                bucket_state["value"] = value
                summary_steps.append(
                    {
                        "step_id": step["id"],
                        "scope": "batch",
                        "records": step_resolution_rows,
                        "buckets": [
                            {
                                "bucket_key": bucket["bucket_key"],
                                "record_paths": bucket["record_paths"],
                                "parameters": bucket["parameters"],
                                "inputs": bucket["inputs"],
                                "file_inputs": _deepcopy(bucket["file_inputs"]),
                                "warnings": self._batch_dir_path_warnings(step, input_definitions, bucket),
                            }
                            for bucket in buckets.values()
                        ],
                    }
                )
                continue

            for record_context in record_contexts:
                trigger_resolution = self._resolve_step_trigger(step, record_context)
                resolved_inputs, resolved_parameters = self._resolve_step_bindings(
                    step,
                    record_context,
                    {"record_info_list": [], "outputs_dir": str(Path(session_row.session_dir) / "outputs")},
                )
                resolved_inputs = self._apply_default_input_bindings(
                    step_component.get("inputs") or [],
                    resolved_inputs,
                    record_context,
                    {"scope": step.get("scope", "record")},
                )
                step_resolution_rows.append(
                    {
                        "record_path": record_context["file_path"],
                        "action": trigger_resolution["action"],
                        "matched_rule_id": trigger_resolution.get("matched_rule_id"),
                        "resolved_inputs": _deepcopy(resolved_inputs),
                        "effective_parameters": {
                            **(step.get("parameters") or {}),
                            **resolved_parameters,
                            **_deepcopy(trigger_resolution.get("parameter_overrides") or {}),
                        },
                    }
                )
            summary_steps.append({"step_id": step["id"], "scope": step.get("scope", "record"), "records": step_resolution_rows})

            if (step.get("component_ref") or step.get("id")) == "input_file_classification":
                for record_context in record_contexts:
                    record_context["step_outputs"].setdefault(
                        step["id"],
                        {
                            "classification_json": self._classify_input_file(record_context["file_path"]),
                        },
                    )

        return {
            "valid": True,
            "pipeline": normalized,
            "preflight_token": self._preflight_signer().dumps({"config_hash": _hash_payload(normalized), "session_id": request_model.session_id, "paths": request_model.local_file_paths, "user_id": user_id}),
            "validation": validation,
            "steps": summary_steps,
        }

    def _resolve_constructor_preflight_file_path(self, session_row: DBSession, candidate_path: str) -> Path:
        candidate_text = str(candidate_path or "").strip()
        if not candidate_text:
            raise ValidationError("Constructor preflight file paths must not be empty")
        candidate = Path(candidate_text).expanduser()
        if not candidate.is_absolute():
            candidate = Path(session_row.session_dir).expanduser() / candidate
        return self._resolve_session_scoped_file_path(session_row, str(candidate))

    def _assert_user_can_access_session(self, session_row: DBSession, user_id: Optional[int]) -> None:
        if session_row is None:
            raise ResourceNotFoundError("Session not found")
        if user_id is None:
            raise ValidationError("Authenticated user is required to access Playground files")
        user = db.session.get(User, int(user_id))
        if user and user.role in {UserRole.ADMIN, UserRole.MODERATOR}:
            return
        if int(session_row.user_id) != int(user_id):
            raise ResourceNotFoundError("Requested Playground resource was not found")

    def _resolve_session_scoped_path(
        self,
        session_row: DBSession,
        candidate_path: str,
        *,
        expected_kind: str,
    ) -> Path:
        session_root = Path(session_row.session_dir).expanduser().resolve()
        candidate = Path(str(candidate_path or "")).expanduser()
        if not candidate.is_absolute():
            candidate = session_root / candidate
        resolved = candidate.resolve()
        if not _path_is_within(session_root, resolved):
            raise ValidationError(
                "Requested Playground file is outside the session scope",
                details={"path": str(resolved), "session_id": session_row.id},
            )
        if expected_kind == "file" and (not resolved.exists() or not resolved.is_file()):
            raise ResourceNotFoundError("Requested Playground file was not found", details={"path": str(resolved)})
        if expected_kind == "directory" and (not resolved.exists() or not resolved.is_dir()):
            raise ResourceNotFoundError("Requested Playground directory was not found", details={"path": str(resolved)})
        return resolved

    def _resolve_session_scoped_file_path(self, session_row: DBSession, candidate_path: str) -> Path:
        return self._resolve_session_scoped_path(session_row, candidate_path, expected_kind="file")

    def _resolve_session_scoped_directory_path(self, session_row: DBSession, candidate_path: str) -> Path:
        return self._resolve_session_scoped_path(session_row, candidate_path, expected_kind="directory")

    def _resolve_playground_session_input(
        self,
        request: AdapterExecutionRequest,
        candidate_path: str,
        *,
        expected_kind: str,
    ) -> str:
        session_id = request.metadata.get("session_id")
        if not session_id:
            return str(candidate_path)
        session_row = db.session.get(DBSession, int(session_id))
        if session_row is None:
            raise ResourceNotFoundError("Session not found", details={"session_id": session_id})
        if expected_kind == "directory":
            return str(self._resolve_session_scoped_directory_path(session_row, candidate_path))
        return str(self._resolve_session_scoped_file_path(session_row, candidate_path))

    def get_playground_session_file(self, session_id: int, candidate_path: str, user_id: Optional[int]) -> Dict[str, Any]:
        session_row = db.session.get(DBSession, int(session_id))
        if session_row is None:
            raise ResourceNotFoundError("Session not found", details={"session_id": session_id})
        self._assert_user_can_access_session(session_row, user_id)
        resolved = self._resolve_session_scoped_file_path(session_row, candidate_path)
        guessed_mimetype = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        return {
            "path": str(resolved),
            "download_name": resolved.name,
            "mimetype": guessed_mimetype,
        }

    def get_playground_run_artifact(self, run_public_id: str, artifact_index: int, user_id: Optional[int]) -> Dict[str, Any]:
        run = PlaygroundRun.query.filter_by(public_id=run_public_id).first()
        if run is None:
            raise ResourceNotFoundError("Playground run not found", details={"run_id": run_public_id})
        session_row = db.session.get(DBSession, run.session_id) if run.session_id else None
        if session_row is None:
            raise ResourceNotFoundError("Session not found", details={"run_id": run_public_id})
        self._assert_user_can_access_session(session_row, user_id)
        result_payload = _json_loads(run.result_json, {})
        artifacts = result_payload.get("artifacts") or []
        if artifact_index < 0 or artifact_index >= len(artifacts):
            raise ResourceNotFoundError(
                "Playground artifact not found",
                details={"run_id": run_public_id, "artifact_index": artifact_index},
            )
        artifact = artifacts[artifact_index]
        resolved = self._resolve_session_scoped_file_path(session_row, artifact.get("path"))
        guessed_mimetype = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        return {
            "path": str(resolved),
            "download_name": str(artifact.get("name") or resolved.name),
            "mimetype": guessed_mimetype,
        }

    def validate_pipeline_config(self, pipeline_definition: Dict[str, Any]) -> Dict[str, Any]:
        self.ensure_seeded()
        normalized = self._normalize_pipeline_config(pipeline_definition)
        PipelineDefinitionSchema.model_validate(normalized)
        errors = self._collect_pipeline_validation_errors(normalized)
        warnings = self._collect_pipeline_validation_warnings(normalized)
        return {"valid": len(errors) == 0, "normalized": normalized, "warnings": warnings, "errors": errors}

    @serialize_registry("native-registry")
    def create_pipeline_version_from_config(
        self,
        identifier: str,
        pipeline_definition: Dict[str, Any],
        *,
        activate: bool = True,
        created_by_user_id: Optional[int] = None,
        mirror_legacy_config: bool = False,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.ensure_seeded()
        request_fingerprint = _hash_payload({"identifier": identifier, "config": pipeline_definition, "activate": activate})
        if request_id:
            try:
                request_id = str(UUID(request_id))
            except (ValueError, TypeError, AttributeError):
                raise ValidationError("request_id must be a UUID")
            previous = db.session.get(PipelinePublicationRequest, request_id)
            if previous:
                if previous.user_id != created_by_user_id or previous.fingerprint != request_fingerprint:
                    raise OperationConflict("This publication request identifier was already used for different changes.")
                version = db.session.get(PipelineVersion, previous.pipeline_version_id)
                definition = db.session.get(PipelineDefinition, version.pipeline_definition_id)
                return {**self._serialize_pipeline_definition(definition), "publication_version": version.version, "reused": True}
        canonical_identifier = self.resolve_pipeline_identifier(identifier)
        normalized = self._normalize_pipeline_config(pipeline_definition, identifier=canonical_identifier)
        PipelineDefinitionSchema.model_validate(normalized)
        errors = self._collect_pipeline_validation_errors(normalized)
        if errors:
            raise ValidationError("Pipeline definition is invalid", details={"errors": errors})

        definition = PipelineDefinition.query.filter_by(identifier=canonical_identifier).first()
        if definition is None:
            definition = PipelineDefinition(
                identifier=canonical_identifier,
                name=normalized["name"],
                description=normalized.get("description", ""),
                status=normalized.get("status", "active"),
                modality=normalized.get("modality"),
                tags_json=_json_dumps(normalized.get("tags", [])),
                processing_mode=normalized.get("processingMode", "root"),
                is_public=True,
                is_active=True,
            )
            db.session.add(definition)
            db.session.flush()

        current_version = self._get_active_pipeline_version_row(definition)
        current_config = _json_loads(current_version.config_json, {}) if current_version else {}
        incoming_semantic_hash = self._pipeline_semantic_hash(normalized)
        current_semantic_hash = self._pipeline_semantic_hash(current_config) if current_config else None
        if current_version is not None and current_semantic_hash == incoming_semantic_hash:
            if current_config.get("version") != current_version.version:
                current_config["version"] = current_version.version
                current_version.config_json = _json_dumps(current_config)
                current_version.config_hash = _hash_payload(current_config)
            definition.name = normalized["name"]
            definition.description = normalized.get("description", "")
            definition.status = normalized.get("status", "active")
            definition.modality = normalized.get("modality")
            definition.tags_json = _json_dumps(normalized.get("tags", []))
            definition.processing_mode = normalized.get("processingMode", "root")
            if mirror_legacy_config:
                self._mirror_pipeline_config(canonical_identifier, current_config)
                if identifier != canonical_identifier:
                    self._mirror_pipeline_config(identifier, current_config)
            if request_id:
                db.session.add(PipelinePublicationRequest(request_id=request_id, fingerprint=request_fingerprint, pipeline_version_id=current_version.id, user_id=created_by_user_id))
            db.session.commit()
            return {**self._serialize_pipeline_definition(definition), "publication_version": current_version.version}

        requested_version = str(normalized.get("version") or "").strip()
        version_number = requested_version or _increment_semver(current_version.version if current_version else "1.0.0")
        existing_same_version = PipelineVersion.query.filter_by(
            pipeline_definition_id=definition.id,
            version=version_number,
        ).first()
        while existing_same_version is not None:
            version_number = _increment_semver(existing_same_version.version)
            existing_same_version = PipelineVersion.query.filter_by(
                pipeline_definition_id=definition.id,
                version=version_number,
            ).first()
        normalized["version"] = version_number
        config_hash = _hash_payload(normalized)

        definition.name = normalized["name"]
        definition.description = normalized.get("description", "")
        definition.status = normalized.get("status", "active")
        definition.modality = normalized.get("modality")
        definition.tags_json = _json_dumps(normalized.get("tags", []))
        definition.processing_mode = normalized.get("processingMode", "root")
        version_row = PipelineVersion(
            pipeline_definition_id=definition.id,
            version=version_number,
            status=PipelineVersionStatus.PUBLISHED if activate else PipelineVersionStatus.DRAFT,
            config_json=_json_dumps(normalized),
            config_hash=config_hash,
            is_active=bool(activate),
            created_by_user_id=created_by_user_id,
            activated_at=datetime.utcnow() if activate else None,
        )
        db.session.add(version_row)
        db.session.flush()
        self._replace_pipeline_structure(version_row, normalized)

        if activate:
            PipelineVersion.query.filter(
                PipelineVersion.pipeline_definition_id == definition.id,
                PipelineVersion.id != version_row.id,
            ).update({"is_active": False})
            definition.active_version_id = version_row.id

        if mirror_legacy_config:
            self._mirror_pipeline_config(canonical_identifier, normalized)
            if identifier != canonical_identifier:
                self._mirror_pipeline_config(identifier, normalized)

        if request_id:
            db.session.add(PipelinePublicationRequest(request_id=request_id, fingerprint=request_fingerprint, pipeline_version_id=version_row.id, user_id=created_by_user_id))
        db.session.commit()
        return {**self._serialize_pipeline_definition(definition), "publication_version": version_row.version}

    @staticmethod
    def _pipeline_semantic_hash(config: Dict[str, Any]) -> str:
        comparable = _deepcopy(config or {})
        comparable.pop("version", None)
        return _hash_payload(comparable)

    @serialize_registry("native-registry")
    def create_pending_run(
        self,
        identifier: str,
        *,
        session_id: Optional[int],
        initiated_by_user_id: Optional[int],
        request_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        self.ensure_seeded()
        request_id = request_payload.get("request_id")
        if request_id:
            existing = PipelineRun.query.filter_by(public_id=request_id).first()
            if existing:
                if existing.initiated_by_user_id != initiated_by_user_id or _json_loads(existing.request_json, {}).get("request_fingerprint") != _hash_payload(request_payload):
                    raise OperationConflict("This request identifier already belongs to another operation.")
                return {"run_id": existing.public_id, "status": existing.status.value, "reused": True, "pipeline_identifier": identifier, "pipeline_version": db.session.get(PipelineVersion, existing.pipeline_version_id).version}
        canonical_identifier = self.resolve_pipeline_identifier(identifier)
        definition = PipelineDefinition.query.filter_by(identifier=canonical_identifier, is_active=True).first()
        if definition is None:
            raise FileProcessingError(f"Pipeline '{identifier}' is not registered in the native pipeline system")
        version_row = self._get_active_pipeline_version_row(definition)
        if version_row is None:
            raise FileProcessingError(f"Pipeline '{identifier}' has no active version")

        if request_payload.get("expected_version") and version_row.version != request_payload["expected_version"]:
            raise OperationConflict("The active pipeline version changed. Reload it and repeat preflight.")
        self._verify_preflight(request_payload, _json_loads(version_row.config_json, {}), initiated_by_user_id)
        active_run = PipelineRun.query.filter(PipelineRun.session_id == session_id, PipelineRun.status.in_([PipelineRunStatus.PENDING, PipelineRunStatus.RUNNING])).first()
        if active_run:
            raise OperationConflict("This session already has an active run.", details={"run_id": active_run.public_id})
        pipeline_run = PipelineRun(
            **({"public_id": request_id} if request_id else {}),
            pipeline_definition_id=definition.id,
            pipeline_version_id=version_row.id,
            session_id=session_id,
            initiated_by_user_id=initiated_by_user_id,
            status=PipelineRunStatus.PENDING,
            request_json=_json_dumps({**request_payload, "request_fingerprint": _hash_payload(request_payload)}),
            started_at=datetime.utcnow(),
        )
        db.session.add(pipeline_run)
        db.session.commit()
        return {
            "run_id": pipeline_run.public_id,
            "pipeline_identifier": canonical_identifier,
            "pipeline_version": version_row.version,
            "status": pipeline_run.status.value,
        }

    def update_run_progress(self, run_public_id: str, progress_payload: Dict[str, Any]) -> None:
        run = PipelineRun.query.filter_by(public_id=run_public_id).first()
        if run is None or run.status not in {PipelineRunStatus.PENDING, PipelineRunStatus.RUNNING}:
            return
        run.result_json = _json_dumps({"status": "running", "progress": progress_payload})
        if run.status == PipelineRunStatus.PENDING:
            run.status = PipelineRunStatus.RUNNING
        db.session.commit()

    def execute_registered_submission(
        self,
        identifier: str,
        execution_context: Dict[str, Any],
        *,
        existing_run_public_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.ensure_seeded()
        canonical_identifier = self.resolve_pipeline_identifier(identifier)
        definition = PipelineDefinition.query.filter_by(identifier=canonical_identifier, is_active=True).first()
        if definition is None:
            raise FileProcessingError(f"Pipeline '{identifier}' is not registered in the native pipeline system")
        pipeline_run = PipelineRun.query.filter_by(public_id=existing_run_public_id).first() if existing_run_public_id else None
        if existing_run_public_id and (pipeline_run is None or pipeline_run.pipeline_definition_id != definition.id or pipeline_run.session_id != execution_context.get("db_session_id")):
            raise ValidationError("The queued run does not match this pipeline and session")
        if pipeline_run and pipeline_run.status in {PipelineRunStatus.COMPLETED, PipelineRunStatus.FAILED}:
            return {**_json_loads(pipeline_run.result_json, {}), "success": pipeline_run.status == PipelineRunStatus.COMPLETED, "run_id": pipeline_run.public_id, "error": pipeline_run.error_message}
        version_row = db.session.get(PipelineVersion, pipeline_run.pipeline_version_id) if pipeline_run else self._get_active_pipeline_version_row(definition)
        if version_row is None:
            raise FileProcessingError(f"Pipeline '{identifier}' has no selected version")
        config = _json_loads(version_row.config_json, {})
        if pipeline_run is None:
            pipeline_run = PipelineRun(
                pipeline_definition_id=definition.id,
                pipeline_version_id=version_row.id,
                session_id=execution_context.get("db_session_id"),
                initiated_by_user_id=execution_context.get("initiated_by_user_id"),
                status=PipelineRunStatus.RUNNING,
                request_json=_json_dumps(
                    {
                        "identifier": identifier,
                        "canonical_identifier": canonical_identifier,
                        "local_file_paths": execution_context.get("local_file_paths", []),
                        "record_ids": execution_context.get("record_ids", []),
                        "execution_items": execution_context.get("execution_items", []),
                        "is_sandbox": execution_context.get("is_sandbox", True),
                        "zenodo_environment": execution_context.get("zenodo_environment"),
                        "credential_source": execution_context.get("credential_source"),
                        "publishing_context": execution_context.get("publishing_context", {}),
                        "abort_on_critical_error": execution_context.get("abort_on_critical_error", False),
                    }
                ),
                started_at=datetime.utcnow(),
            )
            db.session.add(pipeline_run)
        else:
            pipeline_run.status = PipelineRunStatus.RUNNING
            pipeline_run.pipeline_definition_id = definition.id
            pipeline_run.pipeline_version_id = version_row.id
            pipeline_run.session_id = execution_context.get("db_session_id")
            pipeline_run.started_at = pipeline_run.started_at or datetime.utcnow()
        db.session.commit()

        try:
            result = self._run_native_pipeline(config, version_row, pipeline_run, execution_context)
            pipeline_run.status = PipelineRunStatus.COMPLETED if result.get("success", True) else PipelineRunStatus.FAILED
            pipeline_run.result_json = _json_dumps(result)
            pipeline_run.timings_json = _json_dumps(execution_context.get("pipeline_timings", {}))
            pipeline_run.completed_at = datetime.utcnow()
            if not result.get("success", True):
                pipeline_run.error_message = result.get("error")
            db.session.commit()
            result["run_id"] = pipeline_run.public_id
            result["pipeline_version"] = version_row.version
            result["pipeline_identifier"] = canonical_identifier
            return result
        except Exception as exc:
            pipeline_run.status = PipelineRunStatus.FAILED
            pipeline_run.error_message = str(exc)
            pipeline_run.completed_at = datetime.utcnow()
            db.session.commit()
            raise

    def execute_playground(self, payload: Dict[str, Any], user_id: Optional[int] = None) -> Dict[str, Any]:
        self.ensure_seeded()
        request_model = PlaygroundExecutionRequestSchema.model_validate(payload)
        component_definition = ComponentDefinition.query.filter_by(key=request_model.component_key, is_active=True).first()
        if component_definition is None:
            raise ResourceNotFoundError("Component not found", details={"component_key": request_model.component_key})
        component_version = (
            ComponentVersion.query.filter_by(component_definition_id=component_definition.id, is_active=True)
            .order_by(ComponentVersion.created_at.desc())
            .first()
        )
        if component_version is None:
            raise ResourceNotFoundError("Component version not found", details={"component_key": request_model.component_key})
        profile = self._get_profile_row(component_version, request_model.profile_id)
        manifest = _json_loads(component_version.manifest_json, {})
        manifest["compatibility"] = self._normalize_manifest_compatibility(
            manifest.get("compatibility"),
            source_type=component_definition.source_type,
        )
        playground_summary = manifest["compatibility"]["playground"]
        if not playground_summary.get("enabled"):
            raise ValidationError(
                "Component is not available in Playground",
                details={
                    "component_key": request_model.component_key,
                    "reason": playground_summary.get("reason"),
                },
            )
        normalized_inputs, normalized_parameters = self._normalize_playground_payload(manifest, request_model)
        session_row = db.session.get(DBSession, request_model.session_id)
        if session_row is None:
            raise ResourceNotFoundError("Session not found", details={"session_id": request_model.session_id})
        request_payload = request_model.model_dump()
        request_payload["inputs"] = normalized_inputs
        request_payload["parameters"] = normalized_parameters
        run = PlaygroundRun(
            component_version_id=component_version.id,
            component_profile_id=profile.id,
            session_id=request_model.session_id,
            initiated_by_user_id=user_id,
            status=PipelineRunStatus.RUNNING,
            request_json=_json_dumps(request_payload),
            started_at=datetime.utcnow(),
        )
        db.session.add(run)
        db.session.commit()

        workdir = os.path.join(session_row.session_dir, "playground", run.public_id)
        os.makedirs(workdir, exist_ok=True)
        adapter_name = profile.adapter
        if self._should_route_component_to_hpc_link(component_definition.key, request_model.session_id):
            adapter_name = "hpc_link"
        elif adapter_name == "hpc_link":
            self._ensure_component_runtime_available(
                component_definition.key,
                {"db_session_id": request_model.session_id},
                hpc_only=True,
            )
        elif component_definition.key in {"fast_renderer", "any_to_usdz"}:
            self._ensure_component_runtime_available(
                component_definition.key,
                {"db_session_id": request_model.session_id},
            )

        request = AdapterExecutionRequest(
            step_id=component_definition.key,
            profile={**self._profile_payload(profile, component_key=component_definition.key), "adapter": adapter_name},
            workdir=workdir,
            inputs=normalized_inputs,
            parameters=normalized_parameters,
            metadata={"manifest": manifest, "timeout_seconds": None, "session_id": request_model.session_id},
        )
        adapter = self._adapter_registry.get(adapter_name)
        if adapter is None:
            raise ValidationError("Unsupported adapter", details={"adapter": adapter_name})
        result = adapter.execute(request)

        run.status = PipelineRunStatus.COMPLETED if result.get("success", True) else PipelineRunStatus.FAILED
        run.result_json = _json_dumps(result)
        run.logs_json = _json_dumps(result.get("logs", {}))
        run.error_message = result.get("error")
        run.completed_at = datetime.utcnow()
        db.session.commit()

        payload = self._serialize_playground_run(run)
        payload["result"] = result
        return payload

    def _ensure_builtin_components_seeded(self) -> None:
        for component_key, manifest in self._builtin_component_manifests().items():
            definition = ComponentDefinition.query.filter_by(key=component_key).first()
            manifest_hash = _hash_payload(manifest)
            version_text = manifest["metadata"]["version"]
            if definition is None:
                definition = ComponentDefinition(
                    key=component_key,
                    name=manifest["metadata"].get("label") or manifest["metadata"]["name"],
                    description=manifest["metadata"].get("description", ""),
                    source_type="builtin",
                    is_active=True,
                )
                db.session.add(definition)
                db.session.flush()
            else:
                definition.name = manifest["metadata"].get("label") or manifest["metadata"]["name"]
                definition.description = manifest["metadata"].get("description", "")
                definition.source_type = "builtin"
                definition.is_active = True

            version_row = ComponentVersion.query.filter_by(
                component_definition_id=definition.id,
                version=version_text,
            ).first()
            if version_row is None:
                version_row = ComponentVersion(
                    component_definition_id=definition.id,
                    version=version_text,
                    manifest_json=_json_dumps(manifest),
                    source_path="builtin://webhdp",
                    manifest_hash=manifest_hash,
                    is_active=True,
                )
                db.session.add(version_row)
                db.session.flush()
                self._replace_component_profiles(version_row, manifest["execution"]["profiles"])
            elif version_row.manifest_hash != manifest_hash:
                version_row.manifest_json = _json_dumps(manifest)
                version_row.manifest_hash = manifest_hash
                self._replace_component_profiles(version_row, manifest["execution"]["profiles"])
        db.session.commit()

    def _ensure_builtin_pipelines_seeded(self) -> None:
        for identifier, definition in (
            (PREDEFINED_PIPELINE_ID, PIPELINE_DEFINITION),
            (METADATA_ONLY_PIPELINE_ID, METADATA_ONLY_PIPELINE_DEFINITION),
        ):
            effective_config = self._load_effective_seed_config(identifier, definition)
            self.create_pipeline_version_from_config(
                identifier,
                effective_config,
                activate=True,
                mirror_legacy_config=False,
            )
        for identifier, definition in OPTIONAL_3D_PIPELINE_DEFINITIONS.items():
            try:
                effective_config = self._load_effective_seed_config(identifier, definition)
                validation = self.validate_pipeline_config(effective_config)
            except Exception as exc:
                logger.info(
                    "Skipping optional 3D pipeline seed %s because it is not currently valid: %s",
                    identifier,
                    exc,
                )
                continue
            if validation.get("valid") is not True:
                logger.info(
                    "Skipping optional 3D pipeline seed %s because required components are not available: %s",
                    identifier,
                    validation.get("errors") or [],
                )
                continue
            self.create_pipeline_version_from_config(
                identifier,
                effective_config,
                activate=True,
                mirror_legacy_config=False,
            )

    def _load_effective_seed_config(self, identifier: str, default_definition: Dict[str, Any]) -> Dict[str, Any]:
        config = None
        for candidate in (identifier, self.resolve_pipeline_identifier(identifier)):
            config_key = f"pipeline_config:{candidate}"
            config_entry = db.session.get(SystemConfig, config_key)
            if config_entry and config_entry.value:
                loaded = _json_loads(config_entry.value, {})
                if isinstance(loaded, dict) and loaded:
                    config = loaded
                    break
        return self._normalize_pipeline_config(config or default_definition, identifier=identifier)

    def _mirror_pipeline_config(self, identifier: str, config: Dict[str, Any]) -> None:
        config_key = f"pipeline_config:{identifier}"
        entry = db.session.get(SystemConfig, config_key)
        if entry is None:
            entry = SystemConfig(key=config_key)
            db.session.add(entry)
        entry.value = _json_dumps(config)

    def _replace_component_profiles(self, version_row: ComponentVersion, profiles: Iterable[Dict[str, Any]]) -> None:
        ComponentProfile.query.filter_by(component_version_id=version_row.id).delete()
        for profile in profiles:
            row = ComponentProfile(
                component_version_id=version_row.id,
                profile_id=profile["id"],
                adapter=profile["adapter"],
                runtime=profile.get("runtime"),
                entrypoint_json=_json_dumps(profile.get("entrypoint", [])),
                config_json=_json_dumps(profile),
                is_active=True,
            )
            db.session.add(row)

    def _replace_pipeline_structure(self, version_row: PipelineVersion, config: Dict[str, Any]) -> None:
        PipelineOutputAction.query.filter(
            PipelineOutputAction.pipeline_step_id.in_(
                db.session.query(PipelineStep.id).filter_by(pipeline_version_id=version_row.id)
            )
        ).delete(synchronize_session=False)
        PipelineBinding.query.filter(
            PipelineBinding.pipeline_step_id.in_(
                db.session.query(PipelineStep.id).filter_by(pipeline_version_id=version_row.id)
            )
        ).delete(synchronize_session=False)
        PipelineStep.query.filter_by(pipeline_version_id=version_row.id).delete()
        db.session.flush()

        for order_index, step in enumerate(config.get("steps", []), start=1):
            component_version_id = self._step_component_version(step).id
            row = PipelineStep(
                pipeline_version_id=version_row.id,
                step_key=step["id"],
                name=step["name"],
                description=step.get("description", ""),
                order_index=order_index,
                scope=step.get("scope", "record"),
                enabled=bool(step.get("enabled", True)),
                component_key=step.get("component_ref") or step["id"],
                component_version_id=component_version_id,
                execution_profile_id=step.get("execution_profile_ref", "builtin_default"),
                config_json=_json_dumps(step),
            )
            db.session.add(row)
            db.session.flush()
            for binding in step.get("input_bindings", []):
                self._create_binding(row.id, "input", binding)
            for binding in step.get("parameter_bindings", []):
                self._create_binding(row.id, "parameter", binding)
            for action in step.get("output_actions", []):
                db.session.add(
                    PipelineOutputAction(
                        pipeline_step_id=row.id,
                        action_type=action["action_type"],
                        source_output_name=action.get("source_output"),
                        source_selector=action.get("selector"),
                        target_field=action.get("target_field"),
                        transform=action.get("transform"),
                        overwrite_policy=action.get("overwrite_policy"),
                        config_json=_json_dumps(action.get("config", {})),
                    )
                )

    def _create_binding(self, step_id: int, kind: str, binding: Dict[str, Any]) -> None:
        db.session.add(
            PipelineBinding(
                pipeline_step_id=step_id,
                binding_kind=kind,
                target_name=binding["target"],
                binding_type=binding["type"],
                source_step_key=binding.get("source_step"),
                source_output_name=binding.get("source_output"),
                source_selector=binding.get("selector"),
                metadata_field=binding.get("metadata_field"),
                literal_value=_json_dumps(binding.get("value")) if "value" in binding else None,
                secret_ref=binding.get("secret_ref"),
                config_json=_json_dumps(binding.get("config", {})),
            )
        )

    def _resolve_component_version_id(self, component_key: Optional[str]) -> Optional[int]:
        if not component_key:
            return None
        definition = ComponentDefinition.query.filter_by(key=component_key).first()
        if definition is None:
            return None
        version = (
            ComponentVersion.query.filter_by(component_definition_id=definition.id, is_active=True)
            .order_by(ComponentVersion.created_at.desc())
            .first()
        )
        return version.id if version else None

    def _get_active_pipeline_version_row(self, definition: PipelineDefinition) -> Optional[PipelineVersion]:
        if definition.active_version_id:
            row = db.session.get(PipelineVersion, definition.active_version_id)
            if row is not None:
                return row
        return (
            PipelineVersion.query.filter_by(pipeline_definition_id=definition.id, is_active=True)
            .order_by(PipelineVersion.activated_at.desc(), PipelineVersion.created_at.desc())
            .first()
        )

    def _get_profile_row(self, version_row: ComponentVersion, requested_profile_id: Optional[str]) -> ComponentProfile:
        query = ComponentProfile.query.filter_by(component_version_id=version_row.id, is_active=True)
        if requested_profile_id:
            profile = query.filter_by(profile_id=requested_profile_id).first()
            if profile is None:
                raise ResourceNotFoundError(
                    "Component profile not found",
                    details={"version": version_row.version, "profile_id": requested_profile_id},
                )
            return profile
        profile = query.order_by(ComponentProfile.created_at.asc()).first()
        if profile is None:
            raise ResourceNotFoundError("Component profile not found", details={"version": version_row.version})
        return profile

    def _serialize_component_version(self, definition: ComponentDefinition, version_row: ComponentVersion) -> Dict[str, Any]:
        manifest = _json_loads(version_row.manifest_json, {})
        manifest["compatibility"] = self._normalize_manifest_compatibility(
            manifest.get("compatibility"),
            source_type=definition.source_type,
        )
        playground = copy.deepcopy(manifest["compatibility"]["playground"])
        playground_schema = self._build_playground_schema(manifest)
        constructor_schema = self._build_constructor_schema(manifest)
        return {
            "key": definition.key,
            "name": definition.name,
            "description": definition.description,
            "source_type": definition.source_type,
            "version": version_row.version,
            "manifest": manifest,
            "playground": playground,
            "playground_schema": playground_schema,
            "constructor_schema": constructor_schema,
            "profiles": [
                {
                    "profile_id": profile.profile_id,
                    "adapter": profile.adapter,
                    "runtime": profile.runtime,
                    "entrypoint": _json_loads(profile.entrypoint_json, []),
                    "config": _json_loads(profile.config_json, {}),
                }
                for profile in version_row.profiles
            ],
        }

    def _serialize_pipeline_summary(self, definition: PipelineDefinition) -> Dict[str, Any]:
        version_row = self._get_active_pipeline_version_row(definition)
        config = _json_loads(version_row.config_json, {}) if version_row else {}
        return {
            "identifier": definition.identifier,
            "name": definition.name,
            "description": definition.description,
            "status": definition.status,
            "modality": definition.modality,
            "processingMode": definition.processing_mode,
            "version": version_row.version if version_row else None,
            "tags": _json_loads(definition.tags_json, []),
            "config": config,
        }

    def _serialize_pipeline_definition(self, definition: PipelineDefinition) -> Dict[str, Any]:
        summary = self._serialize_pipeline_summary(definition)
        version_row = self._get_active_pipeline_version_row(definition)
        summary["active_version"] = version_row.version if version_row else None
        summary["config"] = _json_loads(version_row.config_json, {}) if version_row else {}
        summary["components"] = [self._serialize_component_version(db.session.get(ComponentDefinition, row.component_definition_id), row) for row in {step.component_version_id: db.session.get(ComponentVersion, step.component_version_id) for step in version_row.steps if step.component_version_id}.values()] if version_row else []
        return summary

    def _serialize_pipeline_run(self, run: PipelineRun) -> Dict[str, Any]:
        return {
            "run_id": run.public_id,
            "pipeline_version": db.session.get(PipelineVersion, run.pipeline_version_id).version,
            "status": run.status.value if hasattr(run.status, "value") else run.status,
            "started_at": run.started_at.isoformat() + "Z" if run.started_at else None,
            "completed_at": run.completed_at.isoformat() + "Z" if run.completed_at else None,
            "request": _json_loads(run.request_json, {}),
            "result": _json_loads(run.result_json, {}),
            "timings": _json_loads(run.timings_json, {}),
            "error": run.error_message,
            "steps": [self._serialize_step_run(step) for step in run.step_runs],
            "artifacts": [
                {
                    "name": artifact.name,
                    "path": artifact.path,
                    "artifact_kind": artifact.artifact_kind,
                    "record_id": artifact.record_id,
                    "metadata": _json_loads(artifact.metadata_json, {}),
                }
                for artifact in run.artifacts
            ],
        }

    def _serialize_step_run(self, step: StepRun) -> Dict[str, Any]:
        pipeline_step = db.session.get(PipelineStep, step.pipeline_step_id) if step.pipeline_step_id else None
        return {
            "id": step.id,
            "pipeline_step_id": step.pipeline_step_id,
            "step_key": pipeline_step.step_key if pipeline_step else None,
            "component_key": pipeline_step.component_key if pipeline_step else None,
            "record_id": step.record_id,
            "record_path": step.record_path,
            "status": step.status,
            "scope": step.scope,
            "command": _json_loads(step.command_json, []),
            "result": _json_loads(step.result_json, {}),
            "error": step.error_message,
        }

    def _serialize_playground_run(self, run: PlaygroundRun) -> Dict[str, Any]:
        return {
            "run_id": run.public_id,
            "status": run.status.value if hasattr(run.status, "value") else run.status,
            "started_at": run.started_at.isoformat() + "Z" if run.started_at else None,
            "completed_at": run.completed_at.isoformat() + "Z" if run.completed_at else None,
            "request": _json_loads(run.request_json, {}),
            "result": _json_loads(run.result_json, {}),
            "logs": _json_loads(run.logs_json, {}),
            "error": run.error_message,
        }

    def _load_zenodo_metadata_schema(self) -> Dict[str, Any]:
        schema_path = self._repo_root() / "zenodo_metadata_schema.json"
        try:
            with open(schema_path, "r", encoding="utf-8") as handle:
                return json.load(handle) or {}
        except FileNotFoundError as exc:
            raise ValidationError("zenodo_metadata_schema.json not found", details={"path": str(schema_path)}) from exc
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValidationError("Failed to parse zenodo_metadata_schema.json", details={"path": str(schema_path)}) from exc

    def _flatten_zenodo_target_paths(self) -> List[Dict[str, Any]]:
        schema = self._load_zenodo_metadata_schema()
        flattened: List[Dict[str, Any]] = []

        for entry in schema.get("standard_fields") or []:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key") or "").strip()
            if not key:
                continue
            flattened.append(
                {
                    "path": key,
                    "label": str(entry.get("label") or key).strip(),
                    "value_type": str(entry.get("type") or "text").strip(),
                    "multiple": False,
                }
            )

        for field_name, definition in (schema.get("complex_fields") or {}).items():
            if not isinstance(definition, dict):
                continue
            allow_multiple = bool(definition.get("allow_multiple", False))
            base_path = f"{field_name}[]" if allow_multiple else str(field_name)
            attributes = definition.get("attributes") or []
            if not isinstance(attributes, list):
                continue
            for attribute in attributes:
                if not isinstance(attribute, dict):
                    continue
                attribute_key = str(attribute.get("key") or "").strip()
                if not attribute_key:
                    continue
                flattened.append(
                    {
                        "path": f"{base_path}.{attribute_key}",
                        "label": f"{definition.get('label') or field_name} / {attribute.get('label') or attribute_key}",
                        "value_type": str(attribute.get("type") or "text").strip(),
                        "multiple": allow_multiple,
                    }
                )

        flattened.sort(key=lambda item: str(item.get("path") or ""))
        return flattened

    def _flatten_edm_metadata_target_paths(self) -> List[Dict[str, Any]]:
        return [_deepcopy(entry) for entry in EDM_METADATA_TARGET_PATHS]

    def _flatten_metadata_target_paths(self) -> List[Dict[str, Any]]:
        combined: Dict[str, Dict[str, Any]] = {}
        for entry in self._flatten_zenodo_target_paths():
            path = str(entry.get("path") or "").strip()
            if not path:
                continue
            combined[path] = {
                **entry,
                "scope": "zenodo",
                "action_type": "zenodo_metadata_field",
            }
        for entry in self._flatten_edm_metadata_target_paths():
            path = str(entry.get("path") or "").strip()
            if not path:
                continue
            combined[path] = {
                **entry,
                "scope": "edm",
                "action_type": entry.get("action_type") or "edm_metadata_field",
            }
        return sorted(combined.values(), key=lambda item: (str(item.get("scope") or ""), str(item.get("path") or "")))

    def _step_component_version(self, step):
        definition = ComponentDefinition.query.filter_by(key=step.get("component_ref") or step["id"]).first()
        if definition is None:
            raise ValidationError("Component is not registered")
        query = ComponentVersion.query.filter_by(component_definition_id=definition.id)
        query = query.filter_by(version=step["component_version"]) if step.get("component_version") else query.filter_by(is_active=True)
        version = query.order_by(ComponentVersion.created_at.desc()).first()
        if version is None:
            raise ValidationError("The selected component version is unavailable")
        if step.get("component_manifest_hash") and step["component_manifest_hash"] != version.manifest_hash:
            raise OperationConflict("The component manifest changed. Select a new component version and publish again.")
        return version

    def _preflight_signer(self):
        return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="pipeline-preflight-v1")

    def _verify_preflight(self, payload, config, user_id):
        token = payload.get("preflight_token")
        if not token:
            return
        try:
            checked = self._preflight_signer().loads(token, max_age=3600)
        except BadSignature as exc:
            raise OperationConflict("Preflight expired or is invalid. Check the selected files again.") from exc
        expected = {"config_hash": _hash_payload(self._normalize_pipeline_config(config)), "session_id": payload.get("session_id"), "paths": payload.get("local_file_paths"), "user_id": user_id}
        if checked != expected:
            raise OperationConflict("The definition or selected files changed. Repeat preflight before running.")

    def _get_component_manifest_by_key(self, component_key: str, version: Optional[str] = None) -> Dict[str, Any]:
        definition = ComponentDefinition.query.filter_by(key=component_key, is_active=True).first()
        if definition is None:
            raise ValidationError("Component is not registered", details={"component_key": component_key})
        query = ComponentVersion.query.filter_by(component_definition_id=definition.id)
        query = query.filter_by(version=version) if version else query.filter_by(is_active=True)
        version_row = query.order_by(ComponentVersion.created_at.desc()).first()
        if version_row is None:
            raise ValidationError("Component has no active version", details={"component_key": component_key})
        manifest = _json_loads(version_row.manifest_json, {})
        manifest["compatibility"] = self._normalize_manifest_compatibility(
            manifest.get("compatibility"),
            source_type=definition.source_type,
        )
        return manifest

    def _build_record_context_for_preflight(self, index: int, file_path: str) -> Dict[str, Any]:
        classification = self._classify_input_file(file_path)
        return {
            "record_id": index,
            "file_path": str(file_path),
            "filename": os.path.basename(str(file_path)),
            "file_zenodo_metadata": {},
            "generated_files": [],
            "step_outputs": {
                "__file_facts__": {
                    "classification_json": classification,
                }
            },
            "specific_output_dir": str(Path(file_path).parent / "__constructor_preflight__"),
            "record_status": {"warnings": [], "step_results": {}},
            "record_timings": {"steps": {}, "subprocesses": {}},
            "current_zenodo_draft_record_id": None,
            "draft_result": {},
            "batch_state": {},
            "index": index,
            "total_records": 1,
        }

    @staticmethod
    def _coerce_truthy(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value in (None, "", [], {}):
            return False
        return True

    @staticmethod
    def _normalize_json_selector(selector: Optional[str]) -> str:
        return str(selector or "").strip().lstrip("$.")

    def _read_json_path_value(self, value: Any, selector: Optional[str]) -> Any:
        return self._extract_selector_value(value, selector)

    def _classify_ply_file(self, file_path: str) -> str:
        try:
            with open(file_path, "rb") as handle:
                header = handle.read(4096).decode("utf-8", errors="ignore")
        except OSError:
            return "unknown"
        if "format ascii" not in header and "format binary_little_endian" not in header and "format binary_big_endian" not in header:
            return "unknown"
        face_match = re.search(r"element\s+face\s+(\d+)", header)
        vertex_match = re.search(r"element\s+vertex\s+(\d+)", header)
        if face_match:
            try:
                if int(face_match.group(1)) > 0:
                    return "mesh"
            except ValueError:
                return "unknown"
        if vertex_match:
            try:
                if int(vertex_match.group(1)) > 0:
                    return "point_cloud"
            except ValueError:
                return "unknown"
        return "unknown"

    def _classify_input_file(self, file_path: str) -> Dict[str, Any]:
        path = Path(str(file_path))
        extension = path.suffix.lower()
        mime_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = None
        asset_kind = "3d_model" if extension in MODEL_FILE_EXTENSIONS else "unknown"
        model_kind = "unknown"
        if extension == ".ply":
            model_kind = self._classify_ply_file(str(path))
        elif extension in MODEL_FILE_EXTENSIONS - {".ply"}:
            model_kind = "mesh"
        return {
            "file": {
                "path": str(path),
                "extension": extension,
                "mime_type": mime_type,
                "size_bytes": size_bytes,
                "is_3d_model": asset_kind == "3d_model",
            },
            "asset": {
                "kind": asset_kind,
                "model_kind": model_kind,
            },
        }

    def _resolve_trigger_condition_value(self, condition: Dict[str, Any], record_context: Dict[str, Any]) -> Any:
        source_type = condition.get("source_type")
        field = str(condition.get("field") or "").strip()
        if source_type == "file_fact":
            classification = record_context.get("step_outputs", {}).get("__file_facts__", {}).get("classification_json") or self._classify_input_file(record_context["file_path"])
            return self._extract_selector_value(classification, f"$.file.{field}")
        if source_type == "classifier_output":
            source_step = str(condition.get("source_step") or "").strip()
            source_output = str(condition.get("source_output") or "").strip()
            outputs = record_context.get("step_outputs", {}).get(source_step, {})
            source_value = outputs.get(source_output)
            selector = field if field.startswith("$.") else f"$.{field.lstrip('.')}"
            return self._extract_selector_value(source_value, selector)
        return None

    def _evaluate_trigger_condition(self, condition: Dict[str, Any], record_context: Dict[str, Any]) -> bool:
        current_value = self._resolve_trigger_condition_value(condition, record_context)
        operator = str(condition.get("operator") or "").strip()
        if operator == "exists":
            return current_value not in (None, "")
        if operator == "truthy":
            return self._coerce_truthy(current_value)
        if operator == "eq":
            return current_value == condition.get("value")
        if operator == "neq":
            return current_value != condition.get("value")
        if operator == "in":
            return current_value in (condition.get("values") or [])
        if operator == "not_in":
            return current_value not in (condition.get("values") or [])
        if operator == "gte":
            return current_value is not None and current_value >= condition.get("value")
        if operator == "lte":
            return current_value is not None and current_value <= condition.get("value")
        if operator == "between":
            values = condition.get("values") or []
            if len(values) != 2 or current_value is None:
                return False
            return values[0] <= current_value <= values[1]
        return False

    def _resolve_step_trigger(self, step: Dict[str, Any], record_context: Dict[str, Any]) -> Dict[str, Any]:
        triggers = step.get("triggers") or {}
        default_behavior = str(triggers.get("default_behavior") or "run").strip().lower()
        for rule in triggers.get("rules") or []:
            conditions = rule.get("conditions") or []
            if conditions and all(self._evaluate_trigger_condition(condition, record_context) for condition in conditions):
                return {
                    "action": str(rule.get("action") or "run").strip().lower(),
                    "matched_rule_id": rule.get("id"),
                    "parameter_overrides": _deepcopy(rule.get("parameter_overrides") or {}),
                }
        return {"action": default_behavior, "matched_rule_id": None, "parameter_overrides": {}}

    def _apply_default_input_bindings(
        self,
        manifest_inputs: List[Dict[str, Any]],
        resolved_inputs: Dict[str, Any],
        record_context: Dict[str, Any],
        execution_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        output = _deepcopy(resolved_inputs or {})
        input_definitions = self._field_definition_map(manifest_inputs)
        for field in manifest_inputs:
            if not isinstance(field, dict):
                continue
            field_name = str(field.get("name") or "").strip()
            field_type = str(field.get("type") or "").strip().lower()
            if not field_name or field_name in output:
                continue
            mutex_fields = {
                str(item).strip()
                for item in _listify(field.get("mutex_with"))
                if str(item).strip()
            }
            if any(self._has_meaningful_bound_value(output.get(mutex_field)) for mutex_field in mutex_fields):
                continue
            if field_type == "file_path":
                output[field_name] = record_context.get("file_path")
            elif field_type == "file_list":
                source_files = self._candidate_source_files_for_inputs(
                    input_definitions,
                    output,
                    execution_context,
                    record_context,
                )
                if source_files:
                    output[field_name] = _deepcopy(source_files)
                else:
                    output[field_name] = [record_context.get("file_path")]
            elif field_type == "dir_path":
                source_files = self._candidate_source_files_for_inputs(
                    input_definitions,
                    output,
                    execution_context,
                    record_context,
                )
                derived_directory = self._common_parent_directory(source_files)
                if derived_directory:
                    output[field_name] = derived_directory
        return output

    @staticmethod
    def _has_meaningful_bound_value(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set)):
            return any(str(item).strip() for item in value if item is not None)
        if isinstance(value, dict):
            return bool(value)
        return True

    @staticmethod
    def _normalize_path_list(value: Any) -> List[str]:
        normalized: List[str] = []
        seen = set()
        for item in _listify(value):
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized

    @staticmethod
    def _parent_directories_for_paths(file_paths: List[str]) -> List[str]:
        directories: List[str] = []
        seen = set()
        for path in file_paths:
            normalized = str(path or "").strip()
            if not normalized:
                continue
            directory = str(Path(normalized).parent)
            if directory in seen:
                continue
            seen.add(directory)
            directories.append(directory)
        return directories

    def _candidate_source_files_for_inputs(
        self,
        input_definitions: Dict[str, Dict[str, Any]],
        resolved_inputs: Dict[str, Any],
        execution_context: Optional[Dict[str, Any]] = None,
        record_context: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        source_files: List[str] = []
        for field_name, definition in input_definitions.items():
            field_type = str(definition.get("type") or "").strip().lower()
            raw_value = resolved_inputs.get(field_name)
            if field_type == "file_list":
                for file_path in self._normalize_path_list(raw_value):
                    if file_path not in source_files:
                        source_files.append(file_path)
            elif field_type == "file_path":
                value = str(raw_value or "").strip()
                if value and value not in source_files:
                    source_files.append(value)

        if isinstance(execution_context, dict):
            for file_path in self._normalize_path_list(execution_context.get("bucket_source_files")):
                if file_path not in source_files:
                    source_files.append(file_path)

        if not source_files and isinstance(record_context, dict):
            record_file = str(record_context.get("file_path") or "").strip()
            if record_file:
                source_files.append(record_file)
        return source_files

    @staticmethod
    def _common_parent_directory(file_paths: List[str]) -> Optional[str]:
        parents = {
            str(Path(path).parent)
            for path in file_paths
            if str(path or "").strip()
        }
        if len(parents) == 1:
            return next(iter(parents))
        return None

    def _prepare_batch_input_state(
        self,
        input_definitions: Dict[str, Dict[str, Any]],
        resolved_inputs: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]], List[str]]:
        file_input_names = [
            name
            for name, definition in input_definitions.items()
            if str(definition.get("type") or "").strip().lower() in {"file_path", "file_list", "dir_path"}
        ]
        signature_inputs = {
            key: value
            for key, value in resolved_inputs.items()
            if key not in file_input_names
        }
        file_inputs: Dict[str, Dict[str, Any]] = {}
        source_files: List[str] = []

        for field_name in file_input_names:
            field_type = str(input_definitions.get(field_name, {}).get("type") or "").strip().lower()
            raw_value = resolved_inputs.get(field_name)
            if field_type == "file_list":
                values = self._normalize_path_list(raw_value)
                file_inputs[field_name] = {"type": field_type, "values": values}
                for file_path in values:
                    if file_path not in source_files:
                        source_files.append(file_path)
                continue

            normalized_value = str(raw_value or "").strip() or None
            file_inputs[field_name] = {"type": field_type, "value": normalized_value}
            if field_type == "file_path" and normalized_value and normalized_value not in source_files:
                source_files.append(normalized_value)
            if field_type == "file_path" and normalized_value:
                signature_inputs[field_name] = normalized_value

        for field_name in file_input_names:
            field_definition = input_definitions.get(field_name, {}) or {}
            field_type = str(field_definition.get("type") or "").strip().lower()
            if field_type != "dir_path":
                continue
            raw_value = resolved_inputs.get(field_name)
            normalized_value = str(raw_value or "").strip() or None
            if normalized_value:
                file_inputs[field_name] = {"type": field_type, "value": normalized_value}
                signature_inputs[field_name] = normalized_value
                continue

            mutex_fields = {
                str(item).strip()
                for item in _listify(field_definition.get("mutex_with"))
                if str(item).strip()
            }
            if any(self._has_meaningful_bound_value(resolved_inputs.get(mutex_field)) for mutex_field in mutex_fields):
                file_inputs[field_name] = {"type": field_type, "value": None, "skipped_due_to_mutex": True}
                continue

            candidate_directories = self._parent_directories_for_paths(source_files)
            derived_directory = self._common_parent_directory(source_files)
            if derived_directory:
                file_inputs[field_name] = {
                    "type": field_type,
                    "value": derived_directory,
                    "derived": True,
                }
                signature_inputs[field_name] = derived_directory
            elif candidate_directories:
                file_inputs[field_name] = {
                    "type": field_type,
                    "value": None,
                    "derived": True,
                    "unresolved": True,
                    "candidate_directories": candidate_directories,
                }
                signature_inputs[field_name] = {
                    "__unresolved_dir_path__": candidate_directories,
                }
            else:
                file_inputs[field_name] = {"type": field_type, "value": None}

        return signature_inputs, file_inputs, source_files

    def _batch_dir_path_warnings(
        self,
        step: Dict[str, Any],
        input_definitions: Dict[str, Dict[str, Any]],
        batch_state: Dict[str, Any],
    ) -> List[str]:
        warnings: List[str] = []
        for field_name, definition in input_definitions.items():
            if str(definition.get("type") or "").strip().lower() != "dir_path":
                continue
            state = (batch_state.get("file_inputs") or {}).get(field_name) or {}
            if not state.get("unresolved"):
                continue
            directories = ", ".join(state.get("candidate_directories") or [])
            warnings.append(
                f"Step '{step['id']}' could not resolve directory input '{field_name}' to a single directory for this batch bucket. Candidate directories: {directories}"
            )
        return warnings

    @staticmethod
    def _normalize_manifest_compatibility(
        compatibility: Optional[Dict[str, Any]],
        *,
        source_type: str,
    ) -> Dict[str, Any]:
        normalized = _deepcopy(compatibility or {})
        playground = normalized.get("playground")
        enabled: Optional[bool] = None
        reason: Optional[str] = None

        if isinstance(playground, dict):
            raw_enabled = playground.get("enabled")
            if isinstance(raw_enabled, bool):
                enabled = raw_enabled
            elif raw_enabled is not None:
                enabled = bool(raw_enabled)
            raw_reason = playground.get("reason")
            if raw_reason is not None:
                reason = str(raw_reason).strip() or None
        elif isinstance(playground, bool):
            enabled = playground

        if enabled is None:
            enabled = source_type != "builtin"

        if not enabled and not reason:
            if source_type == "builtin":
                reason = "Built-in pipeline step components require pipeline runtime context and are not runnable in Playground."
            else:
                reason = "This component is not available in Playground."

        normalized["playground"] = {
            "enabled": bool(enabled),
            "reason": reason if not enabled else None,
        }
        return normalized

    @staticmethod
    def _field_has_meaningful_default(field: Dict[str, Any]) -> bool:
        default = field.get("default")
        if default is None:
            return False
        if isinstance(default, str) and default == "":
            return False
        return True

    @staticmethod
    def _is_missing_manifest_value(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip() == ""
        if isinstance(value, list):
            return len(value) == 0
        return False

    def _normalize_playground_fields(
        self,
        definitions: Iterable[Dict[str, Any]],
        submitted_values: Optional[Dict[str, Any]],
        *,
        category: str,
    ) -> Dict[str, Any]:
        normalized_values = submitted_values if isinstance(submitted_values, dict) else {}
        field_map = {
            str(field.get("name") or "").strip(): field
            for field in definitions
            if isinstance(field, dict) and str(field.get("name") or "").strip()
        }

        unknown_fields = sorted(
            name
            for name in normalized_values.keys()
            if str(name).strip() and str(name).strip() not in field_map
        )
        if unknown_fields:
            raise ValidationError(
                f"Unknown playground {category} fields",
                details={"fields": unknown_fields},
            )

        output: Dict[str, Any] = {}
        for field_name, field in field_map.items():
            has_value = field_name in normalized_values
            raw_value = normalized_values.get(field_name) if has_value else None
            if not has_value or self._is_missing_manifest_value(raw_value):
                if self._field_has_meaningful_default(field):
                    output[field_name] = _deepcopy(field.get("default"))
                    continue
                if field.get("required"):
                    raise ValidationError(
                        f"Missing required playground {category}: {field_name}",
                        details={"field": field_name, "category": category},
                    )
                continue
            output[field_name] = self._coerce_playground_field_value(field, raw_value, category=category)
        return output

    def _coerce_playground_field_value(self, field: Dict[str, Any], value: Any, *, category: str) -> Any:
        field_name = str(field.get("name") or "").strip() or "<unknown>"
        field_type = str(field.get("type") or "").strip().lower()

        try:
            if field_type == "boolean":
                if isinstance(value, bool):
                    return value
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return bool(value)
                text = str(value).strip().lower()
                if text in {"true", "1", "yes", "on"}:
                    return True
                if text in {"false", "0", "no", "off"}:
                    return False
                raise ValueError("Expected a boolean value")

            if field_type == "integer":
                if isinstance(value, bool):
                    raise ValueError("Expected an integer value")
                if isinstance(value, int):
                    return value
                if isinstance(value, float):
                    if value.is_integer():
                        return int(value)
                    raise ValueError("Expected an integer value")
                return int(str(value).strip(), 10)

            if field_type == "number":
                if isinstance(value, bool):
                    raise ValueError("Expected a numeric value")
                if isinstance(value, (int, float)):
                    return value
                return float(str(value).strip())

            if field_type == "string_dropdown":
                text = str(value).strip()
                options = [str(option) for option in _listify(field.get("options"))]
                if options and text not in options:
                    raise ValueError(f"Expected one of: {', '.join(options)}")
                return text

            if field_type == "json":
                if isinstance(value, (list, dict)):
                    return _deepcopy(value)
                text = str(value).strip()
                if not text:
                    return None
                parsed = json.loads(text)
                if not isinstance(parsed, (list, dict)):
                    raise ValueError("Expected a JSON object or array")
                return parsed

            if field_type == "file_list":
                if isinstance(value, str):
                    text = value.strip()
                    if not text:
                        return []
                    if text.startswith("["):
                        parsed = json.loads(text)
                        if not isinstance(parsed, list):
                            raise ValueError("Expected a JSON array")
                        return [str(item).strip() for item in parsed if str(item).strip()]
                    return [line.strip() for line in text.splitlines() if line.strip()]
                return [str(item).strip() for item in _listify(value) if str(item).strip()]

            if field_type in {"array[string]", "array[number]", "array[integer]"}:
                item_type = field_type[6:-1]
                items: List[Any]
                if isinstance(value, str):
                    text = value.strip()
                    if not text:
                        return []
                    if text.startswith("["):
                        parsed = json.loads(text)
                        if not isinstance(parsed, list):
                            raise ValueError("Expected a JSON array")
                        items = parsed
                    else:
                        items = [line.strip() for line in text.splitlines() if line.strip()]
                elif isinstance(value, list):
                    items = value
                else:
                    items = _listify(value)
                return [
                    self._coerce_playground_field_value(
                        {"name": field_name, "type": item_type},
                        item,
                        category=category,
                    )
                    for item in items
                ]

            if field_type in {"file_path", "dir_path", "string", "text"}:
                return str(value).strip()

            return _deepcopy(value)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValidationError(
                f"Invalid playground {category}: {field_name}",
                details={"field": field_name, "category": category, "expected_type": field_type, "reason": str(exc)},
            ) from exc

    def _normalize_playground_payload(
        self,
        manifest: Dict[str, Any],
        request_model: PlaygroundExecutionRequestSchema,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        raw_inputs = _deepcopy(request_model.inputs or {})
        if request_model.input_files and "input_files" not in raw_inputs:
            raw_inputs["input_files"] = _deepcopy(request_model.input_files)
        normalized_inputs = self._normalize_playground_fields(
            manifest.get("inputs") or [],
            raw_inputs,
            category="input",
        )
        parameter_definitions: List[Dict[str, Any]] = []
        for group in manifest.get("parameter_groups") or []:
            if isinstance(group, dict):
                parameter_definitions.extend(group.get("parameters") or [])
        normalized_parameters = self._normalize_playground_fields(
            parameter_definitions,
            request_model.parameters or {},
            category="parameter",
        )
        submitted_field_names = {
            str(name).strip()
            for values in (raw_inputs, request_model.parameters or {})
            for name, value in (values.items() if isinstance(values, dict) else [])
            if str(name).strip() and not self._is_missing_manifest_value(value)
        }
        field_definitions = {
            str(field.get("name") or "").strip(): field
            for field in [*(manifest.get("inputs") or []), *parameter_definitions]
            if isinstance(field, dict) and str(field.get("name") or "").strip()
        }
        for field_name in list(submitted_field_names):
            field = field_definitions.get(field_name) or {}
            for target_name in field.get("mutex_with") or []:
                target = str(target_name or "").strip()
                if target and target not in submitted_field_names:
                    normalized_inputs.pop(target, None)
                    normalized_parameters.pop(target, None)
        combined_values = {**normalized_inputs, **normalized_parameters}
        for field_name, field in field_definitions.items():
            if field_name not in combined_values or self._is_missing_manifest_value(combined_values.get(field_name)):
                continue
            for target_name in field.get("mutex_with") or []:
                target_value = combined_values.get(target_name)
                if not self._is_missing_manifest_value(target_value):
                    raise ValidationError(
                        "Mutually exclusive Playground fields were provided together",
                        details={"field": field_name, "conflicts_with": target_name},
                    )
        return normalized_inputs, normalized_parameters

    @staticmethod
    def _resolve_playground_output_path(
        manifest: Dict[str, Any],
        workdir: str,
        *,
        output_name: Optional[str] = None,
        fallback_directory: str = "outputs",
    ) -> str:
        outputs = manifest.get("outputs") or []
        selected_output = None
        if output_name:
            for output in outputs:
                if isinstance(output, dict) and str(output.get("name") or "").strip() == output_name:
                    selected_output = output
                    break
        if selected_output is None:
            for output in outputs:
                if isinstance(output, dict):
                    selected_output = output
                    break

        declared_default = None
        if isinstance(selected_output, dict):
            declared_default = selected_output.get("default")

        if isinstance(declared_default, str) and declared_default.strip():
            if os.path.isabs(declared_default):
                return declared_default
            return os.path.normpath(os.path.join(workdir, declared_default))

        return os.path.join(workdir, fallback_directory)

    @staticmethod
    def _normalize_manifest_field_type(field_type: Any) -> str:
        normalized = str(field_type or "string").strip().lower()
        normalized = PLAYGROUND_FIELD_TYPE_ALIASES.get(normalized, normalized)
        if normalized not in ALLOWED_PLAYGROUND_FIELD_TYPES:
            raise ValidationError(
                "Unsupported component field type",
                details={"field_type": normalized},
            )
        return normalized

    def _normalize_manifest_field_default(self, field: Dict[str, Any], field_type: str, *, field_name: str) -> Any:
        default = _deepcopy(field.get("default"))
        if default is None:
            return None
        if isinstance(default, str) and default.strip() == "":
            if field_type in {"string", "text", "file_path", "dir_path", "string_dropdown"}:
                return ""
            return None

        if field_type == "boolean":
            return self._coerce_playground_field_value({"name": field_name, "type": field_type}, default, category="default")
        if field_type == "integer":
            return self._coerce_playground_field_value({"name": field_name, "type": field_type}, default, category="default")
        if field_type == "number":
            return self._coerce_playground_field_value({"name": field_name, "type": field_type}, default, category="default")
        if field_type == "file_list":
            if not isinstance(default, list):
                raise ValidationError(
                    "file_list fields require a list default when a default is provided",
                    details={"field": field_name},
                )
            return [str(item).strip() for item in default if str(item).strip()]
        if field_type == "json":
            return default
        if field_type == "array[string]":
            if not isinstance(default, list):
                raise ValidationError(
                    "array[string] fields require a list default when a default is provided",
                    details={"field": field_name},
                )
            return [str(item) for item in default]
        if field_type == "array[number]":
            if not isinstance(default, list):
                raise ValidationError(
                    "array[number] fields require a list default when a default is provided",
                    details={"field": field_name},
                )
            return [
                self._coerce_playground_field_value({"name": field_name, "type": "number"}, item, category="default")
                for item in default
            ]
        if field_type == "array[integer]":
            if not isinstance(default, list):
                raise ValidationError(
                    "array[integer] fields require a list default when a default is provided",
                    details={"field": field_name},
                )
            return [
                self._coerce_playground_field_value({"name": field_name, "type": "integer"}, item, category="default")
                for item in default
            ]
        if field_type in {"string", "text", "file_path", "dir_path", "string_dropdown"}:
            if isinstance(default, (list, dict)):
                raise ValidationError(
                    "String-like component fields cannot declare object or array defaults",
                    details={"field": field_name, "type": field_type},
                )
            return str(default)
        return default

    def _normalize_manifest_field_definition(
        self,
        raw_field: Any,
        *,
        field_name_set: set[str],
        category: str,
    ) -> Dict[str, Any]:
        if not isinstance(raw_field, dict):
            raise ValidationError("Component field definitions must be objects", details={"category": category})
        field = _deepcopy(raw_field)
        field_name = str(field.get("name") or "").strip()
        if not field_name:
            raise ValidationError("Component field definitions require a name", details={"category": category})
        if field_name in field_name_set:
            raise ValidationError("Duplicate component field name", details={"field": field_name, "category": category})
        field_name_set.add(field_name)

        field_type = self._normalize_manifest_field_type(field.get("type"))
        field["type"] = field_type
        field["required"] = bool(field.get("required", False))
        field["label"] = str(field.get("label") or field_name).strip()
        field["description"] = str(field.get("description") or "").strip()
        field["default"] = self._normalize_manifest_field_default(field, field_type, field_name=field_name)

        options = field.get("options") or []
        if field_type == "string_dropdown":
            if not isinstance(options, list) or len(options) == 0:
                raise ValidationError(
                    "string_dropdown fields require a non-empty options list",
                    details={"field": field_name},
                )
            normalized_options = [str(option) for option in options]
            field["options"] = normalized_options
            default_value = field.get("default")
            if isinstance(default_value, str) and default_value and default_value not in normalized_options:
                raise ValidationError(
                    "Dropdown default must be one of the declared options",
                    details={"field": field_name, "default": default_value},
                )
        elif isinstance(options, list):
            field["options"] = _deepcopy(options)
        else:
            raise ValidationError(
                "Field options must be an array when provided",
                details={"field": field_name},
            )

        mutex_with = field.get("mutex_with") or []
        if not isinstance(mutex_with, list):
            raise ValidationError("mutex_with must be an array", details={"field": field_name})
        field["mutex_with"] = [str(item).strip() for item in mutex_with if str(item).strip()]
        return field

    def _normalize_manifest_visibility_condition(
        self,
        raw_condition: Any,
        *,
        known_field_names: set[str],
        owner_field: str,
    ) -> Optional[Dict[str, Any]]:
        if raw_condition in (None, "", {}):
            return None
        if not isinstance(raw_condition, dict):
            raise ValidationError("visible_if must be an object", details={"field": owner_field})
        target_field = str(raw_condition.get("field") or "").strip()
        if not target_field or target_field not in known_field_names:
            raise ValidationError(
                "visible_if must reference a known field",
                details={"field": owner_field, "target_field": target_field},
            )
        normalized: Dict[str, Any] = {"field": target_field}
        for key in ("equals", "not_equals", "truthy"):
            if key in raw_condition:
                normalized[key] = _deepcopy(raw_condition.get(key))
        if "in" in raw_condition:
            value = raw_condition.get("in")
            if not isinstance(value, list):
                raise ValidationError("visible_if.in must be an array", details={"field": owner_field})
            normalized["in"] = _deepcopy(value)
        if len(normalized) == 1:
            raise ValidationError(
                "visible_if must declare a comparison rule",
                details={"field": owner_field},
            )
        return normalized

    def _normalize_manifest_constructor_output_ui(
        self,
        raw_outputs: Any,
        *,
        known_output_names: set[str],
    ) -> Dict[str, Any]:
        if raw_outputs in (None, "", {}):
            return {"outputs": {}}
        if not isinstance(raw_outputs, dict):
            raise ValidationError("ui.constructor.outputs must be an object")

        normalized_outputs: Dict[str, Any] = {}
        for output_name, config in raw_outputs.items():
            normalized_name = str(output_name or "").strip()
            if not normalized_name or normalized_name not in known_output_names:
                raise ValidationError(
                    "ui.constructor.outputs contains an unknown output reference",
                    details={"output": normalized_name},
                )
            if not isinstance(config, dict):
                raise ValidationError(
                    "Constructor output configuration must be an object",
                    details={"output": normalized_name},
                )

            raw_trigger_fields = config.get("trigger_fields") or []
            if not isinstance(raw_trigger_fields, list):
                raise ValidationError(
                    "ui.constructor.outputs.*.trigger_fields must be an array",
                    details={"output": normalized_name},
                )
            normalized_trigger_fields: List[Dict[str, Any]] = []
            for index, entry in enumerate(raw_trigger_fields):
                if not isinstance(entry, dict):
                    raise ValidationError(
                        "Trigger field entries must be objects",
                        details={"output": normalized_name, "index": index},
                    )
                path = str(entry.get("path") or entry.get("json_path") or "").strip()
                if not path or not path.startswith("$."):
                    raise ValidationError(
                        "Trigger field paths must start with '$.'",
                        details={"output": normalized_name, "index": index, "path": path},
                    )
                operators = [
                    str(item).strip()
                    for item in _listify(entry.get("operators"))
                    if str(item).strip()
                ] or ["eq", "neq", "exists", "truthy"]
                invalid_operators = sorted(set(operators) - ALLOWED_CONSTRUCTOR_TRIGGER_OPERATORS)
                if invalid_operators:
                    raise ValidationError(
                        "Unsupported constructor trigger operators declared",
                        details={"output": normalized_name, "operators": invalid_operators},
                    )
                options = []
                for option in _listify(entry.get("options")):
                    if isinstance(option, dict):
                        option_label = str(option.get("label") or option.get("value") or "").strip()
                        option_value = _deepcopy(option.get("value"))
                    else:
                        option_label = str(option).strip()
                        option_value = _deepcopy(option)
                    if not option_label:
                        continue
                    options.append({"label": option_label, "value": option_value})
                normalized_trigger_fields.append(
                    {
                        "path": path,
                        "label": str(entry.get("label") or path).strip(),
                        "value_type": str(entry.get("value_type") or "string").strip().lower(),
                        "operators": operators,
                        "options": options,
                    }
                )

            selector_examples = [
                str(item).strip()
                for item in _listify(config.get("selector_examples"))
                if str(item).strip()
            ]
            normalized_outputs[normalized_name] = {
                "trigger_fields": normalized_trigger_fields,
                "selector_examples": selector_examples,
            }
        return {"outputs": normalized_outputs}

    def _normalize_manifest_ui(
        self,
        raw_ui: Any,
        *,
        known_field_names: set[str],
        known_output_names: set[str],
    ) -> Dict[str, Any]:
        if raw_ui in (None, ""):
            return {
                "playground": {
                    "fields": {},
                    "result": {
                        "artifact_views": _deepcopy(DEFAULT_ARTIFACT_VIEWS),
                        "show_result_json": True,
                        "show_logs": True,
                    },
                },
                "constructor": {"outputs": {}},
            }
        if not isinstance(raw_ui, dict):
            raise ValidationError("ui must be an object")

        playground = raw_ui.get("playground") or {}
        if not isinstance(playground, dict):
            raise ValidationError("ui.playground must be an object")

        raw_field_ui = playground.get("fields") or {}
        if not isinstance(raw_field_ui, dict):
            raise ValidationError("ui.playground.fields must be an object")

        normalized_fields: Dict[str, Any] = {}
        for field_name, config in raw_field_ui.items():
            normalized_name = str(field_name or "").strip()
            if not normalized_name or normalized_name not in known_field_names:
                raise ValidationError(
                    "ui.playground.fields contains an unknown field reference",
                    details={"field": normalized_name},
                )
            if not isinstance(config, dict):
                raise ValidationError(
                    "Field UI configuration must be an object",
                    details={"field": normalized_name},
                )
            widget = str(config.get("widget") or "").strip()
            if widget and widget not in ALLOWED_PLAYGROUND_WIDGETS:
                raise ValidationError(
                    "Unsupported Playground widget",
                    details={"field": normalized_name, "widget": widget},
                )
            rows_value = config.get("rows")
            rows = None
            if rows_value is not None and str(rows_value).strip() != "":
                rows = int(rows_value)
                if rows <= 0:
                    raise ValidationError("Field UI rows must be positive", details={"field": normalized_name})
            accept_extensions = [
                extension if extension.startswith(".") else f".{extension}"
                for extension in [
                    str(item).strip().lower()
                    for item in _listify(config.get("accept_extensions"))
                    if str(item).strip()
                ]
            ]
            accept_mime_types = [str(item).strip() for item in _listify(config.get("accept_mime_types")) if str(item).strip()]
            mutex_with = [str(item).strip() for item in _listify(config.get("mutex_with")) if str(item).strip()]
            for target in mutex_with:
                if target not in known_field_names:
                    raise ValidationError(
                        "Field UI mutex_with references an unknown field",
                        details={"field": normalized_name, "target_field": target},
                    )
            normalized_fields[normalized_name] = {
                "widget": widget or None,
                "placeholder": str(config.get("placeholder") or "").strip() or None,
                "help_text": str(config.get("help_text") or "").strip() or None,
                "rows": rows,
                "path_source": str(config.get("path_source") or "").strip() or None,
                "preview_kind": str(config.get("preview_kind") or "").strip() or None,
                "accept_extensions": accept_extensions,
                "accept_mime_types": accept_mime_types,
                "mutex_with": mutex_with,
                "visible_if": self._normalize_manifest_visibility_condition(
                    config.get("visible_if"),
                    known_field_names=known_field_names,
                    owner_field=normalized_name,
                ),
            }

        raw_result = playground.get("result") or {}
        if not isinstance(raw_result, dict):
            raise ValidationError("ui.playground.result must be an object")

        artifact_views = raw_result.get("artifact_views") or _deepcopy(DEFAULT_ARTIFACT_VIEWS)
        if not isinstance(artifact_views, list):
            raise ValidationError("ui.playground.result.artifact_views must be an array")
        normalized_artifact_views: List[Dict[str, Any]] = []
        for index, entry in enumerate(artifact_views):
            if not isinstance(entry, dict):
                raise ValidationError("Artifact view entries must be objects", details={"index": index})
            widget = str(entry.get("widget") or "file_download").strip()
            if widget not in {"image_gallery", "model_viewer", "file_download"}:
                raise ValidationError("Unsupported artifact view widget", details={"widget": widget, "index": index})
            extensions = [
                value if value.startswith(".") else f".{value}"
                for value in [
                    str(item).strip().lower()
                    for item in _listify(entry.get("extensions"))
                    if str(item).strip()
                ]
            ]
            normalized_artifact_views.append(
                {
                    "id": str(entry.get("id") or f"artifact-view-{index + 1}").strip(),
                    "label": str(entry.get("label") or "Artifacts").strip(),
                    "widget": widget,
                    "extensions": extensions,
                }
            )

        constructor = raw_ui.get("constructor") or {}
        if not isinstance(constructor, dict):
            raise ValidationError("ui.constructor must be an object")

        return {
            "playground": {
                "fields": normalized_fields,
                "result": {
                    "artifact_views": normalized_artifact_views,
                    "show_result_json": bool(raw_result.get("show_result_json", True)),
                    "show_logs": bool(raw_result.get("show_logs", True)),
                },
            },
            "constructor": self._normalize_manifest_constructor_output_ui(
                constructor.get("outputs"),
                known_output_names=known_output_names,
            ),
        }

    @staticmethod
    def _get_supported_source_kinds(field_type: str) -> List[str]:
        return _deepcopy(
            CONSTRUCTOR_SUPPORTED_SOURCE_KINDS_BY_TYPE.get(
                field_type,
                ["literal", "artifact_json_value", "record_metadata_field"],
            )
        )

    def _build_constructor_schema_field(
        self,
        field: Dict[str, Any],
        *,
        kind: str,
        group: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_field = _deepcopy(field)
        field_type = str(normalized_field.get("type") or "string").strip().lower()
        return {
            "name": normalized_field["name"],
            "label": normalized_field.get("label") or normalized_field["name"],
            "description": normalized_field.get("description") or "",
            "kind": kind,
            "type": field_type,
            "widget": CONSTRUCTOR_WIDGET_BY_TYPE.get(field_type, "text_input"),
            "required": bool(normalized_field.get("required", False)),
            "default": _deepcopy(normalized_field.get("default")),
            "options": _deepcopy(normalized_field.get("options") or []),
            "group_title": str((group or {}).get("title") or "").strip() or None,
            "group_description": str((group or {}).get("description") or "").strip() or None,
            "supported_source_kinds": self._get_supported_source_kinds(field_type),
            "constraints": {
                "mutex_with": [str(item).strip() for item in _listify(normalized_field.get("mutex_with")) if str(item).strip()],
            },
        }

    def _build_constructor_schema(self, manifest: Dict[str, Any]) -> Dict[str, Any]:
        metadata = _deepcopy(manifest.get("metadata") or {})
        constructor_ui = _deepcopy((manifest.get("ui") or {}).get("constructor") or {})
        parameter_groups: List[Dict[str, Any]] = []
        for group in manifest.get("parameter_groups") or []:
            if not isinstance(group, dict):
                continue
            fields = [
                self._build_constructor_schema_field(field, kind="parameter", group=group)
                for field in group.get("parameters") or []
                if isinstance(field, dict)
            ]
            if fields:
                parameter_groups.append(
                    {
                        "title": str(group.get("title") or "Parameters").strip(),
                        "description": str(group.get("description") or "").strip(),
                        "fields": fields,
                    }
                )
        outputs_ui = _deepcopy(constructor_ui.get("outputs") or {})
        outputs: List[Dict[str, Any]] = []
        for output in manifest.get("outputs") or []:
            if not isinstance(output, dict):
                continue
            output_name = str(output.get("name") or "").strip()
            output_ui = outputs_ui.get(output_name) or {}
            outputs.append(
                {
                    "name": output_name,
                    "label": str(output.get("label") or output_name).strip(),
                    "description": str(output.get("description") or "").strip(),
                    "type": str(output.get("type") or "").strip().lower(),
                    "default": _deepcopy(output.get("default")),
                    "trigger_fields": _deepcopy(output_ui.get("trigger_fields") or []),
                    "selector_examples": _deepcopy(output_ui.get("selector_examples") or []),
                }
            )
        return {
            "version": 1,
            "component_key": str(metadata.get("name") or "").strip(),
            "title": str(metadata.get("label") or metadata.get("name") or "").strip(),
            "description": str(metadata.get("description") or "").strip(),
            "metadata": {
                "name": str(metadata.get("name") or "").strip(),
                "label": str(metadata.get("label") or metadata.get("name") or "").strip(),
                "version": str(metadata.get("version") or "").strip(),
                "tags": [str(item) for item in _listify(metadata.get("tags")) if str(item).strip()],
                "keywords": [str(item) for item in _listify(metadata.get("keywords")) if str(item).strip()],
                "category": str(metadata.get("category") or "").strip() or None,
            },
            "inputs": [
                self._build_constructor_schema_field(field, kind="input")
                for field in manifest.get("inputs") or []
                if isinstance(field, dict)
            ],
            "outputs": outputs,
            "parameter_groups": parameter_groups,
            "profiles": [
                {
                    "id": str(profile.get("id") or "").strip(),
                    "adapter": str(profile.get("adapter") or "").strip(),
                }
                for profile in manifest.get("execution", {}).get("profiles", [])
                if isinstance(profile, dict)
            ],
        }

    def _build_playground_schema_field(
        self,
        field: Dict[str, Any],
        *,
        kind: str,
        ui_config: Optional[Dict[str, Any]] = None,
        group: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_field = _deepcopy(field)
        ui_config = _deepcopy(ui_config or {})
        field_type = str(normalized_field.get("type") or "string").strip().lower()
        widget = ui_config.get("widget") or PLAYGROUND_WIDGET_BY_TYPE.get(field_type, "text_input")
        item_type = None
        if field_type.startswith("array[") and field_type.endswith("]"):
            item_type = field_type[6:-1]

        mutex_with = sorted({
            *[str(item).strip() for item in _listify(normalized_field.get("mutex_with")) if str(item).strip()],
            *[str(item).strip() for item in _listify(ui_config.get("mutex_with")) if str(item).strip()],
        })
        path_source = ui_config.get("path_source")
        if not path_source and field_type == "dir_path":
            path_source = "directories"
        elif not path_source and field_type in {"file_path", "file_list"}:
            path_source = "files"

        accept_extensions = [str(item).strip().lower() for item in _listify(ui_config.get("accept_extensions")) if str(item).strip()]
        if not accept_extensions and widget == "image_input":
            accept_extensions = [".png", ".jpg", ".jpeg", ".webp", ".gif"]
        if not accept_extensions and widget == "model_input":
            accept_extensions = [".glb", ".gltf", ".usdz", ".obj", ".fbx", ".ply", ".stl", ".usd", ".usda", ".usdc", ".dae", ".abc"]

        preview_kind = ui_config.get("preview_kind")
        if not preview_kind and widget == "image_input":
            preview_kind = "image"
        if not preview_kind and widget == "model_input":
            preview_kind = "model"

        return {
            "name": normalized_field["name"],
            "label": normalized_field.get("label") or normalized_field["name"],
            "description": normalized_field.get("description") or "",
            "kind": kind,
            "type": field_type,
            "widget": widget,
            "required": bool(normalized_field.get("required", False)),
            "default": _deepcopy(normalized_field.get("default")),
            "options": _deepcopy(normalized_field.get("options") or []),
            "placeholder": ui_config.get("placeholder"),
            "help_text": ui_config.get("help_text"),
            "rows": ui_config.get("rows"),
            "path_source": path_source,
            "accept_extensions": accept_extensions,
            "accept_mime_types": _deepcopy(ui_config.get("accept_mime_types") or []),
            "preview_kind": preview_kind,
            "item_type": item_type,
            "group_title": str((group or {}).get("title") or "").strip() or None,
            "group_description": str((group or {}).get("description") or "").strip() or None,
            "constraints": {
                "mutex_with": mutex_with,
                "visible_if": _deepcopy(ui_config.get("visible_if")),
            },
        }

    def _build_playground_schema(self, manifest: Dict[str, Any]) -> Dict[str, Any]:
        ui = _deepcopy((manifest.get("ui") or {}).get("playground") or {})
        field_ui_map = _deepcopy(ui.get("fields") or {})
        metadata = _deepcopy(manifest.get("metadata") or {})
        outputs = manifest.get("outputs") or []
        input_fields = [
            self._build_playground_schema_field(field, kind="input", ui_config=field_ui_map.get(field.get("name")))
            for field in manifest.get("inputs") or []
            if isinstance(field, dict)
        ]
        parameter_groups: List[Dict[str, Any]] = []
        for group in manifest.get("parameter_groups") or []:
            if not isinstance(group, dict):
                continue
            fields = [
                self._build_playground_schema_field(field, kind="parameter", ui_config=field_ui_map.get(field.get("name")), group=group)
                for field in group.get("parameters") or []
                if isinstance(field, dict)
            ]
            if fields:
                parameter_groups.append(
                    {
                        "title": str(group.get("title") or "Parameters").strip(),
                        "description": str(group.get("description") or "").strip(),
                        "fields": fields,
                    }
                )
        return {
            "version": 1,
            "component_key": str(metadata.get("name") or "").strip(),
            "title": str(metadata.get("label") or metadata.get("name") or "").strip(),
            "description": str(metadata.get("description") or "").strip(),
            "metadata": {
                "name": str(metadata.get("name") or "").strip(),
                "label": str(metadata.get("label") or metadata.get("name") or "").strip(),
                "version": str(metadata.get("version") or "").strip(),
                "tags": [str(item) for item in _listify(metadata.get("tags")) if str(item).strip()],
                "keywords": [str(item) for item in _listify(metadata.get("keywords")) if str(item).strip()],
                "category": str(metadata.get("category") or "").strip() or None,
            },
            "inputs": input_fields,
            "outputs": [
                {
                    "name": str(output.get("name") or "").strip(),
                    "label": str(output.get("label") or output.get("name") or "").strip(),
                    "description": str(output.get("description") or "").strip(),
                    "type": str(output.get("type") or "").strip().lower(),
                    "default": _deepcopy(output.get("default")),
                }
                for output in outputs
                if isinstance(output, dict)
            ],
            "parameter_groups": parameter_groups,
            "result": _deepcopy(ui.get("result") or {"artifact_views": _deepcopy(DEFAULT_ARTIFACT_VIEWS), "show_result_json": True, "show_logs": True}),
        }

    def _normalize_manifest(self, manifest: Dict[str, Any], *, source_dir: Optional[Path] = None, source_type: str = "external") -> Dict[str, Any]:
        raw = _deepcopy(manifest or {})
        raw.setdefault("inputs", [])
        raw.setdefault("outputs", [])
        raw.setdefault("parameter_groups", [])
        raw.setdefault("compatibility", {})

        if "execution" not in raw or not raw.get("execution"):
            inferred = self._infer_legacy_execution(source_dir, raw)
            raw["execution"] = {"profiles": [inferred]}
            raw.setdefault("compatibility", {})
            raw["compatibility"]["legacy_inferred_execution"] = True

        all_field_names: set[str] = set()
        output_field_names: set[str] = set()
        raw["inputs"] = [
            self._normalize_manifest_field_definition(field, field_name_set=all_field_names, category="input")
            for field in raw.get("inputs") or []
        ]
        raw["outputs"] = [
            self._normalize_manifest_field_definition(field, field_name_set=output_field_names, category="output")
            for field in raw.get("outputs") or []
        ]

        normalized_groups: List[Dict[str, Any]] = []
        for group in raw.get("parameter_groups") or []:
            if not isinstance(group, dict):
                raise ValidationError("Parameter groups must be objects")
            normalized_group = _deepcopy(group)
            normalized_group["title"] = str(group.get("title") or "Parameters").strip()
            normalized_group["description"] = str(group.get("description") or "").strip()
            normalized_group["parameters"] = [
                self._normalize_manifest_field_definition(field, field_name_set=all_field_names, category="parameter")
                for field in group.get("parameters") or []
            ]
            normalized_groups.append(normalized_group)
        raw["parameter_groups"] = normalized_groups

        for field in [*raw["inputs"], *(parameter for group in raw["parameter_groups"] for parameter in group.get("parameters") or [])]:
            for mutex_target in field.get("mutex_with") or []:
                if mutex_target not in all_field_names:
                    raise ValidationError(
                        "mutex_with references an unknown field",
                        details={"field": field.get("name"), "target_field": mutex_target},
                    )

        raw["ui"] = self._normalize_manifest_ui(
            raw.get("ui"),
            known_field_names=all_field_names,
            known_output_names=output_field_names,
        )
        raw["compatibility"] = self._normalize_manifest_compatibility(
            raw.get("compatibility"),
            source_type=source_type,
        )

        validated = ComponentManifestSchema.model_validate(raw)
        normalized = validated.model_dump(mode="python")
        normalized["playground_schema"] = self._build_playground_schema(normalized)
        normalized["constructor_schema"] = self._build_constructor_schema(normalized)
        return normalized

    def _infer_legacy_execution(self, source_dir: Optional[Path], manifest: Dict[str, Any]) -> Dict[str, Any]:
        if source_dir is None:
            raise ValidationError("Missing execution section and no source directory available for inference")
        main_path = source_dir / "main.py"
        if not main_path.exists():
            raise ValidationError(
                "Missing execution section and unable to infer legacy entrypoint",
                details={"source_dir": str(source_dir)},
            )
        return {
            "id": "legacy_default",
            "adapter": "legacy_hdp_python",
            "entrypoint": ["python", "main.py"],
            "working_directory": ".",
            "input_bindings": [],
            "output_collection": [],
        }

    def _normalize_pipeline_config(self, pipeline_definition: Dict[str, Any], *, identifier: Optional[str] = None) -> Dict[str, Any]:
        raw = _deepcopy(pipeline_definition or {})
        for transport_field in ("activate", "request_id"):
            raw.pop(transport_field, None)
        raw["identifier"] = identifier or raw.get("identifier") or PREDEFINED_PIPELINE_ID
        raw.setdefault("name", raw["identifier"])
        raw.setdefault("description", "")
        raw.setdefault("status", "active")
        raw.setdefault("modality", "3D Model")
        raw.setdefault("processingMode", "root")
        raw.setdefault("version", "1.0.0")
        raw.setdefault("tags", [])
        raw.setdefault("steps", [])

        scope_overrides = {
            "fast_renderer": "batch",
            "any_to_usdz": "record",
            "input_file_classification": "record",
            "zenodo_draft": "record",
            "lod_generation": "record",
            "zenodo_upload": "record",
        }
        component_map = {
            "fast_renderer": "fast_renderer",
            "any_to_usdz": "any_to_usdz",
            "input_file_classification": "input_file_classification",
            "zenodo_draft": "zenodo_draft",
            "lod_generation": "lod_generation",
            "zenodo_upload": "zenodo_upload",
        }

        normalized_steps: List[Dict[str, Any]] = []
        for step in raw.get("steps", []):
            normalized_step = _deepcopy(step)
            normalized_step.setdefault("name", normalized_step.get("id", "step"))
            normalized_step.setdefault("description", "")
            normalized_step.setdefault("enabled", True)
            normalized_step.setdefault("parameters", {})
            normalized_step.setdefault("input_bindings", [])
            normalized_step.setdefault("parameter_bindings", [])
            normalized_step.setdefault("output_actions", [])
            normalized_step.setdefault("triggers", None)
            normalized_step.setdefault("component_ref", component_map.get(normalized_step.get("id"), normalized_step.get("id")))
            normalized_step.setdefault("execution_profile_ref", "builtin_default")
            normalized_step.setdefault("scope", scope_overrides.get(normalized_step.get("id"), "record"))
            if not normalized_step.get("component_version"):
                version_id = self._resolve_component_version_id(normalized_step["component_ref"])
                component_version = db.session.get(ComponentVersion, version_id) if version_id else None
                if component_version:
                    normalized_step["component_version"] = component_version.version
            if normalized_step.get("component_version"):
                component_version = self._step_component_version(normalized_step)
                normalized_step.setdefault("component_manifest_hash", component_version.manifest_hash)
            normalized_steps.append(normalized_step)
        raw["steps"] = normalized_steps
        validated = PipelineDefinitionSchema.model_validate(raw)
        return validated.model_dump(mode="python")

    @staticmethod
    def _field_definition_map(fields: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        return {
            str(field.get("name") or "").strip(): field
            for field in fields
            if isinstance(field, dict) and str(field.get("name") or "").strip()
        }

    def _component_parameter_definition_map(self, manifest: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        definitions: Dict[str, Dict[str, Any]] = {}
        for group in manifest.get("parameter_groups") or []:
            if not isinstance(group, dict):
                continue
            definitions.update(self._field_definition_map(group.get("parameters") or []))
        return definitions

    def _binding_type_is_compatible(self, binding_type: str, target_type: str) -> bool:
        if binding_type == "pipeline_source_file":
            return target_type == "file_path"
        if binding_type == "pipeline_source_files":
            return target_type == "file_list"
        if binding_type == "pipeline_source_directory":
            return target_type == "dir_path"
        if binding_type == "artifact_file":
            return target_type in {"file_path", "file_list"}
        if binding_type == "artifact_directory":
            return target_type in {"dir_path", "file_list"}
        if binding_type == "artifact_json_value":
            return target_type not in {"file_path", "dir_path", "file_list"}
        if binding_type in {"literal", "record_metadata_field"}:
            return target_type not in {"file_path", "dir_path", "file_list"}
        if binding_type == "secret_ref":
            return target_type in {"string", "text", "json"}
        return False

    def _source_output_binding_is_compatible(self, binding_type: str, output_type: str) -> bool:
        if binding_type == "artifact_file":
            return output_type == "file_path"
        if binding_type == "artifact_directory":
            return output_type == "dir_path"
        if binding_type == "artifact_json_value":
            return output_type in {"json", "file_path"}
        return True

    def _collect_pipeline_validation_errors(self, pipeline_definition: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        seen_step_ids = set()
        duplicate_step_ids = set()
        for step in pipeline_definition.get("steps", []):
            step_id = str(step.get("id") or "").strip()
            if not step_id:
                continue
            if step_id in seen_step_ids:
                duplicate_step_ids.add(step_id)
            seen_step_ids.add(step_id)
        for duplicate_step_id in sorted(duplicate_step_ids):
            errors.append(f"Duplicate step id detected: {duplicate_step_id}")

        step_order = {
            step["id"]: index
            for index, step in enumerate(pipeline_definition.get("steps", []))
            if isinstance(step, dict) and step.get("id")
        }
        manifests_by_step: Dict[str, Dict[str, Any]] = {}
        metadata_target_paths = {
            entry["path"]
            for entry in self._flatten_metadata_target_paths()
            if isinstance(entry, dict) and str(entry.get("path") or "").strip()
        }

        for step in pipeline_definition.get("steps", []):
            component_key = step.get("component_ref") or step.get("id")
            try:
                manifest = self._get_component_manifest_by_key(component_key, step.get("component_version"))
            except ValidationError as exc:
                errors.append(f"Step '{step.get('id')}' references an unavailable component '{component_key}': {exc}")
                continue
            manifests_by_step[step["id"]] = manifest
            profile = next((item for item in manifest.get("execution", {}).get("profiles", []) if item.get("id") == step.get("execution_profile_ref")), {})
            if step.get("enabled", True):
                if profile.get("adapter") == "container_cli" and profile.get("runtime") == "docker":
                    if not re.fullmatch(r"(?:sha256:|.+@sha256:)[a-fA-F0-9]{64}", str(profile.get("image") or "")):
                        errors.append(f"Step '{step['id']}' uses a mutable Docker image. Install this component through HDP Components or specify an immutable SHA-256 image digest before publishing.")
                if (profile.get("adapter") == "container_cli" and profile.get("runtime") == "singularity") or profile.get("handler") == "generic_singularity_component":
                    if not re.fullmatch(r"[a-fA-F0-9]{64}", str(profile.get("sif_sha256") or "")):
                        errors.append(f"Step '{step['id']}' has no pinned SIF checksum. Install and verify this component through HDP Components before publishing.")
            input_definitions = self._field_definition_map(manifest.get("inputs") or [])
            parameter_definitions = self._component_parameter_definition_map(manifest)
            input_types = {
                str(field.get("type") or "").strip().lower()
                for field in input_definitions.values()
                if isinstance(field, dict)
            }

            if step.get("scope") == "batch" and "file_path" in input_types and not input_types.intersection({"file_list", "dir_path"}):
                errors.append(
                    f"Step '{step['id']}' uses batch scope but component '{component_key}' has no batch-compatible 'file_list' or 'dir_path' input"
                )

            for binding_name, field_map in (
                ("input_bindings", input_definitions),
                ("parameter_bindings", parameter_definitions),
            ):
                for binding in step.get(binding_name, []):
                    target = str(binding.get("target") or "").strip()
                    target_definition = field_map.get(target)
                    if target_definition is None:
                        errors.append(f"Step '{step['id']}' binding target '{target}' is not declared by component '{component_key}'")
                        continue
                    target_type = str(target_definition.get("type") or "").strip().lower()
                    binding_type = str(binding.get("type") or "").strip()
                    if not self._binding_type_is_compatible(binding_type, target_type):
                        errors.append(
                            f"Step '{step['id']}' binding '{target}' of type '{binding_type}' is incompatible with component field type '{target_type}'"
                        )
                    if binding_type.startswith("artifact_"):
                        source_step = str(binding.get("source_step") or "").strip()
                        if not source_step or source_step not in step_order:
                            errors.append(f"Step '{step['id']}' binding '{target}' references unknown source step '{source_step}'")
                            continue
                        if step_order[source_step] >= step_order[step["id"]]:
                            errors.append(f"Step '{step['id']}' binding '{target}' must reference an earlier step, not '{source_step}'")
                            continue
                        if step.get("enabled", True) and not pipeline_definition["steps"][step_order[source_step]].get("enabled", True):
                            errors.append(f"Step '{step['id']}' binding '{target}' references disabled source step '{source_step}'. Enable it or choose another source.")
                        source_manifest = manifests_by_step.get(source_step)
                        if source_manifest is None:
                            try:
                                source_component_key = pipeline_definition["steps"][step_order[source_step]].get("component_ref") or source_step
                                source_manifest = self._get_component_manifest_by_key(source_component_key, pipeline_definition["steps"][step_order[source_step]].get("component_version"))
                                manifests_by_step[source_step] = source_manifest
                            except ValidationError:
                                source_manifest = None
                        source_output = str(binding.get("source_output") or "").strip()
                        output_definition = self._field_definition_map((source_manifest or {}).get("outputs") or []).get(source_output)
                        if output_definition is None:
                            errors.append(f"Step '{step['id']}' binding '{target}' references unknown output '{source_output}' from step '{source_step}'")
                            continue
                        output_type = str(output_definition.get("type") or "").strip().lower()
                        if not self._source_output_binding_is_compatible(binding_type, output_type):
                            errors.append(
                                f"Step '{step['id']}' binding '{target}' cannot read output '{source_output}' of type '{output_type}' from step '{source_step}'"
                            )

            for action in step.get("output_actions", []):
                action_type = str(action.get("action_type") or "").strip()
                if action_type in {"zenodo_metadata_field", "edm_metadata_field", "record_metadata_field"}:
                    target_field = str(action.get("target_field") or "").strip()
                    if target_field and target_field not in metadata_target_paths:
                        errors.append(f"Step '{step['id']}' output action target '{target_field}' is not a supported record metadata path")
                    if str(action.get("overwrite_policy") or "overwrite").strip().lower() not in SUPPORTED_ZENODO_OVERWRITE_POLICIES:
                        errors.append(f"Step '{step['id']}' output action overwrite policy is unsupported")

            triggers = step.get("triggers") or {}
            for rule in triggers.get("rules") or []:
                for condition in rule.get("conditions") or []:
                    if str(condition.get("operator") or "").strip() not in ALLOWED_CONSTRUCTOR_TRIGGER_OPERATORS:
                        errors.append(f"Step '{step['id']}' trigger rule '{rule.get('id')}' uses unsupported operator '{condition.get('operator')}'")
                    if condition.get("source_type") == "file_fact":
                        field = str(condition.get("field") or "").strip()
                        if field not in CONSTRUCTOR_FILE_FACT_FIELDS:
                            errors.append(f"Step '{step['id']}' trigger rule '{rule.get('id')}' references unsupported file fact '{field}'")
                        continue
                    if condition.get("source_type") == "classifier_output":
                        source_step = str(condition.get("source_step") or "").strip()
                        if not source_step or source_step not in step_order:
                            errors.append(f"Step '{step['id']}' trigger rule '{rule.get('id')}' references unknown classifier step '{source_step}'")
                            continue
                        if step_order[source_step] >= step_order[step["id"]]:
                            errors.append(f"Step '{step['id']}' trigger rule '{rule.get('id')}' must reference an earlier step, not '{source_step}'")
                            continue
                        if step.get("enabled", True) and not pipeline_definition["steps"][step_order[source_step]].get("enabled", True):
                            errors.append(f"Step '{step['id']}' trigger rule '{rule.get('id')}' references disabled classifier step '{source_step}'. Enable it or choose another source.")
                        source_manifest = manifests_by_step.get(source_step)
                        if source_manifest is None:
                            continue
                        if str(source_manifest.get("metadata", {}).get("name") or "").strip() != "input_file_classification":
                            errors.append(f"Step '{step['id']}' trigger rule '{rule.get('id')}' may only reference input_file_classification outputs")
                            continue
                        source_output = str(condition.get("source_output") or "").strip()
                        output_ui = (((source_manifest.get("ui") or {}).get("constructor") or {}).get("outputs") or {}).get(source_output) or {}
                        allowed_paths = {
                            str(entry.get("path") or "").strip()
                            for entry in output_ui.get("trigger_fields") or []
                            if isinstance(entry, dict)
                        }
                        selector = str(condition.get("field") or "").strip()
                        selector_path = selector if selector.startswith("$.") else f"$.{selector.lstrip('.')}"
                        if selector_path not in allowed_paths:
                            errors.append(
                                f"Step '{step['id']}' trigger rule '{rule.get('id')}' references unsupported classifier field '{selector_path}'"
                            )
        return errors

    def _collect_pipeline_validation_warnings(self, pipeline_definition: Dict[str, Any]) -> List[str]:
        warnings: List[str] = []
        for step in pipeline_definition.get("steps", []):
            step_id = step["id"]
            component_key = step.get("component_ref") or step_id
            manifest = None
            try:
                manifest = self._get_component_manifest_by_key(component_key, step.get("component_version"))
            except ValidationError:
                manifest = None
            for binding_name in ("input_bindings", "parameter_bindings"):
                for binding in step.get(binding_name, []):
                    if binding.get("type") == "artifact_json_value" and not binding.get("selector"):
                        warnings.append(
                            f"Binding '{binding['target']}' on step '{step_id}' reads JSON output without a selector"
                        )
            for action in step.get("output_actions", []):
                action_type = str(action.get("action_type") or "").strip()
                if action_type and action_type not in SUPPORTED_OUTPUT_ACTION_TYPES:
                    warnings.append(
                        f"Output action '{action_type}' on step '{step_id}' is not currently executed by the native runtime"
                    )
                transform = str(action.get("transform") or "").strip()
                if transform and transform not in SUPPORTED_OUTPUT_ACTION_TRANSFORMS:
                    warnings.append(
                        f"Output action transform '{transform}' on step '{step_id}' is not currently supported"
                    )
            if step.get("scope") == "batch" and isinstance(manifest, dict):
                input_definitions = self._field_definition_map(manifest.get("inputs") or [])
                explicit_bindings = {
                    str(binding.get("target") or "").strip()
                    for binding in step.get("input_bindings", [])
                    if isinstance(binding, dict)
                }
                for field_name, definition in input_definitions.items():
                    if str(definition.get("type") or "").strip().lower() != "dir_path":
                        continue
                    if field_name in explicit_bindings:
                        continue
                    if _listify(definition.get("mutex_with")):
                        continue
                    warnings.append(
                        f"Step '{step_id}' leaves directory input '{field_name}' without an explicit binding; batch runtime will derive it from the common parent directory of resolved file inputs and may split or fail when a single record spans multiple directories"
                    )
        return warnings

    def _builtin_component_manifests(self) -> Dict[str, Dict[str, Any]]:
        manifests: Dict[str, Dict[str, Any]] = {}
        for component_key, spec in self._builtin_file_component_specs().items():
            manifests[component_key] = self._load_builtin_component_manifest_from_file(component_key, **spec)
        return manifests

    def _run_native_pipeline(
        self,
        config: Dict[str, Any],
        version_row: PipelineVersion,
        pipeline_run: PipelineRun,
        execution_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        from services import submission_pipeline_service as legacy

        record_info_list = execution_context["record_info_list"]
        total_records = len(record_info_list)
        outputs_dir = execution_context["outputs_dir"]
        progress_callback = execution_context.get("progress_callback")
        pipeline_timings = execution_context["pipeline_timings"]

        configured_steps = config.get("steps", [])
        step_overrides = execution_context.get("steps_map") or {}
        merged_steps_map: Dict[str, Dict[str, Any]] = {}
        enabled_steps: List[Dict[str, Any]] = []
        for step in configured_steps:
            merged_step = copy.deepcopy(step)
            override = step_overrides.get(step.get("id")) if isinstance(step_overrides, dict) else None
            if isinstance(override, dict):
                merged_step.update({key: value for key, value in override.items() if key != "parameters"})
                merged_step["parameters"] = {
                    **dict(step.get("parameters") or {}),
                    **dict(override.get("parameters") or {}),
                }
            merged_steps_map[merged_step["id"]] = merged_step
            if merged_step.get("enabled", True):
                enabled_steps.append(merged_step)
        execution_context["steps_map"] = merged_steps_map

        record_contexts: List[Dict[str, Any]] = []
        record_resolution_by_record_id = execution_context.get("record_resolution_by_record_id") or {}
        for index, (record_id, file_path, file_zenodo_metadata) in enumerate(record_info_list, start=1):
            filename = os.path.basename(file_path)
            specific_output_dir = os.path.join(outputs_dir, f"record-{record_id}", os.path.splitext(filename)[0])
            os.makedirs(specific_output_dir, exist_ok=True)
            record_contexts.append(
                {
                    "record_id": record_id,
                    "file_path": file_path,
                    "filename": filename,
                    "file_zenodo_metadata": copy.deepcopy(file_zenodo_metadata),
                    "generated_files": [],
                    "step_outputs": {
                        "__file_facts__": {
                            "classification_json": self._classify_input_file(file_path),
                        }
                    },
                    "specific_output_dir": specific_output_dir,
                    "record_status": {
                        "record_id": record_id,
                        "file_path": file_path,
                        "render": {"success": False, "status": "skipped"},
                        "usdz": {"success": False, "status": "skipped"},
                        "edm": {"success": False, "status": "skipped"},
                        "iiif": {"success": False, "status": "skipped"},
                        "mets": {"success": False, "status": "skipped"},
                        "zenodo": {"draft_success": False, "upload_success": False},
                        "publishing_context": copy.deepcopy(execution_context.get("publishing_context") or {}),
                        "step_results": {},
                        "warnings": [],
                    },
                    "record_timings": {
                        "record_id": record_id,
                        "file_path": file_path,
                        "steps": {},
                        "subprocesses": {},
                    },
                    "current_zenodo_draft_record_id": None,
                    "draft_result": {},
                    "record_resolution": copy.deepcopy(record_resolution_by_record_id.get(int(record_id)) or {}),
                    "index": index,
                    "total_records": total_records,
                }
            )

        processed_results: List[Dict[str, Any]] = []
        converter_failures: List[Dict[str, Any]] = []
        failed_count = 0
        processed_count = 0
        successful_count = 0

        for step in enabled_steps:
            if step.get("scope") == "batch":
                self._execute_batch_step(step, version_row, pipeline_run, execution_context, record_contexts)
                continue
            for record_context in record_contexts:
                try:
                    trigger_resolution = self._resolve_step_trigger(step, record_context)
                    if trigger_resolution["action"] != "run":
                        self._mark_step_skipped(step, record_context, matched_rule_id=trigger_resolution.get("matched_rule_id"))
                        continue
                    self._execute_record_step(
                        step,
                        version_row,
                        pipeline_run,
                        execution_context,
                        record_context,
                        parameter_overrides=trigger_resolution.get("parameter_overrides") or {},
                        matched_rule_id=trigger_resolution.get("matched_rule_id"),
                    )
                except FileProcessingError as exc:
                    record_context["record_status"]["error"] = legacy._format_pipeline_exception(exc)
                    if execution_context.get("abort_on_critical_error"):
                        raise
                except Exception as exc:
                    record_context["record_status"]["error"] = legacy._format_pipeline_exception(exc)

        zenodo_upload_step = execution_context["steps_map"].get("zenodo_upload")
        for record_context in record_contexts:
            filename = record_context["filename"]
            legacy._emit_progress(
                progress_callback,
                {
                    "current_stage": "record_completed",
                    "status_message": f"Finished {filename}",
                    "current_file_name": filename,
                    "current_index": record_context["index"],
                    "total_files": total_records,
                    "processed_count": processed_count,
                    "failed_count": failed_count,
                    "zenodo_draft_record_id": record_context["current_zenodo_draft_record_id"],
                },
            )
            processed_count += 1
            record_context["record_timings"]["total"] = sum(
                float(value or 0)
                for value in (record_context["record_timings"].get("steps") or {}).values()
            )
            record_context["record_timings"]["subprocesses"]["record_total"] = {
                "full_record": record_context["record_timings"]["total"]
            }
            pipeline_timings["record_processing"].append(record_context["record_timings"])
            processed_results.append(record_context["record_status"])

            if record_context["record_status"]["usdz"].get("status") == "failed":
                converter_failures.append(
                    {
                        "record_id": record_context["record_id"],
                        "file_path": record_context["file_path"],
                        "file_name": filename,
                        "error": record_context["record_status"]["usdz"].get("error"),
                        "error_code": record_context["record_status"]["usdz"].get("error_code"),
                        "hint": record_context["record_status"]["usdz"].get("hint"),
                        "details": record_context["record_status"]["usdz"].get("details"),
                    }
                )

            if record_context["record_status"].get("error"):
                failed_count += 1
            elif zenodo_upload_step is None or not zenodo_upload_step.get("enabled", True) or record_context["record_status"]["zenodo"].get("upload_success"):
                successful_count += 1

        failed_records = [
            {
                "record_id": result.get("record_id"),
                "file_path": result.get("file_path"),
                "error": result.get("error"),
                "warnings": result.get("warnings", []),
                "zenodo": result.get("zenodo", {}),
            }
            for result in processed_results
            if result.get("error")
        ]
        overall_success = len(failed_records) == 0
        exec_data: Dict[str, Any] = {
            "success": overall_success,
            "details": processed_results,
            "summary": {
                "total_records": total_records,
                "processed_count": processed_count,
                "successful_count": successful_count,
                "failed_count": failed_count,
                "skipped_count": len(execution_context.get("skipped_files", [])),
                "converter_failed_count": len(converter_failures),
            },
        }
        if failed_records:
            exec_data["failed_records"] = failed_records
            exec_data["error"] = f"{len(failed_records)} record(s) failed during pipeline execution."
        if execution_context.get("skipped_files"):
            exec_data["skipped_files"] = execution_context["skipped_files"]
        if converter_failures:
            exec_data["converter_failures"] = converter_failures
            exec_data["warnings"] = [entry["error"] for entry in converter_failures if entry.get("error")]
        return exec_data

    def _component_can_use_hpc_link(self, component_key: str) -> bool:
        return hpc_required_component(component_key)

    def _has_active_hpc_allocation(self, session_id: Any) -> bool:
        try:
            if session_id in (None, "") or not hasattr(current_app, "hpc_allocation_service"):
                return False
            return current_app.hpc_allocation_service.get_active_for_session(int(session_id)) is not None
        except Exception:
            return False

    def _should_route_component_to_hpc_link(self, component_key: str, session_id: Any) -> bool:
        if not self._component_can_use_hpc_link(component_key):
            return False
        try:
            config = current_app.hpc_allocation_service.get_or_create_config()
            if not config.enabled:
                return False
        except Exception:
            return False
        return self._has_active_hpc_allocation(session_id)

    def _local_component_health(self, component_key: str) -> bool:
        try:
            if component_key == "fast_renderer":
                return bool(current_app.fast_renderer_service.check_health())
            if component_key == "any_to_usdz":
                return bool(current_app.any_to_usdz_service.check_health())
        except Exception:
            return False
        return True

    def _ensure_component_runtime_available(
        self,
        component_key: str,
        execution_context: Dict[str, Any],
        *,
        hpc_only: bool = False,
    ) -> None:
        if not hpc_only and not self._component_can_use_hpc_link(component_key):
            return
        if self._has_active_hpc_allocation(execution_context.get("db_session_id")):
            return
        hpc_link_available = False
        try:
            config = current_app.hpc_allocation_service.get_or_create_config()
            hpc_link_available = bool(config.enabled and config.base_url)
        except Exception:
            pass

        runtime = component_runtime_status(
            component_key,
            current_app,
            active_hpc_allocation=False,
            hpc_link_available=hpc_link_available,
            can_allocate_hpc=hpc_link_available,
            hpc_only=hpc_only,
        )
        if runtime.get("status") == "local_allowed":
            return
        message = str(runtime.get("message") or hpc_required_message(component_key))
        if runtime.get("status") in {"hpc_required", "hpc_only"}:
            message = f"{message} Request an active HPC-Link allocation before starting this pipeline."
        raise FileProcessingError(message)

    @staticmethod
    def _profile_payload(profile: ComponentProfile, *, component_key: str | None = None) -> Dict[str, Any]:
        payload = {
            **_json_loads(profile.config_json, {}),
            "adapter": profile.adapter,
            "entrypoint": _json_loads(profile.entrypoint_json, []),
        }
        if component_key:
            payload.setdefault("handler", component_key)
            payload.setdefault("component_key", component_key)
        return payload

    def _mark_step_skipped(
        self,
        step: Dict[str, Any],
        record_context: Dict[str, Any],
        *,
        matched_rule_id: Optional[str] = None,
    ) -> None:
        step_result = {
            "success": True,
            "status": "skipped",
            "matched_rule_id": matched_rule_id,
        }
        record_context["record_status"]["step_results"][step["id"]] = step_result
        component_key = step.get("component_ref") or step.get("id")
        if component_key == "fast_renderer":
            record_context["record_status"]["render"] = {"success": True, "status": "skipped"}
        elif component_key == "any_to_usdz":
            record_context["record_status"]["usdz"] = {"success": True, "status": "skipped"}

    def _execute_batch_step(
        self,
        step: Dict[str, Any],
        version_row: PipelineVersion,
        pipeline_run: PipelineRun,
        execution_context: Dict[str, Any],
        record_contexts: List[Dict[str, Any]],
    ) -> None:
        component_key = step.get("component_ref") or step["id"]
        component_definition = ComponentDefinition.query.filter_by(key=component_key).first()
        if component_definition is None:
            raise FileProcessingError(f"Component '{component_key}' is not registered")
        self._step_component_version(step)
        persisted_step = self._find_pipeline_step(version_row, step["id"])
        component_version = db.session.get(ComponentVersion, persisted_step.component_version_id) if persisted_step and persisted_step.component_version_id else self._step_component_version(step)
        if component_version is None:
            raise FileProcessingError(f"Component '{component_key}' has no active version")
        manifest = _json_loads(component_version.manifest_json, {})
        input_definitions = self._field_definition_map(manifest.get("inputs") or [])
        file_input_names = {
            name
            for name, definition in input_definitions.items()
            if str(definition.get("type") or "").strip().lower() in {"file_path", "file_list", "dir_path"}
        }
        profile = self._get_profile_row(component_version, step.get("execution_profile_ref"))
        pipeline_step_row = self._find_pipeline_step(version_row, step["id"])

        buckets: Dict[str, Dict[str, Any]] = {}
        for record_context in record_contexts:
            trigger_resolution = self._resolve_step_trigger(step, record_context)
            if trigger_resolution["action"] != "run":
                self._mark_step_skipped(step, record_context, matched_rule_id=trigger_resolution.get("matched_rule_id"))
                continue
            resolved_inputs, resolved_parameters = self._resolve_step_bindings(step, record_context, execution_context)
            resolved_inputs = self._apply_default_input_bindings(
                manifest.get("inputs") or [],
                resolved_inputs,
                record_context,
                execution_context,
            )
            effective_parameters = {
                **(step.get("parameters") or {}),
                **resolved_parameters,
                **_deepcopy(trigger_resolution.get("parameter_overrides") or {}),
            }
            bucket_signature_inputs, file_inputs, source_files = self._prepare_batch_input_state(input_definitions, resolved_inputs)
            bucket_key = _hash_payload({"inputs": bucket_signature_inputs, "parameters": effective_parameters})
            bucket = buckets.setdefault(
                bucket_key,
                {
                    "inputs": bucket_signature_inputs,
                    "parameters": effective_parameters,
                    "records": [],
                    "source_files": [],
                    "file_inputs": {},
                    "matched_rule_ids": {},
                },
            )
            bucket["records"].append(record_context)
            bucket["matched_rule_ids"][record_context["file_path"]] = trigger_resolution.get("matched_rule_id")
            for field_name, state in file_inputs.items():
                bucket_state = bucket["file_inputs"].setdefault(field_name, _deepcopy(state))
                field_type = state.get("type")
                if field_type == "file_list":
                    values = bucket_state.setdefault("values", [])
                    for file_path in state.get("values") or []:
                        if file_path not in values:
                            values.append(file_path)
                        if file_path not in bucket["source_files"]:
                            bucket["source_files"].append(file_path)
                elif field_type == "file_path":
                    value = state.get("value")
                    if value and not bucket_state.get("value"):
                        bucket_state["value"] = value
                    if value and value not in bucket["source_files"]:
                        bucket["source_files"].append(value)
                elif field_type == "dir_path":
                    value = state.get("value")
                    if value and not bucket_state.get("value"):
                        bucket_state["value"] = value

        adapter_name = profile.adapter
        self._ensure_component_runtime_available(
            component_key,
            execution_context,
            hpc_only=adapter_name == "hpc_link",
        )
        if self._should_route_component_to_hpc_link(component_key, execution_context.get("db_session_id")):
            adapter_name = "hpc_link"
        adapter = self._adapter_registry.get(adapter_name)
        if adapter is None:
            raise ValidationError("Unsupported adapter", details={"adapter": adapter_name})

        for bucket in buckets.values():
            request_inputs = _deepcopy(bucket["inputs"])
            for field_name in file_input_names:
                field_definition = input_definitions.get(field_name, {}) or {}
                field_type = field_definition.get("type")
                file_input_state = bucket["file_inputs"].get(field_name) or {}
                if field_type == "file_list":
                    request_inputs[field_name] = _deepcopy(file_input_state.get("values") or [])
                elif field_type == "file_path":
                    value = file_input_state.get("value")
                    if value:
                        request_inputs[field_name] = value
                elif field_type == "dir_path":
                    value = file_input_state.get("value") or self._common_parent_directory(bucket["source_files"])
                    if value:
                        request_inputs[field_name] = value
                    elif file_input_state.get("unresolved") and field_definition.get("required") is True:
                        directories = ", ".join(file_input_state.get("candidate_directories") or [])
                        raise FileProcessingError(
                            f"Step '{step['id']}' could not resolve required directory input '{field_name}' to a single directory for batch execution. Candidate directories: {directories}"
                        )

            step_run = self._create_step_run(
                pipeline_run,
                pipeline_step_row,
                scope="batch",
                record_id=None,
                record_path=None,
                command=["builtin_webhdp", component_key, "batch"],
            )
            request = AdapterExecutionRequest(
                step_id=step["id"],
                profile={**self._profile_payload(profile, component_key=component_key), "adapter": adapter_name},
                workdir=execution_context["outputs_dir"],
                inputs=request_inputs,
                parameters=_deepcopy(bucket["parameters"]),
                metadata={
                    "execution_context": {**execution_context, "bucket_source_files": _deepcopy(bucket["source_files"])},
                    "step": step,
                    "pipeline_run_id": pipeline_run.public_id,
                    "component_manifest": manifest,
                    "batch_records": [{"record_id": row["record_id"], "file_path": row["file_path"]} for row in bucket["records"]],
                },
            )
            result = adapter.execute(request)
            self._finish_step_run(step_run, result, result.get("error"), result.get("command"))
            per_record_results = result.get("record_results") if isinstance(result.get("record_results"), dict) else {}

            for record_context in bucket["records"]:
                file_path = record_context["file_path"]
                per_record_result = _deepcopy(per_record_results.get(file_path) or {
                    "success": result.get("success", True),
                    "status": result.get("status", "completed" if result.get("success", True) else "failed"),
                    "error": result.get("error"),
                    "outputs": {},
                    "artifacts": [],
                })
                if adapter_name == "hpc_link":
                    self._materialize_hpc_artifacts(
                        execution_context,
                        record_context,
                        pipeline_run,
                        step_run,
                        component_key,
                        per_record_result,
                    )
                record_context["record_status"]["step_results"][step["id"]] = {
                    "success": per_record_result.get("success", True),
                    "status": per_record_result.get("status", "completed" if per_record_result.get("success", True) else "failed"),
                    "error": per_record_result.get("error"),
                    "matched_rule_id": bucket["matched_rule_ids"].get(file_path),
                }
                if component_key == "fast_renderer":
                    record_context["record_status"]["render"] = _deepcopy(per_record_result.get("render_status") or per_record_result)
                    render_status = record_context["record_status"]["render"]
                    render_subprocess_timings = render_status.get("subprocess_timings") or {}
                    render_duration = render_status.get("duration")
                    if render_duration in (None, "") and isinstance(render_subprocess_timings, dict):
                        render_duration = render_subprocess_timings.get("total")
                    if render_duration not in (None, ""):
                        record_context["record_timings"]["steps"]["render"] = render_duration
                    if render_subprocess_timings:
                        record_context["record_timings"]["subprocesses"]["render"] = _deepcopy(render_subprocess_timings)
                    discovered_outputs = _listify((per_record_result.get("outputs") or {}).get("render_outputs"))
                    if discovered_outputs:
                        self._register_record_files(
                            execution_context,
                            record_context["record_id"],
                            [str(path) for path in discovered_outputs if str(path).strip()],
                            "render",
                            "fast_renderer",
                        )
                        record_context["generated_files"].extend(
                            [path for path in discovered_outputs if path not in record_context["generated_files"]]
                        )
                applied_actions = self._apply_output_actions(step, record_context, per_record_result)
                if applied_actions:
                    per_record_result.setdefault("post_output_actions", applied_actions)
                self._record_step_outputs(pipeline_run, step_run, step["id"], record_context, per_record_result)
                if not per_record_result.get("success", True) and not record_context["record_status"].get("error"):
                    record_context["record_status"]["error"] = (
                        per_record_result.get("error") or f"Step '{step['id']}' failed during pipeline execution."
                    )

    def _execute_record_step(
        self,
        step: Dict[str, Any],
        version_row: PipelineVersion,
        pipeline_run: PipelineRun,
        execution_context: Dict[str, Any],
        record_context: Dict[str, Any],
        *,
        parameter_overrides: Optional[Dict[str, Any]] = None,
        matched_rule_id: Optional[str] = None,
    ) -> None:
        component_key = step.get("component_ref") or step["id"]
        component_definition = ComponentDefinition.query.filter_by(key=component_key).first()
        if component_definition is None:
            raise FileProcessingError(f"Component '{component_key}' is not registered")
        self._step_component_version(step)
        persisted_step = self._find_pipeline_step(version_row, step["id"])
        component_version = db.session.get(ComponentVersion, persisted_step.component_version_id) if persisted_step and persisted_step.component_version_id else self._step_component_version(step)
        if component_version is None:
            raise FileProcessingError(f"Component '{component_key}' has no active version")
        profile = self._get_profile_row(component_version, step.get("execution_profile_ref"))
        pipeline_step_row = self._find_pipeline_step(version_row, step["id"])
        step_run = self._create_step_run(
            pipeline_run,
            pipeline_step_row,
            scope=step.get("scope", "record"),
            record_id=record_context["record_id"],
            record_path=record_context["file_path"],
            command=["builtin_webhdp", component_key],
        )

        resolved_inputs, resolved_parameters = self._resolve_step_bindings(step, record_context, execution_context)
        manifest = _json_loads(component_version.manifest_json, {})
        resolved_inputs = self._apply_default_input_bindings(
            manifest.get("inputs") or [],
            resolved_inputs,
            record_context,
            execution_context,
        )
        resolved_parameters = {
            **step.get("parameters", {}),
            **resolved_parameters,
            **_deepcopy(parameter_overrides or {}),
        }
        adapter_name = profile.adapter
        self._ensure_component_runtime_available(
            component_key,
            execution_context,
            hpc_only=adapter_name == "hpc_link",
        )
        if self._should_route_component_to_hpc_link(component_key, execution_context.get("db_session_id")):
            adapter_name = "hpc_link"

        request = AdapterExecutionRequest(
            step_id=step["id"],
            profile={**self._profile_payload(profile, component_key=component_key), "adapter": adapter_name},
            workdir=record_context["specific_output_dir"],
            inputs=resolved_inputs,
            parameters=resolved_parameters,
            metadata={
                "record_context": record_context,
                "execution_context": execution_context,
                "step": step,
                "pipeline_run_id": pipeline_run.public_id,
                "component_manifest": manifest,
            },
        )
        adapter = self._adapter_registry.get(adapter_name)
        if adapter is None:
            raise ValidationError("Unsupported adapter", details={"adapter": adapter_name})
        result = adapter.execute(request)
        materialized_paths: List[str] = []
        if adapter_name == "hpc_link":
            materialized_paths = self._materialize_hpc_artifacts(
                execution_context,
                record_context,
                pipeline_run,
                step_run,
                component_key,
                result,
            )
            if component_key == "any_to_usdz":
                record_context["record_status"]["usdz"] = _deepcopy(result)
                duration = result.get("duration")
                if duration not in (None, ""):
                    record_context["record_timings"]["steps"]["usdz"] = duration
                timings = ((result.get("details") or {}).get("timings") if isinstance(result.get("details"), dict) else None) or result.get("timings")
                if timings:
                    record_context["record_timings"]["subprocesses"]["usdz"] = _deepcopy(timings)
                usdz_path = str(((result.get("outputs") or {}).get("output_path") or "")).strip()
                if result.get("success") and usdz_path:
                    self._register_record_files(
                        execution_context,
                        record_context["record_id"],
                        [usdz_path],
                        "any_to_usdz",
                        "converter",
                    )
                    if usdz_path not in record_context["generated_files"]:
                        record_context["generated_files"].append(usdz_path)
                elif result.get("success") and materialized_paths:
                    self._register_record_files(
                        execution_context,
                        record_context["record_id"],
                        materialized_paths,
                        "any_to_usdz",
                        "converter",
                    )
                    for path in materialized_paths:
                        if path not in record_context["generated_files"]:
                            record_context["generated_files"].append(path)
        record_context["record_status"]["step_results"][step["id"]] = {
            "success": result.get("success", True),
            "status": result.get("status", "completed" if result.get("success", True) else "failed"),
            "error": result.get("error"),
            "matched_rule_id": matched_rule_id,
        }
        applied_actions = self._apply_output_actions(step, record_context, result)
        if applied_actions:
            result.setdefault("post_output_actions", applied_actions)
        self._finish_step_run(step_run, result, result.get("error"), result.get("command"))
        self._record_step_outputs(pipeline_run, step_run, step["id"], record_context, result)
        if not result.get("success", True):
            if step["id"] in {"zenodo_draft", "zenodo_upload"}:
                record_context["record_status"]["error"] = result.get("error")
            elif not record_context["record_status"].get("error"):
                record_context["record_status"]["error"] = (
                    result.get("error") or f"Step '{step['id']}' failed during pipeline execution."
                )

    def _resolve_step_bindings(
        self,
        step: Dict[str, Any],
        record_context: Dict[str, Any],
        execution_context: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        inputs: Dict[str, Any] = {}
        parameters: Dict[str, Any] = {}
        for binding in step.get("input_bindings", []):
            inputs[binding["target"]] = self._resolve_binding_value(binding, record_context, execution_context)
        for binding in step.get("parameter_bindings", []):
            parameters[binding["target"]] = self._resolve_binding_value(binding, record_context, execution_context)
        return inputs, parameters

    def _extract_selector_value(self, value: Any, selector: Optional[str]) -> Any:
        if selector is None or str(selector).strip() == "":
            return value
        payload = value
        if isinstance(payload, str):
            normalized = payload.strip()
            if normalized and os.path.exists(normalized) and normalized.lower().endswith(".json"):
                try:
                    with open(normalized, "r", encoding="utf-8") as handle:
                        payload = json.load(handle)
                except Exception:
                    return None
        selector_text = str(selector).strip().lstrip("$.")
        if not selector_text:
            return payload
        current = payload
        for part in selector_text.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    current = current[int(part)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return current

    def _resolve_binding_value(
        self,
        binding: Dict[str, Any],
        record_context: Dict[str, Any],
        execution_context: Dict[str, Any],
    ) -> Any:
        binding_type = binding.get("type")
        if binding_type == "literal":
            return binding.get("value")
        if binding_type == "pipeline_source_file":
            return record_context.get("file_path")
        if binding_type == "pipeline_source_files":
            bucket_source_files = execution_context.get("bucket_source_files")
            if bucket_source_files:
                return _deepcopy(bucket_source_files)
            file_path = record_context.get("file_path")
            return [file_path] if file_path else []
        if binding_type == "pipeline_source_directory":
            file_path = record_context.get("file_path")
            return str(Path(file_path).parent) if file_path else None
        if binding_type == "record_metadata_field":
            return record_context["file_zenodo_metadata"].get(binding.get("metadata_field"))
        if binding_type == "secret_ref":
            return os.environ.get(binding.get("secret_ref", ""))
        if binding_type in {"artifact_file", "artifact_directory", "artifact_json_value"}:
            source_step = binding.get("source_step")
            outputs = record_context["step_outputs"].get(source_step, {})
            value = outputs.get(binding.get("source_output"))
            if binding_type == "artifact_json_value":
                return self._extract_selector_value(value, binding.get("selector"))
            return value
        return None

    def _transform_output_action_value(
        self,
        value: Any,
        action: Dict[str, Any],
    ) -> Any:
        transform = str(action.get("transform") or "identity").strip().lower()
        if transform in {"", "identity"}:
            return value
        if transform == "first":
            if isinstance(value, list):
                return value[0] if value else None
            return value
        if transform == "ensure_list":
            if value is None:
                return []
            if isinstance(value, list):
                return value
            return [value]
        if transform == "join":
            if isinstance(value, list):
                separator = str(action.get("config", {}).get("separator") or ", ")
                return separator.join(str(item) for item in value if item not in (None, ""))
            return value
        if transform == "json_stringify":
            return json.dumps(value, sort_keys=True, default=str)
        if transform == "trim":
            if isinstance(value, str):
                return value.strip()
            if isinstance(value, list):
                return [item.strip() if isinstance(item, str) else item for item in value]
            return value
        if transform == "lowercase":
            if isinstance(value, str):
                return value.lower()
            if isinstance(value, list):
                return [item.lower() if isinstance(item, str) else item for item in value]
            return value
        if transform == "uppercase":
            if isinstance(value, str):
                return value.upper()
            if isinstance(value, list):
                return [item.upper() if isinstance(item, str) else item for item in value]
            return value
        if transform == "dedupe_list":
            deduped: List[Any] = []
            seen = set()
            for item in _listify(value):
                marker = json.dumps(item, sort_keys=True, default=str)
                if marker in seen:
                    continue
                seen.add(marker)
                deduped.append(item)
            return deduped
        if transform == "length":
            if value is None:
                return 0
            if isinstance(value, (str, list, dict, tuple, set)):
                return len(value)
            return 1
        if transform == "coerce_string":
            if value is None:
                return ""
            if isinstance(value, list):
                return [str(item) for item in value]
            return str(value)
        logger.warning("Unsupported output action transform '%s'; using original value", transform)
        return value

    def _get_nested_mapping_value(self, container: Dict[str, Any], dotted_path: str) -> Any:
        current: Any = container
        for part in str(dotted_path or "").split("."):
            if not part:
                continue
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    def _set_nested_mapping_value(self, container: Dict[str, Any], dotted_path: str, value: Any) -> None:
        parts = [part for part in str(dotted_path or "").split(".") if part]
        if not parts:
            return
        current = container
        for part in parts[:-1]:
            existing = current.get(part)
            if not isinstance(existing, dict):
                existing = {}
                current[part] = existing
            current = existing
        current[parts[-1]] = value

    @staticmethod
    def _parse_collection_target_path(target_field: str) -> Tuple[Optional[str], Optional[str]]:
        match = re.match(r"^([A-Za-z0-9_]+)\[\](?:\.(.+))?$", str(target_field or "").strip())
        if not match:
            return None, None
        return match.group(1), match.group(2)

    def _coerce_collection_assignment_items(self, value: Any, leaf_path: Optional[str]) -> List[Any]:
        if not leaf_path:
            if isinstance(value, list):
                return _deepcopy(value)
            return [_deepcopy(value)]

        items: List[Any] = []
        for item in _listify(value):
            entry: Dict[str, Any] = {}
            if isinstance(item, dict) and "." not in leaf_path and leaf_path in item:
                entry = _deepcopy(item)
            else:
                self._set_nested_mapping_value(entry, leaf_path, _deepcopy(item))
            items.append(entry)
        return items

    def _apply_output_action_assignment(
        self,
        container: Dict[str, Any],
        target_field: str,
        resolved_value: Any,
        overwrite_policy: str,
    ) -> None:
        collection_root, collection_leaf = self._parse_collection_target_path(target_field)
        if collection_root:
            existing_value = container.get(collection_root)
            existing_items = existing_value if isinstance(existing_value, list) else []
            if overwrite_policy == "skip_if_present" and existing_items not in (None, [], {}):
                return
            incoming_items = self._coerce_collection_assignment_items(resolved_value, collection_leaf)
            if overwrite_policy in {"append", "append_unique", "merge"}:
                merged = _deepcopy(existing_items) + incoming_items
                if overwrite_policy in {"append_unique", "merge"}:
                    deduped: List[Any] = []
                    seen = set()
                    for item in merged:
                        marker = json.dumps(item, sort_keys=True, default=str)
                        if marker in seen:
                            continue
                        seen.add(marker)
                        deduped.append(item)
                    merged = deduped
                container[collection_root] = merged
                return
            container[collection_root] = incoming_items
            return

        existing_value = self._get_nested_mapping_value(container, target_field)
        if overwrite_policy == "skip_if_present" and existing_value not in (None, "", [], {}):
            return
        if overwrite_policy in {"append", "append_unique"}:
            merged = _listify(existing_value) + _listify(resolved_value)
            if overwrite_policy == "append_unique":
                deduped: List[Any] = []
                seen = set()
                for item in merged:
                    marker = json.dumps(item, sort_keys=True, default=str)
                    if marker in seen:
                        continue
                    seen.add(marker)
                    deduped.append(item)
                merged = deduped
            self._set_nested_mapping_value(container, target_field, merged)
            return
        if overwrite_policy == "merge" and isinstance(existing_value, dict) and isinstance(resolved_value, dict):
            merged = copy.deepcopy(existing_value)
            merged.update(copy.deepcopy(resolved_value))
            self._set_nested_mapping_value(container, target_field, merged)
            return
        self._set_nested_mapping_value(container, target_field, resolved_value)

    def _apply_output_actions(
        self,
        step: Dict[str, Any],
        record_context: Dict[str, Any],
        result: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        outputs = result.get("outputs") if isinstance(result.get("outputs"), dict) else {}
        actions_applied: List[Dict[str, Any]] = []
        for action in step.get("output_actions", []):
            action_type = str(action.get("action_type") or "").strip()
            if action_type and action_type not in SUPPORTED_OUTPUT_ACTION_TYPES:
                logger.warning(
                    "Skipping unsupported output action '%s' on step '%s'",
                    action_type,
                    step.get("id"),
                )
                continue
            source_output = action.get("source_output")
            target_field = action.get("target_field")
            if not source_output:
                continue
            resolved_value = self._extract_selector_value(outputs.get(source_output), action.get("selector"))
            if resolved_value is None:
                continue
            resolved_value = self._transform_output_action_value(resolved_value, action)
            overwrite_policy = str(action.get("overwrite_policy") or "overwrite").strip().lower()
            normalized_action_type = action_type or "zenodo_metadata_field"

            if normalized_action_type in {"zenodo_metadata_field", "edm_metadata_field", "record_metadata_field"}:
                if not target_field:
                    continue
                self._apply_output_action_assignment(
                    record_context["file_zenodo_metadata"],
                    str(target_field),
                    resolved_value,
                    overwrite_policy,
                )
            elif normalized_action_type == "record_status_field":
                if not target_field:
                    continue
                self._apply_output_action_assignment(
                    record_context["record_status"],
                    str(target_field),
                    resolved_value,
                    overwrite_policy,
                )
            elif normalized_action_type == "record_warning":
                warning_field = str(target_field or "warnings")
                existing_warnings = self._get_nested_mapping_value(record_context["record_status"], warning_field)
                merged = _listify(existing_warnings) + [
                    entry for entry in _listify(resolved_value) if entry not in (None, "")
                ]
                if overwrite_policy in {"", "overwrite", "append_unique"}:
                    deduped: List[Any] = []
                    seen = set()
                    for item in merged:
                        marker = json.dumps(item, sort_keys=True, default=str)
                        if marker in seen:
                            continue
                        seen.add(marker)
                        deduped.append(item)
                    merged = deduped
                self._set_nested_mapping_value(record_context["record_status"], warning_field, merged)
                resolved_value = merged

            actions_applied.append(
                {
                    "action_type": normalized_action_type,
                    "target_field": target_field,
                    "value": resolved_value,
                    "overwrite_policy": overwrite_policy,
                }
            )
        return actions_applied

    def _record_step_outputs(
        self,
        pipeline_run: PipelineRun,
        step_run: StepRun,
        step_id: str,
        record_context: Dict[str, Any],
        result: Dict[str, Any],
    ) -> None:
        outputs = result.get("outputs")
        if isinstance(outputs, dict):
            record_context["step_outputs"][step_id] = copy.deepcopy(outputs)
        artifacts = result.get("artifacts")
        if isinstance(artifacts, list):
            for artifact in artifacts:
                db.session.add(
                    ExecutionArtifact(
                        pipeline_run_id=pipeline_run.id,
                        step_run_id=step_run.id,
                        record_id=record_context.get("record_id"),
                        artifact_kind=artifact.get("artifact_kind", "file"),
                        name=artifact.get("name") or os.path.basename(artifact.get("path", "")),
                        path=artifact.get("path"),
                        metadata_json=_json_dumps(artifact.get("metadata", {})),
                    )
                )
        db.session.flush()

    def _create_step_run(
        self,
        pipeline_run: PipelineRun,
        pipeline_step: Optional[PipelineStep],
        *,
        scope: str,
        record_id: Optional[int],
        record_path: Optional[str],
        command: Optional[List[str]],
    ) -> StepRun:
        if pipeline_step is None:
            raise FileProcessingError("Pipeline step definition could not be resolved")
        row = StepRun(
            pipeline_run_id=pipeline_run.id,
            pipeline_step_id=pipeline_step.id,
            record_id=record_id,
            record_path=record_path,
            status="running",
            scope=scope,
            command_json=_json_dumps(command or []),
            started_at=datetime.utcnow(),
        )
        db.session.add(row)
        db.session.flush()
        return row

    def _finish_step_run(
        self,
        row: StepRun,
        result: Dict[str, Any],
        error: Optional[str],
        command: Optional[List[str]],
    ) -> None:
        row.status = "completed" if result.get("success", True) else "failed"
        row.result_json = _json_dumps(result)
        row.logs_json = _json_dumps(result.get("logs", {}))
        row.error_message = error
        row.command_json = _json_dumps(command or result.get("command", []))
        row.completed_at = datetime.utcnow()
        db.session.flush()

    def _find_pipeline_step(self, version_row: PipelineVersion, step_id: str) -> Optional[PipelineStep]:
        return PipelineStep.query.filter_by(pipeline_version_id=version_row.id, step_key=step_id).first()

    def _register_record_files(
        self,
        execution_context: Dict[str, Any],
        record_id: int,
        file_paths: List[str],
        pipeline_name: str,
        step_name: str,
        validation_reports: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not file_paths:
            return
        hdpc_path = execution_context.get("hdpc_path")
        if not isinstance(hdpc_path, str) or not hdpc_path.strip():
            raise FileProcessingError("hdpc_path is required to register pipeline-generated files")
        try:
            add_local_source_files(
                hdpc_path,
                absolute_file_paths=file_paths,
                record_id_to_associate=record_id,
                pipeline_name=pipeline_name,
                step_name=step_name,
                validation_reports=validation_reports,
            )
            return
        except Exception as exc:
            raise FileProcessingError(
                f"Failed to register pipeline-generated files in local .hdpc for record {record_id}: {exc}"
            ) from exc

    def _replace_remote_paths(self, value: Any, replacements: Dict[str, str]) -> Any:
        if isinstance(value, str):
            return replacements.get(value, value)
        if isinstance(value, list):
            return [self._replace_remote_paths(item, replacements) for item in value]
        if isinstance(value, dict):
            return {key: self._replace_remote_paths(item, replacements) for key, item in value.items()}
        return value

    def _materialize_hpc_artifacts(
        self,
        execution_context: Dict[str, Any],
        record_context: Dict[str, Any],
        pipeline_run: PipelineRun,
        step_run: StepRun,
        component_key: str,
        result: Dict[str, Any],
    ) -> List[str]:
        artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), list) else []
        remote_paths: List[str] = []
        for artifact in artifacts:
            if isinstance(artifact, dict):
                remote_path = str(artifact.get("remote_path") or "").strip()
                if remote_path and remote_path not in remote_paths:
                    remote_paths.append(remote_path)

        outputs = result.get("outputs") if isinstance(result.get("outputs"), dict) else {}
        for candidate in _listify(outputs.get("output_path")) + _listify(outputs.get("render_outputs")) + _listify(outputs.get("thumbnail_files")):
            candidate_path = str(candidate or "").strip()
            if candidate_path.startswith("/") and candidate_path not in remote_paths:
                remote_paths.append(candidate_path)
        if not remote_paths:
            return []

        db_session_id = execution_context.get("db_session_id")
        allocation = current_app.hpc_allocation_service.get_active_for_session(int(db_session_id)) if db_session_id else None
        if allocation is None:
            raise FileProcessingError("Cannot materialize HPC artifacts without an active HPC-Link allocation.")

        destination_dir = str(record_context.get("specific_output_dir") or execution_context.get("outputs_dir") or "").strip()
        if not destination_dir:
            raise FileProcessingError("Cannot materialize HPC artifacts without a local output directory.")
        if component_key == "fast_renderer":
            destination_dir = os.path.join(destination_dir, "render")
        elif component_key == "any_to_usdz":
            destination_dir = os.path.join(destination_dir, "usdz")
        os.makedirs(destination_dir, exist_ok=True)

        replacements: Dict[str, str] = {}
        local_paths: List[str] = []
        for remote_path in remote_paths:
            local_path = os.path.join(destination_dir, os.path.basename(remote_path))
            if remote_path in replacements:
                continue
            try:
                current_app.hpc_allocation_service.download_remote_file(allocation, remote_path, local_path)
            except Exception as exc:
                raise FileProcessingError(f"Failed to download HPC artifact '{os.path.basename(remote_path)}': {exc}") from exc
            replacements[remote_path] = local_path
            local_paths.append(local_path)

        if artifacts:
            current_app.hpc_allocation_service.register_remote_artifacts(
                allocation,
                component_key=component_key,
                artifacts=artifacts,
                pipeline_run_id=pipeline_run.id,
                step_run_id=step_run.id,
                record_id=record_context.get("record_id"),
            )
            for artifact in artifacts:
                if isinstance(artifact, dict):
                    remote_path = str(artifact.get("remote_path") or "").strip()
                    if remote_path in replacements:
                        artifact["path"] = replacements[remote_path]
        result["outputs"] = self._replace_remote_paths(outputs, replacements)
        if isinstance(result.get("render_status"), dict):
            result["render_status"] = self._replace_remote_paths(result["render_status"], replacements)
        return local_paths

    def _builtin_fast_renderer_handler(self, request: AdapterExecutionRequest) -> Dict[str, Any]:
        from services import submission_pipeline_service as legacy

        fast_renderer_service = current_app.fast_renderer_service
        execution_context = request.metadata.get("execution_context")
        record_context = request.metadata.get("record_context")
        manifest = request.metadata.get("manifest") or request.metadata.get("component_manifest") or {}

        raw_formats = request.parameters.get("formats")
        candidate_formats = _listify(raw_formats if raw_formats is not None else [
            ".obj", ".glb", ".gltf", ".usdz", ".ply", ".fbx", ".dae", ".stl", ".usd", ".usda", ".usdc", ".abc",
        ])
        normalized_formats = {
            str(item).strip().lower()
            for item in candidate_formats
            if str(item).strip()
        }

        files_to_render = [
            str(item).strip()
            for item in _listify(
                request.inputs.get("input_files")
                or request.inputs.get("input-files")
            )
            if str(item).strip()
        ]
        if execution_context is None and record_context is None:
            files_to_render = [
                self._resolve_playground_session_input(request, item, expected_kind="file")
                for item in files_to_render
            ]
        input_dir = str(
            request.inputs.get("input-dir")
            or request.inputs.get("input_dir")
            or ""
        ).strip()
        if input_dir and execution_context is None and record_context is None:
            input_dir = self._resolve_playground_session_input(request, input_dir, expected_kind="directory")
        if not files_to_render and input_dir:
            if not os.path.isdir(input_dir):
                return {
                    "success": False,
                    "status": "failed",
                    "error": f"Input directory not found: {input_dir}",
                    "command": ["builtin_webhdp", "fast_renderer", "playground"],
                }
            files_to_render = [
                path
                for path in _collect_files_recursively(input_dir)
                if os.path.splitext(path)[1].lower() in normalized_formats
            ]
        if not files_to_render and record_context is not None:
            files_to_render = [record_context["file_path"]]
        if not files_to_render:
            return {
                "success": False,
                "status": "failed",
                "error": "Fast Renderer requires input_files or an input directory.",
                "command": ["builtin_webhdp", "fast_renderer", "playground"],
            }

        output_dir = (
            request.workdir
            if execution_context is not None
            else self._resolve_playground_output_path(
                manifest,
                request.workdir,
                output_name="output-dir",
                fallback_directory="render_output",
            )
        )
        os.makedirs(output_dir, exist_ok=True)

        raw_render_options = dict(request.parameters or {})
        render_options = {
            "preset": raw_render_options.get("preset"),
            "resolution": raw_render_options.get("resolution"),
            "samples": raw_render_options.get("samples"),
            "camera_dist": raw_render_options.get("camera-dist"),
            "engine": raw_render_options.get("engine"),
            "formats": list(candidate_formats),
            "transparent_background": raw_render_options.get("transparent-background"),
            "batch_size": raw_render_options.get("batch-size"),
            "timeout_multiplier": raw_render_options.get("timeout-multiplier"),
            "parallel_mode": raw_render_options.get("parallel-mode"),
            "hpc_mode": raw_render_options.get("hpc-mode"),
            "chunk_index": raw_render_options.get("chunk-index"),
            "total_chunks": raw_render_options.get("total-chunks"),
            "check_textures": raw_render_options.get("check-textures"),
            "skip_missing_textures": raw_render_options.get("skip-missing-textures"),
            "dry_run": raw_render_options.get("dry-run"),
            "verbose": raw_render_options.get("verbose"),
            "no_ansi": raw_render_options.get("no-ansi"),
            "light_energy": raw_render_options.get("light-energy"),
            "light_angle": raw_render_options.get("light-angle"),
        }
        if raw_render_options.get("angles") not in (None, [], ""):
            render_options["custom_angles"] = raw_render_options.get("angles")
        if raw_render_options.get("angle-iteration") not in (None, ""):
            render_options["angle_iteration"] = raw_render_options.get("angle-iteration")
        render_options = {
            key: value
            for key, value in render_options.items()
            if value not in (None, "")
        }
        normalized_engine, render_warning = legacy._normalize_render_engine(render_options.get("engine"))
        render_options["engine"] = normalized_engine
        render_result = fast_renderer_service.render_batch(files_to_render, output_dir, options=render_options)

        raw_results = render_result.get("results", {}) if isinstance(render_result, dict) else {}
        mapped_results: Dict[str, Any] = {}
        for local_path in files_to_render:
            translated = fast_renderer_service._translate_to_container_path(local_path)
            mapped_results[local_path] = raw_results.get(
                translated,
                raw_results.get(local_path, {"success": False, "status": "failed", "error": "Result missing from renderer response"}),
            )

        if execution_context is None and record_context is None:
            generated_outputs = _collect_files_recursively(output_dir)
            warnings: List[str] = []
            if render_warning:
                warnings.append(render_warning)
            if isinstance(render_result, dict):
                for warning in _listify(render_result.get("warnings")):
                    warning_text = str(warning).strip()
                    if warning_text:
                        warnings.append(warning_text)

            success = bool(files_to_render) and all(
                isinstance(result_payload, dict) and result_payload.get("success", False)
                for result_payload in mapped_results.values()
            )
            if success and not generated_outputs:
                success = False
                warnings.append("Renderer reported success but no output files were discovered.")

            payload: Dict[str, Any] = {
                "success": success,
                "status": "completed" if success else "failed",
                "outputs": {
                    "output-dir": output_dir,
                    "render_outputs": generated_outputs,
                    "thumbnail_files": [
                        path
                        for path in generated_outputs
                        if os.path.splitext(path)[1].lower() in legacy.RENDERED_THUMBNAIL_EXTENSIONS
                    ],
                },
                "results": mapped_results,
                "command": ["builtin_webhdp", "fast_renderer", "playground"],
            }
            if warnings:
                payload["warnings"] = warnings
            if not success and not payload.get("error"):
                payload["error"] = render_result.get("error") if isinstance(render_result, dict) else "Fast Renderer execution failed."
            if generated_outputs:
                payload["artifacts"] = [
                    {
                        "artifact_kind": "file",
                        "name": os.path.basename(path),
                        "path": path,
                        "metadata": {"step": "fast_renderer", "playground": True},
                    }
                    for path in generated_outputs
                ]
            return payload

        record_results: Dict[str, Any] = {}
        for local_path in files_to_render:
            input_root = os.path.commonpath([os.path.dirname(path) for path in files_to_render])
            record_output_dir = os.path.join(output_dir, os.path.relpath(local_path, input_root))
            if not os.path.isdir(record_output_dir):
                record_output_dir = os.path.join(output_dir, os.path.splitext(os.path.basename(local_path))[0])
            discovered_render_outputs = legacy._collect_generated_output_files(record_output_dir)
            thumbnail_files = legacy._collect_rendered_thumbnail_files(record_output_dir)
            render_payload = _deepcopy(mapped_results.get(local_path) or {})
            warnings: List[str] = []
            if render_warning:
                warnings.append(render_warning)
            render_success = bool(render_payload.get("success", False))
            if render_success and not discovered_render_outputs:
                render_success = False
                warnings.append(f"Renderer reported success for {os.path.basename(local_path)} but produced no output files.")
            record_results[local_path] = {
                "success": render_success,
                "status": "completed" if render_success else "failed",
                "error": None if render_success else render_payload.get("error") or "Fast Renderer execution failed.",
                "outputs": {
                    "render_outputs": discovered_render_outputs,
                    "thumbnail_files": thumbnail_files,
                },
                "artifacts": [
                    {
                        "artifact_kind": "file",
                        "name": os.path.basename(path),
                        "path": path,
                        "metadata": {"step": "fast_renderer"},
                    }
                    for path in discovered_render_outputs
                ],
                "render_status": {
                    **render_payload,
                    "success": render_success,
                    "status": "completed" if render_success else "failed",
                    "warnings": warnings,
                },
            }

        if record_context is not None:
            return _deepcopy(record_results.get(record_context["file_path"]) or {
                "success": False,
                "status": "failed",
                "error": "Fast Renderer record result missing",
                "outputs": {},
                "artifacts": [],
            })

        success = bool(record_results) and all(result.get("success", False) for result in record_results.values())
        return {
            "success": success,
            "status": "completed" if success else "failed",
            "record_results": record_results,
            "results": mapped_results,
            "command": ["builtin_webhdp", "fast_renderer", "batch"],
            "error": None if success else "Fast Renderer execution failed for one or more records.",
        }

    def _builtin_any_to_usdz_handler(self, request: AdapterExecutionRequest) -> Dict[str, Any]:
        from services import submission_pipeline_service as legacy

        execution_context = request.metadata.get("execution_context")
        record_context = request.metadata.get("record_context")
        if execution_context is None or record_context is None:
            input_file = str(request.inputs.get("input_file") or "").strip()
            if not input_file:
                return {
                    "success": False,
                    "status": "failed",
                    "error": "USDZ Converter requires an input file.",
                    "command": ["builtin_webhdp", "any_to_usdz", "playground"],
                }
            input_file = self._resolve_playground_session_input(request, input_file, expected_kind="file")

            manifest = request.metadata.get("manifest") or {}
            output_dir = self._resolve_playground_output_path(
                manifest,
                request.workdir,
                fallback_directory="usdz_output",
            )
            os.makedirs(output_dir, exist_ok=True)

            usdz_result = current_app.any_to_usdz_service.convert(input_file, output_dir, options=dict(request.parameters or {}))
            output_path = usdz_result.get("output_path") if isinstance(usdz_result, dict) else None
            payload: Dict[str, Any] = {
                "success": bool(isinstance(usdz_result, dict) and usdz_result.get("success", False)),
                "status": "completed" if isinstance(usdz_result, dict) and usdz_result.get("success", False) else "failed",
                "outputs": {"output_path": output_path} if output_path else {},
                "details": usdz_result,
                "command": ["builtin_webhdp", "any_to_usdz", "playground"],
            }
            if not payload["success"]:
                payload["error"] = usdz_result.get("error") if isinstance(usdz_result, dict) else "USDZ conversion failed."
                return payload
            if output_path:
                payload["artifacts"] = [
                    {
                        "artifact_kind": "file",
                        "name": os.path.basename(output_path),
                        "path": output_path,
                        "metadata": {"step": "any_to_usdz", "playground": True},
                    }
                ]
            return payload

        progress_callback = execution_context.get("progress_callback")
        any_to_usdz_enabled = execution_context["steps_map"].get("any_to_usdz", {}).get("enabled", True)
        if not current_app.config.get("ENABLE_USDZ_CONVERSION", True):
            any_to_usdz_enabled = False
        if not any_to_usdz_enabled:
            record_context["record_status"]["usdz"] = {"success": True, "status": "skipped_disabled"}
            return {"success": True, "status": "completed", "outputs": {}}

        input_file = str(request.inputs.get("input_file") or record_context["file_path"]).strip()
        if not input_file:
            return {"success": False, "status": "failed", "error": "USDZ Converter requires an input file.", "outputs": {}, "command": ["builtin_webhdp", "any_to_usdz"]}

        legacy._emit_progress(
            progress_callback,
            {
                "current_stage": "converting_to_usdz",
                "status_message": f"Converting {record_context['filename']} to USDZ",
                "current_file_name": record_context["filename"],
                "current_index": record_context["index"],
                "total_files": record_context["total_records"],
                "processed_count": execution_context.get("processed_count", 0),
                "failed_count": execution_context.get("failed_count", 0),
            },
        )
        started = time.time()
        usdz_result = current_app.any_to_usdz_service.convert(input_file, execution_context["outputs_dir"])
        record_context["record_timings"]["steps"]["usdz"] = time.time() - started
        timings = legacy._normalize_subprocess_timings(usdz_result.get("timings"))
        if timings:
            record_context["record_timings"]["subprocesses"]["usdz"] = timings
        record_context["record_status"]["usdz"] = usdz_result
        if usdz_result.get("success"):
            usdz_path = usdz_result.get("output_path")
            if isinstance(usdz_path, str) and usdz_path.strip():
                self._register_record_files(
                    execution_context,
                    record_context["record_id"],
                    [usdz_path],
                    "any_to_usdz",
                    "converter",
                )
                legacy._append_unique_paths(record_context["generated_files"], [usdz_path])
                return {
                    "success": True,
                    "status": "completed",
                    "outputs": {"output_path": usdz_path},
                    "artifacts": [{"artifact_kind": "file", "name": os.path.basename(usdz_path), "path": usdz_path, "metadata": {}}],
                    "command": ["builtin_webhdp", "any_to_usdz"],
                }
            failure = {
                "message": f"USDZ conversion reported success for {record_context['filename']} but no output_path was returned.",
                "error_message": "Missing USDZ output path",
                "error_code": "USDZ_OUTPUT_PATH_MISSING",
                "hint": "Check converter output and logs for this file.",
                "details": usdz_result.get("details", {}),
            }
            record_context["record_status"]["usdz"]["status"] = "failed"
            record_context["record_status"]["usdz"]["critical"] = True
            record_context["record_status"]["usdz"]["error"] = failure["error_message"]
            record_context["record_status"]["usdz"]["error_code"] = failure["error_code"]
            record_context["record_status"]["usdz"]["hint"] = failure["hint"]
            record_context["record_status"]["warnings"].append(failure["message"])
            if execution_context.get("abort_on_critical_error"):
                raise FileProcessingError(
                    f"{failure['message']} Aborting pipeline because critical-error mode is enabled."
                )
            return {"success": False, "status": "failed", "error": failure["error_message"], "outputs": {}, "command": ["builtin_webhdp", "any_to_usdz"]}

        failure = legacy._build_usdz_failure_message(record_context["filename"], usdz_result)
        record_context["record_status"]["usdz"]["status"] = "failed"
        record_context["record_status"]["usdz"]["critical"] = True
        record_context["record_status"]["usdz"]["error"] = failure["error_message"]
        record_context["record_status"]["usdz"]["error_code"] = failure["error_code"]
        record_context["record_status"]["usdz"]["hint"] = failure["hint"]
        record_context["record_status"]["usdz"]["details"] = failure["details"]
        record_context["record_status"]["warnings"].append(failure["message"])
        legacy._emit_progress(
            progress_callback,
            {
                "current_stage": "usdz_conversion_failed",
                "status_message": f"USDZ conversion failed for {record_context['filename']}",
                "warning_message": failure["message"],
                "warning_code": failure["error_code"],
                "critical_error": True,
                "continue_processing": not execution_context.get("abort_on_critical_error"),
                "current_file_name": record_context["filename"],
                "current_index": record_context["index"],
                "total_files": record_context["total_records"],
                "processed_count": execution_context.get("processed_count", 0),
                "failed_count": execution_context.get("failed_count", 0),
            },
        )
        if execution_context.get("abort_on_critical_error"):
            raise FileProcessingError(f"{failure['message']} Aborting pipeline because critical-error mode is enabled.")
        return {"success": False, "status": "failed", "error": failure["error_message"], "outputs": {}, "command": ["builtin_webhdp", "any_to_usdz"]}

    def _builtin_input_file_classification_handler(self, request: AdapterExecutionRequest) -> Dict[str, Any]:
        input_file = str(request.inputs.get("input_file") or "").strip()
        if not input_file:
            return {
                "success": False,
                "status": "failed",
                "error": "Input File Classification requires an input file.",
                "outputs": {},
                "command": ["builtin_webhdp", "input_file_classification"],
            }
        classification = self._classify_input_file(input_file)
        return {
            "success": True,
            "status": "completed",
            "outputs": {
                "classification_json": classification,
            },
            "command": ["builtin_webhdp", "input_file_classification"],
        }

    def _normalize_lod_policy(self, lod_options: Dict[str, Any]) -> str:
        policy = str((lod_options or {}).get("lod_policy") or "required").strip().lower()
        return policy if policy in LOD_POLICY_VALUES else "required"

    def _set_lod_status(self, record_context: Dict[str, Any], standard_id: str, **payload: Any) -> None:
        record_context["record_status"][standard_id] = {
            "success": bool(payload.get("success", False)),
            "status": payload.get("status"),
            **{key: value for key, value in payload.items() if key not in {"success", "status"}},
        }

    def _mark_lod_step_skipped(self, record_context: Dict[str, Any], *, status: str) -> None:
        for standard_id in ("edm", "iiif", "mets", "cidoc_crm", "jsonld"):
            self._set_lod_status(record_context, standard_id, success=True, status=status)

    def _builtin_zenodo_draft_handler(self, request: AdapterExecutionRequest) -> Dict[str, Any]:
        from services import submission_pipeline_service as legacy

        execution_context = request.metadata["execution_context"]
        record_context = request.metadata["record_context"]
        progress_callback = execution_context.get("progress_callback")
        resolution_action = str((record_context.get("record_resolution") or {}).get("action") or "").strip().lower()
        if not execution_context["steps_map"].get("zenodo_draft", {}).get("enabled", True):
            return {"success": True, "status": "completed", "outputs": {}}

        legacy._emit_progress(
            progress_callback,
            {
                "current_stage": "creating_zenodo_draft",
                "status_message": f"Creating Zenodo draft for {record_context['filename']}",
                "current_file_name": record_context["filename"],
                "current_index": record_context["index"],
                "total_files": record_context["total_records"],
                "processed_count": execution_context.get("processed_count", 0),
                "failed_count": execution_context.get("failed_count", 0),
            },
        )
        start_step = time.time()
        from services.dataset_integrity_service import ensure_record_operation_allowed

        if resolution_action != "force_create_fresh":
            ensure_record_operation_allowed(
                execution_context["db_session"],
                local_record_id=record_context["record_id"],
                allow_allowed_versioning=resolution_action == "create_version",
                exclude_current_record=True,
            )
        prepared_draft = (
            (record_context.get("record_resolution") or {}).get("prepared_draft_result")
            if resolution_action == "create_version"
            else None
        )
        if isinstance(prepared_draft, dict) and prepared_draft.get("success"):
            record_context["record_timings"]["steps"]["zenodo_draft"] = time.time() - start_step
            record_context["record_timings"]["subprocesses"]["zenodo_draft"] = {
                "api_call": record_context["record_timings"]["steps"]["zenodo_draft"]
            }
            record_context["draft_result"] = prepared_draft
            record_context["record_status"]["zenodo"]["draft"] = prepared_draft
            record_context["record_status"]["zenodo"]["draft_success"] = True
            current_draft_id = legacy._extract_zenodo_draft_id(prepared_draft)
            record_context["current_zenodo_draft_record_id"] = current_draft_id
            if current_draft_id:
                record_context["record_status"]["zenodo"]["draft_record_id"] = current_draft_id
            return {
                "success": True,
                "status": "completed",
                "outputs": {"draft": prepared_draft},
                "command": ["builtin_webhdp", "zenodo_draft"],
            }
        try:
            draft_result = create_local_zenodo_draft(
                execution_context["hdpc_path"],
                record_context["record_id"],
                access_token=execution_context.get("access_token"),
            )
        except Exception as exc:
            raise FileProcessingError(
                f"Failed to create local Zenodo draft for record {record_context['record_id']}: {exc}"
            ) from exc
        record_context["record_timings"]["steps"]["zenodo_draft"] = time.time() - start_step
        record_context["record_timings"]["subprocesses"]["zenodo_draft"] = {
            "api_call": record_context["record_timings"]["steps"]["zenodo_draft"]
        }
        record_context["draft_result"] = draft_result
        record_context["record_status"]["zenodo"]["draft"] = draft_result
        record_context["record_status"]["zenodo"]["draft_success"] = draft_result.get("success", False)
        if not record_context["record_status"]["zenodo"]["draft_success"]:
            record_context["record_status"]["error"] = legacy._extract_error_from_service_result(
                draft_result,
                f"Failed to create Zenodo draft for {record_context['filename']}",
            )
        current_draft_id = legacy._extract_zenodo_draft_id(draft_result)
        record_context["current_zenodo_draft_record_id"] = current_draft_id
        if current_draft_id:
            record_context["record_status"]["zenodo"]["draft_record_id"] = current_draft_id
        return {
            "success": draft_result.get("success", False),
            "status": "completed" if draft_result.get("success", False) else "failed",
            "outputs": {"draft": draft_result},
            "command": ["builtin_webhdp", "zenodo_draft"],
            "error": None if draft_result.get("success", False) else record_context["record_status"].get("error"),
        }

    def _builtin_lod_generation_handler(self, request: AdapterExecutionRequest) -> Dict[str, Any]:
        from services import submission_pipeline_service as legacy

        execution_context = request.metadata["execution_context"]
        record_context = request.metadata["record_context"]
        progress_callback = execution_context.get("progress_callback")
        lod_options = execution_context["steps_map"].get("lod_generation", {}).get("parameters", {})
        lod_policy = self._normalize_lod_policy(lod_options)
        if not execution_context["steps_map"].get("lod_generation", {}).get("enabled", True):
            self._mark_lod_step_skipped(record_context, status="skipped_disabled")
            return {"success": True, "status": "completed", "outputs": {}}
        if lod_policy == "disabled":
            self._mark_lod_step_skipped(record_context, status="skipped_disabled")
            return {"success": True, "status": "completed", "outputs": {}}
        if not record_context["record_status"]["zenodo"].get("draft_success"):
            self._mark_lod_step_skipped(record_context, status="skipped_missing_draft")
            return {"success": True, "status": "completed", "outputs": {}}

        legacy._emit_progress(
            progress_callback,
            {
                "current_stage": "generating_lod_metadata",
                "status_message": f"Generating metadata for {record_context['filename']}",
                "current_file_name": record_context["filename"],
                "current_index": record_context["index"],
                "total_files": record_context["total_records"],
                "processed_count": execution_context.get("processed_count", 0),
                "failed_count": execution_context.get("failed_count", 0),
                "zenodo_draft_record_id": record_context["current_zenodo_draft_record_id"],
            },
        )
        start_step = time.time()
        lod_subprocess_timings: Dict[str, float] = {}

        def add_timing(key: str, elapsed: float) -> None:
            if elapsed >= 0:
                lod_subprocess_timings[key] = lod_subprocess_timings.get(key, 0.0) + elapsed

        generated_outputs: Dict[str, Any] = {}
        zenodo_resp = record_context["draft_result"].get("zenodo_response", record_context["draft_result"])
        main_file_key = record_context["file_zenodo_metadata"].get("edm_main_file_key") or record_context["filename"]
        additional_files_for_lod = [
            {"key": os.path.basename(path), "size": os.path.getsize(path)}
            for path in record_context["generated_files"]
            if os.path.exists(path)
        ]
        rendered_thumbnail_filenames = [
            os.path.basename(path)
            for path in record_context["generated_files"]
            if os.path.splitext(path)[1].lower() in legacy.RENDERED_THUMBNAIL_EXTENSIONS
        ]
        renderer_enabled = execution_context["steps_map"].get("fast_renderer", {}).get("enabled", True)
        thumbnail_mapping_active = bool(
            renderer_enabled
            and execution_context["canonical_identifier"] != METADATA_ONLY_PIPELINE_ID
            and rendered_thumbnail_filenames
        )
        allow_placeholder_thumbnail = not renderer_enabled
        modality = legacy._infer_lod_modality(record_context["filename"], record_context["file_zenodo_metadata"])
        lod_row = execution_context["msf_rows_by_filename"].get(record_context["filename"].lower())
        thumbnail_mapping_keys = {
            "lod_thumbnail_mode",
            "lod_thumbnail_pattern",
            "lod_thumbnail_files",
            "lod_thumbnail_mapping_enabled",
            "lod_rendered_thumbnails",
        }

        def build_lod_metadata(standard_id: str) -> Dict[str, Any]:
            base_metadata = {
                key: value
                for key, value in record_context["file_zenodo_metadata"].items()
                if key not in legacy.INTERNAL_ZENODO_KEYS
            }
            for key in thumbnail_mapping_keys:
                base_metadata.pop(key, None)
            if thumbnail_mapping_active:
                base_metadata["lod_thumbnail_mapping_enabled"] = True
                base_metadata["lod_rendered_thumbnails"] = rendered_thumbnail_filenames
            if lod_row is None:
                return base_metadata
            mapping_for_standard = legacy._extract_standard_mapping(
                execution_context["lod_mapping_config"],
                standard_id,
                modality,
            )
            if not mapping_for_standard:
                return base_metadata
            mapped_values = current_app.msf_service.apply_lod_mapping(
                lod_row,
                zenodo_resp,
                mapping_for_standard,
                include_defaults=False,
            )
            return legacy._merge_non_empty_metadata(base_metadata, mapped_values)

        try:
            if lod_options.get("generate_edm", True):
                step_started = time.time()
                edm_metadata = build_lod_metadata("edm")
                edm_generation = current_app.edm_service.generate_edm_xml_with_report(
                    edm_metadata,
                    zenodo_resp,
                    None,
                    main_file_key=main_file_key,
                    validate=False,
                    additional_files=additional_files_for_lod,
                    allow_placeholder_thumbnail=allow_placeholder_thumbnail,
                )
                edm_content = edm_generation["content"]
                edm_validation = current_app.edm_service.validate_edm_document(
                    edm_content,
                    metadata=edm_metadata,
                    include_remote=current_app.config.get(
                        "LOCAL_EDM_VALIDATOR_REQUIRED",
                        False,
                    ) or current_app.config.get(
                        "ENABLE_LOCAL_EDM_VALIDATION",
                        current_app.config.get("ENABLE_METIS_VALIDATION", True),
                    ),
                )
                edm_path = os.path.join(record_context["specific_output_dir"], "edm.xml")
                with open(edm_path, "w", encoding="utf-8") as handle:
                    handle.write(edm_content)
                edm_validation_report_path = os.path.join(
                    record_context["specific_output_dir"],
                    "edm.validation.json",
                )
                with open(edm_validation_report_path, "w", encoding="utf-8") as handle:
                    json.dump(edm_validation, handle, indent=2, sort_keys=True)
                self._register_record_files(
                    execution_context,
                    record_context["record_id"],
                    [edm_path, edm_validation_report_path],
                    "lod_generation",
                    "xml_generator",
                    validation_reports={edm_path: edm_validation},
                )
                legacy._append_unique_paths(
                    record_context["generated_files"],
                    [edm_path, edm_validation_report_path],
                )
                if not edm_validation.get("valid", True):
                    validation_errors = edm_validation.get("errors") or ["Local EDM Validator rejected generated EDM"]
                    raise ValueError(f"EDM validation failed: {validation_errors[0]}")
                self._set_lod_status(
                    record_context,
                    "edm",
                    success=True,
                    status="generated",
                    path=edm_path,
                    validation_report_path=edm_validation_report_path,
                    validation=edm_validation,
                    minimum_viable_applied=edm_generation["minimum_viable_applied"],
                    lod_policy=lod_policy,
                )
                generated_outputs["edm"] = edm_path
                add_timing("edm_generation", time.time() - step_started)
            else:
                self._set_lod_status(
                    record_context,
                    "edm",
                    success=True,
                    status="skipped_disabled",
                    lod_policy=lod_policy,
                )

            if lod_options.get("generate_iiif", True):
                step_started = time.time()
                iiif_metadata = build_lod_metadata("iiif")
                iiif_generation = current_app.iiif_service.generate_iiif_manifest_with_report(
                    iiif_metadata,
                    zenodo_resp,
                    None,
                    main_file_key=main_file_key,
                    allow_placeholder_thumbnail=allow_placeholder_thumbnail,
                    additional_files=additional_files_for_lod,
                )
                iiif_content = iiif_generation["content"]
                iiif_validation = iiif_generation["validation"] or current_app.iiif_service.validate_iiif_manifest(iiif_content)
                iiif_path = os.path.join(record_context["specific_output_dir"], "iiif.json")
                with open(iiif_path, "w", encoding="utf-8") as handle:
                    handle.write(iiif_content)
                self._register_record_files(
                    execution_context,
                    record_context["record_id"],
                    [iiif_path],
                    "lod_generation",
                    "iiif_manifest_generator",
                )
                legacy._append_unique_paths(record_context["generated_files"], [iiif_path])
                if not iiif_validation.get("valid", True):
                    validation_errors = iiif_validation.get("errors") or ["IIIF validation rejected generated manifest"]
                    raise ValueError(f"IIIF validation failed: {validation_errors[0]}")
                self._set_lod_status(
                    record_context,
                    "iiif",
                    success=True,
                    status="generated",
                    path=iiif_path,
                    validation=iiif_validation,
                    minimum_viable_applied=iiif_generation["minimum_viable_applied"],
                    lod_policy=lod_policy,
                )
                generated_outputs["iiif"] = iiif_path
                add_timing("iiif_generation", time.time() - step_started)
            else:
                self._set_lod_status(
                    record_context,
                    "iiif",
                    success=True,
                    status="skipped_disabled",
                    lod_policy=lod_policy,
                )

            if lod_options.get("generate_mets", True):
                step_started = time.time()
                mets_metadata = build_lod_metadata("mets")
                mets_generation = current_app.mets_service.generate_mets_xml_with_report(
                    mets_metadata,
                    zenodo_resp,
                    None,
                    main_file_key=main_file_key,
                    validate=True,
                    allow_placeholder_thumbnail=allow_placeholder_thumbnail,
                    additional_files=additional_files_for_lod,
                )
                mets_content = mets_generation["content"]
                mets_validation = mets_generation["validation"] or current_app.mets_service.validate_mets_xml(mets_content)
                mets_path = os.path.join(record_context["specific_output_dir"], "mets.xml")
                with open(mets_path, "w", encoding="utf-8") as handle:
                    handle.write(mets_content)
                self._register_record_files(
                    execution_context,
                    record_context["record_id"],
                    [mets_path],
                    "lod_generation",
                    "mets_mods_generator",
                )
                legacy._append_unique_paths(record_context["generated_files"], [mets_path])
                if not mets_validation.get("valid", True):
                    validation_errors = mets_validation.get("errors") or ["METS/MODS validation rejected generated document"]
                    raise ValueError(f"METS/MODS validation failed: {validation_errors[0]}")
                self._set_lod_status(
                    record_context,
                    "mets",
                    success=True,
                    status="generated",
                    path=mets_path,
                    validation=mets_validation,
                    minimum_viable_applied=mets_generation["minimum_viable_applied"],
                    lod_policy=lod_policy,
                )
                generated_outputs["mets"] = mets_path
                add_timing("mets_generation", time.time() - step_started)
            else:
                self._set_lod_status(
                    record_context,
                    "mets",
                    success=True,
                    status="skipped_disabled",
                    lod_policy=lod_policy,
                )
            from services.linked_data_service import generate_linked_data

            linked_outputs = generate_linked_data(
                build_lod_metadata("cidoc_crm"), zenodo_resp,
                main_file_key=main_file_key, additional_files=additional_files_for_lod,
            )
            for standard_id, (filename, content) in linked_outputs.items():
                path = os.path.join(record_context["specific_output_dir"], filename)
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(content)
                self._register_record_files(execution_context, record_context["record_id"], [path], "lod_generation", "xml_generator")
                legacy._append_unique_paths(record_context["generated_files"], [path])
                self._set_lod_status(record_context, standard_id, success=True, status="generated", path=path, lod_policy=lod_policy)
                generated_outputs[standard_id] = path
        except Exception as exc:
            current_app.logger.error("LOD generation failed for %s: %s", record_context["filename"], exc)
            failure_message = f"LOD generation failed for {record_context['filename']}: {exc}"
            failure_status = "failed_required" if lod_policy == "required" else "failed_optional"
            for standard_id in ("edm", "iiif", "mets", "cidoc_crm", "jsonld"):
                status_value = (record_context["record_status"].get(standard_id) or {}).get("status")
                if status_value in {"generated", "skipped_disabled", "skipped_missing_draft"}:
                    continue
                self._set_lod_status(
                    record_context,
                    standard_id,
                    success=False,
                    status=failure_status,
                    error=str(exc),
                    lod_policy=lod_policy,
                )
            record_context["record_status"]["warnings"].append(failure_message)
            if lod_policy == "required":
                record_context["record_status"]["error"] = failure_message

        record_context["record_timings"]["steps"]["lod_generation"] = time.time() - start_step
        add_timing("full_step", record_context["record_timings"]["steps"]["lod_generation"])
        record_context["record_timings"]["subprocesses"]["lod_generation"] = lod_subprocess_timings
        artifacts = [
            {"artifact_kind": "file", "name": os.path.basename(path), "path": path, "metadata": {"step": "lod_generation"}}
            for path in generated_outputs.values()
        ]
        return {
            "success": lod_policy != "required" or not bool(record_context["record_status"].get("error")),
            "status": "failed" if lod_policy == "required" and record_context["record_status"].get("error") else "completed",
            "outputs": generated_outputs,
            "artifacts": artifacts,
            "command": ["builtin_webhdp", "lod_generation"],
            "error": record_context["record_status"].get("error"),
        }

    def _builtin_zenodo_upload_handler(self, request: AdapterExecutionRequest) -> Dict[str, Any]:
        from services import submission_pipeline_service as legacy
        from services.dataset_integrity_service import ensure_record_operation_allowed

        execution_context = request.metadata["execution_context"]
        record_context = request.metadata["record_context"]
        progress_callback = execution_context.get("progress_callback")
        resolution_action = str((record_context.get("record_resolution") or {}).get("action") or "").strip().lower()
        step_config = execution_context["steps_map"].get("zenodo_upload", {})
        if not step_config.get("enabled", True):
            return {"success": True, "status": "completed", "outputs": {}}
        if record_context["record_status"].get("error"):
            return {
                "success": False,
                "status": "failed",
                "error": record_context["record_status"]["error"],
                "outputs": {},
            }
        if not record_context["record_status"]["zenodo"].get("draft_success"):
            if not record_context["record_status"].get("error"):
                record_context["record_status"]["error"] = (
                    f"Zenodo upload skipped because draft creation failed for {record_context['filename']}"
                )
            return {"success": False, "status": "failed", "error": record_context["record_status"]["error"], "outputs": {}}

        legacy._emit_progress(
            progress_callback,
            {
                "current_stage": "uploading_to_zenodo",
                "status_message": f"Uploading files for {record_context['filename']}",
                "current_file_name": record_context["filename"],
                "current_index": record_context["index"],
                "total_files": record_context["total_records"],
                "processed_count": execution_context.get("processed_count", 0),
                "failed_count": execution_context.get("failed_count", 0),
                "zenodo_draft_record_id": record_context["current_zenodo_draft_record_id"],
            },
        )
        started = time.time()
        if resolution_action != "force_create_fresh":
            ensure_record_operation_allowed(
                execution_context["db_session"],
                local_record_id=record_context["record_id"],
                allow_allowed_versioning=resolution_action == "create_version",
                exclude_current_record=True,
            )
        try:
            upload_result = upload_local_zenodo_files(
                execution_context["hdpc_path"],
                record_context["record_id"],
                publish=bool(step_config.get("parameters", {}).get("publish", False)),
                prune_inherited_files=resolution_action == "create_version",
                access_token=execution_context.get("access_token"),
            )
        except Exception as exc:
            raise FileProcessingError(
                f"Failed to upload local Zenodo files for record {record_context['record_id']}: {exc}"
            ) from exc
        record_context["record_timings"]["steps"]["zenodo_upload"] = time.time() - started
        record_context["record_timings"]["subprocesses"]["zenodo_upload"] = {
            "api_call": record_context["record_timings"]["steps"]["zenodo_upload"]
        }
        record_context["record_status"]["zenodo"]["upload_success"] = upload_result.get("success", False)
        record_context["record_status"]["zenodo"]["upload"] = upload_result
        if not upload_result.get("success", False):
            record_context["record_status"]["error"] = legacy._extract_error_from_service_result(
                upload_result,
                f"Failed to upload files to Zenodo for {record_context['filename']}",
            )
        return {
            "success": upload_result.get("success", False),
            "status": "completed" if upload_result.get("success", False) else "failed",
            "outputs": {"upload": upload_result},
            "command": ["builtin_webhdp", "zenodo_upload"],
            "error": None if upload_result.get("success", False) else record_context["record_status"].get("error"),
        }
