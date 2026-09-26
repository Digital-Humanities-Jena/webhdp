"""Serialize mutations of one project across web and worker processes."""

from contextlib import contextmanager
from functools import wraps
from inspect import signature
from pathlib import Path
import fcntl
import os
from contextvars import ContextVar

from exceptions import AppException

_held = ContextVar("project_mutation_locks", default=frozenset())


class PipelineAlreadyRunning(AppException):
    status_code = 409
    error_code = "PIPELINE_ALREADY_RUNNING"
    user_message = "This session is already being processed. Wait for it to finish before retrying."

    def __init__(self):
        super().__init__(self.user_message)


@contextmanager
def session_pipeline_lock(hdpc_path):
    lock_path = Path(str(Path(hdpc_path).resolve()) + ".pipeline.lock")
    owner = (os.getpid(), str(lock_path))
    if owner in _held.get():
        yield
        return
    with lock_path.open("a") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PipelineAlreadyRunning() from exc
        token = _held.set(_held.get() | {owner})
        try:
            yield
        finally:
            _held.reset(token)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def project_lock_held(hdpc_path):
    return (os.getpid(), str(Path(str(Path(hdpc_path).resolve()) + '.pipeline.lock'))) in _held.get()


def serialize_project_mutation(function):
    call_signature = signature(function)

    @wraps(function)
    def guarded(*args, **kwargs):
        arguments = call_signature.bind(*args, **kwargs).arguments
        path = arguments.get("hdpc_path") or arguments["session"].hdpc_path
        if not path:
            raise FileNotFoundError("Session .hdpc is not available")
        with session_pipeline_lock(path):
            return function(*args, **kwargs)
    return guarded


def guard_submission_execution(function):
    call_signature = signature(function)

    @wraps(function)
    def guarded(*args, **kwargs):
        from database.database import db
        from database.models import Session, PipelineRun, PipelineRunStatus
        import json

        arguments = call_signature.bind(*args, **kwargs).arguments
        session = db.session.get(Session, arguments["db_session_id"])
        def execute_once():
            run_id = arguments.get("precreated_run_public_id")
            run = PipelineRun.query.filter_by(public_id=run_id).first() if run_id else None
            if run:
                db.session.refresh(run)
            if run and run.status in {PipelineRunStatus.COMPLETED, PipelineRunStatus.FAILED}:
                result = json.loads(run.result_json or "{}")
                result.update(run_id=run.public_id, success=run.status == PipelineRunStatus.COMPLETED)
                return {"result": result, "timings": json.loads(run.timings_json or "{}"), "progress_summary": result.get("summary", {})}
            if run:
                run.status = PipelineRunStatus.RUNNING
                db.session.commit()
            return function(*args, **kwargs)
        if session is None or not session.hdpc_path:
            return execute_once()
        run_id = arguments.get("precreated_run_public_id")
        if run_id:
            from services.pipeline_run_recovery import reconcile_run
            existing = PipelineRun.query.filter_by(public_id=run_id).first()
            if existing:
                reconcile_run(existing)
        with session_pipeline_lock(session.hdpc_path):
            return execute_once()

    return guarded
