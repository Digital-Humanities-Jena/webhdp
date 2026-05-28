const CACHE_VERSION = '__WEBHDP_CACHE_VERSION__'
const CACHE_PREFIXES = ['webhdp-static-', 'webhdp-runtime-']
const STATIC_CACHE = `webhdp-static-${CACHE_VERSION}`
const RUNTIME_CACHE = `webhdp-runtime-${CACHE_VERSION}`
const BUILD_ASSETS = [
  '__WEBHDP_PRECACHE_PLACEHOLDER__',
]

const STATIC_ASSETS = Array.from(new Set([
  '/',
  '/index.html',
  '/favicon.svg',
  '/manifest.webmanifest',
  '/pwa-icon.svg',
  '/icons/webhdp-icon-192.png',
  '/icons/webhdp-icon-512.png',
  '/icons/webhdp-maskable-512.png',
  ...BUILD_ASSETS,
]))

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())
  )
})

self.addEventListener('activate', (event) => {
  const currentCaches = new Set([STATIC_CACHE, RUNTIME_CACHE])

  event.waitUntil(
    caches.keys()
      .then((cacheNames) => Promise.all(
        cacheNames
          .filter((cacheName) => CACHE_PREFIXES.some((prefix) => cacheName.startsWith(prefix)))
          .filter((cacheName) => !currentCaches.has(cacheName))
          .map((cacheName) => caches.delete(cacheName))
      ))
      .then(() => self.clients.claim())
  )
})

async function cacheFirst(request) {
  const cachedResponse = await caches.match(request, { ignoreVary: true })

  if (cachedResponse) {
    return cachedResponse
  }

  const response = await fetch(request)

  if (response && response.ok) {
    const cache = await caches.open(RUNTIME_CACHE)
    cache.put(request, response.clone())
  }

  return response
}

async function navigationResponse(request) {
  try {
    const response = await fetch(request)

    if (response && response.ok) {
      const cache = await caches.open(STATIC_CACHE)
      cache.put('/index.html', response.clone())
    }

    return response
  } catch (error) {
    return caches.match('/index.html', { ignoreVary: true })
  }
}

self.addEventListener('fetch', (event) => {
  const { request } = event
  const url = new URL(request.url)

  if (request.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api')) {
    return
  }

  if (request.mode === 'navigate') {
    event.respondWith(navigationResponse(request))
    return
  }

  event.respondWith(cacheFirst(request))
})
