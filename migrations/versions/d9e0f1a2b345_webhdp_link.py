"""Add durable WebHDP-Link authorization, publications, uploads and runs.

Revision ID: d9e0f1a2b345
Revises: c8d9e0f12345
"""
from alembic import op
import sqlalchemy as sa

revision = 'd9e0f1a2b345'
down_revision = 'e1f0a2b3c456'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('webhdp_link_clients', sa.Column('id', sa.String(80), primary_key=True), sa.Column('name', sa.String(160), nullable=False), sa.Column('enabled', sa.Boolean(), nullable=False), sa.Column('config_json', sa.Text(), nullable=False), sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_table('webhdp_link_publications', sa.Column('id', sa.String(80), primary_key=True), sa.Column('pipeline_version_id', sa.Integer(), sa.ForeignKey('pipeline_versions.id'), nullable=False), sa.Column('name', sa.String(160), nullable=False), sa.Column('description', sa.Text(), nullable=False), sa.Column('enabled', sa.Boolean(), nullable=False), sa.Column('config_json', sa.Text(), nullable=False), sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_table('webhdp_link_codes', sa.Column('id', sa.String(64), primary_key=True), sa.Column('client_id', sa.String(80), sa.ForeignKey('webhdp_link_clients.id'), nullable=False), sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False), sa.Column('config_json', sa.Text(), nullable=False), sa.Column('expires_at', sa.DateTime(), nullable=False), sa.Column('used_at', sa.DateTime()))
    op.create_table('webhdp_link_tokens', sa.Column('id', sa.String(36), primary_key=True), sa.Column('token_hash', sa.String(64), nullable=False), sa.Column('client_id', sa.String(80), sa.ForeignKey('webhdp_link_clients.id'), nullable=False), sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False), sa.Column('user_token_version', sa.Integer(), nullable=False), sa.Column('scope', sa.Text(), nullable=False), sa.Column('pipeline_ids_json', sa.Text(), nullable=False), sa.Column('origin', sa.String(512)), sa.Column('service', sa.Boolean(), nullable=False), sa.Column('revoked', sa.Boolean(), nullable=False), sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('expires_at', sa.DateTime(), nullable=False))
    op.create_index('ix_webhdp_link_tokens_token_hash', 'webhdp_link_tokens', ['token_hash'], unique=True)
    op.create_index('ix_webhdp_link_tokens_client_id', 'webhdp_link_tokens', ['client_id'])
    op.create_table('webhdp_link_uploads', sa.Column('id', sa.String(36), primary_key=True), sa.Column('client_id', sa.String(80), sa.ForeignKey('webhdp_link_clients.id'), nullable=False), sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False), sa.Column('name', sa.String(255), nullable=False), sa.Column('size', sa.BigInteger(), nullable=False), sa.Column('sha256', sa.String(64), nullable=False), sa.Column('media_type', sa.String(160), nullable=False), sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_index('ix_webhdp_link_uploads_client_id', 'webhdp_link_uploads', ['client_id'])
    op.create_table('webhdp_link_runs', sa.Column('id', sa.String(36), primary_key=True), sa.Column('client_id', sa.String(80), sa.ForeignKey('webhdp_link_clients.id'), nullable=False), sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False), sa.Column('token_id', sa.String(36), sa.ForeignKey('webhdp_link_tokens.id'), nullable=False), sa.Column('publication_id', sa.String(80), sa.ForeignKey('webhdp_link_publications.id'), nullable=False), sa.Column('pipeline_version_id', sa.Integer(), sa.ForeignKey('pipeline_versions.id'), nullable=False), sa.Column('native_run_id', sa.Integer(), sa.ForeignKey('pipeline_runs.id')), sa.Column('session_id', sa.Integer(), sa.ForeignKey('sessions.id')), sa.Column('idempotency_key', sa.String(80), nullable=False), sa.Column('fingerprint', sa.String(64), nullable=False), sa.Column('request_json', sa.Text(), nullable=False), sa.Column('status', sa.String(24), nullable=False), sa.Column('cancel_requested', sa.Boolean(), nullable=False), sa.Column('worker_id', sa.String(160)), sa.Column('heartbeat_at', sa.DateTime()), sa.Column('error_code', sa.String(80)), sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('started_at', sa.DateTime()), sa.Column('completed_at', sa.DateTime()), sa.UniqueConstraint('client_id', 'user_id', 'idempotency_key', name='uq_link_run_idempotency'))
    op.create_index('ix_webhdp_link_runs_client_id', 'webhdp_link_runs', ['client_id'])
    op.create_index('ix_webhdp_link_runs_status', 'webhdp_link_runs', ['status'])
    op.create_table('webhdp_link_artifacts', sa.Column('id', sa.String(36), primary_key=True), sa.Column('run_id', sa.String(36), sa.ForeignKey('webhdp_link_runs.id'), nullable=False), sa.Column('relative_path', sa.String(1000), nullable=False), sa.Column('name', sa.String(255), nullable=False), sa.Column('size', sa.BigInteger(), nullable=False), sa.Column('sha256', sa.String(64), nullable=False), sa.Column('media_type', sa.String(160), nullable=False))
    op.create_index('ix_webhdp_link_artifacts_run_id', 'webhdp_link_artifacts', ['run_id'])


def downgrade():
    for table in ('webhdp_link_artifacts', 'webhdp_link_runs', 'webhdp_link_uploads', 'webhdp_link_tokens', 'webhdp_link_codes', 'webhdp_link_publications', 'webhdp_link_clients'):
        op.drop_table(table)
