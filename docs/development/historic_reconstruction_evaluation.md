# Historic reconstruction pipeline evaluation

Evaluation date: 6 November 2026. Source evaluated: the supplied
`historic_reconstruction_pipeline-master` archive. It contains 51 Python files,
265 data files and no source photographs. All Python files parse successfully;
this is not evidence that their imports or scientific stages run. The archive has
no Git metadata, package manifest, dependency lockfile, test suite or top-level
licence declaration. The VGGSfM submodule directory is empty.

The exact evaluated Python package tree digest is
`cb8266490126887616c022f983803141e9ec393522aaab249d167e25c8943a6a`. The
[retained inventory](historic_reconstruction_source_inventory.json) records all
45 package files with sizes and individual SHA-256 values. This is the
same `tree_sha256` algorithm used by the research adapter. The archive has no Git
revision; no revision was inferred from its folder name or timestamps.

## Assessment

The repository contains useful scientific processing code and a substantially
implemented scene-based geolocalization workflow. It is a research workspace,
not a directly installable HDP component. Wrapping the shell scripts unchanged
would retain machine-specific mounts, hidden dependency forks, missing weights,
and successful exit codes for some failed scenes. WebHDP therefore needs two
explicit execution paths:

1. Portable HDP components with bounded inputs, stable artifacts and CPU-testable
   preprocessing, pairing, sparse reconstruction and control-point alignment.
   Conventional COLMAP dense reconstruction is a separately selectable stage.
   These implement the transferable workflow using installed scientific tools;
   they do not claim to reproduce LoMa, Doppelgangers++, RoMa or MVSAnywhere.
2. Fixed adapters for the supplied research implementations, enabled only with
   an operator-installed, checksummed source/dependency/weight environment. The
   original neural stages retain their identities and cannot silently fall back
   to the portable algorithms.

New WebHDP code can be committed separately from upstream source, data and model
weights. The supplied snapshot does not establish permission to redistribute
that source or weights. The integration consequently consumes an explicit local
installation and does not vendor or relicense the archive. This records an
observed packaging fact, not a determination of third-party licence rights.

## Actual workflows and entrypoints

Paths below are relative to the supplied source archive.

| Stage | Actual entrypoint and contract | Evaluation |
| --- | --- | --- |
| Image preparation | `preprocess/prepare_images.py`: `--image_dir`, optional `--image_list_path`, `--output_dir`, `--image_size`; JPEG files | Intended EXIF transpose, resize and metadata removal. It opens relative list entries without joining `image_dir`; creates no output directories; accepts `None` output; only converts RGBA, not palette/CMYK modes; basename/suffix collisions are unhandled. Reimplement as deterministic preparation with an original-to-prepared manifest. |
| Stereo-card detection | `preprocess/stereo_detection.py`: image directory/list → stereo filename list | CPU SIFT cross matching and RANSAC between left/right halves, disparity consistency and feature spread. Useful optional preparation feature. Dummy filename is appended for the author's HLoc parser; remove this compatibility fiction from HDP reports. |
| Semantic masks | `preprocess/generate_segmask.py`: image directory/list → PNG masks, optional NPZ labels and JPEG visualization | Real Mask2Former ADE20K inference, pretrained `facebook/mask2former-swin-large-ade-semantic`. Large postprocessing is capped then labels resized nearest-neighbor. Model and processor are downloaded unless cached. Per-image read errors are printed then skipped; HDP must require every declared output. Semantic skip checks `.npy`, while writes use `.npz`. A mask-only rerun still performs inference before skip. Visualization also needs MMSeg/MMEngine, absent from active Docker installation. |
| GPS pair candidates | `matching/gps_prior/pairs_from_gps.py`: JSON mapping names to `{lat,lng}` → whitespace pair list | CPU Haversine neighbor/radius selection. Random mode is unseeded and pairs may be duplicated in opposite directions. Coordinate schema differs from geolocalization's `[lat,lon]`. The portable component should normalize schemas and make selection deterministic. |
| Historic sparse reconstruction | `reconstruction/pipeline.py`: `--image_dir`, `--image_list_path`, `--workspace_path` | Executes stereo, masks, local/global feature extraction, retrieval pairing, matching, COLMAP database import, DG rejection and incremental mapping. Uses custom HLoc `mask_dir`/`stereo_list_path`, `loma_inloc`, `megaloc`, `loma`, modified MASt3R DG heads, and modern pycolmap CASPAR interfaces. Default DG checkpoint is an absolute author's path. Parameters live in a module dictionary. HDP adapter supplies the checkpoint and thresholds explicitly. |
| Earlier matching prototype | `matching/recon_pipeline.py`: image/workspace directories | Do not expose. Calls nonexistent `utils.get_image_list`, writes a matches filename then reconstructs from a different hard-coded `matches_sparse.h5`, carries author-specific sys.path inserts and TODOs. |
| GSV geolocalization | `geolocalization/geoloc_pipeline.py`: image directory/list, workspace, exactly one GPS JSON or bounds polygon, optional masks/stereo lists | Most complete workflow: stereo/masks → MegaLoc → scene clustering → panorama search/download/cubemaps → per-scene COLMAP databases/rigs → optional AnyCalib → LoMa extraction/matching/verification → DG → GSV triangulation and prior-based mapping → historic registration → diagnostic report. Local ENU frame retained in per-scene `georef.json`. Needs network access for GSV acquisition. |
| Dense intrinsics refinement | `geolocalization/dense_intrinsics.py`: `--workspaces`, image/panorama paths and geoloc options | Operates on completed scene workspaces with `report_<dg>` markers. RoMa v2 dense correspondences, geometric fitting, principal-point stability/tier decisions and fixed-camera retriangulation. Outputs `*-dense_intrinsics/intrinsics/{fits,cameras}.jsonl`, pruned database and `models_geolocalized`. Requires RoMa/DINOv3 cache and full GSV source context. |
| Keypoint refinement | `matching/refine_keypoints/refine_model_keypoints.py`: model/image/output paths, config, max tracks, optional BA | Real VGGSfM track refinement followed by optional bundle adjustment. VGGSfM is not included; explicit config path avoids its CWD-dependent default. Output is refined COLMAP binary model. |
| Dense dataset preparation | `reconstruction/prepare_colmap_model.py`: model/image/output paths | Undistorts images, regenerates segmentation, computes view splits and 4–96 percentile bounds, writes TSV/YAML and NeRF-baselines metadata. Several choices are collection-specific (`fortepan`, `nerfw`), and it imports GPU segmentation for a seemingly geometric task. Treat as research dataset preparation, not a general mesh generator. |
| MVS tuple generation | `meshing/generate_mvs_tuples.py` | Useful `compute_covisibility_efficiently` function, but script scans a hard-coded author's directory and overwrites CWD `mvs_tuples.txt`. No reusable CLI. Pair IDs, dataset naming and tuple filename must agree with the installed MVS configuration. |
| MVSAnywhere depth/fusion | `meshing/mvs_anywhere.py` + `meshing/colmapw_dataset.py` | Genuine depth inference, cached depths, optional TSDF mesh. Requires external `mvsanywhere`, model/data YAML and checkpoint. `colmapw_dataset` is imported as a sibling absolute module. Model setup calls `.cuda()` unconditionally despite a misleading CPU precision branch. Covisibility tuples are expected, not generated by the active code. |
| Visual coarse geolocation | `geolocalization/visual_geolocation.py`: image directory/list → JSONL | PLONK implementation exists, requires external `plonk` and model weights, forces CUDA, and outputs approximate GPS hypotheses. It is not a substitute for surveyed coordinates or GSV registration. Not part of the default integration pipelines. |
| Earlier/manual geolocation | `pipeline_geolocation.py`, `geoloc_pipeline_manual_loma.py`, `localize_pano_in_historic.py`, `manual.py`, scripts/notebooks | Alternative experiments and manual operations with fixed paths and collection assumptions. Preserve as source context, not competing production entrypoints. |
| Textured OSM buildings | README advertises `buildings/building_pipeline.py`, chunk assembly/upload and `run_building_pipeline.sh` | Those paths are absent. Some exploratory OSM scripts/notebooks exist; they do not supply the documented building pipeline. No component should advertise this missing capability. |
| NeuS/Neuralangelo and novel views | README outline; `reconstruction/render_priors/__init__.py` is empty | No complete training/rendering pipeline in the archive. Do not expose invented jobs or generated stand-in geometry. |

## Dependency and execution findings

The source Dockerfile is a broad development environment, not a reproducible
component image. It installs Ceres `master`, COLMAP `main`, numerous unpinned Git
repositories and Python packages, custom CUDA kernels and graph libraries. Some
version choices are internally different (for example CUDA 12.8 PyTorch with
CUDA 12.6 graph-wheel URLs). This evaluation does not assume these combinations
build successfully. Its last stage remains the full development builder and
never installs the historic package. HLoc, DG and several model projects are
supplied through external mounts rather than a resolved image dependency set.

The Compose file binds the author's project, data, weights and home caches,
uses host networking and an unconfined debugger profile. These are inappropriate
as the HDP input/output contract. Slurm scripts use site-specific partitions
(`alpha`, `capella`, `barnard`), bind variables, SIF versions and absolute
Python/Intel preload paths. Draco allocation must instead use its observed
`gpu`/`gpu-test` partitions and the existing WebHDP/HPC-Link allocation boundary.

Keep installed source roots and model checkpoints immutable, hash their exact
contents, and record each invocation's input/output fixity. The original source
cannot be described as pinned to a Git commit because the supplied archive has
none. A content digest identifies the exact installed archive package. Runtime
preflight must detect missing custom HLoc arguments/configurations and missing
pycolmap LoMa/CASPAR support before scheduling long scientific work.

The upstream orchestration has useful lock files, per-step completion markers,
per-scene databases and atomic JSON writes. However, markers encode only that a
step once finished: they do not bind input or parameter hashes. Reusing a workspace
after changing imagery, parameters or dependency versions can therefore reuse
stale work. HDP runs use isolated input copies, and dense-intrinsics continuation
clears only its own derived stage outputs in that copy. It must never mutate a
user's source workspace.

Geolocalization catches per-scene `RuntimeError` and logs completion even when
no scene reconstructed. Its `step_export` is a log-only TODO. The HDP adapter
requires decoded nonempty reconstructed models after the child process exits,
and describes outputs as ENU model plus georeference metadata, not a completed
latitude/longitude camera export. A successful process alone is insufficient.
Some upstream caches use `pickle.loads` and `numpy.load(allow_pickle=True)`;
caller-provided executable/pickle/weight payloads must never be loaded as caches.

## HDP contract and pipeline mapping

| HDP responsibility | Representation |
| --- | --- |
| Scientific input collection | Staged file list or a confined ZIP containing `images/`; prepared filenames mapped to original names/hashes. |
| Stage handoff | Typed file outputs: dataset ZIP, reconstruction ZIP, mesh/cloud, JSON report and transform. ZIP extraction rejects traversal and symlinks. |
| Parameters | Bounded numerical/enum/boolean fields; executable paths, dependency roots, raw shell commands and arbitrary CLI flags are operator-only. |
| CPU pathway | Preparation, pair generation, sparse COLMAP when CPU supported, supplied-control alignment and artifact validation. |
| GPU pathway | Explicit profile with one Draco GPU; neural upstream stages preflight CUDA and dependencies; conventional COLMAP dense stage uses its own implementation. |
| Provenance | Source/dependency/weight pins; original and prepared image hashes; parameter values; scientific counts/errors; retained COLMAP and frame metadata. |
| Result presentation | Downloadable reports and ZIPs, PLY/GLB where actually generated, clear scientific method names; no fabricated mesh on failed reconstruction. |
| Install readiness | Components registered with manifests and pipelines; external research profiles fail clearly until matching runtime is installed. |

Useful saved pipelines are image preparation/assessment; preparation → pairs →
sparse reconstruction; reconstruction → dense fusion; reconstruction → supplied
control alignment; and research segmentation, original SfM, GSV geolocalization,
keypoint refinement, dense-intrinsics continuation or MVS fusion as individually
reviewable jobs. A research segmentation → portable reconstruction chain is valid
only when the portable feature extractor actually consumes the produced masks;
otherwise the masks are retained evidence and must not be claimed to influence
that reconstruction.

## Verification boundary

Without a GPU, verify real image preparation and EXIF handling, stereo fixtures,
coordinate validation and pair determinism, archive confinement, checksum drift,
parameter boundaries, actual CPU COLMAP sparse processing when installed,
control-transform residuals, output decoding, component registry/pipeline
bindings and visible installation states. Stub processes are useful for command
routing/error propagation tests but do not demonstrate neural inference.

With Draco, inspect the allocated GPU and CUDA runtime before work. A new
scientific acceptance run needs real overlapping photographs, recorded input
hashes, actual extraction/matching/mapping logs, decoded camera/point artifacts
and independent reprojection/registration measurements. Dense or neural-stage
acceptance additionally needs genuine generated depths/masks/refined models and
method-specific evidence. Allocation submitted, allocation pending, GPU detected,
process started and scientific output verified are distinct states.

The implementation/test report must list which of these states were actually
observed. Nothing in this evaluation establishes that the original custom
research environment or all its checkpoints were available on Draco. No push,
production install or deployment is part of this work.
