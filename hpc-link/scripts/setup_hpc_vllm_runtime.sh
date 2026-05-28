#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./scripts/setup_hpc_vllm_runtime.sh [host] [user] [ssh_key] [apps_root]
#
# This script prepares:
# - a dedicated vLLM runtime venv in <apps_root>/vllm/venv
# - two small chat models in <apps_root>/models

HOST="${1:-hpc-login.example.edu}"
USER_NAME="${2:-webhdp-user}"
SSH_KEY="${3:-$HOME/.ssh/id_ed25519_hpc}"
APPS_ROOT="${4:-/srv/hpc-link/apps}"

echo "Preparing vLLM runtime on ${USER_NAME}@${HOST}:${APPS_ROOT}"

ssh -i "${SSH_KEY}" "${USER_NAME}@${HOST}" bash <<EOF
set -euo pipefail

mkdir -p "${APPS_ROOT}/vllm" "${APPS_ROOT}/models"

if [ ! -d "${APPS_ROOT}/vllm/venv" ]; then
  /home/${USER_NAME}/.local/bin/uv venv "${APPS_ROOT}/vllm/venv"
fi

/home/${USER_NAME}/.local/bin/uv pip install --python "${APPS_ROOT}/vllm/venv/bin/python" pip
/home/${USER_NAME}/.local/bin/uv pip install --python "${APPS_ROOT}/vllm/venv/bin/python" "vllm==0.6.6.post1"
/home/${USER_NAME}/.local/bin/uv pip install --python "${APPS_ROOT}/vllm/venv/bin/python" "transformers==4.48.3"

"${APPS_ROOT}/vllm/venv/bin/python" - <<'PY'
from huggingface_hub import snapshot_download

models = [
    ("Qwen/Qwen2.5-0.5B-Instruct", "${APPS_ROOT}/models/Qwen2.5-0.5B-Instruct"),
    ("TinyLlama/TinyLlama-1.1B-Chat-v1.0", "${APPS_ROOT}/models/TinyLlama-1.1B-Chat-v1.0"),
]

for repo_id, local_dir in models:
    print(f"Downloading {repo_id} -> {local_dir}", flush=True)
    snapshot_download(repo_id=repo_id, local_dir=local_dir)
    print(f"Done: {repo_id}", flush=True)
PY

echo "vLLM executable: ${APPS_ROOT}/vllm/venv/bin/vllm"
echo "Model dirs:"
echo " - ${APPS_ROOT}/models/Qwen2.5-0.5B-Instruct"
echo " - ${APPS_ROOT}/models/TinyLlama-1.1B-Chat-v1.0"
EOF

echo "Done."
