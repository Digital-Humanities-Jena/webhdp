"""Custom exception hierarchy for better error handling and debugging"""


class AppException(Exception):
    """Base exception for all application errors"""

    status_code = 500
    error_code = "INTERNAL_ERROR"
    user_message = "An internal error occurred"

    def __init__(self, message=None, details=None):
        super().__init__(message)
        self.message = message or self.user_message
        self.details = details or {}

    def to_dict(self):
        """Convert exception to API response format"""
        return {"error_code": self.error_code, "message": self.message, "details": self.details}


class ValidationError(AppException):
    """Raised when input validation fails"""

    status_code = 400
    error_code = "VALIDATION_ERROR"
    user_message = "Invalid input provided"


class SecurityError(AppException):
    """Raised when security validation fails"""

    status_code = 403
    error_code = "SECURITY_ERROR"
    user_message = "Access denied due to security policy"


class FileProcessingError(AppException):
    """Raised when file processing fails"""

    status_code = 400
    error_code = "FILE_PROCESSING_ERROR"
    user_message = "Failed to process file"


class ResourceNotFoundError(AppException):
    """Raised when requested resource doesn't exist"""

    status_code = 404
    error_code = "RESOURCE_NOT_FOUND"
    user_message = "Requested resource not found"


class APIConnectionError(AppException):
    """Raised when external API call fails"""

    status_code = 502
    error_code = "API_CONNECTION_ERROR"
    user_message = "Failed to connect to external service"


class APITimeoutError(AppException):
    """Raised when external API times out"""

    status_code = 504
    error_code = "API_TIMEOUT_ERROR"
    user_message = "External service request timed out"


class SessionError(AppException):
    """Raised when session is invalid or expired"""

    status_code = 401
    error_code = "SESSION_ERROR"
    user_message = "Session is invalid or has expired"


class PipelineExecutionError(AppException):
    """Raised when pipeline execution fails"""

    status_code = 500
    error_code = "PIPELINE_EXECUTION_ERROR"
    user_message = "Pipeline execution failed"
