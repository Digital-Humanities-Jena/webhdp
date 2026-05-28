# HPC Local-Mode Setup

This guide explains how to run WebHDP on an HPC account in local mode, assuming
the public repository is already available at:

```text
https://github.com/Digital-Humanities-Jena/webhdp
```

Local mode means WebHDP uses storage and processing resources on the HPC side.
It does not require the separate WebHDP server deployment or HPC-Link service.

## Intended Use

Use this setup when:

- the user has an HPC login account and Slurm allocation rights
- data should stay on the HPC filesystem
- WebHDP should run for a bounded job allocation
- access is through SSH tunnels to localhost

Do not use this guide for a public web deployment. For public deployments, use
the Docker and operations guides, then add HPC-Link only when remote compute
allocation is intentionally required.

## Best-Practice HPC Deployment Pattern

Recommended default:

- Use HPC local mode for researcher-controlled or operator-controlled runs
  reached through SSH tunnels. Do not expose the Slurm job directly to the
  public internet.
- Use a dedicated `$HPC_ROOT` per test, release candidate, or production-like
  run. Avoid reusing a previous root until its database, sessions, logs, and
  ports have been reviewed.
- Keep `HPC_LINK_BASE_URL` and `HPC_LINK_API_KEY` empty. HPC-Link is a separate
  integration pattern for a web deployment that delegates work to HPC; this
  guide runs WebHDP itself inside the HPC allocation.
- Keep secrets in `$HPC_ROOT/.env.hpc.singularity` only. Do not place real
  credentials in Slurm scripts, shell history, Git, shared notes, or command
  lines.
- Start with local EDM validation disabled unless the validator stack has been
  explicitly provisioned on unique ports for this HPC root.
- Request the smallest Slurm allocation that can complete the test workflow,
  then increase CPU, memory, GPU, and wall time only when the logs show a real
  need.
- Prefer `metadata_only` for the first workflow test. Enable renderer/USDZ only
  after backend, frontend, Redis, worker, storage, and tunnels are healthy.
- Use cluster-approved scratch/project storage for sessions and input data.
  Avoid home-directory quotas for large 3D batches unless the cluster policy
  explicitly allows it.
- Cleanly cancel the Slurm job when the test is finished so GPUs, CPUs, memory,
  and ports are released.

## Prerequisites

Local machine:

- Git
- Docker with Buildx
- `ssh` and `rsync`

HPC cluster:

- Slurm
- Singularity or Apptainer
- one GPU-capable or CPU-capable compute node, depending on enabled processing
- enough quota for images, database, sessions, uploads, outputs, and logs

## 1. Choose Paths And Ports

On the local machine:

```bash
export LOCAL_ROOT="$PWD"
export HPC_HOST=<your-hpc-login-alias>
export HPC_ROOT=/path/on/hpc/webhdp
```

Use a separate root for testing:

```bash
export HPC_ROOT=/path/on/hpc/webhdp-alpha-test-$(date +%Y%m%d-%H%M)
```

Before choosing ports, check what is already in use on the HPC account:

```bash
ssh "$HPC_HOST" 'ss -ltnp | egrep ":(5500|5502|5503|5600|5602|5603|5700|5702|5703|6380|6381|6382|8080|8090)" || true'
```

Pick a non-overlapping set, for example:

```dotenv
BACKEND_PORT=5700
FAST_RENDERER_PORT=5702
ANY_TO_USDZ_PORT=5703
REDIS_PORT=6382
FRONTEND_PORT=8090
```

Best practice:

- Record the chosen ports in the deployment note for that HPC root.
- Use one port set per running WebHDP instance.
- If several users share the same HPC account, agree on a port range before
  starting jobs.
- Never stop an existing listener unless you have confirmed it belongs to the
  WebHDP root you intend to replace.

## 2. Clone Or Sync The Repository

If the HPC can access GitHub:

```bash
ssh "$HPC_HOST" "git clone https://github.com/Digital-Humanities-Jena/webhdp.git '$HPC_ROOT'"
```

If GitHub access is blocked, sync from a local clone:

```bash
rsync -az --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '.DS_Store' \
  --exclude 'frontend/node_modules' \
  "$LOCAL_ROOT/" \
  "$HPC_HOST:$HPC_ROOT/"
```

Best practice:

- Prefer a fresh clone from `https://github.com/Digital-Humanities-Jena/webhdp`
  when the cluster can access GitHub.
- Use `rsync` only when GitHub access is blocked or when a release candidate is
  being tested before publication.
- Do not sync `.env`, local databases, credentials, `node_modules`, virtual
  environments, previous sessions, or local logs from a workstation into the HPC
  root.

## 3. Build And Transfer Singularity Images

From the local clone:

```bash
REMOTE_HOST="$HPC_HOST" REMOTE_ROOT="$HPC_ROOT" ./scripts/hpc_singularity/build_export_archives.sh
REMOTE_HOST="$HPC_HOST" REMOTE_ROOT="$HPC_ROOT" ./scripts/hpc_singularity/transfer_archives.sh
REMOTE_HOST="$HPC_HOST" REMOTE_ROOT="$HPC_ROOT" ./scripts/hpc_singularity/install_sif_on_hpc.sh
REMOTE_HOST="$HPC_HOST" REMOTE_ROOT="$HPC_ROOT" ./scripts/hpc_singularity/sync_remote_scripts.sh
REMOTE_HOST="$HPC_HOST" REMOTE_ROOT="$HPC_ROOT" ./scripts/hpc_singularity/install_optional_frontend.sh
```

Expected image directory on the HPC:

```text
$HPC_ROOT/images/sif
```

Best practice:

- Build images from the same repository commit that users will run.
- Keep image archives and installed SIF files under the chosen `$HPC_ROOT` so
  side-by-side test roots cannot overwrite each other.
- Rebuild images after dependency, Dockerfile, or frontend build changes.
- Keep old SIF files only when they are intentionally needed for rollback and
  storage quota allows it.

## 4. Create Persistent Directories

```bash
ssh "$HPC_HOST" "mkdir -p \
  '$HPC_ROOT/instance' \
  '$HPC_ROOT/databases' \
  '$HPC_ROOT/hdp-shared/sessions' \
  '$HPC_ROOT/data/local_input' \
  '$HPC_ROOT/data/local_output' \
  '$HPC_ROOT/logs' \
  '$HPC_ROOT/logs-sing'"
```

## 5. Configure Environment

Create the HPC environment file:

```bash
ssh "$HPC_HOST" "cp -n '$HPC_ROOT/scripts/hpc_singularity/remote/env.hpc.singularity.example' '$HPC_ROOT/.env.hpc.singularity' || true"
```

Edit `$HPC_ROOT/.env.hpc.singularity` and set at least:

```dotenv
FLASK_ENV=development
SECRET_KEY=<generated_secret>
CREDENTIAL_ENCRYPTION_KEY=<generated_credential_secret>
SETUP_BOOTSTRAP_TOKEN=<generated_setup_token>

BACKEND_PORT=5700
FAST_RENDERER_PORT=5702
ANY_TO_USDZ_PORT=5703
REDIS_PORT=6382
FRONTEND_IN_SINGULARITY=true
FRONTEND_PORT=8090
FRONTEND_URL=http://localhost:8090
CORS_ORIGINS=http://localhost:8090,http://127.0.0.1:8090

WEBHDP_DEPLOYMENT_MODE=local
WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=true
STORAGE_MODE=local
LOCAL_INPUT_PATH=/data/local_input
LOCAL_OUTPUT_PATH=/data/local_output
WEBHDP_SESSIONS_PATH=<absolute-hpc-root>/hdp-shared/sessions
SHARED_SESSION_PATH=<absolute-hpc-root>/hdp-shared/sessions
CELERY_BROKER_URL=redis://127.0.0.1:6382/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6382/0
CELERY_WORKER_CONCURRENCY=1

ENABLE_RENDERER=true
ENABLE_USDZ_CONVERSION=true
ENABLE_LOCAL_EDM_VALIDATION=false
LOCAL_EDM_VALIDATOR_REQUIRED=false
LOCAL_EDM_VALIDATOR_CONTINUE_ON_ERROR=true

ZENODO_SANDBOX_API_KEY=
ZENODO_API_KEY=
HPC_LINK_BASE_URL=
HPC_LINK_API_KEY=
```

Generate secrets locally or on the HPC with:

```bash
openssl rand -hex 32
```

Required values:

- `SECRET_KEY`
- `CREDENTIAL_ENCRYPTION_KEY`
- `SETUP_BOOTSTRAP_TOKEN`
- unique service ports
- `WEBHDP_SESSIONS_PATH` and `SHARED_SESSION_PATH`
- `FRONTEND_URL` and `CORS_ORIGINS`

Optional credentials:

- Zenodo keys can be left empty and added later in the WebHDP account UI.
- SMTP can be left disabled for a local test run with development settings.
- HPC-Link values must stay empty in this local-mode setup.
- Cloud storage credentials should be empty unless cloud mirroring is being
  deliberately tested.

Best practice for secrets:

- Generate `SECRET_KEY`, `CREDENTIAL_ENCRYPTION_KEY`, and
  `SETUP_BOOTSTRAP_TOKEN` separately.
- Restrict the environment file to the HPC user account:

```bash
ssh "$HPC_HOST" "chmod 600 '$HPC_ROOT/.env.hpc.singularity'"
```

- Add Zenodo keys through the WebHDP UI after setup when possible. The UI stores
  user-managed keys encrypted and displays only masked previews.
- Use sandbox credentials for the first publication test.
- Do not store production cloud or repository credentials in a shared HPC
  project directory unless the institution has approved that secret-management
  pattern.

## 6. Submit The Slurm Job

On the HPC:

```bash
cd "$HPC_ROOT"
sbatch -p <partition> --nodes=1 --gres=<gpu-resource> --cpus-per-task=8 --mem=32G --time=12:00:00 \
  scripts/hpc_singularity/remote/webhdp.sbatch
```

For CPU-only validation, use the site-specific CPU partition and disable
renderer/USDZ if the cluster cannot provide the required runtime resources.

Best practice:

- Start with a short wall time for installation validation, for example one to
  two hours.
- Use GPU resources only when renderer/USDZ or other GPU-backed components are
  being tested.
- If the workflow requires user decisions, plan a maximum waiting time and
  cancel or release the allocation when nobody is actively using the instance.
- Keep Slurm output and error logs for release evidence, but review them before
  sharing because logs can contain paths, usernames, hostnames, and configuration
  details.

## 7. Open SSH Tunnels

Find the allocated node:

```bash
squeue -u "$USER" -o "%.18i %.9P %.20j %.8T %.10M %.20N"
```

Then forward the frontend and backend ports. Exact SSH syntax depends on the
cluster network, but the common pattern is:

```bash
ssh -N \
  -L 8090:<compute-node>:8090 \
  -L 5700:<compute-node>:5700 \
  "$HPC_HOST"
```

Open:

```text
http://localhost:8090/setup?setup_token=<generated_setup_token>
```

## 8. Verify The Deployment

On the HPC:

```bash
tail -n 200 "$HPC_ROOT/logs/slurm-webhdp-sing-"*.out
tail -n 200 "$HPC_ROOT/logs/slurm-webhdp-sing-"*.err
```

From the local machine:

```bash
curl http://localhost:5700/api/v1/health
```

Expected result:

- the Slurm log reports that services are healthy
- the health endpoint returns JSON successfully
- the setup wizard loads through the frontend tunnel
- the first administrator can be created

Also verify:

```bash
curl http://localhost:5700/api/v1/readiness
```

In the UI, confirm:

- setup checks complete
- storage paths point into the selected HPC root
- renderer/USDZ status matches the services you intentionally enabled
- local EDM validation is either healthy or explicitly disabled
- no HPC-Link integration is configured for this local-mode deployment

## 9. First End-To-End Test

Use local-mode filesystem paths:

1. Copy a small fixture directory into `$HPC_ROOT/data/local_input`.
2. Start a local storage workflow from the WebHDP UI.
3. Select the mounted input path.
4. Complete scan, file review, and metadata draft steps.
5. Run a metadata-only pipeline if renderer/USDZ services are disabled.
6. Confirm that outputs and `.hdpc` session evidence are written under
   `$HPC_ROOT/hdp-shared/sessions`.

This proves that repository clone/sync, image transfer, Slurm startup, tunnels,
local storage, session persistence, and worker processing are all connected.

## 10. Shutdown, Cleanup, And Reuse

When the test or demonstration is finished:

```bash
scancel <jobid>
```

Then confirm the ports are no longer listening:

```bash
ssh "$HPC_HOST" 'ss -ltnp | egrep ":(5700|5702|5703|6382|8090)" || true'
```

Before deleting an HPC root:

- export or back up any `.hdpc` sessions that matter
- keep logs needed for release evidence
- remove temporary uploads and outputs that contain non-public data
- remove `.env.hpc.singularity` if it contains secrets
- document the commit, image build date, ports, Slurm resources, and test result

Reuse an HPC root only when the same operator has reviewed the old database,
sessions, environment file, image versions, and logs. For most alpha testing, a
fresh root is safer and easier to explain.
