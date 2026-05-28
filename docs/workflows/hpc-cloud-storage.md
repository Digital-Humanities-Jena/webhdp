# HPC, Cloud, And Storage Workflows

This document covers HPC access, HPC-Link execution support, cloud storage,
storage-mode operations, and the operator side of installable HDP Components.

## Overview

These workflows explain how WebHDP moves data and processing beyond the normal
local application path. They cover requesting HPC access, staging work through
HPC-Link, checking renderer and converter services, configuring cloud storage,
and installing either local Docker-backed or HPC/SIF-backed components. The
later sections are intended for operators tuning throughput, staging, and
failure recovery.

## Use Cases

- Request, approve, validate, or revoke HPC access for users.
- Stage files or cloud references into HPC-backed processing.
- Configure storage provider and cloud upload behavior.
- Diagnose renderer, converter, local Docker component, SIF, and HPC-Link failures before rerunning a workflow.

## HPC Resource Request

Primary actor: user requesting larger processing capacity.

Entry points:
- UI: `/hpc-resources`
- API: `/api/v1/hpc-resource-requests/me`
- API: `/api/v1/hpc-resource-requests`
- API: `/api/v1/admin/hpc-resource-requests`
- API: `/api/v1/admin/hpc-resource-requests/<request_id>/approve`
- API: `/api/v1/admin/hpc-resource-requests/<request_id>/reject`
- API: `/api/v1/admin/hpc-access-users`
- API: `/api/v1/admin/hpc-access-users/<user_id>/revoke`

Workflow:
1. User checks current HPC access status.
2. User submits a resource request.
3. Administrator reviews, approves, rejects, or revokes access.
4. Approved access enables HPC-backed workflows.

Complete when:
- The user has the correct HPC access state.

## HPC-Link Allocation And Staging

Primary actor: publishing user or workflow execution engine.

Entry points:
- API: `/api/v1/hpc-link/status`
- API: `/api/v1/hpc-link/allocations`
- API: `/api/v1/hpc-link/allocations/<allocation_id>`
- API: `/api/v1/hpc-link/allocations/<allocation_id>/preflight`
- API: `/api/v1/hpc-link/allocations/<allocation_id>/stage/cloud`
- API: `/api/v1/hpc-link/allocations/<allocation_id>/stage/cloud-references`
- API: `/api/v1/hpc-link/allocations/<allocation_id>/zenodo/upload-draft`
- API: `/api/v1/hpc-link/allocations/<allocation_id>/release`

Workflow:
1. Check HPC-Link availability.
2. Request an allocation.
3. Run preflight for the allocation.
4. Stage files or cloud object references.
5. Optionally upload a Zenodo draft from the allocation context.
6. Release the allocation when finished.

Complete when:
- HPC resources are staged, used, and released cleanly.

## HPC Diagnostics

Primary actor: administrator.

Entry points:
- UI: `/tools/hpc-diagnostics`
- API: `/api/v1/tools/hpc-diagnostics`

Workflow:
1. Load local and remote HPC diagnostic state.
2. Check configured endpoints, storage mode, renderer/converter availability, and queue context.
3. Use diagnostics before component execution or incident response.

Complete when:
- HPC-related dependency status is known.

## Cloud Storage And Storage Modes

Primary actor: administrator or publishing user.

Entry points:
- UI: `/settings/storage`
- UI: `/settings/cloud-testing`
- API: `/api/v1/admin/storage-config`
- API: `/api/v1/admin/storage-status`
- API: `/api/v1/admin/cloud/test/gdrive`
- API: `/api/v1/admin/cloud/test/dropbox`
- API: `/api/v1/sessions/<session_id>/cloud-downloads`
- API: `/api/v1/sessions/<session_id>/cloud-downloads/<mirror_id>`

Storage modes:
- `pure_cloud`
- `cloud_backup`
- `server_only`
- `local`

Workflow:
1. Configure storage providers and storage mode.
2. Test Google Drive or Dropbox connectivity.
3. Upload sessions according to storage mode.
4. Show owner-only cloud downloads for mirrored source artifacts when available.

Complete when:
- Storage status matches the configured mode and downloads behave according to policy.

## Renderer And Converter Runtime Checks

Primary actor: administrator.

Entry points:
- API: `/api/v1/admin/pipelines/render/status`
- API: `/api/v1/admin/pipelines/render/test`
- API: `/api/v1/admin/pipelines/converter/test`
- API: `/api/v1/setup/test-render`

Workflow:
1. Check renderer service status.
2. Run renderer smoke test.
3. Run USDZ converter test.
4. Decide whether local execution or HPC-backed execution is required.

Complete when:
- Renderer and converter state is known before publication.

## Component Installation Strategies

Primary actor: administrator.

Entry points:
- UI: `/tools/hdp-components/install`
- API: `/api/v1/tools/hdp-components/catalog`
- API: `/api/v1/tools/hdp-components/validate`
- API: `/api/v1/tools/hdp-components/install`
- API: `/api/v1/tools/hdp-components/installations/<installation_id>/test`

Workflow:
1. Choose `local_container` for workstation Docker execution or `hpc_sif` for HPC-Link/Singularity execution.
2. Select an installable component manifest for that strategy.
3. Validate manifest and artifact source: Docker image locally, SIF path/URL for HPC.
4. Install and register the component. The native registry can hold both local and HPC profiles for the same component version.
5. Run smoke tests: `install.test` for local Docker, `hpc.test` for HPC-Link/SIF.

Complete when:
- Installed components are available for Pipeline Constructor or Playground as applicable.

## Prerequisites And Permissions

- HPC resource requests require an authenticated user; approval, rejection, and revocation require administrator access.
- HPC-Link allocation and staging require configured HPC-Link service credentials and reachable remote infrastructure.
- Cloud storage workflows require a configured storage provider or local storage mode.
- Renderer, converter, diagnostics, and component installation checks require administrator access or operator shell access.
- Local Docker installation requires a workstation-local deployment with safe Docker CLI access, plus any configured `WEBHDP_LOCAL_COMPONENT_IMAGE_ALLOWLIST` or digest-pinning policy.

## Inputs, Outputs, And State

| Input | Output | State To Watch |
|---|---|---|
| HPC request form | Approved or rejected HPC access | request status, access-user list, revocation state |
| Allocation request and staged files | HPC allocation and staged references | allocation status, preflight result, release state |
| Storage configuration | Active upload/download behavior | storage mode, provider config, cloud mirror availability |
| Component manifest plus Docker image or SIF source | Installed native component | strategy, image/SIF source, policy check, smoke test result, component registry entry |

## Failure And Recovery

- Failed HPC requests should be reviewed through admin access controls before users retry.
- Failed staging should be diagnosed through allocation status, preflight output, and cloud reference availability.
- Cloud storage failures should distinguish provider configuration issues from session-specific artifact availability.
- Failed local container installation should be corrected before exposing the component in Pipeline Constructor or Playground.
- Failed SIF installation should be corrected before exposing the component in Pipeline Constructor or Playground.

## Optimization Targets

- Reduce duplicate staging or transfer work for repeated pipeline runs.
- Make storage-mode checks clear before users start large uploads.
- Keep cloud download availability cheap to compute for record-heavy sessions.
- Improve Docker/SIF validation and smoke tests so broken components fail before runtime.

## Verification Checklist

- Verify user request, admin approve/reject, access listing, and revoke workflows.
- Run HPC-Link status, allocation, preflight, staging, draft upload, and release paths.
- Confirm storage config, storage status, and cloud provider tests.
- Run renderer status/test, converter test, HPC diagnostics, and component installer smoke test.

Related docs:
- `docs/cloud_storage.md`
- `docs/storage_modes_architecture.md`
- `docs/guides/hpc_single_gpu_setup_guide.md`
- `docs/guides/hdp_component_hpc_installation.md`

## Codebase Starting Points

- HPC user/admin views: `frontend/src/views/hpc/`, `frontend/src/views/admin/AdminHpcAccessView.vue`
- HPC resource routes: `routes/hpc_resource_request_routes.py`, `routes/admin_routes.py`
- HPC-Link routes and service: `routes/hpc_link_routes.py`, `services/hpc_link_client.py`, `services/hpc_allocation_service.py`
- Cloud upload and storage: `routes/upload_routes.py`, `services/cloud_storage_service.py`, `services/cloud_upload_service.py`
- Renderer/converter configuration: `routes/admin_routes.py`, `services/submission_pipeline_service.py`
- Component install support: `routes/tools_routes.py`, `services/native_pipeline_system.py`
- HPC deployment scripts: `scripts/hpc_singularity/`
