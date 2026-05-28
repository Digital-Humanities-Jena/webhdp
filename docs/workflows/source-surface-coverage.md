# Workflow Source Surface Coverage

This document is the audit checklist for confirming that executable WebHDP
surfaces are represented in `docs/workflows`. It maps source-code surfaces to
the workflow document that owns them. Support endpoints are listed with the
workflow they enable rather than as independent workflows.

## Overview

This document is not a user guide. It is the maintainer-facing traceability map
that proves each frontend route, backend route family, background task, native
pipeline surface, and script has a documented workflow owner. Use it when adding
or changing executable surfaces so the macro workflow docs stay complete.

## Use Cases

- Verify that a new route, task, pipeline, or script is mapped into workflow documentation.
- Identify the owning workflow document before changing a source-code surface.
- Audit whether macro workflow docs still cover the implementation surface.
- Give maintainers a repeatable checklist for documentation coverage reviews.

## Frontend Route Coverage

| Route | Route Name | Workflow Document |
|---|---|---|
| `/` | `Landing` | [Public, Docs, And Profiles](public-docs-profiles.md) |
| `/setup` | `Setup` | [Access, Setup, And Identity](access-setup-identity.md) |
| `/login` | `Login` | [Access, Setup, And Identity](access-setup-identity.md) |
| `/register` | `Register` | [Access, Setup, And Identity](access-setup-identity.md) |
| `/verify-email/:token` | `VerifyEmail` | [Access, Setup, And Identity](access-setup-identity.md) |
| `/docs` | `DocumentationHub` | [Public, Docs, And Profiles](public-docs-profiles.md) |
| `/docs/:docId` | `DocumentationDoc` | [Public, Docs, And Profiles](public-docs-profiles.md) |
| `/credits` | `Credits` | [Public, Docs, And Profiles](public-docs-profiles.md) |
| `/impressum` | `Impressum` | [Public, Docs, And Profiles](public-docs-profiles.md) |
| `/privacy` | `PrivacyPolicy` | [Public, Docs, And Profiles](public-docs-profiles.md) |
| `/cookies` | `CookiePolicy` | [Public, Docs, And Profiles](public-docs-profiles.md) |
| `/p/records/:environment/:zenodoRecordId` | `PublicRecord` | [Public, Docs, And Profiles](public-docs-profiles.md) |
| `/embed/records/:environment/:zenodoRecordId` | `EmbedRecord` | [Public, Docs, And Profiles](public-docs-profiles.md) |
| `/dashboard` | `Dashboard` | [Sessions, Records, And Provenance](sessions-records-provenance.md) |
| `/onboarding` | `Onboarding` | [Access, Setup, And Identity](access-setup-identity.md) |
| `/hpc-resources` | `HpcResources` | [HPC, Cloud, And Storage](hpc-cloud-storage.md) |
| `/notifications` | `Notifications` | [Issues And Notifications](issues-notifications.md) |
| `/developer` | `DeveloperMode` | [Developer And Operator Scripts](developer-operator-scripts.md) |
| `/admin/dashboard` | `AdminDashboard` | [Admin Operations And Observability](admin-operations-observability.md) |
| `/admin/setup` | `AdminSetupGuidance` | [Admin Operations And Observability](admin-operations-observability.md) |
| `/admin/review/:id` | `AdminReview` | [Admin Operations And Observability](admin-operations-observability.md) |
| `/admin/hpc-access` | `AdminHpcAccess` | [HPC, Cloud, And Storage](hpc-cloud-storage.md) |
| `/admin/session-monitoring` | `AdminSessionMonitoring` | [Admin Operations And Observability](admin-operations-observability.md) |
| `/settings/pipelines` | `PipelineConfig` | [Admin Operations And Observability](admin-operations-observability.md) |
| `/settings/edm` | `EdmConfig` | [Admin Operations And Observability](admin-operations-observability.md) |
| `/settings/edm-templates` | `EdmTemplates` | [Metadata, Standards, And Templates](metadata-standards-templates.md) |
| `/settings/cloud-testing` | `CloudTesting` | [HPC, Cloud, And Storage](hpc-cloud-storage.md) |
| `/settings/storage` | `StorageConfig` | [HPC, Cloud, And Storage](hpc-cloud-storage.md) |
| `/settings/mfa` | `MfaConfig` | [Admin Operations And Observability](admin-operations-observability.md) |
| `/settings/modalities` | `ModalityConfig` | [Admin Operations And Observability](admin-operations-observability.md) |
| `/settings/observability/credentials` | `ObservabilityCredentials` | [Admin Operations And Observability](admin-operations-observability.md) |
| `/settings/observability/api-activity` | `ObservabilityApiActivity` | [Admin Operations And Observability](admin-operations-observability.md) |
| `/settings/observability/notifications` | `ObservabilityNotifications` | [Admin Operations And Observability](admin-operations-observability.md) |
| `/workflow/upload` | `Upload` | [Publication, Upload, And MSF](publication-upload-msf.md) |
| `/workflow/msf-analysis` | `MsfAnalysis` | [Publication, Upload, And MSF](publication-upload-msf.md) |
| `/workflow/files` | `Files` | [Publication, Upload, And MSF](publication-upload-msf.md) |
| `/workflow/file-metadata` | redirect | [Metadata, Standards, And Templates](metadata-standards-templates.md) |
| `/workflow/user-metadata` | redirect | [Metadata, Standards, And Templates](metadata-standards-templates.md) |
| `/workflow/metadata` | `SubmissionMetadata` | [Metadata, Standards, And Templates](metadata-standards-templates.md) |
| `/workflow/edm-selection` | `EdmSelection` | [Metadata, Standards, And Templates](metadata-standards-templates.md) |
| `/workflow/submit` | `Submit` | [Publication, Upload, And MSF](publication-upload-msf.md) |
| `/workflow/pipeline` | `Pipeline` | [Pipelines, Components, And Playground](pipelines-components-playground.md) |
| `/workflow/processing` | `Processing` | [Publication, Upload, And MSF](publication-upload-msf.md) |
| `/submissions` | `Submissions` | [Admin Operations And Observability](admin-operations-observability.md) |
| `/submissions/:id` | `SubmissionDetail` | [Admin Operations And Observability](admin-operations-observability.md) |
| `/uploads` | `UploadOperations` | [Publication, Upload, And MSF](publication-upload-msf.md) |
| `/uploads/:sessionId` | `UploadOperationDetail` | [Publication, Upload, And MSF](publication-upload-msf.md) |
| `/sessions/:sessionId/records` | `SessionRecords` | [Sessions, Records, And Provenance](sessions-records-provenance.md) |
| `/sessions/:sessionId/records/:recordId` | `SessionRecordDetail` | [Sessions, Records, And Provenance](sessions-records-provenance.md) |
| `/sessions/:sessionId/provenance-report` | `SessionProvenanceReport` | [Sessions, Records, And Provenance](sessions-records-provenance.md) |
| `/records/explorer` | `CrossSessionRecordsExplorer` | [Sessions, Records, And Provenance](sessions-records-provenance.md) |
| `/datasets/:datasetKey?` | `DatasetIntegrityWorkspace` | [Sessions, Records, And Provenance](sessions-records-provenance.md) |
| `/profiles/users/:identifier` | `UserProfile` | [Public, Docs, And Profiles](public-docs-profiles.md) |
| `/profiles/institutions/:identifier` | `InstitutionProfile` | [Public, Docs, And Profiles](public-docs-profiles.md) |
| `/issues` | `IssuesWorkspace` | [Issues And Notifications](issues-notifications.md) |
| `/issues/report` | `IssueReport` | [Issues And Notifications](issues-notifications.md) |
| `/issues/:issueId` | `IssueDetail` | [Issues And Notifications](issues-notifications.md) |
| `/tools/playground` | `Playground` | [Pipelines, Components, And Playground](pipelines-components-playground.md) |
| `/tools/native-playground` | redirect | [Pipelines, Components, And Playground](pipelines-components-playground.md) |
| `/tools/pipeline-preflight` | `PipelinePreflight` | [Pipelines, Components, And Playground](pipelines-components-playground.md), [3D Analysis And Processing Pipelines](3d-analysis-processing-pipelines.md) |
| `/tools/pipeline-constructor` | `PipelineConstructor` | [Pipelines, Components, And Playground](pipelines-components-playground.md), [3D Analysis And Processing Pipelines](3d-analysis-processing-pipelines.md) |
| `/tools/msf-validator-local` | `MsfValidatorLocal` | [Publication, Upload, And MSF](publication-upload-msf.md) |
| `/tools/msf-reference-repair` | `MsfReferenceRepair` | [Publication, Upload, And MSF](publication-upload-msf.md) |
| `/tools/metadata-normalizer` | `MetadataNormalizer` | [Metadata, Standards, And Templates](metadata-standards-templates.md) |
| `/tools/output-preview-qa` | `OutputPreviewQa` | [Metadata, Standards, And Templates](metadata-standards-templates.md) |
| `/tools/hpc-diagnostics` | `HpcDiagnostics` | [HPC, Cloud, And Storage](hpc-cloud-storage.md) |
| `/tools/hdp-components/install` | `HdpComponentInstaller` | [Pipelines, Components, And Playground](pipelines-components-playground.md), [3D HDP Component Lifecycle](3d-hdp-component-lifecycle.md) |
| `/tools/session-cleanup` | `SessionCleanup` | [Admin Operations And Observability](admin-operations-observability.md) |
| `/tools/zenodo-batch-operations` | `ZenodoBatchOperations` | [Zenodo Retrieval And Communities](zenodo-retrieval-communities.md) |
| `/tools/zenodo-account-retrieval` | `ZenodoAccountRetrieval` | [Zenodo Retrieval And Communities](zenodo-retrieval-communities.md) |
| `/tools/zenodo-oai-harvest` | `ZenodoOaiHarvest` | [Zenodo Retrieval And Communities](zenodo-retrieval-communities.md) |
| `/tools/community-moderation` | `CommunityModeration` | [Zenodo Retrieval And Communities](zenodo-retrieval-communities.md) |
| `/tools/community-migration` | `CommunityMigration` | [Zenodo Retrieval And Communities](zenodo-retrieval-communities.md) |
| `/account/configuration` | `AccountConfiguration` | [Access, Setup, And Identity](access-setup-identity.md) |
| `/account/institutions` | `InstitutionWorkspace` | [Institutions, Credentials, And Governance](institutions-credentials-governance.md) |

## Backend Route Family Coverage

| Route Family | Workflow Document |
|---|---|
| `/api/v1/setup/*` | [Access, Setup, And Identity](access-setup-identity.md) |
| `/api/v1/auth/*` | [Access, Setup, And Identity](access-setup-identity.md), [Institutions, Credentials, And Governance](institutions-credentials-governance.md) |
| `/api/v1/docs/*` | [Public, Docs, And Profiles](public-docs-profiles.md) |
| `/api/v1/public/*`, `/api/v1/profiles/*`, `/api/v1/oembed` | [Public, Docs, And Profiles](public-docs-profiles.md) |
| `/api/v1/sessions/file`, `/api/v1/sessions/directory`, `/api/v1/sessions/tasks/*`, `/api/v1/sessions/upload-operations*`, `/api/v1/upload/stream` | [Publication, Upload, And MSF](publication-upload-msf.md) |
| `/api/v1/msf/*` | [Publication, Upload, And MSF](publication-upload-msf.md) |
| `/api/v1/metadata/*`, `/api/v1/edm/*`, `/api/v1/templates/*`, `/api/v1/tools/metadata-normalizer/local`, `/api/v1/tools/output-preview/local` | [Metadata, Standards, And Templates](metadata-standards-templates.md) |
| `/api/v1/pipelines/*`, `/api/v1/start-pipeline`, `/api/v2/platform-support`, `/api/v2/components*`, `/api/v2/pipelines*`, `/api/v2/runs/*`, `/api/v2/playground/*`, `/api/v1/tools/pipeline-preflight/local`, `/api/v1/tools/hdp-components/*` | [Pipelines, Components, And Playground](pipelines-components-playground.md), [3D HDP Component Lifecycle](3d-hdp-component-lifecycle.md), [3D Analysis And Processing Pipelines](3d-analysis-processing-pipelines.md) |
| `/api/v1/sessions/*`, `/api/v1/datasets/*` | [Sessions, Records, And Provenance](sessions-records-provenance.md) |
| `/api/v1/tools/zenodo-account-retrieval/*`, `/api/v1/tools/zenodo-batch-operations/*`, `/api/v1/tools/community-migrations/*`, `/api/v1/tools/community-moderation/*` | [Zenodo Retrieval And Communities](zenodo-retrieval-communities.md) |
| `/api/v1/institutions/*` | [Institutions, Credentials, And Governance](institutions-credentials-governance.md) |
| `/api/v1/hpc-resource-requests*`, `/api/v1/hpc-link/*`, `/api/v1/admin/hpc-*`, `/api/v1/admin/storage-*`, `/api/v1/tools/hpc-diagnostics` | [HPC, Cloud, And Storage](hpc-cloud-storage.md) |
| `/api/v1/admin/*`, `/api/v1/health`, `/api/v1/readiness`, `/api/v1/tools/context`, `/api/v1/tools/session-cleanup/*` | [Admin Operations And Observability](admin-operations-observability.md) |
| `/api/v1/issues/*`, `/api/v1/notifications/*` | [Issues And Notifications](issues-notifications.md) |
| `/api/v1/developer/status` | [Developer And Operator Scripts](developer-operator-scripts.md) |

## Background Task Coverage

| Task | Workflow Document |
|---|---|
| `send_notification_digests_task` | [Issues And Notifications](issues-notifications.md) |
| `cleanup_notifications_task` | [Issues And Notifications](issues-notifications.md) |
| `finalize_session_upload` | [Publication, Upload, And MSF](publication-upload-msf.md) |
| `start_upload_coordinator` | [Publication, Upload, And MSF](publication-upload-msf.md) |
| `execute_submission_pipeline_task` | [Pipelines, Components, And Playground](pipelines-components-playground.md) |
| `process_single_file_task` | [Publication, Upload, And MSF](publication-upload-msf.md) |
| `execute_session_batch_operation_task` | [Sessions, Records, And Provenance](sessions-records-provenance.md) |
| `execute_zenodo_batch_community_operation` | [Zenodo Retrieval And Communities](zenodo-retrieval-communities.md) |
| `execute_zenodo_account_retrieval` | [Zenodo Retrieval And Communities](zenodo-retrieval-communities.md) |
| `execute_due_zenodo_account_retrieval_schedules` | [Zenodo Retrieval And Communities](zenodo-retrieval-communities.md) |
| `execute_community_migration_job` | [Zenodo Retrieval And Communities](zenodo-retrieval-communities.md) |
| `execute_community_moderation_batch` | [Zenodo Retrieval And Communities](zenodo-retrieval-communities.md) |
| `execute_pipeline_task` | [Pipelines, Components, And Playground](pipelines-components-playground.md) |

## Native Pipeline Coverage

| Native Surface | Workflow Document |
|---|---|
| Built-in pipeline `render` | [Pipelines, Components, And Playground](pipelines-components-playground.md) |
| Built-in pipeline `metadata_only` | [Pipelines, Components, And Playground](pipelines-components-playground.md) |
| Legacy aliases `glb_simple`, `full_workflow`, `fast-render`, `ingestion` | [Pipelines, Components, And Playground](pipelines-components-playground.md) |
| Built-in components `fast_renderer`, `any_to_usdz`, `zenodo_draft`, `lod_generation`, `zenodo_upload`, `input_file_classification` | [Pipelines, Components, And Playground](pipelines-components-playground.md) |
| Component validation, import, registry listing, constructor preflight, Playground artifact download | [Pipelines, Components, And Playground](pipelines-components-playground.md) |
| External 3D components `model_profiler`, `geometry_qa_gate`, `texture_dependency_auditor`, `canonical_glb_normalizer`, `geometric_lod_generator`, `point_cloud_analyzer`, `scale_orientation_centering_normalizer`, `model_repair_component`, `model_fingerprint_deduplication`, `viewer_readiness_analyzer` | [3D HDP Component Lifecycle](3d-hdp-component-lifecycle.md) |
| Optional 3D pipelines `3d_prepublication_analysis`, `3d_publication_derivatives`, `3d_point_cloud_readiness` | [3D Analysis And Processing Pipelines](3d-analysis-processing-pipelines.md) |

## Script Coverage

| Script Or Script Group | Workflow Document |
|---|---|
| `scripts/backup.py`, `scripts/backup_status.py`, `scripts/list_backups.py`, `scripts/prune_backups.py`, `scripts/restore_backup.py`, `scripts/restore_drill.py`, `scripts/scheduled_backup.sh` | [Admin Operations And Observability](admin-operations-observability.md) |
| `scripts/build_images.sh`, `scripts/bump_version.py`, `scripts/check_release_images.py`, `scripts/pre_update.sh`, `scripts/readiness_check.py`, `scripts/release_check.sh`, `scripts/wait_for_celery_drain.py`, `scripts/maintenance.py` | [Developer And Operator Scripts](developer-operator-scripts.md) |
| `scripts/check_developer_docs.py`, `scripts/check_openapi_fresh.py`, `scripts/generate_openapi.py`, `scripts/doctor.py`, `scripts/run_golden_workflow.py`, `scripts/render_pipeline_smoke.py`, `scripts/validate_hdp_components.py`, `scripts/webhdp_agent_cli.py` | [Developer And Operator Scripts](developer-operator-scripts.md), [3D HDP Component Lifecycle](3d-hdp-component-lifecycle.md) |
| `scripts/cleanup_legacy_workflow_state.py`, `scripts/prepare_subset_msf.py` | [Publication, Upload, And MSF](publication-upload-msf.md) |
| `scripts/execute_zenodo_community_append_from_csv.py`, `scripts/launch_zenodo_historical_backfill.py`, `scripts/monitor_zenodo_historical_backfill.py` | [Zenodo Retrieval And Communities](zenodo-retrieval-communities.md) |
| `scripts/export_hunt_dataset_records.py` | [Sessions, Records, And Provenance](sessions-records-provenance.md) |
| `scripts/hpc_singularity/remote/webhdp_hpc_batch.py`, `scripts/hpc_singularity/remote/webhdp_hpc_tmux.sh`, `scripts/hpc_singularity/remote/webhdp.sbatch` | [HPC Batch Automation](hpc-batch-automation.md) |
| `scripts/hpc_singularity/*` and `scripts/hpc_singularity/remote/*` | [HPC, Cloud, And Storage](hpc-cloud-storage.md), [Developer And Operator Scripts](developer-operator-scripts.md) |

## Prerequisites And Permissions

- Maintainers need repository access and enough local tooling to inspect routes, generated OpenAPI, tasks, and scripts.
- Updating this document should happen with any change that adds, removes, or renames executable workflow surfaces.
- The coverage tables are documentation ownership maps, not permission policy definitions.

## Inputs, Outputs, And State

| Input | Output | State To Watch |
|---|---|---|
| Frontend route table | Route-to-workflow ownership | `frontend/src/router/index.js` |
| OpenAPI path families and Flask routes | Backend route coverage | `docs/api/openapi.json`, `routes/`, `app.py` |
| Celery task definitions | Background workflow coverage | `tasks.py` |
| Native pipeline identifiers and component surfaces | Pipeline workflow coverage | `constants.py`, `services/native_pipeline_system.py` |
| Script inventory | Operator and developer workflow coverage | `scripts/` |

## Failure And Recovery

- If frontend routes are missing from the table, add the route to the owning macro workflow and this coverage file.
- If an OpenAPI path does not fit an existing family, decide whether it is a new workflow or support for an existing one.
- If a Celery task is missing, document the workflow that queues, monitors, or schedules it.
- If a script is missing, decide whether it belongs in operator scripts, HPC/cloud, Zenodo, publication, or records/provenance.

## Optimization Targets

- Keep the coverage file concise by grouping backend support endpoints into route families.
- Keep macro workflow documents readable by moving traceability detail here.
- Make coverage checks easy to rerun with simple route, OpenAPI, task, and script extraction.

## Verification Checklist

- Check frontend routes from `frontend/src/router/index.js` against the frontend coverage table.
- Check OpenAPI paths from `docs/api/openapi.json` against the backend route family table.
- Check Celery tasks from `tasks.py` against background task coverage.
- Check scripts under `scripts/` against script coverage.
- Confirm all coverage targets point to existing workflow documents.

## Non-Workflow Source Surfaces

These source surfaces are intentionally not documented as standalone workflows:

- Static frontend assets `/app.js` and `/styles.css` are delivery assets for the
  single-page app, not user-executable workflows.
- Fallback routing redirects unknown frontend paths to login and is covered by
  the authentication workflow.
- Small support endpoints are represented in the route family table above and
  in the owning workflow document.

## Codebase Starting Points

- Frontend routes: `frontend/src/router/index.js`
- Backend route families: `routes/`, `app.py`
- Generated API contract: `docs/api/openapi.json`
- Background tasks: `tasks.py`
- Native pipeline registry and execution: `services/native_pipeline_system.py`
- Built-in pipeline constants: `constants.py`
- Runnable scripts: `scripts/`
- Docs catalog registration: `routes/docs_routes.py`
