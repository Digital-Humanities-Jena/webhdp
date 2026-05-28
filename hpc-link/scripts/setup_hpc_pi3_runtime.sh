#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./scripts/setup_hpc_pi3_runtime.sh [host] [user] [ssh_key] [apps_root] [pytorch_cuda_tag]
#
# Examples for pytorch_cuda_tag:
#   cu124 (default), cu121, rocm6.1, cpu

HOST="${1:-hpc-login.example.edu}"
USER_NAME="${2:-webhdp-user}"
SSH_KEY="${3:-$HOME/.ssh/id_ed25519_hpc}"
APPS_ROOT="${4:-/srv/hpc-link/apps}"
PYTORCH_CUDA_TAG="${5:-cu124}"

echo "Preparing Pi3 runtime on ${USER_NAME}@${HOST}:${APPS_ROOT} (torch wheel tag: ${PYTORCH_CUDA_TAG})"

ssh -i "${SSH_KEY}" "${USER_NAME}@${HOST}" \
  USER_NAME="${USER_NAME}" APPS_ROOT="${APPS_ROOT}" PYTORCH_CUDA_TAG="${PYTORCH_CUDA_TAG}" 'bash -s' <<'REMOTE'
set -euo pipefail

UV_BIN="/home/${USER_NAME}/.local/bin/uv"
PI3_ROOT="${APPS_ROOT}/pi3"
PI3_RUNTIME_DIR="${PI3_ROOT}/runtime"
PI3_REPO="${PI3_RUNTIME_DIR}/Pi3"
PI3_VENV="${PI3_ROOT}/venv"

mkdir -p "${PI3_RUNTIME_DIR}" "${PI3_ROOT}/sessions"

if [ ! -d "${PI3_REPO}/.git" ]; then
  git clone https://github.com/yyfz/Pi3.git "${PI3_REPO}"
else
  git -C "${PI3_REPO}" fetch --all --tags
  git -C "${PI3_REPO}" pull --ff-only
fi

if [ -x "${UV_BIN}" ]; then
  if [ ! -d "${PI3_VENV}" ]; then
    "${UV_BIN}" venv "${PI3_VENV}"
  fi

  "${UV_BIN}" pip install --python "${PI3_VENV}/bin/python" --upgrade pip

  if [ "${PYTORCH_CUDA_TAG}" = "cpu" ]; then
    "${UV_BIN}" pip install --python "${PI3_VENV}/bin/python" "torch==2.5.1" "torchvision==0.20.1"
  else
    "${UV_BIN}" pip install --python "${PI3_VENV}/bin/python" \
      --index-url "https://download.pytorch.org/whl/${PYTORCH_CUDA_TAG}" \
      "torch==2.5.1" "torchvision==0.20.1"
  fi

  "${UV_BIN}" pip install --python "${PI3_VENV}/bin/python" \
    "numpy==1.26.4" "pillow" "opencv-python" "plyfile" "huggingface_hub" "safetensors"
else
  python3 -m venv "${PI3_VENV}"
  "${PI3_VENV}/bin/pip" install --upgrade pip

  if [ "${PYTORCH_CUDA_TAG}" = "cpu" ]; then
    "${PI3_VENV}/bin/pip" install "torch==2.5.1" "torchvision==0.20.1"
  else
    "${PI3_VENV}/bin/pip" install \
      --index-url "https://download.pytorch.org/whl/${PYTORCH_CUDA_TAG}" \
      "torch==2.5.1" "torchvision==0.20.1"
  fi

  "${PI3_VENV}/bin/pip" install "numpy==1.26.4" "pillow" "opencv-python" "plyfile" "huggingface_hub" "safetensors"
fi

echo "Pi3 repo: ${PI3_REPO}"
echo "Pi3 python: ${PI3_VENV}/bin/python"
echo ""
echo "Set these HPC-Link env vars if needed:"
echo "  PI3_REPO_PATH=${PI3_REPO}"
echo "  PI3_PYTHON=${PI3_VENV}/bin/python"
REMOTE

echo "Done."
