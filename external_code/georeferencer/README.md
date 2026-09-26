# 3DGeoRef HDP Component

This installable component uses the pinned [3DOM-FBK/3DGeoRef](https://github.com/3DOM-FBK/3DGeoRef)
orthographic renderer and the outdoor LoFTR matcher used by its DIM stage. The
WebHDP adapter provides an explicit **reference-orthophoto workflow**, checked
coordinate transformations, isolated execution, and lossless GLB placement.

The **3D Georeferencing & Preview** pipeline runs this component followed by Fast
Renderer. It becomes available after an administrator installs a checksum-verified
HPC image. Adding the source files to WebHDP does not install or deploy it.

## Prepare inputs

Use a static, self-contained, textured GLB, upright in glTF's Y-up convention.
Include exactly one reference `.tif` or `.tiff` in each model's upload bundle.
The reference must cover the complete footprint and depict the same site.
Crop it closely around the site with a modest margin: a model occupying only a
tiny part of a large map may lose the detail needed for reliable matching.

The orthophoto must have an embedded projected CRS with metre units, square
orthogonal ground pixels, and 8-bit grayscale, RGB or RGBA imagery. Geographic
latitude/longitude rasters, feet, elevation grids, non-square pixels and missing
CRS metadata are rejected with an actionable message. Reproject/export these in
GIS software before upload. References are limited to 100 million pixels, at
least 64 pixels per side, and a 5 km local extent.

For batch upload, give each GLB and TIF/TIFF pair the same filename stem
(for example `church.glb` and `church.tif`) in the same folder. Add one metadata
spreadsheet row per GLB; the reference is included automatically as a companion.
Review each bundle in Files.
Each record's reference is isolated; another record's orthophoto is never used
as a fallback. In Component Playground, select the model and reference directly.

## Outputs and review

- `*_georeferenced.glb`: original nodes, geometry buffers, images and materials,
  wrapped by a placement node. Horizontal coordinates are centred on the model
  footprint to avoid precision loss from distant origins and global coordinates.
- `georeferencing_report.json`: CRS, geographic/projected anchor, source and
  reference hashes, source-to-local matrix, match residuals, coverage and revision.
- `alignment_overlay.png`: the aligned model footprint blended over the reference.
- The pipeline additionally renders five views of the placed model.

GLB coordinates are **east, up, south**, in metres. Projected coordinates are
`E = local.x + anchor_easting`, `N = -local.z + anchor_northing`.
The anchor denotes the horizontal centre of the model footprint. The
source-to-local matrix is row-major in the report and acts on column vectors;
glTF stores the equivalent matrix column-major. Placement metadata is also embedded
in `asset.extras.webhdp_georeference` so it travels with the GLB.

Absolute elevation is **not assigned**. Heights remain relative to the source
model's origin, scaled by the horizontal similarity fit. No elevation service is
queried. Image residuals measure matching consistency, not survey accuracy: inspect
the overlay and the reference's provenance/accuracy before scientific reuse.

The adapter checks four orientations, keeps RANSAC inliers, requires distributed
matches, and rejects inconsistent, mirrored, ambiguous or incomplete-footprint
alignments. It never fabricates a successful result when rendering or matching
fails. Failed records have no derived output and do not run the preview step.

## Verified build

Upstream revision: `e50e4562b43c0b105d77e417d01fedb5139529a6` (BSD-2-Clause;
see `UPSTREAM_LICENSE`). Use the upstream `3domfbk/3d-georef:v1.0.0-beta.1`
runtime as a starting point, recording its registry digest and SIF checksum.
The builder verifies the supplied base-image and outdoor LoFTR checkpoint hashes,
checks checkpoint loading, packages the pinned renderer and weights, and emits a
SIF checksum. Dependencies remain in the component image, not the WebHDP server.
The image packages PyTorch 2.5.1 with CUDA 12.1 and matching torchvision, rather
than depending on the upstream image's floating PyTorch installation. Package
download URLs and hashes are retained in the image's build reports. Rebuilding
against a trusted prior candidate reuses its verified PyTorch runtime.

```sh
python3 external_code/georeferencer/build_sif.py \
  --base-image /path/to/upstream.sif --base-sha256 TRUSTED_BASE_SHA256 \
  --weights /path/to/outdoor_ds.ckpt --weights-sha256 TRUSTED_WEIGHTS_SHA256 \
  --scratch /node-local/build-directory --output /path/to/new-candidate.sif
```

The builder also packages the shared GLB validation functions from
`external_code/mesh_optimizer/runner.py`; keep that sibling source available.
It does not register the candidate image or change an existing installation.
Import `component.yaml` using the standard HPC SIF installation workflow only
when deployment is authorized. HPC-Link verifies the installed image checksum
before each invocation and provides an isolated scratch/output directory.

The contract uses `WEBHDP_COMPONENT_REQUEST`, `WEBHDP_COMPONENT_RESPONSE`,
`WEBHDP_INPUT_DIR` and `WEBHDP_OUTPUT_DIR`. Model and reference paths must be
inside the staged input directory. No network downloads or external image uploads
are performed during processing.

## Deliberate upstream adaptations

The upstream top-level runner ignores its reference option, can return exit status
zero after failure, guesses model width through Gemini, and its DIM transformation
code retains rejected matches. This adapter calls the renderer directly, uses the
same LoFTR implementation through Kornia, keeps pixel resolution intact, and fits
a shape-preserving similarity with explicit pixel-centre and axis conventions.
It does not use the upstream pivot mesh or write large global coordinates into
float32 vertex buffers.

Automatic Gemini/Mapbox/GeoCLIP/Ollama geolocation is **not enabled**. It requires
separate credentials, external imagery disclosure choices and acceptance testing.
Supplying a known orthophoto is the supported component workflow; a guessed
location is not silently substituted for a verified reference.

## Tests

```sh
uv venv /tmp/georef-tests --python 3.11
uv pip install --python /tmp/georef-tests/bin/python \
  pytest numpy opencv-python-headless rasterio pyproj pillow
/tmp/georef-tests/bin/python -m pytest external_code/georeferencer/test_component.py \
  --confcutdir=external_code/georeferencer
.venv/bin/python -m pytest tests/test_georeferencer_registry.py
```

`validation/fixtures.py` creates reproducible textured site models and reference
orthophotos with known placement, rotated orientations, several projected CRSs,
Unicode paths, and a deliberate mismatch. These validate transformation recovery
and failure handling; they do not establish accuracy for arbitrary real-world sites.
See [validation results](validation/results.md) for the tested artifact identity
and acceptance scope. `validation/native.py` runs the complete pipeline against
a held test allocation using a disposable application database and `.hdpc` session.
