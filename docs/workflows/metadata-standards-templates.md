# Metadata, Standards, And Templates Workflows

This document covers metadata preparation, standards mapping, output preview,
and template management.

## Overview

These workflows turn user metadata and MSF-derived values into publication-ready
metadata and standards outputs. They cover session and file metadata, Zenodo and
heritage-standard mappings, EDM/IIIF/METS/LOD preview, EDM templates, and local
QA tools. The deeper maintainer sections focus on validation, generated output,
and where mapping behavior can be tuned.

## Use Cases

- Prepare session, file, batch, and draft metadata before publication.
- Test Zenodo, EDM, IIIF, METS, and LOD mapping output before a pipeline run.
- Manage EDM templates and local validator behavior.
- Use local QA tools for metadata normalization, MSF validation, and output preview.

## Session And File Metadata

Primary actor: publishing user.

Entry points:
- UI: `/workflow/metadata`
- UI redirect: `/workflow/file-metadata`
- UI redirect: `/workflow/user-metadata`
- API: `/api/v1/metadata/schema`
- API: `/api/v1/metadata/file/<file_id>`
- API: `/api/v1/metadata/user/<session_id>`
- API: `/api/v1/metadata/user/<session_id>/draft`
- API: `/api/v1/metadata/session/<session_id>/batch-update`
- API: `/api/v1/metadata/zenodo-community-override`

Workflow:
1. Load the metadata schema and any community override.
2. Save file-level metadata or a session-level metadata draft.
3. Normalize and validate final user metadata.
4. Batch-update metadata for a session when needed.

Complete when:
- Metadata is persisted without blocking validation errors.

## Mapping Tests

Primary actor: publishing user, metadata maintainer, or operator.

Entry points:
- API: `/api/v1/metadata/test-mapping`
- API: `/api/v1/edm/test-mapping`
- API: `/api/v1/iiif/test-mapping`
- API: `/api/v1/mets/test-mapping`
- API: `/api/v1/edm/msf-columns`
- API: `/api/v1/edm/mapping/import`
- API: `/api/v1/edm/mapping/export`

Workflow:
1. Load MSF columns or current draft metadata.
2. Test mappings for Zenodo, EDM, IIIF, or METS output.
3. Import or export mapping files where supported.
4. Adjust mapping choices until generated payloads are acceptable.

Complete when:
- The target standard mapping produces the expected metadata payload.

## EDM, IIIF, METS, And LOD Output Review

Primary actor: publishing user or operator.

Entry points:
- UI: `/workflow/edm-selection`
- API: `/api/v1/tools/output-preview/local`
- API: `/api/v1/admin/edm-validator/status`
- Native step: `lod_generation`

Workflow:
1. Select or configure EDM and LOD behavior.
2. Preview generated output.
3. Validate output using local checks, XSD/Schematron, business rules, and local EDM validator where enabled.
4. Persist validation reports with generated artifacts.

Complete when:
- EDM/IIIF/METS output is acceptable for the chosen publication policy.

## EDM Template Management

Primary actor: administrator.

Entry points:
- UI: `/settings/edm-templates`
- API: `/api/v1/templates`
- API: `/api/v1/templates/<template_id>`
- API: `/api/v1/templates/preview`
- API: `/api/v1/templates/validate`

Workflow:
1. List available LOD templates.
2. Create or update template metadata and content.
3. Preview template rendering with sample or real metadata.
4. Validate generated XML.
5. Delete templates that should no longer be available.

Complete when:
- Template output validates and the intended templates are available to users.

## Metadata Tools

Primary actor: administrator in local mode.

Entry points:
- UI: `/tools/metadata-normalizer`
- UI: `/tools/output-preview-qa`
- UI: `/tools/msf-validator-local`
- UI: `/tools/msf-reference-repair`
- API: `/api/v1/tools/metadata-normalizer/local`
- API: `/api/v1/tools/output-preview/local`
- API: `/api/v1/msf/tools/local/validate`
- API: `/api/v1/msf/tools/local/export`

Workflow:
1. Select local MSF and source directory context.
2. Normalize metadata or run output preview.
3. Validate and repair local MSF references.
4. Export repaired or QA-ready results.

Complete when:
- Local metadata or output QA results are available for review.

## Prerequisites And Permissions

- Session and file metadata workflows require edit access to the target session.
- Mapping tests require draft metadata, MSF columns, or representative sample data.
- EDM template management requires administrator access.
- Local metadata tools require local-mode context and, for some tools, administrator access.

## Inputs, Outputs, And State

| Input | Output | State To Watch |
|---|---|---|
| File metadata, session metadata, or MSF-derived values | Saved metadata draft or final metadata | file metadata rows, session metadata, validation errors |
| Mapping configuration and sample values | Zenodo, EDM, IIIF, or METS preview payload | mapping warnings, generated XML or JSON |
| EDM template content | Template preview and validation report | template version, validation errors, generated XML |
| Local MSF and source directory | Normalized metadata or QA export | repaired MSF, preview artifacts, validator report |

## Failure And Recovery

- Blocking metadata validation errors should be resolved before submit.
- Mapping test failures should be reproduced with the same sample metadata or MSF columns.
- Template validation failures should be fixed before making the template available to users.
- Local QA failures should be exported or logged so the source MSF can be repaired safely.

## Optimization Targets

- Reduce repeated schema and workflow-support loading in metadata-heavy sessions.
- Keep batch metadata updates efficient for large MSF-driven publications.
- Cache mapping previews or reduce repeated output generation where it is expensive.
- Make local validation reports concise enough for users while preserving maintainer detail.

## Verification Checklist

- Verify metadata schema, file metadata, session draft, final metadata, and batch update flows.
- Verify Zenodo, EDM, IIIF, and METS mapping tests.
- Verify EDM template create/update/delete/preview/validate.
- Verify local metadata normalizer, MSF validator, MSF repair export, and output preview QA.

Related docs:
- `docs/architecture/metadata_workflow_contract.md`
- `docs/guides/local_edm_validator.md`
- `docs/guides/video_guides/metadata_and_retrieval.md`

## Codebase Starting Points

- Metadata workflow views: `frontend/src/views/workflow/SubmissionMetadataView.vue`, `frontend/src/views/workflow/EdmSelectionView.vue`
- Metadata tools: `frontend/src/views/tools/MetadataNormalizerView.vue`, `frontend/src/views/tools/OutputPreviewQaView.vue`
- Metadata routes: `routes/metadata_routes.py`
- Standards mapping routes: `routes/edm_routes.py`, `routes/iiif_routes.py`, `routes/mets_routes.py`
- Template routes and UI: `routes/template_routes.py`, `frontend/src/views/admin/EdmTemplatesView.vue`
- LOD/native pipeline generation: `services/native_pipeline_system.py`
- Metadata schemas and contracts: `schemas/`, `docs/architecture/metadata_workflow_contract.md`
