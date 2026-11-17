"""Persisted third-party authorization and durable WebHDP-Link jobs."""
from datetime import datetime
from uuid import uuid4
from database.database import db


def uid():
    return str(uuid4())


class LinkClient(db.Model):
    __tablename__ = 'webhdp_link_clients'
    id = db.Column(db.String(80), primary_key=True, default=uid)
    name = db.Column(db.String(160), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    config_json = db.Column(db.Text, nullable=False, default='{}')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class LinkPublication(db.Model):
    __tablename__ = 'webhdp_link_publications'
    id = db.Column(db.String(80), primary_key=True)
    pipeline_version_id = db.Column(db.Integer, db.ForeignKey('pipeline_versions.id'), nullable=False)
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=False, default='')
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    config_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class LinkCode(db.Model):
    __tablename__ = 'webhdp_link_codes'
    id = db.Column(db.String(64), primary_key=True)  # SHA-256, never the authorization code
    client_id = db.Column(db.String(80), db.ForeignKey('webhdp_link_clients.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    config_json = db.Column(db.Text, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)


class LinkToken(db.Model):
    __tablename__ = 'webhdp_link_tokens'
    id = db.Column(db.String(36), primary_key=True, default=uid)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    client_id = db.Column(db.String(80), db.ForeignKey('webhdp_link_clients.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    user_token_version = db.Column(db.Integer, nullable=False)
    scope = db.Column(db.Text, nullable=False)
    pipeline_ids_json = db.Column(db.Text, nullable=False)
    origin = db.Column(db.String(512))
    service = db.Column(db.Boolean, nullable=False, default=False)
    revoked = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)


class LinkUpload(db.Model):
    __tablename__ = 'webhdp_link_uploads'
    id = db.Column(db.String(36), primary_key=True, default=uid)
    client_id = db.Column(db.String(80), db.ForeignKey('webhdp_link_clients.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    size = db.Column(db.BigInteger, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    media_type = db.Column(db.String(160), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class LinkRun(db.Model):
    __tablename__ = 'webhdp_link_runs'
    id = db.Column(db.String(36), primary_key=True, default=uid)
    client_id = db.Column(db.String(80), db.ForeignKey('webhdp_link_clients.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token_id = db.Column(db.String(36), db.ForeignKey('webhdp_link_tokens.id'), nullable=False)
    publication_id = db.Column(db.String(80), db.ForeignKey('webhdp_link_publications.id'), nullable=False)
    pipeline_version_id = db.Column(db.Integer, db.ForeignKey('pipeline_versions.id'), nullable=False)
    native_run_id = db.Column(db.Integer, db.ForeignKey('pipeline_runs.id'))
    session_id = db.Column(db.Integer, db.ForeignKey('sessions.id'))
    idempotency_key = db.Column(db.String(80), nullable=False)
    fingerprint = db.Column(db.String(64), nullable=False)
    request_json = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(24), nullable=False, default='queued', index=True)
    cancel_requested = db.Column(db.Boolean, nullable=False, default=False)
    worker_id = db.Column(db.String(160))
    heartbeat_at = db.Column(db.DateTime)
    error_code = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    __table_args__ = (db.UniqueConstraint('client_id', 'user_id', 'idempotency_key', name='uq_link_run_idempotency'),)


class LinkArtifact(db.Model):
    __tablename__ = 'webhdp_link_artifacts'
    id = db.Column(db.String(36), primary_key=True, default=uid)
    run_id = db.Column(db.String(36), db.ForeignKey('webhdp_link_runs.id'), nullable=False, index=True)
    relative_path = db.Column(db.String(1000), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    size = db.Column(db.BigInteger, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    media_type = db.Column(db.String(160), nullable=False)
