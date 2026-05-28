# Zenodo Account Deep Retrieval

This guide explains the Tools feature for retrieving all records visible to a selected Zenodo API key and storing them as persistent retrieval-generated `.hdpc` collections backed by shard sessions.

## Purpose

Zenodo Account Retrieval is for accounts that already contain records outside WebHDP, or for accounts where WebHDP needs a durable local inventory before duplicate review, provenance inspection, or explorer-only browsing.

The feature retrieves:
- published depositions
- draft depositions
- all versions returned by Zenodo for the selected credential

It does not upload, publish, edit, delete, or version Zenodo records. Generated sessions are read-only explorer sessions.

## Where To Find It

In the WebHDP UI, open:

```text
Tools -> Zenodo Account Retrieval
```

The page shows:
- accessible named Zenodo credentials
- the credential environment, either Sandbox or Production
- retrieval mode, including full inventory, historical backfill, and incremental sync
- execution preflight for the WebHDP worker and HPC handoff checks
- a fixed scope of published records plus drafts
- an optional maximum record limit
- optional created-after and created-before filters
- runtime knobs for initial window size, request retries, and request timeout
- full or incremental retrieval mode
- the latest successful collections for the selected credential
- current job progress
- throughput, duplicate, latest-record, and stale-worker diagnostics
- pause, resume, cancel, and explicit delete controls
- generated shard sessions with links to their Records views
- collection search, export, compaction, retention, and incremental schedule controls

## Credential Rules

The selected credential must be one the current user can access:
- an owned personal Zenodo key
- an accepted shared user key
- an institution key available through the user's workspace context

Tokens are decrypted only inside the backend task. WebHDP sends them to Zenodo as `Authorization: Bearer ...` headers and never writes cleartext tokens to URLs, logs, task history, API responses, screenshots, or `.hdpc` files.

## Retrieval Strategy

Zenodo result windows can be limited for broad searches, so WebHDP does not rely on one unbounded request for the whole account. The retrieval task uses authenticated:

```text
GET /api/deposit/depositions
```

with:
- `status=published` and `status=draft` harvested separately
- `all_versions=1`
- `size=100`
- created-date query windows

The runner preflights windows, splits dense ranges, and harvests page by page. If a broad date window is too large, it is split into smaller date or datetime windows; dense edge cases can fall back to record-ID partitioning. This is what allows account-level retrieval beyond 10,000 records while staying within Zenodo's practical search-window constraints.

During live production verification, Zenodo returned generic `400 BAD REQUEST` responses once a dense window crossed the practical page boundary. WebHDP treats page-boundary `400`/`422` responses as a signal to split the current window and continue, instead of failing the whole retrieval. This behavior is essential for accounts with dense record clusters in a short date range.

The current rate budget is conservative:

```text
30 requests per minute or less
100 records per page
```

The task also respects `Retry-After` and rate-limit reset signals when Zenodo asks the client to wait.

## Historical Backfill And Preflight

Historical backfill mode is for filling known coverage gaps, such as retrieving records before the end date of a previous inventory. It stores the requested date window, source collection hints, runtime options, and preflight report with the retrieval job so the resulting shard tree can be understood later without operator notes.

Before starting a large run, use Preflight. The report checks credential access,
token-handling expectations, selected execution target, date-window coverage,
and operational warnings. HPC execution is surfaced as a preflight target
because it may need explicit operator control over site-specific proxy and
network settings. The WebHDP worker target is queueable directly from the UI;
HPC runs should use the preflight report as the launch checklist until the
dedicated HPC runner is wired into the app.

The live diagnostics intentionally expose split-window counts, deferred windows, wait seconds, records/pages per hour, and ETA confidence. ETA is an operational estimate, not a promise: it can rise when the job enters a dense date cluster, waits on rate limits, retries transient Zenodo errors, or spends time skipping duplicates created by overlapping split windows.

## Record Limits

The UI provides an optional maximum record limit. Leave it blank to retrieve all accessible records. Set a limit for live proof runs, operational sampling, or intentionally bounded inventories.

Limits are stored in the job manifest and checkpoint. When the limit is reached, the job finishes successfully with `limit_reached: true`.

The backend ceiling is currently `1,000,000` records per job.

## Incremental Retrieval

After a successful full or bounded retrieval exists for a credential and environment, a new retrieval can run in incremental mode. Incremental mode finds the latest successful collection for that same credential/environment, reads its latest retrieved record timestamp, subtracts the configured overlap, and starts the next job from that calculated date.

The overlap defaults to `24` hours and can be set from `0` to `168` hours. It deliberately rechecks a short recent window so late Zenodo updates are not missed. Duplicate records from that overlap are skipped by the retrieval dedupe state and counted in the job diagnostics.

If a specific parent collection should be used, the API accepts `parent_retrieval_id`; otherwise WebHDP selects the latest successful collection visible to the current user for the same credential and environment.

## Pause, Resume, and Cancel

Pause and cancel are cooperative:
- pause finishes the current page/window checkpoint and stops at a resumable boundary
- resume requeues the same retrieval ID and continues from the saved checkpoint
- cancel requests a controlled stop and preserves already generated shard sessions

The checkpoint contains progress and deduplication state, but public API responses replace the internal dedupe set with a count so large jobs do not expose heavy internal state.

If the worker process is interrupted externally, for example by network loss or terminal shutdown, the persisted job may still show `PROGRESS` even though no process is alive. In that case, use the same retrieval's Resume action after connectivity is restored. The runner reads the saved checkpoint, keeps the existing dedupe set, and continues with the remaining pending windows. Public job payloads also include heartbeat/stale diagnostics so the UI can warn when a progress state has not been updated recently.

## Collection And Storage Model

Retrieval output is represented as a collection manifest plus multiple `.hdpc` shards.

Each shard is a completed `Session` with:
- `origin_type="zenodo_deep_retrieval"`
- `access_mode="explorer_only"`
- a normal session directory containing `session.hdpc`

This means existing Records, Explorer, and `.hdpc` download behavior works without a separate storage system. The generated files remain available until the retrieval job is explicitly deleted.

Shard files are capped by the shard policy, currently about 5,000 records per shard or one completed leaf window. For page-level checkpoint durability, dense windows may produce smaller shard files.

Each completed collection tracks aggregate information such as total records, shard count, duplicate-skipped count, latest created/modified timestamps, sync mode, parent retrieval ID, export metadata, retention policy, and incremental schedule settings.

## `.hdpc` Semantics

Retrieval-generated records are intentionally marked differently from upload-session records:
- `zenodo_records.record_origin = "zenodo_retrieval"`
- `zenodo_record_snapshots.snapshot_stage = "account_retrieval_deposition"`
- `record_files_map` rows are created only from file metadata returned by Zenodo
- `project_configuration` contains retrieval keys such as `retrieval.kind`, `retrieval.id`, `retrieval.shard_index`, `retrieval.environment`, `retrieval.window`, and `retrieval.manifest`

The stored provenance includes the retrieval ID, shard index, date window, environment, requesting user identity, credential identity and ownership relation, deposition owner information when returned by Zenodo, and whether edit/version action links were present. Edit/version capability is inferred from authenticated deposition access and returned action links; WebHDP does not perform write probes during account retrieval.

## Explorer-Only Behavior

Generated shard sessions are meant for inspection, not publishing.

In the Records view they are labelled:
- `EXPLORER-ONLY`
- `ZENODO RETRIEVAL`

Workflow and publishing actions are read-only or ineligible. Users can inspect record metadata, open Zenodo links, export JSON, download the session `.hdpc` according to normal session access rules, and use the cross-session explorer.

## Search, Export, And Compaction

Completed retrieval collections can be searched from Tools without opening each shard. Search supports free-text matching plus status and edit-capability filters, returning collection records across generated shard sessions.

The collection can also be exported as:
- `manifest`: JSON summary of the collection, shards, provenance, and settings
- `csv`: tabular record inventory for audit or spreadsheet review
- `archive`: ZIP export of the generated shard files

For large runs that produce many small shards, the Tools page can create a compacted shard set with a target record count per compacted shard. Compaction is an additional collection maintenance step; it does not change the original retrieval provenance. The retention controls record whether original shards and/or compacted shards should be kept. Compacted shards can be deleted separately when they are no longer needed.

## Incremental Scheduling

A successful collection can store an incremental schedule:
- frequency: `daily`, `weekly`, or `monthly`
- overlap hours: `0` to `168`
- optional maximum records per scheduled run

Scheduled runs are incremental child retrievals of the completed parent collection. Operators can trigger a configured schedule immediately from the Tools page or by calling the run-now API. Background schedule execution is handled by the Celery task `execute_due_zenodo_account_retrieval_schedules`; production deployments should wire that task into Celery Beat or an equivalent operator-controlled scheduler.

## Deletion

Deleting a retrieval job from the Tools page explicitly removes generated shard sessions/files and deletes the persisted job history entry. This is the cleanup path for retrieval-generated `.hdpc` files.

Do not use generic session cleanup as the primary control for retrieval output. Retrieval shards are intentionally persistent until explicit deletion.

## Operational Notes

For large production accounts:
- start with a small `max_records` value to confirm credential scope and UI behavior
- remove the limit or raise it only after the small run succeeds
- expect runtime to be dominated by Zenodo rate limits, not local write speed
- monitor rate-limit wait counts and generated shard counts
- expect duplicate-skipped counts to rise after a dense window is split or a job is resumed; this is normal and prevents duplicate shard entries
- use incremental mode for follow-up inventories after the first successful collection
- compact only when the generated shard count is operationally inconvenient; keeping shards separate preserves the natural retrieval and checkpoint boundaries
- if the frontend is served from a different origin than the backend, ensure CORS allows `PATCH` so schedule and retention controls can save

Live production verification on April 30, 2026 completed a full account retrieval with:
- `83,657` total records
- `41,828` published records
- `41,829` draft records
- `848` generated `.hdpc` shards
- `11` adaptive dense-window splits
- `80,001` duplicate records skipped during split/resume overlap
- `0` pending windows and final state `SUCCESS`

This confirms that the windowed strategy can cross the account-level 10,000-record concern and complete a large production account retrieval. Runtime still scales with account size, response latency, dense-window overlap, and Zenodo rate-limit waits.

## Related Documentation

- [Zenodo API Keys](zenodo_api_keys.md)
- [Security and Credentials](security_and_credentials.md)
- [Metadata And Retrieval Walkthroughs](video_guides/metadata_and_retrieval.md)
- [WebHDP API Reference](../api/webhdp_api_reference.md)

## Related API

The REST surface is documented in `../api/webhdp_api_reference.md`:
- `GET /api/v1/tools/zenodo-account-retrieval/context`
- `POST /api/v1/tools/zenodo-account-retrieval/jobs`
- `GET /api/v1/tools/zenodo-account-retrieval/jobs`
- `GET /api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>`
- `GET /api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>/records`
- `POST /api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>/pause`
- `POST /api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>/resume`
- `POST /api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>/cancel`
- `POST /api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>/compact`
- `DELETE /api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>/compacted-shards`
- `PATCH /api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>/retention`
- `PATCH /api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>/schedule`
- `POST /api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>/schedule/run-now`
- `GET /api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>/export/manifest`
- `GET /api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>/export/csv`
- `GET /api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>/export/archive`
- `DELETE /api/v1/tools/zenodo-account-retrieval/jobs/<retrieval_id>`
