import api from './api'

export default {
  listInstitutions(params = {}) {
    return api.get('/institutions', { params })
  },

  suggestInstitutions(query, params = {}) {
    return api.get('/institutions/suggestions', { params: { ...params, q: query } })
  },

  configureAffiliation(payload) {
    return api.post('/institutions/affiliation', payload)
  },

  getInstitution(institutionId) {
    return api.get(`/institutions/${institutionId}`)
  },

  createInstitution(payload) {
    return api.post('/institutions', payload)
  },

  updateInstitution(institutionId, payload) {
    return api.put(`/institutions/${institutionId}`, payload)
  },

  listMemberships(institutionId) {
    return api.get(`/institutions/${institutionId}/memberships`)
  },

  listAuditEvents(institutionId, params = {}) {
    return api.get(`/institutions/${institutionId}/audit-events`, { params })
  },

  createMembership(institutionId, payload) {
    return api.post(`/institutions/${institutionId}/memberships`, payload)
  },

  updateMembership(institutionId, userId, payload) {
    return api.put(`/institutions/${institutionId}/memberships/${userId}`, payload)
  },

  deleteMembership(institutionId, userId) {
    return api.delete(`/institutions/${institutionId}/memberships/${userId}`)
  },

  listCommunities(institutionId) {
    return api.get(`/institutions/${institutionId}/communities`)
  },

  createCommunity(institutionId, payload) {
    return api.post(`/institutions/${institutionId}/communities`, payload)
  },

  updateCommunity(institutionId, communityId, payload) {
    return api.put(`/institutions/${institutionId}/communities/${communityId}`, payload)
  },

  deleteCommunity(institutionId, communityId) {
    return api.delete(`/institutions/${institutionId}/communities/${communityId}`)
  },

  getZenodoCredential(institutionId, environment) {
    return api.get(`/institutions/${institutionId}/zenodo-credentials/${environment}`)
  },

  saveZenodoCredential(institutionId, environment, token) {
    return api.put(`/institutions/${institutionId}/zenodo-credentials/${environment}`, { token })
  },

  deleteZenodoCredential(institutionId, environment) {
    return api.delete(`/institutions/${institutionId}/zenodo-credentials/${environment}`)
  },

  validateZenodoCredential(institutionId, environment) {
    return api.post(`/institutions/${institutionId}/zenodo-credentials/${environment}/validate`, {})
  }
}
