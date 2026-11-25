"""Independently validate and atomically promote metadata formats.

The manifest is private recovery state, never a record attachment. Retrying this
operation does not create a remote draft or execute a renderer or upload.
"""
import json
import os
from pathlib import Path
from flask import current_app, has_app_context
from services.edm_service import EDM_SCHEMA_VERSION
from services.lod_reliability import FORMATS, assert_public_document, atomic_write, digest, pinned_templates

FILENAMES = dict(edm='edm.xml', iiif='iiif.json', mets='mets.xml', cidoc_crm='cidoc-crm.xml', jsonld='metadata.jsonld')
EDM_POLICY_KEYS = ('LOCAL_EDM_VALIDATOR_REQUIRED', 'ENABLE_LOCAL_EDM_VALIDATION', 'ENABLE_METIS_VALIDATION',
                   'LOCAL_EDM_VALIDATOR_URL', 'METIS_SANDBOX_URL', 'ENABLE_XSD_VALIDATION')


def lod_record_is_finalized(record_status):
    return str(record_status or '').strip().lower() in {'published', 'done', 'submitted', 'completed'}


def current_record_context(hdpc_path, record_id):
    from services.hdpc_schema_service import connect_hdpc
    from services.edm_service import EdmService
    with connect_hdpc(hdpc_path) as conn:
        row = conn.execute('SELECT zenodo_record_id, record_metadata_json, is_sandbox, zenodo_doi FROM zenodo_records WHERE record_id = ?', (int(record_id),)).fetchone()
    if not row or not row[0]:
        raise ValueError('Create a Zenodo draft before regenerating metadata.')
    payload = json.loads(row[1] or '{}')
    service = EdmService()
    # Construct the public origin from the saved environment; never reuse an
    # authenticated draft link in public metadata.
    public = {'id': row[0], 'links': {'html': 'https://sandbox.zenodo.org' if row[2] else 'https://zenodo.org'}}
    reserved = (payload.get('metadata') or {}).get('prereserve_doi') or {}
    return {'id': str(row[0]), 'doi': payload.get('doi') or reserved.get('doi') or row[3] or None,
            'links': {'html': service.get_record_html_url(public)},
            'metadata': {'prereserve_doi': reserved},
            'files': [{'key': item.get('key') or item.get('filename'), 'size': item.get('size', 0)}
                      for item in service._normalize_zenodo_files(payload)]}


def record_context_changed(manifest, hdpc_path, record_id):
    def identity(record):
        from services.edm_service import EdmService
        return (str(record.get('id') or ''), record.get('doi') or (record.get('metadata') or {}).get('prereserve_doi', {}).get('doi') or '',
                EdmService().get_record_html_url(record))
    try:
        return identity(manifest['request']['record']) != identity(current_record_context(hdpc_path, record_id))
    except (ValueError, KeyError, TypeError, AttributeError):
        return True


def load_record_manifest(hdpc_path, record_id):
    """Read private recovery state even if the output directory was lost."""
    from services.hdpc_schema_service import connect_hdpc, table_exists
    root = Path(hdpc_path).resolve().parent / 'outputs' / f'record-{int(record_id)}'
    with connect_hdpc(hdpc_path) as conn:
        row = conn.execute("SELECT payload_json FROM zenodo_record_snapshots WHERE record_id = ? AND snapshot_stage = 'lod_generation' ORDER BY snapshot_id DESC LIMIT 1", (int(record_id),)).fetchone() if table_exists(conn.cursor(), 'zenodo_record_snapshots') else None
    if row:
        saved = json.loads(row[0])
        path = root / saved['directory'] / 'lod-generation.json'
        if not path.resolve().is_relative_to(root) or path.parent == root:
            raise ValueError('The metadata report is outside this record')
        return path, complete_format_states(saved['manifest'])
    paths = list(root.glob('*/lod-generation.json'))
    if not paths:
        return None, None
    if len(paths) != 1 or not paths[0].resolve().is_relative_to(root):
        raise ValueError('Ambiguous metadata report')
    return paths[0], complete_format_states(json.loads(paths[0].read_text(encoding='utf-8')))


def validation_policy():
    policy = {key: current_app.config.get(key) for key in EDM_POLICY_KEYS} if has_app_context() else {}
    from services.iiif_validation import PROFILE_VERSION
    policy['iiif_profile'] = PROFILE_VERSION
    return policy


def _generation_fingerprint(specification, policy):
    return digest(json.dumps({'request': specification, 'validation_policy': policy}, sort_keys=True, default=str))


def _policy_changed_for_format(captured, current, standard):
    if standard == 'edm' or not isinstance(captured, dict):
        return captured != current
    captured_shared = {key: value for key, value in captured.items() if key not in EDM_POLICY_KEYS}
    current_shared = {key: value for key, value in current.items() if key not in EDM_POLICY_KEYS}
    return captured_shared != current_shared


def policy_error(manifest, standard, status):
    policy = validation_policy()
    if not policy:
        return None
    captured = manifest.get('validation_policy')
    legacy_changed = captured is None and manifest.get('fingerprint') and manifest['fingerprint'] != _generation_fingerprint(manifest.get('request'), policy)
    if (captured is not None and _policy_changed_for_format(captured, policy, standard)) or legacy_changed:
        return 'Validation requirements changed. Revalidate metadata before continuing.'
    report = status.get('validation') or {}
    if standard == 'edm' and policy.get('LOCAL_EDM_VALIDATOR_REQUIRED') and ((report.get('details') or {}).get('remote') or {}).get('valid') is not True:
        return 'Required EDM validation is missing. Revalidate metadata before continuing.'
    return None


def reconcile_disabled_formats(hdpc_path, record_id, options):
    """Retire disabled attachments locally; remote removal is retried during sync."""
    from services.hdpc_schema_service import connect_hdpc
    with connect_hdpc(hdpc_path) as conn:
        for standard, filename in FILENAMES.items():
            if options.get(f'generate_{standard}', True):
                continue
            conn.execute("""UPDATE record_files_map SET upload_status = CASE
                WHEN upload_status IN ('uploaded', 'validation_pending_uploaded', 'removal_pending')
                     OR COALESCE(zenodo_file_id, '') != '' THEN 'removal_pending' ELSE 'disabled' END
                WHERE record_id = ? AND file_id IN
                (SELECT file_id FROM source_files WHERE pipeline_source = 'lod_generation' AND filename = ?)""",
                (int(record_id), filename))


def complete_format_states(manifest):
    """Unattempted formats remain visible and retryable after an interruption."""
    if not isinstance(manifest, dict) or not isinstance(manifest.get('request'), dict):
        raise ValueError('Invalid metadata report')
    if not isinstance(manifest['request'].get('record'), dict) or not isinstance(manifest['request'].get('options', {}), dict):
        raise ValueError('Invalid metadata generation settings')
    formats = manifest.setdefault('formats', {})
    if not isinstance(formats, dict) or any(not isinstance(status, dict) for status in formats.values()):
        raise ValueError('Invalid metadata format report')
    for standard in FORMATS:
        if standard not in formats:
            enabled = (manifest.get('request', {}).get('options') or {}).get(f'generate_{standard}', True)
            formats[standard] = {'status': 'pending' if enabled else 'skipped_disabled', 'success': not enabled}
    return manifest


def record_lod_readiness(hdpc_path, record_id, *, check_current_policy=True):
    """Read artifact readiness. Finalized records can be viewed using saved validation."""
    from services.hdpc_schema_service import connect_hdpc
    root = Path(hdpc_path).resolve().parent / 'outputs' / f'record-{int(record_id)}'
    blocked_formats = []
    revalidation_required = False
    record_changed = False
    manifest = None
    recovery_message = None
    try:
        path, manifest = load_record_manifest(hdpc_path, record_id)
        if manifest:
            record_changed = record_context_changed(manifest, hdpc_path, record_id)
            for standard, status in manifest['formats'].items():
                if status.get('status') == 'skipped_disabled':
                    continue
                intact = False
                if standard in FILENAMES and status.get('success') and (status.get('validation') or {}).get('valid') is True:
                    artifact = path.parent / FILENAMES[standard]
                    intact = artifact.resolve().is_relative_to(root) and artifact.is_file() and digest(artifact.read_bytes()) == status.get('sha256')
                policy_issue = policy_error(manifest, standard, status) if check_current_policy else None
                revalidation_required = revalidation_required or bool(policy_issue)
                if record_changed or policy_issue or (not intact and manifest.get('request', {}).get('lod_policy', 'required') == 'required'):
                    blocked_formats.append(standard)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        blocked_formats.append('metadata report')
        recovery_message = 'The saved metadata report is unreadable. Start a new pipeline run to regenerate metadata.'
    with connect_hdpc(hdpc_path) as conn:
        rows = conn.execute('SELECT rfm.upload_status, sf.pipeline_source FROM record_files_map rfm LEFT JOIN source_files sf ON sf.file_id = rfm.file_id WHERE rfm.record_id = ?', (int(record_id),)).fetchall()
    if not manifest and any(row[1] == 'lod_generation' and row[0] != 'disabled' for row in rows):
        blocked_formats.append('metadata report')
        recovery_message = recovery_message or 'The saved metadata report is missing. Start a new pipeline run to regenerate metadata.'
    if record_changed:
        recovery_message = 'The Zenodo draft changed. Regenerate metadata to update its record links before continuing.'
    blocked_files = sum(str(row[0]).startswith('validation_pending') for row in rows)
    pending_files = sum(row[0] not in ('uploaded', 'disabled') and not str(row[0]).startswith('validation_pending') for row in rows)
    ready = not blocked_formats and not blocked_files
    return {'available': bool(manifest), 'ready': ready, 'blocked_formats': list(dict.fromkeys(blocked_formats)),
            'record_changed': record_changed, 'recovery_message': recovery_message,
            'revalidation_required': revalidation_required, 'blocked_file_count': blocked_files, 'pending_upload_count': pending_files,
            'state': 'blocked' if not ready else 'upload_required' if pending_files else 'uploaded'}


def generate_artifacts(output_dir, specification, register, progress=None, *, hdpc_path=None, record_id=None):
    manifest_path = os.path.join(output_dir, 'lod-generation.json')
    current_policy = validation_policy()
    if hdpc_path is not None and record_id is not None:
        reconcile_disabled_formats(hdpc_path, record_id, specification['options'])
    def save_manifest(manifest):
        if hdpc_path is not None and record_id is not None:
            from services.hdpc_schema_service import connect_hdpc
            root = Path(hdpc_path).resolve().parent / 'outputs' / f'record-{int(record_id)}'
            directory = Path(output_dir).resolve().relative_to(root)
            if not directory.parts:
                raise ValueError('Metadata outputs need a directory within this record')
            with connect_hdpc(hdpc_path) as conn:
                conn.execute("DELETE FROM zenodo_record_snapshots WHERE record_id = ? AND snapshot_stage = 'lod_generation'", (int(record_id),))
                conn.execute("INSERT INTO zenodo_record_snapshots (record_id, snapshot_stage, payload_json) VALUES (?, 'lod_generation', ?)",
                             (int(record_id), json.dumps({'directory': str(directory), 'manifest': manifest}, default=str)))
        atomic_write(manifest_path, json.dumps(manifest, indent=2, default=str))
    fingerprint = _generation_fingerprint(specification, current_policy)
    try:
        with open(manifest_path, encoding='utf-8') as stream:
            previous = complete_format_states(json.load(stream))
    except (OSError, ValueError):
        previous = {}
    previous_policy = previous.get('validation_policy')
    previous_fingerprint = previous.get('fingerprint')
    same_request = previous_fingerprint == fingerprint or (
        isinstance(previous_policy, dict) and previous_fingerprint == _generation_fingerprint(specification, previous_policy)
    )
    previous_formats = {}
    if same_request:
        cached = previous.get('previous_formats')
        if isinstance(cached, dict):
            previous_formats.update({key: value for key, value in cached.items() if isinstance(value, dict)})
        previous_formats.update({key: value for key, value in previous['formats'].items() if value.get('success')})
        if previous_policy is not None:
            previous_formats = {key: value for key, value in previous_formats.items()
                                if not _policy_changed_for_format(previous_policy, current_policy, key)}
    manifest = complete_format_states({'version': 1, 'fingerprint': fingerprint, 'request': specification, 'validation_policy': current_policy, 'formats': {},
                                      'previous_formats': previous_formats})
    save_manifest(manifest)
    outputs = {}
    options = specification['options']
    with pinned_templates(specification.get('templates')):
        for index, standard in enumerate(FORMATS):
            if progress:
                try:
                    progress(standard, index, len(FORMATS))
                except Exception:
                    current_app.logger.warning('Metadata progress update unavailable')
            status = {'status': 'pending', 'success': False}
            manifest['formats'][standard] = status
            if not options.get(f'generate_{standard}', True):
                status.update(status='skipped_disabled', success=True)
            else:
                path = os.path.join(output_dir, FILENAMES[standard])
                try:
                    old = previous_formats.get(standard) or {}
                    old_validation = old.get('validation') or {}
                    current_edm_schema = standard != 'edm' or (
                        ((old_validation.get('details') or {}).get('xsd') or {}).get('schema_version') == EDM_SCHEMA_VERSION
                    )
                    if (old.get('success') and current_edm_schema and old_validation.get('valid') is True
                            and not policy_error(manifest, standard, old) and old.get('sha256')
                            and old.get('sha256') == old_validation.get('sha256') and os.path.isfile(path)):
                        with open(path, 'rb') as stream:
                            unchanged = digest(stream.read()) == old['sha256']
                        if unchanged:
                            register(path, old_validation)
                            status.update(old, reused=True)
                            outputs[standard] = path
                            save_manifest(manifest)
                            continue
                    metadata = specification['metadata'][standard]
                    kwargs = dict(main_file_key=specification['main_file_key'], additional_files=specification['additional_files'])
                    record = specification['record']
                    if standard in ('cidoc_crm', 'jsonld'):
                        from services.linked_data_service import generate_linked_data, validate_linked_data
                        content = generate_linked_data(metadata, record, **kwargs)[standard][1]
                        generation = {'content': content, 'validation': validate_linked_data(content, standard)}
                    else:
                        kwargs['allow_placeholder_thumbnail'] = specification['allow_placeholder_thumbnail']
                        template_id = (specification.get('templates') or {}).get(standard, {}).get('id') or (specification.get('template_ids') or {}).get(standard) or metadata.get(f'{standard}_template_id')
                        if standard == 'edm':
                            generation = current_app.edm_service.generate_edm_xml_with_report(metadata, record, template_id, validate=False, **kwargs)
                            generation['validation'] = current_app.edm_service.validate_edm_document(generation['content'], metadata=metadata, include_remote=current_app.config.get('LOCAL_EDM_VALIDATOR_REQUIRED', False) or current_app.config.get('ENABLE_LOCAL_EDM_VALIDATION', current_app.config.get('ENABLE_METIS_VALIDATION', True)))
                        elif standard == 'iiif':
                            generation = current_app.iiif_service.generate_iiif_manifest_with_report(metadata, record, template_id, validate=False, **kwargs)
                            generation['validation'] = generation.get('validation') or current_app.iiif_service.validate_iiif_manifest(generation['content'])
                        else:
                            generation = current_app.mets_service.generate_mets_xml_with_report(metadata, record, template_id, validate=False, **kwargs)
                            generation['validation'] = generation.get('validation') or current_app.mets_service.validate_mets_xml(generation['content'])
                    validation = generation.get('validation')
                    if not isinstance(validation, dict) or validation.get('valid') is not True:
                        status['validation'] = validation if isinstance(validation, dict) else {'valid': False, 'errors': ['No validation report was returned']}
                        label = 'METS/MODS' if standard == 'mets' else standard.upper()
                        raise ValueError(f'{label} validation failed. Review the validation report and retry.')
                    issue = policy_error(manifest, standard, {'validation': validation})
                    if issue:
                        raise ValueError(issue)
                    content = generation['content']
                    assert_public_document(content)
                    sha256 = digest(content)
                    validation = {**validation, 'sha256': sha256, 'standard': standard}
                    atomic_write(path, content)
                    register(path, validation)
                    status.update(status='generated', success=True, path=path, sha256=sha256, validation=validation,
                                  minimum_viable_applied=bool(generation.get('minimum_viable_applied')),
                                  adjustments=generation.get('adjustments', []))
                    outputs[standard] = path
                except Exception as exc:
                    status.update(status='failed', error=str(exc))
            save_manifest(manifest)
    # Final snapshot includes every requested format.
    save_manifest(manifest)
    if progress:
        try:
            progress(None, len(FORMATS), len(FORMATS))
        except Exception:
            current_app.logger.warning('Metadata progress update unavailable')
    return outputs, manifest


def suspend_previous_artifacts(hdpc_path, record_id):
    """Old outputs cannot remain pending while their replacement is unverified."""
    from services.hdpc_schema_service import connect_hdpc
    with connect_hdpc(hdpc_path) as conn:
        conn.execute("""UPDATE record_files_map SET upload_status = CASE
                        WHEN upload_status IN ('uploaded', 'validation_pending_uploaded') THEN 'validation_pending_uploaded'
                        ELSE 'validation_pending' END
                        WHERE record_id = ? AND upload_status NOT IN ('disabled', 'removal_pending') AND file_id IN
                        (SELECT file_id FROM source_files WHERE pipeline_source = 'lod_generation')""", (int(record_id),))
