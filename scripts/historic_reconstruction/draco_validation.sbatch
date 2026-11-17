#!/bin/bash
#SBATCH --job-name=webhdp-historic-validation
#SBATCH --partition=gpu,gpu-test
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gres=gpu:a100:1
#SBATCH --time=02:00:00
# Submit with --chdir and --output pointing to an isolated validation directory.
# Copy the reviewed run_validation.sh there, then atomically create READY.
# No service installation, publication, deployment, or production data mutation.
set -euo pipefail
umask 077
: "${SLURM_JOB_ID:?Run through sbatch}"
printf '%s\n' "$(date -u +%FT%TZ) allocation-started job=$SLURM_JOB_ID node=$(hostname)"
scontrol show job "$SLURM_JOB_ID" -o > scheduler-start.txt
nvidia-smi --query-gpu=name,uuid,memory.total,driver_version --format=csv > gpu.csv
nvidia-smi > nvidia-smi.txt
# A bounded wait lets the local integration checks finish while the allocation queues.
deadline=$((SECONDS + 3600))
while [[ ! -f READY ]]; do
    if (( SECONDS >= deadline )); then
        printf '%s\n' '{"status":"staging-timeout","gpu_probe":"passed","integration_executed":false}' > validation-status.json
        exit 2
    fi
    sleep 15
done
[[ -f run_validation.sh ]] || { echo 'Missing run_validation.sh'; exit 2; }
set +e
bash run_validation.sh > validation.log 2>&1
status=$?
set -e
printf '{"status":"finished","exit_code":%s,"integration_executed":true}\n' "$status" > validation-status.json
exit "$status"
