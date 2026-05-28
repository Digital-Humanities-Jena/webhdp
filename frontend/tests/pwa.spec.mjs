import { describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { canRegisterServiceWorker, registerServiceWorker } from '../src/pwa'

describe('PWA registration', () => {
  it('only registers the service worker in production-capable browsers', () => {
    expect(canRegisterServiceWorker({ isProduction: true, serviceWorker: { register: vi.fn() } })).toBe(true)
    expect(canRegisterServiceWorker({ isProduction: false, serviceWorker: { register: vi.fn() } })).toBe(false)
    expect(canRegisterServiceWorker({ isProduction: true, serviceWorker: undefined })).toBe(false)
  })

  it('registers /sw.js after the window load event', () => {
    const register = vi.fn().mockResolvedValue({})
    const addEventListener = vi.fn((event, callback) => {
      if (event === 'load') callback()
    })

    const didSchedule = registerServiceWorker({
      isProduction: true,
      serviceWorker: { register },
      windowRef: { addEventListener },
    })

    expect(didSchedule).toBe(true)
    expect(addEventListener).toHaveBeenCalledWith('load', expect.any(Function))
    expect(register).toHaveBeenCalledWith('/sw.js')
  })

  it('does not schedule registration outside production', () => {
    const register = vi.fn()
    const addEventListener = vi.fn()

    const didSchedule = registerServiceWorker({
      isProduction: false,
      serviceWorker: { register },
      windowRef: { addEventListener },
    })

    expect(didSchedule).toBe(false)
    expect(addEventListener).not.toHaveBeenCalled()
    expect(register).not.toHaveBeenCalled()
  })

  it('keeps API requests out of the service worker cache and uses versioned caches', () => {
    const serviceWorkerPath = join(process.cwd(), 'public/sw.js')
    const serviceWorkerSource = readFileSync(serviceWorkerPath, 'utf8')

    expect(serviceWorkerSource).toContain("url.pathname.startsWith('/api')")
    expect(serviceWorkerSource).toContain("const CACHE_VERSION = '__WEBHDP_CACHE_VERSION__'")
    expect(serviceWorkerSource).toContain("cacheName.startsWith(prefix)")
    expect(serviceWorkerSource).toContain('ignoreVary: true')
  })
})
