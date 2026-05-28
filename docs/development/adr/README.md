# Architecture Decision Records

Architecture Decision Records (ADRs) explain why WebHDP is shaped the way it is. They are short, durable notes for contributors who need context before changing a contract.

## Index

| ADR | Decision | Status |
|---|---|---|
| `0001-upload-scan-submit-lifecycle.md` | Upload stops at `scanned`; submit owns first record creation | Accepted |
| `0002-hdpc-session-state.md` | `.hdpc` files are canonical session project state | Accepted |
| `0003-route-service-layering.md` | Routes stay thin; services own business rules | Accepted |
| `0004-inline-celery-mode.md` | Inline task mode exists for local and constrained deployments | Accepted |
| `0005-generated-api-contract.md` | OpenAPI route inventory is generated from Flask route map | Accepted |

## ADR Template

```markdown
# ADR N: Title

Status: Proposed | Accepted | Superseded

## Context

What problem or constraint forced a decision?

## Decision

What did we decide?

## Consequences

What becomes easier, harder, or constrained by this choice?
```
