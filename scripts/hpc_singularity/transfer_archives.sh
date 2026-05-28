#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARCHIVE_DIR="${ARCHIVE_DIR:-$ROOT_DIR/artifacts/hpc_singularity}"
REMOTE_HOST="${REMOTE_HOST:-hpc-login}"
REMOTE_ROOT="${REMOTE_ROOT:-/home/webhdp-user/webhdp}"
REMOTE_ARCHIVE_DIR="${REMOTE_ARCHIVE_DIR:-$REMOTE_ROOT/images/docker-archive}"

required_archives=(backend.tar fast-renderer.tar any-to-usdz.tar redis.tar SHA256SUMS)

for f in "${required_archives[@]}"; do
  if [[ ! -f "$ARCHIVE_DIR/$f" ]]; then
    echo "Missing archive: $ARCHIVE_DIR/$f" >&2
    exit 1
  fi
done

ssh "$REMOTE_HOST" "mkdir -p '$REMOTE_ARCHIVE_DIR'"
rsync -avP "$ARCHIVE_DIR/" "$REMOTE_HOST:$REMOTE_ARCHIVE_DIR/"

echo "Transferred archives to $REMOTE_HOST:$REMOTE_ARCHIVE_DIR"
