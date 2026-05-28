"""add notification delivery audit

Revision ID: 2b3c4d5e6f70
Revises: 1a2b3c4d5e6f
Create Date: 2026-04-30 17:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "2b3c4d5e6f70"
down_revision = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("notification_id", sa.Integer(), nullable=False),
        sa.Column("recipient_user_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("batch_key", sa.String(length=120), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"], name=op.f("fk_notification_deliveries_notification_id_notifications")),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], name=op.f("fk_notification_deliveries_recipient_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_deliveries")),
    )
    op.create_index(op.f("ix_notification_deliveries_channel"), "notification_deliveries", ["channel"], unique=False)
    op.create_index(
        "ix_notification_deliveries_channel_status_created",
        "notification_deliveries",
        ["channel", "status", "created_at"],
        unique=False,
    )
    op.create_index("ix_notification_deliveries_batch_key", "notification_deliveries", ["batch_key"], unique=False)
    op.create_index(op.f("ix_notification_deliveries_notification_id"), "notification_deliveries", ["notification_id"], unique=False)
    op.create_index(
        "ix_notification_deliveries_recipient_channel_created",
        "notification_deliveries",
        ["recipient_user_id", "channel", "created_at"],
        unique=False,
    )
    op.create_index(op.f("ix_notification_deliveries_recipient_user_id"), "notification_deliveries", ["recipient_user_id"], unique=False)
    op.create_index(op.f("ix_notification_deliveries_status"), "notification_deliveries", ["status"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_notification_deliveries_status"), table_name="notification_deliveries")
    op.drop_index(op.f("ix_notification_deliveries_recipient_user_id"), table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_recipient_channel_created", table_name="notification_deliveries")
    op.drop_index(op.f("ix_notification_deliveries_notification_id"), table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_batch_key", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_channel_status_created", table_name="notification_deliveries")
    op.drop_index(op.f("ix_notification_deliveries_channel"), table_name="notification_deliveries")
    op.drop_table("notification_deliveries")
