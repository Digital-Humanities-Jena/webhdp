"""Application configuration using pydantic-settings."""
from functools import lru_cache
import json
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # HPC Connection
    hpc_host: str = "hpc-login.example.edu"
    hpc_user: str = "hpc-user"
    ssh_key_path: str = "/run/secrets/ssh_key"
    ssh_known_hosts_path: str | None = "/run/secrets/ssh_known_hosts"

    # Filesystem Confinement
    hpc_data_root: str = "/srv/hpc-link/data"
    hpc_apps_root: str = "/srv/hpc-link/apps"


    # Jump Host (ProxyJump) settings - optional for direct compute node access
    jump_host: str | None = None  # e.g., "hpc-login.example.edu"
    jump_host_user: str | None = None  # Defaults to hpc_user if not set
    jump_host_key_path: str | None = None  # Defaults to ssh_key_path if not set

    # Terminal session settings
    terminal_timeout_seconds: int = 3600  # 1 hour default
    terminal_cols: int = 80
    terminal_rows: int = 24

    # SLURM defaults
    default_partition: str = "partition-a"
    default_gpu_type: str = "accelerator-a"
    default_gpu_count: int = 1
    default_time_limit: str = "00:10:00"

    # Application gateway defaults
    vllm_binary: str = "/srv/hpc-link/apps/vllm/venv/bin/vllm"
    vllm_base_port: int = 18000
    vllm_max_tokens: int = 512
    vllm_models_json: str = (
        '[{"id":"example-model","label":"Example Model","path":"/srv/hpc-link/apps/models/example-model","max_model_len":4096}]'
    )
    pi3_python: str = "/srv/hpc-link/apps/pi3/venv/bin/python"
    pi3_repo_path: str = "/srv/hpc-link/apps/pi3/runtime/Pi3"
    pi3_default_partition: str = "partition-a"
    pi3_cuda_module: str | None = None
    marker_binary: str = "/srv/hpc-link/apps/marker/venv/bin/marker_single"
    marker_default_partition: str = "partition-a"
    marker_cuda_module: str | None = None
    marker_torch_device: str = "auto"
    webhdp_default_partition: str = "partition-a"
    webhdp_cpus_per_task: int = Field(default=8, ge=1, le=256)
    webhdp_memory_mb: int = Field(default=32768, ge=1024)
    webhdp_cuda_module: str | None = None
    webhdp_component_runtime_root: str = "/srv/hpc-link/apps/webhdp/runtime"
    webhdp_component_runner: str = "/srv/hpc-link/apps/webhdp/bin/webhdp_component_runner.py"
    webhdp_sessions_registry_path: str = "/srv/hpc-link/data/webhdp_sessions.json"
    webhdp_fast_renderer_command: str | None = (
        "WEBHDP_COMPONENT_RUNTIME_ROOT=/srv/hpc-link/apps/webhdp/runtime "
        "python3 /srv/hpc-link/apps/webhdp/bin/webhdp_component_runner.py"
    )
    webhdp_any_to_usdz_command: str | None = (
        "WEBHDP_COMPONENT_RUNTIME_ROOT=/srv/hpc-link/apps/webhdp/runtime "
        "python3 /srv/hpc-link/apps/webhdp/bin/webhdp_component_runner.py"
    )
    webhdp_preflight_command: str = (
        "WEBHDP_COMPONENT_RUNTIME_ROOT=/srv/hpc-link/apps/webhdp/runtime "
        "python3 /srv/hpc-link/apps/webhdp/bin/webhdp_component_runner.py --preflight"
    )
    sinfo_partitions: str = ""

    # Logging
    log_level: str = "INFO"
    environment: str = "development"

    # API
    api_title: str = "HPC Link API"
    api_version: str = "0.1.0-alpha.2"
    api_key: str | None = None  # If set, requires X-API-Key header
    legacy_api_key_auth_enabled: bool = False
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]  # List of allowed origins
    allow_ws_query_token_auth: bool = False
    login_max_attempts_per_window: int = 5
    login_attempt_window_seconds: int = 300
    login_lockout_seconds: int = 900

    # User authentication and authorization
    auth_db_path: str = "/tmp/hpc-link/auth.db"
    auth_token_secret: str = "change-me-in-production"
    auth_token_ttl_minutes: int = 480
    admin_username: str = "admin"
    admin_password: str = "change-me-admin-password"

    # Mocking for local development/testing
    mock_hpc: bool = False
    upload_session_ttl_seconds: int = 1800
    upload_max_active_sessions: int = 200
    upload_max_active_sessions_per_user: int = 20
    upload_max_chunk_bytes: int = 8 * 1024 * 1024
    upload_max_file_bytes: int = 2 * 1024 * 1024 * 1024
    upload_pi3_max_body_bytes: int = 30 * 1024 * 1024
    upload_marker_max_body_bytes: int = 140 * 1024 * 1024
    webhdp_component_test_max_body_bytes: int = 32 * 1024 * 1024
    webhdp_cloud_stage_max_files: int = 100
    webhdp_cloud_stage_max_file_bytes: int = 2 * 1024 * 1024 * 1024
    webhdp_component_sif_max_bytes: int = 10 * 1024 * 1024 * 1024
    legacy_api_key_allowed_partitions: Annotated[list[str], NoDecode] = []
    legacy_api_key_allowed_gpu_types: Annotated[list[str], NoDecode] = []
    legacy_api_key_max_duration_minutes: int = 10080
    legacy_api_key_max_gpu_count: int = 16

    @field_validator(
        "cors_origins",
        "legacy_api_key_allowed_partitions",
        "legacy_api_key_allowed_gpu_types",
        mode="before",
    )
    @classmethod
    def parse_string_list(cls, value):
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if not normalized:
            return []
        if normalized.startswith("["):
            return json.loads(normalized)
        return [item.strip() for item in normalized.split(",") if item.strip()]

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
