#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/home/webhdp-user/webhdp}"
ENV_FILE="${ENV_FILE:-$ROOT/.env.hpc.singularity}"
SIF_DIR="${SIF_DIR:-$ROOT/images/sif}"
FAST_RENDERER_PORT="${FAST_RENDERER_PORT:-5502}"
LOG_FILE="$ROOT/logs-sing/fast_renderer.log"
CUDA_VISIBLE_DEVICES_VALUE="${CUDA_VISIBLE_DEVICES:-}"
SLURM_GPUS_ON_NODE_VALUE="${SLURM_GPUS_ON_NODE:-}"
SLURM_STEP_GPUS_VALUE="${SLURM_STEP_GPUS:-}"
SLURM_JOB_GPUS_VALUE="${SLURM_JOB_GPUS:-}"
NVIDIA_VISIBLE_DEVICES_VALUE="${NVIDIA_VISIBLE_DEVICES:-${CUDA_VISIBLE_DEVICES_VALUE:-all}}"

# Terminate any existing fast-renderer process by cwd to avoid stale PID files.
for p in $(pgrep -f "python server.py" || true); do
  cwd="$(readlink "/proc/$p/cwd" 2>/dev/null || true)"
  if [[ "$cwd" == "/app/external_code/fast_renderer" ]]; then
    kill "$p" || true
  fi
done
sleep 1

nohup singularity exec --cleanenv --env-file "$ENV_FILE" --nv --env PORT="$FAST_RENDERER_PORT" \
  --env CUDA_VISIBLE_DEVICES="$CUDA_VISIBLE_DEVICES_VALUE" \
  --env SLURM_GPUS_ON_NODE="$SLURM_GPUS_ON_NODE_VALUE" \
  --env SLURM_STEP_GPUS="$SLURM_STEP_GPUS_VALUE" \
  --env SLURM_JOB_GPUS="$SLURM_JOB_GPUS_VALUE" \
  --env NVIDIA_VISIBLE_DEVICES="$NVIDIA_VISIBLE_DEVICES_VALUE" \
  -B "$ROOT/hdp-shared/sessions:/shared/sessions" \
  -B "$ROOT/data/local_input:/data/local_input" \
  -B "$ROOT/data/local_output:/data/local_output" \
  -B "$ROOT/external_code:/app/external_code" \
  "$SIF_DIR/fast-renderer.sif" \
  sh -c "cd /app/external_code/fast_renderer && python server.py" >>"$LOG_FILE" 2>&1 &

sleep 2
curl -sf "http://127.0.0.1:${FAST_RENDERER_PORT}/health" >/dev/null
listen_pid="$(ss -ltnp | awk -v p=":$FAST_RENDERER_PORT" '$4 ~ p {print $NF}' | sed -E 's/.*pid=([0-9]+).*/\1/' | head -n1)"
if [[ -n "$listen_pid" ]]; then
  echo "$listen_pid" > "$ROOT/run/pids-sing/fast_renderer.pid"
  printf "restarted_fast_renderer pid=%s port=%s\n" "$listen_pid" "$FAST_RENDERER_PORT"
else
  echo "Failed to detect listening PID on port $FAST_RENDERER_PORT" >&2
  exit 1
fi
