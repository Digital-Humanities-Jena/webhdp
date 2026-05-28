# WebHDP on HPC: Portable Single-GPU Setup (Singularity/Apptainer)

This guide deploys WebHDP on exactly one GPU node and supports both frontend options:
- Mode A: frontend on local machine (`npm run dev`)
- Mode B: frontend in HPC container (single frontend tunnel)

The process is portable to most Slurm-based HPC clusters.

## 1. What this setup gives you

- Standard backend stack on one GPU node: `backend`, `fast-renderer`, `any-to-usdz`, `redis`, `celery`
- Persistent data on HPC host filesystem (DB, sessions, uploads, outputs)
- Local access via SSH tunnels
- Optional frontend hosted on HPC inside Singularity

## 2. Prerequisites

Local machine:
- Docker with buildx
- `ssh`, `rsync`
- Node.js/npm only if using Mode A (local frontend)

HPC cluster:
- Slurm
- Singularity or Apptainer (`singularity` or `apptainer` command)
- Access to at least one GPU partition/node

## 3. Set portable variables (local machine)

```bash
export LOCAL_ROOT=/path/to/local/webhdp
export HPC_HOST=<login-host>
export HPC_ROOT=/path/on/hpc/for/webhdp
```

Example with an SSH alias and shared project directory:

```bash
export HPC_HOST=<hpc-login-alias>
export HPC_ROOT=/shared/path/to/webhdp
```

If your cluster requires a jump host, use `~/.ssh/config` (recommended) and keep `HPC_HOST` as the final SSH alias.

For side-by-side testing, do not reuse a production root. Create a new root under a test parent, for example:

```bash
export HPC_HOST=hpc-login
export HPC_ROOT=/home/webhdp-user/webhdp-tests/webhdp_latest_$(date +%Y%m%d_%H%M)
```

Before choosing ports for a test root, audit the current listeners on the cluster account and reserve a unique set:

```bash
ssh "$HPC_HOST" 'ss -ltnp | egrep ":(5500|5502|5503|5600|5602|5603|5700|5702|5703|6380|6381|6382|8080|8090)" || true'
```

Never stop or restart an existing WebHDP root unless you have confirmed it is the instance you intend to replace.

## 4. Sync project to HPC

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

## 5. Build and install core SIF images

Run locally from project root:

```bash
cd "$LOCAL_ROOT"
REMOTE_HOST="$HPC_HOST" REMOTE_ROOT="$HPC_ROOT" ./scripts/hpc_singularity/build_export_archives.sh
REMOTE_HOST="$HPC_HOST" REMOTE_ROOT="$HPC_ROOT" ./scripts/hpc_singularity/transfer_archives.sh
REMOTE_HOST="$HPC_HOST" REMOTE_ROOT="$HPC_ROOT" ./scripts/hpc_singularity/install_sif_on_hpc.sh
REMOTE_HOST="$HPC_HOST" REMOTE_ROOT="$HPC_ROOT" ./scripts/hpc_singularity/sync_remote_scripts.sh
```

Installed on HPC in `$HPC_ROOT/images/sif`:
- `backend.sif`
- `fast-renderer.sif`
- `any-to-usdz.sif`
- `redis.sif`

## 6. Optional: include frontend in HPC container

If you want Mode B (frontend served on HPC):

```bash
cd "$LOCAL_ROOT"
REMOTE_HOST="$HPC_HOST" REMOTE_ROOT="$HPC_ROOT" ./scripts/hpc_singularity/install_optional_frontend.sh
```

This installs:
- `$HPC_ROOT/images/sif/frontend.sif`

## 7. Configure persistent directories and runtime env

On HPC, ensure persistent paths exist:

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

Create env file on HPC:

```bash
ssh "$HPC_HOST" "cp -n '$HPC_ROOT/scripts/hpc_singularity/remote/env.hpc.singularity.example' '$HPC_ROOT/.env.hpc.singularity' || true"
```

Edit `$HPC_ROOT/.env.hpc.singularity` and set at least:

- `BACKEND_PORT=5500`
- `FAST_RENDERER_PORT=5502`
- `ANY_TO_USDZ_PORT=5503`
- `REDIS_PORT=6380`
- `STORAGE_MODE=local`
- `WEBHDP_DEPLOYMENT_MODE=local`
- `WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=true`
- `LOCAL_INPUT_PATH=/data/local_input`
- `LOCAL_OUTPUT_PATH=/data/local_output`
- `WEBHDP_SESSIONS_PATH=<persistent sessions path on HPC>`
- `SHARED_SESSION_PATH=<same sessions path>`
- `ENABLE_RENDERER=true`
- `ENABLE_USDZ_CONVERSION=true`
- `CELERY_BROKER_URL=redis://127.0.0.1:<REDIS_PORT>/0`
- `CELERY_RESULT_BACKEND=redis://127.0.0.1:<REDIS_PORT>/0`

Frontend mode switch:
- Mode A (local frontend): `FRONTEND_IN_SINGULARITY=false`
- Mode B (HPC frontend): `FRONTEND_IN_SINGULARITY=true` and `FRONTEND_PORT=8080`

For a side-by-side smoke deployment, use a complete non-overlapping port set and independent host paths. One working pattern is:

```dotenv
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
WEBHDP_SESSIONS_PATH=/home/webhdp-user/webhdp-tests/<root>/hdp-shared/sessions
SHARED_SESSION_PATH=/home/webhdp-user/webhdp-tests/<root>/hdp-shared/sessions
CELERY_BROKER_URL=redis://127.0.0.1:6382/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6382/0
CELERY_WORKER_CONCURRENCY=1
```

When another important WebHDP job is running, keep optional local EDM services disabled until the lightweight stack is verified:

```dotenv
ENABLE_LOCAL_EDM_VALIDATION=false
ENABLE_LOCAL_EDM_VALIDATOR_STACK=false
LOCAL_EDM_VALIDATOR_REQUIRED=false
LOCAL_EDM_VALIDATOR_CONTINUE_ON_ERROR=true
```

If local EDM is enabled later, also allocate unique ports for Postgres, Mongo, Solr, ZooKeeper, MinIO, the validator, and the XSLT helper.

## 8. Submit one Slurm job on one GPU node

Job script:
- `$HPC_ROOT/scripts/hpc_singularity/remote/webhdp.sbatch`

Generic command pattern (run on HPC):

```bash
cd "$HPC_ROOT"
sbatch -p <gpu_partition> --nodes=1 --gres=<gpu_spec> --cpus-per-task=<cpu> --mem=<mem> --time=<time> \
  scripts/hpc_singularity/remote/webhdp.sbatch
```

Example site-specific submissions:

```bash
# GPU partition with one named GPU resource.
sbatch -p <gpu_partition_a> --nodes=1 --gres=<gpu_type_a>:1 --cpus-per-task=8 --mem=32G --time=12:00:00 \
  scripts/hpc_singularity/remote/webhdp.sbatch

# Alternate GPU partition or node constraint, when required by the site.
sbatch -p <gpu_partition_b> --constraint=<gpu_constraint> --nodes=1 --gres=<gpu_type_b>:1 --cpus-per-task=8 --mem=32G --time=12:00:00 \
  scripts/hpc_singularity/remote/webhdp.sbatch
```

## 9. Find node and verify health

On HPC:

```bash
squeue -u $USER -o "%.18i %.9P %.20j %.8T %.10M %.20N"
JOBID=<jobid>
NODE=$(squeue -j "$JOBID" -h -o %N)
echo "$NODE"

tail -n 200 "$HPC_ROOT/logs/slurm-webhdp-sing-${JOBID}.out"
tail -n 200 "$HPC_ROOT/logs/slurm-webhdp-sing-${JOBID}.err"
```

Healthy startup marker:
- `All services healthy. Keeping job alive with watchdog interval ...`

The startup script can also be used as a foreground smoke test that returns after all health checks pass:

```bash
cd "$HPC_ROOT"
ROOT="$HPC_ROOT" \
ENV_FILE="$HPC_ROOT/.env.hpc.singularity" \
SIF_DIR="$HPC_ROOT/images/sif" \
WEBHDP_START_SERVICES_RETURN_AFTER_HEALTH=true \
bash scripts/hpc_singularity/remote/start_services.sh
```

Use that mode for one-time validation only; for a persistent service run under Slurm or a supervised tmux session.

## 10. Access from local machine

### Mode A: local frontend + tunneled backend services

Open SSH tunnel:

```bash
NODE=<compute-node>
ssh -L 15500:${NODE}:5500 -L 15502:${NODE}:5502 -L 15503:${NODE}:5503 "$HPC_HOST"
```

Start frontend locally:

```bash
cd "$LOCAL_ROOT/frontend"
VITE_API_URL=http://127.0.0.1:15500/api/v1 npm run dev
```

Open the URL printed by Vite (usually `http://127.0.0.1:5173`).

### Mode B: frontend in HPC container

Open single tunnel:

```bash
NODE=<compute-node>
ssh -L 18080:${NODE}:8080 "$HPC_HOST"
```

Open:
- `http://127.0.0.1:18080`

The frontend container proxies API calls to backend internally.

For a side-by-side test deployment whose frontend binds only on the remote host, tunnel the chosen frontend port directly:

```bash
ssh -L 8090:127.0.0.1:8090 "$HPC_HOST"
```

Open:
- `http://127.0.0.1:8090`

## 11. Dataset upload and HPC-mode processing

- Upload data via UI/API while connected through your tunnel (Mode A or Mode B).
- Ensure backend is in local storage mode (`STORAGE_MODE=local`) so data lands on HPC host paths.
- Rendering and conversion run on the Slurm GPU node where the job is active.

## 12. Restart and persistence

Stop job:

```bash
scancel <JOBID>
```

Restart with same `sbatch` command. Data remains because host directories are persistent:
- `$HPC_ROOT/instance`
- `$HPC_ROOT/databases`
- `$HPC_ROOT/hdp-shared/sessions`
- `$HPC_ROOT/data/local_input`
- `$HPC_ROOT/data/local_output`

## 13. Portability checklist for other HPC clusters

- Scheduler syntax: some clusters use `--gpus` instead of `--gres`.
- Runtime command name: use `apptainer` if `singularity` is not available.
- SSH routing: use `ProxyJump` if direct login-to-node tunneling is restricted.
- Scratch/tmp policy: if `/tmp` is small, adapt singularity temp/cache paths to node-local scratch.
- CPU-only fallback: if GPU queues are full, services can still run in CPU mode (slower render).
- Site security policy: some sites block direct compute-node connections; tunnel through login node alias.

## 14. Troubleshooting

- `PENDING (Resources/Priority)`: request fewer resources or another partition.
- `FAILED` at startup: inspect Slurm log and `$HPC_ROOT/logs-sing/*.log`.
- Local port already in use: change local `-L` ports.
- API not reachable: confirm tunnel is open and `NODE` matches current running job node.
- Frontend in container not starting: confirm `FRONTEND_IN_SINGULARITY=true` and `frontend.sif` exists.
- Status helper says a service is stopped but health endpoints are OK: prefer the `--- listeners ---` and `--- health ---` sections. Singularity launcher parent PIDs can exit while the child service process keeps listening.
- Backend exits immediately with an existing Gunicorn PID: make sure this revision uses a runtime-bound PID path such as `/runtime/gunicorn-${BACKEND_PORT}.pid`, not a shared `/tmp/gunicorn.pid`.
- Frontend exits with nginx template permission errors: rebuild `frontend.sif`; the template `/etc/nginx/templates/default.conf.template` must be readable inside the SIF.
- A new test stack must be cleaned up by exact test ports/PIDs only. Avoid broad `pkill` patterns such as `python server.py` on shared accounts because they can match other WebHDP roots.
