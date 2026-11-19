# routes/submission_routes.py
import json
import logging
import os
import sqlite3

from flask import Blueprint, current_app
from flask_jwt_extended import jwt_required

from api_utils import APIResponse
from constants import WORKFLOW_STATE_FIELD
from database.database import db
from database.models import File, Session, Submission, User, UserMetadata
from routes.access_helpers import get_current_user_from_jwt
from services.session_access_service import can_view_session, get_accessible_sessions

logger = logging.getLogger(__name__)
submission_bp = Blueprint("submissions", __name__)


def _parse_json_value(raw_value, fallback):
    if raw_value is None:
        return fallback
    if isinstance(raw_value, (dict, list)):
        return raw_value
    try:
        return json.loads(raw_value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _normalize_path_signature(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = os.path.normpath(text).replace("\\", "/").lower()
    return f"path:{normalized}" if normalized else None


def _normalize_name_signature(value):
    if value is None:
        return None
    text = os.path.basename(str(value).strip())
    if not text:
        return None
    return f"name:{text.lower()}"


@submission_bp.route("", methods=["GET"])
@jwt_required()
def list_user_submissions():
    """List all submissions for the current authenticated user"""
    try:
        user = get_current_user_from_jwt()
        if not user:
            return APIResponse.unauthorized()
        user_id_str = str(user.id)
        accessible_session_ids = [session.id for session in get_accessible_sessions(user, scope="all")] or [-1]
        submissions = (
            db.session.query(
                Submission.id,
                Submission.session_id,
                Submission.pipeline_id,
                Submission.status,
                Submission.created_at,
                Submission.completed_at,
            )
            .filter(Submission.session_id.in_(accessible_session_ids))
            .order_by(Submission.created_at.desc())
            .all()
        )

        submission_list = [
            {
                "id": sub.id,
                "session_id": sub.session_id,
                "pipeline_id": sub.pipeline_id,
                "status": sub.status,
                "created_at": sub.created_at.isoformat(),
                "completed_at": sub.completed_at.isoformat() if sub.completed_at else None,
            }
            for sub in submissions
        ]

        return APIResponse.success(data={"submissions": submission_list})

    except Exception as e:
        logger.error(f"Failed to list user submissions for user {user_id_str}: {e}", exc_info=True)
        return APIResponse.error("Failed to retrieve submissions", 500)


@submission_bp.route("/<int:submission_id>", methods=["GET"])
@jwt_required()
def get_user_submission_detail(submission_id):
    """Get detailed info for a single submission, verifying user ownership"""
    conn = None
    try:
        user = get_current_user_from_jwt()
        if not user:
            return APIResponse.unauthorized()
        user_id_str = str(user.id)

        # Query for both Submission and Session
        result = (
            db.session.query(Submission, Session)
            .join(Session, Submission.session_id == Session.id)
            .filter(Submission.id == submission_id)
            .first()
        )

        if not result:
            return APIResponse.not_found("Submission not found or you do not have permission to view it")

        submission, session = result  # Unpack the result
        if not can_view_session(session, user):
            return APIResponse.not_found("Submission not found or you do not have permission to view it")

        submission_result = _parse_json_value(submission.result, {})

        # Get the associated files
        files = db.session.query(File).filter_by(session_id=submission.session_id).all()

        workflow_state_record = db.session.query(UserMetadata).filter_by(
            session_id=submission.session_id,
            field_name=WORKFLOW_STATE_FIELD,
        ).first()
        workflow_state = _parse_json_value(workflow_state_record.field_value if workflow_state_record else None, {})
        selected_file_ids = {
            int(file_id)
            for file_id in (workflow_state.get("selected_file_keys") or [])
            if str(file_id).isdigit()
        }
        selected_file_signatures = set()
        processed_file_signatures = set()

        for file_row in files:
            if file_row.id not in selected_file_ids:
                continue
            selected_file_signatures.add(_normalize_path_signature(file_row.path))
            selected_file_signatures.add(_normalize_name_signature(file_row.filename))
        selected_file_signatures.discard(None)

        if isinstance(submission_result, dict):
            for detail in submission_result.get("details", []):
                if not isinstance(detail, dict):
                    continue
                processed_file_signatures.add(_normalize_path_signature(detail.get("file_path")))
                processed_file_signatures.add(_normalize_name_signature(detail.get("file_path")))
        processed_file_signatures.discard(None)

        all_file_entries = []
        for file_row in files:
            path_signature = _normalize_path_signature(file_row.path)
            name_signature = _normalize_name_signature(file_row.filename)
            processed_in_submission = bool(
                path_signature in processed_file_signatures or name_signature in processed_file_signatures
            )
            selected_for_submission = bool(
                file_row.id in selected_file_ids
                or path_signature in selected_file_signatures
                or name_signature in selected_file_signatures
                or processed_in_submission
            )
            all_file_entries.append(
                {
                    "id": file_row.id,
                    "filename": file_row.filename,
                    "path": file_row.path,
                    "size": file_row.size,
                    "status": file_row.status,
                    "selected_for_submission": selected_for_submission,
                    "processed_in_submission": processed_in_submission,
                }
            )

        processed_file_list = [item for item in all_file_entries if item.get("processed_in_submission")]
        if not processed_file_list and selected_file_ids:
            processed_file_list = [item for item in all_file_entries if item.get("selected_for_submission")]
        if not processed_file_list and not selected_file_ids:
            processed_file_list = list(all_file_entries)

        processed_file_ids = {item.get("id") for item in processed_file_list}
        available_file_list = [item for item in all_file_entries if item.get("id") not in processed_file_ids]

        # Get the submitted metadata (the draft)
        metadata_record = db.session.query(UserMetadata).filter_by(
            session_id=submission.session_id, field_name="zenodo_metadata_draft"
        ).first()

        metadata_json = None
        if metadata_record and metadata_record.field_value:
            try:
                metadata_json = json.loads(metadata_record.field_value)
            except json.JSONDecodeError:
                metadata_json = {"error": "Failed to parse metadata JSON"}

        # Get the raw pipeline result string
        submission_result_raw = submission.result

        # --- Get Zenodo Response from .hdpc ---
        zenodo_response_data = []
        hdpc_full_path = session.hdpc_path

        if not hdpc_full_path or not os.path.exists(hdpc_full_path):
            logger.warning(f"Could not find .hdpc file for session {session.id} at {hdpc_full_path}")
            zenodo_response_data = [{"error": "HDPC file not found, cannot load Zenodo response."}]
        else:
            try:
                conn = sqlite3.connect(hdpc_full_path, timeout=30)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT record_metadata_json FROM zenodo_records WHERE record_metadata_json IS NOT NULL;"
                )
                rows = cursor.fetchall()

                for row in rows:
                    json_string = row["record_metadata_json"]
                    if json_string:
                        try:
                            data = json.loads(json_string)
                            zenodo_response_data.append(data)
                        except json.JSONDecodeError:
                            logger.warning(
                                f"Session {session.id} has invalid JSON in zenodo_records: {json_string[:50]}..."
                            )
                            zenodo_response_data.append(
                                {"error": "Invalid JSON data in .hdpc", "raw_data": json_string}
                            )
                    else:
                        zenodo_response_data.append({"error": "Null metadata found in .hdpc"})

                if not rows:
                    zenodo_response_data = [{"info": "No Zenodo records found in .hdpc file."}]

            except sqlite3.Error as e:
                logger.error(f"SQLite error querying {hdpc_full_path}: {e}", exc_info=True)
                zenodo_response_data = [{"error": f"SQLite error reading .hdpc file: {e}"}]
            finally:
                if conn:
                    conn.close()

        return APIResponse.success(
            data={
                "submission": {
                    "id": submission.id,
                    "session_id": submission.session_id,
                    "pipeline_id": submission.pipeline_id,
                    "status": submission.status,
                    "result": submission_result_raw,  # This is the pipeline status
                    "timings": submission.timings,
                    "created_at": submission.created_at.isoformat(),
                    "completed_at": submission.completed_at.isoformat() if submission.completed_at else None,
                },
                "files": processed_file_list,
                "available_files": available_file_list,
                "file_summary": {
                    "session_file_count": len(all_file_entries),
                    "selected_file_count": sum(1 for item in all_file_entries if item.get("selected_for_submission")),
                    "processed_file_count": len(processed_file_list),
                    "available_not_processed_count": len(available_file_list),
                },
                "metadata": metadata_json,  # This is the user-submitted draft
                "zenodo_response": zenodo_response_data,  # This is the final record
                "outcomes": _submission_outcomes(submission, session, submission_result, user.id),
            }
        )
    except Exception as e:
        if conn:
            conn.close()  # Ensure connection is closed on general error
        logger.error(f"Failed to get submission detail for sub {submission_id}: {e}", exc_info=True)
        return APIResponse.server_error("Failed to retrieve submission details")


def _submission_outcomes(submission, session, result, user_id):
    from database.models import PipelineRun
    from services.submission_outcomes import summarize_outcomes
    run = PipelineRun.query.filter_by(submission_id=submission.id).order_by(PipelineRun.started_at.desc()).first()
    if run:
        return current_app.native_pipeline_service.get_pipeline_run(run.public_id, user_id)['outcomes']
    return summarize_outcomes(result if isinstance(result, dict) else {}, session)


@submission_bp.route("/<int:submission_id>/progress", methods=["GET"])
@jwt_required()
def get_user_submission_progress(submission_id):
    """Get lightweight live progress payload for a submission."""
    try:
        user = get_current_user_from_jwt()
        result = (
            db.session.query(Submission, Session)
            .join(Session, Submission.session_id == Session.id)
            .filter(Submission.id == submission_id)
            .first()
        )

        if not result or not can_view_session(result[1], user):
            return APIResponse.not_found("Submission not found or you do not have permission to view it")

        submission, _ = result
        parsed_result = None
        if submission.result:
            try:
                parsed_result = json.loads(submission.result)
            except (json.JSONDecodeError, TypeError):
                parsed_result = None

        parsed_timings = None
        if submission.timings:
            try:
                parsed_timings = json.loads(submission.timings)
            except (json.JSONDecodeError, TypeError):
                parsed_timings = None

        progress_payload = None
        error_message = None
        result_payload = None

        if submission.status == "processing":
            progress_payload = (
                parsed_result.get("progress")
                if isinstance(parsed_result, dict) and isinstance(parsed_result.get("progress"), dict)
                else {
                    "current_stage": "processing",
                    "status_message": "Processing submission",
                    "current_index": 0,
                    "total_files": 0,
                    "processed_count": 0,
                    "failed_count": 0,
                }
            )
        elif submission.status == "completed":
            result_payload = parsed_result
        elif submission.status == "failed":
            if isinstance(parsed_result, dict):
                error_message = parsed_result.get("error") or parsed_result.get("message")
                progress_payload = parsed_result.get("progress")
                result_payload = parsed_result
            if not error_message:
                error_message = submission.result

        return APIResponse.success(
            data={
                "submission_id": submission.id,
                "status": submission.status,
                "progress": progress_payload,
                "result": result_payload,
                "timings": parsed_timings,
                "error": error_message,
                "created_at": submission.created_at.isoformat() if submission.created_at else None,
                "completed_at": submission.completed_at.isoformat() if submission.completed_at else None,
            }
        )
    except Exception as e:
        logger.error(f"Failed to get submission progress for sub {submission_id}: {e}", exc_info=True)
        return APIResponse.server_error("Failed to retrieve submission progress")
