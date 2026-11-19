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
- Operator API: `/api/v1/hpc-link/allocations/<allocation_id>/stage/cloud`
- API: `/api/v1/hpc-link/allocations/<allocation_id>/stage/cloud-references`
- Operator API: `/api/v1/hpc-link/allocations/<allocation_id>/zenodo/upload-draft`
- API: `/api/v1/hpc-link/allocations/<allocation_id>/release`

Workflow:
1. Check HPC-Link availability.
2. Request an allocation, or claim a [pre-reserved GPU](../guides/prereserved_gpu_demo.md)
   that an operator granted to this verified account for its own upload session.
3. Run preflight for the allocation.
4. Use the upload session's files or stage cloud files using receipts from your own WebHDP uploads.
5. Use the publishing workflow to create a Zenodo draft.
6. Release the allocation when finished. Releasing a pre-reserved GPU detaches
   WebHDP access and leaves the operator's Slurm job running.

Complete when:
- HPC resources are staged, used, and released cleanly.

Staging and preflight require a running allocation, current HPC permission and
edit access to the attached working session. An owner can still cancel or
release their idle request after HPC access is withdrawn.

The Compose `hpc-queue` service advances waiting requests even after users
close their browsers. Other deployments can run `python -m flask --app app hpc-queue`
with the same instance database and configuration as the API. The queue pauses
during maintenance and uses the same admission lock as the API.

WebHDP applies the active allocation limits across ordinary allocations and
reserved GPU claims. The default waiting limit is two HPC requests per account
and 24 per site. A waiting request expires after 24 hours if WebHDP has not sent
it to the scheduler. The `HPC_LINK_MAX_QUEUED_ALLOCATIONS_PER_USER`,
`HPC_LINK_MAX_QUEUED_ALLOCATIONS`, and `HPC_LINK_QUEUED_REQUEST_TTL_MINUTES`
environment settings control these limits. Use `HPC_LINK_MAX_GPUS_PER_ALLOCATION`
and `HPC_LINK_MAX_DURATION_MINUTES_PER_ALLOCATION` to set smaller per-request
limits where required by the gateway policy.

### Recover an unconfirmed scheduler submission

WebHDP keeps the active slot occupied when HPC-Link has yet to confirm a
submission. The allocation owner sees **Waiting for confirmation** while the
queue checks the gateway. A current gateway persists a request identity before
calling `sbatch`, so WebHDP can recover its existing job handle after an HTTP
timeout. Replay is only available when the gateway confirms that no request
intent exists. An older gateway can still start an ordinary allocation, but a
lost response on its legacy endpoint requires operator reconciliation.

Upgrade HPC-Link before starting the new WebHDP API and queue worker. Keep
`WEBHDP_SESSIONS_REGISTRY_PATH` on the same persistent volume across updates and
run one gateway process against that registry. Reconcile outstanding requests
before moving WebHDP to a different gateway or restoring its registry.

If confirmation does not return, use the following maintenance procedure.

1. Record the allocation’s public ID, partition attempt index, request time,
   requested resources, and gateway account. Enable maintenance mode and drain
   WebHDP writers before making any corrections, including the `hpc-queue`
   service. Snapshot the WebHDP database and gateway registry.
2. Check cluster accounting and the live scheduler under the gateway’s Slurm
   account with `sacct` and `squeue`. For a current gateway, the full job name is
   `hpc-link-webhdp-<request-id>`. The request ID is
   `uuid5(NAMESPACE_URL, f"webhdp-allocation:{public_id}:{partition_attempt_index}")`.
   Cross-check the job’s output path under the request’s private gateway
   workspace. For legacy submissions, correlate its submission time, partition,
   GPU request and workspace with the gateway logs. Leave the slot occupied if
   the evidence is incomplete or identifies more than one candidate.
3. If a keyed request has one verified live job, stop the gateway and restore
   the numeric `job_id` on its existing intent in the persisted registry, then
   restart the same gateway. The WebHDP queue can attach the handle on its next
   check. If the request is legacy, have the cluster operator cancel only the
   positively identified job and confirm its terminal state before clearing
   the slot.
4. If authoritative scheduler records confirm the job ended or no job was
   submitted, and all original gateway requests have finished, clear the slot
   in WebHDP by changing only the matching ordinary allocation row from
   `allocating` to `failed` in a maintenance transaction. The row must have no
   `remote_session_id` or `reservation_id`. Record the evidence and allocation ID
   in the operations log, then restart the queue and verify that the account’s
   active count drops. Keep the registry’s request intent and release receipts
   so a delayed retry can never create a second job for that identity.

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

In local storage mode, site administrators can use the operator-configured
input mount. Workstation-local deployments can also give verified users
**Mounted input access**. In **Admin
Panel → Users**, grant that capability only to accounts that can read the
shared mount. All accounts with the capability can browse the shared input
root, so mount a dedicated folder containing data intended for that group.
An institution membership and HPC Access have their own permission checks.
Users without mounted input access can still upload ZIP batches into their
own server workspace when local mode is active.

Mounted sessions also require ordinary session access. Revoking the capability
removes access to mounted-input sessions and prevents waiting scans from starting.
Previously created sessions backed by the shared mount follow the same rules.

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
