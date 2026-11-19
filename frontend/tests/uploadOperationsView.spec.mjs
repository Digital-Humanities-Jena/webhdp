import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  submissionService: {
    listUploadOperations: vi.fn(),
  },
}))

vi.mock('@/services/submission.service', () => ({ default: mocked.submissionService }))

import UploadOperationsView from '../src/views/dashboard/UploadOperationsView.vue'

describe('UploadOperationsView', () => {
  beforeEach(() => {
    mocked.submissionService.listUploadOperations.mockReset()
  })

  it('reopens workflow after upload completion instead of implying records already exist', async () => {
    mocked.submissionService.listUploadOperations.mockResolvedValue({
      data: {
        operations: [
          {
            session_id: 25,
            status: 'scanned',
            updated_at: '2026-03-31T10:00:00Z',
            storage_mode: 'cloud_backup',
            workspace: { type: 'institution', institution: { name: 'Museum Grid' } },
            publishing_context: { effective_credential_source: 'institution' },
            workflow_hint: {
              can_resume_workflow: true,
              resume_route: '/workflow/files',
              resume_label: 'Resume File Review',
            },
            progress: {
              current_stage: 'completed',
              status_message: 'Scan and metadata registration complete',
              processed_count: 4,
              total_files: 4,
              failed_count: 0,
              percent: 100,
            },
          },
        ],
      },
    })

    const wrapper = mount(UploadOperationsView, {
      global: {
        stubs: {
          RouterLink: {
            props: ['to'],
            template: '<a :data-to="JSON.stringify(to)"><slot /></a>',
          },
        },
      },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('Records are created when you start processing.')
    expect(wrapper.text()).toContain('Ready to review')
    expect(wrapper.text()).toContain('Resume File Review')
    expect(wrapper.text()).not.toContain('View Records')
  })
})
