"""add email mfa challenges

Revision ID: 3c4d5e6f7a80
Revises: 2b3c4d5e6f70
Create Date: 2026-05-04 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "3c4d5e6f7a80"
down_revision = "2b3c4d5e6f70"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_mfa_challenges",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_user_mfa_challenges_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_mfa_challenges")),
    )
    with op.batch_alter_table("user_mfa_challenges", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_user_mfa_challenges_expires_at"), ["expires_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_user_mfa_challenges_token_hash"), ["token_hash"], unique=True)
        batch_op.create_index(batch_op.f("ix_user_mfa_challenges_user_id"), ["user_id"], unique=False)


def downgrade():
    op.drop_table("user_mfa_challenges")
