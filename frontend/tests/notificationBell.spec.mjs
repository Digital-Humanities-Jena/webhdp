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
  unreadCount: 2,
  loading: false,
  notifications: [
    {
      id: 1,
      title: 'Pipeline completed',
      body: 'Session #1 finished.',
      severity: 'success',
      action_url: '/submissions/1',
      created_at: '2026-04-30T10:00:00Z',
      is_read: false,
    },
  ],
  loadNotifications: vi.fn(),
  markNotificationRead: vi.fn(),
  markAllRead: vi.fn(),
  archiveNotification: vi.fn(),
}))

vi.mock('@/stores/notifications', () => ({
  useNotificationStore: () => notificationStoreMock,
}))

import NotificationBell from '../src/components/layout/NotificationBell.vue'

describe('NotificationBell', () => {
  beforeEach(() => {
    routerMock.push.mockReset()
    notificationStoreMock.unreadCount = 2
    notificationStoreMock.loading = false
    notificationStoreMock.notifications = [
      {
        id: 1,
        title: 'Pipeline completed',
        body: 'Session #1 finished.',
        severity: 'success',
        action_url: '/submissions/1',
        created_at: '2026-04-30T10:00:00Z',
        is_read: false,
      },
    ]
    notificationStoreMock.loadNotifications.mockReset().mockResolvedValue(notificationStoreMock.notifications)
    notificationStoreMock.markNotificationRead.mockReset().mockResolvedValue({ id: 1, is_read: true })
    notificationStoreMock.markAllRead.mockReset().mockResolvedValue(1)
    notificationStoreMock.archiveNotification.mockReset().mockResolvedValue({ id: 1 })
  })

  it('shows unread badge, loads the dropdown, and opens notification links', async () => {
    const wrapper = mount(NotificationBell, {
      global: {
        stubs: {
          RouterLink: {
            props: ['to'],
            template: '<a :href="to"><slot /></a>',
          },
        },
      },
    })

    expect(wrapper.text()).toContain('2')
    await wrapper.get('button[aria-label="Notifications"]').trigger('click')
    await flushPromises()

    expect(notificationStoreMock.loadNotifications).toHaveBeenCalled()
    expect(wrapper.text()).toContain('Pipeline completed')

    await wrapper.findAll('button').find((button) => button.text().includes('Pipeline completed')).trigger('click')
    await flushPromises()

    expect(notificationStoreMock.markNotificationRead).toHaveBeenCalledWith(1, true)
    expect(routerMock.push).toHaveBeenCalledWith('/submissions/1')
  })

  it('marks all read from the dropdown action', async () => {
    const wrapper = mount(NotificationBell, {
      global: {
        stubs: {
          RouterLink: {
            props: ['to'],
            template: '<a :href="to"><slot /></a>',
          },
        },
      },
    })
    await wrapper.get('button[aria-label="Notifications"]').trigger('click')

    await wrapper.findAll('button').find((button) => button.text() === 'Mark all read').trigger('click')

    expect(notificationStoreMock.markAllRead).toHaveBeenCalled()
  })
})
