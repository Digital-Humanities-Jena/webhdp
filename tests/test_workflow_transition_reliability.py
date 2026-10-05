import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from services.hdpc_local_service import add_local_source_files, create_local_record_with_metadata, read_hdpc_operations_summary
from services.hdpc_zenodo_service import create_api_draft, discard_draft, publish_record, upload_files_for_deposition
from services.hdpc_schema_service import connect_hdpc
from services.lod_artifact_service import generate_artifacts, record_lod_readiness, suspend_previous_artifacts
from services.pipeline_execution_lock import PipelineAlreadyRunning, session_pipeline_lock
from services.session_batch_service import execute_session_batch_operation
from test_hdpc_zenodo_service import _create_hdpc_with_source, _DummyZenodoHttp
from test_lod_reliability import services_app, specification


@contextmanager
def locked_by_other_process(path):
    process = subprocess.Popen([sys.executable, '-c',
        'import sys\nfrom services.pipeline_execution_lock import session_pipeline_lock\n'
        'with session_pipeline_lock(sys.argv[1]):\n print("locked", flush=True)\n sys.stdin.read()', str(path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == 'locked'
        yield
    finally:
        process.communicate('', timeout=10)
        assert process.returncode == 0


@pytest.fixture
def record(tmp_path):
    app = services_app()
    app.edm_service.validate_edm_document.return_value = {'valid': True}
    with app.app_context():
        hdpc = str(tmp_path / 'project.hdpc')
        _create_hdpc_with_source(hdpc, str(tmp_path))
        create_local_record_with_metadata(hdpc, file_id=101, metadata={'title': 'Object'}, access_token='test-token')
        http = _DummyZenodoHttp()
        create_api_draft(hdpc, 1, http=http)
        from services.lod_artifact_service import current_record_context
        initial_record = current_record_context(hdpc, 1)
        def generate(spec):
            spec = {**spec, 'record': initial_record}
            suspend_previous_artifacts(hdpc, 1)
            return generate_artifacts(str(tmp_path / 'outputs/record-1/model'), spec,
                lambda path, validation: add_local_source_files(hdpc, absolute_file_paths=[path],
                    record_id_to_associate=1, pipeline_name='lod_generation', validation_reports={path: validation}),
                hdpc_path=hdpc, record_id=1)
        yield app, hdpc, http, generate


def test_batch_and_direct_mutations_respect_another_worker_lock(record):
    _, hdpc, http, _ = record
    service = Mock()
    with locked_by_other_process(hdpc):
        with pytest.raises(PipelineAlreadyRunning):
            execute_session_batch_operation(session=SimpleNamespace(hdpc_path=hdpc), project_service=service,
                                            operation_type='upload_files', target_ids=[1])
        with pytest.raises(PipelineAlreadyRunning):
            upload_files_for_deposition(hdpc, 1, http=http)
    service.upload_files_for_deposition.assert_not_called()
    # Nested mutations within one owning operation remain usable.
    with session_pipeline_lock(hdpc):
        assert upload_files_for_deposition(hdpc, 1, http=http)['success']


def test_queued_publication_rechecks_new_pending_attachment(record, tmp_path, monkeypatch):
    _, hdpc, http, _ = record
    assert upload_files_for_deposition(hdpc, 1, http=http)['success']
    extra = tmp_path / 'required.txt'
    extra.write_text('required')
    add_local_source_files(hdpc, absolute_file_paths=[str(extra)], record_id_to_associate=1)
    monkeypatch.setenv('ZENODO_PUBLISH_ENABLED', 'true')
    monkeypatch.setattr('services.session_batch_service.ensure_record_operation_allowed', lambda *a, **k: None)
    service = SimpleNamespace(publish_record=lambda target, **kw: publish_record(kw['hdpc_path'], target, http=http))
    result = execute_session_batch_operation(session=SimpleNamespace(hdpc_path=hdpc), project_service=service,
                                            operation_type='publish_records', target_ids=[1])
    assert result['summary']['failed'] == 1
    assert not any(url.endswith('/actions/publish') for url, _ in http.post_calls)


def test_missing_all_metadata_reports_blocks_already_uploaded_artifacts(record):
    _, hdpc, http, generate = record
    generate(specification())
    assert upload_files_for_deposition(hdpc, 1, http=http)['success']
    (Path(hdpc).parent / 'outputs/record-1/model/lod-generation.json').unlink()
    with connect_hdpc(hdpc) as conn:
        conn.execute("DELETE FROM zenodo_record_snapshots WHERE snapshot_stage = 'lod_generation'")
    readiness = record_lod_readiness(hdpc, 1)
    assert not readiness['ready']
    assert 'missing' in readiness['recovery_message']
    assert not upload_files_for_deposition(hdpc, 1, http=http)['success']


def test_private_recovery_state_is_excluded_from_record_details_and_shared_exports(record):
    from services.hdpc_local_service import read_hdpc_record_context
    from services.hdpc_shared_export_service import create_sanitized_shared_export
    _, hdpc, _, generate = record
    generate(specification())
    context = read_hdpc_record_context(hdpc, 1)
    assert all(item['snapshot_stage'] != 'lod_generation' for item in context['traceability']['snapshots'])
    assert context['zenodo_status']['summary']['latest_snapshot_stage'] != 'lod_generation'
    exported = create_sanitized_shared_export(hdpc, source_session_id=1, source_institution_id=1, source_owner_user_id=1)
    try:
        with connect_hdpc(exported) as conn:
            assert conn.execute("SELECT count(*) FROM zenodo_record_snapshots WHERE snapshot_stage = 'lod_generation'").fetchone()[0] == 0
    finally:
        Path(exported).unlink()


def test_current_policy_blocks_already_uploaded_outputs_and_retry_restores_readiness(record):
    app, hdpc, http, generate = record
    generate(specification())
    assert upload_files_for_deposition(hdpc, 1, http=http)['success']
    app.config['LOCAL_EDM_VALIDATOR_REQUIRED'] = True
    assert record_lod_readiness(hdpc, 1)['revalidation_required']
    assert not upload_files_for_deposition(hdpc, 1, http=http)['success']
    generate(specification())
    assert not record_lod_readiness(hdpc, 1)['ready']
    app.edm_service.validate_edm_document.return_value = {'valid': True, 'details': {'remote': {'valid': True}}}
    generate(specification())
    assert record_lod_readiness(hdpc, 1)['ready']


@pytest.mark.parametrize('uploaded', [False, True])
def test_disable_retry_sync_and_reenable_preserve_consistent_attachment_set(record, uploaded):
    _, hdpc, http, generate = record
    spec = specification()
    generate(spec)
    if uploaded:
        assert upload_files_for_deposition(hdpc, 1, http=http)['success']
    spec['options']['generate_edm'] = False
    for _ in range(2):
        generate(spec)
        assert record_lod_readiness(hdpc, 1)['ready']
    if uploaded:
        assert record_lod_readiness(hdpc, 1)['pending_upload_count'] == 1
        assert read_hdpc_operations_summary(hdpc)['actionable_operations']['upload_files']['count'] == 1
    assert upload_files_for_deposition(hdpc, 1, http=http)['success']
    assert not any(item['filename'] == 'edm.xml' for item in http.draft_files)
    assert record_lod_readiness(hdpc, 1)['state'] == 'uploaded'
    spec['options']['generate_edm'] = True
    generate(spec)
    assert record_lod_readiness(hdpc, 1)['pending_upload_count'] == 1
    assert upload_files_for_deposition(hdpc, 1, http=http)['success']
    assert record_lod_readiness(hdpc, 1)['state'] == 'uploaded'


def test_disabled_remote_file_removal_recovers_after_lost_response(record):
    _, hdpc, http, generate = record
    spec = specification()
    generate(spec)
    upload_files_for_deposition(hdpc, 1, http=http)
    spec['options']['generate_edm'] = False
    generate(spec)
    delete = http.delete
    def lost_response(*args, **kwargs):
        delete(*args, **kwargs)
        raise ConnectionError('response lost')
    with patch.object(http, 'delete', side_effect=lost_response):
        with pytest.raises(ConnectionError):
            upload_files_for_deposition(hdpc, 1, http=http)
    assert record_lod_readiness(hdpc, 1)['pending_upload_count'] == 1
    assert upload_files_for_deposition(hdpc, 1, http=http)['success']
    assert record_lod_readiness(hdpc, 1)['state'] == 'uploaded'


def test_discarding_and_recreating_a_draft_does_not_restore_disabled_exports(record):
    _, hdpc, http, generate = record
    spec = specification()
    generate(spec)
    upload_files_for_deposition(hdpc, 1, http=http)
    spec['options']['generate_edm'] = False
    generate(spec)
    assert discard_draft(hdpc, 1, http=http)['success']
    http.draft_files = []
    assert create_api_draft(hdpc, 1, http=http)['success']
    assert upload_files_for_deposition(hdpc, 1, http=http)['success']
    assert not any(item['filename'] == 'edm.xml' for item in http.draft_files)
    assert record_lod_readiness(hdpc, 1)['state'] == 'uploaded'


def test_killed_execution_process_is_reconciled_without_reexecution(tmp_path):
    from flask import Flask
    from database.database import db
    from database.models import Session, User
    from services.native_pipeline_system import NativePipelineSystemService
    app = Flask(__name__)
    database_uri = f'sqlite:///{tmp_path / "application.db"}'
    app.config.update(SQLALCHEMY_DATABASE_URI=database_uri, SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    with app.app_context():
        db.create_all()
        user = User(email='worker@example.com', password_hash='test-only-hash')
        db.session.add(user)
        db.session.flush()
        hdpc = str(tmp_path / 'project.hdpc')
        _create_hdpc_with_source(hdpc, str(tmp_path))
        session = Session(user_id=user.id, session_dir=str(tmp_path), hdpc_path=hdpc)
        db.session.add(session)
        db.session.commit()
        service = NativePipelineSystemService()
        # This fixture exercises worker recovery; source readiness is covered separately.
        with patch.object(service, 'require_submission_readiness', return_value={'_state': None}):
            queued = service.create_pending_run('render', session_id=session.id, initiated_by_user_id=user.id, request_payload={})
        script = '''
import sys
from flask import Flask
from database.database import db
from services.native_pipeline_system import NativePipelineSystemService
app = Flask(__name__)
app.config.update(SQLALCHEMY_DATABASE_URI=sys.argv[1], SQLALCHEMY_TRACK_MODIFICATIONS=False)
db.init_app(app)
with app.app_context():
    service = NativePipelineSystemService()
    def running(*args):
        print('executing', flush=True)
        sys.stdin.read()
    service._run_native_pipeline = running
    service.execute_registered_submission('render', {'db_session_id': int(sys.argv[2])}, existing_run_public_id=sys.argv[3])
'''
        process = subprocess.Popen([sys.executable, '-c', script, database_uri, str(session.id), queued['run_id']],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            assert process.stdout.readline().strip() == 'executing'
            assert service.get_pipeline_run(queued['run_id'])['status'] == 'running'
            process.kill()
            process.communicate(timeout=10)
            result = service.get_pipeline_run(queued['run_id'])
            assert result['status'] == 'failed'
            assert result['result']['interrupted']
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
        db.session.remove()
