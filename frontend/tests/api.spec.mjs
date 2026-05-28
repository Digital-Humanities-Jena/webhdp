import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  axiosCreate: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock('axios', () => ({
  default: {
    create: mocked.axiosCreate,
  },
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({
    error: mocked.toastError,
  }),
}))

function createClientHarness() {
  const handlers = {
    request: {},
    response: {},
  }
  const client = {
    interceptors: {
      request: {
        use: vi.fn((onFulfilled, onRejected) => {
          handlers.request.onFulfilled = onFulfilled
          handlers.request.onRejected = onRejected
        }),
      },
      response: {
        use: vi.fn((onFulfilled, onRejected) => {
          handlers.response.onFulfilled = onFulfilled
          handlers.response.onRejected = onRejected
        }),
      },
    },
    post: vi.fn(),
  }

  return { client, handlers }
}

describe('api service interceptors', () => {
  let attachInterceptors
  let createApiClient
  let apiV1

  beforeEach(() => {
    vi.resetModules()
    mocked.axiosCreate.mockReset()
    mocked.toastError.mockReset()
    mocked.axiosCreate.mockImplementation(() => createClientHarness().client)
  })

  it('adds an authorization header when a usable token exists', async () => {
    ;({ attachInterceptors, createApiClient, apiV1 } = await import('../src/services/api.js'))
    const { client, handlers } = createClientHarness()
    const getToken = vi.fn(() => 'token-123')

    attachInterceptors(client, {
      getToken,
      clearToken: vi.fn(),
      redirectToLogin: vi.fn(),
      showError: vi.fn(),
    })

    const config = await handlers.request.onFulfilled({ headers: {} })

    expect(getToken).toHaveBeenCalledTimes(1)
    expect(config.headers.Authorization).toBe('Bearer token-123')
  })

  it('clears bad placeholder tokens before the request proceeds', async () => {
    ;({ attachInterceptors, createApiClient, apiV1 } = await import('../src/services/api.js'))
    const { client, handlers } = createClientHarness()
    const clearToken = vi.fn()

    attachInterceptors(client, {
      getToken: () => 'undefined',
      clearToken,
      redirectToLogin: vi.fn(),
      showError: vi.fn(),
    })

    const config = await handlers.request.onFulfilled({ headers: {} })

    expect(clearToken).toHaveBeenCalledTimes(1)
    expect(config.headers.Authorization).toBeUndefined()
  })

  it('unwraps successful responses to their data payload', async () => {
    ;({ attachInterceptors, createApiClient, apiV1 } = await import('../src/services/api.js'))
    const { client, handlers } = createClientHarness()

    attachInterceptors(client, {
      showError: vi.fn(),
      redirectToLogin: vi.fn(),
      clearToken: vi.fn(),
    })

    expect(handlers.response.onFulfilled({ data: { ok: true } })).toEqual({ ok: true })
  })

  it('clears auth state, redirects, and shows a toast for 401 responses', async () => {
    ;({ attachInterceptors, createApiClient, apiV1 } = await import('../src/services/api.js'))
    const { client, handlers } = createClientHarness()
    const clearToken = vi.fn()
    const redirectToLogin = vi.fn()
    const showError = vi.fn()
    const responsePayload = { message: 'Unauthorized' }

    attachInterceptors(client, {
      showError,
      redirectToLogin,
      clearToken,
    })

    await expect(handlers.response.onRejected({
      config: {},
      response: {
        status: 401,
        data: responsePayload,
      },
      message: 'Unauthorized',
    })).rejects.toEqual(responsePayload)

    expect(clearToken).toHaveBeenCalledTimes(1)
    expect(redirectToLogin).toHaveBeenCalledTimes(1)
    expect(showError).toHaveBeenCalledWith('Session expired. Please login again.')
  })

  it('does not redirect interactive login requests on a 401 response', async () => {
    ;({ attachInterceptors, createApiClient, apiV1 } = await import('../src/services/api.js'))
    const { client, handlers } = createClientHarness()
    const clearToken = vi.fn()
    const redirectToLogin = vi.fn()
    const showError = vi.fn()
    const responsePayload = { error: { message: 'Invalid credentials' } }

    attachInterceptors(client, {
      showError,
      redirectToLogin,
      clearToken,
    })

    await expect(handlers.response.onRejected({
      config: {
        url: '/auth/login',
      },
      response: {
        status: 401,
        data: responsePayload,
      },
      message: 'Invalid credentials',
    })).rejects.toEqual(responsePayload)

    expect(clearToken).not.toHaveBeenCalled()
    expect(redirectToLogin).not.toHaveBeenCalled()
    expect(showError).toHaveBeenCalledWith('Invalid credentials')
  })

  it('suppresses global error toasts when requested', async () => {
    ;({ attachInterceptors, createApiClient, apiV1 } = await import('../src/services/api.js'))
    const { client, handlers } = createClientHarness()
    const showError = vi.fn()

    attachInterceptors(client, {
      showError,
      redirectToLogin: vi.fn(),
      clearToken: vi.fn(),
    })

    await expect(handlers.response.onRejected({
      config: { suppressGlobalError: true },
      response: {
        status: 500,
        data: { message: 'Server exploded' },
      },
      message: 'Server exploded',
    })).rejects.toEqual({ message: 'Server exploded' })

    expect(showError).not.toHaveBeenCalled()
  })

  it('shows a network error toast for failed requests without a response', async () => {
    ;({ attachInterceptors, createApiClient, apiV1 } = await import('../src/services/api.js'))
    const { client, handlers } = createClientHarness()
    const showError = vi.fn()

    attachInterceptors(client, {
      showError,
      redirectToLogin: vi.fn(),
      clearToken: vi.fn(),
    })

    const error = { config: {}, request: {} }
    await expect(handlers.response.onRejected(error)).rejects.toBe(error)

    expect(showError).toHaveBeenCalledWith('Network error. Please check your connection.')
  })

  it('shows the backend error message for non-401 API failures', async () => {
    ;({ attachInterceptors, createApiClient, apiV1 } = await import('../src/services/api.js'))
    const { client, handlers } = createClientHarness()
    const showError = vi.fn()

    attachInterceptors(client, {
      showError,
      redirectToLogin: vi.fn(),
      clearToken: vi.fn(),
    })

    await expect(handlers.response.onRejected({
      config: {},
      response: {
        status: 500,
        data: { error: { message: 'Detailed backend message' } },
      },
      message: 'Detailed backend message',
    })).rejects.toEqual({ error: { message: 'Detailed backend message' } })

    expect(showError).toHaveBeenCalledWith('Detailed backend message')
  })

  it('shows a generic request error when no response or request object exists', async () => {
    ;({ attachInterceptors, createApiClient, apiV1 } = await import('../src/services/api.js'))
    const { client, handlers } = createClientHarness()
    const showError = vi.fn()

    attachInterceptors(client, {
      showError,
      redirectToLogin: vi.fn(),
      clearToken: vi.fn(),
    })

    const error = new Error('Request setup failed')
    await expect(handlers.response.onRejected(error)).rejects.toBe(error)

    expect(showError).toHaveBeenCalledWith('Request setup failed')
  })

  it('creates versioned API clients with normalized base URLs', async () => {
    ;({ attachInterceptors, createApiClient, apiV1 } = await import('../src/services/api.js'))
    const clientHarness = createClientHarness()
    mocked.axiosCreate.mockReturnValue(clientHarness.client)

    const client = createApiClient('v2', {
      showError: vi.fn(),
      redirectToLogin: vi.fn(),
      clearToken: vi.fn(),
    })

    expect(mocked.axiosCreate).toHaveBeenLastCalledWith({
      baseURL: 'http://localhost:5000/api/v2',
    })
    expect(client).toBe(clientHarness.client)
  })

  it('streams uploads with the expected headers and forwards progress', async () => {
    ;({ attachInterceptors, createApiClient, apiV1 } = await import('../src/services/api.js'))
    const progressSpy = vi.fn()
    const file = { name: 'asset.glb' }
    apiV1.post = vi.fn().mockImplementation((url, payload, config) => {
      config.onUploadProgress({ loaded: 5, total: 10 })
      return Promise.resolve({ ok: true, url, payload })
    })

    const result = await apiV1.uploadFileStream(file, progressSpy)

    expect(apiV1.post).toHaveBeenCalledWith('/upload/stream', file, expect.objectContaining({
      headers: {
        'Content-Type': 'application/octet-stream',
        'X-File-Name': 'asset.glb',
      },
      onUploadProgress: expect.any(Function),
    }))
    expect(progressSpy).toHaveBeenCalledWith(50)
    expect(result).toEqual({ ok: true, url: '/upload/stream', payload: file })
  })
})
