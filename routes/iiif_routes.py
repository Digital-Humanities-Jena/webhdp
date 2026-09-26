# routes/iiif_routes.py
import logging
import os
import json
from typing import Any, Dict
from flask import Blueprint, current_app, request
from flask_jwt_extended import jwt_required
from api_utils import APIResponse
from database.models import Session as DBSession, UserMetadata
from routes.access_helpers import get_session_with_permission
from services.iiif_service import IiifService
from services.msf_service import MSFService
from .lod_mapping_helpers import build_pipeline_aligned_lod_metadata, record_for_metadata_row

logger = logging.getLogger(__name__)
iiif_bp = Blueprint("iiif", __name__)
iiif_service = IiifService()
msf_service = MSFService()


def _get_session_msf_profile(session_row: DBSession | None) -> Dict[str, Any]:
    if not session_row:
        return {}

    record = UserMetadata.query.filter_by(session_id=int(session_row.id), field_name="msf_profile").first()
    if not record or not record.field_value:
        return {}
    try:
        payload = json.loads(record.field_value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_authorized_session(session_id: Any) -> tuple[DBSession | None, tuple | None]:
    if session_id in (None, ""):
        return None, APIResponse.validation_error("A session is required to read metadata files")
    try:
        sid = int(session_id)
    except (TypeError, ValueError):
        return None, APIResponse.validation_error("session_id must be an integer")
    session_row, _, error_response = get_session_with_permission(sid, permission="view")
    return session_row, error_response


def _resolve_msf_path(msf_path: str, session_row: DBSession | None) -> str:
    from services.lod_reliability import session_metadata_path
    if not session_row:
        return None
    if msf_path and os.path.exists(msf_path):
        return session_metadata_path(msf_path, session_row)
    profile_path = _get_session_msf_profile(session_row).get("file_path")
    if profile_path and os.path.exists(profile_path):
        return session_metadata_path(profile_path, session_row)
    roots = [session_row.session_dir, os.path.dirname(session_row.hdpc_path or "")]
    for root in roots:
        if not root:
            continue
        for extension in (".xlsx", ".xls", ".csv"):
            candidate = session_metadata_path(os.path.join(root, "uploads", f"upload.msf{extension}"), session_row)
            if candidate:
                return candidate
    return None


def _resolve_msf_parse_options(payload: Dict[str, Any], session_row: DBSession | None) -> Dict[str, Any]:
    raw_options = payload.get("msf_parse_options")
    if isinstance(raw_options, dict):
        return raw_options
    profile = _get_session_msf_profile(session_row)
    profile_options = profile.get("parse_options")
    return profile_options if isinstance(profile_options, dict) else {}


@iiif_bp.route("/test-mapping", methods=["POST"])
@jwt_required()
def test_mapping():
    """
    Test IIIF mapping configuration on a sample record.
    """
    try:
        data = request.get_json() or {}
        msf_path = data.get("msf_path")
        session_id = data.get("session_id")
        requested_row_index = data.get("row_index")
        zenodo_record = data.get("zenodo_record", {})
        mapping_config = data.get("mapping_config", {})
        template_id = data.get("template_id")
        session_row, error_response = _resolve_authorized_session(session_id)
        if error_response:
            return error_response
        parse_options = _resolve_msf_parse_options(data, session_row)
        msf_path = _resolve_msf_path(msf_path, session_row)

        if not msf_path or not os.path.exists(msf_path):
             return APIResponse.validation_error("Valid MSF path is required")

        # 1. Parse MSF and get specific row
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
        zenodo_record, main_file_key = record_for_metadata_row(row, msf_profile, zenodo_record)

        # 2. Apply Mapping (pipeline-aligned merge semantics)
        metadata = build_pipeline_aligned_lod_metadata(
            msf_service=msf_service,
            row=row,
            zenodo_record=zenodo_record,
            mapping_config=mapping_config,
            msf_profile=msf_profile,
        )

        # 3. Render Template
        generation = iiif_service.generate_iiif_manifest_with_report(
            metadata=metadata,
            zenodo_record=zenodo_record,
            main_file_key=main_file_key,
            template_id=template_id,
            validate=False,
        )
        json_output = generation["content"]

        if not json_output:
            return APIResponse.error("Failed to render IIIF JSON manifest", 500)

        validation = iiif_service.validate_iiif_manifest(json_output)

        return APIResponse.success(
            data={
                "json": json_output,
                "metadata": metadata,
                "validation": validation,
                "minimum_viable_applied": generation["minimum_viable_applied"],
                "row_index_used": row_index,
                "msf_profile": msf_profile,
            },
            message="IIIF mapping test completed"
        )

    except Exception as e:
        logger.error(f"IIIF mapping test failed: {e}", exc_info=True)
        return APIResponse.server_error(f"Failed to test mapping: {e}")
