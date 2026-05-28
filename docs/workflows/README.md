# WebHDP Workflow Inventory

This directory is the complete workflow inventory for WebHDP. It complements
`docs/guides/workflows.md`, which is a high-level user guide. The documents here
cover the broader executable surface: UI paths, API workflows, background jobs,
native pipeline workflows, operator scripts, and public record demonstration flows.

## Overview

Use this inventory when you need to understand what WebHDP can do, where a
workflow is documented, and which workflow document owns a part of the
implementation. Start with the workflow document table, then use the coverage
matrix or source-surface checklist only when you need a deeper audit trail.

## How To Read This Inventory

A workflow is any repeatable task that a user, operator, administrator,
moderator, developer, public viewer, API client, or scheduled job can execute
through WebHDP or its repository scripts. Small support endpoints are grouped
under the workflow they enable.

## Workflow Document Structure

Every workflow document should follow the same reader-friendly shape. The first
screen should explain the workflow plainly; detailed operational and maintainer
material belongs near the bottom.

Required order for workflow documents:

1. `# <Workflow Group> Workflows`
2. Short opening paragraph that defines the document scope.
3. `## Overview`
4. `## Use Cases`
5. One or more workflow sections with this local structure:
   - `Primary actor: ...`
   - `Entry points:`
   - `Workflow:`
   - `Complete when:`
6. `## Prerequisites And Permissions`
7. `## Inputs, Outputs, And State`
8. `## Failure And Recovery`
9. `## Optimization Targets`
10. `## Verification Checklist`
11. `Related docs:` when the workflow has useful companion documentation.
12. `## Codebase Starting Points`

Writing guidance:

- Keep `Overview` and `Use Cases` approachable for users, operators, and reviewers who only need orientation.
- Keep endpoint, task, script, and source-surface exhaustiveness in [Workflow Source Surface Coverage](source-surface-coverage.md) instead of overloading every workflow document.
- Put failure handling, optimization targets, verification, and codebase references after the workflow descriptions so first-time readers are not overwhelmed.
- Use concrete file paths, routes, task names, and completion criteria so maintainers can verify and optimize the workflow without guessing.
- When a source surface is intentionally not an executable workflow, record that decision in the relevant non-workflow note or source coverage section.

## Use Cases

- Confirm that a new user-facing or operator-facing task is represented in the workflow docs.
- Decide which workflow document owns a route, background task, pipeline, or script.
- Give maintainers a high-level map before optimizing a workflow implementation.
- Audit whether documentation still matches the executable WebHDP surface.

## Verification Sources

The inventory was checked against:

- `docs/api/openapi.json`
- `frontend/src/router/index.js`
- `frontend/src/views/tools/ToolsLayout.vue`
- `tasks.py`
- `services/native_pipeline_system.py`
- `constants.py`
- `scripts/`

## Workflow Documents

| Document | Workflow Groups Covered |
|---|---|
| [Access, Setup, And Identity](access-setup-identity.md) | setup, reset, authentication, MFA, onboarding, account profile, recovery codes |
| [Public, Docs, And Profiles](public-docs-profiles.md) | documentation center, public pages, legal pages, public record pages, embeds, oEmbed, user and institution profiles |
| [Publication, Upload, And MSF](publication-upload-msf.md) | main publication workflow, upload/scan, directory and file ingestion, streaming upload, upload recovery, MSF QA and repair |
| [Metadata, Standards, And Templates](metadata-standards-templates.md) | Zenodo metadata, mapping tests, EDM/IIIF/METS, LOD, output preview, EDM templates |
| [Pipelines, Components, And Playground](pipelines-components-playground.md) | built-in pipelines, native pipeline platform, component import/install, Playground, pipeline constructor, preflight |
| [3D HDP Component Lifecycle](3d-hdp-component-lifecycle.md) | create, validate, distribute, install, smoke-test, and merge local Docker or HPC SIF profiles for external 3D HDP Components |
| [3D Analysis And Processing Pipelines](3d-analysis-processing-pipelines.md) | optional 3D prepublication analysis, publication derivatives, point-cloud readiness, constructor execution, and run artifact review |
| [Sessions, Records, And Provenance](sessions-records-provenance.md) | session governance, records, explorers, provenance, `.hdpc` downloads, cloud downloads, versioning, batch record operations, dataset integrity |
| [Zenodo Retrieval And Communities](zenodo-retrieval-communities.md) | account retrieval, historical backfill, incremental schedules, compaction, community batch operations, moderation, migration |
| [Institutions, Credentials, And Governance](institutions-credentials-governance.md) | personal and institution credentials, credential sharing, institution membership, community policy, admin user governance |
| [HPC, Cloud, And Storage](hpc-cloud-storage.md) | HPC access requests, HPC allocations, HPC-Link staging, cloud testing, storage configuration, local/HPC component installation |
| [HPC Batch Automation](hpc-batch-automation.md) | unattended chunked HPC processing, scheduler retries, tmux observation, artifact gates, recovery queues, and run reporting |
| [Admin Operations And Observability](admin-operations-observability.md) | admin dashboard, submission review, upload/session monitoring, backups, observability, notification maintenance, release/readiness operations |
| [Issues And Notifications](issues-notifications.md) | issue reporting, issue triage, comments, code-reference refresh, notification preferences and delivery |
| [Developer And Operator Scripts](developer-operator-scripts.md) | developer status, golden workflow, doctor, API/docs checks, release checks, maintenance scripts, HPC deployment scripts, agent CLI |
| [Workflow Source Surface Coverage](source-surface-coverage.md) | audit checklist mapping frontend routes, backend route families, Celery tasks, native pipelines, and scripts to the owning workflow documents |

## Coverage Matrix

The following list is the normalized workflow checklist. Each item is covered in
one of the documents above.

| Workflow | Document |
|---|---|
| First-time setup checks, admin creation, setup completion, setup reset, render smoke test | [Access, Setup, And Identity](access-setup-identity.md) |
| Registration, email verification, login, MFA login, recovery-code login, logout | [Access, Setup, And Identity](access-setup-identity.md) |
| Account profile, password change, recovery codes, onboarding | [Access, Setup, And Identity](access-setup-identity.md) |
| Documentation center and documentation assets | [Public, Docs, And Profiles](public-docs-profiles.md) |
| Landing, credits, impressum, privacy, cookie pages | [Public, Docs, And Profiles](public-docs-profiles.md) |
| Public record page, embed page, oEmbed | [Public, Docs, And Profiles](public-docs-profiles.md) |
| User and institution profile viewing | [Public, Docs, And Profiles](public-docs-profiles.md) |
| Main seven-step publication workflow | [Publication, Upload, And MSF](publication-upload-msf.md) |
| Single-file upload, directory/ZIP upload, local workflow preparation, streaming upload | [Publication, Upload, And MSF](publication-upload-msf.md) |
| Upload operation monitoring, recovery, and resume | [Publication, Upload, And MSF](publication-upload-msf.md) |
| MSF parse, validate, repair, metadata matching, local validator/export, workflow analysis | [Publication, Upload, And MSF](publication-upload-msf.md) |
| Record-resolution review for duplicate, version, and hash-collision candidates | [Publication, Upload, And MSF](publication-upload-msf.md) |
| Metadata draft, file metadata, batch metadata update | [Metadata, Standards, And Templates](metadata-standards-templates.md) |
| Zenodo, EDM, IIIF, and METS mapping tests | [Metadata, Standards, And Templates](metadata-standards-templates.md) |
| EDM template list/create/update/delete/preview/validate | [Metadata, Standards, And Templates](metadata-standards-templates.md) |
| Output preview QA, local EDM validation, LOD output review | [Metadata, Standards, And Templates](metadata-standards-templates.md) |
| Built-in `render` and `metadata_only` pipelines and legacy aliases | [Pipelines, Components, And Playground](pipelines-components-playground.md) |
| Built-in pipeline steps: `fast_renderer`, `any_to_usdz`, `zenodo_draft`, `lod_generation`, `zenodo_upload`, `input_file_classification` | [Pipelines, Components, And Playground](pipelines-components-playground.md) |
| Native pipeline listing, validation, versioning, execution, run polling | [Pipelines, Components, And Playground](pipelines-components-playground.md) |
| Native component listing, validation, import, constructor support, constructor preflight | [Pipelines, Components, And Playground](pipelines-components-playground.md) |
| Native Playground execution and artifact downloads | [Pipelines, Components, And Playground](pipelines-components-playground.md) |
| HDP component installer and smoke tests | [Pipelines, Components, And Playground](pipelines-components-playground.md) |
| 3D HDP Component package creation, manifest validation, artifact distribution, local Docker install, HPC SIF install, and strategy merge | [3D HDP Component Lifecycle](3d-hdp-component-lifecycle.md) |
| Optional 3D pipeline seeding, `3d_prepublication_analysis`, `3d_publication_derivatives`, `3d_point_cloud_readiness`, Pipeline Constructor execution, and 3D report artifact review | [3D Analysis And Processing Pipelines](3d-analysis-processing-pipelines.md) |
| Session list/detail/workspace/workflow-state/progress/resume | [Sessions, Records, And Provenance](sessions-records-provenance.md) |
| Record browser, record detail, traceability, lineage, Zenodo status | [Sessions, Records, And Provenance](sessions-records-provenance.md) |
| Session provenance report and cross-session explorer | [Sessions, Records, And Provenance](sessions-records-provenance.md) |
| `.hdpc`, shared `.hdpc`, Zenodo metadata, and cloud artifact downloads | [Sessions, Records, And Provenance](sessions-records-provenance.md) |
| Versioning match, create version, discard draft, latest concept files | [Sessions, Records, And Provenance](sessions-records-provenance.md) |
| Session batch operations: create drafts, discard drafts, upload files, publish records, remove files | [Sessions, Records, And Provenance](sessions-records-provenance.md) |
| Dataset integrity catalog, duplicate check, conflict review, export | [Sessions, Records, And Provenance](sessions-records-provenance.md) |
| Zenodo account retrieval: full, bounded, historical backfill, incremental, pause/resume/cancel/delete | [Zenodo Retrieval And Communities](zenodo-retrieval-communities.md) |
| Zenodo OAI harvest: public no-credential metadata harvest, search, export, compaction, and delete | [Zenodo Retrieval And Communities](zenodo-retrieval-communities.md) |
| Retrieval search, export, compaction, retention, schedule, run-now | [Zenodo Retrieval And Communities](zenodo-retrieval-communities.md) |
| Zenodo batch community append/remove operations | [Zenodo Retrieval And Communities](zenodo-retrieval-communities.md) |
| Community moderation accept/decline batches | [Zenodo Retrieval And Communities](zenodo-retrieval-communities.md) |
| Community migration plan, launch, resume, cancel, export | [Zenodo Retrieval And Communities](zenodo-retrieval-communities.md) |
| Personal credentials, validation, active selection, sharing, accept/decline/revoke | [Institutions, Credentials, And Governance](institutions-credentials-governance.md) |
| Institution creation/update, affiliation, memberships, communities, audit events | [Institutions, Credentials, And Governance](institutions-credentials-governance.md) |
| Institution credentials and validation | [Institutions, Credentials, And Governance](institutions-credentials-governance.md) |
| Admin user role, capability, and recovery reset workflows | [Institutions, Credentials, And Governance](institutions-credentials-governance.md) |
| HPC resource requests and admin approve/reject/revoke | [HPC, Cloud, And Storage](hpc-cloud-storage.md) |
| HPC-Link allocation, preflight, staging, draft upload, release | [HPC, Cloud, And Storage](hpc-cloud-storage.md) |
| Cloud provider tests, storage config/status, storage modes | [HPC, Cloud, And Storage](hpc-cloud-storage.md) |
| HPC diagnostics and Docker/SIF-backed component installation | [HPC, Cloud, And Storage](hpc-cloud-storage.md) |
| Unattended HPC batch processing, chunk preparation, parallel scheduler submissions, recovery queues, and run reporting | [HPC Batch Automation](hpc-batch-automation.md) |
| Admin submissions, review, delete, upload operation monitoring | [Admin Operations And Observability](admin-operations-observability.md) |
| Admin session monitoring and termination | [Admin Operations And Observability](admin-operations-observability.md) |
| Backup status/list/create/prune and restore drill | [Admin Operations And Observability](admin-operations-observability.md) |
| Observability checks, credential status, API activity, notification delivery audit | [Admin Operations And Observability](admin-operations-observability.md) |
| Session cleanup analyze and execute | [Admin Operations And Observability](admin-operations-observability.md) |
| Issue registry, report, update, comments, code-reference refresh | [Issues And Notifications](issues-notifications.md) |
| Notifications, unread count, preferences, read-all, cleanup, digest | [Issues And Notifications](issues-notifications.md) |
| Developer status, golden sample workflow, doctor, docs/API/component checks | [Developer And Operator Scripts](developer-operator-scripts.md) |
| Agent CLI workflow | [Developer And Operator Scripts](developer-operator-scripts.md) |
| Backup, readiness, release, maintenance, and Celery drain scripts | [Developer And Operator Scripts](developer-operator-scripts.md) |
| HPC Singularity deployment, remote operation scripts, and legacy dataset-specific chunk scripts | [Developer And Operator Scripts](developer-operator-scripts.md) |
| Zenodo historical backfill launch/monitor scripts and CSV community append script | [Developer And Operator Scripts](developer-operator-scripts.md) |
| Source-code route, task, pipeline, and script audit checklist | [Workflow Source Surface Coverage](source-surface-coverage.md) |

## Prerequisites And Permissions

- Readers need repository access only when validating the source-surface coverage.
- Product, user-support, and operator readers can use the inventory without local development setup.
- Maintainers should refresh the route, OpenAPI, task, pipeline, and script checks before declaring new workflow coverage complete.

## Inputs, Outputs, And State

| Input | Output | State To Watch |
|---|---|---|
| Frontend routes, backend routes, tasks, pipelines, and scripts | Workflow document ownership | `docs/workflows/`, `routes/docs_routes.py` |
| New product or operator capability | Updated workflow inventory row | `docs/workflows/README.md` |
| New executable source surface | Updated source-surface coverage row | `docs/workflows/source-surface-coverage.md` |

## Failure And Recovery

- If a workflow appears in code but not in the inventory, add it to the owning workflow doc and the coverage matrix.
- If a source-surface check no longer maps cleanly, update the owning document before adding endpoint-level detail.
- If a route is intentionally not a workflow, record that decision in the non-workflow note or source coverage doc.

## Optimization Targets

- Keep the inventory navigable by grouping support endpoints under user-meaningful workflow names.
- Keep source coverage precise enough for maintainers without turning every workflow document into an API reference.
- Preserve the split between macro workflow docs and the traceability annex.

## Verification Checklist

- Confirm each `docs/workflows/*.md` file is registered in `routes/docs_routes.py` when it should appear in the in-app docs.
- Check that every new workflow has an owner document, use case, completion condition, and codebase starting point.
- Run the docs catalog test after changing workflow registration.

## Explicit Non-Workflow Note

Admin submission retry is intentionally not exposed in the first public release
because no backend retry route currently implements it. Failed submissions are
handled through the documented review, delete, and re-run paths.

## Codebase Starting Points

- Workflow source coverage: `docs/workflows/source-surface-coverage.md`
- Frontend routing: `frontend/src/router/index.js`
- Backend route catalog: `routes/` and `app.py`
- API contract: `docs/api/openapi.json`
- Background work: `tasks.py`
- Native pipelines and components: `services/native_pipeline_system.py`, `constants.py`
- Operator and developer workflows: `scripts/`
- Documentation catalog: `routes/docs_routes.py`
