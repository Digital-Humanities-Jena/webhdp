#!/usr/bin/env python3
"""Measure read-only readiness with the isolated HTTP fixture and unrelated inventory."""
import argparse
import base64
import json
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from io import BytesIO

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from browser_api import create_fixture_app
from database.database import db
from database.models import Session
from services.hdpc_scan_service import create_and_scan_hdpc_project


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--counts', nargs='+', type=int, default=[10, 100, 1000])
    parser.add_argument('--inventory-size', type=int, default=10000)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    measurements = []
    inventory = [{'dataset_key_lower': f'unrelated-{index}', 'session_id': index + 2,
                  'local_record_id': 1, 'is_sandbox': True} for index in range(args.inventory_size)]
    for count in args.counts:
        with TemporaryDirectory(prefix='webhdp-readiness-benchmark-') as directory:
            app = create_fixture_app(directory)
            with app.app_context():
                client = app.test_client()
                fixture = client.post('/__test__/workflow/fixture').json
                headers = {'Authorization': 'Bearer ' + fixture['owner_token']}
                response = client.post('/api/v1/sessions/file', headers=headers,
                    data={'file': (BytesIO(base64.b64decode(fixture['model_base64'])), 'model.glb')})
                assert response.status_code == 200, response.json
                session = db.session.get(Session, response.json['data']['session_id'])
                root = Path(session.session_dir)
                source = root / 'uploads/model.glb'
                paths = [str(source)]
                for index in range(1, count):
                    path = source.with_name(f'model-{index}.glb')
                    path.write_bytes(source.read_bytes())
                    paths.append(str(path))
                create_and_scan_hdpc_project(hdpc_path=session.hdpc_path, data_in_path=str(source.parent),
                    data_out_path=str(root / 'outputs'), project_name='Benchmark', short_code='BENCH',
                    modalities=['3d_model'], scan_options={'extensions': ['.glb'], 'primarysourceext': '.glb'})
                assert client.put(f'/api/v1/metadata/user/{session.id}/draft', headers=headers,
                    json={'title': 'Benchmark source', 'description': 'Benchmark', 'notes': 'Curated', 'creators': [{'name': 'Museum'}]}).status_code == 200
                payload = {'session_id': session.id, 'local_file_paths': paths, 'is_sandbox': True}
                started = time.perf_counter()
                with patch('services.dataset_integrity_service.collect_dataset_records', return_value=(inventory, [])) as collected:
                    response = client.post('/api/v2/pipelines/browser_workflow/readiness?stream=1', headers=headers, json=payload, buffered=False)
                    first_progress = None
                    events = []
                    for chunk in response.response:
                        for line in chunk.decode().splitlines():
                            event = json.loads(line)
                            if event['type'] == 'progress' and first_progress is None:
                                first_progress = time.perf_counter() - started
                            events.append(event)
                    report = events[-1]['report']
                    assert report['ready'], report
                    measurements.append({'selected_sources': count, 'source_bytes': source.stat().st_size,
                        'unrelated_inventory_records': len(inventory), 'inventory_loads': collected.call_count,
                        'first_progress_seconds': round(first_progress, 4), 'elapsed_seconds': round(time.perf_counter() - started, 4),
                        'progress_events': sum(event['type'] == 'progress' for event in events)})
                db.session.remove()
    result = {'measurements': measurements, 'scope': 'Local HTTP readiness with small valid GLBs and synthetic unrelated inventory. Full file hashes are checked; large-file throughput depends on storage.'}
    if args.output:
        args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
