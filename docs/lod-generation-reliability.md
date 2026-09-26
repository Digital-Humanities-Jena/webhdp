# Reliable metadata generation

LOD Generation 1.1.0 produces EDM, IIIF, METS/MODS, CIDOC-CRM RDF/XML, and JSON-LD. CIDOC-CRM and JSON-LD serialize the same digital-dataset graph and share mappings. Each format has its own enable switch and validation result.

## Validation and upload eligibility

A format becomes a record attachment only after explicit successful validation. EDM runs XML, local XSD, business rules, and the configured Local EDM Validator. Disabled checks remain visible as skipped. An unavailable validator, missing required validator stages, unknown statuses, or malformed responses cannot pass. The remote report must include successful VALIDATE_EXTERNAL and VALIDATE_INTERNAL stages.

Public artifacts reject credential-bearing and local URLs. Zenodo landing links use canonical record URLs. Unicode RDF identifiers preserve names instead of replacing distinct characters with the same underscore. RDF/XML and JSON-LD are checked for graph equivalence; the graph validator requires a dataset, title, public record link, and file relationships.

Generated artifacts are written to temporary files in their destination directory and replaced atomically. The private `lod-generation.json` manifest stores per-format results, saved inputs, template hashes, and artifact SHA-256 checksums. It is never registered as a Zenodo attachment. Validation reports are also excluded from the upload set. Both download and upload recheck content hashes; modifying a validated file invalidates its eligibility. Changes to validator settings invalidate cached generation results, and uploads enforce currently required external EDM checks.

The required LOD policy blocks upload when an enabled format fails, including when the failure produced no attachment. Optional failures permit successful new formats to continue independently. Existing LOD attachments are suspended before regeneration so stale files cannot be uploaded as replacements. Suspended attachments block upload and publication until revalidated. Unchanged validated attachments retain their earlier uploaded status; changed content is queued again. Record actions and upload summaries use the same readiness checks, and generated files are never offered as sources for new records.

## Reproducibility and metadata matching

Preflight binds the pipeline, user, source selection, shared metadata, MSF content, parser options, batch metadata, and selected template contents. Queued runs retain those settings. A changed MSF is rejected before processing. An explicit EDM template is respected for 3D files; automatic template switching does not override the selection.

MSF rows match normalized relative paths first. Basename and case-insensitive fallback are permitted only when unique. Duplicate rows, ambiguous nested filenames, and missing selected-source rows require correction. Use paths such as `collection-a/model.glb` and `collection-b/model.glb` when names repeat. Saved spreadsheet-sheet and CSV parser choices are used during execution. Preview filenames come from the selected row, so image and document rows are not treated as example 3D models. MSF preview endpoints require session access and reject out-of-session paths and symlinks.

Batch main-file identity comes from each resolved source, never the shared preview sample. Generation rejects a selected main file outside the record's attachment set. Batch mode uses the mapper preview with the current template, provider, selected row's saved metadata, and mappings; the separate single-file preview is hidden. Preview lookup uses the same exact-path and unambiguous-basename rules as submission. Shared collection titles do not replace individual record titles, and Zenodo mappings are applied before format mappings. Saved provider and template choices survive re-entry, and failed saves retain edits without advancing the step.

## Review and recovery

The record detail page shows each format's status, validation report, and whether generation completed missing fields. Successful exports and a combined report can be downloaded there. Failed, changed, or missing outputs can be retried without creating a draft, running the renderer, or uploading files. Retries keep the captured settings and reuse unchanged valid outputs. To apply edited mappings or templates, start a new pipeline run; the existing draft-reuse mechanism remains in effect.

Recovery requires session edit permission, a mutable session, an unpublished local record, and the session processing lock. Report access and downloads require view permission. The generation request and local output paths are not included in the report API response.

Before generation starts, every requested format is journaled as pending. Completed cached entries are persisted individually, with the previous valid results retained privately across interruptions. Progress-reporting failures do not abort generation. Missing entries in older interrupted reports are exposed as pending so recovery remains available. After retry, record details and file readiness refresh; the earlier pipeline result remains explicitly historical, and the page identifies whether uploads remain necessary.

Guided submission saves an immutable request and operation ID in browser session storage before sending it. Ambiguous responses can be retried using the same ID, while conflicts identifying an existing run reconnect to it. Accepted-run monitoring starts independently of workflow-state persistence. A saved run reconnects before loading submission configuration; definitive validation failures release the request for correction.

Previews are tied to the selected format, template, provider, sample row, source, parser options, and mappings. Changing an input clears the old result; late responses cannot overwrite the current preview. Validator outages display an unverified result. The Constructor's persistent-run monitor stops polling inaccessible or deleted runs and permits explicit dismissal without cancelling processing.

## Verification

Regression coverage includes independent format failure, cached retries, tampering, interrupted writes, missing validator checks, non-ASCII identifiers, duplicate basenames, template edits, sparse draft responses, and authorization. A separate integration test runs all five real generators and validators against a clean local database. Browser checks exercise recovery in Chromium and Firefox at narrow and desktop widths. `scripts/check_lod_mapping_api.py` is an optional manual smoke script using `WEBHDP_TEST_EMAIL`, `WEBHDP_TEST_PASSWORD`, and `WEBHDP_TEST_API_URL`; automated tests do not depend on a running deployment.

These changes are local development work. No deployment, remote publication, or release push is performed by this verification.
