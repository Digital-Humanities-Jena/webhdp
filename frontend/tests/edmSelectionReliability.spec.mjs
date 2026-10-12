import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { useWorkflowStore } from '../src/stores/workflow'
import { persistWorkflowState, restoreWorkflowContext, shouldRestoreWorkflowContext } from '../src/utils/workflowState'
import EdmSelectionView from '../src/views/workflow/EdmSelectionView.vue'
const api = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn(), put: vi.fn() }))
const route = vi.hoisted(() => ({ query: {} }))
vi.mock('@/services/api', () => ({ default: api }))
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/utils/workflowState', () => ({ persistWorkflowState: vi.fn(), restoreWorkflowContext: vi.fn(), shouldRestoreWorkflowContext: vi.fn() }))
beforeEach(() => {
  vi.resetAllMocks()
  setActivePinia(createPinia())
  route.query = {}
  vi.mocked(shouldRestoreWorkflowContext).mockReturnValue(false)
  api.get.mockImplementation(url => Promise.resolve({ success: true, data: url === '/templates' ? { templates: [{ id: 1, standard: 'edm', name: 'First', is_default: true }, { id: 2, standard: 'edm', name: 'Second' }] } : { config: {} } }))
})
it('never shows successful validation when the validator is unavailable', async () => {
  api.post.mockImplementation(url => url.endsWith('/validate') ? Promise.reject(new Error('offline')) : Promise.resolve({ success: true, data: { xml: '<rdf/>' } }))
  const wrapper = mount(EdmSelectionView, { global: { stubs: { StepIndicator: true, LoadingSpinner: true, LodMapper: true } } })
  await flushPromises()
  expect(wrapper.text()).toContain('has not passed validation')
  expect(wrapper.text()).not.toContain('Available checks passed')
  wrapper.unmount()
})
it('shows scope as guidance and only labels actual validation checks', async () => {
  const scope = 'Enabled XML, schema and business checks. Skipped checks have not been performed.'
  api.post.mockImplementation(url => Promise.resolve({ success: true, data: url.endsWith('/validate') ? {
    valid: true,
    details: {
      scope,
      basic: { valid: true },
      xsd: { valid: true },
      schematron: { valid: true, skipped: true },
      business: { valid: true },
      remote: null,
      note: 'Informational text',
      count: 4,
    },
  } : { xml: '<rdf/>' } }))
  const wrapper = mountSelection()
  await flushPromises()
  expect(wrapper.text()).toContain(scope)
  expect(wrapper.text()).toContain('Available checks passed')
  const checks = wrapper.findAll('div.flex.flex-col.items-center.justify-center')
  expect(checks.map(check => check.findAll('span').map(label => label.text()))).toEqual([
    ['Basic', 'PASS'], ['Xsd', 'PASS'], ['Schematron', 'SKIPPED'], ['Business', 'PASS'], ['Remote', 'SKIPPED'],
  ])
  expect(checks.some(check => check.text().includes('Scope') || check.text().includes('FAIL'))).toBe(false)
  wrapper.unmount()
})
it('keeps genuine failed checks visible', async () => {
  api.post.mockImplementation(url => Promise.resolve({ success: true, data: url.endsWith('/validate') ? {
    valid: false,
    errors: ['Schema has an unexpected property'],
    details: { scope: 'Checks enabled', basic: { valid: true }, xsd: { valid: false } },
  } : { xml: '<rdf/>' } }))
  const wrapper = mountSelection()
  await flushPromises()
  expect(wrapper.text()).toContain('Issues Found')
  expect(wrapper.text()).toContain('Schema has an unexpected property')
  expect(wrapper.findAll('div.flex.flex-col.items-center.justify-center').map(check => check.findAll('span').map(label => label.text()))).toEqual([
    ['Basic', 'PASS'], ['Xsd', 'FAIL'],
  ])
  wrapper.unmount()
})
it('ignores a validation response for a previously selected template', async () => {
  let resolveFirst
  api.post.mockImplementation((url, payload) => {
    if (url.endsWith('/preview')) return Promise.resolve({ success: true, data: { xml: payload.template_id === 1 ? 'first' : 'second' } })
    if (payload.xml === 'first') return new Promise(resolve => { resolveFirst = resolve })
    return Promise.resolve({ success: true, data: { valid: false, errors: ['Second template needs attention'] } })
  })
  const wrapper = mount(EdmSelectionView, { global: { stubs: { StepIndicator: true, LoadingSpinner: true, LodMapper: true } } })
  await flushPromises()
  await wrapper.findAll('input[type="radio"]')[1].setValue()
  await flushPromises()
  resolveFirst({ success: true, data: { valid: true } })
  await flushPromises()
  expect(wrapper.text()).toContain('Second template needs attention')
  expect(wrapper.text()).not.toContain('Available checks passed')
  wrapper.unmount()
})

const mountSelection = () => mount(EdmSelectionView, { global: { stubs: { StepIndicator: true, LoadingSpinner: true, LodMapper: true } } })
const mockSuccessfulPreview = () => api.post.mockImplementation(url => Promise.resolve({
  success: true, data: url.endsWith('/validate') ? { valid: true } : { xml: '<rdf/>' },
}))

it('restores registered filenames and the saved main file after draft metadata arrives', async () => {
  const store = useWorkflowStore()
  route.query = { sessionId: '27', resume: 'workflow' }
  const sources = [
    Object.freeze({ file_id: 1, filename: 'terrain.glb', absolute_path: '/session/terrain.glb', size_bytes: 804152 }),
    Object.freeze({ file_id: 2, filename: 'preview.png', absolute_path: '/session/preview.png', size_bytes: 1024 }),
  ]
  vi.mocked(shouldRestoreWorkflowContext).mockReturnValue(true)
  vi.mocked(restoreWorkflowContext).mockImplementation(async (workflow, sessionId) => {
    workflow.setSessionId(sessionId)
    workflow.setUploadedFiles(sources)
    await Promise.resolve()
    workflow.setSelectedFiles(sources)
    workflow.setSubmissionMetadata({ edm_main_file_key: 'preview.png', edm_template_id: 1 })
  })
  mockSuccessfulPreview()
  const wrapper = mountSelection()
  await flushPromises()

  expect(restoreWorkflowContext).toHaveBeenCalledWith(store, 27)
  const assets = wrapper.findAll('button[aria-pressed]')
  expect(assets.map(asset => asset.text())).toEqual(expect.arrayContaining([
    expect.stringContaining('terrain.glb'), expect.stringContaining('preview.png'),
  ]))
  expect(assets[0].text()).toContain('785.3 KB')
  expect(assets.map(asset => asset.attributes('aria-pressed'))).toEqual(['false', 'true'])
  expect(api.post.mock.calls.filter(([url]) => url.endsWith('/preview')).at(-1)[1].main_file_key).toBe('preview.png')
  await assets[0].trigger('click')
  await flushPromises()
  expect(assets.map(asset => asset.attributes('aria-pressed'))).toEqual(['true', 'false'])
  expect(api.post.mock.calls.filter(([url]) => url.endsWith('/preview')).at(-1)[1].main_file_key).toBe('terrain.glb')
  await wrapper.findAll('button').find(button => button.text().includes('Continue to Pipeline')).trigger('click')
  await flushPromises()
  expect(api.put.mock.calls[0][1].edm_main_file_key).toBe('terrain.glb')
  expect(sources[0].name).toBeUndefined()
  expect(sources[0].size).toBeUndefined()
  expect(store.uploadedFiles[0]).toEqual(sources[0])
  wrapper.unmount()
})

it.each(['file_id', 'absolute_path'])('distinguishes duplicate basenames by exact %s selection', async (identityField) => {
  const store = useWorkflowStore()
  store.sessionId = 42
  const files = [
    { filename: 'model.glb', absolute_path: '/session/a/model.glb', relative_path: 'a/model.glb', size_bytes: 5000 },
    { filename: 'model.glb', absolute_path: '/session/b/model.glb', relative_path: 'b/model.glb', size_bytes: 1000 },
  ]
  if (identityField === 'file_id') files.forEach((file, index) => { file.file_id = index + 1 })
  store.uploadedFiles = files
  store.selectedFiles = [{ ...files[1] }]
  store.submissionMetadata = { edm_main_file_key: 'model.glb' }
  mockSuccessfulPreview()
  const wrapper = mountSelection()
  await flushPromises()
  const assets = wrapper.findAll('button[aria-pressed]')
  expect(assets.map(asset => asset.attributes('aria-pressed'))).toEqual(['false', 'true'])
  expect(assets[0].text()).toContain('a/model.glb')
  expect(assets[1].text()).toContain('b/model.glb')
  await assets[0].trigger('click')
  await flushPromises()
  expect(assets.map(asset => asset.attributes('aria-pressed'))).toEqual(['true', 'false'])
  expect(api.post.mock.calls.filter(([url]) => url.endsWith('/preview')).at(-1)[1].main_file_key).toBe('model.glb')
  await wrapper.findAll('button').find(button => button.text().includes('Continue to Pipeline')).trigger('click')
  await flushPromises()
  expect(api.put.mock.calls[0][1].edm_main_file_key).toBe('model.glb')
  expect(JSON.stringify(api.put.mock.calls[0][1])).not.toContain('/session/')
  wrapper.unmount()
})

it('supports browser File names and registered path-only filenames when selecting the largest asset', async () => {
  const store = useWorkflowStore()
  store.uploadedFiles = [new File(['small'], 'thumbnail.png'), { path: '/session/models/object.glb', size_bytes: 4096 }]
  mockSuccessfulPreview()
  const wrapper = mountSelection()
  await flushPromises()
  const assets = wrapper.findAll('button[aria-pressed]')
  expect(assets[0].text()).toContain('thumbnail.png')
  expect(assets[1].text()).toContain('object.glb')
  expect(assets.map(asset => asset.attributes('aria-pressed'))).toEqual(['false', 'true'])
  expect(api.post.mock.calls.filter(([url]) => url.endsWith('/preview')).at(-1)[1].main_file_key).toBe('object.glb')
  wrapper.unmount()
})

it('keeps the exact browser File selected when duplicate names are reordered', async () => {
  const store = useWorkflowStore()
  const first = new File(['small'], 'model.glb')
  const second = new File(['larger model'], 'model.glb')
  store.uploadedFiles = [first, second]
  mockSuccessfulPreview()
  const wrapper = mountSelection()
  await flushPromises()
  let assets = wrapper.findAll('button[aria-pressed]')
  expect(assets.map(asset => asset.attributes('aria-pressed'))).toEqual(['false', 'true'])
  await assets[0].trigger('click')
  store.uploadedFiles = [second, first]
  await flushPromises()
  assets = wrapper.findAll('button[aria-pressed]')
  expect(assets.map(asset => asset.attributes('aria-pressed'))).toEqual(['false', 'true'])
  wrapper.unmount()
})

it('never marks every nameless asset selected or saves a display placeholder as a filename', async () => {
  const store = useWorkflowStore()
  store.sessionId = 42
  store.uploadedFiles = [{ size_bytes: 1000 }, { size_bytes: 10 }]
  store.submissionMetadata = { edm_main_file_key: 'missing.glb' }
  mockSuccessfulPreview()
  const wrapper = mountSelection()
  await flushPromises()
  const assets = wrapper.findAll('button[aria-pressed]')
  expect(assets.map(asset => asset.attributes('aria-pressed'))).toEqual(['true', 'false'])
  expect(api.post.mock.calls.filter(([url]) => url.endsWith('/preview')).at(-1)[1].main_file_key).toBeNull()
  await wrapper.findAll('button').find(button => button.text().includes('Continue to Pipeline')).trigger('click')
  await flushPromises()
  expect(api.put.mock.calls[0][1].edm_main_file_key).toBeUndefined()
  wrapper.unmount()
})

it('preserves provider and keeps the batch preview out of shared file identity', async () => {
  const store = useWorkflowStore()
  store.sessionId = 42
  store.isBatchMode = true
  store.uploadedFiles = [{ name: 'sample-A.glb', size: 100 }]
  store.submissionMetadata = { edm_provider: 'Museum provider', edm_main_file_key: 'sample-A.glb', edm_template_id: 2 }
  const wrapper = mountSelection()
  await flushPromises()
  expect(wrapper.get('#edm-provider').element.value).toBe('Museum provider')
  expect(wrapper.text()).toContain('Selected: Second')
  expect(wrapper.text()).not.toContain('Preview (Live)')
  expect(api.post).not.toHaveBeenCalled()
  await wrapper.findAll('button').find(button => button.text().includes('Continue to Pipeline')).trigger('click')
  await flushPromises()
  expect(api.put.mock.calls[0][1].edm_provider).toBe('Museum provider')
  expect(api.put.mock.calls[0][1].edm_main_file_key).toBeUndefined()
  wrapper.unmount()
})
it('keeps edits separate from saved metadata when saving is rejected', async () => {
  const store = useWorkflowStore()
  store.sessionId = 42
  store.submissionMetadata = { edm_provider: 'Museum provider' }
  api.put.mockRejectedValue({ error: { message: 'Connection lost' } })
  const wrapper = mountSelection()
  await flushPromises()
  const step = store.currentStep
  await wrapper.get('#edm-provider').setValue('Revised museum')
  await wrapper.findAll('button').find(button => button.text().includes('Continue to Pipeline')).trigger('click')
  await flushPromises()
  expect(store.submissionMetadata.edm_provider).toBe('Museum provider')
  expect(store.currentStep).toBe(step)
  expect(wrapper.get('#edm-provider').element.value).toBe('Revised museum')
  expect(wrapper.text()).toContain('Connection lost')
  wrapper.unmount()
})
it('does not advance the step when workflow-state saving fails', async () => {
  const store = useWorkflowStore()
  store.sessionId = 42
  const wrapper = mountSelection()
  await flushPromises()
  const step = store.currentStep
  vi.mocked(persistWorkflowState).mockRejectedValueOnce(new Error('State unavailable'))
  await wrapper.findAll('button').find(button => button.text().includes('Continue to Pipeline')).trigger('click')
  await flushPromises()
  expect(store.currentStep).toBe(step)
  expect(wrapper.text()).toContain('State unavailable')
  wrapper.unmount()
})
