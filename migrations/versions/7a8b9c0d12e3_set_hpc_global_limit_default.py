"""set hpc global allocation limit default

Revision ID: 7a8b9c0d12e3
Revises: 6f7a8b9c0d12
Create Date: 2026-05-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "7a8b9c0d12e3"
down_revision = "6f7a8b9c0d12"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("hpc_link_configs", schema=None) as batch_op:
        batch_op.alter_column(
            "max_active_allocations",
            existing_type=sa.Integer(),
            nullable=False,
            server_default="3",
        )
    op.execute("UPDATE hpc_link_configs SET max_active_allocations = 3 WHERE max_active_allocations IS NULL OR max_active_allocations = 2")


def downgrade():
    with op.batch_alter_table("hpc_link_configs", schema=None) as batch_op:
        batch_op.alter_column(
            "max_active_allocations",
            existing_type=sa.Integer(),
            nullable=False,
            server_default="2",
        )
    op.execute("UPDATE hpc_link_configs SET max_active_allocations = 2 WHERE max_active_allocations = 3")
