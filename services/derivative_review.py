"""Record-scoped geometric detail comparisons before publication."""
import json
from pathlib import Path

from database.database import db
from database.models import PipelineRun, PipelineStep, StepRun
from exceptions import ResourceNotFoundError
from services.pipeline_checkpoints import checked_file, journal
from services.registry_lock import OperationConflict


def _path(session, value):
    path = Path(value or '').resolve(strict=True)
    if not path.is_relative_to(Path(session.session_dir).resolve()) or not path.is_file():
        raise ValueError('The derivative is unavailable inside this session.')
    return path


def detail_sets(session, record_id, *, step_run_id=None):
    rows = StepRun.query.join(PipelineRun).join(PipelineStep, StepRun.pipeline_step_id == PipelineStep.id).filter(
        PipelineRun.session_id == session.id, StepRun.record_id == record_id,
        PipelineStep.component_key == 'geometric_lod_generator', StepRun.status == 'completed',
    ).order_by(StepRun.started_at.desc()).limit(10).all()
    sets = []
    for row in rows:
        if step_run_id is not None and row.id != step_run_id:
            continue
        result = json.loads(row.result_json or '{}')
        outputs = result.get('outputs') or {}
        try:
            report_path = _path(session, outputs.get('analysis_report'))
            if report_path.stat().st_size > 4 * 1024 * 1024:
                raise ValueError('The detail report exceeds the review size limit.')
            step = db.session.get(PipelineStep, row.pipeline_step_id)
            saved = journal(row.pipeline_run).get(str(record_id), {}).get('steps', {}).get(step.step_key, {})
            expected = saved.get('files', {}).get(str(report_path))
            if not expected or checked_file(report_path, session.session_dir) != expected:
                raise ValueError('The detail report changed after processing. Generate it again before reviewing outputs.')
            report = json.loads(report_path.read_text(encoding='utf-8'))
            if report.get('component') != 'geometric_lod_generator' or set(report.get('levels', {})) != {'high', 'medium', 'low'}:
                raise ValueError('The saved report does not describe a complete geometric detail ladder.')
            candidates = [path for path, info in saved.get('inputs', {}).items() if info.get('sha256') == report.get('source_sha256')]
            if len(candidates) != 1:
                raise ValueError('The report source could not be identified. Generate detail levels again.')
            source = _path(session, candidates[0])
            models = [{'level': 'source', 'label': 'Source supplied to this step', 'filename': source.name,
                       'triangles': report['source_triangles'], 'bytes': report['source_bytes'], 'sha256': report['source_sha256']}]
            for level in ('high', 'medium', 'low'):
                path = _path(session, outputs.get('lod_' + level))
                info = report['levels'][level]
                models.append({'level': level, 'label': level.capitalize(), 'filename': path.name,
                               'triangles': info['triangles'], 'bytes': info['bytes'], 'sha256': info['sha256'],
                               'reduction_percent': info['reduction_percent'],
                               'size_change_percent': 100 * (info['bytes'] / report['source_bytes'] - 1),
                               'retained_meshes': sum(check.get('status') == 'retained' for check in info.get('geometry_checks', [])),
                               'repaired_tangents': info.get('repaired_tangents', 0),
                               'geometry_checks': info.get('geometry_checks', [])})
            completed_at = row.completed_at or row.started_at
            sets.append({'step_run_id': row.id, 'run_id': row.pipeline_run.public_id, 'created_at': completed_at.isoformat() + 'Z' if completed_at else None,
                         'models': models, 'quality_note': report.get('quality_note'), 'blender_version': report.get('blender_version')})
        except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
            sets.append({'step_run_id': row.id, 'run_id': row.pipeline_run.public_id, 'error': str(exc), 'models': []})
    return sets


def verified_model(session, record_id, step_run_id, level):
    sets = detail_sets(session, record_id, step_run_id=step_run_id)
    if not sets:
        raise ResourceNotFoundError('This record has no matching detail set.')
    detail = sets[0]
    if detail.get('error'):
        raise OperationConflict(detail['error'])
    model = next((model for model in detail['models'] if model['level'] == level), None)
    if not model:
        raise ResourceNotFoundError('Detail level not found')
    row = db.session.get(StepRun, step_run_id)
    step = db.session.get(PipelineStep, row.pipeline_step_id)
    saved = journal(row.pipeline_run)[str(record_id)]['steps'][step.step_key]
    path = next(path for path, info in saved['inputs'].items() if info['sha256'] == model['sha256']) if level == 'source' else json.loads(row.result_json)['outputs']['lod_' + level]
    try:
        actual = checked_file(path, session.session_dir)
    except (OSError, ValueError) as exc:
        raise OperationConflict('The model is unavailable. Generate detail levels again.') from exc
    if actual['sha256'] != model['sha256'] or actual['bytes'] != model['bytes']:
        raise OperationConflict('The model changed after processing. Generate detail levels again before review.')
    return actual['path'], actual['sha256']
