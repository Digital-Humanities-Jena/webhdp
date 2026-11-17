import api from './api'

const adminService = {
  getCredentialsStatus() {
    return api.get('/admin/observability/credentials-status')
  },

  getApiActivity(params = {}) {
    return api.get('/admin/observability/api-activity', { params })
  },

  getNotificationDeliveries(params = {}) {
    return api.get('/admin/observability/notification-deliveries', { params })
  },

  runNotificationDigest(payload = {}) {
    return api.post('/admin/observability/notification-digest/run', payload)
  },

  cleanupNotifications(payload = {}) {
    return api.post('/admin/observability/notifications/cleanup', payload)
  },

  runObservabilityCheck(checkId) {
    return api.post(`/admin/observability/checks/${encodeURIComponent(checkId)}`)
  },

  getVersionDetectionConfig() {
    return api.get('/admin/version-detection-config')
  },

  updateVersionDetectionConfig(payload) {
    return api.post('/admin/version-detection-config', payload)
  },

  getHpcLinkConfig() {
    return api.get('/admin/hpc-link-config')
  },

  getSetupGuidance() {
    return api.get('/admin/setup-guidance')
  },

  updateHpcLinkConfig(payload) {
    return api.put('/admin/hpc-link-config', payload)
  },

  validateHpcLinkConfig() {
    return api.post('/admin/hpc-link-config/validate')
  },

  listHpcResourceRequests(params = {}) {
    return api.get('/admin/hpc-resource-requests', { params })
  },

  approveHpcResourceRequest(requestId, payload = {}) {
    return api.post(`/admin/hpc-resource-requests/${requestId}/approve`, payload)
  },

  rejectHpcResourceRequest(requestId, payload = {}) {
    return api.post(`/admin/hpc-resource-requests/${requestId}/reject`, payload)
  },

  listHpcAccessUsers() {
    return api.get('/admin/hpc-access-users')
  },

  revokeHpcAccess(userId) {
    return api.post(`/admin/hpc-access-users/${userId}/revoke`, {})
  },

  listHpcReservations() {
    return api.get('/admin/hpc-reservations')
  },

  registerHpcReservation(payload) {
    return api.post('/admin/hpc-reservations', payload)
  },

  updateHpcReservation(reservationId, payload) {
    return api.patch(`/admin/hpc-reservations/${encodeURIComponent(reservationId)}`, payload)
  },

  getSessionMonitoring(params = {}) {
    return api.get('/admin/session-monitoring', { params })
  },

  terminateMonitoredSession(sessionId) {
    return api.post(`/admin/session-monitoring/sessions/${sessionId}/terminate`, {})
  },

  terminateMonitoredAllocation(allocationId) {
    return api.post(`/admin/session-monitoring/allocations/${encodeURIComponent(allocationId)}/terminate`, {})
  },

  resetUserRecovery(userId, payload = {}) {
    return api.post(`/admin/users/${userId}/recovery-reset`, payload)
  },
}

export default adminService
