export function canRegisterServiceWorker({
  isProduction = import.meta.env.PROD,
  serviceWorker = navigator.serviceWorker,
} = {}) {
  return Boolean(isProduction && serviceWorker)
}

export function registerServiceWorker(options = {}) {
  const {
    isProduction = import.meta.env.PROD,
    serviceWorker = navigator.serviceWorker,
    registrationPath = '/sw.js',
    logger = console,
    windowRef = window,
  } = options

  if (!canRegisterServiceWorker({ isProduction, serviceWorker })) {
    return false
  }

  windowRef.addEventListener('load', () => {
    serviceWorker.register(registrationPath).catch((error) => {
      logger.warn('WebHDP PWA service worker registration failed.', error)
    })
  })

  return true
}
