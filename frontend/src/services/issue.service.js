import api from './api'

export default {
  getRegistry() {
    return api.get('/issues/registry')
  },

  listIssues(params = {}) {
    return api.get('/issues', { params })
  },

  createIssue(payload) {
    return api.post('/issues', payload)
  },

  getIssue(issueId) {
    return api.get(`/issues/${issueId}`)
  },

  updateIssue(issueId, payload) {
    return api.patch(`/issues/${issueId}`, payload)
  },

  addComment(issueId, payload) {
    return api.post(`/issues/${issueId}/comments`, payload)
  },

  refreshCodeReferences(issueId) {
    return api.post(`/issues/${issueId}/refresh-code-references`, {})
  },
}
