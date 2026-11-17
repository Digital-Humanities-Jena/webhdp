import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RouterLinkStub } from './helpers/router.mjs'

const mocked = vi.hoisted(() => ({
  router: {
    push: vi.fn(),
  },
  route: {
    params: {},
  },
  authStore: {
    login: vi.fn(),
    verifyLoginCode: vi.fn(),
    verifyRecoveryCode: vi.fn(),
    resendLoginCode: vi.fn(),
    register: vi.fn(),
  },
  axios: {
    get: vi.fn(),
  },
}))

vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRouter: () => mocked.router,
    useRoute: () => mocked.route,
  }
})

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => mocked.authStore,
}))

vi.mock('axios', () => ({
  default: mocked.axios,
}))

import LoginView from '../src/views/auth/LoginView.vue'
import RegisterView from '../src/views/auth/RegisterView.vue'
import VerifyEmailView from '../src/views/auth/VerifyEmailView.vue'

describe('auth views', () => {
  beforeEach(() => {
    Object.values(mocked.router).forEach((fn) => fn.mockReset())
    Object.values(mocked.authStore).forEach((fn) => fn.mockReset())
    Object.values(mocked.axios).forEach((fn) => fn.mockReset())
    mocked.route.params = {}
    mocked.route.query = {}
  })

  it('submits login credentials, verifies the MFA code, and redirects to the upload workflow', async () => {
    mocked.authStore.login.mockResolvedValue({
      data: {
        mfa_required: true,
        mfa_token: 'mfa-token',
        masked_email: 'us***r@example.com',
      },
    })
    mocked.authStore.verifyLoginCode.mockResolvedValue({ data: { access_token: 'access-token' } })

    const wrapper = mount(LoginView, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })

    await wrapper.get('#email').setValue('user@example.com')
    await wrapper.get('#password').setValue('secret')
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()

    expect(mocked.authStore.login).toHaveBeenCalledWith('user@example.com', 'secret')
    expect(mocked.router.push).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('us***r@example.com')

    await wrapper.get('#mfa-code').setValue('123456')
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()

    expect(mocked.authStore.verifyLoginCode).toHaveBeenCalledWith('mfa-token', '123456')
    expect(mocked.router.push).toHaveBeenCalledWith('/workflow/upload')
  })

  it('resumes a local WebHDP-Link consent request after login', async () => {
    mocked.route.query = { redirect: '/link/authorize?client_id=piano&state=opaque' }
    mocked.authStore.login.mockResolvedValue({ data: { access_token: 'access-token' } })
    const wrapper = mount(LoginView, { global: { stubs: { RouterLink: RouterLinkStub } } })
    await wrapper.get('#email').setValue('user@example.com')
    await wrapper.get('#password').setValue('secret')
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()
    expect(mocked.router.push).toHaveBeenCalledWith('/link/authorize?client_id=piano&state=opaque')
    wrapper.unmount()
  })

  it('rejects an external post-login redirect', async () => {
    mocked.route.query = { redirect: 'https://untrusted.example/link/authorize?state=opaque' }
    mocked.authStore.login.mockResolvedValue({ data: { access_token: 'access-token' } })
    const wrapper = mount(LoginView, { global: { stubs: { RouterLink: RouterLinkStub } } })
    await wrapper.get('#email').setValue('user@example.com')
    await wrapper.get('#password').setValue('secret')
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()
    expect(mocked.router.push).toHaveBeenCalledWith('/workflow/upload')
    wrapper.unmount()
  })

  it('resends MFA codes and keeps failed verification on the code step', async () => {
    mocked.authStore.login.mockResolvedValue({
      data: {
        mfa_required: true,
        mfa_token: 'mfa-token',
        masked_email: 'us***r@example.com',
      },
    })
    mocked.authStore.resendLoginCode.mockResolvedValue({
      data: {
        mfa_required: true,
        mfa_token: 'mfa-token',
        masked_email: 'us***r@example.com',
      },
    })
    mocked.authStore.verifyLoginCode.mockRejectedValue({
      error: {
        code: 'MFA_CODE_INVALID',
        message: 'Invalid verification code',
      },
    })

    const wrapper = mount(LoginView, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })

    await wrapper.get('#email').setValue('user@example.com')
    await wrapper.get('#password').setValue('secret')
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()

    await wrapper.get('[data-testid="login-resend-code"]').trigger('click')
    await flushPromises()
    expect(mocked.authStore.resendLoginCode).toHaveBeenCalledWith('mfa-token')

    await wrapper.get('#mfa-code').setValue('000000')
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.text()).toContain('Invalid verification code')
    expect(wrapper.find('#mfa-code').exists()).toBe(true)
    expect(mocked.router.push).not.toHaveBeenCalled()
  })

  it('can verify login with a recovery code instead of an email code', async () => {
    mocked.authStore.login.mockResolvedValue({
      data: {
        mfa_required: true,
        mfa_token: 'mfa-token',
        masked_email: 'us***r@example.com',
      },
    })
    mocked.authStore.verifyRecoveryCode.mockResolvedValue({ data: { access_token: 'access-token' } })

    const wrapper = mount(LoginView, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })

    await wrapper.get('#email').setValue('user@example.com')
    await wrapper.get('#password').setValue('secret')
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()

    await wrapper.get('[data-testid="login-use-recovery-code"]').trigger('click')
    await wrapper.get('#recovery-code').setValue('ABCD-EFGH-IJKL')
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()

    expect(mocked.authStore.verifyRecoveryCode).toHaveBeenCalledWith('mfa-token', 'ABCD-EFGH-IJKL')
    expect(mocked.authStore.verifyLoginCode).not.toHaveBeenCalled()
    expect(mocked.router.push).toHaveBeenCalledWith('/workflow/upload')
  })

  it('renders register validation and success states', async () => {
    mocked.authStore.register.mockResolvedValue({ message: 'Check your inbox.' })
    const wrapper = mount(RegisterView, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })

    await wrapper.get('#email').setValue('user@example.com')
    await wrapper.get('#password').setValue('password-1')
    await wrapper.get('#confirm-password').setValue('password-2')
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.text()).toContain('Passwords do not match')

    await wrapper.get('#confirm-password').setValue('password-1')
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()

    expect(mocked.authStore.register).toHaveBeenCalledWith('user@example.com', 'password-1')
    expect(wrapper.text()).toContain('Account created!')
    expect(wrapper.text()).toContain('Check your inbox.')
  })

  it('verifies email tokens and handles missing-token failures', async () => {
    mocked.route.params = { token: 'verify-token' }
    mocked.axios.get.mockResolvedValue({ data: { ok: true } })

    const successWrapper = mount(VerifyEmailView, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })
    await flushPromises()

    expect(mocked.axios.get).toHaveBeenCalledWith('/api/v1/auth/verify-email/verify-token')
    expect(successWrapper.text()).toContain('Email verified successfully!')

    mocked.route.params = {}
    const errorWrapper = mount(VerifyEmailView, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })
    await flushPromises()

    expect(errorWrapper.text()).toContain('No verification token provided.')
  })
})
