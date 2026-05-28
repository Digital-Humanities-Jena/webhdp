#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PROVIDER="${BACKUP_PROVIDER:-local}"
BACKUP_TYPE="${BACKUP_TYPE:-scheduled}"
PRUNE_PROVIDER="${BACKUP_PRUNE_PROVIDER:-$PROVIDER}"
BACKUP_ARGS=(--type "$BACKUP_TYPE" --provider "$PROVIDER")
if [[ "${BACKUP_INCLUDE_CREDENTIALS:-true}" =~ ^(0|false|no|off)$ ]]; then
  BACKUP_ARGS+=(--no-credentials)
fi

echo "==> Creating ${BACKUP_TYPE} backup via ${PROVIDER}"
BACKUP_JSON="$(mktemp)"
uv run python scripts/backup.py "${BACKUP_ARGS[@]}" --json > "$BACKUP_JSON"
ARCHIVE_PATH="$(python - "$BACKUP_JSON" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["archive_path"])
PY
)"

if [[ "${BACKUP_RESTORE_DRILL:-true}" =~ ^(1|true|yes|on)$ ]]; then
  echo "==> Running restore drill for ${ARCHIVE_PATH}"
  uv run python scripts/restore_drill.py "$ARCHIVE_PATH"
fi

echo "==> Applying backup retention for ${PRUNE_PROVIDER}"
uv run python scripts/prune_backups.py --provider "$PRUNE_PROVIDER" --apply

echo "Scheduled backup completed successfully."
