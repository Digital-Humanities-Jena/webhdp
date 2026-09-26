# Mesh Optimizer

This installable HPC component adapts [3DOM-FBK/mesh-optimizer](https://github.com/3DOM-FBK/mesh-optimizer) at revision `a1e76f43b9257be5288ad18c52b640c6a3f4829a`. The upstream repository carries the GNU GPL version 3; see `UPSTREAM_LICENSE`.

The **Mesh Optimization & Preview** pipeline optimizes each uploaded static GLB, then passes that derivative to Fast Renderer. Original files stay unchanged. The optimized GLB, optimization report, and previews are registered with the session and its `.hdpc` records. This pipeline does not create, upload or publish Zenodo records.

After processing, open the session's record details and use **Download file** in **Included Files** to retrieve the model, report or previews.

## Supported inputs and behavior

Use a self-contained GLB 2.0 with embedded textures. Animated models, skins, external dependencies and malformed containers are rejected before processing. Other formats should first be exported as static GLB.

The standard workflow preserves existing UVs and creates bake UVs for material groups without coordinates (`--skip_remesh` upstream), decimates geometry, bakes textures and exports a Draco-compressed GLB. The selected detail level targets 25,000 / 100,000 / 200,000 faces per material group, subject to upstream's geometric error limit. Small inputs may grow because textures are rebaked. The report records input/output size, mesh count, and embedded image count. Remeshing and PartUV reconstruction are not exposed in the standard component controls.

Texture bake failures, missing outputs, incomplete GLB containers and loss of all embedded textures fail the component. A failed optimizer cannot silently fall back to rendering the original. Retries and identically named records receive separate output directories.

## Build and install

Build on a Linux HPC compute node with Singularity or Apptainer, Python 3.11+, Git, and at least 40 GB of scratch space. Running the component requires one NVIDIA GPU, 8 CPU cores and 32 GB RAM. The SIF includes Blender, the pinned upstream source, wrapper, and checkpoint; runtime processing does not download dependencies.

1. Obtain the upstream runtime from `docker://3domfbk/mesh-optimizer:30122025` using `singularity pull`. Record and independently verify its SHA-256 before building. The tested runtime SIF has SHA-256 `885329ddb0a2648e774e40c624a5d066cc2ec2e506f32886a707c2fd6790fd6e`. SIF metadata can make independently converted images have different checksums.
2. Obtain `model_objaverse.ckpt` from the upstream repository's documented checkpoint location. The builder requires SHA-256 `463efc8a3afd3913142aa025e0125c00f16ef452b8de6a132ebe32bbe7877ee4`.
3. Run `python3 build_sif.py --base-image /path/runtime.sif --base-sha256 TRUSTED_SHA256 --checkpoint /path/model_objaverse.ckpt --scratch /scratch --output /path/webhdp-mesh-optimizer-1.0.0.sif`. This uses an unprivileged sandbox conversion; it does not require root or fakeroot.
4. In **HDP Components**, install `component.yaml` with the absolute remote SIF path and the resulting checksum. Installation pins the artifact. Do not overwrite an installed version; build and register a new version for changes.
5. Restart WebHDP's backend and worker after initial installation to seed the ready pipeline. It is offered only once the component has a verified SIF checksum. Select **Mesh Optimization & Preview**, then submit the selected GLB files with an active HPC allocation.

HPC-Link must run the matching `webhdp_component_runner.py`. Generic GPU profiles receive `--nv`; staged input paths are mapped exactly. `WEBHDP_CPUS_PER_TASK` and `WEBHDP_MEMORY_MB` configure HPC-Link's allocation resources (defaults: 8 and 32768). Keep server-specific paths, credentials, and allocation policy in the deployment profile.

No login-node smoke job is provided: GPU validation must run inside a scheduler allocation. Verify the complete workflow with a textured GLB and a multi-mesh GLB before enabling a new image for users.
