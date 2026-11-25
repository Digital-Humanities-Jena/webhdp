# Common workflow recipes

Use the existing guided workflow for publication and the Component Constructor
for reusable processing plans. Pipeline cards show the result, source formats,
and requirements; expand **Outputs and requirements** for component details.
The recommendation favors compatible plans without publication or an HPC job.
Review the outcome before starting, especially for a custom pipeline.

## Describe and prepare one record

1. Upload the source and select its bundle in **Review Files**. If loading fails,
   use **Try loading files again**; the error does not mean the folder is empty.
2. In **Describe records**, enter a specific title, creators, description, and
   license. An error beside a field links to that field; the first invalid field
   receives focus after **Save & Continue**.
3. Draft edits are saved automatically. Pending edits are also retained in the
   current browser tab for the signed-in user and session. Reloading recovers
   them; leaving through navigation attempts a server save. Closing the tab
   can lose this browser copy, and logout clears it. Session expiry retains the
   copy for the same user's next sign-in in this tab. A failed server save is not
   a completed save: retry before closing the tab. If browser storage is also
   unavailable, keep the page open until a save succeeds.
4. In **Linked metadata**, select a template and inspect the readable preview.
   Expand **Technical metadata** or **Generated document** when needed. Review
   defaults and generated adjustments as well as validation errors.
5. Choose **Prepare a Zenodo draft** (the metadata-only plan) to upload without an
   HPC allocation. The selected environment still needs a Zenodo credential.
   Confirm the draft/upload/publication outcome in **Review & start**.
   **Submission readiness** checks all selected sources and saved settings
   automatically. Follow a blocker’s **Review** link to the existing correction
   screen, save the change, then return and use **Check again**.
6. Open the resulting record to inspect attachments and validation reports.
   Publication is a separate action when the pipeline outcome says so.

## Prepare a batch from a spreadsheet

1. Upload the models ZIP and MSF, then resolve file matching in the spreadsheet
   check. Use relative paths when two folders contain the same basename.
2. Check the column mappings and matched record count. In the metadata review,
   choose a filename to inspect that record's description.
3. In the mapper, choose **Preview record** by filename and row. Check a typical
   row and rows with missing descriptions, different media, or unusual names.
4. Expand **Spreadsheet checks** to see missing source values and duplicate
   filenames across all rows. These counts describe the spreadsheet before
   defaults. A passing preview validates the selected record, not the whole
   batch. Fix the MSF or mappings and rerun the relevant previews.
5. Review **Mapped**, **Entered**, **Inferred**, and **Default** labels. A filename
   title or an `Unknown` creator can make an export structurally complete while
   still needing descriptive improvement. Export or preserve reusable mappings.
6. Select the compatible processing plan and review **Submission readiness**.
   This checks each selected spreadsheet match and saved record decision,
   including rows beyond the preview. Supply actual creators; an automatically
   filled `Unknown` value does not satisfy submission readiness. Start after
   local checks pass. Review failed and skipped
   records individually; successful records need no duplicate submission.

## Inspect or simplify a 3D model

Choose a local analysis pipeline to inspect dependencies and geometry when its
components are installed. For **Mesh Optimization & Preview**, use a static,
self-contained GLB with embedded textures and an active HPC allocation. That
pipeline produces derivatives and previews without uploading to Zenodo.

The separate **Geometric LOD Generator** is an installable CPU component for
static GLB. It produces high, medium, and low detail models plus a reduction
report. The medium target is `target_ratio`; high targets its square root and
low its square. If a reduction exceeds the sampled surface-error limit, the
preceding geometry is retained. Equal detail levels can be a valid conservative
result. The source file remains unchanged.

Inspect triangle counts, retention reasons, file sizes, textures, and appearance
before choosing a derivative. Fewer triangles do not guarantee fewer bytes or
visual equivalence. Animation, skins, morph targets, external dependencies, and
multiple scenes need a static self-contained export first. See the
[3D analysis and processing guide](../workflows/3d-analysis-processing-pipelines.md)
for input contracts, report review, and component verification.

## Review metadata by media type

IIIF Presentation 4.0 RC uses a `Scene` for a 3D `Model`, a `Timeline` for timed
`Audio`, and a `Canvas` for images and timed video. Supply positive width and
height together for the Canvas aspect ratio, or use the default square frame.
Supply the actual duration in seconds for audio and video. Media with an unknown
duration and documents are offered through `rendering`, with a cover image when
available.

CIDOC-CRM RDF/XML and JSON-LD describe the digital dataset and its file
relationships. They do not automatically model a physical heritage object,
production history, provenance events, or a complete CRM application profile.
METS/MODS checks XML and the local schemas. IIIF checks the local Presentation
4.0 RC profile, media extents, 3D placements, and annotation targets. Referenced-file
availability and viewer behavior still need separate review. EDM can additionally
require the configured external validator; **Unverified** means that a required
check could not complete, not that the metadata passed.

## Recover a failed metadata export

Open the record's metadata panel, expand its validation details, and correct the
reported issue. **Retry metadata** reuses the captured mappings and templates
without repeating rendering, draft creation, or uploads. **Revalidate metadata**
uses the current required validation policy; **Regenerate metadata** refreshes
exports after a draft identity changes. Changed exports require another upload.
To apply edited mapping or template contents, start a new pipeline run.

If processing acknowledgement was lost, reconnect to the saved operation before
starting another one. Interrupted runs retain their local results. Review those
results and any outstanding HPC activity before rerunning. See
  [metadata reliability and recovery](../lod-generation-reliability.md).

## Understand the final readiness check

Local checks cover source availability and contents, model dependencies,
spreadsheet matching, record decisions, metadata, enabled templates, and known
component input contracts. The final screen keeps the selected pipeline; if it
is unavailable, choose an available pipeline and review its outcome again.

**Checks still unverified** lists checks that need processing or a remote
service: compute connectivity and installation, Zenodo credentials and
acceptance, generated exports, and required external validators. Local success
does not verify these. With Draco disconnected, its runtime checks remain
unverified and require later validation on the connected deployment.

**Confirm & Process** repeats local checks before requesting compute resources.
The server checks again before accepting a new run and before its worker creates
bundles, records, or drafts. Changed inputs or settings require another check;
the saved check expires after one hour for a new request. An accepted queued run
retains its pipeline version and captured metadata settings, and checks source
contents again when it starts. Reconnect an accepted run using its existing
operation ID instead of submitting another request.
