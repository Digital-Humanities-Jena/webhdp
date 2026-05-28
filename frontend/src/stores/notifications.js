import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import notificationService from '@/services/notification.service'

const DEFAULT_CLIENT_CONFIG = {
  poll_interval_seconds: 120,
  dropdown_limit: 10,
  page_limit: 50,
  sse_enabled: false,
}

export const useNotificationStore = defineStore('notifications', () => {
  const notifications = ref([])
  const categories = ref([])
  const preferences = ref([])
  const clientConfig = ref({ ...DEFAULT_CLIENT_CONFIG })
  const unreadCount = ref(0)
  const loading = ref(false)
  const preferencesLoading = ref(false)
  const error = ref('')
  let pollTimer = null
  let pollStarting = false
  let visibilityListenerAttached = false

  const hasUnread = computed(() => unreadCount.value > 0)
  const dropdownLimit = computed(() => Number(clientConfig.value.dropdown_limit || DEFAULT_CLIENT_CONFIG.dropdown_limit))
  const pageLimit = computed(() => Number(clientConfig.value.page_limit || DEFAULT_CLIENT_CONFIG.page_limit))
  const pollIntervalMs = computed(() => Number(clientConfig.value.poll_interval_seconds || DEFAULT_CLIENT_CONFIG.poll_interval_seconds) * 1000)

  function normalizeNotification(item) {
    return {
      ...item,
      is_read: Boolean(item?.is_read || item?.read_at),
      is_archived: Boolean(item?.is_archived || item?.archived_at),
    }
  }

  async function loadNotifications(params = {}) {
    loading.value = true
    error.value = ''
    try {
      const response = await notificationService.listNotifications({ state: 'all', limit: dropdownLimit.value, ...params })
      const data = response.data || {}
      notifications.value = Array.isArray(data.notifications) ? data.notifications.map(normalizeNotification) : []
      categories.value = Array.isArray(data.categories) ? data.categories : categories.value
      unreadCount.value = Number(data.unread_count || 0)
      if (data.client_config) {
        applyClientConfig(data.client_config)
      }
      return notifications.value
    } catch (err) {
      error.value = err?.error?.message || err?.message || 'Failed to load notifications'
      return []
    } finally {
      loading.value = false
    }
  }

  async function refreshUnreadCount() {
    if (typeof document !== 'undefined' && document.hidden) {
      return unreadCount.value
    }
    try {
      const response = await notificationService.getUnreadCount()
      unreadCount.value = Number(response.data?.unread_count || 0)
      return unreadCount.value
    } catch (err) {
      error.value = err?.error?.message || err?.message || 'Failed to refresh notifications'
      return unreadCount.value
    }
  }

  function applyClientConfig(nextConfig = {}) {
    clientConfig.value = {
      ...clientConfig.value,
      ...Object.fromEntries(
        Object.entries(nextConfig).filter(([, value]) => value !== undefined && value !== null)
      ),
    }
  }

  async function loadClientConfig() {
    try {
      const response = await notificationService.getClientConfig()
      applyClientConfig(response.data || {})
      return clientConfig.value
    } catch {
      return clientConfig.value
    }
  }

  async function markNotificationRead(notificationId, read = true) {
    const response = await notificationService.updateNotification(notificationId, { read })
    const updated = normalizeNotification(response.data?.notification || {})
    notifications.value = notifications.value.map((item) => (item.id === updated.id ? updated : item))
    await refreshUnreadCount()
    return updated
  }

  async function markNotificationArchived(notificationId, archived = true) {
    const response = await notificationService.updateNotification(notificationId, { archived })
    const updated = normalizeNotification(response.data?.notification || {})
    notifications.value = notifications.value.map((item) => (item.id === updated.id ? updated : item))
    await refreshUnreadCount()
    return updated
  }

  async function archiveNotification(notificationId) {
    const response = await notificationService.updateNotification(notificationId, { archived: true, read: true })
    const updated = normalizeNotification(response.data?.notification || {})
    notifications.value = notifications.value.filter((item) => item.id !== updated.id)
    await refreshUnreadCount()
    return updated
  }

  async function markAllRead() {
    const response = await notificationService.markAllRead()
    unreadCount.value = Number(response.data?.unread_count || 0)
    notifications.value = notifications.value.map((item) => ({ ...item, is_read: true, read_at: item.read_at || new Date().toISOString() }))
    return Number(response.data?.updated_count || 0)
  }

  async function loadPreferences() {
    preferencesLoading.value = true
    error.value = ''
    try {
      const response = await notificationService.getPreferences()
      const data = response.data || {}
      preferences.value = Array.isArray(data.categories) ? data.categories : []
      return preferences.value
    } catch (err) {
      error.value = err?.error?.message || err?.message || 'Failed to load notification preferences'
      return []
    } finally {
      preferencesLoading.value = false
    }
  }

  async function savePreferences(nextPreferences = preferences.value) {
    preferencesLoading.value = true
    error.value = ''
    try {
      const response = await notificationService.updatePreferences(nextPreferences)
      const data = response.data || {}
      preferences.value = Array.isArray(data.categories) ? data.categories : []
      return preferences.value
    } catch (err) {
      error.value = err?.error?.message || err?.message || 'Failed to save notification preferences'
      return preferences.value
    } finally {
      preferencesLoading.value = false
    }
  }

  function onVisibilityChange() {
    if (typeof document !== 'undefined' && !document.hidden && pollTimer) {
      refreshUnreadCount()
    }
  }

  function attachVisibilityListener() {
    if (visibilityListenerAttached || typeof document === 'undefined') return
    document.addEventListener('visibilitychange', onVisibilityChange)
    visibilityListenerAttached = true
  }

  function detachVisibilityListener() {
    if (!visibilityListenerAttached || typeof document === 'undefined') return
    document.removeEventListener('visibilitychange', onVisibilityChange)
    visibilityListenerAttached = false
  }

  async function startPolling() {
    if (pollTimer || pollStarting) return
    pollStarting = true
    try {
      await loadClientConfig()
      if (pollTimer) return
      attachVisibilityListener()
      refreshUnreadCount()
      pollTimer = window.setInterval(refreshUnreadCount, pollIntervalMs.value)
    } finally {
      pollStarting = false
    }
  }

  function stopPolling() {
    pollStarting = false
    if (!pollTimer) return
    window.clearInterval(pollTimer)
    pollTimer = null
    detachVisibilityListener()
  }

  function reset() {
    stopPolling()
    notifications.value = []
    categories.value = []
    preferences.value = []
    clientConfig.value = { ...DEFAULT_CLIENT_CONFIG }
    unreadCount.value = 0
    loading.value = false
    preferencesLoading.value = false
    error.value = ''
  }

  return {
    notifications,
    categories,
    preferences,
    clientConfig,
    unreadCount,
    loading,
    preferencesLoading,
    error,
    hasUnread,
    dropdownLimit,
    pageLimit,
    pollIntervalMs,
    loadNotifications,
    loadClientConfig,
    refreshUnreadCount,
    markNotificationRead,
    markNotificationArchived,
    archiveNotification,
    markAllRead,
    loadPreferences,
    savePreferences,
    startPolling,
    stopPolling,
    reset,
  }
})
