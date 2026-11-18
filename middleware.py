"""Flask middleware for request processing and error handling"""

import time
import logging
import os
import shutil
from flask import request, g
from functools import wraps
from exceptions import AppException
from api_utils import generate_request_id, error_response
from services.api_activity_service import record_api_activity
from services.maintenance_service import maintenance_status

logger = logging.getLogger(__name__)


MAINTENANCE_ALLOWED_PATHS = {
    "/api/v1/health",
    "/api/v1/readiness",
}

PASSWORD_CHANGE_ALLOWED_PATHS = {
    "/api/v1/auth/me",
    "/api/v1/auth/me/password",
    "/api/v1/auth/logout",
}


def _upload_disk_roots(app) -> list[str]:
    roots = [
        os.environ.get("SHARED_SESSION_PATH"),
        app.config.get("LOCAL_INPUT_PATH"),
        app.config.get("LOCAL_OUTPUT_PATH"),
    ]
    return [str(root) for root in roots if root]


def _ensure_upload_capacity(app):
    if request.path.startswith("/api/v1/link/") or request.path == "/api/v1/model-publication/jobs":
        return None  # Link streams and enforces its own per-client upload/storage quotas.
    content_length = request.content_length
    if request.method not in {"POST", "PUT", "PATCH"} or not content_length:
        return None

    max_size = int(app.config.get("MAX_CONTENT_LENGTH") or 0)
    if max_size and content_length > max_size:
        return error_response(
            "FILE_TOO_LARGE",
            "Uploaded content exceeds maximum allowed size",
            413,
            {"max_size_mb": max_size / (1024 * 1024)},
            g.get("request_id"),
        )

    min_free_bytes = int(app.config.get("MIN_UPLOAD_FREE_BYTES") or 0)
    multiplier = float(app.config.get("MIN_UPLOAD_FREE_MULTIPLIER") or 1)
    required_free = max(min_free_bytes, int(content_length * multiplier))
    if required_free <= 0:
        return None

    checked_devices = set()
    for root in _upload_disk_roots(app):
        os.makedirs(root, exist_ok=True)
        usage = shutil.disk_usage(root)
        device_key = (usage.total, root)
        if device_key in checked_devices:
            continue
        checked_devices.add(device_key)
        if usage.free < required_free:
            return error_response(
                "INSUFFICIENT_STORAGE",
                "Not enough free disk space for this upload",
                507,
                {
                    "path": root,
                    "free_bytes": usage.free,
                    "required_free_bytes": required_free,
                    "content_length": content_length,
                },
                g.get("request_id"),
            )
    return None


def _enforce_required_password_change():
    if request.method == "OPTIONS":
        return None
    if not request.path.startswith("/api/"):
        return None
    if request.path in PASSWORD_CHANGE_ALLOWED_PATHS:
        return None
    auth_header = request.headers.get("Authorization", "")
    if request.path.startswith("/api/v1/link/") and auth_header.startswith("Bearer whl_"):
        return None  # Link checks account state and token-version revocation itself.
    if not auth_header.startswith("Bearer "):
        return None

    try:
        from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
        from flask_jwt_extended.exceptions import JWTExtendedException
        from database.database import db
        from database.models import User

        verify_jwt_in_request(optional=True)
    except JWTExtendedException:
        return None

    user_id = get_jwt_identity()
    if not user_id:
        return None
    user = db.session.get(User, int(user_id))

    if user and user.force_password_change:
        return error_response(
            "PASSWORD_CHANGE_REQUIRED",
            "Password change required before continuing.",
            403,
            {"action": "change_password"},
            g.get("request_id"),
        )
    return None


def setup_error_handlers(app):
    """Register error handlers for the Flask app"""

    @app.before_request
    def before_request():
        """Execute before each request"""
        # Generate request ID for tracing
        g.request_id = generate_request_id()
        g.start_time = time.time()

        # Log request
        logger.info(
            f"Request started - ID: {g.request_id} | "
            f"Method: {request.method} | "
            f"Path: {request.path} | "
            f"IP: {request.remote_addr}"
        )
        status = maintenance_status()
        if status["enabled"] and request.path not in MAINTENANCE_ALLOWED_PATHS:
            return error_response(
                "MAINTENANCE_MODE",
                "The service is temporarily unavailable for maintenance.",
                503,
                {"reason": status.get("reason"), "enabled_at": status.get("enabled_at")},
                g.request_id,
            )

        capacity_response = _ensure_upload_capacity(app)
        if capacity_response is not None:
            return capacity_response

        password_change_response = _enforce_required_password_change()
        if password_change_response is not None:
            return password_change_response

    @app.after_request
    def after_request(response):
        """Execute after each request"""
        # Calculate request duration
        if hasattr(g, "start_time"):
            duration = time.time() - g.start_time
            logger.info(
                f"Request completed - ID: {g.request_id} | "
                f"Status: {response.status_code} | "
                f"Duration: {duration:.3f}s"
            )
            if request.path.startswith("/api/"):
                record_api_activity(
                    {
                        "method": request.method,
                        "path": request.path,
                        "status_code": response.status_code,
                        "duration_ms": int(duration * 1000),
                        "request_id": g.get("request_id"),
                    }
                )
        if os.environ.get("SECURITY_HEADERS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}:
            if request.path.startswith("/embed/records/"):
                frame_ancestors = os.environ.get("OEMBED_FRAME_ANCESTORS", "'self'").strip() or "'self'"
                csp = (
                    "default-src 'self'; "
                    "base-uri 'self'; "
                    "object-src 'none'; "
                    f"frame-ancestors {frame_ancestors}; "
                    "img-src 'self' data: blob: https://zenodo.org https://sandbox.zenodo.org; "
                    "style-src 'self' 'unsafe-inline'; "
                    "script-src 'self'; "
                    "connect-src 'self' https://zenodo.org https://sandbox.zenodo.org; "
                    "form-action 'self'"
                )
            else:
                csp = os.environ.get(
                    "CONTENT_SECURITY_POLICY",
                    "default-src 'self'; "
                    "base-uri 'self'; "
                    "object-src 'none'; "
                    "frame-ancestors 'none'; "
                    "img-src 'self' data: blob:; "
                    "style-src 'self' 'unsafe-inline'; "
                    "script-src 'self'; "
                    "connect-src 'self'; "
                    "form-action 'self'",
                )
            response.headers.setdefault("Content-Security-Policy", csp)
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
            response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        return response

    @app.errorhandler(AppException)
    def handle_app_exception(error):
        """Handle custom application exceptions"""
        logger.error(
            f"Application error - ID: {g.get('request_id', 'N/A')} | "
            f"Error: {error.error_code} | "
            f"Message: {error.message} | "
            f"Details: {error.details}"
        )
        return error_response(error.error_code, error.message, error.status_code, error.details, g.get("request_id"))

    @app.errorhandler(ValueError)
    def handle_value_error(error):
        """Handle ValueError (typically from validation)"""
        logger.warning(f"Validation error - ID: {g.get('request_id', 'N/A')} | " f"Error: {str(error)}")
        return error_response("VALIDATION_ERROR", str(error), 400, request_id=g.get("request_id"))

    @app.errorhandler(404)
    def handle_not_found(error):
        """Handle 404 Not Found errors"""
        logger.warning(f"Not found - ID: {g.get('request_id', 'N/A')} | " f"Path: {request.path}")
        return error_response("NOT_FOUND", f"Endpoint {request.path} not found", 404, request_id=g.get("request_id"))

    @app.errorhandler(405)
    def handle_method_not_allowed(error):
        """Handle 405 Method Not Allowed errors"""
        logger.warning(
            f"Method not allowed - ID: {g.get('request_id', 'N/A')} | "
            f"Method: {request.method} | Path: {request.path}"
        )
        return error_response(
            "METHOD_NOT_ALLOWED",
            f"Method {request.method} not allowed for {request.path}",
            405,
            request_id=g.get("request_id"),
        )

    @app.errorhandler(413)
    def handle_request_entity_too_large(error):
        """Handle 413 Request Entity Too Large"""
        logger.warning(
            f"Request too large - ID: {g.get('request_id', 'N/A')} | " f"Content-Length: {request.content_length}"
        )
        return error_response(
            "FILE_TOO_LARGE",
            "Uploaded file exceeds maximum allowed size",
            413,
            {"max_size_mb": app.config["MAX_CONTENT_LENGTH"] / (1024 * 1024)},
            g.get("request_id"),
        )

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        """Handle unexpected errors"""
        logger.error(f"Unexpected error - ID: {g.get('request_id', 'N/A')} | " f"Error: {str(error)}", exc_info=True)

        # Don't expose internal error details in production
        if app.config.get("DEBUG"):
            details = {"error": str(error), "type": type(error).__name__}
        else:
            details = {}

        return error_response(
            "INTERNAL_ERROR",
            "An unexpected error occurred. Please try again later.",
            500,
            details,
            g.get("request_id"),
        )


def require_session(f):
    """Decorator to require active session"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        from flask import session
        from exceptions import SessionError

        if "hdpc_path" not in session:
            raise SessionError(
                "No active session found. Please upload files first.",
                details={"session_id": session.get("_id", "none")},
            )
        return f(*args, **kwargs)

    return decorated_function


def validate_content_type(expected_types: list):
    """
    Decorator to validate Content-Type header.

    Args:
        expected_types: List of allowed content types (e.g., ['application/json'])
    """
    from functools import wraps
    from flask import request
    from exceptions import ValidationError

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            content_type = request.content_type

            # Check if content type matches expected
            if not content_type or not any(ct in content_type for ct in expected_types):
                raise ValidationError(
                    f"Invalid Content-Type", details={"expected": expected_types, "received": content_type}
                )

            return f(*args, **kwargs)

        return decorated_function

    return decorator
