<template>
  <div class="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
    <div class="px-4 py-6 sm:px-0 space-y-6">
      <div class="flex items-start justify-between gap-4">
        <div>
          <h1 class="text-2xl font-semibold text-gray-900">Credentials & Integrations</h1>
          <p class="mt-2 text-sm text-gray-600">
            Masked operational visibility for external integrations and targeted readiness checks.
          </p>
        </div>
        <button
          type="button"
          class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:opacity-50"
          :disabled="loading"
          @click="loadStatus"
        >
          {{ loading ? 'Refreshing…' : 'Refresh' }}
        </button>
      </div>

      <div v-if="error" class="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
        {{ error }}
      </div>

      <div class="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <section
          v-for="integration in integrations"
          :key="integration.id"
          class="bg-white rounded-xl border border-slate-200 p-5"
        >
          <div class="flex items-start justify-between gap-4">
            <div>
              <h2 class="text-lg font-semibold text-slate-900">{{ integration.label }}</h2>
              <p class="mt-1 text-xs uppercase tracking-wide text-slate-500">
                {{ integration.configured ? 'Configured' : 'Not configured' }}
              </p>
            </div>
            <button
              type="button"
              class="px-3 py-1.5 text-xs font-semibold rounded-lg border border-slate-200 text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              :disabled="runningCheckId === integration.id"
              @click="runCheck(integration.id)"
            >
              {{ runningCheckId === integration.id ? 'Checking…' : 'Run Check' }}
            </button>
          </div>

          <div class="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
            <div>
              <p class="text-slate-500">Masked value</p>
              <p class="font-medium text-slate-800 break-all">{{ integration.masked_value || 'n/a' }}</p>
            </div>
            <div>
              <p class="text-slate-500">Last check</p>
              <p class="font-medium text-slate-800">{{ integration.last_check?.checked_at ? formatDate(integration.last_check.checked_at) : 'Never' }}</p>
            </div>
            <div class="md:col-span-2">
              <p class="text-slate-500">Status</p>
              <p class="font-medium" :class="integration.last_check?.ok ? 'text-emerald-700' : 'text-slate-800'">
                {{ integration.last_check?.status || 'No validation recorded yet' }}
              </p>
            </div>
          </div>

          <pre class="mt-4 p-3 text-xs bg-slate-50 border border-slate-200 rounded-lg overflow-auto max-h-48">{{ formatJson(integration.details || {}) }}</pre>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import adminService from '@/services/admin.service'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const loading = ref(true)
const runningCheckId = ref('')
const error = ref('')
const integrations = ref([])

const formatDate = (value) => {
  if (!value) return 'N/A'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString()
}

const formatJson = (value) => {
  try {
    return JSON.stringify(value || {}, null, 2)
  } catch {
    return String(value)
  }
}

const loadStatus = async () => {
  loading.value = true
  error.value = ''
  try {
    const response = await adminService.getCredentialsStatus()
    integrations.value = response.data?.integrations || []
  } catch (err) {
    error.value = err.error?.message || err.error || err.message || 'Failed to load credentials status.'
  } finally {
    loading.value = false
  }
}

const runCheck = async (checkId) => {
  runningCheckId.value = checkId
  try {
    await adminService.runObservabilityCheck(checkId)
    toast.success('Observability check completed')
    await loadStatus()
  } catch (err) {
    toast.error(err.error?.message || err.error || err.message || 'Failed to run observability check')
  } finally {
    runningCheckId.value = ''
  }
}

onMounted(loadStatus)
</script>
