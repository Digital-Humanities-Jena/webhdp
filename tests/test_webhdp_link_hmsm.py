"""Central HMSM contracts and immutable scientific installation boundaries."""
import json
from pathlib import Path

import pytest

from external_code.webhdp_link_hmsm import runner, seed


def settings():
    return dict(runtime_python='/opt/hmsm/env/bin/python', remote_component_root='/opt/components/hmsm/1.0.0',
                source_manifest_sha256='a' * 64)


@pytest.mark.parametrize('value', [dict(roll_speed=True), dict(roll_speed=float('nan')),
    dict(roll_speed=.1), dict(roll_speed=31), dict(method=[]), dict(model_id='ariston'),
    dict(polarity='auto'), dict(command='anything'), dict(options_json='/private')])
def test_parameters_cannot_change_execution_or_carrier_scope(value):
    with pytest.raises(ValueError):
        runner.parameters(value, seed.MODELS)


def test_publication_reuses_same_retained_vis_policy_and_bounds_one_scan():
    manifest, pipeline, publication = seed.definitions(**settings())
    assert publication['hpc'] == dict(enabled=True, partition='vis', gpu_type='a5000', gpu_count=1,
        walltime_hours=12, retain_allocation=True, reuse_retained_allocation=True)
    assert publication['input']['min_files'] == publication['input']['max_files'] == 1
    assert set(publication['parameters']) == {'model_id', 'roll_speed', 'method', 'polarity'}
    assert manifest['execution']['profiles'][0]['resources']['gpu_count'] == 0
    assert '--expected-runner-sha256' in manifest['execution']['profiles'][0]['entrypoint']
    assert pipeline['steps'][0]['input_bindings'][0]['type'] == 'pipeline_source_file'
    assert '/opt/' not in json.dumps(publication)


def test_native_registration_accepts_component_pipeline_and_publication():
    from flask import Flask
    from database.database import db
    from services.native_pipeline_system import NativePipelineSystemService
    from services.webhdp_link_service import save_publication
    app = Flask(__name__)
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite://', SQLALCHEMY_TRACK_MODIFICATIONS=False,
                      WEBHDP_DEPLOYMENT_MODE='local', WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=True)
    db.init_app(app)
    app.native_pipeline_service = NativePipelineSystemService()
    with app.test_request_context('/'):
        db.create_all()
        saved = save_publication(seed.seed(app.native_pipeline_service, **settings()))
        assert saved.id == 'link-hmsm-roll-vis'
        db.session.remove(); db.drop_all()


def fixture_source(tmp_path):
    source = tmp_path / 'checkout'
    for name in ['LICENSE', 'requirements.txt', 'backend/__init__.py', 'backend/vendor/HMSM-LICENSE',
                 'docs/ATTRIBUTION.md', 'backend/data/carrier-operational-evidence.json', 'backend/studio/cli.py']:
        file = source / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('')
    (source / 'backend/data/models.json').write_text(json.dumps([
        dict(id=model, media_type='roll', status='available') for model in seed.MODELS]))
    (source / 'private.json').write_text('excluded')
    return source


def installation(tmp_path):
    config = settings(); config.pop('source_manifest_sha256')
    target = tmp_path / 'installation'
    trusted = seed.prepare_installation(target, hmsm_source=fixture_source(tmp_path), **config)
    return target, trusted


def test_frozen_payload_excludes_unrelated_files_and_detects_modifications(tmp_path):
    target, trusted = installation(tmp_path)
    snapshot = runner.source_inventory(target / 'source', trusted['source_manifest_sha256'])
    assert 'private.json' not in snapshot['files']
    assert json.loads((target / 'component.json').read_text())['manifest_sha256'] == runner.sha256(target / 'manifest.json')
    (target / 'source/backend/studio/cli.py').write_text('changed')
    with pytest.raises(ValueError, match='source changed'):
        runner.source_inventory(target / 'source', trusted['source_manifest_sha256'])


def test_frozen_payload_rejects_added_code_and_inventory_replacement(tmp_path):
    target, trusted = installation(tmp_path)
    extra = target / 'source/backend/studio/extra.py'; extra.write_text('')
    with pytest.raises(ValueError, match='Unexpected files'):
        runner.source_inventory(target / 'source', trusted['source_manifest_sha256'])
    extra.unlink(); (target / 'source-manifest.json').write_text('{}')
    with pytest.raises(ValueError, match='inventory changed'):
        runner.source_inventory(target / 'source', trusted['source_manifest_sha256'])


def test_requires_central_allocation_and_rejects_outside_scan_before_execution(tmp_path, monkeypatch):
    target, trusted = installation(tmp_path)
    root = tmp_path / 'inputs'; root.mkdir()
    outside = tmp_path / 'outside.png'; outside.write_bytes(b'image')
    args = dict(source=target / 'source', source_manifest_sha256=trusted['source_manifest_sha256'],
                input_root=root, output_root=tmp_path / 'outputs')
    monkeypatch.delenv('SLURM_JOB_ID', raising=False)
    with pytest.raises(ValueError, match='allocation'):
        runner.execute({}, **args)
    with pytest.raises(ValueError, match='input contract'):
        runner.execute({'inputs': {'input_file': str(outside)}}, require_allocation=False, **args)
