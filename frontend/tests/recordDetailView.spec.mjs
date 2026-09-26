import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RouterLinkStub } from './helpers/router.mjs'

const mocked = vi.hoisted(() => ({
  route: {
    params: {
      sessionId: '42',
      recordId: '9',
    },
  },
  submissionService: {
    getSessionRecordDetail: vi.fn(),
    createSessionRecordVersion: vi.fn(),
  },
  pipelineService: { getPlaygroundSessionFile: vi.fn() },
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRoute: () => mocked.route,
  }
})

vi.mock('@/services/submission.service.js', () => ({
  default: mocked.submissionService,
}))
vi.mock('@/services/pipeline.service.js', () => ({ default: mocked.pipelineService }))

vi.mock('@/composables/useToast', () => ({
  useToast: () => mocked.toast,
}))

import RecordDetailView from '../src/views/dashboard/RecordDetailView.vue'

describe('RecordDetailView', () => {
  beforeEach(() => {
    Object.values(mocked.submissionService).forEach((fn) => fn.mockReset())
    Object.values(mocked.toast).forEach((fn) => fn.mockReset())
    mocked.route.params = {
      sessionId: '42',
      recordId: '9',
    }
    global.URL.createObjectURL = vi.fn(() => 'blob:record-detail')
    global.URL.revokeObjectURL = vi.fn()
    global.confirm = vi.fn(() => true)
  })

  it('downloads generated models through the authenticated session endpoint and reports failures', async () => {
    mocked.submissionService.getSessionRecordDetail.mockResolvedValue({ data: { record: {
      local_record_id: 9, files: [{ file_id: 1, filename: 'model_optimized.glb', absolute_path: '/session/outputs/model_optimized.glb', pipeline_source: 'mesh_optimizer' }],
    } } })
    mocked.pipelineService.getPlaygroundSessionFile.mockRejectedValue(new Error('Missing file'))
    const wrapper = mount(RecordDetailView, { global: { stubs: { RouterLink: RouterLinkStub, PlaygroundModelViewer: true } } })
    await flushPromises()
    const button = wrapper.findAll('button').find(item => item.text() === 'Download file')
    expect(button).toBeTruthy()
    await button.trigger('click')
    await flushPromises()
    expect(mocked.pipelineService.getPlaygroundSessionFile).toHaveBeenCalledWith(42, '/session/outputs/model_optimized.glb')
    expect(mocked.toast.error).toHaveBeenCalledWith(expect.stringContaining('could not be downloaded'))
    expect(button.attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('renders record detail and creates a new version draft', async () => {
    mocked.submissionService.getSessionRecordDetail.mockResolvedValue({
      data: {
        record: {
          local_record_id: 9,
          record_title: 'Published Record',
          record_status: 'published',
          record_link: 'https://zenodo.org/records/9',
          zenodo_record_id: 9,
          concept_rec_id: '1009',
          zenodo_doi: '10.5072/test',
          is_sandbox: true,
          source_file_name: 'model.glb',
          source_file_path: '/tmp/model.glb',
          provenance: {
            msf_path: '/tmp/source.xlsx',
            mapping_field_count: 2,
            mapped_metadata: { title: 'Published Record' },
            pipeline_lineage: [{ pipeline: 'render', step: 'publish' }],
          },
          files: [
            {
              file_id: 1,
              filename: 'model.glb',
              absolute_path: '/tmp/model.glb',
              file_purpose: 'source',
              size_bytes: 2048,
            },
          ],
          processing: {
            render_status: 'completed',
            usdz_status: 'completed',
          },
          record_metadata: { title: 'Published Record' },
        },
        health: {
          total_files: 1,
          uploaded_files: 1,
          can_create_new_version: true,
        },
        lineage: {
          summary: { snapshot_count: 2 },
          latest_same_concept: { record_id: 9, version: 2 },
          source_hierarchy: { filename: 'model.glb' },
        },
        zenodo_status: {
          summary: {
            uploaded_file_count: 1,
            file_count: 1,
            has_html_link: true,
          },
          communities: [{ identifier: 'museum-network' }],
          actions: { can_create_draft: true, can_publish: false },
        },
      },
    })
    mocked.submissionService.createSessionRecordVersion.mockResolvedValue({
      data: {
        new_version: {
          new_local_record_id: 10,
        },
      },
    })

    const wrapper = mount(RecordDetailView, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
          LoadingSpinner: true,
          Alert: true,
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Published Record')
    expect(wrapper.text()).toContain('museum-network')
    expect(wrapper.text()).toContain('Create New Version Draft')
    expect(wrapper.text()).not.toContain('3D Preview')

    const versionButton = wrapper.findAll('button').find((button) => button.text().includes('Create New Version Draft'))
    await versionButton.trigger('click')
    await flushPromises()

    expect(global.confirm).toHaveBeenCalled()
    expect(mocked.submissionService.createSessionRecordVersion).toHaveBeenCalledWith(42, 9, { publish: false })
    expect(mocked.toast.success).toHaveBeenCalledWith('New version draft created as local record #10')
  })

  it('shows a lazy inline 3D preview only after the user loads it', async () => {
    mocked.submissionService.getSessionRecordDetail.mockResolvedValue({
      data: {
        record: {
          local_record_id: 9,
          record_title: 'Previewable Model',
          record_status: 'published',
          source_file_name: 'model.glb',
          provenance: {},
          files: [],
          processing: {},
          record_metadata: {},
          model_preview: {
            is_3d_record: true,
            can_inline_preview: true,
            url: 'https://zenodo.org/api/records/9/files/model.glb/content',
            filename: 'model.glb',
            format: 'glb',
            source: 'zenodo_direct_file',
            reason: null,
          },
        },
        health: {},
        lineage: {},
        zenodo_status: { summary: {}, communities: [], actions: {} },
      },
    })

    const wrapper = mount(RecordDetailView, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
          LoadingSpinner: true,
          Alert: true,
          PlaygroundModelViewer: {
            props: ['src', 'alt'],
            template: '<div data-testid="model-viewer">{{ src }} {{ alt }}</div>',
          },
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('3D Preview')
    expect(wrapper.text()).toContain('Inline preview is available')
    expect(wrapper.find('[data-testid="model-viewer"]').exists()).toBe(false)

    const loadButton = wrapper.findAll('button').find((button) => button.text() === 'Load 3D Preview')
    await loadButton.trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="model-viewer"]').text()).toContain('https://zenodo.org/api/records/9/files/model.glb/content')
    expect(wrapper.find('[data-testid="model-viewer"]').text()).toContain('Previewable Model')
  })

  it('shows fallback messaging for 3D records without inline preview support', async () => {
    mocked.submissionService.getSessionRecordDetail.mockResolvedValue({
      data: {
        record: {
          local_record_id: 9,
          record_title: 'OBJ Model',
          record_status: 'published',
          source_file_name: 'model.obj',
          provenance: {},
          files: [],
          processing: {},
          record_metadata: {},
          model_preview: {
            is_3d_record: true,
            can_inline_preview: false,
            url: '',
            filename: 'model.obj',
            format: 'obj',
            source: null,
            reason: 'inline_preview_unsupported_format',
          },
        },
        health: {},
        lineage: {},
        zenodo_status: { summary: {}, communities: [], actions: {} },
      },
    })

    const wrapper = mount(RecordDetailView, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
          LoadingSpinner: true,
          Alert: true,
          PlaygroundModelViewer: true,
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('3D Preview')
    expect(wrapper.text()).toContain('Inline 3D preview is not available')
    expect(wrapper.text()).toContain('This 3D format falls back to direct file access.')
  })
})
