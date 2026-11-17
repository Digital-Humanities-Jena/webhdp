# Historic reconstruction components and pipelines

The historic reconstruction integration provides eleven installable HDP
Components and fifteen native pipeline recipes. Components appear in the
existing **HDP Components** catalog. Installed components are available in
**Playground** and **Pipeline Constructor**; recipes become available when all
their selected profiles have pinned Docker images or verified SIF checksums.
Reimporting a component or restarting WebHDP preserves saved pipeline versions.
No migration or new frontend is required.

The [source evaluation](../development/historic_reconstruction_evaluation.md)
explains the supplied repository's working stages, missing modules, machine
dependencies and redistribution limits. The portable COLMAP implementation is
separate from the original learned-feature research workflows. Their names and
reports retain that distinction.

## Components

| Component key | Inputs | Outputs | Runtime |
|---|---|---|---|
| `historic_prepare` | Photograph ZIP or image; alternatively a photograph list | Prepared dataset ZIP, report with original names and SHA-256 | Local CPU / HPC |
| `historic_pairs` | Prepared dataset ZIP, optional GPS JSON | Dataset ZIP containing pairs, pair list, report | Local CPU / HPC |
| `historic_sparse` | Dataset ZIP, optional selected pairs inside it | Sparse reconstruction ZIP, PLY points, quality report | Local CPU / HPC CUDA |
| `historic_dense` | Sparse reconstruction ZIP | Dense workspace ZIP, fused PLY, mesh PLY, quality report | HPC CUDA |
| `historic_georeference` | Sparse reconstruction ZIP and paired 3D control points | Transformed sparse reconstruction, PLY, similarity transform, residual report | Local CPU / HPC |
| `historic_segmentation` | Image ZIP | Semantic masks in workspace and dataset ZIPs, report | Research HPC |
| `historic_original_sfm` | Image ZIP, optional masks/stereo list | Original learned-feature reconstruction workspace, report | Research HPC |
| `historic_geolocalization` | Image ZIP and GPS or bounds | Historic/panorama localization workspace, report | Research HPC |
| `historic_dense_intrinsics` | Previous geolocalization workspace ZIP | Refined workspace, report | Research HPC |
| `historic_refine_keypoints` | Image and sparse-model ZIP | Refined model workspace, report | Research HPC |
| `historic_mvs` | Image and sparse-model ZIP | MVS Anywhere workspace and mesh, report | Research HPC |

Research stages require a separately provisioned source-pinned runtime and
weights. See [research installation and input layouts](historic_reconstruction_research.md).
The CPU image does not contain those dependencies, a CUDA-enabled pycolmap build,
or the COLMAP dense executable. No panorama download or external publication
occurs in the portable stages.

## Scene preparation and recipes

Each reconstruction record represents **one scene ZIP containing overlapping
photographs**, rather than an individual photograph. ZIP subdirectories are
supported, including duplicate basenames in different directories. Preparation
assigns unique stable names, records the mapping and original checksums, applies
EXIF orientation, removes metadata and writes JPEG derivatives. Originals remain
in the uploaded source ZIP. The runtime accepts up to 1,000 images, 30,000 ZIP
entries and 8 GiB of total uncompressed ZIP content, with a 2 GiB per-file limit.
Image decompression and unsafe archive paths are checked before reconstruction.

In Playground, select the scene ZIP directly. For a local HDPC project, scan the
scene ZIPs as primary source files (include `.zip` in the scan extensions). The
standard batch ZIP upload extracts its transport archive: put the individual
scene ZIPs **inside** that outer archive and reference each scene ZIP in the MSF.
Uploading the photographs themselves as separate primary records would create
separate one-image runs and cannot reconstruct a scene.

The local recipes are `historic_prepare_images`, `historic_prepare_pairs`,
`historic_sparse_reconstruction` and `historic_georeference`. Each has an `_hpc`
counterpart. `historic_dense_reconstruction_hpc` chains preparation → pairs →
sparse reconstruction → dense fusion and meshing. HPC sparse recipes explicitly
request CUDA. Six `historic_research_<stage>_hpc` recipes run the original stages.

Sparse reconstruction uses COLMAP SIFT and incremental mapping. It does not
substitute for upstream DISK/MegaLoc/LightGlue/MASt3R/LoMa algorithms. Photographs
with insufficient overlap or texture can fail reconstruction; the runner fails
instead of returning a synthetic model. Review registered image counts, point
counts and reprojection error in the scientific reports.

Prepared ZIPs use `dataset.json` with schema `webhdp.historic-dataset/1` and
`images/<prepared-name>.jpg`. The manifest retains checksums and the original
image name mapping. `pairs.txt` contains selected prepared-name pairs. Sparse
ZIPs add the COLMAP model under `sparse/`. Every downstream portable stage
verifies image checksums before use. Outputs have distinct stage report names
and are stored through WebHDP's existing execution-artifact system.

GPS pair selection accepts JSON mapping original or prepared image names to
`[latitude, longitude]`. Select `method=gps` and supply `gps_file` in Playground
or bind it explicitly in Pipeline Constructor. Exhaustive pairing is the
default. GPS selection narrows matching candidates; it does not georeference a
model.

### Dense fusion and surface trimming

Dense reconstruction runs COLMAP image undistortion, CUDA PatchMatch, stereo
fusion and Poisson meshing. `geometric_consistency=true` uses the geometric
depth maps. `max_image_size` bounds the dense image dimension; the Poisson octree
depth is fixed at 10. `poisson_trim` is a surface-density trimming threshold in
the range 0–20, with a default of 5. Lower thresholds retain more low-density
surface regions; they can also retain unwanted background geometry.

On the 11-image, 960-pixel validation scene, fusion produced 115,490 points, but
COLMAP's implicit trimming threshold of 10 removed every mesh face despite a
zero process exit. Meshing the same retained cloud with threshold 5 produced
280,574 vertices and 559,649 faces. The runtime now passes the threshold
explicitly, rejects an empty fused cloud before meshing, and reports point/face
counts plus bounded COLMAP diagnostics when meshing returns an empty result.
Threshold 10 remains selectable for denser scenes.

A dense request can use these explicit settings:

```json
{"inputs":{"input_file":"sparse-reconstruction.zip"},
 "parameters":{"max_image_size":960,"geometric_consistency":true,"poisson_trim":5.0}}
```

Run it with the normal file contract (`component_runner.py dense`) or the
installed HPC profile in Playground. Inspect the returned PLY geometry as well
as the success envelope. The independent retained-cloud check found finite
coordinates, unit cloud normals and valid face indices; eight of the 559,649
triangles had zero area. This is an untextured Poisson surface, not a guarantee
of a watertight or survey-accurate mesh. A mesher-only diagnostic does not replace
a full component or native pipeline acceptance run.

A four-stage native pipeline completed on an RTX A5000 with the installed
immutable SIF: prepare → pairs → CUDA sparse → dense. It used 2,048 sparse features per image,
960-pixel dense images, geometric consistency and `poisson_trim=5`. Independent
decoding verified 116,102 cloud points and a mesh with 282,660 vertices and
563,717 faces, all finite, with valid indices and no zero-area triangles.
Artifact downloads and physical bindings between stages were verified by hash.
For comparable visual review, export camera poses from the same run's sparse
artifact.

For measured georeferencing, supply `control_points_file` or place
`control_points.json` inside the sparse reconstruction ZIP:

```json
{"points": [
  {"source": [0, 0, 0], "target": [100, 200, 300]},
  {"source": [1, 0, 0], "target": [102, 200, 300]},
  {"source": [0, 1, 0], "target": [100, 202, 300]},
  {"source": [0, 0, 1], "target": [100, 200, 302]}
]}
```

Use at least three non-collinear correspondences, preferably more well-spread
surveyed points. `max_error` is in target coordinate units; `crs` labels the
coordinate system and does not perform a map projection. Review inlier counts
and residuals. Georeferencing transforms cameras and sparse points together.
Apply it before dense reconstruction; already dense bundles are rejected to
avoid mixing coordinate frames.

## Install the portable CPU runtime

From the WebHDP repository root:

```bash
docker build --platform linux/amd64 --tag webhdp-historic-reconstruction:local external_code/historic_reconstruction_runtime
.venv/bin/python scripts/validate_hdp_components.py external_code/historic_*
```

The pinned CPU image targets Linux x86-64 because that pycolmap release has no
Linux ARM wheel. Docker Desktop runs it through emulation on Apple Silicon;
allow additional build and processing time there.

In **Tools → HDP Component Installer**, choose **Local Docker**, then install
`historic_prepare`, `historic_pairs`, `historic_sparse` and
`historic_georeference` from the local catalog. The installer records the
resolved image identity. Importing mutable development tags alone does not
enable runnable recipes. Local execution requires workstation mode with
`WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=true` under the existing deployment policy.

GPU SIF builds must contain the same `/app/component_runner.py` entrypoint plus
a CUDA-enabled pycolmap and COLMAP dense executable. Use the runtime's
`Dockerfile.gpu` with an explicit immutable, compatible base image; its build
checks the required software. Convert the result to SIF and install each
component through **HPC SIF**, supplying the SIF and its SHA-256. Reuse the same
verified SIF for the five portable component manifests. The base image is an
operator-provided artifact: no unverified public GPU image is assumed.

Saved pipelines pin complete component manifests. If a component version has
already been installed for one strategy and used in a saved pipeline, install
the other strategy with a new `metadata.version` (for example `1.0.1`). The
installer intentionally refuses to replace a manifest that a saved pipeline
uses. Existing local recipes retain their original version while newly
available HPC recipes select the newly installed version.

Research SIFs additionally include the separate upstream source, dependency
trees, operator configuration and weights described in the research guide.
These are not bundled or automatically downloaded by WebHDP.

## Validation and Draco

```bash
.venv/bin/python -m pytest tests/test_historic_reconstruction_runtime.py tests/test_historic_reconstruction_upstream.py tests/test_historic_reconstruction_integration.py -q
WEBHDP_TEST_HISTORIC_DOCKER=1 .venv/bin/python -m pytest tests/test_historic_reconstruction_integration.py -q
```

The optional Docker test performs real native registry → Docker preparation →
pair selection → artifact persistence, using a temporary database and scene.
It passed on 6 November 2026. A separate real reconstruction inside the final
CPU Docker image registered all 11 ETH3D Statue photographs and produced 1,598
sparse points with a mean reprojection error of 0.4052 pixels. That run used the
image with networking disabled, a read-only root filesystem, a non-root user and
a 4 GiB memory limit. These figures describe the validation dataset, not a
guarantee for arbitrary historic collections or a ground-truth accuracy score.
The non-GPU tests exercise archive boundaries, checksum validation, image
preparation, pairing, robust similarity fitting, actual model/camera transforms,
research-stage command construction and failure handling. Research fixture
tests are contract checks, not proof of learned-model inference.

The manifest validator intentionally warns where a self-contained scientific
installation fixture is absent. Do not mark GPU or learned-model stages as
tested using empty archives or fabricated geometry. Use a real overlapping
photo set with `scripts/historic_reconstruction/validate_runtime.py`, which
independently decodes returned models and requires nonempty measured outputs.

To verify an HPC installation, request an allocation with the HPC operator's
approved GPU type, partition, memory and walltime. Validate the SIF and manifest
pins, then run the intended pipeline through WebHDP using rights-cleared,
overlapping images. Inspect every completed step and download the artifacts.
Check input and output hashes, registered camera/image counts, finite geometry
and surface validity. A CLI run inside an allocation checks the scientific
runtime; it does not exercise WebHDP's job staging, bindings or download.

Isolated acceptance exercised sparse CUDA and dense fusion on an RTX A5000.
Further research runs used a provisioned A100 runtime. These checks cover
the tested fixtures and installed runtimes. Use the [research runtime guide](historic_reconstruction_research.md)
for learned-stage setup and measured limits.
