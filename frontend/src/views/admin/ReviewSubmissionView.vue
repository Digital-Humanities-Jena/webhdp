<template>
  <div class="min-h-screen bg-gray-50">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <LoadingSpinner v-if="loading" size="lg" text="Loading submission details..." />

      <div v-else-if="submission" class="space-y-6">
        <div class="bg-white shadow rounded-lg p-6">
          <div class="flex justify-between items-start mb-6">
            <div>
              <h2 class="text-2xl font-bold text-gray-900">Submission #{{ submission.id }}</h2>
              <p class="mt-1 text-sm text-gray-500">Created {{ formatDate(submission.created_at) }}</p>
            </div>
            <span
              :class="[
                'px-3 py-1 text-sm font-medium rounded-full capitalize',
                submission.status === 'completed' ? 'bg-green-100 text-green-800' :
                submission.status === 'processing' ? 'bg-yellow-100 text-yellow-800' :
                submission.status === 'failed' ? 'bg-red-100 text-red-800' :
                'bg-gray-100 text-gray-800'
              ]"
            >
              {{ submission.status }}
            </span>
          </div>

          <dl class="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <dt class="text-sm font-medium text-gray-500">User</dt>
              <dd class="mt-1 text-sm text-gray-900">{{ user.email }}</dd>
            </div>
            <div>
              <dt class="text-sm font-medium text-gray-500">Pipeline</dt>
              <dd class="mt-1 text-sm text-gray-900">{{ submission.pipeline_id }}</dd>
            </div>
            <div>
              <dt class="text-sm font-medium text-gray-500">Session ID</dt>
              <dd class="mt-1 text-sm text-gray-900">{{ submission.session_id }}</dd>
            </div>
            <div v-if="submission.session_id">
              <dt class="text-sm font-medium text-gray-500">Session Records</dt>
              <dd class="mt-1">
                <router-link
                  :to="`/sessions/${submission.session_id}/records`"
                  class="text-sm font-medium text-indigo-600 hover:text-indigo-800"
                >
                  View Zenodo Records
                </router-link>
              </dd>
              <dd class="mt-1">
                <router-link
                  :to="`/sessions/${submission.session_id}/provenance-report`"
                  class="text-sm font-medium text-emerald-600 hover:text-emerald-800"
                >
                  View Provenance Report
                </router-link>
              </dd>
            </div>
            <div>
              <dt class="text-sm font-medium text-gray-500">Files Processed</dt>
              <dd class="mt-1 text-sm text-gray-900">{{ session.file_count }}</dd>
            </div>
            <div v-if="submission.completed_at">
              <dt class="text-sm font-medium text-gray-500">Completed At</dt>
              <dd class="mt-1 text-sm text-gray-900">{{ formatDate(submission.completed_at) }}</dd>
            </div>
          </dl>
        </div>

        <div v-if="submission.result" class="bg-white shadow rounded-lg p-6">
          <h3 class="text-lg font-semibold text-gray-900 mb-4">Processing Result</h3>
          <pre class="bg-gray-50 p-4 rounded-lg overflow-auto text-sm text-gray-700">{{ formatResult(submission.result) }}</pre>
        </div>

        <div class="bg-white shadow rounded-lg p-6">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-lg font-semibold text-gray-900">Timings</h3>
            <span v-if="submissionTimings && totalExecutionSeconds !== null" class="text-xs font-mono text-gray-500">
              Total: {{ formatSeconds(totalExecutionSeconds) }}
            </span>
          </div>

          <div v-if="!submissionTimings" class="text-sm text-gray-500">
            No timing data available for this submission.
          </div>

          <div v-else class="space-y-6">
            <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
              <div
                v-for="entry in timingSummaryEntries"
                :key="entry.key"
                class="p-3 bg-gray-50 rounded-lg border border-gray-200"
              >
                <dt class="text-xs font-medium text-gray-500 uppercase tracking-wide">{{ entry.label }}</dt>
                <dd class="mt-1 text-lg font-mono text-indigo-700">{{ formatSeconds(entry.value) }}</dd>
              </div>
            </div>

            <div>
              <h4 class="text-sm font-semibold text-gray-900 mb-2">Per Record Process Times</h4>
              <div v-if="recordTimingRows.length === 0" class="text-sm text-gray-500">
                No per-record timing entries were stored.
              </div>

              <div v-else class="space-y-4">
                <div
                  v-for="row in recordTimingRows"
                  :key="row.record_id"
                  class="border border-gray-200 rounded-lg p-4 bg-gray-50/60"
                >
                  <div class="flex flex-wrap items-center gap-2 mb-3">
                    <span class="text-xs font-semibold text-gray-600 uppercase">Record {{ row.record_id }}</span>
                    <span class="text-xs font-mono text-gray-500 break-all">{{ row.file_path || 'N/A' }}</span>
                  </div>

                  <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
                    <div
                      v-for="step in stepTimingEntries(row)"
                      :key="`${row.record_id}-${step.key}`"
                      class="rounded border border-gray-200 bg-white px-2 py-1"
                    >
                      <dt class="text-[11px] text-gray-500 uppercase tracking-wide">{{ step.label }}</dt>
                      <dd class="text-sm font-mono text-gray-800">{{ formatSeconds(step.value) }}</dd>
                    </div>
                  </div>

                  <div v-if="subprocessEntries(row).length > 0" class="mt-3 pt-3 border-t border-gray-200 space-y-2">
                    <h5 class="text-xs font-semibold text-gray-700 uppercase tracking-wide">Subprocesses</h5>
                    <div
                      v-for="group in subprocessEntries(row)"
                      :key="`${row.record_id}-${group.step}`"
                      class="rounded border border-gray-200 bg-white p-2"
                    >
                      <p class="text-xs font-medium text-gray-700 mb-1">{{ humanizeTimingKey(group.step) }}</p>
                      <dl class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-1">
                        <div
                          v-for="item in group.entries"
                          :key="`${row.record_id}-${group.step}-${item.key}`"
                          class="flex items-center justify-between gap-2 text-xs"
                        >
                          <dt class="text-gray-500">{{ humanizeTimingKey(item.key) }}</dt>
                          <dd class="font-mono text-gray-800">{{ formatSeconds(item.value) }}</dd>
                        </div>
                      </dl>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <details class="rounded border border-gray-200 bg-gray-50 p-3">
              <summary class="text-sm font-medium text-gray-700 cursor-pointer">Raw timing payload</summary>
              <pre class="mt-2 max-h-96 overflow-auto text-xs text-gray-700">{{ formatResult(JSON.stringify(submissionTimings)) }}</pre>
            </details>
          </div>
        </div>

        <div class="bg-white shadow rounded-lg p-6">
          <h3 class="text-lg font-semibold text-gray-900 mb-4">Review History</h3>
          <div v-if="!review_history || review_history.length === 0" class="text-gray-500 text-sm">
            No review history for this submission.
          </div>
          <ul v-else class="space-y-4">
            <li v-for="review in review_history" :key="review.id" class="border-b border-gray-200 pb-4 last:border-b-0">
              <p class="text-sm">
                <span class="font-medium text-gray-900">{{ review.moderator_email }}</span>
                <span v-if="review.action === 'status_change' && review.new_status" class="text-gray-700">
                  changed status to <span class="font-semibold capitalize">{{ review.new_status }}</span>
                </span>
                <span v-else class="text-gray-700">
                  left a comment
                </span>
              </p>
              <p v-if="review.comment" class="mt-2 p-3 bg-gray-50 rounded-md text-sm text-gray-700 whitespace-pre-wrap">
                {{ review.comment }}
              </p>
              <p class="text-xs text-gray-400 mt-2">{{ formatDate(review.created_at) }}</p>
            </li>
          </ul>
        </div>

        <div class="bg-white shadow rounded-lg p-6">
          <h3 class="text-lg font-semibold text-gray-900 mb-4">Add Review</h3>
          <form @submit.prevent="handleAddReview">
            <div class="space-y-4">
              <div>
                <label for="review-comment" class="block text-sm font-medium text-gray-700">Comment</label>
                <textarea v-model="newReview.comment" id="review-comment" rows="4" class="mt-1 w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"></textarea>
              </div>
              <div>
                <label for="review-status" class="block text-sm font-medium text-gray-700">New Status (Optional)</label>
                <select v-model="newReview.new_status" id="review-status" class="mt-1 w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500 bg-white">
                  <option value="">-- No Change --</option>
                  <option value="approved">Approve</option>
                  <option value="rejected">Reject</option>
                  <option value="needs_revision">Needs Revision</option>
                  <option value="pending">Re-queue (Pending)</option>
                </select>
              </div>
              <button
                type="submit"
                :disabled="reviewSubmitting || (!newReview.comment && !newReview.new_status)"
                class="px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50 transition-colors"
              >
                {{ reviewSubmitting ? 'Submitting...' : 'Submit Review' }}
              </button>
            </div>
          </form>
        </div>

        <div class="flex space-x-3">
          <button
            @click="handleExport"
            class="px-4 py-2 border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50"
          >
            Export Data
          </button>
          <button
            v-if="authStore.user?.role === 'admin'"
            @click="handleDelete"
            :disabled="deleting"
            class="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 disabled:opacity-50"
          >
            {{ deleting ? 'Deleting...' : 'Delete Submission' }}
          </button>
        </div>
      </div>

      <Alert v-model="showError" variant="error" :message="errorMessage" />
      <Alert v-model="showSuccess" variant="success" :message="successMessage" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import Alert from '@/components/ui/Alert.vue'
import api from '@/services/api'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth' // Import auth store

const router = useRouter()
const route = useRoute()
const toast = useToast()
const authStore = useAuthStore() // Initialize auth store

const loading = ref(true)
const deleting = ref(false)
const submission = ref(null)
const session = ref(null)
const user = ref(null)
const showError = ref(false)
const showSuccess = ref(false)
const errorMessage = ref('')
const successMessage = ref('')

// --- NEW: Refs for review functionality ---
const review_history = ref([])
const newReview = ref({ comment: '', new_status: '' })
const reviewSubmitting = ref(false)
// ---

const TIMING_LABELS = {
  project_loading: 'Project Loading',
  record_registration: 'Record Registration',
  batch_render: 'Batch Render',
  total_execution: 'Total Execution',
  render: 'Render',
  usdz: 'USDZ',
  zenodo_draft: 'Zenodo Draft',
  lod_generation: 'LOD Generation',
  local_edm_validator_validation: 'Local EDM Validator',
  zenodo_upload: 'Zenodo Upload',
  metis_api_validation: 'Local EDM Validator',
  total: 'Record Total'
}

const parseSeconds = (value) => {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value !== 'string') return null

  const normalized = value.trim().toLowerCase()
  if (!normalized) return null

  const candidate = normalized.endsWith('s') ? normalized.slice(0, -1).trim() : normalized
  const parsed = Number(candidate)
  return Number.isFinite(parsed) ? parsed : null
}

const humanizeTimingKey = (key) => TIMING_LABELS[key] || String(key || '').replace(/_/g, ' ')

const formatSeconds = (value) => {
  const parsed = parseSeconds(value)
  if (parsed === null) return 'N/A'
  return `${parsed.toFixed(3)}s`
}

const submissionTimings = computed(() => submission.value?.timings || null)

const totalExecutionSeconds = computed(() => parseSeconds(submissionTimings.value?.total_execution))

const timingSummaryEntries = computed(() => {
  if (!submissionTimings.value) return []

  const keys = ['project_loading', 'record_registration', 'batch_render', 'total_execution']
  return keys.map((key) => ({
    key,
    label: TIMING_LABELS[key] || key,
    value: submissionTimings.value[key]
  }))
})

const recordTimingRows = computed(() => {
  const rows = submissionTimings.value?.record_processing
  return Array.isArray(rows) ? rows : []
})

const stepTimingEntries = (row) => {
  const steps = row?.steps
  if (!steps || typeof steps !== 'object') return []

  return Object.entries(steps).map(([key, value]) => ({
    key,
    label: humanizeTimingKey(key),
    value
  }))
}

const subprocessEntries = (row) => {
  const groups = row?.subprocesses
  if (!groups || typeof groups !== 'object') return []

  return Object.entries(groups)
    .map(([step, timings]) => {
      if (!timings || typeof timings !== 'object') return null
      const entries = Object.entries(timings)
        .filter(([, value]) => parseSeconds(value) !== null)
        .map(([key, value]) => ({ key, value }))
      if (entries.length === 0) return null
      return { step, entries }
    })
    .filter(Boolean)
}

const formatDate = (dateString) => {
  if (!dateString) return 'N/A';
  const date = new Date(dateString)
  return date.toLocaleString()
}

const formatResult = (result) => {
  try {
    // Try parsing as JSON first
    return JSON.stringify(JSON.parse(result), null, 2)
  } catch {
    // If not JSON, return the raw string
    return result
  }
}

const loadSubmission = async () => {
  try {
    loading.value = true // Ensure loading is true at the start
    const submissionId = route.params.id
    const response = await api.get(`/admin/submissions/${submissionId}`)
    submission.value = response.data.submission
    session.value = response.data.session
    user.value = response.data.user
    review_history.value = response.data.review_history || [] // Store review history
  } catch (err) {
    errorMessage.value = 'Failed to load submission details'
    showError.value = true
  } finally {
    loading.value = false
  }
}

// --- NEW: Function to handle review submission ---
const handleAddReview = async () => {
  if (!newReview.value.comment && !newReview.value.new_status) {
    toast.error("Please add a comment or select a new status.");
    return;
  }

  reviewSubmitting.value = true
  try {
    await api.post(`/admin/submissions/${submission.value.id}/review`, {
      comment: newReview.value.comment || null,
      new_status: newReview.value.new_status || null,
    })
    toast.success('Review added successfully')
    newReview.value = { comment: '', new_status: '' } // Reset form
    await loadSubmission() // Reload details to show new review and status
  } catch (err)
 {
    toast.error(err.error || 'Failed to add review')
  } finally {
    reviewSubmitting.value = false
  }
}
// ---

const handleExport = () => {
  const data = {
    submission: submission.value,
    session: session.value,
    user: user.value,
    review_history: review_history.value
  }
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `submission-${submission.value.id}.json`
  a.click()
  URL.revokeObjectURL(url)
  toast.success('Data exported successfully')
}

const handleDelete = async () => {
  if (!confirm('Are you sure you want to delete this submission? This action is permanent.')) return

  deleting.value = true
  try {
    await api.delete(`/admin/submissions/${submission.value.id}`)
    toast.success('Submission deleted successfully')
    router.push('/admin/dashboard')
  } catch (err) {
    toast.error('Failed to delete submission')
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  loadSubmission()
})
</script>
