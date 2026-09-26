# WebHDP Release Notes

## 0.1.0-alpha.2 - 2026-09-26

- Password login is the default. Each user can enable email two-factor authentication after confirming an enrollment code, or disable it with their current password.
- Core pipelines generate CIDOC-CRM RDF/XML and equivalent JSON-LD alongside EDM, IIIF, and METS/MODS. Exports describe the digital dataset without inventing physical-object history.
- Nested MSF-listed models remain separate records. Model dependencies retain their directory structure during streaming HPC uploads, and record outputs cannot overwrite namesakes.
- The bundled EDM XSD now runs on every validated export. Aggregation elements follow the schema sequence, and the preview distinguishes passed checks from skipped ones.
- HPC-Link service accounts renew bearer tokens automatically. Allocation owners can download their own output artifacts without general filesystem access.
- The renderer honors the configured Blender executable and supports the Blender 4.x STL importer. Unreadable textures fail with an explicit error instead of producing placeholder-colored thumbnails.
- Reruns reuse unpublished Zenodo drafts, restore remotely missing originals, and retry failed uploads. Expired HPC allocations release queue capacity and can be replaced in one request.
- Production draft workflows support individual uploads as well as named dataset directories, while retaining duplicate-record checks.
- A core deployment profile disables unverified optional tools and pipeline authoring. A separate publishing switch permits draft-only operation.
- Backend images build from the frozen dependency lock; frontend dependency security updates are included.

Deployment credentials, scheduler policy, VPN configuration, and operator validation artifacts belong in private deployment profiles outside the public source tree. Component manifest and `.hdpc` schemas are unchanged.

Verification: 575 backend tests, 227 frontend unit tests, 111 HPC-Link tests, and 39 browser tests passed. Live validation covered a fresh deployment, public HTTPS uploads and browser workflow, email 2FA, GPU rendering of glTF/OBJ/STL with dependencies and Unicode paths, and unpublished Sandbox/Production drafts. Downloaded artifacts passed checksum, EDM XSD, METS/MODS XSD, and RDF equivalence checks. A corrupt texture is rejected explicitly. Five environment-dependent or browser-specific checks remain intentionally skipped; unverified optional deployment features are disabled.

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
