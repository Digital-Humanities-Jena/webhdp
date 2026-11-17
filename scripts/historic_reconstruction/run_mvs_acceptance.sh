#!/usr/bin/env bash
# Invoke inside an existing authorized GPU allocation; never submits a new job.
set -euo pipefail
runtime_root=${1:?private provisioned MVS root required}
outer_python=${2:?Python 3.11+ with shared contract dependencies required}
input_dir=${3:?directory containing the checked source ZIP required}
run_name=${4:-acceptance-$(date -u +%Y%m%dT%H%M%SZ)}
runner_dir=${5:-$runtime_root/runtime}
case "$run_name" in *[!A-Za-z0-9_-]*|'') echo 'Invalid run name' >&2; exit 2;; esac
run_dir="$runtime_root/$run_name"
mkdir "$run_dir"
export HISTORIC_RECONSTRUCTION_UPSTREAM_CONFIG="$runtime_root/operator-config.json"
export WEBHDP_INPUT_DIR="$input_dir"
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK:-4}
export OPENBLAS_NUM_THREADS=$OMP_NUM_THREADS MKL_NUM_THREADS=$OMP_NUM_THREADS
date -u +%FT%TZ > "$run_dir/started-at.txt"
nvidia-smi --query-gpu=name,uuid,memory.total,memory.used,driver_version --format=csv > "$run_dir/gpu-before.csv"
set +e
/usr/bin/time -v "$outer_python" "$runner_dir/component_runner.py" upstream-mvs \
  --webhdp-input "$runtime_root/request.json" --webhdp-output-dir "$run_dir/output" \
  --webhdp-result "$run_dir/result.json" > "$run_dir/process.log" 2>&1
result=$?
set -e
printf '%s\n' "$result" > "$run_dir/exit-code.txt"
date -u +%FT%TZ > "$run_dir/finished-at.txt"
nvidia-smi --query-gpu=name,uuid,memory.total,memory.used,driver_version --format=csv > "$run_dir/gpu-after.csv"
cat "$run_dir/result.json"
exit "$result"
