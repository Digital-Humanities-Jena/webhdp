#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="${OUT_DIR:-$ROOT_DIR/artifacts/hpc_singularity}"
PLATFORM="${PLATFORM:-linux/amd64}"
TAG="${TAG:-singularity-latest}"

REMOTE_HOST="${REMOTE_HOST:-hpc-login}"
REMOTE_ROOT="${REMOTE_ROOT:-/home/webhdp-user/webhdp}"
REMOTE_ARCHIVE_DIR="${REMOTE_ARCHIVE_DIR:-$REMOTE_ROOT/images/docker-archive}"
REMOTE_SIF_DIR="${REMOTE_SIF_DIR:-$REMOTE_ROOT/images/sif}"

IMAGE_TAG="webhdp-frontend:$TAG"
FRONTEND_TAR="$OUT_DIR/frontend.tar"

mkdir -p "$OUT_DIR"

echo "==> Building optional frontend image ($IMAGE_TAG) for $PLATFORM"
docker buildx build \
  --platform "$PLATFORM" \
  --load \
  -f "$ROOT_DIR/frontend/Dockerfile.singularity" \
  -t "$IMAGE_TAG" \
  "$ROOT_DIR/frontend"

echo "==> Exporting $IMAGE_TAG -> $FRONTEND_TAR"
docker save -o "$FRONTEND_TAR" "$IMAGE_TAG"
ls -lh "$FRONTEND_TAR"

echo "==> Transferring frontend archive to $REMOTE_HOST:$REMOTE_ARCHIVE_DIR"
ssh "$REMOTE_HOST" "mkdir -p '$REMOTE_ARCHIVE_DIR' '$REMOTE_SIF_DIR'"
rsync -avP "$FRONTEND_TAR" "$REMOTE_HOST:$REMOTE_ARCHIVE_DIR/frontend.tar"

echo "==> Converting frontend archive to SIF on $REMOTE_HOST"
ssh "$REMOTE_HOST" "set -euo pipefail
export TMPDIR=/tmp
export SINGULARITY_TMPDIR=/tmp
export SINGULARITY_CACHEDIR=/tmp/\$USER-sing-cache
mkdir -p \"\$SINGULARITY_CACHEDIR\" '$REMOTE_SIF_DIR'
singularity pull -F '$REMOTE_SIF_DIR/frontend.sif' 'docker-archive://$REMOTE_ARCHIVE_DIR/frontend.tar'
ls -lh '$REMOTE_SIF_DIR/frontend.sif'
"

echo "==> Syncing runtime scripts (frontend optional support)"
"$ROOT_DIR/scripts/hpc_singularity/sync_remote_scripts.sh"

echo "Done."
echo "To enable frontend in HPC Singularity, set in $REMOTE_ROOT/.env.hpc.singularity:"
echo "  FRONTEND_IN_SINGULARITY=true"
echo "  FRONTEND_PORT=8080"
echo "Then restart the Slurm job."
