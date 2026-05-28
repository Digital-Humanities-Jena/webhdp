import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RouterLinkStub } from './helpers/router.mjs'

const mocked = vi.hoisted(() => ({
  route: {
    params: {
      sessionId: '42',
    },
  },
  router: {
    push: vi.fn(),
    back: vi.fn(),
  },
  submissionService: {
    getSessionRecords: vi.fn(),
    getSessionWorkspaceSummary: vi.fn(),
    listSessionBatchOperations: vi.fn(),
    getSessionBatchOperation: vi.fn(),
    launchSessionBatchOperation: vi.fn(),
    createSessionRecordVersion: vi.fn(),
  },
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
  buildDatasetRoute: vi.fn(() => '/datasets/dataset-42'),
}))

vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRoute: () => mocked.route,
    useRouter: () => mocked.router,
  }
})

vi.mock('@/services/submission.service.js', () => ({
  default: mocked.submissionService,
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => mocked.toast,
}))

vi.mock('@/utils/datasetKey.js', () => ({
  buildDatasetRoute: mocked.buildDatasetRoute,
}))

import SessionRecordsView from '../src/views/dashboard/SessionRecordsView.vue'

describe('SessionRecordsView', () => {
  beforeEach(() => {
    Object.values(mocked.router).forEach((fn) => fn.mockReset())
    Object.values(mocked.submissionService).forEach((fn) => fn.mockReset())
    Object.values(mocked.toast).forEach((fn) => fn.mockReset())
    mocked.buildDatasetRoute.mockClear()
    mocked.route.params = { sessionId: '42' }
    Object.defineProperty(global.navigator, 'clipboard', {
      value: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
      configurable: true,
    })
    global.URL.createObjectURL = vi.fn(() => 'blob:session-records')
    global.URL.revokeObjectURL = vi.fn()
  })

  it('renders session record intelligence and copies Zenodo IDs', async () => {
    mocked.submissionService.getSessionRecords.mockResolvedValue({
      data: {
        session: {
          status: 'completed',
          access_mode: 'default',
          origin_type: 'workflow',
          permissions: {
            can_manage: true,
          },
        },
        summary: {
          total_records: 1,
          processed_records: 1,
          published_records: 1,
        },
        provenance: {
          dataset_key: 'dataset-42',
          mapping_field_count: 2,
        },
        warnings: [],
        records: [
          {
            local_record_id: 9,
            record_title: 'Published Model',
            record_status: 'published',
            zenodo_record_id: 701,
            provenance: {
              mapping_field_count: 2,
            },
            updated_at: '2026-04-10T09:00:00Z',
          },
        ],
      },
    })
    mocked.submissionService.getSessionWorkspaceSummary.mockResolvedValue({
      data: {
        project_info: { project_name: 'Museum Session' },
        configuration_hints: { batch_entity: 'record' },
        record_summary: { prepared_count: 0, draft_count: 1, published_count: 1 },
        upload_summary: { uploadable_item_count: 2 },
        operations: {
          actionable_operations: {
            create_drafts: { count: 1 },
            discard_drafts: { count: 0 },
            upload_files: { count: 1 },
            publish_records: { count: 1 },
            remove_files: { count: 0 },
          },
        },
      },
    })
    mocked.submissionService.listSessionBatchOperations.mockResolvedValue({
      data: {
        tasks: [],
      },
    })

    const wrapper = mount(SessionRecordsView, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
          LoadingSpinner: true,
          Alert: true,
          SessionGovernanceDrawer: {
            props: ['open', 'session'],
            template: '<div data-testid="governance-drawer" />',
          },
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Workspace Intelligence')
    expect(wrapper.text()).toContain('Published Model')
    expect(wrapper.text()).toContain('Dataset Workspace')
    expect(mocked.buildDatasetRoute).toHaveBeenCalledWith('dataset-42')

    const copyButton = wrapper.findAll('button').find((button) => button.text() === 'Copy Zenodo IDs')
    await copyButton.trigger('click')
    await flushPromises()

    expect(global.navigator.clipboard.writeText).toHaveBeenCalledWith('701')
    expect(mocked.toast.success).toHaveBeenCalledWith('Zenodo IDs copied to clipboard')
  })
})
