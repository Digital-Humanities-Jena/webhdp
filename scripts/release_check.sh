#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

enabled() {
  [[ "${1:-}" =~ ^(1|true|yes|on)$ ]]
}

compose_config_quiet() {
  local created_env=0

  if [[ ! -f .env ]]; then
    cp .env.example .env
    created_env=1
    echo "Using temporary .env copied from .env.example for Docker Compose config validation."
  fi

  set +e
  docker compose "$@" config --quiet
  local rc=$?
  set -e

  if [[ "$created_env" -eq 1 ]]; then
    rm -f .env
  fi

  return "$rc"
}

echo "==> Developer documentation catalog"
uv run python scripts/check_developer_docs.py

echo "==> OpenAPI contract freshness"
uv run python scripts/check_openapi_fresh.py

echo "==> HDP Component manifest validation"
uv run python scripts/validate_hdp_components.py

echo "==> Backend tests"
uv run pytest

echo "==> Frontend unit tests"
(cd frontend && npm run test:unit)

echo "==> Frontend production build"
(cd frontend && npm run build)

echo "==> Frontend production dependency audit"
(cd frontend && npm audit --omit=dev --audit-level=moderate)

echo "==> Core browser workflow tests"
(cd frontend && npm run test:e2e:core)

echo "==> Browser tests against isolated backend routes"
(cd frontend && npm run test:e2e:backend)

if enabled "${RUN_E2E:-false}"; then
  echo "==> Frontend browser E2E tests"
  (cd frontend && npm run test:e2e)
fi

echo "==> Release asset validation"
uv run python scripts/check_release_assets.py

echo "==> HPC-Link backend tests"
(
  cd hpc-link
  CORS_ORIGINS='["http://localhost:5173","http://127.0.0.1:5173"]' \
    uv run --with pytest --with-requirements requirements.txt python -m pytest
)

echo "==> HPC-Link frontend lint/build/audit"
(cd hpc-link/frontend && npm run lint && npm run build && npm audit --omit=dev --audit-level=moderate)

echo "==> Docker Compose base validation"
compose_config_quiet

echo "==> Docker Compose production validation"
compose_config_quiet -f docker-compose.prod.yml

echo "==> Docker Compose local EDM validator overlay validation"
compose_config_quiet -f docker-compose.yml -f docker-compose.edm-validator.yml

echo "==> Docker Compose HPC overlay validation"
compose_config_quiet -f docker-compose.yml -f docker-compose.hpc.yml

if enabled "${CHECK_RELEASE_IMAGES:-false}" || [[ "${FLASK_ENV:-}" = "production" ]]; then
  echo "==> Production image tag validation"
  uv run python scripts/check_release_images.py
fi

if enabled "${RUN_DEVCONTAINER:-false}"; then
  echo "==> Devcontainer build"
  make devcontainer-check
fi

if enabled "${VERIFY_LOCAL_EDM_VALIDATOR:-false}"; then
  echo "==> Local EDM validator source verification"
  bash scripts/setup_local_edm_validator.sh --verify-only
fi

echo "==> Backup service import check"
uv run python -c "from services.backup_service import BackupService; print(BackupService.__name__)"

echo "==> Backup script syntax check"
uv run python -m py_compile \
  services/backup_service.py \
  scripts/backup.py \
  scripts/restore_backup.py \
  scripts/list_backups.py \
  scripts/prune_backups.py \
  scripts/backup_status.py \
  scripts/restore_drill.py \
  scripts/maintenance.py \
  scripts/wait_for_celery_drain.py \
  scripts/readiness_check.py \
  scripts/check_release_assets.py \
  scripts/check_release_images.py

echo "==> Shell script syntax check"
bash -n scripts/release_check.sh
bash -n scripts/scheduled_backup.sh
bash -n scripts/pre_update.sh
bash -n scripts/build_images.sh

echo "Release check completed successfully."
