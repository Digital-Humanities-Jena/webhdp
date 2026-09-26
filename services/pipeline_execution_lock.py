"""Serialize mutations of one project across web and worker processes."""

from contextlib import contextmanager
from functools import wraps
from inspect import signature
from pathlib import Path
import fcntl

from exceptions import AppException


class PipelineAlreadyRunning(AppException):
    status_code = 409
    error_code = "PIPELINE_ALREADY_RUNNING"
    user_message = "This session is already being processed. Wait for it to finish before retrying."

    def __init__(self):
        super().__init__(self.user_message)


@contextmanager
def session_pipeline_lock(hdpc_path):
    lock_path = Path(str(Path(hdpc_path).resolve()) + ".pipeline.lock")
    with lock_path.open("a") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PipelineAlreadyRunning() from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def guard_submission_execution(function):
    call_signature = signature(function)

    @wraps(function)
    def guarded(*args, **kwargs):
        from database.database import db
        from database.models import Session

        arguments = call_signature.bind(*args, **kwargs).arguments
        session = db.session.get(Session, arguments["db_session_id"])
        if session is None or not session.hdpc_path:
            return function(*args, **kwargs)
        with session_pipeline_lock(session.hdpc_path):
            return function(*args, **kwargs)

    return guarded
