# CPU geometric LOD acceptance

This corpus gate exercises generation, independent geometry/material comparison,
Khronos glTF conformance, source integrity and process resources. It does not
establish appearance quality or acceptance of a deployment's installed image.

## Repeatable corpus

Use a new directory outside the checkout. The public downloader uses immutable
Khronos sample-model URLs and verifies all 14 source hashes in
[`sources.json`](../../mesh_optimizer/validation/sources.json). It saves each
model's license notes beside the inputs. Public model binaries are not committed.
The shared Blender fixture script adds 10 edge cases; the CPU fixture script adds
thin features, a disconnected small island and hard edges.

```sh
python external_code/mesh_optimizer/validation/download.py /tmp/lod-corpus
blender --background --factory-startup --python-exit-code 1 \
  --python external_code/mesh_optimizer/validation/fixtures.py -- /tmp/lod-corpus/inputs
blender --background --factory-startup --python-exit-code 1 \
  --python external_code/geometric_lod_generator/validation/fixtures.py -- /tmp/lod-corpus/inputs
npm install --prefix /tmp/lod-validator --no-audit --no-fund gltf-validator@2.0.0-dev.3.10
.venv/bin/python external_code/geometric_lod_generator/validation/run.py \
  --inputs /tmp/lod-corpus/inputs --output /tmp/lod-corpus/results \
  --blender /path/to/blender --validator-node-path /tmp/lod-validator/node_modules
```

Each case runs in a fresh Python worker with one Blender child. `case.json`
records wall time, Blender child peak RSS, source hash/bytes, actual level counts,
output sizes and retained meshes. `comparison.json` independently imports every
output and checks bounds, area, UV sets, vertex colors and material features.
`conformance.json` holds every validator issue. `summary.json` fails acceptance
if any supported case fails, an expected unsupported case succeeds, the source
changes, a worker fails/times out, or comparison/conformance fails. Use a fresh
output directory to retain previous evidence. Animated `BoxAnimated` and entirely
degenerate geometry are intentional rejections, not skipped acceptance cases.

## Measured local acceptance

[`acceptance-1.0.2.json`](acceptance-1.0.2.json) summarizes the 2026-10-06 local
Blender 5.1.1 run at medium ratio 0.5 and relative error 0.001. All 25 supported
models produced three valid levels (75 outputs); the two intentional rejections
were correctly rejected. Independent comparisons passed and Khronos Validator
2.0.0-dev.3.10 reported no errors or warnings. Every source remained unchanged.

The corpus includes embedded textures, alpha blending, unlit/emissive materials,
multiple UV sets, vertex colors, interleaved/sparse buffers, mirrored transforms,
shared mesh instances, Unicode paths, large/microscopic coordinates, dense
surfaces, thin geometry, hard edges and disconnected islands. The largest source
had 327,680 triangles. Supported-case median time was 0.57 seconds; maximum time
was 14.62 seconds and maximum Blender child RSS was 1.23 GiB. These are workstation
observations, not CPU-limit or container memory guarantees.

The dense sphere produced 231,704 / 163,840 / 81,920 triangles. Most other cases
conservatively retained their geometry at this tight error limit. Exported bytes
can grow: DamagedHelmet increased by approximately 132% after re-export, while
the dense sphere's low level was approximately 73% smaller. Choose settings from
geometry and appearance review, rather than assuming lower counts mean smaller
files or accepting targets as guaranteed reductions.

The expanded corpus found and now guards two regressions: MultiUVTest could lose
one third of its surface area while nearest-surface distance still passed;
DamagedHelmet could contain a zero-length exported tangent at a degenerate UV.
Material-group area guards retain the former geometry, and exported tangent
repair preserves valid unit directions and handedness. Reports count repairs.
Normal-mapped appearance still needs inspection.

## Deployment and disconnected compute

Rebuild/install the component, pin its verified image digest, and run the
manifest smoke test plus the optional local/container integration cases in
[`../README.md`](../README.md). For corpus acceptance of a packaged runtime, run
the corpus gate inside that image with read-only inputs and a separate output
mount, then independently validate every exported level. Keep the same pinned
sources and record the image digest and Blender version with the evidence.
Exercise the installed component through a real session and review the source
and level comparison in record details before publication.

The 1.0.2 native CPU corpus passed locally. Packaged-image acceptance remains
pending because the local Docker engine could not start during this validation.
Draco GPU optimization, rendering, allocation and installed HPC/SIF checks were
not run because Draco was unavailable. Their existing runbooks remain the gates
when compute becomes available; local CPU evidence does not imply HPC acceptance.
