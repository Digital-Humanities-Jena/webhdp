"""Compare every CPU ladder level using the shared Blender fidelity checks."""
import json
from pathlib import Path
import runpy
import sys

shared = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'mesh_optimizer/validation/compare.py'))
root = Path(sys.argv[sys.argv.index('--') + 1])
checks = []
for case_path in sorted(root.glob('case-*/case.json')):
    case = json.loads(case_path.read_text())
    if case['status'] != 'passed':
        continue
    for level in ('high', 'medium', 'low'):
        try:
            comparison = shared['compare'](Path(case['source']), Path(case['response']['outputs']['lod_' + level]))
            checks.append({'level': level, **comparison})
        except Exception as exc:
            checks.append({'source': case['source'], 'level': level, 'error': str(exc)})
(root / 'comparison.json').write_text(json.dumps(checks, indent=2))
if not checks or any('error' in check for check in checks):
    raise SystemExit(1)
