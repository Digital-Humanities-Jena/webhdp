"""Request validation decorator using Pydantic schemas"""

from functools import wraps
from typing import Type, Optional
from flask import request, g
from pydantic import BaseModel, ValidationError as PydanticValidationError
from exceptions import ValidationError
import logging

logger = logging.getLogger(__name__)


def validate_request(schema: Type[BaseModel], location: str = "json", store_in_g: bool = True):
    """
    Decorator to validate request data against a Pydantic schema.

    Args:
        schema: Pydantic BaseModel class to validate against
        location: Where to find data ('json', 'form', 'args')
        store_in_g: Whether to store validated data in Flask's g object

    Usage:
        @app.route('/endpoint', methods=['POST'])
        @validate_request(MySchema)
        def my_endpoint():
            validated_data = g.validated_data
            # Use validated_data...
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Get data from request based on location
            if location == "json":
                data = request.get_json(silent=True)
                if data is None:
                    raise ValidationError(
                        "Request body must be valid JSON", details={"content_type": request.content_type}
                    )
            elif location == "form":
                data = request.form.to_dict()
            elif location == "args":
                data = request.args.to_dict()
            else:
                raise ValueError(f"Invalid location: {location}")

            # Validate data against schema
            try:
                validated = schema(**data)

                # Store in Flask's g object if requested
                if store_in_g:
                    g.validated_data = validated

                # Log successful validation
                logger.debug(f"Request validation successful for {schema.__name__}")

                return f(*args, **kwargs)

            except PydanticValidationError as e:
                # Convert Pydantic validation errors to our ValidationError
                errors = []
                for error in e.errors():
                    field = ".".join(str(loc) for loc in error["loc"])
                    message = error["msg"]
                    errors.append(f"{field}: {message}")

                logger.warning(f"Validation failed for {schema.__name__}: {errors}")

                raise ValidationError(
                    "Request validation failed", details={"errors": errors, "schema": schema.__name__}
                )

        return decorated_function

    return decorator


def validate_file_upload(required: bool = True, field_name: str = "file", max_size: Optional[int] = None):
    """
    Decorator to validate file uploads.

    Args:
        required: Whether file upload is required
        field_name: Name of the file field in the request
        max_size: Maximum file size in bytes (overrides config)

    Usage:
        @app.route('/upload', methods=['POST'])
        @validate_file_upload(required=True)
        def upload_endpoint():
            file = request.files['file']
            # File is guaranteed to exist and be valid
    """

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Check if file exists
            if field_name not in request.files:
                if required:
                    raise ValidationError("File upload required", details={"expected_field": field_name})
                else:
                    return f(*args, **kwargs)

            file = request.files[field_name]

            # Check if file is empty
            if file.filename == "":
                if required:
                    raise ValidationError("No file selected")
                else:
                    return f(*args, **kwargs)

            # Validate file size if specified
            if max_size is not None:
                file.seek(0, 2)  # Seek to end
                file_size = file.tell()
                file.seek(0)  # Reset to beginning

                if file_size > max_size:
                    max_mb = max_size / (1024 * 1024)
                    actual_mb = file_size / (1024 * 1024)
                    raise ValidationError(
                        "File too large",
                        details={"max_size_mb": round(max_mb, 2), "actual_size_mb": round(actual_mb, 2)},
                    )

            # Store file in g for easy access
            g.uploaded_file = file

            logger.debug(f"File upload validation successful: {file.filename}")

            return f(*args, **kwargs)

        return decorated_function

    return decorator
