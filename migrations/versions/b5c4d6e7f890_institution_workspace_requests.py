"""Record institutional workspace applications and administrator decisions."""

from alembic import op
import sqlalchemy as sa

revision = "b5c4d6e7f890"
down_revision = "a4b3c5d6e789"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "institution_workspace_requests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("requester_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("normalized_name", sa.Text, nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("institution_id", sa.Integer, sa.ForeignKey("institutions.id", ondelete="SET NULL")),
        sa.Column("reviewed_by_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("review_note", sa.Text),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("reviewed_at", sa.DateTime),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="institution_workspace_request_status"),
    )
    op.create_index(
        "ix_institution_workspace_requests_requester_status",
        "institution_workspace_requests",
        ["requester_user_id", "status"],
    )
    op.create_index(
        "ix_institution_workspace_requests_status_created",
        "institution_workspace_requests",
        ["status", "created_at"],
    )


def downgrade():
    op.drop_index("ix_institution_workspace_requests_status_created", table_name="institution_workspace_requests")
    op.drop_index("ix_institution_workspace_requests_requester_status", table_name="institution_workspace_requests")
    op.drop_table("institution_workspace_requests")
