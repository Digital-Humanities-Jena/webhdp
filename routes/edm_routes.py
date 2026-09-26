# routes/edm_routes.py
import logging
import os
from typing import Any, Dict
from flask import Blueprint, current_app, request
from flask_jwt_extended import jwt_required
from api_utils import APIResponse
from database.models import Session as DBSession, UserMetadata
from routes.access_helpers import get_session_with_permission
from services.edm_service import EdmService
from services.msf_service import MSFService
from .lod_mapping_helpers import build_pipeline_aligned_lod_metadata, record_for_metadata_row
import yaml
from schemas.mapping_schemas import MappingConfig, MappingExportRequest
from flask import send_file
import io
import json

logger = logging.getLogger(__name__)
edm_bp = Blueprint("edm", __name__)
edm_service = EdmService()
msf_service = MSFService()
LOD_STANDARD_ORDER = ("zenodo", "edm", "iiif", "mets", "cidoc_crm", "jsonld")


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


def _recursive_dump(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return {k: _recursive_dump(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_recursive_dump(i) for i in obj]
    return obj


def _normalize_mapping_structure(mapping: dict) -> dict:
    dumped = _recursive_dump(mapping)
    if not isinstance(dumped, dict):
        return {key: {} for key in LOD_STANDARD_ORDER}

    normalized = {}
    for standard_id in LOD_STANDARD_ORDER:
        node = dumped.get(standard_id, {})
        normalized[standard_id] = node if isinstance(node, dict) else {}

    for standard_id, node in dumped.items():
        if standard_id not in normalized:
            normalized[standard_id] = node if isinstance(node, dict) else {}

    normalized["cidoc_crm"] = normalized["cidoc_crm"] or normalized["jsonld"]
    normalized["jsonld"] = normalized["cidoc_crm"]
    return normalized


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
    if isinstance(profile_options, dict):
        return profile_options
    return {}


@edm_bp.route("/test-mapping", methods=["POST"])
@jwt_required()
def test_mapping():
    """
    Test mapping configuration on a sample record.

    Request body:
    {
        "msf_path": "/path/to/msf",
        "row_index": 0,
        "zenodo_record": {...},
        "mapping_config": {...},
        "template_id": 1
    }
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

        if not template_id:
             return APIResponse.validation_error("Template ID is required")

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

        # 3. Render Template & Validate
        generation = edm_service.generate_edm_xml_with_report(
            metadata=metadata,
            zenodo_record=zenodo_record,
            main_file_key=main_file_key,
            template_id=template_id,
            validate=False,
        )
        xml_output = generation["content"]

        if not xml_output:
            return APIResponse.error("Failed to render XML template", 500)

        validation = edm_service.validate_edm_document(
            xml_output,
            metadata=metadata,
            include_remote=current_app.config.get(
                "LOCAL_EDM_VALIDATOR_REQUIRED",
                False,
            ) or current_app.config.get(
                "ENABLE_LOCAL_EDM_VALIDATION",
                current_app.config.get("ENABLE_METIS_VALIDATION", True),
            ),
        )

        return APIResponse.success(
            data={
                "xml": xml_output,
                "metadata": metadata,
                "validation": validation,
                "minimum_viable_applied": generation["minimum_viable_applied"],
                "row_index_used": row_index,
                "msf_profile": msf_profile,
            },
            message="Mapping test completed"
        )

    except Exception as e:
        logger.error(f"LOD mapping test failed: {e}", exc_info=True)
        return APIResponse.server_error(f"Failed to test mapping: {e}")

@edm_bp.route("/msf-columns", methods=["POST"])
@jwt_required()
def get_msf_columns():
    """Get columns from an MSF file for mapping purposes"""
    try:
        data = request.get_json() or {}
        msf_path = data.get("msf_path")
        session_id = data.get("session_id")
        session_row, error_response = _resolve_authorized_session(session_id)
        if error_response:
            return error_response
        parse_options = _resolve_msf_parse_options(data, session_row)
        msf_path = _resolve_msf_path(msf_path, session_row)

        if not msf_path or not os.path.exists(msf_path):
             return APIResponse.validation_error("Valid MSF path is required")

        df, msf_profile = msf_service.parse_msf_file_with_profile(msf_path, parse_options=parse_options)
        columns = list(df.columns)
        suggested_row = msf_profile.get("suggested_row_index")
        if suggested_row is None:
            suggested_row = msf_service.suggest_sample_row_index(df, msf_profile.get("filename_column"))

        return APIResponse.success(
            data={
                "columns": columns,
                "filename_column": msf_profile.get("filename_column"),
                "suggested_row_index": suggested_row,
                "msf_profile": msf_profile,
                "msf_mapping_suggestions": msf_service.suggest_column_mapping(columns),
            },
            message="Columns retrieved successfully"
        )
    except Exception as e:
         return APIResponse.server_error(f"Failed to get columns: {e}")

@edm_bp.route("/mapping/export", methods=["POST"])
@jwt_required()
def export_mapping():
    """
    Export current mapping configuration as YAML.
    """
    try:
        data = request.get_json() or {}
        export_format = str(request.args.get("format", "yaml")).strip().lower()
        if export_format not in {"yaml", "yml", "json"}:
            return APIResponse.validation_error("Unsupported export format. Use 'yaml' or 'json'.")
        # Validate structure
        try:
            req = MappingExportRequest(mapping=data)
        except Exception as e:
            return APIResponse.validation_error(f"Invalid mapping structure: {e}")

        mapping_dict = _normalize_mapping_structure(req.model_dump()["mapping"])

        mem = io.BytesIO()
        if export_format == "json":
            payload = json.dumps(mapping_dict, ensure_ascii=False, indent=2)
            mem.write(payload.encode("utf-8"))
            mimetype = "application/json"
            download_name = "lod_mapping_config.json"
        else:
            yaml_content = yaml.dump(mapping_dict, default_flow_style=False, sort_keys=False)
            mem.write(yaml_content.encode("utf-8"))
            mimetype = "application/x-yaml"
            download_name = "lod_mapping_config.yaml"
        mem.seek(0)

        return send_file(
            mem,
            mimetype=mimetype,
            as_attachment=True,
            download_name=download_name
        )

    except Exception as e:
        logger.error(f"Export failed: {e}")
        return APIResponse.server_error(f"Export failed: {e}")

@edm_bp.route("/mapping/import", methods=["POST"])
@jwt_required()
def import_mapping():
    """
    Import and validate mapping configuration from YAML file.
    """
    try:
        if 'file' not in request.files:
            return APIResponse.validation_error("No file part")

        file = request.files['file']
        if file.filename == '':
            return APIResponse.validation_error("No selected file")

        filename = file.filename or ""
        lowered = filename.lower()
        if not lowered.endswith(('.yaml', '.yml', '.json')):
             return APIResponse.validation_error("File must be .yaml, .yml, or .json")

        # Read and Parse YAML
        try:
            content = file.read()
            if lowered.endswith(".json"):
                data = json.loads(content.decode("utf-8"))
            else:
                data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            return APIResponse.validation_error(f"Invalid YAML format: {e}")
        except json.JSONDecodeError as e:
            return APIResponse.validation_error(f"Invalid JSON format: {e}")

        # Validate against Schema
        try:
            # Pydantic validation
            # We iterate to ensure deep validation (MappingConfig is Dict[str, Dict...])
            # Pydantic's parse_obj_as or TypeAdapter is good here, or just basic dict traverse if simple.
            # But we defined MappingConfig as complex dicts.
            from pydantic import TypeAdapter
            validator = TypeAdapter(MappingConfig)
            validated_data = validator.validate_python(data)

        except Exception as e:
            return APIResponse.validation_error(f"Schema Validation Failed: {e}")

        return APIResponse.success(
            data=_normalize_mapping_structure(validated_data),
            message="Mapping imported and validated successfully"
        )

    except Exception as e:
        logger.error(f"Import failed: {e}")
        return APIResponse.server_error(f"Import failed: {e}")


@edm_bp.route('/test-linked-mapping', methods=['POST'])
@jwt_required()
def test_linked_mapping():
    from services.linked_data_service import generate_linked_data, validate_linked_data
    data = request.get_json() or {}
    standard = data.get('standard')
    if standard not in ('cidoc_crm', 'jsonld'):
        return APIResponse.validation_error('Choose CIDOC-CRM or JSON-LD')
    session_row, error = _resolve_authorized_session(data.get('session_id'))
    if error:
        return error
    if session_row is None:
        return APIResponse.validation_error('A session is required')
    try:
        path = _resolve_msf_path(data.get('msf_path'), session_row)
        roots = [session_row.session_dir, os.path.dirname(session_row.hdpc_path or '')]
        if not path or not any(root and os.path.commonpath([os.path.realpath(path), os.path.realpath(root)]) == os.path.realpath(root) for root in roots):
            return APIResponse.validation_error('The MSF must belong to this session')
        df, profile = msf_service.parse_msf_file_with_profile(path, parse_options=_resolve_msf_parse_options(data, session_row))
        index = int(data.get('row_index', 0))
        if index < 0 or index >= len(df):
            return APIResponse.validation_error('Choose an existing sample row')
        row = df.iloc[index]
        record = data.get('zenodo_record') or {}
        metadata = build_pipeline_aligned_lod_metadata(msf_service=msf_service, row=row, zenodo_record=record, mapping_config=data.get('mapping_config') or {}, msf_profile=profile)
        name = str(row.get(profile.get('filename_column'), '')).strip()
        if not name:
            return APIResponse.validation_error('The sample row needs a source filename')
        record = {**record, 'files': [{'key': name}]}
        content = generate_linked_data(metadata, record, main_file_key=name)[standard][1]
        return APIResponse.success(data={'json' if standard == 'jsonld' else 'xml': content, 'metadata': metadata, 'row_index_used': index, 'validation': validate_linked_data(content, standard)})
    except (ValueError, OSError) as exc:
        return APIResponse.validation_error(str(exc))
