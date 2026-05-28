import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  api: {
    get: vi.fn(),
    put: vi.fn(),
  },
  submissionService: {
    listAdminUploadOperations: vi.fn(),
    adminImportHdpcForUser: vi.fn(),
  },
  adminService: {
    getHpcLinkConfig: vi.fn(),
    resetUserRecovery: vi.fn(),
  },
  authStore: {
    user: {
      id: 1,
      email: 'admin@example.com',
      role: 'admin',
    },
    logout: vi.fn(),
  },
  systemStore: {
    resetSystem: vi.fn(),
  },
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  },
  router: {
    push: vi.fn(),
  },
}))

vi.mock('@/services/api', () => ({ default: mocked.api }))
vi.mock('@/services/submission.service.js', () => ({ default: mocked.submissionService }))
vi.mock('@/services/admin.service', () => ({ default: mocked.adminService }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => mocked.authStore }))
vi.mock('@/stores/system', () => ({ useSystemStore: () => mocked.systemStore }))
vi.mock('@/composables/useToast', () => ({ useToast: () => mocked.toast }))
vi.mock('vue-router', () => ({ useRouter: () => mocked.router }))

import AdminDashboardView from '../src/views/admin/AdminDashboardView.vue'

describe('AdminDashboardView account recovery', () => {
  beforeEach(() => {
    Object.values(mocked.api).forEach((fn) => fn.mockReset())
    Object.values(mocked.submissionService).forEach((fn) => fn.mockReset())
    Object.values(mocked.adminService).forEach((fn) => fn.mockReset())
    Object.values(mocked.toast).forEach((fn) => fn.mockReset())
    mocked.api.get.mockImplementation((url) => {
      if (url === '/admin/stats') {
        return Promise.resolve({ data: { total_users: 2, total_sessions: 0, pending_submissions: 0, completed_submissions: 0 } })
      }
      if (url === '/admin/submissions') {
        return Promise.resolve({ data: { submissions: [] } })
      }
      if (url === '/admin/users') {
        return Promise.resolve({
          data: {
            users: [
              {
                id: 1,
                email: 'admin@example.com',
                role: 'admin',
                capabilities: [],
                recovery_codes: { remaining_count: 0 },
                admin_recovery_codes: { remaining_count: 0 },
                force_password_change: false,
                last_recovery_reset_at: null,
              },
              {
                id: 2,
                email: 'user@example.com',
                role: 'user',
                capabilities: [],
                recovery_codes: { remaining_count: 2 },
                admin_recovery_codes: { remaining_count: 1 },
                force_password_change: true,
                last_recovery_reset_at: '2026-05-04T12:00:00',
              },
            ],
          },
        })
      }
      return Promise.resolve({ data: {} })
    })
    mocked.submissionService.listAdminUploadOperations.mockResolvedValue({ data: { operations: [] } })
    mocked.adminService.getHpcLinkConfig.mockResolvedValue({ data: { config: {} } })
    mocked.adminService.resetUserRecovery.mockResolvedValue({
      data: {
        temporary_password: 'temporary-password-1',
        recovery_code: 'ABCD-EFGH-IJKL',
        recovery_code_expires_at: '2026-05-05T00:00:00',
        user: {
          id: 2,
          email: 'user@example.com',
          role: 'user',
          capabilities: [],
          recovery_codes: { remaining_count: 1 },
          admin_recovery_codes: { remaining_count: 1 },
          force_password_change: true,
          last_recovery_reset_at: '2026-05-04T12:10:00',
        },
      },
    })
  })

  it('opens the recovery reset modal and displays returned one-time secrets', async () => {
    const wrapper = mount(AdminDashboardView, {
      global: {
        stubs: {
          RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' },
          LoadingSpinner: { template: '<div />' },
          VersionDetectionPolicyCard: { template: '<div />' },
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('2 user recovery codes available')
    expect(wrapper.text()).toContain('1 admin-issued one-time code pending')
    expect(wrapper.text()).toContain('Password change required')
    expect(wrapper.text()).toContain('Last reset')

    const buttons = wrapper.findAll('button').filter((button) => button.text() === 'Account recovery')
    expect(buttons).toHaveLength(2)
    await buttons[1].trigger('click')
    await wrapper.get('input[placeholder="Leave blank to generate"]').setValue('temporary-password-1')
    await wrapper.get('[data-testid="admin-recovery-submit"]').trigger('click')
    await flushPromises()

    expect(mocked.adminService.resetUserRecovery).toHaveBeenCalledWith(2, { temporary_password: 'temporary-password-1' })
    expect(wrapper.get('[data-testid="admin-recovery-result"]').text()).toContain('temporary-password-1')
    expect(wrapper.get('[data-testid="admin-recovery-result"]').text()).toContain('ABCD-EFGH-IJKL')
  })
})
