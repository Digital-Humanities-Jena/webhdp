"""Schemas for pipeline-related requests"""

from typing import List
from pydantic import BaseModel, Field, field_validator, ConfigDict


class PipelineExecutionSchema(BaseModel):
    """Schema for pipeline execution request"""

    model_config = ConfigDict(str_strip_whitespace=True)

    local_file_paths: List[str] = Field(..., min_length=1, max_length=100, description="List of file paths to process")

    @field_validator("local_file_paths")
    @classmethod
    def validate_file_paths(cls, v: List[str]) -> List[str]:
        """Validate file paths list"""
        if not v:
            raise ValueError("At least one file path is required")

        if len(v) > 100:
            raise ValueError("Maximum 100 files can be processed at once")

        # Check for duplicates
        if len(v) != len(set(v)):
            raise ValueError("Duplicate file paths detected")

        # Validate each path
        for path in v:
            if not path or not path.strip():
                raise ValueError("Empty file paths are not allowed")

            if len(path) > 4096:
                raise ValueError("File path too long (max 4096 characters)")

            # Check for null byte injection
            if "\x00" in path:
                raise ValueError("Invalid path: contains null bytes")

        return v
