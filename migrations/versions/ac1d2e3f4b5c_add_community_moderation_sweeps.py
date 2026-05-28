"""add community moderation sweeps

Revision ID: ac1d2e3f4b5c
Revises: 9e1f2a3b4c5d
Create Date: 2026-05-26 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "ac1d2e3f4b5c"
down_revision = "9e1f2a3b4c5d"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade():
    if not _has_table("community_moderation_sweep_jobs"):
        op.create_table(
            "community_moderation_sweep_jobs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("public_id", sa.String(length=36), nullable=False),
            sa.Column("task_id", sa.String(length=120), nullable=True),
            sa.Column("requested_by_user_id", sa.Integer(), nullable=False),
            sa.Column("community_identifier", sa.String(length=120), nullable=False),
            sa.Column("community_uuid", sa.String(length=120), nullable=True),
            sa.Column("community_title", sa.String(length=255), nullable=True),
            sa.Column("community_links_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("action", sa.String(length=32), nullable=False),
            sa.Column("status_filter", sa.String(length=32), nullable=False, server_default="submitted"),
            sa.Column("request_type", sa.String(length=120), nullable=True),
            sa.Column("note_present", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("note_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("page_size", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("max_requests", sa.Integer(), nullable=True),
            sa.Column("plan_checksum", sa.String(length=64), nullable=False),
            sa.Column("confirmation_text", sa.String(length=255), nullable=False),
            sa.Column("state", sa.String(length=32), nullable=False, server_default="PENDING"),
            sa.Column("phase", sa.String(length=64), nullable=False, server_default="planned"),
            sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("progress_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("control_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], name=op.f("fk_community_moderation_sweep_jobs_requested_by_user_id_users")),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_community_moderation_sweep_jobs")),
            sa.UniqueConstraint("public_id", name=op.f("uq_community_moderation_sweep_jobs_public_id")),
        )
        with op.batch_alter_table("community_moderation_sweep_jobs", schema=None) as batch_op:
            batch_op.create_index(batch_op.f("ix_community_moderation_sweep_jobs_community_identifier"), ["community_identifier"], unique=False)
            batch_op.create_index(batch_op.f("ix_community_moderation_sweep_jobs_public_id"), ["public_id"], unique=True)
            batch_op.create_index(batch_op.f("ix_community_moderation_sweep_jobs_requested_by_user_id"), ["requested_by_user_id"], unique=False)
            batch_op.create_index(batch_op.f("ix_community_moderation_sweep_jobs_state"), ["state"], unique=False)
            batch_op.create_index(batch_op.f("ix_community_moderation_sweep_jobs_task_id"), ["task_id"], unique=False)

    if not _has_table("community_moderation_sweep_events"):
        op.create_table(
            "community_moderation_sweep_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.Integer(), nullable=False),
            sa.Column("request_id", sa.String(length=120), nullable=True),
            sa.Column("request_number", sa.String(length=120), nullable=True),
            sa.Column("record_id", sa.String(length=120), nullable=True),
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("request_type", sa.String(length=120), nullable=True),
            sa.Column("event", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=64), nullable=True),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("rate_limit_reason", sa.String(length=120), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["community_moderation_sweep_jobs.id"], name=op.f("fk_community_moderation_sweep_events_job_id_community_moderation_sweep_jobs")),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_community_moderation_sweep_events")),
        )
        with op.batch_alter_table("community_moderation_sweep_events", schema=None) as batch_op:
            batch_op.create_index(batch_op.f("ix_community_moderation_sweep_events_created_at"), ["created_at"], unique=False)
            batch_op.create_index(batch_op.f("ix_community_moderation_sweep_events_event"), ["event"], unique=False)
            batch_op.create_index(batch_op.f("ix_community_moderation_sweep_events_job_id"), ["job_id"], unique=False)
            batch_op.create_index(batch_op.f("ix_community_moderation_sweep_events_request_id"), ["request_id"], unique=False)


def downgrade():
    if _has_table("community_moderation_sweep_events"):
        op.drop_table("community_moderation_sweep_events")
    if _has_table("community_moderation_sweep_jobs"):
        op.drop_table("community_moderation_sweep_jobs")
