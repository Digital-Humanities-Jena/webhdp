from services.pipeline_guidance import pipeline_guidance


def test_outcomes_follow_enabled_publication_steps():
    config = {'steps': [{'id': 'draft', 'component_ref': 'zenodo_draft'},
                        {'id': 'upload', 'component_ref': 'zenodo_upload', 'parameters': {'publish': False}},
                        {'id': 'publish', 'component_ref': 'zenodo_publish', 'enabled': False}]}
    guide = pipeline_guidance(config, {})
    assert guide['creates_draft'] and guide['uploads'] and not guide['publishes']
    assert 'separate action' in guide['outcome']
    assert guide['requirements'] == ['Zenodo credential for the selected environment']
    config['steps'][1]['parameters']['publish'] = True
    assert pipeline_guidance(config, {})['publishes']


def test_publication_overrides_are_visible_even_when_the_base_setting_is_draft_only():
    step = {'id': 'zenodo_upload', 'parameters': {'publish': False},
            'triggers': {'rules': [{'action': 'run', 'parameter_overrides': {'publish': True}}]}}
    guide = pipeline_guidance({'steps': [step]}, {})
    assert guide['publishes'] and guide['conditional_publication']
    assert guide['outcome'].startswith('May publish')
    step['triggers'] = None
    step['parameter_bindings'] = [{'target': 'publish', 'type': 'record_metadata_field', 'field': 'approved'}]
    assert pipeline_guidance({'steps': [step]}, {})['conditional_publication']


def test_legacy_truthy_publication_settings_are_not_described_as_draft_only():
    guide = pipeline_guidance({'steps': [{'id': 'zenodo_upload', 'parameters': {'publish': 'false'}}]}, {})
    assert guide['publishes']
    assert guide['outcome'] == 'Publishes on Zenodo'


def test_input_restrictions_ignore_derived_files_and_disabled_steps():
    manifests = {'geometry': {'inputs': [{'name': 'input_file'}],
                 'ui': {'playground': {'fields': {'input_file': {'accept_extensions': ['.glb']}}}}},
                 'renderer': {'inputs': [{'name': 'input_file'}],
                 'ui': {'playground': {'fields': {'input_file': {'accept_extensions': ['.obj']}}}}}}
    config = {'steps': [{'id': 'geometry', 'input_bindings': [{'target': 'input_file', 'type': 'pipeline_source_file'}]},
                       {'id': 'renderer', 'input_bindings': [{'target': 'input_file', 'type': 'artifact_file'}]},
                       {'id': 'renderer', 'enabled': False}]}
    assert pipeline_guidance(config, manifests)['source_extensions'] == ['.glb']


def test_lod_input_contract_does_not_restrict_the_source_of_an_upstream_conversion():
    config = {'steps': [{'id': 'convert', 'input_bindings': [{'target': 'input_file', 'type': 'pipeline_source_file'}]},
                       {'id': 'geometric_lod_generator', 'input_bindings': [{'target': 'input_file', 'type': 'artifact_file'}]}]}
    manifest = {'ui': {'playground': {'fields': {'input_file': {'accept_extensions': ['.obj', '.glb']}}}}}
    assert pipeline_guidance(config, {'convert': manifest})['source_extensions'] == ['.glb', '.obj']


def test_conditional_format_requirements_do_not_block_mixed_media_batches():
    manifest = {'ui': {'playground': {'fields': {'input_file': {'accept_extensions': ['.glb']}}}}}
    step = {'id': 'geometry', 'input_bindings': [{'target': 'input_file', 'type': 'pipeline_source_file'}],
            'triggers': {'default_behavior': 'skip', 'rules': [{'id': 'models', 'action': 'run'}]}}
    guide = pipeline_guidance({'steps': [step]}, {'geometry': manifest})
    assert guide['source_extensions'] is None
    assert any('Conditional' in value and '.glb' in value for value in guide['requirements'])


def test_paired_inputs_do_not_intersect_unrelated_formats_and_resources_are_explicit():
    manifest = {'inputs': [{'name': 'input_file'}, {'name': 'reference_files'}],
                'execution': {'profiles': [{'id': 'gpu', 'adapter': 'hpc_link', 'runtime': 'singularity',
                                          'resources': {'gpu_count': 1, 'cpus': 8, 'memory_mb': 32768}}]},
                'ui': {'playground': {'fields': {'input_file': {'accept_extensions': ['.glb']},
                                                'reference_files': {'accept_extensions': ['.tif', '.tiff']}}}}}
    guide = pipeline_guidance({'steps': [{'id': 'align', 'execution_profile_ref': 'gpu',
                 'input_bindings': [{'target': 'input_file', 'type': 'pipeline_source_file'},
                                    {'target': 'reference_files', 'type': 'record_source_files'}]}]}, {'align': manifest})
    assert guide['requires_hpc']
    assert guide['source_extensions'] is None
    assert 'reference files: .tif, .tiff' in guide['requirements']
    assert guide['largest_step_resources']['memory_mb'] == 32768
    assert any('32 GiB' in value for value in guide['requirements'])


def test_invalid_optional_resource_values_do_not_hide_the_pipeline_list():
    manifest = {'execution': {'profiles': [{'resources': {'cpus': 4, 'memory_mb': 'unknown', 'gpu_count': True}}]}}
    guide = pipeline_guidance({'steps': [{'id': 'custom'}]}, {'custom': manifest})
    assert guide['largest_step_resources'] == {'cpus': 4, 'memory_mb': 0, 'gpu_count': 0}
    assert any('review invalid memory_mb' in value for value in guide['requirements'])
    assert any('review invalid gpu_count' in value for value in guide['requirements'])
