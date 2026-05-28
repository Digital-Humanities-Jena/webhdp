# Components And Development Walkthroughs

These recordings help operators and developers verify manifest-backed HDP
Component behavior before they rely on components inside broader workflows.

## HDP Component Playground And Component Tests

Use this with the component installation and developer guides when checking a
single installed component.

<video controls muted playsinline preload="metadata">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_01_hdp_component_playground_tests.webm" type="video/webm">
  <source src="/api/v1/docs/assets/screen_recordings/raw/webhdp_real_01_hdp_component_playground_tests.mp4" type="video/mp4">
  <track kind="subtitles" src="/api/v1/docs/assets/screen_recordings/subtitles/webhdp_real_01_hdp_component_playground_tests.en.vtt" srclang="en" label="English">
  Your browser does not support the embedded video.
</video>

What to watch for:

1. The Playground lists manifest-backed HDP Components from the running
   instance.
2. Input File Classification opens from the component catalog.
3. The run uses a seeded session fixture at `source_files/bronze_helmet.glb`.
4. The Playground run completes successfully.
5. The result JSON classifies the GLB as a 3D mesh model.
