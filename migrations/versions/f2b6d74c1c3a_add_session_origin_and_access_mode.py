"""add session origin and access mode

Revision ID: f2b6d74c1c3a
Revises: e1f7f20a9d4b
Create Date: 2026-03-30 23:10:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f2b6d74c1c3a"
down_revision = "e1f7f20a9d4b"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("origin_type", sa.String(length=32), nullable=False, server_default="workflow"))
        batch_op.add_column(sa.Column("access_mode", sa.String(length=32), nullable=False, server_default="full"))
        batch_op.add_column(sa.Column("origin_metadata_json", sa.Text(), nullable=True))

    op.execute("UPDATE sessions SET origin_type = 'workflow' WHERE origin_type IS NULL")
    op.execute("UPDATE sessions SET access_mode = 'full' WHERE access_mode IS NULL")


def downgrade():
    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.drop_column("origin_metadata_json")
        batch_op.drop_column("access_mode")
        batch_op.drop_column("origin_type")
