"""Exercise the native pipeline and HDPC registration against a held test allocation.

Uses a disposable local database and a candidate outer runner over SSH. Never
changes the deployed HTTP gateway, component registry, or application database.
"""
import argparse
import hashlib
import json
import math
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import yaml
from flask import Flask
from database.database import db
from database.models import User, UserRole, Session, HpcAllocation, StepRun
from services.native_pipeline_system import NativePipelineSystemService
from services.hpc_allocation_service import HpcAllocationService
from services.hdpc_local_service import add_local_source_files, create_local_record_with_metadata, read_hdpc_source_files, read_hdpc_record_files
from external_code.georeferencer.validation.run import binary_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('host', 'job-id', 'image', 'image-sha256', 'runner', 'runtime-root', 'blender', 'remote-root'):
        parser.add_argument('--'+key, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix='webhdp-georef-acceptance-'))
    remote = args.remote_root.rstrip('/')+'/native-'+uuid.uuid4().hex[:12]
    print('Evidence:', root, flush=True)

    def ssh(command):
        return subprocess.run(['ssh', args.host, command], check=True, text=True, capture_output=True).stdout

    def copy(source, destination):
        subprocess.run(['scp', '-q', str(source), str(destination)], check=True)

    ssh('mkdir -p '+shlex.quote(remote+'/inputs')+' '+shlex.quote(remote+'/outputs'))

    class Transport(HpcAllocationService):
        def get_or_create_config(self): return SimpleNamespace(enabled=True, base_url='ssh://'+args.host)
        def get_active_for_session(self, session_id): return allocation

        def stage_local_files(self, alloc, paths):
            staged = []
            for path in paths:
                folder = hashlib.sha256(str(Path(path).parent).encode()).hexdigest()[:12]
                destination = remote+'/inputs/'+folder+'/'+Path(path).name
                ssh('mkdir -p '+shlex.quote(str(Path(destination).parent)))
                copy(path, args.host+':'+destination)
                staged.append({'local_path': path, 'remote_path': destination, 'size_bytes': Path(path).stat().st_size})
            return {'staged_files': staged}

        def execute_component(self, alloc, payload):
            key = uuid.uuid4().hex
            request = root/(key+'.json'); response = root/(key+'-response.json')
            payload.update(remote_input_dir=remote+'/inputs', remote_output_dir=remote+'/outputs')
            request.write_text(json.dumps(payload)); copy(request, args.host+':'+remote+'/'+request.name)
            env = {'WEBHDP_COMPONENT_REQUEST': remote+'/'+request.name, 'WEBHDP_COMPONENT_RESPONSE': remote+'/'+response.name,
                   'WEBHDP_INPUT_DIR': remote+'/inputs', 'WEBHDP_OUTPUT_DIR': remote+'/outputs',
                   'WEBHDP_COMPONENT_RUNTIME_ROOT': args.runtime_root, 'BLENDER_BIN': args.blender}
            command = ' '.join(k+'='+shlex.quote(v) for k, v in env.items())+' python3 '+shlex.quote(args.runner)
            process = subprocess.run(['ssh', args.host, 'srun --jobid='+shlex.quote(args.job_id)+
                ' --overlap --ntasks=1 bash -lc '+shlex.quote(command)], text=True, capture_output=True)
            (root/(key+'.log')).write_text(process.stdout+'\n'+process.stderr)
            copy(args.host+':'+remote+'/'+response.name, response)
            result = json.loads(response.read_text())
            print(payload['component_key'], result.get('success'), result.get('error'), flush=True)
            return result

        def download_remote_file(self, alloc, remote_path, local_path): copy(args.host+':'+remote_path, local_path)

    app = Flask(__name__)
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///'+str(root/'app.db'),
                      SQLALCHEMY_TRACK_MODIFICATIONS=False, SECRET_KEY=uuid.uuid4().hex, WEBHDP_DEPLOYMENT_MODE='server')
    db.init_app(app)
    app.native_pipeline_service = NativePipelineSystemService(); app.hpc_allocation_service = Transport()
    with app.app_context():
        db.create_all(); native = app.native_pipeline_service; native.ensure_seeded()
        user = User(email='georef-validation@example.invalid', role=UserRole.ADMIN, is_verified=True)
        user.set_password(uuid.uuid4().hex); db.session.add(user); db.session.commit()
        uploads = root/'uploads'; shutil.copytree(args.inputs, uploads)
        cases = json.loads((uploads/'cases.json').read_text())
        inputs = [str(uploads/case['name']/'site.glb') for case in cases]
        originals = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in uploads.rglob('*') if p.is_file()}
        hdpc = str(root/'session.hdpc')
        add_local_source_files(hdpc, absolute_file_paths=inputs, pipeline_name='ingestion')
        rows = {row['absolute_path']: row for row in read_hdpc_source_files(hdpc)['items']}
        records = []
        for path in inputs:
            record = create_local_record_with_metadata(hdpc, file_id=rows[path]['file_id'],
                metadata={'metadata': {'title': Path(path).parent.name, 'description': 'Reference alignment acceptance test'}})
            record_id = record['local_record_db_id']
            add_local_source_files(hdpc, absolute_file_paths=[str(Path(path).with_suffix('.tif'))],
                                   record_id_to_associate=record_id, pipeline_name='ingestion')
            records.append((record_id, path, {'title': Path(path).parent.name}))
        session = Session(user_id=user.id, session_dir=str(root), hdpc_path=hdpc, status='processing')
        db.session.add(session); db.session.commit()
        allocation = HpcAllocation(user_id=user.id, session_id=session.id, status='running', purpose='workflow',
            requested_partition='vascunet', remote_job_id=args.job_id, remote_session_id=Path(remote).name,
            remote_session_dir=remote, remote_input_dir=remote+'/inputs', remote_output_dir=remote+'/outputs')
        db.session.add(allocation); db.session.commit()
        component_dir = Path(__file__).resolve().parents[1]
        manifest = yaml.safe_load((component_dir/'component.yaml').read_text())
        manifest['execution']['profiles'][0].update(image=args.image, sif_sha256=args.image_sha256)
        native.import_component_from_manifest(manifest, source_path=str(component_dir))
        native._seed_state = 'idle'; native.ensure_seeded()
        config = native.get_pipeline('model_georeferencing')['config']
        output = root/'outputs'; output.mkdir()
        context = {'identifier': 'model_georeferencing', 'canonical_identifier': 'model_georeferencing',
            'local_file_paths': inputs, 'db_session_id': session.id, 'db_session': session, 'initiated_by_user_id': user.id,
            'hdpc_path': hdpc, 'is_sandbox': True, 'abort_on_critical_error': False,
            'progress_callback': lambda x: print(x.get('status_message'), flush=True),
            'pipeline_timings': {'record_processing': []}, 'record_info_list': records, 'skipped_files': [],
            'outputs_dir': str(output), 'steps_map': {step['id']: step for step in config['steps']}}
        result = native.execute_registered_submission('model_georeferencing', context)
        (root/'result.json').write_text(json.dumps(result, indent=2, default=str))
        successful = sum(case['expected_success'] for case in cases)
        assert result['summary']['successful_count'] == successful, result['summary']
        assert result['summary']['failed_count'] == len(cases)-successful
        assert len(list(output.rglob('*_georeferenced.glb'))) == successful
        assert len(list(output.rglob('*.png'))) == successful*6
        assert sum(step.status == 'completed' for step in StepRun.query.all()) == successful*2
        for case, (record_id, source_path, _) in zip(cases, records):
            files = read_hdpc_record_files(hdpc, record_id)
            assert len(files) == (10 if case['expected_success'] else 2), (case['name'], files)
            if case['expected_success']:
                paths = [Path(item['absolute_path']) for item in files if item.get('absolute_path')]
                report = json.loads(next(path for path in paths if path.name == 'georeferencing_report.json').read_text())
                anchor = report['georeference']
                assert math.hypot(anchor['anchor_easting']-case['expected_anchor'][0],
                                  anchor['anchor_northing']-case['expected_anchor'][1]) < .15
                matrix = report['source_to_local_matrix']
                angle = math.degrees(math.atan2(matrix[0][2], matrix[0][0]))
                assert abs((angle-case['angle']+180)%360-180) < .5
                assert abs(report['vertical_scale']-case['expected_scale']) < .01
                assert binary_hash(Path(source_path)) == binary_hash(next(path for path in paths if path.name.endswith('_georeferenced.glb')))
        for path, checksum in originals.items():
            assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == checksum
        print('All native pipeline, failure isolation, download and original-preservation assertions passed.', flush=True)


if __name__ == '__main__':
    main()
