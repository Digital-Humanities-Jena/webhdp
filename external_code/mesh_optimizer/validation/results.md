# Mesh pipeline robustness results

Validated on 2026-09-26 for component **1.0.1**, with Blender 5.0.0 for optimization and Blender 4.1.1 for Fast Renderer on an NVIDIA RTX A5000 allocation. WebHDP remains `0.1.0-alpha.2`. The verified image was subsequently installed and tested through the deployed application.

## Coverage and outcomes

| Check | Outcome |
| --- | --- |
| 13 static Khronos sample assets | Optimization, decoded geometry/material comparisons, conformance, and previews passed |
| Animated Khronos sample | Rejected explicitly; no derived artifacts |
| Nine valid generated cases | Passed, including sparse data-URI geometry, tiny/large coordinates, Unicode filenames, multiple materials, shared instances, and dense geometry |
| Degenerate geometry | Rejected explicitly; no derived artifacts |
| Previously Draco-compressed input | Re-optimization and previews passed |
| Large architectural model with 538 source meshes | Optimization, geometry/material comparison, conformance, and previews passed |
| Smooth sphere, 327,680 triangles | Reduced to 24,999 triangles; geometry comparisons passed |
| Flat surface, 96,800 triangles | Geometry retained because the requested reduction exceeded the error limit |
| Texture settings | LOW/256 corpus; MEDIUM/1024 full workflow; HIGH/4096 non-power-of-two case preserved its original 211×211 texture without upscaling |
| Independent glTF validation | Zero errors and warnings in checked derivatives, including all packaged synthetic outputs and full-workflow outputs |
| Preview decoding | 155 PNGs from 31 rendering cases decoded successfully at 512×512; another 15 full-workflow previews also decoded |
| Backend tests | 765 passed, one skipped |
| HPC-Link tests | 116 passed, plus three subtests |
| Component manifest | No errors; expected warning because no login-node GPU smoke test is declared |
| Developer documentation, release assets, diff checks | Passed |

The main corpus contains **24 valid input scenarios** (13 public, nine generated, one compressed repeat, one architectural) plus two intentional rejection cases. An earlier flat-shaded sphere variant was also checked; conservative geometry retention was confirmed. Repeated runs at different settings and representative source renders are additional executions, not additional unique assets.

## Complete workflow

A fresh local WebHDP database and `.hdpc` session used the native pipeline service with actual SSH/Slurm execution and artifact transfer. The test used the immutable candidate SIF, without wrapper binds, at the built-in MEDIUM/1024 settings. Transport bypassed the deployed HTTP gateway; this was not a deployed-site or browser test.

Four records had the same `model.glb` filename in different directories: metallic/textured, animated, alpha/textured, and vertex-colored models. Three records completed successfully. Each received its own optimized GLB, report, and five previews, registered in both the application and `.hdpc`. The animated record failed, its dependent renderer did not execute, and processing continued for later records. It retained only its original file. All four original checksums remained unchanged. The generated GLBs passed independent conformance validation.

## Fixes exercised

- Retain imported material graphs and resize existing images. This avoids upstream metallic/opacity bake failures, overlapping-UV rebaking errors, and loss of unlit/emissive properties.
- Keep intermediate meshes in memory to retain extra UV sets, colors, custom normals and material boundaries that OBJ cannot represent.
- Materialize glTF default materials in a temporary import copy, avoiding Blender-version differences for material-less vertex-colored meshes.
- Export tangents required by normal-mapped and anisotropic materials.
- Avoid fixed-distance vertex merging that damages tiny models. Check reduction against source/result surfaces in both directions and retain preceding geometry when the limit is exceeded.
- Reject invalid resource boundaries, cyclic or invalid node references, unsupported extensions, invalid parameter types and empty/degenerate surfaces. Unused embedded images do not trigger a false texture-loss failure.
- Preserve Slurm's CUDA device selection through Singularity/Apptainer's clean environment.

The geometry safeguard measures vertices against surfaces, not the exact continuous Hausdorff distance. Material and geometry comparisons, independent validation, and representative visual inspection provide complementary checks. These results establish coverage of the listed cases, not a guarantee for every possible GLB extension or scene. Unsupported inputs fail explicitly.

## Candidate identity

- SIF SHA-256: `2c4bcee3d80edba1a68b01654076b5d10dda0375cba4f5b30d86650d6b480a28`
- Packaged `runner.py`: `9a9aa2422eed23f55f6b4e59c8a819e0ec5f718127437a77fda39c3f24245356`
- Packaged `blender_entry.py`: `876a6b88427952f9b90ee8df06bb87fd9cb84118998864997d97f33cf9455c76`

Packaged wrapper hashes matched the repository sources. Initial validation used isolated storage without changing the deployed application. Subsequent public HTTPS acceptance processed two records through Celery and HPC-Link, producing two validated GLBs, two reports and ten previews. All originals retained their checksums. No Zenodo records were created or published during these component tests.
