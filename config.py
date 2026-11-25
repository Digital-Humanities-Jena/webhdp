from dotenv import load_dotenv
import os
import secrets
from pathlib import Path
import logging
from datetime import timedelta

load_dotenv()


PLACEHOLDER_SECRET_VALUES = {
    "",
    "change-me",
    "change-me-admin-password",
    "change-this-in-production",
    "dev-secret-key-replace-in-prod",
    "dev-secret-key-change-in-production",
    "your-secret-key-here",
    "your-smtp-password",
}


def _env_value(name, default=""):
    return str(os.environ.get(name, default) or "").strip()


def _is_placeholder(value):
    return str(value or "").strip().lower() in PLACEHOLDER_SECRET_VALUES


def _production_enabled():
    return _env_value("FLASK_ENV").lower() == "production"


def validate_production_environment():
    if not _production_enabled():
        return

    missing = []
    for name in ("SECRET_KEY", "CREDENTIAL_ENCRYPTION_KEY"):
        if _is_placeholder(_env_value(name)):
            missing.append(name)

    setup_token = _env_value("SETUP_BOOTSTRAP_TOKEN")
    default_admin_email = _env_value("DEFAULT_ADMIN_EMAIL")
    default_admin_password = _env_value("DEFAULT_ADMIN_PASSWORD")
    has_setup_token = not _is_placeholder(setup_token)
    has_default_admin = bool(default_admin_email) and not _is_placeholder(default_admin_password)
    if not has_setup_token and not has_default_admin:
        missing.append("SETUP_BOOTSTRAP_TOKEN or DEFAULT_ADMIN_EMAIL/DEFAULT_ADMIN_PASSWORD")

    if missing:
        raise ValueError(
            "Production configuration is missing required non-placeholder values: "
            + ", ".join(missing)
        )
    if len(_env_value("SECRET_KEY").encode("utf-8")) < 32:
        raise ValueError("SECRET_KEY must contain at least 32 bytes for production JWT signing")


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class Config:
    """Base configuration with security-first defaults"""

    # Generate or validate secret key
    SECRET_KEY = os.environ.get("SECRET_KEY")
    if not SECRET_KEY or _is_placeholder(SECRET_KEY):
        if _production_enabled():
            raise ValueError(
                "SECRET_KEY must be set in production. "
                "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
            )
        # Generate a random key for development
        SECRET_KEY = secrets.token_hex(32)
        print(f"WARNING: Using auto-generated SECRET_KEY. Set SECRET_KEY environment variable in production.")

    # Default admin credentials
    DEFAULT_ADMIN_EMAIL = os.environ.get("DEFAULT_ADMIN_EMAIL")
    DEFAULT_ADMIN_PASSWORD = os.environ.get("DEFAULT_ADMIN_PASSWORD")

    # Session configuration with security
    SESSION_TYPE = "filesystem"
    SESSION_COOKIE_SECURE = True  # HTTPS only
    SESSION_COOKIE_HTTPONLY = True  # Prevent JavaScript access
    SESSION_COOKIE_SAMESITE = "Strict"  # CSRF protection
    PERMANENT_SESSION_LIFETIME = 1800  # 30 minutes in seconds

    # File upload security
    MAX_CONTENT_LENGTH = _env_int("MAX_CONTENT_LENGTH", _env_int("WEBHDP_MAX_UPLOAD_BYTES", 50 * 1024 * 1024 * 1024))
    ACCOUNT_UPLOAD_STORAGE_BYTES = _env_int("ACCOUNT_UPLOAD_STORAGE_BYTES", 50 * 1024**3)
    ACCOUNT_UPLOAD_MAX_ACTIVE = _env_int("ACCOUNT_UPLOAD_MAX_ACTIVE", 3)
    ACCOUNT_UPLOAD_STREAM_DAILY_BYTES = _env_int("ACCOUNT_UPLOAD_STREAM_DAILY_BYTES", 50 * 1024**3)
    MIN_UPLOAD_FREE_BYTES = _env_int("MIN_UPLOAD_FREE_BYTES", 5 * 1024 * 1024 * 1024)
    MIN_UPLOAD_FREE_MULTIPLIER = _env_float("MIN_UPLOAD_FREE_MULTIPLIER", 1.5)
    ALLOWED_EXTENSIONS = {".obj", ".mtl", ".jpg", ".jpeg", ".png", ".xml", ".txt"}
    ALLOWED_UPLOAD_DIRECTORIES = []  # Whitelist of allowed directories (empty = use validation function)

    # Artifact cleanup is intentionally separate from browser/JWT session expiry.
    # Production defaults preserve session artifacts until an operator enables
    # cleanup with an explicit retention window.
    SESSION_ARTIFACT_CLEANUP_ENABLED = os.environ.get(
        "SESSION_ARTIFACT_CLEANUP_ENABLED",
        "false",
    ).lower() in ["true", "on", "1", "yes"]
    SESSION_ARTIFACT_RETENTION_SECONDS = _env_int(
        "SESSION_ARTIFACT_RETENTION_SECONDS",
        _env_int("SESSION_ARTIFACT_RETENTION_DAYS", 30) * 24 * 60 * 60,
    )
    SESSION_CLEANUP_INTERVAL_SECONDS = _env_int("SESSION_CLEANUP_INTERVAL_SECONDS", 300)

    API_TIMEOUT = 60

    # Zenodo Configuration
    ZENODO_SANDBOX_MODE = os.environ.get("ZENODO_SANDBOX_MODE", "false").lower() in ["true", "on", "1"]

    # Storage Mode
    STORAGE_MODE = os.environ.get("STORAGE_MODE", "pure_cloud")
    LOCAL_INPUT_PATH = os.environ.get("LOCAL_INPUT_PATH", "/data/local_input")
    LOCAL_OUTPUT_PATH = os.environ.get("LOCAL_OUTPUT_PATH", "/data/local_output")

    # Local EDM Validator Configuration. METIS_* names are retained as
    # backwards-compatible aliases because the local validator exposes the same
    # /record/validation contract.
    LOCAL_EDM_VALIDATOR_URL = os.environ.get(
        "LOCAL_EDM_VALIDATOR_URL",
        os.environ.get("METIS_SANDBOX_URL", "http://localhost:18080"),
    )
    METIS_SANDBOX_URL = os.environ.get("METIS_SANDBOX_URL", LOCAL_EDM_VALIDATOR_URL)
    METIS_SANDBOX_API_URL = os.environ.get("METIS_SANDBOX_API_URL", METIS_SANDBOX_URL)
    ENABLE_LOCAL_EDM_VALIDATION = os.environ.get(
        "ENABLE_LOCAL_EDM_VALIDATION",
        os.environ.get("ENABLE_METIS_VALIDATION", "true"),
    ).lower() in ["true", "on", "1"]
    ENABLE_METIS_VALIDATION = ENABLE_LOCAL_EDM_VALIDATION
    LOCAL_EDM_VALIDATOR_REQUIRED = os.environ.get(
        "LOCAL_EDM_VALIDATOR_REQUIRED",
        "true",
    ).lower() in ["true", "on", "1"]
    LOCAL_EDM_VALIDATOR_CONTINUE_ON_ERROR = os.environ.get(
        "LOCAL_EDM_VALIDATOR_CONTINUE_ON_ERROR",
        "true",
    ).lower() in ["true", "on", "1"]
    LOCAL_EDM_VALIDATOR_EXPECTED_EDM_SCHEMA_VERSION = _env_value("LOCAL_EDM_VALIDATOR_EXPECTED_EDM_SCHEMA_VERSION")
    LOCAL_EDM_VALIDATOR_EXPECTED_METIS_SCHEMA_VERSION = _env_value("LOCAL_EDM_VALIDATOR_EXPECTED_METIS_SCHEMA_VERSION")
    LOCAL_EDM_VALIDATOR_EXPECTED_SOURCE_REF = _env_value("LOCAL_EDM_VALIDATOR_EXPECTED_SOURCE_REF")
    EMIT_EUROPEANA_3D_ADVISORY_FIELDS = os.environ.get(
        "EMIT_EUROPEANA_3D_ADVISORY_FIELDS",
        "false",
    ).lower() in ["true", "on", "1"]

    # Frontend URL for verification links
    FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost")
    IIIF_PUBLIC_BASE_URL = _env_value("IIIF_PUBLIC_BASE_URL")

    # Mail configuration
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "localhost")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 1025))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "false").lower() in ["true", "on", "1"]
    MAIL_USE_SSL = os.environ.get("MAIL_USE_SSL", "false").lower() in ["true", "on", "1"]
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "noreply@heritage-data.org")
    MAIL_TIMEOUT = _env_int("MAIL_TIMEOUT", 5)

    # Optional email MFA for login
    MFA_DEVELOPMENT_CODE_DELIVERY = os.environ.get("MFA_DEVELOPMENT_CODE_DELIVERY", "")
    MFA_EMAIL_CODE_LENGTH = _env_int("MFA_EMAIL_CODE_LENGTH", 6)
    MFA_EMAIL_CODE_TTL_SECONDS = _env_int("MFA_EMAIL_CODE_TTL_SECONDS", 600)
    MFA_EMAIL_MAX_VERIFY_ATTEMPTS = _env_int("MFA_EMAIL_MAX_VERIFY_ATTEMPTS", 5)
    MFA_EMAIL_RESEND_COOLDOWN_SECONDS = _env_int("MFA_EMAIL_RESEND_COOLDOWN_SECONDS", 60)
    MFA_RECOVERY_CODE_COUNT = _env_int("MFA_RECOVERY_CODE_COUNT", 10)
    MFA_RECOVERY_CODE_LENGTH = _env_int("MFA_RECOVERY_CODE_LENGTH", 12)
    MFA_ADMIN_RECOVERY_CODE_TTL_SECONDS = _env_int("MFA_ADMIN_RECOVERY_CODE_TTL_SECONDS", 24 * 60 * 60)
    MFA_RECOVERY_RATE_LIMIT_ATTEMPTS = _env_int("MFA_RECOVERY_RATE_LIMIT_ATTEMPTS", 5)
    MFA_RECOVERY_RATE_LIMIT_WINDOW_SECONDS = _env_int("MFA_RECOVERY_RATE_LIMIT_WINDOW_SECONDS", 300)
    MFA_RECOVERY_RATE_LIMIT_LOCKOUT_SECONDS = _env_int("MFA_RECOVERY_RATE_LIMIT_LOCKOUT_SECONDS", 900)

    # Notification tuning for low-resource deployments
    NOTIFICATION_POLL_INTERVAL_SECONDS = _env_int("NOTIFICATION_POLL_INTERVAL_SECONDS", 120)
    NOTIFICATION_DROPDOWN_LIMIT = _env_int("NOTIFICATION_DROPDOWN_LIMIT", 10)
    NOTIFICATION_PAGE_LIMIT = _env_int("NOTIFICATION_PAGE_LIMIT", 50)
    NOTIFICATION_DIGEST_MAX_PER_USER = _env_int("NOTIFICATION_DIGEST_MAX_PER_USER", 10)
    NOTIFICATION_DIGEST_USER_BATCH_SIZE = _env_int("NOTIFICATION_DIGEST_USER_BATCH_SIZE", 25)
    NOTIFICATION_DELIVERY_AUDIT_RETENTION_DAYS = _env_int("NOTIFICATION_DELIVERY_AUDIT_RETENTION_DAYS", 90)
    NOTIFICATION_READ_RETENTION_DAYS = _env_int("NOTIFICATION_READ_RETENTION_DAYS", 180)
    NOTIFICATION_ARCHIVED_RETENTION_DAYS = _env_int("NOTIFICATION_ARCHIVED_RETENTION_DAYS", 90)
    NOTIFICATION_SSE_ENABLED = os.environ.get("NOTIFICATION_SSE_ENABLED", "false").lower() in ["true", "on", "1"]

    # Feature Flags (Service toggles)
    ENABLE_RENDERER = os.environ.get("ENABLE_RENDERER", "true").lower() in ["true", "on", "1"]
    ENABLE_USDZ_CONVERSION = os.environ.get("ENABLE_USDZ_CONVERSION", "true").lower() in ["true", "on", "1"]
    WEBHDP_DEPLOYMENT_MODE = os.environ.get("WEBHDP_DEPLOYMENT_MODE", "server").strip().lower()
    WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS = os.environ.get(
        "WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS",
        "false",
    ).lower() in ["true", "on", "1", "yes"]
    WEBHDP_COMPONENT_INDEX_SOURCES = os.environ.get("WEBHDP_COMPONENT_INDEX_SOURCES", "")
    WEBHDP_COMPONENT_INDEX_TIMEOUT_SECONDS = _env_int("WEBHDP_COMPONENT_INDEX_TIMEOUT_SECONDS", 15)
    WEBHDP_COMPONENT_INDEX_CACHE_TTL_SECONDS = _env_int("WEBHDP_COMPONENT_INDEX_CACHE_TTL_SECONDS", 900)
    WEBHDP_COMPONENT_INDEX_MIN_TRUST = os.environ.get("WEBHDP_COMPONENT_INDEX_MIN_TRUST", "unknown")

    # Operational backup configuration. Backups are intentionally independent
    # from user-facing cloud mirror records.
    BACKUP_ENABLED = os.environ.get("BACKUP_ENABLED", "false").lower() in ["true", "on", "1"]
    BACKUP_PROVIDER = os.environ.get("BACKUP_PROVIDER", "local")
    BACKUP_LOCAL_DIR = os.environ.get("BACKUP_LOCAL_DIR", "backups")
    BACKUP_REMOTE_PREFIX = os.environ.get("BACKUP_REMOTE_PREFIX", "/WebHDP/backups")
    BACKUP_INCLUDE_CREDENTIALS = os.environ.get("BACKUP_INCLUDE_CREDENTIALS", "true").lower() in ["true", "on", "1"]
    BACKUP_RETENTION_DAYS = _env_int("BACKUP_RETENTION_DAYS", 30)
    BACKUP_MAX_AGE_SECONDS = _env_int("BACKUP_MAX_AGE_SECONDS", 26 * 60 * 60)

    # Celery Configuration
    CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
    CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")
    # Modern Celery names
    broker_url = CELERY_BROKER_URL
    result_backend = CELERY_RESULT_BACKEND

    # EDM Schema Paths
    BASE_DIR = Path(__file__).resolve().parent
    EDM_SCHEMA_PATH = os.environ.get("EDM_SCHEMA_PATH", str(BASE_DIR / "schema_xsds" / "EDM.xsd"))
    EDM_SCHEMATRON_PATH = os.environ.get("EDM_SCHEMATRON_PATH", str(BASE_DIR / "schema_xsds" / "schematron" / "schematron.xsl"))

    @staticmethod
    def init_app(app):
        """Initialize application with configuration"""
        pass


class DevelopmentConfig(Config):
    """Development-specific configuration"""

    DEBUG = True
    SESSION_COOKIE_SECURE = False  # Allow HTTP in development


class ProductionConfig(Config):
    """Production configuration"""

    DEBUG = False
    TESTING = False

    validate_production_environment()

    # Use environment variables for sensitive data
    SECRET_KEY = os.environ.get("SECRET_KEY") or Config.SECRET_KEY
    CREDENTIAL_ENCRYPTION_KEY = os.environ.get("CREDENTIAL_ENCRYPTION_KEY", "")
    SETUP_BOOTSTRAP_TOKEN = os.environ.get("SETUP_BOOTSTRAP_TOKEN")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or "sqlite:////app/instance/hdp_web.db"

    # Security settings
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)

    # CORS settings for production
    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "").split(",")

    # Logging
    LOG_LEVEL = logging.WARNING


config = {"development": DevelopmentConfig, "production": ProductionConfig, "default": DevelopmentConfig}
