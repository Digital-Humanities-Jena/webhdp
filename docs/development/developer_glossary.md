# Developer Glossary

This glossary defines WebHDP terms as contributors encounter them in code, tests, and documentation. It is intentionally implementation-oriented. Public-facing terminology lives in `../guides/glossary.md`.

## Core Workflow

| Term | Developer meaning | Common owners |
|---|---|---|
| Upload | The act of bringing source files into a session before scan/submit behavior creates records | upload routes, file services, workflow views |
| Scan | The workflow stage that inspects uploaded files and prepares file/record candidates without publishing | scan routes/services, `.hdpc` services |
| Submit | The stage that creates local records from selected files and final metadata | submission routes/services, workflow views |
| Rerun | Processing an existing persisted record again by `record_id` rather than re-inferring upload selections | batch/session services, tasks |
| Publish | Uploading or synchronizing a record to Zenodo using the active credential resolution policy | Zenodo services, publishing routes |
| Session | A user workflow container with state, files, records, progress, and provenance | session models/routes/services |
| Record | A persisted digital-object unit in WebHDP and `.hdpc`; publishing and reruns operate on record IDs | `.hdpc` services, record views |
| Primary file | The main source file for a record, such as a 3D model | scan logic, MSF matching, `.hdpc` records |
| Generated artifact | A file produced by processing, such as metadata, previews, reports, or converted files | tasks, renderer/conversion services |
| Provenance | Traceable history of inputs, transformations, records, and publishing actions | `.hdpc`, session provenance services |

## Data And Metadata

| Term | Developer meaning | Common owners |
|---|---|---|
| MSF | Metadata spreadsheet/file used to match source files with structured metadata | MSF services, workflow fixtures |
| EDM | Europeana Data Model metadata generated for cultural heritage publishing | EDM services/templates/docs |
| LOD | Linked Open Data enrichment/generation behavior with required, optional, or disabled policy | LOD/EDM services, submission flow |
| IIIF | Interoperability framework for image/manifest presentation | IIIF services and docs |
| METS/MODS | Metadata/package standards supported by template and generation paths | METS services/templates/docs |
| Template | Configurable metadata generation shape for EDM, IIIF, METS/MODS, or related exports | template routes/services |
| Mapping | A field-to-field conversion rule between input metadata and output metadata structures | mapping schemas/services |
| Validation report | Structured result from schema, Schematron, local EDM validator, or business-rule validation | validation services, UI reports |
| API contract | Generated OpenAPI route inventory at `docs/api/openapi.json` | `scripts/generate_openapi.py`, route docs |

## `.hdpc`

| Term | Developer meaning | Common owners |
|---|---|---|
| `.hdpc` | WebHDP local SQLite project/session container for records and provenance | `services/hdpc_*`, `docs/architecture/hdpc_schema.md` |
| HDPC schema | Versioned table/field contract for `.hdpc` files | schema service, schema docs |
| HDPC import | Loading an existing `.hdpc` project into WebHDP | import routes/services |
| Shared export | Exporting `.hdpc` state for another user, process, or environment | shared export services |
| Explorer-only session | A session generated for browsing/retrieved records, not for normal upload/submit workflow mutation | retrieval/session services |
| Retrieval shard | One `.hdpc` piece created during large Zenodo account retrieval | Zenodo account retrieval services |

## Accounts, Auth, And Permissions

| Term | Developer meaning | Common owners |
|---|---|---|
| Role | Coarse user classification such as user, moderator, or admin | user model, auth routes |
| Capability | Fine-grained permission such as `developer_access` | user model, route checks |
| Developer mode | In-app diagnostics page at `/developer` for admin, moderator, or `developer_access` users | developer routes/view |
| Institution credential | Shared configured credential fallback for publishing | institution/credential services |
| User Zenodo key | Named encrypted Zenodo token owned or accepted by a user | Zenodo credential services |
| Active key | User-selected credential for sandbox or production publishing/retrieval | credential services/UI |
| Masked preview | Non-secret display form of a stored token or key | credential UI/services |

## Background Work And Processing

| Term | Developer meaning | Common owners |
|---|---|---|
| Celery task | Background unit of work used for processing, publishing, retrieval, or maintenance | `tasks.py`, services |
| Inline tasks | Local mode where work runs in-process instead of through a worker | config, onboarding, tests |
| Redis broker | Queue broker/result coordination for Celery in full-stack mode | Compose, Celery config |
| Progress payload | Stable task status data consumed by UI polling and dashboards | tasks, route responses, frontend views |
| Fast renderer | Optional service for rendering previews | external code, renderer service |
| Any-to-USDZ | Optional conversion component for USDZ output | external code, conversion service |
| Local EDM validator | Optional local service for EDM validation reports | compose override, local validator client |

## Zenodo And Public Presentation

| Term | Developer meaning | Common owners |
|---|---|---|
| Zenodo draft | Zenodo record state before final publish | Zenodo services/routes |
| Zenodo published record | Publicly available Zenodo record | retrieval/public routes |
| Sandbox | Zenodo testing environment | credential config and publishing services |
| Production | Real Zenodo environment | credential config and publishing services |
| Account retrieval | Pulling records/drafts from an accessible Zenodo key into explorer-only `.hdpc` collections | Zenodo account retrieval services |
| oEmbed | Public embedding response for published WebHDP/Zenodo records | public/oEmbed services |
| Public record page | Read-only public-facing record presentation | public routes/frontend views |

## Developer Tooling

| Term | Developer meaning | Common owners |
|---|---|---|
| Golden workflow | Local fixture-backed confidence check for scan, `.hdpc`, and MSF matching | `scripts/run_golden_workflow.py` |
| Doctor | `make doctor`; contributor environment health report | `scripts/doctor.py` |
| Devcontainer | VS Code/Codespaces development environment under `.devcontainer/` | `.devcontainer/`, CI |
| Docs check | `make docs-check`; validates developer docs and docs catalog | `scripts/check_developer_docs.py` |
| API contract check | `make api-contract-check`; verifies generated OpenAPI inventory is fresh | `scripts/check_openapi_fresh.py` |
| Compose check | `make compose-check`; validates Docker Compose configuration | Makefile, Compose files |
| First PR walkthrough | Step-by-step first contribution guide | `first_pr_walkthrough.md` |
| ADR | Architecture Decision Record for important constraints and tradeoffs | `docs/development/adr/` |

## Common Confusions

| Confusion | Clarification |
|---|---|
| Frontend guard vs backend permission | Frontend guards improve navigation UX; backend checks are the security boundary |
| Upload vs submit | Upload moves files into a session; submit creates local records from selected files and metadata |
| App DB vs `.hdpc` | App DB stores platform/account/session metadata; `.hdpc` stores project record/provenance data |
| Golden workflow vs full stack | Golden workflow is local and fixture-backed; full stack includes Compose services and optional integrations |
| Devcontainer dependencies vs host dependencies | Devcontainer Python env and `frontend/node_modules` are isolated so Linux packages do not overwrite host packages |
| API reference vs API contract | Reference explains semantics and examples; generated contract inventories Flask routes |
| Zenodo key sharing vs token exposure | Sharing grants access to encrypted credential records; cleartext tokens are not returned |
