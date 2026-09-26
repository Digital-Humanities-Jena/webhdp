"""Make email two-factor authentication a per-user opt-in."""
from alembic import op
import sqlalchemy as sa

revision = "b7c8d9e0f123"
down_revision = "ac1d2e3f4b5c"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("users", "mfa_enabled")
