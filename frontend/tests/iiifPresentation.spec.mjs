import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import IiifManifestPreview from '@/components/workflow/IiifManifestPreview.vue'
import EdmTemplatesView from '@/views/admin/EdmTemplatesView.vue'
import { iiifInlineModelUrl, inspectIiifManifest, IIIF_PRESENTATION_LABEL } from '@/utils/iiifPresentation'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }))
vi.mock('@/services/api', () => ({ default: api }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ success: vi.fn(), warning: vi.fn(), error: vi.fn() }) }))

const asset = { id: 'https://zenodo.org/api/records/21/files/model.glb/content', type: 'Model', format: 'model/gltf-binary' }
const manifest = {
  '@context': 'http://iiif.io/api/presentation/4/context.json',
  type: 'Manifest',
  label: { en: ['Exhibition'] },
  items: [{ type: 'Scene', label: { en: ['Statue'] }, items: [{ type: 'AnnotationPage', items: [{
    motivation: ['painting'],
    type: 'Annotation',
    body: { type: 'SpecificResource', source: asset, transform: [{ type: 'ScaleTransform', x: 2, y: 2, z: 2 }] },
    target: { type: 'SpecificResource', selector: [{ type: 'PointSelector', x: 0, y: -1, z: 3 }] },
  }] }] }],
}

describe('IIIF Presentation manifests', () => {
  it('reports current and legacy versions without treating unsupported or unauthorized URLs as loadable assets', () => {
    const inspection = inspectIiifManifest(JSON.stringify(manifest))
    expect(inspection.versionLabel).toBe(IIIF_PRESENTATION_LABEL)
    expect(inspection.scenes[0].models[0]).toMatchObject({
      url: asset.id, label: 'Statue', point: [0, -1, 3], transforms: [{ name: 'Scale', values: [2, 2, 2] }],
    })
    expect(inspectIiifManifest({ ...manifest, '@context': 'http://iiif.io/api/presentation/3/context.json' })).toEqual({
      versionLabel: 'IIIF Presentation 3.0', scenes: [],
    })
    const unsupported = structuredClone(manifest)
    unsupported.items[0].items[0].items[0].body = { ...asset, id: 'javascript:alert(1)' }
    expect(inspectIiifManifest(unsupported).scenes[0].models).toEqual([])
    unsupported.items[0].items[0].items[0].body = { ...asset, id: `${asset.id}?access_token=private` }
    expect(inspectIiifManifest(unsupported).scenes[0].models).toEqual([])
    unsupported.items[0].items[0].items[0].body = { id: 'https://example.org/model.obj', type: 'Model', format: 'model/obj' }
    expect(inspectIiifManifest(unsupported).scenes[0].models[0].previewable).toBe(false)
    expect(inspectIiifManifest('{')).toBeNull()
  })

  it('opens the cited model asset only on request', async () => {
    const wrapper = mount(IiifManifestPreview, { props: { content: manifest }, global: { stubs: { PlaygroundModelViewer: true } } })
    expect(wrapper.find('playground-model-viewer-stub').exists()).toBe(false)
    await wrapper.get('button').trigger('click')
    expect(wrapper.get('playground-model-viewer-stub').attributes('src')).toBe(asset.id)
    expect(wrapper.text()).toContain('Scene placement, cameras and annotations are described in the manifest.')
    expect(wrapper.text()).toContain('Target point (X, Y, Z) 0, -1, 3')
    await wrapper.setProps({ content: { ...manifest, label: { en: ['Another sample'] } } })
    expect(wrapper.find('playground-model-viewer-stub').exists()).toBe(false)
    wrapper.unmount()
  })

  it('only offers inline viewing to same-origin glTF files and exact Zenodo record paths', () => {
    const origin = 'https://example.org'
    const model = url => ({ previewable: true, url })
    expect(iiifInlineModelUrl(model('https://example.org/assets/sample.glb'), origin)).toBe('https://example.org/assets/sample.glb')
    expect(iiifInlineModelUrl(model(asset.id), origin)).toBe(asset.id)
    const sandbox = asset.id.replace('https://zenodo.org/', 'https://sandbox.zenodo.org/')
    expect(iiifInlineModelUrl(model(sandbox), origin)).toBe(sandbox)
    expect(iiifInlineModelUrl(model('https://zenodo.org/api/deposit/depositions/21/file.glb'), origin)).toBe('')
    expect(iiifInlineModelUrl(model('https://external.example/model.glb'), origin)).toBe('')
    expect(iiifInlineModelUrl(model('http://zenodo.org/api/records/21/files/model.glb/content'), origin)).toBe('')
  })

  it('accepts extension contexts before the one terminal v4 context', () => {
    const base = manifest['@context']
    const extension = 'https://example.org/context'
    expect(inspectIiifManifest({ ...manifest, '@context': [extension, base] }).versionLabel).toBe(IIIF_PRESENTATION_LABEL)
    expect(inspectIiifManifest({ ...manifest, '@context': [base, extension] })).toBeNull()
    expect(inspectIiifManifest({ ...manifest, '@context': [base, base] })).toBeNull()
  })

  it('renders, validates and saves IIIF JSON in admin templates', async () => {
    const json = JSON.stringify(manifest)
    api.get.mockResolvedValue({ success: true, data: { templates: [
      { id: 1, standard: 'iiif', name: 'Museum Scene', content: json },
    ] } })
    api.post.mockImplementation(async endpoint => endpoint === '/templates/preview'
      ? { success: true, data: { json } }
      : { success: true, data: { valid: true, details: { scope: 'IIIF structure checks' }, warnings: [], errors: [] } })
    api.put.mockResolvedValue({ success: true })
    const wrapper = mount(EdmTemplatesView)
    const button = label => wrapper.findAll('button').find(item => item.text() === label)
    await flushPromises()
    await button('Edit').trigger('click')
    expect(wrapper.get('#iiif-template-content').element.value).toBe(json)
    await button('Preview Render').trigger('click')
    await flushPromises()
    expect(api.post).toHaveBeenCalledWith('/templates/preview', expect.objectContaining({ standard: 'iiif', content: json }), expect.anything())
    expect(wrapper.get('pre').text()).toContain(asset.id)
    await button('Validate').trigger('click')
    await flushPromises()
    expect(api.post).toHaveBeenLastCalledWith('/templates/validate', { standard: 'iiif', json }, expect.anything())
    expect(wrapper.text()).toContain('IIIF structure checks')
    await button('Save Template').trigger('click')
    await flushPromises()
    expect(api.put).toHaveBeenCalledWith('/templates/1', expect.objectContaining({ standard: 'iiif', format: 'json', content: json }))
    wrapper.unmount()
  })
})
