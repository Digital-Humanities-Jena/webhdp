# Historic reconstruction runtime

The portable stages are an independent, conservative implementation of image
preparation, pair selection, COLMAP sparse reconstruction, dense reconstruction,
and similarity georeferencing. They do not substitute ordinary SIFT for the
original repository's learned methods without reporting that distinction. The
separate `upstream-*` processors run an operator-provided, hash-pinned research
checkout; source, learned models and credentials are not distributed here.

## Contract

Run `python /app/component_runner.py STAGE` with the standard
`WEBHDP_COMPONENT_REQUEST`, `WEBHDP_COMPONENT_RESPONSE`, `WEBHDP_INPUT_DIR`, and
`WEBHDP_OUTPUT_DIR` environment variables. CLI equivalents for the request,
output directory, and response are `--webhdp-input`, `--webhdp-output-dir`, and
`--webhdp-result`. Inputs must remain inside the staged input root. Requests use
`{"inputs": {...}, "parameters": {...}}`. Use a fresh output directory per run.

| Stage | Input ports | Output ports |
| --- | --- | --- |
| `prepare` | `input_file` (image/ZIP) **or** `input_files` (image list) | `dataset`, `report` |
| `pairs` | `input_file` (dataset ZIP), optional `gps_file` | `dataset`, `pairs`, `report` |
| `sparse` | `input_file` (dataset ZIP) | `reconstruction`, `point_cloud`, `report` |
| `dense` | `input_file` (sparse reconstruction ZIP) | `reconstruction`, `point_cloud`, `mesh`, `report` |
| `georeference` | `input_file` (sparse reconstruction ZIP), `control_points_file` or bundled `control_points.json` | `reconstruction`, `point_cloud`, `transform`, `report` |

Datasets contain `dataset.json` (`schema: webhdp.historic-dataset/1`) and
`images/<prepared-name>`. The manifest retains the source name, source SHA-256,
prepared SHA-256 and dimensions. Prepared names are deterministic six-digit
JPEG basenames. Preparation applies EXIF orientation, bounds image dimensions,
removes EXIF, converts to RGB and composites transparency onto white. It never
edits the originals. Maximums: 1,000 images, 100 million pixels/image, 8 GiB
uncompressed ZIP content and 30,000 archive entries. Symlinks, duplicate names,
unsafe paths, encryption, and mutated dataset content are rejected.

Pair selection accepts GPS JSON `{ "original/name.jpg": [latitude, longitude] }`
or prepared names. All images need finite GPS values for GPS selection; invalid
or missing values fail explicitly. Geographic coordinates are WGS84 degrees;
distances use a spherical Earth of radius 6,371,008.8 m. The selection is the
symmetric union of the nearest `max_neighbors` images within `radius_m`.
Exhaustive selection is the default. Isolated images are reported.

Sparse reconstruction uses SIFT with individual camera intrinsics. When the
bundle includes `masks/<image-stem>.png`, every image needs a binary grayscale
mask of matching dimensions (0 excludes features; 255 includes). The runtime
converts the naming convention for COLMAP, applies masks during extraction, and
records their SHA-256 values. A complete
pair graph uses native COLMAP matching. A restricted graph uses bounded-memory
CPU SIFT ratio/mutual matching followed by COLMAP geometric verification. CUDA
can accelerate extraction in either case. Sparse reconstruction keeps the model
with the most registered images, breaking ties by point count, and reports
unregistered images and omitted model count. Sparse coordinates have arbitrary
scale until georeferenced. A minimum registered-image gate and nonempty point
cloud are mandatory; image registration is not guaranteed for every dataset.

Dense reconstruction requires the CUDA COLMAP executable, uses PatchMatch,
stereo fusion and Poisson meshing (depth 10), and returns an **untextured** mesh.
It does not run upstream MVSAnywhere, Neuralangelo, NeuS, or novel-view synthesis.
CPU parallelism honors `SLURM_CPUS_PER_TASK` and is capped at eight threads.

Georeferencing control JSON is:

```json
{"points": [
  {"source": [0, 0, 0], "target": [100, 200, 300]},
  {"source": [1, 0, 0], "target": [102, 200, 300]},
  {"source": [0, 1, 0], "target": [100, 202, 300]}
]}
```

Provide at least three noncollinear 3D correspondences. `max_error` is measured in
target coordinate units. A deterministic robust fit rejects inconsistent points
and reports every residual and inlier decision. Both sparse points and camera
poses are transformed. `crs` is a descriptive label; no CRS reprojection occurs.
Georeference before dense meshing so all derived geometry has the same frame.

## Packaging

CPU image (preparation, pairs, CPU sparse and georeferencing), built for
Linux x86_64 because pycolmap 3.13 has no Linux ARM64 wheel. Docker Desktop on
Apple Silicon runs this image through its x86_64 emulation:

```sh
docker build --platform linux/amd64 -t webhdp-historic-reconstruction:local external_code/historic_reconstruction_runtime
```

The CPU image intentionally does not claim GPU or dense support. The GPU recipe
requires an existing operator-reviewed Linux CUDA image containing compatible
COLMAP CLI and pycolmap; supply its immutable digest:

```sh
docker build -f external_code/historic_reconstruction_runtime/Dockerfile.gpu \
  --build-arg GPU_BASE_IMAGE=registry.example/colmap-runtime@sha256:REPLACE_WITH_DIGEST \
  -t webhdp-historic-reconstruction:gpu external_code/historic_reconstruction_runtime
```

The build checks CUDA pycolmap support and the COLMAP executable. Convert the
built image to SIF using the site's supported Apptainer/Singularity workflow,
record its SHA-256, and install it through WebHDP's HPC Component Installer. Both
images expose `/app/component_runner.py`; GPU execution needs `--nv` and a GPU
allocation. This recipe does not publish an image, allocate resources or deploy
WebHDP. Optional upstream dependencies require a separately provisioned base and
operator configuration described in `upstream.py` and the integration guide.

For a bounded geolocation acceptance run, an operator can pin a `pano_metadata`
JSON asset and set `geolocation_acquisition` in the operator configuration:

```json
{"geolocation_acquisition": {"max_panoramas": 4, "bounds_margin": 50,
  "zoom": 3, "cubemap_width": 1024, "download_workers": 2}}
```

The seed is a nonempty dictionary of panorama IDs to genuine metadata containing
finite `lat` and `lon` coordinates. It must contain no more than `max_panoramas`
(hard maximum 32). Its SHA-256 is verified like other installation assets. The
adapter passes the upstream `--pano-meta-json` option, which bypasses discovery
and applies normal spatial/coverage filtering to only those IDs. This bounds the
number of panorama downloads without changing matching or reconstruction.
Settings are operator-owned; a run cannot select source code or arbitrary flags.
Without these optional settings the existing network-authorized acquisition
behavior is retained. Panorama metadata and historic GPS priors require their
own provenance; they are not surveyed ground truth.

The original SfM launcher's pinned Doppelgangers checkpoint may contain an
`argparse.Namespace` configuration. Modern PyTorch is given only that extra safe
global while retaining its restricted checkpoint loader. This does not enable
arbitrary pickle loading for run inputs.

Original learned SfM retrieves `num_retrieval` neighbors per image (default 100),
limited to the number of other images in the dataset. This prevents the author's
HLoc retrieval call from requesting more neighbors than exist in small inputs.
The report records both requested and effective counts; original scientific
source and learned feature/matcher choices remain unchanged.

The portable scientific dependency versions are pinned in `requirements.txt`.
The [COLMAP Python API](https://colmap.github.io/pycolmap/pycolmap.html) is the
scientific backend. COLMAP Python APIs were exercised with 3.13.0 on CPU. GPU validation uses the
allocated site's CUDA build and records its version and source hashes separately.
