# Publication And Processing Walkthroughs

These recordings show the central publication path: upload, MSF preflight,
pipeline execution, generated artifacts, records, provenance, and persisted EDM
validation evidence.

## Main Upload And MSF Preflight

Use this with the [End-to-End User Guide](../end_to_end_user_guide.md) when a
batch upload includes an MSF.

<video controls muted playsinline preload="metadata">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_14_main_upload_msf_preflight.webm" type="video/webm">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_14_main_upload_msf_preflight.mp4" type="video/mp4">
  <track kind="subtitles" src="/api/v1/docs/assets/screen_recordings/subtitles/webhdp_real_14_main_upload_msf_preflight.en.vtt" srclang="en" label="English">
  Your browser does not support the embedded video.
</video>

What to watch for:

1. The workflow uses the MSF-driven batch path.
2. A synthetic model ZIP and intentionally messy MSF are selected.
3. Preflight repair normalizes filename and duplicate-row issues.
4. Validation reports matched model files and included dependencies.
5. The workflow continues into Guided MSF Analysis.

## Pipeline Execution Results And Credential Gate

Use this when checking that local pipeline execution produces artifacts and that
publication remains blocked until credentials are configured.

<video controls muted playsinline preload="metadata">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_15_pipeline_execution_results.webm" type="video/webm">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_15_pipeline_execution_results.mp4" type="video/mp4">
  <track kind="subtitles" src="/api/v1/docs/assets/screen_recordings/subtitles/webhdp_real_15_pipeline_execution_results.en.vtt" srclang="en" label="English">
  Your browser does not support the embedded video.
</video>

What to watch for:

1. The Pipeline Constructor opens with its diagnostics panel.
2. A session-backed GLB fixture is used as input.
3. Execution returns a persisted run ID and one processed record.
4. Renderer and USDZ artifacts appear in execution results.
5. Missing sandbox credentials are shown as a safe gate without revealing
   credential values.

## Records, Provenance, And HDPC Import Export

Use this after processing to verify that WebHDP keeps record evidence portable
and inspectable.

<video controls muted playsinline preload="metadata">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_16_records_provenance_hdpc_import_export.webm" type="video/webm">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_16_records_provenance_hdpc_import_export.mp4" type="video/mp4">
  <track kind="subtitles" src="/api/v1/docs/assets/screen_recordings/subtitles/webhdp_real_16_records_provenance_hdpc_import_export.en.vtt" srclang="en" label="English">
  Your browser does not support the embedded video.
</video>

What to watch for:

1. Session Zenodo Records opens for a real ZIP/MSF upload session.
2. The records page shows mapped metadata, provenance, and `.hdpc` controls.
3. A record detail page shows files, hierarchy, health, and Zenodo status.
4. The provenance report summarizes records and file types.
5. A raw `.hdpc` export is imported through the Cross-Session Records Explorer.

## Session-Persisted EDM Validation Report

Use this to confirm that local EDM validation evidence is stored with the
session, not only shown in the template editor.

<video controls muted playsinline preload="metadata">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_18_session_persisted_edm_validation_report.webm" type="video/webm">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_18_session_persisted_edm_validation_report.mp4" type="video/mp4">
  <track kind="subtitles" src="/api/v1/docs/assets/screen_recordings/subtitles/webhdp_real_18_session_persisted_edm_validation_report.en.vtt" srclang="en" label="English">
  Your browser does not support the embedded video.
</video>

What to watch for:

1. A record detail page opens from a local Docker instance.
2. The record includes an `edm.xml` output registered in `.hdpc`.
3. Metadata Validation Reports are populated from persisted JSON.
4. Validator name, profile, status, errors, warnings, and detail JSON are shown.
5. No credentials, private endpoints, or personal paths are exposed.
