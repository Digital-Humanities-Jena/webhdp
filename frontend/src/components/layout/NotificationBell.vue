<template>
  <div class="relative">
    <button
      type="button"
      class="relative inline-flex h-9 w-9 items-center justify-center rounded-md border border-gray-200 bg-white text-gray-700 transition-colors hover:border-gray-300 hover:bg-gray-50 hover:text-gray-900"
      aria-label="Notifications"
      @click="toggleOpen"
    >
      <BellIcon class="h-5 w-5" aria-hidden="true" />
      <span
        v-if="notificationStore.unreadCount > 0"
        class="absolute -right-1 -top-1 min-w-[18px] rounded-full bg-rose-600 px-1 text-center text-[10px] font-semibold leading-[18px] text-white"
      >
        {{ badgeLabel }}
      </span>
    </button>

    <div
      v-if="isOpen"
      class="absolute right-0 z-50 mt-2 w-[min(92vw,24rem)] overflow-hidden rounded-md border border-gray-200 bg-white shadow-lg"
    >
      <div class="flex items-center justify-between border-b border-gray-100 px-4 py-3">
        <h2 class="text-sm font-semibold text-gray-900">Notifications</h2>
        <div class="flex items-center gap-3">
          <RouterLink class="text-xs font-medium text-indigo-700 hover:text-indigo-900" to="/notifications" @click="isOpen = false">
            View all
          </RouterLink>
          <button
            type="button"
            class="text-xs font-medium text-indigo-700 hover:text-indigo-900 disabled:text-gray-400"
            :disabled="notificationStore.unreadCount === 0"
            @click="markAllRead"
          >
            Mark all read
          </button>
        </div>
      </div>

      <div v-if="notificationStore.loading" class="px-4 py-6 text-sm text-gray-500">
        Loading notifications...
      </div>
      <div v-else-if="notificationStore.notifications.length === 0" class="px-4 py-6 text-sm text-gray-500">
        No notifications yet.
      </div>
      <ul v-else class="max-h-96 divide-y divide-gray-100 overflow-y-auto">
        <li
          v-for="notification in notificationStore.notifications"
          :key="notification.id"
          :class="[
            'group flex gap-3 px-4 py-3 transition-colors hover:bg-gray-50',
            notification.is_read ? 'bg-white' : 'bg-indigo-50/60'
          ]"
        >
          <button
            type="button"
            class="min-w-0 flex-1 text-left"
            @click="openNotification(notification)"
          >
            <div class="flex items-start justify-between gap-3">
              <p class="text-sm font-semibold text-gray-900">{{ notification.title }}</p>
              <span :class="severityClass(notification.severity)" class="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase">
                {{ notification.severity || 'info' }}
              </span>
            </div>
            <p v-if="notification.body" class="mt-1 line-clamp-2 text-xs text-gray-600">{{ notification.body }}</p>
            <p class="mt-2 text-[11px] text-gray-400">{{ formatDate(notification.created_at) }}</p>
          </button>
          <button
            type="button"
            class="self-start rounded p-1 text-gray-400 opacity-0 transition-opacity hover:bg-gray-100 hover:text-gray-700 group-hover:opacity-100"
            aria-label="Archive notification"
            @click="archive(notification)"
          >
            <XMarkIcon class="h-4 w-4" aria-hidden="true" />
          </button>
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { BellIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import { useNotificationStore } from '@/stores/notifications'

const router = useRouter()
const notificationStore = useNotificationStore()
const isOpen = ref(false)

const badgeLabel = computed(() => (notificationStore.unreadCount > 99 ? '99+' : String(notificationStore.unreadCount)))

const toggleOpen = async () => {
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    await notificationStore.loadNotifications()
  }
}

const openNotification = async (notification) => {
  if (!notification?.is_read) {
    await notificationStore.markNotificationRead(notification.id, true)
  }
  isOpen.value = false
  if (notification?.action_url) {
    router.push(notification.action_url)
  }
}

const markAllRead = async () => {
  await notificationStore.markAllRead()
}

const archive = async (notification) => {
  await notificationStore.archiveNotification(notification.id)
}

const formatDate = (value) => {
  if (!value) return ''
  try {
    return new Date(value).toLocaleString('de-DE', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return value
  }
}

const severityClass = (severity) => {
  if (severity === 'success') return 'bg-emerald-50 text-emerald-700'
  if (severity === 'warning') return 'bg-amber-50 text-amber-700'
  if (severity === 'error') return 'bg-rose-50 text-rose-700'
  return 'bg-blue-50 text-blue-700'
}
</script>
