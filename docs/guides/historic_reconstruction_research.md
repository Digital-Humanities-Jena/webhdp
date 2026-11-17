# Historic reconstruction research components

These six optional components execute the supplied historic-reconstruction
research code through fixed adapters. They require a separate scientific
runtime. The portable WebHDP COLMAP image does not include the original custom
HLoc, LoMa/CASPAR build, MASt3R/Doppelgangers++, VGGSfM, RoMa or MVSAnywhere.
See the [source evaluation](../development/historic_reconstruction_evaluation.md)
for the exact capability and dependency boundaries.

| Component | Required input ZIP layout | Additional requirements | Outputs |
| --- | --- | --- | --- |
| `historic_segmentation` | `images/` | Cached Mask2Former ADE20K model and processor | PNG keep-masks in the dataset ZIP, per-image completeness check |
| `historic_original_sfm` | `images/` | Custom HLoc configurations/arguments, pycolmap CASPAR, modified MASt3R DG head, DG checkpoint | Original learned-feature sparse models and workspace |
| `historic_geolocalization` | `images/`, optional `gps.json` or `bounds.json` | LoMa/CASPAR, panorama network acquisition, cached MegaLoc/Mask2Former, DG unless skipped; optional AnyCalib | Scene models, `georef.json`, upstream reports and panorama evidence |
| `historic_dense_intrinsics` | A preceding geolocalization ZIP including `workspace/scenes/`, `images/`, `panoramas/`, `cubemaps/` | RoMa v2/DINOv3 cache; completed upstream scene report markers | Dense correspondence/fit decisions, pruned DB and refined scene models |
| `historic_refine_keypoints` | `images/` and `sparse/` COLMAP binary model | VGGSfM plus pinned VGGSfM checkpoint and its dependencies | Refined binary model; bundle adjustment enabled by default |
| `historic_mvs` | `images/` and `sparse/` COLMAP binary model with at least eight registered views | MVSAnywhere, pinned model/data YAML and checkpoint, CUDA | Rectified images, regenerated covisibility tuples, cached depths, TSDF mesh/workspace |

All stages return `workspace_bundle` and `report`. Segmentation additionally
returns the same ZIP through `dataset_bundle` for a downstream component. The
ZIP retains image hashes, stage logs and a report identifying the installed
source, interpreter, dependency and asset digests. Upstream pickle and object
array caches are omitted from the portable ZIP because they are executable
serialization formats; they are not required by dense-intrinsics continuation.

The ZIP must use relative filenames without whitespace. Prefer the portable
Historic Image Preparation component first: it normalizes names/orientation and
preserves the original-name/hash mapping. Existing `dataset.json` image checksums
are verified before processing. If a research ZIP has no manifest, the adapter
creates one without claiming that metadata was removed. Input bundles containing
Python/native code, weights or pickle/object-array caches are rejected. Weights
are provided only by the operator runtime.

Geolocalization accepts one staged `gps_file` or `bounds_file`, or the equivalent
file in the ZIP. GPS is `{ "000001.jpg": [latitude, longitude] }`; bounds are
`[[latitude, longitude], ...]` with at least three points. Coordinates must be
finite and inside latitude/longitude limits. Its result is a model in local ENU
coordinates with a georeference origin. The upstream latitude/longitude camera
export is unimplemented and is explicitly reported as such. Unregistered images
and scene diagnostic reports remain part of the scientific result.
Geolocation and dense intrinsics accept one or more historic input photographs
because panorama views support the reconstruction. Their output still requires
at least three registered views overall and at least one registered historic
input photograph. Reports distinguish registered input images from panorama
images; an all-panorama model cannot establish successful historic geolocation.

## Provision a private research runtime

1. Prepare a private Linux/CUDA environment from the supplied source and the
   corresponding external projects. Use the actual custom HLoc fork and COLMAP
   build required by the snapshot. Installing stock packages with the same
   import names is insufficient. Keep the package directory named
   `historic_reconstruction_pipeline`. The original archive contains no licence
   declaration; this integration does not redistribute it or its checkpoints.
2. Put `component_runner.py` and `upstream.py` from
   `external_code/historic_reconstruction_runtime/` in `/app` inside the same
   private container/SIF. Install the small runner dependencies (Pillow, PyYAML,
   NumPy, trimesh) as well as the scientific environment. Package the approved
   source, dependency roots, configs and weights at stable absolute paths inside
   that SIF. No production installation or deployment was performed by this
   integration task.
3. Prepopulate Hugging Face and Torch caches and download reviewed checkpoints
   during environment preparation. Hugging Face model/processor inference runs
   with offline flags. `allow_network` permits panorama acquisition; it does not
   turn on model downloads. The original keypoint configuration is copied into
   the run workspace with `resume_ckpt` set to the pinned checkpoint and
   `auto_download_ckpt: false`.
4. Generate the private operator JSON below using the fingerprint functions from
   `/app/upstream.py`. `source.path` is the package directory, while each
   `dependencies[].path` is an import root to add to `PYTHONPATH`, for example
   the directory containing `hloc/`. Tree hashes include every regular file
   except Git metadata, interpreter bytecode and common tool caches; symlinks
   inside trees are rejected. Use materialized cache files instead of Hugging
   Face snapshot symlinks. File hashes pin the actual interpreter/checkpoints.
5. Set `HISTORIC_RECONSTRUCTION_UPSTREAM_CONFIG=/opt/historic/operator.json`
   **inside the SIF environment**. This is an operator setting, never a public
   pipeline parameter. Import the desired component manifests through HDP
   Components, install the SIF with its SHA-256, then select the generated HPC
   research pipeline in the Constructor. The existing native installation gate
   requires a pinned SIF before publishing an executable recipe.

A minimal segmentation-only configuration has this shape; replace every digest
with the calculated value, and enable only stages actually provisioned:

```json
{
  "schema_version": 1,
  "enabled_stages": ["segmentation"],
  "python": {"path": "/opt/science/bin/python", "sha256": "CALCULATED_FILE_SHA256"},
  "source": {
    "path": "/opt/research/historic_reconstruction_pipeline",
    "sha256": "CALCULATED_TREE_SHA256"
  },
  "dependencies": [
    {"path": "/opt/research/hierarchical_localization", "sha256": "CALCULATED_TREE_SHA256"}
  ],
  "assets": {
    "model_cache": {"path": "/opt/models/huggingface", "kind": "tree", "sha256": "CALCULATED_TREE_SHA256"}
  },
  "allow_network": false,
  "timeout_seconds": 21600
}
```

Calculate a digest inside that environment with:

```sh
PYTHONPATH=/app /opt/science/bin/python -c 'from upstream import tree_sha256; print(tree_sha256("/opt/research/historic_reconstruction_pipeline"))'
PYTHONPATH=/app /opt/science/bin/python -c 'from upstream import file_sha256; print(file_sha256("/opt/science/bin/python"))'
```

Required asset names by stage:

| Asset key | Kind | Stages |
| --- | --- | --- |
| `model_cache` | `tree`, Hugging Face cache root | segmentation, original SfM, geolocalization |
| `torch_cache` | `tree`, `TORCH_HOME` root | original SfM, geolocalization, keypoint refinement |
| `doppelgangers_weights` | checkpoint file | original SfM; geolocalization unless `skip_doppelgangers=true` |
| `romav2_hub` | `tree`, RoMa/DINOv3 Torch hub directory | dense intrinsics; geolocalization with `dense_intrinsics=true` |
| `pano_metadata`, `tls_ca_bundle` | Optional bounded panorama JSON and cluster CA certificate bundle files | geolocalization |
| `native_libraries` | Optional pinned directory of native DSOs, prepended to the child library search path | separately compiled COLMAP runtimes |
| `vggsfm_weights` | checkpoint file | keypoint refinement |
| `mvs_model_config`, `mvs_data_config`, `mvs_checkpoint` | two YAML files and a checkpoint | MVS |
| `mvs_repository`, `mvs_extension_cache` | trees containing the checked repository and precompiled CUDA extension cache | MVS |
| `mvs_cuda_compiler`, `mvs_cxx_compiler`, `mvs_ninja` | compiler/build-tool executable files | MVS |

Add each asset under `assets` with `path` and `sha256`. Add the matching project
import roots under `dependencies`. AnyCalib is optional in the original
geolocalization implementation: when absent it logs that the default camera
initialization remains. The saved logs retain that distinction. Cache trees and
pinned files are rechecked after execution against the original pins. The
operator JSON's initial byte digest is checked before and after that validation;
replacing both source and configuration during a run cannot publish success.

The preflight checks imports, actual CUDA visibility for GPU stages, the custom
HLoc parameter/configuration interface, and pycolmap LoMa/CASPAR capability. It
cannot establish scientific correctness of a checkpoint merely by importing it.
In particular, the tested official `pycolmap-cuda12==4.2.1` wheel exposes the
CASPAR and LoMa enum values while omitting both compiled implementations. The
adapter therefore checks CASPAR mapper-option validation and the conditional
`LomaExtractionOptions` binding before starting inference. A compatible build
for geolocation must enable `CASPAR_ENABLED`, `ONNX_ENABLED` and CUDA explicitly;
original SfM needs CASPAR but performs its LoMa inference through HLoc. A package
version or enum check alone is insufficient. Dense intrinsics consumes the
completed geolocation workspace and uses RoMa plus the original Ceres-based
triangulation/consistency adjustment, so it is not gated on CASPAR or LoMa.
Use the native smoke test and a representative small dataset after installing a
new runtime. For Draco, select `gpu` or `gpu-test`; pending allocation time is
separate from component execution time. Set allocation wall time and component
timeout to fit the actual scene. The example operator timeout does not override
WebHDP's enclosing job limit.

For a bounded geolocation acceptance run, the operator may pin a
`pano_metadata` JSON file under `assets` and add `geolocation_acquisition`:

```json
{
  "geolocation_acquisition": {
    "max_panoramas": 4,
    "bounds_margin": 50,
    "zoom": 3,
    "cubemap_width": 1024,
    "download_workers": 2
  }
}
```

This passes the original upstream panorama-seed option and bypasses unbounded
discovery. The pinned JSON must contain at most the declared number of panorama
IDs (hard maximum 32), each with valid finite latitude/longitude metadata.
Panorama imagery still comes from the original acquisition implementation; this
setting does not fabricate coordinates or replace scientific inference. Keep the
original image/GPS provenance and acquisition metadata with verification evidence.
With `allow_network=true`, the child preserves the installed environment's
standard proxy variables. A pinned `tls_ca_bundle` sets the Python TLS and
Requests trust stores; certificate verification remains enabled. The Draco
panorama acquisition check used the existing compute-node CA bundle to trust its
institutional proxy. Proxy values are not included in component reports.
ONNX Runtime telemetry is disabled before child initialization, including when
panorama acquisition is enabled; acquisition does not authorize runtime telemetry.

Original SfM's `num_retrieval` defaults to 100 and is clamped to the actual image
count minus one, because a small dataset cannot have 100 distinct neighbors.
The report records both requested and effective values. The original SfM and
geolocation launchers allow only the known `argparse.Namespace` configuration
class while loading the operator-pinned Doppelgangers checkpoint; they do not
disable restricted checkpoint loading globally.

## Runs and verification

Use a fresh image ZIP for segmentation, original SfM and geolocalization. The
latter two refuse an existing `workspace/` to avoid stale upstream completion
markers. Dense-intrinsics refinement accepts a copied completed workspace and
clears only previous dense-intrinsics outputs/markers in that isolated copy. Set
`skip_doppelgangers` to match the geolocalization run, since its value determines
the upstream scene directory tag.
The original geolocation source links its merged masks to semantic mask files.
The adapter materializes only these exact matching mask links inside the private
dataset, preserving bytes and image dimensions; all other links remain rejected
by the archive boundary.

Dense intrinsics validates the actual numeric RoMa observations, fit records,
calibration decisions and successful-fit inlier arrays. Missing, inconsistent,
nonfinite or all-empty evidence fails. A legitimate run may reject every proposed
camera update; upstream then writes no calibrated model. The component reports
`executed_no_accepted_updates`, retains the validated input models, and records
zero accepted updates. Accepted updates require a new valid model. Both outcomes
include actual before/after camera parameters and changed/unchanged counts.
At least one historical input must remain registered. Filenames with the same
stem are rejected because upstream uses the stem for its per-image NPZ files.

For keypoint refinement, put the desired model directly in `sparse/`, alongside
`images/`. For MVS use the same layout; the adapter validates the model/image
references, runs pycolmap undistortion, computes the original covisibility
function, and writes the exact `mvs_tuples.txt` expected by the source adapter.
It never consumes arbitrary caller-supplied tuple paths. At least eight views
are needed for the seven-source-view tuple layout. MVS output meshes are decoded
and checked for actual faces/vertices. Its dataset loader has no ground-truth
depth, so upstream placeholder depth inputs do not establish depth accuracy.

A zero process exit is insufficient: segmentation requires every correct-sized
mask, reconstruction/refinement require decoded models with at least three
registered images, nonzero points, finite coordinates/camera parameters/poses/
keypoints and finite reprojection error. Camera dimensions must match the staged
photograph or cubemap. MVS requires a nonempty decoded mesh. These are
structural/consistency gates, not independent
accuracy measurements. Stage failures return component failure; no substitute
geometry is emitted. Bounded child diagnostics are included in component logs on
failure, and successful ZIPs retain full stage logs.

Local adapter tests exercise source pin drift, parameter/input boundaries, the
fixed child launchers, actual subprocess file handoff and missing-output failures.
Their deterministic child fixture is a contract test, not a claim that
Mask2Former or the other neural models were exercised. Original-method scientific
acceptance remains tied to observed runs in the matching installed environment.

## Verified VGGSfM refinement runtime

The bounded acceptance scene used the 11 prepared Statue photographs and their
portable sparse reconstruction. The input contained `images/`, `sparse/` and
`dataset.json`, with no existing `workspace/`. On a Draco RTX A5000 allocation, the original refinement source ran without modification.
`max_refine_num=32` limits **each of two track-selection passes**. Setting
`run_ba=false` disables the additional adjustment/filtering loops; the upstream
method still performs its base bundle adjustment after refining tracks.

The following pins and compatibility choices reproduce that research setup:

| Item | Verified value |
| --- | --- |
| Historic source package tree | `cb8266490126887616c022f983803141e9ec393522aaab249d167e25c8943a6a` |
| Official VGGSfM checkout | `e1d9d2eb2b3575525792206fb94b2c749c58dc50` |
| HLoc checkout for refinement | `c13273bd0ecc2917a35910fd843712a1c6243193` |
| LightGlue checkout | `eb42fee2d71449efb0aa5c10549752b5d75384d8` |
| PyCOLMAP | `3.13.0`; the source calls the three-argument `ObservationManager.filter_frames` API |
| PyCeres / Kornia | `2.6` / `0.8.2` |
| Successful Python 3.12 environments | Torch `2.6.0+cu124`, NumPy `1.26.4`; and Torch `2.11.0+cu126`, NumPy `2.4.4` |

Use the **full** `vggsfm_v2_0_0.bin`, not the tracker-only checkpoint. The
[official checkpoint at the verified revision](https://huggingface.co/facebook/VGGSfM/resolve/643a1eb2069dad9b4cff071960323542477272e3/vggsfm_v2_0_0.bin)
contains 1,125,199,014 bytes and has SHA-256
`e14f2c292686f078ae45bb323c562acc1e4e5fe5d3f940480c565b72af822778`.
The publisher declares the weights under CC-BY-NC-4.0. Prepopulate `torch_cache`
with the official DINOv2 Hub code and
`hub/checkpoints/dinov2_vitb14_reg4_pretrain.pth`, then hash the complete cache
tree. Include `hub/trusted_list` before pinning the cache; creating that file
during inference would correctly fail the post-run immutability check.

Keep the refinement Python overlay separate from segmentation's Kornia 0.9.0
overlay. Refinement uses `kornia.utils.get_cuda_or_mps_device_if_available`,
whereas the segmentation snapshot needs a different API. Pinning PyCOLMAP 3.13.0
also matters: the 4.0.4 environment completed real tracker inference and bundle
adjustment, then failed because its `filter_frames` requires a fourth argument.
That failed receipt is retained alongside the successful runs.

For a new container, copy the configured source, import roots, checkpoint and
cache into the image, preserving their content hashes. Recompute the interpreter
pin and update absolute configuration paths to the container locations. The
verified overlay adds approximately 125 MB of Python packages to the existing
ART environment; it does not require copying the separate DA3 environment.
Run an actual small-scene contract test after import checks because matching
package names alone do not establish API compatibility.

The following command runs inside an already authorized GPU allocation. Set the
four paths to the provisioned interpreter, wrapper directory, immutable operator
JSON and input directory containing `scene.zip`. Use a new output directory for
each run. Native Playground and Constructor execution should use the installed
SIF profile rather than operator paths supplied as public parameters.

```bash
research_python=/opt/science/bin/python
research_runtime=/app
research_operator=/opt/historic/operator.json
research_inputs=/inputs
research_output=$(mktemp -d /tmp/webhdp-refinement.XXXXXX)
cat > "$research_output/request.json" <<'JSON'
{"inputs":{"input_file":"scene.zip"},"parameters":{"max_refine_num":32,"run_ba":true}}
JSON
env WEBHDP_INPUT_DIR="$research_inputs" \
    HISTORIC_RECONSTRUCTION_UPSTREAM_CONFIG="$research_operator" \
    "$research_python" "$research_runtime/component_runner.py" upstream-refine_keypoints \
    --webhdp-input "$research_output/request.json" \
    --webhdp-output-dir "$research_output/artifacts" \
    --webhdp-result "$research_output/result.json"
```

Repeat with `run_ba=false` and a fresh output directory to check both behaviors.
Download both artifacts, verify their recorded SHA-256 values, decode
`workspace/refined/` independently, and compare the source image bytes, registered
image names, finite camera/point/keypoint values and reprojection statistics.
For this fixture, the additional-BA variant retained 11 images and 1,604 points,
changed 220 2D observations, and reduced mean reprojection error from 0.40046 to
0.35262 pixels. The no-additional-BA variant retained 1,613 points and produced
0.39643 pixels. These values describe this fixture, not metric survey accuracy
or a guarantee for other scenes.

Slurm recorded approximately 3.75 GiB maximum RSS for the ART-based run using
four CPUs. A 16 GiB acceptance profile has headroom for this bounded fixture;
it is not a memory estimate for the default 100,000 tracks per pass or larger
photograph collections. Record failed and successful direct checks separately
from native WebHDP SIF runs. Offline model flags and pinned caches do not establish network
isolation; Torch Hub may still query repository metadata.

After running the native refinement pipeline, verify downloaded artifact
checksums, preserved source image/model bytes, image-camera dimensions, finite
geometry and camera poses, changed observations and reported reprojection
errors. The tested native component version 1.0.1 registered 11 images and
produced 1,604 points and 220 changed observations. Mean reprojection error
dropped from 0.400457 to 0.352618 pixels. Its request and downloads confirmed
the 32-track cap, additional adjustment, unchanged input bytes and the 4 CPU /
16 GiB / 1 GPU profile. These figures describe one fixture; the default
100,000-track setting requires separate memory and accuracy checks.

## Provisioning the MVSAnywhere runtime

MVSAnywhere needs a separate environment from the portable CUDA or refinement
images. The private validation environment uses Python 3.10, Torch 2.1.2 with
CUDA 11.8, PyTorch3D 0.7.8, Open3D 0.16, Lightning 2.2.5, Kornia 0.6.7,
PyCOLMAP 3.13.0, moviepy 1.0.3 and scikit-image 0.24.0. Preserve the environment's
absolute prefix when copying it into a container; conda compiler and library
paths can depend on that prefix. These package versions describe the prepared
environment and do not by themselves establish scientific acceptance.

The private source checkout is the author's unmodified MVSAnywhere commit
`5bd49bba0992aa56060e1aa3bb40b2150b04726f`. The publisher's
`mvsanywhere_hero.ckpt` has SHA-256
`00878bab903b1d384cd6bb9ea092e247a9036d429cb8bcc3d6dcbb81f67e556d`;
the downloaded file also matched its published MD5
`bZ23qETYc6eQuaZQPfevFA==` (base64). The source's `LICENSE` declares
non-commercial use terms and redistribution restrictions. Keep that original
license and the provisioning receipts with the private runtime; the repository
integration does not vendor the model or redistribute this scientific image.

Importing the model alone is insufficient. The upstream fuser helper eagerly
imports its custom marching-cubes CUDA extension even when the selected depth
fuser is Open3D. Provision the matching CUDA 11.8 compiler/developer headers,
GCC 11 toolchain and Ninja, then compile and import that genuine extension before
pinning the runtime. Keep the repository root as the child's working directory:
its extension source paths are relative to `src/mvsanywhere/tools/marching_cubes/`.
The adapter copies the pinned compiled cache into a writable per-run directory
for PyTorch's lock/build files and caps `MAX_JOBS` to the allocated CPU count.
The installed cache and repository remain immutable.

After all dependencies and model caches are complete,
`scripts/historic_reconstruction/prepare_mvs_acceptance.py` creates the operator
configuration and checkpoint/source provenance receipt. Run it with Python
3.11 or newer; the installed component itself supports the Python 3.10 scientific
environment. The resulting operator asset list includes the full repository,
compiled extension cache and compiler executables in addition to the model/data
YAML files and model checkpoint. Regenerate pins after provisioning changes.

The private image builder has separate preparation, copy and finalization phases:

```bash
export HISTORIC_MVS_ROOT=/work/example/mvs-research
export HISTORIC_BUILD_ROOT=/work/example/mvs-sif-build
export HISTORIC_RUNNER_SOURCE="$HISTORIC_MVS_ROOT/runtime"
export HISTORIC_UBUNTU_ROOTFS=/work/example/portable-sif-build/rootfs
bash scripts/historic_reconstruction/build_mvs_runtime.sh prepare
bash scripts/historic_reconstruction/build_mvs_runtime.sh copy
```

Use real operator paths and execute inside an existing authorized allocation.
`prepare` creates a fresh Ubuntu-based root filesystem and copies only named
source/assets/provenance. `copy` preserves the private environment prefix and
verifies the copied environment with an rsync archive dry-run. Rerun `copy` after
any dependency, cache, configuration or wrapper change; it writes only inside
the new build root and never changes the provisioned source environment.

Run the genuine bounded MVS file contract with a checked model containing at
least eight registered views and `batch_size=1`. `fusion_max_depth` defaults to
3 and accepts 0.01–10,000; `fusion_resolution` defaults to 0.04 and accepts
0.001–10. Both distances are in the input model's units, which are arbitrary
unless the reconstruction has a measured scale. They are passed explicitly to
the original Open3D fusion path without rescaling the source reconstruction.

Check camera-space depths before choosing the clipping threshold. In the Statue
input, first-view positive sparse-point depth percentiles were approximately
4.90/6.67/14.93 at 5/50/95 percent; fewer than 1% were below 3. That check did not
filter point visibility and is a scale diagnostic, not a ground-truth depth
measurement. The bounded acceptance request therefore uses:

```json
{"inputs":{"input_file":"sparse-reconstruction.zip"},
 "parameters":{"batch_size":1,"fusion_max_depth":30.0,"fusion_resolution":0.04}}
```

Choose values appropriate to the actual scene. Inspect the returned mesh and
depth artifacts independently. Only after that scientific acceptance succeeds
should the image be finalized:

```bash
export HISTORIC_MVS_ACCEPTANCE_RESULT="$HISTORIC_MVS_ROOT/accepted-run/result.json"
bash scripts/historic_reconstruction/build_mvs_runtime.sh finalize
```

The direct run on an RTX A5000 passed independent checks with these
settings: 11 complete eight-view tuples, 11 rectified images, 923,342 finite mesh
vertices and 1,596,662 faces with valid indices. Fifteen faces had zero area;
the output is not claimed to be watertight or defect-free. The original source
images and sparse model files were unchanged. Slurm execution took 127.38 seconds
with approximately 5.94 GiB peak RSS. These are direct scientific results for
the recorded runtime and fixture; native SIF integration is a separate check.

The native WebHDP run passed that check with component 1.0.1.
Its downloaded mesh exactly matches the direct mesh SHA-256
`77f6e024fba0f0804853fd46aed12f8f0bcba3bd94cc3ef78de6e8ee64261b02`.
Both artifact downloads, the remote staged input, runtime pins and the explicit
4 CPU / 32 GiB / 1 GPU acceptance profile were independently verified. The same
15 zero-area faces remain; native integration does not improve the mesh itself.

Finalization checks the supplied success receipt, tests the isolated container
imports and operator pins, normalizes permissions only in the copied filesystem,
and produces a SIF with a SHA-256 file. It then runs the exact MVS preflight
inside that SIF with `--nv` and a fresh writable output mount. This checks CUDA
availability, fuser imports, the copied JIT cache and unchanged runtime pins
with a two-CPU thread cap; it does not run neural inference. A successful probe
writes `sif-verification.json` alongside the image. Install that immutable image through
WebHDP and run the native pipeline separately; a host-environment success does
not prove that container packaging, native staging or artifact download works.
Retain failed attempts and their dependency diagnostics as separate evidence.

## Learned runtime packaging for the A100

The A100 validation used 40 GiB of device memory, 8 CPUs and 64 GiB of RAM.
Record accelerator architecture and runtime pins for each test. A runtime
preflight or a kernel probe cannot substitute for native scientific execution.

The private learned sandbox is based on the copied ART Python 3.12 runtime,
with Torch 2.11.0+cu126. The completed COLMAP CASPAR/ONNX build was rebuilt for
SM80; the earlier SM86 build and wheel were retained. The A100 wheel SHA-256 is
`d1282aea0c5c394e9bf4cee5d3c45f05af9e4c6e39a5a8ee884a9d01e5f4ac09`.
`collect_native_libraries.py` follows the trusted compiled ELF dependencies,
includes ONNX providers and the cuDNN libraries they load dynamically, and
retains every needed SONAME as a regular file. The reviewed closure has 134
files, tree SHA-256
`2dc6a15db0f60613b75f07ec09cdb748c3fd35b4170a05c4552ea5128b88515b`.
It excludes the host glibc/loader, libpython and NVIDIA driver libraries.
Driver libraries enter through Singularity `--nv`; the original ART library
directory remains a fallback after the pinned closure.

The copied interpreter initially had an ELF `DT_RPATH` that loaded an older
gflags dependency before the explicit private closure. This caused a real
duplicate-flag failure. `allow_private_library_priority.py` changes only that
copied interpreter's dynamic tag to `DT_RUNPATH`, retaining the same search
string, backing up the old bytes and checking that the original interpreter
is untouched. The copied interpreter SHA-256 becomes
`a6595f087355323f5bdb769033834596d67df3826ede87829bc8dbf023e4b39a`;
operator configurations must pin those actual bytes. The resulting contained
runtime completed a genuine five-frame / 100-point CASPAR GPU solve on the
A100. The bounded 20-iteration probe returned a usable finite result with
1,000 residuals and `NO_CONVERGENCE`; it establishes working kernels and
linkage, not convergence or photographic reconstruction quality.

The first geolocation attempt then exposed an ONNX CUDA-provider requirement:
Torch loaded its bundled CUDA 12.6 runtime, which does not export
`cudaLibraryGetKernel`. The already installed conda CUDA 12.9.79 runtime does
export it. A separate sandbox replaces both the copied Torch runtime file and
the corresponding native-closure entry with SHA-256
`a8fe0bbc9beba7e2f751fcd30ccd7943073b5c2458752acf8a06f4541609960b`.
The resulting closure is
`b0338d850aa8d97a9a527adb4a7f209adb956ff914fc7f184741cffb5b311d89`.
The original sandbox and shared ART installation are retained unchanged.
Real native LoMa inference with those exact bytes produced 512 finite
keypoints and 512 x 1,024 descriptors on one retained photograph; the new
copied sandbox also passed the CASPAR kernel probe. The actual Torch-loaded
runtime file is explicitly pinned as the `cuda_runtime` operator asset.

Each learned native profile prepends
`python /opt/historic-learned/learned_entrypoint.py` to its fixed installed
entrypoint. The wrapper verifies the exact stage/configuration prefix and
starts the scientific child with a new mode-0700 home under the invocation's
private `/tmp`. It preserves the launcher's environment and does not expose
or write the host home. For geolocation only, the child home's
`.cache/colmap` links to the pinned embedded native model cache. This handles
COLMAP's use of `HOME/.cache/colmap` without changing a shared environment or
silently downloading replacement weights. A genuine contained probe verifies
the private home, cache target and unchanged parent environment.

The fixed container configuration paths are:

```text
/opt/historic-learned/original_sfm-operator-config.json
/opt/historic-learned/geolocalization-operator-config.json
/opt/historic-learned/dense_intrinsics-operator-config.json
```

After a genuine direct acceptance succeeds and active scientific runs release
the sandbox, `finalize_learned_runtime.py` can compress it with two CPUs using
Singularity 3.11-compatible SIF object commands. It requires the actual
successful result JSON, records source/configuration hashes and runs
`probe_learned_sif.py` inside the resulting immutable SIF. The probe exercises
the embedded launcher, exact stage imports, CUDA capability gates, private
home/cache and before/after installation pins. It performs no photographic
inference and records only the stages whose contained probes actually passed.

```bash
python3 scripts/historic_reconstruction/finalize_learned_runtime.py \
  --build-root /absolute/private/learned-sif-build \
  --acceptance /absolute/actual-original-sfm-acceptance/result.json \
  --acceptance-report /absolute/actual-original-sfm-acceptance/outputs/research-report.json \
  --probe scripts/historic_reconstruction/probe_learned_sif.py
```

Run this within the existing authorized allocation and provide a private build
directory prepared by `stage_learned_runtime.py`. Each subsequent WebHDP
installation normally requires the corresponding direct stage acceptance and
the immutable SIF verification. Native execution and independent downloaded
artifact audits are separate gates. The report index refresh helper preserves
the date and hardware of each receipt when combining the two GPU sessions.

For an explicitly authorized test-only runtime revision, the finalizer's
`--allow-runtime-revision` option retains a prior direct result with its exact
old/new pin differences and `runtime_pins_match: false`. That earlier result
does not count as final-image execution. The isolated native installation can
then test the verified SIF, and a fresh completed native run plus independent
artifact audit is required before any PASS claim. This avoids repeating full
scientific inference solely as an installation prerequisite while preserving
the distinction between earlier evidence and current execution.

The resulting learned SIF is
`8690e9cb185f3f546d99e1261f72041ac43c9d9a43755afbf4ec6fe23d50a5e0`.
Its contained preflights passed for original SfM, geolocation and dense
intrinsics. The native original SfM run registered all 11 input
photographs with 6,758 points and mean reprojection error 1.150379 px. Native
geolocation registered five historic
images and sixteen panorama views, with 5,766 points and mean reprojection
error 1.239544 px. Both used component version 1.0.1 on the A100 allocation.
Their actual remote requests, staged input bytes, downloaded artifacts and
full runtime pins were checked against the final-image preflight. These
numbers describe the final image's native runs.

### Dense fixture and conservative fit outcome

The four-panorama church fixture is sufficient for geolocation, but its
panorama viewpoints did not satisfy the unchanged dense stage's viewpoint
selection rules for any historic image. That initial run correctly failed
with “no real correspondences”; it is retained as a negative result rather
than counted as dense inference success.

A separate fixture adds four real panoramas near the inferred historic
camera positions. Those positions were transformed using the retained local
ENU reference; they are reconstruction estimates, not surveyed ground truth.
The new panorama coordinates and orientations come unchanged from the source
metadata API. Discovery used four bounded location queries and four metadata
lookups, followed by the original zoom-3 downloader. The eight explicit IDs
are pinned in seed SHA-256
`69ba4e8b1c8f67e8b1cf3f620b49415cf279b63a215e6a68267c257d20a22d43`.
The separate operator configuration permits eight panoramas within a 250 m
acquisition margin, with 1,024-pixel cubemaps and two download workers. These
are acquisition settings; the dense 20-degree viewing-angle limit and
minimum point support remain unchanged. The frozen SIF and its installed
four-panorama seed were not changed.

The expanded direct geolocation run used read-only seed/configuration
overlays and produced the independently audited bundle
`f676148fce5588f67f66556e663efb5181eb471a6381237d27b86fb9913c9c89`:
five historic images, 32 panorama views, 7,039 points, and mean reprojection
error 1.224137 px. Actual upstream viewpoint selection then found between two
and five eligible panoramas for each historic image. The input photographs,
GPS metadata, generated masks and panorama ENU metadata were independently
checked against their retained sources.

Direct dense execution on that exact bundle completed in 107.3 seconds with
6,037 raw correspondence observations, five successful fits and 3,915 fit
inliers. All five scientific decisions were `unchanged`: two images failed
the minimum nonplanarity requirement, while the other three failed focal
stability across spatial folds or camera models. The original thresholds
were retained. The component reports `executed_no_accepted_updates`, zero
changed camera intrinsics and five unchanged cameras, validates and retains
the original finite models, and writes no fabricated calibrated model.
The output bundle SHA-256 is
`0d265daceb82af0e8898a8c4a35f60aa0ff1bee0dfc4f61c2c85ceabb3359974`.
Its NPZ correspondences, successful-fit arrays and JSONL decisions remain
available for inspection. An independent audit decoded those arrays and
verified the retained model, photograph and GPS bytes plus unchanged camera
parameters. This establishes executed matching and fitting;
it does not establish improved camera calibration or ground-truth accuracy.

Keep fixture provenance, source metadata, visual checks and execution
receipts in private operator storage. The native dense run used the expanded
direct geolocation bundle above as its input, rather than the four-panorama
native geolocation result.
Independent checks reproduced 6,037 observations, five successful fits and
3,915 inliers, with zero accepted updates, zero changed intrinsics and five
unchanged cameras. Both downloaded artifacts, the physically staged input,
final SIF/runtime pins and the real browser report download were verified.
The accepted-update branch remains unexercised by this fixture.

Isolated acceptance covered 11 historic and eight community components,
23 recipes, and 43 checked artifact downloads from 11 native HPC cases. The
results cover their respective fixtures and installed runtimes.
