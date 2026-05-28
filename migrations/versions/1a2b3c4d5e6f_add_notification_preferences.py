"""add notification preferences

Revision ID: 1a2b3c4d5e6f
Revises: 0f7a6c5d4e3b
Create Date: 2026-04-30 16:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "1a2b3c4d5e6f"
down_revision = "0f7a6c5d4e3b"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.add_column(sa.Column("category", sa.String(length=80), nullable=False, server_default="system"))
        batch_op.add_column(sa.Column("email_status", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("emailed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("email_error", sa.Text(), nullable=True))
        batch_op.create_index(batch_op.f("ix_notifications_category"), ["category"], unique=False)
        batch_op.create_index(
            "ix_notifications_recipient_category_created",
            ["recipient_user_id", "category", "created_at"],
            unique=False,
        )

    op.execute(
        """
        UPDATE notifications
        SET category = CASE
            WHEN notification_type LIKE 'issue.%' THEN 'issues'
            WHEN notification_type LIKE 'credential.%' THEN 'credentials'
            WHEN notification_type LIKE 'pipeline.%' THEN 'jobs'
            WHEN notification_type LIKE 'session_batch.%' THEN 'jobs'
            WHEN notification_type LIKE 'hpc.%' THEN 'hpc'
            WHEN notification_type LIKE 'dataset.%' THEN 'datasets'
            WHEN notification_type LIKE 'profile.%' THEN 'profiles'
            WHEN notification_type LIKE 'institution.%' THEN 'profiles'
            WHEN notification_type LIKE 'zenodo.%' THEN 'zenodo'
            WHEN notification_type LIKE 'admin.%' THEN 'admin'
            ELSE 'system'
        END
        """
    )

    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("in_app_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("digest_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_notification_preferences_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_preferences")),
        sa.UniqueConstraint("user_id", "category", name="uq_notification_preferences_user_category"),
    )
    op.create_index(op.f("ix_notification_preferences_user_id"), "notification_preferences", ["user_id"], unique=False)
    op.create_index(
        "ix_notification_preferences_user_category",
        "notification_preferences",
        ["user_id", "category"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_notification_preferences_user_category", table_name="notification_preferences")
    op.drop_index(op.f("ix_notification_preferences_user_id"), table_name="notification_preferences")
    op.drop_table("notification_preferences")

    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.drop_index("ix_notifications_recipient_category_created")
        batch_op.drop_index(batch_op.f("ix_notifications_category"))
        batch_op.drop_column("email_error")
        batch_op.drop_column("emailed_at")
        batch_op.drop_column("email_status")
        batch_op.drop_column("category")
