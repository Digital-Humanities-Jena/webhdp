#!/usr/bin/env bash
#SBATCH --job-name=webhdp-sing
#SBATCH --partition=vascunet
#SBATCH --nodes=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --time=02:00:00
#SBATCH --signal=B:TERM@600
#SBATCH --output=/home/webhdp-user/webhdp/logs/slurm-webhdp-sing-%j.out
#SBATCH --error=/home/webhdp-user/webhdp/logs/slurm-webhdp-sing-%j.err

set -euo pipefail
ROOT="${ROOT:-/home/webhdp-user/webhdp}"
cd "$ROOT"
mkdir -p "$ROOT/run/runtime-sing"
echo "${SLURM_JOB_ID:-unknown}" > "$ROOT/run/runtime-sing/current_webhdp_singularity_jobid"
echo "$(hostname)" > "$ROOT/run/runtime-sing/current_webhdp_singularity_node"

echo "Starting WebHDP (Singularity) on node $(hostname) at $(date -Iseconds)"

cleanup() {
  echo "Stopping WebHDP (Singularity) on $(hostname) at $(date -Iseconds)"
  "$ROOT/scripts/hpc_singularity/remote/stop_services.sh" || true
}
trap cleanup EXIT TERM INT

if [[ -f "${ENV_FILE:-$ROOT/.env.hpc.singularity}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE:-$ROOT/.env.hpc.singularity}"
  set +a
fi

if [[ -n "${WEBHDP_JOB_COMMAND:-}" || -n "${WEBHDP_BATCH_CHUNK_JSON:-}" ]]; then
  export WEBHDP_START_SERVICES_RETURN_AFTER_HEALTH=true
fi

"$ROOT/scripts/hpc_singularity/remote/start_services.sh"

if [[ -n "${WEBHDP_JOB_COMMAND:-}" ]]; then
  echo "Running WebHDP job command at $(date -Iseconds): $WEBHDP_JOB_COMMAND"
  bash -lc "$WEBHDP_JOB_COMMAND"
  echo "WebHDP job command completed at $(date -Iseconds)"
  exit 0
fi

if [[ -n "${WEBHDP_BATCH_CHUNK_JSON:-}" ]]; then
  if [[ -z "${WEBHDP_BATCH_CONFIG:-}" ]]; then
    echo "WEBHDP_BATCH_CHUNK_JSON is set but WEBHDP_BATCH_CONFIG is missing" >&2
    exit 2
  fi
  echo "Running generic WebHDP batch chunk $WEBHDP_BATCH_CHUNK_JSON at $(date -Iseconds)"
  python3 "$ROOT/scripts/hpc_singularity/remote/webhdp_hpc_batch.py" \
    run-chunk \
    --config "$WEBHDP_BATCH_CONFIG" \
    --chunk-json "$WEBHDP_BATCH_CHUNK_JSON"
  echo "Generic WebHDP batch chunk completed at $(date -Iseconds)"
  exit 0
fi

while true; do
  sleep 300
done
