import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RouterLinkStub } from './helpers/router.mjs'

const mocked = vi.hoisted(() => ({
  router: {
    push: vi.fn(),
  },
  route: {
    path: '/dashboard',
  },
  authStore: {
    token: 'token',
    user: {
      id: 1,
      email: 'admin@example.com',
      role: 'admin',
      groups: [],
    },
    institutions: [{ id: 9, name: 'Museum Network' }],
    logout: vi.fn(),
    hasCapability: vi.fn(() => false),
    hasGroup: vi.fn(() => false),
  },
  notificationStore: {
    startPolling: vi.fn(),
    stopPolling: vi.fn(),
    reset: vi.fn(),
  },
  issueDraft: {
    buildIssueDraftContext: vi.fn(() => ({ route: '/dashboard' })),
    saveIssueDraftContext: vi.fn(),
  },
}))

vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRoute: () => mocked.route,
    useRouter: () => mocked.router,
  }
})

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => mocked.authStore,
}))

vi.mock('@/stores/notifications', () => ({
  useNotificationStore: () => mocked.notificationStore,
}))

vi.mock('@/utils/issueDraft', () => mocked.issueDraft)

import MainLayout from '../src/components/layout/MainLayout.vue'

describe('MainLayout', () => {
  beforeEach(() => {
    Object.values(mocked.router).forEach((fn) => fn.mockReset())
    mocked.authStore.logout.mockReset()
    mocked.authStore.hasCapability.mockClear()
    mocked.authStore.hasGroup.mockClear()
    Object.values(mocked.notificationStore).forEach((fn) => fn.mockReset())
    mocked.issueDraft.buildIssueDraftContext.mockClear()
    mocked.issueDraft.saveIssueDraftContext.mockClear()
    mocked.route.path = '/dashboard'
    global.fetch = vi.fn().mockResolvedValue({
      json: vi.fn().mockResolvedValue({
        success: true,
        data: {
          version: '1.2.3',
          timestamp: '2026-04-10T09:00:00Z',
        },
      }),
    })
  })

  it('renders admin navigation, loads version info, and handles report/logout actions', async () => {
    const wrapper = mount(MainLayout, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
          RouterView: { template: '<div data-testid="router-view" />' },
        },
      },
    })
    await flushPromises()

    expect(global.fetch).toHaveBeenCalledWith('/api/v1/admin/version', {
      headers: {
        Authorization: 'Bearer token',
      },
    })
    expect(wrapper.text()).toContain('Admin')
    expect(wrapper.text()).toContain('Settings')
    expect(wrapper.text()).toContain('Admin Panel')
    expect(wrapper.text()).toContain('Institutions')
    expect(wrapper.text()).toContain('Developer')
    expect(mocked.notificationStore.startPolling).toHaveBeenCalled()

    const reportButton = wrapper.findAll('a').find((node) => node.text() === 'Report Issue')
    await reportButton.trigger('click')
    expect(mocked.issueDraft.buildIssueDraftContext).toHaveBeenCalled()
    expect(mocked.issueDraft.saveIssueDraftContext).toHaveBeenCalledWith({ route: '/dashboard' })
    expect(mocked.router.push).toHaveBeenCalledWith('/issues/report')

    const logoutButton = wrapper.findAll('button').find((node) => node.text() === 'Logout')
    await logoutButton.trigger('click')
    expect(mocked.notificationStore.reset).toHaveBeenCalledTimes(1)
    expect(mocked.authStore.logout).toHaveBeenCalledTimes(1)
    expect(mocked.router.push).toHaveBeenLastCalledWith('/login')
  })
})
