# routes/cloud_test_routes.py
"""API routes for testing cloud storage connectivity (Admin only)."""

import logging
from flask import Blueprint
from flask_jwt_extended import jwt_required, get_jwt_identity
from database.database import db
from database.models import User
from api_utils import APIResponse
from services.cloud_storage_service import CloudStorageService

logger = logging.getLogger(__name__)

cloud_test_bp = Blueprint("cloud_test", __name__)


def require_admin(func):
    """Decorator to require admin role."""
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        user_id = get_jwt_identity()
        user = db.session.get(User, user_id)

        if not user or user.role.value != 'admin':
            return APIResponse.error(
                message="Admin access required",
                status_code=403
            )
        return func(*args, **kwargs)
    return wrapper


@cloud_test_bp.route("/test/gdrive", methods=["GET"])
@jwt_required()
@require_admin
def test_gdrive_connection():
    """
    Test Google Drive connectivity.

    Returns connection status and folder access details.
    """
    logger.info("🧪 Admin requested Google Drive connectivity test")

    try:
        result = CloudStorageService.test_gdrive_connection()

        if result["success"]:
            return APIResponse.success(
                data=result,
                message="Google Drive connection test successful"
            )
        else:
            return APIResponse.success(
                data=result,
                message="Google Drive connection test failed"
            )

    except Exception as e:
        logger.error(f"Error during Google Drive test: {e}", exc_info=True)
        return APIResponse.error(
            message=f"Test failed with error: {str(e)}",
            status_code=500
        )


@cloud_test_bp.route("/test/dropbox", methods=["GET"])
@jwt_required()
@require_admin
def test_dropbox_connection():
    """
    Test Dropbox connectivity.

    Returns connection status and account details.
    """
    logger.info("🧪 Admin requested Dropbox connectivity test")

    try:
        result = CloudStorageService.test_dropbox_connection()

        if result["success"]:
            return APIResponse.success(
                data=result,
                message="Dropbox connection test successful"
            )
        else:
            return APIResponse.success(
                data=result,
                message="Dropbox connection test failed"
            )

    except Exception as e:
        logger.error(f"Error during Dropbox test: {e}", exc_info=True)
        return APIResponse.error(
            message=f"Test failed with error: {str(e)}",
            status_code=500
        )
