"""Isolated HTTP fixture for browser tests of the real native execution routes."""
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token
from werkzeug.serving import run_simple

from database.database import db
from database.models import ComponentDefinition, ComponentProfile, ComponentVersion, PlaygroundRun, Session, User
from middleware import setup_error_handlers
from routes.pipeline_v2_routes import pipeline_v2_bp
from services.native_pipeline_system import NativePipelineSystemService


class FixtureAdapter:
    def execute(self, execution):
        output = Path(execution.workdir) / 'result.txt'
        output.write_text('Session-scoped component output', encoding='utf-8')
        return {'success': True, 'logs': {'stdout': 'Session-scoped component output'}, 'outputs': {}}


def create_fixture_app(directory):
    app = Flask(__name__)
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=f'sqlite:///{directory}/browser.sqlite',
                      SQLALCHEMY_TRACK_MODIFICATIONS=False, JWT_SECRET_KEY=str(uuid4()) + str(uuid4()))
    db.init_app(app)
    JWTManager(app)
    CORS(app, origins=['http://127.0.0.1:4175'])
    setup_error_handlers(app)
    app.register_blueprint(pipeline_v2_bp, url_prefix='/api/v2')
    service = NativePipelineSystemService()
    service.ensure_seeded = lambda *args, **kwargs: None
    service._should_route_component_to_hpc_link = lambda *args, **kwargs: False
    service._adapter_registry['local_cli'] = FixtureAdapter()
    app.native_pipeline_service = service
    # Only broker delivery and external computation are replaced. Reservations,
    # dispatch commits, permissions, paths and worker finalization use production code.
    task = SimpleNamespace(apply_async=lambda **kwargs: SimpleNamespace(id=kwargs['task_id']))
    sys.modules['tasks'] = SimpleNamespace(execute_playground_task=task)
    sys.modules['celery_app'] = SimpleNamespace(celery=SimpleNamespace(AsyncResult=lambda _: SimpleNamespace(state='PENDING')))
    with app.app_context():
        db.create_all()
        component = ComponentDefinition(key='browser_component', name='Browser component', source_type='local')
        db.session.add(component)
        db.session.flush()
        manifest = {
            'metadata': {'name': component.key, 'label': 'Browser component', 'version': '1.0.0'},
            'inputs': [{'name': 'files', 'label': 'Files', 'type': 'file_list', 'required': True}],
            'outputs': [], 'parameter_groups': [], 'compatibility': {},
            'execution': {'profiles': [{'id': 'local', 'adapter': 'local_cli', 'entrypoint': ['browser-component']}]},
        }
        version = ComponentVersion(component_definition_id=component.id, version='1.0.0', manifest_json=json.dumps(manifest), manifest_hash='browser-fixture')
        db.session.add(version)
        db.session.flush()
        db.session.add(ComponentProfile(component_version_id=version.id, profile_id='local', adapter='local_cli', entrypoint_json='["browser-component"]'))
        db.session.commit()

    @app.get('/__test__/health')
    def health():
        return jsonify(ready=True)

    @app.post('/__test__/fixture')
    def fixture():
        label = str(uuid4())
        users = [User(email=f'{name}-{label}@example.com', password_hash='test-only-hash') for name in ('owner', 'other')]
        db.session.add_all(users)
        db.session.flush()
        workspace = Path(directory) / label
        workspace.mkdir()
        source = workspace / 'model.glb'
        source.write_bytes(b'model')
        session = Session(user_id=users[0].id, session_dir=str(workspace), hdpc_path=str(workspace / 'project.hdpc'))
        db.session.add(session)
        db.session.commit()
        return jsonify(session_id=session.id, path=str(source), owner_id=users[0].id,
                       owner_token=create_access_token(identity=str(users[0].id)),
                       other_token=create_access_token(identity=str(users[1].id)))

    @app.post('/__test__/runs/<run_id>/deliver')
    def deliver(run_id):
        if not PlaygroundRun.query.filter_by(public_id=run_id).first():
            return jsonify(error='Unknown fixture run'), 404
        result = service.execute_playground_run(run_id)
        return jsonify(run=result)

    return app


if __name__ == '__main__':
    if os.environ.get('WEBHDP_BROWSER_TESTING') != '1':
        raise SystemExit('Set WEBHDP_BROWSER_TESTING=1 to run this isolated test server.')
    with TemporaryDirectory(prefix='webhdp-browser-') as directory:
        run_simple('127.0.0.1', 4876, create_fixture_app(directory), use_reloader=False, threaded=False)
