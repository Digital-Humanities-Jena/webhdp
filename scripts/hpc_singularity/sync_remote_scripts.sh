#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REMOTE_HOST="${REMOTE_HOST:-hpc-login}"
REMOTE_ROOT="${REMOTE_ROOT:-/home/webhdp-user/webhdp}"
REMOTE_SCRIPT_DIR="$REMOTE_ROOT/scripts/hpc_singularity/remote"

ssh "$REMOTE_HOST" "mkdir -p '$REMOTE_SCRIPT_DIR'"
rsync -avP "$ROOT_DIR/scripts/hpc_singularity/remote/" "$REMOTE_HOST:$REMOTE_SCRIPT_DIR/"

ssh "$REMOTE_HOST" "chmod +x '$REMOTE_SCRIPT_DIR/start_services.sh' '$REMOTE_SCRIPT_DIR/stop_services.sh' '$REMOTE_SCRIPT_DIR/status_services.sh' '$REMOTE_SCRIPT_DIR/webhdp.sbatch' '$REMOTE_SCRIPT_DIR/webhdp_hpc_batch.py' '$REMOTE_SCRIPT_DIR/webhdp_hpc_tmux.sh'"

echo "Remote scripts synced to $REMOTE_HOST:$REMOTE_SCRIPT_DIR"
