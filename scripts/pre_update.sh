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

MAINTENANCE_ENABLED_BY_SCRIPT=0
DATABASE_MIGRATION_STARTED=0
UPDATE_CHECKS_PASSED=0
UPDATE_CHECK_DIR=""

cleanup() {
  if [[ "$MAINTENANCE_ENABLED_BY_SCRIPT" = "1" ]]; then
    if [[ "$DATABASE_MIGRATION_STARTED" = "1" && "$UPDATE_CHECKS_PASSED" != "1" ]]; then
      echo "Maintenance mode remains enabled because the database upgrade checks failed." >&2
    else
      uv run python scripts/maintenance.py disable >/dev/null || true
    fi
  fi
  if [[ -n "$UPDATE_CHECK_DIR" ]]; then
    rm -f -- "$UPDATE_CHECK_DIR/backup.json"
    if [[ "$DATABASE_MIGRATION_STARTED" = "1" && "$UPDATE_CHECKS_PASSED" != "1" ]]; then
      echo "Account snapshot retained at $UPDATE_CHECK_DIR/accounts.json for verification during recovery." >&2
    else
      rm -f -- "$UPDATE_CHECK_DIR/accounts.json"
      rmdir -- "$UPDATE_CHECK_DIR"
    fi
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

UPDATE_CHECK_DIR="$(mktemp -d)"
ACCOUNT_DB="$(uv run python - <<'PY'
from dotenv import load_dotenv
from services.backup_service import BackupService

load_dotenv(".env")
print(BackupService.resolve_paths().database)
PY
)"
ACCOUNT_SNAPSHOT="$UPDATE_CHECK_DIR/accounts.json"
echo "==> Recording existing accounts before migration"
uv run python scripts/check_account_continuity.py capture --database "$ACCOUNT_DB" --snapshot "$ACCOUNT_SNAPSHOT"

echo "==> Creating pre-update backup via ${PROVIDER}"
BACKUP_JSON="$UPDATE_CHECK_DIR/backup.json"
uv run python scripts/backup.py "${BACKUP_ARGS[@]}" --json > "$BACKUP_JSON"
ARCHIVE_PATH="$(uv run python - "$BACKUP_JSON" <<'PY'
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
DATABASE_MIGRATION_STARTED=1
uv run python -m flask db upgrade

echo "==> Verifying existing accounts after migration"
uv run python scripts/check_account_continuity.py verify --database "$ACCOUNT_DB" --snapshot "$ACCOUNT_SNAPSHOT"

echo "==> Running post-migration readiness check"
uv run python scripts/readiness_check.py --strict-backups

UPDATE_CHECKS_PASSED=1
echo "Pre-update checks completed successfully."
