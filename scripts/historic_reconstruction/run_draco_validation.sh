#!/bin/bash
# Run from a dedicated, staged validation directory on an allocated Draco GPU.
set -euo pipefail
umask 077
: "${SLURM_JOB_ID:?Run through the validation sbatch allocation}"
: "${HISTORIC_PYTHON:?Set the absolute scientific Python executable}"
: "${HISTORIC_COLMAP_BIN:?Set the directory containing the CUDA COLMAP executable}"
[[ -x "$HISTORIC_PYTHON" && -x "$HISTORIC_COLMAP_BIN/colmap" ]]
[[ -f runtime/component_runner.py && -f validate_runtime.py && -d inputs ]]
export PATH="$HISTORIC_COLMAP_BIN:$PATH"
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-8}"
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
unset DISPLAY
"$HISTORIC_PYTHON" -c 'import pycolmap; assert pycolmap.has_cuda, "CUDA-enabled pycolmap required"; print("pycolmap", pycolmap.__version__)'
colmap -h > colmap-version.txt
sha256sum runtime/*.py inputs/* > staged-sha256.txt
"$HISTORIC_PYTHON" validate_runtime.py \
    --runtime-dir "$PWD/runtime" --input-dir "$PWD/inputs" \
    --output-dir "$PWD/results-${SLURM_JOB_ID}" --gpu --dense
