<template>
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
    <div class="mb-6">
      <router-link :to="route.params.runId && details?.submission.session_id ? `/sessions/${details.submission.session_id}/records` : '/submissions'" class="text-indigo-600 hover:text-indigo-800">
        &larr; {{ route.params.runId && details?.submission.session_id ? 'Back to Session Records' : 'Back to Submissions' }}
      </router-link>
    </div>

    <LoadingSpinner v-if="loading" size="lg" text="Loading submission details..." />

    <div v-else-if="error" class="bg-white shadow rounded-lg p-6">
      <Alert v-model="hasError" variant="error" :message="error" :dismissible="false" />
    </div>

    <div v-else-if="details" class="space-y-6">

      <div class="bg-white shadow rounded-lg p-6">
        <div class="flex justify-between items-start mb-6">
          <div>
            <h2 class="text-2xl font-bold text-gray-900">{{ route.params.runId ? 'Processing Run' : `Submission #${details.submission.id}` }}</h2>
            <p class="mt-1 text-sm text-gray-500">
              Submitted {{ formatDate(details.submission.created_at) }}
            </p>
          </div>
          <span
            :class="[
              'px-3 py-1 text-sm font-medium rounded-full',
              statusClass(details.submission.status)
            ]"
          >
            {{ details.submission.status }}
          </span>
        </div>
        <dl class="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <dt class="text-sm font-medium text-gray-500">Pipeline</dt>
            <dd class="mt-1 text-sm text-gray-900">{{ details.submission.pipeline_id }}</dd>
          </div>
          <div v-if="details.submission.session_id">
            <dt class="text-sm font-medium text-gray-500">Session Records</dt>
            <dd class="mt-1">
              <router-link
                :to="`/sessions/${details.submission.session_id}/records`"
                class="text-sm font-medium text-indigo-600 hover:text-indigo-800"
              >
                View Zenodo Records for this session
              </router-link>
            </dd>
            <dd class="mt-1">
              <router-link
                :to="`/sessions/${details.submission.session_id}/provenance-report`"
                class="text-sm font-medium text-emerald-600 hover:text-emerald-800"
              >
                View Provenance Report
              </router-link>
            </dd>
          </div>
          <div v-if="details.submission.completed_at">
            <dt class="text-sm font-medium text-gray-500">Completed At</dt>
            <dd class="mt-1 text-sm text-gray-900">{{ formatDate(details.submission.completed_at) }}</dd>
          </div>
        </dl>
      </div>

      <div v-if="details.submission.status === 'processing' && liveProgress" class="bg-white shadow rounded-lg p-6">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-lg font-semibold text-gray-900">Live Processing Progress</h3>
          <span class="text-xs font-medium text-yellow-700 bg-yellow-100 px-2.5 py-1 rounded-full">
            Running
          </span>
        </div>
        <p class="text-sm text-gray-600">{{ liveProgress.status_message || 'Processing submission' }}</p>
        <div class="mt-4">
          <div class="flex justify-between text-sm text-gray-600 mb-1">
            <span>{{ liveProgress.processed_count || 0 }} / {{ liveProgress.total_files || 0 }} processed</span>
            <span>{{ progressPercent }}%</span>
          </div>
          <div class="w-full bg-gray-200 rounded-full h-2.5">
            <div
              class="bg-indigo-600 h-2.5 rounded-full transition-all duration-300"
              :style="{ width: `${progressPercent}%` }"
            />
          </div>
          <p v-if="liveProgress.failed_count" class="mt-2 text-sm text-red-600">
            {{ liveProgress.failed_count }} file(s) failed so far.
          </p>
        </div>
      </div>

      <div class="bg-white shadow rounded-lg p-6">
        <div class="flex justify-between items-center mb-4">
          <h3 class="text-lg font-semibold text-gray-900">Processing Result</h3>
          <button
            @click="handleDownloadJson"
            class="px-3 py-1 text-xs font-medium text-indigo-600 border border-indigo-200 rounded-full hover:bg-indigo-50"
            title="Download Zenodo response"
          >
            Download JSON
          </button>
        </div>

        <SubmissionOutcomes :outcomes="details.outcomes" :can-edit="details.can_edit !== false" />
        <details class="mt-4">
          <summary class="cursor-pointer text-sm text-slate-600">Technical processing result</summary>
        <div v-if="details.submission.status === 'completed' && zenodoLink">
          <p class="text-sm text-gray-700">
            Successfully processed.
            <a :href="zenodoLink" target="_blank" class="font-medium text-indigo-600 hover:text-indigo-800">
              View on Zenodo
            </a>
          </p>
          <p v-if="zenodoDOI" class="text-sm text-gray-500 mt-1">
            DOI: {{ zenodoDOI }}
          </p>
          <!-- Local Mirroring Info -->
          <div v-if="mirroredPath" class="mt-3 p-3 bg-indigo-50 rounded-md border border-indigo-100">
            <p class="text-xs font-semibold text-indigo-800 mb-1 flex items-center">
              <svg class="w-4 h-4 mr-1" fill="currentColor" viewBox="0 0 20 20">
                <path d="M7 9a2 2 0 012-2h6a2 2 0 012 2v6a2 2 0 01-2 2H9a2 2 0 01-2-2V9z" />
                <path d="M5 5a2 2 0 012-2h6a2 2 0 012 2v2H7a4 4 0 00-4 4v5a2 2 0 01-2-2V7a2 2 0 012-2h2V5z" />
              </svg>
              Mirrored to Local Storage
            </p>
            <p class="text-xs text-indigo-700 break-all font-mono">{{ mirroredPath }}</p>
          </div>
        </div>
        <pre v-else class="bg-gray-50 p-4 rounded-lg overflow-auto text-sm text-gray-700">{{ formatJson(details.submission.result) }}</pre>
        </details>
      </div>

      <!-- Performance Metrics Section -->
      <div v-if="submissionTimings" class="bg-white shadow rounded-lg p-6">
        <h3 class="text-lg font-semibold text-gray-900 mb-4">Performance Metrics</h3>
        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <div v-for="(time, key) in submissionTimings" :key="key" class="p-3 bg-gray-50 rounded-lg border border-gray-100">
            <dt class="text-xs font-medium text-gray-500 uppercase tracking-wider capitalize">{{ key.replace(/_/g, ' ') }}</dt>
            <dd class="mt-1 text-lg font-mono font-bold text-indigo-600">
              {{ typeof time === 'number' ? time.toFixed(2) + 's' : time }}
            </dd>
          </div>
        </div>
      </div>

      <details class="bg-white shadow rounded-lg p-6">
        <summary class="cursor-pointer font-semibold text-gray-900">Zenodo response details</summary>
        <div class="flex justify-between items-center mb-4">
          <h3 class="text-lg font-semibold text-gray-900">Zenodo Response</h3>
        </div>

        <div v-if="details.submission.status === 'completed' && zenodoLink">
          <p class="text-sm text-gray-700">
            Successfully processed.
            <a :href="zenodoLink" target="_blank" class="font-medium text-indigo-600 hover:text-indigo-800">
              View on Zenodo
            </a>
          </p>
          <p v-if="zenodoDOI" class="text-sm text-gray-500 mt-1">
            DOI: {{ zenodoDOI }}
          </p>
        </div>
        <pre v-else class="bg-gray-50 p-4 rounded-lg overflow-auto text-sm text-gray-700">{{ formatJson(details.zenodo_response) }}</pre>
      </details>

      <details class="bg-white shadow rounded-lg p-6">
        <summary class="cursor-pointer font-semibold text-gray-900 mb-4">Submitted metadata details</summary>
        <pre class="bg-gray-50 p-4 rounded-lg overflow-auto text-sm text-gray-700">{{ formatJson(details.metadata) }}</pre>
      </details>

      <div class="bg-white shadow rounded-lg p-6">
        <div class="flex items-start justify-between gap-4 mb-4">
          <div>
            <h3 class="text-lg font-semibold text-gray-900">{{ route.params.runId ? 'Registered record sources' : 'Processed Files' }} ({{ details.files.length }})</h3>
            <p class="mt-1 text-sm text-gray-500">
              {{ route.params.runId ? 'Review each record’s processing outcome above.' : 'These are the files actually processed in this submission.' }}
            </p>
          </div>
          <div v-if="details.file_summary" class="text-right text-xs text-gray-500">
            <p>Selected: {{ details.file_summary.selected_file_count || 0 }}</p>
            <p>Available in session: {{ details.file_summary.session_file_count || 0 }}</p>
          </div>
        </div>
        <ul class="divide-y divide-gray-200">
          <li v-for="file in details.files" :key="file.path" class="py-2">
            <p class="text-sm font-medium text-gray-900">{{ file.filename }}</p>
            <p class="text-xs text-gray-500">{{ file.path }}</p>
          </li>
        </ul>
        <p
          v-if="details.file_summary?.available_not_processed_count"
          class="mt-4 text-sm text-gray-600"
        >
          {{ details.file_summary.available_not_processed_count }} additional session file{{ details.file_summary.available_not_processed_count === 1 ? '' : 's' }}
          were available but not selected for this submission.
        </p>
      </div>

      <div
        v-if="details.available_files?.length"
        class="bg-white shadow rounded-lg p-6"
      >
        <h3 class="text-lg font-semibold text-gray-900 mb-4">
          Available but Not Processed ({{ details.available_files.length }})
        </h3>
        <ul class="divide-y divide-gray-200">
          <li v-for="file in details.available_files" :key="`available-${file.path}`" class="py-2">
            <p class="text-sm font-medium text-gray-900">{{ file.filename }}</p>
            <p class="text-xs text-gray-500">{{ file.path }}</p>
          </li>
        </ul>
      </div>

    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import submissionService from '@/services/submission.service.js'
import pipelineService from '@/services/pipeline.service.js'
import SubmissionOutcomes from '@/components/workflow/SubmissionOutcomes.vue'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import Alert from '@/components/ui/Alert.vue'

const route = useRoute()

const loading = ref(true)
const details = ref(null)
const error = ref('')
const hasError = computed(() => !!error.value)
const liveProgress = ref(null)
let pollTimer = null

const formatDate = (dateString) => {
  if (!dateString) return 'N/A'
  const date = new Date(dateString)
  return date.toLocaleString()
}

// This function is now correct and will handle all cases
const formatJson = (data) => {
  if (data === null || data === undefined) return 'N/A'

  if (typeof data === 'string') {
    try {
      const parsedData = JSON.parse(data)
      return JSON.stringify(parsedData, null, 2)
    } catch (e) {
      return data;
    }
  }

  try {
    return JSON.stringify(data, null, 2)
  } catch (e) {
    return String(data)
  }
}

const statusClass = (status) => {
  switch (status) {
    case 'completed': return 'bg-green-100 text-green-800'
    case 'processing': return 'bg-yellow-100 text-yellow-800'
    case 'failed': return 'bg-red-100 text-red-800'
    default: return 'bg-gray-100 text-gray-800'
  }
}

const zenodoLink = computed(() => {
  try {
    const record = details.value?.zenodo_response?.[0];

    if (details.value?.submission?.result) {
        const subResult = JSON.parse(details.value.submission.result);
        if (subResult?.links?.html) {
            return subResult.links.html;
        }
    }

    // If not in submission.result, check the .hdpc data
    const hdpcRecord = details.value?.zenodo_response?.[0];
    const pipelineResult = JSON.parse(details.value.submission.result)
    return pipelineResult?.links?.html

  } catch (e) {
    return null
  }
})

const zenodoDOI = computed(() => {
  try {
    // Check submission.result first
    if (details.value?.submission?.result) {
        const subResult = JSON.parse(details.value.submission.result);
        if (subResult?.doi) {
            return subResult.doi;
        }
    }

    // If not in submission.result, check the .hdpc data's metadata
    const hdpcRecord = details.value?.zenodo_response?.[0];
    if (hdpcRecord?.metadata?.doi) {
        return hdpcRecord.metadata.doi;
    }

    // Fallback for older data structures
    const pipelineResult = JSON.parse(details.value.submission.result)
    return pipelineResult?.doi

  } catch (e) {
    return null
  }
})

const mirroredPath = computed(() => {
  try {
    const subResult = JSON.parse(details.value.submission.result);
    return subResult?.mirrored_path || null;
  } catch (e) {
    return null;
  }
})

const progressPercent = computed(() => {
  const total = liveProgress.value?.total_files || 0
  const processed = liveProgress.value?.processed_count || 0
  if (!total) return 0
  return Math.round((processed / total) * 100)
})

const submissionTimings = computed(() => {
  try {
    const subResult = JSON.parse(details.value.submission.result);
    // Backend stores submission.timings as JSON string in DB,
    // but results might also contain it directly or it might be in details.submission.timings
    return subResult?.timings || (details.value.submission.timings ? JSON.parse(details.value.submission.timings) : null);
  } catch (e) {
    return null;
  }
})

const handleDownloadJson = () => {
  if (!details.value?.submission?.result) return

  const dataToDownload = details.value.submission.result
  const jsonString = formatJson(dataToDownload)

  const blob = new Blob([jsonString], { type: 'application/json' })
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `submission_${details.value.submission.id}_processing_result.json`
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.URL.revokeObjectURL(url)
}

const stopPolling = () => {
  if (pollTimer) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

const schedulePoll = () => {
  stopPolling()
  pollTimer = window.setTimeout(loadProgress, 2500)
}

const loadProgress = async () => {
  if (route.params.runId) { await loadDetails(); return }
  if (!details.value?.submission?.id) return

  try {
    const response = await submissionService.getSubmissionProgress(details.value.submission.id)
    const payload = response.data || {}
    liveProgress.value = payload.progress || null
    details.value.submission.status = payload.status || details.value.submission.status
    if (payload.timings) {
      details.value.submission.timings = JSON.stringify(payload.timings)
    }
    if (payload.status === 'processing') {
      schedulePoll()
      return
    }

    stopPolling()
    if (payload.status === 'completed' || payload.status === 'failed') {
      await loadDetails()
    }
  } catch (err) {
    console.error('Failed to fetch submission progress:', err)
    schedulePoll()
  }
}

const loadDetails = async () => {
  try {
    if (route.params.runId) {
      const response = await pipelineService.getPipelineRun(route.params.runId)
      const run = response.data.run
      details.value = { submission: { id: run.run_id, session_id: run.session_id, pipeline_id: run.pipeline_identifier,
        status: ['pending', 'running'].includes(run.status) ? 'processing' : run.status, result: JSON.stringify(run.result),
        timings: JSON.stringify(run.timings), created_at: run.started_at, completed_at: run.completed_at },
        outcomes: run.outcomes, can_edit: run.can_edit, files: (run.result.details || []).map(record => ({ path: record.file_path, filename: record.file_path?.split('/').pop() })),
        metadata: {}, zenodo_response: [] }
      liveProgress.value = run.result.progress || null
      if (details.value.submission.status === 'processing') schedulePoll()
      else stopPolling()
      return
    }
    const response = await submissionService.getSubmission(route.params.id)
    details.value = response.data
    if (details.value?.submission?.status === 'processing') {
      await loadProgress()
    } else {
      liveProgress.value = null
      stopPolling()
    }
  } catch (err) {
    console.error('Failed to load submission details:', err)
    error.value = err.error || 'Failed to load submission details.'
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadDetails()
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>
