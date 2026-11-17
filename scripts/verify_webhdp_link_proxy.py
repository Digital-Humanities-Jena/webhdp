#!/usr/bin/env python3
"""Check both shipped nginx templates against a running loopback Link demo.
Uses an isolated disposable nginx container; never changes an existing service.
"""
from pathlib import Path
import json
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def request(port, path, origin, method='GET'):
    headers = {'Origin': origin}
    if method == 'OPTIONS':
        headers.update({'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization,content-type,idempotency-key'})
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', headers=headers, method=method)
    try:
        response = urllib.request.urlopen(req, timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, dict(response.headers), response.read()


def main():
    results = []
    for index, name in enumerate(('nginx.conf', 'nginx.hpc.singularity.conf.template')):
        with tempfile.TemporaryDirectory(prefix='webhdp-link-proxy-') as directory:
            config = (ROOT / 'frontend' / name).read_text()
            config = config.replace('${NGINX_CLIENT_MAX_BODY_SIZE}', '50G').replace('${OEMBED_FRAME_ANCESTORS}', "'self'").replace('${FRONTEND_PORT}', '80').replace('${BACKEND_PORT}', '5100')
            # Only upstream addressing changes for the disposable Docker fixture.
            config = config.replace('http://backend:5000', 'http://host.docker.internal:5100').replace('http://127.0.0.1:5100', 'http://host.docker.internal:5100')
            path = Path(directory) / 'default.conf'; path.write_text(config)
            container = 'webhdp-link-proxy-' + uuid4().hex[:10]
            port = 5294 + index
            base = ['docker', 'run', '--rm', '--name', container, '-v', f'{path}:/etc/nginx/conf.d/default.conf:ro', '-v', f'{ROOT / "frontend/dist"}:/usr/share/nginx/html:ro']
            subprocess.run(base + ['nginx:1.29-alpine', 'nginx', '-t'], check=True, capture_output=True)
            subprocess.run(base + ['-d', '-p', f'127.0.0.1:{port}:80', 'nginx:1.29-alpine'], check=True, capture_output=True)
            try:
                for _ in range(30):
                    try:
                        status, headers, _ = request(port, '/api/v1/link/discovery', 'http://127.0.0.1:5191')
                        break
                    except (OSError, urllib.error.URLError):
                        time.sleep(.2)
                else:
                    raise RuntimeError('Temporary proxy failed to start')
                assert status == 200, status
                assert headers.get('Access-Control-Allow-Origin') == 'http://127.0.0.1:5191', headers
                assert 'Access-Control-Allow-Credentials' not in headers
                status, headers, _ = request(port, '/api/v1/link/runs', 'http://127.0.0.1:5191', 'OPTIONS')
                assert status == 204 and 'Idempotency-Key' in headers.get('Access-Control-Allow-Headers', ''), (status, headers)
                status, headers, _ = request(port, '/api/v1/link/runs', 'https://unregistered.example', 'OPTIONS')
                assert status == 403 and 'Access-Control-Allow-Origin' not in headers, (status, headers)
                status, headers, _ = request(port, '/api/v1/link/pipelines', 'http://127.0.0.1:5191')
                assert status == 401 and headers.get('WWW-Authenticate', '').startswith('Bearer'), (status, headers)
                status, headers, _ = request(port, '/link/authorize', 'http://127.0.0.1:5191')
                assert status == 200 and "frame-ancestors 'none'" in headers.get('Content-Security-Policy', ''), (status, headers)
                # Only synthetic markers: a callback request must be logged by
                # path without its authorization code/state or bearer headers.
                status, _, _ = request(port, '/link/authorize?code=private-code-marker&state=private-state-marker', 'http://127.0.0.1:5191')
                assert status == 200, status
                # Docker's log collector can lag the completed HTTP response.
                for _ in range(20):
                    logs = subprocess.run(['docker', 'logs', container], check=True, capture_output=True, text=True)
                    access = logs.stdout + logs.stderr
                    # $uri is the current path: try_files can internally rewrite
                    # the SPA route to /index.html before access logging.
                    if re.search(r'\bGET /(?:link/authorize|index\.html) 200\b', access):
                        break
                    time.sleep(.1)
                assert re.search(r'\bGET /(?:link/authorize|index\.html) 200\b', access), 'Path-only access logging missing'
                assert 'private-code-marker' not in access and 'private-state-marker' not in access, 'OAuth query leaked to access logs'
                results.append({'template': name, 'syntax_valid': True, 'registered_origin_forwarded': True, 'idempotency_preflight_forwarded': True, 'unregistered_origin_rejected': True, 'unauthenticated_rejected': True, 'consent_framing_denied': True, 'oauth_query_excluded_from_access_logs': True})
            finally:
                subprocess.run(['docker', 'stop', container], check=True, capture_output=True)
    print(json.dumps({'success': True, 'live_api': 'loopback', 'results': results}, indent=2))


if __name__ == '__main__':
    main()
