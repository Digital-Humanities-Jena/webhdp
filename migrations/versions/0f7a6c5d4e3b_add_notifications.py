"""add notifications

Revision ID: 0f7a6c5d4e3b
Revises: f6a7b8c9d012
Create Date: 2026-04-30 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "0f7a6c5d4e3b"
down_revision = "f6a7b8c9d012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recipient_user_id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("institution_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("entity_type", sa.String(length=120), nullable=True),
        sa.Column("entity_id", sa.String(length=120), nullable=True),
        sa.Column("notification_type", sa.String(length=120), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("action_url", sa.String(length=512), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("dedupe_key", sa.String(length=255), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_notifications_actor_user_id_users")),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], name=op.f("fk_notifications_institution_id_institutions")),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], name=op.f("fk_notifications_recipient_user_id_users")),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], name=op.f("fk_notifications_session_id_sessions")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_notifications_dedupe_key")),
    )
    op.create_index(op.f("ix_notifications_actor_user_id"), "notifications", ["actor_user_id"], unique=False)
    op.create_index(op.f("ix_notifications_institution_id"), "notifications", ["institution_id"], unique=False)
    op.create_index(op.f("ix_notifications_notification_type"), "notifications", ["notification_type"], unique=False)
    op.create_index(op.f("ix_notifications_recipient_user_id"), "notifications", ["recipient_user_id"], unique=False)
    op.create_index("ix_notifications_recipient_archived", "notifications", ["recipient_user_id", "archived_at"], unique=False)
    op.create_index(
        "ix_notifications_recipient_read_created",
        "notifications",
        ["recipient_user_id", "read_at", "created_at"],
        unique=False,
    )
    op.create_index(op.f("ix_notifications_session_id"), "notifications", ["session_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_notifications_session_id"), table_name="notifications")
    op.drop_index("ix_notifications_recipient_read_created", table_name="notifications")
    op.drop_index("ix_notifications_recipient_archived", table_name="notifications")
    op.drop_index(op.f("ix_notifications_recipient_user_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_notification_type"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_institution_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_actor_user_id"), table_name="notifications")
    op.drop_table("notifications")
