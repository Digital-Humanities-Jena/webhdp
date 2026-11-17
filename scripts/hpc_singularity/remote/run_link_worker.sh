#!/usr/bin/env bash
# Opt-in foreground entrypoint for an operator supervisor. No submission,
# allocation, migration, config sourcing, PID killing, or background daemon.
set -euo pipefail
: "${ROOT:?Set the existing WebHDP deployment root}"
: "${ENV_FILE:?Set the existing private backend environment file}"
SIF_DIR="${SIF_DIR:-$ROOT/images/sif}"
for path in "$ENV_FILE" "$SIF_DIR/backend.sif"; do
  [[ -f "$path" ]] || { echo 'Required worker file is missing' >&2; exit 2; }
done
for path in "$ROOT/instance" "$ROOT/logs" "$ROOT/hdp-shared/sessions" \
  "$ROOT/data/local_input" "$ROOT/data/local_output"; do
  [[ -d "$path" ]] || { echo 'Required persistence directory is missing' >&2; exit 2; }
done
# The immutable backend.sif contains all code. Do not bind a mutable checkout
# over it. The API must use the same release and these exact persistence paths.
# Keep Link storage under /app/instance/webhdp-link and SQLite locks beside DB.
exec singularity exec --cleanenv --env-file "$ENV_FILE" --pwd /app \
  --env RUN_DB_BOOTSTRAP=0 --env SKIP_DB_CREATE_ALL=1 \
  --env WEBHDP_LINK_STORAGE_PATH=/app/instance/webhdp-link \
  -B "$ROOT/instance:/app/instance" -B "$ROOT/logs:/app/logs" \
  -B "$ROOT/hdp-shared/sessions:/shared/sessions" \
  -B "$ROOT/data/local_input:/data/local_input" \
  -B "$ROOT/data/local_output:/data/local_output" \
  "$SIF_DIR/backend.sif" python /app/scripts/webhdp_link_worker.py --poll-seconds 2
