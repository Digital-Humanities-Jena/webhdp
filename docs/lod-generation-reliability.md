# Reliable metadata generation

LOD Generation 1.1.0 produces EDM, IIIF, METS/MODS, CIDOC-CRM RDF/XML, and JSON-LD. CIDOC-CRM and JSON-LD serialize the same digital-dataset graph and share mappings. Each format has its own enable switch and validation result.

## Validation and upload eligibility

A format becomes a record attachment only after explicit successful validation. EDM runs XML, local XSD, business rules, and the configured Local EDM Validator. Disabled checks remain visible as skipped. An unavailable validator, missing required validator stages, unknown statuses, or malformed responses cannot pass. The remote report must include successful VALIDATE_EXTERNAL and VALIDATE_INTERNAL stages.

Public artifacts reject credential-bearing and local URLs. Zenodo landing links use canonical record URLs. Unicode RDF identifiers preserve names instead of replacing distinct characters with the same underscore. RDF/XML and JSON-LD are checked for graph equivalence; the graph validator requires a dataset, title, public record link, and file relationships.

Generated artifacts are written to temporary files in their destination directory and replaced atomically. The private `lod-generation.json` manifest stores per-format results, saved inputs, template hashes, and artifact SHA-256 checksums. It is never registered as a Zenodo attachment. Validation reports are also excluded from the upload set. Both download and upload recheck content hashes; modifying a validated file invalidates its eligibility. Changes to validator settings invalidate cached generation results, and uploads enforce currently required external EDM checks.

The required LOD policy blocks upload when an enabled format fails. The optional policy permits successful formats to continue independently. Failed formats never enter the pending upload set. Existing LOD attachments are suspended before regeneration so an old pending file cannot be uploaded as a replacement.

## Reproducibility and metadata matching

Preflight binds the pipeline, user, source selection, shared metadata, MSF content, parser options, batch metadata, and selected template contents. Queued runs retain those settings. A changed MSF is rejected before processing. An explicit EDM template is respected for 3D files; automatic template switching does not override the selection.

MSF rows match normalized relative paths first. Basename and case-insensitive fallback are permitted only when unique. Duplicate rows, ambiguous nested filenames, and missing selected-source rows require correction. Use paths such as `collection-a/model.glb` and `collection-b/model.glb` when names repeat. Saved spreadsheet-sheet and CSV parser choices are used during execution. Preview filenames come from the selected row, so image and document rows are not treated as example 3D models. MSF preview endpoints require session access and reject out-of-session paths and symlinks.

## Review and recovery

The record detail page shows each format's status, validation report, and whether generation completed missing fields. Successful exports and a combined report can be downloaded there. Failed, changed, or missing outputs can be retried without creating a draft, running the renderer, or uploading files. Retries keep the captured settings and reuse unchanged valid outputs. To apply edited mappings or templates, start a new pipeline run; the existing draft-reuse mechanism remains in effect.

Recovery requires session edit permission, a mutable session, an unpublished local record, and the session processing lock. Report access and downloads require view permission. The generation request and local output paths are not included in the report API response.

Previews are tied to the selected format, template, sample row, source, parser options, and mappings. Changing an input clears the old result; late responses cannot overwrite the current preview. Validator outages display an unverified result. An inaccessible or deleted persistent run stops polling and can be explicitly dismissed without cancelling processing.

## Verification

Regression coverage includes independent format failure, cached retries, tampering, interrupted writes, missing validator checks, non-ASCII identifiers, duplicate basenames, template edits, sparse draft responses, and authorization. A separate integration test runs all five real generators and validators against a clean local database. Browser checks exercise recovery in Chromium and Firefox at narrow and desktop widths. `scripts/check_lod_mapping_api.py` is an optional manual smoke script using `WEBHDP_TEST_EMAIL`, `WEBHDP_TEST_PASSWORD`, and `WEBHDP_TEST_API_URL`; automated tests do not depend on a running deployment.

These changes are local development work. No deployment, remote publication, or release push is performed by this verification.
