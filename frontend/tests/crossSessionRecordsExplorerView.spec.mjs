import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RouterLinkStub } from './helpers/router.mjs'

const mocked = vi.hoisted(() => ({
  submissionService: {
    exploreRecords: vi.fn(),
    importHdpc: vi.fn(),
  },
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

vi.mock('@/services/submission.service.js', () => ({ default: mocked.submissionService }))
vi.mock('@/composables/useToast', () => ({ useToast: () => mocked.toast }))

import CrossSessionRecordsExplorerView from '../src/views/dashboard/CrossSessionRecordsExplorerView.vue'

describe('CrossSessionRecordsExplorerView', () => {
  beforeEach(() => {
    Object.values(mocked.submissionService).forEach((fn) => fn.mockReset())
    Object.values(mocked.toast).forEach((fn) => fn.mockReset())
    mocked.submissionService.exploreRecords.mockResolvedValue({
      data: {
        records: [],
        summary: {
          sessions_scanned: 0,
          records_found: 0,
          records_filtered: 0,
          records_returned: 0,
          failed_sessions: 0,
          degraded_sessions: 0,
        },
        session_warnings: [],
      },
    })
  })

  it('explains that sanitized shared exports import as explorer-only sessions', async () => {
    const wrapper = mount(CrossSessionRecordsExplorerView)
    await flushPromises()

    expect(wrapper.text()).toContain('Sanitized shared exports import as explorer-only sessions')
  })

  it('preserves each record environment when opening an encoded dataset workspace', async () => {
    mocked.submissionService.exploreRecords.mockResolvedValue({ data: {
      records: [true, false].map((isSandbox, index) => ({
        session_id: 27 + index, local_record_id: 1, dataset_key: '100%_dataset', is_sandbox: isSandbox,
        record_title: 'Terrain', record_status: 'draft',
      })), summary: {}, session_warnings: [],
    } })
    const wrapper = mount(CrossSessionRecordsExplorerView, { global: { stubs: { RouterLink: RouterLinkStub } } })
    await flushPromises()
    const links = wrapper.findAll('a').filter(link => link.text() === 'Dataset Workspace')
    expect(links.map(link => link.attributes('href'))).toEqual([
      '/datasets/100%25_dataset?environment=sandbox', '/datasets/100%25_dataset?environment=production',
    ])
    wrapper.unmount()
  })
})
