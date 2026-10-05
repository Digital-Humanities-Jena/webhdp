# Developer And Operator Script Workflows

This document covers repository-executable workflows that are not always exposed
through the WebHDP UI, but are part of the operational and developer workflow
surface.

## Overview

These workflows are for people working directly with the repository or an
operator shell. They cover local diagnostics, contract checks, fixture-backed
smoke tests, release checks, maintenance jobs, agent operations, and HPC scripts.
Read the workflow summaries first; the bottom sections identify what to verify
and where optimization work should start.

## Use Cases

- Bootstrap or diagnose a developer environment before changing workflow code.
- Run fixture-backed smoke tests for upload, render, `.hdpc`, and pipeline behavior.
- Prepare release, image, API, docs, and maintenance checks.
- Locate operator scripts used for HPC deployment, unattended batch processing,
  legacy dataset-specific chunking, and agent workflows.

## Developer Status And Onboarding Checks

Primary actor: developer or maintainer.

Entry points:
- UI: `/developer`
- API: `/api/v1/developer/status`
- Make: `make doctor`
- Make: `make docs-check`
- Make: `make api-contract-check`
- Make: `make hdp-components-check`
- Make: `make golden-workflow`
- Make: `make verify-onboarding`

Workflow:
1. Check developer access and repository status.
2. Run environment diagnostics.
3. Validate docs catalog and API contract freshness.
4. Validate HDP component manifests.
5. Run the fixture-backed golden workflow.

Complete when:
- Onboarding checks pass and local development prerequisites are confirmed.

## Golden Sample Workflow

Primary actor: developer or CI.

Entry points:
- Script: `scripts/run_golden_workflow.py`
- Make: `make golden-workflow`

Workflow:
1. Load fixture manifest from `test_data/workflow_fixtures/manifest.json`.
2. Scan the curated fixture set.
3. Create a temporary `.hdpc` project.
4. Inspect records and verify expected primary files.
5. Match the minimal MSF against the expected files.

Complete when:
- The script reports success with expected record count and matched MSF rows.

## API And Documentation Contract Workflows

Primary actor: developer or CI.

Entry points:
- Script: `scripts/generate_openapi.py`
- Script: `scripts/check_openapi_fresh.py`
- Script: `scripts/check_developer_docs.py`

Workflow:
1. Generate the OpenAPI contract from Flask routes.
2. Check whether the committed contract is stale.
3. Validate developer docs and docs catalog references.

Complete when:
- Generated API and docs checks pass.

## Agent API CLI

Primary actor: automation client or developer.

Entry points:
- Script: `scripts/webhdp_agent_cli.py`

Supported command workflows:
- login
- health
- local-msf
- sessions and session detail
- workflow-state
- metadata
- upload operations and upload operation detail
- resume-session
- records and record detail
- provenance
- submissions and submission detail
- submission progress and monitor-submission
- renderer-status
- storage-status
- execute-render

Workflow:
1. Authenticate or provide a token.
2. Call the selected API-backed command.
3. Print JSON or human-readable results for automation.

Complete when:
- The command exits successfully or reports the API error.

## Operator Backup, Readiness, Release, And Maintenance Scripts

Primary actor: operator.

Entry points:
- `scripts/backup.py`
- `scripts/backup_status.py`
- `scripts/list_backups.py`
- `scripts/prune_backups.py`
- `scripts/restore_backup.py`
- `scripts/restore_drill.py`
- `scripts/readiness_check.py`
- `scripts/release_check.sh`
- `scripts/check_release_images.py`
- `scripts/maintenance.py`
- `scripts/wait_for_celery_drain.py`
- `scripts/cleanup_legacy_workflow_state.py`
- `scripts/validate_hdp_components.py`

`scripts/release_check.sh` always runs core Chromium/Firefox workflow tests and the isolated backend browser suite. Install both Playwright browsers first. `RUN_E2E=true` additionally runs the complete browser suite.

Workflow:
1. Check readiness or release state.
2. Run backup, restore, or retention operations.
3. Drain queues before maintenance.
4. Clean legacy workflow state when required.
5. Validate component manifests before release.

Complete when:
- The script reports success and any generated status output is reviewed.

## Render And Batch Smoke Scripts

Primary actor: developer or operator.

Entry points:
- `scripts/render_pipeline_smoke.py`

Workflow:
1. Authenticate against a running WebHDP instance.
2. Create or select a session.
3. Execute render or batch pipeline smoke behavior.
4. Verify records and outputs.

Complete when:
- The smoke script reaches its expected terminal success state.

## Zenodo Historical Backfill And CSV Community Scripts

Primary actor: operator.

Entry points:
- `scripts/launch_zenodo_historical_backfill.py`
- `scripts/monitor_zenodo_historical_backfill.py`
- `scripts/execute_zenodo_community_append_from_csv.py`
- `scripts/export_hunt_dataset_records.py`

Workflow:
1. Launch a historical account backfill or inspect its progress.
2. Execute community append operations from a CSV action plan when needed.
3. Export selected dataset records for offline audit or migration.

Complete when:
- Backfill, append, or export results are written and verified.

## HPC Singularity Deployment And Remote Operation Scripts

Primary actor: HPC operator.

Entry points:
- `scripts/hpc_singularity/build_export_archives.sh`
- `scripts/hpc_singularity/transfer_archives.sh`
- `scripts/hpc_singularity/sync_remote_scripts.sh`
- `scripts/hpc_singularity/install_sif_on_hpc.sh`
- `scripts/hpc_singularity/install_optional_frontend.sh`
- `scripts/hpc_singularity/deploy_all.sh`
- `scripts/hpc_singularity/remote/start_services.sh`
- `scripts/hpc_singularity/remote/status_services.sh`
- `scripts/hpc_singularity/remote/stop_services.sh`
- `scripts/hpc_singularity/remote/restart_fast_renderer_in_job.sh`
- `scripts/hpc_singularity/remote/benchmark_fast_renderer.sbatch`
- `scripts/hpc_singularity/remote/install_ffmpeg8_tools.sh`
- `scripts/hpc_singularity/remote/patch_local_edm_validator_jar.sh`
- `scripts/hpc_singularity/remote/webhdp.sbatch`
- `scripts/hpc_singularity/remote/webhdp_hpc_batch.py`
- `scripts/hpc_singularity/remote/webhdp_hpc_tmux.sh`

Workflow:
1. Build and transfer deployment archives.
2. Install SIF images and optional frontend assets.
3. Sync remote scripts.
4. Start, stop, or inspect remote WebHDP services.
5. Benchmark or restart renderer services in job context.
6. Prepare and resume generic chunked batch runs.
7. Patch or install supporting tools when required by the deployment.

Complete when:
- Remote services and runtime assets match the intended deployment state.

## Generic HPC Batch Scripts

Primary actor: HPC operator.

Entry points:
- `scripts/hpc_singularity/remote/webhdp_hpc_batch.py`
- `scripts/hpc_singularity/remote/webhdp.sbatch`
- `scripts/hpc_singularity/remote/webhdp_hpc_tmux.sh`

Workflow:
1. Prepare chunk definitions.
2. Run chunk processing.
3. Orchestrate multi-chunk execution with scheduler or tmux helpers.
4. Resume failed chunks from checkpoint state.

Complete when:
- Chunk outputs and recovery state show the intended processing result.

## Prerequisites And Permissions

- Developer checks require a local repository checkout with backend and frontend dependencies installed.
- Release and image checks require the container, registry, or build tooling used by the deployment.
- Agent CLI workflows require valid WebHDP credentials and network access to the target API.
- HPC scripts require remote shell access, SIF/image artifacts, and environment variables expected by the HPC runbooks.

## Inputs, Outputs, And State

| Input | Output | State To Watch |
|---|---|---|
| Local environment and fixture data | Doctor, docs, API, component, and golden workflow reports | dependency versions, generated OpenAPI, fixture outputs |
| Agent CLI command | JSON API response or workflow action | token file, base URL, selected session or record IDs |
| Release and maintenance commands | Readiness, image, queue, or maintenance report | git version, image tags, Celery queue depth |
| HPC scripts and chunk plans | Remote services, chunk outputs, recovery checkpoints | remote state files, logs, chunk manifests |

## Failure And Recovery

- Failed doctor or onboarding checks should be fixed before deeper workflow debugging.
- Failed API or docs freshness checks usually require regenerating OpenAPI or updating docs registration.
- Failed golden or render smoke tests should be traced through upload, `.hdpc`, and pipeline output state.
- Failed HPC batch runs should resume from checkpoint files rather than reprocessing completed chunks.

## Optimization Targets

- Keep smoke workflows fast enough for routine maintainer use.
- Reduce duplicate setup logic across scripts and Make targets.
- Improve CLI output consistency for automation agents.
- Keep HPC scripts resumable, observable, and conservative with remote state.

## Verification Checklist

- Run doctor, docs catalog, API contract, component validation, and golden workflow checks.
- Verify agent CLI login, session inspection, records, provenance, and render execution commands.
- Run release/readiness checks before deployment work.
- Confirm HPC service start/status/stop and chunk recovery scripts in a controlled environment.

Related docs:
- `docs/development/golden_workflow.md`
- `docs/guides/operations_and_setup_guide.md`
- `docs/workflows/hpc-batch-automation.md`

## Codebase Starting Points

- Developer status route: `routes/developer_routes.py`
- Local diagnostics: `scripts/doctor.py`, `scripts/check_developer_docs.py`, `scripts/check_openapi_fresh.py`
- Golden and smoke workflows: `scripts/run_golden_workflow.py`, `scripts/render_pipeline_smoke.py`
- Release and maintenance scripts: `scripts/release_check.sh`, `scripts/check_release_images.py`, `scripts/maintenance.py`
- Agent CLI: `scripts/webhdp_agent_cli.py`
- HPC deployment scripts: `scripts/hpc_singularity/`
- ScanTheWorld remote scripts: `scripts/hpc_singularity/remote/`
