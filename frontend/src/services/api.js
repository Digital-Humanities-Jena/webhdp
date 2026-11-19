import axios from 'axios'
import { useToast } from '@/composables/useToast'
import { buildApiBaseUrl } from './apiBase'
import { linkLoginDestination } from '@/utils/webhdpLink'

const RAW_API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000'

function defaultRedirectToLogin() {
  const current = window.location.pathname + window.location.search
  window.location.href = linkLoginDestination(current) === current
    ? `/login?redirect=${encodeURIComponent(current)}`
    : '/login'
}

export function attachInterceptors(client, {
  showError = useToast().error,
  redirectToLogin = defaultRedirectToLogin,
  getToken = () => sessionStorage.getItem('token'),
  clearToken = () => {
    sessionStorage.removeItem('token')
    localStorage.removeItem('token')
  },
} = {}) {
  client.interceptors.request.use(
    (config) => {
      const token = getToken()

      if (token && token !== 'null' && token !== 'undefined') {
        config.headers.Authorization = `Bearer ${token}`
      } else if (token === 'null' || token === 'undefined') {
        clearToken()
      }

      return config
    },
    (error) => Promise.reject(error)
  )

  client.interceptors.response.use(
    (response) => response.data,
    (error) => {
      const suppressError = error.config?.suppressGlobalError
      const requestUrl = String(error.config?.url || '')
      const isInteractiveAuthRequest = /^\/auth\/(?:login(?:\/|$)|register$|resend-verification$|verify-email$)/.test(requestUrl)
      let responseData = error.response?.data
      if (typeof responseData === 'string') {
        try { responseData = JSON.parse(responseData) } catch { /* Non-JSON errors use the transport message. */ }
      }

      if (error.response) {
        const status = error.response.status
        const data = responseData
        const message = data?.error?.message || data?.message || error.message || 'An unexpected error occurred'

        if (status === 401 && !isInteractiveAuthRequest) {
          clearToken()
          redirectToLogin()
          if (!suppressError) showError('Session expired. Please login again.')
        } else if (!suppressError) {
          showError(message)
        }
      } else if (error.request) {
        if (!suppressError) showError('Network error. Please check your connection.')
      } else if (!suppressError) {
        showError(error.message || 'Request failed')
      }

      return Promise.reject(responseData || error)
    }
  )

  return client
}

export function createApiClient(version = 'v1', options = {}) {
  return attachInterceptors(
    axios.create({
      baseURL: buildApiBaseUrl(RAW_API_BASE_URL, version)
    }),
    options
  )
}

const api = createApiClient('v1')
export const apiV1 = api
export const apiV2 = createApiClient('v2')

// Add streaming upload method
api.uploadFileStream = (file, onProgress, options = {}) => {
  const headers = {
    'Content-Type': 'application/octet-stream',
    'X-File-Name': file.name
  }
  if (options.hpcAllocationId) {
    headers['X-HPC-Allocation-ID'] = options.hpcAllocationId
  }
  if (options.hpcRelativeDir) {
    headers['X-HPC-Relative-Dir'] = options.hpcRelativeDir
  }
  return api.post('/upload/stream', file, {
    headers,
    onUploadProgress: (progressEvent) => {
      const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total)
      if (onProgress) onProgress(percentCompleted)
    }
  })
}

export default api
