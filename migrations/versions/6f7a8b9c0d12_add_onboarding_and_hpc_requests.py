"""add onboarding and hpc resource requests

Revision ID: 6f7a8b9c0d12
Revises: 5e6f7a8091b2
Create Date: 2026-05-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "6f7a8b9c0d12"
down_revision = "5e6f7a8091b2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("onboarding_required", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("onboarding_completed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("onboarding_skipped_at", sa.DateTime(), nullable=True))

    op.create_table(
        "hpc_resource_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("affiliation", sa.String(length=255), nullable=False),
        sa.Column("use_cases_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("reviewer_user_id", sa.Integer(), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"], name=op.f("fk_hpc_resource_requests_reviewer_user_id_users")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_hpc_resource_requests_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hpc_resource_requests")),
        sa.UniqueConstraint("public_id", name=op.f("uq_hpc_resource_requests_public_id")),
    )
    op.create_index(op.f("ix_hpc_resource_requests_public_id"), "hpc_resource_requests", ["public_id"], unique=True)
    op.create_index(op.f("ix_hpc_resource_requests_reviewer_user_id"), "hpc_resource_requests", ["reviewer_user_id"], unique=False)
    op.create_index(op.f("ix_hpc_resource_requests_status"), "hpc_resource_requests", ["status"], unique=False)
    op.create_index(op.f("ix_hpc_resource_requests_user_id"), "hpc_resource_requests", ["user_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_hpc_resource_requests_user_id"), table_name="hpc_resource_requests")
    op.drop_index(op.f("ix_hpc_resource_requests_status"), table_name="hpc_resource_requests")
    op.drop_index(op.f("ix_hpc_resource_requests_reviewer_user_id"), table_name="hpc_resource_requests")
    op.drop_index(op.f("ix_hpc_resource_requests_public_id"), table_name="hpc_resource_requests")
    op.drop_table("hpc_resource_requests")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("onboarding_skipped_at")
        batch_op.drop_column("onboarding_completed_at")
        batch_op.drop_column("onboarding_required")
