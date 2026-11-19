"""Persist per-account upload admission and source usage."""

from alembic import op
import sqlalchemy as sa

revision = "e2f1a3b4c567"
down_revision = "d9e0f1a2b345"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "account_upload_reservations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("sessions.id", ondelete="CASCADE"), unique=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime),
    )
    op.create_index("ix_account_upload_reservations_user_id", "account_upload_reservations", ["user_id"])


def downgrade():
    op.drop_index("ix_account_upload_reservations_user_id", table_name="account_upload_reservations")
    op.drop_table("account_upload_reservations")
