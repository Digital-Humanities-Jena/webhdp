import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import LodMapper from '../src/components/workflow/LodMapper.vue'
import { useWorkflowStore } from '../src/stores/workflow'
const api = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn() }))
vi.mock('@/services/api', () => ({ default: api }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ success: vi.fn(), warning: vi.fn(), error: vi.fn() }) }))
let wrapper
beforeEach(async () => {
  vi.resetAllMocks()
  setActivePinia(createPinia())
  useWorkflowStore().sessionId = 1
  api.get.mockResolvedValue({ data: { config: {} } })
  api.post.mockResolvedValue({ success: true, data: { columns: ['filename', 'title'], suggested_row_index: 0 } })
  wrapper = mount(LodMapper, { props: { msfPath: '/session/msf.csv', templateId: 7 } })
  await flushPromises()
})
const button = label => wrapper.findAll('button').find(b => b.text().includes(label))
describe('LOD preview reliability', () => {
  it('loads source columns and discards a late response after switching formats', async () => {
    expect(api.post).toHaveBeenCalledWith('/edm/msf-columns', expect.objectContaining({ session_id: 1 }))
    let resolve
    api.post.mockImplementation(() => new Promise(r => { resolve = r }))
    await button('Test Mapping').trigger('click')
    await button('EDM-XML').trigger('click')
    resolve({ success: true, data: { xml: 'OLD RESULT', validation: { valid: true } } })
    await flushPromises()
    expect(wrapper.text()).not.toContain('OLD RESULT')
    expect(wrapper.text()).not.toContain('Valid EDM-XML')
    wrapper.unmount()
  })
  it('shows validation unavailable and only sends the EDM template to EDM', async () => {
    await button('IIIF').trigger('click')
    api.post.mockResolvedValue({ success: true, data: {} })
    await button('Test Mapping').trigger('click')
    await flushPromises()
    const payload = api.post.mock.calls.at(-1)[1]
    expect(payload.template_id).toBeUndefined()
    expect(wrapper.get('[role="alert"]').text()).toContain('Validation is unavailable')
    wrapper.unmount()
  })
  it('keeps known metadata errors distinct from a concurrent validator outage', async () => {
    await button('EDM-XML').trigger('click')
    api.post.mockResolvedValue({ success: true, data: { xml: '<invalid/>', validation: {
      valid: false, status: 'invalid', errors: ['Title is missing'], details: { remote: { valid: false, status: 'unavailable' } },
    } } })
    await button('Test Mapping').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Validation Failed')
    expect(wrapper.text()).not.toContain('Unverified · validator unavailable')
    wrapper.unmount()
  })
  it('provides CIDOC and JSON-LD previews with shared mappings', async () => {
    await button('CIDOC-CRM').trigger('click')
    api.post.mockResolvedValue({ success: true, data: { xml: '<rdf/>', validation: { valid: true } } })
    await button('Test Mapping').trigger('click')
    await flushPromises()
    expect(api.post.mock.calls.at(-1)[0]).toBe('/edm/test-linked-mapping')
    await button('JSON-LD').trigger('click')
    expect(wrapper.text()).not.toContain('<rdf/>')
    expect(wrapper.text()).toContain('same digital dataset')
    wrapper.unmount()
  })
  it('previews current metadata and provider, then invalidates the result when provider changes', async () => {
    useWorkflowStore().submissionMetadata = { title: 'Actual record', creators: [{ name: 'Museum' }] }
    await wrapper.setProps({ provider: 'Museum provider' })
    await button('EDM-XML').trigger('click')
    api.post.mockResolvedValue({ success: true, data: { xml: '<rdf/>', validation: { valid: true } } })
    await button('Test Mapping').trigger('click')
    await flushPromises()
    const payload = api.post.mock.calls.at(-1)[1]
    expect(payload.zenodo_record.metadata).toMatchObject({ title: 'Actual record', edm_provider: 'Museum provider' })
    expect(payload.zenodo_record.files).toEqual([])
    expect(payload.zenodo_mapping).toBeDefined()
    expect(wrapper.text()).toContain('<rdf/>')
    await wrapper.setProps({ provider: 'Another provider' })
    expect(wrapper.text()).not.toContain('<rdf/>')
    wrapper.unmount()
  })

})
