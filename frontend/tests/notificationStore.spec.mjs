import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const notificationServiceMock = vi.hoisted(() => ({
  listNotifications: vi.fn(),
  getUnreadCount: vi.fn(),
  getClientConfig: vi.fn(),
  getPreferences: vi.fn(),
  updatePreferences: vi.fn(),
  updateNotification: vi.fn(),
  markAllRead: vi.fn(),
}))

vi.mock('@/services/notification.service', () => ({
  default: notificationServiceMock,
}))

import { useNotificationStore } from '../src/stores/notifications'

describe('notification store', () => {
  beforeEach(() => {
    vi.useRealTimers()
    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
    setActivePinia(createPinia())
    Object.values(notificationServiceMock).forEach((fn) => fn.mockReset())
    notificationServiceMock.getClientConfig.mockResolvedValue({
      data: { poll_interval_seconds: 120, dropdown_limit: 10, page_limit: 50, sse_enabled: false },
    })
  })

  it('loads notifications and unread counts', async () => {
    notificationServiceMock.listNotifications.mockResolvedValue({
      data: {
        unread_count: 2,
        notifications: [
          { id: 1, title: 'Pipeline completed', read_at: null },
          { id: 2, title: 'Issue assigned', read_at: '2026-04-30T10:00:00Z' },
        ],
      },
    })
    const store = useNotificationStore()

    await store.loadNotifications()

    expect(notificationServiceMock.listNotifications).toHaveBeenCalledWith({ state: 'all', limit: 10 })
    expect(store.unreadCount).toBe(2)
    expect(store.notifications[0].is_read).toBe(false)
    expect(store.notifications[1].is_read).toBe(true)
  })

  it('marks one notification read and refreshes the count', async () => {
    notificationServiceMock.updateNotification.mockResolvedValue({
      data: { notification: { id: 7, title: 'Done', read_at: '2026-04-30T10:00:00Z' } },
    })
    notificationServiceMock.getUnreadCount.mockResolvedValue({ data: { unread_count: 0 } })
    const store = useNotificationStore()
    store.notifications = [{ id: 7, title: 'Done', is_read: false }]

    const updated = await store.markNotificationRead(7, true)

    expect(notificationServiceMock.updateNotification).toHaveBeenCalledWith(7, { read: true })
    expect(updated.is_read).toBe(true)
    expect(store.unreadCount).toBe(0)
  })

  it('loads and saves notification preferences', async () => {
    notificationServiceMock.getPreferences.mockResolvedValue({
      data: { categories: [{ category: 'issues', label: 'Issues', in_app_enabled: true, email_enabled: false }] },
    })
    notificationServiceMock.updatePreferences.mockResolvedValue({
      data: { categories: [{ category: 'issues', label: 'Issues', in_app_enabled: false, email_enabled: true }] },
    })
    const store = useNotificationStore()

    await store.loadPreferences()
    expect(store.preferences[0].category).toBe('issues')

    const saved = await store.savePreferences([{ category: 'issues', in_app_enabled: false, email_enabled: true }])

    expect(notificationServiceMock.updatePreferences).toHaveBeenCalledWith([
      { category: 'issues', in_app_enabled: false, email_enabled: true },
    ])
    expect(saved[0].email_enabled).toBe(true)
  })

  it('updates archived state through the shared patch endpoint', async () => {
    notificationServiceMock.updateNotification.mockResolvedValue({
      data: { notification: { id: 9, title: 'Archived', archived_at: '2026-04-30T10:00:00Z' } },
    })
    notificationServiceMock.getUnreadCount.mockResolvedValue({ data: { unread_count: 1 } })
    const store = useNotificationStore()
    store.notifications = [{ id: 9, title: 'Archived', is_archived: false }]

    const updated = await store.markNotificationArchived(9, true)

    expect(notificationServiceMock.updateNotification).toHaveBeenCalledWith(9, { archived: true })
    expect(updated.is_archived).toBe(true)
  })

  it('starts and stops unread polling', async () => {
    vi.useFakeTimers()
    notificationServiceMock.getUnreadCount.mockResolvedValue({ data: { unread_count: 3 } })
    const store = useNotificationStore()

    await store.startPolling()
    await vi.advanceTimersByTimeAsync(120_000)
    store.stopPolling()

    expect(notificationServiceMock.getClientConfig).toHaveBeenCalled()
    expect(notificationServiceMock.getUnreadCount).toHaveBeenCalled()
  })

  it('pauses polling while hidden and refreshes when visible again', async () => {
    vi.useFakeTimers()
    notificationServiceMock.getUnreadCount.mockResolvedValue({ data: { unread_count: 4 } })
    const store = useNotificationStore()

    await store.startPolling()
    notificationServiceMock.getUnreadCount.mockClear()

    Object.defineProperty(document, 'hidden', { configurable: true, value: true })
    await vi.advanceTimersByTimeAsync(120_000)
    expect(notificationServiceMock.getUnreadCount).not.toHaveBeenCalled()

    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
    document.dispatchEvent(new Event('visibilitychange'))
    await Promise.resolve()
    await Promise.resolve()

    expect(notificationServiceMock.getUnreadCount).toHaveBeenCalledTimes(1)
    store.stopPolling()
  })
})
