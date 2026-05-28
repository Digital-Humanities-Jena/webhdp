# Good First Changes

This list helps new contributors find safe, useful places to start. Before choosing one, read `onboarding.md`, run `make doctor`, and skim the first-PR flow in `first_pr_walkthrough.md`.

## Documentation

- Clarify setup notes where commands are ambiguous or missing platform assumptions.
- Add short troubleshooting entries for errors you hit during local setup.
- Improve API examples with realistic request/response payloads.
- Add glossary entries for WebHDP, `.hdpc`, MSF, EDM, IIIF, METS, and Zenodo terms.
- Add links between related docs when a contributor would otherwise need to search manually.

Recommended checks:

```bash
make docs-check
git diff --check
```

## Backend

- Add route tests for existing endpoints that have clear behavior but thin coverage.
- Move small duplicated route logic into a service with tests.
- Improve validation error details for an existing request payload.
- Add safe, read-only diagnostics to an existing admin or tools endpoint.
- Add docs for an existing endpoint that is already stable.

Recommended checks:

```bash
uv run pytest tests/test_relevant_file.py
make docs-check
```

## Frontend

- Add focused tests for existing service modules or utility functions.
- Improve empty/loading/error states on a single view.
- Replace direct API calls in a view with a service method where that pattern already exists.
- Add stable test IDs to workflow controls that already have Playwright coverage.
- Improve Documentation Hub discoverability or filtering behavior.

Recommended checks:

```bash
cd frontend && npm run test:unit
cd frontend && npm run build
```

## Operations And Developer Experience

- Improve `Makefile` help text or add a safe validation target.
- Add an ADR for a decision already reflected in the code and docs.
- Improve `.env.example` comments without changing runtime behavior.
- Add a docs-check rule for a new class of documentation drift.
- Add a small script that reports environment readiness without exposing secrets.

Recommended checks:

```bash
make verify-onboarding
```

## Changes To Avoid As A First PR

- Reworking the upload/scan/submit lifecycle.
- Changing `.hdpc` schema or migration behavior.
- Combining database migrations, Celery tasks, and frontend workflow rewrites.
- Touching credential encryption or token handling without a maintainer-reviewed design.
- Large visual redesigns that make many unrelated snapshots or tests churn.

## How To Propose A New Good First Change

Open an issue using the Good First Issue template and include:

- The expected files or area.
- The user or contributor value.
- The smallest acceptable outcome.
- Suggested tests.
- Any risks or docs that must be updated.
