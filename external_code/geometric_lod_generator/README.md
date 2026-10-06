# Geometric LOD Generator

Version 1.0.2 produces three guarded CPU Blender
reductions. This installable component is separate from Linked Open Data
generation and the HPC mesh optimizer. No HPC allocation is needed.

## Input and outputs

Supply one static, self-contained GLB with embedded resources and one scene.
Animations, skins, morph targets, external textures/buffers, unsupported glTF
extensions, and point/line primitives are rejected with an export instruction.
Empty, non-finite, or entirely degenerate surfaces fail before results are
registered. The shared GLB preflight is bounded and does not replace an
independent glTF validator.

The response contains `lod_high`, `lod_medium`, `lod_low`, and `analysis_report`.
`lod_preview` aliases the medium output for existing bindings. Four unique
artifacts are registered. Every invocation uses a new output directory, including
retries and records with the same basename. Caught failures remove partial outputs.
The source is read-only, its SHA-256 is checked again before success, and the
report stores source/output hashes and sizes.

| Parameter | Default | Effect |
| --- | --- | --- |
| `target_ratio` | `0.5` | Medium fraction of original triangles; strictly between 0 and 1. High targets its square root and low its square. |
| `max_relative_error` | `0.001` | Maximum sampled surface displacement relative to each mesh's world-space bounding-box diagonal; strictly between 0 and 0.1. |

Targets apply to each mesh. Levels are processed from high to low, and exported
scene triangle counts are independently compared with the report. The ladder
must be non-increasing. If reduction violates the error limit or cannot simplify
further, the preceding accepted geometry is retained. Consequently levels can
be identical and a target is not a guarantee. Retention is recorded per mesh
with its reason, requested budget, accepted level's `sampled_error`, and limit.
`candidate_sampled_error` records an attempted reduction separately, including
rejected candidates; it is absent (`null`) when no finite candidate was measured.
Every material group's world-space surface area must also remain within 2.5%
of the original. This guards overlapping surfaces and small material groups
that nearest-surface distance alone cannot distinguish.

Error is sampled in both directions against the original surface, using all
vertices, triangle edge midpoints, and triangle centroids. This is a conservative
sampled check, not a continuous Hausdorff-distance guarantee. It measures geometry,
not texture appearance. Mesh instances are copied independently; meshes are not
joined, welded, or remeshed. UV layers, colors, normals, tangents, embedded
textures, and supported material graphs pass through Blender's importer/exporter.
Missing glTF default materials are made explicit in a temporary import copy.
Invalid exported tangent lengths are normalized. Zero directions at degenerate
UVs receive a deterministic perpendicular to the normal with preserved
handedness, and `repaired_tangents` records their count per level. Inspect
normal-mapped lighting around these locations during appearance review.
Export can repack resources or increase file size. Review appearance and material
boundaries in the intended viewer before publication.

## Build and invoke

From the repository root, build this self-contained image with the
`external_code` context:

```sh
docker build -f external_code/geometric_lod_generator/Dockerfile \
  -t webhdp/geometric-lod-generator:1.0.2 external_code
```

The image installs CPU Blender. The component declares one CPU and 8 GiB RAM,
and the runner enforces a 600-second execution timeout. Large inputs can require more memory; the complete
sampling set is proportional to the source triangle count. Configure resources
and timeout for the deployment after representative corpus measurements.
The registered execution profile uses the installation's verified image;
pin its immutable digest for reproducible deployments.

The file-based HDP Component contract is:

```json
{
  "inputs": {"input_file": "/inputs/model.glb"},
  "parameters": {"target_ratio": 0.5, "max_relative_error": 0.001}
}
```

Pass the file paths through `WEBHDP_COMPONENT_REQUEST=/inputs/request.json` and
`WEBHDP_COMPONENT_RESPONSE=/outputs/result.json`, as used by the native adapter.
For a CLI smoke check, use `--input-file /inputs/model.glb --target-ratio 0.5
--max-relative-error 0.001`. Local development
can call `runner.execute(request)` with `WEBHDP_BLENDER_BIN` pointing to Blender
and `WEBHDP_OUTPUT_DIR` pointing to an isolated directory. Never use the scholarly
source directory as a disposable output directory.

## Verification and deployment acceptance

The regression suite checks invalid ratios, unsupported input, a missing
runtime, timeout cleanup, and unchanged sources without Blender. To also run
real CPU integration checks from the repository root:

```sh
WEBHDP_TEST_BLENDER=/path/to/blender .venv/bin/python -m pytest -q \
  tests/test_geometric_lod_component.py
```

To exercise the packaged runtime with the same generated fixtures, also set
`WEBHDP_TEST_GEOMETRIC_IMAGE=webhdp/geometric-lod-generator:1.0.2`. These optional
checks require Docker and run with networking disabled, one CPU, 8 GiB RAM, and
read-only source mounts. They also check ratio changes and retry isolation.

The earlier 1.0.1 CPU cases covered a 3,968-triangle smooth sphere, embedded texture with two UV
layers and vertex colors, a tight limit that retains geometry, distinct retry
directories, and a changed target ratio. A Blender 5.1.1 local run at ratio 0.5
and relative error 0.01 produced 2,804 / 1,983 / 990 triangles with an unchanged
source checksum. The packaged Debian runtime with Blender 4.3.2 produced the same
ladder and retained both UV layers, vertex colors, the embedded texture, and
material settings in the textured fixture. The tight-limit fixture retained
all source triangles, and the manifest's single-triangle smoke fixture exported
all three levels. These are fixture observations, not quality promises for other
models. All exported fixture levels passed the independent Khronos glTF Validator
2.0.0-dev.3.10 with no errors or warnings.

Before installing a new image, run its manifest smoke test, the CPU cases against
the packaged Blender version, and the independent validator against every output.
Use the [mesh validation corpus and conformance runner](../mesh_optimizer/validation/README.md)
for material-rich cases, mirrored instances, Unicode paths, large and microscopic
geometry. Compare representative originals and derivatives visually, and exercise
the installed component through a fresh WebHDP session with duplicate basenames
and an unsupported record between valid records. Confirm record-local artifacts,
unchanged originals, failure isolation, and source/output provenance.

The [CPU corpus validation guide](validation/README.md) records the broader
1.0.2 acceptance, discovered regressions, and resource/file-size measurements.
The earlier packaged checks do not establish 1.0.2 packaged or installed-session
acceptance. GPU optimizer/renderer and disconnected-cluster
checks belong to their existing validation runbooks and must be completed in an
available test allocation.
