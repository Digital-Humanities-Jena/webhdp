import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RouterLinkStub } from './helpers/router.mjs'

const mocked = vi.hoisted(() => ({
  router: {
    push: vi.fn(),
    replace: vi.fn(),
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
    user: null,
  },
  authService: {
    resendVerification: vi.fn(),
    verifyEmail: vi.fn(),
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

vi.mock('@/services/auth.service', () => ({ default: mocked.authService }))

import LoginView from '../src/views/auth/LoginView.vue'
import RegisterView from '../src/views/auth/RegisterView.vue'
import VerifyEmailView from '../src/views/auth/VerifyEmailView.vue'

describe('auth views', () => {
  beforeEach(() => {
    Object.values(mocked.router).forEach((fn) => fn.mockReset())
    Object.values(mocked.authStore).filter((value) => typeof value === 'function').forEach((fn) => fn.mockReset())
    mocked.authStore.user = null
    Object.values(mocked.authService).forEach((fn) => fn.mockReset())
    mocked.route.params = {}
    mocked.route.query = {}
    mocked.route.hash = ''
    sessionStorage.clear()
  })

  it('submits login credentials, verifies the MFA code, and opens the dashboard', async () => {
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
    expect(mocked.router.push).toHaveBeenCalledWith('/dashboard')
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
    expect(mocked.router.push).toHaveBeenCalledWith('/dashboard')
    wrapper.unmount()
  })

  it.each(['/tutorial/3d', '/onboarding?tour=1', '/institution-invitation'])('returns to the learning route %s after login', async (redirect) => {
    mocked.route.query = { redirect }
    mocked.authStore.login.mockResolvedValue({ data: { access_token: 'access-token' } })
    const wrapper = mount(LoginView, { global: { stubs: { RouterLink: RouterLinkStub } } })
    await wrapper.get('#email').setValue('user@example.com')
    await wrapper.get('#password').setValue('secret')
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()
    expect(mocked.router.push).toHaveBeenCalledWith(redirect)
  })

  it('routes the demo sign-in to the limited workflow even from a tutorial link', async () => {
    mocked.route.query = { redirect: '/tutorial/3d' }
    mocked.authStore.user = { model_publication_only: true }
    mocked.authStore.login.mockResolvedValue({ data: { access_token: 'access-token' } })
    const wrapper = mount(LoginView, { global: { stubs: { RouterLink: RouterLinkStub } } })
    await wrapper.get('#email').setValue('demo')
    await wrapper.get('#password').setValue('secret')
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()
    expect(mocked.router.push).toHaveBeenCalledWith('/model-publication')
  })

  it('explains the inbox action when sign-in is blocked by email verification', async () => {
    mocked.authStore.login.mockRejectedValue({ error: { code: 'EMAIL_NOT_VERIFIED' } })
    const wrapper = mount(LoginView, { global: { stubs: { RouterLink: RouterLinkStub } } })
    await wrapper.get('#email').setValue('user@example.com')
    await wrapper.get('#password').setValue('secret')
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toMatch(/Verify your email.*request a new link/)
    expect(mocked.router.push).not.toHaveBeenCalled()
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
    expect(mocked.router.push).toHaveBeenCalledWith('/dashboard')
  })

  it('starts with email and can request a new verification link', async () => {
    mocked.authStore.register.mockResolvedValue({ data: { accepted: true } })
    mocked.authService.resendVerification.mockResolvedValue({ data: { accepted: true } })
    const wrapper = mount(RegisterView, { global: { stubs: { RouterLink: RouterLinkStub } } })
    await wrapper.get('#email').setValue('user@example.com')
    expect(wrapper.find('#password').exists()).toBe(false)
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()

    expect(mocked.authStore.register).toHaveBeenCalledWith('user@example.com')
    expect(wrapper.get('h1').text()).toBe('Check your inbox')
    expect(wrapper.text()).toContain('user@example.com')
    expect(wrapper.text()).toContain('spam or junk')
    await wrapper.findAll('button').find(button => button.text() === 'Resend verification email').trigger('click')
    await flushPromises()
    expect(mocked.authService.resendVerification).toHaveBeenCalledWith('user@example.com')
  })

  it('keeps the address and gives a retry when mail delivery fails', async () => {
    mocked.authStore.register.mockRejectedValue({ error: { message: 'Mail temporarily unavailable.' } })
    const wrapper = mount(RegisterView, { global: { stubs: { RouterLink: RouterLinkStub } } })
    await wrapper.get('#email').setValue('user@example.com')
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('Mail temporarily unavailable.')
    expect(wrapper.get('#email').element.value).toBe('user@example.com')
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeUndefined()
  })

  it('requires an explicit confirmation with matching passwords', async () => {
    const token = 'a'.repeat(43)
    mocked.route.hash = '#token=' + token
    mocked.authService.verifyEmail.mockResolvedValue({ data: {} })
    const wrapper = mount(VerifyEmailView, { global: { stubs: { RouterLink: RouterLinkStub } } })
    await flushPromises()
    expect(mocked.router.replace).toHaveBeenCalledWith('/verify-email')
    expect(mocked.authService.verifyEmail).not.toHaveBeenCalled()

    await wrapper.get('#password').setValue('password-1')
    await wrapper.get('#confirm-password').setValue('password-2')
    await wrapper.get('form').trigger('submit.prevent')
    expect(wrapper.get('#confirm-password').attributes('aria-describedby')).toBe('password-match-error')
    expect(mocked.authService.verifyEmail).not.toHaveBeenCalled()

    await wrapper.get('#confirm-password').setValue('password-1')
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()
    expect(mocked.authService.verifyEmail).toHaveBeenCalledWith(token, 'password-1')
    expect(wrapper.get('h1').text()).toBe('Email verified')
    expect(sessionStorage.getItem('webhdp:email-verification')).toBeNull()
  })

  it('offers a new link when a legacy or expired link cannot be used', async () => {
    mocked.route.params = { token: 'legacy-token' }
    const wrapper = mount(VerifyEmailView, { global: { stubs: { RouterLink: RouterLinkStub } } })
    await flushPromises()

    expect(mocked.authService.verifyEmail).not.toHaveBeenCalled()
    expect(wrapper.get('[role="alert"]').text()).toContain('Request a new verification email')
    expect(wrapper.text()).toContain('Request a new link')
  })
})
