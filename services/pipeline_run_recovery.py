"""Reconcile persisted runs without replaying interrupted remote operations."""
import json
import os
import socket
import subprocess
from datetime import datetime, timezone
from functools import wraps
from contextlib import nullcontext

from database.database import db
from database.models import PipelineRun, PipelineRunStatus, PlaygroundRun, Session, StepRun
from services.pipeline_execution_lock import PipelineAlreadyRunning, session_pipeline_lock, project_lock_held
from services.registry_lock import OperationConflict, registry_lock

DISPATCH_RESERVATION_SECONDS = 120


def dispatch_lock(run):
    return registry_lock(f'run-dispatch:{run.__tablename__}:{run.public_id}')


def dispatch_reservation_expired(run):
    if not run.started_at:
        return False
    started = run.started_at
    if started.tzinfo:
        started = started.astimezone(timezone.utc).replace(tzinfo=None)
    return (datetime.utcnow() - started).total_seconds() >= DISPATCH_RESERVATION_SECONDS


def process_owner():
    return {'host': socket.gethostname(), 'pid': os.getpid(), 'started': _process_start(os.getpid())}


def _process_start(pid):
    try:
        return subprocess.check_output(['ps', '-o', 'lstart=', '-p', str(int(pid))], text=True, timeout=3).strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def owner_alive(owner):
    if not owner or owner.get('host') != socket.gethostname():
        return None
    try:
        os.kill(int(owner['pid']), 0)
    except ProcessLookupError:
        return False
    except (KeyError, ValueError, TypeError, PermissionError):
        return None
    started = _process_start(owner['pid'])
    if started and owner.get('started'):
        return started == owner['started']
    return True


def reconcile_run(run):
    if run.status not in {PipelineRunStatus.PENDING, PipelineRunStatus.RUNNING}:
        return
    session = db.session.get(Session, run.session_id)
    if not session or not session.hdpc_path or not os.path.isdir(os.path.dirname(session.hdpc_path)):
        return
    if project_lock_held(session.hdpc_path):
        return
    try:
        with session_pipeline_lock(session.hdpc_path):
            db.session.refresh(run)
            if run.status not in {PipelineRunStatus.PENDING, PipelineRunStatus.RUNNING}:
                return
            request = json.loads(run.request_json or '{}')
            dispatch = request.get('_dispatch') or {}
            abandoned = run.status == PipelineRunStatus.RUNNING
            if run.status == PipelineRunStatus.PENDING:
                if dispatch.get('state') == 'preparing':
                    # A shared dispatch lock proves an active request across hosts.
                    # Expiry only cancels unstarted work; late deliveries see FAILED.
                    with dispatch_lock(run):
                        abandoned = owner_alive(dispatch.get('owner')) is False or dispatch_reservation_expired(run)
                if dispatch.get('task_id'):
                    try:
                        from celery_app import celery
                        abandoned = abandoned or celery.AsyncResult(dispatch['task_id']).state in {'FAILURE', 'REVOKED'}
                    except Exception:
                        pass  # Unavailable task monitoring is not evidence of termination.
            if not abandoned:
                return
            message = ('Processing was interrupted. Existing files and drafts were kept. '
                       'Review record results and any HPC activity before starting another run.')
            run.status = PipelineRunStatus.FAILED
            run.error_message = message
            result = json.loads(run.result_json or '{}')
            result.update(success=False, status='failed', interrupted=True, error=message)
            run.result_json = json.dumps(result)
            run.completed_at = datetime.utcnow()
            if isinstance(run, PipelineRun):
                for step in StepRun.query.filter(StepRun.pipeline_run_id == run.id, StepRun.status.in_(['pending', 'running'])).all():
                    step.status = 'failed'
                    step.error_message = message
                    step.completed_at = run.completed_at
                session.status = 'failed'
            db.session.commit()
    except (PipelineAlreadyRunning, OperationConflict):
        return


def resolve_dispatch_failure(run_id, model=PipelineRun):
    """Cancel unstarted work without overwriting a worker's accepted result."""
    db.session.rollback()
    run = model.query.filter_by(public_id=run_id).one()
    session = db.session.get(Session, run.session_id)
    lock = session_pipeline_lock(session.hdpc_path) if session and session.hdpc_path else nullcontext()
    try:
        with lock:
            db.session.refresh(run)
            if run.status != PipelineRunStatus.PENDING:
                return
            message = 'This run could not be queued reliably and was cancelled before processing. Retry with a new run.'
            run.status = PipelineRunStatus.FAILED
            run.error_message = message
            run.completed_at = datetime.utcnow()
            run.result_json = json.dumps({'success': False, 'status': 'failed', 'error': message})
            if isinstance(run, PipelineRun) and session:
                session.status = 'failed'
            db.session.commit()
    except PipelineAlreadyRunning:
        pass  # The running worker owns the final outcome.


def cancel_pending_run(run):
    session = db.session.get(Session, run.session_id)
    if not session or not session.hdpc_path or not os.path.isdir(os.path.dirname(session.hdpc_path)):
        raise OperationConflict('The run workspace is unavailable.')
    with dispatch_lock(run), session_pipeline_lock(session.hdpc_path):
        db.session.refresh(run)
        if run.status != PipelineRunStatus.PENDING:
            raise OperationConflict('Only a queued run can be cancelled. Refresh its status.')
        message = 'This run was cancelled before processing. Existing files and drafts were kept.'
        run.status = PipelineRunStatus.FAILED
        run.error_message = message
        run.completed_at = datetime.utcnow()
        run.result_json = json.dumps({'success': False, 'status': 'failed', 'cancelled': True, 'error': message})
        if isinstance(run, PipelineRun):
            session.status = 'failed'
        db.session.commit()


def require_available_session(session_id, run_id=None):
    """Honor queued reservations as well as workers already holding a lock."""
    for model in (PipelineRun, PlaygroundRun):
        active = model.query.filter(model.session_id == session_id,
            model.status.in_([PipelineRunStatus.PENDING, PipelineRunStatus.RUNNING]))
        if run_id:
            active = active.filter(model.public_id != run_id)
        for other in active.all():
            reconcile_run(other)
            if other.status in {PipelineRunStatus.PENDING, PipelineRunStatus.RUNNING}:
                raise PipelineAlreadyRunning(other.public_id, 'playground' if model is PlaygroundRun else 'pipeline')


def guard_run_reservation(function):
    @wraps(function)
    def guarded(self, identifier, *, session_id, **kwargs):
        request_id = (kwargs.get('request_payload') or {}).get('request_id')
        if request_id and PipelineRun.query.filter_by(public_id=request_id).first():
            return function(self, identifier, session_id=session_id, **kwargs)
        session = db.session.get(Session, session_id)
        lock = session_pipeline_lock(session.hdpc_path) if session and session.hdpc_path else nullcontext()
        def check_available():
            if session:
                try:
                    require_available_session(session_id)
                except PipelineAlreadyRunning as exc:
                    raise OperationConflict('This session already has an active run.', details=exc.details) from exc
        check_available()
        with lock:
            check_available()
            return function(self, identifier, session_id=session_id, **kwargs)
    return guarded


def guard_native_run(function):
    @wraps(function)
    def guarded(self, identifier, execution_context, **kwargs):
        session = db.session.get(Session, execution_context.get('db_session_id'))
        if not session or not session.hdpc_path:
            return function(self, identifier, execution_context, **kwargs)
        run_id = kwargs.get('existing_run_public_id')
        if run_id:
            run = PipelineRun.query.filter_by(public_id=run_id, session_id=session.id).first()
            if run:
                reconcile_run(run)
                if run.status in {PipelineRunStatus.COMPLETED, PipelineRunStatus.FAILED}:
                    return function(self, identifier, execution_context, **kwargs)
        require_available_session(session.id, run_id)
        with session_pipeline_lock(session.hdpc_path):
            require_available_session(session.id, run_id)
            return function(self, identifier, execution_context, **kwargs)
    return guarded
