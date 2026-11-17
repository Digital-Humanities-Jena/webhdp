import enum
import json
import uuid
from datetime import datetime

from sqlalchemy import and_
from sqlalchemy.orm import foreign
from werkzeug.security import check_password_hash, generate_password_hash

from database.database import db


class UserRole(enum.Enum):
    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"


class InstitutionRole(enum.Enum):
    READER = "reader"
    CURATOR = "curator"
    MANAGER = "manager"
    OWNER = "owner"


class User(db.Model):
    __tablename__ = "users"
    __table_args__ = (
        db.CheckConstraint(
            "profile_visibility IN ('private', 'internal')",
            name="profile_visibility_internal",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    slug = db.Column(db.String(120), unique=True, nullable=True, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(
        db.Enum(UserRole, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=UserRole.USER,
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_verified = db.Column(db.Boolean, default=False)
    verification_token = db.Column(db.String(100), unique=True, nullable=True)
    force_password_change = db.Column(db.Boolean, nullable=False, default=False)
    mfa_enabled = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    token_version = db.Column(db.Integer, nullable=False, default=0)
    capabilities_json = db.Column(db.Text, nullable=False, default="[]")
    onboarding_required = db.Column(db.Boolean, nullable=False, default=False)
    onboarding_completed_at = db.Column(db.DateTime, nullable=True)
    onboarding_skipped_at = db.Column(db.DateTime, nullable=True)
    display_name = db.Column(db.String(120), nullable=True)
    full_name = db.Column(db.String(255), nullable=True)
    affiliation = db.Column(db.String(255), nullable=True)
    orcid = db.Column(db.String(32), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    website_url = db.Column(db.String(500), nullable=True)
    avatar_url = db.Column(db.String(500), nullable=True)
    profile_visibility = db.Column(db.String(32), nullable=False, default="private")
    show_email = db.Column(db.Boolean, nullable=False, default=False)
    show_orcid = db.Column(db.Boolean, nullable=False, default=False)
    show_affiliation = db.Column(db.Boolean, nullable=False, default=False)
    default_institution_id = db.Column(
        db.Integer,
        db.ForeignKey("institutions.id", use_alter=True, name="fk_users_default_institution_id"),
        nullable=True,
    )

    # Relationships
    sessions = db.relationship(
        "Session",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan",
        foreign_keys="Session.user_id",
    )
    publishing_sessions = db.relationship(
        "Session",
        lazy=True,
        foreign_keys="Session.publishing_user_id",
        back_populates="publishing_user",
    )
    reviews = db.relationship("SubmissionReview", backref="moderator", lazy=True)
    default_institution = db.relationship(
        "Institution",
        foreign_keys=[default_institution_id],
        post_update=True,
    )
    institution_memberships = db.relationship(
        "InstitutionMembership",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan",
    )
    audit_events = db.relationship("AuditEvent", backref="actor", lazy=True)
    reported_issues = db.relationship(
        "Issue",
        foreign_keys="Issue.reporter_user_id",
        backref="reporter",
        lazy=True,
    )
    assigned_issues = db.relationship(
        "Issue",
        foreign_keys="Issue.assignee_user_id",
        backref="assignee",
        lazy=True,
    )
    issue_comments = db.relationship(
        "IssueComment",
        foreign_keys="IssueComment.author_user_id",
        backref="author",
        lazy=True,
    )
    notifications = db.relationship(
        "Notification",
        foreign_keys="Notification.recipient_user_id",
        backref="recipient",
        lazy=True,
        cascade="all, delete-orphan",
    )
    notification_deliveries = db.relationship(
        "NotificationDelivery",
        foreign_keys="NotificationDelivery.recipient_user_id",
        backref="recipient",
        lazy=True,
        cascade="all, delete-orphan",
    )
    notification_preferences = db.relationship(
        "NotificationPreference",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan",
    )
    acted_notifications = db.relationship(
        "Notification",
        foreign_keys="Notification.actor_user_id",
        backref="actor",
        lazy=True,
    )
    zenodo_credentials = db.relationship(
        "ZenodoCredential",
        primaryjoin="and_(foreign(ZenodoCredential.owner_id)==User.id, ZenodoCredential.owner_type=='user')",
        viewonly=True,
        lazy=True,
    )
    mfa_challenges = db.relationship(
        "UserMfaChallenge",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan",
    )
    recovery_codes = db.relationship(
        "UserRecoveryCode",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan",
    )
    hpc_resource_requests = db.relationship(
        "HpcResourceRequest",
        foreign_keys="HpcResourceRequest.user_id",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan",
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def capabilities(self):
        raw_value = self.capabilities_json
        if raw_value in (None, ""):
            return []
        if isinstance(raw_value, list):
            return [str(item).strip() for item in raw_value if str(item).strip()]
        try:
            parsed = json.loads(raw_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(parsed, list):
            return []
        return [str(item).strip() for item in parsed if str(item).strip()]

    @property
    def groups(self):
        groups = []
        direct_capabilities = {item.lower() for item in self.capabilities}
        if "developer_access" in direct_capabilities:
            groups.append("developer")
        return groups

    def set_capabilities(self, values):
        normalized = []
        seen = set()
        for value in values or []:
            capability = str(value or "").strip()
            if not capability:
                continue
            marker = capability.lower()
            if marker in seen:
                continue
            seen.add(marker)
            normalized.append(capability)
        self.capabilities_json = json.dumps(normalized, sort_keys=True)

    def has_capability(self, capability: str) -> bool:
        capability_text = str(capability or "").strip().lower()
        if not capability_text:
            return False
        if self.role == UserRole.ADMIN:
            return True
        return capability_text in {item.lower() for item in self.capabilities}

    def to_dict(self):
        profile_visibility = str(self.profile_visibility or "private").strip().lower()
        if profile_visibility == "public":
            profile_visibility = "internal"
        return {
            "id": self.id,
            "public_id": self.public_id,
            "slug": self.slug,
            "email": self.email,
            "role": self.role.value if self.role else "user",
            "created_at": self.created_at.isoformat(),
            "force_password_change": bool(self.force_password_change),
            "mfa_enabled": bool(self.mfa_enabled),
            "capabilities": self.capabilities,
            "groups": self.groups,
            "onboarding_required": bool(self.onboarding_required),
            "onboarding_completed_at": self.onboarding_completed_at.isoformat() if self.onboarding_completed_at else None,
            "onboarding_skipped_at": self.onboarding_skipped_at.isoformat() if self.onboarding_skipped_at else None,
            "display_name": self.display_name,
            "full_name": self.full_name,
            "affiliation": self.affiliation,
            "orcid": self.orcid,
            "bio": self.bio,
            "website_url": self.website_url,
            "avatar_url": self.avatar_url,
            "profile_visibility": profile_visibility,
            "show_email": bool(self.show_email),
            "show_orcid": bool(self.show_orcid),
            "show_affiliation": bool(self.show_affiliation),
            "default_institution_id": self.default_institution_id,
        }


class UserMfaChallenge(db.Model):
    __tablename__ = "user_mfa_challenges"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    method = db.Column(db.String(32), nullable=False, default="email")
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    code_hash = db.Column(db.String(64), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    last_sent_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    consumed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserRecoveryCode(db.Model):
    __tablename__ = "user_recovery_codes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    source = db.Column(db.String(32), nullable=False, default="user_generated", index=True)
    code_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    code_prefix = db.Column(db.String(12), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True, index=True)
    used_at = db.Column(db.DateTime, nullable=True)
    invalidated_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class Institution(db.Model):
    __tablename__ = "institutions"
    __table_args__ = (
        db.CheckConstraint(
            "profile_visibility IN ('private', 'internal')",
            name="profile_visibility_internal",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    name = db.Column(db.String(255), nullable=False, unique=True, index=True)
    slug = db.Column(db.String(120), nullable=False, unique=True, index=True)
    description = db.Column(db.Text, nullable=True)
    display_name = db.Column(db.String(255), nullable=True)
    website_url = db.Column(db.String(500), nullable=True)
    logo_url = db.Column(db.String(500), nullable=True)
    profile_visibility = db.Column(db.String(32), nullable=False, default="private")
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    created_by = db.relationship("User", foreign_keys=[created_by_user_id], lazy=True)
    memberships = db.relationship(
        "InstitutionMembership",
        backref="institution",
        lazy=True,
        cascade="all, delete-orphan",
    )
    sessions = db.relationship("Session", backref="institution", lazy=True)
    communities = db.relationship(
        "InstitutionZenodoCommunity",
        backref="institution",
        lazy=True,
        cascade="all, delete-orphan",
    )
    audit_events = db.relationship("AuditEvent", backref="institution", lazy=True)
    zenodo_credentials = db.relationship(
        "ZenodoCredential",
        primaryjoin="and_(foreign(ZenodoCredential.owner_id)==Institution.id, ZenodoCredential.owner_type=='institution')",
        viewonly=True,
        lazy=True,
    )

    def to_dict(self):
        profile_visibility = str(self.profile_visibility or "private").strip().lower()
        if profile_visibility == "public":
            profile_visibility = "internal"
        return {
            "id": self.id,
            "public_id": self.public_id,
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "display_name": self.display_name,
            "website_url": self.website_url,
            "logo_url": self.logo_url,
            "profile_visibility": profile_visibility,
            "created_by_user_id": self.created_by_user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class InstitutionMembership(db.Model):
    __tablename__ = "institution_memberships"

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    role = db.Column(
        db.Enum(InstitutionRole, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=InstitutionRole.READER,
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("institution_id", "user_id", name="uq_institution_membership"),)

    def to_dict(self):
        return {
            "id": self.id,
            "institution_id": self.institution_id,
            "user_id": self.user_id,
            "role": self.role.value if self.role else InstitutionRole.READER.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "user": self.user.to_dict() if getattr(self, "user", None) else None,
        }


class LodStandard(enum.Enum):
    EDM = "edm"
    IIIF = "iiif"
    METS = "mets"


class LodTemplate(db.Model):
    __tablename__ = "lod_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    standard = db.Column(db.Enum(LodStandard, values_callable=lambda x: [e.value for e in x]), nullable=False, default=LodStandard.EDM)
    format = db.Column(db.String(50), nullable=False, default="xml") # xml, json
    content = db.Column(db.Text, nullable=False)  # Jinja2 template
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "standard": self.standard.value if self.standard else "edm",
            "format": self.format,
            "content": self.content,
            "is_default": self.is_default,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Session(db.Model):
    __tablename__ = "sessions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=True)
    session_dir = db.Column(db.String(500), nullable=False)
    hdpc_path = db.Column(db.String(500))
    # Canonical workflow session states:
    # queued -> scanned -> submitting -> completed | failed
    # Legacy aliases such as pending/active/ready/processing are normalized at the API layer.
    status = db.Column(db.String(50), default="queued")
    timings = db.Column(db.Text)  # JSON serialized timing data
    sharing_scope = db.Column(db.String(32), nullable=False, default="private")
    credential_preference = db.Column(db.String(32), nullable=False, default="user")
    publishing_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    default_zenodo_environment = db.Column(db.String(32), nullable=False, default="sandbox")
    use_institution_default_communities = db.Column(db.Boolean, nullable=False, default=False)
    origin_type = db.Column(db.String(32), nullable=False, default="workflow")
    access_mode = db.Column(db.String(32), nullable=False, default="full")
    origin_metadata_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    files = db.relationship("File", backref="session", lazy=True, cascade="all, delete-orphan")
    cloud_mirror_objects = db.relationship("CloudMirrorObject", backref="session", lazy=True, cascade="all, delete-orphan")
    user_metadata = db.relationship("UserMetadata", backref="session", lazy=True, cascade="all, delete-orphan")
    submissions = db.relationship("Submission", backref="session", lazy=True, cascade="all, delete-orphan")
    publishing_user = db.relationship("User", foreign_keys=[publishing_user_id], lazy=True, back_populates="publishing_sessions")

    @property
    def origin_metadata(self):
        raw_value = self.origin_metadata_json
        if raw_value in (None, ""):
            return None
        if isinstance(raw_value, dict):
            return raw_value
        try:
            parsed = json.loads(raw_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None


class File(db.Model):
    __tablename__ = "files"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    path = db.Column(db.String(500), nullable=False)
    size = db.Column(db.Integer)
    # Upload/source file records still persist low-level scanner states and are normalized for the
    # workflow UI to queued/registered/missing/selected/processed/failed.
    status = db.Column(db.String(50), default="uploaded")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    file_metadata = db.relationship("FileMetadata", backref="file", lazy=True, cascade="all, delete-orphan")


class CloudMirrorObject(db.Model):
    __tablename__ = "cloud_mirror_objects"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=False, index=True)
    file_id = db.Column(db.Integer, db.ForeignKey("files.id"), nullable=True, index=True)
    artifact_kind = db.Column(db.String(64), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    storage_provider = db.Column(db.String(32), nullable=True)
    cloud_path = db.Column(db.String(1000), nullable=True)
    remote_url = db.Column(db.String(1000), nullable=True)
    status = db.Column(db.String(32), nullable=False, default="pending", index=True)
    error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    checked_at = db.Column(db.DateTime, nullable=True)

    file = db.relationship("File", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "file_id": self.file_id,
            "artifact_kind": self.artifact_kind,
            "original_filename": self.original_filename,
            "storage_provider": self.storage_provider,
            "cloud_path": self.cloud_path,
            "remote_url": self.remote_url,
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
        }


class FileBundle(db.Model):
    __tablename__ = "file_bundles"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=False)
    primary_file_id = db.Column(db.Integer, db.ForeignKey("files.id"))
    bundle_name = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class FileMetadata(db.Model):
    __tablename__ = "file_metadata"

    id = db.Column(db.Integer, primary_key=True)
    file_id = db.Column(db.Integer, db.ForeignKey("files.id"), nullable=False)
    field_name = db.Column(db.String(100), nullable=False)
    field_value = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class UserMetadata(db.Model):
    __tablename__ = "user_metadata"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=False)
    field_name = db.Column(db.String(100), nullable=False)
    field_value = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Submission(db.Model):
    __tablename__ = "submissions"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=False)
    pipeline_id = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(50), default="pending")
    result = db.Column(db.Text)
    timings = db.Column(db.Text)  # JSON serialized timing data
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    reviews = db.relationship(
        "SubmissionReview",
        backref="submission",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="SubmissionReview.created_at.desc()",
    )


class SubmissionReview(db.Model):
    __tablename__ = "submission_reviews"

    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey("submissions.id"), nullable=False)
    moderator_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # 'comment', 'status_change', etc.
    action = db.Column(db.String(50), nullable=False, default="comment")
    comment = db.Column(db.Text, nullable=True)

    # For provenance: track what the status was and what it became
    previous_status = db.Column(db.String(50), nullable=True)
    new_status = db.Column(db.String(50), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class TokenBlocklist(db.Model):
    __tablename__ = "token_blocklist"

    id = db.Column(db.Integer, primary_key=True)
    jti = db.Column(db.String(36), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class SystemConfig(db.Model):
    __tablename__ = "system_config"
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text)


class CommunityMigrationJob(db.Model):
    __tablename__ = "community_migration_jobs"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    requested_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    source_retrieval_id = db.Column(db.String(64), nullable=False, index=True)
    source_community = db.Column(db.String(120), nullable=False)
    target_community = db.Column(db.String(120), nullable=False)
    environment = db.Column(db.String(32), nullable=False, default="production")
    filters_json = db.Column(db.Text, nullable=False, default="{}")
    options_json = db.Column(db.Text, nullable=False, default="{}")
    state = db.Column(db.String(32), nullable=False, default="PENDING", index=True)
    phase = db.Column(db.String(64), nullable=False, default="planned")
    task_id = db.Column(db.String(120), nullable=True, index=True)
    summary_json = db.Column(db.Text, nullable=False, default="{}")
    progress_json = db.Column(db.Text, nullable=False, default="{}")
    error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    requested_by = db.relationship("User", lazy=True)
    records = db.relationship(
        "CommunityMigrationRecord",
        backref="job",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="CommunityMigrationRecord.id",
    )

    def _json_field(self, value):
        if value in (None, ""):
            return {}
        if isinstance(value, dict):
            return value
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @property
    def filters(self):
        return self._json_field(self.filters_json)

    @property
    def options(self):
        return self._json_field(self.options_json)

    @property
    def summary(self):
        return self._json_field(self.summary_json)

    @property
    def progress(self):
        return self._json_field(self.progress_json)

    def to_dict(self, *, include_records=False):
        payload = {
            "id": self.public_id,
            "job_id": self.public_id,
            "task_id": self.task_id,
            "requested_by_user_id": self.requested_by_user_id,
            "source_retrieval_id": self.source_retrieval_id,
            "source_community": self.source_community,
            "target_community": self.target_community,
            "environment": self.environment,
            "filters": self.filters,
            "options": self.options,
            "state": self.state,
            "phase": self.phase,
            "summary": self.summary,
            "progress": self.progress,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
        if include_records:
            payload["records"] = [record.to_dict() for record in self.records]
        return payload


class CommunityMigrationRecord(db.Model):
    __tablename__ = "community_migration_records"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("community_migration_jobs.id"), nullable=False, index=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=False, index=True)
    local_record_id = db.Column(db.Integer, nullable=False)
    zenodo_record_id = db.Column(db.String(120), nullable=True, index=True)
    concept_rec_id = db.Column(db.String(120), nullable=True)
    record_title = db.Column(db.Text, nullable=True)
    record_status = db.Column(db.String(32), nullable=True)
    record_origin = db.Column(db.String(64), nullable=True)
    is_editable = db.Column(db.Boolean, nullable=False, default=False)
    ineligibility_reason = db.Column(db.Text, nullable=True)
    before_communities_json = db.Column(db.Text, nullable=False, default="[]")
    after_communities_json = db.Column(db.Text, nullable=False, default="[]")
    append_status = db.Column(db.String(32), nullable=False, default="pending")
    verify_status = db.Column(db.String(32), nullable=False, default="pending")
    remove_status = db.Column(db.String(32), nullable=False, default="pending")
    final_status = db.Column(db.String(32), nullable=False, default="pending")
    retry_count = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.Text, nullable=True)
    last_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    session = db.relationship("Session", lazy=True)

    __table_args__ = (
        db.UniqueConstraint("job_id", "session_id", "local_record_id", name="uq_community_migration_job_record"),
    )

    def _json_list(self, value):
        if value in (None, ""):
            return []
        if isinstance(value, list):
            return value
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return parsed if isinstance(parsed, list) else []

    @property
    def before_communities(self):
        return self._json_list(self.before_communities_json)

    @property
    def after_communities(self):
        return self._json_list(self.after_communities_json)

    def to_dict(self):
        return {
            "id": self.id,
            "job_id": self.job.public_id if self.job else self.job_id,
            "session_id": self.session_id,
            "local_record_id": self.local_record_id,
            "zenodo_record_id": self.zenodo_record_id,
            "concept_rec_id": self.concept_rec_id,
            "record_title": self.record_title,
            "record_status": self.record_status,
            "record_origin": self.record_origin,
            "is_editable": bool(self.is_editable),
            "ineligibility_reason": self.ineligibility_reason,
            "before_communities": self.before_communities,
            "after_communities": self.after_communities,
            "append_status": self.append_status,
            "verify_status": self.verify_status,
            "remove_status": self.remove_status,
            "final_status": self.final_status,
            "retry_count": int(self.retry_count or 0),
            "last_error": self.last_error,
            "last_message": self.last_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CommunityModerationSweepJob(db.Model):
    __tablename__ = "community_moderation_sweep_jobs"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    task_id = db.Column(db.String(120), nullable=True, index=True)
    requested_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    community_identifier = db.Column(db.String(120), nullable=False, index=True)
    community_uuid = db.Column(db.String(120), nullable=True)
    community_title = db.Column(db.String(255), nullable=True)
    community_links_json = db.Column(db.Text, nullable=False, default="{}")
    action = db.Column(db.String(32), nullable=False)
    status_filter = db.Column(db.String(32), nullable=False, default="submitted")
    request_type = db.Column(db.String(120), nullable=True)
    note_present = db.Column(db.Boolean, nullable=False, default=False)
    note_json = db.Column(db.Text, nullable=False, default="{}")
    page_size = db.Column(db.Integer, nullable=False, default=100)
    max_requests = db.Column(db.Integer, nullable=True)
    plan_checksum = db.Column(db.String(64), nullable=False)
    confirmation_text = db.Column(db.String(255), nullable=False)
    state = db.Column(db.String(32), nullable=False, default="PENDING", index=True)
    phase = db.Column(db.String(64), nullable=False, default="planned")
    summary_json = db.Column(db.Text, nullable=False, default="{}")
    progress_json = db.Column(db.Text, nullable=False, default="{}")
    control_json = db.Column(db.Text, nullable=False, default="{}")
    error = db.Column(db.Text, nullable=True)
    last_error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    requested_by = db.relationship("User", lazy=True)
    events = db.relationship(
        "CommunityModerationSweepEvent",
        backref="job",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="CommunityModerationSweepEvent.id",
    )

    def _json_field(self, value):
        if value in (None, ""):
            return {}
        if isinstance(value, dict):
            return value
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @property
    def community_links(self):
        return self._json_field(self.community_links_json)

    @property
    def note_payload(self):
        return self._json_field(self.note_json)

    @property
    def summary(self):
        return self._json_field(self.summary_json)

    @property
    def progress(self):
        return self._json_field(self.progress_json)

    @property
    def control(self):
        return self._json_field(self.control_json)

    def to_dict(self, *, include_events=False, event_limit=50):
        payload = {
            "id": self.public_id,
            "job_id": self.public_id,
            "task_id": self.task_id,
            "requested_by_user_id": self.requested_by_user_id,
            "community_identifier": self.community_identifier,
            "community_uuid": self.community_uuid,
            "community_title": self.community_title,
            "community_links": self.community_links,
            "action": self.action,
            "status_filter": self.status_filter,
            "request_type": self.request_type,
            "note_present": bool(self.note_present),
            "page_size": int(self.page_size or 0),
            "max_requests": int(self.max_requests) if self.max_requests is not None else None,
            "plan_checksum": self.plan_checksum,
            "confirmation_text": self.confirmation_text,
            "state": self.state,
            "phase": self.phase,
            "summary": self.summary,
            "progress": self.progress,
            "control": self.control,
            "error": self.error,
            "last_error": self.last_error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
        if include_events:
            events = self.events
            if event_limit is not None:
                events = events[-max(1, int(event_limit)) :]
            payload["events"] = [event.to_dict() for event in events]
        return payload


class CommunityModerationSweepEvent(db.Model):
    __tablename__ = "community_moderation_sweep_events"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("community_moderation_sweep_jobs.id"), nullable=False, index=True)
    request_id = db.Column(db.String(120), nullable=True, index=True)
    request_number = db.Column(db.String(120), nullable=True)
    record_id = db.Column(db.String(120), nullable=True)
    title = db.Column(db.Text, nullable=True)
    request_type = db.Column(db.String(120), nullable=True)
    event = db.Column(db.String(64), nullable=False, index=True)
    status = db.Column(db.String(64), nullable=True)
    message = db.Column(db.Text, nullable=True)
    rate_limit_reason = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "job_id": self.job.public_id if self.job else self.job_id,
            "request_id": self.request_id,
            "request_number": self.request_number,
            "record_id": self.record_id,
            "title": self.title,
            "request_type": self.request_type,
            "event": self.event,
            "status": self.status,
            "message": self.message,
            "rate_limit_reason": self.rate_limit_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class HpcLinkConfig(db.Model):
    __tablename__ = "hpc_link_configs"

    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    require_for_components = db.Column(db.Boolean, nullable=False, default=False)
    base_url = db.Column(db.String(500), nullable=True)
    encrypted_token = db.Column(db.Text, nullable=True)
    masked_token_preview = db.Column(db.String(64), nullable=True)
    default_partition = db.Column(db.String(64), nullable=False, default="partition-a")
    default_gpu_type = db.Column(db.String(64), nullable=True)
    default_gpu_count = db.Column(db.Integer, nullable=False, default=1)
    default_duration_minutes = db.Column(db.Integer, nullable=False, default=30)
    max_active_allocations = db.Column(db.Integer, nullable=False, default=3)
    max_active_allocations_per_user = db.Column(db.Integer, nullable=False, default=1)
    remote_data_root = db.Column(db.String(500), nullable=True)
    remote_apps_root = db.Column(db.String(500), nullable=True)
    last_validation_status = db.Column(db.String(32), nullable=False, default="unknown")
    last_validation_error = db.Column(db.Text, nullable=True)
    last_validated_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class HpcReservation(db.Model):
    __tablename__ = "hpc_reservations"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    gateway_reservation_id = db.Column(db.String(128), nullable=False, unique=True)
    gateway_url = db.Column(db.String(500), nullable=False)
    label = db.Column(db.String(120), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    scheduler_json = db.Column(db.Text, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    grants = db.relationship("HpcReservationGrant", cascade="all, delete-orphan", lazy=True)


class HpcReservationGrant(db.Model):
    __tablename__ = "hpc_reservation_grants"

    reservation_id = db.Column(db.Integer, db.ForeignKey("hpc_reservations.id", ondelete="CASCADE"), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    user = db.relationship("User", lazy=True)


class HpcAllocation(db.Model):
    __tablename__ = "hpc_allocations"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=True, index=True)
    reservation_id = db.Column(db.Integer, db.ForeignKey("hpc_reservations.id"), nullable=True, index=True)
    purpose = db.Column(db.String(32), nullable=False, default="workflow")
    status = db.Column(db.String(32), nullable=False, default="queued", index=True)
    requested_partition = db.Column(db.String(64), nullable=False)
    requested_gpu_type = db.Column(db.String(64), nullable=True)
    requested_gpu_count = db.Column(db.Integer, nullable=False, default=1)
    requested_duration_minutes = db.Column(db.Integer, nullable=False, default=30)
    partition_sequence_json = db.Column(db.Text, nullable=True)
    partition_attempt_index = db.Column(db.Integer, nullable=False, default=0)
    partition_attempt_started_at = db.Column(db.DateTime, nullable=True)
    partition_attempt_history_json = db.Column(db.Text, nullable=True)
    remote_session_id = db.Column(db.String(128), nullable=True, index=True)
    remote_job_id = db.Column(db.String(128), nullable=True)
    remote_session_dir = db.Column(db.String(1000), nullable=True)
    remote_input_dir = db.Column(db.String(1000), nullable=True)
    remote_output_dir = db.Column(db.String(1000), nullable=True)
    scheduler_state = db.Column(db.String(64), nullable=True)
    scheduler_reason = db.Column(db.String(255), nullable=True)
    node_name = db.Column(db.String(255), nullable=True)
    last_health_json = db.Column(db.Text, nullable=True)
    last_error = db.Column(db.Text, nullable=True)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    allocated_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    released_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = db.relationship("User", lazy=True)
    session = db.relationship("Session", lazy=True)
    reservation = db.relationship("HpcReservation", lazy=True)


class HpcArtifact(db.Model):
    __tablename__ = "hpc_artifacts"

    id = db.Column(db.Integer, primary_key=True)
    allocation_id = db.Column(db.Integer, db.ForeignKey("hpc_allocations.id"), nullable=False, index=True)
    pipeline_run_id = db.Column(db.Integer, db.ForeignKey("pipeline_runs.id"), nullable=True, index=True)
    step_run_id = db.Column(db.Integer, db.ForeignKey("step_runs.id"), nullable=True, index=True)
    playground_run_id = db.Column(db.Integer, db.ForeignKey("playground_runs.id"), nullable=True, index=True)
    record_id = db.Column(db.Integer, nullable=True)
    component_key = db.Column(db.String(120), nullable=False)
    artifact_kind = db.Column(db.String(50), nullable=False, default="file")
    name = db.Column(db.String(255), nullable=False)
    remote_path = db.Column(db.String(1000), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=True)
    metadata_json = db.Column(db.Text, nullable=False, default="{}")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    allocation = db.relationship("HpcAllocation", lazy=True)


class HpcResourceRequest(db.Model):
    __tablename__ = "hpc_resource_requests"

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CANCELLED = "cancelled"
    VALID_STATUSES = {STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED, STATUS_CANCELLED}

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    status = db.Column(db.String(32), nullable=False, default=STATUS_PENDING, index=True)
    full_name = db.Column(db.String(255), nullable=False)
    affiliation = db.Column(db.String(255), nullable=False)
    use_cases_json = db.Column(db.Text, nullable=False, default="[]")
    notes = db.Column(db.Text, nullable=True)
    reviewer_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    review_comment = db.Column(db.Text, nullable=True)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    reviewer = db.relationship("User", foreign_keys=[reviewer_user_id], lazy=True)

    def use_cases(self):
        try:
            parsed = json.loads(self.use_cases_json or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(parsed, list):
            return []
        return [str(item).strip() for item in parsed if str(item).strip()]

    def set_use_cases(self, values):
        normalized = []
        seen = set()
        for value in values or []:
            text = str(value or "").strip()
            if not text:
                continue
            marker = text.lower()
            if marker in seen:
                continue
            seen.add(marker)
            normalized.append(text)
        self.use_cases_json = json.dumps(normalized, sort_keys=True)

    def to_dict(self):
        reviewer = getattr(self, "reviewer", None)
        return {
            "id": self.id,
            "public_id": self.public_id,
            "user_id": self.user_id,
            "status": self.status,
            "full_name": self.full_name,
            "affiliation": self.affiliation,
            "use_cases": self.use_cases(),
            "notes": self.notes,
            "reviewer_user_id": self.reviewer_user_id,
            "reviewer": (
                {
                    "id": reviewer.id,
                    "email": reviewer.email,
                    "display_name": reviewer.display_name,
                    "full_name": reviewer.full_name,
                }
                if reviewer
                else None
            ),
            "review_comment": self.review_comment,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class HpcComponentInstallation(db.Model):
    __tablename__ = "hpc_component_installations"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    component_key = db.Column(db.String(120), nullable=False, index=True)
    version = db.Column(db.String(64), nullable=False)
    component_version_id = db.Column(db.Integer, db.ForeignKey("component_versions.id"), nullable=True, index=True)
    status = db.Column(db.String(32), nullable=False, default="pending", index=True)
    sif_remote_path = db.Column(db.String(1000), nullable=True)
    remote_install_dir = db.Column(db.String(1000), nullable=True)
    manifest_hash = db.Column(db.String(64), nullable=False, index=True)
    manifest_json = db.Column(db.Text, nullable=False)
    checks_json = db.Column(db.Text, nullable=False, default="{}")
    logs_json = db.Column(db.Text, nullable=False, default="{}")
    error = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    installed_at = db.Column(db.DateTime, nullable=True)
    last_tested_at = db.Column(db.DateTime, nullable=True)

    component_version = db.relationship("ComponentVersion", lazy=True)
    creator = db.relationship("User", lazy=True)

class ZenodoCredential(db.Model):
    __tablename__ = "zenodo_credentials"

    VALIDATION_MODE = "live_write_cleanup"
    RECOMMENDED_SCOPES = ("deposit:write", "deposit:actions")

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, default="Zenodo API key")
    owner_type = db.Column(db.String(32), nullable=False)
    owner_id = db.Column(db.Integer, nullable=False)
    environment = db.Column(db.String(32), nullable=False)
    encrypted_value = db.Column(db.Text, nullable=False)
    masked_preview = db.Column(db.String(64), nullable=True)
    validation_status = db.Column(db.String(32), nullable=False, default="unknown")
    last_validated_at = db.Column(db.DateTime, nullable=True)
    last_validation_error = db.Column(db.Text, nullable=True)
    last_validation_report = db.Column(db.Text, nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    created_by = db.relationship("User", foreign_keys=[created_by_user_id], lazy=True)
    shares = db.relationship("ZenodoCredentialShare", backref="credential", lazy=True, cascade="all, delete-orphan")

    def _parse_validation_report(self):
        if not self.last_validation_report:
            return None
        try:
            parsed = json.loads(self.last_validation_report)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def to_dict(self):
        validation_report = self._parse_validation_report()
        return {
            "id": self.id,
            "name": self.name,
            "owner_type": self.owner_type,
            "owner_id": self.owner_id,
            "environment": self.environment,
            "masked_preview": self.masked_preview,
            "validation_status": self.validation_status,
            "validation_mode": (validation_report or {}).get("mode") or self.VALIDATION_MODE,
            "validation_report": validation_report,
            "recommended_scopes": list(self.RECOMMENDED_SCOPES),
            "last_validated_at": self.last_validated_at.isoformat() if self.last_validated_at else None,
            "last_validation_error": self.last_validation_error,
            "created_by_user_id": self.created_by_user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ZenodoCredentialShare(db.Model):
    __tablename__ = "zenodo_credential_shares"

    id = db.Column(db.Integer, primary_key=True)
    credential_id = db.Column(db.Integer, db.ForeignKey("zenodo_credentials.id"), nullable=False, index=True)
    shared_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    recipient_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    status = db.Column(db.String(32), nullable=False, default="pending", index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    responded_at = db.Column(db.DateTime, nullable=True)

    shared_by = db.relationship("User", foreign_keys=[shared_by_user_id], lazy=True)
    recipient = db.relationship("User", foreign_keys=[recipient_user_id], lazy=True)

    __table_args__ = (
        db.UniqueConstraint("credential_id", "recipient_user_id", name="uq_zenodo_credential_share_recipient"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "credential_id": self.credential_id,
            "shared_by_user_id": self.shared_by_user_id,
            "recipient_user_id": self.recipient_user_id,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "responded_at": self.responded_at.isoformat() if self.responded_at else None,
        }


class UserZenodoActiveCredential(db.Model):
    __tablename__ = "user_zenodo_active_credentials"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    environment = db.Column(db.String(32), nullable=False)
    credential_id = db.Column(db.Integer, db.ForeignKey("zenodo_credentials.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id], lazy=True)
    credential = db.relationship("ZenodoCredential", foreign_keys=[credential_id], lazy=True)

    __table_args__ = (
        db.UniqueConstraint("user_id", "environment", name="uq_user_zenodo_active_environment"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "environment": self.environment,
            "credential_id": self.credential_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class InstitutionZenodoCommunity(db.Model):
    __tablename__ = "institution_zenodo_communities"

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False)
    identifier = db.Column(db.String(120), nullable=False)
    is_primary_submission = db.Column(db.Boolean, nullable=False, default=False)
    is_moderation_default = db.Column(db.Boolean, nullable=False, default=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("institution_id", "identifier", name="uq_institution_community_identifier"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "institution_id": self.institution_id,
            "identifier": self.identifier,
            "is_primary_submission": self.is_primary_submission,
            "is_moderation_default": self.is_moderation_default,
            "enabled": self.enabled,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Issue(db.Model):
    __tablename__ = "issues"

    id = db.Column(db.Integer, primary_key=True)
    reporter_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    assignee_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    title = db.Column(db.String(255), nullable=False)
    issue_type = db.Column(db.String(64), nullable=False, default="general")
    reporter_impact = db.Column(db.String(32), nullable=False, default="medium")
    internal_priority = db.Column(db.String(32), nullable=False, default="medium")
    status = db.Column(db.String(32), nullable=False, default="new", index=True)
    page_key = db.Column(db.String(120), nullable=True, index=True)
    page_label = db.Column(db.String(255), nullable=True)
    route_name = db.Column(db.String(120), nullable=True)
    route_path = db.Column(db.String(255), nullable=True)
    current_url = db.Column(db.String(512), nullable=True)
    route_context_json = db.Column(db.Text, nullable=False, default="{}")
    related_entity_ids_json = db.Column(db.Text, nullable=False, default="{}")
    environment_context_json = db.Column(db.Text, nullable=False, default="{}")
    user_context_json = db.Column(db.Text, nullable=False, default="{}")
    public_description = db.Column(db.Text, nullable=True)
    expected_behavior = db.Column(db.Text, nullable=True)
    technical_details = db.Column(db.Text, nullable=True)
    reproduction_steps = db.Column(db.Text, nullable=True)
    console_notes = db.Column(db.Text, nullable=True)
    api_notes = db.Column(db.Text, nullable=True)
    suspected_subsystem = db.Column(db.String(120), nullable=True)
    capture_context_json = db.Column(db.Text, nullable=False, default="{}")
    code_refs_json = db.Column(db.Text, nullable=False, default="{}")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    resolved_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)

    comments = db.relationship(
        "IssueComment",
        backref="issue",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="IssueComment.created_at.asc()",
    )

    @staticmethod
    def _parse_json_dict(raw_value):
        if raw_value in (None, ""):
            return {}
        if isinstance(raw_value, dict):
            return raw_value
        try:
            parsed = json.loads(raw_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @property
    def route_context(self):
        return self._parse_json_dict(self.route_context_json)

    @property
    def related_entity_ids(self):
        return self._parse_json_dict(self.related_entity_ids_json)

    @property
    def environment_context(self):
        return self._parse_json_dict(self.environment_context_json)

    @property
    def user_context(self):
        return self._parse_json_dict(self.user_context_json)

    @property
    def capture_context(self):
        return self._parse_json_dict(self.capture_context_json)

    @property
    def code_references(self):
        payload = self._parse_json_dict(self.code_refs_json)
        return {
            "first_order": list(payload.get("first_order") or []),
            "second_order": list(payload.get("second_order") or []),
            "third_order": list(payload.get("third_order") or []),
        }

    def set_route_context(self, payload):
        self.route_context_json = json.dumps(payload or {}, sort_keys=True)

    def set_related_entity_ids(self, payload):
        self.related_entity_ids_json = json.dumps(payload or {}, sort_keys=True)

    def set_environment_context(self, payload):
        self.environment_context_json = json.dumps(payload or {}, sort_keys=True)

    def set_user_context(self, payload):
        self.user_context_json = json.dumps(payload or {}, sort_keys=True)

    def set_capture_context(self, payload):
        self.capture_context_json = json.dumps(payload or {}, sort_keys=True)

    def set_code_references(self, payload):
        normalized = payload if isinstance(payload, dict) else {}
        self.code_refs_json = json.dumps(
            {
                "first_order": list(normalized.get("first_order") or []),
                "second_order": list(normalized.get("second_order") or []),
                "third_order": list(normalized.get("third_order") or []),
            },
            sort_keys=True,
        )

    def to_dict(self):
        return {
            "id": self.id,
            "reporter_user_id": self.reporter_user_id,
            "assignee_user_id": self.assignee_user_id,
            "title": self.title,
            "issue_type": self.issue_type,
            "reporter_impact": self.reporter_impact,
            "internal_priority": self.internal_priority,
            "status": self.status,
            "page_key": self.page_key,
            "page_label": self.page_label,
            "route_name": self.route_name,
            "route_path": self.route_path,
            "current_url": self.current_url,
            "route_context": self.route_context,
            "related_entity_ids": self.related_entity_ids,
            "environment_context": self.environment_context,
            "user_context": self.user_context,
            "public_description": self.public_description,
            "expected_behavior": self.expected_behavior,
            "technical_details": self.technical_details,
            "reproduction_steps": self.reproduction_steps,
            "console_notes": self.console_notes,
            "api_notes": self.api_notes,
            "suspected_subsystem": self.suspected_subsystem,
            "capture_context": self.capture_context,
            "code_references": self.code_references,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
        }


class IssueComment(db.Model):
    __tablename__ = "issue_comments"

    id = db.Column(db.Integer, primary_key=True)
    issue_id = db.Column(db.Integer, db.ForeignKey("issues.id"), nullable=False, index=True)
    author_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    body = db.Column(db.Text, nullable=False)
    is_internal = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "issue_id": self.issue_id,
            "author_user_id": self.author_user_id,
            "body": self.body,
            "is_internal": self.is_internal,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AuditEvent(db.Model):
    __tablename__ = "audit_events"

    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=True)
    event_type = db.Column(db.String(120), nullable=False)
    entity_type = db.Column(db.String(120), nullable=False)
    entity_id = db.Column(db.String(120), nullable=True)
    details_json = db.Column(db.Text, nullable=False, default="{}")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    session = db.relationship("Session", lazy=True)

    @property
    def details(self):
        raw_value = self.details_json
        if raw_value in (None, ""):
            return {}
        if isinstance(raw_value, dict):
            return raw_value
        try:
            parsed = json.loads(raw_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def set_details(self, payload):
        self.details_json = json.dumps(payload or {}, sort_keys=True)

    def to_dict(self):
        return {
            "id": self.id,
            "actor_user_id": self.actor_user_id,
            "institution_id": self.institution_id,
            "session_id": self.session_id,
            "event_type": self.event_type,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "details": self.details,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Notification(db.Model):
    __tablename__ = "notifications"
    __table_args__ = (
        db.Index("ix_notifications_recipient_read_created", "recipient_user_id", "read_at", "created_at"),
        db.Index("ix_notifications_recipient_archived", "recipient_user_id", "archived_at"),
        db.Index("ix_notifications_recipient_category_created", "recipient_user_id", "category", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    recipient_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=True, index=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=True, index=True)
    entity_type = db.Column(db.String(120), nullable=True)
    entity_id = db.Column(db.String(120), nullable=True)
    notification_type = db.Column(db.String(120), nullable=False, index=True)
    category = db.Column(db.String(80), nullable=False, default="system", index=True)
    severity = db.Column(db.String(32), nullable=False, default="info")
    title = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=True)
    action_url = db.Column(db.String(512), nullable=True)
    payload_json = db.Column(db.Text, nullable=False, default="{}")
    dedupe_key = db.Column(db.String(255), unique=True, nullable=True)
    email_status = db.Column(db.String(32), nullable=True)
    emailed_at = db.Column(db.DateTime, nullable=True)
    email_error = db.Column(db.Text, nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)
    archived_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    institution = db.relationship("Institution", lazy=True)
    session = db.relationship("Session", lazy=True)
    deliveries = db.relationship("NotificationDelivery", backref="notification", lazy=True, cascade="all, delete-orphan")

    @property
    def payload(self):
        raw_value = self.payload_json
        if raw_value in (None, ""):
            return {}
        if isinstance(raw_value, dict):
            return raw_value
        try:
            parsed = json.loads(raw_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def set_payload(self, payload):
        self.payload_json = json.dumps(payload or {}, sort_keys=True)

    def to_dict(self):
        return {
            "id": self.id,
            "recipient_user_id": self.recipient_user_id,
            "actor_user_id": self.actor_user_id,
            "institution_id": self.institution_id,
            "session_id": self.session_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "notification_type": self.notification_type,
            "category": self.category,
            "severity": self.severity,
            "title": self.title,
            "body": self.body,
            "action_url": self.action_url,
            "payload": self.payload,
            "dedupe_key": self.dedupe_key,
            "email_status": self.email_status,
            "emailed_at": self.emailed_at.isoformat() if self.emailed_at else None,
            "email_error": self.email_error,
            "read_at": self.read_at.isoformat() if self.read_at else None,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class NotificationPreference(db.Model):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        db.UniqueConstraint("user_id", "category", name="uq_notification_preferences_user_category"),
        db.Index("ix_notification_preferences_user_category", "user_id", "category"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    category = db.Column(db.String(80), nullable=False)
    in_app_enabled = db.Column(db.Boolean, nullable=False, default=True)
    email_enabled = db.Column(db.Boolean, nullable=False, default=False)
    digest_enabled = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "category": self.category,
            "in_app_enabled": bool(self.in_app_enabled),
            "email_enabled": bool(self.email_enabled),
            "digest_enabled": bool(self.digest_enabled),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class NotificationDelivery(db.Model):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        db.Index("ix_notification_deliveries_channel_status_created", "channel", "status", "created_at"),
        db.Index("ix_notification_deliveries_recipient_channel_created", "recipient_user_id", "channel", "created_at"),
        db.Index("ix_notification_deliveries_batch_key", "batch_key"),
    )

    id = db.Column(db.Integer, primary_key=True)
    notification_id = db.Column(db.Integer, db.ForeignKey("notifications.id"), nullable=False, index=True)
    recipient_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    channel = db.Column(db.String(32), nullable=False, index=True)
    status = db.Column(db.String(32), nullable=False, index=True)
    batch_key = db.Column(db.String(120), nullable=True)
    provider_message_id = db.Column(db.String(255), nullable=True)
    error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    sent_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "notification_id": self.notification_id,
            "recipient_user_id": self.recipient_user_id,
            "channel": self.channel,
            "status": self.status,
            "batch_key": self.batch_key,
            "provider_message_id": self.provider_message_id,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
        }


class BatchFileMetadata(db.Model):
    """Stores MSF-derived metadata for each file in a batch session"""
    __tablename__ = "batch_file_metadata"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)  # The matched filename
    metadata_json = db.Column(db.Text, nullable=False)  # JSON-serialized Zenodo metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    session = db.relationship("Session", backref=db.backref("batch_file_metadata", lazy=True, cascade="all, delete-orphan"))

    # Composite unique constraint
    __table_args__ = (db.UniqueConstraint('session_id', 'filename', name='uq_session_filename'),)

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "filename": self.filename,
            "metadata_json": self.metadata_json,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class PipelineVersionStatus(enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class PipelineRunStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ComponentDefinition(db.Model):
    __tablename__ = "component_definitions"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(120), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    source_type = db.Column(db.String(50), nullable=False, default="builtin")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    versions = db.relationship(
        "ComponentVersion",
        backref="component_definition",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="ComponentVersion.created_at.desc()",
    )


class ComponentVersion(db.Model):
    __tablename__ = "component_versions"

    id = db.Column(db.Integer, primary_key=True)
    component_definition_id = db.Column(db.Integer, db.ForeignKey("component_definitions.id"), nullable=False)
    version = db.Column(db.String(64), nullable=False)
    manifest_json = db.Column(db.Text, nullable=False)
    source_path = db.Column(db.String(1000))
    manifest_hash = db.Column(db.String(64), nullable=False, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    profiles = db.relationship(
        "ComponentProfile",
        backref="component_version",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="ComponentProfile.created_at.asc()",
    )

    __table_args__ = (
        db.UniqueConstraint("component_definition_id", "version", name="uq_component_definition_version"),
    )


class ComponentProfile(db.Model):
    __tablename__ = "component_profiles"

    id = db.Column(db.Integer, primary_key=True)
    component_version_id = db.Column(db.Integer, db.ForeignKey("component_versions.id"), nullable=False)
    profile_id = db.Column(db.String(120), nullable=False)
    adapter = db.Column(db.String(50), nullable=False)
    runtime = db.Column(db.String(50))
    entrypoint_json = db.Column(db.Text, nullable=False, default="[]")
    config_json = db.Column(db.Text, nullable=False, default="{}")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("component_version_id", "profile_id", name="uq_component_profile"),
    )


class PipelineDefinition(db.Model):
    __tablename__ = "pipeline_definitions"

    id = db.Column(db.Integer, primary_key=True)
    identifier = db.Column(db.String(120), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(50), nullable=False, default="active")
    modality = db.Column(db.String(120))
    tags_json = db.Column(db.Text, nullable=False, default="[]")
    processing_mode = db.Column(db.String(50), nullable=False, default="root")
    is_public = db.Column(db.Boolean, nullable=False, default=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    active_version_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "pipeline_versions.id",
            use_alter=True,
            name="fk_pipeline_definitions_active_version",
        ),
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    versions = db.relationship(
        "PipelineVersion",
        foreign_keys="PipelineVersion.pipeline_definition_id",
        backref="pipeline_definition",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="PipelineVersion.created_at.desc()",
    )


class PipelineVersion(db.Model):
    __tablename__ = "pipeline_versions"

    id = db.Column(db.Integer, primary_key=True)
    pipeline_definition_id = db.Column(db.Integer, db.ForeignKey("pipeline_definitions.id"), nullable=False)
    version = db.Column(db.String(64), nullable=False)
    status = db.Column(
        db.Enum(PipelineVersionStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=PipelineVersionStatus.DRAFT,
    )
    config_json = db.Column(db.Text, nullable=False)
    config_hash = db.Column(db.String(64), nullable=False, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=False)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    activated_at = db.Column(db.DateTime)

    steps = db.relationship(
        "PipelineStep",
        backref="pipeline_version",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="PipelineStep.order_index.asc()",
    )

    __table_args__ = (
        db.UniqueConstraint("pipeline_definition_id", "version", name="uq_pipeline_definition_version"),
    )


class PipelinePublicationRequest(db.Model):
    __tablename__ = "pipeline_publication_requests"

    request_id = db.Column(db.String(36), primary_key=True)
    fingerprint = db.Column(db.String(64), nullable=False)
    pipeline_version_id = db.Column(db.Integer, db.ForeignKey("pipeline_versions.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))


class PipelineStep(db.Model):
    __tablename__ = "pipeline_steps"

    id = db.Column(db.Integer, primary_key=True)
    pipeline_version_id = db.Column(db.Integer, db.ForeignKey("pipeline_versions.id"), nullable=False)
    step_key = db.Column(db.String(120), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    order_index = db.Column(db.Integer, nullable=False)
    scope = db.Column(db.String(50), nullable=False, default="record")
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    component_key = db.Column(db.String(120), nullable=False)
    component_version_id = db.Column(db.Integer, db.ForeignKey("component_versions.id"))
    execution_profile_id = db.Column(db.String(120), nullable=False, default="builtin_default")
    config_json = db.Column(db.Text, nullable=False, default="{}")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    bindings = db.relationship(
        "PipelineBinding",
        backref="pipeline_step",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="PipelineBinding.id.asc()",
    )
    output_actions = db.relationship(
        "PipelineOutputAction",
        backref="pipeline_step",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="PipelineOutputAction.id.asc()",
    )


class PipelineBinding(db.Model):
    __tablename__ = "pipeline_bindings"

    id = db.Column(db.Integer, primary_key=True)
    pipeline_step_id = db.Column(db.Integer, db.ForeignKey("pipeline_steps.id"), nullable=False)
    binding_kind = db.Column(db.String(50), nullable=False)
    target_name = db.Column(db.String(120), nullable=False)
    binding_type = db.Column(db.String(50), nullable=False)
    source_step_key = db.Column(db.String(120))
    source_output_name = db.Column(db.String(120))
    source_selector = db.Column(db.String(255))
    metadata_field = db.Column(db.String(120))
    literal_value = db.Column(db.Text)
    secret_ref = db.Column(db.String(255))
    config_json = db.Column(db.Text, nullable=False, default="{}")


class PipelineOutputAction(db.Model):
    __tablename__ = "pipeline_output_actions"

    id = db.Column(db.Integer, primary_key=True)
    pipeline_step_id = db.Column(db.Integer, db.ForeignKey("pipeline_steps.id"), nullable=False)
    action_type = db.Column(db.String(50), nullable=False)
    source_output_name = db.Column(db.String(120))
    source_selector = db.Column(db.String(255))
    target_field = db.Column(db.String(120))
    transform = db.Column(db.String(120))
    overwrite_policy = db.Column(db.String(50))
    config_json = db.Column(db.Text, nullable=False, default="{}")


class PipelineRun(db.Model):
    __tablename__ = "pipeline_runs"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    pipeline_definition_id = db.Column(db.Integer, db.ForeignKey("pipeline_definitions.id"), nullable=False)
    pipeline_version_id = db.Column(db.Integer, db.ForeignKey("pipeline_versions.id"), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"))
    submission_id = db.Column(db.Integer, db.ForeignKey("submissions.id"))
    initiated_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    status = db.Column(
        db.Enum(PipelineRunStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=PipelineRunStatus.PENDING,
    )
    request_json = db.Column(db.Text, nullable=False, default="{}")
    result_json = db.Column(db.Text)
    timings_json = db.Column(db.Text)
    logs_json = db.Column(db.Text)
    error_message = db.Column(db.Text)
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime)

    step_runs = db.relationship(
        "StepRun",
        backref="pipeline_run",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="StepRun.started_at.asc()",
    )
    artifacts = db.relationship(
        "ExecutionArtifact",
        backref="pipeline_run",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="ExecutionArtifact.created_at.asc()",
    )


class StepRun(db.Model):
    __tablename__ = "step_runs"

    id = db.Column(db.Integer, primary_key=True)
    pipeline_run_id = db.Column(db.Integer, db.ForeignKey("pipeline_runs.id"), nullable=False)
    pipeline_step_id = db.Column(db.Integer, db.ForeignKey("pipeline_steps.id"), nullable=False)
    record_id = db.Column(db.Integer)
    record_path = db.Column(db.String(1000))
    status = db.Column(db.String(50), nullable=False, default="pending")
    scope = db.Column(db.String(50), nullable=False, default="record")
    command_json = db.Column(db.Text)
    logs_json = db.Column(db.Text)
    result_json = db.Column(db.Text)
    error_message = db.Column(db.Text)
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime)


class ExecutionArtifact(db.Model):
    __tablename__ = "execution_artifacts"

    id = db.Column(db.Integer, primary_key=True)
    pipeline_run_id = db.Column(db.Integer, db.ForeignKey("pipeline_runs.id"), nullable=False)
    step_run_id = db.Column(db.Integer, db.ForeignKey("step_runs.id"))
    record_id = db.Column(db.Integer)
    artifact_kind = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    path = db.Column(db.String(1000))
    metadata_json = db.Column(db.Text, nullable=False, default="{}")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class PlaygroundRun(db.Model):
    __tablename__ = "playground_runs"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    component_version_id = db.Column(db.Integer, db.ForeignKey("component_versions.id"), nullable=False)
    component_profile_id = db.Column(db.Integer, db.ForeignKey("component_profiles.id"), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"))
    initiated_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    status = db.Column(
        db.Enum(PipelineRunStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=PipelineRunStatus.PENDING,
    )
    request_json = db.Column(db.Text, nullable=False, default="{}")
    result_json = db.Column(db.Text)
    logs_json = db.Column(db.Text)
    error_message = db.Column(db.Text)
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime)

# Imported after native models so metadata includes Link foreign-key targets.
from database.webhdp_link_models import (  # noqa: E402,F401
    LinkClient, LinkPublication, LinkCode, LinkToken, LinkUpload, LinkRun, LinkArtifact,
)
