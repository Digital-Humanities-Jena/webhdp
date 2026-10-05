# routes/metadata_routes.py
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from flask import Blueprint, current_app, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from api_utils import APIResponse
from database.database import db
from database.models import Session as DBSession, UserMetadata
from routes.access_helpers import get_file_with_session_permission, get_session_with_permission
from security import path_is_within, resolve_child_path
from services.metadata_service import MetadataService
from services.msf_service import MSFService
from services.metadata_workflow_service import get_metadata_workflow_contract
from services.publishing_context_service import PublishingContextService
from services.zenodo_config_service import ZenodoConfigService
from services.zenodo_metadata_normalizer import normalize_zenodo_metadata as shared_normalize_zenodo_metadata
from .lod_mapping_helpers import build_pipeline_aligned_lod_metadata

logger = logging.getLogger(__name__)
metadata_bp = Blueprint("metadata", __name__)
metadata_service = MetadataService()
msf_service = MSFService()
publishing_context_service = PublishingContextService()
INTERNAL_METADATA_KEYS = {"lod_mapping", "msf_path", "msf_profile", "msf_parse_options"}


def _get_session_msf_profile(session_id: Any) -> Dict[str, Any]:
    try:
        sid = int(session_id)
    except (TypeError, ValueError):
        return {}

    record = UserMetadata.query.filter_by(session_id=sid, field_name="msf_profile").first()
    if not record or not record.field_value:
        return {}
    try:
        payload = json.loads(record.field_value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_msf_path(msf_path: str, session_id: Any) -> str:
    try:
        sid = int(session_id)
    except (TypeError, ValueError):
        if msf_path:
            upload_folder = current_app.config.get("UPLOAD_FOLDER", "/tmp/msf_uploads")
            return str(resolve_child_path(upload_folder, msf_path, must_exist=True))
        return msf_path

    session = db.session.get(DBSession, sid)
    if not session:
        return msf_path

    candidate_dirs = []
    if session.session_dir:
        candidate_dirs.append(os.path.join(session.session_dir, "uploads"))
    if session.hdpc_path:
        candidate_dirs.append(os.path.join(os.path.dirname(session.hdpc_path), "uploads"))

    if msf_path:
        raw_candidate = Path(msf_path).expanduser()
        if not raw_candidate.is_absolute() and candidate_dirs:
            raw_candidate = Path(candidate_dirs[0]) / raw_candidate
        resolved_candidate = raw_candidate.resolve(strict=False)
        if os.path.exists(resolved_candidate) and any(path_is_within(base_dir, resolved_candidate) for base_dir in candidate_dirs):
            return str(resolved_candidate)

    profile = _get_session_msf_profile(sid)
    profile_path = profile.get("file_path")
    if (
        isinstance(profile_path, str)
        and os.path.exists(profile_path)
        and any(path_is_within(base_dir, profile_path) for base_dir in candidate_dirs)
    ):
        return profile_path

    for base_dir in candidate_dirs:
        if not base_dir or not os.path.isdir(base_dir):
            continue
        for ext in (".xlsx", ".xls", ".csv"):
            candidate = os.path.join(base_dir, f"upload.msf{ext}")
            if os.path.exists(candidate):
                return candidate

    return msf_path


def _resolve_msf_parse_options(payload: Dict[str, Any], session_id: Any) -> Dict[str, Any]:
    raw_options = payload.get("msf_parse_options")
    if isinstance(raw_options, dict):
        return raw_options
    profile = _get_session_msf_profile(session_id)
    profile_options = profile.get("parse_options")
    return profile_options if isinstance(profile_options, dict) else {}


def _split_zenodo_and_internal_metadata(payload: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    zenodo_payload: Dict[str, Any] = {}
    internal_payload: Dict[str, Any] = {}
    for key, value in (payload or {}).items():
        if key.startswith("edm_") or key in INTERNAL_METADATA_KEYS:
            internal_payload[key] = value
        else:
            zenodo_payload[key] = value
    return zenodo_payload, internal_payload


# --- Workaround as Validation Endpoint is not yet implemented in HDP Server API ---
def validate_zenodo_metadata(zenodo_metadata: Dict[str, Dict[str, Any]]) -> List[str]:
    """
    Validates Zenodo metadata against a set of predefined rules and constraints.

    This function checks the structure, required fields, data types, and specific
    content requirements for Zenodo metadata. It performs comprehensive validation
    including checks for upload types, publication types, date formats, creator
    information, access rights, and more.

    Args:
        zenodo_metadata: The Zenodo metadata to be validated.

    Returns:
        A list of error messages. An empty list indicates no validation errors.
    """
    errors = []

    if "metadata" not in zenodo_metadata:
        errors.append("Missing required 'metadata' key")
        return errors
    metadata = zenodo_metadata["metadata"]

    required_fields = ["upload_type", "publication_date", "title", "creators", "description", "access_right"]
    for field in required_fields:
        if not metadata.get(field):
            errors.append(f"Missing required field or value for: {field}")

    valid_datatypes = {
        "upload_type": str,
        "publication_type": str,
        "image_type": str,
        "publication_date": str,
        "title": str,
        "creators": list,
        "description": str,
        "access_right": str,
        "license": str,
        "embargo_date": str,
        "access_conditions": str,
        "doi": str,
        "prereserve_doi": dict,
        "keywords": list,
        "notes": str,
        "related_identifiers": list,
        "contributors": list,
        "references": list,
        "communities": list,
        "grants": list,
        "journal_title": str,
        "journal_volume": str,
        "journal_issue": str,
        "journal_pages": str,
        "conference_title": str,
        "conference_acronym": str,
        "conference_dates": str,
        "conference_place": str,
        "conference_url": str,
        "conference_session": str,
        "conference_session_part": str,
        "imprint_publisher": str,
        "imprint_isbn": str,
        "imprint_place": str,
        "partof_title": str,
        "partof_pages": str,
        "thesis_supervisors": list,
        "thesis_university": str,
        "subjects": list,
        "version": str,
        "language": str,
        "locations": list,
        "dates": list,
        "method": str,
        # Internal fields for workflow (not Zenodo-native)
        "edm_template_id": int,
    }

    # Check for unknown fields
    for field in metadata:
        if field not in valid_datatypes:
            errors.append(f"Unknown field: {field}")

    # Check datatypes and structure of known fields
    for field, expected_type in valid_datatypes.items():
        if field in metadata and metadata[field] is not None:
            value = metadata[field]
            if not isinstance(value, expected_type):
                errors.append(f"'{field}' must be of type {expected_type.__name__}, but got {type(value).__name__}.")
                continue  # Skip further checks on this broken field

            if expected_type == list and value:
                # Ensure list is not empty before checking item types
                if not value:
                    continue

                is_dict_list = all(isinstance(item, dict) for item in value)
                is_str_list = all(isinstance(item, str) for item in value)

                if not is_dict_list and not is_str_list:
                    errors.append(
                        f"All items in '{field}' must be of the same type (either all strings or all dictionaries)."
                    )
                elif is_dict_list:
                    # Field-specific key validation for lists of dictionaries
                    if field in ["creators", "contributors", "thesis_supervisors"]:
                        if not all("name" in item for item in value):
                            errors.append(f"Each item in '{field}' must have a 'name' key.")
                    elif field == "related_identifiers":
                        if not all("identifier" in item and "relation" in item for item in value):
                            errors.append(f"Each item in '{field}' must have 'identifier' and 'relation' keys.")
                    elif field == "communities":
                        if not all("identifier" in item for item in value):
                            errors.append(f"Each item in '{field}' must have an 'identifier' key.")
                    elif field == "grants":
                        if not all("id" in item for item in value):
                            errors.append(f"Each item in '{field}' must have an 'id' key.")
                    elif field == "subjects":
                        if not all("term" in item for item in value):
                            errors.append(f"Each item in '{field}' must have a 'term' key.")
                    elif field == "locations":
                        if not all("place" in item for item in value):
                            errors.append(f"Each item in '{field}' must have a 'place' key.")
                    elif field == "dates":
                        if not all("type" in item and ("start" in item or "end" in item) for item in value):
                            errors.append(
                                f"Each item in '{field}' must have a 'type' key and at least a 'start' or 'end' key."
                            )

    # Validate controlled vocabularies and formats
    valid_upload_types = [
        "publication",
        "poster",
        "presentation",
        "dataset",
        "image",
        "video",
        "software",
        "lesson",
        "physicalobject",
        "other",
    ]
    if "upload_type" in metadata and metadata["upload_type"] not in valid_upload_types:
        errors.append(f"Invalid upload_type: {metadata['upload_type']}")

    if metadata.get("upload_type") == "publication" and "publication_type" not in metadata:
        errors.append("Missing publication_type for upload_type 'publication'")

    if metadata.get("upload_type") == "image" and "image_type" not in metadata:
        errors.append("Missing image_type for upload_type 'image'")

    if "publication_date" in metadata and isinstance(metadata["publication_date"], str):
        try:
            datetime.strptime(metadata["publication_date"], "%Y-%m-%d")
        except (ValueError, TypeError):
            errors.append("Invalid publication_date format. Use YYYY-MM-DD.")

    if "creators" in metadata and isinstance(metadata["creators"], list):
        for creator in metadata["creators"]:
            if isinstance(creator, dict) and "orcid" in creator and creator["orcid"]:
                if not re.match(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]$", creator["orcid"]):
                    errors.append(f"Invalid ORCID format for creator: {creator.get('name', 'N/A')}")

    valid_access_rights = ["open", "embargoed", "restricted", "closed"]
    if "access_right" in metadata and metadata["access_right"] not in valid_access_rights:
        errors.append(f"Invalid access_right: {metadata['access_right']}")

    if metadata.get("access_right") in ["open", "embargoed"] and not metadata.get("license"):
        errors.append("Missing license for open or embargoed access_right")

    if metadata.get("access_right") == "embargoed":
        if not metadata.get("embargo_date"):
            errors.append("Missing embargo_date for embargoed access_right")
        elif isinstance(metadata["embargo_date"], str):
            try:
                embargo_date = datetime.strptime(metadata["embargo_date"], "%Y-%m-%d").date()
                if embargo_date <= datetime.now().date():
                    errors.append("embargo_date must be in the future")
            except (ValueError, TypeError):
                errors.append("Invalid embargo_date format. Use YYYY-MM-DD.")

    if metadata.get("access_right") == "restricted" and not metadata.get("access_conditions"):
        errors.append("Missing access_conditions for restricted access_right")

    return errors


def normalize_zenodo_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizes Zenodo metadata by coercing certain fields (like keywords)
    into the expected formats (e.g., list of strings).
    """
    return shared_normalize_zenodo_metadata(metadata, apply_defaults=False)


# --- Routes ---
@metadata_bp.route("/workflow-support", methods=["GET"])
@jwt_required()
def metadata_workflow_support():
    return APIResponse.success(
        data=get_metadata_workflow_contract(),
        message="Metadata workflow support contract retrieved",
    )


@metadata_bp.route("/test-mapping", methods=["POST"])
@jwt_required()
def test_zenodo_mapping():
    """Test a Zenodo mapping configuration on one MSF row."""
    try:
        data = request.get_json() or {}
        msf_path = data.get("msf_path")
        session_id = data.get("session_id")
        session_row = None
        if session_id is not None:
            session_row, _, error_response = get_session_with_permission(int(session_id), permission="view")
            if error_response:
                return error_response
        requested_row_index = data.get("row_index")
        zenodo_record = data.get("zenodo_record", {})
        mapping_config = data.get("mapping_config", {})
        parse_options = _resolve_msf_parse_options(data, session_id)
        msf_path = _resolve_msf_path(msf_path, session_id)

        if not msf_path or not os.path.exists(msf_path):
            return APIResponse.validation_error("Valid MSF path is required")
        if not isinstance(mapping_config, dict):
            return APIResponse.validation_error("mapping_config must be an object")

        df, msf_profile = msf_service.parse_msf_file_with_profile(msf_path, parse_options=parse_options)
        if requested_row_index is None:
            row_index = msf_profile.get("suggested_row_index")
            if row_index is None:
                row_index = msf_service.suggest_sample_row_index(df, msf_profile.get("filename_column"))
        else:
            try:
                row_index = int(requested_row_index)
            except (TypeError, ValueError):
                return APIResponse.validation_error("row_index must be an integer")
        if row_index < 0:
            return APIResponse.validation_error("row_index must be a non-negative integer")
        if row_index >= len(df):
            return APIResponse.validation_error(f"Row index {row_index} out of bounds")

        row = df.iloc[row_index]
        mapped_metadata, provenance = build_pipeline_aligned_lod_metadata(
            msf_service=msf_service,
            row=row,
            zenodo_record=zenodo_record,
            mapping_config=mapping_config,
            msf_profile=msf_profile,
            session_id=session_row.id if session_row else None,
            with_provenance=True,
        )
        mapped_metadata = normalize_zenodo_metadata(mapped_metadata)
        community_cfg = ZenodoConfigService.get_community_override_config()
        mapped_metadata = (
            publishing_context_service.apply_community_policy(session_row, mapped_metadata)
            if session_row
            else ZenodoConfigService.apply_community_override(mapped_metadata)
        )

        if community_cfg.get("enabled"):
            provenance["communities"] = {"source": "default", "field": "Administrator policy"}
        validation_payload = {"metadata": mapped_metadata}
        errors = validate_zenodo_metadata(validation_payload)
        warnings = []
        if community_cfg.get("enabled"):
            warnings.append(
                f"Zenodo community is forced by admin setting to '{community_cfg.get('community')}'."
            )

        return APIResponse.success(
            data={
                "metadata": mapped_metadata,
                "provenance": provenance,
                "source_filename": str(row.get(msf_profile.get("filename_column") or "filename", "")),
                "payload": validation_payload,
                "community_override": community_cfg,
                "row_index_used": row_index,
                "msf_profile": msf_profile,
                "validation": {
                    "valid": len(errors) == 0,
                    "errors": errors,
                    "warnings": warnings,
                },
            },
            message="Zenodo mapping test completed",
        )
    except ValueError as exc:
        return APIResponse.validation_error(str(exc))
    except Exception as exc:
        logger.error(f"Zenodo mapping test failed: {exc}", exc_info=True)
        return APIResponse.server_error(f"Failed to test Zenodo mapping: {exc}")


@metadata_bp.route("/file/<int:file_id>", methods=["POST", "PUT"])
@jwt_required()
def save_file_metadata(file_id):
    """Save or update metadata for a file"""
    _, _, _, error_response = get_file_with_session_permission(
        file_id,
        permission="edit",
        require_mutable=True,
    )
    if error_response:
        return error_response
    data = request.get_json()
    metadata = data.get("metadata", {})

    metadata_objects = metadata_service.save_file_metadata(file_id, metadata)

    return APIResponse.success(
        data={"saved_fields": len(metadata_objects)}, message="File metadata saved successfully"
    )


@metadata_bp.route("/zenodo-community-override", methods=["GET"])
@jwt_required()
def get_zenodo_community_override():
    """Return effective community override so workflows can indicate active hardcoding."""
    config = ZenodoConfigService.get_community_override_config()
    return APIResponse.success(data={"config": config})


@metadata_bp.route("/file/<int:file_id>", methods=["GET"])
@jwt_required()
def get_file_metadata(file_id):
    """Get metadata for a file"""
    _, _, _, error_response = get_file_with_session_permission(file_id, permission="view")
    if error_response:
        return error_response
    metadata = metadata_service.get_file_metadata(file_id)
    return APIResponse.success(data={"metadata": metadata})


@metadata_bp.route("/user/<int:session_id>", methods=["POST", "PUT"])
@jwt_required()
def save_user_metadata(session_id):
    """
    Save or update user metadata for a session.
    This endpoint VALIDATES Zenodo metadata before saving.
    """
    session_row, _, error_response = get_session_with_permission(
        session_id,
        permission="edit",
        require_mutable=True,
    )
    if error_response:
        return error_response

    # The frontend now sends the metadata object (formData) as the payload
    zenodo_draft = request.get_json()

    if not isinstance(zenodo_draft, dict):
        return APIResponse.validation_error("Invalid payload. Expected a JSON object.")

    zenodo_payload, internal_payload = _split_zenodo_and_internal_metadata(zenodo_draft)

    # Normalize Zenodo fields (e.g., keywords string -> list), keep internal keys untouched.
    normalized_zenodo = normalize_zenodo_metadata(zenodo_payload)
    normalized_zenodo = publishing_context_service.apply_community_policy(session_row, normalized_zenodo)
    zenodo_draft = {**normalized_zenodo, **internal_payload}

    # Sanitize draft for validation (remove internal/EDM fields)
    # We filter out any keys starting with "edm_" as they are valid for HDP internal use
    # but strictly invalid in the eyes of Zenodo schema.
    clean_draft_for_validation = normalized_zenodo

    # We must validate the *contents* of the draft
    # The validator expects the format {"metadata": {...}}
    validation_payload = {"metadata": clean_draft_for_validation}
    validation_errors = validate_zenodo_metadata(validation_payload)

    if validation_errors:
        logger.warning(f"Zenodo metadata validation failed for session {session_id}: {validation_errors}")
        # Return a 400 Bad Request with the validation errors
        return APIResponse.validation_error("Metadata validation failed", details={"errors": validation_errors})

    # If validation passes, save the metadata.
    # We must wrap it in the format our service expects.
    # IMPORTANT: We save the ORIGINAL draft (zenodo_draft) which allows us to keep
    # the internal fields (edm_main_file_key, etc.) in the database for later pipeline use.
    payload_to_save = {"zenodo_metadata_draft": zenodo_draft}
    metadata_objects = metadata_service.save_user_metadata(session_id, payload_to_save)

    return APIResponse.success(
        data={"saved_fields": len(metadata_objects)}, message="User metadata saved successfully"
    )


@metadata_bp.route("/user/<int:session_id>/draft", methods=["POST", "PUT"])
@jwt_required()
def save_user_metadata_draft(session_id):
    """
    Save user metadata draft WITHOUT validation.
    Used for auto-save.
    """
    session_row, _, error_response = get_session_with_permission(
        session_id,
        permission="edit",
        require_mutable=True,
    )
    if error_response:
        return error_response

    # The auto-save also sends the raw formData object
    zenodo_draft = request.get_json()

    if not isinstance(zenodo_draft, dict):
        return APIResponse.validation_error("Invalid payload. Expected a JSON object.")

    zenodo_payload, internal_payload = _split_zenodo_and_internal_metadata(zenodo_draft)

    # Normalize Zenodo fields while preserving internal workflow keys for round-trip.
    normalized_zenodo = normalize_zenodo_metadata(zenodo_payload)
    normalized_zenodo = publishing_context_service.apply_community_policy(session_row, normalized_zenodo)
    zenodo_draft = {**normalized_zenodo, **internal_payload}

    # Wrap it in the format our service expects
    payload_to_save = {"zenodo_metadata_draft": zenodo_draft}
    metadata_objects = metadata_service.save_user_metadata(session_id, payload_to_save)

    return APIResponse.success(data={"saved_fields": len(metadata_objects)}, message="Draft saved successfully")


@metadata_bp.route("/user/<int:session_id>", methods=["GET"])
@jwt_required()
def get_user_metadata(session_id):
    """Get user metadata for a session"""
    _, _, error_response = get_session_with_permission(session_id, permission="view")
    if error_response:
        return error_response
    metadata = metadata_service.get_user_metadata(session_id)
    return APIResponse.success(data={"metadata": metadata})


@metadata_bp.route("/session/<int:session_id>/batch-update", methods=["POST", "PUT"])
@jwt_required()
def update_session_batch_metadata(session_id):
    """
    Mass-update Zenodo metadata for all files in a batch session.
    Expects a JSON object with metadata fields to merge.
    """
    _, _, error_response = get_session_with_permission(
        session_id,
        permission="edit",
        require_mutable=True,
    )
    if error_response:
        return error_response

    updates = request.get_json()
    if not isinstance(updates, dict):
        return APIResponse.validation_error("Invalid payload. Expected a JSON object.")

    count = metadata_service.update_batch_metadata(session_id, updates)

    return APIResponse.success(
        data={"updated_count": count},
        message=f"Successfully updated metadata for {count} batch files."
    )


# --- NEW ENDPOINT ---
@metadata_bp.route("/schema", methods=["GET"])
def get_metadata_schema():
    """
    Get the Zenodo metadata schema.
    This is an unprotected endpoint as the schema is not sensitive
    and is required by the frontend to build the form.
    """
    try:
        # current_app.root_path points to the 'codebase' directory
        schema_path = os.path.join(current_app.root_path, "zenodo_metadata_schema.json")

        if not os.path.exists(schema_path):
            logger.error(f"Schema file not found at: {schema_path}")
            return APIResponse.error("SCHEMA_NOT_FOUND", "Metadata schema file not found on server", 500)

        with open(schema_path, "r") as f:
            schema_data = json.load(f)

        return APIResponse.success(data=schema_data)

    except json.JSONDecodeError:
        logger.error(f"Failed to decode zenodo_metadata_schema.json at: {schema_path}")
        return APIResponse.error("SCHEMA_INVALID", "Metadata schema file is invalid JSON", 500)
    except Exception as e:
        logger.error(f"Error loading metadata schema: {e}", exc_info=True)
        return APIResponse.server_error(f"An unexpected error occurred while loading the schema: {e}")
