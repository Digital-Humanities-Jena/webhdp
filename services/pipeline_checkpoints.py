"""Durable, content-verified continuation of interrupted record processing."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from database.database import db
from database.models import PipelineRun, PipelineRunStatus, PipelineVersion, Session
from exceptions import ResourceNotFoundError, ValidationError
from services.registry_lock import OperationConflict


def snapshot(context):
    return copy.deepcopy({key: context[key] for key in (
        'record_id', 'file_path', 'record_status', 'file_zenodo_metadata',
        'generated_files', 'current_zenodo_draft_record_id', 'draft_result',
    ) if key in context})


def journal(run):
    return json.loads(run.request_json or '{}').get('_checkpoints', {}).get('records', {})


def persist_registration(run, record_id, file_path, metadata, *, source_file_path=None):
    """Retain registered IDs even if the worker stops before component processing."""
    persist(run, [{'record_id': int(record_id), 'file_path': file_path,
                   'file_zenodo_metadata': metadata, 'generated_files': [],
                   '_registration_source': source_file_path or file_path,
                   'record_status': {'record_id': int(record_id), 'file_path': file_path,
                                     'step_results': {}, 'warnings': []}}])


def persist(run, contexts, step_id=None):
    """Commit after registration and each step, before another external call."""
    from datetime import datetime
    request = json.loads(run.request_json or '{}')
    records = request.setdefault('_checkpoints', {'format': 1, 'records': {}})['records']
    for context in contexts:
        record = records.setdefault(str(context['record_id']), {'steps': {}})
        record['state'] = snapshot(context)
        if context.get('_registration_source'):
            source = str(Path(context['_registration_source']).resolve())
            if source not in record.setdefault('sources', []):
                record['sources'].append(source)
        if step_id:
            state = context['record_status'].get('step_results', {}).get(step_id)
            if state:
                files = {}
                try:
                    for path in output_paths(context['step_outputs'].get(step_id, {})):
                        info = checked_file(path, context['_session_root'])
                        files[info['path']] = info
                    for path in set(context['generated_files']) - set(context.get('_generated_before_step', [])):
                        info = checked_file(path, context['_session_root'])
                        files[info['path']] = info
                    verifiable = True
                except (OSError, ValueError):
                    verifiable = False
                record['steps'][step_id] = {
                    'signature': context.get('_step_signature'), 'files': files,
                    'outputs': copy.deepcopy(context['step_outputs'].get(step_id, {})),
                    'inputs': copy.deepcopy(context.get('_step_inputs', {})),
                    'state': snapshot(context), 'success': bool(state.get('success')),
                    'generated': sorted(set(context['generated_files']) - set(context.get('_generated_before_step', []))),
                    'verifiable': verifiable, 'completed_at': datetime.utcnow().isoformat() + 'Z',
                }
    run.request_json = json.dumps(request)
    result = json.loads(run.result_json or '{}')
    result['details'] = [record['state']['record_status'] for record in records.values()]
    result['summary'] = {
        'total_records': len(records),
        'processed_count': sum(bool(record.get('steps')) for record in records.values()),
        'failed_count': sum(bool(record['state']['record_status'].get('error')) for record in records.values()),
    }
    run.result_json = json.dumps(result)
    db.session.commit()


def checked_file(path, root):
    from services.submission_readiness import file_fingerprint
    resolved = Path(path).resolve(strict=True)
    if not resolved.is_relative_to(Path(root).resolve()) or not resolved.is_file():
        raise ValueError('An artifact is outside its session or unavailable.')
    return file_fingerprint(resolved)


def output_paths(value):
    if isinstance(value, str) and Path(value).is_absolute():
        path = Path(value)
        if path.is_dir():
            yield from (str(item) for item in sorted(path.rglob('*')) if item.is_file())
        else:
            yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from output_paths(item)
    elif isinstance(value, list):
        for item in value:
            yield from output_paths(item)


def signature(native, step, context, execution):
    """Bind reuse to the pinned component, profile, parameters and actual inputs."""
    from services.submission_readiness import fingerprint
    context['_step_inputs'] = {}
    try:
        component = native._step_component_version(step)
        manifest = json.loads(component.manifest_json)
        profile = native._get_profile_row(component, step.get('execution_profile_ref'))
        trigger = native._resolve_step_trigger(step, context)
        inputs, parameters = native._resolve_step_bindings(step, context, execution)
        inputs = native._apply_default_input_bindings(manifest.get('inputs', []), inputs, context, execution)
        parameters = {**step.get('parameters', {}), **parameters, **trigger.get('parameter_overrides', {})}
        files = {}
        fields = manifest.get('inputs', []) + [field for group in manifest.get('parameter_groups', []) for field in group.get('parameters', [])]
        for field in fields:
            if field.get('type') in {'file_path', 'file_list', 'dir_path'}:
                value = (inputs if field in manifest.get('inputs', []) else parameters).get(field['name'])
                for path in output_paths(value):
                    info = checked_file(path, context['_session_root'])
                    files[info['path']] = info
        details = {'step': step, 'manifest': component.manifest_hash,
                   'profile': native._profile_payload(profile), 'inputs': inputs,
                   'parameters': parameters, 'trigger': trigger, 'files': files}
        context['_step_inputs'] = files
        key = step.get('component_ref') or step['id']
        if key in {'zenodo_draft', 'zenodo_upload', 'lod_generation'}:
            details['metadata'] = context['file_zenodo_metadata']
            details['lod'] = {key: execution.get(key) for key in ('lod_mapping_config', 'lod_templates', 'resolved_lod_msf_path')}
            details['environment'] = execution.get('is_sandbox')
        return fingerprint(details)
    except (OSError, ValueError, KeyError, ValidationError):
        return None  # An unverified input must be executed and validated again.


def reuse(native, previous, step, context, execution):
    entry = (previous.get(str(context['record_id']), {}).get('steps') or {}).get(step['id'])
    dependencies = {binding.get('source_step') for binding in step.get('input_bindings', []) + step.get('parameter_bindings', [])}
    dependencies.update(condition.get('source_step') for rule in (step.get('triggers') or {}).get('rules', []) for condition in rule.get('conditions', []))
    key = step.get('component_ref') or step['id']
    # Arbitrary batch components may depend on the complete group. Renderer outputs
    # are record-local; other batch work is rerun with the original membership.
    if step.get('scope') == 'batch' and key != 'fast_renderer':
        return False
    if not entry or not entry.get('success') or not entry.get('verifiable') or not entry.get('signature'):
        return False
    if dependencies.intersection(context.get('_rerun_steps', set())) or entry['signature'] != context.get('_step_signature'):
        return False
    try:
        for path, expected in entry['files'].items():
            if checked_file(path, context['_session_root']) != expected:
                return False
    except (OSError, ValueError):
        return False
    # Remote mutations use the existing record-aware handlers and reconciliation
    # guards. They can reuse a saved draft/upload without replaying its creation.
    if key in {'zenodo_draft', 'zenodo_upload', 'lod_generation'}:
        return False
    state = entry['state']
    context['step_outputs'][step['id']] = copy.deepcopy(entry['outputs'])
    context['generated_files'] = list(dict.fromkeys(context['generated_files'] + entry.get('generated', [])))
    for name in ('render', 'usdz', 'edm', 'iiif', 'mets'):
        if key == {'render': 'fast_renderer', 'usdz': 'any_to_usdz'}.get(name, name):
            context['record_status'][name] = copy.deepcopy(state['record_status'][name])
    context['record_status']['step_results'][step['id']] = {
        **state['record_status']['step_results'][step['id']], 'reused': True,
    }
    native._apply_output_actions(step, context, {'outputs': entry['outputs']})
    return True


def recovery_plan(native, run_id, user_id):
    from services.dataset_integrity_service import read_session_records
    from services.hdpc_schema_service import connect_hdpc, table_exists
    run = PipelineRun.query.filter_by(public_id=run_id).first()
    if not run:
        raise ResourceNotFoundError('Pipeline run not found')
    session = db.session.get(Session, run.session_id)
    native._assert_user_can_access_session(session, user_id, edit=True)
    from services.pipeline_run_recovery import reconcile_run
    reconcile_run(run)
    records = journal(run)
    if run.status != PipelineRunStatus.FAILED or not records:
        raise ValidationError('This run has no saved failed work to continue. Review its results before starting another run.')
    version = db.session.get(PipelineVersion, run.pipeline_version_id)
    config = json.loads(version.config_json)
    steps = [step for step in config.get('steps', []) if step.get('enabled', True)]
    whole_batch = any(step.get('scope') == 'batch' and (step.get('component_ref') or step['id']) != 'fast_renderer' for step in steps)
    request = json.loads(run.request_json or '{}')
    requested_sources = request.get('local_file_paths') or [item['source_file_path'] for item in request.get('execution_items', []) if item.get('action') != 'skip']
    registered_sources = {str(Path(path).resolve()) for record in records.values()
                          for path in [record['state']['file_path'], *record.get('sources', [])]}
    unregistered = [path for path in requested_sources if str(Path(path).resolve()) not in registered_sources]
    unregistered_ids = [rid for rid in request.get('record_ids', []) if str(rid) not in records]
    current = {str(record['local_record_id']): record for record in read_session_records(session)}
    uncertain = set()
    from database.models import HpcAllocation
    interrupted_hpc = bool(json.loads(run.result_json or '{}').get('interrupted') and HpcAllocation.query.filter(
        HpcAllocation.session_id == session.id, HpcAllocation.remote_session_id.isnot(None),
        HpcAllocation.status.in_(['queued', 'allocated', 'active', 'ready', 'running']),
    ).first())
    with connect_hdpc(session.hdpc_path, readonly=True) as connection:
        if table_exists(connection.cursor(), 'zenodo_remote_operations'):
            uncertain = {str(row[0]) for row in connection.execute("SELECT record_id FROM zenodo_remote_operations WHERE state = 'uncertain'")}
    entries = []
    for rid, record in records.items():
        done = record.get('steps', {})
        needs_retry = bool(record['state']['record_status'].get('error')) or any(not done.get(step['id'], {}).get('success') for step in steps)
        if not needs_retry and not whole_batch:
            continue
        reason = None
        if rid not in current:
            reason = 'The local record is unavailable. Review the session files.'
        elif current[rid].get('record_status') == 'published':
            reason = 'The record is published. Create a new version before changing it.'
        elif rid in uncertain:
            reason = 'Verify the uncertain Zenodo operation from this record before retrying.'
        elif interrupted_hpc:
            reason = 'Review and release the interrupted HPC allocation before retrying this run.'
        elif whole_batch and (unregistered or unregistered_ids):
            reason = 'Registration stopped before the original batch was complete. Review the remaining sources or records and prepare the complete record group.'
        entries.append({'record_id': int(rid), 'file_path': record['state']['file_path'],
                        'eligible': reason is None, 'reason': reason,
                        'route': f'/sessions/{session.id}/records/{rid}',
                        'completed_steps': sum(bool(step.get('success')) for step in done.values())})
    return {'run_id': run.public_id, 'pipeline_identifier': config['identifier'], 'pipeline_version': version.version,
            'session_id': session.id, 'records': entries, 'record_ids': [entry['record_id'] for entry in entries if entry['eligible']],
            'is_sandbox': request.get('is_sandbox', True), 'whole_batch': whole_batch,
            'unregistered_sources': unregistered, 'unregistered_record_ids': unregistered_ids}


def validate_recovery(native, payload, user_id):
    plan = recovery_plan(native, payload['resume_from_run_id'], user_id)
    if payload.get('local_file_paths') or payload.get('execution_items') or payload.get('session_id') != plan['session_id']:
        raise ValidationError('Continuation must use the saved run and its existing local records.')
    selected = payload.get('record_ids') or []
    if not selected or not set(selected).issubset(plan['record_ids']):
        raise OperationConflict('Some records cannot be continued. Refresh the recovery plan and resolve its blockers.')
    if plan['whole_batch'] and set(selected) != set(plan['record_ids']):
        raise ValidationError('This batch component requires its complete original record group.')
    if plan['whole_batch'] and any(not record['eligible'] for record in plan['records']):
        raise OperationConflict('Resolve every blocked record before continuing this batch component.')
    if bool(payload.get('is_sandbox', True)) != bool(plan['is_sandbox']):
        raise ValidationError('Continuation must keep the original Zenodo destination.')
    return PipelineRun.query.filter_by(public_id=plan['run_id']).one()
