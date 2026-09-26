import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { useWorkflowStore } from '../src/stores/workflow'
import { persistWorkflowState } from '../src/utils/workflowState'
import EdmSelectionView from '../src/views/workflow/EdmSelectionView.vue'
const api = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn(), put: vi.fn() }))
vi.mock('@/services/api', () => ({ default: api }))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/utils/workflowState', () => ({ persistWorkflowState: vi.fn(), restoreWorkflowContext: vi.fn(), shouldRestoreWorkflowContext: () => false }))
beforeEach(() => {
  vi.resetAllMocks()
  setActivePinia(createPinia())
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
