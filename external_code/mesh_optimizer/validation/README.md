# Mesh pipeline validation

Run these tools in an isolated working directory and an existing GPU scheduler allocation. They do not register components, update HPC-Link, deploy WebHDP, or contact Zenodo. Do not bind candidate code over an installed component directory. Bind it read-only into a test invocation instead.

Run the commands below from this tooling directory, with all generated data stored outside the repository.

## Corpus

`sources.json` pins 14 public [Khronos glTF Sample Assets](https://github.com/KhronosGroup/glTF-Sample-Assets) to a Git revision and SHA-256 per file. `download.py` verifies the downloads and saves each model's license and credit notes beside them. Binary assets are not redistributed in this repository.

```sh
python3 download.py /path/to/validation
blender --background --python-exit-code 1 --python fixtures.py -- /path/to/validation/inputs
```

The public cases cover interleaved buffers, vertex colors, non-power-of-two textures, metallic/roughness maps, alpha masks/blending, multiple UV sets, negative scales, mirrored tangents, unlit materials, emission strength, and texture transforms. `BoxAnimated` is an intentional rejection case.

The generated cases cover absent materials, microscopic geometry, large coordinates, Unicode/spaced filenames, multiple materials on one mesh, transformed shared instances, a 96,800-triangle surface, a 327,680-triangle sphere, sparse positions in an embedded data URI, and degenerate geometry. The last must fail with an actionable error. To check compressed input and repeated optimization, copy a successful derivative into the input directory under another name.

## GPU execution and result checks

Inside the allocation, run an immutable image, or bind candidate wrappers over the image's wrapper directory for development:

```sh
python3 run.py --image /path/to/component.sif --inputs /path/to/validation/inputs \
  --output /path/to/validation/results --component-dir /path/to/candidate/wrappers
blender --background --python-exit-code 1 --python compare.py -- \
  /path/to/validation/inputs /path/to/validation/results /path/to/validation/comparison.json
```

Omit `--component-dir` for the packaged-image check. The output directory must be new; requests, responses, logs, and a machine-readable summary are retained. Defaults are LOW geometry detail and 256-pixel maximum textures. Also test the built-in pipeline's MEDIUM/1024 defaults through WebHDP.

`compare.py` imports both files and checks finite geometry, world bounds, triangle count, surface area, UV layer preservation, vertex colors, and material factors. It compares effective emission, since exporters may redistribute brightness between the emission color and strength. Unlit materials ignore lighting-dependent PBR values by definition. These checks complement visual comparisons; they do not establish visual equivalence for every possible scene.

Run the independent [Khronos glTF Validator](https://github.com/KhronosGroup/glTF-Validator) against every derivative:

```sh
npm install --prefix /path/to/validation/validator gltf-validator@2.0.0-dev.3.10
NODE_PATH=/path/to/validation/validator/node_modules node conformance.cjs /path/to/validation/results
```

The script fails on errors or warnings. Draco geometry must additionally be decoded by Blender because the format validator does not establish geometric fidelity of the compressed data.

Finally pass each derivative to Fast Renderer using the file-based HDP Component contract (`scope: record`, `input_files` containing only the derivative, `preset: medium`, `angle-iteration: 5`, `strict_gpu: true`). Verify five nonempty PNGs per successful record. Compare representative originals/derivatives visually. A direct render of a material-less original in older Blender versions can omit vertex colors; the optimizer makes glTF's default material explicit to prevent that ambiguity in its derivative.

For WebHDP acceptance, use a fresh application database and `.hdpc` session, submit identically named files in separate records, and include an unsupported animated file between valid records. Verify that each valid record gets its own optimized GLB, report and five previews, the rejected record gets no derived files, original checksums remain unchanged, and processing continues after the rejected record. Do not use the deployed service for this validation when deployment is not authorized.

See `results.md` for the latest completed checks and their limits.
