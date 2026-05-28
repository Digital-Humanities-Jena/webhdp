const DEFAULT_API_ORIGIN = 'http://localhost:5000'
const API_VERSION_PATTERN = /\/api\/v\d+$/i
const API_ROOT_PATTERN = /\/api$/i
const TRAILING_SLASHES_PATTERN = /\/+$/

export function normalizeApiBaseUrl(rawBaseUrl, fallbackBaseUrl = DEFAULT_API_ORIGIN) {
  const candidate = String(rawBaseUrl || '').trim() || fallbackBaseUrl
  return candidate.replace(TRAILING_SLASHES_PATTERN, '')
}

export function buildApiBaseUrl(rawBaseUrl, version = 'v1') {
  const normalizedVersion = String(version || '').trim().toLowerCase()
  if (!/^v\d+$/.test(normalizedVersion)) {
    throw new Error(`Unsupported API version: ${version}`)
  }

  const normalizedBaseUrl = normalizeApiBaseUrl(rawBaseUrl)

  if (API_VERSION_PATTERN.test(normalizedBaseUrl)) {
    return normalizedBaseUrl.replace(API_VERSION_PATTERN, `/api/${normalizedVersion}`)
  }

  if (API_ROOT_PATTERN.test(normalizedBaseUrl)) {
    return `${normalizedBaseUrl}/${normalizedVersion}`
  }

  return `${normalizedBaseUrl}/api/${normalizedVersion}`
}
