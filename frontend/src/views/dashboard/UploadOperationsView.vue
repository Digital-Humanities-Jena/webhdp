<template>
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-6">
      <div>
        <h1 class="text-2xl font-bold text-gray-900">Uploads</h1>
        <p class="mt-1 text-sm text-gray-600">
          Check whether files are ready, then resume an upload to review metadata and choose a pipeline. Records are created when you start processing.
        </p>
      </div>
      <button
        type="button"
        class="px-4 py-2 text-sm font-medium text-indigo-600 border border-indigo-200 rounded-md hover:bg-indigo-50"
        @click="loadOperations"
      >
        Refresh
      </button>
    </div>

    <div v-if="loading" class="bg-white shadow rounded-lg p-6 text-center text-sm text-gray-500">
      Loading upload operations...
    </div>

    <div v-else-if="error" role="alert" class="bg-white shadow rounded-lg p-6 text-sm text-red-600">
      {{ error }}
    </div>

    <div v-else-if="operations.length === 0" class="bg-white shadow rounded-lg p-6 text-center text-sm text-gray-500">
      <p>Your uploads will appear here.</p>
      <div class="mt-3 flex flex-wrap justify-center gap-4">
        <router-link to="/workflow/upload" class="font-semibold text-indigo-700 underline">Upload files</router-link>
        <router-link :to="{ name: 'ModelPublicationTutorial' }" class="font-semibold text-indigo-700 underline">Try the 3D tutorial</router-link>
      </div>
    </div>

    <div v-else class="space-y-4">
      <div
        v-for="operation in operations"
        :key="operation.session_id"
        class="bg-white shadow rounded-lg p-5"
      >
        <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div class="min-w-0">
            <div class="flex items-center gap-3 flex-wrap">
              <h2 class="text-lg font-semibold text-gray-900">
                Session #{{ operation.session_id }}
              </h2>
              <span :class="statusClass(operation.progress?.current_stage)" class="px-2.5 py-1 text-xs font-medium rounded-full">
                {{ uploadStatusLabel(operation.progress?.current_stage || operation.status) }}
              </span>
              <span class="px-2.5 py-1 text-xs font-medium rounded-full bg-gray-100 text-gray-700">
                {{ operation.workspace?.type === 'institution' ? 'Institution workspace' : 'Personal workspace' }}
              </span>
              <span
                v-if="operation.workspace?.institution?.name"
                class="px-2.5 py-1 text-xs font-medium rounded-full bg-indigo-100 text-indigo-700"
              >
                {{ operation.workspace.institution.name }}
              </span>
              <span class="px-2.5 py-1 text-xs font-medium rounded-full bg-amber-100 text-amber-700">
                {{ formatCredentialSource(operation.publishing_context?.effective_credential_source) }}
              </span>
            </div>
            <p class="mt-1 text-sm text-gray-600">{{ operation.progress?.status_message || 'Upload processing' }}</p>
            <div class="mt-3 grid grid-cols-2 gap-3 text-xs text-gray-500 sm:grid-cols-4">
              <div>
                <p class="uppercase tracking-wide">Files</p>
                <p class="mt-1 text-sm font-medium text-gray-900">{{ operation.progress?.processed_count || 0 }} / {{ operation.progress?.total_files || 0 }}</p>
              </div>
              <div>
                <p class="uppercase tracking-wide">Failed</p>
                <p class="mt-1 text-sm font-medium text-gray-900">{{ operation.progress?.failed_count || 0 }}</p>
              </div>
              <div>
                <p class="uppercase tracking-wide">Storage</p>
                <p class="mt-1 text-sm font-medium text-gray-900">{{ formatMode(operation.storage_mode) }}</p>
              </div>
              <div>
                <p class="uppercase tracking-wide">Updated</p>
                <p class="mt-1 text-sm font-medium text-gray-900">{{ formatDate(operation.progress?.updated_at || operation.updated_at) }}</p>
              </div>
            </div>
          </div>

          <div class="w-full lg:max-w-xs">
            <div class="flex justify-between text-xs text-gray-500 mb-1">
              <span>{{ operation.progress?.processed_count || 0 }} processed</span>
              <span>{{ Math.round(operation.progress?.percent || 0) }}%</span>
            </div>
            <div class="w-full bg-gray-200 rounded-full h-2.5">
              <div
                class="bg-indigo-600 h-2.5 rounded-full transition-all duration-300"
                :style="{ width: `${Math.min(100, operation.progress?.percent || 0)}%` }"
              />
            </div>
            <div class="mt-4 flex gap-3">
              <router-link
                :to="`/uploads/${operation.session_id}`"
                class="px-4 py-2 text-sm font-medium text-indigo-700 border border-indigo-200 rounded-md hover:bg-indigo-50"
              >
                Details
              </router-link>
              <router-link
                v-if="operation.workflow_hint?.can_resume_workflow"
                :to="buildResumeLocation(operation)"
                class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700"
              >
                {{ operation.workflow_hint?.resume_label || 'Resume Workflow' }}
              </router-link>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import submissionService from '@/services/submission.service'
import { buildWorkflowResumeLocation } from '@/utils/workflowState'

const loading = ref(true)
const error = ref('')
const operations = ref([])
let refreshTimer = null

const hasRunningOperations = computed(() =>
  operations.value.some(operation => operation?.is_running)
)

const clearRefreshTimer = () => {
  if (refreshTimer) {
    window.clearTimeout(refreshTimer)
    refreshTimer = null
  }
}

const scheduleRefresh = () => {
  clearRefreshTimer()
  if (hasRunningOperations.value) {
    refreshTimer = window.setTimeout(loadOperations, 4000)
  }
}

const loadOperations = async () => {
  try {
    error.value = ''
    const response = await submissionService.listUploadOperations()
    operations.value = response.data?.operations || []
  } catch (err) {
    console.error('Failed to load upload operations:', err)
    error.value = err?.error?.message || 'Could not load uploads. Use Refresh to try again.'
  } finally {
    loading.value = false
    scheduleRefresh()
  }
}

const formatDate = (value) => {
  if (!value) return 'N/A'
  return new Date(value).toLocaleString()
}

const formatMode = (value) => {
  if (!value) return 'Unknown'
  return value.replace(/_/g, ' ')
}

const uploadStatusLabel = (status) => ({
  completed: 'Ready to review', awaiting_scan_start: 'Ready to check files', scanning: 'Checking files',
  processing: 'Checking files', failed: 'Needs attention', cancelled: 'Cancelled', pending: 'Waiting',
}[status] || (status ? status.replace(/_/g, ' ') : 'Waiting'))

const statusClass = (status) => {
  if (status === 'completed') return 'bg-green-100 text-green-800'
  if (status === 'failed') return 'bg-red-100 text-red-800'
  if (status === 'awaiting_scan_start') return 'bg-blue-100 text-blue-800'
  return 'bg-yellow-100 text-yellow-800'
}

const formatCredentialSource = (source) => {
  if (!source || source === 'none') return 'No Zenodo credential'
  return `${source.charAt(0).toUpperCase()}${source.slice(1)} credentials`
}

const buildResumeLocation = (operation) => (
  buildWorkflowResumeLocation(operation?.session_id, operation?.workflow_hint, '/workflow/upload')
)

onMounted(loadOperations)
onBeforeUnmount(clearRefreshTimer)
</script>
