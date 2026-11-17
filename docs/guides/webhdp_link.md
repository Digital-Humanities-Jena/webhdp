# WebHDP-Link

WebHDP-Link lets a web application submit data to an operator-approved pipeline
on a central WebHDP installation. WebHDP owns the compute runtime, component
installation, file staging, queue, and result storage. The integrating application
never receives SSH, scheduler, HPC-Link, cloud-provider, or Zenodo credentials.

## Integration contract

The versioned API is `/api/v1/link`. Its discovery document is
`GET /api/v1/link/discovery`; the separately maintained OpenAPI 3.1 contract is
`GET /api/v1/link/openapi.json`. Only explicitly published pipelines are available.
A publication pins a native pipeline version and its component versions, declares
allowed file extensions/counts and scalar parameters, and exposes a sanitized
step graph. Pipeline commands, runtime paths and internal configuration stay on
the server. Unsupported pipeline constructs fail publication validation.

Link creates a private execution session and invokes the registered native
pipeline. External
applications provide opaque upload identifiers and typed parameter values.
They cannot submit paths, commands, execution profiles or arbitrary pipeline
configurations. Component authors remain trusted operators: execute untrusted
processing tools in appropriately isolated containers or an HPC runtime.

## Operator workflow

1. Install and validate HDP Components and publish a native pipeline through
   the existing component and pipeline tools.
2. Open **WebHDP-Link** in the administrator navigation. Publish a selected
   pipeline version with its public input contract and selected parameter bounds.
3. Register each application with exact browser origins and exact callback URLs.
   Allow only the required pipeline publications and set storage, upload and
   queue limits. Use HTTPS outside loopback development.
4. Run the Link worker against the same database and storage as the web process.
   Keep the regular WebHDP worker for existing submission workloads.
5. Monitor Link jobs and revoke application tokens or disable a client when needed.

Start a supervised worker using the same database, code and storage volume:

For a reviewable production overlay, exact application registration plan and
offline configuration validator, see [WebHDP-Link production preparation](webhdp_link_deployment.md).

```sh
.venv/bin/python scripts/webhdp_link_worker.py --poll-seconds 2
```

`WEBHDP_LINK_PUBLIC_BASE_URL` is the API deployment origin/base URL, without
`/api/v1/link`; `FRONTEND_URL` identifies the WebHDP frontend. Set
`WEBHDP_LINK_STORAGE_PATH` to a persistent private directory shared by the API
and workers. `WEBHDP_LINK_MAX_CONCURRENT_RUNS` limits global concurrent jobs
(default 2); application limits can be lower. One worker process executes one
job at a time. Additional worker processes use database-aware registry locks.

Keep a dedicated `/api/v1/link/` reverse-proxy location ahead of generic API
handling. Preserve `Origin`, `Authorization`, `Idempotency-Key` and the request
body, and forward `OPTIONS` to WebHDP; the proxy must not add wildcard CORS
headers or return its own successful preflight response. Both shipped nginx
templates provide this separation. Keep `proxy_request_buffering off` together
with explicit `proxy_http_version 1.1` so chunked uploads reach the backend's
authentication and per-client byte limits without first being fully buffered by
nginx. The proxy's request-size ceiling remains an additional deployment limit;
choose it to accommodate approved file sizes and multipart overhead. See the
[nginx request-buffering documentation](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_request_buffering).

Serve the authenticated SPA, including `/link/authorize`, with
`Content-Security-Policy: frame-ancestors 'none'`; only the existing public record
embed surface should override framing restrictions. Set `WEBHDP_LINK_PUBLIC_BASE_URL`
and `FRONTEND_URL` to their externally reachable HTTPS URLs rather than relying
on internal proxy addresses. With the default loopback demo running on port 5100,
a built `frontend/dist`, and Docker available, run
`.venv/bin/python scripts/verify_webhdp_link_proxy.py` to check both templates in
disposable local nginx containers. The probe checks exact-origin forwarding,
allowed and denied preflights, rejection of unauthenticated requests, and consent
framing protection. Also verify an authenticated upload and artifact download
through the actual deployment proxy before enabling external applications.

For an HPC-backed component, enable the publication's central allocation policy.
The normal WebHDP HPC permissions and resource limits still apply. By default,
the job releases its allocation after completion, failure or cancellation.
Optional administrator retention keeps an active allocation for operator-managed
follow-up. An operator may also enable `reuse_retained_allocation` on both
publications: only idle allocations retained by completed Link jobs belonging
to the same user with an identical frozen resource policy are eligible. The
queue serializes these jobs across applications. Inputs and remote outputs use
unique invocation directories, and local downloads are isolated per step.
Reusing an allocation never extends or resets its original scheduler expiry.
Omit the walltime override to use the central default. A deployment must permit
and validate its requested walltime and scheduler resources.
Scheduler walltime starts when the hold job runs. The gateway refreshes its
displayed expiry from that start marker and does not expire pending jobs based
on time spent waiting in the scheduler queue. Host component timeouts terminate
their invocation process group while preserving an explicitly retained allocation.
For long scheduler queues, configure both `HPC_LINK_PARTITION_ATTEMPT_TIMEOUT_SECONDS`
(central partition attempt, default 300) and `WEBHDP_LINK_HPC_WAIT_SECONDS`
(Link worker wait, default 900) before starting workers. For example, set each
to `14400` to allow four hours of queueing. These waits do not consume or extend
the allocation's scheduler walltime. Accepted jobs keep their original policy;
changing a partition or GPU type requires a new immutable publication.

The default remote execution profile uses a verified Singularity image. A
reviewed operator-installed runtime can instead use `trusted_host_component`:
the gateway reads its fixed entrypoint only from the central component registry
and verifies the manifest's SHA-256 before execution. This host profile is not
exposed by the remote component installation API and has no container sandbox;
the HPC maintainer must review the executable and pin its runtime dependencies.
Applications cannot submit entrypoints or executable profiles. The runner maps
only exact staged file paths and rejects artifacts outside its private invocation
output directory. Sandbox Zenodo credentials remain invocation-only environment
variables for the approved local component; they are never sent to the HPC.

Workers heartbeat while processing. An abandoned claim becomes explicitly
failed after its stale threshold (default 120 seconds) when its execution lock
is no longer held. Unknown side effects are never automatically replayed.

Apply the additive migration before starting an upgraded deployment:

```sh
SKIP_DB_CREATE_ALL=true .venv/bin/flask --app app db upgrade
```

Disabling import-time table bootstrap ensures Alembic owns this upgrade. The
migration is `d9e0f1a2b345` after `c8d9e0f12345`.
Database schema changes use the normal migration process. Do not point a new
application version at production before applying its migrations and validating
its worker/storage configuration. This change does not deploy anything.

## Browser integration

Use the framework-independent module at `sdk/webhdp-link/client.mjs`:

```js
import { WebHdpLink } from './client.mjs'

const link = new WebHdpLink({
  baseUrl: 'https://processing.example.org/api/v1/link',
  clientId: 'your-registered-client-id',
})

// On the integration's callback page:
const connected = await link.completeAuthorization()

// In the Connect button handler:
location.assign(await link.authorizationUrl({
  redirectUri: 'https://your-app.example.org/process/',
}))

// After connection, using a File from a file input:
const input = await link.upload(file)
const run = await link.submit({
  pipelineId: 'your-published-pipeline',
  inputs: [input],
  parameters: { quality: 75 },
  idempotencyKey: crypto.randomUUID(),
})
const result = await link.wait(run.id, { onProgress: renderProgress })
if (result.status === 'succeeded') {
  const blob = await link.download(result.id, result.artifacts[0])
  // The SDK checks size and SHA-256 before returning the Blob.
}
```

Keep the idempotency key when retrying an uncertain submission. Reusing it with
changed inputs or parameters returns a conflict. Once accepted, jobs persist
independently of the browser tab. `GET /runs` restores the application's history
for the same user after reconnecting. A cancellation request is cooperative;
a running component may finish before the job becomes cancelled.

The stable job `status` remains `queued`, `running`, `succeeded`, `failed` or
`cancelled`. The optional `progress.phase` explains what an active job is doing:

| Phase | Meaning shown to users |
| --- | --- |
| `queued` | Accepted; waiting for a WebHDP worker |
| `waiting_for_resources` | Waiting for centrally managed computing resources; scientific execution has not started |
| `processing` | Pipeline processing is underway |
| `finalizing` | WebHDP is collecting results and settling the final job status |
| `completed` | Processing has ended; read `status` to distinguish success, failure and cancellation |

A job can have `status: running` while its resource request is still pending.
The prototypes and hosted pages then say **Waiting for resources**, rather than
implying that reconstruction is executing. This phase is derived from persisted
WebHDP state and exposes no scheduler job ID, node, cluster path or credential.
It does not predict when resources will become available. Older servers that omit
the phase remain compatible; their running jobs display **Job in progress**.

The SDK stores a short-lived PKCE verifier/state in session storage only while
authorizing. Access tokens remain in memory and expire after one hour. Reloading
the application requires reconnecting. The SDK refuses redirects for authenticated
API requests, confines URLs to the selected API, and never uses browser cookies.
Do not place tokens in URLs, application source, screenshots, analytics, or
browser persistent storage.

Token expiry stops new API reads or submissions; it does **not** revoke the
authorization of an already accepted durable job. When a prototype sees an HTTP
401, it clears its in-memory connection without calling token revocation and
offers **Connect with WebHDP**. Reconnect with the same account and select the job
under **Your recent jobs** to resume tracking. Reloading the page also requires
reconnection. The hosted job URL remains bookmarkable and is preserved through
WebHDP login when its own session expires. Explicitly revoking a grant or
disconnecting while its token is still valid withdraws that authorization;
accepted work can then stop at the next authorization check. Reconnect after
expiry rather than revoking a grant simply to renew observation.

## Optional WebHDP-hosted processing pages

An integrating site does not have to build a progress screen. Submit through the
SDK and navigate to the returned `progress_url`:

```js
const job = await link.process({ pipelineId, files, parameters })
location.assign(link.hostedUrl(job))
```

This opens `/link/jobs/<job-id>` on WebHDP. WebHDP handles progress, cancellation,
result downloads and checksum verification. The page is bookmarkable and resumes
after WebHDP login. No bearer token or input data is placed in the URL. Each user
can access only their own jobs, even when they know another job's identifier.

`/link/jobs` lists the user's latest 100 jobs across applications, grouped by
application and filterable by status. Older job detail links continue to work.
`/account/connected-apps` lets users review and revoke their application grants.
The prototypes expose **Follow processing in WebHDP** before submission and
**Open this job in WebHDP** afterward; embedded progress remains the default.
Batch jobs appear as individual durable jobs in the overview.

The upload and submit API remains the same in both modes. A third-party server
can also return the WebHDP progress URL to its user, provided the job is owned by
that user's WebHDP account. Jobs submitted under a service account are visible
to that service account; a progress link does not itself grant access.

## Batch and server integration

An administrator can issue a scoped, expiring server token for a registered
application and a WebHDP user. Store it in the application's server-side secret
manager. Use the same upload/run/status/download endpoints with
`Authorization: Bearer …`. Server tokens must never be embedded in browser code.
Limits apply to both interactive and batch requests. Client and user ownership
checks isolate uploads, jobs and artifacts; knowing an identifier is insufficient.

For example, a batch integration can upload each scan once, submit one run per
scan with a stable idempotency key, poll pending jobs, and compare downloaded
checksums. There is no special HPC login in this workflow. The administrator
chooses the runtime and resource policy centrally.

## Local demonstration

The three prototypes are independent static applications, served on different
origins and connected to one actual WebHDP API:

| Application | Address | Real processing |
| --- | --- | --- |
| Photo Lab | `http://127.0.0.1:5191/photo-lab/` | Photo decoding/orientation, contact sheet, checksummed reconstruction handoff |
| Roll Studio | `http://127.0.0.1:5192/roll-studio/` | Existing HMSM optical processor and MIDI generation |
| Model Depot | `http://127.0.0.1:5193/model-depot/` | Geometry-only OBJ validation, normalization, GLB and repository package |

Install the examples' small additional dependency and configure an existing HMSM
checkout with its installed environment:

```sh
uv pip install --python .venv/bin/python -r external_code/webhdp_link_examples/requirements.txt
export WEBHDP_LINK_HMSM_SOURCE=/absolute/path/to/interactive-hmsm
export WEBHDP_LINK_HMSM_PYTHON=/absolute/path/to/interactive-hmsm/.venv/bin/python
.venv/bin/python scripts/run_webhdp_link_demo.py --credentials-file /private/development-account.json
```

The private JSON contains `email` and `password` for the existing development
account. The launcher creates an isolated database and
storage below `instance/link-demo`, binds only to loopback, starts the native
API, Link worker, WebHDP frontend and three prototype servers, and stops its
owned processes on Ctrl-C. State and results persist for the next launch.
Use a development account and fixture data; the launcher stays on loopback.

Select **Connect with WebHDP**, sign in on WebHDP, review the requested access,
and approve. Back in the prototype, choose **Use sample data**, set parameters,
and run the pipeline. Roll Studio and Model Depot also support one job per file.

In this default mode, the samples are synthetic fixtures. Photo Lab's
`link-photo-preparation` publication creates a contact sheet, without
photogrammetry. Model Depot's `link-model-deposit` prepares files without a Zenodo
upload. These base publications remain separate from the live pipelines below.

## Isolated Draco and Sandbox validation

Live mode uses the same three applications and API, but registers dedicated
clients `photo-lab-draco` and `model-depot-sandbox`. Photo Lab selects
`link-photogrammetry`: genuine COLMAP reconstruction through the centrally
configured HPC-Link gateway on Draco. Model Depot selects
`link-model-sandbox-draft`: OBJ preparation followed by a real **unpublished**
Zenodo Sandbox draft upload and download verification. Roll Studio retains its
HMSM pipeline. Starting the launcher installs definitions; a processing job is
submitted only through the application or validation script.

First prepare the trusted remote runtime and register its pinned component in
the isolated HPC-Link service, following the
[photogrammetry component instructions](../../external_code/webhdp_link_photogrammetry/README.md).
The launcher requires an already running, operator-configured loopback gateway;
it does not install or start that service. Keep the normal HMSM prerequisites
above, because live mode also installs the base examples.

Create a private `instance/link-draco/live-settings.json`, for example:

```json
{
  "hpc_environment_file": "/private/development/hpc-link.env",
  "zenodo_environment_file": "/private/development/backend-env.json",
  "photo_sample_directory": "/private/datasets/original-captures",
  "queue_wait_seconds": 14400,
  "photogrammetry": {
    "runtime_python": "/trusted/runtime/bin/python",
    "runtime_colmap": "/trusted/runtime/bin/colmap",
    "remote_component_root": "/trusted/components/link_reprojector_photogrammetry/1.0.0",
    "colmap_sha256": "<64 lowercase hexadecimal characters>",
    "reprojector_source_sha256": "<64 lowercase hexadecimal characters>",
    "partition": "gpu"
  }
}
```

Replace every placeholder with the paths and digests from the reviewed remote
installation; `gpu_type` is an optional trusted photogrammetry setting. The sample
directory must contain 3–30 intended JPEG/PNG photographs. Its selected images
are served by the local Photo Lab fixture endpoint for browser submission, so use
a dedicated dataset directory. The private directory path is excluded from the
prototype's public `/config.json`.

Live setup compares existing publication contracts and client allowlists with
the requested settings. A conflicting pipeline, parameter/input contract, HPC
policy, origin, callback or pipeline allowlist stops startup with the affected
identifier and field names. It preserves administrator names, enabled states and
client quotas. To deliberately change the photogrammetry resource policy, supply
new `photo_publication_id` and `photo_client_id` settings; existing accepted jobs
keep their frozen configuration. Do not restart a working launcher merely to
capture evidence for an already accepted job.

The HPC environment reference accepts dotenv or JSON (an object or `KEY=value`
array). Only the named HPC-Link connection/resource settings are loaded; its
`HPC_LINK_BASE_URL` must be HTTP on `localhost` or `127.0.0.1`. The Zenodo reference
accepts JSON containing the existing `ZENODO_SANDBOX_API_KEY`. That key is stored
encrypted as the initiating development user's active Sandbox credential, then
injected only into the approved local upload component. It is not placed in
public configuration, manifests, command arguments, or the HPC environment.
Keep these private files owner-readable and outside any static web directory.

From the repository root, start:

```sh
.venv/bin/python scripts/run_webhdp_link_demo.py --live-validation \
  --live-config-file instance/link-draco/live-settings.json \
  --credentials-file /private/development-account.json
```

Pass an explicit owner-readable JSON file for the isolated development
account; its keys are `email` and `password`. Use a dedicated development
identity. Live state persists separately in `instance/link-draco`.
API/Vue/prototype ports remain 5100/5173/5191–5193, so stop the base launcher
first. Keep the browser and worker on a trusted development machine.

The live photogrammetry publication requests one GPU for **12 hours**, explicitly
retains a running allocation after completion and opts into reuse. Reuse requires
the same user, an identical frozen resource policy, both jobs' explicit opt-in,
and an idle allocation owned by a completed Link job. Jobs retain separate input
and output directories; reuse does not extend the original scheduler expiry.
Queued allocations are released on failure/timeout. Ordinary publications still
release allocations by default. Stopping the launcher does not cancel a retained
scheduler allocation.

`queue_wait_seconds` controls the live launcher's central partition-attempt and
Link worker waits, with a default of 14400 seconds and an accepted range of
300–604800. This is a queue deadline, separate from the **12 hours of actual
allocation time**, which start when Slurm runs the hold job. A pending start time
is an estimate, not a reservation guarantee. The browser's observation deadline
is separate again: `WEBHDP_LINK_BROWSER_WAIT_MINUTES` defaults to 360 minutes.
Ending browser observation does not cancel the durable job or release its
allocation. While resources are pending, `status` may be `running` with
`progress.phase: waiting_for_resources`; this does not mean COLMAP has started.

### Verify a live run

1. Connect Photo Lab as the verified development user. Upload an authorized,
   overlapping scene and submit it once. While Slurm is pending, check that
   hosted progress says **Waiting for resources**. If browser observation
   stops, reconnect with the same account and reopen the run instead of
   submitting a duplicate.
2. Download the output package. Verify the advertised sizes and SHA-256
   digests, then inspect calibrated cameras, registered image counts and
   nonempty geometry. A completed process alone does not establish accuracy.
   Confirm GPU usage and start/end times in private scheduler tooling. Retain
   fixture provenance and redacted evidence outside the source tree.
3. To exercise Model Depot, use a dedicated Sandbox credential and fixture.
   Its input processing creates an **unpublished** draft. Compare receipt
   filenames, sizes and hashes with the draft files using read-only Sandbox
   requests. Review or delete the test draft separately with the Sandbox
   account. Do not use a Production credential or replay unclear requests.

Confirm the operators' intended release or retention policy after the test.
A retained allocation can stay active until its recorded Slurm end time.
Model normalization reports its selected target extent; it does not recover
physical units or alter the input OBJ.

## Actual application integrations

After the initial installation, restart the isolated development installation
without reseeding immutable component versions:

```sh
.venv/bin/python scripts/run_webhdp_link_demo.py --resume-existing --live-validation \
  --live-config-file instance/link-draco/live-settings.json \
  --credentials-file /private/development-account.json
```

Resume requires the existing database, secrets, verified account, publications
and exact client registrations. It does not change accounts, resource settings,
credentials or component/pipeline versions. A normal fresh-install startup still
refuses to replace a pinned version when scientific source bytes have changed.
In this development configuration the Roll Studio prototype now selects the
frozen central `link-hmsm-roll-vis` publication via the new `roll-studio-vis`
client. Optional private settings `roll_publication_id` and `roll_client_id`
select that already registered contract; the older local publication is retained
as historical evidence, with its source checks intact.

The development installation also registers two actual applications using the
same SDK and protocol as the prototypes:

| Application | Client | Exact development origin and callback | Published pipeline |
| --- | --- | --- | --- |
| HMSM-Studio | `hmsm-studio` | `http://127.0.0.1:5194` → `http://127.0.0.1:5194/?webhdp=1` | `link-hmsm-roll-vis` |
| Reprojector desktop | `reprojector-desktop` | `http://127.0.0.1:5195` → `http://127.0.0.1:5195/callback/` | `link-photogrammetry-vis` |

HMSM-Studio's WebHDP processing page offers local or owner-authorized registered
scans, parameters discovered from the publication, one queued run per scan,
optional hosted progress, verified downloads and explicit generated-MIDI import
for comparison. Refreshing loses unsubmitted files and unfinished local batch
retry state; accepted jobs remain in WebHDP and can be reopened after reconnecting.
The [central HMSM component](../../external_code/webhdp_link_hmsm/README.md)
freezes eleven roll profiles and performs CPU optical extraction. It can run
in an operator-managed allocation; scan extraction does not require a GPU.

Reprojector's native preparation workflow offers “Reconstruct with WebHDP”.
Selected photographs are served only through a private loopback bridge with
exact Host/Origin checks and a per-launch capability. Authorization and tokens
stay in the browser. The checked scientific package returns calibrated cameras,
geometry and evidence to native preparation, preserving original-photo hashes
and identifying its WebHDP provenance. Integration-specific operator and user
instructions are in each application's `docs/WEBHDP_LINK.md` (Studio) and
`docs/WEBHDP-LINK.md` (Reprojector).

These are development registrations, not production allowlists. Review exact
HTTPS origins and callbacks for any hosted installation. Desktop loopback is an
explicit native-application exception. Use a new registration/publication for a
changed contract rather than silently altering an existing one.

## Security and operational boundaries

* OAuth authorization-code flow with S256 PKCE, exact redirects, browser state,
  one-use expiring codes, scoped expiring tokens, and hashed token storage.
* Separate WebHDP JWT authorization for administrator actions and user consent.
  A browser application never receives the user's WebHDP password or JWT.
* Exact origin checks and CORS; no wildcard credentialed origins. A successful
  preflight alone is not authorization.
* Strict scalar parameter validation, opaque upload IDs, bounded file counts,
  streaming upload limits and client storage/queue quotas.
* File-typed inputs are validated inside the run workspace. Local CLI components
  receive a small environment plus approved invocation settings. A trusted host
  program still has its worker user's filesystem access; use containers for
  components that need isolation.
* Persistent queued work, bounded worker execution and explicit failure states.
  Interrupted work must not silently rerun a side-effecting pipeline.
* Confined artifact paths, attachment downloads, size and SHA-256 metadata.
  Public status hides private paths, raw subprocess logs and credentials.
* No arbitrary remote URL imports or webhook destinations in v1. This avoids
  a server-side URL-fetching surface; cloud providers can be added later through
  separately authorized transfer adapters.

A deployment still needs HTTPS termination, backups, operational supervision,
storage retention planning and runtime isolation appropriate to its components.
The Link API deliberately exposes a documented subset of the native pipeline
model; it does not claim that every existing submission/publication pipeline can
be exported unchanged. Production deployment and live HPC execution need their
own acceptance tests.

## Standards and design sources

The OAuth design follows [OAuth 2.0 Security Best Current Practice, RFC 9700](https://www.rfc-editor.org/rfc/rfc9700.html)
and [PKCE, RFC 7636](https://www.rfc-editor.org/rfc/rfc7636.html). Resource errors
use [HTTP Problem Details, RFC 9457](https://www.rfc-editor.org/rfc/rfc9457.html).
The contract uses [OpenAPI 3.1.1](https://spec.openapis.org/oas/v3.1.1.html)
and JSON Schema types and bounds. WebHDP's discovery document is a documented
Link discovery format; it is not a claim of OpenID Connect certification.
