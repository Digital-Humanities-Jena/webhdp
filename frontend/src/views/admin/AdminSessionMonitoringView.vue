<template>
  <div class="min-h-screen bg-gray-50">
    <div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <div class="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 class="text-2xl font-semibold text-gray-900">Session Monitoring</h1>
          <p class="mt-1 text-sm text-gray-500">Running workflow sessions and active HPC-Link allocations.</p>
        </div>
        <button
          type="button"
          class="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60"
          :disabled="loading"
          @click="loadMonitoring"
        >
          {{ loading ? 'Refreshing...' : 'Refresh' }}
        </button>
      </div>

      <div class="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div class="rounded-lg border border-gray-200 bg-white p-4">
          <p class="text-xs font-medium uppercase tracking-wide text-gray-500">Running sessions</p>
          <p class="mt-2 text-2xl font-semibold text-gray-900">{{ summary.running_sessions ?? 0 }}</p>
        </div>
        <div class="rounded-lg border border-gray-200 bg-white p-4">
          <p class="text-xs font-medium uppercase tracking-wide text-gray-500">HPC allocations</p>
          <p class="mt-2 text-2xl font-semibold text-gray-900">{{ summary.active_hpc_allocations ?? 0 }}</p>
        </div>
        <div class="rounded-lg border border-gray-200 bg-white p-4">
          <p class="text-xs font-medium uppercase tracking-wide text-gray-500">Global HPC limit</p>
          <p class="mt-2 text-2xl font-semibold text-gray-900">{{ summary.global_hpc_limit ?? 3 }}</p>
        </div>
      </div>

      <section class="overflow-hidden rounded-lg border border-gray-200 bg-white">
        <div class="border-b border-gray-200 px-5 py-4">
          <h2 class="text-lg font-semibold text-gray-900">Running Sessions</h2>
        </div>
        <div v-if="loading" class="px-5 py-8 text-center text-sm text-gray-500">Loading sessions...</div>
        <div v-else-if="sessions.length === 0" class="px-5 py-8 text-center text-sm text-gray-500">No running sessions.</div>
        <div v-else class="overflow-x-auto">
          <table class="min-w-full divide-y divide-gray-200">
            <thead class="bg-gray-50">
              <tr>
                <th class="px-5 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">Session</th>
                <th class="px-5 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">User</th>
                <th class="px-5 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">Status</th>
                <th class="px-5 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">Files</th>
                <th class="px-5 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">Updated</th>
                <th class="px-5 py-3 text-right text-xs font-medium uppercase tracking-wide text-gray-500">Action</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-200 bg-white">
              <tr v-for="session in sessions" :key="session.id" :class="highlightSessionId === Number(session.id) ? 'bg-indigo-50' : ''">
                <td class="whitespace-nowrap px-5 py-4 text-sm font-medium text-gray-900">#{{ session.id }}</td>
                <td class="px-5 py-4 text-sm text-gray-700">{{ session.user?.email || 'Unknown user' }}</td>
                <td class="px-5 py-4 text-sm text-gray-700">{{ session.status }}</td>
                <td class="px-5 py-4 text-sm text-gray-700">{{ session.file_count || 0 }}</td>
                <td class="whitespace-nowrap px-5 py-4 text-sm text-gray-500">{{ formatDate(session.updated_at) }}</td>
                <td class="whitespace-nowrap px-5 py-4 text-right">
                  <button
                    type="button"
                    class="rounded-md border border-rose-200 px-3 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-50"
                    :disabled="terminatingSessionId === session.id"
                    @click="terminateSession(session)"
                  >
                    {{ terminatingSessionId === session.id ? 'Terminating...' : 'Terminate' }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="mt-6 overflow-hidden rounded-lg border border-gray-200 bg-white">
        <div class="border-b border-gray-200 px-5 py-4">
          <h2 class="text-lg font-semibold text-gray-900">HPC-Link Allocations</h2>
        </div>
        <div v-if="loading" class="px-5 py-8 text-center text-sm text-gray-500">Loading allocations...</div>
        <div v-else-if="allocations.length === 0" class="px-5 py-8 text-center text-sm text-gray-500">No active HPC allocations.</div>
        <div v-else class="overflow-x-auto">
          <table class="min-w-full divide-y divide-gray-200">
            <thead class="bg-gray-50">
              <tr>
                <th class="px-5 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">Allocation</th>
                <th class="px-5 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">User</th>
                <th class="px-5 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">Session</th>
                <th class="px-5 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">Status</th>
                <th class="px-5 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">Node</th>
                <th class="px-5 py-3 text-right text-xs font-medium uppercase tracking-wide text-gray-500">Action</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-200 bg-white">
              <tr v-for="allocation in allocations" :key="allocation.allocation_id">
                <td class="px-5 py-4 text-sm font-medium text-gray-900">{{ shortId(allocation.allocation_id) }}</td>
                <td class="px-5 py-4 text-sm text-gray-700">{{ allocation.user?.email || 'Unknown user' }}</td>
                <td class="px-5 py-4 text-sm text-gray-700">{{ allocation.session_id ? `#${allocation.session_id}` : 'Unattached' }}</td>
                <td class="px-5 py-4 text-sm text-gray-700">{{ allocation.status }}</td>
                <td class="px-5 py-4 text-sm text-gray-700">{{ allocation.node_name || allocation.scheduler_state || 'Pending' }}</td>
                <td class="whitespace-nowrap px-5 py-4 text-right">
                  <button
                    type="button"
                    class="rounded-md border border-rose-200 px-3 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-50"
                    :disabled="terminatingAllocationId === allocation.allocation_id"
                    @click="terminateAllocation(allocation)"
                  >
                    {{ terminatingAllocationId === allocation.allocation_id ? 'Terminating...' : 'Terminate' }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import adminService from '@/services/admin.service'
import { useToast } from '@/composables/useToast'

const route = useRoute()
const toast = useToast()

const loading = ref(false)
const sessions = ref([])
const allocations = ref([])
const summary = ref({})
const terminatingSessionId = ref(null)
const terminatingAllocationId = ref(null)

const highlightSessionId = computed(() => {
  const value = Number(route.query.session_id || 0)
  return Number.isFinite(value) ? value : 0
})

const loadMonitoring = async () => {
  loading.value = true
  try {
    const response = await adminService.getSessionMonitoring({ status: 'active' })
    sessions.value = response.data?.sessions || []
    allocations.value = response.data?.allocations || []
    summary.value = response.data?.summary || {}
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to load session monitoring')
  } finally {
    loading.value = false
  }
}

const terminateSession = async (session) => {
  if (!session?.id) return
  terminatingSessionId.value = session.id
  try {
    await adminService.terminateMonitoredSession(session.id)
    toast.success(`Session #${session.id} terminated`)
    await loadMonitoring()
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to terminate session')
  } finally {
    terminatingSessionId.value = null
  }
}

const terminateAllocation = async (allocation) => {
  if (!allocation?.allocation_id) return
  terminatingAllocationId.value = allocation.allocation_id
  try {
    await adminService.terminateMonitoredAllocation(allocation.allocation_id)
    toast.success('HPC allocation terminated')
    await loadMonitoring()
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to terminate HPC allocation')
  } finally {
    terminatingAllocationId.value = null
  }
}

const shortId = (value) => String(value || '').slice(0, 8)

const formatDate = (value) => {
  if (!value) return 'N/A'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

onMounted(loadMonitoring)
</script>
