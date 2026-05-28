import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RouterLinkStub } from './helpers/router.mjs'

const mocked = vi.hoisted(() => ({
  authStore: {
    token: null,
    fetchCurrentUser: vi.fn(),
    logout: vi.fn(),
  },
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => mocked.authStore,
}))

import App from '../src/App.vue'

describe('App bootstrap', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/')
    mocked.authStore.token = null
    mocked.authStore.fetchCurrentUser.mockReset()
    mocked.authStore.logout.mockReset()
  })

  it('fetches the current user on mount when a token exists and logs out on failure', async () => {
    window.history.pushState({}, '', '/dashboard')
    mocked.authStore.token = 'token'
    mocked.authStore.fetchCurrentUser.mockRejectedValue(new Error('expired'))

    mount(App, {
      global: {
        stubs: {
          RouterView: { template: '<div data-testid="router-view" />' },
          RouterLink: RouterLinkStub,
          ToastContainer: { template: '<div data-testid="toast-container" />' },
        },
      },
    })
    await flushPromises()

    expect(mocked.authStore.fetchCurrentUser).toHaveBeenCalledTimes(1)
    expect(mocked.authStore.logout).toHaveBeenCalledTimes(1)
  })

  it('does not fetch the current user when there is no token', async () => {
    mount(App, {
      global: {
        stubs: {
          RouterView: { template: '<div data-testid="router-view" />' },
          RouterLink: RouterLinkStub,
          ToastContainer: { template: '<div data-testid="toast-container" />' },
        },
      },
    })
    await flushPromises()

    expect(mocked.authStore.fetchCurrentUser).not.toHaveBeenCalled()
  })

  it('shows the storage notice once and skips auth bootstrap on legal pages', async () => {
    window.history.pushState({}, '', '/privacy')
    mocked.authStore.token = 'token'

    const wrapper = mount(App, {
      global: {
        stubs: {
          RouterView: { template: '<div data-testid="router-view" />' },
          RouterLink: RouterLinkStub,
          ToastContainer: { template: '<div data-testid="toast-container" />' },
        },
      },
    })
    await flushPromises()

    expect(mocked.authStore.fetchCurrentUser).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('does not use non-essential tracking cookies')

    await wrapper.get('button').trigger('click')
    expect(localStorage.getItem('webhdp_cookie_notice_v1')).toBe('accepted')
    expect(wrapper.text()).not.toContain('does not use non-essential tracking cookies')
  })
})
