"""Run a CPU corpus in isolated processes and record quality/resource evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def run_case(args):
    from external_code.geometric_lod_generator import runner
    import resource
    source = args.case.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ['WEBHDP_BLENDER_BIN'] = str(args.blender.resolve())
    os.environ['WEBHDP_OUTPUT_DIR'] = str(args.output.resolve())
    before = digest(source)
    started = time.monotonic()
    result = {'source': str(source), 'source_sha256': before}
    try:
        result['response'] = runner.execute({'inputs': {'input_file': str(source)},
            'parameters': {'target_ratio': args.ratio, 'max_relative_error': args.relative_error}})
        report = json.loads(Path(result['response']['outputs']['analysis_report']).read_text())
        result['levels'] = {level: {'triangles': entry['triangles'], 'bytes': entry['bytes'],
            'size_change_percent': 100 * (entry['bytes'] / report['source_bytes'] - 1),
            'retained_meshes': sum(check['status'] == 'retained' for check in entry['geometry_checks']),
            'maximum_relative_error': max(check['sampled_error'] / check['error_limit'] * args.relative_error for check in entry['geometry_checks'])}
            for level, entry in report['levels'].items()}
        result['source_triangles'] = report['source_triangles']
        result['blender_version'] = report['blender_version']
        result['status'] = 'passed'
    except Exception as exc:
        result.update(status='rejected', error=str(exc), error_type=type(exc).__name__)
    result['elapsed_seconds'] = time.monotonic() - started
    # A fresh worker has exactly one Blender child, so this is per-case peak RSS.
    result['blender_peak_rss_bytes'] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * (1 if sys.platform == 'darwin' else 1024)
    result['source_unchanged'] = digest(source) == before
    if not result['source_unchanged']:
        result['status'] = 'failed'
    (args.output / 'case.json').write_text(json.dumps(result, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--blender', required=True, type=Path)
    parser.add_argument('--ratio', type=float, default=0.5)
    parser.add_argument('--relative-error', type=float, default=0.001)
    parser.add_argument('--expected-rejections', nargs='*', default=['BoxAnimated', 'degenerate'])
    parser.add_argument('--validator-node-path', type=Path)
    parser.add_argument('--case', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.case:
        run_case(args)
        return
    if not args.inputs or not args.inputs.is_dir() or not args.validator_node_path:
        parser.error('--inputs and --validator-node-path are required for corpus acceptance')
    if args.output.exists():
        parser.error('Use a new output directory to preserve earlier evidence.')
    inputs = sorted(args.inputs.glob('*.glb'))
    if not inputs:
        parser.error('The corpus contains no GLB files.')
    args.output.mkdir(parents=True)
    cases = []
    for index, source in enumerate(inputs):
        destination = args.output / f'case-{index:03d}'
        timed_out = False
        try:
            completed = subprocess.run([sys.executable, __file__, '--case', str(source), '--output', str(destination),
                '--blender', str(args.blender), '--ratio', str(args.ratio), '--relative-error', str(args.relative_error)], timeout=660)
        except subprocess.TimeoutExpired:
            timed_out = True
        evidence = destination / 'case.json'
        result = json.loads(evidence.read_text()) if not timed_out and completed.returncode == 0 and evidence.exists() else {'source': str(source), 'status': 'failed', 'error': 'Corpus worker timed out.' if timed_out else 'Corpus worker failed.'}
        expected = source.stem in args.expected_rejections
        result['accepted'] = result['status'] == ('rejected' if expected else 'passed') and result.get('source_unchanged', False)
        cases.append(result)
        (args.output / 'summary.json').write_text(json.dumps({'cases': cases}, indent=2), encoding='utf-8')
        print(source.name, result['status'], f"{result.get('elapsed_seconds', 0):.2f}s", flush=True)
    comparison = subprocess.run([str(args.blender), '--background', '--factory-startup', '--python-exit-code', '1',
        '--python', str(Path(__file__).with_name('compare.py')), '--', str(args.output)], capture_output=True, text=True, timeout=600)
    (args.output / 'comparison.log').write_text(comparison.stdout + comparison.stderr)
    environment = {**os.environ, 'NODE_PATH': str(args.validator_node_path.resolve())}
    validation = subprocess.run(['node', str(ROOT / 'external_code/mesh_optimizer/validation/conformance.cjs'), str(args.output)], env=environment, capture_output=True, text=True, timeout=180)
    (args.output / 'conformance.log').write_text(validation.stdout + validation.stderr)
    summary = {'ratio': args.ratio, 'max_relative_error': args.relative_error, 'cases': cases,
               'comparison_passed': comparison.returncode == 0, 'conformance_passed': validation.returncode == 0,
               'accepted': all(case['accepted'] for case in cases) and comparison.returncode == 0 and validation.returncode == 0,
               'scope': 'CPU geometry, attributes, conformance and resources; visual appearance and installed-session acceptance require separate review.'}
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(f"Acceptance: {summary['accepted']}; comparison: {summary['comparison_passed']}; conformance: {summary['conformance_passed']}")
    if not summary['accepted']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
