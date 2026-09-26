"""Run component contracts inside an existing GPU allocation; never install them."""
import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, type=Path)
    parser.add_argument('--inputs', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--component-dir', type=Path, help='Optional candidate wrapper bind; does not modify the SIF')
    parser.add_argument('--resolution', type=int, default=256)
    parser.add_argument('--quality', choices=['LOW', 'MEDIUM', 'HIGH'], default='LOW')
    parser.add_argument('--reject', nargs='*', default=['BoxAnimated', 'degenerate'])
    args = parser.parse_args()
    runtime = shutil.which('singularity') or shutil.which('apptainer')
    if not runtime: parser.error('Singularity or Apptainer is required.')
    if not os.environ.get('SLURM_JOB_ID'): parser.error('Run inside a GPU scheduler allocation.')
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=False)
    results = []
    for model in sorted(args.inputs.resolve().glob('*.glb')):
        request = output / (model.stem + '-request.json')
        response = output / (model.stem + '-response.json')
        request.write_text(json.dumps({'inputs': {'input_file': '/inputs/' + model.name},
                                      'parameters': {'quality': args.quality, 'texture_resolution': args.resolution}}))
        env = os.environ.copy()
        for prefix in ('SINGULARITYENV_', 'APPTAINERENV_'):
            for key, value in {'WEBHDP_COMPONENT_REQUEST': '/outputs/' + request.name,
                               'WEBHDP_COMPONENT_RESPONSE': '/outputs/' + response.name,
                               'WEBHDP_OUTPUT_DIR': '/outputs',
                               'CUDA_VISIBLE_DEVICES': os.environ.get('CUDA_VISIBLE_DEVICES', '')}.items():
                env[prefix + key] = value
        start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix='mesh-validation-', dir='/tmp') as scratch:
            command = [runtime, 'exec', '--nv', '--cleanenv', '--containall', '--no-home', '--pwd', '/app',
                       '--bind', scratch + ':/tmp', '--bind', str(args.inputs.resolve()) + ':/inputs:ro',
                       '--bind', str(output) + ':/outputs']
            if args.component_dir:
                command += ['--bind', str(args.component_dir.resolve()) + ':/opt/webhdp/mesh_optimizer:ro']
            command += [str(args.image.resolve()), 'python3', '/opt/webhdp/mesh_optimizer/runner.py']
            with (output / (model.stem + '.log')).open('w') as log:
                process = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=7200)
        result = json.loads(response.read_text()) if response.exists() else {}
        success = result.get('success') is True and process.returncode == 0
        expected = model.stem not in args.reject
        item = {'model': model.name, 'success': success, 'expected_success': expected,
                'matched': success == expected and bool(result), 'error': result.get('error'),
                'seconds': round(time.monotonic() - start, 1)}
        results.append(item); print(json.dumps(item), flush=True)
    (output / 'summary.json').write_text(json.dumps(results, indent=2))
    if not results or any(not item['matched'] for item in results): raise SystemExit(1)


if __name__ == '__main__':
    main()
