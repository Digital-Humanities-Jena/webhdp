"""Register existing HPC reservations and audit their exclusive claims."""

from alembic import op
import sqlalchemy as sa


revision = "e1f0a2b3c456"
down_revision = "c8d9e0f12345"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hpc_reservations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(36), nullable=False, unique=True),
        sa.Column("gateway_reservation_id", sa.String(128), nullable=False, unique=True),
        sa.Column("gateway_url", sa.String(500), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("scheduler_json", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "hpc_reservation_grants",
        sa.Column("reservation_id", sa.Integer(), sa.ForeignKey("hpc_reservations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    )
    with op.batch_alter_table("hpc_allocations") as batch:
        batch.add_column(sa.Column("reservation_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_hpc_allocation_reservation", "hpc_reservations", ["reservation_id"], ["id"])
        batch.create_index("ix_hpc_allocations_reservation_id", ["reservation_id"])


def downgrade():
    with op.batch_alter_table("hpc_allocations") as batch:
        batch.drop_index("ix_hpc_allocations_reservation_id")
        batch.drop_constraint("fk_hpc_allocation_reservation", type_="foreignkey")
        batch.drop_column("reservation_id")
    op.drop_table("hpc_reservation_grants")
    op.drop_table("hpc_reservations")
