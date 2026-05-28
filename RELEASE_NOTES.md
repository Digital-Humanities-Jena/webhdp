# WebHDP Release Notes

## 0.1.0-alpha.1 - 2026-05-28

This is the first public alpha repository release for WebHDP.

### Supported Alpha Boundary

- Stable first-release workflows: predefined `render` and `metadata_only` publication paths.
- Local EDM validation: pinned external checkout of `Digital-Humanities-Jena/local-edm-validator` via `make local-edm-validator-setup`.
- Optional local compute services: `fast-renderer` and `any-to-usdz` remain first-class Compose services for workstation-local evaluation.
- Broader installable HDP Components, Pipeline Constructor workflows, HPC/SIF execution, and production HPC-Link operation remain evaluation features unless a deployment validates them separately.

### Release Hygiene

- Public fixtures are synthetic or minimized generated assets.
- Local runtime data, reports, production/research exports, logs, databases, credentials, generated build outputs, and scratch test folders are excluded from the release index.
- Docker and CI validation use `.env.example` safely without overwriting an existing local `.env`.
- Public documentation includes a Docker quickstart, HPC local-mode setup guide, release walkthrough videos, and a consolidated future roadmap.

### Verification Scope

Before publishing this alpha, maintainers should run the checks in `PUBLISHING.md`, including backend tests, frontend tests/build, HPC-Link tests, Compose validation, devcontainer validation, and release image tag checks.
