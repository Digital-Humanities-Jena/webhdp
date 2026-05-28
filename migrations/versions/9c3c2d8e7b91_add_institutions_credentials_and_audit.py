"""add institutions credentials and audit

Revision ID: 9c3c2d8e7b91
Revises: 2f5f1d5ee3c9
Create Date: 2026-03-30 14:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9c3c2d8e7b91"
down_revision = "2f5f1d5ee3c9"
branch_labels = None
depends_on = None


institution_role = sa.Enum("reader", "curator", "manager", "owner", name="institutionrole")


def upgrade():
    institution_role.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "institutions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name=op.f("fk_institutions_created_by_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_institutions")),
    )
    with op.batch_alter_table("institutions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_institutions_name"), ["name"], unique=True)
        batch_op.create_index(batch_op.f("ix_institutions_slug"), ["slug"], unique=True)

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("display_name", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("full_name", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("affiliation", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("orcid", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("default_institution_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_users_default_institution_id_institutions"),
            "institutions",
            ["default_institution_id"],
            ["id"],
        )

    op.create_table(
        "institution_memberships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("institution_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", institution_role, nullable=False, server_default="reader"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], name=op.f("fk_institution_memberships_institution_id_institutions")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_institution_memberships_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_institution_memberships")),
        sa.UniqueConstraint("institution_id", "user_id", name="uq_institution_membership"),
    )

    op.create_table(
        "zenodo_credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_type", sa.String(length=32), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("masked_preview", sa.String(length=64), nullable=True),
        sa.Column("validation_status", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("last_validated_at", sa.DateTime(), nullable=True),
        sa.Column("last_validation_error", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name=op.f("fk_zenodo_credentials_created_by_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_zenodo_credentials")),
        sa.UniqueConstraint("owner_type", "owner_id", "environment", name="uq_zenodo_credential_owner_env"),
    )

    op.create_table(
        "institution_zenodo_communities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("institution_id", sa.Integer(), nullable=False),
        sa.Column("identifier", sa.String(length=120), nullable=False),
        sa.Column("is_primary_submission", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_moderation_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], name=op.f("fk_institution_zenodo_communities_institution_id_institutions")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_institution_zenodo_communities")),
        sa.UniqueConstraint("institution_id", "identifier", name="uq_institution_community_identifier"),
    )

    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("institution_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("sharing_scope", sa.String(length=32), nullable=False, server_default="private"))
        batch_op.add_column(sa.Column("credential_preference", sa.String(length=32), nullable=False, server_default="user"))
        batch_op.add_column(sa.Column("publishing_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("default_zenodo_environment", sa.String(length=32), nullable=False, server_default="sandbox"))
        batch_op.add_column(
            sa.Column("use_institution_default_communities", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_sessions_institution_id_institutions"),
            "institutions",
            ["institution_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_sessions_publishing_user_id_users"),
            "users",
            ["publishing_user_id"],
            ["id"],
        )

    op.execute("UPDATE sessions SET publishing_user_id = user_id WHERE publishing_user_id IS NULL")

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("institution_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("entity_type", sa.String(length=120), nullable=False),
        sa.Column("entity_id", sa.String(length=120), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_audit_events_actor_user_id_users")),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], name=op.f("fk_audit_events_institution_id_institutions")),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], name=op.f("fk_audit_events_session_id_sessions")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )


def downgrade():
    op.drop_table("audit_events")

    with op.batch_alter_table("sessions", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("fk_sessions_publishing_user_id_users"), type_="foreignkey")
        batch_op.drop_constraint(batch_op.f("fk_sessions_institution_id_institutions"), type_="foreignkey")
        batch_op.drop_column("use_institution_default_communities")
        batch_op.drop_column("default_zenodo_environment")
        batch_op.drop_column("publishing_user_id")
        batch_op.drop_column("credential_preference")
        batch_op.drop_column("sharing_scope")
        batch_op.drop_column("institution_id")

    op.drop_table("institution_zenodo_communities")
    op.drop_table("zenodo_credentials")
    op.drop_table("institution_memberships")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("fk_users_default_institution_id_institutions"), type_="foreignkey")
        batch_op.drop_column("default_institution_id")
        batch_op.drop_column("orcid")
        batch_op.drop_column("affiliation")
        batch_op.drop_column("full_name")
        batch_op.drop_column("display_name")

    with op.batch_alter_table("institutions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_institutions_slug"))
        batch_op.drop_index(batch_op.f("ix_institutions_name"))
    op.drop_table("institutions")

    institution_role.drop(op.get_bind(), checkfirst=True)
