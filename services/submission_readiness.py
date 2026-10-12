"""Local, read-only checks before submission has any external effects."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from flask import current_app
from itsdangerous import BadSignature, URLSafeTimedSerializer

from database.database import db
from database.models import PipelineDefinition, PipelineRun, PipelineRunStatus, PlaygroundRun
from exceptions import FileProcessingError, ValidationError
from services.registry_lock import OperationConflict
from services.lod_reliability import capture_session_lod
from services.dataset_integrity_service import (
    analyze_session_record_resolution, read_session_records, ensure_fresh_record_creation_allowed, ensure_record_operation_allowed, RecordInventorySnapshot,
)
from services.submission_pipeline_service import (
    prepare_submission_sources, record_submission_metadata, _validate_execution_items_against_resolution_state,
    _resolve_version_target_record,
)


ROUTES = {'files': '/workflow/files', 'metadata': '/workflow/metadata',
          'mapping': '/workflow/edm-selection', 'pipeline': '/workflow/pipeline', 'review': '/workflow/submit'}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(',', ':')).encode()).hexdigest()


def file_fingerprint(path):
    path = Path(path)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('A source changed while it was being checked. Check readiness again.')
    if after.st_size == 0:
        raise ValueError('The source is empty. Upload a complete file.')
    return {'path': str(path.resolve()), 'bytes': after.st_size, 'sha256': digest.hexdigest()}


class ReadinessFieldError(ValueError):
    def __init__(self, message, category, field):
        super().__init__(message)
        self.category, self.field = category, field


class SubmissionReadiness:
    def __init__(self, native):
        self.native = native

    @staticmethod
    def signer():
        return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='submission-readiness-v1')

    def check(self, identifier, session, payload, user_id, *, version=None, lod_snapshot=None, own_run_id=None):
        for event in self.events(identifier, session, payload, user_id, version=version, lod_snapshot=lod_snapshot, own_run_id=own_run_id):
            if event['type'] == 'result':
                return event['report']

    def events(self, identifier, session, payload, user_id, *, version=None, lod_snapshot=None, own_run_id=None):
        self.native._assert_user_can_access_session(session, user_id, edit=True)
        blockers, deferred, checked_files, checked_records, effective_metadata = [], [], {}, [], []
        source_labels = {}

        def issue(message, area, *, source=None, step=None):
            entry = {'message': message, 'route': ROUTES[area]}
            if source:
                entry['source'] = source_labels.get(str(source), Path(source).name)
            if step:
                entry['step'] = step.get('name') or step['id']
            if entry not in blockers:
                blockers.append(entry)

        for model in (PipelineRun, PlaygroundRun):
            active = model.query.filter(model.session_id == session.id, model.status.in_([PipelineRunStatus.PENDING, PipelineRunStatus.RUNNING])).all()
            for run in active:
                if run.public_id == own_run_id:
                    continue
                issue('This session already has an active run. Open its monitor before starting another.', 'review')
                if model is PipelineRun:
                    blockers[-1]['route'] = f'/workflow/submit?sessionId={session.id}&runId={run.public_id}'
        definition = PipelineDefinition.query.filter_by(identifier=self.native.resolve_pipeline_identifier(identifier), is_active=True).first()
        if payload.get('resume_from_run_id'):
            from database.models import PipelineVersion
            from services.pipeline_checkpoints import validate_recovery
            previous = validate_recovery(self.native, payload, user_id)
            if not definition or previous.pipeline_definition_id != definition.id:
                raise ValidationError('Continuation must keep the original pipeline.')
            version = db.session.get(PipelineVersion, previous.pipeline_version_id)
        version = version or (self.native._get_active_pipeline_version_row(definition) if definition else None)
        if not version:
            issue('The selected pipeline is unavailable. Choose an available pipeline.', 'pipeline')
            yield {'type': 'result', 'report': self._report(blockers, deferred, None, 0, 0, None)}
            return
        config = json.loads(version.config_json)
        if payload.get('expected_version') and payload['expected_version'] != version.version:
            issue('The pipeline version changed. Choose the pipeline again and review its steps.', 'pipeline')
        steps = [step for step in config.get('steps', []) if step.get('enabled', True)]
        if not steps:
            issue('The pipeline has no enabled steps. Choose another pipeline.', 'pipeline')

        paths = payload.get('local_file_paths') or []
        record_ids = payload.get('record_ids') or []
        items = payload.get('execution_items') or []
        if items and bool(payload.get('is_sandbox', True)) != (session.default_zenodo_environment != 'production'):
            issue("Batch plans must use this session's default Zenodo environment.", 'review')
        target_keys = [item['decision_key'] for item in items] if items else record_ids if record_ids else paths
        if not target_keys:
            issue('Select at least one source to process.', 'files')
        if len(target_keys) != len(set(target_keys)):
            issue('A source or record is selected more than once. Select each source once.', 'files')
        try:
            lod_snapshot = lod_snapshot or capture_session_lod(session.id, bootstrap_templates=False, allow_missing_templates=True)
            sources = prepare_submission_sources(session, paths, items, record_ids, lod_snapshot=lod_snapshot)
            source_labels.update(sources['absolute_to_relative_path'])
        except Exception as exc:
            issue('Could not read the saved metadata, spreadsheet, templates, or project: ' + str(exc), 'mapping')
            yield {'type': 'result', 'report': self._report(blockers, deferred, version.version, len(target_keys), 0, None)}
            return

        inventory = RecordInventorySnapshot()
        decisions = {}
        if items:
            analysis = analyze_session_record_resolution(session, inventory=inventory)
            # Validate every decision, including skip decisions, against the same execution rule.
            for item in items:
                try:
                    decisions.update(_validate_execution_items_against_resolution_state(session, [item], analysis=analysis))
                except Exception as exc:
                    issue(str(exc), 'files', source=item['source_file_path'])
        records = {int(row['local_record_id']): row for row in read_session_records(session)} if record_ids and not items else {}
        selected = items or ([{'record_id': rid, 'source_file_path': records.get(rid, {}).get('source_file_path')} for rid in record_ids] if record_ids else [{'source_file_path': path} for path in paths])
        skipped = 0
        uses_zenodo = any((step.get('component_ref') or step['id']) in {'zenodo_draft', 'zenodo_upload'} for step in steps)
        for index, selection in enumerate(selected, 1):
            yield {'type': 'progress', 'checked': index - 1, 'total': len(selected)}
            if selection.get('action') == 'skip':
                skipped += 1
                continue
            raw_path = selection.get('source_file_path')
            try:
                if not raw_path:
                    raise ValueError('The selected record has no source. Select a current source.')
                path = self.native._resolve_constructor_preflight_file_path(session, raw_path)
                source = sources['resolve'](str(path))
                if not source:
                    raise ValueError('The selected source is absent from the project. Refresh the file selection.')
                effective = self.native._resolve_constructor_preflight_file_path(session, source['effective_file_path'])
                bundle = source['paths_to_associate']
                from services.hdpc_scan_service import _find_gltf_external_files, _find_mtl_files_for_obj, _find_texture_files_for_mtl
                dependencies, missing = [], []
                if effective.suffix.lower() == '.gltf':
                    dependencies, missing = _find_gltf_external_files(effective, Path(session.session_dir))
                elif effective.suffix.lower() == '.obj':
                    dependencies = _find_mtl_files_for_obj(effective, Path(session.session_dir))
                    for material in list(dependencies):
                        textures, absent = _find_texture_files_for_mtl(material, Path(session.session_dir))
                        dependencies.extend(textures)
                        missing.extend(absent)
                if missing:
                    raise ValueError('Referenced resources are missing. Restore the model dependencies and rescan the file selection.')
                if any(str(path) not in bundle for path in dependencies):
                    from services.submission_pipeline_service import _iter_file_nodes
                    archived = {node.get('absolute_path') for node in _iter_file_nodes(sources['inspect_data'].get('file_tree', [])) if node.get('type') == 'archived_file'}
                    if any(str(path) not in bundle and str(path) not in archived for path in dependencies):
                        raise ValueError('The model dependencies changed since scanning. Rescan the file selection before processing.')
                for member in list(dict.fromkeys([*bundle, *(str(path) for path in dependencies)])):
                    scoped = self.native._resolve_constructor_preflight_file_path(session, member)
                    if str(scoped) not in checked_files:
                        checked_files[str(scoped)] = file_fingerprint(scoped)
                rid = selection.get('record_id')
                if rid:
                    row = records[rid]
                    if row.get('record_status') == 'published':
                        raise ValueError('This record is published. Resolve it as a new version before processing.')
                    ensure_record_operation_allowed(session, local_record_id=rid, allow_allowed_versioning=True, inventory=inventory)
                    metadata = record_submission_metadata(row)
                    checked_records.append(row)
                else:
                    metadata = source['lod_base_metadata']
                    if selection.get('action') != 'force_create_fresh' and selection.get('action') != 'create_version':
                        ensure_fresh_record_creation_allowed(session, source_file_path=str(effective), is_sandbox=bool(payload.get('is_sandbox', True)), inventory=inventory)
                    if selection.get('action') == 'create_version':
                        target = db.session.get(type(session), selection.get('target_session_id'))
                        self.native._assert_user_can_access_session(target, user_id)
                        row = _resolve_version_target_record(target.id, selection['target_local_record_id'])
                        if row.get('record_status') != 'published' or not row.get('concept_rec_id'):
                            raise ValueError('The version target must be a published record with a version lineage.')
                        if str(row['concept_rec_id']) != str(selection.get('target_concept_rec_id') or ''):
                            raise ValueError('The version lineage changed. Review the saved record decision.')
                        checked_records.append(row)
            except Exception as exc:
                issue(str(exc), 'mapping' if isinstance(exc, FileProcessingError) else 'files', source=raw_path)
                continue

            effective_metadata.append({'source': str(effective), 'metadata': metadata})
            context = self.native._build_record_context_for_preflight(index, str(effective))
            context['file_zenodo_metadata'] = metadata
            context['record_id'] = rid
            execution = {'hdpc_path': session.hdpc_path}
            # Original bundle inputs can be resolved before a record is registered.
            available_outputs, pending_outputs = set(), set()
            checked_zenodo_metadata = False
            for step in steps:
                try:
                    component_version = self.native._step_component_version(step)
                    manifest = json.loads(component_version.manifest_json)
                    profile = self.native._get_profile_row(component_version, step.get('execution_profile_ref'))
                    conditions = [condition for rule in (step.get('triggers') or {}).get('rules', []) for condition in rule.get('conditions', [])]
                    unknown_trigger = any(condition.get('source_type') == 'classifier_output' and (condition.get('source_step'), condition.get('source_output')) not in available_outputs for condition in conditions)
                    if unknown_trigger:
                        deferred.append({'message': 'Conditional requirements will be checked when earlier step outputs are available.', 'step': step.get('name') or step['id']})
                        pending_outputs.update((step['id'], field['name']) for field in manifest.get('outputs', []))
                        continue
                    trigger = self.native._resolve_step_trigger(step, context)
                    if trigger['action'] != 'run':
                        continue
                    inputs, parameters = self.native._resolve_step_bindings(step, context, execution)
                    for binding in step.get('input_bindings', []):
                        if binding.get('type') == 'record_source_files' and not rid:
                            inputs[binding['target']] = bundle
                    unresolved = set()
                    for binding in step.get('input_bindings', []) + step.get('parameter_bindings', []):
                        if binding.get('type', '').startswith('artifact_') and (binding.get('source_step'), binding.get('source_output')) not in available_outputs:
                            if (binding.get('source_step'), binding.get('source_output')) not in pending_outputs:
                                raise ValueError('An input depends on a skipped or unavailable earlier step. Review the pipeline bindings.')
                            unresolved.add((binding['kind'], binding['target']))
                    if unresolved:
                        deferred.append({'message': 'Inputs and parameters supplied by earlier steps are checked when their outputs are available.', 'step': step.get('name') or step['id']})
                    inputs = self.native._apply_default_input_bindings(manifest.get('inputs', []), inputs, context, execution)
                    parameters = {**step.get('parameters', {}), **parameters, **trigger.get('parameter_overrides', {})}
                    input_fields = [dict(field) for field in manifest.get('inputs', [])]
                    widgets = ((manifest.get('ui') or {}).get('playground') or {}).get('fields') or {}
                    for field in input_fields:
                        if field['type'] == 'file_path':
                            field['accept_extensions'] = widgets.get(field['name'], {}).get('accept_extensions') or []
                    self._fields(input_fields, inputs, 'input', unresolved, session, checked_files)
                    fields = [field for group in manifest.get('parameter_groups', []) for field in group.get('parameters', [])]
                    self._fields(fields, parameters, 'parameter', unresolved, session, checked_files)
                    key = step.get('component_ref') or step['id']
                    if key in {'zenodo_draft', 'zenodo_upload'} and not checked_zenodo_metadata:
                        from routes.metadata_routes import validate_zenodo_metadata
                        candidate_metadata = source['zenodo_submission_metadata'] if not rid else metadata
                        try:
                            if not rid:
                                candidate_metadata = {**candidate_metadata, 'creators': source['supplied_creators']}
                            for message in validate_zenodo_metadata({'metadata': candidate_metadata}):
                                issue(message, 'metadata', source=effective)
                        except (TypeError, ValueError):
                            issue('The record metadata contains invalid field values. Review the saved metadata.', 'metadata', source=effective)
                        checked_zenodo_metadata = True
                    if key == 'lod_generation' and parameters.get('lod_policy', 'required') != 'disabled':
                        from jinja2 import Environment
                        for standard in ('edm', 'iiif', 'mets'):
                            if not parameters.get(f'generate_{standard}', True):
                                continue
                            template = lod_snapshot['templates'].get(standard)
                            try:
                                if not template:
                                    raise ValueError(f'Choose an existing {standard.upper()} template.')
                                Environment().parse(template['content'])
                            except Exception as exc:
                                issue(f'{standard.upper()} template: {exc}', 'mapping', source=effective, step=step)
                    if key == 'geometric_lod_generator':
                        from external_code.geometric_lod_generator.runner import validate_parameters
                        known_parameters = {key: value for key, value in parameters.items() if ('parameter', key) not in unresolved}
                        validate_parameters(known_parameters)
                    if ('input', 'input_file') not in unresolved and key in {'geometric_lod_generator', 'mesh_optimizer', 'georeferencer'}:
                        if key == 'geometric_lod_generator':
                            from external_code.geometric_lod_generator.runner import validate_request
                            validate_request({'inputs': inputs, 'parameters': known_parameters})
                        else:
                            from external_code.mesh_optimizer.runner import inspect_glb
                            inspect_glb(Path(inputs['input_file']))
                    if key == 'georeferencer' and ('input', 'reference_files') not in unresolved:
                        refs = {path for path in inputs.get('reference_files', []) if Path(path).suffix.lower() in {'.tif', '.tiff'}}
                        if len(refs) != 1:
                            raise ValueError('Each model bundle needs exactly one reference GeoTIFF (.tif or .tiff).')
                        deferred.append({'message': 'GeoTIFF coordinates, image quality and GPU alignment are checked in the compute runtime.', 'step': step.get('name') or step['id']})
                    if profile.adapter == 'hpc_link' or key in {'fast_renderer', 'any_to_usdz'}:
                        deferred.append({'message': 'Compute connectivity, allocation and component installation are unverified until runtime preparation.', 'step': step.get('name') or step['id']})
                    elif profile.adapter == 'container_cli':
                        deferred.append({'message': 'Container installation and runtime availability are checked when processing starts.', 'step': step.get('name') or step['id']})
                    if key == 'input_file_classification':
                        context['step_outputs'][step['id']] = {'classification_json': self.native._classify_input_file(str(effective))}
                        available_outputs.add((step['id'], 'classification_json'))
                    else:
                        pending_outputs.update((step['id'], field['name']) for field in manifest.get('outputs', []))
                except Exception as exc:
                    metadata_field = isinstance(exc, ReadinessFieldError) and any(
                        binding.get('kind') == exc.category and binding.get('target') == exc.field
                        and binding.get('type') == 'record_metadata_field'
                        for binding in step.get('input_bindings', []) + step.get('parameter_bindings', []))
                    issue(str(exc), 'metadata' if metadata_field else 'pipeline', source=effective, step=step)
        if selected and skipped == len(selected):
            issue('All selected sources are marked as skip. Choose at least one source to process.', 'files')
        if uses_zenodo:
            deferred.append({'message': 'Zenodo connectivity, credentials and remote acceptance are checked during processing.'})
        if any((step.get('component_ref') or step['id']) == 'lod_generation' for step in steps):
            deferred.append({'message': 'Generated exports and required external validators are checked after generation; a preview covers only its selected record.'})
        from services.lod_artifact_service import validation_policy
        state = {'scope': 'submission-readiness-1', 'user': user_id, 'session': session.id, 'version': version.id,
                 'config': fingerprint(config), 'request': fingerprint({key: payload.get(key) for key in ('local_file_paths', 'record_ids', 'execution_items', 'is_sandbox', 'abort_on_critical_error', 'resume_from_run_id')}),
                 'settings': fingerprint(lod_snapshot), 'sources': fingerprint(checked_files), 'records': fingerprint(checked_records),
                 'effective_metadata': fingerprint(effective_metadata), 'validation_policy': fingerprint(validation_policy()),
                 'decisions': fingerprint(decisions), 'workspace': fingerprint({'environment': session.default_zenodo_environment, 'institution': session.institution_id, 'credential_preference': session.credential_preference})}
        yield {'type': 'progress', 'checked': len(selected), 'total': len(selected)}
        yield {'type': 'result', 'report': self._report(blockers, deferred, version.version, len(selected), skipped, state)}

    def _fields(self, definitions, values, category, unresolved, session, files):
        for field in definitions:
            name = field['name']
            if (category, name) in unresolved:
                continue
            if name not in values and any(
                (category, other) in unresolved
                or self.native._has_meaningful_bound_value(values.get(other))
                for other in field.get('mutex_with', [])
            ):
                continue
            value = values.get(name, field.get('default'))
            if self.native._is_missing_manifest_value(value):
                if any(self.native._has_meaningful_bound_value(values.get(other)) for other in field.get('mutex_with', [])):
                    continue
                if field.get('required'):
                    raise ReadinessFieldError(f"Supply the required {field.get('label') or name}.", category, name)
                continue
            value = self.native._coerce_playground_field_value(field, value, category=category)
            kind = field.get('type')
            if kind in {'number', 'integer'} and (isinstance(value, bool) or not math.isfinite(float(value))):
                raise ValueError(f"{field.get('label') or name} must be finite.")
            if kind not in {'file_path', 'file_list', 'dir_path'}:
                continue
            paths = value if kind == 'file_list' else [value]
            for path in paths:
                if kind == 'dir_path':
                    # Do not scan or read arbitrary configured directories during readiness.
                    if not Path(path).is_dir() or not Path(path).resolve().is_relative_to(Path(session.session_dir).resolve()):
                        raise ValueError('Choose an existing input directory inside this session.')
                    continue
                scoped = self.native._resolve_constructor_preflight_file_path(session, path)
                if str(scoped) not in files:
                    files[str(scoped)] = file_fingerprint(scoped)
                extensions = field.get('accept_extensions') or []
                if extensions and scoped.suffix.lower() not in extensions:
                    raise ValueError(f"{field.get('label') or name} requires: {', '.join(extensions)}.")

    def _report(self, blockers, deferred, version, count, skipped, state):
        unique_deferred = list({json.dumps(entry, sort_keys=True): entry for entry in deferred}.values())
        result = {'ready': not blockers, 'blockers': blockers, 'unverified': unique_deferred,
                  'pipeline_version': version, 'selected_count': count, 'skipped_count': skipped,
                  'scope': 'Local source, metadata and pipeline requirements. Remote services and generated outputs are checked during execution.', '_state': state}
        if result['ready'] and state:
            result['readiness_token'] = self.signer().dumps(state)
        return result

    def require(self, report, token=None, *, saved_state=None):
        if not report['ready']:
            raise ValidationError('Resolve the submission readiness blockers before processing.', details={'readiness': self.public(report)})
        if token:
            try:
                saved_state = self.signer().loads(token, max_age=3600)
            except BadSignature as exc:
                raise OperationConflict('Readiness expired or is invalid. Check readiness again.', details={'readiness_stale': True}) from exc
        if saved_state is not None and saved_state != report['_state']:
            raise OperationConflict('The sources, metadata, record decisions or pipeline changed. Check readiness again.', details={'readiness_stale': True})
        return report

    @staticmethod
    def public(report):
        return {key: value for key, value in report.items() if not key.startswith('_')}
