#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PROVIDER="${BACKUP_PROVIDER:-local}"
BACKUP_ARGS=(--type pre-update --provider "$PROVIDER")
if [[ "${BACKUP_INCLUDE_CREDENTIALS:-true}" =~ ^(0|false|no|off)$ ]]; then
  BACKUP_ARGS+=(--no-credentials)
fi
if [[ "${BACKUP_ENCRYPT:-}" =~ ^(1|true|yes|on)$ ]]; then
  BACKUP_ARGS+=(--encrypt)
fi

cleanup() {
  if [[ "${MAINTENANCE_ENABLED_BY_SCRIPT:-0}" = "1" ]]; then
    uv run python scripts/maintenance.py disable >/dev/null || true
  fi
}
trap cleanup EXIT

echo "==> Running release checks before touching live data"
CHECK_RELEASE_IMAGES="${CHECK_RELEASE_IMAGES:-true}" ./scripts/release_check.sh

echo "==> Enabling maintenance mode"
uv run python scripts/maintenance.py enable --reason "pre-update backup and migration"
MAINTENANCE_ENABLED_BY_SCRIPT=1

if [[ "${WAIT_FOR_CELERY_DRAIN:-true}" =~ ^(1|true|yes|on)$ ]]; then
  echo "==> Waiting for Celery queue to drain"
  uv run python scripts/wait_for_celery_drain.py
fi

echo "==> Creating pre-update backup via ${PROVIDER}"
BACKUP_JSON="$(mktemp)"
uv run python scripts/backup.py "${BACKUP_ARGS[@]}" --json > "$BACKUP_JSON"
ARCHIVE_PATH="$(python - "$BACKUP_JSON" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["archive_path"])
PY
)"

echo "==> Running restore drill for ${ARCHIVE_PATH}"
uv run python scripts/restore_drill.py "$ARCHIVE_PATH"

echo "==> Applying database migrations"
export FLASK_APP="${FLASK_APP:-app.py}"
export SKIP_DB_CREATE_ALL="${SKIP_DB_CREATE_ALL:-1}"
uv run python -m flask db upgrade

echo "==> Running post-migration readiness check"
uv run python scripts/readiness_check.py --strict-backups

echo "Pre-update checks completed successfully."
