#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./scripts/setup_hpc_apps_structure.sh [host] [user] [ssh_key] [apps_root]

HOST="${1:-hpc-login.example.edu}"
USER_NAME="${2:-webhdp-user}"
SSH_KEY="${3:-$HOME/.ssh/id_ed25519_hpc}"
APPS_ROOT="${4:-/srv/hpc-link/apps}"

echo "Preparing HPC-Link app structure on ${USER_NAME}@${HOST}:${APPS_ROOT}"

ssh -i "${SSH_KEY}" "${USER_NAME}@${HOST}" bash <<EOF
set -euo pipefail

mkdir -p "${APPS_ROOT}"/vllm/sessions
mkdir -p "${APPS_ROOT}"/pi3/sessions
mkdir -p "${APPS_ROOT}"/pi3/runtime
mkdir -p "${APPS_ROOT}"/marker/sessions
mkdir -p "${APPS_ROOT}"/marker/runtime
mkdir -p "${APPS_ROOT}"/webhdp/sessions
mkdir -p "${APPS_ROOT}"/webhdp/runtime
mkdir -p "${APPS_ROOT}"/webhdp/bin
mkdir -p "${APPS_ROOT}"/vggt/sessions
mkdir -p "${APPS_ROOT}"/shared/cache

# Keep permissions strict: only the account owner can access runtime state.
chmod 700 "${APPS_ROOT}" "${APPS_ROOT}"/vllm "${APPS_ROOT}"/vllm/sessions
chmod 700 "${APPS_ROOT}"/pi3 "${APPS_ROOT}"/pi3/sessions "${APPS_ROOT}"/pi3/runtime
chmod 700 "${APPS_ROOT}"/marker "${APPS_ROOT}"/marker/sessions "${APPS_ROOT}"/marker/runtime
chmod 700 "${APPS_ROOT}"/webhdp "${APPS_ROOT}"/webhdp/sessions "${APPS_ROOT}"/webhdp/runtime "${APPS_ROOT}"/webhdp/bin
chmod 700 "${APPS_ROOT}"/vggt "${APPS_ROOT}"/vggt/sessions
chmod 700 "${APPS_ROOT}"/shared "${APPS_ROOT}"/shared/cache

cat > "${APPS_ROOT}/README.txt" <<'README'
HPC-Link application runtime root.
- vllm/sessions/<session_id>: sbatch scripts, logs, metadata for vLLM sessions
- pi3/sessions/<session_id>: sbatch scripts, uploaded images, and generated 3D artifacts
- pi3/runtime: Pi3 repository checkout and runtime-related assets
- marker/sessions/<session_id>: sbatch scripts, uploaded documents, and conversion artifacts
- marker/runtime: Marker runtime tools and optional model artifacts
- webhdp/sessions/<session_id>: WebHDP allocation hold jobs, inputs, outputs, logs, and request/response JSON
- webhdp/runtime: WebHDP HDP component runtime files, including external_code/fast_renderer and external_code/any_to_usdz
- webhdp/bin: trusted WebHDP component runner entrypoints called by the WebHDP adapter
- vggt/sessions/<session_id>: reserved for future VGGT workloads
- shared/cache: optional shared runtime cache for future apps
README
EOF

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER_PATH="${SCRIPT_DIR}/webhdp_component_runner.py"
if [ -f "${RUNNER_PATH}" ]; then
  echo "Installing WebHDP component runner..."
  scp -i "${SSH_KEY}" "${RUNNER_PATH}" "${USER_NAME}@${HOST}:${APPS_ROOT}/webhdp/bin/webhdp_component_runner.py"
  ssh -i "${SSH_KEY}" "${USER_NAME}@${HOST}" "chmod 700 '${APPS_ROOT}/webhdp/bin/webhdp_component_runner.py'"
else
  echo "WebHDP component runner not found at ${RUNNER_PATH}; skipping runner upload."
fi

echo "Done."
