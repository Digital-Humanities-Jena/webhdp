import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { activateTestPinia } from './helpers/pinia.mjs'

const mocked = vi.hoisted(() => ({
  fileService: {
    getNodes: vi.fn(),
    listCloudDownloads: vi.fn(),
    getCloudDownloadUrl: vi.fn(),
    updateWorkflowState: vi.fn(),
    getWorkflowState: vi.fn(),
  },
  router: {
    push: vi.fn(),
    replace: vi.fn(),
  },
  route: {
    query: {},
  },
}))

vi.mock('@/services/file.service', () => ({ default: mocked.fileService }))
vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRoute: () => mocked.route,
    useRouter: () => mocked.router,
  }
})

import { useWorkflowStore } from '../src/stores/workflow.js'
import FilesView from '../src/views/workflow/FilesView.vue'

describe('FilesView', () => {
  beforeEach(() => {
    Object.values(mocked.fileService).forEach((fn) => fn.mockReset())
    mocked.router.push.mockReset()
    mocked.router.replace.mockReset()
    mocked.route.query = {}

    activateTestPinia()

    mocked.fileService.getNodes.mockResolvedValue({ data: { nodes: [] } })
    mocked.fileService.listCloudDownloads.mockResolvedValue({ data: { available: false, reason: 'Cloud download is unavailable.', items: [] } })
    mocked.fileService.getCloudDownloadUrl.mockResolvedValue({ data: { download_url: 'https://example.invalid/download' } })
    mocked.fileService.getWorkflowState.mockResolvedValue({ data: { state: {} } })
    mocked.fileService.updateWorkflowState.mockResolvedValue({ data: { ok: true } })
  })

  it('requires explicit batch selection instead of auto-selecting scanned bundles', async () => {
    const workflowStore = useWorkflowStore()
    workflowStore.setSessionId(15)
    workflowStore.setBatchMode(true)
    workflowStore.setUploadedFiles([
      { file_id: 101, name: 'model-one.glb', relative_path: 'model-one.glb', status: 'registered', children: [] },
      { file_id: 102, name: 'model-two.glb', relative_path: 'model-two.glb', status: 'registered', children: [] },
    ])
    workflowStore.setSelectedFiles([])

    const wrapper = mount(FilesView, {
      global: {
        stubs: {
          StepIndicator: true,
          ValidationModal: true,
        },
      },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('Select at least one model to continue.')
    expect(workflowStore.selectedFiles).toHaveLength(0)

    const selectAllButton = wrapper.findAll('button').find((button) => button.text() === 'Select all scanned bundles')
    await selectAllButton.trigger('click')
    await flushPromises()

    expect(workflowStore.selectedFiles).toHaveLength(2)
  })

  it('excludes prior outputs from review and clears stale output selections', async () => {
    const workflowStore = useWorkflowStore()
    workflowStore.setSessionId(15)
    const model = { file_id: 101, name: 'site.glb', file_type: 'primary_source', children: [
      { file_id: 102, name: 'site.tif', file_type: 'source', children: [] },
    ] }
    const output = { file_id: 103, name: 'site_georeferenced.glb', file_type: 'generated', children: [] }
    workflowStore.setUploadedFiles([model, output])
    workflowStore.setSelectedFiles([output])
    const wrapper = mount(FilesView, { global: { stubs: { StepIndicator: true, ValidationModal: true } } })
    await flushPromises()
    expect(wrapper.text()).not.toContain('site_georeferenced.glb')
    expect(workflowStore.selectedFiles).toHaveLength(0)
    await wrapper.findAll('button').find(button => button.text() === 'Select all scanned bundles').trigger('click')
    expect(workflowStore.selectedFiles.map(file => file.file_id)).toEqual([101])
    expect(workflowStore.selectedFiles[0].children[0].name).toBe('site.tif')
  })

  it('shows Cloud Storage download availability and opens provider URLs', async () => {
    const originalLocation = window.location
    const assign = vi.fn()
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...originalLocation, assign },
    })

    mocked.fileService.listCloudDownloads.mockResolvedValue({
      data: {
        available: true,
        reason: null,
        items: [
          {
            id: 7,
            original_filename: 'dataset.zip',
            label: 'Batch ZIP',
            can_download: true,
            availability_message: 'Dropbox mirror is available',
          },
        ],
      },
    })
    mocked.fileService.getCloudDownloadUrl.mockResolvedValue({
      data: { download_url: 'https://example.invalid/dataset.zip' },
    })

    const workflowStore = useWorkflowStore()
    workflowStore.setSessionId(22)
    workflowStore.setUploadedFiles([
      { file_id: 101, name: 'model-one.glb', relative_path: 'model-one.glb', status: 'registered', children: [] },
    ])

    const wrapper = mount(FilesView, {
      global: {
        stubs: {
          StepIndicator: true,
          ValidationModal: true,
        },
      },
    })

    await flushPromises()

    expect(wrapper.get('[data-testid="cloud-downloads-panel"]').text()).toContain('dataset.zip')
    expect(wrapper.get('[data-testid="cloud-downloads-panel"]').text()).toContain('Available')

    await wrapper.get('[data-testid="cloud-download-button"]').trigger('click')
    await flushPromises()

    expect(mocked.fileService.getCloudDownloadUrl).toHaveBeenCalledWith(22, 7)
    expect(assign).toHaveBeenCalledWith('https://example.invalid/dataset.zip')
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: originalLocation,
    })
  })

  it('shows the unavailable reason when no Cloud Storage mirror exists', async () => {
    mocked.fileService.listCloudDownloads.mockResolvedValue({
      data: {
        available: false,
        reason: 'Cloud download is unavailable because this session was created in HPC/local storage mode.',
        items: [],
      },
    })

    const workflowStore = useWorkflowStore()
    workflowStore.setSessionId(33)
    workflowStore.setUploadedFiles([])

    const wrapper = mount(FilesView, {
      global: {
        stubs: {
          StepIndicator: true,
          ValidationModal: true,
        },
      },
    })

    await flushPromises()

    expect(wrapper.get('[data-testid="cloud-downloads-reason"]').text()).toContain('HPC/local storage mode')
  })
})
