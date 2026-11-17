# Live WebHDP demo with a pre-reserved GPU

A presenter can run a WebHDP workflow over the public HTTPS site while a private
HPC-Link gateway starts Slurm job steps inside a pre-reserved GPU allocation.
Only named, verified WebHDP users with HPC access can claim that allocation.
The audience can watch the presenter’s browser without a WebHDP or HPC account.

## What the current site can do

The public site identified itself as **WebHDP Alpha (Test)** on 17 November
2026. The existing operator configuration documents a private VPN-backed gateway
and an ordinary job request workflow. That workflow submits a new Slurm job via
HPC-Link. The earlier release has no supported way to register an already
running job, grant selected WebHDP users access, or attach it to a workflow
without making WebHDP responsible for cancellation. A working public page also
does not establish that the current gateway can reach or use a particular job.
[WebHDP Alpha (Test)](https://hdp.3drepo.eu/)

With the reservation feature, the browser still talks to WebHDP over the public
origin. WebHDP calls a private, authenticated HPC-Link endpoint. HPC-Link
connects by SSH to a Draco login host, verifies the scheduler allocation belongs
to its configured SSH account, and starts a step on the allocated node. The
browser does not need a route to the compute node. The GPU job belongs to its
Slurm owner and keeps the scheduler’s original deadline. The operator registers
the exact job to share, so WebHDP does not list other jobs visible to the SSH
account.
[University of Jena HPC access](https://www.uni-jena.de/en/22210/scientific-computing-and-data-science)

## Prepare the release and the gateway

1. Build and deploy the matching WebHDP frontend, backend and worker plus the
   updated HPC-Link service and remote component runner. Record image digests
   and the database migration revision. Apply migrations once against an
   isolated copy of production data first. Keep a consistent database and
   session-file backup for rollback. Reuse the same frontend/backend HTTPS
   origin and private application configuration.
   [Docker deployment guide](../docker_deployment_guide.md)
2. Confirm that backend and worker can both reach the private gateway and that
   its SSH connection reaches Draco from the deployment network or VPN. Use the
   intended owner’s SSH identity and known-hosts file. Keep authentication and
   WebHDP session registry state in writable, private, persistent storage. The
   supplied HPC-Link deployment Compose file puts `WEBHDP_SESSIONS_REGISTRY_PATH`
   on the existing private `/data/auth` mount. A custom profile must preserve
   any existing registry and set a path on its own writable volume. Use one
   gateway replica with the file-based registry.
   Preserve the existing VPN and check that a gateway restart reloads the active
   reservation and its claim before relying on it during the demo.
3. Use a restricted gateway service principal for WebHDP. Keep the gateway
   administrator account for the separate registration step. The earlier
   deployment profile authorized ordinary requests on `vis` and `vascunet` up to
   six hours. Check the active production principal, Slurm owner, partition and
   delegation policy separately before treating an eight-hour `gpu` hold as
   available to the deployed application. A reservation does not raise the
   service principal’s new-job limits.
4. Confirm that the release profile exposes the workflow and tools the presenter
   will use. Install the precise component versions in advance. For a
   Singularity component, verify its SIF SHA-256 in the registry, check input
   and output storage, run preflight in the allocated node, and run the exact
   demo fixture once through the production proxy and worker. A GPU allocation
   does not install component software, model weights or the CUDA stack.
   [HDP Component installation](hdp_component_hpc_installation.md)

The current feature can be exercised in an isolated staging instance on the
same Slurm job. The operator should still rehearse through the deployed site's
actual VPN, proxy, storage and worker before presenting from the public URL.

## Register and grant the allocation

Reserve a Slurm GPU allocation before the event using the cluster’s approved
partition, GPU count, memory and walltime. A detached batch hold remains active
if the operator’s terminal disconnects. Check the live job identity and end
time, then verify GPU devices in the existing allocation. This only reserves
the scheduler resources requested for the job. One allocated GPU does not
imply exclusive control of a multi-GPU node.

```sh
squeue -j "$DEMO_JOB_ID" -o '%i %P %T %N %L %R'
srun --jobid="$DEMO_JOB_ID" --overlap --nodes=1 --ntasks=1 nvidia-smi -L
```

1. From an operator session, call HPC-Link
   `POST /api/apps/webhdp/reservations` with `job_id` and `owner_username`, the
   restricted WebHDP service principal’s name. The gateway verifies the running
   single-node GPU job through Slurm and returns an opaque reservation
   identifier. An administrator can first check a job using
   `POST /api/apps/webhdp/reservations/inspect` with `job_id`. The delegated
   principal reads an existing registration with
   `GET /api/apps/webhdp/reservations/{reservation_id}`. Use private operator
   tooling for gateway credentials and avoid placing them on the presentation
   screen.
2. In WebHDP, open **HPC Admin → Reserved GPUs**. Register the gateway identifier
   with a recognizable label and the existing email addresses of the presenter
   and any named backup operator. The equivalent endpoint is
   `POST /api/v1/admin/hpc-reservations`, with `gateway_reservation_id`, `label`
   and `allowed_emails`. Use the verified ordinary presenter account for the
   demo. It also needs the existing HPC Access capability.
3. Sign in as the presenter and check that the reservation is available with
   enough time remaining. Claim it for an upload session owned by the presenter.
   A session collaborator cannot run work using the presenter's claim. The
   claim is exclusive, with a private workspace. A second authorized account can
   use a new claim after the first claim is released. Releasing WebHDP access
   leaves the Slurm job running until its scheduled end or a deliberate operator
   cancellation. Download the required outputs before releasing the claim. The
   operator should avoid overlapping compute steps outside WebHDP during the
   demo because the exclusive claim applies only to WebHDP users.

## Run the presentation

One small textured model with **Fast 3D Model Renderer** is a good default if its
GPU renderer has passed preflight and timed rehearsal on the target node. Upload
the asset, show the reservation running, execute the existing workflow, then open
the resulting thumbnails and download one output. Use a rights-cleared fixture
and a separate browser profile with the ordinary demo account. Have an earlier
completed run ready to show if the VPN, scheduler or browser projection fails.
Describe it as a recorded result if you switch to it.

For a photogrammetry presentation, `historic_sparse_reconstruction_hpc` takes a
small ZIP of overlapping photos and produces a point cloud and scientific report
when the historic components and recipe have been installed.
The previous 11-photo rehearsal took about four minutes, including three native
steps, on its test fixture. Rehearse the exact fixture over the target network.
Geolocation, learned MVS and dense reconstruction are better shown from
completed runs if their asset transfers or compute time exceed the live slot.
Keep publication disabled for the demo unless it has separate authorization.

The isolated reservation rehearsal used a pinned Mask2Former segmentation SIF
and a ZIP with five historic photographs. A verified non-admin claimed job
`9319538` in the browser and ran the workflow. The run produced five binary
masks and two downloadable artifacts. Its report download matched the API
checksum. A second approved account later ran the same component in a fresh
workspace on the same A100. The gateway reported both releases as detached,
and Slurm still showed the original job running. The isolated instance exercised
the reservation, authentication, GPU and artifact routes. Run the same smoke
test through the real deployment proxy and worker before presenting.

## Rehearsal and follow-up tests

- Check an anonymous browser, a verified account without a reservation grant,
  two concurrently allowed accounts, and an attempt to claim another account's
  upload session. Only the permitted account and session should receive
  execution and artifact access. Repeat with real proxy and worker processes,
  and verify that reconnecting the browser recovers the run status.
- Try registering a missing, queued, completed, foreign or CPU-only job. Verify
  that an expired or changed job blocks new work and produces a clear message,
  including when the gateway or worker restarts. Release an idle claim, confirm
  the original Slurm job is still `RUNNING`, then reclaim it as a second allowed
  user and confirm it cannot see the previous workspace or downloads.
- Time the real upload, stage, execution, result download and refresh at the
  public site. Confirm that Slurm assigned the GPU and that the scientific
  application used it. Compare artifacts to a completed run and keep the run
  identifier and checksums with demo notes.
- Treat the historic scientific acceptance separately from the demo. The
  dense-intrinsics rehearsal produced real correspondences and five fits, with
  zero accepted camera changes. Add a benchmark fixture with an independently
  measured camera and a successful accepted update before claiming that real
  data exercises the calibration update branch.
