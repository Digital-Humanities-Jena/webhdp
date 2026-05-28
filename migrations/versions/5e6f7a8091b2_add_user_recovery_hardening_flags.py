"""add user recovery hardening flags

Revision ID: 5e6f7a8091b2
Revises: 4d5e6f7a8091
Create Date: 2026-05-04 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "5e6f7a8091b2"
down_revision = "4d5e6f7a8091"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("force_password_change", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("token_version")
        batch_op.drop_column("force_password_change")
