# Genuine WebHDP-Link photogrammetry

This operator-installed HDP component runs the existing Reprojector reconstruction
worker through WebHDP's native `hpc_link` adapter. The external application uploads
photographs to WebHDP and starts an allowlisted pipeline. WebHDP owns the Slurm
allocation, staging, execution, status and artifact retrieval. There is no SSH
connection or HPC credential in the integrating application.

The scientific stages are real COLMAP SIFT extraction, exhaustive matching,
incremental structure from motion, image undistortion, GPU geometric PatchMatch
stereo, dense fusion and Poisson or Delaunay meshing. A failed reconstruction
returns a failed run; this component never substitutes generated geometry.

## Inputs and outputs

Upload 3–30 overlapping JPEG or PNG photographs with unique filenames. Unrelated
pictures, low overlap, transparent objects and textureless surfaces may fail
registration. Client parameters are limited to `max_image_size` (640–2400, default
960) and `mesher` (`poisson` or `delaunay`). Neither executable paths nor shell
fragments are accepted from the request.

The fixed quality gate requires at least three registered photographs, at least
75% coverage and mean sparse reprojection error at most four pixels. It cannot be
overridden through the public interface. Reprojector validates the complete
native bundle and its checksums before any output is published.

Returned artifacts:

- `model.ply`: the actual COLMAP reconstructed mesh.
- `model.glb`: the same geometry converted to glTF 2.0, with its reconstructed
  coordinates preserved; textures are not baked.
- `fused.ply`: the measured dense point cloud.
- `reconstruction-preview.png`: three orthographic views of measured cloud
  points, oriented by a recovered camera; the outer 1% bounds may be outside the
  preview viewport.
- `reconstruction-report.json`: registration, reprojection error, mesh and cloud
  counts, input SHA256, runtime versions, executed settings and native evidence
  hashes. Successful geometric depth generation demonstrates CUDA dense stereo.
- `reconstruction-package.zip`: these outputs plus calibrated source/rectified
  camera models, rectified images, geometric depths, rectification mapping and a
  per-file SHA256/size inventory.

The public package is explicitly a *derived scientific package*, not a replacement
for the complete Reprojector native bundle. Original uploaded photographs and full
native command logs/receipts remain in the private reconstruction workspace. The
package references original captures by filename, dimensions and SHA256. Internal
filesystem paths, source code and scheduler/account identifiers are not included
in its public report. Physical scale and independent geometric accuracy remain
unmeasured until external evidence is supplied.

## Operator installation

The trusted host profile is intended for an existing operator-maintained scientific
environment. It provides no container sandbox. HPC-Link loads and checksum-verifies
the installed manifest and ignores caller-provided executable profiles. The fixed
entrypoint unsets inherited Python/Intel library variables, preserves the
scheduler's GPU visibility and executes only the pinned component. Input files
must be staged below the allocation input directory; declared artifacts must stay
inside the unique invocation output directory.

Requirements are Python 3.10 or later, NumPy, SciPy, Pillow, trimesh and a CUDA
COLMAP executable supporting the seven stages above. The exercised Draco runtime
has Python 3.12.13, COLMAP 3.13.0 with CUDA, NumPy 2.4.4, SciPy 1.18.0, Pillow
12.2.0 and trimesh 4.12.2. Keep the environment read-only to regular users and retain
an environment package inventory alongside deployment records. The component pins
the COLMAP executable, its own runner, and the exact ten-module scientific source
closure with SHA256; external dependency versions are recorded in the report.

Prepare the package locally with `seed.prepare_installation(destination,
reprojector_source=local_checkout, **trusted_config)`. It copies only the explicitly
listed scientific modules and writes `component.json`, `manifest.json` and file
checksums. It does not copy whole repositories, tools, caches, development notes,
credentials or agent configuration. Deploy this package to the registered
`<HPC_APPS_ROOT>/webhdp/components/link_reprojector_photogrammetry/1.0.0` directory
using the administrator's existing installation mechanism. The installed
HPC-Link runner must support `trusted_host_component`.

The required trusted configuration keys are `runtime_python`, `runtime_colmap`,
`remote_component_root`, `colmap_sha256`, `reprojector_source_sha256`; optional
keys are `partition` (default `gpu`) and `gpu_type`. None are public parameters.
`prepare_installation` computes and returns the source digest with the other
settings. `seed(native_pipeline_service, **trusted_config)` imports the component
and fixed pipeline version, and returns `[publication_payload]` for the Link
administrator publication service. Pipeline identifier: `link_photogrammetry`;
public publication identifier: `link-photogrammetry`.

The publication requests one centrally managed GPU for 12 hours, explicitly keeps
the running allocation after completion, and permits reuse by the same owner
under the same resource policy. Pending allocations still release on queue
timeout/failure. The component refuses to run outside a Slurm allocation. Changing
the runner, source or executable requires a new reviewed immutable version.

## Evidence and validation

`tests/test_webhdp_link_photogrammetry.py` covers public parameter boundaries,
actual native component/pipeline registration, minimal installation inventory,
runtime checksums, allocation enforcement, input confinement/fixity and preview
rendering. An optional test validates and packages an authentic existing
Reprojector bundle when `WEBHDP_LINK_REPROJECTOR_SOURCE`,
`WEBHDP_LINK_REPROJECTOR_PYTHON` and `WEBHDP_LINK_REPROJECTOR_BUNDLE` are set.
That test is deliberately described as retained-data packaging, not a new GPU run.

For a new live proof, upload the 11 original ETH3D Statue photographs from the
existing Reprojector `COLMAP-statue-all-views-0.11.reprojector/reconstruction-evidence/original-captures`
directory (`DSC_0490.JPG`–`DSC_0500.JPG`, 6048×4032), and request 960-pixel processing.
These are real photographs from the [ETH3D benchmark](https://www.eth3d.net/datasets),
not the synthetic contact-sheet fixtures of the separate photo preparation example.
Use the returned input hashes, native run, remote component invocation, successful
quality report and independently decoded PLY/GLB/ZIP artifacts as evidence of the
new run. Do not use the prior reconstruction to claim new processing occurred.

`verify_outputs.py --artifacts <download-directory> --original-captures <inputs>
--run-record <saved-Link-run.json> --output <verification.json>` independently
decodes PLY/GLB geometry, COLMAP camera/point records and geometric depth maps;
recomputes the mean sparse reprojection error; and checks API artifact, package
and original input hashes. It imports neither the reconstruction worker nor its
exporter. The saved evidence is sanitized and contains no internal paths. The PNG
preview must also receive a visual review; numeric checks initially mark that
review pending.
