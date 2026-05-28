#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-hpc-login}"
REMOTE_ROOT="${REMOTE_ROOT:-/home/webhdp-user/webhdp}"
REMOTE_ARCHIVE_DIR="${REMOTE_ARCHIVE_DIR:-$REMOTE_ROOT/images/docker-archive}"
REMOTE_SIF_DIR="${REMOTE_SIF_DIR:-$REMOTE_ROOT/images/sif}"

ssh "$REMOTE_HOST" "set -euo pipefail
mkdir -p '$REMOTE_SIF_DIR'
export TMPDIR=/tmp
export SINGULARITY_TMPDIR=/tmp
export SINGULARITY_CACHEDIR=/tmp/\$USER-sing-cache
mkdir -p \"\$SINGULARITY_CACHEDIR\"

pull_from_archive() {
  local archive_file=\"\$1\"
  local sif_file=\"\$2\"
  local src=\"docker-archive://\$archive_file\"
  echo \"==> singularity pull \$sif_file from \$src\"
  singularity pull -F \"\$sif_file\" \"\$src\"
}

pull_from_archive '$REMOTE_ARCHIVE_DIR/backend.tar' '$REMOTE_SIF_DIR/backend.sif'
pull_from_archive '$REMOTE_ARCHIVE_DIR/fast-renderer.tar' '$REMOTE_SIF_DIR/fast-renderer.sif'
pull_from_archive '$REMOTE_ARCHIVE_DIR/any-to-usdz.tar' '$REMOTE_SIF_DIR/any-to-usdz.sif'
pull_from_archive '$REMOTE_ARCHIVE_DIR/redis.tar' '$REMOTE_SIF_DIR/redis.sif'

for optional_archive in \
  local-edm-postgres \
  local-edm-mongo \
  local-edm-solr \
  local-edm-minio \
  local-edm-mc \
  local-edm-validator; do
  if [[ -f '$REMOTE_ARCHIVE_DIR/'\"\$optional_archive\"'.tar' ]]; then
    pull_from_archive '$REMOTE_ARCHIVE_DIR/'\"\$optional_archive\"'.tar' '$REMOTE_SIF_DIR/'\"\$optional_archive\"'.sif'
  fi
done

ls -lh '$REMOTE_SIF_DIR'
"

echo "SIF conversion completed on $REMOTE_HOST"
