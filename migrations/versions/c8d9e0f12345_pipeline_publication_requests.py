"""Persist publication request identities for safe retries."""
from alembic import op
import sqlalchemy as sa

revision = "c8d9e0f12345"
down_revision = "b7c8d9e0f123"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pipeline_publication_requests",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("pipeline_version_id", sa.Integer(), sa.ForeignKey("pipeline_versions.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
    )


def downgrade():
    op.drop_table("pipeline_publication_requests")
