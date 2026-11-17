"""Pinned HMSM optical extraction through the central HPC file contract."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

OUTPUTS = {'midi_file': 'result.mid', 'report': 'piano-report.json',
           'scan_preview': 'scan-preview.webp', 'track_preview': 'track-preview.webp',
           'package': 'piano-evidence.zip'}
EXTENSIONS = {'.png', '.jpg', '.jpeg', '.tif', '.tiff', '.webp'}


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def source_inventory(source, expected):
    source = Path(source).resolve(strict=True)
    manifest_path = source.parent / 'source-manifest.json'
    if sha256(manifest_path) != expected:
        raise ValueError('Installed source inventory changed')
    inventory = json.loads(manifest_path.read_text())
    for name, digest in inventory['files'].items():
        path = source / name
        if Path(name).is_absolute() or '..' in Path(name).parts or path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(source) or sha256(path) != digest:
            raise ValueError('Installed scientific source changed')
    actual = {str(p.relative_to(source)) for p in source.rglob('*') if p.is_file()}
    if actual != set(inventory['files']):
        raise ValueError('Unexpected files in scientific source')
    return inventory


def parameters(value, models):
    if not isinstance(value, dict) or set(value) - {'model_id', 'roll_speed', 'method', 'polarity'}:
        raise ValueError('Unknown processing parameter')
    result = {'model_id': value.get('model_id', 'generic_65_no_dynamics'),
              'roll_speed': value.get('roll_speed', 6), 'method': value.get('method', 'robust'),
              'polarity': value.get('polarity', 'dark')}
    if any(not isinstance(result[key], str) for key in ('model_id', 'method', 'polarity')) or result['model_id'] not in models or result['method'] not in {'robust', 'background', 'adaptive', 'otsu'} or result['polarity'] not in {'dark', 'light'}:
        raise ValueError('Unsupported carrier or extraction setting')
    speed = result['roll_speed']
    if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not math.isfinite(speed) or not .2 <= speed <= 30:
        raise ValueError('Roll speed outside the published range')
    return result


def execute(request, *, source, source_manifest_sha256, input_root, output_root, require_allocation=True):
    if require_allocation and not os.environ.get('SLURM_JOB_ID'):
        raise ValueError('A centrally managed Slurm allocation is required')
    source = Path(source).resolve(strict=True)
    inventory = source_inventory(source, source_manifest_sha256)
    options = parameters(request.get('parameters', {}), inventory['roll_models'])
    inputs = request.get('inputs', {})
    if not isinstance(inputs, dict) or set(inputs) != {'input_file'} or not isinstance(inputs['input_file'], str):
        raise ValueError('Exactly one staged scan is required')
    root = Path(input_root).resolve(strict=True)
    path = Path(inputs['input_file'])
    path = (root / path).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() not in EXTENSIONS or not 0 < path.stat().st_size <= 512 * 1024**2:
        raise ValueError('Scan is outside the staged input contract')
    before = sha256(path)
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('The output directory must be empty')
    started = time.monotonic()
    # This private tree remains within the invocation. No scientific files or
    # private source paths are copied into the public derived evidence package.
    with tempfile.TemporaryDirectory(prefix='hmsm-private-', dir=output.parent) as temporary:
        data = Path(temporary) / 'data'
        environment = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'TMP', 'TEMP') if key in os.environ}
        environment.update(HMSM_DATA_DIR=str(data), PYTHONDONTWRITEBYTECODE='1', HOME=temporary, XDG_CACHE_HOME=str(Path(temporary) / 'cache'),
                           VIPS_CONCURRENCY='2', OPENBLAS_NUM_THREADS='2', OMP_NUM_THREADS='2',
                           MPLBACKEND='Agg', MPLCONFIGDIR=str(Path(temporary) / 'matplotlib'))
        command = [sys.executable, '-m', 'backend.studio.cli', str(path), '--model', options['model_id'],
                   '--output-name', 'link-result', '--roll-speed', str(options['roll_speed']),
                   '--method', options['method'], '--polarity', options['polarity']]
        with (Path(temporary) / 'processing.log').open('w') as log:
            process = subprocess.run(command, cwd=source, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=3500)
        if process.returncode:
            print((Path(temporary) / 'processing.log').read_text()[-8000:], file=sys.stderr)
            raise ValueError('HMSM optical processing failed')
        folder = data / 'projects/link-result'
        native = json.loads((folder / 'result.json').read_text())
        if sha256(path) != before or native['provenance']['source_sha256'] != before:
            raise ValueError('Source scan changed during processing')
        source_inventory(source, source_manifest_sha256)
        if native['provenance']['software']['source_sha256'] != inventory['module_sha256']:
            raise ValueError('Scientific source identity differs from the frozen inventory')
        note_fields = {'id', 'pitch', 'onset', 'offset', 'start', 'end', 'duration', 'velocity', 'confidence', 'track', 'time'}
        notes = [{key: value for key, value in note.items() if key in note_fields} for note in native['notes']]
        report = {'schema_version': '1.0', 'operation': 'hmsm-scan-digitization', 'engine': 'HMSM Studio',
                  'source': {'name': path.name, 'sha256': before, 'bytes': path.stat().st_size},
                  'model_id': options['model_id'], 'parameters': options, 'roll_speed_fpm': options['roll_speed'],
                  'note_count': len(notes), 'notes': notes, 'control_count': len(native.get('controls', [])),
                  'duration_seconds': native.get('duration'), 'model_digest': native['provenance']['model_digest'],
                  'source_snapshot_sha256': source_manifest_sha256, 'software': native['provenance']['software'],
                  'elapsed_seconds': time.monotonic() - started, 'processing_kind': 'CPU optical extraction inside central allocation',
                  'scope': 'Measured candidate notes and MIDI. Carrier profile, orientation, timing and historical interpretation require review.',
                  'limitations': native.get('limitations', [])}
        for target, relative in [('result.mid', 'result.mid'), ('scan-preview.webp', 'artifacts/source.webp'), ('track-preview.webp', 'artifacts/tracks.webp')]:
            original = folder / relative
            if original.is_symlink() or not original.is_file() or not original.resolve().is_relative_to(folder):
                raise ValueError('Expected optical output is unavailable')
            shutil.copyfile(original, output / target)
        for key, filename in [('physical_observations', 'physical-observations.json'), ('interpretation_decisions', 'interpretation-decisions.json')]:
            receipt = native.get(key)
            if receipt:
                original = folder / 'artifacts' / filename
                if receipt.get('file') != filename or original.is_symlink() or not original.is_file() or receipt.get('sha256') != sha256(original) or receipt.get('bytes') != original.stat().st_size:
                    raise ValueError('Optical ledger fixity failed')
                raw = original.read_bytes()
                if any(private.encode() in raw for private in [str(source), str(data), str(root)]):
                    raise ValueError('Optical ledger contains a private processing path')
                shutil.copyfile(original, output / filename)
                report.setdefault('optical_evidence', {})[key] = {'name': filename, 'sha256': sha256(original), 'bytes': original.stat().st_size}
        write_json(output / 'piano-report.json', report)
    files = {p.name: {'sha256': sha256(p), 'bytes': p.stat().st_size} for p in sorted(output.iterdir()) if p.is_file() and p.name != 'piano-evidence.zip'}
    with zipfile.ZipFile(output / 'piano-evidence.zip', 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in files:
            bundle.write(output / name, name)
        bundle.writestr('manifest.json', json.dumps({'schema_version': '1.0', 'files': files}, sort_keys=True))
    results = {name: str(output / filename) for name, filename in OUTPUTS.items()}
    return {'success': True, 'status': 'completed', 'outputs': results,
            'artifacts': [{'name': name, 'artifact_kind': 'file', 'path': filename} for name, filename in results.items()],
            'summary': {'note_count': len(notes), 'model_id': options['model_id'], 'source_sha256': before}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--source-manifest-sha256', required=True)
    parser.add_argument('--expected-runner-sha256', required=True)
    args = parser.parse_args()
    try:
        if sha256(__file__) != args.expected_runner_sha256:
            raise ValueError('Installed runner changed')
        request = json.loads(Path(os.environ['WEBHDP_COMPONENT_REQUEST']).read_text())
        result = execute(request, source=args.source, source_manifest_sha256=args.source_manifest_sha256,
                         input_root=os.environ['WEBHDP_INPUT_DIR'], output_root=os.environ['WEBHDP_OUTPUT_DIR'])
    except Exception as error:
        import traceback
        traceback.print_exc()
        result = {'success': False, 'status': 'failed', 'error': 'HMSM processing did not pass its source, runtime or scan checks.', 'error_type': type(error).__name__}
    write_json(os.environ['WEBHDP_COMPONENT_RESPONSE'], result)
    return 0 if result['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
