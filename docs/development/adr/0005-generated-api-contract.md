# ADR 0005: Generated API Contract

Status: Accepted

## Context

WebHDP has a large Flask API and detailed hand-written API documentation. New frontend and integration contributors need a quick route inventory, but the current codebase does not yet use request/response schemas consistently enough to generate a complete formal OpenAPI contract with precise payload models.

## Decision

WebHDP includes a lightweight generated OpenAPI route inventory at `docs/api/openapi.json`, produced by `scripts/generate_openapi.py` from the Flask route map.

The generated contract is an onboarding and discovery aid. The source of truth for endpoint semantics, request bodies, response examples, and workflow constraints remains:

- `docs/api/webhdp_api_reference.md`
- `docs/api/webhdp_api_examples.md`
- `docs/architecture/system_architecture.md`
- route and service tests

## Consequences

- Contributors can regenerate the route inventory with `make api-contract`.
- The generated contract should stay deterministic and safe to run locally.
- Endpoint-specific schemas can be added over time as request/response validation becomes more structured.
- Pull requests that add routes should regenerate `docs/api/openapi.json` or explain why it was not updated.
