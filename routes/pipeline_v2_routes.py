import logging
import json
import os
from functools import wraps

from flask import Blueprint, current_app, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required

from api_utils import APIResponse
from database.database import db
from database.models import User, UserRole
from exceptions import SecurityError, ValidationError
from uuid import UUID
from routes.admin_routes import require_admin
from routes.access_helpers import get_session_with_permission
from schemas.native_pipeline_schemas import PipelineExecutionRequestSchema
from schemas.native_pipeline_schemas import PlaygroundExecutionRequestSchema
from services.pipeline_platform_service import get_pipeline_platform_contract
from services.submission_pipeline_service import execute_submission_pipeline

logger = logging.getLogger(__name__)

pipeline_v2_bp = Blueprint("pipeline_v2", __name__)


def _enqueue_submission_pipeline_task(*args):
    from tasks import execute_submission_pipeline_task
    from database.models import PipelineRun, PipelineRunStatus
    from services.pipeline_run_recovery import dispatch_lock
    run_id = args[-1]
    row = PipelineRun.query.filter_by(public_id=run_id).one()
    with dispatch_lock(row):
        db.session.refresh(row)
        if row.status != PipelineRunStatus.PENDING:
            raise ValidationError('This run is no longer queued.')
        payload = json.loads(row.request_json)
        payload['_dispatch'].update(task_id=run_id)
        row.request_json = json.dumps(payload)
        db.session.commit()
        task = execute_submission_pipeline_task.apply_async(args=args, task_id=run_id)
        db.session.refresh(row)
        payload = json.loads(row.request_json)
        payload['_dispatch'].update(state='queued', task_id=task.id)
        row.request_json = json.dumps(payload)
        db.session.commit()
        return task


def _enqueue_playground_task(run_id):
    from tasks import execute_playground_task
    from database.models import PlaygroundRun, PipelineRunStatus
    from services.pipeline_run_recovery import dispatch_lock
    row = PlaygroundRun.query.filter_by(public_id=run_id).one()
    with dispatch_lock(row):
        db.session.refresh(row)
        if row.status != PipelineRunStatus.PENDING:
            raise ValidationError('This component run is no longer queued.')
        payload = json.loads(row.request_json)
        payload['_dispatch'].update(task_id=run_id)
        row.request_json = json.dumps(payload)
        db.session.commit()
        task = execute_playground_task.apply_async(args=[run_id], task_id=run_id)
        db.session.refresh(row)
        payload = json.loads(row.request_json)
        payload['_dispatch'].update(state='queued', task_id=task.id)
        row.request_json = json.dumps(payload)
        db.session.commit()
        return task


def _current_user_can_author_pipelines() -> bool:
    user_id = get_jwt_identity()
    if user_id is None:
        return False
    user = db.session.get(User, int(user_id))
    if user is None:
        return False
    if user.role == UserRole.ADMIN:
        return True
    return user.has_capability("native_pipeline_author")


def require_pipeline_author(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if os.environ.get("WEBHDP_CORE_ONLY", "false").lower() == "true":
            return APIResponse.error("FEATURE_DISABLED", "Pipeline authoring is disabled in the core workflow profile.", 403)
        if not _current_user_can_author_pipelines():
            raise SecurityError("Pipeline author access required")
        return func(*args, **kwargs)

    return wrapper


@pipeline_v2_bp.route("/platform-support", methods=["GET"])
@jwt_required()
def pipeline_platform_support_v2():
    return APIResponse.success(
        data=get_pipeline_platform_contract(),
        message="Native pipeline platform support contract retrieved",
    )


@pipeline_v2_bp.route("/components", methods=["GET"])
@jwt_required()
def list_components_v2():
    playground_only = str(request.args.get("playground_only", "")).strip().lower() in {"1", "true", "yes", "on"}
    components = current_app.native_pipeline_service.list_components(playground_only=playground_only)
    return APIResponse.success(data={"components": components})


@pipeline_v2_bp.route("/components/validate", methods=["POST"])
@jwt_required()
@require_admin
def validate_component_manifest_v2():
    data = request.get_json() or {}
    component_path = data.get("component_path")
    if not component_path:
        return APIResponse.validation_error("component_path is required")
    validation = current_app.native_pipeline_service.validate_component_manifest_path(component_path)
    return APIResponse.success(data=validation)


@pipeline_v2_bp.route("/components/import", methods=["POST"])
@jwt_required()
@require_admin
def import_component_v2():
    data = request.get_json() or {}
    component_path = data.get("component_path")
    if not component_path:
        return APIResponse.validation_error("component_path is required")
    imported = current_app.native_pipeline_service.import_component_from_path(component_path)
    return APIResponse.created(data={"component": imported}, message="Component imported")


@pipeline_v2_bp.route("/pipelines", methods=["GET"])
@jwt_required()
def list_pipelines_v2():
    status = request.args.get("status")
    pipelines = current_app.native_pipeline_service.list_pipelines(status=status)
    return APIResponse.success(data={"pipelines": pipelines})


@pipeline_v2_bp.route("/pipelines/validate", methods=["POST"])
@jwt_required()
@require_pipeline_author
def validate_pipeline_v2():
    data = request.get_json() or {}
    validation = current_app.native_pipeline_service.validate_pipeline_config(data)
    return APIResponse.success(data=validation)


@pipeline_v2_bp.route("/pipelines/<identifier>", methods=["GET"])
@jwt_required()
def get_pipeline_v2(identifier):
    pipeline = current_app.native_pipeline_service.get_pipeline(identifier)
    return APIResponse.success(data={"pipeline": pipeline})


@pipeline_v2_bp.route("/pipelines/<identifier>/versions", methods=["POST"])
@jwt_required()
@require_pipeline_author
def create_pipeline_version_v2(identifier):
    data = dict(request.get_json() or {})
    request_id = data.pop("request_id", None)
    activate = bool(data.pop("activate", True))
    user_id = get_jwt_identity()
    pipeline = current_app.native_pipeline_service.create_pipeline_version_from_config(
        identifier,
        data,
        activate=activate,
        request_id=request_id,
        created_by_user_id=int(user_id) if user_id else None,
        mirror_legacy_config=True,
    )
    return APIResponse.created(data={"pipeline": pipeline}, message="Pipeline version created")


@pipeline_v2_bp.route("/pipelines/constructor-support", methods=["GET"])
@jwt_required()
@require_pipeline_author
def get_pipeline_constructor_support_v2():
    payload = current_app.native_pipeline_service.get_pipeline_constructor_support()
    return APIResponse.success(data=payload)


@pipeline_v2_bp.route("/pipelines/constructor/preflight", methods=["POST"])
@jwt_required()
@require_pipeline_author
def preflight_pipeline_constructor_v2():
    data = request.get_json() or {}
    user_id = get_jwt_identity()
    payload = current_app.native_pipeline_service.preflight_pipeline_constructor(
        data,
        user_id=int(user_id) if user_id else None,
    )
    return APIResponse.success(data=payload)


@pipeline_v2_bp.route("/pipelines/<identifier>/readiness", methods=["POST"])
@jwt_required()
def submission_readiness_v2(identifier):
    data = request.get_json() or {}
    payload = PipelineExecutionRequestSchema.model_validate({**data, 'pipeline_identifier': identifier}).model_dump(mode='python')
    _, _, error_response = get_session_with_permission(payload['session_id'], permission='edit', require_mutable=True)
    if error_response:
        return error_response
    result = current_app.native_pipeline_service.check_submission_readiness(
        identifier, payload['session_id'], payload, int(get_jwt_identity()),
    )
    return APIResponse.success(data=result)


@pipeline_v2_bp.route("/pipelines/<identifier>/execute", methods=["POST"])
@jwt_required()
def execute_pipeline_v2(identifier):
    data = request.get_json() or {}
    user_id = get_jwt_identity()
    try:
        request_id = str(UUID(data["request_id"])) if data.get("request_id") else None
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("request_id must be a UUID")
    payload = {
        "pipeline_identifier": identifier,
        "request_id": request_id,
        "expected_version": data.get("expected_version"),
        "preflight_token": data.get("preflight_token"),
        "readiness_token": data.get("readiness_token"),
        "session_id": data.get("session_id"),
        "local_file_paths": data.get("local_file_paths") or [],
        "record_ids": data.get("record_ids") or [],
        "execution_items": data.get("execution_items") or [],
        "is_sandbox": data.get("is_sandbox", True),
        "async_execution": bool(data.get("async_execution", False)),
        "abort_on_critical_error": bool(data.get("abort_on_critical_error", False)),
    }
    request_model = PipelineExecutionRequestSchema.model_validate(payload)
    payload = request_model.model_dump(mode='python')
    session_row, _, error_response = get_session_with_permission(
        request_model.session_id,
        permission="edit",
        require_mutable=True,
    )
    if error_response:
        return error_response

    if request_model.async_execution:
        pending_run = current_app.native_pipeline_service.create_pending_run(
            identifier,
            session_id=request_model.session_id,
            initiated_by_user_id=int(user_id) if user_id else None,
            request_payload=payload,
        )
        if pending_run.get("reused"):
            return APIResponse.accepted(data=pending_run, message="Reconnected to existing pipeline run")
        try:
            task = _enqueue_submission_pipeline_task(
                None,
                identifier,
                request_model.local_file_paths,
                request_model.session_id,
                request_model.is_sandbox,
                request_model.abort_on_critical_error,
                request_model.record_ids,
                [item.model_dump(mode="python") for item in request_model.execution_items],
                pending_run["run_id"],
            )
        except Exception:
            from services.pipeline_run_recovery import resolve_dispatch_failure
            # Broker acceptance and its acknowledgement are separate events.
            # Reconnect if a worker already started; otherwise cancel the saved
            # run under its execution lock so a late delivery cannot run it.
            resolve_dispatch_failure(pending_run["run_id"])
            return APIResponse.accepted(data={"run_id": pending_run["run_id"]},
                                        message="Check this run's status before retrying")
        return APIResponse.accepted(
            data={
                "run_id": pending_run["run_id"],
                "task_id": task.id,
                "pipeline_identifier": pending_run["pipeline_identifier"],
                "pipeline_version": pending_run["pipeline_version"],
                "status": pending_run["status"],
            },
            message="Native pipeline execution started",
        )

    pending_run = current_app.native_pipeline_service.create_pending_run(
        identifier, session_id=request_model.session_id,
        initiated_by_user_id=int(user_id) if user_id else None, request_payload=payload,
    )
    execution_output = execute_submission_pipeline(
        identifier=identifier,
        local_file_paths=request_model.local_file_paths,
        db_session_id=request_model.session_id,
        is_sandbox=request_model.is_sandbox,
        abort_on_critical_error=request_model.abort_on_critical_error,
        record_ids=request_model.record_ids,
        execution_items=[item.model_dump(mode="python") for item in request_model.execution_items],
        precreated_run_public_id=pending_run['run_id'],
    )
    session_row.status = "completed" if execution_output["result"].get("success", True) else "failed"
    session_row.timings = json.dumps(execution_output["timings"])
    db.session.commit()
    return APIResponse.success(
        data={
            "run_id": execution_output["result"].get("run_id"),
            "pipeline_identifier": execution_output["result"].get("pipeline_identifier", identifier),
            "pipeline_version": execution_output["result"].get("pipeline_version"),
            "result": execution_output["result"],
            "timings": execution_output["timings"],
            "progress_summary": execution_output["progress_summary"],
        }
    )


@pipeline_v2_bp.route("/runs/<run_id>", methods=["GET"])
@jwt_required()
def get_pipeline_run_v2(run_id):
    run_payload = current_app.native_pipeline_service.get_pipeline_run(run_id, int(get_jwt_identity()))
    return APIResponse.success(data={"run": run_payload})


@pipeline_v2_bp.route("/runs/<run_id>/cancel", methods=["POST"])
@jwt_required()
def cancel_pipeline_run_v2(run_id):
    from database.models import PipelineRun
    from exceptions import ResourceNotFoundError
    from services.pipeline_run_recovery import cancel_pending_run
    run = PipelineRun.query.filter_by(public_id=run_id).first()
    if run is None:
        raise ResourceNotFoundError('Pipeline run not found')
    _, _, error_response = get_session_with_permission(run.session_id, permission='edit', require_mutable=True)
    if error_response:
        return error_response
    cancel_pending_run(run)
    return APIResponse.success(data={'run': current_app.native_pipeline_service.get_pipeline_run(run_id, int(get_jwt_identity()))})


@pipeline_v2_bp.route("/playground/execute", methods=["POST"])
@jwt_required()
def execute_playground_v2():
    data = request.get_json() or {}
    user_id = get_jwt_identity()
    request_model = PlaygroundExecutionRequestSchema.model_validate(data)
    _, _, error_response = get_session_with_permission(request_model.session_id, permission='edit', require_mutable=True)
    if error_response:
        return error_response
    if request_model.async_execution:
        result = current_app.native_pipeline_service.create_pending_playground_run(data, int(user_id))
        if not result.get('reused'):
            try:
                _enqueue_playground_task(result['run_id'])
            except Exception:
                from database.models import PlaygroundRun
                from services.pipeline_run_recovery import resolve_dispatch_failure
                resolve_dispatch_failure(result['run_id'], PlaygroundRun)
                result = current_app.native_pipeline_service.get_playground_run(result['run_id'], int(user_id))
        return APIResponse.accepted(data={'playground_run': result}, message='Component run accepted')
    result = current_app.native_pipeline_service.execute_playground(data, int(user_id) if user_id else None)
    return APIResponse.created(data={"playground_run": result}, message="Playground execution completed")


@pipeline_v2_bp.route("/playground/runs/<run_id>", methods=["GET"])
@jwt_required()
def get_playground_run_v2(run_id):
    result = current_app.native_pipeline_service.get_playground_run(run_id, int(get_jwt_identity()))
    return APIResponse.success(data={"playground_run": result})


@pipeline_v2_bp.route('/playground/runs/<run_id>/cancel', methods=['POST'])
@jwt_required()
def cancel_playground_run_v2(run_id):
    from database.models import PlaygroundRun
    from exceptions import ResourceNotFoundError
    from services.pipeline_run_recovery import cancel_pending_run
    run = PlaygroundRun.query.filter_by(public_id=run_id).first()
    if run is None:
        raise ResourceNotFoundError('Playground run not found')
    _, _, error_response = get_session_with_permission(run.session_id, permission='edit', require_mutable=True)
    if error_response:
        return error_response
    cancel_pending_run(run)
    result = current_app.native_pipeline_service.get_playground_run(run_id, int(get_jwt_identity()))
    return APIResponse.success(data={'playground_run': result})


@pipeline_v2_bp.route("/playground/runs/<run_id>/artifacts/<int:artifact_index>", methods=["GET"])
@jwt_required()
def download_playground_artifact_v2(run_id, artifact_index):
    user_id = get_jwt_identity()
    artifact = current_app.native_pipeline_service.get_playground_run_artifact(
        run_id,
        artifact_index,
        int(user_id) if user_id else None,
    )
    return send_file(
        artifact["path"],
        mimetype=artifact.get("mimetype"),
        as_attachment=True,
        download_name=artifact.get("download_name"),
    )


@pipeline_v2_bp.route("/playground/sessions/<int:session_id>/file", methods=["GET"])
@jwt_required()
def download_playground_session_file_v2(session_id):
    candidate_path = str(request.args.get("path") or "").strip()
    if not candidate_path:
        return APIResponse.validation_error("path is required")
    user_id = get_jwt_identity()
    file_payload = current_app.native_pipeline_service.get_playground_session_file(
        session_id,
        candidate_path,
        int(user_id) if user_id else None,
    )
    return send_file(
        file_payload["path"],
        mimetype=file_payload.get("mimetype"),
        as_attachment=False,
        download_name=file_payload.get("download_name"),
    )
