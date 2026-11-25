# Reliable metadata generation

LOD Generation 1.2.0 produces EDM, IIIF, METS/MODS, CIDOC-CRM RDF/XML, and JSON-LD. CIDOC-CRM and JSON-LD serialize the same digital-dataset graph and share mappings. Each format has its own enable switch and validation result.

## Format profiles and limits

New IIIF exports use the Presentation 4.0 release candidate. WebHDP paints a
3D `Model` into a `Scene`, timed `Audio` into a `Timeline`, and images or timed
video into a `Canvas`. Supply width and height together for a custom Canvas
aspect ratio. The fallback 1000 × 1000 dimensions describe the presentation
frame. Provide the actual duration in seconds for timed media. Viewable documents
and media with unknown duration are offered through `rendering`. Machine-readable
datasets and archives use `seeAlso`. An available cover image appears on the
Canvas. Use scene X, Y, and Z coordinates for 3D placement. Map latitude
and longitude together to publish a geographic point through `navPlace`.
Optional altitude is measured in metres relative to the WGS 84 ellipsoid.
[IIIF Presentation 4.0 data model](https://iiif.io/api/presentation/4.0/model/)

The `presentation-4-rc-media-1` validation profile checks local manifest
structure, media types, Canvas and Timeline extents, Scene placement and painting
targets. This includes later containers, annotation pages and annotations.
Check referenced files and the intended viewer independently. The IIIF release
candidate's published JSON-LD context is still empty, so local checks validate
the draft's JSON structure. [IIIF Presentation 4.0 context](https://iiif.io/api/presentation/4/context.json)

Hosted deployments can set `IIIF_PUBLIC_BASE_URL` to use WebHDP's public manifest
endpoint. It serves the deposited bytes with IIIF response headers once the
record and its files are public on Zenodo. Choose a compatible viewer from the
[IIIF 4.0 viewer matrix](https://iiif.io/api/cookbook/recipe/matrix-v4/).

On retry, the updated IIIF profile regenerates older IIIF exports in open drafts.
The other formats keep their existing validation and cache eligibility. Finalized
records retain access to the manifests they originally validated, subject to the
same record identity and file integrity checks.

Retries with an unchanged older bundled template use the updated bundle. WebHDP
can also convert older custom templates whose painting bodies and targets map
unambiguously to Presentation 4. If a template has ambiguous or unsupported
structures, the error identifies what needs to be updated. Preview the edited
template in Settings and start a new metadata generation to use it.

CIDOC-CRM/JSON-LD use the `digital-dataset-1` profile: a digital dataset with its
title, public record link, and file relationships. The paired serializations are
checked for graph equivalence. Physical objects and historical events require
an explicit richer model; this profile is not a general CRM conformance claim.
METS/MODS uses the local XML schemas and EDM uses the configured required checks.
Reports identify validation scope and distinguish invalid exports from an
unavailable validator.

## Validation and upload eligibility

A format becomes a record attachment only after explicit successful validation. EDM runs XML, local XSD, business rules, and the configured Local EDM Validator. Disabled checks remain visible as skipped. An unavailable validator, missing required validator stages, unknown statuses, or malformed responses cannot pass. The remote report must include successful VALIDATE_EXTERNAL and VALIDATE_INTERNAL stages.

Public artifacts reject credential-bearing and local URLs. Zenodo landing links use canonical record URLs. Unicode RDF identifiers preserve names instead of replacing distinct characters with the same underscore. RDF/XML and JSON-LD are checked for graph equivalence; the graph validator requires a dataset, title, public record link, and file relationships.

Generated artifacts are written to temporary files in their destination directory and replaced atomically. The private `lod-generation.json` manifest stores per-format results, saved inputs, template hashes, and artifact SHA-256 checksums. It is never registered as a Zenodo attachment. Validation reports are also excluded from the upload set. Both download and upload recheck content hashes; modifying a validated file invalidates its eligibility. Changes to validator settings invalidate cached generation results, and uploads enforce currently required external EDM checks.

The required LOD policy blocks upload when an enabled format fails, including when the failure produced no attachment. Optional failures permit successful new formats to continue independently. Existing LOD attachments are suspended before regeneration so stale files cannot be uploaded as replacements. Suspended attachments block upload and publication until revalidated. Unchanged validated attachments retain their earlier uploaded status; changed content is queued again. Record actions and upload summaries use the same readiness checks, and generated files are never offered as sources for new records.

## Reproducibility and metadata matching

The guided final review runs a read-only submission readiness check across all
selected sources. It uses the execution source resolver, metadata validators,
saved record decisions, component manifests, and the bounded geometric input
validators. It identifies local blockers with links to the existing files,
metadata, mapping, or pipeline screen. Only enabled metadata formats require
valid templates. A preview still validates its selected record rather than an
entire batch.

Readiness creates no files, records, drafts, uploads, allocations, or jobs, and
does not contact compute or Zenodo services. Runtime installation, credentials,
remote acceptance, generated-output validation, and required external validators
remain explicitly unverified. Disconnected Draco checks must be validated later
on the connected deployment.

The signed readiness token binds the user, session, source and bundle content
hashes, metadata and spreadsheet settings, template contents, record decisions,
pipeline version and parameters, destination, workspace settings, and validation
policy. It expires after one hour for a new request. Execution without a token
still performs mandatory local checks. A changed state is rejected before a new
run is queued. Accepted-request retries reconnect before rechecking sources,
and workers recheck captured state without imposing the token’s one-hour limit
on queue time. Workers use the pinned pipeline version and reject changed
source or spreadsheet contents before registration and draft creation.

Preflight binds the pipeline, user, source selection, shared metadata, MSF content, parser options, batch metadata, and selected template contents. Queued runs retain those settings. A changed MSF is rejected before processing. An explicit EDM template is respected for 3D files; automatic template switching does not override the selection.

MSF rows match normalized relative paths first. Basename and case-insensitive fallback are permitted only when unique. Duplicate rows, ambiguous nested filenames, and missing selected-source rows require correction. Use paths such as `collection-a/model.glb` and `collection-b/model.glb` when names repeat. Saved spreadsheet-sheet and CSV parser choices are used during execution. Preview filenames come from the selected row, so image and document rows are not treated as example 3D models. MSF preview endpoints require session access and reject out-of-session paths and symlinks.

Batch main-file identity comes from each resolved source, never the shared preview sample. Generation rejects a selected main file outside the record's attachment set. Batch mode uses the mapper preview with the current template, provider, selected row's saved metadata, and mappings; the separate single-file preview is hidden. Preview lookup uses the same exact-path and unambiguous-basename rules as submission. Shared collection titles do not replace individual record titles, and Zenodo mappings are applied before format mappings. Saved provider and template choices survive re-entry, and failed saves retain edits without advancing the step.

## Review and recovery

The record detail page shows each format's status, validation report, and whether generation completed missing fields. Successful exports and a combined report can be downloaded there. Failed, changed, or missing outputs can be retried without creating a draft, running the renderer, or uploading files. Retries keep the captured settings and reuse unchanged valid outputs. To apply edited mappings or templates, start a new pipeline run; the existing draft-reuse mechanism remains in effect.

Recovery requires session edit permission, a mutable session, an unpublished local record, and the session processing lock. Report access and downloads require view permission. The generation request and local output paths are not included in the report API response.

Generation also saves private recovery state in the project file. If the output report or directory is lost, the same metadata retry rebuilds it from the saved inputs. This recovery state is excluded from record details and sanitized shared exports. If neither copy remains, existing LOD attachments cannot pass readiness checks; the metadata panel explains that a new pipeline run is needed.

Before generation starts, every requested format is journaled as pending. Completed cached entries are persisted individually, with the previous valid results retained privately across interruptions. Progress-reporting failures do not abort generation. Missing entries in older interrupted reports are exposed as pending so recovery remains available. After retry, record details and file readiness refresh; the earlier pipeline result remains explicitly historical, and the page identifies whether uploads remain necessary.

Guided submission saves an immutable request and operation ID in browser session storage before sending it. Ambiguous responses can be retried using the same ID, while conflicts identifying an existing run reconnect to it. Accepted-run monitoring starts independently of workflow-state persistence. A saved run reconnects before loading submission configuration; definitive validation failures release the request for correction.

Previews are tied to the selected format, template, provider, sample row, source, parser options, and mappings. Changing an input clears the old result; late responses cannot overwrite the current preview. Validator outages display an unverified result. The Constructor's persistent-run monitor stops polling inaccessible or deleted runs and permits explicit dismissal without cancelling processing.

Readable previews show titles, descriptions, creators, rights, and source
filenames before technical JSON/XML. Source labels distinguish mapped, entered,
shared, record-specific, inferred, and default values. Spreadsheet checks count
input gaps across all rows before defaults; export validation still concerns the
selected preview. Minimum-viable adjustments report semantic additions, changes,
and removals rather than formatting differences. Removed values are not copied
into the report. These details are also available in the record metadata panel.

## Changes after generation

Readiness compares the captured validation policy with the current deployment requirements. If requirements change, the existing metadata panel shows **Revalidation required** and offers **Revalidate metadata**. Upload, publication, and downloads cannot bypass that check, including records whose files were already uploaded. A required EDM validator must supply a passing remote report.

Readiness also compares the saved Zenodo record ID, DOI, and public landing URL with the current draft. Recreating a draft invalidates exports containing its previous identity. **Regenerate metadata** uses the current draft identity while retaining the saved generation settings, then requires the changed exports to be uploaded again.

Disabling a format retires its attachment from the intended file set. A local-only attachment becomes `disabled`; an attachment that may already exist on the draft becomes `removal_pending`. The existing upload action syncs this removal after checking the current draft. Interrupted removals can be retried safely. Publication waits until all intended file changes are synced. Discarding and recreating a draft preserves disabled formats; enabling the format again restores it as an upload candidate. These are text statuses in the existing `.hdpc` mapping table and require no new columns.

All native record mutations share the session processing lock, including batch actions and direct lifecycle helpers. Publication checks current validation and pending-file state inside that lock, rather than relying on eligibility recorded when a task was queued.

## Interrupted operations

Native execution holds the session lock throughout processing. Run inspection reconciles a persisted running state only after the lock is free; a live worker is never failed merely because rendering takes a long time. Interrupted runs retain artifacts and drafts, finish their incomplete step statuses, and ask the user to review results and HPC activity before another run. They are not automatically replayed. Late acknowledgement and worker-loss redelivery allow the queue to recover a terminated task without repeating a terminal run. Dispatch ownership is private recovery metadata and is excluded from run responses. Unknown task-monitor availability alone does not prove interruption.

Direct file uploads have a user-scoped submission token bound to the file content and workspace settings. The session and its identity are committed together; successful response data can be recovered without transferring or scanning the file again. Invalid files are rejected before creating a session. The upload view retains the request across lost responses and reloads. An interrupted upload keeps its saved session available for review; starting over is an explicit action.

Direct upload recovery checks the request lock instead of assuming that a live web process still owns the request. Batch uploads reserve their identity before dispatch, bind it to the submitted files and settings, and save initial progress before the worker can update it. A lost queue acknowledgement preserves an active worker's progress; unstarted work is cancelled under the execution lock, including late deliveries. The upload screen checks saved session progress even when the queue result is still pending and offers an explicit restart for cancelled preparation.

Queued native runs reserve the session against synchronous execution. Their task identity is saved before dispatch. An uncertain handoff cannot overwrite a running or completed worker result, and a cancelled run cannot execute on late delivery. Retrying the same accepted request reconnects even while a worker holds the session lock.

Upload, guided submission, and Constructor monitors distinguish temporary outages from inaccessible resources. Temporary failures use bounded backoff; permanent failures stop monitoring and show an existing review or return action. Leaving a view stops its local monitoring without cancelling remote work. Batch notifications distinguish completed, failed, and skipped items and link to record actions.

## Verification

Regression coverage includes independent format failure, cached retries, tampering, interrupted writes, missing validator checks, non-ASCII identifiers, duplicate basenames, template edits, sparse draft responses, and authorization. A separate integration test runs all five real generators and validators against a clean local database. Browser checks exercise recovery in Chromium and Firefox at narrow and desktop widths. `scripts/check_lod_mapping_api.py` is an optional manual smoke script using `WEBHDP_TEST_EMAIL`, `WEBHDP_TEST_PASSWORD`, and `WEBHDP_TEST_API_URL`; automated tests do not depend on a running deployment.

These changes are local development work. No deployment, remote publication, or release push is performed by this verification.
