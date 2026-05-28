"""add issues workspace tables

Revision ID: 6d4c2ab9f1a0
Revises: f2b6d74c1c3a
Create Date: 2026-03-31 10:45:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6d4c2ab9f1a0"
down_revision = "f2b6d74c1c3a"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "issues",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporter_user_id", sa.Integer(), nullable=False),
        sa.Column("assignee_user_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("issue_type", sa.String(length=64), nullable=False, server_default="general"),
        sa.Column("reporter_impact", sa.String(length=32), nullable=False, server_default="medium"),
        sa.Column("internal_priority", sa.String(length=32), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="new"),
        sa.Column("page_key", sa.String(length=120), nullable=True),
        sa.Column("page_label", sa.String(length=255), nullable=True),
        sa.Column("route_name", sa.String(length=120), nullable=True),
        sa.Column("route_path", sa.String(length=255), nullable=True),
        sa.Column("current_url", sa.String(length=512), nullable=True),
        sa.Column("route_context_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("related_entity_ids_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("environment_context_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("user_context_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("public_description", sa.Text(), nullable=True),
        sa.Column("expected_behavior", sa.Text(), nullable=True),
        sa.Column("technical_details", sa.Text(), nullable=True),
        sa.Column("reproduction_steps", sa.Text(), nullable=True),
        sa.Column("console_notes", sa.Text(), nullable=True),
        sa.Column("api_notes", sa.Text(), nullable=True),
        sa.Column("suspected_subsystem", sa.String(length=120), nullable=True),
        sa.Column("capture_context_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("code_refs_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["assignee_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reporter_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_issues_page_key"), "issues", ["page_key"], unique=False)
    op.create_index(op.f("ix_issues_reporter_user_id"), "issues", ["reporter_user_id"], unique=False)
    op.create_index(op.f("ix_issues_assignee_user_id"), "issues", ["assignee_user_id"], unique=False)
    op.create_index(op.f("ix_issues_status"), "issues", ["status"], unique=False)

    op.create_table(
        "issue_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("author_user_id", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_internal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_issue_comments_author_user_id"), "issue_comments", ["author_user_id"], unique=False)
    op.create_index(op.f("ix_issue_comments_issue_id"), "issue_comments", ["issue_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_issue_comments_issue_id"), table_name="issue_comments")
    op.drop_index(op.f("ix_issue_comments_author_user_id"), table_name="issue_comments")
    op.drop_table("issue_comments")

    op.drop_index(op.f("ix_issues_status"), table_name="issues")
    op.drop_index(op.f("ix_issues_assignee_user_id"), table_name="issues")
    op.drop_index(op.f("ix_issues_reporter_user_id"), table_name="issues")
    op.drop_index(op.f("ix_issues_page_key"), table_name="issues")
    op.drop_table("issues")
