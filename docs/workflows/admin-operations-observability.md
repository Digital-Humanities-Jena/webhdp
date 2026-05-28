# Admin Operations And Observability Workflows

This document covers administrator workflows for operations, monitoring,
backup, cleanup, readiness, and observability.

## Overview

These workflows help administrators keep WebHDP healthy after users start doing
real work. They cover review queues, operational dashboards, session monitoring,
configuration, backups, readiness checks, observability, and cleanup. Start with
the operational task you are trying to complete, then use the deeper sections at
the bottom when tuning reliability or performance.

## Use Cases

- Monitor live submissions, uploads, sessions, allocations, and deployment health.
- Review or clean up operational state without interrupting unrelated user work.
- Configure pipelines, EDM, MFA, modalities, storage, communities, and HPC-Link.
- Run backup, restore, readiness, observability, and maintenance workflows.

## Admin Dashboard And Submission Review

Primary actor: moderator or administrator.

Entry points:
- UI: `/admin/dashboard`
- UI: `/admin/review/:id`
- API: `/api/v1/admin/stats`
- API: `/api/v1/admin/submissions`
- API: `/api/v1/admin/submissions/<submission_id>`
- API: `/api/v1/admin/submissions/<submission_id>/review`
- API: `DELETE /api/v1/admin/submissions/<submission_id>`
- API: `/api/v1/admin/upload-operations`

Workflow:
1. Review dashboard stats and failed/running submissions.
2. Open submission details.
3. Add moderator review notes.
4. Delete submissions only when policy allows cleanup.
5. Inspect upload operations.

Complete when:
- Operational status is understood and review notes or cleanup actions are persisted.

Note:
- Submission retry is intentionally not exposed in the first public release because no backend retry route currently implements it.

## Admin Session Monitoring

Primary actor: administrator.

Entry points:
- UI: `/admin/session-monitoring`
- API: `/api/v1/admin/session-monitoring`
- API: `/api/v1/admin/session-monitoring/sessions/<session_id>/terminate`
- API: `/api/v1/admin/session-monitoring/allocations/<allocation_id>/terminate`

Workflow:
1. List active monitored sessions and allocations.
2. Terminate sessions or allocations when required by operations policy.

Complete when:
- Unwanted runtime activity has stopped and monitoring state is updated.

## Admin Configuration

Primary actor: administrator.

Entry points:
- UI: `/settings/pipelines`
- UI: `/settings/edm`
- UI: `/settings/mfa`
- UI: `/settings/modalities`
- API: `/api/v1/admin/pipelines/<pipeline_id>/config`
- API: `/api/v1/admin/edm-config`
- API: `/api/v1/admin/mfa-config`
- API: `/api/v1/admin/modality-config`
- API: `/api/v1/admin/version-detection-config`
- API: `/api/v1/admin/zenodo-community-config`
- API: `/api/v1/admin/hpc-link-config`
- API: `/api/v1/admin/hpc-link-config/validate`
- API: `/api/v1/admin/version`

Workflow:
1. Review current runtime configuration.
2. Update pipeline, EDM, MFA, modality, hash-collision, community, or HPC-Link settings.
3. Validate where supported.
4. Confirm runtime version when diagnosing deployments.

Complete when:
- Configuration matches intended deployment behavior.

## Backup And Restore Operations

Primary actor: administrator or operator.

Entry points:
- API: `/api/v1/admin/backups/status`
- API: `/api/v1/admin/backups`
- API: `/api/v1/admin/backups/prune`
- Script: `scripts/backup.py`
- Script: `scripts/backup_status.py`
- Script: `scripts/list_backups.py`
- Script: `scripts/prune_backups.py`
- Script: `scripts/restore_backup.py`
- Script: `scripts/restore_drill.py`
- Script: `scripts/scheduled_backup.sh`

Workflow:
1. Check backup status.
2. Create or list backup archives.
3. Prune backups according to retention policy.
4. Restore a backup or run a restore drill in operator-controlled context.

Complete when:
- Backup artifacts and restore confidence match recovery objectives.

## Observability

Primary actor: administrator.

Entry points:
- UI: `/settings/observability/credentials`
- UI: `/settings/observability/api-activity`
- UI: `/settings/observability/notifications`
- API: `/api/v1/admin/observability/credentials-status`
- API: `/api/v1/admin/observability/api-activity`
- API: `/api/v1/admin/observability/checks/<check_id>`
- API: `/api/v1/admin/observability/notification-deliveries`
- API: `/api/v1/admin/observability/notification-digest/run`
- API: `/api/v1/admin/observability/notifications/cleanup`

Workflow:
1. Review credential encryption and runtime configuration status.
2. Inspect API activity.
3. Run named observability checks.
4. Inspect notification delivery audit.
5. Run notification digest or cleanup tasks.

Complete when:
- Observability findings and notification maintenance tasks are recorded.

## Readiness, Health, And Session Cleanup

Primary actor: administrator or operator.

Entry points:
- UI: `/admin/setup`
- API: `/api/v1/health`
- API: `/api/v1/readiness`
- UI: `/tools/session-cleanup`
- API: `/api/v1/tools/session-cleanup/analyze`
- API: `/api/v1/tools/session-cleanup/execute`

Workflow:
1. Check the operational setup guidance page or health/readiness endpoints.
2. Analyze session cleanup candidates.
3. Execute cleanup only after reviewing candidates.

Complete when:
- Readiness is acceptable and cleanup results are recorded.

## Admin Media Inventory

Primary actor: administrator.

Entry points:
- API: `/api/v1/admin/projects/media`

Workflow:
1. Query project media inventory.
2. Use the inventory for diagnostics, cleanup review, or demonstrations.

Complete when:
- Media inventory is available for the operator task.

## Prerequisites And Permissions

- Admin dashboard, configuration, backup, and observability workflows require administrator access unless a route explicitly allows moderator review.
- Submission review requires moderator or administrator access.
- Backup and restore scripts require shell access to the deployment environment and storage targets.
- Session cleanup and termination actions should be performed only under an operational policy.

## Inputs, Outputs, And State

| Input | Output | State To Watch |
|---|---|---|
| Submission and upload operation filters | Reviewable operational lists | submission status, upload progress, review notes |
| Runtime configuration forms | Updated deployment behavior | pipeline, EDM, MFA, modality, storage, community, and HPC-Link config |
| Backup or restore command | Backup archive or restored environment | backup metadata, archive location, integrity-check result |
| Observability and cleanup actions | Audit, digest, cleanup, or termination results | notification deliveries, API activity, session cleanup candidates |

## Failure And Recovery

- Failed submission review should be recovered only through implemented review, delete, and re-run paths.
- Failed backup or restore should be followed by `restore_drill` or integrity checks before trusting recovery posture.
- Failed observability checks should point to credential, API activity, notification, or configuration state.
- Cleanup and termination actions should be reviewed before execution because they can remove or stop active work.

## Optimization Targets

- Reduce admin dashboard query cost on large submission and upload tables.
- Improve polling and progress updates for long-running submissions and sessions.
- Keep configuration writes atomic and easy to audit.
- Make backup, restore, and cleanup workflows predictable in production-sized deployments.

## Verification Checklist

- Verify admin stats, submission review, upload operations, and session monitoring views.
- Run health and readiness checks after configuration changes.
- Confirm backup create/list/prune and restore-drill behavior.
- Confirm notification digest, cleanup, and delivery audit workflows.
- Confirm session cleanup analyze mode before execute mode.

Related docs:
- `docs/guides/operations_and_setup_guide.md`
- `docs/guides/restore_drill_checklist.md`
- `docs/guides/troubleshooting.md`

## Codebase Starting Points

- Admin frontend views: `frontend/src/views/admin/`, `frontend/src/views/settings/`
- Admin routes: `routes/admin_routes.py`
- Submission routes and pipeline progress: `routes/submission_routes.py`, `services/submission_pipeline_service.py`
- Upload/session monitoring: `routes/session_routes.py`, `routes/admin_routes.py`
- Health and readiness: `app.py`, `scripts/readiness_check.py`
- Backups and restore: `scripts/backup.py`, `scripts/restore_backup.py`, `scripts/restore_drill.py`
- Observability and notifications: `services/admin_observability_service.py`, `tasks.py`
