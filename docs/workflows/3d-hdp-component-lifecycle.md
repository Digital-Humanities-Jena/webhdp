# 3D HDP Component Lifecycle Workflows

This document covers the workflows for creating, validating, distributing,
installing, and smoke-testing the external 3D HDP Components used by WebHDP's
native 3D analysis and processing pipelines.

## Overview

The 3D HDP Components are separate executable packages, not WebHDP application
modules. WebHDP reads each component's `component.yaml`, registers the declared
component version, and runs the selected execution profile through the native
adapter system. The component package and runtime artifact stay installable
separately from the main WebHDP application.

Current 3D component packages:

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

This workflow is intended for component developers, WebHDP administrators, HPC
operators, and research projects that need to understand which processing logic
lives outside WebHDP. For digital cultural heritage deployments, the important
distinction is that WebHDP stores the manifest contract, execution profile, run
state, and provenance, while the component package supplies the separately
installed analysis or processing implementation.

## Use Cases

- Create a new external 3D HDP Component with a manifest-backed runtime contract.
- Validate component metadata, inputs, outputs, profiles, and smoke-test fixtures.
- Install the same component version for local Docker, HPC-Link/Singularity, or both.
- Make an installed component available in Playground, Pipeline Constructor, and optional seeded pipelines.
- Diagnose why an optional 3D pipeline is not visible because one or more required components are missing.

## Create A 3D Component Package

Primary actor: component developer.

Entry points:
- Filesystem: `external_code/<component_name>/component.yaml`
- Filesystem: `external_code/<component_name>/component_runner.py`
- Optional filesystem: `external_code/<component_name>/Dockerfile`
- Validator: `scripts/validate_hdp_components.py`

Workflow:
1. Create an `external_code/<component_name>/` package.
2. Add `component.yaml` with metadata, distribution metadata, inputs, outputs, execution profiles, compatibility, and install metadata.
3. Add a runner that reads `WEBHDP_COMPONENT_REQUEST` and writes `WEBHDP_COMPONENT_RESPONSE`.
4. Keep generated files in `WEBHDP_OUTPUT_DIR` and return structured `outputs` plus `artifacts`.
5. Add a small smoke-test fixture under `install.test` and, when supported, `hpc.test`.

Complete when:
- The package has a manifest, executable runner, declared outputs, and at least one install strategy.

## Validate Component Manifests

Primary actor: component developer, maintainer, or CI.

Entry points:
- Make: `make hdp-components-check`
- Script: `uv run python scripts/validate_hdp_components.py external_code/<component_name>`
- Script: `uv run python scripts/validate_hdp_components.py --strict-warnings`

Workflow:
1. Run the component validator from the repository root.
2. Confirm `component.yaml` follows the backend manifest contract.
3. Confirm required files stay inside the component directory and exist.
4. Confirm local Docker profiles use `adapter: container_cli` and `runtime: docker`.
5. Confirm HPC profiles use `adapter: hpc_link` and `runtime: singularity`.
6. Fix any validation errors before import or installation.

Complete when:
- The validator reports zero failures, and strict warning mode is clean when used for release or CI.

## Build Or Publish Runtime Artifacts

Primary actor: component developer or operator.

Entry points:
- Docker: local build or registry pull for `local_container`
- HPC artifact store: `.sif` path or HTTPS `.sif` URL for `hpc_sif`

Workflow:
1. Build or pull the Docker image declared by the local install strategy.
2. For HPC, build the Singularity/Apptainer SIF outside WebHDP.
3. Publish the SIF to a readable HPC path or HTTPS URL.
4. Keep the manifest image/profile metadata aligned with the artifact that will be installed.
5. Avoid relying on WebHDP to build Docker or SIF images during installation.

Complete when:
- The runtime artifact exists and can be inspected by the target installation strategy.

## Install Local Docker Components

Primary actor: administrator or workstation-local operator.

Entry points:
- UI: `/tools/hdp-components/install`
- API: `/api/v1/tools/hdp-components/catalog`
- API: `/api/v1/tools/hdp-components/validate`
- API: `/api/v1/tools/hdp-components/install`
- API: `/api/v1/tools/hdp-components/installations/<installation_id>/test`
- API: `/api/v2/components/import`

Workflow:
1. Enable local component execution intentionally with `WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=true`.
2. Configure a deliberate `WEBHDP_LOCAL_COMPONENT_IMAGE_ALLOWLIST`.
3. Select the `local_container` install strategy.
4. Validate the manifest and Docker image policy.
5. Install the component, which imports the manifest into the native registry.
6. Run the `install.test` smoke test when declared.

Complete when:
- The component version is registered with a working `local_docker` profile and is visible to Pipeline Constructor or Playground when compatible.

## Install HPC SIF Components

Primary actor: HPC operator or administrator.

Entry points:
- UI: `/tools/hdp-components/install`
- API: `/api/v1/tools/hdp-components/catalog`
- API: `/api/v1/tools/hdp-components/validate`
- API: `/api/v1/tools/hdp-components/install`
- API: `/api/v1/tools/hdp-components/installations/<installation_id>/test`
- HPC-Link component install/test endpoints

Workflow:
1. Confirm HPC-Link is configured and reachable.
2. Select the `hpc_sif` install strategy.
3. Provide a readable remote SIF path or HTTPS SIF URL.
4. Ask HPC-Link to install or verify the SIF.
5. Import the component with the installed remote SIF path in its execution profile.
6. Run the `hpc.test` smoke test when declared.

Complete when:
- The component version is registered with an HPC execution profile and can be used by pipelines that target that profile.

## Merge Multiple Install Strategies

Primary actor: administrator.

Entry points:
- UI: `/tools/hdp-components/install`
- API: `/api/v1/tools/hdp-components/install`
- Native registry: `services/native_pipeline_system.py`

Workflow:
1. Install one strategy for a component version, such as `local_container`.
2. Later install the other strategy for the same component version, such as `hpc_sif`.
3. Let WebHDP merge the new profile into the existing component version.
4. Confirm installation records remain separate while the native component version stays unique.

Complete when:
- The same component version exposes the intended local and HPC profiles without duplicate component versions.

## Record Component Provenance And Reuse Metadata

Primary actor: component developer, administrator, or repository maintainer.

Entry points:
- Manifest: `external_code/<component_name>/component.yaml`
- Runtime artifact: Docker image digest or SIF checksum
- Installer record: `/api/v1/tools/hdp-components/install`
- Native registry: `/api/v2/components`

Workflow:
1. Record the component name, version, distribution tier, license, and maintainer in the manifest.
2. Pin or archive the runtime artifact reference used for installation.
3. Record Docker image digests for local profiles and SIF checksums for HPC profiles when available.
4. Keep the local Docker and HPC SIF profiles semantically equivalent for the same component version.
5. Add citation or acknowledgement text when the component wraps external research software or trained models.
6. Preserve smoke-test results and installed profile information with the component installation record.

Complete when:
- A project can identify which component version, artifact reference, checksum, profile, and smoke-test result produced a given pipeline run.

## Prerequisites And Permissions

- Component validation requires repository access.
- Component import and installer workflows require administrator access.
- Local Docker installation requires a workstation-local deployment or another deliberately safe Docker access pattern.
- HPC SIF installation requires configured HPC-Link, a readable SIF source, and target HPC runtime availability.
- Pipeline authors can use registered components, but importing or installing new components remains an admin workflow.

Deployment choice:

| Strategy | Best Fit | Avoid When | Required Evidence |
|---|---|---|---|
| `local_container` | Workstation-local WebHDP, lab machines, developer validation, small to medium CPU/GPU jobs | Public VPS deployments without an intentional Docker access pattern, untrusted images, very large batch jobs | Docker image exists locally or in an approved registry, image policy passes, `install.test` succeeds |
| `hpc_sif` | Institutional HPC, reproducible large jobs, shared GPU queues, projects with strict runtime isolation | No HPC-Link allocation, missing Singularity/Apptainer runtime, unreadable SIF source | SIF path or URL is readable, HPC-Link install/verify succeeds, `hpc.test` succeeds |
| Built-in WebHDP core component | Stable publication behavior that ships with WebHDP | Experimental analysis, project-specific processing, heavyweight runtime dependencies | WebHDP release version and built-in pipeline support are documented |

## Inputs, Outputs, And State

| Input | Output | State To Watch |
|---|---|---|
| `component.yaml` plus runner files | Validated component package | manifest schema, source path, required files |
| Docker image | Local Docker execution profile | image policy, image inspection, `install.test` result |
| SIF source | HPC execution profile | installed remote path, HPC-Link validation, `hpc.test` result |
| Component import request | Native component version | component key, version, active profile list |
| Second install strategy for same version | Merged component profile set | installation records, duplicate prevention |
| Runtime artifact digest or checksum | Reproducibility evidence | Docker digest, SIF checksum, profile ID, install timestamp |
| Component license and citation text | Reuse context | project acknowledgement, wrapped software terms, publication notes |

## Failure And Recovery

- If validation fails, fix the manifest before building or installing artifacts.
- If Docker image inspection fails, build or pull the image on the host that runs WebHDP's backend or worker.
- If Docker policy rejects the image, update the image reference or deployment allowlist deliberately.
- If HPC validation fails, check SIF readability, runtime availability, and HPC-Link connectivity.
- If an optional 3D pipeline is not seeded, verify every referenced component is registered and active.
- If provenance evidence is incomplete, rerun installation with a pinned image digest or recorded SIF checksum before using results for publication claims.
- If a component wraps third-party software with unclear licensing or citation requirements, hold it for administrator review before project distribution.

## Optimization Targets

- Keep component smoke fixtures tiny so installation tests are fast.
- Prefer structured JSON outputs first and derivative files second.
- Keep local and HPC profiles semantically equivalent so pipeline definitions can be versioned with minimal changes.
- Use manifest validation as the cheapest failure point before runtime execution.
- Prefer digest-pinned Docker images and checksum-recorded SIF artifacts for reusable research workflows.
- Use plain component names and descriptions so curators can distinguish core WebHDP behavior from optional external processing.

## Verification Checklist

- Validate all 3D component manifests with `--strict-warnings`.
- Confirm local Docker images exist for local install strategy tests.
- Confirm SIF paths or URLs exist before HPC install tests.
- Import or install the component and confirm it appears in `/api/v2/components`.
- Run Playground or installer smoke tests for at least one representative input.
- Confirm optional 3D pipelines seed only after all required components are registered.
- Confirm component version, runtime artifact reference, checksum or digest, and profile ID are visible in the installation or run evidence.
- Confirm licensing, citation, and reuse notes are documented before distributing a component to research partners.

Related docs:
- `docs/guides/hdp_component_hpc_installation.md`
- `docs/workflows/pipelines-components-playground.md`
- `docs/workflows/3d-analysis-processing-pipelines.md`
- `external_code/*/component.yaml`

## Codebase Starting Points

- Component manifests: `external_code/*/component.yaml`
- Component validator: `scripts/validate_hdp_components.py`
- Installer routes: `routes/tools_routes.py`
- Native component registry: `services/native_pipeline_system.py`
- Runtime adapters: `services/native_pipeline_adapters.py`
- Pipeline Constructor UI: `frontend/src/views/admin/PipelineConfigView.vue`
- Installer UI: `frontend/src/views/tools/HdpComponentInstallerView.vue`
