import axios from 'axios'
import { useToast } from '@/composables/useToast'
import { buildApiBaseUrl } from './apiBase'

const RAW_API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000'

function defaultRedirectToLogin() {
  window.location.href = '/login'
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
      const isInteractiveAuthRequest = requestUrl.includes('/auth/login') || requestUrl.includes('/auth/register')

      if (error.response) {
        const status = error.response.status
        const data = error.response.data
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

      return Promise.reject(error.response?.data || error)
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
