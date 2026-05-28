import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RouterLinkStub } from './helpers/router.mjs'

const mocked = vi.hoisted(() => ({
  submissionService: {
    listSubmissions: vi.fn(),
  },
}))

vi.mock('@/services/submission.service.js', () => ({
  default: mocked.submissionService,
}))

import SubmissionsView from '../src/views/dashboard/SubmissionsView.vue'

describe('SubmissionsView', () => {
  beforeEach(() => {
    mocked.submissionService.listSubmissions.mockReset()
  })

  it('renders submission history rows and session record links', async () => {
    mocked.submissionService.listSubmissions.mockResolvedValue({
      data: {
        submissions: [
          {
            id: 14,
            pipeline_id: 'render',
            status: 'completed',
            created_at: '2026-04-10T08:00:00Z',
            session_id: 42,
          },
        ],
      },
    })

    const wrapper = mount(SubmissionsView, {
      global: {
        stubs: {
          LoadingSpinner: true,
          RouterLink: RouterLinkStub,
        },
      },
    })
    await flushPromises()

    expect(mocked.submissionService.listSubmissions).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('My Submissions')
    expect(wrapper.text()).toContain('render')
    expect(wrapper.text()).toContain('View Details')
    expect(wrapper.text()).toContain('Session Records')
  })
})
