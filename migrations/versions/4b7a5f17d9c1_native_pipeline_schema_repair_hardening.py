"""native pipeline schema repair hardening

Revision ID: 4b7a5f17d9c1
Revises: dffd40c829a8
Create Date: 2026-03-29 22:35:00.000000

"""

from alembic import op

from services.schema_bootstrap_service import native_pipeline_tables


# revision identifiers, used by Alembic.
revision = "4b7a5f17d9c1"
down_revision = "dffd40c829a8"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for table in native_pipeline_tables():
        table.create(bind=bind, checkfirst=True)


def downgrade():
    pass
