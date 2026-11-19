import { georeferencingInputError } from './georeferencingInputs'

export function pipelineGuidance(pipeline) {
  if (pipeline.guidance) return pipeline.guidance
  const steps = (pipeline.config?.steps || []).filter(step => step.enabled !== false)
  const keys = steps.map(step => step.component_ref || step.id)
  const uploads = keys.includes('zenodo_upload')
  const publicationRisk = step => {
    const key = step.component_ref || step.id
    const rules = step.triggers?.rules || []
    const bindings = (step.parameter_bindings || []).filter(value => value.target === 'publish')
    const publishes = key === 'zenodo_publish' || (key === 'zenodo_upload' && (Boolean(step.parameters?.publish)
      || rules.some(rule => rule.action !== 'skip' && Boolean(rule.parameter_overrides?.publish))
      || bindings.some(value => value.type !== 'literal' || Boolean(value.value))))
    return { publishes, conditional: publishes && (rules.length > 0 || bindings.some(value => value.type !== 'literal')) }
  }
  const risks = steps.map(publicationRisk)
  const publishes = risks.some(value => value.publishes)
  const conditional = risks.some(value => value.conditional)
  const createsDraft = keys.includes('zenodo_draft')
  const hpc = keys.some(key => ['fast_renderer', 'any_to_usdz', 'mesh_optimizer', 'georeferencer'].includes(key))
  return { creates_draft: createsDraft, uploads, publishes, requires_hpc: hpc, requires_gpu: keys.includes('fast_renderer'),
    outcome: publishes ? (conditional ? 'May publish on Zenodo; review publication conditions' : 'Publishes on Zenodo') : uploads ? 'Uploads files to a Zenodo draft; publication is a separate action' : createsDraft ? 'Creates or reuses a Zenodo draft' : 'Produces local results',
    requirements: [hpc ? 'Active HPC allocation' : '', createsDraft || uploads || publishes ? 'Zenodo credential for the selected environment' : ''].filter(Boolean),
    source_extensions: pipeline.identifier === 'mesh_optimization' ? ['.glb'] : null, outputs: steps.map(step => step.name) }
}

export function pipelineGpuCount(pipeline) {
  const guide = pipelineGuidance(pipeline)
  return guide.largest_step_resources?.gpu_count || Number(Boolean(guide.requires_gpu))
}

export function pipelineInputError(pipeline, files) {
  if (pipeline.identifier === 'model_georeferencing') return georeferencingInputError(files)
  const accepted = pipelineGuidance(pipeline).source_extensions
  if (!accepted) return ''
  if (!accepted.length) return 'The processing steps have no common source format. Choose another pipeline or revise its input bindings.'
  const unsupported = files.filter(file => {
    const name = file.filename || file.name || file.relative_path || file.absolute_path || ''
    return !accepted.some(extension => name.toLowerCase().endsWith(extension))
  })
  return unsupported.length ? `Requires ${accepted.join(', ')} source files. Return to Files to change the selection, or choose another pipeline.` : ''
}

export function recommendPipeline(pipelines, files) {
  const compatible = pipelines.filter(pipeline => !pipelineInputError(pipeline, files))
  // Avoid recommending publication or a resource-heavy job just because it sorts first.
  return [...compatible].sort((a, b) => {
    const score = pipeline => {
      const guide = pipelineGuidance(pipeline)
      const resources = guide.largest_step_resources || {}
      return [Number(Boolean(guide.publishes)), Number(Boolean(guide.requires_hpc)), pipeline.identifier === 'metadata_only' ? 0 : 1,
        resources.gpu_count || 0, resources.memory_mb || 0, resources.cpus || 0]
    }
    const left = score(a), right = score(b)
    for (let index = 0; index < left.length; index++) {
      if (left[index] !== right[index]) return left[index] - right[index]
    }
    return 0
  })[0] || null
}

export function pipelineTaskLabel(pipeline) {
  if (pipeline.name && pipeline.name !== pipeline.identifier) return pipeline.name
  return { metadata_only: 'Prepare a Zenodo draft', render: 'Prepare a draft with previews', mesh_optimization: 'Optimize and preview models',
    '3d_prepublication_analysis': 'Inspect models', '3d_point_cloud_readiness': 'Check point cloud readiness',
    model_georeferencing: 'Align models to reference imagery' }[pipeline.identifier] || pipeline.name
}
