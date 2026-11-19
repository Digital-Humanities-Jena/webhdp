"""Durable Link queue worker that invokes the existing native pipeline engine.

Claims are serialized across processes; a run is never automatically replayed
following an interrupted component or remote side effect. Each worker process
executes one job at a time. Run multiple processes for bounded concurrency.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import timedelta
import hashlib
import mimetypes
import os
from pathlib import Path
import shutil
import socket
import threading
import time
from uuid import uuid4

from flask import current_app

from database.database import db
from database.models import HpcAllocation, PipelineRun, PipelineRunStatus, PipelineVersion, Session, User
from database.webhdp_link_models import LinkArtifact, LinkClient, LinkPublication, LinkRun, LinkToken, LinkUpload
from exceptions import FileProcessingError
from services.native_pipeline_system import NativePipelineSystemService
from services.registry_lock import OperationConflict, registry_lock
from services import webhdp_link_service as link


class LinkCancelled(FileProcessingError):
    pass


def authorization_valid(run):
    client = db.session.get(LinkClient, run.client_id)
    token = db.session.get(LinkToken, run.token_id)
    user = db.session.get(User, run.user_id)
    publication = db.session.get(LinkPublication, run.publication_id)
    # Expiry limits new HTTP operations. Accepted durable jobs remain authorized
    # after access-token expiry, but explicit revocation/account changes stop them.
    return bool(client and client.enabled and token and not token.revoked and link.user_can_link(user)
                and (user.token_version or 0) == token.user_token_version
                and publication and publication.enabled and run.publication_id in link.client_config(client)['pipeline_ids'])


def check_run(run_id):
    db.session.expire_all()
    run = db.session.get(LinkRun, run_id)
    if run.cancel_requested or run.status == 'cancelled':
        raise LinkCancelled('Cancellation was requested.')
    if not authorization_valid(run):
        raise link.LinkError('authorization_revoked', 'Authorization was withdrawn before the next component.', 403)
    return run


def _inside(path, root, *, must_file=False):
    candidate = Path(path)
    try:
        return candidate.is_absolute() and candidate.is_relative_to(root) and candidate.resolve(strict=True) == candidate and (candidate.is_file() or (not must_file and candidate.is_dir()))
    except (OSError, RuntimeError, ValueError):
        return False


class GuardedAdapter:
    """Apply Link authority and data confinement around the native adapter."""
    def __init__(self, delegate, run_id, root, timeout):
        self.delegate, self.run_id, self.root, self.timeout = delegate, run_id, root, timeout

    def execute(self, request):
        check_run(self.run_id)
        manifest = request.metadata.get('component_manifest') or {}
        fields = manifest.get('inputs', []) + [p for group in manifest.get('parameter_groups', []) for p in group.get('parameters', [])]
        for field in fields:
            if field.get('type') not in {'file_path', 'file_list', 'dir_path'}:
                continue
            value = (request.inputs if field in manifest.get('inputs', []) else request.parameters).get(field['name'])
            values = value if isinstance(value, list) else [value]
            for path in values:
                if path is not None and not _inside(path, self.root):
                    raise FileProcessingError('A component input is outside the private run workspace.')
                if path is not None and Path(path).is_dir() and any(not _inside(child, self.root) for child in Path(path).rglob('*')):
                    raise FileProcessingError('A component input directory contains a link or nonregular file.')
        request.metadata['timeout_seconds'] = self.timeout
        request.metadata['private_execution_root'] = str(self.root)
        # Give every component invocation its own directory even for CLI
        # profiles, so artifacts cannot be overwritten by a later step.
        if request.profile.get('adapter') != 'hpc_link':
            request.workdir = str(Path(request.workdir) / ('link-step-' + request.step_id))
            Path(request.workdir).mkdir(parents=True, exist_ok=True)
        from services.webhdp_link_secrets import component_environment
        extra_environment = component_environment(request, db.session.get(LinkRun, self.run_id).user_id)
        original_environment = request.environment
        try:
            request.environment = {**(original_environment or {}), **extra_environment}
            result = self.delegate.execute(request)
        finally:
            request.environment = original_environment
        if request.profile.get('adapter') != 'hpc_link':
            for artifact in result.get('artifacts') or []:
                path = artifact.get('path')
                if path and not _inside(path, self.root / 'outputs'):
                    raise FileProcessingError('A component output is outside the private output directory.')
            # Require manifest-declared required outputs, not merely exit code 0.
            outputs = result.get('outputs') or {}
            for field in manifest.get('outputs', []):
                if field.get('required') and field.get('type') == 'file_path':
                    path = outputs.get(field['name'])
                    if not isinstance(path, str) or not _inside(path, self.root / 'outputs', must_file=True):
                        raise FileProcessingError('A required component artifact was not produced.')
        check_run(self.run_id)
        return result


@contextmanager
def heartbeat(run_id):
    app = current_app._get_current_object()
    stop = threading.Event()
    def pulse():
        while not stop.wait(10):
            with app.app_context():
                try:
                    LinkRun.query.filter_by(id=run_id, status='running').update({'heartbeat_at': link.now()})
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    app.logger.exception('Link worker heartbeat failed')
                finally:
                    db.session.remove()
    thread = threading.Thread(target=pulse, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=2)


def recover_interrupted():
    """Mark abandoned jobs explicitly failed; never repeat unknown side effects."""
    threshold = link.now() - timedelta(seconds=int(current_app.config.get('WEBHDP_LINK_STALE_SECONDS', 120)))
    for run in LinkRun.query.filter(LinkRun.status == 'running', LinkRun.heartbeat_at < threshold).all():
        try:
            with registry_lock('link-run:' + run.id):
                db.session.refresh(run)
                if run.status != 'running' or run.heartbeat_at >= threshold:
                    continue
                run.status, run.error_code, run.completed_at = 'failed', 'interrupted', link.now()
                if run.native_run_id:
                    native = db.session.get(PipelineRun, run.native_run_id)
                    if native and native.status in {PipelineRunStatus.PENDING, PipelineRunStatus.RUNNING}:
                        native.status, native.completed_at = PipelineRunStatus.FAILED, link.now()
                        native.error_message = 'Link worker interrupted; no automatic replay.'
                db.session.commit()
        except OperationConflict:
            continue  # An actual worker still holds the execution lock.


def release_owned_allocation(run):
    saved = link.loads(run.request_json)
    if not saved.get('_hpc_cleanup_pending') or not saved.get('_hpc_allocation_id'):
        return
    try:
        service = current_app.hpc_allocation_service
        user = db.session.get(User, run.user_id)
        allocation = service.get_allocation(saved['_hpc_allocation_id'], user=user)
        if allocation.session_id != run.session_id or allocation.user_id != run.user_id:
            raise FileProcessingError('Refusing to release an allocation not owned by this Link job.')
        retain = saved['publication'].get('hpc', {}).get('retain_allocation', False)
        if not (retain and allocation.status == 'running'):
            service.release(allocation)
        saved['_hpc_cleanup_pending'] = False
        saved['_hpc_retained'] = bool(retain and allocation.status == 'running')
        run.request_json = link.dumps(saved)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Link HPC cleanup needs retry for run %s', run.id)


def cleanup_allocations():
    for row in LinkRun.query.filter(LinkRun.status.in_(list(link.TERMINAL))).all():
        if link.loads(row.request_json).get('_hpc_cleanup_pending'):
            try:
                with registry_lock('link-run:' + row.id):
                    release_owned_allocation(row)
            except OperationConflict:
                continue


def claim_next():
    try:
        with registry_lock('link-queue'):
            recover_interrupted()
            maximum = int(current_app.config.get('WEBHDP_LINK_MAX_CONCURRENT_RUNS') or os.environ.get('WEBHDP_LINK_MAX_CONCURRENT_RUNS', '2'))
            running = LinkRun.query.filter_by(status='running').all()
            if len(running) >= maximum:
                return None
            running_by_account = Counter(run.user_id for run in running)
            running_by_app = Counter(run.client_id for run in running)
            queued = LinkRun.query.filter_by(status='queued').order_by(LinkRun.created_at, LinkRun.id).all()
            queued.sort(key=lambda run: running_by_account[run.user_id])
            for run in queued:
                if not authorization_valid(run):
                    run.status, run.error_code, run.completed_at = 'failed', 'authorization_revoked', link.now()
                    db.session.commit()
                    continue
                client = db.session.get(LinkClient, run.client_id)
                if running_by_app[run.client_id] >= link.client_config(client)['max_concurrent_runs']:
                    continue
                policy = link.loads(run.request_json).get('publication', {}).get('hpc', {})
                if policy.get('reuse_retained_allocation'):
                    # Reuse is serialized in the durable queue even across apps
                    # and worker processes. A waiting job consumes no worker.
                    same_user = (row for row in running if row.user_id == run.user_id)
                    if any(link.loads(row.request_json).get('publication', {}).get('hpc', {}).get('enabled') for row in same_user):
                        continue
                run.status, run.started_at, run.heartbeat_at = 'running', link.now(), link.now()
                run.worker_id = f'{socket.gethostname()}:{os.getpid()}:{uuid4()}'
                db.session.commit()
                return run.id
    except OperationConflict:
        return None
    return None


def _copy_inputs(run, root):
    paths = []
    for upload_id in link.loads(run.request_json)['inputs']:
        upload = db.session.get(LinkUpload, upload_id)
        if upload is None or upload.client_id != run.client_id or upload.user_id != run.user_id:
            raise FileProcessingError('An accepted input upload is unavailable.')
        source = link.upload_path(upload)
        if not _inside(str(source), link.storage_root() / 'uploads', must_file=True):
            raise FileProcessingError('An input file is unavailable.')
        destination = root / 'inputs' / f'{len(paths)+1:04d}' / upload.name
        destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        checksum = hashlib.sha256()
        with source.open('rb') as reader, destination.open('xb') as writer:
            while chunk := reader.read(1024**2):
                checksum.update(chunk)
                writer.write(chunk)
        if checksum.hexdigest() != upload.sha256:
            raise FileProcessingError('An accepted input upload changed before execution.')
        paths.append(str(destination))
    return paths


def _prepare_records(session, paths, root, config):
    from services.hdpc_scan_service import create_and_scan_hdpc_project
    from services.hdpc_local_service import get_hdpc_file_id_map, create_local_record_with_metadata, add_local_source_files
    hdpc_path = str(root / 'project.hdpc')
    create_and_scan_hdpc_project(hdpc_path=hdpc_path, data_in_path=str(root / 'inputs'), data_out_path=str(root / 'outputs'),
                                project_name='WebHDP-Link run', batch_entity='subdirectory', scan_options={'extensions': config['input']['extensions']})
    mapping = get_hdpc_file_id_map(hdpc_path)
    records = []
    selected = paths[:1] if config['execution_mode'] == 'bundle' else paths
    for path in selected:
        relative = str(Path(path).relative_to(root / 'inputs'))
        file_id = mapping.get(relative)
        if file_id is None:
            raise FileProcessingError('An uploaded file could not be registered as a pipeline input.')
        result = create_local_record_with_metadata(hdpc_path, file_id=file_id, metadata={'metadata': {'title': Path(path).name}}, is_sandbox=True)
        record_id = result['local_record_db_id']
        if config['execution_mode'] == 'bundle' and len(paths) > 1:
            add_local_source_files(hdpc_path, absolute_file_paths=paths[1:], record_id_to_associate=record_id)
        records.append((record_id, path, {}))
    session.hdpc_path = hdpc_path
    db.session.commit()
    return records


def _reuse_retained_allocation(run, policy, service, user):
    """Transfer an idle, retained Link allocation under a cross-worker lease.

    Both jobs must opt in and have the same frozen resource policy. This never
    changes scheduler walltime, uses a foreign user's allocation, or takes a
    reservation from a normal workflow or an active Link job.
    """
    if not policy.get('reuse_retained_allocation'):
        return None
    service.require_allocation_access(user, purpose='workflow')
    if not service.get_or_create_config().enabled:
        raise FileProcessingError('HPC-Link is not enabled on this WebHDP instance.')
    with registry_lock('link-hpc-reuse:' + str(run.user_id)):
        candidates = LinkRun.query.filter(LinkRun.user_id == run.user_id,
            LinkRun.status.in_(list(link.TERMINAL)), LinkRun.id != run.id).order_by(LinkRun.completed_at.desc()).all()
        for previous in candidates:
            saved = link.loads(previous.request_json)
            old_policy = saved.get('publication', {}).get('hpc', {})
            if (not saved.get('_hpc_retained') or saved.get('_hpc_cleanup_pending')
                    or not old_policy.get('reuse_retained_allocation') or old_policy != policy):
                continue
            allocation = HpcAllocation.query.filter_by(public_id=saved.get('_hpc_allocation_id'),
                user_id=run.user_id, session_id=previous.session_id, status='running', purpose='workflow').first()
            old_session = db.session.get(Session, previous.session_id)
            if allocation is None or old_session is None or old_session.origin_type != 'webhdp_link':
                continue
            service.refresh_allocation(allocation)
            if allocation.status != 'running':
                continue
            # Commit the transfer and consumed retention marker atomically.
            allocation.session_id = run.session_id
            saved['_hpc_retained'] = False
            saved['_hpc_reused_by'] = run.id
            previous.request_json = link.dumps(saved)
            current = link.loads(run.request_json)
            current.update({'_hpc_allocation_id': allocation.public_id, '_hpc_cleanup_pending': True,
                            '_hpc_reused_from': previous.id})
            run.request_json = link.dumps(current)
            db.session.commit()
            return allocation
    return None


def _prepare_hpc(run, config):
    policy = config.get('hpc') or {}
    if not policy.get('enabled'):
        return
    service = current_app.hpc_allocation_service
    user = db.session.get(User, run.user_id)
    payload = {key: value for key, value in policy.items() if key in {'partition', 'gpu_count', 'gpu_type'}}
    # The central service remains the only authority for scheduler access,
    # resource grants and queue limits. Clients cannot supply this policy.
    if 'walltime_hours' in policy:
        payload['duration_minutes'] = int(policy['walltime_hours'] * 60)
    allocation = _reuse_retained_allocation(run, policy, service, user)
    if allocation is None:
        result = service.request_allocation(user=user, session_id=run.session_id, purpose='workflow', payload=payload)
        allocation = service.get_allocation(result['allocation_id'], user=user)
    else:
        result = {'allocation_id': allocation.public_id}

    saved = link.loads(run.request_json)
    saved['_hpc_allocation_id'] = result['allocation_id']
    saved['_hpc_cleanup_pending'] = True
    run.request_json = link.dumps(saved)
    db.session.commit()
    deadline = time.monotonic() + int(current_app.config.get(
        'WEBHDP_LINK_HPC_WAIT_SECONDS', os.environ.get('WEBHDP_LINK_HPC_WAIT_SECONDS', '900')))
    while service.get_active_for_session(run.session_id) is None or allocation.status != 'running':
        check_run(run.id)
        if time.monotonic() >= deadline:
            raise FileProcessingError('HPC allocation was not ready before the central queue deadline.')
        service.poll_allocation(allocation)
        if allocation.status in {'failed', 'expired', 'released', 'cancelled'}:
            raise FileProcessingError('The central HPC allocation failed.')
        time.sleep(2)
    preflight = service.preflight(allocation, components=[step['component'] for step in config['structure']])
    if not preflight.get('success', True):
        raise FileProcessingError('Central HPC component preflight failed.')


def _storage_overflow(client, user_id):
    quota = link.client_config(client)
    if link.storage_used(client.id) > quota['max_storage_bytes']:
        return 'storage_quota_exceeded'
    if link.storage_used(client.id, user_id) > link.client_account_limits(quota)['max_storage_bytes']:
        return 'account_storage_quota_exceeded'
    return None


def _collect_artifacts(run, root):
    native = db.session.get(PipelineRun, run.native_run_id)
    client = db.session.get(LinkClient, run.client_id)
    overflow = _storage_overflow(client, run.user_id)
    if overflow:
        raise link.LinkError(overflow, 'Outputs exceeded a storage limit for this application.', 413)
    seen = set()
    for artifact in native.artifacts:
        source = Path(artifact.path or '')
        if not _inside(str(source), root / 'outputs', must_file=True):
            # Directory outputs require explicit file outputs from the component;
            # never serve directories, links or arbitrary native artifact paths.
            continue
        if str(source) in seen:
            continue
        seen.add(str(source))
        size = source.stat().st_size
        checksum = hashlib.sha256()
        with source.open('rb') as reader:
            while chunk := reader.read(1024**2):
                checksum.update(chunk)
        # Artifacts are immutable references to this run's isolated output tree.
        db.session.add(LinkArtifact(run_id=run.id, relative_path=str(source.relative_to(root)),
                                    name=source.name, size=size, sha256=checksum.hexdigest(),
                                    media_type=mimetypes.guess_type(source.name)[0] or 'application/octet-stream'))
    db.session.commit()


def execute_run(run_id):
    with registry_lock('link-run:' + run_id), heartbeat(run_id):
        run = db.session.get(LinkRun, run_id)
        if run is None or run.status != 'running':
            return
        root = link.storage_root() / 'runs' / run.id
        native_run = None
        try:
            check_run(run_id)
            root.mkdir(parents=True, mode=0o700, exist_ok=False)
            (root / 'outputs').mkdir(mode=0o700)
            paths = _copy_inputs(run, root)
            payload = link.loads(run.request_json)
            config = payload['publication']
            session = Session(user_id=run.user_id, session_dir=str(root), status='submitting', origin_type='webhdp_link',
                              sharing_scope='private', origin_metadata_json=link.dumps({'client_id': run.client_id, 'link_run_id': run.id}))
            db.session.add(session)
            db.session.flush()
            run.session_id = session.id
            db.session.commit()
            records = _prepare_records(session, paths, root, config)
            version = db.session.get(PipelineVersion, run.pipeline_version_id)
            native_run = PipelineRun(public_id=run.id, pipeline_definition_id=version.pipeline_definition_id,
                                     pipeline_version_id=version.id, session_id=session.id, initiated_by_user_id=run.user_id,
                                     status=PipelineRunStatus.PENDING, request_json=link.dumps({'link_run_id': run.id}))
            db.session.add(native_run)
            db.session.flush()
            run.native_run_id = native_run.id
            db.session.commit()
            _prepare_hpc(run, config)
            native = NativePipelineSystemService()
            native._adapter_registry = {name: GuardedAdapter(adapter, run.id, root, config['step_timeout_seconds']) for name, adapter in native._adapter_registry.items()}
            overrides = {}
            for name, value in payload['parameters'].items():
                field = config['parameters'][name]
                overrides.setdefault(field['step_id'], {'parameters': {}})['parameters'][field['parameter']] = value
            execution = {'db_session_id': session.id, 'db_session': session, 'hdpc_path': session.hdpc_path,
                         'record_info_list': records, 'outputs_dir': str(root / 'outputs'), 'steps_map': overrides,
                         'bucket_source_files': paths if config['execution_mode'] == 'bundle' else [], 'local_file_paths': paths,
                         'pipeline_timings': {'record_processing': []}, 'abort_on_critical_error': True,
                         'initiated_by_user_id': run.user_id, 'is_sandbox': True, 'publishing_context': {}}
            result = native.execute_registered_submission(version.pipeline_definition.identifier, execution, existing_run_public_id=native_run.public_id)
            check_run(run_id)
            with registry_lock('link-storage:' + run.client_id):
                _collect_artifacts(run, root)
            run.status = 'succeeded' if result.get('success') else 'failed'
            run.error_code = None if result.get('success') else 'execution_failed'
            session.status = 'completed' if result.get('success') else 'failed'
        except Exception as exc:
            db.session.rollback()
            run = db.session.get(LinkRun, run_id)
            if isinstance(exc, LinkCancelled) or run.cancel_requested:
                run.status, run.error_code = 'cancelled', None
            else:
                run.status = 'failed'
                run.error_code = exc.code if isinstance(exc, link.LinkError) else 'execution_failed'
                current_app.logger.exception('WebHDP-Link run %s failed', run_id)
            native_run = db.session.get(PipelineRun, run.native_run_id) if run.native_run_id else None
            if native_run and native_run.status in {PipelineRunStatus.PENDING, PipelineRunStatus.RUNNING}:
                native_run.status, native_run.completed_at = PipelineRunStatus.FAILED, link.now()
                native_run.error_message = str(exc)
                for step in native_run.step_runs:
                    if step.status in {'running', 'pending'}:
                        step.status, step.completed_at, step.error_message = 'failed', link.now(), str(exc)
            if run.session_id:
                db.session.get(Session, run.session_id).status = 'failed'
            client = db.session.get(LinkClient, run.client_id)
            overflow = _storage_overflow(client, run.user_id) if client else None
            if overflow:
                # Remove only this failed run's derived outputs, never uploads.
                shutil.rmtree(root / 'outputs', ignore_errors=True)
                LinkArtifact.query.filter_by(run_id=run.id).delete()
                run.error_code = overflow
        run.completed_at, run.heartbeat_at = link.now(), link.now()
        db.session.commit()
        release_owned_allocation(run)


def process_next():
    cleanup_allocations()
    run_id = claim_next()
    if run_id is None:
        return False
    execute_run(run_id)
    return True
