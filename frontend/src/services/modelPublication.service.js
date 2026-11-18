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

export default {
  async samples() {
    const { data } = await publicApi.get(`${prefix}/samples`)
    return data.data
  },
  async availability() {
    const response = await api.get(`${prefix}/availability`, quiet)
    return response.data
  },
  async jobs(signal) {
    const response = await api.get(`${prefix}/jobs`, { ...quiet, signal })
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
    return api.get(`${prefix}/jobs/${encodeURIComponent(jobId)}/files/${encodeURIComponent(filename)}`, {
      ...quiet,
      responseType: 'blob'
    })
  }
}
