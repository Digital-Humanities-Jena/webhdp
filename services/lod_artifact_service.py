"""Independently validate and atomically promote metadata formats.

The manifest is private recovery state, never a record attachment. Retrying this
operation does not create a remote draft or execute a renderer or upload.
"""
import json
import os
from pathlib import Path
from flask import current_app, has_app_context
from services.lod_reliability import FORMATS, assert_public_document, atomic_write, digest, pinned_templates

FILENAMES = dict(edm='edm.xml', iiif='iiif.json', mets='mets.xml', cidoc_crm='cidoc-crm.xml', jsonld='metadata.jsonld')


def validation_policy():
    keys = ('LOCAL_EDM_VALIDATOR_REQUIRED', 'ENABLE_LOCAL_EDM_VALIDATION', 'ENABLE_METIS_VALIDATION',
            'LOCAL_EDM_VALIDATOR_URL', 'METIS_SANDBOX_URL', 'ENABLE_XSD_VALIDATION')
    return {key: current_app.config.get(key) for key in keys} if has_app_context() else {}


def policy_error(manifest, standard, status):
    policy = validation_policy()
    if not policy:
        return None
    captured = manifest.get('validation_policy')
    legacy_changed = captured is None and manifest.get('fingerprint') and manifest['fingerprint'] != digest(json.dumps({'request': manifest.get('request'), 'validation_policy': policy}, sort_keys=True, default=str))
    if (captured is not None and captured != policy) or legacy_changed:
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
    formats = manifest.setdefault('formats', {})
    for standard in FORMATS:
        if standard not in formats:
            enabled = (manifest.get('request', {}).get('options') or {}).get(f'generate_{standard}', True)
            formats[standard] = {'status': 'pending' if enabled else 'skipped_disabled', 'success': not enabled}
    return manifest


def record_lod_readiness(hdpc_path, record_id):
    """Current artifact readiness, independent of historical pipeline results."""
    from services.hdpc_schema_service import connect_hdpc
    root = Path(hdpc_path).resolve().parent / 'outputs' / f'record-{int(record_id)}'
    paths = list(root.glob('*/lod-generation.json'))
    blocked_formats = []
    revalidation_required = False
    if paths:
        try:
            if len(paths) != 1 or not paths[0].resolve().is_relative_to(root):
                raise ValueError('Ambiguous metadata report')
            manifest = complete_format_states(json.loads(paths[0].read_text(encoding='utf-8')))
            for standard, status in manifest['formats'].items():
                if status.get('status') == 'skipped_disabled':
                    continue
                intact = False
                if standard in FILENAMES and status.get('success') and (status.get('validation') or {}).get('valid') is True:
                    artifact = paths[0].parent / FILENAMES[standard]
                    intact = artifact.resolve().is_relative_to(root) and artifact.is_file() and digest(artifact.read_bytes()) == status.get('sha256')
                policy_issue = policy_error(manifest, standard, status)
                revalidation_required = revalidation_required or bool(policy_issue)
                if policy_issue or (not intact and manifest.get('request', {}).get('lod_policy', 'required') == 'required'):
                    blocked_formats.append(standard)
        except (OSError, ValueError, TypeError, AttributeError):
            blocked_formats.append('metadata report')
    with connect_hdpc(hdpc_path) as conn:
        rows = conn.execute('SELECT upload_status FROM record_files_map WHERE record_id = ?', (int(record_id),)).fetchall()
    blocked_files = sum(str(row[0]).startswith('validation_pending') for row in rows)
    pending_files = sum(row[0] not in ('uploaded', 'disabled') and not str(row[0]).startswith('validation_pending') for row in rows)
    ready = not blocked_formats and not blocked_files
    return {'available': bool(paths), 'ready': ready, 'blocked_formats': blocked_formats,
            'revalidation_required': revalidation_required, 'blocked_file_count': blocked_files, 'pending_upload_count': pending_files,
            'state': 'blocked' if not ready else 'upload_required' if pending_files else 'uploaded'}


def generate_artifacts(output_dir, specification, register, progress=None, *, hdpc_path=None, record_id=None):
    manifest_path = os.path.join(output_dir, 'lod-generation.json')
    current_policy = validation_policy()
    if hdpc_path is not None and record_id is not None:
        reconcile_disabled_formats(hdpc_path, record_id, specification['options'])
    fingerprint = digest(json.dumps({'request': specification, 'validation_policy': current_policy}, sort_keys=True, default=str))
    try:
        with open(manifest_path, encoding='utf-8') as stream:
            previous = json.load(stream)
    except (OSError, ValueError):
        previous = {}
    previous_formats = dict(previous.get('previous_formats') or {}) if previous.get('fingerprint') == fingerprint else {}
    previous_formats.update({key: value for key, value in (previous.get('formats') or {}).items() if value.get('success')})
    manifest = complete_format_states({'version': 1, 'fingerprint': fingerprint, 'request': specification, 'validation_policy': current_policy, 'formats': {},
                                      'previous_formats': previous_formats if previous.get('fingerprint') == fingerprint else {}})
    atomic_write(manifest_path, json.dumps(manifest, indent=2, default=str))
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
                    if previous.get('fingerprint') == fingerprint and old.get('success') and (old.get('validation') or {}).get('valid') is True and old.get('sha256') and old.get('sha256') == old['validation'].get('sha256') and os.path.isfile(path):
                        with open(path, 'rb') as stream:
                            unchanged = digest(stream.read()) == old['sha256']
                        if unchanged:
                            register(path, old['validation'])
                            status.update(old, reused=True)
                            outputs[standard] = path
                            atomic_write(manifest_path, json.dumps(manifest, indent=2, default=str))
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
                    status.update(status='generated', success=True, path=path, sha256=sha256, validation=validation, minimum_viable_applied=bool(generation.get('minimum_viable_applied')))
                    outputs[standard] = path
                except Exception as exc:
                    status.update(status='failed', error=str(exc))
            atomic_write(manifest_path, json.dumps(manifest, indent=2, default=str))
    # Final snapshot includes every requested format.
    atomic_write(manifest_path, json.dumps(manifest, indent=2, default=str))
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
