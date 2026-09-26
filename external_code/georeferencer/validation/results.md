# 3DGeoRef reference-workflow validation

Validation date: 2026-09-26. The component was validated for WebHDP
`v0.1.0-alpha.2`, then installed and tested through the deployed application.

## Scope

The supported workflow aligns a static GLB against a supplied GeoTIFF on an HPC
GPU and then renders previews. Automatic Gemini/Mapbox geolocation and absolute
elevation assignment are disabled. The tests do not establish survey accuracy
or automatic location discovery for arbitrary heritage models.

The GPU checks use reproducible textured fixtures with known placement at 0°,
31°, 90° and 187°, projected northern/southern UTM and ETRS89 coordinates,
Unicode paths, a distant model origin, and a grayscale reference. A deliberately
unrelated reference and a large architectural model with a nearly uniform roof
exercise rejection. The latter remained below the consistent-match threshold,
even against a render-derived reference; its thresholds were not weakened to
force an alignment.

The additional relief case has 4,225 vertices and 8,192 triangles with varying
height. It exercises non-flat geometry and the complete preview pipeline.

## Artifact identity

- Pinned 3DGeoRef revision: `e50e4562b43c0b105d77e417d01fedb5139529a6`.
- Upstream container index: `sha256:b24eceb634247682d727a9e7f693271d033fa7130ff4cef974cde202ef2d5480`.
- Upstream amd64 manifest: `sha256:a3a050262e70fe940b715845aefc2c0ff075d9a02c7eb33c06b9822369f65f6d`.
- Upstream SIF SHA-256: `f3fb1cd3a28be7028bdec97fd0ad87ba59b27e24aef4018a33af079e37a50e47`.
- LoFTR outdoor checkpoint SHA-256: `21f5bec5968178e8bc8b7633441836fe5de4f47d861dd2cd7dc38e271b0479ec`.
- Candidate: `georeferencer-1.0.0-reference.sif`.
- Candidate SHA-256: `f4505f194cc3dfc4fe016ddcf818d67ffae500309b1674299dd4383635225f9b`.

The image contains a CUDA 12.1 PyTorch 2.5.1 runtime, matching torchvision,
the pinned renderer, offline model weights, and file-level provenance.
Unused duplicate GPU packages and the DIM checkout are removed. The built image
fits within HPC-Link's default 10 GiB download limit. Its wrapper hashes match
the repository sources; no candidate bind is needed for the final acceptance run.

## Automated regression checks

- Backend: **768 passed, 1 skipped**.
- Component geometry/input/failure tests: **26 passed**.
- Frontend georeferencing/constructor tests: **7 passed**; production build passed.
- Component manifest validation: no failures. As with Mesh Optimizer, no small
  manifest-embedded GPU smoke fixture is declared; use the supplied allocation
  acceptance scripts for workload validation.

The focused tests cover inlier selection, clustered/duplicate/mirrored/unrelated
matches, footprint coverage, pixel-centre and axis conventions, distant origins,
shape preservation, binary GLB preservation, CRS and image constraints, symlink
escapes, disguised VRT files, missing/ambiguous references, failed-run cleanup,
record isolation, installation gating and single-artifact file-list bindings.
These component checks also have a dedicated CI job.

## GPU alignment results

These results come from the final image through fresh native WebHDP sessions on
an NVIDIA RTX A5000. Each positive case retained the original GLB binary payload.

| Case | Result | Centre error | Heading error | Inliers |
|---|---|---:|---:|---:|
| North-aligned reference | Accepted | 0.0140 m | 0.0061° | 2,300 |
| 31° rotation | Accepted | 0.0176 m | 0.0043° | 1,444 |
| 90° rotation / ETRS89 | Accepted | 0.0143 m | 0.0002° | 2,452 |
| 187° rotation / southern UTM / Unicode path | Accepted | 0.0147 m | 0.0015° | 2,191 |
| Distant source origin | Accepted | 0.0134 m | 0.0025° | 2,251 |
| Grayscale reference | Accepted | 0.0208 m | 0.0187° | 67 |
| Textured 3D relief | Accepted | 0.0148 m | 0.0047° | 1,833 |
| Unrelated reference | Rejected | — | — | — |
| Nearly uniform architectural roof | Rejected | — | — | — |

These centimetre-scale errors describe controlled fixtures at known resolution,
not an accuracy guarantee for real-world geolocation. All seven output GLBs also
passed Khronos glTF Validator `2.0.0-dev.3.10` with **zero errors and warnings**.

Two fresh application sessions completed all native acceptance assertions:
**7 successful records, 2 correctly rejected records, 7 GLBs, 7 coordinate reports,
7 alignment overlays and 35 Fast Renderer previews**. All 42 PNGs fully decoded;
rendered previews contained visible geometry. Same-basename inputs remained
isolated, all derived files were downloaded and registered to the correct `.hdpc`
record, and every original input hash was unchanged. Rejected records retained
only their original model/reference files and produced no previews.

## Deployed workflow acceptance

Three additional records (flat, rotated with a Unicode filename, and non-flat
relief) completed through public HTTPS, Celery and HPC-Link. Each produced a
validated GLB, coordinate report, alignment overlay and five previews. An
unrelated reference was rejected without derived artifacts. Original checksums
and binary GLB payloads were preserved. Browser selection, report downloads,
Dropbox mirror integrity and private-file access controls passed. Raw deployment
evidence remains outside the public repository.

## Reproducing GPU acceptance

Generate fixtures with `fixtures.py`, run `run.py` in a held GPU allocation,
and use `native.py` for the full application pipeline. The latter creates a fresh
Flask/SQLite database and `.hdpc` session, stages same-basename records through
HPC-Link's adapter, executes the candidate outer runner over SSH, downloads and
registers artifacts, and checks coordinates, preview counts and preserved inputs.
It bypasses the deployed HTTP gateway so the installed application is untouched.

`from_render.py` supports controlled checks with additional models. Such a
render-derived reference is a transformation test, not independent geographic
ground truth. Keep private input models and raw execution evidence outside the
public repository.
