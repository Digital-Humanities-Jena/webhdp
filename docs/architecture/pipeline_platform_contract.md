# Pipeline Platform Contract

## Official platform

WebHDP officially supports the native pipeline/component platform.

Supported core capabilities:

- native component listing, validation, and import
- native pipeline definition validation and versioning
- native pipeline execution
- native playground execution
- compatibility wrappers for older WebHDP pipeline routes backed by the native platform

## Supported native surfaces

- `/api/v2/components`
- `/api/v2/components/validate`
- `/api/v2/components/import`
- `/api/v2/pipelines`
- `/api/v2/pipelines/validate`
- `/api/v2/pipelines/<identifier>/versions`
- `/api/v2/pipelines/<identifier>/readiness`
- `/api/v2/pipelines/<identifier>/execute`
- `/api/v2/runs/<run_id>`
- `/api/v2/runs/<run_id>/recovery`
- `/api/v2/sessions/<session_id>/records/<record_id>/derivatives`
- `/api/v2/playground/execute`
- `/api/v2/playground/runs/<run_id>`

## Compatibility surfaces

These remain supported as wrappers over the native platform:

- `/api/v1/pipelines`
- `/api/v1/pipelines/<identifier>`
- `/api/v1/pipelines/<identifier>/execute_on_local_files`
- `/api/v1/pipelines/executions/<execution_uuid>/status`

## Submission readiness

`POST /api/v2/pipelines/<identifier>/readiness` requires session edit permission
and a mutable session. It accepts the execution selection (`session_id` and
`local_file_paths`, `record_ids`, or `execution_items`), `is_sandbox`,
`abort_on_critical_error`, and optional `expected_version`. It returns HTTP 200
for a completed check, including a blocked result, with `ready`, `blockers`,
`unverified`, selected/skipped counts, scope, pipeline version, and a signed
`readiness_token` when ready. Blockers carry an existing workflow `route` and
optional source/step labels. The token contains hashes rather than source paths
or descriptive metadata.

The check is read-only and invokes no remote service, subprocess, or allocation.
Source resolution and component contracts are shared with execution. Known
local failures block; inputs produced by earlier steps and remote requirements
are deferred explicitly. Generated exports retain their separate validation and
upload-eligibility checks.

Native synchronous and asynchronous execution repeat readiness for new requests.
`readiness_token` is optional for compatibility callers but, when supplied, must
match current state and be at most one hour old. Blockers return HTTP 400 with
`error.details.readiness`; invalid, expired, or changed tokens return HTTP 409
with `error.details.readiness_stale`. Accepted identical `request_id` retries
reconnect to the persisted run before these checks. Queued workers retain the
pipeline version and metadata snapshot and check saved source hashes before
registration. Private readiness state is excluded from run API payloads.

The guided workflow uses `?stream=1` for newline-delimited JSON. Progress events
contain `type: "progress"`, `checked`, and `total`; the terminal result contains
`type: "result"` and the public `report`. An error or missing terminal result
leaves readiness unverified. Clients can cancel obsolete checks. Reverse proxies
must allow streaming; `X-Accel-Buffering: no` is supplied for Nginx. Ordinary JSON
responses remain available without this query parameter.

Each check loads the record inventory once and indexes it by dataset, environment
and session/record. Indexing preserves the existing duplicate/version rules.
Source and artifact bytes are hashed again on every new check and before reuse;
there is no cross-request shortcut based only on size or modification time.
`scripts/benchmark_submission_readiness.py` measures the HTTP path offline. With
376-byte GLBs and 10,000 synthetic unrelated inventory entries, 10/100/1,000
sources took 0.047/0.132/1.239 seconds on the local development machine, with one
inventory load per check. These measurements exclude real inventory I/O and
large-file hashing throughput.

## Durable continuation and outcomes

Record registration and completed steps are committed before the next external
call. A private checkpoint journal in `PipelineRun.request_json` stores pinned
component/profile/configuration signatures, resolved input hashes, output
hashes and record state. Public partial results survive worker interruptions.
No database migration is required, and the journal is excluded from API output.

`GET /api/v2/runs/<run_id>/recovery` requires edit access to a mutable session.
It returns the original pipeline version, destination, eligible existing record
IDs and blocked records with review routes. Continue with the same execution
endpoint using `resume_from_run_id`, `record_ids`, and the returned session and
environment. Ordinary readiness and reservation rules still apply. Completed
records are excluded, except when an arbitrary batch component requires its
complete original group. Every blocked batch member must be resolved first.
Original selected paths are retained separately from metadata-resolved asset
paths. Recovery reports sources and existing record IDs whose registration
never finished; either gap blocks continuation of an arbitrary batch component.

A successful step is reused only if its pinned signature and every recorded
output hash match. Changed inputs, parameters or outputs invalidate that step
and dependent steps. Reuse preserves current record metadata and replays the
configured output actions. Arbitrary batch computations rerun with original
membership; record-local renderer outputs can be reused. Zenodo and linked
metadata steps use their existing idempotent record handlers and validation
journals. Uncertain remote operations and interrupted active HPC allocations
block continuation until reviewed. Recovery planning does not contact Draco.

Runs include compact `outcomes`: per-record processing/publication states, named
step results, warnings and next actions. An unreadable current project leaves
publication state unknown without hiding historical processing results. Session
Records lists recent runs, `/runs/:runId` shows native history, and technical JSON
is collapsed beneath the actionable results.

## Geometric detail review

Record details compare the exact source supplied to the geometric LOD step with
high, medium and low outputs. The source may be an upstream normalized derivative.
The list endpoint requires view access and returns a complete, checksum-verified
report. Models are served by
`GET /api/v2/sessions/<session_id>/records/<record_id>/derivatives/<step_run_id>/<level>`
for `source`, `high`, `medium`, or `low`. Step/record/session mismatches are rejected.
Files must resolve inside the session, including through symlinks; changed or
unverifiable content returns HTTP 409. The browser verifies transferred SHA-256
hashes and sizes before display and releases stale comparison URLs on changes.
Older runs without verified journals require regeneration before comparison.

## Retired HDP-Server families

- Legacy component-manager API
  Replacement: `/api/v2/components`, `/api/v2/components/validate`, `/api/v2/components/import`

- Legacy component-runner server API
  Replacement: `/api/v2/pipelines/<identifier>/execute`, `/api/v2/playground/execute`

- Legacy pipeline-manager API
  Replacement for supported workflows:
  - `/api/v2/pipelines`
  - `/api/v2/pipelines/validate`
  - `/api/v2/pipelines/<identifier>`
  - `/api/v2/pipelines/<identifier>/versions`
  - `/api/v2/pipelines/<identifier>/execute`
  - `/api/v2/runs/<run_id>`
  - `/api/v1/pipelines`
  - `/api/v1/pipelines/<identifier>`
  - `/api/v1/pipelines/<identifier>/execute_on_local_files`
  - `/api/v1/pipelines/executions/<execution_uuid>/status`
  Explicitly retired rather than ported:
  - `/pipelines/import`
  - `/pipelines/<identifier>/export`
  - `/pipelines/<identifier>/metadata_mapping`

- Legacy CLI HTTP route
  Replacement: import a manifest-backed component and execute it through the native platform

- Generic HDP-Server settings/utils API families
  Replacement:
  - `/api/v1/admin/pipelines/<pipeline_id>/config`
  - `/api/v1/admin/zenodo-community-config`
  - `/api/v1/admin/storage-config`
  - `/api/v1/admin/modality-config`
  - `/api/v1/admin/storage-status`
  - `/api/v1/tools/context`
  - `/api/v1/tools/hpc-diagnostics`
  - `/api/v1/health`

## Notes

- Native adapters may still launch local CLI, container CLI, or legacy python entrypoints.
- Those execution profiles are supported only through the native component platform, not through standalone HDP-Server management APIs.
- The old HDP-Server pipeline manager family is not considered a parity target anymore; only the native replacement surfaces above are supported.
