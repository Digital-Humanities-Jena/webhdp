"""add validation report to zenodo creds

Revision ID: e1f7f20a9d4b
Revises: 9c3c2d8e7b91
Create Date: 2026-03-30 20:20:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e1f7f20a9d4b"
down_revision = "9c3c2d8e7b91"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("zenodo_credentials", schema=None) as batch_op:
        batch_op.add_column(sa.Column("last_validation_report", sa.Text(), nullable=True))

    op.execute("UPDATE zenodo_credentials SET validation_status = 'warning' WHERE validation_status = 'valid'")


def downgrade():
    with op.batch_alter_table("zenodo_credentials", schema=None) as batch_op:
        batch_op.drop_column("last_validation_report")
