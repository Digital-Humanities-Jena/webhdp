# ADR 0004: Inline Celery Mode

Status: Accepted

## Context

WebHDP uses Celery and Redis for production background work. New contributors, low-resource deployments, and focused local tests sometimes need to exercise task-backed behavior without starting a separate worker and broker.

## Decision

`celery_app.py` provides an inline task fallback when Celery is unavailable or `WEBHDP_INLINE_TASKS=true` is set. Inline mode implements the subset of task behavior WebHDP uses locally and keeps task call sites compatible with Celery-style `.delay()` and `.apply_async()` usage.

## Consequences

- Inline mode is useful for local development and constrained deployments, not a production replacement for worker-based processing.
- Long-running production workflows should still use real Celery workers and Redis.
- New tasks should keep core logic in services so behavior can be tested without depending on either execution mode.
- Task metadata must remain safe because both inline and worker modes expose progress to callers.
