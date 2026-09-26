"""Validate the immutable component in a held GPU allocation without installing it."""
import argparse
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import tempfile
import time
from pathlib import Path


def binary_hash(path):
    with path.open('rb') as stream:
        stream.seek(12)
        size, _ = struct.unpack('<I4s', stream.read(8))
        stream.seek(size, 1)
        checksum = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            checksum.update(chunk)
        return checksum.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, type=Path)
    parser.add_argument('--inputs', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--component-dir', type=Path)
    parser.add_argument('--case', action='append', help='Run only a named case; repeat to select several.')
    args = parser.parse_args()
    if not os.environ.get('SLURM_JOB_ID'):
        parser.error('Run inside an allocated GPU scheduler job.')
    runtime = shutil.which('singularity') or shutil.which('apptainer')
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    results = []
    for case in json.loads((args.inputs/'cases.json').read_text()):
        name = case['name']
        if args.case and name not in args.case:
            continue
        request = output/f'{name}-request.json'; response = output/f'{name}-response.json'
        request.write_text(json.dumps({'inputs': {'input_file': f'/inputs/{name}/site.glb',
            'reference_files': [f'/inputs/{name}/site.tif']}, 'parameters': {}}))
        env = os.environ.copy()
        for prefix in ('SINGULARITYENV_', 'APPTAINERENV_'):
            for key, value in {'WEBHDP_COMPONENT_REQUEST': '/outputs/'+request.name,
                'WEBHDP_COMPONENT_RESPONSE': '/outputs/'+response.name, 'WEBHDP_INPUT_DIR': '/inputs',
                'WEBHDP_OUTPUT_DIR': '/outputs', 'CUDA_VISIBLE_DEVICES': os.environ.get('CUDA_VISIBLE_DEVICES', '')}.items():
                env[prefix+key] = value
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix='georef-check-', dir='/tmp') as scratch:
            command = [runtime, 'exec', '--nv', '--cleanenv', '--containall', '--no-home', '--pwd', '/app',
                '--bind', scratch+':/tmp', '--bind', str(args.inputs.resolve())+':/inputs:ro',
                '--bind', str(output)+':/outputs']
            if args.component_dir:
                command += ['--bind', str(args.component_dir.resolve())+':/opt/webhdp/georeferencer:ro']
            command += [str(args.image.resolve()), 'python3', '/opt/webhdp/georeferencer/runner.py']
            with (output/f'{name}.log').open('w') as log:
                process = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=3600)
        result = json.loads(response.read_text()) if response.exists() else {}
        success = result.get('success') is True and process.returncode == 0
        item = {'case': name, 'success': success, 'expected_success': case['expected_success'],
                'matched': bool(result) and success == case['expected_success'], 'error': result.get('error'),
                'seconds': round(time.monotonic()-started, 1)}
        if success:
            def local(value):
                return output/Path(value).relative_to('/outputs')
            report = json.loads(local(result['outputs']['georeferencing_report']).read_text())
            anchor = report['georeference']
            error = math.hypot(anchor['anchor_easting']-case['expected_anchor'][0], anchor['anchor_northing']-case['expected_anchor'][1])
            matrix = report['source_to_local_matrix']
            angle = math.degrees(math.atan2(matrix[0][2], matrix[0][0]))
            angle_error = abs((angle-case['angle']+180)%360-180)
            scale_error = abs(report['vertical_scale']-case['expected_scale'])
            preserved = binary_hash(args.inputs/name/'site.glb') == binary_hash(local(result['outputs']['georeferenced_model']))
            item.update(anchor_error_metres=error, angle_error_degrees=angle_error, scale_error=scale_error,
                        binary_preserved=preserved, quality=report['quality'])
            item['matched'] &= error < 0.15 and angle_error < 0.5 and scale_error < 0.01 and preserved
        elif result.get('outputs'):
            item['matched'] = False
        results.append(item)
        print(json.dumps(item), flush=True)
        (output/'summary.json').write_text(json.dumps(results, indent=2))
    if not results or any(not item['matched'] for item in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
