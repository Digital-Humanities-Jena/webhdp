"""Admission limits for account-owned pipeline and Playground executions."""

from contextlib import contextmanager
import os

from flask import current_app
from sqlalchemy import func

from database.database import db
from database.models import PipelineRun, PipelineRunStatus, PlaygroundRun, User, UserRole
from database.webhdp_link_models import LinkRun
from exceptions import AppException
from services.pipeline_run_recovery import reconcile_run
from services.registry_lock import registry_lock


class NativeRunQuotaExceeded(AppException):
    status_code = 429
    error_code = "NATIVE_PROCESSING_QUOTA"
    user_message = "Your processing limit is full. Wait for a run to finish or cancel a queued run."


RUN_MODELS = (PipelineRun, PlaygroundRun)
ACTIVE_RUN_STATES = (PipelineRunStatus.PENDING, PipelineRunStatus.RUNNING)


def _active_rows(model, user_id):
    rows = model.query.filter(model.initiated_by_user_id == user_id, model.status.in_(ACTIVE_RUN_STATES))
    if model is PipelineRun:
        # A connected application already has its own admission queue.
        rows = rows.filter(~db.session.query(LinkRun.id).filter(LinkRun.id == model.public_id).exists())
    return rows


def _active_limit(user):
    if user.role == UserRole.ADMIN:
        return None
    configured = current_app.config.get("NATIVE_PROCESSING_ACTIVE_LIMIT", os.getenv("WEBHDP_NATIVE_PROCESSING_ACTIVE_LIMIT", "3"))
    try:
        return max(1, int(configured))
    except (TypeError, ValueError):
        return 3


def native_run_usage(user):
    counts = dict.fromkeys(ACTIVE_RUN_STATES, 0)
    for model in RUN_MODELS:
        for status, count in _active_rows(model, user.id).with_entities(model.status, func.count()).group_by(model.status):
            counts[status] += count
    return {"queued": counts[PipelineRunStatus.PENDING], "running": counts[PipelineRunStatus.RUNNING],
            "active": sum(counts.values()), "active_limit": _active_limit(user)}


@contextmanager
def admit_native_run(user_id):
    user = db.session.get(User, user_id) if user_id is not None else None
    if user is None or user.role == UserRole.ADMIN:
        yield
        return

    with registry_lock(f"native-processing-quota:{user.id}"):
        usage = native_run_usage(user)
        if usage["active"] >= usage["active_limit"]:
            for model in RUN_MODELS:
                for run in _active_rows(model, user.id):
                    if run.session_id is not None:
                        reconcile_run(run)
            usage = native_run_usage(user)
            if usage["active"] >= usage["active_limit"]:
                raise NativeRunQuotaExceeded(details=usage)
        yield
