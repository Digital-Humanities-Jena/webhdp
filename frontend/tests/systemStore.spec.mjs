import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

vi.mock('@/services/api', () => ({
  default: mocked.api,
}))

import { useSystemStore } from '../src/stores/system.js'
import { activateTestPinia } from './helpers/pinia.mjs'

describe('system store', () => {
  beforeEach(() => {
    mocked.api.get.mockReset()
    mocked.api.post.mockReset()
    window.sessionStorage.clear()
    window.history.pushState({}, '', '/')
    activateTestPinia()
  })

  it('caches the setup status after the first successful check', async () => {
    mocked.api.get.mockResolvedValue({ data: { initialized: false } })
    const store = useSystemStore()

    await store.checkStatus()
    await store.checkStatus()

    expect(mocked.api.get).toHaveBeenCalledTimes(1)
    expect(mocked.api.get).toHaveBeenCalledWith('/setup/status')
    expect(store.isInitialized).toBe(false)
    expect(store.loading).toBe(false)
  })

  it('falls back to initialized mode when the status check fails', async () => {
    mocked.api.get.mockRejectedValue(new Error('offline'))
    const store = useSystemStore()

    await store.checkStatus()

    expect(store.isInitialized).toBe(true)
    expect(store.loading).toBe(false)
  })

  it('updates the initialization state when setup is completed or reset', async () => {
    mocked.api.post.mockResolvedValue({ data: { ok: true } })
    window.sessionStorage.setItem('setup_token', 'stored-token')
    const store = useSystemStore()

    await store.resetSystem()
    expect(store.isInitialized).toBe(false)

    await store.completeSetup()
    expect(store.isInitialized).toBe(true)
    expect(store.setupToken).toBe('')
    expect(window.sessionStorage.getItem('setup_token')).toBeNull()
  })

  it('proxies the remaining setup actions to the API client', async () => {
    mocked.api.post.mockResolvedValue({ data: { ok: true } })
    const store = useSystemStore()

    await store.checkHealth()
    await store.testRender()
    await store.verifyZenodo({ apiKey: 'live', sandboxKey: 'sandbox' })
    await store.createAdmin({ email: 'admin@example.com', password: 'secret' })

    expect(mocked.api.post).toHaveBeenNthCalledWith(1, '/setup/check', undefined, undefined)
    expect(mocked.api.post).toHaveBeenNthCalledWith(2, '/setup/test-render', undefined, undefined)
    expect(mocked.api.post).toHaveBeenNthCalledWith(3, '/setup/verify-zenodo', {
      api_key: 'live',
      sandbox_key: 'sandbox',
    }, undefined)
    expect(mocked.api.post).toHaveBeenNthCalledWith(4, '/setup/create-admin', {
      email: 'admin@example.com',
      password: 'secret',
    }, undefined)
  })

  it('captures a setup token from the URL and sends it on setup-only requests', async () => {
    mocked.api.post.mockResolvedValue({ data: { ok: true } })
    window.history.pushState({}, '', '/setup?setup_token=url-token-123')
    const store = useSystemStore()

    await store.checkHealth()
    await store.createAdmin({ email: 'admin@example.com', password: 'secret' })

    const expectedConfig = {
      headers: {
        'X-Setup-Token': 'url-token-123',
      },
    }
    expect(store.setupToken).toBe('url-token-123')
    expect(window.sessionStorage.getItem('setup_token')).toBe('url-token-123')
    expect(mocked.api.post).toHaveBeenNthCalledWith(1, '/setup/check', undefined, expectedConfig)
    expect(mocked.api.post).toHaveBeenNthCalledWith(2, '/setup/create-admin', {
      email: 'admin@example.com',
      password: 'secret',
    }, expectedConfig)
  })
})
