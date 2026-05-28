# services/file_service.py
"""File service for handling file operations"""

import os
import logging
from pathlib import Path
from typing import Tuple
from werkzeug.datastructures import FileStorage
from security import SecurityValidator
from exceptions import FileProcessingError

logger = logging.getLogger(__name__)


class FileService:
    """Service for file handling operations"""

    def __init__(self, security_validator: SecurityValidator, allowed_extensions: set):
        """
        Initialize file service.

        Args:
            security_validator: Security validator instance
            allowed_extensions: Set of allowed file extensions
        """
        self.validator = security_validator
        self.allowed_extensions = allowed_extensions

    def validate_and_save_upload(self, file: FileStorage, upload_path: str, max_file_size: int) -> Tuple[str, str]:
        """
        Validate and save an uploaded file.

        Args:
            file: Uploaded file object
            upload_path: Directory to save the file
            max_file_size: Maximum allowed file size in bytes

        Returns:
            tuple: (safe_filename, saved_file_path)

        Raises:
            ValidationError: If file validation fails
            FileProcessingError: If file save fails
        """
        # Validate filename and extension
        safe_filename = self.validator.validate_filename(file.filename, self.allowed_extensions)

        # Validate file size
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)  # Reset to beginning

        self.validator.validate_file_size(file_size, max_file_size)

        # Save file
        saved_file_path = os.path.join(upload_path, safe_filename)
        try:
            file.save(saved_file_path)
            logger.info(f"File saved: {saved_file_path}")
            return safe_filename, saved_file_path
        except Exception as e:
            raise FileProcessingError(
                "Failed to save uploaded file", details={"filename": safe_filename, "error": str(e)}
            )

    def validate_directory_path(self, directory_path: str, allowed_dirs: list = None) -> str:
        """
        Validate a directory path for security.

        Args:
            directory_path: Path to validate
            allowed_dirs: Optional list of allowed directory prefixes

        Returns:
            str: Validated absolute path

        Raises:
            ValidationError: If path is invalid
            SecurityError: If path is forbidden
        """
        return self.validator.validate_directory_path(directory_path, allowed_dirs)
