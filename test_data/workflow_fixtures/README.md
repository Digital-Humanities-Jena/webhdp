# WebHDP Workflow Fixtures

This directory is the curated, CI-ready fixture set distilled from earlier local test data. It is intentionally small enough to live in the repository while still covering the workflow scanner's important grouping and dependency cases.

All media-like assets in this directory are synthetic, generated, or minimized fixtures. Do not replace them with real-world media unless redistribution rights and attribution requirements are documented in the release notices.

## What Is Included

- Root-mode bundling with stem, regex pattern, and literal prefix/suffix strategies.
- Subdirectory and hybrid grouping modes.
- OBJ/MTL texture dependency discovery, including archived texture folders.
- GLB, GLTF external BIN/image, OBJ, FBX, JPEG, and PNG fixtures with tiny generated content.
- FBX material-folder discovery.
- Negative fixtures for missing MTL files, missing texture references, and the current literal-only `prefix_suffix` implementation.
- Fresh MSF CSV/XLSX files that reference only curated fixture filenames.

## What Was Excluded

The unsorted source directory contains duplicate GLB files, extracted archive copies, `.DS_Store` files, stale `.hdpc` databases, broad real-world datasets, and duplicate texture ZIPs. Those are not copied here.

## Using The Fixtures

Use `manifest.json` as the source of truth for test setup. Each case declares its relative path, scanner options, expected record count, primary source filenames, expected bundle members, and any expected warning/error statuses.

The scanner behavior in this repository is intentionally reflected as-is: core identifier tests use the `pattern` strategy, and `prefix_suffix` tests use literal prefix/suffix matching unless a later scanner change expands that behavior.
