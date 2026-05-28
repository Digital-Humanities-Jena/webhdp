#!/bin/sh
set -e

export FLASK_APP="${FLASK_APP:-app.py}"
export SKIP_DB_CREATE_ALL="${SKIP_DB_CREATE_ALL:-1}"

bootstrap_database() {
    migration_state="$(python - <<'PY'
import os
import sys

from services.schema_bootstrap_service import inspect_migration_state

database_url = os.environ.get("DATABASE_URL", "sqlite:////app/instance/hdp_web.db")
state = inspect_migration_state(database_url)

if state["should_stamp_baseline"]:
    raise SystemExit(10)

raise SystemExit(0)
PY
)" || migration_state=$?

    if [ "${migration_state:-0}" -ne 0 ] && [ "${migration_state:-0}" -ne 10 ]; then
        echo "Failed to inspect database migration state."
        exit "${migration_state}"
    fi

    if [ "${migration_state:-0}" -eq 10 ]; then
        echo "Stamping legacy database schema at Alembic baseline revision..."
        python -m flask db stamp dffd40c829a8
    fi

    echo "Applying database migrations..."
    python -m flask db upgrade

    echo "Verifying native pipeline schema..."
    python - <<'PY'
import os
import sys

from services.schema_bootstrap_service import missing_native_pipeline_tables

database_url = os.environ.get("DATABASE_URL", "sqlite:////app/instance/hdp_web.db")
missing = missing_native_pipeline_tables(database_url)
if missing:
    if os.environ.get("ENABLE_NATIVE_PIPELINE_SCHEMA_FALLBACK", "").strip().lower() not in {"1", "true", "yes", "on"}:
        print("Missing native pipeline tables after migrations:", ", ".join(missing))
        raise SystemExit(1)

    print("Fallback schema repair enabled; creating missing native pipeline tables:", ", ".join(missing))
    from app import app
    from database.database import db
    from services.schema_bootstrap_service import native_pipeline_tables

    with app.app_context():
        existing = set(missing_native_pipeline_tables(database_url))
        tables = [table for table in native_pipeline_tables() if table.name in existing]
        if tables:
            db.metadata.create_all(bind=db.engine, tables=tables)
            missing = missing_native_pipeline_tables(database_url)
    if missing:
        print("Native pipeline schema verification still failing:", ", ".join(missing))
        raise SystemExit(1)
PY

    echo "Initializing default data..."
    python -m flask init-data
}

if [ "${RUN_DB_BOOTSTRAP:-0}" = "1" ]; then
    bootstrap_database
fi

# If arguments are passed (e.g., celery), run them
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

# Start Gunicorn (Default behavior if no command provided)
echo "Starting Gunicorn..."
exec gunicorn --bind 0.0.0.0:5000 \
    --workers 4 \
    --timeout 1200 \
    --access-logfile - \
    --error-logfile - \
    --preload \
    app:app
