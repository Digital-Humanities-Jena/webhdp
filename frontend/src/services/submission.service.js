// frontend/src/services/submission.service.js
import api from './api'

export default {
  /**
   * Lists all submissions for the current user.
   */
  listSubmissions() {
    return api.get('/submissions')
  },

  /**
   * Gets the detailed information for a single submission.
   * @param {number} id The ID of the submission
   */
  getSubmission(id) {
    return api.get(`/submissions/${id}`)
  },

  /**
   * Gets current processing progress for a submission.
   * @param {number} id The submission ID
   */
  getSubmissionProgress(id) {
    return api.get(`/submissions/${id}/progress`, { suppressGlobalError: true })
  },

  /**
   * Lists persisted upload operations for the current user.
   */
  listUploadOperations() {
    return api.get('/sessions/upload-operations')
  },

  /**
   * Gets a single upload operation for the current user.
   * @param {number} sessionId The session ID backing the upload
   */
  getUploadOperation(sessionId) {
    return api.get(`/sessions/upload-operations/${sessionId}`)
  },

  /**
   * Lists upload operations for moderators/admins.
   * @param {object} params Query params like { status: 'running' }
   */
  listAdminUploadOperations(params = {}) {
    return api.get('/admin/upload-operations', { params })
  },

  /**
   * Gets all Zenodo records created during a session.
   * @param {number} sessionId The session ID
   */
  getSessionRecords(sessionId) {
    return api.get(`/sessions/${sessionId}/records`)
  },

  getSessionWorkspaceSummary(sessionId, params = {}) {
    return api.get(`/sessions/${sessionId}/workspace-summary`, { params })
  },

  /**
   * Gets detail for one local record in a session.
   * @param {number} sessionId The session ID
   * @param {number} recordId The local record ID
   */
  getSessionRecordDetail(sessionId, recordId) {
    return api.get(`/sessions/${sessionId}/records/${recordId}`)
  },

  getSessionRecordLineage(sessionId, recordId) {
    return api.get(`/sessions/${sessionId}/records/${recordId}/lineage`)
  },

  getSessionRecordZenodoStatus(sessionId, recordId) {
    return api.get(`/sessions/${sessionId}/records/${recordId}/zenodo-status`)
  },

  getSessionRecordResolution(sessionId) {
    return api.get(`/sessions/${sessionId}/record-resolution`)
  },

  analyzeSessionRecordResolution(sessionId, payload = {}) {
    return api.post(`/sessions/${sessionId}/record-resolution/analyze`, payload)
  },

  updateSessionRecordResolution(sessionId, payload) {
    return api.put(`/sessions/${sessionId}/record-resolution`, payload)
  },

  getSessionOperationsSummary(sessionId, params = {}) {
    return api.get(`/sessions/${sessionId}/operations/summary`, { params })
  },

  launchSessionBatchOperation(sessionId, payload) {
    return api.post(`/sessions/${sessionId}/batch-operations`, payload)
  },

  listSessionBatchOperations(sessionId, params = {}) {
    return api.get(`/sessions/${sessionId}/batch-operations`, { params })
  },

  getSessionBatchOperation(sessionId, taskId) {
    return api.get(`/sessions/${sessionId}/batch-operations/${taskId}`, { suppressGlobalError: true })
  },

  /**
   * Create a new Zenodo version for a published session record.
   * @param {number} sessionId The session ID
   * @param {number} recordId The local record ID
   * @param {object} payload Optional payload like { publish: true }
   */
  createSessionRecordVersion(sessionId, recordId, payload = {}) {
    return api.post(`/sessions/${sessionId}/records/${recordId}/create-version`, payload)
  },

  /**
   * Gets a full provenance report for a session.
   * @param {number} sessionId The session ID
   */
  getSessionProvenanceReport(sessionId) {
    return api.get(`/sessions/${sessionId}/provenance-report`)
  },

  /**
   * Explore records across sessions.
   * @param {object} params Query params for filtering
   */
  exploreRecords(params = {}) {
    return api.get('/sessions/records/explorer', { params })
  },

  /**
   * Import an .hdpc file for the current user.
   * @param {File} file The .hdpc file to import
   */
  importHdpc(file) {
    const formData = new FormData()
    formData.append('hdpc_file', file)
    return api.post('/sessions/import-hdpc', formData)
  },

  /**
   * Admin-only: import an .hdpc file for a specific user.
   * @param {number} userId Target user ID
   * @param {File} file The .hdpc file to import
   */
  adminImportHdpcForUser(userId, file) {
    const formData = new FormData()
    formData.append('hdpc_file', file)
    return api.post(`/admin/users/${userId}/hdpc/import`, formData)
  }
}
