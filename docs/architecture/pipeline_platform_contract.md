# Pipeline Platform Contract

## Official platform

WebHDP officially supports the native pipeline/component platform.

Supported core capabilities:

- native component listing, validation, and import
- native pipeline definition validation and versioning
- native pipeline execution
- native playground execution
- compatibility wrappers for older WebHDP pipeline routes backed by the native platform

## Supported native surfaces

- `/api/v2/components`
- `/api/v2/components/validate`
- `/api/v2/components/import`
- `/api/v2/pipelines`
- `/api/v2/pipelines/validate`
- `/api/v2/pipelines/<identifier>/versions`
- `/api/v2/pipelines/<identifier>/execute`
- `/api/v2/runs/<run_id>`
- `/api/v2/playground/execute`
- `/api/v2/playground/runs/<run_id>`

## Compatibility surfaces

These remain supported as wrappers over the native platform:

- `/api/v1/pipelines`
- `/api/v1/pipelines/<identifier>`
- `/api/v1/pipelines/<identifier>/execute_on_local_files`
- `/api/v1/pipelines/executions/<execution_uuid>/status`

## Retired HDP-Server families

- Legacy component-manager API
  Replacement: `/api/v2/components`, `/api/v2/components/validate`, `/api/v2/components/import`

- Legacy component-runner server API
  Replacement: `/api/v2/pipelines/<identifier>/execute`, `/api/v2/playground/execute`

- Legacy pipeline-manager API
  Replacement for supported workflows:
  - `/api/v2/pipelines`
  - `/api/v2/pipelines/validate`
  - `/api/v2/pipelines/<identifier>`
  - `/api/v2/pipelines/<identifier>/versions`
  - `/api/v2/pipelines/<identifier>/execute`
  - `/api/v2/runs/<run_id>`
  - `/api/v1/pipelines`
  - `/api/v1/pipelines/<identifier>`
  - `/api/v1/pipelines/<identifier>/execute_on_local_files`
  - `/api/v1/pipelines/executions/<execution_uuid>/status`
  Explicitly retired rather than ported:
  - `/pipelines/import`
  - `/pipelines/<identifier>/export`
  - `/pipelines/<identifier>/metadata_mapping`

- Legacy CLI HTTP route
  Replacement: import a manifest-backed component and execute it through the native platform

- Generic HDP-Server settings/utils API families
  Replacement:
  - `/api/v1/admin/pipelines/<pipeline_id>/config`
  - `/api/v1/admin/zenodo-community-config`
  - `/api/v1/admin/storage-config`
  - `/api/v1/admin/modality-config`
  - `/api/v1/admin/storage-status`
  - `/api/v1/tools/context`
  - `/api/v1/tools/hpc-diagnostics`
  - `/api/v1/health`

## Notes

- Native adapters may still launch local CLI, container CLI, or legacy python entrypoints.
- Those execution profiles are supported only through the native component platform, not through standalone HDP-Server management APIs.
- The old HDP-Server pipeline manager family is not considered a parity target anymore; only the native replacement surfaces above are supported.
