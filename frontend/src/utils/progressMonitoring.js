export function isPermanentProgressError(error) {
  const status = Number(error?.response?.status || error?.status)
  const code = error?.response?.data?.error?.code || error?.error?.code
  return [401, 403, 404, 410].includes(status) ||
    ['FORBIDDEN', 'NOT_FOUND', 'RESOURCE_NOT_FOUND', 'SECURITY_ERROR'].includes(code)
}

export function progressRetryDelay(failures = 0) {
  return Math.min(30000, 1000 * 2 ** Math.min(failures, 5))
}

export function waitForProgress(delay, signal) {
  return new Promise((resolve, reject) => {
    const cancel = () => {
      clearTimeout(timer)
      signal?.removeEventListener('abort', cancel)
      reject(Object.assign(new Error('Monitoring stopped'), { code: 'MONITOR_CANCELLED' }))
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', cancel)
      resolve()
    }, delay)
    if (signal?.aborted) cancel()
    else signal?.addEventListener('abort', cancel, { once: true })
  })
}
