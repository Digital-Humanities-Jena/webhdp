import json
import logging
from datetime import datetime

from flask import Blueprint, request, current_app
from flask_jwt_extended import get_jwt_identity, jwt_required

from api_utils import APIResponse
from routes.access_helpers import get_session_with_permission
from exceptions import FileProcessingError, ResourceNotFoundError
from services.pipeline_execution_lock import PipelineAlreadyRunning
# Services will be accessed via current_app
from database.database import db
from database.models import PipelineRun, Session as DBSession, Submission
from workflow_status import normalize_session_state

logger = logging.getLogger(__name__)
pipeline_bp = Blueprint("pipelines", __name__)


@pipeline_bp.route("", methods=["GET"])
@jwt_required()
def list_pipelines():
    """List all available pipelines"""
    try:
        status = request.args.get("status")
        pipelines = current_app.native_pipeline_service.list_pipelines(status=status)
        return APIResponse.success(data={"pipelines": pipelines})
    except Exception as e:
        logger.error(f"Failed to list pipelines: {e}")
        return APIResponse.server_error("Failed to retrieve pipelines")


@pipeline_bp.route("/<identifier>", methods=["GET"])
@jwt_required()
def get_pipeline(identifier):
    """Get specific pipeline details with configuration steps"""
    try:
        pipeline = current_app.native_pipeline_service.get_pipeline(identifier)

        # Override enabled status based on global config
        if pipeline.get("config") and "steps" in pipeline["config"]:
            for step in pipeline["config"]["steps"]:
                if step["id"] == "fast_renderer" and not current_app.config.get("ENABLE_RENDERER", True):
                    step["enabled"] = False
                    step["disabled_by_system"] = True
                if step["id"] == "any_to_usdz" and not current_app.config.get("ENABLE_USDZ_CONVERSION", True):
                    step["enabled"] = False
                    step["disabled_by_system"] = True

        return APIResponse.success(data={"pipeline": pipeline})
    except Exception as e:
        logger.error(f"Failed to get pipeline {identifier}: {e}")
        return APIResponse.not_found(f"Pipeline {identifier} not found")


# @pipeline_bp.route("/<identifier>/execute_on_local_files", methods=["POST"])
# @jwt_required()
# def execute_pipeline(identifier):
#     """
#     Execute pipeline on specified files.
#     This route performs the full record creation and execution logic.
#     """
#     # We must import these from app.py where they are initialized
#     from app import PIPELINE_DEFINITION, PREDEFINED_PIPELINE_ID, app, project_service
#     from database.database import db
#     from database.models import Session as DBSession
#     from database.models import Submission
#     ... (rest of commented out code if needed, but I'll skip for brevity if it's too long)
#     ...

@pipeline_bp.route("/<identifier>/execute_on_local_files", methods=["POST"])
@jwt_required()
def execute_pipeline(identifier):
    from routes.pipeline_v2_routes import _enqueue_submission_pipeline_task
    from services.pipeline_run_recovery import resolve_dispatch_failure
    from services.submission_pipeline_service import execute_submission_pipeline

    data = request.get_json() or {}
    local_file_paths = data.get("local_file_paths", [])
    db_session_id = data.get("session_id")
    is_sandbox = data.get("is_sandbox", True)
    async_execution = bool(data.get("async_execution", False))
    abort_on_critical_error = bool(data.get("abort_on_critical_error", False))

    if not local_file_paths:
        return APIResponse.validation_error("No files specified for processing")
    if not db_session_id or not isinstance(db_session_id, int):
        return APIResponse.validation_error("Invalid or missing session_id")

    db_session, _, error_response = get_session_with_permission(
        db_session_id,
        permission="edit",
        require_mutable=True,
    )
    if error_response:
        return error_response
    if not db_session.hdpc_path:
        return APIResponse.validation_error("Session has no .hdpc file path")
    readiness_payload = {
        'pipeline_identifier': identifier, 'session_id': db_session_id,
        'local_file_paths': local_file_paths, 'record_ids': [], 'execution_items': [],
        'is_sandbox': is_sandbox, 'abort_on_critical_error': abort_on_critical_error,
        'async_execution': async_execution, 'expected_version': data.get('expected_version'),
        'readiness_token': data.get('readiness_token'),
    }
    pending_run = current_app.native_pipeline_service.create_pending_run(
        identifier, session_id=db_session_id, initiated_by_user_id=int(get_jwt_identity()),
        request_payload=readiness_payload,
    )
    run_id = pending_run['run_id']

    try:
        submission = Submission(session_id=db_session_id, pipeline_id=identifier, status="processing")
        db.session.add(submission)
        db.session.flush()
        submission.result = json.dumps(
            {
                "status": "processing",
                "progress": {
                    "current_stage": "queued",
                    "status_message": "Pipeline job queued",
                    "current_index": 0,
                    "total_files": len(local_file_paths),
                    "processed_count": 0,
                    "failed_count": 0,
                    "abort_on_critical_error": abort_on_critical_error,
                },
            }
        )
        run = PipelineRun.query.filter_by(public_id=run_id).first()
        if run:
            run.submission_id = submission.id
        db_session.status = normalize_session_state("submitting")
        db.session.commit()
    except Exception:
        resolve_dispatch_failure(run_id)
        raise

    if async_execution:
        try:
            task = _enqueue_submission_pipeline_task(
                submission.id,
                identifier,
                local_file_paths,
                db_session_id,
                is_sandbox,
                abort_on_critical_error,
                [], [], run_id,
            )
            return APIResponse.accepted(
                data={
                    "submission_id": submission.id,
                    "task_id": task.id,
                    "status": submission.status,
                },
                message="Pipeline execution started",
            )
        except Exception as exc:
            logger.error(f"Failed to queue async pipeline submission {submission.id}: {exc}", exc_info=True)
            resolve_dispatch_failure(run_id)
            if run and run.status.value in {'running', 'completed'}:
                return APIResponse.accepted(data={"submission_id": submission.id, "status": submission.status},
                                            message="Check this submission's status before retrying")
            submission.status = "failed"
            submission.result = json.dumps(
                {
                    "status": "failed",
                    "error": f"Failed to queue pipeline task: {str(exc)}",
                    "progress": {"current_stage": "failed"},
                }
            )
            submission.completed_at = datetime.utcnow()
            db_session.status = "failed"
            db.session.commit()
            return APIResponse.server_error("Failed to queue pipeline execution task")

    try:
        execution_output = execute_submission_pipeline(
            identifier=identifier,
            local_file_paths=local_file_paths,
            db_session_id=db_session_id,
            is_sandbox=is_sandbox,
            abort_on_critical_error=abort_on_critical_error,
            precreated_run_public_id=run_id,
        )
        result_success = bool(execution_output.get("result", {}).get("success", True))
        submission.status = "completed" if result_success else "failed"
        submission.result = json.dumps(execution_output["result"])
        submission.timings = json.dumps(execution_output["timings"])
        submission.completed_at = datetime.utcnow()

        db_session.status = "completed" if result_success else "failed"
        db_session.timings = json.dumps(execution_output["timings"])
        db.session.commit()

        return APIResponse.success(
            data={
                "submission_id": submission.id,
                "result": execution_output["result"],
                "timings": execution_output["timings"],
            }
        )
    except PipelineAlreadyRunning as exc:
        db.session.rollback()
        if run:
            resolve_dispatch_failure(run_id)
        duplicate = db.session.get(Submission, submission.id)
        if duplicate:
            db.session.delete(duplicate)
        db.session.commit()
        return APIResponse.error(exc.error_code, exc.message, exc.status_code)
    except FileProcessingError as exc:
        logger.error(f"Pipeline failed: {exc}", exc_info=True)
        db.session.rollback()
        if run:
            resolve_dispatch_failure(run_id)
        submission_to_update = db.session.get(Submission, submission.id)
        if submission_to_update:
            submission_to_update.status = "failed"
            submission_to_update.result = json.dumps(
                {"status": "failed", "error": str(exc), "progress": {"current_stage": "failed"}}
            )
            submission_to_update.completed_at = datetime.utcnow()

        db_session_to_update = db.session.get(DBSession, db_session_id)
        if db_session_to_update:
            db_session_to_update.status = "failed"
        db.session.commit()
        return APIResponse.server_error(f"Pipeline execution failed: {str(exc)}")
    except Exception as exc:
        logger.error(f"Pipeline execution failed: {exc}", exc_info=True)
        db.session.rollback()
        if run:
            resolve_dispatch_failure(run_id)

        submission_to_update = db.session.get(Submission, submission.id)
        if submission_to_update:
            submission_to_update.status = "failed"
            submission_to_update.result = json.dumps(
                {"status": "failed", "error": str(exc), "progress": {"current_stage": "failed"}}
            )
            submission_to_update.completed_at = datetime.utcnow()

        db_session_to_update = db.session.get(DBSession, db_session_id)
        if db_session_to_update:
            db_session_to_update.status = "failed"
        db.session.commit()
        return APIResponse.server_error(f"Pipeline execution failed: {str(exc)}")


@pipeline_bp.route("/executions/<execution_uuid>/status", methods=["GET"])
@jwt_required()
def get_execution_status(execution_uuid):
    """Compatibility wrapper for native pipeline run status."""
    try:
        native_run = current_app.native_pipeline_service.get_pipeline_run(execution_uuid, int(get_jwt_identity()))
        return APIResponse.success(data=native_run)
    except ResourceNotFoundError:
        return APIResponse.not_found("Pipeline run not found")
    except Exception as e:
        logger.error(f"Failed to get execution status: {e}")
        return APIResponse.server_error("Failed to retrieve execution status")
