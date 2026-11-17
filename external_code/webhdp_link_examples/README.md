# WebHDP-Link reference processors

These three administrator-installed HDP Components execute real local work
through WebHDP's native `local_cli` adapter. They exercise the same Link upload,
authorization, parameter validation, queue, run status, and artifact download
contract that larger components use. They require no HPC login from a client.

| Pipeline | Input | Actual output | Boundary |
|---|---|---|---|
| Photo set preparation | JPEG, PNG or WebP photographs | Decoded image inventory, source SHA-256 values, contact sheet, COLMAP/Reprojector handoff | Does not estimate camera poses or generate a 3D reconstruction |
| HMSM piano-roll digitization | Carrier scan | Real HMSM candidate notes, Standard MIDI File, source/track previews, checksummed evidence ZIP | Exposes the generic 65-note study profile; historical interpretation requires review |
| 3D model preparation | Triangular, geometry-only OBJ | Centered/scaled glTF 2.0 GLB, topology counts, metadata template, original plus outputs in a checksummed ZIP | No textures, arbitrary polygons, physical-scale inference, Zenodo upload or publication |

The images in `fixtures/` are synthetic capture illustrations. The roll fixture
is the existing WebHDP HMSM synthetic scan and contains seven gates. Its pitches
in scan order are 60, 64, 67, 64, 60, 55 and 48. The OBJ is a synthetic closed
tetrahedron. These prove software behavior without claiming real collection
accuracy, photogrammetric quality or publication acceptance.

## Install and register

Install `requirements.txt` in the WebHDP task worker's Python environment. Only
Pillow is added by the photo/reference wrapper. The mesh processor uses Python's
standard library. A working HMSM Studio installation with its own environment
is required for piano digitization; install the pinned HMSM requirements using
that project's documented setup. The wrapper uses its real CLI and existing
optical algorithm, rather than copying its scientific implementation.

In an application context, call:

```python
from external_code.webhdp_link_examples.seed import seed

publications = seed(
    app.native_pipeline_service,
    hmsm_source="/srv/processing/interactive-hmsm",
    hmsm_python="/srv/processing/interactive-hmsm/.venv/bin/python",
)
```

Alternatively, set `WEBHDP_LINK_HMSM_SOURCE` and `WEBHDP_LINK_HMSM_PYTHON` in the
operator environment. The returned publication records are ready for the Link
administrator service. Entry points use absolute administrator-selected paths.
The runner hash and HMSM processor source hash are bound at registration and
checked at execution. Identical registration is repeatable; changed code needs
a deliberately new component version. The local interpreter and its dependency
environment must also remain operator-managed and stable.

The YAML files are valid portable manifest templates. Use `seed()` to resolve
their executable paths before registration. An unconfigured piano template
fails with a runtime explanation. No browser parameter can choose an executable,
HMSM checkout, filesystem destination, network address, or secret.

Inputs are size-bounded and decoded before processing; photographs are bounded
to one frame and 40 million pixels. The example OBJ parser rejects nonfinite
coordinates, invalid indices, degenerate triangles and external material/texture
references. It counts open, nonmanifold and inconsistent-winding edges without
claiming a full geometric validator. Coordinates are transformed by a recorded
uniform scale; originals remain in the downloadable package. Repository metadata
deliberately awaits the user's creator/rights review.

HMSM runs with a small inherited environment and no inherited WebHDP credentials.
Its private temporary native project is removed after copying the public MIDI,
previews, and a report containing selected scientific fields. Public artifacts
contain source names and hashes, not server paths. The evidence ZIP includes
SHA-256 hashes for each deliverable. Local CLI execution is trusted operator code,
not a sandbox for third-party code. Install untrusted or resource-heavy processors
as isolated container/HPC components instead.

## Extend to full photogrammetry

The reference Reprojector checkout provides:

- `python/reprojector/recipes.py`: strict versioned recipes for camera grouping,
  features/matching, incremental/global SfM, dense fusion, meshing and QA.
- `python/reprojector/reconstruction.py`: the genuine COLMAP worker, immutable
  stage receipts, source fixity, camera calibration, dense geometry and bundle QA.
- `scripts/reconstruction_worker.py`: CLI entry point accepting an operator
  workspace, resolved recipe and optionally a pinned container.

Create a distinct versioned HDP Component around that worker. Stage the Link
photo inputs into its job root, resolve a complete operator-approved recipe,
declare parameter limits, and expose only scientific choices through Link.
Install and validate COLMAP/CUDA and the worker's pinned dependencies centrally.
Bind the component to WebHDP's HPC-Link execution profile; external applications
continue to use the same Link HTTP contract. Collect the real reconstruction
bundle with its source/calibration/mesh hashes and QA evidence. Never label the
photo-preparation component as successful reconstruction. Source photographs,
calibration and mesh must retain their shared coordinate convention; physical
accuracy requires independent evidence.

For full HMSM profiles and linked interpretation/reconstruction steps, the
existing `hmsm_scan_digitizer`, `hmsm_midi_interpretation`, and
`hmsm_midi_reconstruction` container components remain the richer integration.
Their native manifests document model snapshots, optional classifiers and
evidence ledgers. A Link publication can point to an approved version of one of
those pipelines when its runtime is installed.

## Validation

```sh
python scripts/validate_hdp_components.py external_code/webhdp_link_examples
WEBHDP_LINK_HMSM_SOURCE=/srv/processing/interactive-hmsm \
WEBHDP_LINK_HMSM_PYTHON=/srv/processing/interactive-hmsm/.venv/bin/python \
python -m pytest tests/test_webhdp_link_examples.py -q
```

Tests inspect actual decoded photo data, GLB buffers and normalized coordinates,
topology findings, ZIP fixity, rejection of unsupported inputs, executable hash
pinning, and a genuine native CLI invocation. With HMSM configured, the test
independently reads the generated MIDI and verifies all seven expected pitches.
Without that runtime, the single HMSM integration test is explicitly skipped.
