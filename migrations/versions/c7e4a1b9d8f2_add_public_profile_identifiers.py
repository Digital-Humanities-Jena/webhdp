"""add internal profile identifiers

Revision ID: c7e4a1b9d8f2
Revises: b3f8c1d2e4a9
Create Date: 2026-04-29 12:00:00.000000

"""

import re
import uuid

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c7e4a1b9d8f2"
down_revision = "b3f8c1d2e4a9"
branch_labels = None
depends_on = None


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")[:120]


def _unique_slug(base_value: str, existing: set[str]) -> str | None:
    slug_base = _slugify(base_value)
    if not slug_base:
        return None
    slug = slug_base
    suffix = 1
    while slug in existing:
        suffix += 1
        trimmed_base = slug_base[: max(1, 120 - len(str(suffix)) - 1)]
        slug = f"{trimmed_base}-{suffix}"
    existing.add(slug)
    return slug


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("public_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("slug", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("bio", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("website_url", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("avatar_url", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("profile_visibility", sa.String(length=32), nullable=False, server_default="private"))
        batch_op.add_column(sa.Column("show_email", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("show_orcid", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("show_affiliation", sa.Boolean(), nullable=False, server_default=sa.false()))

    with op.batch_alter_table("institutions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("public_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("display_name", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("website_url", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("logo_url", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("profile_visibility", sa.String(length=32), nullable=False, server_default="private"))

    bind = op.get_bind()

    user_rows = bind.execute(sa.text("SELECT id, email, display_name, full_name, slug FROM users ORDER BY id ASC")).fetchall()
    existing_user_slugs = {str(row[4]) for row in user_rows if row[4]}
    for row in user_rows:
        user_slug = row[4] or _unique_slug(row[2] or row[3] or str(row[1]).split("@", 1)[0], existing_user_slugs)
        bind.execute(
            sa.text("UPDATE users SET public_id = :public_id, slug = :slug WHERE id = :id"),
            {"public_id": str(uuid.uuid4()), "slug": user_slug, "id": row[0]},
        )

    institution_rows = bind.execute(sa.text("SELECT id FROM institutions ORDER BY id ASC")).fetchall()
    for row in institution_rows:
        bind.execute(
            sa.text("UPDATE institutions SET public_id = :public_id WHERE id = :id"),
            {"public_id": str(uuid.uuid4()), "id": row[0]},
        )
    bind.execute(sa.text("UPDATE users SET profile_visibility = 'internal' WHERE profile_visibility = 'public'"))
    bind.execute(sa.text("UPDATE institutions SET profile_visibility = 'internal' WHERE profile_visibility = 'public'"))

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_users_public_id"), ["public_id"], unique=True)
        batch_op.create_index(batch_op.f("ix_users_slug"), ["slug"], unique=True)

    with op.batch_alter_table("institutions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_institutions_public_id"), ["public_id"], unique=True)


def downgrade():
    with op.batch_alter_table("institutions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_institutions_public_id"))
        batch_op.drop_column("profile_visibility")
        batch_op.drop_column("logo_url")
        batch_op.drop_column("website_url")
        batch_op.drop_column("display_name")
        batch_op.drop_column("public_id")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_slug"))
        batch_op.drop_index(batch_op.f("ix_users_public_id"))
        batch_op.drop_column("show_affiliation")
        batch_op.drop_column("show_orcid")
        batch_op.drop_column("show_email")
        batch_op.drop_column("profile_visibility")
        batch_op.drop_column("avatar_url")
        batch_op.drop_column("website_url")
        batch_op.drop_column("bio")
        batch_op.drop_column("slug")
        batch_op.drop_column("public_id")
