"""shareable zenodo credentials

Revision ID: f6a7b8c9d012
Revises: d4a2c6e8f901
Create Date: 2026-04-29 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "f6a7b8c9d012"
down_revision = "d4a2c6e8f901"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("zenodo_credentials", schema=None) as batch_op:
        batch_op.add_column(sa.Column("name", sa.String(length=120), nullable=False, server_default="Zenodo API key"))
        batch_op.drop_constraint("uq_zenodo_credential_owner_env", type_="unique")

    op.execute(
        """
        UPDATE zenodo_credentials
        SET name = CASE
            WHEN environment = 'sandbox' THEN 'Sandbox API key'
            WHEN environment = 'production' THEN 'Production API key'
            ELSE 'Zenodo API key'
        END
        WHERE name IS NULL OR name = '' OR name = 'Zenodo API key'
        """
    )

    op.create_table(
        "zenodo_credential_shares",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("credential_id", sa.Integer(), nullable=False),
        sa.Column("shared_by_user_id", sa.Integer(), nullable=False),
        sa.Column("recipient_user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("responded_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["credential_id"], ["zenodo_credentials.id"], name=op.f("fk_zenodo_credential_shares_credential_id_zenodo_credentials")),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], name=op.f("fk_zenodo_credential_shares_recipient_user_id_users")),
        sa.ForeignKeyConstraint(["shared_by_user_id"], ["users.id"], name=op.f("fk_zenodo_credential_shares_shared_by_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_zenodo_credential_shares")),
        sa.UniqueConstraint("credential_id", "recipient_user_id", name="uq_zenodo_credential_share_recipient"),
    )
    with op.batch_alter_table("zenodo_credential_shares", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_zenodo_credential_shares_credential_id"), ["credential_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_zenodo_credential_shares_recipient_user_id"), ["recipient_user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_zenodo_credential_shares_shared_by_user_id"), ["shared_by_user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_zenodo_credential_shares_status"), ["status"], unique=False)

    op.create_table(
        "user_zenodo_active_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("credential_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["credential_id"], ["zenodo_credentials.id"], name=op.f("fk_user_zenodo_active_credentials_credential_id_zenodo_credentials")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_user_zenodo_active_credentials_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_zenodo_active_credentials")),
        sa.UniqueConstraint("user_id", "environment", name="uq_user_zenodo_active_environment"),
    )
    with op.batch_alter_table("user_zenodo_active_credentials", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_user_zenodo_active_credentials_credential_id"), ["credential_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_user_zenodo_active_credentials_user_id"), ["user_id"], unique=False)

    op.execute(
        """
        INSERT INTO user_zenodo_active_credentials (user_id, environment, credential_id, created_at, updated_at)
        SELECT owner_id, environment, MIN(id), CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM zenodo_credentials
        WHERE owner_type = 'user'
        GROUP BY owner_id, environment
        """
    )


def downgrade():
    op.drop_table("user_zenodo_active_credentials")
    op.drop_table("zenodo_credential_shares")

    with op.batch_alter_table("zenodo_credentials", schema=None) as batch_op:
        batch_op.create_unique_constraint("uq_zenodo_credential_owner_env", ["owner_type", "owner_id", "environment"])
        batch_op.drop_column("name")
