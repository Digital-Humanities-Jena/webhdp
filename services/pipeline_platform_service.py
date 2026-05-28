"""Support contract for the native WebHDP pipeline/component platform."""

from __future__ import annotations

from typing import Any


OFFICIAL_PIPELINE_PLATFORM_ID = "webhdp_native_pipeline_platform"


def get_pipeline_platform_contract() -> dict[str, Any]:
    return {
        "official_platform_id": OFFICIAL_PIPELINE_PLATFORM_ID,
        "status": "active",
        "summary": (
            "WebHDP officially supports native component import/validation, native pipeline execution, "
            "and native playground execution without a standalone HDP-Server component manager or runner."
        ),
        "decision": {
            "retain_native_component_registry": True,
            "retain_native_playground": True,
            "retain_v1_pipeline_compatibility_wrappers": True,
            "retire_legacy_component_manager_api": True,
            "retire_legacy_component_runner_server_api": True,
            "retire_legacy_pipeline_manager_api": True,
            "retire_legacy_cli_http_route": True,
            "retire_generic_hdp_settings_utils_api": True,
        },
        "supported_surfaces": {
            "components_list": "/api/v2/components",
            "components_validate": "/api/v2/components/validate",
            "components_import": "/api/v2/components/import",
            "pipelines_list": "/api/v2/pipelines",
            "pipelines_validate": "/api/v2/pipelines/validate",
            "pipeline_versions_create": "/api/v2/pipelines/<identifier>/versions",
            "pipeline_execute": "/api/v2/pipelines/<identifier>/execute",
            "pipeline_run_status": "/api/v2/runs/<run_id>",
            "playground_execute": "/api/v2/playground/execute",
            "playground_run_status": "/api/v2/playground/runs/<run_id>",
        },
        "compatibility_surfaces": [
            {
                "id": "v1_pipeline_routes",
                "status": "supported_compatibility_wrapper",
                "surfaces": [
                    "/api/v1/pipelines",
                    "/api/v1/pipelines/<identifier>",
                    "/api/v1/pipelines/<identifier>/execute_on_local_files",
                    "/api/v1/pipelines/executions/<execution_uuid>/status",
                ],
                "backed_by": "native_pipeline_service",
            }
        ],
        "legacy_family_inventory": [
            {
                "id": "legacy_component_manager_api",
                "status": "retired",
                "legacy_patterns": [
                    "/pipeline_components",
                    "/pipeline_components/<component_name>/install",
                    "/pipeline_components/<component_name>/update",
                    "/pipeline_components/uninstall",
                    "/pipeline_components/download",
                    "/pipeline_components/remote",
                    "/pipeline_components/<component_name>/config",
                    "/pipeline_components/<component_name>/templates",
                    "/pipeline_components/storage",
                ],
                "replacement_scope": "partial_native_replacement",
            },
            {
                "id": "legacy_component_runner_server_api",
                "status": "retired",
                "legacy_patterns": [
                    "/components/<component_name>/run",
                    "/components/logs/<execution_id>",
                    "/components/<execution_id>/cancel",
                    "/components/executions/<execution_id>/status",
                ],
                "replacement_scope": "native_pipeline_execute_and_playground",
            },
            {
                "id": "legacy_pipeline_manager_api",
                "status": "retired",
                "legacy_patterns": [
                    "/pipelines",
                    "/pipelines/<identifier>",
                    "/pipelines/import",
                    "/pipelines/<identifier>/export",
                    "/pipelines/<identifier>/execute",
                    "/pipelines/<identifier>/execute_on_local_files",
                    "/executions/<execution_uuid>/status",
                    "/pipelines/<identifier>/metadata_mapping",
                ],
                "replacement_scope": "native_pipeline_registry_with_explicitly_retired_non-native_admin_helpers",
            },
            {
                "id": "legacy_cli_http_route",
                "status": "retired",
                "legacy_patterns": [
                    "/cli/pipelines/<pipeline_name>/execute",
                ],
                "replacement_scope": "component_import_then_native_execution",
            },
            {
                "id": "legacy_hdp_settings_utils_api",
                "status": "retired",
                "legacy_patterns": [
                    "/config/get",
                    "/config/save",
                    "/utils/*",
                ],
                "replacement_scope": "webhdp_admin_and_tools_surfaces",
            },
        ],
        "replacement_surfaces": {
            "admin_configuration": [
                "/api/v1/admin/pipelines/<pipeline_id>/config",
                "/api/v1/admin/zenodo-community-config",
                "/api/v1/admin/storage-config",
                "/api/v1/admin/modality-config",
                "/api/v1/admin/storage-status",
            ],
            "operability": [
                "/api/v1/tools/context",
                "/api/v1/tools/hpc-diagnostics",
                "/api/v1/health",
            ],
        },
        "retired_surfaces": [
            {
                "id": "legacy_component_manager_api",
                "status": "retired",
                "replacement": [
                    "/api/v2/components",
                    "/api/v2/components/validate",
                    "/api/v2/components/import",
                ],
                "reason": "Component registry/import is now handled directly by the native pipeline platform.",
            },
            {
                "id": "legacy_component_runner_server_api",
                "status": "retired",
                "replacement": [
                    "/api/v2/pipelines/<identifier>/execute",
                    "/api/v2/playground/execute",
                ],
                "reason": "Standalone runner-server execution is replaced by native pipeline and playground execution.",
            },
            {
                "id": "legacy_pipeline_manager_api",
                "status": "retired",
                "replacement": [
                    "/api/v2/pipelines",
                    "/api/v2/pipelines/validate",
                    "/api/v2/pipelines/<identifier>",
                    "/api/v2/pipelines/<identifier>/versions",
                    "/api/v2/pipelines/<identifier>/execute",
                    "/api/v2/runs/<run_id>",
                    "/api/v1/pipelines",
                    "/api/v1/pipelines/<identifier>",
                    "/api/v1/pipelines/<identifier>/execute_on_local_files",
                    "/api/v1/pipelines/executions/<execution_uuid>/status",
                ],
                "reason": (
                    "The legacy HDP-Server pipeline manager family is retired. Native list/detail/validate/version/execute "
                    "surfaces replace the supported workflow, while direct import/export and metadata-mapping mutation "
                    "endpoints are not carried forward as standalone APIs."
                ),
            },
            {
                "id": "legacy_cli_http_route",
                "status": "retired",
                "replacement": [
                    "Import a manifest-backed component through /api/v2/components/import",
                    "Execute it through /api/v2/playground/execute or /api/v2/pipelines/<identifier>/execute",
                ],
                "reason": "CLI integrations are now modeled as imported native components instead of ad hoc HTTP-driven CLI routes.",
            },
            {
                "id": "legacy_hdp_settings_utils_api",
                "status": "retired",
                "replacement": [
                    "/api/v1/admin/pipelines/<pipeline_id>/config",
                    "/api/v1/admin/storage-config",
                    "/api/v1/admin/modality-config",
                    "/api/v1/tools/context",
                    "/api/v1/tools/hpc-diagnostics",
                ],
                "reason": "Configuration and operability are now exposed through WebHDP-specific admin and tooling surfaces.",
            },
        ],
        "notes": [
            "Native adapters may still execute local CLI, container CLI, or legacy python entrypoints, but they run inside the native component platform.",
            "The native platform is the only supported place for component import, execution, and playground experimentation.",
            "No standalone HDP-Server component manager or runner process is required for supported WebHDP operation.",
            "Legacy HDP-Server pipeline manager import/export and metadata-mapping mutation routes are explicitly retired rather than re-exposed.",
        ],
    }
