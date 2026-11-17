import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  adminService: {
    listHpcResourceRequests: vi.fn(),
    approveHpcResourceRequest: vi.fn(),
    rejectHpcResourceRequest: vi.fn(),
    listHpcAccessUsers: vi.fn(),
    revokeHpcAccess: vi.fn(),
    listHpcReservations: vi.fn(),
    registerHpcReservation: vi.fn(),
    updateHpcReservation: vi.fn(),
  },
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('@/services/admin.service', () => ({ default: mocked.adminService }))
vi.mock('@/composables/useToast', () => ({ useToast: () => mocked.toast }))

import AdminHpcAccessView from '../src/views/admin/AdminHpcAccessView.vue'

describe('AdminHpcAccessView', () => {
  beforeEach(() => {
    Object.values(mocked.adminService).forEach((fn) => fn.mockReset())
    Object.values(mocked.toast).forEach((fn) => fn.mockReset())
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    mocked.adminService.listHpcResourceRequests.mockResolvedValue({
      data: {
        requests: [
          {
            id: 12,
            full_name: 'Ada Lovelace',
            affiliation: 'Analytical Institute',
            use_cases: ['3D Models'],
            status: 'pending',
            submitted_at: '2026-05-04T12:00:00Z',
            user: { email: 'ada@example.com' },
          },
        ],
      },
    })
    mocked.adminService.listHpcAccessUsers.mockResolvedValue({
      data: {
        users: [
          { id: 1, email: 'admin@example.com', hpc_access_source: 'implicit_admin' },
          { id: 2, email: 'ada@example.com', hpc_access_source: 'explicit' },
        ],
      },
    })
    mocked.adminService.approveHpcResourceRequest.mockResolvedValue({ data: {} })
    mocked.adminService.revokeHpcAccess.mockResolvedValue({ data: {} })
    mocked.adminService.listHpcReservations.mockResolvedValue({ data: { reservations: [] } })
    mocked.adminService.registerHpcReservation.mockResolvedValue({ data: {} })
    mocked.adminService.updateHpcReservation.mockResolvedValue({ data: {} })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('approves pending requests and revokes explicit access', async () => {
    const wrapper = mount(AdminHpcAccessView)
    await flushPromises()

    expect(wrapper.text()).toContain('Ada Lovelace')
    await wrapper.findAll('button').find((button) => button.text() === 'Approve').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Approval note')
    await wrapper.find('textarea').setValue('Looks good')
    await wrapper.findAll('button').find((button) => button.text() === 'Approve request').trigger('click')
    await flushPromises()

    expect(mocked.adminService.approveHpcResourceRequest).toHaveBeenCalledWith(12, { comment: 'Looks good' })

    await wrapper.findAll('button').find((button) => button.text() === 'Accounts').trigger('click')
    await flushPromises()
    const revokeButtons = wrapper.findAll('button').filter((button) => button.text() === 'Revoke')
    await revokeButtons[1].trigger('click')
    await flushPromises()

    expect(mocked.adminService.revokeHpcAccess).toHaveBeenCalledWith(2)
  })

  it('registers a gateway reservation and edits its enabled access policy', async () => {
    const reservation = {
      reservation_id: 'webhdp-reservation', label: 'Live demo GPU', job_id: '98765', node_name: 'gpu017',
      gpu_type: 'a100', gpu_count: 1, cpus: 8, memory_mb: 65536, status: 'available', enabled: true,
      allowed_emails: ['presenter@example.org', 'operator@example.org'],
    }
    mocked.adminService.listHpcReservations
      .mockResolvedValueOnce({ data: { reservations: [] } })
      .mockResolvedValue({ data: { reservations: [reservation] } })
    const wrapper = mount(AdminHpcAccessView)
    const button = (name) => wrapper.findAll('button').find(candidate => candidate.text() === name)
    await button('Reserved GPUs').trigger('click')
    await flushPromises()

    const form = wrapper.get('[data-testid="admin-gpu-reservation-form"]')
    await form.get('input[autocomplete="off"]').setValue('gateway-reservation')
    await form.get('input[placeholder="Live presentation GPU"]').setValue('Live demo GPU')
    await form.get('textarea').setValue('Presenter@example.org, operator@example.org\n presenter@example.org')
    await form.trigger('submit')
    await flushPromises()
    expect(mocked.adminService.registerHpcReservation).toHaveBeenCalledWith({
      gateway_reservation_id: 'gateway-reservation', label: 'Live demo GPU',
      allowed_emails: ['presenter@example.org', 'operator@example.org'],
    })
    expect(wrapper.text()).toContain('Slurm job 98765')
    expect(wrapper.text()).toContain('1 A100 · 8 CPUs · 64 GiB RAM')

    await button('Edit access').trigger('click')
    await form.get('textarea').setValue('presenter@example.org')
    await form.trigger('submit')
    await flushPromises()
    expect(mocked.adminService.updateHpcReservation).toHaveBeenCalledWith('webhdp-reservation', {
      label: 'Live demo GPU', allowed_emails: ['presenter@example.org'],
    })

    await button('Disable access').trigger('click')
    await flushPromises()
    expect(mocked.adminService.updateHpcReservation).toHaveBeenLastCalledWith('webhdp-reservation', { enabled: false })
    wrapper.unmount()
  })
})
