# Zenodo Retrieval And Communities Workflows

This document covers workflows that operate on existing Zenodo accounts,
retrieval-generated inventories, community membership, moderation, and migration.

## Overview

These workflows are for managing records that already exist in Zenodo or need
community-level changes. They cover account retrieval, retrieval maintenance,
batch community operations, moderation, migration, and supporting scripts. The
early sections explain what each operation does; the lower sections focus on
rate limits, checkpoints, recovery, and high-volume optimization.

## Use Cases

- Retrieve large Zenodo account inventories into explorer-only `.hdpc` shards.
- Harvest public Zenodo OAI-PMH metadata without credentials.
- Schedule, pause, resume, compact, retain, search, or export retrieval results.
- Run community append/remove, moderation, and migration workflows in batches.
- Use scripts and services for controlled high-volume Zenodo operations.

## Zenodo Account Retrieval

Primary actor: authenticated user with an accessible Zenodo credential.

Entry points:
- UI: `/tools/zenodo-account-retrieval`
- API: `/api/v1/tools/zenodo-account-retrieval/context`
- API: `/api/v1/tools/zenodo-account-retrieval/preflight`
- API: `/api/v1/tools/zenodo-account-retrieval/jobs`
- API: `/api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>`
- Celery: `execute_zenodo_account_retrieval`

Retrieval modes:
- full account inventory
- bounded retrieval with `max_records`
- historical backfill with date filters
- incremental retrieval from a previous successful collection

Workflow:
1. Select an accessible credential and environment.
2. Run preflight for credential, scope, worker, and date-window assumptions.
3. Start a retrieval job.
4. Harvest published and draft depositions with window splitting and dedupe.
5. Persist explorer-only `.hdpc` shard sessions.
6. Monitor progress, rate-limit waits, split counts, and stale-worker diagnostics.

Complete when:
- The retrieval job reaches `SUCCESS`, `FAILURE`, `PAUSED`, or `CANCELLED` with checkpoint state persisted.

## Zenodo OAI Harvest

Primary actor: authenticated user who needs a public, no-credential Zenodo
community or repository metadata harvest.

Entry points:
- UI: `/tools/zenodo-oai-harvest`
- API: `/api/v1/tools/zenodo-oai-harvest/context`
- API: `/api/v1/tools/zenodo-oai-harvest/preflight`
- API: `/api/v1/tools/zenodo-oai-harvest/jobs`
- API: `/api/v1/tools/zenodo-oai-harvest/jobs/<harvest_id>`
- API: `/api/v1/tools/zenodo-oai-harvest/jobs/<harvest_id>/records`
- API: `/api/v1/tools/zenodo-oai-harvest/jobs/<harvest_id>/detectors`
- API: `/api/v1/tools/zenodo-oai-harvest/jobs/<harvest_id>/export/<export_format>`
- Celery: `execute_zenodo_oai_harvest`

Workflow:
1. Select a Zenodo OAI set, metadata prefix, and optional date bounds.
2. Start a harvest job.
3. Page through public OAI-PMH records and persist explorer-only `.hdpc` shards.
4. Search, inspect, export, compact, schedule, or delete the resulting collection.

Complete when:
- The harvest job reaches a terminal state and the public metadata inventory is available as explorer-only shards or an export.

## Retrieval Control, Search, Export, Compaction, And Scheduling

Primary actor: retrieval owner or administrator.

Entry points:
- API: `/api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>/pause`
- API: `/api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>/resume`
- API: `/api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>/cancel`
- API: `/api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>/records`
- API: `/api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>/compact`
- API: `/api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>/compacted-shards`
- API: `/api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>/retention`
- API: `/api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>/schedule`
- API: `/api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>/schedule/run-now`
- API: `/api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>/export/<export_format>`
- API: `DELETE /api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>`
- Celery: `execute_due_zenodo_account_retrieval_schedules`

Workflow:
1. Pause, resume, cancel, or delete a retrieval job as needed.
2. Search records across completed retrieval shards.
3. Export manifest, CSV, or shard archive.
4. Compact many small shards into fewer compacted shards.
5. Save retention preferences.
6. Configure daily, weekly, or monthly incremental schedules.
7. Run a configured schedule immediately when needed.

Complete when:
- Collection maintenance state matches the intended operational policy.

## Zenodo Batch Community Operations

Primary actor: moderator or administrator.

Entry points:
- UI: `/tools/zenodo-batch-operations`
- API: `/api/v1/tools/zenodo-batch-operations/records`
- API: `/api/v1/tools/zenodo-batch-operations/community-operations`
- API: `/api/v1/tools/zenodo-batch-operations/history`
- API: `/api/v1/tools/zenodo-batch-operations/tasks/<task_id>`
- Celery: `execute_zenodo_batch_community_operation`

Supported operations:
- append community if missing
- remove one community
- remove all communities

Workflow:
1. Search editable records across accessible sessions.
2. Filter by status, owner, community, creator, date, or environment.
3. Select eligible records.
4. Queue a serial Zenodo-safe community operation.
5. Poll task progress and review per-record results.

Complete when:
- The batch task reports completed with succeeded, unchanged, ineligible, and failed counts.

## Community Moderation

Primary actor: moderator or administrator.

Entry points:
- UI: `/tools/community-moderation`
- API: `/api/v1/tools/community-moderation/requests`
- API: `/api/v1/tools/community-moderation/actions`
- API: `/api/v1/tools/community-moderation/history`
- API: `/api/v1/tools/community-moderation/tasks/<task_id>`
- Celery: `execute_community_moderation_batch`

Supported actions:
- accept selected community requests
- decline selected community requests

Workflow:
1. Resolve the target community from explicit input, institution policy, or global override.
2. Fetch and filter open moderation requests.
3. Select requests.
4. Queue an accept or decline batch with optional note.
5. Poll task progress and review results.

Complete when:
- Selected requests have been accepted, declined, or reported as failed.

## Community Migration

Primary actor: moderator or administrator.

Entry points:
- UI: `/tools/community-migration`
- API: `/api/v1/tools/community-migrations/context`
- API: `/api/v1/tools/community-migrations/plan`
- API: `/api/v1/tools/community-migrations/jobs`
- API: `/api/v1/tools/community-migrations/jobs/<job_id>`
- API: `/api/v1/tools/community-migrations/jobs/<job_id>/resume`
- API: `/api/v1/tools/community-migrations/jobs/<job_id>/cancel`
- API: `/api/v1/tools/community-migrations/jobs/<job_id>/export`
- Celery: `execute_community_migration_job`

Workflow:
1. Choose a successful retrieval collection as source inventory.
2. Select source and target community identifiers.
3. Apply filters and options such as editable-only and remove-source-after-verify.
4. Build a migration plan.
5. Launch, monitor, resume, cancel, or export the migration job.

Complete when:
- Target community append and optional source removal decisions have completed or been exported for audit.

## Scripted Zenodo Community And Retrieval Operations

Primary actor: operator.

Entry points:
- Script: `scripts/launch_zenodo_historical_backfill.py`
- Script: `scripts/monitor_zenodo_historical_backfill.py`
- Script: `scripts/execute_zenodo_community_append_from_csv.py`
- Remote script: `scripts/hpc_singularity/remote/approve_zenodo_community_requests.py`

Workflow:
1. Launch or monitor historical backfill from operator context.
2. Execute community append from a CSV action plan when UI batching is not the right operational control.
3. Approve Zenodo community requests remotely when running on HPC.

Complete when:
- Script output or checkpoint files show the intended terminal state.

## Prerequisites And Permissions

- Zenodo account retrieval requires an authenticated user with a valid accessible Zenodo credential.
- Batch community operations, moderation, and migration require moderator or administrator access.
- Retrieval scheduling requires worker availability for scheduled Celery execution.
- Scripted operations require operator shell access and carefully scoped Zenodo tokens.

## Inputs, Outputs, And State

| Input | Output | State To Watch |
|---|---|---|
| Credential, environment, retrieval mode, and filters | Retrieval job and explorer-only `.hdpc` shards | checkpoint, split windows, shard count, task status |
| OAI set, metadata prefix, date bounds, and record limit | Public OAI harvest and explorer-only `.hdpc` shards | resumption token, page count, shard count, task status |
| Retrieval collection query | Search results, export, compacted shards, or schedule | retention settings, schedule metadata, compaction state |
| Record filters and community action | Batch community task | per-record result, rate-limit waits, history row |
| Moderation request selection | Accept or decline task | request state, action note, task progress |
| Migration source and target communities | Migration plan and job | editable-only filter, source removal, export log |

## Failure And Recovery

- Retrieval failures should resume from checkpoint state when available instead of restarting from scratch.
- Dense Zenodo result windows should be split or bounded to avoid API search limits.
- Rate-limit waits should be treated as controlled progress unless the task becomes stale.
- Batch community and moderation failures should be reviewed per record or request before retrying.
- Migration cancellation or failure should preserve the plan and export for audit.

## Optimization Targets

- Reduce redundant Zenodo API calls during large account retrieval.
- Tune checkpoint frequency so resume is useful without excessive writes.
- Keep shard creation and compaction efficient for very large accounts.
- Keep batch community operations serial enough for Zenodo safety while reporting progress clearly.
- Make migration plans explain ineligible records before launch.

## Verification Checklist

- Verify retrieval context, preflight, job launch, job detail, pause, resume, cancel, delete, records, export, compaction, retention, schedule, and run-now.
- Verify OAI harvest context, preflight, launch, detail, record search, detector, export, compaction, schedule, and delete.
- Verify retrieval-generated sessions and `.hdpc` shards open in explorer workflows.
- Verify batch community record search, append/remove operation, history, and task polling.
- Verify community moderation request list, accept/decline action, history, and task polling.
- Verify community migration context, plan, launch, detail, resume, cancel, and export.
- Verify historical backfill, monitor, and CSV community append scripts in a controlled account.

Related docs:
- `docs/guides/zenodo_account_retrieval.md`
- `docs/guides/zenodo_oai_harvest.md`

## Codebase Starting Points

- Zenodo tools frontend: `frontend/src/views/tools/ZenodoAccountRetrievalView.vue`, `frontend/src/views/tools/ZenodoOaiHarvestView.vue`, `frontend/src/views/tools/ZenodoBatchOperationsView.vue`
- Community tools frontend: `frontend/src/views/tools/CommunityModerationPanelView.vue`, `frontend/src/views/tools/CommunityMigrationView.vue`
- Tool routes: `routes/tools_routes.py`
- Retrieval and community services: `services/zenodo_account_retrieval_service.py`, `services/community_migration_service.py`
- Batch history services: `services/zenodo_batch_history_service.py`, `services/community_moderation_history_service.py`
- Background tasks: `tasks.py`
- Operator scripts: `scripts/launch_zenodo_historical_backfill.py`, `scripts/monitor_zenodo_historical_backfill.py`, `scripts/execute_zenodo_community_append_from_csv.py`
