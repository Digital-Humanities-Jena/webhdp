"""User-scoped request identity for direct uploads."""
import hashlib
import json
from functools import wraps

from flask import current_app, g, make_response, request
from flask_jwt_extended import get_jwt_identity

from api_utils import APIResponse
from constants import UPLOAD_SUBMIT_TOKEN_FIELD
from database.database import db
from database.models import Session, UserMetadata
from exceptions import ValidationError
from security import SecurityValidator, sanitize_upload_filename
from services.registry_lock import OperationConflict, registry_lock

IDENTITY_FIELD = 'single_upload_identity'
RESULT_FIELD = 'single_upload_result'


def recover_single_upload(user_id, token):
    row = (db.session.query(Session).join(UserMetadata, UserMetadata.session_id == Session.id)
           .filter(Session.user_id == user_id, UserMetadata.field_name == UPLOAD_SUBMIT_TOKEN_FIELD,
                   UserMetadata.field_value == token).first())
    if row is None:
        return None
    fields = {item.field_name: item.field_value for item in UserMetadata.query.filter_by(session_id=row.id).all()}
    if IDENTITY_FIELD not in fields:
        raise OperationConflict('This request belongs to another upload. Start a new upload.')
    identity = json.loads(fields[IDENTITY_FIELD])
    result = json.loads(fields[RESULT_FIELD]) if fields.get(RESULT_FIELD) else None
    if result:
        return {**result, 'reused': True, 'status': 'completed', 'fingerprint': identity['fingerprint']}
    # A web process can survive a terminated request, or be replaced on another
    # host. The request lock, not its process identity, proves work is in flight.
    try:
        with registry_lock(f'single-upload:{user_id}:{token}'):
            db.session.refresh(row)
            saved = UserMetadata.query.filter_by(session_id=row.id, field_name=RESULT_FIELD).first()
            if saved:
                return {**json.loads(saved.field_value), 'reused': True, 'status': 'completed', 'fingerprint': identity['fingerprint']}
            row.status = 'failed'
            db.session.commit()
            status = 'failed'
    except OperationConflict:
        status = 'processing'
    return {'session_id': row.id, 'status': status,
            'fingerprint': identity['fingerprint'], 'reused': True}


def persist_single_upload_identity(session_row):
    identity = getattr(g, 'single_upload_identity', None)
    if not identity:
        return
    db.session.flush()
    db.session.add_all([
        UserMetadata(session_id=session_row.id, field_name=UPLOAD_SUBMIT_TOKEN_FIELD, field_value=identity['token']),
        UserMetadata(session_id=session_row.id, field_name=IDENTITY_FIELD, field_value=json.dumps(identity)),
    ])


def single_upload_request(allowed_extensions):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            from routes.session_routes import _normalize_submit_token
            file = request.files.get('file')
            if not file or not file.filename:
                raise ValidationError('Select a file to upload.')
            name = sanitize_upload_filename(file.filename, allowed_extensions=allowed_extensions)
            file.seek(0, 2)
            size = file.tell()
            file.seek(0)
            if size == 0:
                raise ValidationError('This file is empty. Select a file containing data.')
            SecurityValidator().validate_file_size(size, current_app.config['MAX_CONTENT_LENGTH'])
            token = _normalize_submit_token(request.form.get('submit_token'))
            if not token:
                return function(*args, **kwargs)
            content_hash = hashlib.sha256()
            for chunk in iter(lambda: file.read(1024 * 1024), b''):
                content_hash.update(chunk)
            file.seek(0)
            form = {key: request.form.get(key) for key in sorted(request.form) if key != 'submit_token'}
            fingerprint = hashlib.sha256(json.dumps([name, size, content_hash.hexdigest(), form], sort_keys=True).encode()).hexdigest()
            user_id = int(get_jwt_identity())
            with registry_lock(f'single-upload:{user_id}:{token}'):
                previous = recover_single_upload(user_id, token)
                if previous:
                    if previous.pop('fingerprint') != fingerprint:
                        raise OperationConflict('This upload request was already used for different content or settings.')
                    return APIResponse.success(data=previous)
                g.single_upload_identity = {'token': token, 'fingerprint': fingerprint}
                try:
                    response = make_response(function(*args, **kwargs))
                    payload = response.get_json(silent=True) or {}
                    data = payload.get('data') or {}
                    if response.status_code < 300 and data.get('session_id'):
                        if not UserMetadata.query.filter_by(session_id=data['session_id'], field_name=RESULT_FIELD).first():
                            db.session.add(UserMetadata(session_id=data['session_id'], field_name=RESULT_FIELD, field_value=json.dumps(data)))
                        db.session.commit()
                    return response
                finally:
                    g.pop('single_upload_identity', None)
        return wrapped
    return decorate
