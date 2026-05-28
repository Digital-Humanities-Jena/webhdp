#!/usr/bin/env bash
#SBATCH --job-name=fr-bench
#SBATCH --partition=partition-b
#SBATCH --nodes=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
#SBATCH --gres=gpu:a100:1
#SBATCH --time=00:20:00
#SBATCH --output=/home/webhdp-user/webhdp/logs/slurm-fr-bench-%j.out
#SBATCH --error=/home/webhdp-user/webhdp/logs/slurm-fr-bench-%j.err

set -euo pipefail

ROOT="${ROOT:-/home/webhdp-user/webhdp}"
ENV_FILE="${ENV_FILE:-$ROOT/.env.hpc.singularity}"
SIF="$ROOT/images/sif/fast-renderer.sif"
BENCH_ID="fr_bench_${SLURM_JOB_ID}"
BENCH_DIR="$ROOT/artifacts/$BENCH_ID"
INPUT_DIR="$ROOT/data/local_input/$BENCH_ID"
OUT_HOST_DIR="$ROOT/hdp-shared/sessions/$BENCH_ID"
PORT="${FAST_RENDERER_PORT:-5502}"

mkdir -p "$BENCH_DIR" "$INPUT_DIR" "$OUT_HOST_DIR"
cp -f "$ROOT/test_model.glb" "$INPUT_DIR/model_a.glb"
cp -f "$ROOT/test_model.glb" "$INPUT_DIR/model_b.glb"
cp -f "$ROOT/test_model.glb" "$INPUT_DIR/model_c.glb"
cp -f "$ROOT/test_model.glb" "$INPUT_DIR/model_d.glb"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

if bash -ic "type set_cuda121 >/dev/null 2>&1"; then
  bash -ic "set_cuda121 >/dev/null 2>&1 || true"
fi

echo "[bench] host=$(hostname) date=$(date -Iseconds)" | tee "$BENCH_DIR/meta.txt"
echo "[bench] nvidia-smi -L" | tee -a "$BENCH_DIR/meta.txt"
(nvidia-smi -L || true) | tee -a "$BENCH_DIR/meta.txt"
echo "[bench] nvcc --version" | tee -a "$BENCH_DIR/meta.txt"
(nvcc --version || true) | tee -a "$BENCH_DIR/meta.txt"

nvidia-smi --query-gpu=timestamp,name,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw --format=csv -l 1 > "$BENCH_DIR/nvidia_samples.csv" &
SMI_PID=$!

cleanup() {
  set +e
  [[ -n "${SERVER_PID:-}" ]] && kill "$SERVER_PID" >/dev/null 2>&1 || true
  [[ -n "${SMI_PID:-}" ]] && kill "$SMI_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

singularity exec --cleanenv --nv --env PORT="$PORT" \
  -B "$ROOT/hdp-shared/sessions:/shared/sessions" \
  -B "$ROOT/data/local_input:/data/local_input" \
  -B "$ROOT/data/local_output:/data/local_output" \
  -B "$ROOT/external_code:/app/external_code" \
  "$SIF" \
  sh -c "cd /app/external_code/fast_renderer && python server.py" \
  > "$BENCH_DIR/fast_renderer_server.log" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
  echo "[bench] fast-renderer health check failed" | tee -a "$BENCH_DIR/meta.txt"
  exit 1
fi

python3 - <<PY
import json
import time
import urllib.request

port = int("$PORT")
base = f"http://127.0.0.1:{port}"
input_dir = "/data/local_input/$BENCH_ID"
output_root = "/shared/sessions/$BENCH_ID"

runs = [
    {
        "name": "single_cycles",
        "payload": {
            "input_files": [f"{input_dir}/model_a.glb"],
            "output_dir": f"{output_root}/single_cycles",
            "engine": "CYCLES",
            "resolution": 512,
            "samples": 32,
            "angle_iteration": 5,
            "parallel_mode": True,
            "parallel_workers": 0,
            "batch_size": 100,
            "transparent_background": True
        }
    },
    {
        "name": "batch_eevee_parallel",
        "payload": {
            "input_files": [
                f"{input_dir}/model_a.glb",
                f"{input_dir}/model_b.glb",
                f"{input_dir}/model_c.glb",
                f"{input_dir}/model_d.glb",
            ],
            "output_dir": f"{output_root}/batch_eevee",
            "engine": "BLENDER_EEVEE",
            "resolution": 512,
            "samples": 32,
            "angle_iteration": 5,
            "parallel_mode": True,
            "parallel_workers": 0,
            "batch_size": 100,
            "transparent_background": True
        }
    },
]

summary = {"runs": []}
for run in runs:
    data = json.dumps(run["payload"]).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/render",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=3600) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    elapsed = time.perf_counter() - t0
    summary["runs"].append(
        {
            "name": run["name"],
            "elapsed_seconds": round(elapsed, 3),
            "success": payload.get("success"),
            "success_count": payload.get("success_count"),
            "processed_count": payload.get("processed_count"),
            "warnings": payload.get("warnings") or [],
            "server_log_markers": [
                line for line in (payload.get("logs") or []) if isinstance(line, str) and line.startswith("SERVER_LOG:")
            ],
            "result_keys": sorted(list((payload.get("results") or {}).keys())),
        }
    )

out_path = "$BENCH_DIR/benchmark_summary.json"
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(summary, fh, indent=2)
print(json.dumps(summary, indent=2))
print(f"wrote {out_path}")
PY

sleep 2
kill "$SMI_PID" >/dev/null 2>&1 || true
SMI_PID=""

echo "[bench] done at $(date -Iseconds)" | tee -a "$BENCH_DIR/meta.txt"
