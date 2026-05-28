# Sessions, Records, And Provenance Workflows

This document covers the workflows that happen after sessions exist: browsing,
downloads, provenance, versioning, batch operations, and dataset integrity.

## Overview

These workflows help users and reviewers understand what WebHDP produced after
ingestion or processing. They cover session reopening, record review, file and
lineage inspection, provenance reports, `.hdpc` downloads, draft/version
control, batch operations, and dataset integrity checks. The later sections are
for maintainers optimizing state, reports, and record-heavy views.

## Use Cases

- Reopen, resume, and inspect session workspace and workflow state.
- Review records, files, lineage, traceability, Zenodo status, and provenance.
- Download `.hdpc`, shared `.hdpc`, metadata, and cloud artifacts.
- Manage versioning, draft control, batch operations, cross-session exploration, and dataset integrity.

## Session Governance And Resume

Primary actor: session owner, collaborator, moderator, or administrator.

Entry points:
- API: `/api/v1/sessions`
- API: `/api/v1/sessions/<session_id>`
- API: `/api/v1/sessions/<session_id>/workspace`
- API: `/api/v1/sessions/<session_id>/workspace-summary`
- API: `/api/v1/sessions/<session_id>/workflow-state`
- API: `/api/v1/sessions/<session_id>/progress`
- API: `/api/v1/sessions/<session_id>/resume`
- API: `/api/v1/sessions/<session_id>/audit-events`

Workflow:
1. List accessible sessions.
2. Inspect a session and its workspace context.
3. Persist or restore workflow state.
4. Poll progress for upload or processing state.
5. Resume an interrupted workflow.
6. Review audit events when governance context is needed.

Complete when:
- The session can be reopened at the correct workflow step.

## Record Browser And Record Detail

Primary actor: session owner or reviewer.

Entry points:
- UI: `/sessions/:sessionId/records`
- UI: `/sessions/:sessionId/records/:recordId`
- API: `/api/v1/sessions/<session_id>/records`
- API: `/api/v1/sessions/<session_id>/records/<local_record_id>`
- API: `/api/v1/sessions/<session_id>/records/<local_record_id>/files`
- API: `/api/v1/sessions/<session_id>/records/<local_record_id>/traceability`
- API: `/api/v1/sessions/<session_id>/records/<local_record_id>/lineage`
- API: `/api/v1/sessions/<session_id>/records/<local_record_id>/zenodo-status`
- API: `/api/v1/sessions/<session_id>/published-records`
- API: `/api/v1/sessions/<session_id>/files`
- API: `/api/v1/sessions/<session_id>/files/<file_id>/hierarchy`
- API: `/api/v1/sessions/<session_id>/nodes`

Workflow:
1. Open a session's record list.
2. Inspect record metadata, source files, generated files, and Zenodo state.
3. Review file hierarchy and node structure.
4. Trace source mappings and record lineage.

Complete when:
- Record state, files, metadata, and publication status are understood.

## Provenance Review

Primary actor: reviewer, auditor, or operator.

Entry points:
- UI: `/sessions/:sessionId/provenance-report`
- API: `/api/v1/sessions/<session_id>/provenance-report`

Workflow:
1. Build a session-level provenance report.
2. Inspect source inputs, process steps, generated artifacts, metadata sources, and Zenodo evidence.
3. Use provenance to verify reproducibility after processing or import.

Complete when:
- The session's scientific and technical traceability has been reviewed.

## Cross-Session Explorer

Primary actor: reviewer or operator.

Entry points:
- UI: `/records/explorer`
- API: `/api/v1/sessions/records/explorer`

Workflow:
1. Search records across accessible sessions.
2. Filter by session, owner, record state, or metadata.
3. Open records for detailed review.

Complete when:
- The target records are found or confirmed absent across accessible inventories.

## Import And Downloads

Primary actor: session owner, administrator, or reviewer.

Entry points:
- API: `/api/v1/sessions/import-hdpc`
- API: `/api/v1/admin/users/<user_id>/hdpc/import`
- API: `/api/v1/sessions/<session_id>/hdpc`
- API: `/api/v1/sessions/<session_id>/hdpc/shared`
- API: `/api/v1/sessions/<session_id>/zenodo_metadata`
- API: `/api/v1/sessions/<session_id>/cloud-downloads`
- API: `/api/v1/sessions/<session_id>/cloud-downloads/<mirror_id>`

Workflow:
1. Import an existing `.hdpc` package for the current user or target user.
2. Open the resulting session and verify records.
3. Download raw `.hdpc`, shared `.hdpc`, Zenodo metadata, or mirrored cloud artifacts according to access policy.

Complete when:
- Imported records are inspectable or requested session artifacts are downloaded.

## Record Versioning And Draft Control

Primary actor: session owner or authorized publisher.

Entry points:
- API: `/api/v1/sessions/<session_id>/versioning/match-files`
- API: `/api/v1/sessions/<session_id>/concepts/<concept_rec_id>/latest-files`
- API: `/api/v1/sessions/<session_id>/records/<local_record_id>/create-version`
- API: `/api/v1/sessions/<session_id>/records/<local_record_id>/discard-draft`
- API: `/api/v1/sessions/<session_id>/zenodo/uploadable-files`
- API: `/api/v1/sessions/<session_id>/zenodo/uploads-by-tab`

Workflow:
1. Match selected files against published concepts.
2. Inspect latest files for a concept.
3. Create a new Zenodo version when allowed.
4. Discard draft records when cleanup is needed.
5. Review uploadable files and upload grouping.

Complete when:
- Versioning or draft cleanup is reflected in the local record and remote Zenodo state.

## Session Batch Operations

Primary actor: session owner or authorized publisher.

Entry points:
- API: `/api/v1/sessions/<session_id>/operations/summary`
- API: `/api/v1/sessions/<session_id>/batch-operations`
- API: `/api/v1/sessions/<session_id>/batch-operations/<task_id>`
- Celery: `execute_session_batch_operation_task`

Supported operation types:
- `create_drafts`
- `discard_drafts`
- `upload_files`
- `publish_records`
- `remove_files`

Workflow:
1. Inspect operation eligibility and summary.
2. Select target record or file IDs.
3. Queue a serial batch operation.
4. Poll task progress and review results.

Complete when:
- The task reports completed or completed-with-errors with per-target results.

## Dataset Integrity

Primary actor: publishing user, reviewer, moderator, or administrator.

Entry points:
- UI: `/datasets/:datasetKey?`
- API: `/api/v1/datasets`
- API: `/api/v1/datasets/conflict-review`
- API: `/api/v1/datasets/duplicate-check`
- API: `/api/v1/datasets/<dataset_key>/summary`
- API: `/api/v1/datasets/<dataset_key>/duplicates`
- API: `/api/v1/datasets/<dataset_key>/export`

Workflow:
1. List detected datasets.
2. Review dataset conflicts and duplicate candidates.
3. Run duplicate checks for specific inputs.
4. Export dataset integrity results.

Complete when:
- Conflicts, duplicates, and export data are available for review or remediation.

## Prerequisites And Permissions

- Session, record, provenance, download, and batch-operation workflows require access to the target session.
- Mutating operations such as resume, workspace updates, draft discard, version creation, and batch operations require edit permission.
- Admin import for another user requires administrator access.
- Dataset integrity review may require moderator or administrator visibility for cross-user conflicts.

## Inputs, Outputs, And State

| Input | Output | State To Watch |
|---|---|---|
| Session ID and workspace state | Reopenable workflow context | workflow state, workspace metadata, progress |
| Record ID or record filters | Record detail, files, lineage, and traceability | local record status, generated files, Zenodo status |
| Session ID | Provenance report | process steps, source mappings, artifact evidence |
| `.hdpc` import or download request | Imported session or downloadable artifact | hdpc path, shared export, cloud mirror state |
| Batch operation request | Batch task and per-target results | task status, operation history, record state |
| Dataset key or duplicate-check input | Dataset integrity report or export | conflicts, duplicates, export payload |

## Failure And Recovery

- Missing session access should be diagnosed through ownership, collaboration, and admin/moderator policy.
- Broken `.hdpc` imports should be checked against schema compatibility and file availability.
- Versioning failures should distinguish local eligibility from remote Zenodo draft or concept state.
- Batch operation failures should be reviewed per target rather than rerunning the whole set blindly.
- Provenance gaps should be traced to source registration, pipeline outputs, and `.hdpc` evidence.

## Optimization Targets

- Keep record lists and cross-session explorer queries fast for large inventories.
- Reduce cost of provenance report generation on record-heavy sessions.
- Make `.hdpc` downloads and shared exports stream safely for large files.
- Keep batch operations serial enough for Zenodo safety but observable enough for users.
- Improve dataset duplicate and conflict review performance.

## Verification Checklist

- Verify session list/detail/workspace/workflow-state/progress/resume and audit events.
- Verify record list/detail/files/hierarchy/traceability/lineage/Zenodo status.
- Verify provenance report and cross-session explorer.
- Verify `.hdpc`, shared `.hdpc`, Zenodo metadata, cloud downloads, and imports.
- Verify version match, create version, discard draft, uploadable files, and batch operations.
- Verify dataset list, conflict review, duplicate check, summary, duplicates, and export.

Related docs:
- `docs/architecture/hdpc_schema.md`
- `docs/guides/video_guides/publication_and_processing.md`

## Codebase Starting Points

- Dashboard/session views: `frontend/src/views/dashboard/`
- Record and provenance views: `frontend/src/views/dashboard/RecordDetailView.vue`, `frontend/src/views/dashboard/SessionProvenanceReportView.vue`
- Session routes: `routes/session_routes.py`
- Dataset integrity routes: `routes/dataset_routes.py`
- `.hdpc` and record services: `services/hdpc_schema_service.py`, `services/hdpc_local_service.py`, `services/hdpc_import_service.py`, `services/hdpc_provenance_service.py`
- Batch operation task: `tasks.py`
- Database models and schema docs: `database/models.py`, `docs/architecture/hdpc_schema.md`
