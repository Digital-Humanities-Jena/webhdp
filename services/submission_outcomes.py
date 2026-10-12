"""Plain-language record outcomes shared by live and historical run views."""
from pathlib import Path
import logging
import sqlite3


def _step_outcome(step, saved, detail, result, *, has_effective_snapshot):
    state = str(saved.get('status') or '').strip().lower()
    if state.startswith('skipped'):
        return 'skipped'
    if state in {'failed', 'error'} or saved.get('success') is False:
        return 'failed'
    if saved.get('success') is True or state in {'completed', 'success', 'generated'}:
        return 'completed'
    if step.get('enabled') is False:
        return 'skipped'
    if not has_effective_snapshot:
        component = step.get('component_ref') or step['id']
        aggregate_key = {'fast_renderer': 'render', 'any_to_usdz': 'usdz'}.get(component)
        aggregate = detail.get(aggregate_key) if aggregate_key else None
        aggregate = aggregate if isinstance(aggregate, dict) else {}
        aggregate_state = str(aggregate.get('status') or '').lower()
        if not aggregate.get('error') and (
            aggregate_state.startswith('skipped_disabled')
            or (aggregate_state.startswith('skipped') and result.get('success') is True and not detail.get('error'))
        ):
            return 'skipped'
    return 'not_started'


def summarize_outcomes(result, session, *, run_id=None, config=None, recoverable=False):
    from services.dataset_integrity_service import read_session_records
    current = {}
    if session and session.hdpc_path and (result or {}).get('details'):
        try:
            current = {int(record['local_record_id']): record for record in read_session_records(session)}
        except (OSError, sqlite3.Error, ValueError):
            logging.getLogger(__name__).warning('Current record state is unavailable for session %s.', session.id)
    effective_steps = (result or {}).get('effective_steps')
    has_effective_snapshot = isinstance(effective_steps, list)
    configured = effective_steps if has_effective_snapshot else (config or {}).get('steps', [])
    records = []
    for detail in (result or {}).get('details', []):
        if not session or not isinstance(detail, dict) or not detail.get('record_id'):
            continue
        rid = int(detail['record_id'])
        local = current.get(rid, {})
        saved_steps = detail.get('step_results') or {}
        definitions = [step for step in configured if isinstance(step, dict) and step.get('id')]
        configured_ids = {step['id'] for step in definitions}
        definitions += [{'id': key, 'name': key.replace('_', ' ').capitalize()} for key in saved_steps if key not in configured_ids]
        steps = []
        for step in definitions:
            saved = saved_steps.get(step['id'], {})
            status = _step_outcome(step, saved, detail, result or {}, has_effective_snapshot=has_effective_snapshot)
            steps.append({'id': step['id'], 'name': step.get('name') or step['id'],
                          'status': status, 'issue': saved.get('error'), 'reused': bool(saved.get('reused'))})
        attention = bool(detail.get('error')) or any(step['status'] in {'failed', 'not_started'} for step in steps)
        publication = local.get('record_status') or 'unknown'
        record_route = f'/sessions/{session.id}/records/{rid}'
        uncertain = 'REMOTE_OUTCOME_UNCERTAIN' in str(local.get('last_api_error') or '')
        if uncertain:
            action = {'label': 'Verify Zenodo state', 'route': record_route}
        elif attention and recoverable:
            action = {'label': 'Review failed work', 'route': f'/workflow/submit?sessionId={session.id}&recoverRunId={run_id}'}
        elif publication == 'published':
            action = {'label': 'View published record', 'route': record_route}
        elif publication == 'draft':
            pending = int(local.get('record_file_count') or 0) > int(local.get('uploaded_file_count') or 0)
            action = {'label': 'Review pending uploads' if pending else 'Review before publishing', 'route': record_route}
        else:
            action = {'label': 'Review outputs and metadata' if not attention else 'Review record issues', 'route': record_route}
        records.append({'record_id': rid, 'filename': Path(detail.get('file_path') or '').name or f'Record {rid}',
                        'file_path': detail.get('file_path'), 'title': local.get('record_title'),
                        'status': 'needs_attention' if attention else 'completed', 'publication_status': publication,
                        'steps': steps, 'issue': detail.get('error'), 'warnings': detail.get('warnings') or [],
                        'next_action': action, 'record_route': record_route})
    return {'records': records, 'summary': {'total': len(records),
            'completed': sum(record['status'] == 'completed' for record in records),
            'needs_attention': sum(record['status'] == 'needs_attention' for record in records),
            'drafts': sum(record['publication_status'] == 'draft' for record in records),
            'published': sum(record['publication_status'] == 'published' for record in records)},
            'can_recover': recoverable,
            'recovery_route': f'/workflow/submit?sessionId={session.id}&recoverRunId={run_id}' if recoverable else None}
