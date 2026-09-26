"""Cross-process registry locks held across short database commits."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import fcntl
import hashlib
import os
from pathlib import Path
import tempfile

from sqlalchemy import text

from database.database import db
from exceptions import AppException


class OperationConflict(AppException):
    status_code = 409
    error_code = "OPERATION_CONFLICT"


_held = ContextVar("registry_locks", default=frozenset())


@contextmanager
def registry_lock(name):
    engine = db.engine
    key = hashlib.sha256(f"{engine.url}:{name}".encode()).hexdigest()[:48]
    owner_key = (os.getpid(), key)
    if owner_key in _held.get():
        yield
        return
    token = _held.set(_held.get() | {owner_key})
    connection = handle = None
    acquired = False
    dialect = engine.dialect.name
    try:
        if dialect == "sqlite":
            directory = (Path(engine.url.database).resolve().parent if engine.url.database and engine.url.database != ":memory:" else Path(tempfile.gettempdir())) / ".webhdp-registry-locks"
            directory.mkdir(mode=0o700, exist_ok=True)
            handle = (directory / key).open("a")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                pass
        elif dialect in {"postgresql", "mysql", "mariadb"}:
            connection = engine.connect()
            if dialect == "postgresql":
                acquired = connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": int(key[:15], 16)}).scalar()
            else:
                acquired = connection.execute(text("SELECT GET_LOCK(:key, 0)"), {"key": key}).scalar() == 1
        else:
            raise OperationConflict("Registry mutations are not supported on this database engine.")
        if not acquired:
            raise OperationConflict("Another registry operation is in progress. Refresh its status before retrying.")
        yield
    finally:
        try:
            if handle:
                handle.close()
            if connection:
                try:
                    if acquired:
                        if dialect == "postgresql":
                            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": int(key[:15], 16)})
                        else:
                            connection.execute(text("SELECT RELEASE_LOCK(:key)"), {"key": key})
                except Exception:
                    connection.invalidate()  # Do not return a still-locked connection to the pool.
                    raise
                finally:
                    connection.close()
        finally:
            _held.reset(token)


def serialize_registry(name):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with registry_lock(name):
                try:
                    return function(*args, **kwargs)
                except Exception:
                    db.session.rollback()
                    raise
        return wrapped
    return decorate
