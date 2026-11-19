# tasks.py
import os
import logging
import uuid
import time
import zipfile
import shutil
import json
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from celery_app import celery
from flask import current_app
from services.pipeline_execution_lock import PipelineAlreadyRunning
from services.directory_upload_recovery import guard_upload_coordinator

from constants import (
    CLOUD_BATCH_INPUT_DIR,
    UPLOAD_PROGRESS_FIELD,
    UPLOAD_STORAGE_MODE_FIELD,
    UPLOAD_TASK_ID_FIELD,
    UPLOAD_WORKER_GROUP_ID_FIELD,
)
from exceptions import FileProcessingError
from database.database import db
from database.models import Session as DBSession, File as DBFile, BatchFileMetadata, PipelineRun, Submission, User, UserMetadata
from services.msf_service import MSFService
from services.community_moderation_history_service import update_task_entry as update_community_moderation_task_entry
from services import zenodo_moderation_service
from services.hdpc_local_service import read_hdpc_zenodo_records
from services.hdpc_provenance_service import build_hdpc_provenance
from services.publishing_context_service import PublishingContextService
from services.session_access_service import can_edit_session, can_use_mounted_inputs, is_platform_moderator_or_admin, is_session_mutable
from services.session_batch_history_service import (
    record_task_launch as record_session_batch_task_launch,
    update_task_entry as update_session_batch_task_entry,
)
from services.session_batch_service import execute_session_batch_operation
from services.notification_service import cleanup_notifications, notify_user, send_notification_digests
from services.zenodo_batch_history_service import update_task_entry
from services.zenodo_account_retrieval_history_service import get_retrieval_entry, list_retrieval_entries, new_retrieval_id, record_retrieval_launch, update_retrieval_entry
from services.zenodo_account_retrieval_service import ZenodoAccountRetrievalRunner
from services.zenodo_oai_harvest_history_service import (
    get_harvest_entry,
    list_harvest_entries,
    new_harvest_id,
    record_harvest_launch,
    update_harvest_entry,
)
from services.zenodo_oai_harvest_service import ZenodoOaiHarvestRunner
from services.zenodo_credential_service import ZenodoCredentialService
from services.cloud_upload_service import CloudUploadService, STORAGE_MODE_LOCAL, STORAGE_MODE_PURE_CLOUD, STORAGE_MODE_CLOUD_BACKUP, STORAGE_MODE_SERVER_ONLY
from services.csv_service import CSVService
from security import safe_extract_zip
from sqlalchemy.exc import OperationalError, DatabaseError
from workflow_status import normalize_session_state

logger = logging.getLogger(__name__)
publishing_context_service = PublishingContextService()
zenodo_credential_service = ZenodoCredentialService()


def _upsert_session_metadata(session_id, field_name, field_value):
    record = UserMetadata.query.filter_by(session_id=session_id, field_name=field_name).first()
    if record:
        record.field_value = field_value
    else:
        db.session.add(UserMetadata(session_id=session_id, field_name=field_name, field_value=field_value))


def _delete_session_metadata(session_id, field_name):
    UserMetadata.query.filter_by(session_id=session_id, field_name=field_name).delete()


def _get_session_file_counts(session_id):
    from sqlalchemy import func

    rows = (
        db.session.query(DBFile.status, func.count(DBFile.id))
        .filter(DBFile.session_id == session_id)
        .group_by(DBFile.status)
        .all()
    )
    counts = {str(status or "unknown"): int(count or 0) for status, count in rows}
    uploaded = int(counts.get("uploaded", 0))
    failed = int(counts.get("failed", 0))
    pending = int(counts.get("pending", 0))
    return {
        "uploaded": uploaded,
        "failed": failed,
        "pending": pending,
        "total": uploaded + failed + pending,
    }


def _persist_upload_operation_progress(session_id, progress_payload, *, update_session_status=None):
    session = db.session.get(DBSession, session_id)
    if not session:
        return

    counts = _get_session_file_counts(session_id)
    total_files = max(int(progress_payload.get("total_files", 0) or 0), counts["total"])
    processed_count = max(int(progress_payload.get("processed_count", 0) or 0), counts["uploaded"] + counts["failed"])
    failed_count = max(int(progress_payload.get("failed_count", 0) or 0), counts["failed"])
    pending_count = max(total_files - processed_count, counts["pending"])
    percent = float(progress_payload.get("percent", 0) or 0)
    if total_files > 0:
        percent = round(min(100.0, (processed_count / total_files) * 100), 1)
    elif progress_payload.get("current_stage") == "completed":
        percent = 100.0

    normalized = {
        "current_stage": progress_payload.get("current_stage", "queued"),
        "status_message": progress_payload.get("status_message", "Upload scan in progress"),
        "current_file_name": progress_payload.get("current_file_name"),
        "current_index": int(progress_payload.get("current_index", processed_count) or 0),
        "total_files": total_files,
        "processed_count": processed_count,
        "failed_count": failed_count,
        "pending_count": pending_count,
        "matched_files": int(progress_payload.get("matched_files", total_files) or 0),
        "percent": percent,
        "warning_message": progress_payload.get("warning_message"),
        "updated_at": datetime.utcnow().isoformat(),
    }

    _upsert_session_metadata(session_id, UPLOAD_PROGRESS_FIELD, json.dumps(normalized))
    if update_session_status:
        session.status = update_session_status
    db.session.commit()


def _build_upload_completion_message(failed_count: int) -> str:
    if failed_count > 0:
        return f"Upload scan completed with {failed_count} unavailable file(s)."
    return "Upload scan and metadata registration completed."


def _build_upload_warning_message(filenames: list[str]) -> str | None:
    normalized = [str(name or "").strip() for name in filenames or [] if str(name or "").strip()]
    if not normalized:
        return None
    preview = ", ".join(normalized[:3])
    if len(normalized) > 3:
        preview = f"{preview}, and {len(normalized) - 3} more"
    return f"Missing or unreadable files: {preview}."


def _persist_submission_progress(submission_id, progress_payload):
    """Persist lightweight progress information for a submission."""
    submission = db.session.get(Submission, submission_id)
    if not submission:
        return

    normalized = {
        "current_stage": progress_payload.get("current_stage", "processing"),
        "status_message": progress_payload.get("status_message", "Processing"),
        "current_file_name": progress_payload.get("current_file_name"),
        "current_index": int(progress_payload.get("current_index", 0) or 0),
        "total_files": int(progress_payload.get("total_files", 0) or 0),
        "processed_count": int(progress_payload.get("processed_count", 0) or 0),
        "failed_count": int(progress_payload.get("failed_count", 0) or 0),
        "converter_failed_count": int(progress_payload.get("converter_failed_count", 0) or 0),
        "zenodo_draft_record_id": progress_payload.get("zenodo_draft_record_id"),
        "warning_message": progress_payload.get("warning_message"),
        "warning_code": progress_payload.get("warning_code"),
        "critical_error": bool(progress_payload.get("critical_error", False)),
        "continue_processing": progress_payload.get("continue_processing"),
        "updated_at": datetime.utcnow().isoformat(),
    }

    submission.result = json.dumps({"status": "processing", "progress": normalized})
    db.session.commit()


def _to_celery_progress(progress_payload):
    total_files = int(progress_payload.get("total_files", 0) or 0)
    processed_count = int(progress_payload.get("processed_count", 0) or 0)
    current_index = int(progress_payload.get("current_index", 0) or 0)

    if total_files > 0:
        base = max(processed_count, current_index)
        percent = int(min(99, round((base / total_files) * 100)))
    else:
        percent = 0

    if progress_payload.get("current_stage") == "completed":
        percent = 100

    return percent

@celery.task(bind=True)
def send_notification_digests_task(self, user_id=None, max_per_user=None, user_batch_size=None):
    """Send opt-in notification digest emails and write delivery audit rows."""
    try:
        return send_notification_digests(user_id=user_id, max_per_user=max_per_user, user_batch_size=user_batch_size)
    except Exception as exc:
        logger.error("Notification digest task failed: %s", exc, exc_info=True)
        raise


@celery.task(bind=True)
def cleanup_notifications_task(self, batch_size=1000):
    """Prune old notification audit/read/archive rows according to runtime config."""
    try:
        return cleanup_notifications(batch_size=batch_size)
    except Exception as exc:
        logger.error("Notification cleanup task failed: %s", exc, exc_info=True)
        raise


@celery.task(bind=True)
def finalize_session_upload(self, results, session_id):
    """
    Legacy callback for old worker-based uploads.
    Current uploads finish inside start_upload_coordinator, but queued callbacks
    should still normalize the session to the post-scan active state.
    """
    try:
        logger.info(f"Finalizing session {session_id} upload...")
        session = db.session.get(DBSession, session_id)
        if session:
            # Check if any file failed?
            # Results is a list of return values from process_single_file_task
            failed_count = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "failed")

            if failed_count > 0:
                logger.warning(f"Session {session_id} finalized with {failed_count} failed files.")
                # We still mark as ready, but maybe with a warning?
                # User can inspect files.

            counts = _get_session_file_counts(session_id)
            total_failed = max(failed_count, counts["failed"])
            completion_message = _build_upload_completion_message(total_failed)
            warning_message = None
            if total_failed > 0:
                failed_files = [
                    row.filename
                    for row in DBFile.query.filter_by(session_id=session_id, status="failed").all()
                ]
                warning_message = _build_upload_warning_message(failed_files)

            _persist_upload_operation_progress(
                session_id,
                {
                    "current_stage": "completed",
                    "status_message": completion_message,
                    "current_index": counts["uploaded"] + counts["failed"],
                    "total_files": counts["total"],
                    "processed_count": counts["uploaded"] + counts["failed"],
                    "failed_count": total_failed,
                    "warning_message": warning_message,
                },
                update_session_status="scanned",
            )
            _delete_session_metadata(session_id, UPLOAD_WORKER_GROUP_ID_FIELD)
            db.session.commit()
            logger.info(f"Session {session_id} marked as SCANNED after upload finalization.")
        else:
             logger.error(f"Session {session_id} not found during finalization.")

        return {"status": "completed", "session_id": session_id}
    except Exception as e:
        logger.error(f"Session finalization failed: {e}", exc_info=True)
        return {"status": "failed", "error": str(e)}

@celery.task(bind=True)
@guard_upload_coordinator
def start_upload_coordinator(self, session_id, zip_path, msf_path, storage_mode, msf_parse_options=None, input_directory_path=None,
                             requested_by_user_id=None):
    """
    Coordinator task to initialize a session, scan files, and register upload metadata.
    """
    try:
        def update_upload_stage(stage, status_message, progress, **extra):
            payload = {
                "current_stage": stage,
                "status_message": status_message,
                **extra,
            }
            _persist_upload_operation_progress(session_id, payload)
            self.update_state(state='PROCESSING', meta={'progress': progress, 'status': status_message})

        update_upload_stage("initializing", "Initializing upload coordinator...", 1)

        # Re-verify session exists
        db_session = db.session.get(DBSession, session_id)
        if not db_session:
            logger.error(f"Session {session_id} not found during background task")
            return {"status": "failed", "error": "Session not found"}
        if storage_mode == STORAGE_MODE_LOCAL:
            actor = db.session.get(User, requested_by_user_id or db_session.user_id)
            if not can_use_mounted_inputs(actor) or not can_edit_session(db_session, actor):
                message = "The requesting account no longer has mounted input access for this session."
                _persist_upload_operation_progress(session_id, {"current_stage": "failed", "status_message": message},
                                                    update_session_status="failed")
                return {"status": "failed", "error": message}

        uploads_path = getattr(db_session, 'uploads_path', None)
        if not uploads_path:
             uploads_path = os.path.join(db_session.session_dir, "uploads")

        _delete_session_metadata(session_id, UPLOAD_WORKER_GROUP_ID_FIELD)

        # Upload lifecycle now uses queued -> scanned for scan/registration work.
        db_session.status = normalize_session_state("queued")
        db.session.commit()
        _persist_upload_operation_progress(
            session_id,
            {
                "current_stage": "initializing",
                "status_message": "Preparing upload workspace",
                "total_files": 0,
                "processed_count": 0,
                "failed_count": 0,
            },
        )

        timings = {}

        # 1. Extraction (Coordinator handles this to avoid race conditions on extraction)
        update_upload_stage("preparing_files", "Preparing files...", 5)

        start_time = time.time()

        extract_dir = os.path.join(os.environ.get("SHARED_SESSION_PATH", "/tmp"), f"hdp_extract_{session_id}")
        os.makedirs(extract_dir, exist_ok=True)

        # Determine effective input directory
        # If input_directory_path is passed (e.g. from Local Mode selection), use it.
        # Otherwise default to extract_dir.
        effective_input_directory = input_directory_path if input_directory_path else extract_dir

        extracted_from_zip = False
        prepared_cloud_input = os.path.join(uploads_path, CLOUD_BATCH_INPUT_DIR)
        use_prepared_cloud_input = False

        try:
            if storage_mode == STORAGE_MODE_LOCAL and zip_path and os.path.exists(zip_path):
                logger.info(f"Local Mode: Using uploaded ZIP from {zip_path}")
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    safe_extract_zip(zip_ref, extract_dir)
                extracted_from_zip = True

                extracted_items = [f for f in os.listdir(extract_dir) if not f.startswith('.')]
                if len(extracted_items) == 1 and os.path.isdir(os.path.join(extract_dir, extracted_items[0])):
                    effective_input_directory = os.path.join(extract_dir, extracted_items[0])
                else:
                    effective_input_directory = extract_dir

            elif storage_mode == STORAGE_MODE_LOCAL:
                if not input_directory_path:
                    base_local_path = current_app.config.get("LOCAL_INPUT_PATH", "/data/local_input")
                    effective_input_directory = base_local_path
                logger.info(f"Local Mode: Scanning directly from {effective_input_directory}")


            elif zip_path and os.path.exists(zip_path):
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    safe_extract_zip(zip_ref, extract_dir)
                extracted_from_zip = True

                # Detect subfolder
                extracted_items = [f for f in os.listdir(extract_dir) if not f.startswith('.')]
                if len(extracted_items) == 1 and os.path.isdir(os.path.join(extract_dir, extracted_items[0])):
                    input_directory_path = os.path.join(extract_dir, extracted_items[0])
                else:
                    effective_input_directory = extract_dir
            elif storage_mode == STORAGE_MODE_PURE_CLOUD and os.path.isdir(prepared_cloud_input):
                effective_input_directory = prepared_cloud_input
                use_prepared_cloud_input = True
            else:
                if storage_mode != STORAGE_MODE_LOCAL:
                    raise FileProcessingError("ZIP file missing for non-local mode")

        except Exception as e:
            _persist_upload_operation_progress(
                session_id,
                {
                    "current_stage": "failed",
                    "status_message": f"Extraction failed: {str(e)}",
                    "failed_count": 0,
                },
                update_session_status="failed",
            )
            return {"status": "failed", "error": f"Extraction failed: {str(e)}"}

        timings["preparation"] = time.time() - start_time

        update_upload_stage(
            "analyzing_msf",
            "Analyzing MSF...",
            20,
            current_file_name=os.path.basename(msf_path) if msf_path else None,
        )

        # 2. MSF Parsing & Validation (Monolithic for speed)
        start_time = time.time()
        msf_service = MSFService()

        if not msf_path:
             _persist_upload_operation_progress(
                 session_id,
                 {
                     "current_stage": "failed",
                     "status_message": "MSF path not provided to task",
                 },
                 update_session_status="failed",
             )
             return {"status": "failed", "error": "MSF path not provided to task"}

        if not os.path.exists(msf_path):
             # Try finding it in extracted dir
             pass

        df, msf_profile = msf_service.parse_msf_file_with_profile(msf_path, parse_options=msf_parse_options)
        columns = list(df.columns)

        # In Local Mode, we might scan a huge directory.
        # Coordinator scan is okay for 10k files.
        directory_files = []
        file_path_map = {}
        for root, dirs, files in os.walk(effective_input_directory):
            for file in files:
                if os.path.join(root, file) == msf_path: continue
                ext = os.path.splitext(file)[1].lower()
                if ext not in {".xlsx", ".xls", ".csv"} and not file.startswith("."):
                     directory_files.append(file)
                     lowered = file.lower()
                     if lowered not in file_path_map:
                         file_path_map[lowered] = os.path.join(root, file)

        # Matched/Missing Logic
        validation_result = msf_service.validate_msf_against_directory(
            df,
            directory_files,
            directory_root=effective_input_directory,
        )
        detected_col, detected_confidence = msf_service.detect_filename_column(df, directory_files)
        suggested_row_index = msf_service.suggest_sample_row_index(
            df,
            validation_result.filename_column or detected_col,
        )
        msf_profile.update(
            {
                "filename_column": validation_result.filename_column or detected_col,
                "filename_confidence": round(detected_confidence, 3),
                "data_start_row": suggested_row_index,
                "suggested_row_index": suggested_row_index,
                "parse_options": msf_parse_options or msf_profile.get("parse_options", {}),
            }
        )

        if not validation_result.is_valid:
             _persist_upload_operation_progress(
                 session_id,
                 {
                     "current_stage": "failed",
                     "status_message": "MSF validation failed",
                     "warning_message": "; ".join(validation_result.errors[:5]) if validation_result.errors else None,
                 },
                 update_session_status="failed",
             )
             return {"status": "failed", "error": "MSF Validation Failed", "details": validation_result.errors}

        timings["msf_validation"] = time.time() - start_time

        # 3. Project Creation (Monolithic Step)
        update_upload_stage(
            "initializing_project",
            "Initializing HDP project...",
            40,
            matched_files=len(validation_result.matched_files or []),
        )

        start_time = time.time()
        project_service = current_app.project_service
        matched_files = validation_result.matched_files

        # Scan Options
        files_to_scan = list(matched_files) + list(validation_result.implicitly_included_files)
        matched_extensions = {
            os.path.splitext(filename)[1].lower()
            for filename in files_to_scan
            if os.path.splitext(filename)[1]
        }
        matched_extensions.update([".mtl", ".jpg", ".jpeg", ".png", ".xml", ".txt"])

        # Primary extension should prefer explicit MSF-listed source assets.
        explicit_extensions = {
            os.path.splitext(filename)[1].lower()
            for filename in matched_files
            if os.path.splitext(filename)[1]
        }
        primary_ext = ".obj"
        for pref in [".glb", ".fbx", ".obj", ".gltf", ".stl", ".ply", ".dae"]:
            if pref in explicit_extensions:
                primary_ext = pref
                break

        dynamic_scan_options = {
            "extensions": list(matched_extensions),
            "primarysourceext": primary_ext,
            "preferred_primary_files": matched_files,
            "bundling": {"enabled": True, "strategy": "stem_match"},
            "batchEntity": "hybrid",
            "obj_options": {"add_mtl": True, "add_textures": True, "archive_subdirectories": True},
        }

            # Move files to upload path if not local
        original_input_directory = effective_input_directory
        should_persist_input_files = not use_prepared_cloud_input and (storage_mode != STORAGE_MODE_LOCAL or extracted_from_zip)
        if should_persist_input_files:
            for item in os.listdir(effective_input_directory):
                s = os.path.join(effective_input_directory, item)
                d = os.path.join(uploads_path, item)
                if os.path.exists(d):
                    if os.path.isdir(d): shutil.rmtree(d)
                    else: os.remove(d)
                shutil.move(s, d)
            effective_input_directory = uploads_path


        # Call HDP Scan
        scan_data = project_service.create_and_scan(
            hdpc_path=db_session.hdpc_path,
            data_in_path=effective_input_directory,
            data_out_path=db_session.session_dir,
            project_name=f"HDP Web Session {session_id}",
            scan_options=dynamic_scan_options,
            provenance=build_hdpc_provenance(
                user=db_session.user,
                session=db_session,
                institution=db_session.institution if getattr(db_session, "institution", None) else None,
            ),
        )
        timings["project_creation"] = time.time() - start_time


        # 4. Bulk creation of file records and metadata registration.
        update_upload_stage(
            "registering_files",
            "Registering files...",
            60,
            total_files=len(matched_files),
            matched_files=len(matched_files),
        )

        start_time = time.time()
        file_metadata_map = msf_service.get_all_file_metadata(df, matched_files, validation_result.filename_column)

        file_ids = []
        unavailable_files = []
        try:
             # Create DBFile records first and validate the resolved source path.
             new_files = []
             for filename in matched_files:
                 resolved_path = file_path_map.get(filename.lower(), os.path.join(original_input_directory, filename))

                 # FIX: If we moved files, we need to update the resolved path
                 if should_persist_input_files and resolved_path.startswith(original_input_directory):
                     # Replace the base prefix
                     resolved_path = resolved_path.replace(original_input_directory, effective_input_directory, 1)

                 file_exists = os.path.isfile(resolved_path)
                 if not file_exists:
                     unavailable_files.append(filename)

                 new_file = DBFile(
                     session_id=session_id,
                     filename=filename,
                     path=resolved_path,
                     size=os.path.getsize(resolved_path) if file_exists else 0,
                     status="uploaded" if file_exists else "failed",
                 )
                 db.session.add(new_file)
                 new_files.append(new_file)

             db.session.flush() # Populate IDs without commit

             # Create Metadata records
             for file_record in new_files:
                 if file_record.filename in file_metadata_map:
                     batch_meta = BatchFileMetadata(
                         session_id=session_id,
                         filename=file_record.filename,
                         metadata_json=json.dumps(file_metadata_map[file_record.filename])
                     )
                     db.session.add(batch_meta)
                 file_ids.append(file_record.id)

             existing_profile = UserMetadata.query.filter_by(
                 session_id=session_id,
                 field_name="msf_profile",
             ).first()
             merged_profile = {}
             if existing_profile and existing_profile.field_value:
                 try:
                     existing_payload = json.loads(existing_profile.field_value)
                     if isinstance(existing_payload, dict):
                         merged_profile.update(existing_payload)
                 except (TypeError, ValueError, json.JSONDecodeError):
                     pass
             if isinstance(msf_profile, dict):
                 merged_profile.update(msf_profile)
             profile_payload = json.dumps(merged_profile or msf_profile)
             if existing_profile:
                 existing_profile.field_value = profile_payload
             else:
                 db.session.add(
                     UserMetadata(
                         session_id=session_id,
                         field_name="msf_profile",
                         field_value=profile_payload,
                     )
                 )

             timings["file_registration"] = time.time() - start_time

             # Save timings to session
             db_session.timings = json.dumps(timings)
             db.session.commit()

        except Exception as db_err:
             db.session.rollback()
             logger.error(f"Failed to save batch metadata: {db_err}")
             _persist_upload_operation_progress(
                 session_id,
                 {
                     "current_stage": "failed",
                     "status_message": f"Database Error: {db_err}",
                     "total_files": len(file_ids),
                     "matched_files": len(matched_files),
                 },
                 update_session_status="failed",
             )
             return {"status": "failed", "error": f"Database Error: {db_err}"}

        # Upload is complete once scan + metadata registration finish.
        failed_count = len(unavailable_files)
        completion_message = _build_upload_completion_message(failed_count)
        warning_message = _build_upload_warning_message(unavailable_files)
        _persist_upload_operation_progress(
            session_id,
            {
                "current_stage": "completed",
                "status_message": completion_message,
                "current_index": len(file_ids),
                "total_files": len(file_ids),
                "matched_files": len(matched_files),
                "processed_count": len(file_ids),
                "failed_count": failed_count,
                "warning_message": warning_message,
            },
            update_session_status="scanned",
        )

        return {
            'status': 'coordinator_completed',
            'file_count': len(file_ids),
            'worker_group_id': None,
            'timings': timings
        }

    except Exception as e:
        logger.error(f"Coordinator failed: {e}", exc_info=True)
        try:
            _persist_upload_operation_progress(
                session_id,
                {
                    "current_stage": "failed",
                    "status_message": f"Coordinator failed: {str(e)}",
                },
                update_session_status="failed",
            )
        except Exception:
            db.session.rollback()
        # Return failure status instead of raising to avoid Celery serialization issues
        return {"status": "failed", "error": str(e)}
    finally:
        if 'extract_dir' in locals() and os.path.exists(extract_dir):
            shutil.rmtree(extract_dir, ignore_errors=True)



@celery.task(bind=True, acks_late=True, reject_on_worker_lost=True)
def execute_playground_task(self, run_id):
    from services.pipeline_execution_lock import PipelineAlreadyRunning
    from services.pipeline_run_recovery import resolve_dispatch_failure
    from database.models import PlaygroundRun
    try:
        return current_app.native_pipeline_service.execute_playground_run(run_id)
    except PipelineAlreadyRunning as exc:
        raise self.retry(exc=exc, countdown=15, max_retries=None)
    except Exception:
        resolve_dispatch_failure(run_id, PlaygroundRun)
        raise


@celery.task(bind=True, acks_late=True, reject_on_worker_lost=True)
def execute_submission_pipeline_task(
    self,
    submission_id,
    pipeline_id,
    local_file_paths,
    db_session_id,
    is_sandbox=True,
    abort_on_critical_error=False,
    record_ids=None,
    execution_items=None,
    precreated_run_public_id=None,
):
    """Execute pipeline for a submission asynchronously with persisted progress state."""
    from services.submission_pipeline_service import execute_submission_pipeline

    def progress_callback(progress_payload):
        if submission_id is not None:
            _persist_submission_progress(submission_id, progress_payload)
        if precreated_run_public_id:
            try:
                current_app.native_pipeline_service.update_run_progress(precreated_run_public_id, progress_payload)
            except Exception as progress_exc:
                logger.warning("Failed to persist native pipeline run progress for %s: %s", precreated_run_public_id, progress_exc)
        self.update_state(
            state="PROCESSING",
            meta={
                "submission_id": submission_id,
                "progress": _to_celery_progress(progress_payload),
                "status": progress_payload.get("status_message", "Processing"),
                "progress_details": progress_payload,
            },
        )

    try:
        delivery = getattr(getattr(self, "request", None), "delivery_info", None) or {}
        if precreated_run_public_id:
            from database.models import PipelineRunStatus
            from services.pipeline_run_recovery import reconcile_run
            saved_run = PipelineRun.query.filter_by(public_id=precreated_run_public_id, session_id=db_session_id).first()
            if saved_run:
                reconcile_run(saved_run)
                if saved_run.status in {PipelineRunStatus.COMPLETED, PipelineRunStatus.FAILED}:
                    return {'submission_id': submission_id, 'run_id': saved_run.public_id,
                            'status': saved_run.status.value, 'result': json.loads(saved_run.result_json or '{}'),
                            'timings': json.loads(saved_run.timings_json or '{}')}
        if not precreated_run_public_id and delivery.get("redelivered") is True:
            # Older callers have no stable native run identity. Never replay their remote actions.
            from services.pipeline_execution_lock import session_pipeline_lock
            session_row = db.session.get(DBSession, db_session_id)
            if not session_row or not session_row.hdpc_path:
                raise FileProcessingError("Interrupted submission has no available project.")
            with session_pipeline_lock(session_row.hdpc_path):
                previous = db.session.get(Submission, submission_id) if submission_id is not None else None
                if previous and previous.status in {"completed", "failed"}:
                    return {"submission_id": submission_id, "status": previous.status,
                            "result": json.loads(previous.result or "{}"), "timings": json.loads(previous.timings or "{}")}
                raise FileProcessingError("Processing was interrupted. Existing files and drafts were kept. Review record results and HPC activity before starting another run.")
        if submission_id is not None:
            submission = db.session.get(Submission, submission_id)
            if not submission:
                raise FileProcessingError(f"Submission {submission_id} not found")

            submission.status = "processing"
            db_session = db.session.get(DBSession, db_session_id)
            if db_session:
                db_session.status = normalize_session_state("submitting")
            db.session.commit()

            _persist_submission_progress(
                submission_id,
                {
                    "current_stage": "queued",
                    "status_message": "Pipeline job started",
                    "current_index": 0,
                    "total_files": len(execution_items or []) or len(local_file_paths or []) or len(record_ids or []),
                    "processed_count": 0,
                    "failed_count": 0,
                    "abort_on_critical_error": bool(abort_on_critical_error),
                },
            )

        execution_output = execute_submission_pipeline(
            identifier=pipeline_id,
            local_file_paths=local_file_paths,
            db_session_id=db_session_id,
            is_sandbox=is_sandbox,
            abort_on_critical_error=bool(abort_on_critical_error),
            progress_callback=progress_callback,
            record_ids=record_ids,
            execution_items=execution_items,
            precreated_run_public_id=precreated_run_public_id,
        )
        result_success = bool(execution_output.get("result", {}).get("success", True))
        if execution_output.get('reused'):
            return {'submission_id': submission_id, 'run_id': precreated_run_public_id,
                    'status': 'completed' if result_success else 'failed',
                    'result': execution_output['result'], 'timings': execution_output['timings']}

        if submission_id is not None:
            submission = db.session.get(Submission, submission_id)
            if submission:
                submission.status = "completed" if result_success else "failed"
                submission.result = json.dumps(execution_output["result"])
                submission.timings = json.dumps(execution_output["timings"])
                submission.completed_at = datetime.utcnow()

        db_session = db.session.get(DBSession, db_session_id)
        if db_session:
            db_session.status = "completed" if result_success else "failed"
            db_session.timings = json.dumps(execution_output["timings"])
            notify_user(
                recipient_user_id=db_session.user_id,
                notification_type="pipeline.completed" if result_success else "pipeline.failed",
                severity="success" if result_success else "error",
                title="Pipeline completed" if result_success else "Pipeline failed",
                body=f"Session #{db_session.id} finished with status {'completed' if result_success else 'failed'}.",
                session_id=db_session.id,
                entity_type="submission",
                entity_id=submission_id,
                action_url=f"/submissions/{submission_id}" if submission_id is not None else f"/sessions/{db_session.id}/records",
                payload={"submission_id": submission_id, "session_id": db_session.id, "pipeline_id": pipeline_id},
                dedupe_key=f"submission:{submission_id}:pipeline:{'completed' if result_success else 'failed'}" if submission_id is not None else None,
            )

        db.session.commit()

        return {
            "submission_id": submission_id,
            "run_id": execution_output["result"].get("run_id"),
            "status": "completed" if result_success else "failed",
            "result": execution_output["result"],
            "timings": execution_output["timings"],
        }
    except Exception as exc:
        from services.pipeline_execution_lock import PipelineAlreadyRunning
        if isinstance(exc, PipelineAlreadyRunning):
            if precreated_run_public_id:
                raise self.retry(exc=exc, countdown=30, max_retries=None)
            raise
        logger.error(f"Async pipeline submission {submission_id} failed: {exc}", exc_info=True)
        db.session.rollback()

        try:
            if submission_id is not None:
                submission = db.session.get(Submission, submission_id)
                if submission:
                    submission.status = "failed"
                    submission.result = json.dumps(
                        {
                            "status": "failed",
                            "error": str(exc),
                            "progress": {
                                "current_stage": "failed",
                                "status_message": "Pipeline execution failed",
                                "updated_at": datetime.utcnow().isoformat(),
                            },
                        }
                    )
                    submission.completed_at = datetime.utcnow()

            db_session = db.session.get(DBSession, db_session_id)
            if db_session and not isinstance(exc, PipelineAlreadyRunning):
                db_session.status = "failed"
                notify_user(
                    recipient_user_id=db_session.user_id,
                    notification_type="pipeline.failed",
                    severity="error",
                    title="Pipeline failed",
                    body=f"Session #{db_session.id} failed during pipeline execution.",
                    session_id=db_session.id,
                    entity_type="submission",
                    entity_id=submission_id,
                    action_url=f"/submissions/{submission_id}" if submission_id is not None else f"/sessions/{db_session.id}/records",
                    payload={"submission_id": submission_id, "session_id": db_session.id, "pipeline_id": pipeline_id, "error": str(exc)},
                    dedupe_key=f"submission:{submission_id}:pipeline:failed" if submission_id is not None else None,
                )

            if precreated_run_public_id and not isinstance(exc, PipelineAlreadyRunning):
                run_row = PipelineRun.query.filter_by(public_id=precreated_run_public_id).first()
                if run_row:
                    run_row.status = "failed"
                    run_row.error_message = str(exc)
                    run_row.result_json = json.dumps({"status": "failed", "error": str(exc)})
                    run_row.completed_at = datetime.utcnow()

            db.session.commit()
        except Exception as commit_exc:
            logger.error(f"Failed to persist async failure state for submission {submission_id}: {commit_exc}")
            db.session.rollback()

        if submission_id is not None:
            _persist_submission_progress(
                submission_id,
                {
                    "current_stage": "failed",
                    "status_message": "Pipeline execution failed",
                    "current_index": 0,
                    "total_files": len(local_file_paths or []) or len(record_ids or []),
                    "processed_count": 0,
                    "failed_count": len(local_file_paths or []) or len(record_ids or []),
                    "critical_error": True,
                },
            )
        raise

@celery.task(bind=True, max_retries=10, autoretry_for=(OperationalError, DatabaseError), retry_backoff=True)
def process_single_file_task(self, file_id):
    """
    Worker task to process a single file.
    Verifies existence, validation, and updates status.
    """
    try:
        # 1. Get File
        file_record = db.session.get(DBFile, file_id)
        if not file_record:
            return # Should not happen

        session_id = file_record.session_id

        # 2. Processing Login (e.g. Verify existence, generate thumb, etc)
        if not os.path.exists(file_record.path):
            file_record.status = "failed"
            db.session.commit()
            counts = _get_session_file_counts(session_id)
            _persist_upload_operation_progress(
                session_id,
                {
                    "current_stage": "processing_files",
                    "status_message": "Processing files...",
                    "current_file_name": file_record.filename,
                    "current_index": counts["uploaded"] + counts["failed"],
                    "total_files": counts["total"],
                    "processed_count": counts["uploaded"] + counts["failed"],
                    "failed_count": counts["failed"],
                },
            )
            return {"status": "failed", "error": "File not found on disk"}

        # Simulate work or perform per-file validation if needed
        # ...

        # 3. Update Status
        file_record.status = "uploaded" # Completed
        db.session.commit()
        counts = _get_session_file_counts(session_id)
        _persist_upload_operation_progress(
            session_id,
            {
                "current_stage": "processing_files",
                "status_message": "Processing files...",
                "current_file_name": file_record.filename,
                "current_index": counts["uploaded"] + counts["failed"],
                "total_files": counts["total"],
                "processed_count": counts["uploaded"] + counts["failed"],
                "failed_count": counts["failed"],
            },
        )

        # Optional: Increment Redis counter for fast progress polling

        return {"status": "uploaded", "file_id": file_id}

    except Exception as e:
        db.session.rollback()
        # Mark as failed in DB
        try:
            file_record = db.session.get(DBFile, file_id)
            if file_record:
                session_id = file_record.session_id
                file_record.status = "failed"
                db.session.commit()
                counts = _get_session_file_counts(session_id)
                _persist_upload_operation_progress(
                    session_id,
                    {
                        "current_stage": "processing_files",
                        "status_message": "Processing files...",
                        "current_file_name": file_record.filename,
                        "current_index": counts["uploaded"] + counts["failed"],
                        "total_files": counts["total"],
                        "processed_count": counts["uploaded"] + counts["failed"],
                        "failed_count": counts["failed"],
                    },
                )
        except Exception:
            pass
        logger.error(f"Worker failed for file {file_id}: {e}")
        if isinstance(e, (OperationalError, DatabaseError)):
            raise
        return {"status": "failed", "file_id": file_id, "error": str(e)}


@celery.task(bind=True)
def execute_session_batch_operation_task(
    self,
    *,
    session_id,
    operation_type,
    target_ids=None,
    options=None,
    requested_by_user_id=None,
):
    normalized_target_ids = [int(item) for item in (target_ids or []) if str(item).isdigit()]
    options = dict(options or {})
    session_id = int(session_id)
    requested_by_user_id = int(requested_by_user_id) if str(requested_by_user_id or "").isdigit() else None

    requester = db.session.get(User, requested_by_user_id) if requested_by_user_id is not None else None
    record_session_batch_task_launch(
        task_id=self.request.id,
        session_id=session_id,
        operation_type=str(operation_type),
        target_ids=normalized_target_ids,
        options=options,
        requested_by_user_id=requested_by_user_id,
        requested_by_email=getattr(requester, "email", None),
    )

    def _emit(progress):
        self.update_state(
            state="PROGRESS",
            meta={
                "status": f"Running {operation_type}",
                "progress": dict(progress),
            },
        )
        update_session_batch_task_entry(
            self.request.id,
            state="PROGRESS",
            status=f"Running {operation_type}",
            progress=dict(progress),
        )

    try:
        session = db.session.get(DBSession, session_id)
        if not can_edit_session(session, requester) or not is_session_mutable(session):
            raise ValueError("This account no longer has edit access to the session")
        is_sandbox = bool((options or {}).get("is_sandbox", True))
        token_context = publishing_context_service.resolve_token_for_session(
            session,
            "sandbox" if is_sandbox else "production",
            actor_user_id=requester.id,
            require_credential=True,
        )

        result = execute_session_batch_operation(
            session=session,
            project_service=current_app.project_service,
            operation_type=str(operation_type),
            target_ids=normalized_target_ids,
            options=options,
            access_token=token_context.get("token"),
            progress_callback=_emit,
        )
        update_session_batch_task_entry(
            self.request.id,
            state="SUCCESS",
            status=str(result.get("status") or "completed"),
            progress=result.get("progress"),
            result=result,
            error=None,
        )
        summary = result.get("summary") or {}
        completed, failed, skipped = (int(summary.get(key, 0)) for key in ("completed", "failed", "skipped"))
        outcome_severity = "error" if failed and not completed else "warning" if failed or skipped else "success"
        outcome_title = "Session batch needs attention" if failed else "Session batch finished"
        notify_user(
            recipient_user_id=requested_by_user_id,
            notification_type="session_batch.completed",
            severity=outcome_severity,
            title=outcome_title,
            body=f"Session #{session_id}: {completed} completed, {failed} failed, {skipped} skipped. Open record actions for details.",
            actor_user_id=requested_by_user_id,
            session_id=session_id,
            entity_type="session_batch_task",
            entity_id=self.request.id,
            action_url=f"/sessions/{session_id}/records",
            payload={"task_id": self.request.id, "operation_type": operation_type, "session_id": session_id},
            dedupe_key=f"session-batch:{self.request.id}:completed",
        )
        db.session.commit()
        return result
    except Exception as exc:
        progress = {
            "total_items": len(normalized_target_ids),
            "processed": 0,
            "completed": 0,
            "skipped": 0,
            "failed": len(normalized_target_ids),
            "percent": 0,
            "current_target_id": None,
        }
        update_session_batch_task_entry(
            self.request.id,
            state="FAILURE",
            status=str(exc),
            progress=progress,
            result=None,
            error=str(exc),
        )
        notify_user(
            recipient_user_id=requested_by_user_id,
            notification_type="session_batch.failed",
            severity="error",
            title="Session batch operation failed",
            body=f"{operation_type} failed for session #{session_id}.",
            actor_user_id=requested_by_user_id,
            session_id=session_id,
            entity_type="session_batch_task",
            entity_id=self.request.id,
            action_url=f"/sessions/{session_id}/records",
            payload={"task_id": self.request.id, "operation_type": operation_type, "session_id": session_id, "error": str(exc)},
            dedupe_key=f"session-batch:{self.request.id}:failed",
        )
        db.session.commit()
        self.update_state(state="FAILURE", meta={"error": str(exc), "progress": progress})
        raise


@celery.task(bind=True)
def execute_zenodo_batch_community_operation(
    self,
    *,
    operation,
    remove_mode=None,
    community_identifier=None,
    selected_records=None,
    requested_by_user_id=None,
):
    requester = db.session.get(User, requested_by_user_id) if requested_by_user_id else None
    if not requester or not requester.is_verified or requester.force_password_change or not is_platform_moderator_or_admin(requester):
        raise ValueError("A verified moderator or administrator must initiate this operation")
    selected_records = list(selected_records or [])
    total_records = len(selected_records)
    grouped_records = defaultdict(list)
    for item in selected_records:
        try:
            grouped_records[int(item.get("session_id"))].append(dict(item))
        except (TypeError, ValueError):
            continue

    progress = {
        "total_records": total_records,
        "processed": 0,
        "succeeded": 0,
        "unchanged": 0,
        "ineligible": 0,
        "failed": 0,
        "rate_limited_waits": 0,
        "percent": 0,
        "current_record": None,
    }
    results = []

    def _emit_status(status_message, *, current_record=None, current_result=None):
        if total_records > 0:
            progress["percent"] = int(round((progress["processed"] / total_records) * 100))
        else:
            progress["percent"] = 100
        progress["current_record"] = current_record
        meta = {
            "status": status_message,
            "progress": dict(progress),
        }
        if current_result is not None:
            meta["result"] = current_result
        self.update_state(state="PROGRESS", meta=meta)

    def _resolve_record_environment(session_row, record_item):
        raw_is_sandbox = record_item.get("is_sandbox")
        if raw_is_sandbox in (None, ""):
            session_environment = str(getattr(session_row, "default_zenodo_environment", None) or "sandbox").strip().lower()
            return "production" if session_environment == "production" else "sandbox"
        if isinstance(raw_is_sandbox, bool):
            return "sandbox" if raw_is_sandbox else "production"
        return "sandbox" if str(raw_is_sandbox).strip().lower() in {"1", "true", "yes", "on"} else "production"

    _emit_status("Queued Zenodo community operation")

    from routes.session_routes import _resolve_existing_hdpc_path

    try:
        for session_id in sorted(grouped_records.keys()):
            session = db.session.get(DBSession, session_id)
            session_records = grouped_records[session_id]
            token_context_by_environment = {}
            if not session:
                for item in session_records:
                    result_entry = {
                        "session_id": session_id,
                        "local_record_id": item.get("local_record_id"),
                        "record_title": item.get("record_title"),
                        "status": "failed",
                        "message": "Session not found",
                        "rate_limited_waits": 0,
                    }
                    progress["processed"] += 1
                    progress["failed"] += 1
                    results.append(result_entry)
                    _emit_status("Session not found", current_record=result_entry, current_result=result_entry)
                continue

            hdpc_path = _resolve_existing_hdpc_path(getattr(session, "hdpc_path", None)) or getattr(session, "hdpc_path", None)
            if not hdpc_path:
                for item in session_records:
                    result_entry = {
                        "session_id": session_id,
                        "local_record_id": item.get("local_record_id"),
                        "record_title": item.get("record_title"),
                        "status": "failed",
                        "message": "HDPC project path is unavailable",
                        "rate_limited_waits": 0,
                    }
                    progress["processed"] += 1
                    progress["failed"] += 1
                    results.append(result_entry)
                    _emit_status("HDPC project unavailable", current_record=result_entry, current_result=result_entry)
                continue

            for item in session_records:
                local_record_id = int(item.get("local_record_id"))
                result_entry = {
                    "session_id": session_id,
                    "local_record_id": local_record_id,
                    "record_title": item.get("record_title"),
                    "record_status": item.get("record_status"),
                    "zenodo_record_id": item.get("zenodo_record_id"),
                    "status": "failed",
                    "message": "",
                    "before_communities": list(item.get("communities_normalized") or []),
                    "after_communities": None,
                    "rate_limited_waits": 0,
                }
                eligibility_key = (
                    "append_if_missing"
                    if operation == "append_if_missing"
                    else "remove_one"
                    if remove_mode == "one"
                    else "remove_all"
                )
                eligibility = ((item.get("operation_eligibility") or {}).get(eligibility_key) or {})
                if not eligibility.get("eligible"):
                    result_entry["status"] = "ineligible"
                    result_entry["message"] = str(eligibility.get("reason") or "Record is not eligible for this operation")
                    progress["processed"] += 1
                    progress["ineligible"] += 1
                    results.append(result_entry)
                    _emit_status("Skipping ineligible record", current_record=result_entry, current_result=result_entry)
                    continue

                try:
                    record_environment = _resolve_record_environment(session, item)
                    token_context = token_context_by_environment.get(record_environment)
                    if token_context is None:
                        token_context = publishing_context_service.resolve_token_for_session(
                            session, record_environment, actor_user_id=requester.id, require_credential=True,
                        )
                        token_context_by_environment[record_environment] = token_context
                    if operation == "append_if_missing":
                        api_response = current_app.project_service.append_community_to_record(
                            local_record_id=local_record_id,
                            community_identifier=str(community_identifier or ""),
                            hdpc_path=hdpc_path,
                            access_token=token_context.get("token"),
                        )
                    else:
                        api_response = current_app.project_service.remove_community_from_record(
                            local_record_id=local_record_id,
                            community_identifier=str(community_identifier or "") if remove_mode == "one" else None,
                            remove_all=bool(remove_mode == "all"),
                            hdpc_path=hdpc_path,
                            access_token=token_context.get("token"),
                        )
                    api_result = api_response.get("result") if isinstance(api_response, dict) else {}
                    api_result = api_result if isinstance(api_result, dict) else {}
                    api_status = str(api_result.get("status") or "failed").strip().lower()
                    result_entry["status"] = api_status
                    result_entry["message"] = str(api_result.get("message") or "")
                    result_entry["after_communities"] = api_result.get("communities_after")
                    result_entry["rate_limited_waits"] = int(api_result.get("rate_limited_waits") or 0)
                    progress["rate_limited_waits"] += int(api_result.get("rate_limited_waits") or 0)

                    progress["processed"] += 1
                    if api_status == "succeeded":
                        progress["succeeded"] += 1
                    elif api_status == "unchanged":
                        progress["unchanged"] += 1
                    elif api_status in {"ineligible", "failed_capability_check"}:
                        progress["ineligible"] += 1
                    else:
                        progress["failed"] += 1
                except Exception as exc:
                    logger.error(
                        "Zenodo batch community operation failed for session %s record %s: %s",
                        session_id,
                        local_record_id,
                        exc,
                        exc_info=True,
                    )
                    progress["processed"] += 1
                    progress["failed"] += 1
                    result_entry["status"] = "failed"
                    result_entry["message"] = str(exc)

                results.append(result_entry)
                _emit_status("Processing Zenodo community operation", current_record=result_entry, current_result=result_entry)

        progress["percent"] = 100
        progress["current_record"] = None
        final_result = {
            "status": "completed",
            "operation": operation,
            "remove_mode": remove_mode,
            "community_identifier": community_identifier,
            "progress": dict(progress),
            "results": results,
            "summary": {
                "total_records": total_records,
                "processed": progress["processed"],
                "succeeded": progress["succeeded"],
                "unchanged": progress["unchanged"],
                "ineligible": progress["ineligible"],
                "failed": progress["failed"],
                "rate_limited_waits": progress["rate_limited_waits"],
            },
        }
        update_task_entry(
            self.request.id,
            state="SUCCESS",
            status=str(final_result.get("status") or "completed"),
            progress=final_result.get("progress"),
            result=final_result,
            error=None,
        )
        return final_result
    except Exception as exc:
        logger.error("Zenodo batch community operation task failed: %s", exc, exc_info=True)
        update_task_entry(
            self.request.id,
            state="FAILURE",
            status=str(exc),
            progress=dict(progress),
            result=None,
            error=str(exc),
        )
        self.update_state(state="FAILURE", meta={"error": str(exc), "progress": dict(progress)})
        raise


@celery.task(bind=True)
def execute_zenodo_account_retrieval(
    self,
    *,
    retrieval_id,
    credential_id,
    requester_user_id,
):
    task_id = getattr(getattr(self, "request", None), "id", None) or getattr(self, "id", None)
    if task_id:
        update_retrieval_entry(str(retrieval_id), task_id=str(task_id))
    try:
        credential = zenodo_credential_service.require_credential_by_id(int(credential_id))
        zenodo_credential_service._ensure_accessible_by_user(credential, int(requester_user_id))
        requester = db.session.get(User, int(requester_user_id))
        if requester is None:
            raise ValueError("Requesting user not found")
        token = zenodo_credential_service.decrypt_value(credential)
        if not token:
            raise ValueError("Zenodo credential token is empty")
        entry = get_retrieval_entry(str(retrieval_id)) or {}
        options = entry.get("options") if isinstance(entry.get("options"), dict) else {}
        runner = ZenodoAccountRetrievalRunner(
            retrieval_id=str(retrieval_id),
            credential=credential,
            requester=requester,
            initial_window_days=int(options.get("initial_window_days") or 31),
            request_retries=int(options.get("request_retries") if options.get("request_retries") is not None else 2),
            request_timeout_seconds=float(options.get("request_timeout_seconds") or 30),
        )
        return runner.run(token=token, task_self=self)
    except Exception as exc:
        logger.error("Zenodo account retrieval task failed for %s: %s", retrieval_id, exc, exc_info=True)
        update_retrieval_entry(
            str(retrieval_id),
            state="FAILURE",
            status=str(exc),
            error=str(exc),
        )
        raise


def _parse_schedule_datetime(value):
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _shift_schedule_datetime(value, hours):
    parsed = _parse_schedule_datetime(value)
    if parsed is None:
        return None
    return (parsed - timedelta(hours=max(0, int(hours or 0)))).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _next_schedule_datetime(frequency):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    if frequency == "daily":
        delta = timedelta(days=1)
    elif frequency == "monthly":
        delta = timedelta(days=30)
    else:
        delta = timedelta(days=7)
    return (now + delta).isoformat().replace("+00:00", "Z")


@celery.task(bind=True)
def execute_due_zenodo_account_retrieval_schedules(self):
    launched = []
    now = datetime.now(timezone.utc)
    for parent in list_retrieval_entries(limit=50):
        if str(parent.get("state") or "").upper() != "SUCCESS":
            continue
        collection = parent.get("collection") if isinstance(parent.get("collection"), dict) else {}
        schedule = collection.get("schedule") if isinstance(collection.get("schedule"), dict) else {}
        if not schedule.get("enabled"):
            continue
        next_run = _parse_schedule_datetime(schedule.get("next_run_at"))
        if next_run is None or next_run > now:
            continue
        latest = collection.get("latest_created") or collection.get("latest_modified")
        start_datetime = _shift_schedule_datetime(latest, schedule.get("incremental_overlap_hours", 24))
        if not latest or not start_datetime:
            continue
        credential_id = int(parent.get("credential_id") or 0)
        requester_id = int((parent.get("requested_by") or {}).get("user_id") or 0)
        credential = zenodo_credential_service.require_credential_by_id(credential_id)
        requester = db.session.get(User, requester_id)
        if requester is None:
            continue
        retrieval_id = new_retrieval_id()
        record_retrieval_launch(
            retrieval_id=retrieval_id,
            task_id=None,
            credential_id=credential_id,
            environment=str(parent.get("environment") or credential.environment or "production"),
            requested_by_user_id=requester_id,
            requested_by_email=requester.email,
            credential_summary={
                "credential_id": credential_id,
                "name": credential.name,
                "environment": credential.environment,
                "owner_type": credential.owner_type,
                "owner_id": int(credential.owner_id) if credential.owner_id is not None else None,
                "masked_preview": credential.masked_preview,
            },
            max_records=schedule.get("max_records"),
            start_datetime=start_datetime,
            end_datetime=None,
            sync_mode="incremental",
            parent_retrieval_id=str(parent.get("retrieval_id") or ""),
            incremental_since=latest,
            incremental_overlap_hours=int(schedule.get("incremental_overlap_hours") or 24),
        )
        child = execute_zenodo_account_retrieval.delay(
            retrieval_id=retrieval_id,
            credential_id=credential_id,
            requester_user_id=requester_id,
        )
        launched.append({"retrieval_id": retrieval_id, "parent_retrieval_id": parent.get("retrieval_id"), "task_id": getattr(child, "id", None)})
        schedule["last_queued_at"] = now.isoformat().replace("+00:00", "Z")
        schedule["next_run_at"] = _next_schedule_datetime(schedule.get("frequency") or "weekly")
        update_retrieval_entry(str(parent.get("retrieval_id") or ""), collection={"schedule": schedule})
    return {"launched": launched, "count": len(launched)}


@celery.task(bind=True)
def execute_zenodo_oai_harvest(
    self,
    *,
    harvest_id,
    requester_user_id,
):
    task_id = getattr(getattr(self, "request", None), "id", None) or getattr(self, "id", None)
    if task_id:
        update_harvest_entry(str(harvest_id), task_id=str(task_id))
    try:
        requester = db.session.get(User, int(requester_user_id))
        if requester is None:
            raise ValueError("Requesting user not found")
        entry = get_harvest_entry(str(harvest_id)) or {}
        options = entry.get("options") if isinstance(entry.get("options"), dict) else {}
        runner = ZenodoOaiHarvestRunner(
            harvest_id=str(harvest_id),
            requester=requester,
            request_retries=int(options.get("request_retries") if options.get("request_retries") is not None else 2),
            request_timeout_seconds=float(options.get("request_timeout_seconds") or 30),
        )
        return runner.run(task_self=self)
    except Exception as exc:
        logger.error("Zenodo OAI harvest task failed for %s: %s", harvest_id, exc, exc_info=True)
        update_harvest_entry(str(harvest_id), state="FAILURE", status=str(exc), error=str(exc))
        raise


@celery.task(bind=True)
def execute_due_zenodo_oai_harvest_schedules(self):
    launched = []
    now = datetime.now(timezone.utc)
    for parent in list_harvest_entries(limit=50):
        if str(parent.get("state") or "").upper() != "SUCCESS":
            continue
        collection = parent.get("collection") if isinstance(parent.get("collection"), dict) else {}
        schedule = collection.get("schedule") if isinstance(collection.get("schedule"), dict) else {}
        if not schedule.get("enabled"):
            continue
        next_run = _parse_schedule_datetime(schedule.get("next_run_at"))
        if next_run is None or next_run > now:
            continue
        latest = collection.get("latest_datestamp")
        start_datetime = _shift_schedule_datetime(latest, schedule.get("incremental_overlap_hours", 24))
        if not latest or not start_datetime:
            continue
        requester_id = int((parent.get("requested_by") or {}).get("user_id") or 0)
        requester = db.session.get(User, requester_id)
        if requester is None:
            continue
        options = parent.get("options") if isinstance(parent.get("options"), dict) else {}
        harvest_id = new_harvest_id()
        record_harvest_launch(
            harvest_id=harvest_id,
            task_id=None,
            requested_by_user_id=requester_id,
            requested_by_email=requester.email,
            base_url=str(options.get("base_url") or "https://zenodo.org/oai2d"),
            set_spec=str(options.get("set_spec") or "user-3dbigdataspace"),
            metadata_prefix=str(options.get("metadata_prefix") or "oai_datacite"),
            max_records=schedule.get("max_records"),
            from_datetime=start_datetime,
            until_datetime=None,
            sync_mode="incremental",
            parent_harvest_id=str(parent.get("harvest_id") or ""),
            incremental_since=latest,
            incremental_overlap_hours=int(schedule.get("incremental_overlap_hours") or 24),
        )
        child = execute_zenodo_oai_harvest.delay(harvest_id=harvest_id, requester_user_id=requester_id)
        launched.append({"harvest_id": harvest_id, "parent_harvest_id": parent.get("harvest_id"), "task_id": getattr(child, "id", None)})
        schedule["last_queued_at"] = now.isoformat().replace("+00:00", "Z")
        schedule["next_run_at"] = _next_schedule_datetime(schedule.get("frequency") or "weekly")
        update_harvest_entry(str(parent.get("harvest_id") or ""), collection={"schedule": schedule})
    return {"launched": launched, "count": len(launched)}


@celery.task(bind=True)
def execute_community_migration_job(self, *, job_id):
    try:
        from services.community_migration_service import CommunityMigrationService

        return CommunityMigrationService().execute_job(str(job_id), task_self=self)
    except Exception as exc:
        logger.error("Community migration job %s failed: %s", job_id, exc, exc_info=True)
        try:
            from database.models import CommunityMigrationJob

            job = CommunityMigrationJob.query.filter_by(public_id=str(job_id)).first()
            if job is not None:
                job.state = "FAILURE"
                job.phase = "failed"
                job.error = str(exc)
                job.updated_at = datetime.utcnow()
                db.session.commit()
        except Exception:
            db.session.rollback()
        raise


def _execute_community_moderation_batch_impl(
    task_self,
    *,
    action,
    community_identifier,
    note=None,
    selected_requests=None,
):
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"accept", "decline"}:
        raise ValueError("action must be 'accept' or 'decline'")

    community_value = str(community_identifier or "").strip()
    if not community_value:
        raise ValueError("community_identifier is required")

    selected_requests = [dict(item) for item in (selected_requests or []) if isinstance(item, dict)]
    total_requests = len(selected_requests)
    progress = {
        "total_requests": total_requests,
        "processed": 0,
        "accepted": 0,
        "declined": 0,
        "failed": 0,
        "rate_limited_waits": 0,
        "percent": 0,
        "current_request": None,
    }
    results = []

    def _emit_status(status_message, *, current_request=None, current_result=None):
        if total_requests > 0:
            progress["percent"] = int(round((progress["processed"] / total_requests) * 100))
        else:
            progress["percent"] = 100
        progress["current_request"] = current_request
        meta = {
            "status": status_message,
            "progress": dict(progress),
        }
        if current_result is not None:
            meta["result"] = current_result
        task_self.update_state(state="PROGRESS", meta=meta)

    _emit_status("Queued community moderation batch")

    try:
        for item in selected_requests:
            request_id = str(item.get("request_id") or "").strip()
            result_entry = {
                "request_id": request_id,
                "number": item.get("number"),
                "title": item.get("title"),
                "type": item.get("type"),
                "status": "failed",
                "message": "",
                "community_identifier": community_value,
                "rate_limited_waits": 0,
            }
            wait_stats = {"count": 0}

            def _wait_callback(reason: str, sleep_time: float, response=None):
                wait_stats["count"] += 1
                current_app.logger.warning(
                    "Zenodo moderation wait (%s) for request %s: %.2fs",
                    reason,
                    request_id,
                    sleep_time,
                )

            try:
                updated_request = zenodo_moderation_service.perform_request_action(
                    request_id,
                    normalized_action,
                    note=note,
                    wait_callback=_wait_callback,
                )
                result_entry["status"] = str(updated_request.get("status") or normalized_action)
                result_entry["message"] = f"Request {normalized_action}ed successfully."
                result_entry["updated_request"] = updated_request
                result_entry["rate_limited_waits"] = int(wait_stats["count"])
                progress["processed"] += 1
                progress["rate_limited_waits"] += int(wait_stats["count"])
                if normalized_action == "accept":
                    progress["accepted"] += 1
                else:
                    progress["declined"] += 1
            except Exception as exc:
                logger.error("Community moderation action failed for request %s: %s", request_id, exc, exc_info=True)
                progress["processed"] += 1
                progress["failed"] += 1
                progress["rate_limited_waits"] += int(wait_stats["count"])
                result_entry["status"] = "failed"
                result_entry["message"] = str(exc)
                result_entry["rate_limited_waits"] = int(wait_stats["count"])

            results.append(result_entry)
            _emit_status("Processing community moderation batch", current_request=result_entry, current_result=result_entry)

        progress["percent"] = 100
        progress["current_request"] = None
        final_result = {
            "status": "completed",
            "action": normalized_action,
            "community_identifier": community_value,
            "note_present": bool(str(note or "").strip()),
            "progress": dict(progress),
            "results": results,
            "summary": {
                "total_requests": total_requests,
                "processed": progress["processed"],
                "accepted": progress["accepted"],
                "declined": progress["declined"],
                "failed": progress["failed"],
                "rate_limited_waits": progress["rate_limited_waits"],
            },
        }
        update_community_moderation_task_entry(
            task_self.request.id,
            state="SUCCESS",
            status=str(final_result.get("status") or "completed"),
            progress=final_result.get("progress"),
            result=final_result,
            error=None,
        )
        return final_result
    except Exception as exc:
        logger.error("Community moderation batch task failed: %s", exc, exc_info=True)
        update_community_moderation_task_entry(
            task_self.request.id,
            state="FAILURE",
            status=str(exc),
            progress=dict(progress),
            result=None,
            error=str(exc),
        )
        task_self.update_state(state="FAILURE", meta={"error": str(exc), "progress": dict(progress)})
        raise


@celery.task(bind=True)
def execute_community_moderation_batch(
    self,
    *,
    action,
    community_identifier,
    note=None,
    selected_requests=None,
):
    return _execute_community_moderation_batch_impl(
        self,
        action=action,
        community_identifier=community_identifier,
        note=note,
        selected_requests=selected_requests,
    )


@celery.task(bind=True)
def execute_community_moderation_sweep(self, *, job_id):
    try:
        from services.community_moderation_sweep_service import CommunityModerationSweepService

        return CommunityModerationSweepService().execute_job(str(job_id), task_self=self)
    except Exception as exc:
        logger.error("Community moderation sweep %s failed: %s", job_id, exc, exc_info=True)
        try:
            from database.models import CommunityModerationSweepJob

            job = CommunityModerationSweepJob.query.filter_by(public_id=str(job_id)).first()
            if job is not None:
                job.state = "FAILURE"
                job.phase = "failed"
                job.error = str(exc)
                job.last_error = str(exc)
                job.completed_at = datetime.utcnow()
                job.updated_at = datetime.utcnow()
                db.session.commit()
        except Exception:
            db.session.rollback()
        raise


@celery.task(bind=True)
def execute_pipeline_task(self, pipeline_id, record_ids, is_sandbox):
    """
    Background task to execute a pipeline on rate-limited APIs (Zenodo).
    Chunks parsing into batches of 50 to avoid timeouts.
    """
    from services.pipeline_service import PipelineService

    pipeline_service = current_app.pipeline_service
    project_service = current_app.project_service

    # 1. Check if pipeline has publishing enabled
    # We want granular updates if publishing is enabled
    check_publishing = True
    try:
        pipeline_info = pipeline_service.get(pipeline_id)
        # If publish step allows it (checking both enabled flag and step presence)
        if not pipeline_info.get("zenodoPublishStepEnabled", False):
           check_publishing = False
    except Exception:
        pass # Assume true to be safe for tracking

    # Batch size config - Optimized for efficiency (User Request)
    # We will process 50 at a time, and fetch metadata ONCE per batch.
    BATCH_SIZE = 50

    # Try to find session_id from records to update CSV
    session_id = None
    try:
        if record_ids:
            first_file = db.session.get(DBFile, record_ids[0])
            if first_file:
                session_id = first_file.session_id

        # Initialize CSV Service
        csv_service = None
        if session_id:
            session = db.session.get(DBSession, session_id)
            if session:
                csv_service = CSVService(session.session_dir)

    except Exception as e:
        logger.warning(f"Could not initialize CSV service: {e}")

    try:
        total_records = len(record_ids)
        logger.info(f"Starting batched pipeline execution for {total_records} records (Target Batch Size: {BATCH_SIZE})")

        chunked_results = []

        # --- SMART BATCHING LOGIC ---
        # We must NOT split files that belong to the same logical record (Zenodo Deposition).
        # We assume files with the same 'title' in metadata belong to the same record.

        # 1. Fetch metadata for all records to determine groups
        record_groups = {} # title -> list of file_ids

        # Optimization: Fetch all needed metadata in one query or loop
        # Since we have record_ids (file_ids), we can look up BatchFileMetadata via filename?
        # Actually Record ID is DBFile ID. DBFile has filename. BatchFileMetadata has filename.
        # We need to join them.

        try:
            # Get all DBFile objects first to map ID -> Filename
            db_files = db.session.query(DBFile).filter(DBFile.id.in_(record_ids)).all()
            id_map = {f.id: f.filename for f in db_files}

            # Get all Metadata objects
            filenames = [f.filename for f in db_files]
            if filenames and session_id:
                metas = db.session.query(BatchFileMetadata).filter(
                    BatchFileMetadata.session_id == session_id,
                    BatchFileMetadata.filename.in_(filenames)
                ).all()

                meta_map = {m.filename: json.loads(m.metadata_json) for m in metas}

                # Group IDs
                for r_id in record_ids:
                    fname = id_map.get(r_id)
                    title = "Unknown"
                    if fname and fname in meta_map:
                        title = meta_map[fname].get("title", fname) # Fallback to filename if no title
                    elif fname:
                        title = fname # Fallback to filename if no metadata

                    if title not in record_groups:
                        record_groups[title] = []
                    record_groups[title].append(r_id)
            else:
                # Fallback: Group by ID (single file groups)
                for r_id in record_ids:
                    record_groups[str(r_id)] = [r_id]

        except Exception as e:
            logger.error(f"Failed to group records for batching: {e}")
            # Fallback to simple chunking if grouping fails
            record_groups = {str(i): [r_id] for i, r_id in enumerate(record_ids)}

        # 2. Create Batches from Groups
        batches = []
        current_batch = []
        current_count = 0

        for title, group_ids in record_groups.items():
            # If adding this group exceeds batch size significantly, start new batch
            # We allow going slightly over (e.g. 55) to keep group together
            if current_count + len(group_ids) > BATCH_SIZE and current_count > 0:
                batches.append(current_batch)
                current_batch = []
                current_count = 0

            current_batch.extend(group_ids)
            current_count += len(group_ids)

        if current_batch:
            batches.append(current_batch)

        # --- EXECUTE BATCHES ---

        total_batches = len(batches)
        for i, batch_ids in enumerate(batches):
            chunk_num = i + 1

            logger.info(f"Processing Batch {chunk_num}/{total_batches} ({len(batch_ids)} records)...")
            self.update_state(state='PROCESSING', meta={
                'progress': int((i / total_batches) * 100),
                'status': f'Executing batch {chunk_num}/{total_batches}...'
            })

            # Execute Batch
            # 1-hour timeout per batch should be plenty (for ~50 items)
            batch_result = pipeline_service.execute(
                pipeline_id=pipeline_id,
                record_ids=batch_ids,
                is_sandbox=is_sandbox,
                timeout=3600
            )

            chunked_results.append(batch_result)

            # Update CSV efficiently (Once per batch)
            if csv_service:
                csv_records = []

                # Retrieve Session to get HDPC path (needed for inspect)
                session_obj = db.session.get(DBSession, session_id) if session_id else None

                # Fetch fresh Zenodo info lookup map
                zenodo_records_map = {}
                if check_publishing and session_obj:
                    try:
                         for record in read_hdpc_zenodo_records(session_obj.hdpc_path):
                             sid = record.get("source_file_id")
                             if sid:
                                 zenodo_records_map[str(sid)] = record
                    except Exception as ins_err:
                        logger.warning(f"Failed to inspect project for CSV update: {ins_err}")

                for rid in batch_ids:
                    f = db.session.get(DBFile, rid)
                    if f:
                        # Extract info
                        doi = ""
                        links = ""

                        # Find matched Zenodo record in our lookup map
                        if str(rid) in zenodo_records_map:
                            z_rec = zenodo_records_map[str(rid)]
                            doi = z_rec.get("doi", "")
                            # Links usually in z_rec.get("links", {})
                            links = z_rec.get("links", z_rec.get("record_url", ""))

                        csv_records.append({
                            "id": rid,
                            "filename": f.filename,
                            "doi": doi,
                            "links": links
                        })

                csv_service.update_tracking_csv(csv_records)

        return {'status': 'completed', 'result': chunked_results, 'batch_count': total_batches}

    except Exception as e:
        logger.error(f"Pipeline execution task failed: {e}", exc_info=True)
        self.update_state(state='FAILURE', meta={'error': str(e)})
        raise e
