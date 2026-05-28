import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RouterLinkStub } from './helpers/router.mjs'

const mocked = vi.hoisted(() => ({
  route: {
    params: {
      environment: 'zenodo',
      zenodoRecordId: '123',
    },
  },
  publicRecordService: {
    getRecord: vi.fn(),
  },
  publicOembedUrl: vi.fn(() => 'https://webhdp.example/api/v1/oembed?url=public&format=json'),
}))

vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRoute: () => mocked.route,
  }
})

vi.mock('@/services/publicRecord.service.js', () => ({
  default: mocked.publicRecordService,
  publicOembedUrl: mocked.publicOembedUrl,
}))

import EmbedRecordView from '../src/views/public/EmbedRecordView.vue'
import PublicRecordView from '../src/views/public/PublicRecordView.vue'

function recordPayload(overrides = {}) {
  return {
    title: 'Public 3D Model',
    environment: 'zenodo',
    zenodo_record_id: '123',
    creators: ['Ada Lovelace'],
    doi: '10.5281/zenodo.123',
    publication_date: '2026-04-29',
    description: '<p>A model description.</p>',
    file_count: 2,
    public_url: 'https://webhdp.example/p/records/zenodo/123',
    embed_url: 'https://webhdp.example/embed/records/zenodo/123',
    oembed_url: 'https://webhdp.example/api/v1/oembed?url=public&format=json',
    zenodo_url: 'https://zenodo.org/records/123',
    model_preview: {
      is_3d_record: true,
      can_inline_preview: true,
      url: 'https://zenodo.org/api/records/123/files/model.glb/content',
      filename: 'model.glb',
      format: 'glb',
    },
    ...overrides,
  }
}

describe('public record views', () => {
  beforeEach(() => {
    mocked.publicRecordService.getRecord.mockReset()
    mocked.publicOembedUrl.mockClear()
    mocked.route.params = {
      environment: 'zenodo',
      zenodoRecordId: '123',
    }
    document.head.querySelectorAll('link[type="application/json+oembed"]').forEach((node) => node.remove())
  })

  it('renders the public landing page and adds oEmbed discovery', async () => {
    mocked.publicRecordService.getRecord.mockResolvedValue({ data: recordPayload() })

    const wrapper = mount(PublicRecordView, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
          LoadingSpinner: true,
          PublicRecordPreview: { props: ['record'], template: '<div data-testid="preview">{{ record.title }}</div>' },
        },
      },
    })
    await flushPromises()

    expect(mocked.publicRecordService.getRecord).toHaveBeenCalledWith('zenodo', '123')
    expect(wrapper.text()).toContain('Public 3D Model')
    expect(wrapper.text()).toContain('Ada Lovelace')
    expect(wrapper.text()).toContain('Open on Zenodo')
    const discovery = document.head.querySelector('link[type="application/json+oembed"]')
    expect(discovery?.href).toBe('https://webhdp.example/api/v1/oembed?url=public&format=json')
  })

  it('renders the embed page without navigation chrome', async () => {
    mocked.publicRecordService.getRecord.mockResolvedValue({ data: recordPayload() })

    const wrapper = mount(EmbedRecordView, {
      global: {
        stubs: {
          LoadingSpinner: true,
          PublicRecordPreview: { props: ['record'], template: '<div data-testid="preview">{{ record.title }}</div>' },
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Public 3D Model')
    expect(wrapper.text()).toContain('Ada Lovelace')
    expect(wrapper.text()).toContain('Details')
    expect(wrapper.text()).not.toContain('Dashboard')
    expect(wrapper.text()).not.toContain('Logout')
  })
})
