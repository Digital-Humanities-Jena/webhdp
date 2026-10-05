import { describe, expect, it } from 'vitest'
import { pipelineGuidance, pipelineInputError, recommendPipeline } from '../src/utils/pipelineGuidance'

describe('pipeline guidance', () => {
  const pipeline = (identifier, steps) => ({ identifier, config: { steps } })
  it('recommends a compatible lower-resource choice instead of list order or publication', () => {
    const render = pipeline('render', [{ id: 'fast_renderer' }])
    const metadata = pipeline('metadata_only', [{ id: 'zenodo_draft' }, { id: 'zenodo_upload', parameters: { publish: false } }])
    const publish = pipeline('publish', [{ id: 'zenodo_upload', parameters: { publish: true } }])
    expect(recommendPipeline([publish, render, metadata], [{ name: 'model.glb' }])).toBe(metadata)
    expect(pipelineGuidance(metadata).outcome).toContain('publication is a separate action')
    expect(pipelineGuidance(publish).outcome).toBe('Publishes on Zenodo')
    expect(pipelineGuidance(pipeline('legacy', [{ id: 'zenodo_upload', parameters: { publish: 'false' } }])).publishes).toBe(true)
  })
  it('uses component contracts to reject incompatible inputs and ignores disabled steps', () => {
    const glb = { identifier: 'custom', guidance: { source_extensions: ['.glb'] } }
    expect(pipelineInputError(glb, [{ filename: 'photo.jpg' }])).toContain('.glb')
    expect(recommendPipeline([glb], [{ filename: 'photo.jpg' }])).toBe(null)
    expect(pipelineGuidance(pipeline('custom', [{ id: 'zenodo_upload', enabled: false, parameters: { publish: true } }])).publishes).toBe(false)
  })
  it('compares declared resource limits between otherwise compatible local plans', () => {
    const large = { identifier: 'large', guidance: { requires_hpc: false, publishes: false, largest_step_resources: { cpus: 8, memory_mb: 32768 } } }
    const small = { identifier: 'small', guidance: { requires_hpc: false, publishes: false, largest_step_resources: { cpus: 1, memory_mb: 2048 } } }
    expect(recommendPipeline([large, small], [{ name: 'model.glb' }])).toBe(small)
  })
  it('makes conditional publication visible before a workflow is selected', () => {
    const conditional = pipeline('custom', [{ id: 'zenodo_upload', parameters: { publish: false },
      triggers: { rules: [{ action: 'run', parameter_overrides: { publish: true } }] } }])
    expect(pipelineGuidance(conditional).publishes).toBe(true)
    expect(pipelineGuidance(conditional).outcome).toContain('May publish')
  })
})
