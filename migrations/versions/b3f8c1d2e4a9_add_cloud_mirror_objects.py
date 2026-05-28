"""add cloud mirror objects

Revision ID: b3f8c1d2e4a9
Revises: a2d4e6f8c901
Create Date: 2026-04-29 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b3f8c1d2e4a9"
down_revision = "a2d4e6f8c901"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cloud_mirror_objects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=True),
        sa.Column("artifact_kind", sa.String(length=64), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_provider", sa.String(length=32), nullable=True),
        sa.Column("cloud_path", sa.String(length=1000), nullable=True),
        sa.Column("remote_url", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], name=op.f("fk_cloud_mirror_objects_file_id_files")),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], name=op.f("fk_cloud_mirror_objects_session_id_sessions")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cloud_mirror_objects")),
    )
    op.create_index(op.f("ix_cloud_mirror_objects_file_id"), "cloud_mirror_objects", ["file_id"], unique=False)
    op.create_index(op.f("ix_cloud_mirror_objects_session_id"), "cloud_mirror_objects", ["session_id"], unique=False)
    op.create_index(op.f("ix_cloud_mirror_objects_status"), "cloud_mirror_objects", ["status"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_cloud_mirror_objects_status"), table_name="cloud_mirror_objects")
    op.drop_index(op.f("ix_cloud_mirror_objects_session_id"), table_name="cloud_mirror_objects")
    op.drop_index(op.f("ix_cloud_mirror_objects_file_id"), table_name="cloud_mirror_objects")
    op.drop_table("cloud_mirror_objects")
