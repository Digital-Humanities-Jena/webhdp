import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RouterLinkStub } from './helpers/router.mjs'

const mocked = vi.hoisted(() => ({
  route: {
    params: {
      id: '14',
    },
  },
  submissionService: {
    getSubmission: vi.fn(),
    getSubmissionProgress: vi.fn(),
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

import SubmissionDetailView from '../src/views/dashboard/SubmissionDetailView.vue'

describe('SubmissionDetailView', () => {
  beforeEach(() => {
    Object.values(mocked.submissionService).forEach((fn) => fn.mockReset())
    mocked.route.params = { id: '14' }
    global.URL.createObjectURL = vi.fn(() => 'blob:submission')
    global.URL.revokeObjectURL = vi.fn()
  })

  it('renders completed submission details and exports the JSON result', async () => {
    mocked.submissionService.getSubmission.mockResolvedValue({
      data: {
        submission: {
          id: 14,
          status: 'completed',
          created_at: '2026-04-10T08:00:00Z',
          pipeline_id: 'render',
          session_id: 42,
          result: JSON.stringify({
            links: { html: 'https://zenodo.org/records/14' },
            doi: '10.5072/example',
            timings: { upload: 1.23 },
            mirrored_path: '/tmp/mirror',
          }),
        },
        zenodo_response: [{ id: 14 }],
        metadata: { title: 'Completed Submission' },
        files: [{ filename: 'model.glb', path: '/tmp/model.glb' }],
        file_summary: {
          selected_file_count: 1,
          session_file_count: 2,
          available_not_processed_count: 1,
        },
        available_files: [{ filename: 'extra.glb', path: '/tmp/extra.glb' }],
      },
    })

    const appendChildSpy = vi.spyOn(document.body, 'appendChild')
    const wrapper = mount(SubmissionDetailView, {
      global: {
        stubs: {
          LoadingSpinner: true,
          Alert: true,
          RouterLink: RouterLinkStub,
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Submission #14')
    expect(wrapper.text()).toContain('Performance Metrics')
    expect(wrapper.text()).toContain('Mirrored to Local Storage')
    expect(wrapper.text()).toContain('Available but Not Processed (1)')

    const downloadButton = wrapper.findAll('button').find((button) => button.text().includes('Download JSON'))
    await downloadButton.trigger('click')

    expect(global.URL.createObjectURL).toHaveBeenCalledTimes(1)
    expect(appendChildSpy).toHaveBeenCalled()
  })
})
