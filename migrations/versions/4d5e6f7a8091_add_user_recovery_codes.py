"""add user recovery codes

Revision ID: 4d5e6f7a8091
Revises: 3c4d5e6f7a80
Create Date: 2026-05-04 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4d5e6f7a8091"
down_revision = "3c4d5e6f7a80"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_recovery_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("code_prefix", sa.String(length=12), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_user_recovery_codes_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_recovery_codes")),
    )
    with op.batch_alter_table("user_recovery_codes", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_user_recovery_codes_code_hash"), ["code_hash"], unique=True)
        batch_op.create_index(batch_op.f("ix_user_recovery_codes_expires_at"), ["expires_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_user_recovery_codes_source"), ["source"], unique=False)
        batch_op.create_index(batch_op.f("ix_user_recovery_codes_user_id"), ["user_id"], unique=False)


def downgrade():
    op.drop_table("user_recovery_codes")
