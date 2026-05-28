#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./scripts/setup_hpc_marker_runtime.sh [host] [user] [ssh_key] [apps_root] [pytorch_cuda_tag] [marker_version]
#
# Examples for pytorch_cuda_tag:
#   cu124 (default), cu121, rocm6.1, cpu

HOST="${1:-hpc-login.example.edu}"
USER_NAME="${2:-webhdp-user}"
SSH_KEY="${3:-$HOME/.ssh/id_ed25519_hpc}"
APPS_ROOT="${4:-/srv/hpc-link/apps}"
PYTORCH_CUDA_TAG="${5:-cu124}"
MARKER_VERSION="${6:-1.10.1}"

echo "Preparing Marker runtime on ${USER_NAME}@${HOST}:${APPS_ROOT} (torch wheel tag: ${PYTORCH_CUDA_TAG}, marker-pdf: ${MARKER_VERSION})"

ssh -i "${SSH_KEY}" "${USER_NAME}@${HOST}" \
  USER_NAME="${USER_NAME}" APPS_ROOT="${APPS_ROOT}" PYTORCH_CUDA_TAG="${PYTORCH_CUDA_TAG}" MARKER_VERSION="${MARKER_VERSION}" 'bash -s' <<'REMOTE'
set -euo pipefail

UV_BIN="/home/${USER_NAME}/.local/bin/uv"
MARKER_ROOT="${APPS_ROOT}/marker"
MARKER_RUNTIME_DIR="${MARKER_ROOT}/runtime"
MARKER_VENV="${MARKER_ROOT}/venv"

mkdir -p "${MARKER_RUNTIME_DIR}" "${MARKER_ROOT}/sessions"

if [ "${PYTORCH_CUDA_TAG}" = "cpu" ]; then
  TORCH_INDEX_URL="https://download.pytorch.org/whl/cpu"
else
  TORCH_INDEX_URL="https://download.pytorch.org/whl/${PYTORCH_CUDA_TAG}"
fi

if [ -x "${UV_BIN}" ]; then
  if [ ! -d "${MARKER_VENV}" ]; then
    "${UV_BIN}" venv "${MARKER_VENV}"
  fi
  "${UV_BIN}" pip install --python "${MARKER_VENV}/bin/python" --upgrade pip

  "${UV_BIN}" pip install --python "${MARKER_VENV}/bin/python" "marker-pdf[full]==${MARKER_VERSION}"
  if ! "${UV_BIN}" pip install --python "${MARKER_VENV}/bin/python" \
    --index-url "${TORCH_INDEX_URL}" \
    "torch>=2.7,<3"; then
    echo "Warning: torch>=2.7 unavailable at ${TORCH_INDEX_URL}; falling back to default index."
    "${UV_BIN}" pip install --python "${MARKER_VENV}/bin/python" "torch>=2.7,<3"
  fi
  "${UV_BIN}" pip uninstall --python "${MARKER_VENV}/bin/python" -y torchvision >/dev/null 2>&1 || true
else
  python3 -m venv "${MARKER_VENV}"
  "${MARKER_VENV}/bin/pip" install --upgrade pip

  "${MARKER_VENV}/bin/pip" install "marker-pdf[full]==${MARKER_VERSION}"
  if ! "${MARKER_VENV}/bin/pip" install \
    --index-url "${TORCH_INDEX_URL}" \
    "torch>=2.7,<3"; then
    echo "Warning: torch>=2.7 unavailable at ${TORCH_INDEX_URL}; falling back to default index."
    "${MARKER_VENV}/bin/pip" install "torch>=2.7,<3"
  fi
  "${MARKER_VENV}/bin/pip" uninstall -y torchvision >/dev/null 2>&1 || true
fi

"${MARKER_VENV}/bin/marker_single" --help >/dev/null 2>&1 || {
  echo "Warning: marker_single command test failed. Verify runtime manually."
}

echo "Marker executable: ${MARKER_VENV}/bin/marker_single"
echo "Marker runtime dir: ${MARKER_RUNTIME_DIR}"
echo ""
echo "Set these HPC-Link env vars if needed:"
echo "  MARKER_BINARY=${MARKER_VENV}/bin/marker_single"
echo "  MARKER_DEFAULT_PARTITION=partition-a"
echo "  MARKER_TORCH_DEVICE=auto"
REMOTE

echo "Done."
