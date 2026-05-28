# Installation And Setup Walkthroughs

These recordings are the best starting point for users who want to prove that a
fresh WebHDP clone can be configured, started, and initialized.

## Clone And Docker Installation

Use this when verifying the basic clone-to-health-check path described in the
[Docker Quickstart](../docker_quickstart.md).

<video controls muted playsinline preload="metadata">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_11_clone_docker_installation.webm" type="video/webm">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_11_clone_docker_installation.mp4" type="video/mp4">
  <track kind="subtitles" src="/api/v1/docs/assets/screen_recordings/subtitles/webhdp_real_11_clone_docker_installation.en.vtt" srclang="en" label="English">
  Your browser does not support the embedded video.
</video>

What to watch for:

1. The workflow starts from a clean release-candidate clone.
2. `.env.example` is copied to `.env`.
3. Local-only values are generated without printing secrets.
4. Docker Compose starts backend, frontend, worker, and Redis.
5. Container status and `/api/v1/health` confirm the instance is reachable.

## First-Time Setup Wizard

Use this after the containers are healthy and before regular users enter the
application.

<video controls muted playsinline preload="metadata">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_13_first_time_setup_wizard.webm" type="video/webm">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_13_first_time_setup_wizard.mp4" type="video/mp4">
  <track kind="subtitles" src="/api/v1/docs/assets/screen_recordings/subtitles/webhdp_real_13_first_time_setup_wizard.en.vtt" srclang="en" label="English">
  Your browser does not support the embedded video.
</video>

What to watch for:

1. The recording opens `/setup` on a disposable uninitialized Docker clone.
2. System checks report deployment mode and mandatory readiness items.
3. Renderer unavailability in conservative server mode is handled through the
   safe skip-rendering path.
4. The administrator account is created without exposing the password.
5. Setup completion redirects to login without leaking bootstrap tokens.
