# Public Records And Operations Walkthroughs

These recordings show public-facing record views and operator troubleshooting
surfaces. They are useful for demonstrations, readiness checks, and support
triage.

## Public Record Page And oEmbed

Use this when testing public record presentation and embeddable record metadata.

<video controls muted playsinline preload="metadata">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_08_public_record_and_oembed.webm" type="video/webm">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_08_public_record_and_oembed.mp4" type="video/mp4">
  <track kind="subtitles" src="/api/v1/docs/assets/screen_recordings/subtitles/webhdp_real_08_public_record_and_oembed.en.vtt" srclang="en" label="English">
  Your browser does not support the embedded video.
</video>

What to watch for:

1. A public WebHDP record page opens for a published Zenodo record.
2. Title, creator, DOI, file count, record ID, and preview controls appear.
3. The iframe-safe embed page opens for the same record.
4. The oEmbed endpoint returns a raw `rich` JSON response with iframe HTML.

## Cloud Storage Mirror Download

Use this when checking whether mirrored source artifacts can be reviewed and
downloaded without exposing cloud credentials.

<video controls muted playsinline preload="metadata">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_20_cloud_storage_mirror_download.webm" type="video/webm">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_20_cloud_storage_mirror_download.mp4" type="video/mp4">
  <track kind="subtitles" src="/api/v1/docs/assets/screen_recordings/subtitles/webhdp_real_20_cloud_storage_mirror_download.en.vtt" srclang="en" label="English">
  Your browser does not support the embedded video.
</video>

What to watch for:

1. The Review Files step opens for a real local session.
2. Cloud Storage downloads list mirrored ZIP and MSF artifacts.
3. Mirror availability checks report synthetic Dropbox objects as available.
4. Download opens a simulated temporary provider page.
5. No cloud credential, refresh token, private link, or production provider
   account is exposed.

## Admin Observability Troubleshooting

Use this when investigating integration readiness and failed background
operations.

<video controls muted playsinline preload="metadata">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_21_admin_observability_troubleshooting.webm" type="video/webm">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_21_admin_observability_troubleshooting.mp4" type="video/mp4">
  <track kind="subtitles" src="/api/v1/docs/assets/screen_recordings/subtitles/webhdp_real_21_admin_observability_troubleshooting.en.vtt" srclang="en" label="English">
  Your browser does not support the embedded video.
</video>

What to watch for:

1. Credentials & Integrations shows masked Dropbox status.
2. A safe Dropbox check reports missing local environment variables.
3. API & Integration Activity filters to cloud-storage server errors.
4. Notification Delivery filters to failed delivery attempts.
5. The workflow shows operational evidence without exposing secrets or private
   infrastructure.
