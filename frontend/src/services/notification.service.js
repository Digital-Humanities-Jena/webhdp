import api from './api'

export default {
  listNotifications(params = {}) {
    return api.get('/notifications', { params, suppressGlobalError: true })
  },

  getUnreadCount() {
    return api.get('/notifications/unread-count', { suppressGlobalError: true })
  },

  getClientConfig() {
    return api.get('/notifications/client-config', { suppressGlobalError: true })
  },

  getPreferences() {
    return api.get('/notifications/preferences', { suppressGlobalError: true })
  },

  updatePreferences(preferences) {
    return api.put('/notifications/preferences', { preferences }, { suppressGlobalError: true })
  },

  updateNotification(notificationId, payload) {
    return api.patch(`/notifications/${notificationId}`, payload, { suppressGlobalError: true })
  },

  markAllRead() {
    return api.post('/notifications/read-all', {}, { suppressGlobalError: true })
  },
}
