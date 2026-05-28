"""Utilities for standardized API responses"""

from flask import jsonify
import uuid
import logging

logger = logging.getLogger(__name__)


def generate_request_id():
    """Generate unique request ID for tracing"""
    return str(uuid.uuid4())


def success_response(data=None, message=None, status_code=200, metadata=None):
    """
    Create standardized success response.

    Args:
        data: Response data (dict, list, or None)
        message: Optional success message
        status_code: HTTP status code (default 200)
        metadata: Optional metadata (pagination, timestamps, etc.)

    Returns:
        Flask JSON response with standardized format
    """
    response = {"success": True, "data": data or {}, "message": message, "metadata": metadata or {}}

    return jsonify(response), status_code


def error_response(error_code, message, status_code=500, details=None, request_id=None):
    """
    Create standardized error response.

    Args:
        error_code: Application error code (e.g., "VALIDATION_ERROR")
        message: User-friendly error message
        status_code: HTTP status code
        details: Additional error details (dict)
        request_id: Request ID for tracing

    Returns:
        Flask JSON response with standardized format
    """
    response = {"success": False, "error": {"code": error_code, "message": message, "details": details or {}}}

    if request_id:
        response["request_id"] = request_id

    return jsonify(response), status_code


class APIResponse:
    """Wrapper class for creating standardized API responses"""

    @staticmethod
    def success(data=None, message=None, status_code=200):
        """Return success response"""
        return success_response(data, message, status_code)

    @staticmethod
    def accepted(data=None, message="Request accepted for processing"):
        """Return 202 Accepted response"""
        return success_response(data, message, 202)

    @staticmethod
    def created(data=None, message="Resource created successfully"):
        """Return 201 Created response"""
        return success_response(data, message, 201)

    @staticmethod
    def no_content():
        """Return 204 No Content response"""
        return "", 204

    @staticmethod
    def error(error_code, message, status_code=500, details=None):
        """Return error response"""
        return error_response(error_code, message, status_code, details)

    @staticmethod
    def validation_error(message, details=None):
        """Return 400 validation error"""
        return error_response("VALIDATION_ERROR", message, 400, details)

    @staticmethod
    def not_found(message="Resource not found", details=None):
        """Return 404 not found error"""
        return error_response("NOT_FOUND", message, 404, details)

    @staticmethod
    def unauthorized(message="Unauthorized access", details=None):
        """Return 401 unauthorized error"""
        return error_response("UNAUTHORIZED", message, 401, details)

    @staticmethod
    def forbidden(message="Access forbidden", details=None):
        """Return 403 forbidden error"""
        return error_response("FORBIDDEN", message, 403, details)

    @staticmethod
    def server_error(message="Internal server error", details=None):
        """Return 500 server error"""
        return error_response("INTERNAL_ERROR", message, 500, details)
