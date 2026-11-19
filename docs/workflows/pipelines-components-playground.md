# Pipelines, Components, And Playground Workflows

This document covers WebHDP's executable pipeline platform and standalone
component execution surfaces.

## Overview

These workflows explain how WebHDP executes processing work. They cover the
built-in publication pipelines, native pipeline definitions, reusable
components, Pipeline Constructor, preflight, Playground, and component
installation. Users can read the workflow sections to understand what runs;
maintainers can use the lower sections to tune execution and component behavior.

## Use Cases

- Select and run the built-in `render` or `metadata_only` publication pipelines.
- Add, validate, version, or execute native pipeline definitions.
- Import, test, or install components for Pipeline Constructor and Playground.
- Diagnose component preflight, run polling, artifact download, and pipeline execution behavior.

## Built-In Publication Pipelines

Pipeline selection and submission review show a GPU requirement when a selected
component profile needs one. A session with no allocation can still be prepared.
When processing requests a GPU, the submission view distinguishes the WebHDP
queue from a request waiting for the HPC scheduler. The scheduler can report
that no resources match the request yet or that it is prioritizing other jobs.
GPU availability can change while you prepare a workflow. A running allocation
and successful runtime preflight are required to use a newly requested GPU.

Primary actor: publishing user or API client.

Entry points:
- UI: `/workflow/pipeline`
- UI: `/workflow/submit`
- API: `/api/v1/pipelines`
- API: `/api/v1/pipelines/<identifier>`
- API: `/api/v1/pipelines/<identifier>/execute_on_local_files`
- API: `/api/v1/pipelines/executions/<execution_uuid>/status`
- API: `/api/v1/start-pipeline`
- API: `/api/v2/pipelines/<identifier>/execute`
- Celery: `execute_submission_pipeline_task`
- Celery: `execute_pipeline_task`

Built-in pipeline IDs:
- `render`: Fast 3D Model Renderer & Zenodo Submission Pipeline.
- `metadata_only`: low-resource metadata-only publishing.

Legacy aliases mapped to `render`:
- `glb_simple`
- `full_workflow`
- `fast-render`
- `ingestion`

Workflow:
1. List available pipelines.
2. Select a pipeline for the session.
3. Execute the pipeline on selected files, record IDs, or execution items.
4. Poll run or execution status.
5. Persist submission and session state.

Complete when:
- The pipeline run reaches completed or failed state and the result is persisted.

## Built-In Pipeline Step Workflows

Primary actor: pipeline execution engine.

Built-in step IDs:
- `fast_renderer`: render previews and thumbnails from 3D models.
- `any_to_usdz`: convert supported 3D assets to USDZ.
- `zenodo_draft`: create Zenodo draft depositions.
- `lod_generation`: generate EDM, IIIF, and METS outputs.
- `zenodo_upload`: upload prepared files to Zenodo and optionally publish.
- `input_file_classification`: classify file facts for constructor triggers and branching.

Workflow:
1. Resolve enabled steps from pipeline configuration.
2. Build per-record execution context.
3. Execute each enabled component or built-in handler.
4. Collect generated files and structured step outputs.
5. Register outputs in `.hdpc` and submission results.

Complete when:
- Every enabled step has produced success, failure, warning, or skipped status for each record.

## HDP Component Boundary

HDP Components are separate executable packages. WebHDP hosts, validates,
installs, versions, and orchestrates them, but an external component is not a
Flask module or a frontend bundle inside the main WebHDP application. The
canonical package shape is an `external_code/<component_name>/component.yaml`
manifest plus the component runner files and at least one installable execution
artifact.

Component distribution metadata makes this boundary visible:

- Core WebHDP components can be bundled with the app for stable publication
  behavior, for example `fast_renderer`, `any_to_usdz`, and
  `input_file_classification`.
- External HDP Components use `distribution.tier: external_installable`,
  `distribution.bundled_with_webhdp: false`, and an explicit
  `distribution.installation_scope`.
- Installable components can be registered for `local_container`, `hpc_sif`, or
  both. Installing a second strategy for the same component version merges the
  new execution profile into the existing native component version.

## Optional 3D Analysis Pipelines

The 3D analysis and processing pipelines are optional native pipelines. They
are seeded only after all required HDP Components are registered, so a default
WebHDP installation does not expose broken pipelines that reference missing
external packages.

Optional pipeline IDs:

- `3d_prepublication_analysis`: non-mutating analysis. It classifies the source
  asset, profiles technical metadata, audits texture/dependency completeness,
  runs geometry QA, scores viewer readiness, and computes fingerprints.
- `3d_publication_derivatives`: explicit derivative generation. It creates a
  canonical GLB-style derivative, spatial normalization output, repaired output,
  geometric LOD preview, and viewer-readiness report.
- `3d_point_cloud_readiness`: point-cloud focused readiness for PLY/LAS/LAZ/E57
  style assets. It runs point-cloud analysis, profiling, viewer readiness, and
  fingerprinting.

These pipelines currently use local Docker execution profiles from the
installed components. They are appropriate for workstation-local deployments
with `WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=true` and a deliberate Docker image
allowlist. A production HPC deployment can use the same pipeline shape after
the component manifests add `hpc_sif` profiles and the components are installed
through HPC-Link/Singularity.

The Pipeline Constructor can now execute a selected pipeline against the
preflight file list, then reload the persisted native run. Operators should
review the persisted step results and generated report artifacts before using
the outputs in a publication workflow.

## Native Pipeline Platform

Primary actor: pipeline author, administrator, or API client.

Entry points:
- API: `/api/v2/platform-support`
- API: `/api/v2/pipelines`
- API: `/api/v2/pipelines/validate`
- API: `/api/v2/pipelines/<identifier>`
- API: `/api/v2/pipelines/<identifier>/versions`
- API: `/api/v2/pipelines/<identifier>/execute`
- API: `/api/v2/runs/<run_id>`

Workflow:
1. Inspect platform support.
2. List or validate pipeline definitions.
3. Create a new active pipeline version.
4. Execute a registered pipeline.
5. Poll the native run record.

Complete when:
- The pipeline definition is registered and executable through the native platform.

## Component Registry And Import

Primary actor: pipeline author or administrator.

Entry points:
- API: `/api/v2/components`
- API: `/api/v2/components/validate`
- API: `/api/v2/components/import`

Workflow:
1. List registered components.
2. Validate a component manifest.
3. Import a manifest-backed component.
4. Use the component in Playground or Pipeline Constructor when supported by its manifest.

Complete when:
- The component version is active and visible through the native component registry.

## Pipeline Constructor

Primary actor: pipeline author.

Entry points:
- UI: `/tools/pipeline-constructor`
- API: `/api/v2/pipelines/constructor-support`
- API: `/api/v2/pipelines/constructor/preflight`
- API: `/api/v2/pipelines/<identifier>/versions`

Workflow:
1. Inspect components, schemas, trigger fields, and output selectors.
2. Compose pipeline steps and mappings.
3. Run constructor preflight.
4. Optionally execute the selected pipeline against the preflight file list and
   review persisted step results and report artifacts.
5. Save a new pipeline version.

Complete when:
- The authored pipeline validates and an active version is available.

## Pipeline Preflight

Primary actor: pipeline author, operator, or publishing user validating local inputs.

Entry points:
- UI: `/tools/pipeline-preflight`
- API: `/api/v1/tools/pipeline-preflight/local`

Workflow:
1. Choose local files, pipeline configuration, and validation options.
2. Run preflight before executing expensive or remote component work.
3. Review warnings, blocking errors, and execution readiness.

Complete when:
- The target pipeline inputs are confirmed executable or the blocking issues are known.

## Native Playground

Primary actor: authenticated user testing components.

Entry points:
- UI: `/tools/playground`
- UI redirect: `/tools/native-playground`
- API: `/api/v2/playground/execute`
- API: `/api/v2/playground/runs/<run_id>`
- API: `/api/v2/playground/runs/<run_id>/cancel`
- API: `/api/v2/playground/runs/<run_id>/artifacts/<artifact_index>`
- API: `/api/v2/playground/sessions/<session_id>/file`

Built-in Playground-capable components:
- `fast_renderer`
- `any_to_usdz`
- `input_file_classification`

Additional imported components can be Playground-capable when their manifests
declare compatibility.

Workflow:
1. Select a registered Playground-capable component.
2. Select session-backed files and parameter values.
3. Queue the component through the native adapter system. The browser saves the request ID and reconnects to the same run after a refresh or reopening the dialog.
4. Review JSON results, logs, and downloadable artifacts.

Execution requires edit permission on a mutable session. Readers of an institution-shared session can inspect its runs and download permitted session files. All file and directory inputs, including imported components' parameters, resolve inside the selected session; traversal and symlink escapes are rejected before dispatch and checked again by the worker.

API clients can send `async_execution: true` and a UUID `request_id`. Retry an unconfirmed request with the same ID and unchanged payload. The run pins its registered component version and execution profile. `timeout_seconds` defaults to 3600 and accepts values from 1 to 86400. Synchronous execution remains available for existing clients.

Queued runs can be cancelled from Playground, Pipeline Constructor, or submission progress. Cancellation persists before returning, so a late delivery cannot execute the cancelled request. A preparation reservation abandoned by a web process expires after 120 seconds when no dispatcher holds its shared lock. Running jobs remain protected by the project execution lock regardless of age. Interrupted work retains its files and drafts for review.

Complete when:
- The Playground run reaches completed or failed state and artifacts are available.

## HDP Component Installer

Primary actor: administrator.

Entry points:
- UI: `/tools/hdp-components/install`
- API: `/api/v1/tools/hdp-components/catalog`
- API: `/api/v1/tools/hdp-components/validate`
- API: `/api/v1/tools/hdp-components/install`
- API: `/api/v1/tools/hdp-components/installations`
- API: `/api/v1/tools/hdp-components/installations/<installation_id>`
- API: `/api/v1/tools/hdp-components/installations/<installation_id>/test`

Workflow:
1. Choose an install strategy: `local_container` for workstation Docker or `hpc_sif` for HPC-Link/Singularity.
2. List component manifests installable by that strategy.
3. Validate the manifest and execution artifact source: Docker image for local installs, SIF source for HPC installs.
4. For local installs, verify Docker policy and image availability, then register the component in the native registry.
5. For HPC installs, ask HPC-Link to install or verify the SIF, then import the installed component into the native registry.
6. Run a smoke test when the manifest declares one. Local Docker tests use `install.test`; HPC tests use `hpc.test`.
7. If the same component version is later installed for the other strategy, merge the new profile into the existing native component version rather than creating a duplicate component.

Complete when:
- The component installation is `installed`, registered with the intended strategy/profile, and smoke-tested when applicable.

## Current Component Lifecycle

Recommended flow for new HDP Components:

1. Create `external_code/<component_name>/component.yaml`, a runner, and any
   required files listed in `structure.required_files`.
2. Declare distribution metadata, manifest inputs/outputs, compatibility, and
   one or more execution profiles.
3. Validate locally with `scripts/validate_hdp_components.py` or
   `make hdp-components-check`.
4. Build or publish the execution artifact outside WebHDP: a Docker image for
   `local_container` or a Singularity/Apptainer SIF for `hpc_sif`.
5. Install through Tools -> HDP Component Installer or import the component
   manifest through `/api/v2/components/import`.
6. Smoke test the installed strategy. Local Docker uses `install.test`; HPC SIF
   uses `hpc.test`.
7. Use the component from Playground, Pipeline Constructor, or seeded native
   pipelines. Optional pipelines appear only after their referenced component
   versions are registered.

## Prerequisites And Permissions

- Built-in pipeline execution requires edit access to the target session and selected files or records.
- Pipeline authoring, constructor saves, component import, and installer workflows require administrator or pipeline-author capability.
- Playground execution requires an authenticated user and a Playground-capable component.
- Local container installation requires a workstation-local deployment with safe Docker CLI access from the backend/worker process and a deliberate image policy.
- SIF-backed installation requires configured HPC-Link and valid component manifests.

## Inputs, Outputs, And State

| Input | Output | State To Watch |
|---|---|---|
| Pipeline ID, session ID, files, records, or execution items | Pipeline run result | run status, progress summary, generated artifacts |
| Pipeline definition | Validated or versioned native pipeline | pipeline version, active flag, validation errors |
| Component manifest | Registered component version | component key, manifest validation, Playground compatibility |
| Playground request | Standalone component run and artifacts | run logs, artifact indexes, session file access |
| HDP component install request | Installed local Docker or HPC SIF component | installation strategy, distribution tier, policy check, status, smoke test result |

## Failure And Recovery

- Pipeline failures should be traced through run status, step result, generated artifacts, and submission progress.
- Invalid pipeline definitions should be fixed through constructor preflight before creating versions.
- Component import failures should be resolved at manifest validation before runtime execution.
- Playground artifact download failures should check run ownership, artifact index, and stored artifact path.

## Optimization Targets

- Reduce per-record overhead in native pipeline execution.
- Keep progress updates useful without excessive polling or database writes.
- Cache component and constructor support metadata where possible.
- Make preflight catch expensive runtime failures before execution starts.
- Keep artifact registration and `.hdpc` writes efficient for large outputs.

## Verification Checklist

- Verify pipeline list/detail and built-in `render` and `metadata_only` execution.
- Verify native pipeline validation, version creation, execution, and run polling.
- Verify component list, validate, import, and installer smoke test.
- Verify Pipeline Constructor support and preflight.
- Verify Playground execution, run detail, session file access, and artifact download.

Related docs:
- `docs/architecture/pipeline_platform_contract.md`
- `docs/guides/hdp_component_hpc_installation.md`
- `docs/guides/video_guides/components_and_development.md`
- `external_code/*/component.yaml`

## Codebase Starting Points

- Workflow pipeline UI: `frontend/src/views/workflow/PipelineView.vue`, `frontend/src/views/workflow/SubmitView.vue`
- Tools UI: `frontend/src/views/tools/NativePlaygroundView.vue`, `frontend/src/views/tools/PipelinePreflightView.vue`
- Admin pipeline UI: `frontend/src/views/admin/PipelineConfigView.vue`
- Legacy pipeline routes: `routes/pipeline_routes.py`
- Native pipeline routes: `routes/pipeline_v2_routes.py`
- Tool routes for preflight and installer: `routes/tools_routes.py`
- Native pipeline engine: `services/native_pipeline_system.py`
- Submission pipeline execution: `services/submission_pipeline_service.py`, `tasks.py`
- Built-in definitions and aliases: `constants.py`
