# Documentation Screen Recordings

This directory is reserved for curated WebHDP walkthrough recordings used by
in-app documentation guide pages.

Release policy:

- Only the media files listed in `manifest.json` are intended for the alpha
  source release.
- The alpha release ships only the accepted bundled videos listed in the
  manifest. Provisional automated captures were rejected because they did not
  demonstrate complete, meaningful user workflows.
- Alpha release videos must be real screen recordings from a running WebHDP
  environment. Route-tour, generated storyboard, or documentation-scroll
  placeholders are not shipped.
- Each video must stay below 5 MiB. Larger recordings should be published as
  external release assets or stored in Git LFS.
- English subtitles live in `subtitles/` and should be referenced with
  `<track kind="subtitles">` from the guide page that embeds the video.
- Draft storyboard generators may still be used for planning, but their output
  must stay out of the release manifest until it has been replaced by a real
  recording.
- OS metadata files such as `.DS_Store` must never be publishable.
- `scripts/check_release_assets.py` verifies that the guide references and
  shipped media stay in sync.
