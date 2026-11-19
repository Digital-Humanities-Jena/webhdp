import io
from unittest.mock import Mock

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token, get_jwt_identity, jwt_required

from api_utils import APIResponse
from database.database import db
from database.models import Session, User
from exceptions import AppException
from routes.session_routes import session_bp
from services.account_upload_quota import attach_upload_to_session
from services.single_upload_recovery import persist_single_upload_identity, single_upload_request


@pytest.fixture
def upload_app(tmp_path):
    app = Flask(__name__)
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
                      SQLALCHEMY_TRACK_MODIFICATIONS=False, JWT_SECRET_KEY='upload-test-secret', MAX_CONTENT_LENGTH=4096)
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(session_bp, url_prefix='/api/v1/sessions')
    scanned = Mock()

    @app.errorhandler(AppException)
    def error(exc):
        return APIResponse.error(exc.error_code, exc.message, exc.status_code)

    @app.post('/api/v1/sessions/file')
    @jwt_required()
    @single_upload_request({'.glb'})
    def upload():
        row = Session(user_id=int(get_jwt_identity()), session_dir=str(tmp_path), status='scanned')
        db.session.add(row)
        persist_single_upload_identity(row)
        attach_upload_to_session(row)
        db.session.commit()
        scanned()
        return APIResponse.success(data={'session_id': row.id, 'foundFiles': [{'name': 'model.glb'}], 'file_id': 1})

    with app.app_context():
        db.create_all()
        users = [User(email=f'upload{i}@example.com', password_hash='test-only-hash', is_verified=True) for i in (1, 2)]
        db.session.add_all(users)
        db.session.commit()
        headers = [{'Authorization': f'Bearer {create_access_token(identity=str(user.id))}'} for user in users]
        yield app.test_client(), headers, scanned
        db.session.remove()
        db.drop_all()


def send(client, headers, *, content=b'model', filename='model.glb', token='upload-1', **form):
    return client.post('/api/v1/sessions/file', headers=headers, data={
        'file': (io.BytesIO(content), filename), 'submit_token': token, **form,
    }, content_type='multipart/form-data')


def test_lost_acknowledgement_reuses_session_file_and_scan(upload_app):
    client, headers, scanned = upload_app
    first = send(client, headers[0]).json['data']
    second = send(client, headers[0]).json['data']
    assert first['session_id'] == second['session_id']
    assert first['foundFiles'] == second['foundFiles']
    assert second['reused']
    scanned.assert_called_once()
    response = client.post('/api/v1/sessions/file/recover', headers=headers[0], json={'submit_token': 'upload-1'})
    assert response.json['data']['status'] == 'completed'
    assert 'fingerprint' not in response.json['data']
    assert Session.query.count() == 1


@pytest.mark.parametrize('change', [{'content': b'different'}, {'sharing_scope': 'private'}, {'filename': 'other.glb'}])
def test_reused_identity_rejects_changed_input(upload_app, change):
    client, headers, scanned = upload_app
    assert send(client, headers[0]).status_code == 200
    assert send(client, headers[0], **change).status_code == 409
    scanned.assert_called_once()


def test_recovery_is_owner_scoped(upload_app):
    client, headers, _ = upload_app
    send(client, headers[0])
    assert client.post('/api/v1/sessions/file/recover', headers=headers[1], json={'submit_token': 'upload-1'}).status_code == 404
    second = send(client, headers[1]).json['data']
    assert second['session_id'] == 2


def test_account_quota_rejects_new_payload_without_blocking_last_upload_recovery(upload_app):
    client, headers, scanned = upload_app
    client.application.config['ACCOUNT_UPLOAD_STORAGE_BYTES'] = 5
    assert send(client, headers[0], content=b'model').status_code == 200
    duplicate = send(client, headers[0], content=b'model')
    assert duplicate.status_code == 200 and duplicate.json['data']['reused']
    full = send(client, headers[0], content=b'x', token='upload-2')
    assert full.status_code == 413
    assert full.json['error']['code'] == 'UPLOAD_STORAGE_QUOTA'
    assert Session.query.count() == 1
    scanned.assert_called_once()


@pytest.mark.parametrize('invalid', [{'content': b''}, {'filename': 'model.exe'}, {'content': b'x' * 5000}])
def test_invalid_file_does_not_create_a_session(upload_app, invalid):
    client, headers, scanned = upload_app
    assert send(client, headers[0], **invalid).status_code in (400, 413)
    assert Session.query.count() == 0
    scanned.assert_not_called()


def test_interrupted_request_is_terminal_even_while_its_web_process_lives(upload_app):
    client, headers, scanned = upload_app
    scanned.side_effect = RuntimeError('request interrupted')
    with pytest.raises(RuntimeError):
        send(client, headers[0])
    response = client.post('/api/v1/sessions/file/recover', headers=headers[0], json={'submit_token': 'upload-1'})
    assert response.json['data']['status'] == 'failed'
    assert send(client, headers[0]).json['data']['status'] == 'failed'
    assert Session.query.count() == 1
    scanned.assert_called_once()


def test_live_upload_request_remains_processing_until_its_lock_releases(upload_app):
    import subprocess
    import sys
    client, headers, scanned = upload_app
    scanned.side_effect = RuntimeError('request interrupted')
    with pytest.raises(RuntimeError):
        send(client, headers[0])
    script = '''
from flask import Flask
from database.database import db
from services.registry_lock import registry_lock
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
db.init_app(app)
with app.app_context(), registry_lock('single-upload:1:upload-1'):
    print('locked', flush=True)
    input()
'''
    process = subprocess.Popen([sys.executable, '-c', script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == 'locked'
        response = client.post('/api/v1/sessions/file/recover', headers=headers[0], json={'submit_token': 'upload-1'})
        assert response.json['data']['status'] == 'processing'
    finally:
        process.communicate('\n', timeout=10)
    response = client.post('/api/v1/sessions/file/recover', headers=headers[0], json={'submit_token': 'upload-1'})
    assert response.json['data']['status'] == 'failed'
