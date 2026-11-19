import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  authService: {
    login: vi.fn(),
    verifyLoginCode: vi.fn(),
    verifyRecoveryCode: vi.fn(),
    resendLoginCode: vi.fn(),
    register: vi.fn(),
    getCurrentUser: vi.fn(),
    updateCurrentUser: vi.fn(),
    updatePassword: vi.fn(),
  },
}))

vi.mock('@/services/auth.service', () => ({
  default: mocked.authService,
}))

import {
  getNormalizedCapabilities,
  getNormalizedGroups,
  normalizeAuthUser,
  useAuthStore,
} from '../src/stores/auth.js'
import { activateTestPinia } from './helpers/pinia.mjs'

describe('auth store', () => {
  beforeEach(() => {
    Object.values(mocked.authService).forEach((mockFn) => mockFn.mockReset())
    localStorage.clear()
    sessionStorage.clear()
    activateTestPinia()
  })

  it('removes invalid persisted placeholder tokens during initialization', () => {
    localStorage.setItem('token', 'undefined')
    activateTestPinia()

    const store = useAuthStore()

    expect(store.token).toBeNull()
    expect(localStorage.getItem('token')).toBeNull()
    expect(sessionStorage.getItem('token')).toBeNull()
  })

  it('persists the token and normalizes capabilities and groups on login', async () => {
    mocked.authService.login.mockResolvedValue({
      data: {
        access_token: 'access-token',
        user: {
          id: 7,
          email: 'user@example.com',
          capabilities_json: ['native_pipeline_author', 'native_pipeline_author'],
          groups: '["Editors","editors"]',
        },
      },
    })

    const store = useAuthStore()
    await store.login('user@example.com', 'secret')

    expect(store.token).toBe('access-token')
    expect(sessionStorage.getItem('token')).toBe('access-token')
    expect(localStorage.getItem('token')).toBeNull()
    expect(store.capabilities).toEqual(['native_pipeline_author'])
    expect(store.groups).toEqual(['Editors', 'editors'])
    expect(store.hasCapability('NATIVE_PIPELINE_AUTHOR')).toBe(true)
    expect(store.hasGroup('editors')).toBe(true)
  })

  it('keeps login unauthenticated until MFA code verification succeeds', async () => {
    mocked.authService.login.mockResolvedValue({
      data: {
        mfa_required: true,
        mfa_token: 'mfa-token',
        masked_email: 'us***r@example.com',
      },
    })
    mocked.authService.verifyLoginCode.mockResolvedValue({
      data: {
        access_token: 'access-token',
        user: {
          id: 7,
          email: 'user@example.com',
          capabilities: ['review'],
        },
      },
    })
    mocked.authService.resendLoginCode.mockResolvedValue({
      data: {
        mfa_required: true,
        mfa_token: 'mfa-token',
      },
    })
    mocked.authService.verifyRecoveryCode.mockResolvedValue({
      data: {
        access_token: 'recovery-token',
        user: {
          id: 7,
          email: 'user@example.com',
          capabilities: ['recovered'],
        },
      },
    })

    const store = useAuthStore()
    const loginResponse = await store.login('user@example.com', 'secret')

    expect(loginResponse.data.mfa_required).toBe(true)
    expect(store.token).toBeNull()
    expect(store.user).toBeNull()
    expect(sessionStorage.getItem('token')).toBeNull()

    await expect(store.resendLoginCode('mfa-token')).resolves.toMatchObject({
      data: {
        mfa_required: true,
      },
    })

    await store.verifyLoginCode('mfa-token', '123456')

    expect(mocked.authService.verifyLoginCode).toHaveBeenCalledWith('mfa-token', '123456')
    expect(store.token).toBe('access-token')
    expect(sessionStorage.getItem('token')).toBe('access-token')
    expect(store.user.email).toBe('user@example.com')
    expect(store.capabilities).toEqual(['review'])

    store.logout()
    await store.verifyRecoveryCode('mfa-token', 'ABCD-EFGH-IJKL')
    expect(mocked.authService.verifyRecoveryCode).toHaveBeenCalledWith('mfa-token', 'ABCD-EFGH-IJKL')
    expect(store.token).toBe('recovery-token')
    expect(store.capabilities).toEqual(['recovered'])
  })

  it('clears auth state when fetching the current user fails', async () => {
    mocked.authService.getCurrentUser.mockRejectedValue(new Error('token expired'))
    const store = useAuthStore()
    store.token = 'stale-token'
    sessionStorage.setItem('token', 'stale-token')
    sessionStorage.setItem('webhdp:metadata-draft:1:42', '{"title":"Unsent"}')

    await expect(store.fetchCurrentUser()).rejects.toThrow('token expired')

    expect(store.token).toBeNull()
    expect(store.user).toBeNull()
    expect(sessionStorage.getItem('token')).toBeNull()
    expect(localStorage.getItem('token')).toBeNull()
    expect(sessionStorage.getItem('webhdp:metadata-draft:1:42')).not.toBeNull()
    store.logout()
    expect(sessionStorage.getItem('webhdp:metadata-draft:1:42')).toBeNull()
  })

  it('keeps registration unauthenticated and proxies account update helpers', async () => {
    mocked.authService.register.mockResolvedValue({ data: { ok: true } })
    mocked.authService.updateCurrentUser.mockResolvedValue({
      data: {
        user: {
          id: 7,
          email: 'updated@example.com',
          capabilities: ['review'],
        },
      },
    })
    mocked.authService.updatePassword.mockResolvedValue({ data: { ok: true } })

    const store = useAuthStore()
    await store.register('user@example.com')
    expect(mocked.authService.register).toHaveBeenCalledWith('user@example.com')
    expect(store.token).toBeNull()

    await store.updateCurrentUser({ email: 'updated@example.com' })
    expect(store.user.email).toBe('updated@example.com')
    expect(store.capabilities).toEqual(['review'])

    await expect(store.updatePassword('old', 'new', 'new')).resolves.toEqual({ data: { ok: true } })
    store.logout()
    expect(store.isAuthenticated).toBe(false)
  })

  it('normalizes capability and group payload variants and handles empty token fetches', async () => {
    expect(getNormalizedCapabilities({
      capabilities: '["review","review"]',
      capabilities_json: ['native_pipeline_author'],
    })).toEqual(['review', 'native_pipeline_author'])
    expect(getNormalizedGroups({
      groups: '["Editors","Editors"]',
    })).toEqual(['Editors'])
    expect(normalizeAuthUser({
      email: 'user@example.com',
      capabilities_json: 'not-json',
      groups: 'not-json',
    })).toMatchObject({
      capabilities: [],
      groups: [],
    })

    const store = useAuthStore()
    await expect(store.fetchCurrentUser()).resolves.toBeUndefined()
    expect(store.hasCapability('missing')).toBe(false)
    expect(store.hasGroup('missing')).toBe(false)
  })

  it('handles successful logins without an access token', async () => {
    const consoleWarn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    mocked.authService.login.mockResolvedValue({
      data: {
        user: {
          id: 8,
          email: 'missing-token@example.com',
        },
      },
    })

    const store = useAuthStore()
    await store.login('missing-token@example.com', 'secret')

    expect(store.token).toBeNull()
    expect(sessionStorage.getItem('token')).toBeNull()
    expect(localStorage.getItem('token')).toBeNull()
    expect(normalizeAuthUser(null)).toBeNull()
    expect(consoleWarn).toHaveBeenCalledWith('Login successful but no token received')
    consoleWarn.mockRestore()
  })
})
