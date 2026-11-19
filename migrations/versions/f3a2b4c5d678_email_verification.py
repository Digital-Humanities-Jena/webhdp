"""Add email identity and replace raw registration links with expiring challenges."""

from collections import defaultdict

from alembic import op
import sqlalchemy as sa


revision = "f3a2b4c5d678"
down_revision = "e2f1a3b4c567"
branch_labels = None
depends_on = None


def _legacy_email_key(value):
    local, separator, domain = value.strip().rpartition("@")
    if not separator or not local or not domain:
        return None
    try:
        key = f"{local.lower()}@{domain.lower().encode('idna').decode('ascii')}"
    except UnicodeError:
        return None
    return key if len(key) <= 254 else None


def upgrade():
    op.add_column("users", sa.Column("canonical_email", sa.String(254), nullable=True))
    op.add_column("users", sa.Column("legacy_canonical_email", sa.String(254), nullable=True))
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column("users", "email", existing_type=sa.String(120), type_=sa.String(254), existing_nullable=False)

    db = op.get_bind()
    users = sa.table(
        "users", sa.column("id", sa.Integer), sa.column("email", sa.String),
        sa.column("canonical_email", sa.String), sa.column("legacy_canonical_email", sa.String),
        sa.column("verification_token", sa.String),
    )
    accounts_by_email = defaultdict(list)
    for user_id, email in db.execute(sa.select(users.c.id, users.c.email)):
        key = _legacy_email_key(email)
        if key:
            accounts_by_email[key].append(user_id)
    for key, user_ids in accounts_by_email.items():
        column = users.c.canonical_email if len(user_ids) == 1 else users.c.legacy_canonical_email
        db.execute(users.update().where(users.c.id.in_(user_ids)).values({column: key}))
    db.execute(users.update().where(users.c.verification_token.is_not(None)).values(verification_token=None))

    op.create_index("uq_users_canonical_email", "users", ["canonical_email"], unique=True)
    op.create_index("ix_users_legacy_canonical_email", "users", ["legacy_canonical_email"])
    op.create_table(
        "user_email_verifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_email", sa.String(254), nullable=False),
        sa.Column("delivery_email", sa.String(254), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_user_email_verifications_canonical_email", "user_email_verifications", ["canonical_email"])
    op.create_index("ix_user_email_verifications_expires_at", "user_email_verifications", ["expires_at"])


def downgrade():
    op.drop_table("user_email_verifications")
    op.drop_index("ix_users_legacy_canonical_email", table_name="users")
    op.drop_index("uq_users_canonical_email", table_name="users")
    op.drop_column("users", "legacy_canonical_email")
    op.drop_column("users", "canonical_email")
