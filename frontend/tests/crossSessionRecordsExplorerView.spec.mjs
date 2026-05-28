import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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
})
