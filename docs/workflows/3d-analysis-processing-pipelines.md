# 3D Analysis And Processing Pipeline Workflows

This document covers the optional 3D native pipelines that use external HDP
Components for model analysis, publication readiness, derivative generation,
and point-cloud readiness.

## Overview

The optional 3D pipelines are native pipeline definitions seeded by WebHDP only
after their required HDP Components are registered. This prevents the interface
from exposing pipelines that cannot execute in the current deployment. The
current seeded pipelines are:

- `3d_prepublication_analysis`
- `3d_publication_derivatives`
- `3d_point_cloud_readiness`

The stable publication workflow can still use the built-in `render` and
`metadata_only` pipelines. The optional 3D pipelines provide pre-publication
analysis and derivative workflows that can be run from the native API, Pipeline
Constructor, or future publication flow integrations.

For heritage and research projects, these pipelines are decision-support
workflows. They can identify technical risk, metadata enrichment opportunities,
and viewer-readiness problems, but they do not certify authenticity, rights
clearance, conservation status, cultural sensitivity, or institutional approval
for public release.

## Use Cases

- Check a 3D model before publication without mutating the scholarly source asset.
- Generate explicit derivative files for web viewing and publication workflows.
- Analyze point-cloud assets separately from mesh-heavy GLB/OBJ workflows.
- Surface structured report artifacts for operator review before Zenodo upload.
- Confirm local Docker or HPC component profile readiness before running expensive processing.

## Seed Optional 3D Pipelines

Primary actor: administrator or native pipeline service.

Entry points:
- Startup seed: `services/native_pipeline_system.py`
- Constants: `constants.py`
- API: `/api/v2/pipelines`
- API: `/api/v2/components`

Workflow:
1. Register all required 3D HDP Components.
2. Run native pipeline seeding during startup or service initialization.
3. Skip any optional pipeline whose required components are missing.
4. Create or update active pipeline versions only when the semantic definition changes.
5. Keep the stored config version aligned with the active `PipelineVersion` row.

Complete when:
- `3d_prepublication_analysis`, `3d_publication_derivatives`, and `3d_point_cloud_readiness` are listed only in deployments where their required components are available.

## Run 3D Prepublication Analysis

Primary actor: pipeline author, operator, or publishing user validating assets.

Entry points:
- UI: `/tools/pipeline-constructor`
- API: `/api/v2/pipelines/3d_prepublication_analysis`
- API: `/api/v2/pipelines/3d_prepublication_analysis/execute`
- API: `/api/v2/runs/<run_id>`

Workflow:
1. Select local source model files from a session.
2. Run constructor preflight to resolve inputs and trigger behavior.
3. Execute the pipeline.
4. Review classification, profiling, texture/dependency audit, geometry QA, viewer readiness, and fingerprint outputs.
5. Use warnings or recommendations to decide whether the source asset can move toward publication, manual review, quarantine, repair, or derivative generation.

Complete when:
- The persisted run reaches `completed` or `failed`, report artifacts are visible, and any blocking QA findings are triaged.

## Run 3D Publication Derivatives

Primary actor: operator or publishing user preparing derivative outputs.

Entry points:
- UI: `/tools/pipeline-constructor`
- API: `/api/v2/pipelines/3d_publication_derivatives`
- API: `/api/v2/pipelines/3d_publication_derivatives/execute`
- API: `/api/v2/runs/<run_id>`

Workflow:
1. Select source model files from a session.
2. Run constructor preflight to confirm artifact bindings between steps.
3. Execute canonical GLB normalization.
4. Execute spatial normalization, repair, geometric LOD generation, and viewer readiness checks.
5. Review derivative files and reports before using them in publication or viewer workflows.
6. Keep source assets unchanged and label repaired, normalized, or optimized outputs as derivatives.

Complete when:
- Generated derivatives and report artifacts are persisted, visible in run detail, and intentionally accepted or rejected by the operator.

### Geometric detail levels

Geometric LOD Generator 1.0.1 accepts a static, self-contained GLB with one scene.
It runs on the CPU in its installed container. It rejects animation, skins,
morph targets, external dependencies, and unsupported glTF extensions. Convert
other source formats with an appropriate upstream component before binding its
GLB output to the generator. The original source remains unchanged.

The component returns high, medium, and low detail GLBs plus a report. The
`lod_preview` binding aliases the medium output. At target ratio `r`, high targets
`sqrt(r)`, medium `r`, and low `r²` of each original mesh's triangles. Counts must
form a non-increasing ladder. The error limit defaults to `0.001` of each mesh's
world-space bounding-box diagonal. Reduction is accepted only when bidirectional
vertex, edge-midpoint, and triangle-centroid samples stay within the limit.
Otherwise the preceding geometry is retained and the report explains why.
Equal levels can therefore be an expected conservative result.

Sampling is not a continuous surface-distance or appearance guarantee. Check
textures, material boundaries, source/output hashes, and file sizes in the
report, then review representative models in the intended viewer. Export can
repack resources or increase bytes even when triangle counts decrease. The
component declares one CPU, 8 GiB RAM, and a 600-second timeout; representative
large models require resource measurements before changing deployment settings.

The repository component README at
`external_code/geometric_lod_generator/README.md` gives build instructions, CPU
regression commands, and packaged-image acceptance checks. HPC Mesh Optimization
& Preview is a separate workflow: static embedded GLB, an active GPU allocation,
per-material geometry budgets, and renderer checks. Its corpus and acceptance
commands are in `external_code/mesh_optimizer/validation/README.md`. A disconnected
cluster leaves those GPU checks pending; local CPU results do not establish HPC
readiness.

## Run 3D Point Cloud Readiness

Primary actor: operator or publishing user validating point-cloud assets.

Entry points:
- UI: `/tools/pipeline-constructor`
- API: `/api/v2/pipelines/3d_point_cloud_readiness`
- API: `/api/v2/pipelines/3d_point_cloud_readiness/execute`
- API: `/api/v2/runs/<run_id>`

Workflow:
1. Select PLY, LAS, LAZ, E57, or similar point-cloud files from a session.
2. Run constructor preflight to resolve the session file paths.
3. Execute point-cloud analysis, model profiling, viewer readiness, and fingerprinting.
4. Review point count, fields, format hints, viewer suitability, and deduplication signatures.
5. Decide whether optimization, decimation, metadata correction, or manual review is needed.

Complete when:
- The run reports point-cloud readiness results and persisted artifacts are available for review.

## Review Scholarly Readiness And Rights Context

Primary actor: collection steward, researcher, curator, or publishing user.

Entry points:
- Pipeline reports: `/api/v2/runs/<run_id>`
- Session provenance report
- Public presentation review
- Zenodo draft review

Workflow:
1. Confirm whether each file is a source asset, derivative, report, or preview.
2. Review QA recommendations as technical evidence, not as automatic publication approval.
3. Check that rights, license, access limits, and sensitive cultural context have been reviewed outside the component report.
4. Use profiling, dependency audit, and point-cloud reports to improve EDM, IIIF, METS, Zenodo, and project metadata when applicable.
5. Record the pipeline identifier, pipeline version, component versions, execution profile, run ID, and report artifacts in project notes when results support research claims.

Complete when:
- Technical findings and scholarly decisions are both recorded before publication, public record demonstration, or derivative reuse.

## Execute From Pipeline Constructor

Primary actor: pipeline author or operator.

Entry points:
- UI: `/tools/pipeline-constructor`
- API: `/api/v2/pipelines/constructor/preflight`
- API: `/api/v2/pipelines/<identifier>/execute`
- API: `/api/v2/runs/<run_id>`

Workflow:
1. Select one of the optional 3D pipelines.
2. Enter a session ID and local file paths, or choose files from the session file browser.
3. Run preflight to inspect resolved inputs.
4. Click Run Pipeline to execute against the same file list.
5. Review persisted step statuses, outputs, and artifact/report paths in the execution panel.

Complete when:
- The execution panel shows the run summary, step results, and report artifacts for the selected run.

## Execute From API Or Automation

Primary actor: API client, developer, or operator script.

Entry points:
- API: `/api/v2/pipelines/<identifier>/execute`
- API: `/api/v2/runs/<run_id>`
- Optional Celery task: `execute_pipeline_task`

Workflow:
1. Authenticate as a user with access to the target session.
2. Submit `session_id`, selected local file paths or record IDs, and execution options.
3. Use synchronous execution for short local checks or asynchronous execution for queued runs.
4. Poll `/api/v2/runs/<run_id>` for terminal state and artifacts.
5. Persist downstream decisions in the session or publication workflow when needed.

Complete when:
- The API client has a terminal run state plus structured result, step list, and artifact paths.

## Prerequisites And Permissions

- Users must have access to the target session and selected files.
- Pipeline authoring and constructor save actions require administrator or native pipeline author capability.
- Local Docker execution requires installed `local_docker` profiles and a deployment that allows local HDP Components.
- HPC execution requires component manifests with HPC profiles, installed SIF artifacts, and active HPC-Link allocation behavior.
- Publication derivative workflows should not silently replace scholarly source assets; repaired or normalized outputs are explicit derivatives.
- Rights, cultural sensitivity, collection policy, and data-protection review remain project responsibilities even when technical QA passes.
- Pipeline outputs should be cited with run and component evidence when used in publications, reports, or project deliverables.

## Inputs, Outputs, And State

| Input | Output | State To Watch |
|---|---|---|
| Session ID and local file paths | Native pipeline run | run status, run ID, selected pipeline version |
| Source 3D model | Analysis reports | geometry QA, dependency audit, viewer readiness, fingerprints |
| Source model plus derivative pipeline | Derivative files and reports | canonical asset, normalized asset, repaired asset, LOD preview |
| Point-cloud file | Point-cloud readiness reports | point count, fields, bounds, viewer suitability |
| Component artifacts | Persisted run artifacts | `path`, `metadata.role`, record association |
| Component and pipeline versions | Reproducibility context | pipeline identifier, pipeline version, component versions, profile IDs |
| Analysis fields for publication metadata | FAIR and standards enrichment | type, geometry counts, dimensions, units, dependencies, viewer suitability |
| Rights and access decisions | Publication policy state | license, public/private status, cultural sensitivity notes, manual approval |

## Failure And Recovery

- If a pipeline is missing from the list, install or import the required components and rerun seeding.
- If preflight cannot resolve a path, use session-scoped files or correct the local path list.
- If local Docker execution fails, inspect image availability, allowlist policy, and component smoke-test output.
- If an artifact path is missing, inspect the component response contract and adapter path translation.
- If derivative generation fails, keep the original source asset unchanged and rerun only after the component or input issue is fixed.
- If a technical report passes but rights, access, or cultural context is unresolved, hold the asset in manual review instead of treating the report as publication clearance.
- If analysis values conflict with curator knowledge, prefer manual review and record the discrepancy rather than overwriting scholarly metadata automatically.

## Optimization Targets

- Keep analysis-first pipelines non-mutating and fast enough for pre-publication triage.
- Reuse structured JSON outputs for validation reports, dashboard warnings, EDM enrichment, and pipeline triggers.
- Avoid running derivative generation until analysis reports indicate that publication processing is appropriate.
- Prefer explicit pipeline versions for local Docker versus HPC profile choices.
- Keep artifact registration consistent so reports remain visible from API and UI run detail.
- Expose clear report labels so non-technical reviewers can separate source assets, derivatives, QA findings, and viewer recommendations.
- Keep enough provenance in reports for FAIR reuse, including tool identity, version, run context, and input file identity.

## Verification Checklist

- Confirm all required 3D component manifests validate.
- Confirm optional 3D pipelines seed only when all required components are active.
- Validate each optional pipeline definition through `/api/v2/pipelines/validate`.
- Run constructor preflight for a GLB or PLY sample.
- Execute `3d_point_cloud_readiness` or another representative pipeline and inspect `/api/v2/runs/<run_id>`.
- Confirm the Pipeline Constructor execution panel shows run summary, step outputs, and artifact/report paths.
- Confirm source assets and generated derivatives are labeled distinctly in project review.
- Confirm rights/license/access review is recorded separately from technical QA status.
- Confirm run ID, pipeline version, component versions, and report artifacts are retained for citation or audit.

Related docs:
- `docs/workflows/3d-hdp-component-lifecycle.md`
- `docs/workflows/pipelines-components-playground.md`
- `docs/guides/hdp_component_hpc_installation.md`
- `docs/architecture/pipeline_platform_contract.md`

## Codebase Starting Points

- Optional pipeline definitions: `constants.py`
- Native pipeline seeding and execution: `services/native_pipeline_system.py`
- Runtime adapters: `services/native_pipeline_adapters.py`
- Native pipeline routes: `routes/pipeline_v2_routes.py`
- Pipeline Constructor UI: `frontend/src/views/admin/PipelineConfigView.vue`
- Constructor side panel: `frontend/src/components/admin/pipeline/PipelineConstructorSidePanel.vue`
- 3D component manifests: `external_code/*/component.yaml`
