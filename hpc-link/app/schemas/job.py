from typing import List, Optional, Dict
import re

from pydantic import BaseModel, Field, field_validator

from app.security import validate_slurm_resource_token, validate_slurm_time_string


_SLURM_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_MEMORY_RE = re.compile(r"^[1-9][0-9]{0,5}[KMGTP]?$")
_MODULE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+/-]{0,127}$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

class JobConfig(BaseModel):
    """Configuration for a SLURM batch job."""

    # Core SLURM directives
    job_name: str = Field(..., description="Name of the job")
    partition: str = Field("partition-a", description="SLURM partition")
    time_limit: str = Field("01:00:00", description="Time limit (HH:MM:SS)")
    nodes: int = Field(1, description="Number of nodes")
    tasks_per_node: int = Field(1, description="Tasks per node")
    cpus_per_task: int = Field(1, description="CPUs per task")
    memory: str = Field("8G", description="Memory per node (e.g., 8G)")

    # GPU
    gpu_type: Optional[str] = Field(None, description="GPU type")
    gpu_count: int = Field(0, description="Number of GPUs")

    # I/O
    output_path: str = Field("slurm-%j.out", description="Standard output path")
    error_path: str = Field("slurm-%j.err", description="Standard error path")
    working_dir: Optional[str] = Field(None, description="Working directory")

    # Execution
    modules: List[str] = Field(default_factory=list, description="Modules to load")
    environment_vars: Dict[str, str] = Field(default_factory=dict, description="Environment variables to export")
    commands: List[str] = Field(..., description="List of commands to execute")

    # UV Integration
    use_uv: bool = Field(False, description="Use UV for environment management")
    uv_install: bool = Field(False, description="Run 'uv sync' before execution")


    # Integration
    # email? webhook? (Future)
    webhook_url: Optional[str] = Field(None, description="URL to call when job completes")

    @field_validator("job_name")
    @classmethod
    def validate_job_name(cls, value: str) -> str:
        if not _SLURM_NAME_RE.fullmatch(str(value or "")):
            raise ValueError("job_name may only contain letters, numbers, dot, underscore, and dash")
        return value

    @field_validator("partition", "gpu_type")
    @classmethod
    def validate_resource_token(cls, value: Optional[str], info) -> Optional[str]:
        try:
            return validate_slurm_resource_token(value, info.field_name)
        except Exception as exc:
            raise ValueError(str(getattr(exc, "detail", exc))) from exc

    @field_validator("time_limit")
    @classmethod
    def validate_time_limit(cls, value: str) -> str:
        try:
            return validate_slurm_time_string(value)
        except Exception as exc:
            raise ValueError(str(getattr(exc, "detail", exc))) from exc

    @field_validator("memory")
    @classmethod
    def validate_memory(cls, value: str) -> str:
        text = str(value or "").strip()
        if not _MEMORY_RE.fullmatch(text):
            raise ValueError("memory must be a numeric SLURM memory value with an optional K/M/G/T/P suffix")
        return text

    @field_validator("nodes", "tasks_per_node", "cpus_per_task", "gpu_count")
    @classmethod
    def validate_positive_bounds(cls, value: int, info):
        minimum = 0 if info.field_name == "gpu_count" else 1
        if value < minimum:
            raise ValueError(f"{info.field_name} must be >= {minimum}")
        if value > 256:
            raise ValueError(f"{info.field_name} is unreasonably large")
        return value

    @field_validator("modules")
    @classmethod
    def validate_modules(cls, values: List[str]) -> List[str]:
        for value in values or []:
            if not _MODULE_RE.fullmatch(str(value or "")):
                raise ValueError("module names contain unsafe characters")
        return values

    @field_validator("environment_vars")
    @classmethod
    def validate_environment_vars(cls, values: Dict[str, str]) -> Dict[str, str]:
        for key, value in (values or {}).items():
            if not _ENV_NAME_RE.fullmatch(str(key or "")):
                raise ValueError("environment variable names must be valid shell identifiers")
            if "\x00" in str(value) or len(str(value)) > 4096:
                raise ValueError("environment variable values are invalid")
        return values

    @field_validator("commands")
    @classmethod
    def validate_commands(cls, values: List[str]) -> List[str]:
        if not values:
            raise ValueError("commands must not be empty")
        for command in values:
            text = str(command or "")
            if "\x00" in text or len(text) > 8192:
                raise ValueError("commands contain invalid content")
        return values
