"""add hpc link integration tables

Revision ID: 8b7e2f4c9a10
Revises: f2b6d74c1c3a
Create Date: 2026-04-28 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "8b7e2f4c9a10"
down_revision = "6d4c2ab9f1a0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hpc_link_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("require_for_components", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("encrypted_token", sa.Text(), nullable=True),
        sa.Column("masked_token_preview", sa.String(length=64), nullable=True),
        sa.Column("default_partition", sa.String(length=64), nullable=False, server_default="partition-a"),
        sa.Column("default_gpu_type", sa.String(length=64), nullable=True),
        sa.Column("default_gpu_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("default_duration_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("max_active_allocations", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("max_active_allocations_per_user", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("remote_data_root", sa.String(length=500), nullable=True),
        sa.Column("remote_apps_root", sa.String(length=500), nullable=True),
        sa.Column("last_validation_status", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("last_validation_error", sa.Text(), nullable=True),
        sa.Column("last_validated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hpc_link_configs")),
    )
    op.create_table(
        "hpc_allocations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("purpose", sa.String(length=32), nullable=False, server_default="workflow"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("requested_partition", sa.String(length=64), nullable=False),
        sa.Column("requested_gpu_type", sa.String(length=64), nullable=True),
        sa.Column("requested_gpu_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("requested_duration_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("remote_session_id", sa.String(length=128), nullable=True),
        sa.Column("remote_job_id", sa.String(length=128), nullable=True),
        sa.Column("remote_session_dir", sa.String(length=1000), nullable=True),
        sa.Column("remote_input_dir", sa.String(length=1000), nullable=True),
        sa.Column("remote_output_dir", sa.String(length=1000), nullable=True),
        sa.Column("scheduler_state", sa.String(length=64), nullable=True),
        sa.Column("scheduler_reason", sa.String(length=255), nullable=True),
        sa.Column("node_name", sa.String(length=255), nullable=True),
        sa.Column("last_health_json", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("allocated_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("released_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], name=op.f("fk_hpc_allocations_session_id_sessions")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_hpc_allocations_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hpc_allocations")),
        sa.UniqueConstraint("public_id", name=op.f("uq_hpc_allocations_public_id")),
    )
    op.create_index(op.f("ix_hpc_allocations_remote_session_id"), "hpc_allocations", ["remote_session_id"], unique=False)
    op.create_index(op.f("ix_hpc_allocations_session_id"), "hpc_allocations", ["session_id"], unique=False)
    op.create_index(op.f("ix_hpc_allocations_status"), "hpc_allocations", ["status"], unique=False)
    op.create_index(op.f("ix_hpc_allocations_user_id"), "hpc_allocations", ["user_id"], unique=False)
    op.create_table(
        "hpc_artifacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("allocation_id", sa.Integer(), nullable=False),
        sa.Column("pipeline_run_id", sa.Integer(), nullable=True),
        sa.Column("step_run_id", sa.Integer(), nullable=True),
        sa.Column("playground_run_id", sa.Integer(), nullable=True),
        sa.Column("record_id", sa.Integer(), nullable=True),
        sa.Column("component_key", sa.String(length=120), nullable=False),
        sa.Column("artifact_kind", sa.String(length=50), nullable=False, server_default="file"),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("remote_path", sa.String(length=1000), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["allocation_id"], ["hpc_allocations.id"], name=op.f("fk_hpc_artifacts_allocation_id_hpc_allocations")),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"], name=op.f("fk_hpc_artifacts_pipeline_run_id_pipeline_runs")),
        sa.ForeignKeyConstraint(["playground_run_id"], ["playground_runs.id"], name=op.f("fk_hpc_artifacts_playground_run_id_playground_runs")),
        sa.ForeignKeyConstraint(["step_run_id"], ["step_runs.id"], name=op.f("fk_hpc_artifacts_step_run_id_step_runs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hpc_artifacts")),
    )
    op.create_index(op.f("ix_hpc_artifacts_allocation_id"), "hpc_artifacts", ["allocation_id"], unique=False)
    op.create_index(op.f("ix_hpc_artifacts_pipeline_run_id"), "hpc_artifacts", ["pipeline_run_id"], unique=False)
    op.create_index(op.f("ix_hpc_artifacts_playground_run_id"), "hpc_artifacts", ["playground_run_id"], unique=False)
    op.create_index(op.f("ix_hpc_artifacts_step_run_id"), "hpc_artifacts", ["step_run_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_hpc_artifacts_step_run_id"), table_name="hpc_artifacts")
    op.drop_index(op.f("ix_hpc_artifacts_playground_run_id"), table_name="hpc_artifacts")
    op.drop_index(op.f("ix_hpc_artifacts_pipeline_run_id"), table_name="hpc_artifacts")
    op.drop_index(op.f("ix_hpc_artifacts_allocation_id"), table_name="hpc_artifacts")
    op.drop_table("hpc_artifacts")
    op.drop_index(op.f("ix_hpc_allocations_user_id"), table_name="hpc_allocations")
    op.drop_index(op.f("ix_hpc_allocations_status"), table_name="hpc_allocations")
    op.drop_index(op.f("ix_hpc_allocations_session_id"), table_name="hpc_allocations")
    op.drop_index(op.f("ix_hpc_allocations_remote_session_id"), table_name="hpc_allocations")
    op.drop_table("hpc_allocations")
    op.drop_table("hpc_link_configs")
