"""Exercise the reservation migration on a database with an existing allocation."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


def test_existing_scheduler_owned_allocation_survives_upgrade_and_downgrade(tmp_path):
    path = Path(__file__).resolve().parents[1] / "migrations/versions/e1f0a2b3c456_hpc_reservations.py"
    spec = importlib.util.spec_from_file_location("hpc_reservation_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'webhdp.sqlite'}")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE hpc_allocations (id INTEGER PRIMARY KEY, remote_job_id VARCHAR(128))"))
        connection.execute(sa.text("INSERT INTO hpc_allocations (id, remote_job_id) VALUES (1, '4321')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migrated = connection.execute(sa.text("SELECT remote_job_id, reservation_id FROM hpc_allocations")).one()
            assert migrated == ("4321", None)
            assert set(sa.inspect(connection).get_table_names()) >= {"hpc_reservations", "hpc_reservation_grants"}
            assert sa.inspect(connection).get_foreign_keys("hpc_allocations")[0]["referred_table"] == "hpc_reservations"
            migration.downgrade()
        assert connection.execute(sa.text("SELECT remote_job_id FROM hpc_allocations")).scalar_one() == "4321"
        assert "hpc_reservations" not in sa.inspect(connection).get_table_names()
    engine.dispose()
