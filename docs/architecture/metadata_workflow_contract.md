# Metadata Workflow Contract

## Official workflow

WebHDP officially supports the native MSF-driven metadata workflow:

- MSF parsing, validation, and repair
- Zenodo/EDM/IIIF/METS mapping tests
- output preview QA
- local `.hdpc` record preparation during submission and pipeline execution

## Supported surfaces

- `/api/v1/msf/default-mapping`
- `/api/v1/msf/metadata-for-files`
- `/api/v1/metadata/test-mapping`
- `/api/v1/edm/test-mapping`
- `/api/v1/iiif/test-mapping`
- `/api/v1/mets/test-mapping`
- `/api/v1/tools/output-preview/local`
- native pipeline workspace at `/workflow/pipeline`

## Retired legacy surface

The old HDP-Server-style `prepare_metadata_for_file` flow is retired.

Reasons:

- it depends on the removed HDP-Server-era preparation model
- it duplicates behavior now handled by session metadata drafts, LOD mapping, and local `.hdpc` record creation
- it creates ambiguity about which metadata workflow is authoritative

## Replacement guidance

- Use session metadata drafts and the LodMapper to author metadata.
- Use the mapping test endpoints to preview standard-specific payloads.
- Use `/api/v1/tools/output-preview/local` to validate generated EDM, IIIF, and METS output.
- Let submission-time local `.hdpc` record creation prepare records for execution.
