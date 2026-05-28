"""Schemas for the native WebHDP pipeline system."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AdapterType = Literal["legacy_hdp_python", "local_cli", "container_cli", "builtin_webhdp", "hpc_link"]
BindingType = Literal[
    "artifact_file",
    "artifact_directory",
    "artifact_json_value",
    "literal",
    "pipeline_source_file",
    "pipeline_source_files",
    "pipeline_source_directory",
    "record_metadata_field",
    "secret_ref",
]
BindingKind = Literal["input", "parameter"]
PipelineScope = Literal["record", "batch", "pipeline"]
TriggerSourceType = Literal["file_fact", "classifier_output"]
TriggerOperator = Literal["eq", "neq", "in", "not_in", "gte", "lte", "between", "exists", "truthy"]


class ComponentManifestMetadataSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    label: Optional[str] = None
    description: str = ""
    component_schema: Optional[str] = None


class ComponentIOFieldSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)
    label: Optional[str] = None
    description: str = ""
    required: bool = False
    default: Any = None
    options: List[Any] = Field(default_factory=list)


class ComponentParameterSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)
    label: Optional[str] = None
    description: str = ""
    required: bool = False
    default: Any = None
    options: List[Any] = Field(default_factory=list)


class ComponentParameterGroupSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str = Field(..., min_length=1)
    description: str = ""
    parameters: List[ComponentParameterSchema] = Field(default_factory=list)


class ComponentExecutionProfileSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(..., min_length=1)
    adapter: AdapterType
    entrypoint: List[str] = Field(default_factory=list)
    working_directory: str = "."
    runtime: Optional[str] = None
    image: Optional[str] = None
    handler: Optional[str] = None
    input_bindings: List[Dict[str, Any]] = Field(default_factory=list)
    output_collection: List[Dict[str, Any]] = Field(default_factory=list)
    environment: Dict[str, str] = Field(default_factory=dict)
    resources: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_profile(self) -> "ComponentExecutionProfileSchema":
        if self.adapter in {"builtin_webhdp", "hpc_link"}:
            if not self.handler:
                raise ValueError(f"{self.adapter} profiles require a handler")
            return self

        if not self.entrypoint:
            raise ValueError(f"{self.adapter} profiles require an entrypoint")

        if self.adapter == "container_cli":
            if not self.runtime:
                raise ValueError("container_cli profiles require a runtime")
            if not self.image:
                raise ValueError("container_cli profiles require an image")

        return self


class ComponentExecutionSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    profiles: List[ComponentExecutionProfileSchema] = Field(..., min_length=1)


class ComponentManifestSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    metadata: ComponentManifestMetadataSchema
    inputs: List[ComponentIOFieldSchema] = Field(default_factory=list)
    outputs: List[ComponentIOFieldSchema] = Field(default_factory=list)
    parameter_groups: List[ComponentParameterGroupSchema] = Field(default_factory=list)
    execution: ComponentExecutionSchema
    compatibility: Dict[str, Any] = Field(default_factory=dict)
    ui: Optional[Dict[str, Any]] = None


class PipelineBindingSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: BindingKind
    target: str = Field(..., min_length=1)
    type: BindingType
    source_step: Optional[str] = None
    source_output: Optional[str] = None
    selector: Optional[str] = None
    metadata_field: Optional[str] = None
    value: Any = None
    secret_ref: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_binding(self) -> "PipelineBindingSchema":
        if self.type in {"artifact_file", "artifact_directory", "artifact_json_value"}:
            if not self.source_step or not self.source_output:
                raise ValueError(f"{self.type} bindings require source_step and source_output")
        elif self.type in {"pipeline_source_file", "pipeline_source_files", "pipeline_source_directory"}:
            return self
        elif self.type == "record_metadata_field":
            if not self.metadata_field:
                raise ValueError("record_metadata_field bindings require metadata_field")
        elif self.type == "secret_ref":
            if not self.secret_ref:
                raise ValueError("secret_ref bindings require secret_ref")
        elif self.type == "literal" and self.value is None:
            raise ValueError("literal bindings require value")
        return self


class PipelineOutputActionSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    action_type: str = Field(..., min_length=1)
    source_output: Optional[str] = None
    selector: Optional[str] = None
    target_field: Optional[str] = None
    transform: Optional[str] = None
    overwrite_policy: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)


class PipelineTriggerConditionSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_type: TriggerSourceType
    field: str = Field(..., min_length=1)
    operator: TriggerOperator
    value: Any = None
    values: List[Any] = Field(default_factory=list)
    config: Dict[str, Any] = Field(default_factory=dict)
    source_step: Optional[str] = None
    source_output: Optional[str] = None

    @model_validator(mode="after")
    def validate_condition(self) -> "PipelineTriggerConditionSchema":
        if self.source_type == "classifier_output":
            if not self.source_step or not self.source_output:
                raise ValueError("classifier_output trigger conditions require source_step and source_output")
        if self.operator in {"in", "not_in", "between"} and not self.values:
            raise ValueError(f"{self.operator} trigger conditions require values")
        if self.operator not in {"in", "not_in", "between", "exists", "truthy"} and self.value is None:
            raise ValueError(f"{self.operator} trigger conditions require value")
        return self


class PipelineTriggerRuleSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(..., min_length=1)
    label: Optional[str] = None
    conditions: List[PipelineTriggerConditionSchema] = Field(default_factory=list)
    action: Literal["run", "skip"] = "run"
    parameter_overrides: Dict[str, Any] = Field(default_factory=dict)


class PipelineTriggerSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    default_behavior: Literal["run", "skip"] = "run"
    rules: List[PipelineTriggerRuleSchema] = Field(default_factory=list)


class PipelineStepSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = ""
    enabled: bool = True
    scope: PipelineScope = "record"
    component_ref: Optional[str] = None
    execution_profile_ref: str = "builtin_default"
    parameters: Dict[str, Any] = Field(default_factory=dict)
    input_bindings: List[PipelineBindingSchema] = Field(default_factory=list)
    parameter_bindings: List[PipelineBindingSchema] = Field(default_factory=list)
    output_actions: List[PipelineOutputActionSchema] = Field(default_factory=list)
    triggers: Optional[PipelineTriggerSchema] = None
    resources: Dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: Optional[int] = None

    @field_validator("timeout_seconds")
    @classmethod
    def validate_timeout(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value <= 0:
            raise ValueError("timeout_seconds must be positive")
        return value


class PipelineDefinitionSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    identifier: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = ""
    status: str = "active"
    modality: Optional[str] = None
    processingMode: str = "root"
    version: str = Field(..., min_length=1)
    tags: List[str] = Field(default_factory=list)
    steps: List[PipelineStepSchema] = Field(default_factory=list)


class PipelineExecutionItemSchema(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    decision_key: str = Field(..., min_length=1)
    action: Literal["create_fresh_record", "create_version", "skip", "force_create_fresh"]
    source_file_path: str = Field(..., min_length=1)
    source_file_name: Optional[str] = None
    target_session_id: Optional[int] = None
    target_local_record_id: Optional[int] = None
    target_concept_rec_id: Optional[str] = None
    forced_override_reason: Optional[str] = None


class PipelineExecutionRequestSchema(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    pipeline_identifier: str = Field(..., min_length=1)
    session_id: int = Field(..., gt=0)
    local_file_paths: List[str] = Field(default_factory=list)
    record_ids: List[int] = Field(default_factory=list)
    execution_items: List[PipelineExecutionItemSchema] = Field(default_factory=list)
    is_sandbox: bool = True
    async_execution: bool = False
    abort_on_critical_error: bool = False

    @model_validator(mode="after")
    def validate_targets(self) -> "PipelineExecutionRequestSchema":
        if not self.local_file_paths and not self.record_ids and not self.execution_items:
            raise ValueError("Either local_file_paths, record_ids, or execution_items must be provided")
        return self


class PlaygroundExecutionRequestSchema(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    component_key: str = Field(..., min_length=1)
    session_id: int = Field(..., gt=0)
    inputs: Dict[str, Any] = Field(default_factory=dict)
    input_files: List[str] = Field(default_factory=list)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    profile_id: Optional[str] = None
    is_sandbox: bool = True


class PipelineConstructorPreflightRequestSchema(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    pipeline_definition: PipelineDefinitionSchema
    session_id: int = Field(..., gt=0)
    local_file_paths: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_targets(self) -> "PipelineConstructorPreflightRequestSchema":
        if not self.local_file_paths:
            raise ValueError("local_file_paths must contain at least one file")
        return self
