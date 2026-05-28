<template>
  <div class="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
    <div class="px-4 py-6 sm:px-0 space-y-6">
      <div class="flex items-start justify-between gap-4">
        <div>
          <h1 class="text-2xl font-semibold text-gray-900">API & Integration Activity</h1>
          <p class="mt-2 text-sm text-gray-600">
            Recent WebHDP API activity with route-family, service, and status filters for operational review.
          </p>
        </div>
        <button
          type="button"
          class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:opacity-50"
          :disabled="loading"
          @click="loadActivity"
        >
          {{ loading ? 'Refreshing…' : 'Refresh' }}
        </button>
      </div>

      <div class="bg-white rounded-xl border border-slate-200 p-4">
        <div class="grid grid-cols-1 md:grid-cols-4 gap-3">
          <select v-model="filters.routeFamily" class="px-3 py-2 rounded-lg border border-slate-300 bg-white text-sm">
            <option value="">All route families</option>
            <option value="sessions">sessions</option>
            <option value="admin">admin</option>
            <option value="tools">tools</option>
            <option value="setup">setup</option>
            <option value="pipelines">pipelines</option>
          </select>
          <select v-model="filters.service" class="px-3 py-2 rounded-lg border border-slate-300 bg-white text-sm">
            <option value="">All services</option>
            <option value="webhdp">webhdp</option>
            <option value="zenodo">zenodo</option>
            <option value="cloud_storage">cloud_storage</option>
            <option value="pipeline">pipeline</option>
            <option value="system">system</option>
          </select>
          <select v-model="filters.statusClass" class="px-3 py-2 rounded-lg border border-slate-300 bg-white text-sm">
            <option value="">All statuses</option>
            <option value="success">success</option>
            <option value="client_error">client_error</option>
            <option value="server_error">server_error</option>
          </select>
          <select v-model.number="filters.hours" class="px-3 py-2 rounded-lg border border-slate-300 bg-white text-sm">
            <option :value="24">Last 24 hours</option>
            <option :value="72">Last 72 hours</option>
            <option :value="168">Last 7 days</option>
          </select>
        </div>
        <div class="mt-3 text-right">
          <button
            type="button"
            class="px-4 py-2 text-sm font-medium text-slate-700 border border-slate-200 rounded-md hover:bg-slate-50"
            @click="loadActivity"
          >
            Apply Filters
          </button>
        </div>
      </div>

      <div v-if="error" class="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
        {{ error }}
      </div>

      <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div class="bg-white rounded-xl border border-slate-200 p-4">
          <p class="text-xs uppercase tracking-wide text-slate-500">Entries</p>
          <p class="mt-1 text-2xl font-bold text-slate-900">{{ summary.total_entries || 0 }}</p>
        </div>
        <div class="bg-white rounded-xl border border-slate-200 p-4">
          <p class="text-xs uppercase tracking-wide text-slate-500">Avg Duration</p>
          <p class="mt-1 text-2xl font-bold text-slate-900">{{ summary.average_duration_ms || 0 }} ms</p>
        </div>
        <div class="bg-white rounded-xl border border-slate-200 p-4">
          <p class="text-xs uppercase tracking-wide text-slate-500">Top Route Family</p>
          <p class="mt-1 text-xl font-bold text-slate-900">{{ topSummaryKey(summary.route_families) }}</p>
        </div>
        <div class="bg-white rounded-xl border border-slate-200 p-4">
          <p class="text-xs uppercase tracking-wide text-slate-500">Top Service</p>
          <p class="mt-1 text-xl font-bold text-slate-900">{{ topSummaryKey(summary.services) }}</p>
        </div>
      </div>

      <div class="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <table class="min-w-full divide-y divide-slate-200">
          <thead class="bg-slate-50">
            <tr>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Time</th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Method</th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Path</th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Family</th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Service</th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Status</th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Duration</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 bg-white">
            <tr v-if="entries.length === 0">
              <td colspan="7" class="px-4 py-8 text-center text-sm text-slate-500">No activity entries available for the selected filters.</td>
            </tr>
            <tr v-for="entry in entries" :key="`${entry.timestamp}-${entry.request_id || entry.path}`">
              <td class="px-4 py-3 text-sm text-slate-700">{{ formatDate(entry.timestamp) }}</td>
              <td class="px-4 py-3 text-sm font-medium text-slate-900">{{ entry.method }}</td>
              <td class="px-4 py-3 text-sm text-slate-700 break-all">{{ entry.path }}</td>
              <td class="px-4 py-3 text-sm text-slate-700">{{ entry.route_family }}</td>
              <td class="px-4 py-3 text-sm text-slate-700">{{ entry.service }}</td>
              <td class="px-4 py-3 text-sm" :class="entry.status_class === 'success' ? 'text-emerald-700' : entry.status_class === 'server_error' ? 'text-rose-700' : 'text-amber-700'">
                {{ entry.status_code }} · {{ entry.status_class }}
              </td>
              <td class="px-4 py-3 text-sm text-slate-700">{{ entry.duration_ms }} ms</td>
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
const error = ref('')
const entries = ref([])
const summary = ref({})
const filters = reactive({
  routeFamily: '',
  service: '',
  statusClass: '',
  hours: 24,
})

const formatDate = (value) => {
  if (!value) return 'N/A'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString()
}

const topSummaryKey = (value = {}) => {
  const items = Object.entries(value || {})
  if (!items.length) return 'n/a'
  items.sort((a, b) => b[1] - a[1])
  return items[0][0]
}

const loadActivity = async () => {
  loading.value = true
  error.value = ''
  try {
    const response = await adminService.getApiActivity({
      route_family: filters.routeFamily || undefined,
      service: filters.service || undefined,
      status_class: filters.statusClass || undefined,
      hours: filters.hours,
      limit: 100,
    })
    entries.value = response.data?.entries || []
    summary.value = response.data?.summary || {}
  } catch (err) {
    error.value = err.error?.message || err.error || err.message || 'Failed to load API activity.'
  } finally {
    loading.value = false
  }
}

onMounted(loadActivity)
</script>
