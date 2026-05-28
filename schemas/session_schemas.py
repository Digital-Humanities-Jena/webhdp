"""Schemas for session-related requests"""

from typing import Optional
from pydantic import BaseModel, Field, field_validator, ConfigDict
import os


class DirectorySessionSchema(BaseModel):
    """Schema for directory scan request"""

    model_config = ConfigDict(str_strip_whitespace=True)

    input_directory_path: str = Field(
        ..., min_length=1, max_length=4096, description="Absolute path to the directory to scan"
    )

    @field_validator("input_directory_path")
    @classmethod
    def validate_path_format(cls, v: str) -> str:
        """Validate path format"""
        if not v:
            raise ValueError("Directory path cannot be empty")

        # Basic path validation (detailed validation happens in security layer)
        if "\x00" in v:  # Null byte injection check
            raise ValueError("Invalid path: contains null bytes")

        # Check for suspicious patterns
        if ".." in v and not os.path.isabs(v):
            raise ValueError("Relative paths with '..' are not allowed")

        return v


class FileUploadMetadataSchema(BaseModel):
    """Schema for file upload metadata (when needed)"""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: Optional[str] = Field(None, max_length=500, description="Optional file description")

    tags: Optional[list[str]] = Field(None, max_length=10, description="Optional tags for the file")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        """Validate tags format"""
        if v is None:
            return v

        if len(v) > 10:
            raise ValueError("Maximum 10 tags allowed")

        for tag in v:
            if len(tag) > 50:
                raise ValueError("Each tag must be 50 characters or less")
            if not tag.strip():
                raise ValueError("Empty tags are not allowed")

        return v
