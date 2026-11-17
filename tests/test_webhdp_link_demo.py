"""Private live settings and local prototype serving boundaries (no real keys)."""
import functools
from copy import deepcopy
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import stat
import threading
from types import SimpleNamespace

import pytest
import requests

from scripts import run_webhdp_link_demo as demo


@pytest.fixture
def static_server(tmp_path):
    samples = tmp_path / "samples"
    samples.mkdir()
    (samples / "public.jpg").write_bytes(b"intended sample")
    private = tmp_path / "private.json"
    private.write_text('{"secret":"private-canary"}')
    (samples / "escape.jpg").symlink_to(private)
    configuration = {"app": "photo-lab", "base_url": "http://127.0.0.1:5100/api/v1/link",
        "client_id": "photo-lab-draco", "pipeline_id": "link-photogrammetry",
        "samples": [{"name": name, "url": "/fixtures/" + name} for name in ["public.jpg", "escape.jpg"]],
        "_sample_directory": str(samples), "_private": "private-canary"}
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(demo.PrototypeHandler, configuration=configuration))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_public_config_excludes_private_operator_fields(static_server):
    response = requests.get(static_server + "/config.json", timeout=3)
    assert response.status_code == 200
    config = response.json()
    assert config["pipeline_id"] == "link-photogrammetry"
    assert "_sample_directory" not in config and "_private" not in config
    assert "private-canary" not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_only_allowlisted_samples_are_served_and_symlink_escape_is_denied(static_server):
    response = requests.get(static_server + "/fixtures/public.jpg", timeout=3)
    assert response.status_code == 200 and response.content == b"intended sample"
    for path in ["/fixtures/unknown.jpg", "/fixtures/escape.jpg", "/fixtures/%2e%2e/private.json"]:
        response = requests.get(static_server + path, timeout=3)
        assert response.status_code == 404
        assert "private-canary" not in response.text


def settings(tmp_path, endpoint="http://127.0.0.1:8000"):
    hpc_file = tmp_path / "gateway.json"
    hpc_file.write_text(json.dumps(["HPC_LINK_BASE_URL=" + endpoint, "HPC_LINK_API_KEY=gateway-test-key",
                                    "ZENODO_SANDBOX_API_KEY=must-not-enter-environment", "UNRELATED_SECRET=not-allowed"]))
    live_file = tmp_path / "live-settings.json"
    live_file.write_text(json.dumps({"hpc_environment_file": str(hpc_file)}))
    account = tmp_path / "account.json"
    account.write_text(json.dumps({"email": "operator@example.test", "password": "existing-test-password"}))
    return SimpleNamespace(state_dir=str(tmp_path / "state"), live_validation=True, live_config_file=str(live_file),
                           credentials_file=str(account), api_port=5100, frontend_port=5173)


def test_live_environment_loads_only_hpc_fields_and_keeps_sandbox_secret_out(monkeypatch, tmp_path):
    monkeypatch.setattr(demo.os, "environ", {})
    args = settings(tmp_path)
    state = demo.configure(args)
    assert demo.os.environ["HPC_LINK_API_KEY"] == "gateway-test-key"
    assert demo.os.environ["HPC_LINK_DEFAULT_DURATION_MINUTES"] == "720"
    assert demo.os.environ["ZENODO_SANDBOX_API_KEY"] == ""
    assert "UNRELATED_SECRET" not in demo.os.environ
    assert demo.os.environ["ZENODO_PUBLISH_ENABLED"] == "false"
    assert stat.S_IMODE((state / "local-secrets.json").stat().st_mode) == 0o600
    persisted = (state / "local-secrets.json").read_text()
    assert "gateway-test-key" not in persisted and "existing-test-password" not in persisted


def test_resume_requires_state_before_creating_secrets_or_directories(monkeypatch, tmp_path):
    monkeypatch.setattr(demo.os, 'environ', {})
    args = settings(tmp_path)
    args.resume_existing = True
    with pytest.raises(SystemExit, match='existing database and local secrets'):
        demo.configure(args)
    assert not Path(args.state_dir).exists() and not demo.os.environ


@pytest.mark.parametrize("endpoint", ["https://gateway.example.test", "http://127.0.0.1.evil.test:8000", "http://192.0.2.10:8000"])
def test_live_launcher_rejects_non_loopback_gateway(monkeypatch, tmp_path, endpoint):
    monkeypatch.setattr(demo.os, "environ", {})
    with pytest.raises(SystemExit, match="isolated loopback"):
        demo.configure(settings(tmp_path, endpoint))
    assert not demo.os.environ


@pytest.fixture
def client_registry():
    from flask import Flask
    from database.database import db
    from database.webhdp_link_models import LinkClient
    from external_code.webhdp_link_photogrammetry.seed import seed
    from services.native_pipeline_system import NativePipelineSystemService
    from services import webhdp_link_service as link

    app = Flask(__name__)
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite://', SQLALCHEMY_TRACK_MODIFICATIONS=False,
                      WEBHDP_DEPLOYMENT_MODE='local', WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=True)
    db.init_app(app)
    app.native_pipeline_service = NativePipelineSystemService()
    with app.test_request_context('/'):
        db.create_all()
        publication = seed(app.native_pipeline_service, runtime_python='/operator/science/python',
            runtime_colmap='/operator/science/colmap', remote_component_root='/operator/component',
            colmap_sha256='a' * 64, reprojector_source_sha256='b' * 64)[0]
        link.save_publication(publication)
        other = deepcopy(publication)
        other['id'] = 'second-reviewed-policy'
        link.save_publication(other)
        requested = {'id': 'photo-app', 'name': 'Photo app', 'enabled': True,
                     'origins': ['http://127.0.0.1:5191', 'http://127.0.0.1:5194'],
                     'redirect_uris': ['http://127.0.0.1:5191/photo-lab/', 'http://127.0.0.1:5194/callback'],
                     'pipeline_ids': [publication['id'], other['id']], 'max_queued_runs': 20,
                     'max_concurrent_runs': 1, 'max_upload_bytes': 104857600, 'max_storage_bytes': 1073741824}
        yield SimpleNamespace(db=db, model=LinkClient, link=link, requested=requested)
        db.session.remove()
        db.drop_all()


def test_live_client_restart_preserves_admin_name_disabled_state_and_quotas(client_registry):
    registry = client_registry
    row = demo.register_clients([registry.requested], live_validation=True)[0]
    registry.link.save_client({'name': 'Temporarily paused by operator', 'enabled': False,
        'max_queued_runs': 8, 'max_concurrent_runs': 2, 'max_upload_bytes': 123456,
        'max_storage_bytes': 456789}, existing=row)
    saved_config = row.config_json
    requested = deepcopy(registry.requested)
    for field in ('origins', 'redirect_uris', 'pipeline_ids'):
        requested[field] = list(reversed(requested[field])) + requested[field][:1]
    result = demo.register_clients([requested], live_validation=True)[0]
    assert result.id == row.id and registry.model.query.count() == 1
    assert result.enabled is False and result.name == 'Temporarily paused by operator'
    assert result.config_json == saved_config
    assert registry.link.client_config(result)['max_upload_bytes'] == 123456


def test_resume_does_not_create_any_missing_client(client_registry):
    registry = client_registry
    row = demo.register_clients([registry.requested])[0]
    original = row.config_json
    other = deepcopy(registry.requested); other['id'] = 'missing-client'
    with pytest.raises(ValueError, match='no clients were created'):
        demo.register_clients([registry.requested, other], live_validation=True, require_existing=True)
    assert registry.model.query.count() == 1 and row.config_json == original
    assert demo.register_clients([registry.requested], live_validation=True, require_existing=True)[0].id == row.id
    changed = deepcopy(registry.requested)
    changed['redirect_uris'] = ['http://127.0.0.1:5191/changed']
    with pytest.raises(ValueError, match='redirect_uris'):
        demo.register_clients([changed], require_existing=True)


@pytest.mark.parametrize('field', ['origins', 'redirect_uris', 'pipeline_ids'])
def test_live_client_drift_fails_without_creating_other_clients_or_revealing_values(client_registry, field, capsys):
    registry = client_registry
    row = demo.register_clients([registry.requested], live_validation=True)[0]
    original = row.config_json
    requested = deepcopy(registry.requested)
    sensitive = 'sensitive-operator-setting-marker'
    requested[field] = [sensitive]
    new = deepcopy(registry.requested)
    new['id'] = 'new-client-before-conflict'
    with pytest.raises(ValueError) as error:
        demo.register_clients([new, requested], live_validation=True)
    message = str(error.value)
    assert "client 'photo-app'" in message and field in message
    assert 'new client identifier' in message and sensitive not in message
    assert sensitive not in ''.join(capsys.readouterr())
    assert row.config_json == original and registry.model.query.count() == 1


def test_live_client_extra_grants_and_changed_exact_callback_are_drift(client_registry):
    registry = client_registry
    row = demo.register_clients([registry.requested], live_validation=True)[0]
    registry.link.save_client({'origins': [*registry.requested['origins'], 'https://additional.example.test'],
                              'redirect_uris': [*registry.requested['redirect_uris'], 'https://additional.example.test/callback']}, existing=row)
    with pytest.raises(ValueError, match='origins, redirect_uris'):
        demo.register_clients([registry.requested], live_validation=True)
    registry.link.save_client({'origins': registry.requested['origins'],
                              'redirect_uris': [uri.rstrip('/') for uri in registry.requested['redirect_uris']]}, existing=row)
    with pytest.raises(ValueError, match='redirect_uris'):
        demo.register_clients([registry.requested], live_validation=True)


def test_nonlive_client_registration_keeps_prior_skip_behavior(client_registry):
    registry = client_registry
    row = demo.register_clients([registry.requested])[0]
    original = row.config_json
    changed = deepcopy(registry.requested)
    changed['pipeline_ids'] = [registry.requested['pipeline_ids'][1]]
    assert demo.register_clients([changed], live_validation=False)[0].id == row.id
    assert row.config_json == original and registry.model.query.count() == 1


def test_explicit_new_client_id_supports_intentional_contract_change(client_registry):
    registry = client_registry
    old = demo.register_clients([registry.requested], live_validation=True)[0]
    original = old.config_json
    changed = deepcopy(registry.requested)
    changed['id'] = 'photo-app-new-policy'
    changed['pipeline_ids'] = [registry.requested['pipeline_ids'][1]]
    new = demo.register_clients([changed], live_validation=True)[0]
    assert new.id == 'photo-app-new-policy' and registry.model.query.count() == 2
    assert registry.link.client_config(new)['pipeline_ids'] == changed['pipeline_ids']
    assert old.config_json == original
