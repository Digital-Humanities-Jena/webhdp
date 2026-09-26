"""Independently validate and atomically promote metadata formats.

The manifest is private recovery state, never a record attachment. Retrying this
operation does not create a remote draft or execute a renderer or upload.
"""
import json
import os
from flask import current_app
from services.lod_reliability import FORMATS, assert_public_document, atomic_write, digest, pinned_templates

FILENAMES = dict(edm='edm.xml', iiif='iiif.json', mets='mets.xml', cidoc_crm='cidoc-crm.xml', jsonld='metadata.jsonld')


def generate_artifacts(output_dir, specification, register, progress=None):
    manifest_path = os.path.join(output_dir, 'lod-generation.json')
    validation_policy = {key: current_app.config.get(key) for key in ('LOCAL_EDM_VALIDATOR_REQUIRED', 'ENABLE_LOCAL_EDM_VALIDATION', 'ENABLE_METIS_VALIDATION', 'LOCAL_EDM_VALIDATOR_URL', 'METIS_SANDBOX_URL', 'ENABLE_XSD_VALIDATION')}
    fingerprint = digest(json.dumps({'request': specification, 'validation_policy': validation_policy}, sort_keys=True, default=str))
    try:
        with open(manifest_path, encoding='utf-8') as stream:
            previous = json.load(stream)
    except (OSError, ValueError):
        previous = {}
    manifest = {'version': 1, 'fingerprint': fingerprint, 'request': specification, 'formats': {}}
    atomic_write(manifest_path, json.dumps(manifest, indent=2, default=str))
    outputs = {}
    options = specification['options']
    with pinned_templates(specification.get('templates')):
        for index, standard in enumerate(FORMATS):
            if progress:
                progress(standard, index, len(FORMATS))
            status = {'status': 'pending', 'success': False}
            manifest['formats'][standard] = status
            if not options.get(f'generate_{standard}', True):
                status.update(status='skipped_disabled', success=True)
            else:
                path = os.path.join(output_dir, FILENAMES[standard])
                try:
                    old = (previous.get('formats') or {}).get(standard) or {}
                    if previous.get('fingerprint') == fingerprint and old.get('success') and (old.get('validation') or {}).get('valid') is True and old.get('sha256') and old.get('sha256') == old['validation'].get('sha256') and os.path.isfile(path):
                        with open(path, 'rb') as stream:
                            unchanged = digest(stream.read()) == old['sha256']
                        if unchanged:
                            register(path, old['validation'])
                            status.update(old, reused=True)
                            outputs[standard] = path
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
    # Also persist cached entries whose loop iteration continued early.
    atomic_write(manifest_path, json.dumps(manifest, indent=2, default=str))
    if progress:
        progress(None, len(FORMATS), len(FORMATS))
    return outputs, manifest


def suspend_previous_artifacts(hdpc_path, record_id):
    """Old outputs cannot remain pending while their replacement is unverified."""
    from services.hdpc_schema_service import connect_hdpc
    with connect_hdpc(hdpc_path) as conn:
        conn.execute("""UPDATE record_files_map SET upload_status = 'validation_pending'
                        WHERE record_id = ? AND file_id IN
                        (SELECT file_id FROM source_files WHERE pipeline_source = 'lod_generation')""", (int(record_id),))
