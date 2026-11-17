"""Round-trip the actual Link migration against the application base schema."""

import importlib.util
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa

from database.database import db
from database.models import User, UserRole
from database import webhdp_link_models  # noqa: F401: register the metadata


def test_link_migration_upgrade_downgrade_and_reupgrade_preserve_base_data(tmp_path):
    path = Path(__file__).resolve().parents[1] / "migrations/versions/d9e0f1a2b345_webhdp_link.py"
    spec = importlib.util.spec_from_file_location("link_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine(f"sqlite:///{tmp_path}/migration.sqlite")
    base = [table for table in db.metadata.sorted_tables if not table.name.startswith("webhdp_link_")]
    expected = {table.name for table in db.metadata.sorted_tables if table.name.startswith("webhdp_link_")}
    assert len(expected) == 7
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        db.metadata.create_all(connection, tables=base)
        connection.execute(User.__table__.insert().values(email="retained@example.test", password_hash="not-a-login", role=UserRole.USER))
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        with Operations.context(context):
            migration.upgrade()
        assert expected <= set(sa.inspect(connection).get_table_names())
        assert compare_metadata(context, db.metadata) == []
        unique = sa.inspect(connection).get_unique_constraints("webhdp_link_runs")
        assert any(item["column_names"] == ["client_id", "user_id", "idempotency_key"] for item in unique)
        assert sa.inspect(connection).get_foreign_keys("webhdp_link_runs")
        with Operations.context(context):
            migration.downgrade()
        assert not expected & set(sa.inspect(connection).get_table_names())
        assert connection.execute(sa.select(User.__table__.c.email)).scalars().all() == ["retained@example.test"]
        with Operations.context(context):
            migration.upgrade()
        assert compare_metadata(context, db.metadata) == []
        assert connection.execute(sa.select(User.__table__.c.email)).scalars().all() == ["retained@example.test"]
    engine.dispose()
