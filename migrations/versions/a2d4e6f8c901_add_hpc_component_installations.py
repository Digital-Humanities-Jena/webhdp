"""add hpc component installations

Revision ID: a2d4e6f8c901
Revises: 8b7e2f4c9a10
Create Date: 2026-04-28 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a2d4e6f8c901"
down_revision = "8b7e2f4c9a10"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hpc_component_installations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column("component_key", sa.String(length=120), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("component_version_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("sif_remote_path", sa.String(length=1000), nullable=True),
        sa.Column("remote_install_dir", sa.String(length=1000), nullable=True),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("checks_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("logs_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("installed_at", sa.DateTime(), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["component_version_id"], ["component_versions.id"], name=op.f("fk_hpc_component_installations_component_version_id_component_versions")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_hpc_component_installations_created_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hpc_component_installations")),
        sa.UniqueConstraint("public_id", name=op.f("uq_hpc_component_installations_public_id")),
    )
    op.create_index(op.f("ix_hpc_component_installations_component_key"), "hpc_component_installations", ["component_key"], unique=False)
    op.create_index(op.f("ix_hpc_component_installations_component_version_id"), "hpc_component_installations", ["component_version_id"], unique=False)
    op.create_index(op.f("ix_hpc_component_installations_created_by"), "hpc_component_installations", ["created_by"], unique=False)
    op.create_index(op.f("ix_hpc_component_installations_manifest_hash"), "hpc_component_installations", ["manifest_hash"], unique=False)
    op.create_index(op.f("ix_hpc_component_installations_status"), "hpc_component_installations", ["status"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_hpc_component_installations_status"), table_name="hpc_component_installations")
    op.drop_index(op.f("ix_hpc_component_installations_manifest_hash"), table_name="hpc_component_installations")
    op.drop_index(op.f("ix_hpc_component_installations_created_by"), table_name="hpc_component_installations")
    op.drop_index(op.f("ix_hpc_component_installations_component_version_id"), table_name="hpc_component_installations")
    op.drop_index(op.f("ix_hpc_component_installations_component_key"), table_name="hpc_component_installations")
    op.drop_table("hpc_component_installations")
