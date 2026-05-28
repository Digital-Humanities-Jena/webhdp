"""add user capabilities json

Revision ID: 2f5f1d5ee3c9
Revises: 4b7a5f17d9c1
Create Date: 2026-03-30 10:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2f5f1d5ee3c9"
down_revision = "4b7a5f17d9c1"
branch_labels = None
depends_on = None


def _using_sqlite():
    return op.get_bind().dialect.name == "sqlite"


def upgrade():
    sqlite = _using_sqlite()
    if sqlite:
        op.execute("PRAGMA foreign_keys=OFF")
        op.execute("DROP TABLE IF EXISTS _alembic_tmp_users")

    try:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "capabilities_json",
                    sa.Text(),
                    nullable=False,
                    server_default=sa.text("'[]'"),
                )
            )
    finally:
        if sqlite:
            op.execute("PRAGMA foreign_keys=ON")


def downgrade():
    sqlite = _using_sqlite()
    if sqlite:
        op.execute("PRAGMA foreign_keys=OFF")
        op.execute("DROP TABLE IF EXISTS _alembic_tmp_users")

    try:
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.drop_column("capabilities_json")
    finally:
        if sqlite:
            op.execute("PRAGMA foreign_keys=ON")
