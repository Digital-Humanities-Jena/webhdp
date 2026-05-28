"""add community migration jobs

Revision ID: 8c9d0e1f2a3b
Revises: 7a8b9c0d12e3
Create Date: 2026-05-04 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "8c9d0e1f2a3b"
down_revision = "7a8b9c0d12e3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "community_migration_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=False),
        sa.Column("source_retrieval_id", sa.String(length=64), nullable=False),
        sa.Column("source_community", sa.String(length=120), nullable=False),
        sa.Column("target_community", sa.String(length=120), nullable=False),
        sa.Column("environment", sa.String(length=32), nullable=False, server_default="production"),
        sa.Column("filters_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("options_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("phase", sa.String(length=64), nullable=False, server_default="planned"),
        sa.Column("task_id", sa.String(length=120), nullable=True),
        sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("progress_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], name=op.f("fk_community_migration_jobs_requested_by_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_community_migration_jobs")),
        sa.UniqueConstraint("public_id", name=op.f("uq_community_migration_jobs_public_id")),
    )
    with op.batch_alter_table("community_migration_jobs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_community_migration_jobs_public_id"), ["public_id"], unique=True)
        batch_op.create_index(batch_op.f("ix_community_migration_jobs_requested_by_user_id"), ["requested_by_user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_community_migration_jobs_source_retrieval_id"), ["source_retrieval_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_community_migration_jobs_state"), ["state"], unique=False)
        batch_op.create_index(batch_op.f("ix_community_migration_jobs_task_id"), ["task_id"], unique=False)

    op.create_table(
        "community_migration_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("local_record_id", sa.Integer(), nullable=False),
        sa.Column("zenodo_record_id", sa.String(length=120), nullable=True),
        sa.Column("concept_rec_id", sa.String(length=120), nullable=True),
        sa.Column("record_title", sa.Text(), nullable=True),
        sa.Column("record_status", sa.String(length=32), nullable=True),
        sa.Column("record_origin", sa.String(length=64), nullable=True),
        sa.Column("is_editable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ineligibility_reason", sa.Text(), nullable=True),
        sa.Column("before_communities_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("after_communities_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("append_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("verify_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("remove_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("final_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["community_migration_jobs.id"], name=op.f("fk_community_migration_records_job_id_community_migration_jobs")),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], name=op.f("fk_community_migration_records_session_id_sessions")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_community_migration_records")),
        sa.UniqueConstraint("job_id", "session_id", "local_record_id", name="uq_community_migration_job_record"),
    )
    with op.batch_alter_table("community_migration_records", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_community_migration_records_job_id"), ["job_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_community_migration_records_session_id"), ["session_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_community_migration_records_zenodo_record_id"), ["zenodo_record_id"], unique=False)


def downgrade():
    op.drop_table("community_migration_records")
    op.drop_table("community_migration_jobs")
