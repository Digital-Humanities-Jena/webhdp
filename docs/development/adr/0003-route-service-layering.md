# ADR 0003: Route And Service Layering

Status: Accepted

## Context

WebHDP's backend routes are broad: authentication, sessions, uploads, templates, tools, Zenodo, notifications, public pages, and admin workflows. Placing business rules directly in routes makes behavior hard to reuse from Celery tasks, difficult to test, and risky to change.

## Decision

Routes own HTTP concerns: request parsing, auth/role/ownership checks, validation, status codes, and `APIResponse` formatting.

Services own business logic: persistence coordination, external API clients, `.hdpc` mutation/query, workflow orchestration, and reusable domain behavior.

Non-trivial payload validation should use structured schemas under `schemas/`.

## Consequences

- New route behavior should usually be paired with service tests or route tests.
- Reusable behavior should not be trapped inside a Flask request context.
- Celery tasks should call services rather than duplicate route logic.
- Frontend developers can rely on stable response shapes when routes consistently use `APIResponse`.
