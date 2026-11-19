import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  service: {
    getMyStatus: vi.fn(),
    submitRequest: vi.fn(),
  },
  hpcLink: {
    listReservations: vi.fn(), getStatus: vi.fn(), listMyAllocations: vi.fn(),
    getAllocation: vi.fn(), releaseAllocation: vi.fn(),
  },
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('@/services/hpcResourceRequest.service', () => ({ default: mocked.service }))
vi.mock('@/services/hpcLink.service', () => ({ default: mocked.hpcLink }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 7 } }) }))
vi.mock('@/composables/useToast', () => ({ useToast: () => mocked.toast }))

import HpcResourceRequestView from '../src/views/hpc/HpcResourceRequestView.vue'

describe('HpcResourceRequestView', () => {
  beforeEach(() => {
    Object.values(mocked.service).forEach((fn) => fn.mockReset())
    Object.values(mocked.hpcLink).forEach((fn) => fn.mockReset())
    Object.values(mocked.toast).forEach((fn) => fn.mockReset())
    mocked.service.getMyStatus.mockResolvedValue({
      data: {
        profile_defaults: { full_name: 'Ada Lovelace', affiliation: 'Analytical Institute' },
        use_cases: ['3D Models', 'Photographies', 'Historical Data', 'Documents', 'Other'],
        hpc: { has_access: false, latest_request: null },
      },
    })
    mocked.service.submitRequest.mockResolvedValue({ data: { request: { status: 'pending' } } })
    mocked.hpcLink.getStatus.mockResolvedValue({ data: { quota: { active: 0, active_limit: 1, queued: 1, queued_limit: 2, max_gpu_count: 1, max_duration_minutes: 360 } } })
    mocked.hpcLink.listReservations.mockResolvedValue({ data: { reservations: [] } })
    mocked.hpcLink.listMyAllocations.mockResolvedValue({ data: { allocations: [] } })
  })

  it('prefills account fields and submits selected use cases', async () => {
    const wrapper = mount(HpcResourceRequestView)
    await flushPromises()

    expect(wrapper.get('input[type="text"]').element.value).toBe('Ada Lovelace')
    await wrapper.findAll('input[type="checkbox"]')[0].setValue(true)
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()

    expect(mocked.service.submitRequest).toHaveBeenCalledWith({
      full_name: 'Ada Lovelace',
      affiliation: 'Analytical Institute',
      use_cases: ['3D Models'],
      notes: '',
    })
  })

  it('locks the request form when HPC access is already enabled', async () => {
    mocked.service.getMyStatus.mockResolvedValue({
      data: {
        profile_defaults: { full_name: 'Ada Lovelace', affiliation: 'Analytical Institute' },
        use_cases: ['3D Models', 'Photographies', 'Historical Data', 'Documents', 'Other'],
        hpc: {
          has_access: true,
          latest_request: {
            status: 'approved',
            submitted_at: '2026-05-04T12:00:00Z',
          },
        },
      },
    })

    const wrapper = mount(HpcResourceRequestView)
    await flushPromises()

    expect(wrapper.text()).toContain('HPC access is enabled')
    expect(wrapper.text()).toContain('Access: Enabled')
    expect(wrapper.find('form').exists()).toBe(false)
  })

  it('shows personal limits and lets an owner cancel a queued request after access is removed', async () => {
    const allocation = { allocation_id: 'request-42', session_id: 12, purpose: 'workflow', status: 'queued', can_release: true }
    mocked.hpcLink.listMyAllocations.mockResolvedValueOnce({ data: { allocations: [allocation] } })
    mocked.hpcLink.getAllocation.mockResolvedValue({ data: { allocation } })
    mocked.hpcLink.releaseAllocation.mockResolvedValue({ data: { allocation: { ...allocation, status: 'released' } } })
    const wrapper = mount(HpcResourceRequestView)
    await flushPromises()

    expect(wrapper.text()).toContain('Requests waiting in WebHDP')
    expect(wrapper.text()).toContain('Workflow allocation for session 12')
    expect(mocked.hpcLink.getAllocation).toHaveBeenCalledWith('request-42', expect.any(Object))
    await wrapper.findAll('button').find(button => button.text() === 'Cancel request').trigger('click')
    await flushPromises()

    expect(mocked.hpcLink.releaseAllocation).toHaveBeenCalledWith('request-42', expect.any(Object))
    expect(wrapper.text()).toContain('Request cancelled.')
    expect(wrapper.text()).toContain('You have no queued or active allocations.')
    wrapper.unmount()
  })
})
