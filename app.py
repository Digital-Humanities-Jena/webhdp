# app.py
"""
app.py - Secure Flask application for HDP Web Interface

This module provides a web interface for the HDP (Heritage Data Processor) system
with comprehensive security, error handling, and logging.
"""
import logging
import logging.handlers
import os
import sys
import tempfile
import fcntl
from pathlib import Path
import json

import requests
from dotenv import load_dotenv
from flask import Flask, g, has_request_context, jsonify, request, send_from_directory, session
from flask_cors import CORS
from flask_jwt_extended import JWTManager, get_jwt_identity, jwt_required
from flask_migrate import Migrate
from flask_session import Session
from flask_mail import Mail
from sqlalchemy.exc import OperationalError

from api_utils import APIResponse
from config import config
from database.database import db, init_db
from database.lod_template_bootstrap import ensure_default_lod_templates
from database.models import File as DBFile
from database.models import Session as DBSession, User, UserRole, UserMetadata
from exceptions import (
    APIConnectionError,
    APITimeoutError,
    AppException,
    FileProcessingError,
    ResourceNotFoundError,
    SecurityError,
    SessionError,
    ValidationError,
)
from middleware import require_session, setup_error_handlers, validate_content_type
from routes import register_routes
from schemas import PipelineExecutionSchema
from security import SecurityValidator, sanitize_upload_filename
from services import FileService, NativePipelineSystemService, ProjectService, UserService
from services.fast_renderer_service import FastRendererService
from services.any_to_usdz_service import AnyToUsdzService
from services.edm_service import EdmService
from services.msf_service import MSFService
from services.email_service import EmailService
from services.iiif_service import IiifService
from services.mets_service import MetsService
from services.credential_crypto import validate_encryption_configuration
from services.hpc_allocation_service import HpcAllocationService
from services.component_index_service import ComponentIndexService
from services.hpc_component_installer_service import ComponentInstallerService
from services.zenodo_config_service import ZenodoConfigService
from services.hdpc_provenance_service import build_hdpc_provenance
from database.seed_edm_templates import seed_templates as seed_edm_templates
from database.seed_iiif_templates import seed_iiif_templates
from database.seed_mets_mods_templates import seed_mets_templates
from session_manager import SessionManager
from validation import validate_file_upload, validate_request
from workflow_status import normalize_session_state

load_dotenv()


def _skip_db_bootstrap() -> bool:
    return os.environ.get("SKIP_DB_CREATE_ALL", "").strip().lower() in {"1", "true", "yes", "on"}


# --- Logging Configuration ---
class RequestIdFilter(logging.Filter):
    """Add request_id to all log records"""

    def filter(self, record):
        if has_request_context():
            record.request_id = g.get("request_id", "N/A")
        else:
            record.request_id = "SYSTEM"
        return True


def setup_logging(app):
    """Configure structured logging with proper handlers"""

    # Create formatters
    detailed_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] - " "%(filename)s:%(lineno)d - %(message)s"
    )

    simple_formatter = logging.Formatter("%(asctime)s - %(levelname)s - [%(request_id)s] - %(message)s")

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(simple_formatter)
    console_handler.addFilter(RequestIdFilter())

    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)

    # File handler for errors only
    error_file_handler = logging.handlers.RotatingFileHandler(
        "logs/error.log", maxBytes=10485760, backupCount=10  # 10MB
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(detailed_formatter)
    error_file_handler.addFilter(RequestIdFilter())

    # File handler for all logs
    app_file_handler = logging.handlers.RotatingFileHandler("logs/app.log", maxBytes=10485760, backupCount=10)  # 10MB
    app_file_handler.setLevel(logging.INFO)
    app_file_handler.setFormatter(detailed_formatter)
    app_file_handler.addFilter(RequestIdFilter())

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Remove existing handlers to avoid duplicates
    root_logger.handlers = []

    root_logger.addHandler(console_handler)
    root_logger.addHandler(error_file_handler)
    root_logger.addHandler(app_file_handler)

    # Flask logger
    app.logger.setLevel(logging.INFO)
    app.logger.info("Logging configured successfully")


# --- Application Setup ---
app = Flask(__name__)

env = os.environ.get("FLASK_ENV", "development")
config_name = env if env in config else "default"
app.config.from_object(config[config_name])


def _build_cors_origins() -> list[str]:
    configured = os.environ.get("CORS_ORIGINS", "")
    explicit_origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
    if explicit_origins:
        return explicit_origins

    frontend_url = str(app.config.get("FRONTEND_URL") or "").strip()
    if config_name == "production":
        return [frontend_url] if frontend_url else []

    defaults = {
        "http://localhost",
        "http://localhost:80",
        "http://localhost:8080",
        "http://localhost:4173",
        "http://localhost:5173",
        "http://127.0.0.1",
        "http://127.0.0.1:80",
        "http://127.0.0.1:8080",
        "http://127.0.0.1:4173",
        "http://127.0.0.1:5173",
    }
    if frontend_url:
        defaults.add(frontend_url)
    return sorted(defaults)


CORS(
    app,
    resources={r"/api/*": {"origins": _build_cors_origins()}},
    supports_credentials=True,
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-Requested-With",
        "X-Setup-Token",
        "X-Bootstrap-Token",
    ],
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    expose_headers=["Content-Type", "Authorization"],
)

# Configure Flask-Session with secure settings
app.config["SESSION_FILE_DIR"] = tempfile.mkdtemp(prefix="hdp_flask_session_")
os.chmod(app.config["SESSION_FILE_DIR"], 0o700)  # Secure permissions
Session(app)

# Initialize JWT
app.config["JWT_SECRET_KEY"] = app.config.get("SECRET_KEY", "dev-secret-key-change-in-production")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = 86400  # 24 hours
app.config["JWT_TOKEN_LOCATION"] = ["headers"]
jwt = JWTManager(app)


# JWT Error Handlers
@jwt.expired_token_loader
def expired_token_callback(jwt_header, jwt_payload):
    return APIResponse.unauthorized("Token has expired")


@jwt.invalid_token_loader
def invalid_token_callback(error):
    app.logger.error(f"Invalid JWT token: {error}")
    return APIResponse.validation_error(f"Invalid token: {str(error)}")


@jwt.unauthorized_loader
def missing_token_callback(error):
    return APIResponse.unauthorized("Authorization token is missing")


@jwt.token_in_blocklist_loader
def check_if_token_revoked(jwt_header, jwt_payload):
    from database.models import TokenBlocklist
    jti = jwt_payload["jti"]
    token = db.session.query(TokenBlocklist.id).filter_by(jti=jti).scalar()
    if token is not None:
        return True

    identity = jwt_payload.get("sub")
    try:
        user_id = int(identity)
    except (TypeError, ValueError):
        return True

    user = db.session.get(User, user_id)
    if not user:
        return True

    token_version = int(jwt_payload.get("token_version", 0) or 0)
    return token_version != int(user.token_version or 0)


@jwt.revoked_token_loader
def revoked_token_callback(jwt_header, jwt_payload):
    return APIResponse.unauthorized("Token has been revoked")


# Initialize Database
if not app.config.get("SQLALCHEMY_DATABASE_URI"):
    default_db_path = Path(app.instance_path) / "hdp_web.db"
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL") or f"sqlite:///{default_db_path}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
init_db(app)
migrate = Migrate(app, db)


def initialize_database():
    """Serialize metadata creation so concurrent Gunicorn workers do not race."""
    if _skip_db_bootstrap():
        app.logger.info("Skipping db.create_all() bootstrap because SKIP_DB_CREATE_ALL is enabled.")
        return

    lock_path = Path(app.instance_path) / ".db-init.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with app.app_context():
        with open(lock_path, "w", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                db.create_all()
                ensure_default_lod_templates()
            except OperationalError as exc:
                if "already exists" not in str(exc).lower():
                    raise
                app.logger.warning("Ignoring concurrent database initialization race: %s", exc)
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


initialize_database()

# Initialize Mail
mail = Mail(app)


# --- Create Default Admin ---
def create_default_admin(app_instance):
    """
    Check if an admin user exists, and if not, create one
    from the .env configuration.
    """
    with app_instance.app_context():
        admin_email = app_instance.config.get("DEFAULT_ADMIN_EMAIL")
        admin_password = app_instance.config.get("DEFAULT_ADMIN_PASSWORD")

        if not admin_email or not admin_password:
            app_instance.logger.info("DEFAULT_ADMIN_EMAIL or DEFAULT_ADMIN_PASSWORD not set. Skipping admin creation.")
            return

        user_service = UserService()

        # Check if any admin user already exists
        try:
            admin_exists = User.query.filter_by(role=UserRole.ADMIN).first()
            if admin_exists:
                app_instance.logger.info("An admin user already exists. Skipping.")
                return

            app_instance.logger.info(f"No admin user found. Attempting to create default admin: {admin_email}")

            # Check if the user email exists but with a different role
            existing_user = user_service.get_by_email(admin_email)
            if existing_user:
                existing_user.role = UserRole.ADMIN
                db.session.commit()
                app_instance.logger.info(f"Promoted existing user {admin_email} to ADMIN.")
            else:
                # Create a new admin user
                user_service.create_user(email=admin_email, password=admin_password, role=UserRole.ADMIN)
                app_instance.logger.info(f"Successfully created default admin user: {admin_email}")

        except Exception as e:
            # Catch exceptions (like DB not ready on first-ever run)
            app_instance.logger.error(f"Error during default admin creation: {e}")
            db.session.rollback()


def validate_credential_encryption_startup(app_instance):
    with app_instance.app_context():
        report = validate_encryption_configuration()
    if report["status"] == "warning":
        app_instance.logger.warning("Credential encryption configuration warning: %s", json.dumps(report, sort_keys=True))
    return report


# Admin creation and template seeding is now handled in entrypoint.sh via CLI
# to ensure database migrations are complete before running these tasks.
# with app.app_context():
#     create_default_admin(app)
#     seed_edm_templates()

# Register route blueprints
register_routes(app)
from routes.upload_routes import upload_bp
app.register_blueprint(upload_bp, url_prefix="/api/v1/upload")
from routes.iiif_routes import iiif_bp
app.register_blueprint(iiif_bp, url_prefix="/api/v1/iiif")
from routes.mets_routes import mets_bp
app.register_blueprint(mets_bp, url_prefix="/api/v1/mets")

# Setup logging
setup_logging(app)
validate_credential_encryption_startup(app)

# Setup error handlers and middleware
setup_error_handlers(app)

# Initialize utilities
api_client = requests.Session()
security_validator = SecurityValidator()
session_manager = SessionManager(
    session_timeout=app.config["PERMANENT_SESSION_LIFETIME"],
    flask_session_dir=app.config.get("SESSION_FILE_DIR"),
    cleanup_flask_sessions=os.environ.get("ENABLE_FLASK_SESSION_CLEANUP", "false").lower() in ("1", "true", "on"),
    artifact_cleanup_enabled=app.config.get("SESSION_ARTIFACT_CLEANUP_ENABLED", False),
    artifact_retention_seconds=app.config.get("SESSION_ARTIFACT_RETENTION_SECONDS"),
    cleanup_interval=app.config.get("SESSION_CLEANUP_INTERVAL_SECONDS", 300),
)

app.logger.info(f"Application started in {env} mode")

# Import shared constants
from constants import PREDEFINED_PIPELINE_ID, PIPELINE_DEFINITION, SHARED_SCAN_OPTIONS

SINGLE_FILE_ALLOWED_EXTENSIONS = {
    ".obj",
    ".mtl",
    ".glb",
    ".gltf",
    ".bin",
    ".ply",
    ".stl",
    ".fbx",
    ".dae",
    ".usdz",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tif",
    ".tiff",
    ".xml",
    ".txt",
}

# Initialize Services
project_service = ProjectService()
user_service = UserService()
file_service = FileService(security_validator, app.config["ALLOWED_EXTENSIONS"])
fast_renderer_service = FastRendererService()
any_to_usdz_service = AnyToUsdzService(os.environ.get("ANY_TO_USDZ_URL", "http://any-to-usdz:5003"))
edm_service = EdmService()
msf_service = MSFService()
email_service = EmailService(mail)
iiif_service = IiifService()
mets_service = MetsService()
native_pipeline_service = NativePipelineSystemService()
hpc_allocation_service = HpcAllocationService()
component_installer_service = ComponentInstallerService()
component_index_service = ComponentIndexService()
hpc_component_installer_service = component_installer_service

# Attach services to app for easy access in routes
app.project_service = project_service
app.user_service = user_service
app.file_service = file_service
app.fast_renderer_service = fast_renderer_service
app.any_to_usdz_service = any_to_usdz_service
app.edm_service = edm_service
app.msf_service = msf_service
app.email_service = email_service
app.iiif_service = iiif_service
app.mets_service = mets_service
app.session_manager = session_manager
app.native_pipeline_service = native_pipeline_service
app.hpc_allocation_service = hpc_allocation_service
app.component_installer_service = component_installer_service
app.component_index_service = component_index_service
app.hpc_component_installer_service = hpc_component_installer_service

if not _skip_db_bootstrap():
    with app.app_context():
        app.native_pipeline_service.ensure_seeded()


# --- Static File Serving ---
APP_ROOT = os.path.dirname(os.path.abspath(__file__))


@app.route("/")
def serve_index():
    """Serve the main HTML page"""
    app.logger.info("Serving index.html")
    return send_from_directory(APP_ROOT, "index.html")


@app.route("/app.js")
def serve_app_js():
    """Serve the JavaScript application file"""
    app.logger.info("Serving app.js")
    return send_from_directory(APP_ROOT, "app.js")


@app.route("/styles.css")
def serve_styles_css():
    """Serve the CSS stylesheet"""
    app.logger.info("Serving styles.css")
    return send_from_directory(APP_ROOT, "styles.css")


# --- Internal Helper Functions ---
def _create_session_dirs(
    *,
    institution_id=None,
    sharing_scope=None,
    credential_preference=None,
    publishing_user_id=None,
    default_zenodo_environment=None,
    use_institution_default_communities=None,
):
    """
    Creates temporary directories for a user session and saves to database.
    Returns:
        tuple: (hdpc_path, data_out_path, uploads_path, db_session_id)
    """
    from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

    from database.database import db
    from database.models import Session as DBSession

    # Verify JWT in request
    try:
        verify_jwt_in_request()
        user_id_str = get_jwt_identity()
        user_id = int(user_id_str)  # Convert back to integer
    except Exception as e:
        app.logger.error(f"JWT verification failed: {e}")
        raise SecurityError("Authentication required")

    hdpc_path, data_out_path, uploads_path, session_dir = session_manager.create_session_dirs()

    # Create database session record
    db_session = DBSession(
        user_id=user_id,
        institution_id=institution_id,
        session_dir=session_dir,
        hdpc_path=hdpc_path,
        status="queued",
        sharing_scope=sharing_scope or ("institution" if institution_id else "private"),
        credential_preference=credential_preference or ("institution" if institution_id else "user"),
        publishing_user_id=publishing_user_id or user_id,
        default_zenodo_environment=default_zenodo_environment or "sandbox",
        use_institution_default_communities=bool(use_institution_default_communities) if institution_id else False,
        origin_type="workflow",
        access_mode="full",
    )
    db.session.add(db_session)
    from services.single_upload_recovery import persist_single_upload_identity
    persist_single_upload_identity(db_session)
    db.session.commit()

    # Store in Flask session
    session["hdpc_path"] = hdpc_path
    session["session_dir"] = session_dir
    session["data_out_path"] = data_out_path
    session["uploads_path"] = uploads_path
    session["db_session_id"] = db_session.id
    session.permanent = True

    app.logger.info(f"Session directories created at {session_dir}, DB session ID: {db_session.id}")
    return hdpc_path, data_out_path, uploads_path


# --- API Endpoints ---
@app.route("/api/v1/health", methods=["GET"])
def health_check():
    """Health check endpoint for monitoring and configuration exposure"""
    return APIResponse.success(
        data={
            "status": "healthy",
            "environment": env,
            "config": {
                "enable_local_edm_validation": app.config.get("ENABLE_LOCAL_EDM_VALIDATION", True),
                "local_edm_validator_url": app.config.get("LOCAL_EDM_VALIDATOR_URL"),
                "enable_metis_validation": app.config.get("ENABLE_METIS_VALIDATION", True),
                "enable_xsd_validation": True,
                "enable_schematron_validation": False,  # Hardcoded as disabled in EdmService
                "enable_renderer": app.config.get("ENABLE_RENDERER", True),
                "enable_usdz_conversion": app.config.get("ENABLE_USDZ_CONVERSION", True),
            }
        },
        message="Service is running"
    )


@app.route("/api/v1/readiness", methods=["GET"])
def readiness_check():
    """Readiness check for deployment/update automation."""
    from services.readiness_service import build_readiness_report

    report = build_readiness_report(app)
    status_code = 200 if report["ready"] else 503
    return jsonify({"success": report["ready"], "data": report}), status_code


from services.single_upload_recovery import single_upload_request


@app.route("/api/v1/sessions/file", methods=["POST"])
@jwt_required()
@single_upload_request(SINGLE_FILE_ALLOWED_EXTENSIONS)
def api_start_session_file():
    """
    API endpoint for file upload (Vue frontend compatible)
    """
    from pathlib import Path

    from database.database import db
    from database.models import File as DBFile
    from database.models import Session as DBSession, User
    from routes.session_routes import _normalize_session_workspace_options
    from routes.access_helpers import get_current_user_from_jwt

    app.logger.info("Handling single file upload request via API.")

    db_session_id = None
    try:
        if "file" not in request.files:
            app.logger.error("No file in request.files")
            return APIResponse.error("No file provided", 422)

        file = request.files["file"]

        if not file or file.filename == "":
            app.logger.error("Empty filename")
            return APIResponse.error("No file selected", 422)

        # Step 1: Create session directories and get paths
        workspace_payload = {
            key: request.form.get(key)
            for key in (
                "institution_id",
                "sharing_scope",
                "credential_preference",
                "default_zenodo_environment",
                "use_institution_default_communities",
            )
            if request.form.get(key) is not None
        }
        current_user = get_current_user_from_jwt() or db.session.get(User, int(get_jwt_identity()))
        workspace_options = _normalize_session_workspace_options(user=current_user, payload=workspace_payload)
        hdpc_path, data_out_path, uploads_path = _create_session_dirs(
            institution_id=workspace_options["institution_id"],
            sharing_scope=workspace_options["sharing_scope"],
            credential_preference=workspace_options["credential_preference"],
            publishing_user_id=workspace_options["publishing_user_id"],
            default_zenodo_environment=workspace_options["default_zenodo_environment"],
            use_institution_default_communities=workspace_options["use_institution_default_communities"],
        )
        db_session_id = session.get("db_session_id")  # <-- Get session ID
        if not db_session_id:
            app.logger.error("Failed to create a database session ID.")
            return APIResponse.error("SESSION_CREATION_FAILED", "Could not create session", 500)

        # Step 2: Save the uploaded file to the session's 'uploads' directory
        safe_filename = sanitize_upload_filename(file.filename, allowed_extensions=SINGLE_FILE_ALLOWED_EXTENSIONS)
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        security_validator.validate_file_size(file_size, app.config["MAX_CONTENT_LENGTH"])
        saved_file_path = os.path.join(uploads_path, safe_filename)
        file.save(saved_file_path)
        app.logger.info(f"File saved to: {saved_file_path}")

        # Step 3: Save file metadata to our web app's database
        db_file = DBFile(
            session_id=db_session_id,
            filename=safe_filename,
            path=saved_file_path,
            size=os.path.getsize(saved_file_path),
            status="uploaded",
        )
        db.session.add(db_file)
        db.session.commit()

        try:
            from constants import UPLOAD_STORAGE_MODE_FIELD
            from services.cloud_mirror_service import ARTIFACT_SINGLE_FILE, mirror_local_artifact
            from services.cloud_upload_service import CloudUploadService

            storage_mode = CloudUploadService.get_storage_mode()
            db.session.add(
                UserMetadata(
                    session_id=db_session_id,
                    field_name=UPLOAD_STORAGE_MODE_FIELD,
                    field_value=str(storage_mode),
                )
            )
            mirror_local_artifact(
                session_id=db_session_id,
                local_path=saved_file_path,
                original_filename=safe_filename,
                artifact_kind=ARTIFACT_SINGLE_FILE,
                file_id=db_file.id,
                storage_mode=storage_mode,
            )
            db.session.commit()
        except Exception as mirror_exc:
            db.session.rollback()
            app.logger.warning("Failed to persist Cloud Storage mirror metadata for session %s: %s", db_session_id, mirror_exc)

        # Get the file extension (e.g., '.glb')
        file_ext = Path(safe_filename).suffix.lower()
        if not file_ext:
            app.logger.error(f"File '{safe_filename}' has no extension, cannot determine scan options.")
            raise FileProcessingError("File has no extension, cannot determine scan options.")

        # Create a mutable set of extensions from the config
        extensions_set = set(app.config["ALLOWED_EXTENSIONS"])

        # Add the uploaded file's extension to the set
        extensions_set.add(file_ext)

        # Convert back to list for JSON serialization
        final_extensions_list = list(extensions_set)

        # Create scan options specifically for this single file
        single_file_scan_options = {
            "extensions": final_extensions_list,  # <-- Use the new list
            "primarysourceext": file_ext,  # Treat this file's extension as the primary
            "bundling": {"enabled": False},  # Disable bundling
            "obj_options": {"add_mtl": False, "add_textures": False, "archive_subdirectories": False},
        }

        app.logger.info(f"Using single-file scan options with primary extension: {file_ext}")
        app.logger.info(f"Full extension list for scanner: {final_extensions_list}")

        # Step 4: Call create_and_scan on the 'uploads_path'
        db_session = db.session.get(DBSession, db_session_id)
        scan_data = project_service.create_and_scan(
            hdpc_path=hdpc_path,
            data_in_path=uploads_path,  # Use the uploads directory as the input
            data_out_path=data_out_path,
            project_name="HDP Web Session (File)",
            scan_options=single_file_scan_options,  # Use the new options
            provenance=build_hdpc_provenance(
                user=current_user,
                session=db_session,
                institution=workspace_options.get("institution"),
            ),
        )
        app.logger.info(f"Scan completed. Found {scan_data.get('filesAdded', 0)} files.")

        # Step 5: The local scan/bootstrap path now writes the .hdpc directly.
        app.logger.info(f"Prepared local project context at {hdpc_path} for file session.")

        # --- Update session status to "active" on success ---
        try:
            if db_session:
                db_session.status = "scanned"
                from flask import g
                if getattr(g, 'single_upload_identity', None):
                    from services.single_upload_recovery import RESULT_FIELD
                    db.session.add(UserMetadata(session_id=db_session_id, field_name=RESULT_FIELD,
                        field_value=json.dumps({'foundFiles': scan_data.get('foundFiles', []), 'session_id': db_session_id, 'file_id': db_file.id})))
                db.session.commit()
        except Exception as e_inner:
            app.logger.error(f"Failed to update session {db_session_id} status to scanned: {e_inner}")
            # Don't fail the whole request, but log it

        # Step 6: Return the *actual* file list from the scan
        return APIResponse.success(
            data={
                "foundFiles": scan_data.get("foundFiles", []),  # Return real scan data
                "session_id": db_session_id,
                "file_id": db_file.id,
            },
            message="File uploaded and scanned successfully",
        )

    except Exception as e:
        app.logger.error(f"File upload error: {e}", exc_info=True)

        # --- Update session status to "failed" on error ---
        if db_session_id:
            try:
                db_session = db.session.get(DBSession, db_session_id)
                if db_session:
                    db_session.status = "failed"
                    db.session.commit()
                    app.logger.info(f"Set session {db_session_id} status to 'failed'")
            except Exception as e_inner:
                app.logger.error(f"Failed to update session {db_session_id} status to failed: {e_inner}")

        # Re-raise user-facing exceptions to let global handler process them
        if isinstance(e, AppException):
            raise e

        # Wrap unexpected exceptions in AppException or just raise to let generic 500 handler catch it
        raise e




@app.route("/start-session-file", methods=["POST"])
@jwt_required()
@validate_file_upload(required=True, field_name="file")
def start_session_file():
    """
    Start a session by uploading a single file.
    File upload is automatically validated.
    """

    app.logger.info("Handling single file upload request.")

    file = g.uploaded_file
    hdpc_path, data_out_path, uploads_path = _create_session_dirs()
    db_session_id = session.get("db_session_id")

    # Use file service to validate and save
    safe_filename, saved_file_path = file_service.validate_and_save_upload(
        file=file, upload_path=uploads_path, max_file_size=app.config["MAX_CONTENT_LENGTH"]
    )

    # Save file to database
    db_file = DBFile(
        session_id=db_session_id,
        filename=safe_filename,
        path=saved_file_path,
        size=os.path.getsize(saved_file_path),
        status="uploaded",
    )
    db.session.add(db_file)
    db.session.commit()

    # Use project service to scan
    current_user = db.session.get(User, int(get_jwt_identity()))
    db_session = db.session.get(DBSession, db_session_id)
    scan_data = project_service.create_and_scan(
        hdpc_path=hdpc_path,
        data_in_path=uploads_path,
        data_out_path=data_out_path,
        project_name="HDP Web Session (File)",
        scan_options=SHARED_SCAN_OPTIONS,
        provenance=build_hdpc_provenance(user=current_user, session=db_session),
    )

    return APIResponse.success(
        data={"foundFiles": scan_data.get("foundFiles", []), "session_id": db_session_id, "file_id": db_file.id},
        message="File uploaded and scanned successfully",
    )


@app.route("/api/v1/start-pipeline", methods=["POST"])
@jwt_required()
@require_session
@validate_request(PipelineExecutionSchema)
def start_pipeline():
    """
    Compatibility entrypoint for starting the predefined native pipeline on session files.
    """
    from database.models import Submission
    from services.submission_pipeline_service import execute_submission_pipeline

    app.logger.info("Pipeline execution requested for %s", PREDEFINED_PIPELINE_ID)
    db_session_id = session.get("db_session_id")
    db_session = db.session.get(DBSession, db_session_id) if db_session_id else None
    if not db_session:
        raise FileProcessingError("Session not found in database")
    if not db_session.hdpc_path:
        raise FileProcessingError("Session has no .hdpc file path")

    validated_data = g.validated_data
    local_file_paths = list(validated_data.local_file_paths or [])
    if not local_file_paths:
        raise FileProcessingError("No files specified for processing")

    db_session.status = normalize_session_state("submitting")

    submission = Submission(session_id=db_session_id, pipeline_id=PREDEFINED_PIPELINE_ID, status="processing")
    db.session.add(submission)
    submission.result = json.dumps(
        {
            "status": "processing",
            "progress": {
                "current_stage": "queued",
                "status_message": "Pipeline job queued",
                "current_index": 0,
                "total_files": len(local_file_paths),
                "processed_count": 0,
                "failed_count": 0,
                "abort_on_critical_error": False,
            },
        }
    )
    db.session.commit()

    try:
        execution_output = execute_submission_pipeline(
            identifier=PREDEFINED_PIPELINE_ID,
            local_file_paths=local_file_paths,
            db_session_id=db_session_id,
            is_sandbox=True,
        )
        result_success = bool(execution_output.get("result", {}).get("success", True))
        submission.status = "completed" if result_success else "failed"
        submission.result = json.dumps(execution_output["result"])
        submission.timings = json.dumps(execution_output["timings"])
        submission.completed_at = datetime.utcnow()
        db_session.status = "completed" if result_success else "failed"
        db_session.timings = json.dumps(execution_output["timings"])
        db.session.commit()

        response_data = {
            "processed_count": int((execution_output.get("progress_summary") or {}).get("processed_count", 0) or 0),
            "execution_result": execution_output["result"],
            "submission_id": submission.id,
        }
        skipped_files = execution_output["result"].get("skipped_files") if isinstance(execution_output.get("result"), dict) else None
        if skipped_files:
            response_data["skipped_files"] = skipped_files
            response_data["skipped_count"] = len(skipped_files)

        return APIResponse.success(data=response_data, message="Pipeline executed successfully")

    except Exception as exc:
        submission_to_update = db.session.get(Submission, submission.id)
        if submission_to_update:
            submission_to_update.status = "failed"
            submission_to_update.result = json.dumps(
                {"status": "failed", "error": str(exc), "progress": {"current_stage": "failed"}}
            )
            submission_to_update.completed_at = datetime.utcnow()
        db_session_to_update = db.session.get(DBSession, db_session_id)
        if db_session_to_update:
            db_session_to_update.status = "failed"
        db.session.commit()
        raise





@app.cli.command("init-data")
def init_data():
    """Seed initial data like admin user and EDM templates."""
    create_default_admin(app)
    seed_edm_templates()
    seed_iiif_templates()
    seed_mets_templates()
    print("Initial data seeded successfully.")


# --- Main Entry Point ---
if __name__ == "__main__":
    # Production warning
    if os.environ.get("FLASK_ENV") == "production":
        app.logger.warning(
            "Running in production mode. Ensure SECRET_KEY is set and using a production WSGI server "
            "(e.g., gunicorn, uwsgi) instead of Flask's development server."
        )

    # Start the application
    app.run(host="0.0.0.0", port=5000, debug=app.config["DEBUG"])
