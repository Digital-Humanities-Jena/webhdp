"""Prepare and publish a frozen HMSM roll processor for central execution."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil

from .runner import OUTPUTS, sha256, write_json

ROOT = Path(__file__).resolve().parent
KEY = 'link_hmsm_roll_digitizer'
VERSION = '1.0.0'
MODELS = ('phonola', 'phonola_solodant', 'animatic', 'generic_73', 'generic_73_no_dynamics',
          'generic_73_fsharp_no_dynamics', 'generic_73_fsharp', 'generic_88', 'generic_65',
          'generic_65_no_dynamics', 'clavitist')
PARAMETERS = {
    'model_id': {'type': 'string', 'enum': list(MODELS), 'default': 'generic_65_no_dynamics', 'label': 'Piano-roll carrier profile'},
    'roll_speed': {'type': 'number', 'minimum': .2, 'maximum': 30, 'default': 6, 'label': 'Roll speed (feet/minute)'},
    'method': {'type': 'string', 'enum': ['robust', 'background', 'adaptive', 'otsu'], 'default': 'robust', 'label': 'Optical extraction method'},
    'polarity': {'type': 'string', 'enum': ['dark', 'light'], 'default': 'dark', 'label': 'Perforation polarity'},
}


def definitions(*, runtime_python, remote_component_root, source_manifest_sha256, publication_id='link-hmsm-roll-vis', partition='vis', gpu_type='a5000'):
    for value in [runtime_python, remote_component_root]:
        if not isinstance(value, str) or not value.startswith('/') or '..' in Path(value).parts or '\x00' in value:
            raise ValueError('Runtime locations must be trusted absolute paths')
    if not re.fullmatch(r'[a-f0-9]{64}', source_manifest_sha256):
        raise ValueError('A frozen source inventory SHA256 is required')
    manifest = {'metadata': {'name': KEY, 'version': VERSION, 'label': 'Central HMSM piano-roll digitizer',
        'description': 'Extract candidate notes and MIDI from a scan with frozen HMSM Studio roll profiles.',
        'component_schema': '0.1.0-alpha.1', 'status': 'alpha', 'tags': ['webhdp-link', 'hmsm', 'piano-roll']},
        'distribution': {'tier': 'operator_managed', 'bundled_with_webhdp': False},
        'inputs': [{'name': 'input_file', 'label': 'Piano-roll scan', 'type': 'file_path', 'required': True}],
        'outputs': [{'name': key, 'label': filename, 'type': 'file_path', 'extensions': [Path(filename).suffix], 'required': True}
                    for key, filename in OUTPUTS.items()],
        'parameter_groups': [{'title': 'Optical extraction', 'parameters': [{'name': key, **deepcopy(value)} for key, value in PARAMETERS.items()]}],
        'execution': {'timeout_seconds': 3600, 'profiles': [{'id': 'hpc', 'adapter': 'hpc_link', 'handler': 'trusted_host_component', 'runtime': 'host',
            'entrypoint': ['/usr/bin/env', '-u', 'PYTHONPATH', '-u', 'PYTHONHOME', '-u', 'LD_LIBRARY_PATH',
                'PYTHONDONTWRITEBYTECODE=1', 'OPENBLAS_NUM_THREADS=2', 'OMP_NUM_THREADS=2', runtime_python,
                remote_component_root.rstrip('/') + '/runner.py', '--source', remote_component_root.rstrip('/') + '/source',
                '--source-manifest-sha256', source_manifest_sha256, '--expected-runner-sha256', sha256(ROOT / 'runner.py')],
            'resources': {'gpu_count': 0, 'cpus': 2, 'memory_mb': 4096}}]},
        'compatibility': {'playground': {'enabled': True}}}
    publication = {'id': publication_id, 'name': 'HMSM roll processing on central compute', 'enabled': True,
        'description': 'Digitize a piano-roll scan through WebHDP and the frozen HMSM optical processor; retrieve MIDI, candidate-note evidence and previews. Carrier assumptions require review.',
        'pipeline_identifier': 'link_hmsm_roll', 'pipeline_version': VERSION, 'execution_mode': 'record', 'step_timeout_seconds': 3600,
        'input': {'min_files': 1, 'max_files': 1, 'extensions': ['.png', '.jpg', '.jpeg', '.tif', '.tiff', '.webp']},
        'parameters': {key: {'step_id': 'digitize', 'parameter': key, **deepcopy(value)} for key, value in PARAMETERS.items()},
        # Retained allocation compatibility is exact. CPU optical work can reuse
        # the existing GPU reservation without requesting another allocation.
        'hpc': {'enabled': True, 'partition': partition, 'gpu_type': gpu_type, 'gpu_count': 1,
                'walltime_hours': 12, 'retain_allocation': True, 'reuse_retained_allocation': True}}
    pipeline = {'identifier': publication['pipeline_identifier'], 'name': publication['name'], 'description': publication['description'],
        'version': VERSION, 'status': 'active', 'processingMode': 'root', 'tags': ['webhdp-link', 'hmsm'],
        'steps': [{'id': 'digitize', 'name': 'HMSM optical roll extraction', 'component_ref': KEY, 'component_version': VERSION,
                   'execution_profile_ref': 'hpc', 'scope': 'record',
                   'parameters': {key: value['default'] for key, value in PARAMETERS.items()},
                   'input_bindings': [{'kind': 'input', 'target': 'input_file', 'type': 'pipeline_source_file'}]}]}
    return manifest, pipeline, publication


def prepare_installation(destination, *, hmsm_source, runtime_python, remote_component_root):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    source = Path(hmsm_source).resolve(strict=True)
    paths = [source / name for name in ['LICENSE', 'requirements.txt', 'backend/__init__.py', 'backend/vendor/HMSM-LICENSE',
             'docs/ATTRIBUTION.md', 'backend/data/models.json', 'backend/data/carrier-operational-evidence.json']]
    paths += sorted((source / 'backend/studio').glob('*.py'))
    installed = destination / 'source'
    inventory = {}
    for path in paths:
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(source):
            raise ValueError('Scientific source must be ordinary files within its checkout')
        raw = path.read_bytes()
        if re.search(rb'(?i)\b(?:codex|chatgpt)\b|agents\.md', raw):
            raise ValueError('Installation source contains excluded development attribution')
        relative = path.relative_to(source)
        target = installed / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        inventory[str(relative)] = hashlib.sha256(raw).hexdigest()
    if any(sha256(source / name) != checksum for name, checksum in inventory.items()):
        raise ValueError('HMSM source changed during installation staging')
    module_hash = hashlib.sha256()
    for module in sorted((installed / 'backend/studio').glob('*.py')):
        module_hash.update(module.name.encode()); module_hash.update(module.read_bytes())
    models = json.loads((installed / 'backend/data/models.json').read_text())
    available = {item['id'] for item in models if item.get('media_type') == 'roll' and item.get('status') == 'available'}
    if set(MODELS) - available:
        raise ValueError('Published roll profiles are unavailable in this source snapshot')
    write_json(destination / 'source-manifest.json', {'schema_version': '1.0', 'files': inventory,
        'module_sha256': module_hash.hexdigest(), 'roll_models': list(MODELS), 'license': 'GPL-3.0-or-later'})
    shutil.copyfile(ROOT / 'runner.py', destination / 'runner.py')
    trusted = {'runtime_python': runtime_python, 'remote_component_root': remote_component_root,
               'source_manifest_sha256': sha256(destination / 'source-manifest.json')}
    manifest, _, _ = definitions(**trusted)
    write_json(destination / 'manifest.json', manifest)
    write_json(destination / 'component.json', {'component_key': KEY, 'version': VERSION,
        'manifest_path': remote_component_root.rstrip('/') + '/manifest.json', 'manifest_sha256': sha256(destination / 'manifest.json')})
    write_json(destination / 'checksums.json', {str(path.relative_to(destination)): sha256(path) for path in sorted(destination.rglob('*')) if path.is_file()})
    return trusted


def seed(service, **trusted):
    manifest, pipeline, publication = definitions(**trusted)
    service.import_component_from_manifest(manifest, source_path=str(ROOT), source_type='external')
    service.create_pipeline_version_from_config(pipeline['identifier'], pipeline, activate=True)
    return publication
