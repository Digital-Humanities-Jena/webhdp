"""Actual upload/HDPC scanning preserves component inputs as opaque source files."""
import io
import sqlite3
import wave
import zipfile
from pathlib import Path

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from database.database import db
from database.models import File, Session, User
from middleware import setup_error_handlers
from routes.single_file_routes import single_file_bp
from services.project_service import ProjectService
from session_manager import SessionManager


@pytest.fixture
def source_upload_app(tmp_path, monkeypatch):
    monkeypatch.setenv('SHARED_SESSION_PATH', str(tmp_path / 'sessions'))
    monkeypatch.setenv('STORAGE_MODE', 'server_only')
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='source-upload-test-secret',
                      JWT_SECRET_KEY='source-upload-jwt-test-secret-long-enough',
                      SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
                      SQLALCHEMY_TRACK_MODIFICATIONS=False,
                      MAX_CONTENT_LENGTH=1024 * 1024, ALLOWED_EXTENSIONS={'.obj', '.glb'})
    db.init_app(app)
    JWTManager(app)
    setup_error_handlers(app)
    app.register_blueprint(single_file_bp, url_prefix='/api/v1/sessions')
    app.session_manager = SessionManager()
    app.project_service = ProjectService()
    with app.app_context():
        db.create_all()
        user = User(email='component-upload@example.com', password_hash='test-only', is_verified=True)
        db.session.add(user)
        db.session.commit()
        headers = {'Authorization': f'Bearer {create_access_token(identity=str(user.id))}'}
        yield app.test_client(), headers, tmp_path
        db.session.remove()
        db.drop_all()


@pytest.mark.parametrize('extension', ['.zip', '.json', '.hdpc', '.sqlite', '.pdf', '.wav', '.wave',
                                     '.mp3', '.flac', '.ogg', '.oga', '.opus', '.m4a',
                                     '.aac', '.aif', '.aiff', '.aifc'])
def test_component_input_upload_preserves_original_and_creates_scanned_source(source_upload_app, extension):
    client, headers, root = source_upload_app
    if extension == '.zip':
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('../unpacked.txt', 'Archives must remain intact here.')
            archive.writestr('images/photo.txt', 'source payload')
        content = stream.getvalue()
    elif extension in {'.hdpc', '.sqlite'}:
        fixture = root / 'fixture.sqlite'
        with sqlite3.connect(fixture) as conn:
            conn.execute('CREATE TABLE evidence (value TEXT)')
            conn.execute("INSERT INTO evidence VALUES ('source payload')")
        content = fixture.read_bytes()
    elif extension == '.json':
        content = b'{"control_points": [], "crs": "synthetic-validation-frame"}'
    elif extension in {'.wav', '.wave'}:
        stream = io.BytesIO()
        with wave.open(stream, 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(b'\x00\x00' * 80)
        content = stream.getvalue()
    else:
        # Scanning must preserve even malformed inputs for an explicit validation
        # component; it does not decode, rewrite or claim their format is correct.
        content = b'opaque component source\x00\xff\x01'
    filename = 'component-source' + extension
    response = client.post('/api/v1/sessions/file', headers=headers,
        data={'file': (io.BytesIO(content), filename)}, content_type='multipart/form-data')
    assert response.status_code == 200, response.json
    result = response.json['data']
    row = db.session.get(Session, result['session_id'])
    assert row.status == 'scanned'
    source = db.session.get(File, result['file_id'])
    assert Path(source.path).read_bytes() == content
    assert result['foundFiles'][0]['name'] == filename
    assert len(result['foundFiles']) == 1
    assert not list(root.rglob('unpacked.txt'))
    assert not list(root.rglob('photo.txt'))
    assert Path(row.hdpc_path).is_file()


def test_executable_upload_is_rejected_before_creating_session(source_upload_app):
    client, headers, _ = source_upload_app
    response = client.post('/api/v1/sessions/file', headers=headers,
        data={'file': (io.BytesIO(b'executable'), 'component.exe')}, content_type='multipart/form-data')
    assert response.status_code == 400
    assert Session.query.count() == 0
