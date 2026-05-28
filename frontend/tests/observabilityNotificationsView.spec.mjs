import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const adminServiceMock = vi.hoisted(() => ({
  getNotificationDeliveries: vi.fn(),
  runNotificationDigest: vi.fn(),
  cleanupNotifications: vi.fn(),
}))

vi.mock('@/services/admin.service', () => ({
  default: adminServiceMock,
}))

import ObservabilityNotificationsView from '../src/views/admin/ObservabilityNotificationsView.vue'

describe('ObservabilityNotificationsView', () => {
  beforeEach(() => {
    adminServiceMock.getNotificationDeliveries.mockReset().mockResolvedValue({
      data: {
        summary: { total: 1, statuses: { sent: 1 } },
        deliveries: [
          {
            id: 1,
            channel: 'digest',
            status: 'sent',
            created_at: '2026-04-30T10:00:00Z',
            recipient_user_id: 3,
            recipient: { email: 'admin@example.com' },
            notification: { title: 'Digest item', category_label: 'Admin observability' },
            batch_key: 'digest:test',
          },
        ],
      },
    })
    adminServiceMock.runNotificationDigest.mockReset().mockResolvedValue({
      data: { batch_key: 'digest:test', sent_users: 1, delivered_notifications: 1 },
    })
    adminServiceMock.cleanupNotifications.mockReset().mockResolvedValue({
      data: { deleted_notifications: 1, deleted_deliveries: 2 },
    })
  })

  it('loads delivery attempts and runs a digest', async () => {
    const wrapper = mount(ObservabilityNotificationsView)
    await flushPromises()

    expect(adminServiceMock.getNotificationDeliveries).toHaveBeenCalled()
    expect(wrapper.text()).toContain('Digest item')
    expect(wrapper.text()).toContain('Notification Delivery')

    await wrapper.findAll('button').find((button) => button.text() === 'Run digest now').trigger('click')
    await flushPromises()

    expect(adminServiceMock.runNotificationDigest).toHaveBeenCalledWith()
    expect(wrapper.text()).toContain('delivering 1 notification')

    await wrapper.findAll('button').find((button) => button.text() === 'Run cleanup').trigger('click')
    await flushPromises()

    expect(adminServiceMock.cleanupNotifications).toHaveBeenCalledWith({ batch_size: 1000 })
    expect(wrapper.text()).toContain('Cleanup deleted 1 notification')
  })
})
