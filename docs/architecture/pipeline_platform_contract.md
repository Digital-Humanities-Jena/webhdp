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
- `/api/v2/pipelines/<identifier>/readiness`
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

## Submission readiness

`POST /api/v2/pipelines/<identifier>/readiness` requires session edit permission
and a mutable session. It accepts the execution selection (`session_id` and
`local_file_paths`, `record_ids`, or `execution_items`), `is_sandbox`,
`abort_on_critical_error`, and optional `expected_version`. It returns HTTP 200
for a completed check, including a blocked result, with `ready`, `blockers`,
`unverified`, selected/skipped counts, scope, pipeline version, and a signed
`readiness_token` when ready. Blockers carry an existing workflow `route` and
optional source/step labels. The token contains hashes rather than source paths
or descriptive metadata.

The check is read-only and invokes no remote service, subprocess, or allocation.
Source resolution and component contracts are shared with execution. Known
local failures block; inputs produced by earlier steps and remote requirements
are deferred explicitly. Generated exports retain their separate validation and
upload-eligibility checks.

Native synchronous and asynchronous execution repeat readiness for new requests.
`readiness_token` is optional for compatibility callers but, when supplied, must
match current state and be at most one hour old. Blockers return HTTP 400 with
`error.details.readiness`; invalid, expired, or changed tokens return HTTP 409
with `error.details.readiness_stale`. Accepted identical `request_id` retries
reconnect to the persisted run before these checks. Queued workers retain the
pipeline version and metadata snapshot and check saved source hashes before
registration. Private readiness state is excluded from run API payloads.

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
