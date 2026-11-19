"""Isolated HTTP fixture for browser tests of the real native execution routes."""
import json
import base64
import hashlib
from collections import Counter
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token
from flask_mail import Mail
from werkzeug.serving import run_simple

from database.database import db
from database.models import ComponentDefinition, ComponentProfile, ComponentVersion, PlaygroundRun, PipelineRun, Session, User, UserRole
from middleware import setup_error_handlers
from routes.auth_routes import auth_bp
from routes.institution_invitation_routes import institution_invitation_bp
from routes.institution_routes import institution_bp
from routes.pipeline_v2_routes import pipeline_v2_bp
from services.native_pipeline_system import NativePipelineSystemService
from routes.session_routes import session_bp
from routes.single_file_routes import single_file_bp, SINGLE_FILE_ALLOWED_EXTENSIONS
from routes.metadata_routes import metadata_bp
from routes.template_routes import template_bp
from services.project_service import ProjectService
from services.msf_service import MSFService
from services.edm_service import EdmService
from services.email_service import EmailService
from session_manager import SessionManager
from services.submission_pipeline_service import execute_submission_pipeline
from unittest.mock import patch
import yaml


class FixtureAdapter:
    def __init__(self):
        self.calls = Counter()
        self.failures = {}

    def execute(self, execution):
        record = execution.metadata.get('record_context')
        if record:
            sid = execution.metadata['execution_context']['db_session_id']
            self.calls[(sid, record['record_id'], execution.step_id)] += 1
            if execution.step_id == 'detail' and self.failures.get(sid, True):
                return {'success': False, 'error': 'Derivative processing was interrupted. Review and continue the saved work.', 'outputs': {}}
            source = Path(execution.inputs['input_file'])
            data = source.read_bytes()
            if execution.step_id == 'prepare':
                output = Path(execution.workdir) / 'prepared.glb'
                output.write_bytes(data)
                return {'success': True, 'outputs': {'normalized_asset': str(output)},
                        'artifacts': [{'name': output.name, 'path': str(output), 'artifact_kind': 'model'}]}
            outputs, levels, artifacts = {}, {}, []
            for level in ('high', 'medium', 'low'):
                output = Path(execution.workdir) / f'lod-{level}.glb'
                output.write_bytes(data)
                outputs['lod_' + level] = str(output)
                levels[level] = {'triangles': 1, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                    'reduction_percent': 0, 'geometry_checks': [{'mesh': 'Triangle', 'status': 'retained',
                    'reason': 'Already at the minimum surface budget.', 'sampled_error': 0, 'error_limit': 0.001}]}
                artifacts.append({'name': output.name, 'path': str(output), 'artifact_kind': 'model'})
            report = Path(execution.workdir) / 'lod-report.json'
            report.write_text(json.dumps({'component': 'geometric_lod_generator', 'source_triangles': 1,
                'source_filename': source.name, 'source_bytes': len(data), 'source_sha256': hashlib.sha256(data).hexdigest(),
                'levels': levels, 'blender_version': 'fixture', 'quality_note': 'Geometry sampling requires visual appearance review.'}))
            outputs['analysis_report'] = str(report)
            artifacts.append({'name': report.name, 'path': str(report), 'artifact_kind': 'report'})
            return {'success': True, 'outputs': outputs, 'artifacts': artifacts}
        output = Path(execution.workdir) / 'result.txt'
        output.write_text('Session-scoped component output', encoding='utf-8')
        return {'success': True, 'logs': {'stdout': 'Session-scoped component output'}, 'outputs': {}}


def create_fixture_app(directory):
    app = Flask(__name__, root_path=str(ROOT))
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=f'sqlite:///{directory}/browser.sqlite',
                      SQLALCHEMY_TRACK_MODIFICATIONS=False, JWT_SECRET_KEY=str(uuid4()) + str(uuid4()),
                      SECRET_KEY=str(uuid4()), MAX_CONTENT_LENGTH=32 * 1024 * 1024,
                      ALLOWED_EXTENSIONS=SINGLE_FILE_ALLOWED_EXTENSIONS, STORAGE_MODE='server_only',
                      WEBHDP_DEPLOYMENT_MODE='local', WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=True,
                      ENABLE_RENDERER=False, ENABLE_USDZ_CONVERSION=False, ENABLE_METIS_VALIDATION=False,
                      FRONTEND_URL='http://127.0.0.1:4175')
    os.environ['SHARED_SESSION_PATH'] = directory
    db.init_app(app)
    JWTManager(app)
    CORS(app, origins=['http://127.0.0.1:4175'])
    setup_error_handlers(app)
    app.register_blueprint(auth_bp, url_prefix='/api/v1/auth')
    app.register_blueprint(institution_bp, url_prefix='/api/v1/institutions')
    app.register_blueprint(institution_invitation_bp, url_prefix='/api/v1/institutions')
    mailbox = []
    Mail(app)
    app.email_service = EmailService(SimpleNamespace(send=mailbox.append))
    app.register_blueprint(pipeline_v2_bp, url_prefix='/api/v2')
    app.register_blueprint(session_bp, url_prefix='/api/v1/sessions')
    app.register_blueprint(single_file_bp, url_prefix='/api/v1/sessions')
    app.register_blueprint(metadata_bp, url_prefix='/api/v1/metadata')
    app.register_blueprint(template_bp, url_prefix='/api/v1/templates')
    app.project_service = ProjectService()
    app.msf_service = MSFService()
    app.edm_service = EdmService()
    app.session_manager = SessionManager.__new__(SessionManager)
    service = NativePipelineSystemService()
    service.ensure_seeded = lambda *args, **kwargs: None
    service._should_route_component_to_hpc_link = lambda *args, **kwargs: False
    adapter = FixtureAdapter()
    service._adapter_registry['local_cli'] = adapter
    service._adapter_registry['container_cli'] = adapter
    app.native_pipeline_service = service
    # Broker delivery, deployment status and external computation are isolated.
    # Uploads, metadata, reservations, permissions and finalization use production code.
    task = SimpleNamespace(apply_async=lambda **kwargs: SimpleNamespace(id=kwargs['task_id']))
    sys.modules['tasks'] = SimpleNamespace(execute_playground_task=task, execute_submission_pipeline_task=task)
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
        service._ensure_builtin_components_seeded()
        component_dir = Path(directory) / 'workflow-component'
        component_dir.mkdir()
        (component_dir / 'component.yaml').write_text(yaml.safe_dump({
            'metadata': {'name': 'browser_prepare', 'label': 'Prepare source', 'version': '1.0.0'},
            'inputs': [{'name': 'input_file', 'type': 'file_path', 'required': True}],
            'outputs': [{'name': 'normalized_asset', 'type': 'file_path'}],
            'parameter_groups': [{'id': 'curation', 'label': 'Curation', 'parameters': [{'name': 'curation_note', 'label': 'Curation note', 'type': 'string', 'required': True}]}],
            'execution': {'profiles': [{'id': 'local', 'adapter': 'local_cli', 'entrypoint': ['fixture-prepare']}]},
        }))
        service.import_component_from_path(str(component_dir))
        lod_dir = Path(directory) / 'lod-component'
        lod_dir.mkdir()
        manifest = (ROOT / 'external_code/geometric_lod_generator/component.yaml').read_text()
        (lod_dir / 'component.yaml').write_text(manifest.replace('webhdp-geometric-lod-generator:local', 'example/lod@sha256:' + 'a' * 64))
        service.import_component_from_path(str(lod_dir))
        service.create_pipeline_version_from_config('browser_workflow', {'name': 'Local review workflow', 'steps': [
            {'id': 'prepare', 'name': 'Prepare source', 'component_ref': 'browser_prepare', 'execution_profile_ref': 'local', 'scope': 'record',
             'input_bindings': [{'kind': 'input', 'target': 'input_file', 'type': 'pipeline_source_file'}],
             'parameter_bindings': [{'kind': 'parameter', 'target': 'curation_note', 'type': 'record_metadata_field', 'metadata_field': 'notes'}]},
            {'id': 'detail', 'name': 'Generate detail levels', 'component_ref': 'geometric_lod_generator', 'execution_profile_ref': 'local_docker', 'scope': 'record',
             'input_bindings': [{'kind': 'input', 'target': 'input_file', 'type': 'artifact_file', 'source_step': 'prepare', 'source_output': 'normalized_asset'}]},
        ]})
        from database.lod_template_bootstrap import ensure_default_lod_templates
        ensure_default_lod_templates()

    @app.get('/__test__/health')
    def health():
        return jsonify(ready=True)

    @app.post('/__test__/identity/fixture')
    def identity_fixture():
        label = uuid4().hex
        admin = User(email=f'admin-{label}@example.com', role=UserRole.ADMIN, is_verified=True, password_hash='fixture')
        requester = User(email=f'requester-{label}@example.com', role=UserRole.USER, is_verified=True, password_hash='fixture')
        db.session.add_all([admin, requester])
        db.session.commit()
        return jsonify(admin_token=create_access_token(identity=str(admin.id)),
                       requester_token=create_access_token(identity=str(requester.id)),
                       invited_email=f'invitee-{label}@example.com')

    @app.get('/__test__/identity/mail')
    def identity_mail():
        email = request.args.get('email')
        kind = request.args.get('kind')
        path = {'verification': 'verify-email', 'invitation': 'institution-invitation'}.get(kind)
        if path:
            for message in reversed(mailbox):
                if email in message.recipients:
                    match = re.search(rf'http://127\.0\.0\.1:4175/{path}#token=[A-Za-z0-9_-]+', message.body or '')
                    if match:
                        return jsonify(url=match.group())
        return jsonify(error='Mail not found'), 404

    @app.get('/api/v1/admin/storage-status')
    def storage_status():
        return jsonify(success=True, data={'config': {'storage_mode': 'server_only'}, 'active_storage': 'server', 'services': {}})

    @app.get('/api/v1/health')
    def deployment_health():
        return jsonify(success=True, data={'config': {'enable_renderer': False, 'enable_usdz_conversion': False, 'enable_metis_validation': False}})

    @app.get('/api/v1/hpc-link/status')
    def runtime_status():
        return jsonify(success=True, data={'available': False, 'component_runtime': {
            'geometric_lod_generator': {'status': 'local_allowed'}, 'browser_prepare': {'status': 'local_allowed'}}})

    @app.post('/__test__/workflow/fixture')
    def workflow_fixture():
        from test_mesh_optimizer_component import glb
        user = User(email=f'workflow-{uuid4()}@example.com', password_hash='test-only-hash', role=UserRole.ADMIN, is_verified=True)
        db.session.add(user)
        db.session.commit()
        source = glb(Path(directory) / f'{uuid4()}.glb', scenes=[{'nodes': [0]}], nodes=[{'mesh': 0}])
        return jsonify(owner_id=user.id, owner_token=create_access_token(identity=str(user.id)),
                       model_base64=base64.b64encode(source.read_bytes()).decode())

    @app.post('/__test__/runs/<run_id>/correct')
    def correct(run_id):
        run = PipelineRun.query.filter_by(public_id=run_id).one()
        adapter.failures[run.session_id] = False
        return jsonify(corrected=True)

    @app.get('/__test__/runs/<run_id>/observations')
    def observations(run_id):
        run = PipelineRun.query.filter_by(public_id=run_id).one()
        return jsonify(calls=[{'record_id': rid, 'step': step, 'count': count} for (sid, rid, step), count in adapter.calls.items() if sid == run.session_id])

    @app.post('/__test__/fixture')
    def fixture():
        label = str(uuid4())
        users = [User(email=f'{name}-{label}@example.com', password_hash='test-only-hash', is_verified=True)
                 for name in ('owner', 'other')]
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
        pipeline = PipelineRun.query.filter_by(public_id=run_id).first()
        if pipeline:
            payload = json.loads(pipeline.request_json)
            with patch('services.submission_pipeline_service.publishing_context_service.resolve_token_for_session', return_value={'environment': 'sandbox', 'source': 'user', 'token': None}):
                result = execute_submission_pipeline(identifier=payload['pipeline_identifier'],
                    db_session_id=pipeline.session_id, local_file_paths=payload.get('local_file_paths'),
                    record_ids=payload.get('record_ids'), execution_items=payload.get('execution_items'),
                    precreated_run_public_id=run_id, progress_callback=lambda progress: service.update_run_progress(run_id, progress))
            return jsonify(run=service.get_pipeline_run(run_id, pipeline.initiated_by_user_id))
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
