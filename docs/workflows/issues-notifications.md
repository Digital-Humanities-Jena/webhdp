# Issues And Notifications Workflows

This document covers user-reported issues, issue triage, notification delivery,
and notification maintenance.

## Overview

These workflows connect user-facing support signals with maintainer action.
Users can report issues and manage notifications; maintainers can triage issues,
refresh code references, and audit notification delivery. The bottom sections
focus on delivery reliability, cleanup, and the data paths that need attention
when the support loop feels noisy or slow.

## Use Cases

- Let users report workflow issues with enough context for maintainers to reproduce them.
- Triage, comment on, update, or refresh code references for reported issues.
- Manage notification preferences, unread counts, and read-state behavior.
- Maintain notification delivery, digest, and cleanup jobs.

## Issue Reporting

Primary actor: authenticated user.

Entry points:
- UI: `/issues/report`
- API: `/api/v1/issues`
- API: `/api/v1/issues/registry`

Workflow:
1. Load the issue page registry and metadata.
2. Create an issue report with route, context, description, and optional technical references.
3. Save the issue for triage.

Complete when:
- The issue exists and can be opened from the issues workspace.

## Issue Triage And Comments

Primary actor: reporter, moderator, administrator, or developer.

Entry points:
- UI: `/issues`
- UI: `/issues/:issueId`
- API: `/api/v1/issues`
- API: `/api/v1/issues/<issue_id>`
- API: `/api/v1/issues/<issue_id>/comments`
- API: `/api/v1/issues/<issue_id>/refresh-code-references`

Workflow:
1. List and filter issues.
2. Open issue detail.
3. Update issue fields such as status or metadata.
4. Add comments.
5. Refresh code references when the codebase changed.

Complete when:
- The issue state and discussion reflect the latest triage outcome.

## User Notifications

Primary actor: authenticated user.

Entry points:
- UI: `/notifications`
- API: `/api/v1/notifications`
- API: `/api/v1/notifications/unread-count`
- API: `/api/v1/notifications/client-config`
- API: `/api/v1/notifications/preferences`
- API: `/api/v1/notifications/<notification_id>`
- API: `/api/v1/notifications/read-all`

Workflow:
1. Load notification client configuration.
2. List notifications and unread count.
3. Update notification preferences.
4. Mark individual notifications or all notifications as read.

Complete when:
- Notification state and preferences match user intent.

## Notification Delivery Maintenance

Primary actor: administrator or scheduled worker.

Entry points:
- API: `/api/v1/admin/observability/notification-deliveries`
- API: `/api/v1/admin/observability/notification-digest/run`
- API: `/api/v1/admin/observability/notifications/cleanup`
- Celery: `send_notification_digests_task`
- Celery: `cleanup_notifications_task`

Workflow:
1. Inspect delivery audit.
2. Run digest delivery manually or by schedule.
3. Cleanup old notification data according to runtime policy.

Complete when:
- Delivery audit and cleanup state are current.

## Prerequisites And Permissions

- Issue reporting and notification preferences require an authenticated user.
- Issue triage may involve reporter, moderator, administrator, or developer access depending on the action.
- Notification delivery audit, digest, and cleanup require administrator access or scheduled worker execution.
- Code-reference refresh depends on the page registry and current repository metadata.

## Inputs, Outputs, And State

| Input | Output | State To Watch |
|---|---|---|
| Issue report form and route context | Issue record for triage | issue status, reporter, page key, code references |
| Comment or status update | Triage history | comment list, status, assignee or moderator notes |
| Notification preferences | Updated delivery preferences | unread count, preference flags, read state |
| Digest or cleanup trigger | Delivery audit or cleanup result | delivery rows, digest task state, cleanup counts |

## Failure And Recovery

- Failed issue creation should preserve user-entered context where possible.
- Stale code references should be refreshed from the page registry before developer triage.
- Notification delivery failures should be reviewed through the admin delivery audit.
- Cleanup should be rerun in bounded batches if a large notification table times out.

## Optimization Targets

- Reduce issue-triage noise by keeping page registry metadata accurate.
- Keep unread-count and notification list queries fast.
- Batch digest and cleanup work to avoid long locks or worker starvation.
- Make code-reference refresh cheap enough to run when routes or views change.

## Verification Checklist

- Verify issue registry, report, list, detail, update, comments, and code-reference refresh.
- Verify notification list, unread count, preferences, mark-read, and read-all flows.
- Verify admin delivery audit, digest run, cleanup trigger, and Celery task behavior.

Related docs:
- `shared/issues/page_registry.json`
- `docs/guides/troubleshooting.md`

## Codebase Starting Points

- Issue frontend views: `frontend/src/views/issues/`
- Notification frontend view: `frontend/src/views/notifications/NotificationsView.vue`
- Issue routes and page registry: `routes/issues_routes.py`, `shared/issues/page_registry.json`
- Notification routes: `routes/notification_routes.py`
- Notification services and tasks: `services/notification_service.py`, `tasks.py`
- Admin observability: `routes/admin_routes.py`
