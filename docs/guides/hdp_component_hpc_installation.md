# HDP Component Installation Guide

This guide describes how to prepare HDP Components for WebHDP installation.
WebHDP is the host/orchestrator; HDP Components are separate executable
packages described by `component.yaml`.

If you are creating your first component from an existing container, start with
`../development/first_hdp_component.md`. This guide focuses on installation
strategy, validation, and local Docker vs HPC/Singularity deployment choices.
For the complete manifest field contract, use
`../development/hdp_component_manifest_specification.md`.

WebHDP now distinguishes two install strategies:

- `local_container`: install/register a Docker-backed component on a capable
  workstation-local WebHDP deployment.
- `hpc_sif`: install/register a Singularity SIF-backed component through
  HPC-Link.

Core WebHDP components may still be bundled with the application for the
stable publication workflow. External HDP Components should use one or both of
the install strategies below.

Use explicit distribution metadata for installable external components:

```yaml
distribution:
  tier: external_installable
  bundled_with_webhdp: false
  installation_scope:
    - local_container
    - hpc_sif
```

## Component Package

Every installable component provides:

- `component.yaml`
- an executable container artifact for at least one install strategy

For `local_container`, the artifact is a Docker image already available to the
machine running WebHDP's backend/worker process. For `hpc_sif`, the artifact is
a prebuilt `.sif` image available as an absolute HPC path or a public HTTPS
URL ending in `.sif`. Use an administrator-approved host. Public Zenodo file
URLs may include `?download=1`. If a SIF needs authentication or a signed
download link, stage it on the cluster and enter its absolute path readable by
HPC-Link.

Dockerfiles may be used to build images outside WebHDP. WebHDP does not build
Docker images or SIF images during installation.

Recommended repository shape:

```text
external_code/
  your_component/
    component.yaml
    component_runner.py
    Dockerfile
    ...
```

The manifest is the component contract. WebHDP imports the manifest into the
native component registry and executes the declared profile; it does not import
the component as application code.

## Hybrid Distribution And Discovery

WebHDP now supports a hybrid discovery model:

- Git repositories are the source and review location for component code.
- Docker/OCI images and SIF files are the executable artifacts.
- Zenodo records and the HDP Components community provide DOI-backed archival
  publication for stable releases.
- WebHDP component indexes provide curated, machine-readable discovery.

Configure remote indexes with:

```env
WEBHDP_COMPONENT_INDEX_SOURCES=https://example.org/webhdp-components/index.json
WEBHDP_COMPONENT_INDEX_TIMEOUT_SECONDS=15
WEBHDP_COMPONENT_INDEX_CACHE_TTL_SECONDS=900
WEBHDP_COMPONENT_INDEX_MIN_TRUST=unknown
```

If `WEBHDP_COMPONENT_INDEX_SOURCES` is empty, WebHDP only lists the bundled
local `external_code/` catalog. Index sources must be HTTPS URLs or absolute
local JSON paths. Index entries use schema `webhdp.component-index.v1` and may
include:

- component key/version, label, category, tags, and trust level
- manifest URL and manifest SHA-256
- Git repository URL, tag, and commit
- Zenodo DOI, concept DOI, and record URL
- Docker image plus digest for `local_container`
- SIF source plus SHA-256 for `hpc_sif`
- release URL/tag/assets for GitHub, Codeberg, GitLab, or another Git-like host
- license, citation, SBOM, provenance, and WebHDP compatibility metadata

WebHDP verifies the manifest checksum before exposing an indexed entry, rejects
non-HTTPS provenance/SBOM/release links, and filters entries below
`WEBHDP_COMPONENT_INDEX_MIN_TRUST`. It also enforces `compatibility.webhdp_min`
and `compatibility.webhdp_max` against the running WebHDP version. During
installation it persists the catalog reference and provenance metadata with the
installation record. SIF checksums are passed to HPC-Link, which verifies the
installed SIF when `sif_sha256` is provided.

The formal JSON Schema is in
`docs/schemas/webhdp_component_index_v1.schema.json`. A local unpublished
fixture lives in `docs/examples/component-index/index.json` and can be loaded
with an absolute path while the public repository and hosted index do not exist
yet.

## Create, Deploy, Download, And Install Flow

Use this flow for new HDP Components:

1. Create the package under `external_code/<component_name>/` with a
   `component.yaml`, runner code, and smoke-test fixtures.
2. Declare `distribution.tier: external_installable`,
   `bundled_with_webhdp: false`, and the intended `installation_scope`.
3. Add one execution profile per strategy:
   - `local_docker` with `adapter: container_cli`, `runtime: docker`, and a
     Docker image for local workstation installs.
   - `hpc_singularity` with `adapter: hpc_link`, `runtime: singularity`, and an
     install-time SIF image for HPC installs.
4. Validate the manifest with `scripts/validate_hdp_components.py`.
5. Build and distribute the artifact outside WebHDP:
   - For `local_container`, build or pull the Docker image on the machine that
     runs the WebHDP backend/worker.
   - For `hpc_sif`, publish a `.sif` file at a readable HPC path or HTTPS URL.
6. Install from Tools -> HDP Component Installer:
   - Local strategy validates Docker policy and `docker image inspect`, imports
     the component, and can run `install.test`.
   - HPC strategy asks HPC-Link to install or verify the SIF, imports the
     component with the installed remote SIF path, and can run `hpc.test`.

Before repository publication, implement and verify the same flow locally with
absolute-path component indexes. After publication, point the index entries at
immutable Git tags/commits, release assets, OCI digests, SIF checksums, and
Zenodo record URLs. Direct retrieval from GitHub, Codeberg, GitLab, or similar
platforms should stay a developer/custom-manifest workflow until the release is
curated into a configured WebHDP index.
7. After installation, use the component in Playground, Pipeline Constructor,
   native pipeline execution, or optional seeded pipelines.

Downloading is strategy-specific: WebHDP does not download arbitrary runner code
into the application. Local deployments pull or build Docker images before
installation; HPC deployments provide a SIF source for HPC-Link to install or
verify on the target system.

## Deployment Choice Matrix

Choose the strategy according to deployment context and project risk:

| Strategy | Use When | Do Not Use When | Verification Before Project Use |
|---|---|---|---|
| `local_container` | WebHDP runs on a trusted workstation, lab server, or developer machine with intentional Docker CLI access | The deployment is a small public VPS, the Docker socket would be exposed broadly, or the image source is untrusted | Docker image is pulled or built, image policy passes, digest is recorded when possible, `install.test` succeeds |
| `hpc_sif` | Processing should run on institutional HPC, large batches need queue resources, or project policy requires Singularity/Apptainer isolation | HPC-Link is not configured, the SIF cannot be read by the HPC user, or the job needs interactive local files only | SIF path or HTTPS source is verified, checksum is recorded when possible, HPC-Link install/test succeeds |
| Built-in WebHDP component | The behavior is part of the stable WebHDP publication workflow and ships with the application | The processing logic is experimental, heavyweight, project-specific, or separately maintained | WebHDP release version and built-in pipeline behavior are documented |

Local and HPC strategies can coexist for the same component version. In that
case, treat them as two execution profiles for one manifest-backed component,
not as separate scholarly tools unless their behavior intentionally differs.

## Reproducibility, Citation, And Supply Chain

For research and cultural heritage reuse, record enough evidence to reconstruct
which executable produced a result:

- Component name, component version, and manifest source reference
- Pipeline identifier, pipeline version, and execution profile ID
- Docker image digest for `local_container` installs, or SIF checksum/path for
  `hpc_sif` installs
- Smoke-test result, install timestamp, and installer status
- License, citation, and acknowledgement text for wrapped third-party software
  or trained models
- Security or SBOM evidence when the component is distributed beyond a single
  trusted project team

Do not enable local Docker execution merely because Docker is present. The
deployment must intentionally allow the backend or worker to run approved
component images, and administrators should prefer digest-pinned images for
repeatable research runs.

## Developer Manifest Validation

Before opening a pull request, validate local HDP Component manifests from the
repository root:

```bash
make hdp-components-check
```

To validate a single component directory or manifest file:

```bash
uv run python scripts/validate_hdp_components.py external_code/gltf_validator
uv run python scripts/validate_hdp_components.py external_code/gltf_validator/component.yaml
```

For CI-style consumers or scripted reports, emit JSON:

```bash
uv run python scripts/validate_hdp_components.py external_code/gltf_validator --json
```

Use `--strict-warnings` when warnings should fail the command:

```bash
uv run python scripts/validate_hdp_components.py --strict-warnings
```

The validator checks that:

- `component.yaml` is parseable YAML and follows the backend manifest contract
- metadata names and versions are present and component versions are unique
- `structure.required_files` entries stay inside the component directory and exist
- local Python entrypoint scripts exist
- HPC-Link Singularity profiles declare the expected adapter, handler, runtime,
  and entrypoint shape
- local container profiles declare the expected `container_cli` adapter,
  Docker runtime, image, and entrypoint shape
- optional `hpc.test` and `install.test` fixtures use valid smoke-test file
  metadata

The same validation runs in CI and through the broader developer targets
`make test` and `make verify-onboarding`.

## Strategy-Aware Manifest Profiles

A component that supports local workstation execution declares a Docker-backed
profile:

```yaml
execution:
  profiles:
    - id: local_docker
      adapter: container_cli
      runtime: docker
      image: ghcr.io/hdp-components/your-component:1.0.0
      entrypoint:
        - python
        - /app/your_component.py
```

A component that supports HPC execution declares an HPC-Link/Singularity
profile:


```yaml
execution:
  profiles:
    - id: hpc_singularity
      adapter: hpc_link
      handler: generic_singularity_component
      runtime: singularity
      image: ""
      entrypoint:
        - python
        - /app/your_component.py
```

The installer replaces `image` with the installed remote SIF path.

Components can declare both profiles. Pipeline authors can then choose the
appropriate execution profile, and installers can register the same component
for local Docker or HPC SIF execution.

The native registry is still keyed by component name and version. Installing
the same component version for both strategies does not create two component
versions; WebHDP merges the new strategy profile into the existing registered
component version while preserving separate installation records.

Recommended strategy metadata:

```yaml
install:
  strategies:
    - id: local_container
      runtime: docker
      profile: local_docker
      image: ghcr.io/hdp-components/your-component:1.0.0
    - id: hpc_sif
      runtime: singularity
      profile: hpc_singularity
  test:
    files:
      - name: sample.glb
        content_base64: "<base64-encoded small test file>"
    inputs:
      input_file: sample.glb
    parameters:
      strict: false
```

## Current 3D Component Set

The current 3D model analysis and processing components are external
installable packages under `external_code/`:

- `model_profiler`
- `geometry_qa_gate`
- `texture_dependency_auditor`
- `canonical_glb_normalizer`
- `geometric_lod_generator`
- `point_cloud_analyzer`
- `scale_orientation_centering_normalizer`
- `model_repair_component`
- `model_fingerprint_deduplication`
- `viewer_readiness_analyzer`

These manifests currently declare local Docker installation scope. Once they
are installed, WebHDP can seed the optional native pipelines
`3d_prepublication_analysis`, `3d_publication_derivatives`, and
`3d_point_cloud_readiness`. If any required component is missing, the optional
pipeline is skipped during seeding instead of being exposed in a broken state.

To make the same components available on HPC, add an `hpc_sif` install strategy
and an `hpc_singularity` execution profile to each manifest, build the
corresponding SIF images, and install them through HPC-Link. The pipeline
definitions can then select the HPC profile or be versioned by a pipeline author
for the target deployment.

## Runtime Contract

The container entrypoint receives these environment variables:

- `WEBHDP_COMPONENT_REQUEST`: JSON request path
- `WEBHDP_COMPONENT_RESPONSE`: JSON response path to write
- `WEBHDP_INPUT_DIR`: mounted input directory, usually `/inputs`
- `WEBHDP_OUTPUT_DIR`: mounted output directory, usually `/outputs`
- `WEBHDP_COMPONENT_KEY`: component key

The request JSON contains:

```json
{
  "component_key": "your_component",
  "inputs": {},
  "parameters": {},
  "profile": {},
  "record_context": {},
  "batch_records": []
}
```

The response JSON should contain:

```json
{
  "success": true,
  "status": "completed",
  "outputs": {
    "result": "/outputs/result.json"
  },
  "artifacts": [
    {
      "artifact_kind": "file",
      "name": "result.json",
      "remote_path": "/outputs/result.json",
      "metadata": {}
    }
  ],
  "logs": {
    "stdout": "...",
    "stderr": ""
  }
}
```

Use `success: false`, `status: "failed"`, and an `error` string for failures.

## Smoke Test Metadata

Add an `install.test` block for local Docker installation tests. The local
installer mounts the files into `/inputs`, creates a request JSON, runs the
container with the runtime contract environment variables, and reads the
component response JSON.

Add an `hpc.test` block for the HPC-Link/SIF smoke test:

```yaml
hpc:
  test:
    files:
      - name: sample.glb
        content_base64: "<base64-encoded small test file>"
    inputs:
      input_file: sample.glb
    parameters:
      strict: false
```

Files listed in `hpc.test.files` are written into the smoke-test input
directory before execution. Keep them small; this is intended for minimal
fixtures only.

## HPC Prerequisites

- HPC-Link is reachable from WebHDP.
- `singularity` or `apptainer` is available on the target HPC.
- The configured component application directory exists and is writable by the
  HPC-Link user.
- Component SIF files are readable by the HPC-Link user.
- Verification should allocate one node only and use the site's configured
  partition or queue order.

## Preserve installations during a WebHDP upgrade

WebHDP records installed component versions, execution profiles, and saved
pipeline bindings in its database. HPC-Link keeps each installed SIF, manifest,
and checksum record in `$HPC_APPS_ROOT/webhdp/components/<component>/<version>/`
on the cluster. Upgrading the WebHDP application image reuses those records
and files.

1. Back up the WebHDP database and the HPC component registry. Keep the
   original component versions used by saved pipelines. Include any private
   model caches and operator configuration required by the registered images.
2. Point the new backend and worker at the same persistent database. With the
   production Compose file and SQLite, preserve the `WEBHDP_INSTANCE_PATH`
   bind mount. Apply database migrations to that database. Keep the HPC
   gateway pointed at the same `HPC_APPS_ROOT` and retain the component runner.
3. After rollout, compare the installed component keys, versions and SIF
   checksums in the **HDP Component Installer**. Open **Playground** and run
   a small fixture through one of the installed profiles. Retain the checksums
   alongside the deployment record.

Install a new component version when its executable or manifest changes.
Existing saved pipelines retain the component version they reference. When
moving to another cluster, migrate the pinned files and their registry
records and verify their paths and checksums before enabling execution.

## Example Component

`external_code/gltf_validator` is a CPU-only example component. It validates
`.glb` and `.gltf` assets, writes a JSON report, and uses the same
request/response contract expected by the installer.

## Local Container Prerequisites

- WebHDP is running in a workstation-local deployment, or the backend/worker
  process otherwise has access to the local Docker CLI.
- The target Docker image is already built or pulled locally.
- If WebHDP itself runs inside Docker, operators must intentionally provide a
  safe Docker access pattern, such as a host process deployment, Docker socket
  mount, or a dedicated local runner. Do not enable this on a small public VPS
  merely because Docker is installed.
- The component manifest declares a `container_cli` profile with
  `runtime: docker`.
- Optional hardening knobs:
  - `WEBHDP_LOCAL_COMPONENT_IMAGE_ALLOWLIST`: comma-separated Docker image
    patterns, for example `ghcr.io/hdp-components/*,webhdp-*`.
  - `WEBHDP_REQUIRE_PINNED_LOCAL_COMPONENT_IMAGES=true`: require
    digest-pinned images such as `ghcr.io/org/component@sha256:...`.

The local installer validates the manifest and checks that `docker image
inspect <image>` succeeds before registering the component in the native
registry. Local smoke tests run with `--network none` and only the test input,
output, request, and response directories mounted.

## Compatibility Notes

Some internal class, table, and migration names still contain `hpc_component`
because the installer began as an HPC-only SIF installer. New docs, UI labels,
and generated API operation names use neutral HDP Component language. The old
names remain for database and route compatibility.
