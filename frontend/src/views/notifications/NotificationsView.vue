<template>
  <div class="mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:px-8">
    <div class="flex flex-col gap-4 border-b border-gray-200 pb-5 md:flex-row md:items-end md:justify-between">
      <div>
        <h1 class="text-2xl font-semibold text-gray-900">Notifications</h1>
        <p class="mt-1 text-sm text-gray-600">{{ notificationStore.unreadCount }} unread</p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <button
          v-for="option in stateOptions"
          :key="option.value"
          type="button"
          :class="[
            'rounded-md px-3 py-2 text-sm font-medium transition-colors',
            filters.state === option.value
              ? 'bg-indigo-600 text-white'
              : 'border border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
          ]"
          @click="setState(option.value)"
        >
          {{ option.label }}
        </button>
        <select
          v-model="filters.category"
          class="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
          aria-label="Notification category"
        >
          <option value="">All categories</option>
          <option v-for="category in notificationStore.categories" :key="category.value" :value="category.value">
            {{ category.label }}
          </option>
        </select>
      </div>
    </div>

    <div class="grid gap-6 py-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <section class="min-w-0">
        <div class="mb-3 flex items-center justify-between">
          <h2 class="text-sm font-semibold uppercase text-gray-500">Inbox</h2>
          <button
            type="button"
            class="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:text-gray-400"
            :disabled="notificationStore.unreadCount === 0"
            @click="markAllRead"
          >
            Mark all read
          </button>
        </div>

        <div class="overflow-hidden rounded-md border border-gray-200 bg-white">
          <div v-if="notificationStore.loading" class="px-4 py-10 text-center text-sm text-gray-500">
            Loading notifications...
          </div>
          <div v-else-if="notificationStore.notifications.length === 0" class="px-4 py-10 text-center text-sm text-gray-500">
            No notifications match this view.
          </div>
          <ul v-else class="divide-y divide-gray-100">
            <li
              v-for="notification in notificationStore.notifications"
              :key="notification.id"
              :class="['px-4 py-4', notification.is_read ? 'bg-white' : 'bg-indigo-50/50']"
            >
              <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <button type="button" class="min-w-0 text-left" @click="openNotification(notification)">
                  <div class="flex flex-wrap items-center gap-2">
                    <span :class="severityClass(notification.severity)" class="rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase">
                      {{ notification.severity || 'info' }}
                    </span>
                    <span class="text-xs font-medium text-gray-500">{{ notification.category_label }}</span>
                    <span class="text-xs text-gray-400">{{ formatDate(notification.created_at) }}</span>
                  </div>
                  <h3 class="mt-2 text-base font-semibold text-gray-900">{{ notification.title }}</h3>
                  <p v-if="notification.body" class="mt-1 text-sm text-gray-600">{{ notification.body }}</p>
                </button>
                <div class="flex shrink-0 flex-wrap gap-2">
                  <button
                    type="button"
                    class="rounded-md border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
                    @click="toggleRead(notification)"
                  >
                    {{ notification.is_read ? 'Mark unread' : 'Mark read' }}
                  </button>
                  <button
                    type="button"
                    class="rounded-md border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
                    @click="toggleArchive(notification)"
                  >
                    {{ notification.is_archived ? 'Unarchive' : 'Archive' }}
                  </button>
                </div>
              </div>
            </li>
          </ul>
        </div>
      </section>

      <aside class="min-w-0">
        <div class="rounded-md border border-gray-200 bg-white">
          <div class="border-b border-gray-100 px-4 py-3">
            <h2 class="text-sm font-semibold text-gray-900">Preferences</h2>
          </div>
          <div v-if="notificationStore.preferencesLoading" class="px-4 py-6 text-sm text-gray-500">
            Loading preferences...
          </div>
          <div v-else class="divide-y divide-gray-100">
            <div
              v-for="preference in notificationStore.preferences"
              :key="preference.category"
              class="px-4 py-3"
            >
              <p class="text-sm font-medium text-gray-900">{{ preference.label }}</p>
              <div class="mt-2 grid grid-cols-2 gap-2 text-xs text-gray-600">
                <label class="inline-flex items-center gap-1.5">
                  <input v-model="preference.in_app_enabled" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
                  In-app
                </label>
                <label class="inline-flex items-center gap-1.5">
                  <input v-model="preference.email_enabled" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
                  Email
                </label>
              </div>
            </div>
          </div>
          <div class="border-t border-gray-100 px-4 py-3">
            <button
              type="button"
              class="w-full rounded-md bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:bg-gray-300"
              :disabled="notificationStore.preferencesLoading"
              @click="savePreferences"
            >
              Save preferences
            </button>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useNotificationStore } from '@/stores/notifications'

const router = useRouter()
const notificationStore = useNotificationStore()

const stateOptions = [
  { value: 'all', label: 'All' },
  { value: 'unread', label: 'Unread' },
  { value: 'archived', label: 'Archived' },
]

const filters = reactive({
  state: 'all',
  category: '',
})

const loadNotifications = () => notificationStore.loadNotifications({
  state: filters.state,
  category: filters.category || undefined,
  limit: notificationStore.pageLimit,
})

const setState = (state) => {
  filters.state = state
}

const openNotification = async (notification) => {
  if (!notification?.is_read) {
    await notificationStore.markNotificationRead(notification.id, true)
  }
  if (notification?.action_url) {
    router.push(notification.action_url)
  }
}

const toggleRead = async (notification) => {
  await notificationStore.markNotificationRead(notification.id, !notification.is_read)
  await loadNotifications()
}

const toggleArchive = async (notification) => {
  await notificationStore.markNotificationArchived(notification.id, !notification.is_archived)
  await loadNotifications()
}

const markAllRead = async () => {
  await notificationStore.markAllRead()
  await loadNotifications()
}

const savePreferences = async () => {
  await notificationStore.savePreferences()
}

const formatDate = (value) => {
  if (!value) return ''
  try {
    return new Date(value).toLocaleString('de-DE', {
      day: '2-digit',
      month: '2-digit',
      year: '2-digit',
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

watch(() => [filters.state, filters.category], loadNotifications)

onMounted(async () => {
  await Promise.all([
    loadNotifications(),
    notificationStore.loadPreferences(),
  ])
})
</script>
