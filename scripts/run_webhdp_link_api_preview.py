#!/usr/bin/env python3
"""Preview the current hosted Link UI against an existing local job database.

This starts one API and one Vue development server, never a worker, seed step,
HPC gateway or prototype server. Only the hosted-job reads and authentication
needed by this preview are exposed; all pipeline/resource mutations are denied.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_webhdp_link_demo import configure


READ_PATHS = {
    '/api/v1/setup/status', '/api/v1/auth/me',
    '/api/v1/notifications', '/api/v1/notifications/',
    '/api/v1/notifications/unread-count', '/api/v1/notifications/client-config',
    '/api/v1/link/jobs', '/api/v1/link/grants', '/api/v1/link/openapi.json',
    '/api/v1/link/discovery',
}
JOB_PATH = re.compile(r'^/api/v1/link/jobs/[a-zA-Z0-9_-]+(?:/artifacts/[a-zA-Z0-9_-]+)?$')
LOGIN_PATH = '/api/v1/auth/login'


class ReadOnlyPreview:
    """Enforce the preview boundary before application request hooks run."""
    def __init__(self, application, frontend_origin):
        self.application = application
        self.frontend_origin = frontend_origin

    def __call__(self, environ, start_response):
        method = environ.get('REQUEST_METHOD', '').upper()
        path = environ.get('PATH_INFO', '')
        read = path in READ_PATHS or JOB_PATH.fullmatch(path)
        allowed = method == 'OPTIONS' or (method in {'GET', 'HEAD'} and read) or (method == 'POST' and path == LOGIN_PATH)
        if allowed:
            return self.application(environ, start_response)
        body = json.dumps({'type':'about:blank', 'title':'Preview operation unavailable', 'status':405,
            'detail':'This temporary preview exposes hosted-job reads and login only.'}).encode()
        headers = [('Content-Type', 'application/problem+json'), ('Content-Length', str(len(body))),
                   ('Cache-Control', 'no-store'), ('Allow', 'GET, HEAD, OPTIONS'), ('Vary', 'Origin')]
        if environ.get('HTTP_ORIGIN') == self.frontend_origin:
            headers.append(('Access-Control-Allow-Origin', self.frontend_origin))
        start_response('405 Method Not Allowed', headers)
        return [] if method == 'HEAD' else [body]


def frontend_environment(api_port):
    allowed = ('PATH', 'HOME', 'TMPDIR', 'TEMP', 'TMP', 'SHELL', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TERM')
    return {**{key:os.environ[key] for key in allowed if key in os.environ},
            'VITE_API_URL': f'http://127.0.0.1:{api_port}'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', required=True)
    parser.add_argument('--live-config-file', required=True)
    parser.add_argument('--credentials-file', required=True, help='Private JSON file for the isolated development account')
    parser.add_argument('--api-port', type=int, default=5101)
    parser.add_argument('--frontend-port', type=int, default=5174)
    args = parser.parse_args()
    state = Path(args.state_dir).resolve()
    for required in (state / 'webhdp.sqlite', state / 'local-secrets.json', Path(args.live_config_file), Path(args.credentials_file)):
        if not required.is_file():
            raise SystemExit('Preview requires the existing database, local secrets, live settings and development credentials.')
    args.live_validation = True
    os.chdir(ROOT)
    configure(args)
    # app.py uses this flag for both metadata bootstrap and native seeding.
    os.environ['SKIP_DB_CREATE_ALL'] = 'true'
    os.environ['ENABLE_FLASK_SESSION_CLEANUP'] = 'false'
    os.environ['SESSION_ARTIFACT_CLEANUP_ENABLED'] = 'false'
    from app import app
    app.config.update(WEBHDP_LINK_PUBLIC_BASE_URL=os.environ['WEBHDP_LINK_PUBLIC_BASE_URL'],
        WEBHDP_LINK_STORAGE_PATH=os.environ['WEBHDP_LINK_STORAGE_PATH'],
        WEBHDP_LINK_ROOT=os.environ['WEBHDP_LINK_ROOT'])
    origin = f'http://127.0.0.1:{args.frontend_port}'
    app.wsgi_app = ReadOnlyPreview(app.wsgi_app, origin)
    from werkzeug.serving import make_server
    server = make_server('127.0.0.1', args.api_port, app, threaded=True)
    frontend = None
    thread = None
    log = None
    try:
        log = (state / 'preview-frontend.log').open('a')
        frontend = subprocess.Popen(['npm', 'run', 'dev', '--', '--host', '127.0.0.1',
            '--port', str(args.frontend_port), '--strictPort'], cwd=ROOT / 'frontend',
            env=frontend_environment(args.api_port), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(json.dumps({'preview_pid':os.getpid(),'frontend_pid':frontend.pid,
            'api_url':f'http://127.0.0.1:{args.api_port}', 'frontend_url':origin,
            'hosted_jobs_url':origin+'/link/jobs', 'worker_started':False}), flush=True)
        while not stop.wait(1):
            if frontend.poll() is not None:
                raise SystemExit('Preview frontend stopped; see preview-frontend.log.')
    finally:
        if thread:
            server.shutdown()
        server.server_close()
        if frontend and frontend.poll() is None:
            os.killpg(frontend.pid, signal.SIGTERM)
            try:
                frontend.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(frontend.pid, signal.SIGKILL)
                frontend.wait()
        if log:
            log.close()


if __name__ == '__main__':
    main()
