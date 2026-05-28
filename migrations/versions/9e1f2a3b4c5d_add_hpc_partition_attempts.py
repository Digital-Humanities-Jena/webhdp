"""add hpc partition fallback attempt state

Revision ID: 9e1f2a3b4c5d
Revises: 8c9d0e1f2a3b
Create Date: 2026-05-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "9e1f2a3b4c5d"
down_revision = "8c9d0e1f2a3b"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("hpc_link_configs") as batch_op:
        batch_op.alter_column(
            "default_partition",
            existing_type=sa.String(length=64),
            server_default="partition-a",
            existing_nullable=False,
        )

    with op.batch_alter_table("hpc_allocations") as batch_op:
        batch_op.add_column(sa.Column("partition_sequence_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("partition_attempt_index", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("partition_attempt_started_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("partition_attempt_history_json", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("hpc_allocations") as batch_op:
        batch_op.drop_column("partition_attempt_history_json")
        batch_op.drop_column("partition_attempt_started_at")
        batch_op.drop_column("partition_attempt_index")
        batch_op.drop_column("partition_sequence_json")

    with op.batch_alter_table("hpc_link_configs") as batch_op:
        batch_op.alter_column(
            "default_partition",
            existing_type=sa.String(length=64),
            server_default="partition-a",
            existing_nullable=False,
        )
