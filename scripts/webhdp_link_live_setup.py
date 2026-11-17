"""Operator-only setup for the isolated Draco and Zenodo sandbox acceptance run.

Settings contain trusted runtime locations and references to existing private
credential files. None of those settings are returned to external applications.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from copy import deepcopy

from database.database import db
from database.webhdp_link_models import LinkPublication
from services import webhdp_link_service as link
from services.zenodo_credential_service import ZenodoCredentialService


def _sandbox_credential(user, environment_file):
    values = json.loads(Path(environment_file).expanduser().resolve().read_text())
    if isinstance(values, list):
        values = dict(item.split('=', 1) for item in values if '=' in item)
    token = str(values.get('ZENODO_SANDBOX_API_KEY') or '').strip()
    if not token:
        raise ValueError('The existing development configuration has no Zenodo sandbox credential.')
    service = ZenodoCredentialService()
    credential = service.get_credential('user', user.id, 'sandbox')
    if credential is None or service.decrypt_value(credential) != token:
        credential = service.upsert_credential(
            owner_type='user', owner_id=user.id, environment='sandbox', token=token,
            actor_user_id=user.id, name='Development Zenodo sandbox',
        )
    service.set_active_credential(user_id=user.id, environment='sandbox', credential_id=credential.id)


def _publication_list(publications):
    return [publications] if isinstance(publications, dict) else list(publications)


def _immutable_contract(publication, native_parameters):
    """Compare effective contracts, including defaults inherited at publication.

    The public service stores normalized schemas (label becomes title, component
    bounds/defaults are inherited). Comparing raw seed dictionaries would reject
    unchanged configurations or miss omitted resource-policy fields. Names,
    descriptions and enabled flags are intentionally left to administrators.
    """
    data = deepcopy(publication)
    parameters = {}
    for name, parameter in (data.get('parameters') or {}).items():
        field = native_parameters.get((parameter.get('step_id'), parameter.get('parameter')), {})
        schema = {key: value for key, value in parameter.items() if key not in {'label'}}
        for key in ('type', 'default', 'enum', 'minimum', 'maximum', 'minLength', 'maxLength'):
            if key not in schema and key in field:
                schema[key] = field[key]
        if parameter.get('label'):
            schema['title'] = parameter['label'].strip()
        parameters[name] = schema
    inputs = {'min_files': 1, 'max_files': 1, **(data.get('input') or {})}
    # Extension order does not change the upload contract.
    inputs['extensions'] = sorted(set(inputs.get('extensions', [])))
    hpc = data.get('hpc') or {}
    if hpc.get('enabled'):
        hpc = {'gpu_count': 1, 'retain_allocation': False, 'reuse_retained_allocation': False, **hpc}
    elif hpc == {'enabled': False}:
        hpc = {}
    return {
        'pipeline_identifier': data.get('pipeline_identifier'), 'pipeline_version': data.get('pipeline_version'),
        'input': inputs, 'parameters': parameters, 'execution_mode': data.get('execution_mode', 'record'),
        'step_timeout_seconds': data.get('step_timeout_seconds', 3600), 'hpc': hpc,
    }


def _check_existing_publications(publications):
    """Read-only preflight; never silently retain an unexpected execution policy."""
    for publication in _publication_list(publications):
        link.object_payload(publication, {'id', 'name', 'description', 'pipeline_identifier', 'pipeline_version',
                                         'enabled', 'input', 'parameters', 'execution_mode', 'step_timeout_seconds', 'hpc'})
        identifier = link.identifier(publication.get('id'))
        existing = db.session.get(LinkPublication, identifier)
        if existing is None:
            continue
        stored = link.serialize_publication(existing, admin=True)
        config = link.loads(existing.config_json)
        native_parameters = {(step['id'], parameter['name']): parameter
                             for step in config['structure'] for parameter in step['parameters']}
        actual = _immutable_contract(stored, native_parameters)
        requested = _immutable_contract(publication, native_parameters)
        # Canonical JSON preserves scalar types (True must not compare equal to
        # one GPU). Do not include config values in diagnostic messages: setup
        # settings can refer to private credentials and runtime locations.
        changed = [key for key in actual if link.dumps(actual[key]) != link.dumps(requested[key])]
        if changed:
            raise ValueError(
                f"Existing Link publication '{identifier}' has a different immutable configuration "
                f"({', '.join(changed)}). Use a new publication identifier and its intended client "
                "configuration; existing publications are not overwritten."
            )


def _publish(publications):
    publications = _publication_list(publications)
    # Check the entire batch before creating any missing publication.
    _check_existing_publications(publications)
    result = []
    for publication in publications:
        existing = db.session.get(LinkPublication, publication['id'])
        row = existing or link.save_publication(deepcopy(publication))
        result.append(link.serialize_publication(row, admin=True))
    return result


def _existing_publication(identifier):
    identifier = link.identifier(identifier)
    row = db.session.get(LinkPublication, identifier)
    if row is None:
        raise ValueError(f"Existing Link publication '{identifier}' is required; resume never creates publications.")
    return link.serialize_publication(row, admin=True)


def _photo_samples(settings, photo):
    try:
        directory = Path(settings['photo_sample_directory']).expanduser().resolve(strict=True)
        candidates = sorted(path for path in directory.iterdir() if path.suffix.lower() in {'.jpg', '.jpeg', '.png'})
        if any(path.is_symlink() or not path.is_file() for path in candidates):
            raise ValueError('The photograph dataset must contain ordinary image files.')
    except (OSError, TypeError, KeyError):
        raise ValueError('The configured real photograph dataset is unavailable.') from None
    contract = photo['input']
    if (not contract['min_files'] <= len(candidates) <= contract['max_files']
            or any(path.suffix.lower() not in contract['extensions'] for path in candidates)):
        raise ValueError('The configured real photograph dataset does not match the published file contract.')
    return directory, [path.name for path in candidates]


def _existing_roll(settings):
    if not settings.get('roll_publication_id'):
        return None
    publication = _existing_publication(settings['roll_publication_id'])
    contract = publication['input']
    if not contract['min_files'] <= 1 <= contract['max_files'] or '.png' not in contract['extensions']:
        raise ValueError('The existing roll publication must accept the prototype single PNG scan.')
    return publication


def describe_existing_live_validation(settings):
    """Describe already-persisted prototypes in an app context, without setup.

    This path deliberately does not import a seed, open credentials, validate a
    gateway, alter account/registry state or create a missing publication. The
    configured runtime source may have changed since an immutable version was
    installed; only the persisted publication contract controls a resumed demo.
    """
    if db.session.new or db.session.dirty or db.session.deleted:
        raise ValueError('Resume requires a clean database session; pending changes are not applied.')
    with db.session.no_autoflush:
        photo = _existing_publication(settings.get('photo_publication_id') or 'link-photogrammetry')
        zenodo = _existing_publication('link-model-sandbox-draft')
        roll = _existing_roll(settings)
        sample_directory, sample_names = _photo_samples(settings, photo)
        return _prototype_configuration(settings, photo, zenodo, sample_directory, sample_names, roll=roll)


def prepare_live_validation(app, user, settings):
    from external_code.webhdp_link_photogrammetry.seed import seed as seed_photogrammetry
    from external_code.webhdp_link_zenodo.seed import seed as seed_zenodo

    roll = _existing_roll(settings)
    photo_publications = seed_photogrammetry(app.native_pipeline_service, **settings['photogrammetry'])
    if settings.get('photo_publication_id'):
        photo_publications[-1]['id'] = settings['photo_publication_id']
    zenodo_publications = _publication_list(seed_zenodo(app.native_pipeline_service))
    _check_existing_publications([*photo_publications, *zenodo_publications])
    photo = photo_publications[-1]
    sample_directory, sample_names = _photo_samples(settings, photo)
    app.hpc_allocation_service.update_config({
        'enabled': True, 'base_url': os.environ['HPC_LINK_BASE_URL'],
        'default_partition': settings['photogrammetry'].get('partition', 'gpu'),
        'default_gpu_type': settings['photogrammetry'].get('gpu_type'),
        'default_gpu_count': 1, 'default_duration_minutes': 720,
        'max_active_allocations': 1, 'max_active_allocations_per_user': 1,
    })
    validation = app.hpc_allocation_service.validate_config()
    if validation.get('last_validation_status') != 'valid':
        raise ValueError('The isolated HPC-Link gateway did not pass its authenticated WebHDP configuration check.')
    _sandbox_credential(user, settings['zenodo_environment_file'])
    photo_publications = _publish(photo_publications)
    zenodo_publications = _publish(zenodo_publications)
    photo = photo_publications[-1]
    zenodo = zenodo_publications[-1]
    return _prototype_configuration(settings, photo, zenodo, sample_directory, sample_names, roll=roll)


def _prototype_configuration(settings, photo, zenodo, sample_directory, sample_names, *, roll=None):
    result = {
        'photo-lab': {
            'client_id': settings.get('photo_client_id', 'photo-lab-draco'), 'pipeline_id': photo['id'],
            'sample_names': sample_names, '_sample_directory': str(sample_directory),
            'poll_interval_ms': 3000,
            'hero_title': 'Reconstruct from real photographs.',
            'hero_description': 'Send a photo set to WebHDP for genuine COLMAP photogrammetry on Draco, then retrieve the reconstructed geometry and validation evidence.',
            'scope_note': 'Real photogrammetry runs on a centrally managed Draco GPU. This application only communicates with WebHDP-Link.',
        },
        'model-depot': {
            'client_id': 'model-depot-sandbox', 'pipeline_id': zenodo['id'],
            'hero_title': 'Prepare a model. Save a draft.',
            'hero_description': 'Convert and check geometry, then upload the results to an unpublished Zenodo sandbox draft through WebHDP.',
            'scope_note': 'Uploads go only to the Zenodo sandbox. Drafts remain unpublished; this pipeline has no publish action.',
        },
    }
    if roll is not None:
        result['roll-studio'] = {
            'client_id': settings.get('roll_client_id', 'roll-studio'), 'pipeline_id': roll['id'],
            'hero_title': 'Process a piano-roll scan.',
            'hero_description': 'Send one scan per job to the approved WebHDP pipeline, then retrieve MIDI, candidate-note evidence and previews.',
            'scope_note': 'Processing uses the published carrier, timing and extraction bounds. Generated MIDI requires review; this application communicates only with WebHDP-Link.',
        }
    return result
