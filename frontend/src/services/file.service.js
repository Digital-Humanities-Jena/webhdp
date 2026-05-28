import api from './api'

export default {
  uploadFile(file, options = {}) {
    const formData = new FormData()
    formData.append('file', file)
    Object.entries(options || {}).forEach(([key, value]) => {
      if (value === undefined || value === null || value === '') return
      formData.append(key, String(value))
    })

    // DO NOT set Content-Type - axios handles it automatically for FormData
    return api.post('/sessions/file', formData)
  },

  scanDirectory(directoryPath) {
    return api.post('/sessions/directory', {
      input_directory_path: directoryPath
    })
  },

  getSessionFiles(sessionId) {
    return api.get(`/sessions/${sessionId}`)
  },

  getSession(sessionId, options = {}) {
    return api.get(`/sessions/${sessionId}`, options)
  },

  getNodes(sessionId, options = {}) {
    return api.get(`/sessions/${sessionId}/nodes`, options)
  },

  listCloudDownloads(sessionId) {
    return api.get(`/sessions/${sessionId}/cloud-downloads`)
  },

  getCloudDownloadUrl(sessionId, mirrorId) {
    return api.get(`/sessions/${sessionId}/cloud-downloads/${mirrorId}`, {
      params: { as_json: true }
    })
  },

  listSessions(params = {}) {
    return api.get('/sessions', { params })
  },

  updateSessionWorkspace(sessionId, payload) {
    return api.put(`/sessions/${sessionId}/workspace`, payload)
  },

  getSessionWorkspace(sessionId, params = {}) {
    return api.get(`/sessions/${sessionId}/workspace`, { params })
  },

  getSessionAuditEvents(sessionId, params = {}) {
    return api.get(`/sessions/${sessionId}/audit-events`, { params })
  },

  getWorkflowState(sessionId, options = {}) {
    return api.get(`/sessions/${sessionId}/workflow-state`, options)
  },

  updateWorkflowState(sessionId, payload) {
    return api.put(`/sessions/${sessionId}/workflow-state`, payload)
  },

  /**
   * Downloads the .hdpc file for a given session.
   * @param {number} sessionId
   */
  downloadHdpc(sessionId) {
    return api.get(`/sessions/${sessionId}/hdpc`, {
      responseType: 'blob' // Important: tells axios to handle a file download
    })
  },

  /**
   * Downloads the sanitized shared .hdpc export for a given session.
   * @param {number} sessionId
   */
  downloadSharedHdpc(sessionId) {
    return api.get(`/sessions/${sessionId}/hdpc/shared`, {
      responseType: 'blob'
    })
  },

  /**
   * Downloads the Zenodo metadata JSON for a given session.
   * @param {number} sessionId The ID of the session
   */
  downloadZenodoMetadata(sessionId) {
    return api.get(`/sessions/${sessionId}/zenodo_metadata`, {
      responseType: 'blob' // use blob to handle the file download
    })
  }
}
