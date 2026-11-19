"""User-facing outcomes derived from enabled pipeline steps and component contracts."""


def _publication_risk(step, manifest):
    key = step.get('component_ref') or step.get('id')
    rules = (step.get('triggers') or {}).get('rules') or []
    if key == 'zenodo_publish':
        return True, bool(rules)
    if key != 'zenodo_upload':
        return False, False
    defaults = {value.get('name'): value.get('default') for group in manifest.get('parameter_groups', [])
                for value in group.get('parameters', [])}
    bindings = [value for value in step.get('parameter_bindings', []) if value.get('target') == 'publish']
    override = any(value.get('action', 'run') == 'run' and bool((value.get('parameter_overrides') or {}).get('publish')) for value in rules)
    bound = any(value.get('type') != 'literal' or bool(value.get('value')) for value in bindings)
    # The built-in uploader evaluates this setting with bool(), including older
    # imported configurations which did not enforce a boolean parameter type.
    publishes = bool(step.get('parameters', {}).get('publish', defaults.get('publish'))) or override or bound
    conditional = bool(rules) or any(value.get('type') != 'literal' for value in bindings)
    return publishes, publishes and conditional


def pipeline_guidance(config, manifests, selected_profiles=None):
    from services.hdp_component_policy import component_gpu_count, hpc_required_component
    steps = [step for step in config.get('steps', []) if step.get('enabled', True)]
    keys = {step.get('component_ref') or step.get('id') for step in steps}
    uploads = 'zenodo_upload' in keys
    risks = [_publication_risk(step, manifests.get(step.get('id')) or manifests.get(step.get('component_ref')) or {}) for step in steps]
    publishes = any(value[0] for value in risks)
    conditional_publication = any(value[1] for value in risks)
    drafts = 'zenodo_draft' in keys
    outputs, requirements, extensions = [], [], None
    resources = {'gpu_count': 0, 'cpus': 0, 'memory_mb': 0}
    hpc_keys = []
    for step in steps:
        key = step.get('component_ref') or step.get('id')
        manifest = manifests.get(step.get('id')) or manifests.get(key) or {}
        profiles = manifest.get('execution', {}).get('profiles', [])
        if selected_profiles is None:
            requested = step.get('execution_profile_ref')
            profile = next((value for value in profiles if value.get('id') == requested), {}) if requested else (profiles[0] if profiles else {})
        else:
            profile = selected_profiles.get(step.get('id'), {})
        if hpc_required_component(key) or profile.get('adapter') == 'hpc_link' or profile.get('runtime') in ('singularity', 'apptainer'):
            hpc_keys.append(key)
        elif profile.get('runtime') == 'docker':
            requirements.append('Installed local container')
        limits = profile.get('resources') or {}
        for resource in resources:
            value = component_gpu_count(key, limits) if resource == 'gpu_count' else limits.get(resource, 0)
            if type(value) is not int or value < 0:
                requirements.append(f"{step.get('name') or key}: review invalid {resource} resource limit")
                continue
            resources[resource] = max(resources[resource], value)
        for output in manifest.get('outputs', []):
            outputs.append(output.get('label') or output.get('name'))
        # Restrictions apply to original sources, not inputs produced by an earlier step.
        bindings = step.get('input_bindings') or []
        source_targets = {binding.get('target') for binding in bindings if binding.get('type') in ('pipeline_source_file', 'pipeline_source_files', 'record_source_files')}
        if not bindings:
            source_targets = {value.get('name') for value in manifest.get('inputs', [])}
        fields = manifest.get('ui', {}).get('playground', {}).get('fields', {})
        input_formats = []
        for target in sorted(source_targets):
            accepted = fields.get(target, {}).get('accept_extensions')
            if key == 'geometric_lod_generator' and target == 'input_file' and not accepted:
                accepted = ['.glb']
            if accepted:
                accepted = {value.lower() for value in accepted}
                input_formats.append((target, accepted))
        if input_formats and (step.get('triggers') or {}).get('rules'):
            requirements.extend(f"Conditional {target.replace('_', ' ')}: {', '.join(sorted(accepted))}; checked during preflight"
                                for target, accepted in input_formats)
        elif len(input_formats) == 1:
            accepted = input_formats[0][1]
            extensions = accepted if extensions is None else extensions & accepted
        elif input_formats:
            # Distinct inputs can require distinct formats (for example GLB plus GeoTIFF).
            # Their intersection would disable a valid paired-input workflow.
            requirements.extend(f"{target.replace('_', ' ')}: {', '.join(sorted(accepted))}"
                                for target, accepted in input_formats)
    requires_hpc = bool(hpc_keys)
    requires_gpu = resources['gpu_count'] > 0
    if requires_hpc:
        requirements.insert(0, 'Active HPC allocation')
    if any(resources.values()):
        limits = [f"{resources['gpu_count']} GPU(s)" if resources['gpu_count'] else '',
                  f"{resources['cpus']} CPU(s)" if resources['cpus'] else '',
                  f"{resources['memory_mb'] / 1024:g} GiB RAM" if resources['memory_mb'] else '']
        requirements.append('Declared per-step resource maxima: ' + ', '.join(value for value in limits if value))
    if drafts or uploads or publishes:
        requirements.append('Zenodo credential for the selected environment')
    if publishes:
        outcome = 'May publish on Zenodo; review publication conditions' if conditional_publication else 'Publishes on Zenodo'
    elif uploads:
        outcome = 'Uploads files to a Zenodo draft; publication is a separate action'
    elif drafts:
        outcome = 'Creates or reuses a Zenodo draft'
    else:
        outcome = 'Produces local results'
    return {'outcome': outcome, 'creates_draft': drafts, 'uploads': uploads, 'publishes': publishes, 'conditional_publication': conditional_publication,
            'requires_hpc': requires_hpc, 'requires_gpu': requires_gpu,
            'hpc_component_keys': list(dict.fromkeys(hpc_keys)), 'requirements': list(dict.fromkeys(requirements)),
            'outputs': list(dict.fromkeys(value for value in outputs if value)),
            'source_extensions': sorted(extensions) if extensions is not None else None,
            'largest_step_resources': resources}
