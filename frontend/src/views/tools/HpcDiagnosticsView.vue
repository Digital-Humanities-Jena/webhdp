<template>
  <div class="bg-white rounded-lg shadow p-6 space-y-5">
    <div class="flex items-start justify-between">
      <div>
        <h2 class="text-xl font-semibold text-gray-900">HPC Diagnostics</h2>
        <p class="mt-1 text-sm text-gray-600">Live runtime checks for core services, storage paths, database state, and session counters.</p>
      </div>
      <button @click="refresh" :disabled="loading || !isEnabled" class="px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50">
        {{ loading ? 'Refreshing…' : 'Refresh' }}
      </button>
    </div>

    <div v-if="!isEnabled" class="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
      Requires Admin role.
    </div>

    <div v-if="diagnostics" class="space-y-4">
      <div class="grid grid-cols-1 md:grid-cols-4 gap-3">
        <div class="rounded border p-3"><p class="text-xs text-gray-500">Storage mode</p><p class="text-lg font-semibold text-gray-900">{{ diagnostics.storage_mode || 'n/a' }}</p></div>
        <div class="rounded border p-3"><p class="text-xs text-gray-500">Sessions total</p><p class="text-lg font-semibold text-gray-900">{{ diagnostics.sessions?.total || 0 }}</p></div>
        <div class="rounded border p-3"><p class="text-xs text-gray-500">Live workflow sessions</p><p class="text-lg font-semibold text-gray-900">{{ diagnostics.sessions?.live ?? diagnostics.sessions?.active_or_processing ?? 0 }}</p></div>
        <div class="rounded border p-3"><p class="text-xs text-gray-500">DB size</p><p class="text-lg font-semibold text-gray-900">{{ formatBytes(diagnostics.db?.size_bytes || 0) }}</p></div>
      </div>

      <div class="rounded border p-4">
        <h3 class="text-sm font-semibold text-gray-900 mb-2">Service Health</h3>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
          <div v-for="(service, key) in diagnostics.services || {}" :key="key" class="rounded border p-2">
            <p class="font-semibold" :class="service.ok ? 'text-green-700' : 'text-red-700'">{{ key }}: {{ service.ok ? 'ok' : 'failed' }}</p>
            <p class="text-gray-600 break-all">{{ service.url || service.message || '' }}</p>
          </div>
        </div>
      </div>

      <div class="rounded border p-4">
        <h3 class="text-sm font-semibold text-gray-900 mb-2">Path Status</h3>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-2 text-xs">
          <div v-for="(pathInfo, key) in diagnostics.paths || {}" :key="key" class="rounded border p-2">
            <p class="font-semibold" :class="pathInfo.exists ? 'text-green-700' : 'text-red-700'">{{ key }}: {{ pathInfo.exists ? 'exists' : 'missing' }}</p>
            <p class="text-gray-600 break-all">{{ pathInfo.path }}</p>
            <p v-if="pathInfo.total_bytes" class="text-gray-500">Free {{ formatBytes(pathInfo.free_bytes) }} / {{ formatBytes(pathInfo.total_bytes) }}</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useToast } from '@/composables/useToast'
import toolsService from '@/services/tools.service'

const { error: showError } = useToast()

const isEnabled = ref(false)
const loading = ref(false)
const diagnostics = ref(null)

const formatBytes = (value) => {
  const bytes = Number(value || 0)
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let unitIdx = -1
  let current = bytes
  do {
    current /= 1024
    unitIdx += 1
  } while (current >= 1024 && unitIdx < units.length - 1)
  return `${current.toFixed(1)} ${units[unitIdx]}`
}

const refresh = async () => {
  if (!isEnabled.value) return
  loading.value = true
  try {
    const response = await toolsService.getHpcDiagnostics()
    diagnostics.value = response.data || null
  } catch (e) {
    showError(e?.message || 'Failed to load diagnostics.')
  } finally {
    loading.value = false
  }
}

const loadContext = async () => {
  try {
    const context = await toolsService.getContext()
    isEnabled.value = !!context.data?.features?.hpc_diagnostics?.enabled
  } catch (e) {
    isEnabled.value = false
  }
  await refresh()
}

onMounted(loadContext)
</script>
