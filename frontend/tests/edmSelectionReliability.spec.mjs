import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import EdmSelectionView from '../src/views/workflow/EdmSelectionView.vue'
const api = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn() }))
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
