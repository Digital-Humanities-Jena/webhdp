import axios from 'axios'
import api from './api'
import { buildApiBaseUrl } from './apiBase'

const prefix = '/model-publication'
const publicApi = axios.create({
  baseURL: buildApiBaseUrl(import.meta.env.VITE_API_URL || '/api/v1', 'v1')
})
const quiet = { suppressGlobalError: true }

export function sampleUrl(id, preview = false) {
  const endpoint = `${publicApi.defaults.baseURL}${prefix}/samples/${encodeURIComponent(id)}`
  return preview ? `${endpoint}/preview` : endpoint
}

export function sandboxDraftUrl(value) {
  if (typeof value !== 'string') return ''
  try {
    const url = new URL(value)
    if (url.origin === 'https://sandbox.zenodo.org' &&
        !url.username && !url.password &&
        /^\/(?:uploads|deposit|records)\/\d+\/?$/.test(url.pathname)) {
      return url.origin + url.pathname
    }
  } catch { /* Only link to a valid Sandbox address. */ }
  return ''
}

export function sandboxDraftPreviewUrl(value, id) {
  if (typeof value !== 'string' || value.length > 2000) return ''
  const matched = value.match(/^https:\/\/sandbox\.zenodo\.org\/records\/([1-9][0-9]*)\?preview=1&token=[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){2}$/)
  return matched?.[0] === value && matched[1] === String(id) ? value : ''
}

export default {
  async samples() {
    const { data } = await publicApi.get(`${prefix}/samples`)
    return data.data
  },
  async availability(signal) {
    const response = await api.get(`${prefix}/availability`, { ...quiet, signal, timeout: 10000 })
    return response.data
  },
  async queue(signal) {
    const response = await api.get(`${prefix}/queue`, { ...quiet, signal, timeout: 10000 })
    return response.data
  },
  async jobs(signal) {
    const response = await api.get(`${prefix}/jobs`, { ...quiet, signal, timeout: 10000 })
    return response.data
  },
  async start(form, requestId, onUploadProgress) {
    const response = await api.post(`${prefix}/jobs`, form, {
      ...quiet,
      onUploadProgress,
      headers: { 'Idempotency-Key': requestId }
    })
    return response.data.job
  },
  file(jobId, filename) {
    return api.get(`${prefix}/jobs/${encodeURIComponent(jobId)}/files/${filename.split('/').map(encodeURIComponent).join('/')}`, {
      ...quiet,
      responseType: 'blob'
    })
  }
}
