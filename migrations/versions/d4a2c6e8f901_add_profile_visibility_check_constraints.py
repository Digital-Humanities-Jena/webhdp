"""add profile visibility check constraints

Revision ID: d4a2c6e8f901
Revises: c7e4a1b9d8f2
Create Date: 2026-04-29 14:45:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d4a2c6e8f901"
down_revision = "c7e4a1b9d8f2"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE users SET profile_visibility = 'internal' WHERE profile_visibility = 'public'"))
    bind.execute(sa.text("UPDATE institutions SET profile_visibility = 'internal' WHERE profile_visibility = 'public'"))

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.create_check_constraint(
            "profile_visibility_internal",
            "profile_visibility IN ('private', 'internal')",
        )

    with op.batch_alter_table("institutions", schema=None) as batch_op:
        batch_op.create_check_constraint(
            "profile_visibility_internal",
            "profile_visibility IN ('private', 'internal')",
        )


def downgrade():
    with op.batch_alter_table("institutions", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_institutions_profile_visibility_internal"), type_="check")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_users_profile_visibility_internal"), type_="check")
