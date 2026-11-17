#!/usr/bin/env bash
# Compile the actual upstream dependency, inside the authorized allocation.
set -euo pipefail
runtime_root=${1:?private provisioned MVS root required}
env_prefix="$runtime_root/env-py310"
export PATH="$env_prefix/bin:$PATH"
export CUDA_HOME="$env_prefix"
export LD_LIBRARY_PATH="$env_prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export CXX="$env_prefix/bin/x86_64-conda-linux-gnu-c++"
export CC="$CXX"
export CUDAHOSTCXX="$CXX"
export PYTHONPATH="$runtime_root/source/src"
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export TORCH_EXTENSIONS_DIR="$runtime_root/torch-extensions"
export MAX_JOBS=${SLURM_CPUS_PER_TASK:-2}
export OMP_NUM_THREADS=$MAX_JOBS OPENBLAS_NUM_THREADS=$MAX_JOBS
export MKL_THREADING_LAYER=GNU
cd "$runtime_root/source"
"$env_prefix/bin/python" -c 'import mvsanywhere.tools.fusers_helper; print("Genuine MVS CUDA extension compiled and imported")'
"$env_prefix/bin/python" -m pip freeze > "$runtime_root/pip-freeze.txt"
