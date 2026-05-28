# Metadata And Retrieval Walkthroughs

These recordings cover metadata validation and retrieval workflows that support
publication quality, account inventory work, and reusable `.hdpc` evidence.

## EDM Template Validation Report

Use this when an operator needs to verify the local EDM validator path before
users rely on generated EDM.

<video controls muted playsinline preload="metadata">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_12_edm_template_validation_report.webm" type="video/webm">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_12_edm_template_validation_report.mp4" type="video/mp4">
  <track kind="subtitles" src="/api/v1/docs/assets/screen_recordings/subtitles/webhdp_real_12_edm_template_validation_report.en.vtt" srclang="en" label="English">
  Your browser does not support the embedded video.
</video>

What to watch for:

1. The administrator EDM Templates page opens in local Docker.
2. The Standard EDM Template is selected for validation.
3. Sample EDM XML is generated and validated locally.
4. The report shows compliance status and warnings.
5. Validator step details are visible for audit review.

## Zenodo Credentials Safe Configuration

Use this before any workflow that publishes to Zenodo or retrieves authenticated
account inventories.

<video controls muted playsinline preload="metadata">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_17_zenodo_credentials_safe_configuration.webm" type="video/webm">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_17_zenodo_credentials_safe_configuration.mp4" type="video/mp4">
  <track kind="subtitles" src="/api/v1/docs/assets/screen_recordings/subtitles/webhdp_real_17_zenodo_credentials_safe_configuration.en.vtt" srclang="en" label="English">
  Your browser does not support the embedded video.
</video>

What to watch for:

1. Account Configuration opens the Zenodo Keys form.
2. The key is entered through a password input.
3. Saved credentials show only masked previews.
4. Sandbox active-key selection is visible.
5. Validation reports authentication and API capabilities without exposing the
   token.

## Zenodo OAI Harvest Collection

Use this when public Zenodo metadata should be harvested without account
credentials.

<video controls muted playsinline preload="metadata">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_09_zenodo_oai_harvest_collection.webm" type="video/webm">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_09_zenodo_oai_harvest_collection.mp4" type="video/mp4">
  <track kind="subtitles" src="/api/v1/docs/assets/screen_recordings/subtitles/webhdp_real_09_zenodo_oai_harvest_collection.en.vtt" srclang="en" label="English">
  Your browser does not support the embedded video.
</video>

What to watch for:

1. The workflow uses the public 3DBigDataSpace OAI set.
2. A one-record limit keeps the documentation run bounded.
3. The harvest reaches `SUCCESS`.
4. Collection search finds the harvested public record.

## Zenodo Account Retrieval Collection

Use this for authenticated account inventory work with explorer-only shard
collections.

<video controls muted playsinline preload="metadata">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_19_zenodo_account_retrieval_collection.webm" type="video/webm">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_19_zenodo_account_retrieval_collection.mp4" type="video/mp4">
  <track kind="subtitles" src="/api/v1/docs/assets/screen_recordings/subtitles/webhdp_real_19_zenodo_account_retrieval_collection.en.vtt" srclang="en" label="English">
  Your browser does not support the embedded video.
</video>

What to watch for:

1. A sandbox recording credential is selected without showing a token value.
2. The preflight report confirms the worker path and prior coverage.
3. A completed retrieval collection shows two records and one shard.
4. Collection search finds a synthetic amphora record from the local shard.
5. The community-migration detector reads from the retrieval shards.
