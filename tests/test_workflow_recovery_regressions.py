"""Recovery preserves record identity and honest upload readiness."""
import json
import sqlite3
from unittest.mock import Mock

import pytest

from test_lod_reliability import services_app, specification
from test_hdpc_zenodo_service import _create_hdpc_with_source, _DummyZenodoHttp
from services.hdpc_local_service import add_local_source_files, create_local_record_with_metadata, read_hdpc_record_context
from services.hdpc_zenodo_service import create_api_draft, upload_files_for_deposition, publish_record
from services.lod_artifact_service import generate_artifacts, suspend_previous_artifacts, record_lod_readiness
from services.submission_pipeline_service import _split_batch_shared_zenodo_metadata
from services.linked_data_service import generate_linked_data


def test_batch_preview_never_becomes_another_records_file():
    shared, _ = _split_batch_shared_zenodo_metadata({'edm_main_file_key': 'sample-A.glb', 'edm_provider': 'Museum'})
    assert shared == {'edm_provider': 'Museum'}
    for filename in ['model-B.glb', 'image-C.tif', '模型.glb']:
        content = generate_linked_data({'title': filename}, {'id': 123}, main_file_key=shared.get('edm_main_file_key') or filename)['jsonld'][1]
        assert 'sample-A.glb' not in content
        assert filename in content


@pytest.mark.parametrize('interrupt_at', [0, 1, 4])
def test_interrupted_retry_journals_all_formats_and_preserves_cache(tmp_path, interrupt_at):
    app = services_app()
    app.edm_service.validate_edm_document.return_value = {'valid': True}
    with app.app_context():
        generate_artifacts(str(tmp_path), specification(), Mock())
        def interrupt(standard, index, count):
            if index == interrupt_at:
                raise SystemExit('Worker terminated')
        with pytest.raises(SystemExit):
            generate_artifacts(str(tmp_path), specification(), Mock(), interrupt)
        manifest = json.loads((tmp_path / 'lod-generation.json').read_text())
        assert len(manifest['formats']) == 5
        assert any(not item['success'] for item in manifest['formats'].values())
        _, retried = generate_artifacts(str(tmp_path), specification(), Mock())
        assert all(item.get('reused') for item in retried['formats'].values())
        assert app.edm_service.generate_edm_xml_with_report.call_count == 1


def test_progress_reporting_failure_does_not_interrupt_generation(tmp_path):
    app = services_app()
    app.edm_service.validate_edm_document.return_value = {'valid': True}
    with app.app_context():
        outputs, _ = generate_artifacts(str(tmp_path), specification(), Mock(), Mock(side_effect=RuntimeError('offline')))
    assert len(outputs) == 5


@pytest.fixture
def record(tmp_path):
    app = services_app()
    app.edm_service.validate_edm_document.return_value = {'valid': True}
    hdpc = str(tmp_path / 'project.hdpc')
    _create_hdpc_with_source(hdpc, str(tmp_path))
    create_local_record_with_metadata(hdpc, file_id=101, metadata={'title': 'Object'}, is_sandbox=True, access_token='test-token')
    http = _DummyZenodoHttp()
    create_api_draft(hdpc, 1, http=http)
    output = str(tmp_path / 'outputs' / 'record-1' / 'model')
    def register(path, validation):
        result = add_local_source_files(hdpc, absolute_file_paths=[path], record_id_to_associate=1, pipeline_name='lod_generation', validation_reports={path: validation})
        assert result['success']
    with app.app_context():
        yield app, hdpc, output, register, http


def test_unchanged_retry_preserves_uploaded_files_and_blocks_upload_while_suspended(record):
    app, hdpc, output, register, http = record
    generate_artifacts(output, specification(), register)
    assert upload_files_for_deposition(hdpc, 1, http=http)['success']
    puts = len(http.put_calls)
    suspend_previous_artifacts(hdpc, 1)
    suspend_previous_artifacts(hdpc, 1)  # Repeated interruption must retain the original upload status.
    assert not upload_files_for_deposition(hdpc, 1, http=http)['success']
    assert not publish_record(hdpc, 1, http=http)['success']
    assert len(http.put_calls) == puts
    assert not read_hdpc_record_context(hdpc, 1)['zenodo_status']['actions']['can_publish']
    _, report = generate_artifacts(output, specification(), register)
    assert all(item.get('reused') for item in report['formats'].values())
    readiness = record_lod_readiness(hdpc, 1)
    assert readiness['ready'] and readiness['pending_upload_count'] == 0
    assert upload_files_for_deposition(hdpc, 1, http=http)['success']
    assert len(http.put_calls) == puts


def test_changed_retry_only_queues_changed_outputs(record):
    app, hdpc, output, register, http = record
    spec = specification()
    generate_artifacts(output, spec, register)
    assert upload_files_for_deposition(hdpc, 1, http=http)['success']
    spec['metadata']['edm']['title'] = 'Revised'
    app.edm_service.generate_edm_xml_with_report.return_value = {'content': '<rdf>revised</rdf>'}
    suspend_previous_artifacts(hdpc, 1)
    generate_artifacts(output, spec, register)
    assert record_lod_readiness(hdpc, 1)['pending_upload_count'] == 1
    with sqlite3.connect(hdpc) as conn:
        pending = conn.execute("SELECT filename FROM source_files JOIN record_files_map USING(file_id) WHERE upload_status='pending'").fetchall()
    assert pending == [('edm.xml',)]


def test_first_failed_required_export_blocks_upload_even_without_file_mapping(record):
    app, hdpc, output, register, http = record
    app.edm_service.validate_edm_document.return_value = {'valid': False}
    generate_artifacts(output, specification(), register)
    result = upload_files_for_deposition(hdpc, 1, http=http)
    assert not result['success']
    assert result['readiness']['blocked_formats'] == ['edm']
    assert not http.put_calls
    app.edm_service.validate_edm_document.return_value = {'valid': True}
    generate_artifacts(output, specification(), register)
    assert record_lod_readiness(hdpc, 1)['ready']


def test_tampered_uploaded_export_blocks_readiness(record):
    from pathlib import Path
    _, hdpc, output, register, http = record
    generate_artifacts(output, specification(), register)
    assert upload_files_for_deposition(hdpc, 1, http=http)['success']
    Path(output, 'edm.xml').write_text('changed')
    assert not record_lod_readiness(hdpc, 1)['ready']


def test_operations_summary_excludes_validation_blocked_records(record):
    from services.hdpc_local_service import read_hdpc_operations_summary
    app, hdpc, output, register, _ = record
    app.edm_service.validate_edm_document.return_value = {'valid': False}
    generate_artifacts(output, specification(), register)
    summary = read_hdpc_operations_summary(hdpc)
    assert summary['actionable_operations']['upload_files']['count'] == 0
    assert summary['actionable_operations']['publish_records']['count'] == 0
    assert summary['summary']['uploadable_item_count'] == 0
