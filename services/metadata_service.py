import json
import logging
from typing import Any, Dict, List

from database.database import db
from database.models import File, FileMetadata, UserMetadata, BatchFileMetadata
from exceptions import ResourceNotFoundError
from services.metadata_workflow_service import get_retired_prepare_metadata_message

logger = logging.getLogger(__name__)


class MetadataService:
    """Service for managing metadata"""

    def save_file_metadata(self, file_id: int, metadata: Dict[str, Any]) -> List[FileMetadata]:
        """
        Save metadata for a specific file.

        Args:
            file_id: File ID
            metadata: Dictionary of metadata fields

        Returns:
            List of created FileMetadata objects
        """
        # Verify file exists
        file = db.session.get(File, file_id)
        if not file:
            raise ResourceNotFoundError(f"File {file_id} not found")

        # Delete existing metadata for this file
        FileMetadata.query.filter_by(file_id=file_id).delete()

        # Create new metadata entries
        metadata_objects = []
        for field_name, field_value in metadata.items():
            meta = FileMetadata(file_id=file_id, field_name=field_name, field_value=str(field_value))
            metadata_objects.append(meta)
            db.session.add(meta)

        db.session.commit()
        logger.info(f"Saved {len(metadata_objects)} metadata fields for file {file_id}")
        return metadata_objects

    def get_file_metadata(self, file_id: int) -> Dict[str, Any]:
        """Get all metadata for a file"""
        metadata_records = FileMetadata.query.filter_by(file_id=file_id).all()
        return {m.field_name: m.field_value for m in metadata_records}

    def save_user_metadata(self, session_id: int, metadata: Dict[str, Any], merge: bool = True) -> List[UserMetadata]:
        """
        Save user-provided metadata for a session using an upsert/merge approach.

        Args:
            session_id: The session ID to save metadata for
            metadata: Dictionary of metadata fields to save
            merge: If True (default), merge with existing metadata. If False, replace all.

        This correctly serializes dicts/lists as JSON strings and uses a merge strategy
        to prevent data loss when only partial updates are sent.
        """
        metadata_objects = []

        if not merge:
            # Legacy behavior: delete all existing metadata first
            UserMetadata.query.filter_by(session_id=session_id).delete()

        for field_name, field_value in metadata.items():
            # Check if the value is complex (list/dict) and serialize it
            if isinstance(field_value, (dict, list)):
                value_to_store = json.dumps(field_value)
            else:
                value_to_store = str(field_value)

            if merge:
                # Upsert: Update existing or create new
                existing = UserMetadata.query.filter_by(
                    session_id=session_id,
                    field_name=field_name
                ).first()

                if existing:
                    existing.field_value = value_to_store
                    metadata_objects.append(existing)
                else:
                    meta = UserMetadata(session_id=session_id, field_name=field_name, field_value=value_to_store)
                    metadata_objects.append(meta)
                    db.session.add(meta)
            else:
                # Insert new (existing already deleted above)
                meta = UserMetadata(session_id=session_id, field_name=field_name, field_value=value_to_store)
                metadata_objects.append(meta)
                db.session.add(meta)

        db.session.commit()
        logger.info(f"Saved {len(metadata_objects)} user metadata fields for session {session_id} (merge={merge})")
        return metadata_objects

    def get_user_metadata(self, session_id: int) -> Dict[str, Any]:
        """Get all user metadata for a session"""
        metadata_records = UserMetadata.query.filter_by(session_id=session_id).all()

        # Attempt to deserialize JSON strings back into objects
        parsed_metadata = {}
        for m in metadata_records:
            try:
                # Try to parse the value as JSON
                parsed_metadata[m.field_name] = json.loads(m.field_value)
            except (json.JSONDecodeError, TypeError):
                # Fallback to string if it's not valid JSON
                parsed_metadata[m.field_name] = m.field_value
        return parsed_metadata

    def prepare_metadata(self, file_id: str, is_sandbox: bool = True) -> Dict[str, Any]:
        """Legacy prepare-metadata behavior is retired in favor of the native WebHDP workflow."""
        raise NotImplementedError(get_retired_prepare_metadata_message())

    def update_batch_metadata(self, session_id: int, updates: Dict[str, Any]) -> int:
        """
        Mass-update Zenodo metadata for all files in a batch session.

        Args:
            session_id: The session ID
            updates: Dictionary of fields to update/merge into each file's metadata

        Returns:
            Number of records updated
        """
        records = BatchFileMetadata.query.filter_by(session_id=session_id).all()
        for record in records:
            try:
                current_meta = json.loads(record.metadata_json) if record.metadata_json else {}
                current_meta.update(updates)
                record.metadata_json = json.dumps(current_meta)
            except json.JSONDecodeError:
                logger.warning(f"Could not parse existing metadata for record {record.id}, creating new")
                record.metadata_json = json.dumps(updates)

        db.session.commit()
        return len(records)
