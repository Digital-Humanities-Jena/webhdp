# WebHDP Workflow Guide

This page is the workflow index for WebHDP. Use it when you know the job you want to complete and need the right guide, prerequisite page, verification point, or follow-up workflow without searching across the full documentation portal.

For an exhaustive inventory of UI, API, background job, native pipeline, and operator-script workflows, use the [Complete Workflow Inventory](../workflows/README.md).

## Workflow Paths

| Goal | Start Here | Complete When |
|---|---|---|
| Publish a new dataset | [End-to-End User Guide](end_to_end_user_guide.md) | The submission reaches `completed`, Zenodo links are present, and provenance/records match the intended source files. |
| Review and repair MSF-driven batch metadata | [End-to-End User Guide](end_to_end_user_guide.md#step-2-msf-qa-batch-only) | Record-resolution actions are saved, blocking MSF issues are repaired or accepted, and the workflow can advance to file review. |
| Retrieve an existing Zenodo account inventory | [Zenodo Account Deep Retrieval](zenodo_account_retrieval.md) | The retrieval job is `SUCCESS`, shard sessions are generated, and search/export/compaction options reflect the collection state. |
| Prepare or repair account credentials | [Zenodo API Keys](zenodo_api_keys.md) and [Security and Credentials](security_and_credentials.md) | The intended Sandbox or Production key is saved, active, validated, and share state is accepted where needed. |
| Import an existing `.hdpc` package | [Complete Workflow Inventory](../workflows/README.md) | The imported session opens, record counts look correct, and records are available for explorer or provenance review. |
| Review records and process provenance | [Sessions, Records, And Provenance](../workflows/sessions-records-provenance.md) | Record detail, generated artifacts, source mappings, and provenance evidence are inspected after processing or import. |
| Configure setup, modalities, storage, and credentials | [Operations and Setup Guide](operations_and_setup_guide.md) | Readiness checks pass and the deployment exposes the expected upload, storage, renderer, credential, and validator behavior. |
| Run local EDM validation | [Local EDM Validator](local_edm_validator.md) | The validator status is healthy and EDM validation reports are persisted with actionable warnings or pass results. |
| Configure installable component execution | [HDP Component Installation](hdp_component_hpc_installation.md), [HPC Single GPU Setup Guide](hpc_single_gpu_setup_guide.md), and [HDP Server Integration Guide](hdp_server_integration_guide.md) | The chosen local Docker or HPC-Link/Singularity strategy is validated, the component runner is reachable, and workflow preflight can see the enabled component steps. |
| Turn a container into an HDP Component | [Build Your First HDP Component](../development/first_hdp_component.md) | The package has a manifest, runner, container image, smoke test, and passing component validation. |
| Create and install 3D HDP Components | [3D HDP Component Lifecycle](../workflows/3d-hdp-component-lifecycle.md) | The component manifests validate, runtime artifacts exist for the chosen strategy, and installed profiles are visible in the native component registry. |
| Run optional 3D analysis and processing pipelines | [3D Analysis And Processing Pipelines](../workflows/3d-analysis-processing-pipelines.md) | The selected optional pipeline preflights, executes, and exposes persisted step results plus report artifacts. |
| Operate, recover, or release a deployment | [Operations and Setup Guide](operations_and_setup_guide.md), [Troubleshooting Guide](troubleshooting.md), and [Restore Drill Checklist](restore_drill_checklist.md) | Health checks, backup/restore checks, queue state, and release readiness checks are clean for the target environment. |
| Present or embed public records | [Public Records And Operations Walkthroughs](video_guides/public_records_and_operations.md) and [WebHDP API Reference](../api/webhdp_api_reference.md) | Public record pages and oEmbed responses expose the intended metadata, media, credits, and fallback behavior. |
| Confirm a developer environment | [Developer Onboarding](../development/onboarding.md) and [Golden Sample Workflow](../development/golden_workflow.md) | Local setup, docs checks, API contract checks, component validation, and the golden workflow complete successfully. |

## Publication Workflow

The normal publication path is documented in the [End-to-End User Guide](end_to_end_user_guide.md). It follows the stages below. The interface shows six steps for a single file and seven for a batch; spreadsheet checks appear only for a batch:

1. Upload or scan source files.
2. Complete MSF QA when the session is MSF-driven batch mode.
3. Review discovered files and choose the processing set.
4. Save submission metadata or confirm MSF-derived metadata.
5. Select EDM/LOD behavior and validate output.
6. Choose the pipeline.
7. Submit, monitor processing, and verify records/provenance.

Completion criteria:
- Session upload state has moved from `queued` to `scanned`.
- All selected source files are intentional and auditable.
- Metadata has no blocking validation errors.
- EDM/LOD selections are saved to the session draft.
- A pipeline is selected before submit.
- The final submission reaches `completed` or a failure is triaged from the submission detail page.

Related pages:
- [Glossary](glossary.md) for workflow terms
- [Operations and Setup Guide](operations_and_setup_guide.md) for deployment prerequisites
- [WebHDP API Examples](../api/webhdp_api_examples.md) for integration examples
- [WebHDP API Reference](../api/webhdp_api_reference.md) for route-level behavior

## MSF Batch Workflow

MSF-driven publication adds a guided QA branch between upload and file review. This branch is complete only after WebHDP knows which MSF file is active, how it should be parsed, and whether record-resolution decisions are required.

Use this flow when a batch directory or ZIP contains an MSF file:

1. Select the directory or ZIP and the MSF source.
2. Run MSF preflight so parse options, column mapping, and file references are known.
3. Resolve duplicate/version/hash-collision candidates if the record-resolution panel appears.
4. Apply guided MSF repair for blocking metadata or file-reference issues.
5. Start the local scan when local storage mode prepared a session before scanning.
6. Continue to file review only after the workflow monitor reports the scan as complete.

Important distinction:
- Hash collisions are warnings until the affected candidate has a saved action.
- Missing required metadata, unresolved file references, and unsaved record-resolution plans are workflow gates.

## Credential Workflow

Credential setup is often the prerequisite for publication, retrieval, and shared institutional publishing. Use:

- [Zenodo API Keys](zenodo_api_keys.md) for named Sandbox and Production keys.
- [Security and Credentials](security_and_credentials.md) for encryption, sharing, recovery codes, and validation behavior.
- [Release Walkthrough Videos](video_guides/release_walkthroughs.md) for accepted replayable workflow recordings.

Completion criteria:
- The credential environment matches the intended target.
- The key is active for the user or accepted as a share.
- Live validation has succeeded when write access must be proven.
- Production validation is run deliberately because it creates and deletes a temporary draft.

## Retrieval Workflow

Use [Zenodo Account Deep Retrieval](zenodo_account_retrieval.md) when the source of truth is an existing Zenodo account rather than a new upload session. That workflow creates explorer-only `.hdpc` shard sessions for inspection, search, export, compaction, and incremental follow-up retrieval.

Retrieval-generated sessions are intentionally read-only. They support record browsing and audit work, but they do not become publishable workflow sessions.

Completion criteria:
- A full, bounded, or incremental retrieval job reaches `SUCCESS`.
- The generated shard sessions open in Records or Explorer views.
- Exported manifest/CSV/archive files reflect the intended credential, environment, scope, and filters.
- Incremental schedules, retention, and compaction settings are saved when the collection will be maintained over time.

## Import And Review Workflow

Use the `.hdpc` import workflow when records already exist in a WebHDP-compatible package and should be inspected or migrated without repeating the upload pipeline.

1. Open the HDPC import action.
2. Select the `.hdpc` package.
3. Start the import and wait for completion feedback.
4. Open the resulting session.
5. Verify record count, record details, attachments, and provenance.
6. Use explorer, export, or public record demonstration workflows as appropriate.

Imported sessions should be treated as existing evidence unless a separate publication rerun is deliberately started from source files.

## Operator Workflow

Operators should pair user workflow docs with:

- [Operations and Setup Guide](operations_and_setup_guide.md) for setup, environment, modes, and release readiness.
- [Troubleshooting Guide](troubleshooting.md) for diagnostics and recovery.
- [Restore Drill Checklist](restore_drill_checklist.md) for backup restore validation.
- [Local EDM Validator](local_edm_validator.md) for local validation behavior.
- [Storage Modes Architecture](../storage_modes_architecture.md) for storage-mode constraints.
- [Cloud Storage](../cloud_storage.md) for mirror/download behavior.
- [Renderer Configuration](../renderer_configuration.md) for render service configuration.
- [HDP Component Installation](hdp_component_hpc_installation.md) for local Docker and HPC component execution.

Completion criteria:
- `/api/v1/readiness` and operator-facing status pages report healthy dependencies.
- Backup and restore checks match the deployment's recovery objective.
- Storage mode, CORS, Celery, validator, renderer, Zenodo, and HPC settings match the features exposed in the UI.
- Degraded modes are documented before users rely on the deployment.

## Public Record Demonstration Workflow

Use [Public Records And Operations Walkthroughs](video_guides/public_records_and_operations.md) and the public-record API reference after records are published or imported and need to be demonstrated, embedded, or shared outside the operator UI.

Completion criteria:
- Public record pages show title, credits, media, and identifiers correctly.
- oEmbed responses return stable embeddable metadata for supported records.
- Fallback screenshots, sample records, and demo links are prepared before live presentation.

## Video Walkthroughs

The alpha tree ships only accepted walkthrough videos that demonstrate complete
workflows. Provisional automated captures were rejected because they did not
demonstrate complete workflows.

Use [Release Walkthrough Videos](video_guides/release_walkthroughs.md) for
accepted recordings. Add new recordings only after they show a complete
workflow, use repeatable local or synthetic data, and avoid credentials, private
endpoints, and personal filesystem paths.

## Developer Workflow

Developers changing workflow behavior should keep code, tests, and docs aligned:

- [Developer Onboarding](../development/onboarding.md)
- [First PR Walkthrough](../development/first_pr_walkthrough.md)
- [Contributor Architecture Map](../development/architecture_map.md)
- [PR Size And Scope Examples](../development/pr_scope_examples.md)
- [Known Development Warnings](../development/known_warnings.md)
- [Architecture Decision Records](../development/adr/README.md)

Workflow changes commonly affect upload/scan state, `.hdpc` persistence, session access, metadata normalization, publication context resolution, pipeline selection, submit/rerun behavior, and frontend resume behavior. Update the [System Architecture](../architecture/system_architecture.md), [HDPC Schema](../architecture/hdpc_schema.md), API docs, and this workflow guide when those contracts change.
