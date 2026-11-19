import api from './api'

export default {
  listInstitutions(params = {}) {
    return api.get('/institutions', { params })
  },

  suggestInstitutions(query, params = {}, options = {}) {
    return api.get('/institutions/suggestions', { ...options, params: { ...params, q: query } })
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

  listInvitations(institutionId, params = {}) {
    return api.get(`/institutions/${institutionId}/invitations`, { params, suppressGlobalError: true })
  },

  sendInvitation(institutionId, payload) {
    return api.post(`/institutions/${institutionId}/invitations`, payload, { suppressGlobalError: true })
  },

  revokeInvitation(institutionId, invitationId) {
    return api.delete(`/institutions/${institutionId}/invitations/${invitationId}`, { suppressGlobalError: true })
  },

  acceptInvitation(token) {
    return api.post('/institutions/invitations/accept', { token }, { suppressGlobalError: true })
  },

  previewInvitation(token) {
    return api.post('/institutions/invitations/preview', { token }, { suppressGlobalError: true })
  },

  listWorkspaceRequests(params = {}) {
    return api.get('/institutions/workspace-requests', { params, suppressGlobalError: true })
  },

  requestWorkspace(payload) {
    return api.post('/institutions/workspace-requests', payload, { suppressGlobalError: true })
  },

  decideWorkspaceRequest(requestId, payload) {
    return api.patch(`/institutions/workspace-requests/${requestId}/decision`, payload, { suppressGlobalError: true })
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
