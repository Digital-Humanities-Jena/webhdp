<template>
  <div class="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
    <div class="mb-6">
      <router-link to="/uploads" class="text-indigo-600 hover:text-indigo-800">
        &larr; Back to Upload Operations
      </router-link>
    </div>

    <div v-if="loading" class="bg-white shadow rounded-lg p-6 text-center text-sm text-gray-500">
      Loading upload operation...
    </div>

    <div v-else-if="error" class="bg-white shadow rounded-lg p-6 text-sm text-red-600">
      {{ error }}
    </div>

    <div v-else-if="operation" class="space-y-6">
      <div class="bg-white shadow rounded-lg p-6">
        <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div class="flex items-center gap-3 flex-wrap">
              <h1 class="text-2xl font-bold text-gray-900">Upload Session #{{ operation.session_id }}</h1>
              <span :class="statusClass(operation.progress?.current_stage)" class="px-2.5 py-1 text-xs font-medium rounded-full">
                {{ operation.progress?.current_stage || operation.status }}
              </span>
            </div>
            <p class="mt-2 text-sm text-gray-600">{{ operation.progress?.status_message || 'Upload processing' }}</p>
            <p class="mt-2 text-xs text-indigo-700">
              Upload completion only means the scan is ready for workflow review. Records are created later during submit.
            </p>
            <dl class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <dt class="text-xs uppercase tracking-wide text-gray-500">Storage Mode</dt>
                <dd class="mt-1 text-sm font-medium text-gray-900">{{ formatMode(operation.storage_mode) }}</dd>
              </div>
              <div>
                <dt class="text-xs uppercase tracking-wide text-gray-500">Task ID</dt>
                <dd class="mt-1 text-sm font-mono text-gray-900 break-all">{{ operation.task_id || 'N/A' }}</dd>
              </div>
              <div>
                <dt class="text-xs uppercase tracking-wide text-gray-500">Worker Group</dt>
                <dd class="mt-1 text-sm font-mono text-gray-900 break-all">{{ operation.worker_group_id || 'N/A' }}</dd>
              </div>
              <div>
                <dt class="text-xs uppercase tracking-wide text-gray-500">Updated</dt>
                <dd class="mt-1 text-sm font-medium text-gray-900">{{ formatDate(operation.progress?.updated_at || operation.updated_at) }}</dd>
              </div>
            </dl>
          </div>

          <div class="flex gap-3">
            <router-link
              v-if="operation.workflow_hint?.can_resume_workflow"
              :to="resumeLocation"
              class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700"
            >
              {{ operation.workflow_hint?.resume_label || 'Resume Workflow' }}
            </router-link>
            <router-link
              to="/workflow/upload"
              class="px-4 py-2 text-sm font-medium text-indigo-600 border border-indigo-200 rounded-md hover:bg-indigo-50"
            >
              Back to Workflow
            </router-link>
          </div>
        </div>
      </div>

      <div class="bg-white shadow rounded-lg p-6">
        <div class="flex justify-between text-sm text-gray-600 mb-2">
          <span>{{ operation.progress?.processed_count || 0 }} processed of {{ operation.progress?.total_files || 0 }}</span>
          <span>{{ Math.round(operation.progress?.percent || 0) }}%</span>
        </div>
        <div class="w-full bg-gray-200 rounded-full h-3">
          <div
            class="bg-indigo-600 h-3 rounded-full transition-all duration-300"
            :style="{ width: `${Math.min(100, operation.progress?.percent || 0)}%` }"
          />
        </div>
        <div class="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div class="p-3 rounded-lg bg-gray-50">
            <p class="text-xs uppercase tracking-wide text-gray-500">Uploaded</p>
            <p class="mt-1 text-lg font-semibold text-gray-900">{{ operation.file_counts?.uploaded || 0 }}</p>
          </div>
          <div class="p-3 rounded-lg bg-gray-50">
            <p class="text-xs uppercase tracking-wide text-gray-500">Failed</p>
            <p class="mt-1 text-lg font-semibold text-gray-900">{{ operation.file_counts?.failed || 0 }}</p>
          </div>
          <div class="p-3 rounded-lg bg-gray-50">
            <p class="text-xs uppercase tracking-wide text-gray-500">Pending</p>
            <p class="mt-1 text-lg font-semibold text-gray-900">{{ operation.file_counts?.pending || 0 }}</p>
          </div>
          <div class="p-3 rounded-lg bg-gray-50">
            <p class="text-xs uppercase tracking-wide text-gray-500">Matched</p>
            <p class="mt-1 text-lg font-semibold text-gray-900">{{ operation.progress?.matched_files || 0 }}</p>
          </div>
        </div>
      </div>

      <div class="bg-white shadow rounded-lg p-6">
        <h2 class="text-lg font-semibold text-gray-900 mb-4">Operation Details</h2>
        <dl class="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <dt class="text-xs uppercase tracking-wide text-gray-500">Session Directory</dt>
            <dd class="mt-1 text-sm font-mono text-gray-900 break-all">{{ operation.session_dir || 'N/A' }}</dd>
          </div>
          <div>
            <dt class="text-xs uppercase tracking-wide text-gray-500">HDP Project</dt>
            <dd class="mt-1 text-sm font-mono text-gray-900 break-all">{{ operation.hdpc_path || 'N/A' }}</dd>
          </div>
          <div>
            <dt class="text-xs uppercase tracking-wide text-gray-500">Created</dt>
            <dd class="mt-1 text-sm text-gray-900">{{ formatDate(operation.created_at) }}</dd>
          </div>
          <div>
            <dt class="text-xs uppercase tracking-wide text-gray-500">Submit Token</dt>
            <dd class="mt-1 text-sm font-mono text-gray-900 break-all">{{ operation.submit_token || 'N/A' }}</dd>
          </div>
        </dl>

        <p v-if="operation.progress?.warning_message" class="mt-4 text-sm text-amber-700">
          {{ operation.progress.warning_message }}
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import submissionService from '@/services/submission.service'
import { buildWorkflowResumeLocation } from '@/utils/workflowState'

const route = useRoute()
const loading = ref(true)
const error = ref('')
const operation = ref(null)
let refreshTimer = null
const resumeLocation = computed(() => (
  buildWorkflowResumeLocation(operation.value?.session_id, operation.value?.workflow_hint, '/workflow/upload')
))

const clearRefreshTimer = () => {
  if (refreshTimer) {
    window.clearTimeout(refreshTimer)
    refreshTimer = null
  }
}

const loadOperation = async () => {
  try {
    error.value = ''
    const response = await submissionService.getUploadOperation(route.params.sessionId)
    operation.value = response.data?.operation || null
  } catch (err) {
    console.error('Failed to load upload operation:', err)
    error.value = err?.error || 'Failed to load upload operation.'
  } finally {
    loading.value = false
    clearRefreshTimer()
    if (operation.value?.is_running) {
      refreshTimer = window.setTimeout(loadOperation, 3000)
    }
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

const statusClass = (status) => {
  if (status === 'completed') return 'bg-green-100 text-green-800'
  if (status === 'failed') return 'bg-red-100 text-red-800'
  if (status === 'awaiting_scan_start') return 'bg-blue-100 text-blue-800'
  return 'bg-yellow-100 text-yellow-800'
}

onMounted(loadOperation)
onBeforeUnmount(clearRefreshTimer)
</script>
