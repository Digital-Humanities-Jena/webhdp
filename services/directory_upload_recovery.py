"""Reserve batch uploads before dispatch and reconcile uncertain queue handoffs."""
import hashlib
import json
from functools import wraps

from flask import g, request
from flask_jwt_extended import get_jwt_identity

from api_utils import APIResponse
from constants import UPLOAD_SUBMIT_TOKEN_FIELD, UPLOAD_PROGRESS_FIELD
from database.database import db
from database.models import Session, UserMetadata
from services.registry_lock import OperationConflict, registry_lock
from services.pipeline_execution_lock import PipelineAlreadyRunning, session_pipeline_lock

IDENTITY_FIELD = 'directory_upload_identity'


def persist_directory_upload_identity(session):
    identity = getattr(g, IDENTITY_FIELD, None)
    if identity:
        db.session.flush()
        db.session.add_all([
            UserMetadata(session_id=session.id, field_name=UPLOAD_SUBMIT_TOKEN_FIELD, field_value=identity['token']),
            UserMetadata(session_id=session.id, field_name=IDENTITY_FIELD, field_value=json.dumps(identity)),
        ])


def mark_upload_dispatched(session_id):
    identity = UserMetadata.query.filter_by(session_id=session_id, field_name=IDENTITY_FIELD).first()
    if identity:
        identity.field_value = json.dumps({**json.loads(identity.field_value), 'dispatched': True})
        db.session.commit()


def directory_upload_request(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        from routes.session_routes import _normalize_submit_token, _get_upload_submission_context, _build_upload_recovery_payload
        payload = dict(request.get_json(silent=True) or {}) if request.is_json else request.form.to_dict(flat=False)
        raw_token = payload.get('submit_token') or request.headers.get('X-Upload-Submit-Token')
        token = _normalize_submit_token(raw_token[0] if isinstance(raw_token, list) else raw_token)
        if not token or str(request.args.get('validate_only', '')).lower() == 'true':
            return function(*args, **kwargs)
        files = []
        for key in sorted(request.files):
            for file in request.files.getlist(key):
                digest = hashlib.sha256()
                for chunk in iter(lambda: file.read(1024 * 1024), b''):
                    digest.update(chunk)
                file.seek(0)
                files.append([key, file.filename, digest.hexdigest()])
        payload.pop('submit_token', None)
        fingerprint = hashlib.sha256(json.dumps([payload, files], sort_keys=True).encode()).hexdigest()
        user_id = int(get_jwt_identity())
        with registry_lock(f'single-upload:{user_id}:{token}'):
            context = _get_upload_submission_context(user_id, token)
            if context:
                identity = UserMetadata.query.filter_by(session_id=context['session_id'], field_name=IDENTITY_FIELD).first()
                if identity and json.loads(identity.field_value)['fingerprint'] != fingerprint:
                    raise OperationConflict('This upload request was already used for different content or settings.')
                if UserMetadata.query.filter_by(session_id=context['session_id'], field_name='single_upload_identity').first():
                    raise OperationConflict('This request belongs to a single-file upload. Start a new upload.')
                return APIResponse.accepted(data=_build_upload_recovery_payload(context), message='Reconnected to the saved upload')
            setattr(g, IDENTITY_FIELD, {'token': token, 'fingerprint': fingerprint})
            try:
                return function(*args, **kwargs)
            finally:
                g.pop(IDENTITY_FIELD, None)
    return wrapped


def cancel_unstarted_upload(session_id):
    """Late deliveries must see the cancellation before doing any work."""
    from routes.session_routes import _upsert_session_metadata
    db.session.rollback()
    session = db.session.get(Session, session_id)
    if not session:
        return
    try:
        with session_pipeline_lock(session.hdpc_path):
            progress = UserMetadata.query.filter_by(session_id=session_id, field_name=UPLOAD_PROGRESS_FIELD).first()
            if progress and json.loads(progress.field_value).get('current_stage') not in ('queued', 'preparing'):
                return
            message = 'Upload preparation was interrupted before processing. Review this session and start a new upload.'
            session.status = 'failed'
            _upsert_session_metadata(session_id, UPLOAD_PROGRESS_FIELD, json.dumps({
                'current_stage': 'failed', 'status_message': message, 'dispatch_cancelled': True,
            }))
            db.session.commit()
    except PipelineAlreadyRunning:
        pass


def guard_upload_coordinator(function):
    @wraps(function)
    def wrapped(task, session_id, *args, **kwargs):
        session = db.session.get(Session, session_id)
        if not session or not session.hdpc_path:
            return function(task, session_id, *args, **kwargs)
        try:
            with session_pipeline_lock(session.hdpc_path):
                progress = UserMetadata.query.filter_by(session_id=session_id, field_name=UPLOAD_PROGRESS_FIELD).first()
                if progress and json.loads(progress.field_value).get('dispatch_cancelled'):
                    return {'status': 'failed', 'error': 'This upload was cancelled before processing.'}
                return function(task, session_id, *args, **kwargs)
        except PipelineAlreadyRunning:
            raise task.retry(countdown=15, max_retries=None)
    return wrapped


def reconcile_preparing_upload(user_id, token, session_id):
    """An interrupted request must not leave an unconfirmed handoff spinning."""
    identity = UserMetadata.query.filter_by(session_id=session_id, field_name=IDENTITY_FIELD).first()
    if not identity or json.loads(identity.field_value).get('dispatched'):
        return
    try:
        with registry_lock(f'single-upload:{user_id}:{token}'):
            cancel_unstarted_upload(session_id)
    except OperationConflict:
        pass
