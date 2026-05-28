import { afterAll, afterEach, beforeAll, beforeEach, vi } from 'vitest'
import { server } from './msw/server.mjs'

const createMemoryStorage = () => {
  let store = new Map()

  return {
    get length() {
      return store.size
    },
    clear() {
      store.clear()
    },
    getItem(key) {
      return store.has(String(key)) ? store.get(String(key)) : null
    },
    key(index) {
      return Array.from(store.keys())[index] ?? null
    },
    removeItem(key) {
      store.delete(String(key))
    },
    setItem(key, value) {
      store.set(String(key), String(value))
    },
  }
}

const localStorageMock = createMemoryStorage()
const sessionStorageMock = createMemoryStorage()

beforeAll(() => {
  Object.defineProperty(window, 'localStorage', {
    value: localStorageMock,
    configurable: true,
  })
  Object.defineProperty(window, 'sessionStorage', {
    value: sessionStorageMock,
    configurable: true,
  })
  Object.defineProperty(globalThis, 'localStorage', {
    value: localStorageMock,
    configurable: true,
  })
  Object.defineProperty(globalThis, 'sessionStorage', {
    value: sessionStorageMock,
    configurable: true,
  })
  server.listen({ onUnhandledRequest: 'error' })
})

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  document.body.innerHTML = ''
  window.scrollTo = vi.fn()
  window.URL.createObjectURL = window.URL.createObjectURL || vi.fn(() => 'blob:mock-url')
  window.URL.revokeObjectURL = window.URL.revokeObjectURL || vi.fn()
  HTMLAnchorElement.prototype.click = vi.fn()
  window.matchMedia = window.matchMedia || (() => ({
    matches: false,
    media: '',
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
  global.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
})

afterEach(() => {
  server.resetHandlers()
  vi.clearAllMocks()
  vi.useRealTimers()
})

afterAll(() => {
  server.close()
})
