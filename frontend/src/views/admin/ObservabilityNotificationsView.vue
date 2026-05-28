<template>
  <div class="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
    <div class="px-4 py-6 sm:px-0 space-y-6">
      <div class="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div>
          <h1 class="text-2xl font-semibold text-gray-900">Notification Delivery</h1>
          <p class="mt-2 text-sm text-gray-600">
            Delivery attempts for immediate email and digest channels, including failures and skipped sends.
          </p>
        </div>
        <div class="flex flex-wrap gap-2">
          <button
            type="button"
            class="px-4 py-2 text-sm font-medium text-slate-700 border border-slate-200 rounded-md hover:bg-slate-50 disabled:opacity-50"
            :disabled="loading"
            @click="loadDeliveries"
          >
            {{ loading ? 'Refreshing...' : 'Refresh' }}
          </button>
          <button
            type="button"
            class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:opacity-50"
            :disabled="digestRunning"
            @click="runDigest"
          >
            {{ digestRunning ? 'Running digest...' : 'Run digest now' }}
          </button>
          <button
            type="button"
            class="px-4 py-2 text-sm font-medium text-white bg-slate-700 rounded-md hover:bg-slate-800 disabled:opacity-50"
            :disabled="cleanupRunning"
            @click="runCleanup"
          >
            {{ cleanupRunning ? 'Cleaning...' : 'Run cleanup' }}
          </button>
        </div>
      </div>

      <div class="bg-white rounded-xl border border-slate-200 p-4">
        <div class="grid grid-cols-1 md:grid-cols-6 gap-3">
          <select v-model="filters.channel" class="px-3 py-2 rounded-lg border border-slate-300 bg-white text-sm">
            <option value="">All channels</option>
            <option value="email">email</option>
            <option value="digest">digest</option>
          </select>
          <select v-model="filters.status" class="px-3 py-2 rounded-lg border border-slate-300 bg-white text-sm">
            <option value="">All statuses</option>
            <option value="sent">sent</option>
            <option value="failed">failed</option>
            <option value="skipped">skipped</option>
          </select>
          <input
            v-model="filters.recipientUserId"
            type="number"
            min="1"
            class="px-3 py-2 rounded-lg border border-slate-300 bg-white text-sm"
            placeholder="Recipient user ID"
          />
          <input
            v-model="filters.startAt"
            type="date"
            class="px-3 py-2 rounded-lg border border-slate-300 bg-white text-sm"
            aria-label="Start date"
          />
          <input
            v-model="filters.endAt"
            type="date"
            class="px-3 py-2 rounded-lg border border-slate-300 bg-white text-sm"
            aria-label="End date"
          />
          <button
            type="button"
            class="px-4 py-2 text-sm font-medium text-slate-700 border border-slate-200 rounded-md hover:bg-slate-50"
            @click="loadDeliveries"
          >
            Apply Filters
          </button>
        </div>
      </div>

      <div v-if="error" class="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
        {{ error }}
      </div>

      <div v-if="digestResult" class="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
        Digest {{ digestResult.batch_key }} sent to {{ digestResult.sent_users }} user(s), delivering
        {{ digestResult.delivered_notifications }} notification(s).
      </div>

      <div v-if="cleanupResult" class="rounded-md border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800">
        Cleanup deleted {{ cleanupResult.deleted_notifications }} notification(s) and
        {{ cleanupResult.deleted_deliveries }} delivery audit row(s).
      </div>

      <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div class="bg-white rounded-xl border border-slate-200 p-4">
          <p class="text-xs uppercase text-slate-500">Attempts</p>
          <p class="mt-1 text-2xl font-bold text-slate-900">{{ summary.total || 0 }}</p>
        </div>
        <div class="bg-white rounded-xl border border-slate-200 p-4">
          <p class="text-xs uppercase text-slate-500">Sent</p>
          <p class="mt-1 text-2xl font-bold text-emerald-700">{{ summary.statuses?.sent || 0 }}</p>
        </div>
        <div class="bg-white rounded-xl border border-slate-200 p-4">
          <p class="text-xs uppercase text-slate-500">Failed</p>
          <p class="mt-1 text-2xl font-bold text-rose-700">{{ summary.statuses?.failed || 0 }}</p>
        </div>
        <div class="bg-white rounded-xl border border-slate-200 p-4">
          <p class="text-xs uppercase text-slate-500">Skipped</p>
          <p class="mt-1 text-2xl font-bold text-amber-700">{{ summary.statuses?.skipped || 0 }}</p>
        </div>
      </div>

      <div class="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <table class="min-w-full divide-y divide-slate-200">
          <thead class="bg-slate-50">
            <tr>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase text-slate-500">Time</th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase text-slate-500">Channel</th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase text-slate-500">Status</th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase text-slate-500">Recipient</th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase text-slate-500">Notification</th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase text-slate-500">Batch</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 bg-white">
            <tr v-if="deliveries.length === 0">
              <td colspan="6" class="px-4 py-8 text-center text-sm text-slate-500">No delivery attempts match the selected filters.</td>
            </tr>
            <tr v-for="delivery in deliveries" :key="delivery.id">
              <td class="px-4 py-3 text-sm text-slate-700">{{ formatDate(delivery.created_at) }}</td>
              <td class="px-4 py-3 text-sm font-medium text-slate-900">{{ delivery.channel }}</td>
              <td class="px-4 py-3 text-sm" :class="statusClass(delivery.status)">
                {{ delivery.status }}
                <p v-if="delivery.error" class="mt-1 max-w-xs text-xs text-slate-500">{{ delivery.error }}</p>
              </td>
              <td class="px-4 py-3 text-sm text-slate-700">
                <p>{{ delivery.recipient?.email || `User ${delivery.recipient_user_id}` }}</p>
                <p class="text-xs text-slate-400">ID {{ delivery.recipient_user_id }}</p>
              </td>
              <td class="px-4 py-3 text-sm text-slate-700">
                <p class="font-medium text-slate-900">{{ delivery.notification?.title || `Notification ${delivery.notification_id}` }}</p>
                <p class="text-xs text-slate-500">{{ delivery.notification?.category_label }}</p>
              </td>
              <td class="px-4 py-3 text-xs text-slate-500 break-all">{{ delivery.batch_key || 'n/a' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import adminService from '@/services/admin.service'

const loading = ref(true)
const digestRunning = ref(false)
const cleanupRunning = ref(false)
const error = ref('')
const deliveries = ref([])
const summary = ref({})
const digestResult = ref(null)
const cleanupResult = ref(null)
const filters = reactive({
  channel: '',
  status: '',
  recipientUserId: '',
  startAt: '',
  endAt: '',
})

const formatDate = (value) => {
  if (!value) return 'N/A'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString()
}

const statusClass = (status) => {
  if (status === 'sent') return 'text-emerald-700'
  if (status === 'failed') return 'text-rose-700'
  return 'text-amber-700'
}

const loadDeliveries = async () => {
  loading.value = true
  error.value = ''
  try {
    const response = await adminService.getNotificationDeliveries({
      channel: filters.channel || undefined,
      status: filters.status || undefined,
      recipient_user_id: filters.recipientUserId || undefined,
      start_at: filters.startAt || undefined,
      end_at: filters.endAt || undefined,
      limit: 100,
    })
    deliveries.value = response.data?.deliveries || []
    summary.value = response.data?.summary || {}
  } catch (err) {
    error.value = err.error?.message || err.error || err.message || 'Failed to load notification deliveries.'
  } finally {
    loading.value = false
  }
}

const runDigest = async () => {
  digestRunning.value = true
  error.value = ''
  digestResult.value = null
  try {
    const response = await adminService.runNotificationDigest()
    digestResult.value = response.data || {}
    await loadDeliveries()
  } catch (err) {
    error.value = err.error?.message || err.error || err.message || 'Failed to run notification digest.'
  } finally {
    digestRunning.value = false
  }
}

const runCleanup = async () => {
  cleanupRunning.value = true
  error.value = ''
  cleanupResult.value = null
  try {
    const response = await adminService.cleanupNotifications({ batch_size: 1000 })
    cleanupResult.value = response.data || {}
    await loadDeliveries()
  } catch (err) {
    error.value = err.error?.message || err.error || err.message || 'Failed to run notification cleanup.'
  } finally {
    cleanupRunning.value = false
  }
}

onMounted(loadDeliveries)
</script>
