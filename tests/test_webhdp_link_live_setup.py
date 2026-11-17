"""Operator setup preserves published policy and never returns credentials."""

from copy import deepcopy
import json
from types import SimpleNamespace

from flask import Flask
import pytest

from database.database import db
from database.webhdp_link_models import LinkPublication
from external_code.webhdp_link_photogrammetry.seed import seed
from scripts import webhdp_link_live_setup as setup
from services.native_pipeline_system import NativePipelineSystemService
from services import webhdp_link_service as link


@pytest.fixture
def system():
    app = Flask(__name__)
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite://', SQLALCHEMY_TRACK_MODIFICATIONS=False,
                      WEBHDP_DEPLOYMENT_MODE='local', WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=True)
    db.init_app(app)
    app.native_pipeline_service = NativePipelineSystemService()
    with app.test_request_context('/'):
        db.create_all()
        publication = seed(app.native_pipeline_service, runtime_python='/operator/science/bin/python',
            runtime_colmap='/operator/science/bin/colmap', remote_component_root='/operator/component',
            colmap_sha256='a' * 64, reprojector_source_sha256='b' * 64, partition='gpu', gpu_type='a100')[0]
        yield app, publication
        db.session.remove()
        db.drop_all()


def test_unchanged_setup_is_idempotent_and_preserves_administrator_edits(system):
    _, publication = system
    original = deepcopy(publication)
    first = setup._publish(publication)[0]
    row = db.session.get(LinkPublication, publication['id'])
    original_config = row.config_json
    link.save_publication({'enabled': False, 'name': 'Paused for maintenance', 'description': 'Operator-maintained notice'}, existing=row)
    repeated = setup._publish(publication)[0]
    assert LinkPublication.query.count() == 1
    assert row.config_json == original_config
    assert repeated['enabled'] is False and repeated['name'] == 'Paused for maintenance'
    assert repeated['description'] == 'Operator-maintained notice'
    assert repeated['hpc'] == first['hpc']
    assert publication == original  # Normalization cannot alter future seed calls.


def test_equivalent_inherited_schema_and_hpc_defaults_do_not_create_false_drift(system):
    _, publication = system
    publication['hpc'] = {'enabled': True, 'partition': 'gpu'}
    publication.pop('step_timeout_seconds')
    parameter = publication['parameters']['max_image_size']
    for name in ('type', 'minimum', 'maximum', 'default'):
        parameter.pop(name)
    setup._publish(publication)
    explicit = deepcopy(publication)
    explicit['hpc'].update(gpu_count=1, retain_allocation=False, reuse_retained_allocation=False)
    explicit['step_timeout_seconds'] = 3600
    explicit['parameters']['max_image_size'].update(type='integer', minimum=640, maximum=2400, default=960)
    explicit['input']['extensions'].reverse()
    assert setup._publish(explicit)[0]['id'] == publication['id']
    assert LinkPublication.query.count() == 1


@pytest.mark.parametrize(('section', 'field', 'value'), [
    ('hpc', 'partition', 'vis'), ('hpc', 'gpu_type', 'rtx2080'), ('hpc', 'gpu_count', 2),
    ('hpc', 'walltime_hours', 8), ('hpc', 'retain_allocation', False),
    ('hpc', 'reuse_retained_allocation', False), ('hpc', 'gpu_count', True),
    ('input', 'max_files', 12), ('parameters', 'max_image_size', {'step_id': 'reconstruct', 'parameter': 'max_image_size', 'type': 'integer', 'default': 1280}),
    (None, 'pipeline_version', '2.0.0'), (None, 'pipeline_identifier', 'another_pipeline'),
    (None, 'execution_mode', 'record'), (None, 'step_timeout_seconds', 1200),
])
def test_immutable_drift_fails_before_any_batch_publication_is_created(system, section, field, value):
    _, publication = system
    setup._publish(publication)
    original_config = db.session.get(LinkPublication, publication['id']).config_json
    changed = deepcopy(publication)
    (changed[section] if section else changed)[field] = value
    new = deepcopy(publication)
    new['id'] = 'would-have-been-created-first'
    with pytest.raises(ValueError, match='different immutable configuration') as error:
        setup._publish([new, changed])
    assert 'new publication identifier' in str(error.value)
    assert (section or field) in str(error.value)
    assert LinkPublication.query.count() == 1
    assert db.session.get(LinkPublication, publication['id']).config_json == original_config


def test_changed_policy_can_be_published_under_an_explicit_new_identifier(system):
    _, publication = system
    setup._publish(publication)
    changed = deepcopy(publication)
    changed['id'] = 'link-photogrammetry-vis'
    changed['hpc'].update(partition='vis', gpu_type='rtx2080')
    result = setup._publish(changed)[0]
    assert result['hpc']['partition'] == 'vis'
    assert link.serialize_publication(db.session.get(LinkPublication, publication['id']), admin=True)['hpc']['partition'] == 'gpu'


def _setup_dependencies(monkeypatch, app, publication, tmp_path):
    from external_code.webhdp_link_photogrammetry import seed as photo_module
    from external_code.webhdp_link_zenodo import seed as zenodo_module

    photo = deepcopy(publication)
    other = deepcopy(publication)
    other['id'] = 'link-model-test-draft'
    monkeypatch.setattr(photo_module, 'seed', lambda *_args, **_kwargs: [deepcopy(photo)])
    monkeypatch.setattr(zenodo_module, 'seed', lambda *_args, **_kwargs: deepcopy(other))
    calls = []
    app.hpc_allocation_service = SimpleNamespace(update_config=lambda config: calls.append(('hpc', config)),
                                                validate_config=lambda: {'last_validation_status': 'valid'})
    monkeypatch.setenv('HPC_LINK_BASE_URL', 'http://127.0.0.1:8011')
    samples = tmp_path / 'samples'
    samples.mkdir()
    for number in range(3):
        (samples / f'photo-{number}.jpg').write_bytes(b'dataset enumeration fixture')
    settings = {'photogrammetry': {'partition': 'gpu', 'gpu_type': 'a100'},
                'photo_sample_directory': str(samples), 'zenodo_environment_file': str(tmp_path / 'private.json')}
    return photo, calls, settings


def test_setup_policy_drift_precedes_hpc_or_credential_updates_and_redacts_values(system, monkeypatch, tmp_path, capsys):
    app, publication = system
    setup._publish(publication)
    photo, calls, settings = _setup_dependencies(monkeypatch, app, publication, tmp_path)
    sensitive = 'private-runtime-reference-and-credential-marker'
    photo['hpc']['gpu_type'] = sensitive
    monkeypatch.setattr(setup, '_sandbox_credential', lambda *_args: calls.append(('credential',)))
    with pytest.raises(ValueError) as error:
        setup.prepare_live_validation(app, SimpleNamespace(id=1), settings)
    assert calls == []
    assert sensitive not in str(error.value) and 'hpc' in str(error.value)
    assert sensitive not in ''.join(capsys.readouterr())


def test_explicit_photo_ids_and_credentials_stay_out_of_client_configuration(system, monkeypatch, tmp_path, capsys):
    app, publication = system
    _, calls, settings = _setup_dependencies(monkeypatch, app, publication, tmp_path)
    settings.update(photo_publication_id='photo-policy-v2', photo_client_id='photo-application-v2')
    secret = 'example-private-sandbox-token-used-only-in-this-test'
    source = tmp_path / 'private.json'
    source.write_text(json.dumps(['UNRELATED=private', 'ZENODO_SANDBOX_API_KEY=' + secret]))
    credential_calls = []
    credential = SimpleNamespace(id=7)
    stored = {'credential': None}
    class Credentials:
        def get_credential(self, *_args):
            return stored['credential']
        def decrypt_value(self, _credential):
            return secret
        def upsert_credential(self, **values):
            credential_calls.append(values)
            stored['credential'] = credential
            return credential
        def set_active_credential(self, **values):
            assert values == {'user_id': 123, 'environment': 'sandbox', 'credential_id': 7}
    monkeypatch.setattr(setup, 'ZenodoCredentialService', Credentials)
    first = setup.prepare_live_validation(app, SimpleNamespace(id=123), settings)
    second = setup.prepare_live_validation(app, SimpleNamespace(id=123), settings)
    assert first == second
    assert first['photo-lab']['client_id'] == 'photo-application-v2'
    assert first['photo-lab']['pipeline_id'] == 'photo-policy-v2'
    assert len(credential_calls) == 1 and credential_calls[0]['token'] == secret
    assert len(calls) == 2 and LinkPublication.query.count() == 2
    assert secret not in json.dumps(first) and str(source) not in json.dumps(first)
    assert 'ZENODO_SANDBOX_API_KEY' not in json.dumps(first)
    assert secret not in ''.join(capsys.readouterr())


def _resume_fixture(system, tmp_path, *, photo_id=None, roll=False):
    app, original = system
    photo = deepcopy(original)
    photo['id'] = photo_id or 'link-photogrammetry'
    sandbox = deepcopy(original)
    sandbox['id'] = 'link-model-sandbox-draft'
    publications = [photo, sandbox]
    if roll:
        scan = deepcopy(original)
        scan.update(id='link-hmsm-roll-vis', input={'min_files': 1, 'max_files': 1, 'extensions': ['.png']})
        publications.append(scan)
    setup._publish(publications)
    samples = tmp_path / 'photos'
    samples.mkdir()
    for number in range(3):
        (samples / f'scan-{number}.jpg').write_bytes(b'photo fixture')
    settings = {'photo_sample_directory': str(samples)}
    if photo_id:
        settings.update(photo_publication_id=photo_id, photo_client_id='existing-photo-client')
    if roll:
        settings.update(roll_publication_id='link-hmsm-roll-vis', roll_client_id='roll-studio-vis')
    return app, settings, samples


def test_resume_describes_existing_rows_without_seeds_credentials_network_or_writes(system, monkeypatch, tmp_path):
    from sqlalchemy import event
    from external_code.webhdp_link_photogrammetry import seed as photo_module
    from external_code.webhdp_link_zenodo import seed as zenodo_module

    app, settings, _ = _resume_fixture(system, tmp_path, photo_id='existing-photo-v1', roll=True)
    photo = db.session.get(LinkPublication, 'existing-photo-v1')
    link.save_publication({'enabled': False, 'name': 'Operator pause'}, existing=photo)
    before = {row.id: (row.name, row.enabled, row.config_json) for row in LinkPublication.query.all()}
    def forbidden(*_args, **_kwargs):
        pytest.fail('Read-only resume invoked a mutation or external integration')
    monkeypatch.setattr(photo_module, 'seed', forbidden)
    monkeypatch.setattr(zenodo_module, 'seed', forbidden)
    monkeypatch.setattr(setup, '_sandbox_credential', forbidden)
    monkeypatch.setattr(setup, '_publish', forbidden)
    monkeypatch.setattr(link, 'save_publication', forbidden)
    app.hpc_allocation_service = SimpleNamespace(update_config=forbidden, validate_config=forbidden)
    # No photogrammetry runtime/credential settings exist: they are unnecessary.
    statements = []
    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
    event.listen(db.engine, 'before_cursor_execute', capture)
    try:
        result = setup.describe_existing_live_validation(settings)
    finally:
        event.remove(db.engine, 'before_cursor_execute', capture)
    assert all(statement.lstrip().upper().startswith('SELECT') for statement in statements)
    assert result['photo-lab']['pipeline_id'] == 'existing-photo-v1'
    assert result['photo-lab']['client_id'] == 'existing-photo-client'
    assert result['photo-lab']['sample_names'] == ['scan-0.jpg', 'scan-1.jpg', 'scan-2.jpg']
    assert result['model-depot']['pipeline_id'] == 'link-model-sandbox-draft'
    assert result['roll-studio']['pipeline_id'] == 'link-hmsm-roll-vis'
    assert result['roll-studio']['client_id'] == 'roll-studio-vis'
    assert before == {row.id: (row.name, row.enabled, row.config_json) for row in LinkPublication.query.all()}
    assert not db.session.new and not db.session.dirty and not db.session.deleted


@pytest.mark.parametrize('missing', ['photo', 'sandbox', 'roll'])
def test_resume_missing_publication_fails_without_creating_anything(system, tmp_path, missing):
    _, settings, _ = _resume_fixture(system, tmp_path)
    if missing == 'photo':
        settings['photo_publication_id'] = 'missing-photo'
    elif missing == 'roll':
        settings['roll_publication_id'] = 'missing-roll'
    else:
        row = db.session.get(LinkPublication, 'link-model-sandbox-draft')
        db.session.delete(row); db.session.commit()
    count = LinkPublication.query.count()
    with pytest.raises(ValueError, match='resume never creates'):
        setup.describe_existing_live_validation(settings)
    assert LinkPublication.query.count() == count


@pytest.mark.parametrize('count', [2, 31])
def test_resume_sample_count_uses_persisted_contract(system, tmp_path, count):
    _, settings, samples = _resume_fixture(system, tmp_path)
    for path in samples.iterdir():
        path.unlink()
    for number in range(count):
        (samples / f'photo-{number}.jpg').write_bytes(b'photo')
    with pytest.raises(ValueError, match='published file contract'):
        setup.describe_existing_live_validation(settings)


def test_resume_rejects_sample_extension_outside_persisted_contract(system, tmp_path):
    _, original = system
    publication = deepcopy(original)
    publication.update(id='link-photogrammetry', input={'min_files': 3, 'max_files': 30, 'extensions': ['.png']})
    sandbox = deepcopy(publication); sandbox['id'] = 'link-model-sandbox-draft'
    setup._publish([publication, sandbox])
    samples = tmp_path / 'photos'; samples.mkdir()
    for number in range(3):
        (samples / f'photo-{number}.jpg').write_bytes(b'photo')
    with pytest.raises(ValueError, match='published file contract'):
        setup.describe_existing_live_validation({'photo_sample_directory': str(samples)})


def test_resume_rejects_unavailable_dataset_without_private_path_diagnostic(system, tmp_path):
    _, settings, _ = _resume_fixture(system, tmp_path)
    private = str(tmp_path / 'private-missing-dataset')
    settings['photo_sample_directory'] = private
    with pytest.raises(ValueError, match='dataset is unavailable') as failure:
        setup.describe_existing_live_validation(settings)
    assert private not in str(failure.value)


def test_resume_never_autoflushes_pending_application_changes(system, tmp_path):
    _, settings, _ = _resume_fixture(system, tmp_path)
    row = db.session.get(LinkPublication, 'link-photogrammetry')
    row.name = 'Uncommitted application edit'
    with pytest.raises(ValueError, match='clean database session'):
        setup.describe_existing_live_validation(settings)
    assert row in db.session.dirty
    db.session.rollback()
    assert db.session.get(LinkPublication, row.id).name != 'Uncommitted application edit'


def test_fresh_prepare_adds_only_existing_optional_roll_descriptor(system, monkeypatch, tmp_path):
    app, publication = system
    _, calls, settings = _setup_dependencies(monkeypatch, app, publication, tmp_path)
    roll = deepcopy(publication)
    roll.update(id='central-roll-v1', input={'min_files': 1, 'max_files': 1, 'extensions': ['.png']})
    setup._publish(roll)
    settings.update(roll_publication_id=roll['id'], roll_client_id='reviewed-roll-client')
    monkeypatch.setattr(setup, '_sandbox_credential', lambda *_args: None)
    result = setup.prepare_live_validation(app, SimpleNamespace(id=1), settings)
    assert result['roll-studio']['pipeline_id'] == 'central-roll-v1'
    assert result['roll-studio']['client_id'] == 'reviewed-roll-client'
    settings['roll_publication_id'] = 'not-created-on-prepare'
    before = len(calls)
    with pytest.raises(ValueError, match='resume never creates'):
        setup.prepare_live_validation(app, SimpleNamespace(id=1), settings)
    assert len(calls) == before
    assert db.session.get(LinkPublication, 'not-created-on-prepare') is None
