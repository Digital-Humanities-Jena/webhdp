import sqlite3

from sqlalchemy import create_engine

from database.database import db
from services.schema_bootstrap_service import (
    BASELINE_ALEMBIC_REVISION,
    inspect_migration_state,
    missing_native_pipeline_tables,
    native_pipeline_table_names,
)


def test_inspect_migration_state_identifies_empty_database(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'empty.db'}"

    state = inspect_migration_state(database_url)

    assert state["status"] == "empty"
    assert state["should_stamp_baseline"] is False
    assert state["stamp_revision"] is None


def test_inspect_migration_state_identifies_legacy_unversioned_database(tmp_path):
    database_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(database_path)
    connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
    connection.commit()
    connection.close()

    state = inspect_migration_state(f"sqlite:///{database_path}")

    assert state["status"] == "legacy_unversioned"
    assert state["should_stamp_baseline"] is True
    assert state["stamp_revision"] == BASELINE_ALEMBIC_REVISION


def test_inspect_migration_state_reads_existing_revision(tmp_path):
    database_path = tmp_path / "versioned.db"
    connection = sqlite3.connect(database_path)
    connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
    connection.execute("INSERT INTO alembic_version (version_num) VALUES (?)", ("4b7a5f17d9c1",))
    connection.commit()
    connection.close()

    state = inspect_migration_state(f"sqlite:///{database_path}")

    assert state["status"] == "versioned"
    assert state["current_revision"] == "4b7a5f17d9c1"
    assert state["should_stamp_baseline"] is False


def test_missing_native_pipeline_tables_reports_remaining_tables(tmp_path):
    database_path = tmp_path / "partial-native.db"
    database_url = f"sqlite:///{database_path}"
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            db.metadata.tables["component_definitions"].create(bind=connection, checkfirst=True)
    finally:
        engine.dispose()

    missing = missing_native_pipeline_tables(database_url)

    assert "component_definitions" not in missing
    assert set(missing).issubset(set(native_pipeline_table_names()))
    assert len(missing) == len(native_pipeline_table_names()) - 1
