import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
}))

vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRouter: () => routerMock,
  }
})

const notificationStoreMock = vi.hoisted(() => ({
  unreadCount: 1,
  loading: false,
  preferencesLoading: false,
  pageLimit: 50,
  categories: [
    { value: 'issues', label: 'Issues' },
    { value: 'jobs', label: 'Jobs and pipelines' },
  ],
  preferences: [
    { category: 'issues', label: 'Issues', in_app_enabled: true, email_enabled: false },
    { category: 'jobs', label: 'Jobs and pipelines', in_app_enabled: true, email_enabled: true },
  ],
  notifications: [
    {
      id: 5,
      title: 'Issue assigned',
      body: 'A new issue needs your attention.',
      category_label: 'Issues',
      severity: 'info',
      action_url: '/issues/5',
      created_at: '2026-04-30T10:00:00Z',
      is_read: false,
      is_archived: false,
    },
  ],
  loadNotifications: vi.fn(),
  loadPreferences: vi.fn(),
  savePreferences: vi.fn(),
  markNotificationRead: vi.fn(),
  markNotificationArchived: vi.fn(),
  markAllRead: vi.fn(),
}))

vi.mock('@/stores/notifications', () => ({
  useNotificationStore: () => notificationStoreMock,
}))

import NotificationsView from '../src/views/notifications/NotificationsView.vue'

describe('NotificationsView', () => {
  beforeEach(() => {
    routerMock.push.mockReset()
    notificationStoreMock.loadNotifications.mockReset().mockResolvedValue(notificationStoreMock.notifications)
    notificationStoreMock.loadPreferences.mockReset().mockResolvedValue(notificationStoreMock.preferences)
    notificationStoreMock.savePreferences.mockReset().mockResolvedValue(notificationStoreMock.preferences)
    notificationStoreMock.markNotificationRead.mockReset().mockResolvedValue({ id: 5, is_read: true })
    notificationStoreMock.markNotificationArchived.mockReset().mockResolvedValue({ id: 5, is_archived: true })
    notificationStoreMock.markAllRead.mockReset().mockResolvedValue(1)
  })

  it('renders inbox filters, opens notification links, and saves preferences', async () => {
    const wrapper = mount(NotificationsView)
    await flushPromises()

    expect(notificationStoreMock.loadNotifications).toHaveBeenCalledWith({ state: 'all', category: undefined, limit: 50 })
    expect(notificationStoreMock.loadPreferences).toHaveBeenCalled()
    expect(wrapper.text()).toContain('Issue assigned')
    expect(wrapper.text()).toContain('Preferences')

    await wrapper.findAll('button').find((button) => button.text().includes('Issue assigned')).trigger('click')
    await flushPromises()

    expect(notificationStoreMock.markNotificationRead).toHaveBeenCalledWith(5, true)
    expect(routerMock.push).toHaveBeenCalledWith('/issues/5')

    await wrapper.findAll('button').find((button) => button.text() === 'Save preferences').trigger('click')
    expect(notificationStoreMock.savePreferences).toHaveBeenCalled()
  })

  it('marks all read and archives from the page controls', async () => {
    const wrapper = mount(NotificationsView)
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text() === 'Mark all read').trigger('click')
    expect(notificationStoreMock.markAllRead).toHaveBeenCalled()

    await wrapper.findAll('button').find((button) => button.text() === 'Archive').trigger('click')
    expect(notificationStoreMock.markNotificationArchived).toHaveBeenCalledWith(5, true)
  })
})
