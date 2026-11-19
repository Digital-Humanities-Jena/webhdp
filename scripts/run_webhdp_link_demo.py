#!/usr/bin/env python3
"""Run one isolated real WebHDP API, a durable worker, and three local Link apps.

Uses the normal WebHDP application and native pipeline engine. No mocked API or
computation. Remote processing is enabled only by the explicit live-validation
mode and its private operator configuration. Zenodo publication stays disabled.
"""
from __future__ import annotations

import argparse
import functools
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / 'examples' / 'webhdp-link'
sys.path.insert(0, str(ROOT))


def configure(args):
    state = Path(args.state_dir).resolve()
    if getattr(args, 'resume_existing', False):
        if not all((state / filename).is_file() for filename in ('webhdp.sqlite', 'local-secrets.json')):
            raise SystemExit('--resume-existing requires the existing database and local secrets; no state was created.')
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    secret_file = state / 'local-secrets.json'
    if not secret_file.exists():
        fd = os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump({'SECRET_KEY': secrets.token_hex(32), 'CREDENTIAL_ENCRYPTION_KEY': secrets.token_hex(32)}, stream)
    local_secrets = json.loads(secret_file.read_text())
    env = {
        **local_secrets, 'FLASK_ENV': 'development', 'DATABASE_URL': f'sqlite:///{state}/webhdp.sqlite',
        'SHARED_SESSION_PATH': str(state / 'sessions'), 'WEBHDP_SESSIONS_PATH': str(state / 'sessions'),
        'WEBHDP_LINK_STORAGE_PATH': str(state / 'link-data'), 'WEBHDP_LINK_ROOT': str(state / 'link-data'),
        'WEBHDP_LINK_PUBLIC_BASE_URL': f'http://127.0.0.1:{args.api_port}',
        'FRONTEND_URL': f'http://127.0.0.1:{args.frontend_port}',
        'PUBLIC_BASE_URL': f'http://127.0.0.1:{args.frontend_port}',
        'CORS_ORIGINS': f'http://127.0.0.1:{args.frontend_port}',
        'WEBHDP_INLINE_TASKS': 'true', 'WEBHDP_DEPLOYMENT_MODE': 'local',
        'WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS': 'true', 'STORAGE_MODE': 'server_only',
        'ZENODO_PUBLISH_ENABLED': 'false', 'ENABLE_RENDERER': 'false', 'ENABLE_USDZ_CONVERSION': 'false',
        'ENABLE_LOCAL_EDM_VALIDATION': 'false', 'ENABLE_METIS_VALIDATION': 'false',
        'SESSION_ARTIFACT_CLEANUP_ENABLED': 'false', 'MAIL_SUPPRESS_SEND': 'true',
        'HPC_LINK_BASE_URL': '', 'HPC_LINK_API_KEY': '',
        'ZENODO_API_KEY': '', 'ZENODO_SANDBOX_API_KEY': '',
        'LOCAL_INPUT_PATH': str(state / 'input'), 'LOCAL_OUTPUT_PATH': str(state / 'output'),
        'MAINTENANCE_FLAG_PATH': str(state / 'maintenance.json'),
    }
    if args.live_validation:
        if not args.live_config_file:
            raise SystemExit('--live-validation requires --live-config-file with trusted operator settings.')
        settings = json.loads(Path(args.live_config_file).resolve().read_text())
        hpc_environment_path = Path(settings['hpc_environment_file']).expanduser().resolve()
        if hpc_environment_path.suffix == '.json':
            hpc_environment = json.loads(hpc_environment_path.read_text())
            if isinstance(hpc_environment, list):
                hpc_environment = dict(item.split('=', 1) for item in hpc_environment if '=' in item)
        else:
            from dotenv import dotenv_values
            hpc_environment = dotenv_values(hpc_environment_path)
        allowed = {
            'HPC_LINK_BASE_URL', 'HPC_LINK_USERNAME', 'HPC_LINK_PASSWORD', 'HPC_LINK_API_KEY',
            'HPC_LINK_DEFAULT_PARTITION', 'HPC_LINK_DEFAULT_GPU_TYPE', 'HPC_LINK_DEFAULT_GPU_COUNT',
            'HPC_LINK_PARTITION_SEQUENCE', 'HPC_LINK_PARTITION_ATTEMPT_TIMEOUT_SECONDS',
            'WEBHDP_LINK_HPC_WAIT_SECONDS',
        }
        env.update({key: str(value) for key, value in hpc_environment.items() if key in allowed and value is not None})
        endpoint = urlsplit(env['HPC_LINK_BASE_URL'])
        if endpoint.scheme != 'http' or endpoint.hostname not in {'localhost', '127.0.0.1'}:
            raise SystemExit('Live validation expects an isolated loopback HPC-Link service.')
        env['HPC_LINK_DEFAULT_DURATION_MINUTES'] = '720'
        queue_wait = settings.get('queue_wait_seconds', 14400)
        if type(queue_wait) is not int or not 300 <= queue_wait <= 604800:
            raise SystemExit('queue_wait_seconds must be between300 and604800 seconds.')
        env['HPC_LINK_PARTITION_ATTEMPT_TIMEOUT_SECONDS'] = str(queue_wait)
        env['WEBHDP_LINK_HPC_WAIT_SECONDS'] = str(queue_wait)
        args.live_settings = settings
    credentials = Path(args.credentials_file).resolve() if args.credentials_file else None
    if credentials and credentials.exists():
        account = json.loads(credentials.read_text())
        env.update(DEFAULT_ADMIN_EMAIL=account['email'], DEFAULT_ADMIN_PASSWORD=account['password'])
    if not env.get('DEFAULT_ADMIN_EMAIL') and not os.environ.get('DEFAULT_ADMIN_EMAIL'):
        raise SystemExit('Supply --credentials-file with an existing development account, or DEFAULT_ADMIN_EMAIL and DEFAULT_ADMIN_PASSWORD in the environment.')
    os.environ.update(env)
    return state


class PrototypeHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, configuration, **kwargs):
        self.configuration = configuration
        super().__init__(*args, directory=str(EXAMPLES), **kwargs)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/config.json':
            data = json.dumps({key: value for key, value in self.configuration.items() if not key.startswith('_')}).encode()
            self.send_response(200); self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store'); self.send_header('Content-Length', str(len(data)))
            self.end_headers(); self.wfile.write(data); return
        if path == '/sdk/client.mjs':
            self.send_file(ROOT / 'sdk/webhdp-link/client.mjs', 'text/javascript'); return
        if path.startswith('/fixtures/'):
            name = Path(path).name
            allowed = {sample['name'] for sample in self.configuration['samples']}
            if name not in allowed:
                self.send_error(404); return
            directory = Path(self.configuration.get('_sample_directory') or ROOT / 'external_code/webhdp_link_examples/fixtures').resolve()
            source = (directory / name).resolve()
            if source.parent != directory:
                self.send_error(404); return
            self.send_file(source, self.guess_type(name)); return
        if path == '/':
            self.send_response(302); self.send_header('Location', f"/{self.configuration['app']}/"); self.end_headers(); return
        super().do_GET()

    def send_file(self, path, media_type):
        if not path.is_file():
            self.send_error(404); return
        data = path.read_bytes(); self.send_response(200)
        self.send_header('Content-Type', media_type); self.send_header('Content-Length', str(len(data)))
        self.end_headers(); self.wfile.write(data)

    def end_headers(self):
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', f"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob:; connect-src 'self' {self.configuration['base_url'].split('/api/')[0]}; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        super().end_headers()

    def log_message(self, *_args):
        pass  # OAuth query strings must not be logged by the static server.


def register_clients(clients, *, live_validation=False, require_existing=False):
    """Preserve administrator edits and reject unexpected live OAuth contracts."""
    from database.database import db
    from database.webhdp_link_models import LinkClient
    from services import webhdp_link_service as link_service

    existing = {client['id']: db.session.get(LinkClient, client['id']) for client in clients}
    if require_existing and any(row is None for row in existing.values()):
        raise ValueError('Resume requires every prototype client to be registered already; no clients were created.')
    if live_validation or require_existing:
        for client in clients:
            registered = existing[client['id']]
            if registered is None:
                continue
            config = link_service.client_config(registered)
            # These are allowlists: order and duplicate entries do not change
            # access, while redirect URLs themselves must remain exact matches.
            changed = [field for field in ('origins', 'redirect_uris', 'pipeline_ids')
                       if set(config.get(field, [])) != set(client.get(field, []))]
            if changed:
                raise ValueError(
                    f"Existing Link client '{client['id']}' has a different live application configuration "
                    f"({', '.join(changed)}). Use a new client identifier for the intended application "
                    "contract; existing clients are not overwritten."
                )
    # Preflight the entire live batch before creating anything. Existing names,
    # enabled flags and quotas are administrator decisions in both modes.
    return [existing[client['id']] or link_service.save_client(client) for client in clients]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir')
    parser.add_argument('--credentials-file', help='Private JSON file for an isolated development account')
    parser.add_argument('--api-port', type=int, default=5100)
    parser.add_argument('--frontend-port', type=int, default=5173)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--no-frontend', action='store_true')
    parser.add_argument('--live-validation', action='store_true', help='Enable the configured Draco and unpublished Zenodo sandbox validation pipelines.')
    parser.add_argument('--live-config-file', help='Private operator settings; never served to the prototype applications.')
    parser.add_argument('--resume-existing', action='store_true', help='Use persisted registrations and credentials without seeding or changing accounts, components, pipelines or resource configuration.')
    args = parser.parse_args()
    args.state_dir = args.state_dir or str(ROOT / 'instance' / ('link-live-validation' if args.live_validation else 'link-demo'))
    os.chdir(ROOT)
    state = configure(args)
    if args.resume_existing:
        os.environ['SKIP_DB_CREATE_ALL'] = 'true'
        os.environ['ENABLE_FLASK_SESSION_CLEANUP'] = 'false'
    from app import app
    from services import webhdp_link_service as link_service
    # These settings also work in production when set in the application config.
    app.config.update(WEBHDP_LINK_PUBLIC_BASE_URL=os.environ['WEBHDP_LINK_PUBLIC_BASE_URL'],
                      WEBHDP_LINK_STORAGE_PATH=os.environ['WEBHDP_LINK_STORAGE_PATH'],
                      WEBHDP_LINK_ROOT=os.environ['WEBHDP_LINK_ROOT'])
    if args.worker:
        while True:
            with app.app_context():
                result = link_service.process_next()
            if not result:
                time.sleep(0.5)
        return
    from database.database import db
    from database.models import User, UserRole, SystemConfig
    from database.webhdp_link_models import LinkPublication
    from external_code.webhdp_link_examples.seed import seed
    with app.app_context():
        if not args.resume_existing:
            db.create_all()
        # Reuse the development account without changing a production user/database.
        user = User.query.filter_by(email=os.environ['DEFAULT_ADMIN_EMAIL']).first()
        if args.resume_existing and (user is None or not user.is_verified):
            raise SystemExit('Resume requires the existing verified development account.')
        if not args.resume_existing and user is None:
            user = User(email=os.environ['DEFAULT_ADMIN_EMAIL'], role=UserRole.ADMIN, is_verified=True)
            user.set_password(os.environ['DEFAULT_ADMIN_PASSWORD'])
            db.session.add(user)
        if not args.resume_existing:
            user.is_verified = True
            setup = db.session.get(SystemConfig, 'setup_completed')
            if setup is None: db.session.add(SystemConfig(key='setup_completed', value='true'))
            else: setup.value = 'true'
            db.session.commit()
        publications = [] if args.resume_existing else seed(app.native_pipeline_service)
        for publication in publications:
            if db.session.get(LinkPublication, publication['id']) is None:
                link_service.save_publication(publication)
        app_configs, clients = [], []
        by_app = {'photo-lab': (5191, 'link-photo-preparation'), 'roll-studio': (5192, 'link-piano-roll'), 'model-depot': (5193, 'link-model-deposit')}
        app_names = {'photo-lab': 'Reconstruction Testlab', 'roll-studio': 'MMIC-Transformer', 'model-depot': 'Model Depot'}
        samples = {'photo-lab': ['photo-1.jpg', 'photo-2.jpg', 'photo-3.jpg'], 'roll-studio': ['piano-roll.png'], 'model-depot': ['tetrahedron.obj']}
        live_configs = {}
        if args.live_validation:
            from scripts.webhdp_link_live_setup import prepare_live_validation, describe_existing_live_validation
            live_configs = describe_existing_live_validation(args.live_settings) if args.resume_existing else prepare_live_validation(app, user, args.live_settings)
            for name, live_config in live_configs.items():
                by_app[name] = (by_app[name][0], live_config['pipeline_id'])
                samples[name] = live_config.get('sample_names', samples[name])
        for name, (port, publication_id) in by_app.items():
            origin = f'http://127.0.0.1:{port}'
            client_id = live_configs.get(name, {}).get('client_id', name)
            clients.append({'id': client_id, 'name': app_names[name], 'origins': [origin],
                'redirect_uris': [f'{origin}/{name}/'], 'pipeline_ids': [publication_id], 'enabled': True,
                'max_queued_runs': 20, 'max_concurrent_runs': 1, 'max_upload_bytes': 104857600, 'max_storage_bytes': 1073741824})
            app_configs.append({'app': name, 'port': port, 'base_url': os.environ['WEBHDP_LINK_PUBLIC_BASE_URL'] + '/api/v1/link',
                'client_id': client_id, 'pipeline_id': publication_id,
                'samples': [{'name': filename, 'url': f'/fixtures/{filename}'} for filename in samples[name]]})
            app_configs[-1].update(live_configs.get(name, {}))
        register_clients(clients, live_validation=args.live_validation, require_existing=args.resume_existing)
    children, servers, handles = [], [], []
    try:
        worker_log = open(state / 'worker.log', 'a')
        handles.append(worker_log)
        worker_command = [sys.executable, __file__, '--worker', '--state-dir', str(state), '--api-port', str(args.api_port), '--frontend-port', str(args.frontend_port)]
        worker_command += ['--credentials-file', args.credentials_file or '']
        if args.live_validation:
            worker_command += ['--live-validation', '--live-config-file', str(Path(args.live_config_file).resolve())]
        if args.resume_existing:
            worker_command += ['--resume-existing']
        children.append(subprocess.Popen(worker_command, stdout=worker_log, stderr=subprocess.STDOUT))
        if not args.no_frontend:
            frontend_log = open(state / 'frontend.log', 'a'); handles.append(frontend_log)
            frontend_environment = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR', 'TEMP', 'TMP', 'SHELL', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TERM') if key in os.environ}
            frontend_environment['VITE_API_URL'] = f'http://127.0.0.1:{args.api_port}'
            children.append(subprocess.Popen(['npm', 'run', 'dev', '--', '--host', '127.0.0.1', '--port', str(args.frontend_port), '--strictPort'], cwd=ROOT / 'frontend', env=frontend_environment, stdout=frontend_log, stderr=subprocess.STDOUT, start_new_session=True))
        for config in app_configs:
            server = ThreadingHTTPServer(('127.0.0.1', config['port']), functools.partial(PrototypeHandler, configuration=config))
            servers.append(server); threading.Thread(target=server.serve_forever, daemon=True).start()
        from werkzeug.serving import make_server
        server = make_server('127.0.0.1', args.api_port, app, threaded=True)
        servers.append(server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        def stop(*_args):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, stop)
        print('\nWebHDP-Link local demonstration is ready:', flush=True)
        print(f'  Admin: http://127.0.0.1:{args.frontend_port}/admin/webhdp-link', flush=True)
        for config in app_configs:
            print(f"  {config['app']}: http://127.0.0.1:{config['port']}/{config['app']}/", flush=True)
        print('Use the existing development administrator login. Ctrl-C stops the owned services; jobs and outputs persist.', flush=True)
        while True:
            for child in children:
                if child.poll() is not None:
                    raise RuntimeError('A demo child process stopped; inspect the logs in the state directory.')
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for server in servers:
            server.shutdown(); server.server_close()
        for child in children:
            if child.poll() is None:
                if child.args[0] == 'npm': os.killpg(child.pid, signal.SIGTERM)
                else: child.terminate()
                try: child.wait(timeout=10)
                except subprocess.TimeoutExpired: child.kill(); child.wait()
        for handle in handles: handle.close()


if __name__ == '__main__':
    main()
