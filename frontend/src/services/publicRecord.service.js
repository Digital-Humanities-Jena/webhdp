import axios from 'axios'
import { buildApiBaseUrl } from './apiBase'

const RAW_API_BASE_URL = import.meta.env.VITE_API_URL || '/api/v1'
const API_BASE_URL = buildApiBaseUrl(RAW_API_BASE_URL, 'v1')

const publicApi = axios.create({
  baseURL: API_BASE_URL
})

export function publicOembedUrl(pageUrl) {
  const endpoint = `${API_BASE_URL}/oembed?url=${encodeURIComponent(pageUrl)}&format=json`
  if (typeof window === 'undefined') return endpoint
  return new URL(endpoint, window.location.origin).toString()
}

export default {
  getRecord(environment, zenodoRecordId) {
    return publicApi
      .get(`/public/records/${encodeURIComponent(environment)}/${encodeURIComponent(zenodoRecordId)}`)
      .then((response) => response.data)
  },
}
