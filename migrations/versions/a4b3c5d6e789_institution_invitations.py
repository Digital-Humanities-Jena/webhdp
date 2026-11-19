"""Persist invitations tied to verified institution member email addresses."""

from alembic import op
import sqlalchemy as sa

revision = "a4b3c5d6e789"
down_revision = "f3a2b4c5d678"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "institution_invitations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("institution_id", sa.Integer, sa.ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_email", sa.String(254), nullable=False),
        sa.Column("delivery_email", sa.String(254), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=True, unique=True),
        sa.Column("issued_by_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("accepted_by_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("delivery_attempted_at", sa.DateTime(), nullable=False),
        sa.Column("delivery_status", sa.String(16), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("role IN ('reader', 'curator', 'manager', 'owner')", name="institution_invitation_role"),
        sa.CheckConstraint("delivery_status IN ('sending', 'sent', 'failed')", name="institution_invitation_delivery"),
        sa.CheckConstraint("accepted_at IS NULL OR revoked_at IS NULL", name="institution_invitation_terminal_state"),
    )
    op.create_index(
        "ix_institution_invitations_recipient",
        "institution_invitations",
        ["institution_id", "recipient_email", "created_at"],
    )


def downgrade():
    op.drop_index("ix_institution_invitations_recipient", table_name="institution_invitations")
    op.drop_table("institution_invitations")
