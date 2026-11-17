# WebHDP-Link production preparation

Use this guide to review and rehearse a WebHDP-Link deployment. The validator
reads only local configuration. For backups and the shared WebHDP migration
sequence, see [Upgrade to v0.1.0-alpha.3](upgrade_alpha3.md).

The existing production stack has a WebHDP API, nginx frontend and Celery worker.
Link additionally needs a persistent database-backed worker. Celery does not
consume Link jobs. The opt-in `docker-compose.webhdp-link.yml` overlay adds this
worker, shares the existing persistence, disables concurrent migration bootstrap,
pins operator-selected images and bounds container logs. It does not expose a
worker port. Keep the ordinary Celery worker for existing WebHDP tasks.

## Prepare the exact contract offline

Copy `deploy/webhdp-link.production.example.json` to a private operator-controlled
review directory. All `null` values and empty publication/grant lists must be
resolved; the template deliberately fails preflight. Do not put passwords,
tokens, signing keys or decrypted credentials in this plan. Keep secrets in the
existing private backend environment/credential store. Never paste rendered
Compose configuration into a report: it contains resolved environment values.

The template includes two example registrations for local integrations:

| Client | Exact origin | Exact callback |
| --- | --- | --- |
| `hmsm-studio` | `http://127.0.0.1:5194` | `http://127.0.0.1:5194/?webhdp=1` |
| `reprojector-desktop` | `http://127.0.0.1:5195` | `http://127.0.0.1:5195/callback/` |

These are explicit loopback exceptions for local applications, **not** proposed
public application hostnames. `localhost` and `127.0.0.1` are different origins;
register each only if the actual application uses it. A fixed desktop callback
must bind only loopback, validate state/PKCE/issuer and reject a callback for a
different pending request. Register an actual publicly hosted HMSM website with
its approved HTTPS origin and exact callback instead. No wildcard, arbitrary
port, callback fragment or preassigned OAuth response query parameter is allowed.
Keep `allow_loopback: false` for ordinary public web apps. The JSON plan's
`registration` object is the actual `POST /api/v1/link/admin/clients` request.

For this shipped nginx/Compose configuration, choose the same externally reachable
HTTPS origin for `deployment.public_base_url` and `deployment.frontend_url`.
Do not append `/api/v1/link`: discovery appends it. A separately hosted frontend
needs its own reviewed build, CORS and CSP changes; this overlay does not assume
them. Set immutable backend and frontend image references ending in
`@sha256:<digest>` from the reviewed release build. Do not reuse an old image tag
that lacks Link, the migration or the new nginx configuration.

Add one entry per publication:

```json
{
  "request_file": "publication.json",
  "sha256": "SHA256_OF_EXACT_FILE_BYTES",
  "native_inventory_file": "native-inventory.json",
  "native_inventory_sha256": "SHA256_OF_EXACT_FILE_BYTES",
  "retained_allocation_owner": "NAMED_OPERATOR_IF_RETENTION_IS_ENABLED"
}
```

Each request file is the exact admin `PublicationCreate` JSON documented in
`docs/api/webhdp-link.openapi.json`: explicit ID, native pipeline identifier and
version, file count/extensions, exposed bounded scalar parameters, execution
mode, step timeout and resource policy. Set `enabled: false` for staging. Link
pins native versions and component manifests, rejects unsafe bindings and keeps
execution policy immutable. Use a new publication ID for a version, parameter
contract or resource change; do not mutate a previously authorized publication.

The paired review inventory must match that native version:

```json
{
  "pipeline_identifier": "THE_REVIEWED_NATIVE_IDENTIFIER",
  "pipeline_version": "THE_REVIEWED_VERSION",
  "steps": [
    {
      "id": "THE_NATIVE_STEP_ID",
      "component": "THE_COMPONENT_IDENTIFIER",
      "version": "THE_COMPONENT_VERSION",
      "manifest_sha256": "SHA256_OF_THE_REVIEWED_MANIFEST",
      "adapter": "hpc_link"
    }
  ]
}
```

List every enabled native step, in order. This is an offline review inventory,
not an installer. Verify the inventory against the native registry on the target
before publishing. The validator checks hashes, request structure and policy
consistency; only the native service can verify the actual registered bindings,
component availability and effective parameter bounds. Never import the local
demo's absolute runtime paths unchanged into a deployment.

Set each client's `pipeline_ids` to only its approved publication IDs. Review
upload bytes, retained storage bytes, queued jobs and concurrency separately.
The template values are starting limits for review, not a capacity promise.
Storage must fit originals, per-run private copies, outputs and intermediate
files. One Link process executes one job at a time; worker replica count must
fit `WEBHDP_LINK_MAX_CONCURRENT_RUNS` and application limits.

For HPC publications, specify the actual approved partition, GPU type/count and
walltime. Copy only verified central principal limits into `hpc_authority` and
record the policy review reference. Never guess an account, partition or GPU
type from a prototype. The gateway remains the authority and may reject a request
even if this static review passes. Default to `retain_allocation: false` and
`reuse_retained_allocation: false` for ordinary jobs. Retention needs a named
operator. Explicit reuse is restricted to completed Link jobs, the same user and
identical frozen policy; it does not extend the original Slurm expiry. Select
walltime for the reviewed workload and the current scheduler policy.

Configure both queue waits explicitly. `WEBHDP_LINK_HPC_WAIT_SECONDS` must cover
`HPC_LINK_PARTITION_ATTEMPT_TIMEOUT_SECONDS` and any intended central fallback
sequence. Waiting does not consume the Slurm walltime. A claimed job waiting for
a GPU still occupies a Link worker slot. Monitor `progress.phase` as well as
status; `waiting_for_resources` means processing has not yet reached its native
components. Expired HTTP access tokens do not cancel accepted durable work;
revocation, account changes and disabled authorization do.

## Offline preflight

Use the existing private `.env` convention and set these additional values to
match the reviewed plan; do not source an untrusted file as shell code:

```text
WEBHDP_BACKEND_IMAGE=<reviewed immutable backend image>
WEBHDP_FRONTEND_IMAGE=<reviewed immutable frontend image>
WEBHDP_LINK_PUBLIC_BASE_URL=<approved external HTTPS origin>
FRONTEND_URL=<same approved external HTTPS origin>
WEBHDP_LINK_MAX_CONCURRENT_RUNS=<approved global limit>
WEBHDP_LINK_WORKER_REPLICAS=<approved process count>
WEBHDP_LINK_HPC_WAIT_SECONDS=<approved total resource wait>
HPC_LINK_PARTITION_ATTEMPT_TIMEOUT_SECONDS=<approved partition wait>
WEBHDP_LINK_STOP_GRACE_SECONDS=<whole-job drain bound>
```

The worker handles SIGTERM by finishing its current claimed job and then exiting.
Choose the grace period to cover resource wait plus **all** bounded native step
invocations and result finalization. For record pipelines the conservative bound
is `max_files × enabled_steps × step_timeout_seconds`; bundle pipelines use one
invocation per step. Preflight adds 300 seconds for finalization and reports the
minimum. Large data transfers may need more time than this lower bound. Drain
before upgrades; do not depend on a force-kill timeout to finish a job.

From the repository root, with an existing Python environment:

```sh
set -o pipefail
docker compose -f docker-compose.prod.yml -f docker-compose.webhdp-link.yml \
  config --format json |
  .venv/bin/python scripts/validate_webhdp_link_deployment.py \
    --plan "$LINK_REVIEW_DIR/production.json"
```

`LINK_REVIEW_DIR` is an operator-selected local review directory. Compose rendering
is client-side and starts no containers. Pipe it directly; do not use `tee`, shell
tracing or a public intermediate file. The validator uses only the Python standard
library and the pure OpenAPI description module. It imports no app, opens no
database, reads no credential file, calls no network and changes no state. Its
output contains field paths/codes, not supplied values. Exit status 1 blocks the
review on missing configuration or inconsistency. Exit status 0 means
`offline_configuration_only`; it does not prove live credentials, network, quota,
TLS or resource availability, and never authorizes deployment.

Focused verification, including a synthetic render of the real overlay:

```sh
.venv/bin/python -m pytest tests/test_webhdp_link_deployment.py -q
```

## Persistence, secrets and logs

API and Link worker must use the **identical database URL**, signing key and
credential encryption key. `WEBHDP_LINK_STORAGE_PATH` is fixed by the overlay to
`/app/instance/webhdp-link`; the existing instance mount therefore persists both
database and Link files. Both processes also share `/shared/sessions`. Configure
host directories for the non-root image user before startup. Preflight checks
rendered mounts, including a nested mount that could hide shared Link storage.

SQLite is suitable only for a modest single-host deployment on a local filesystem
with working advisory file locks. `.webhdp-registry-locks` lives beside the database
and must be shared by API and workers. Do not put separate copies of the database
or lock directory in each container. Do not scale SQLite across hosts or an
unverified network filesystem. PostgreSQL/MySQL/MariaDB registry locks use the
database's advisory-lock facilities; shared artifact storage is still required.

Use a filesystem/container-volume hard quota as well as client API quotas. The
worker accounts retained run trees and rejects over-quota outputs, but a running
trusted component can temporarily create large intermediate files. An application
quota is not a kernel-enforced runtime limit. Define disk free-space alerts and
capacity for maximum concurrency. `review_after_days` is an operator review SLA,
not an implemented automatic deletion policy: Link does not yet purge completed
run history/artifacts automatically. Delete unused original uploads through the
authorized API. For completed run data, review ownership, references, remote side
effects and backup requirements before a separately reviewed cleanup migration;
do not run a blanket `find -mtime -delete` against live storage. Keep automatic
generic session cleanup disabled for Link data until its handling has been
explicitly verified. If automatic expiry is a deployment requirement, it remains
a release prerequisite rather than a checkbox this plan can satisfy.

Reuse the existing encrypted credential system. `secret_references` names
environment variables without copying their values. Central HPC credentials
belong only to WebHDP/gateway. Zenodo sandbox credentials remain the initiating
user's active encrypted credential and are injected only into the exact approved
local sandbox component invocation. They must not be client configuration, native
parameters, image layers, remote HPC environment or artifacts. Production Zenodo
publishing is outside the sandbox prototype's authority.

Container logging uses the `local` driver with five 10 MB files per container.
Both nginx templates now log `$uri`, excluding query strings; the overlay uses
Gunicorn `%(U)s`, not the complete request line. Do not add Authorization,
Cookie, query, request body or environment dumps in an upstream proxy/APM.
The same path-only logging is needed on each integrating app's callback server.
Set equivalent bounded journal/log retention for non-Docker supervision. Restrict
operator error logs: component exceptions may include private data paths even
though the public API hides them.

## HTTPS and proxy gate

Terminate TLS on the approved public origin and keep backend/gateway management
interfaces private. Keep the dedicated `/api/v1/link/` location ahead of generic
API handling. Preserve Origin, Authorization, Idempotency-Key and bodies; forward
OPTIONS to the backend. Do not add wildcard CORS or intercept preflight. Preserve
`proxy_request_buffering off` and `proxy_http_version 1.1` together so chunked
uploads reach the authenticated byte limit without full proxy buffering. Set the
outer proxy's upload ceiling above approved file sizes plus multipart overhead.
Keep `frame-ancestors 'none'` on consent/authenticated pages, including error
responses. Public record embeds retain their separate existing policy.

The existing `scripts/verify_webhdp_link_proxy.py` tests both templates against a
loopback demo using disposable nginx containers, including denied origins,
missing authorization, consent framing and query-free access logs. It does not
validate an external production proxy. After an authorized deployment, verify
discovery issuer, exact PKCE redirect, an authenticated upload, scoped submission,
hosted progress and checksum-verified download through the **actual** HTTPS chain
before enabling general application traffic.

## Authorized rollout and recovery sequence

The following is a plan for the later authorized rollout, not a command sequence
to run during development.

1. Record the current image digests, Alembic revision, private environment and
   storage/credential backup locations. Make a consistent database **and data**
   backup and run a restore drill against an isolated directory. The existing
   `scripts/backup.py`, `scripts/restore_drill.py` and `scripts/backup_status.py`
   provide the established workflow; verify that the archive includes the Link
   instance subtree and any external data mounts. Do not assume a database-only
   backup can restore artifacts or encrypted credentials without their key.
2. Enable the existing maintenance gate for new HTTP mutations. Allow accepted
   Link jobs to finish, checking the admin queue and central allocation state.
   Do not disable clients/publications merely to drain: that withdraws existing
   job authorization. Maintenance alone does not pause worker claims. Once the
   queue has no queued/running jobs, stop Link/Celery workers, then API writers.
   Keep independently retained allocations under their explicit operator policy.
3. With writers stopped and the reviewed new image selected, run migrations once:

   ```sh
   docker compose -f docker-compose.prod.yml -f docker-compose.webhdp-link.yml \
     run --rm --no-deps -e RUN_DB_BOOTSTRAP=0 -e SKIP_DB_CREATE_ALL=1 \
     backend python -m flask --app app db upgrade
   ```

   Link migration `d9e0f1a2b345` follows GPU reservation migration
   `e1f0a2b3c456`. Alembic owns the upgrade;
   do not use `db.create_all` or automatic fallback repair to conceal drift.
   Check the target revision and all Link tables before starting processes.
   The overlay keeps startup bootstrap disabled on both API and Link worker.
4. Start the reviewed API/frontend and required ordinary services, then the Link
   worker. Keep external clients/publications disabled while verifying native
   registry pins, component installation hashes, runtime isolation and central
   principal authority. Register the reviewed disabled publication/client JSON
   through authenticated admin endpoints/UI. Test with a dedicated account and
   narrowly enabled review client; review response errors without secrets.
5. Verify the actual HTTPS flow and output bytes. Enable only the reviewed
   publications and client grants, then clear maintenance and monitor queue age,
   `waiting_for_resources`, stale claims, cleanup retries, quota failures and
   filesystem usage. `/api/v1/health` alone does not prove a Link worker is alive;
   monitor the supervisor process and active-run heartbeats/admin queue.

If a worker crashes, its abandoned claim becomes an explicit failure after the
stale threshold once the execution lock is free. It is **not replayed**: a remote
action might already have happened. Reconcile native/HPC execution and any draft
receipt first; resubmit with a new idempotency key only after the outcome is known.
Retained allocations and pending cleanup require central operator review. Do not
reset a failed run to queued or alter timestamps to manufacture recovery.

For a rollback, close new mutations and drain again. Prefer keeping the additive
Link tables and reverting the application images only if compatibility has been
verified on the restored staging copy. A schema downgrade to the preceding
revision destroys Link history and does not undo remote side effects. If necessary,
restore the matched database, private data and prior release together from the
pre-upgrade snapshot, with writers stopped. Reconcile any side effects created
after that snapshot separately; never restore an older database over live workers.

## Opt-in Singularity worker

The existing full-stack Singularity scripts neither migrate an existing database
nor supervise a Link worker, and their generic stop helper force-kills after
20 seconds. Their default behavior remains unchanged. Do not add a Link process
to that stop path or assume the sample `webhdp.sbatch` resource request is an
approved production control-plane allocation.

`scripts/hpc_singularity/remote/run_link_worker.sh` is a separate foreground
entrypoint: it takes `ROOT`, `ENV_FILE` and optionally `SIF_DIR`, uses `--cleanenv`,
does not source the environment as shell code, and executes the same worker from
the reviewed immutable `backend.sif`. It binds the existing instance, log,
session and local data directories. It submits no job, allocates no resource,
migrates no database and kills no existing PID. All required directories/images
must already exist. The API must use the same release, database URL and mounts;
the wrapper deliberately does not overlay a mutable source checkout into the SIF.

`deploy/webhdp-link-worker.service.example` is an opt-in supervisor template for
an approved persistent application-service host with Singularity and systemd.
Replace every `@...@` placeholder, set the whole-job stop bound, and configure
journal retention. It is not intended to run a daemon on an HPC login node or to
replace the site's scheduler policies. If WebHDP itself is hosted in a scheduled
allocation, establish a permitted service lifetime and graceful drain before its
walltime; use the site's approved supervisor. The central HPC-Link gateway remains
the only route from external applications to scientific GPU resources.
