import io
import json
from unittest.mock import Mock

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token, get_jwt_identity, jwt_required

from api_utils import APIResponse
from constants import UPLOAD_PROGRESS_FIELD, UPLOAD_STORAGE_MODE_FIELD, UPLOAD_SUBMIT_TOKEN_FIELD, UPLOAD_TASK_ID_FIELD
from database.database import db
from database.models import Session, User, UserMetadata
from exceptions import AppException
from routes.session_routes import session_bp
from services.directory_upload_recovery import (
    directory_upload_request, persist_directory_upload_identity, mark_upload_dispatched,
    cancel_unstarted_upload, guard_upload_coordinator,
)


@pytest.fixture
def directory_app(tmp_path):
    app = Flask(__name__)
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
                      SQLALCHEMY_TRACK_MODIFICATIONS=False, JWT_SECRET_KEY='directory-test-secret-at-least-32')
    db.init_app(app)
    JWTManager(app)
    app.register_blueprint(session_bp, url_prefix='/sessions')
    enqueue = Mock()

    @app.errorhandler(AppException)
    def error(exc):
        return APIResponse.error(exc.error_code, exc.message, exc.status_code)

    @app.post('/upload')
    @jwt_required()
    @directory_upload_request
    def upload():
        row = Session(user_id=int(get_jwt_identity()), session_dir=str(tmp_path), hdpc_path=str(tmp_path / 'project.hdpc'))
        db.session.add(row)
        persist_directory_upload_identity(row)
        db.session.commit()
        enqueue(row.id)
        mark_upload_dispatched(row.id)
        return APIResponse.accepted(data={'session_id': row.id})

    with app.app_context():
        db.create_all()
        user = User(email='batch@example.com', password_hash='test-only-hash', is_verified=True)
        db.session.add(user)
        db.session.commit()
        headers = {'Authorization': f'Bearer {create_access_token(identity=str(user.id))}'}
        yield app.test_client(), headers, enqueue
        db.session.remove()
        db.drop_all()


def send(client, headers, *, content=b'archive', **settings):
    return client.post('/upload', headers=headers, data={
        'submit_token': 'batch-1', 'zip_file': (io.BytesIO(content), 'models.zip'), **settings,
    })


def test_token_is_durable_before_dispatch_and_retry_creates_no_duplicate(directory_app):
    client, headers, enqueue = directory_app
    def check_durable(session_id):
        assert UserMetadata.query.filter_by(session_id=session_id, field_name=UPLOAD_SUBMIT_TOKEN_FIELD).one().field_value == 'batch-1'
    enqueue.side_effect = check_durable
    first = send(client, headers).json['data']
    assert send(client, headers).json['data']['session_id'] == first['session_id']
    assert send(client, headers, content=b'changed').status_code == 409
    assert send(client, headers, sharing_scope='institution').status_code == 409
    assert Session.query.count() == 1
    enqueue.assert_called_once()


def test_interrupted_preparation_with_saved_task_identity_is_cancelled_without_replay(directory_app):
    client, headers, enqueue = directory_app
    def interrupted(session_id):
        db.session.add(UserMetadata(session_id=session_id, field_name=UPLOAD_TASK_ID_FIELD, field_value='saved-task'))
        db.session.commit()
        raise RuntimeError('request ended before acknowledgement')
    enqueue.side_effect = interrupted
    with pytest.raises(RuntimeError):
        send(client, headers)
    recovered = client.post('/sessions/directory/recover', headers=headers, json={'submit_token': 'batch-1'})
    assert recovered.json['data']['session_status'] == 'failed'
    worker = Mock()
    result = guard_upload_coordinator(worker)(Mock(), 1)
    assert result['status'] == 'failed'
    worker.assert_not_called()
    assert send(client, headers).json['data']['session_status'] == 'failed'
    assert Session.query.count() == 1


def test_dispatch_failure_does_not_replace_live_or_completed_progress(directory_app):
    from test_workflow_transition_reliability import locked_by_other_process
    client, headers, _ = directory_app
    send(client, headers)
    session = db.session.get(Session, 1)
    with locked_by_other_process(session.hdpc_path):
        cancel_unstarted_upload(session.id)
        assert session.status != 'failed'
    session.status = 'scanned'
    db.session.add(UserMetadata(session_id=1, field_name=UPLOAD_PROGRESS_FIELD, field_value=json.dumps({'current_stage': 'completed'})))
    db.session.commit()
    cancel_unstarted_upload(session.id)
    assert session.status == 'scanned'


@pytest.mark.parametrize('lost_acknowledgement', [False, True])
def test_directory_route_saves_identity_before_worker_and_keeps_newer_progress(directory_app, tmp_path, monkeypatch, lost_acknowledgement):
    import sys
    import zipfile
    from types import SimpleNamespace
    from flask import session as flask_session
    client, headers, _ = directory_app
    client.application.secret_key = 'directory-test-session'
    client.application.project_service = SimpleNamespace()
    monkeypatch.setenv('SHARED_SESSION_PATH', str(tmp_path))
    monkeypatch.setattr('services.cloud_upload_service.CloudUploadService.get_storage_mode', lambda: 'server_only')
    monkeypatch.setattr('services.cloud_upload_service.CloudUploadService.get_available_storage', lambda: ('server', 'Ready'))
    monkeypatch.setattr('services.msf_service.MSFService.patch_msf_file', lambda *a, **kw: {'is_valid': True})
    def create_workspace(**kwargs):
        uploads = tmp_path / 'uploads'
        uploads.mkdir(exist_ok=True)
        row = Session(user_id=1, session_dir=str(tmp_path), hdpc_path=str(tmp_path / 'project.hdpc'))
        db.session.add(row)
        persist_directory_upload_identity(row)
        db.session.commit()
        flask_session['db_session_id'] = row.id
        return row.hdpc_path, str(tmp_path / 'outputs'), str(uploads)
    def worker_accepted(*, kwargs, task_id):
        sid = kwargs['session_id']
        fields = {row.field_name: row.field_value for row in UserMetadata.query.filter_by(session_id=sid).all()}
        assert fields[UPLOAD_SUBMIT_TOKEN_FIELD] == 'route-request'
        assert fields[UPLOAD_TASK_ID_FIELD] == task_id
        progress = UserMetadata.query.filter_by(session_id=sid, field_name=UPLOAD_PROGRESS_FIELD).one()
        progress.field_value = json.dumps({'current_stage': 'completed', 'percent': 100})
        db.session.get(Session, sid).status = 'scanned'
        db.session.commit()
        if lost_acknowledgement:
            raise ConnectionError('queue acknowledgement lost')
        return SimpleNamespace(id=task_id)
    monkeypatch.setitem(sys.modules, 'app', SimpleNamespace(_create_session_dirs=create_workspace))
    monkeypatch.setitem(sys.modules, 'tasks', SimpleNamespace(start_upload_coordinator=SimpleNamespace(apply_async=worker_accepted)))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('model.glb', 'model')
    archive.seek(0)
    result = client.post('/sessions/directory', headers=headers, data={
        'submit_token': 'route-request', 'zip_file': (archive, 'models.zip'),
        'msf_file': (io.BytesIO(b'filename,title\nmodel.glb,Model\n'), 'metadata.csv'),
    })
    assert result.status_code == 202, result.json
    progress = UserMetadata.query.filter_by(session_id=result.json['data']['session_id'], field_name=UPLOAD_PROGRESS_FIELD).one()
    assert json.loads(progress.field_value)['current_stage'] == 'completed'
    assert db.session.get(Session, result.json['data']['session_id']).status == 'scanned'


@pytest.mark.parametrize('task_info', [None, 'retrying', []])
def test_task_monitor_accepts_absent_or_non_mapping_worker_metadata(directory_app, monkeypatch, task_info):
    import sys
    from types import SimpleNamespace
    client, headers, _ = directory_app
    session_id = send(client, headers).json['data']['session_id']
    db.session.add(UserMetadata(session_id=session_id, field_name=UPLOAD_TASK_ID_FIELD, field_value='task-started'))
    outsider = User(email='outsider@example.com', password_hash='test-only-hash', is_verified=True)
    db.session.add(outsider)
    db.session.commit()
    outsider_headers = {'Authorization': f'Bearer {create_access_token(identity=str(outsider.id))}'}
    task = SimpleNamespace(state='STARTED', info=task_info)
    monkeypatch.setitem(sys.modules, 'celery_app', SimpleNamespace(celery=SimpleNamespace(AsyncResult=lambda _: task)))
    result = client.get('/sessions/tasks/task-started', headers=headers)
    assert result.status_code == 200
    assert result.json['data']['state'] == 'STARTED'
    assert client.get('/sessions/tasks/task-started', headers=outsider_headers).status_code == 404
    assert client.get('/sessions/tasks/unrelated-task', headers=headers).status_code == 404


def test_mounted_input_access_can_be_granted_and_revoked_without_affecting_other_uploads(directory_app, tmp_path):
    from flask import current_app

    client, headers, _ = directory_app
    current_app.config.update(STORAGE_MODE='local', LOCAL_INPUT_PATH=str(tmp_path),
                              WEBHDP_DEPLOYMENT_MODE='workstation-local', WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=True)
    (tmp_path / 'metadata.csv').write_text('filename,title\nmodel.glb,Example\n')
    mounted_id = send(client, headers).json['data']['session_id']
    db.session.add(UserMetadata(session_id=mounted_id, field_name='msf_profile',
                                field_value=json.dumps({'storage_mode': 'local'})))
    own_id = send(client, headers, submit_token='another').json['data']['session_id']
    db.session.add(UserMetadata(session_id=own_id, field_name=UPLOAD_STORAGE_MODE_FIELD, field_value='local'))
    db.session.commit()

    assert client.get('/sessions/local-msf', headers=headers).status_code == 403
    assert {row['id'] for row in client.get('/sessions', headers=headers).json['data']['sessions']} == {own_id}
    assert client.get(f'/sessions/{mounted_id}', headers=headers).status_code == 404

    user = User.query.filter_by(email='batch@example.com').one()
    user.set_capabilities(['mounted_input_access'])
    db.session.commit()
    available = client.get('/sessions/local-msf', headers=headers)
    assert available.status_code == 200
    assert available.json['data']['msf_files'][0]['path'] == 'metadata.csv'
    assert {row['id'] for row in client.get('/sessions', headers=headers).json['data']['sessions']} == {mounted_id, own_id}

    user.set_capabilities([])
    db.session.commit()
    assert client.get('/sessions/local-msf', headers=headers).status_code == 403
    assert client.get(f'/sessions/{mounted_id}', headers=headers).status_code == 404
