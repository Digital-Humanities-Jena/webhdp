# HPC Batch Automation Workflows

This document covers unattended WebHDP batch processing on an HPC scheduler from
a shared work directory. It is cluster-neutral: queue, partition, account, GPU,
path, and node names must come from the site-specific batch configuration rather
than from this documentation.

## Overview

The HPC batch automation workflow lets an operator process a large local-mode
dataset in chunks without relying on an interactive browser session. The
operator creates a protected credential file and a batch config, runs preflight,
prepares chunk-local inputs, and then starts or resumes the orchestrator.

The orchestrator keeps a configured number of scheduler jobs active, submits each
chunk through the configured partition or queue order, waits for queued jobs up
to the configured timeout, and retries retryable scheduler failures in a later
allocation. Inside each allocation, WebHDP services start from the Singularity
deployment, the chunk is scanned into a local session, the native render pipeline
is executed through `/api/v2/pipelines/<pipeline>/execute`, and record artifacts
are audited before optional publication actions run.

Tmux is only an observation and convenience layer. Correctness comes from chunk
state files, the run event log, scheduler state, WebHDP run status, artifact
audits, and explicit recovery queues.

## Use Cases

- Process tens of thousands of local files from an HPC-shared filesystem.
- Let non-expert operators start, resume, and monitor a run with one wrapper
  command after the administrator prepares credentials and config.
- Keep two or more GPU allocations active in parallel when the site policy and
  batch config allow it.
- Move to the next configured scheduler partition or queue after a queue timeout.
- Recover chunks after scheduler timeout, node failure, out-of-memory failure,
  interrupted login shells, or stopped tmux sessions.
- Publish only records that pass configured artifact gates, while quarantining
  incomplete records with reason codes.

## Operator Configuration And Credential Handoff

Primary actor: administrator or lead operator.

Entry points:
- Protected env file, usually referenced by `env_file` in the batch config.
- Batch config JSON or YAML consumed by `webhdp_hpc_batch.py`.
- `scripts/webhdp_agent_cli.py secret-scan`
- `scripts/hpc_singularity/remote/webhdp_hpc_batch.py preflight`

Workflow:
1. Deploy or select an existing WebHDP HPC work directory.
2. Create administrator credentials or an operator token outside shell history.
3. Store runtime credentials in a chmod-600 env file.
4. Create a batch config with dataset paths, MSF path, chunk size, file
   extensions, scheduler partition or queue order, timeout policy, parallelism,
   API URLs, pipeline, publication mode, artifact requirements, and path
   mappings.
5. Run a secret scan over the intended config and logs location.
6. Run preflight with failure enabled before handing the workflow to colleagues.

Complete when:
- The config is site-specific but cluster-neutral in structure, credentials are
  not embedded in commands, and preflight passes for paths, tools, API access,
  scheduler commands, disk space, and required runtime assets.

## Chunk Preparation And State Initialization

Primary actor: operator or prepared automation wrapper.

Entry points:
- `scripts/hpc_singularity/remote/webhdp_hpc_batch.py prepare`
- `scripts/hpc_singularity/remote/webhdp_hpc_tmux.sh`

Workflow:
1. Read the MSF file and dataset directory from the batch config.
2. Match MSF rows to source files using the configured filename and optional
   source-path columns.
3. Split matched records into deterministic chunks using `chunk_size`.
4. Write chunk-local MSF files and input manifests under the configured output
   directory.
5. Initialize per-chunk JSON state files and the run-level JSONL event log under
   `state_dir`.
6. Write or refresh the preparation report used by `summary`, `resume`, and
   `report`.

Complete when:
- Every source file intended for processing belongs to exactly one chunk, chunk
  state exists, and unmatched or duplicate MSF rows are visible before compute
  allocations are requested.

## Parallel HPC Execution

Primary actor: scheduler-backed orchestrator.

Entry points:
- `scripts/hpc_singularity/remote/webhdp_hpc_tmux.sh`
- `scripts/hpc_singularity/remote/webhdp_hpc_batch.py start`
- `scripts/hpc_singularity/remote/webhdp_hpc_batch.py resume`
- `scripts/hpc_singularity/remote/webhdp.sbatch`
- `scripts/hpc_singularity/remote/start_services.sh`

Workflow:
1. Start or resume the orchestrator from `state_dir`.
2. Keep at most `max_parallel_jobs` active scheduler jobs.
3. Select the next scheduler partition or queue from the configured order and
   partition strategy.
4. Submit a chunk through the generic batch script with configured CPU, memory,
   GPU, time limit, env file, root path, and command values.
5. Wait while the job is pending, configuring, or running.
6. If a pending job exceeds `partition_queue_timeout_seconds`, cancel it and
   retry the chunk on the next configured partition or queue.
7. In the allocation, start WebHDP services and verify backend, worker,
   renderer, USDZ conversion, Redis, and validation dependencies as configured.
8. Create or refresh the chunk-local WebHDP session, prepare metadata, and start
   local scan.
9. Execute the configured native pipeline. The intended default for the large
   dataset workflow is `render`.
10. Poll `/api/v2/runs/<run_id>` until the pipeline reaches a terminal state.
11. Audit record artifacts before any publication step.
12. Mark the chunk completed, quarantined, or needing recovery in the chunk
   state file.

Complete when:
- All chunks are terminal, active scheduler jobs have drained, and `summary` or
  `report` shows completed, quarantined, or recovery-needed counts that match
  the operator's expectations.

## Monitoring, Diagnosis, And Reporting

Primary actor: operator or colleague monitoring the run.

Entry points:
- `scripts/hpc_singularity/remote/webhdp_hpc_tmux.sh`
- `scripts/hpc_singularity/remote/webhdp_hpc_batch.py monitor`
- `scripts/hpc_singularity/remote/webhdp_hpc_batch.py summary`
- `scripts/hpc_singularity/remote/webhdp_hpc_batch.py diagnose`
- `scripts/hpc_singularity/remote/webhdp_hpc_batch.py report`
- Scheduler commands such as queue inspection and job log tailing.

Workflow:
1. Attach to the tmux session or run read-only status commands.
2. Watch scheduler state, service status, orchestrator logs, chunk state, and
   recent event-log entries.
3. Use `diagnose` for next-action hints when chunks stop progressing.
4. Use `report` to export a run-level JSON and CSV summary for handoff or audit.

Complete when:
- Operators can tell which chunks are active, completed, queued, retrying,
  quarantined, or waiting for manual recovery without inspecting source code.

## Recovery And Publication Control

Primary actor: operator.

Entry points:
- `scripts/hpc_singularity/remote/webhdp_hpc_batch.py recover`
- `scripts/hpc_singularity/remote/webhdp_hpc_batch.py resume`
- Session batch-operation APIs for draft creation, upload, publication, and
  cleanup.

Workflow:
1. Treat scheduler `TIMEOUT`, `NODE_FAIL`, `OUT_OF_MEMORY`, `FAILED`,
   `PREEMPTED`, `CANCELLED`, and queue timeout states as retryable unless the
   chunk has reached the configured retry limit.
2. Treat artifact-gate failures as record-level quarantine unless the operator
   explicitly changes the recovery queue.
3. Resume interrupted orchestration from state files rather than tmux state.
4. Publish only records that passed the artifact audit.
5. Keep `publish_mode` as `none` for validation runs, then move to `drafts`,
   `upload`, or `publish` only after credentials, metadata, and artifact gates
   have been verified.
6. Rotate or revoke shared operator credentials after the run.

Complete when:
- Retryable chunks have been resubmitted, ineligible records have reason-coded
  quarantine files, and publication actions have run only for eligible records.

## Prerequisites And Permissions

- A deployed WebHDP HPC work directory with the required Singularity images and
  remote scripts.
- Scheduler access for the operators who will submit jobs.
- Permission to request the configured CPU, memory, GPU, wall-time, partition,
  queue, project, or account resources.
- Writable shared paths for input chunks, output artifacts, state files, logs,
  and service runtime files.
- A valid WebHDP administrator credential or operator token stored in a protected
  env file.
- Access to the intended Zenodo environment when publication modes beyond
  `none` are used.
- Runtime tools required by the selected pipeline, including renderer, USDZ
  conversion, FFmpeg tools when needed, Redis, and the local EDM validator when
  artifact validation is required.

## Inputs, Outputs, And State

| Input | Output | State To Watch |
|---|---|---|
| Batch config JSON/YAML | Scheduler submissions and chunk-local commands | configured partition order, `max_parallel_jobs`, queue timeout, retry limits |
| Dataset directory and MSF file | Chunk MSFs, manifests, and preparation report | unmatched files, duplicate filenames, chunk count |
| Protected env file or token file | Authenticated API calls | file permissions, credential expiry, redacted logs |
| WebHDP API and native pipeline | Session records, pipeline runs, artifacts | task IDs, run IDs, terminal statuses |
| Artifact requirements | Completion, quarantine, or recovery queue | missing USDZ, PNG, EDM, METS/MODS, IIIF, or validation artifacts |
| Optional publication mode | Draft, upload, or publish batch operations | eligible record list, Zenodo status, failed batch actions |

## Failure And Recovery

- If preflight fails, fix the reported path, credential, tool, disk, scheduler, or
  API issue before requesting compute allocations.
- If preparation finds unmatched or duplicate files, repair the MSF or mapping
  configuration before starting the orchestrator.
- If a job stays queued beyond the configured timeout, the orchestrator cancels
  it and retries according to the partition strategy.
- If a scheduler allocation fails in a retryable state, resume creates a fresh
  allocation for the chunk until retry limits are reached.
- If an API run fails or is cancelled, the chunk enters recovery with the run
  reason code.
- If artifact audit fails, the affected records are quarantined and the chunk is
  not considered publishable until the operator resolves the recovery queue.
- If tmux or the login shell is interrupted, rerun `resume` or the tmux wrapper;
  state files remain the source of truth.

## Optimization Targets

- Choose `chunk_size` so a single chunk finishes comfortably within the scheduler
  wall-time on the slowest expected GPU allocation.
- Set `max_parallel_jobs` to match site policy, expected GPU availability, API
  capacity, and filesystem throughput.
- Put the most appropriate scheduler partitions or queues first, but keep the
  order configurable per site.
- Use `partition_queue_timeout_seconds` long enough to avoid unnecessary churn
  but short enough to move away from congested queues.
- Keep artifact gates strict for production publication and looser only for
  controlled smoke tests.
- Keep publication disabled until render output, metadata, Zenodo credentials,
  and record eligibility are verified on a small chunk.

## Verification Checklist

- The batch config has no site-specific placeholder values and explicitly names
  the intended partitions or queues.
- The protected env file is chmod 600 and does not appear in shell history or
  committed files.
- `preflight --fail` passes from the shared work directory.
- `prepare` creates the expected chunk count and reports no unexplained
  unmatched files.
- A small smoke chunk completes local scan, native render pipeline execution,
  run polling, and artifact audit before the full dataset starts.
- `summary`, `diagnose`, and `report` work without mutating chunk state.
- Queue timeout behavior has been tested with a short timeout in a non-production
  config.
- Publication mode is intentionally selected and credential rotation is planned
  after the run.

Related docs:
- `docs/workflows/publication-upload-msf.md`
- `docs/workflows/pipelines-components-playground.md`
- `docs/workflows/sessions-records-provenance.md`
- `docs/workflows/hpc-cloud-storage.md`
- `docs/workflows/developer-operator-scripts.md`

## Codebase Starting Points

- Generic batch orchestrator: `scripts/hpc_singularity/remote/webhdp_hpc_batch.py`
- Tmux observer wrapper: `scripts/hpc_singularity/remote/webhdp_hpc_tmux.sh`
- Scheduler job wrapper: `scripts/hpc_singularity/remote/webhdp.sbatch`
- Remote service lifecycle: `scripts/hpc_singularity/remote/start_services.sh`, `scripts/hpc_singularity/remote/status_services.sh`, `scripts/hpc_singularity/remote/stop_services.sh`
- Agent API CLI: `scripts/webhdp_agent_cli.py`
- Native pipeline API: `routes/native_pipeline_routes.py`
- Session batch operations: `routes/session_batch_operations_routes.py`
