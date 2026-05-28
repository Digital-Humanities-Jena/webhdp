import os
import uuid
from typing import Any, Callable

from flask import Flask


def _as_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


try:
    if _as_bool(os.environ.get("WEBHDP_INLINE_TASKS")):
        raise ImportError("WEBHDP_INLINE_TASKS requested")
    from celery import Celery as _Celery
except ImportError:
    _Celery = None


class InlineTaskResult:
    """Minimal Celery AsyncResult-compatible object for single-process deployments."""

    def __init__(
        self,
        task_id: str,
        value: Any = None,
        exception: BaseException | None = None,
        *,
        state: str | None = None,
        info: Any = None,
    ):
        self.id = task_id
        self.value = value
        self.exception = exception
        self.state = state or ("FAILURE" if exception is not None else "SUCCESS")
        self.info = info if info is not None else (exception if exception is not None else value)

    def ready(self) -> bool:
        return True

    def successful(self) -> bool:
        return self.exception is None and self.state == "SUCCESS"

    def get(self, timeout: float | None = None) -> Any:
        if self.exception is not None:
            raise self.exception
        return self.value


class InlineTask:
    """Small callable wrapper that supports the Celery task methods used by WebHDP."""

    def __init__(self, func: Callable[..., Any], *, bind: bool = False, owner: "InlineCelery | None" = None):
        self.func = func
        self.bind = bind
        self.owner = owner
        self.__name__ = getattr(func, "__name__", "inline_task")
        self.__doc__ = getattr(func, "__doc__", None)
        self.id: str | None = None
        self.state: str | None = None
        self.meta: dict[str, Any] | None = None

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self.bind:
            return self.func(self, *args, **kwargs)
        return self.func(*args, **kwargs)

    def delay(self, *args: Any, **kwargs: Any) -> InlineTaskResult:
        return self.apply_async(args=args, kwargs=kwargs)

    def apply_async(self, args: tuple[Any, ...] | None = None, kwargs: dict[str, Any] | None = None, **_: Any) -> InlineTaskResult:
        self.id = str(uuid.uuid4())
        if self.owner is not None:
            self.owner._results[self.id] = InlineTaskResult(self.id, state="PENDING", info=None)
        try:
            value = self(*(args or ()), **(kwargs or {}))
        except BaseException as exc:
            result = InlineTaskResult(self.id, exception=exc)
            if self.owner is not None:
                self.owner._results[self.id] = result
            return result
        result = InlineTaskResult(self.id, value=value, state="SUCCESS", info=value)
        if self.owner is not None:
            self.owner._results[self.id] = result
        return result

    def update_state(self, *, state: str | None = None, meta: dict[str, Any] | None = None, **_: Any) -> None:
        self.state = state
        self.meta = meta
        if self.owner is not None and self.id:
            self.owner._results[self.id] = InlineTaskResult(self.id, state=state or "PENDING", info=meta)


class InlineCelery:
    """Fallback task registry used when Celery is unavailable or explicitly disabled."""

    Task = InlineTask

    def __init__(self, *args: Any, **kwargs: Any):
        self.conf: dict[str, Any] = {}
        self.tasks: dict[str, InlineTask] = {}
        self._results: dict[str, InlineTaskResult] = {}

    def task(self, *decorator_args: Any, **decorator_kwargs: Any):
        bind = bool(decorator_kwargs.get("bind", False))

        def decorator(func: Callable[..., Any]) -> InlineTask:
            task = InlineTask(func, bind=bind, owner=self)
            self.tasks[task.__name__] = task
            return task

        if decorator_args and callable(decorator_args[0]):
            return decorator(decorator_args[0])
        return decorator

    def AsyncResult(self, task_id: str) -> InlineTaskResult:
        return self._results.get(task_id, InlineTaskResult(task_id, state="PENDING", info=None))

def make_celery(app):
    if _Celery is None:
        app.logger.warning(
            "Celery is not available or WEBHDP_INLINE_TASKS is enabled; "
            "background tasks will execute inline in the web process. "
            "Use a real Celery worker for production workloads."
        )
        return InlineCelery(app.import_name)

    celery = _Celery(
        app.import_name,
        backend=app.config["CELERY_RESULT_BACKEND"],
        broker=app.config["CELERY_BROKER_URL"],
    )
    celery.conf.update(app.config)

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery

# We need to initialize the Flask app to configure Celery
# This is a bit circular, but necessary for Flask-Celery integration
from app import app
celery = make_celery(app)

# Import tasks to ensure they are registered
import tasks
