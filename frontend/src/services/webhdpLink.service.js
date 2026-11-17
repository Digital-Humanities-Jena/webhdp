import { createApiClient } from './api'
const api = createApiClient('v1')

// Link uses raw JSON and RFC 9457 errors. Keep error messages beside the action.
const options = { suppressGlobalError: true }
const path = (value) => encodeURIComponent(value)

export default {
  listJobs: () => api.get('/link/jobs', options),
  getJob: (id) => api.get(`/link/jobs/${path(id)}`, options),
  cancelJob: (id) => api.post(`/link/jobs/${path(id)}/cancel`, {}, options),
  downloadJobArtifact: (id, artifactId) => api.get(`/link/jobs/${path(id)}/artifacts/${path(artifactId)}`, { ...options, responseType: 'blob' }),
  listGrants: () => api.get('/link/grants', options),
  revokeGrant: (id) => api.delete(`/link/grants/${path(id)}`, options),
  listClients: () => api.get('/link/admin/clients', options),
  createClient: (payload) => api.post('/link/admin/clients', payload, options),
  updateClient: (id, payload) => api.patch(`/link/admin/clients/${path(id)}`, payload, options),
  listPublications: () => api.get('/link/admin/publications', options),
  createPublication: (payload) => api.post('/link/admin/publications', payload, options),
  updatePublication: (id, payload) => api.patch(`/link/admin/publications/${path(id)}`, payload, options),
  pipelineOptions: () => api.get('/link/admin/pipeline-options', options),
  listTokens: () => api.get('/link/admin/tokens', options),
  issueToken: (id, payload) => api.post(`/link/admin/clients/${path(id)}/tokens`, payload, options),
  revokeToken: (id) => api.delete(`/link/admin/tokens/${path(id)}`, options),
  listRuns: () => api.get('/link/admin/runs', options),
  cancelRun: (id) => api.post(`/link/admin/runs/${path(id)}/cancel`, {}, options),
  authorizationRequest: (params) => api.get('/link/oauth/request', { ...options, params }),
  authorize: (payload) => api.post('/link/oauth/authorize', payload, options),
}
