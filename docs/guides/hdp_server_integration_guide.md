# HDP-Server Removal Note

This document is retained only as historical context.

## Current status

WebHDP no longer integrates with HDP-Server at runtime.

Primary runtime behavior uses:

- local `.hdpc` project state
- native Zenodo lifecycle helpers
- native component import and pipeline execution
- native playground execution

## What replaced the old integration boundary

- Metadata workflow contract:
  `../architecture/metadata_workflow_contract.md`

- Native pipeline/platform contract:
  `../architecture/pipeline_platform_contract.md`

- Current architecture overview:
  `../architecture/system_architecture.md`

## Superior native replacements now in WebHDP

Useful HDP-Server ideas were merged into higher-level WebHDP-native endpoints rather than copied route-for-route:

- Session intelligence
  - `GET /api/v1/sessions/<id>/workspace-summary`
  - `GET /api/v1/sessions/<id>/records/<record_id>/lineage`
  - `GET /api/v1/sessions/<id>/records/<record_id>/zenodo-status`
  - `GET /api/v1/sessions/<id>/operations/summary`
- Native session batch orchestration
  - `POST /api/v1/sessions/<id>/batch-operations`
  - `GET /api/v1/sessions/<id>/batch-operations`
  - `GET /api/v1/sessions/<id>/batch-operations/<task_id>`
- Admin observability
  - `GET /api/v1/admin/observability/credentials-status`
  - `GET /api/v1/admin/observability/api-activity`
  - `POST /api/v1/admin/observability/checks/<check_id>`

These are the preferred replacements for the legacy `data_query`, `batch_action`, operability, credentials, and API-log concepts that still add product value.

## Historical note

Older WebHDP versions delegated scanning, inspect/load behavior, record preparation, and pipeline execution to HDP-Server.
That deployment model has been removed.
