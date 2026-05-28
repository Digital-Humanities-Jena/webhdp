import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  adminService: {
    getSessionMonitoring: vi.fn(),
    terminateMonitoredSession: vi.fn(),
    terminateMonitoredAllocation: vi.fn(),
  },
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('@/services/admin.service', () => ({ default: mocked.adminService }))
vi.mock('@/composables/useToast', () => ({ useToast: () => mocked.toast }))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: { session_id: '12' } }) }))

import AdminSessionMonitoringView from '../src/views/admin/AdminSessionMonitoringView.vue'

describe('AdminSessionMonitoringView', () => {
  beforeEach(() => {
    Object.values(mocked.adminService).forEach((fn) => fn.mockReset())
    Object.values(mocked.toast).forEach((fn) => fn.mockReset())
    mocked.adminService.getSessionMonitoring.mockResolvedValue({
      data: {
        summary: { running_sessions: 1, active_hpc_allocations: 1, global_hpc_limit: 3 },
        sessions: [
          {
            id: 12,
            status: 'processing',
            file_count: 4,
            updated_at: '2026-05-04T12:00:00Z',
            user: { email: 'runner@example.com' },
          },
        ],
        allocations: [
          {
            allocation_id: 'abcdef12-3456',
            user: { email: 'runner@example.com' },
            session_id: 12,
            status: 'running',
            node_name: 'gpu-01',
          },
        ],
      },
    })
    mocked.adminService.terminateMonitoredSession.mockResolvedValue({ data: {} })
    mocked.adminService.terminateMonitoredAllocation.mockResolvedValue({ data: {} })
  })

  it('renders monitoring data and terminates sessions and allocations', async () => {
    const wrapper = mount(AdminSessionMonitoringView)
    await flushPromises()

    expect(wrapper.text()).toContain('Global HPC limit')
    expect(wrapper.text()).toContain('runner@example.com')
    expect(wrapper.text()).toContain('gpu-01')

    const terminateButtons = wrapper.findAll('button').filter((button) => button.text() === 'Terminate')
    await terminateButtons[0].trigger('click')
    await flushPromises()
    expect(mocked.adminService.terminateMonitoredSession).toHaveBeenCalledWith(12)

    await terminateButtons[1].trigger('click')
    await flushPromises()
    expect(mocked.adminService.terminateMonitoredAllocation).toHaveBeenCalledWith('abcdef12-3456')
  })
})
