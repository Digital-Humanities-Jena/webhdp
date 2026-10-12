<template>
  <div class="min-h-screen bg-gradient-to-b from-cyan-50 via-white to-slate-50">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 class="text-3xl font-bold text-slate-900">Cross-Session Records Explorer</h1>
          <p class="mt-1 text-sm text-slate-600">Find and inspect Zenodo records across sessions.</p>
        </div>
        <button
          type="button"
          class="px-3 py-2 text-sm font-medium border border-slate-200 rounded-lg text-slate-700 hover:bg-slate-50"
          @click="downloadJson"
          :disabled="!payload"
        >
          Export JSON
        </button>
      </div>

      <div class="bg-white rounded-xl border border-slate-200 p-4">
        <div class="flex flex-col lg:flex-row lg:items-end gap-3">
          <div class="flex-1">
            <h2 class="text-sm font-semibold text-slate-900">Import .hdpc File</h2>
            <p class="mt-1 text-xs text-slate-600">
              Upload a local `.hdpc` file to create a new session and add its encoded records to your explorer.
            </p>
            <p class="mt-1 text-xs text-rose-700">
              Sanitized shared exports import as explorer-only sessions. They stay read-only and cannot resume workflow or publishing actions.
            </p>
          </div>
          <div class="flex flex-col sm:flex-row gap-2 sm:items-center">
            <input
              ref="hdpcInput"
              type="file"
              accept=".hdpc"
              data-testid="hdpc-import-input"
              class="block w-full text-sm text-slate-700 file:mr-3 file:px-3 file:py-2 file:text-sm file:font-medium file:border file:border-slate-300 file:rounded-lg file:bg-slate-50 file:text-slate-700 hover:file:bg-slate-100"
              @change="onHdpcFileChange"
            />
            <button
              type="button"
              class="px-3 py-2 text-sm font-semibold text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed"
              data-testid="hdpc-import-submit"
              :disabled="importing || !hdpcFile"
              @click="handleImportHdpc"
            >
              {{ importing ? 'Importing...' : 'Import .hdpc' }}
            </button>
          </div>
        </div>
      </div>

      <div class="bg-white rounded-xl border border-slate-200 p-4">
        <div class="grid grid-cols-1 md:grid-cols-5 gap-3">
          <input
            v-model="filters.q"
            type="text"
            placeholder="Search title, DOI, IDs, owner..."
            class="px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-cyan-200"
            @keyup.enter="loadRecords"
          />
          <select
            v-model="filters.status"
            class="px-3 py-2 rounded-lg border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-cyan-200"
          >
            <option value="all">All statuses</option>
            <option value="published">Published</option>
            <option value="draft">Draft</option>
            <option value="other">Other</option>
          </select>
          <input
            v-model.number="filters.session_id"
            type="number"
            min="1"
            placeholder="Session ID"
            class="px-3 py-2 rounded-lg border border-slate-300 focus:outline-none focus:ring-2 focus:ring-cyan-200"
          />
          <select
            v-model="filters.sort"
            class="px-3 py-2 rounded-lg border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-cyan-200"
          >
            <option value="updated_desc">Newest first</option>
            <option value="updated_asc">Oldest first</option>
            <option value="title_asc">Title A-Z</option>
            <option value="title_desc">Title Z-A</option>
          </select>
          <div class="flex gap-2">
            <button
              type="button"
              class="flex-1 px-3 py-2 text-sm font-semibold text-white bg-cyan-600 rounded-lg hover:bg-cyan-700"
              @click="loadRecords"
              :disabled="loading"
            >
              Apply
            </button>
            <button
              type="button"
              class="px-3 py-2 text-sm font-medium border border-slate-300 rounded-lg text-slate-700 hover:bg-slate-50"
              @click="resetFilters"
              :disabled="loading"
            >
              Reset
            </button>
          </div>
        </div>
      </div>

      <LoadingSpinner v-if="loading" size="lg" text="Loading records explorer..." />

      <div v-else-if="error" class="bg-white rounded-xl border border-rose-200 p-6">
        <Alert v-model="showError" variant="error" :message="error" :dismissible="false" />
      </div>

      <div v-else-if="payload" class="space-y-6">
        <div class="grid grid-cols-2 md:grid-cols-5 gap-3">
          <div class="bg-white rounded-xl border border-slate-200 p-4">
            <p class="text-xs uppercase tracking-wide text-slate-500">Sessions Scanned</p>
            <p class="text-2xl font-bold text-slate-900">{{ summary.sessions_scanned || 0 }}</p>
          </div>
          <div class="bg-white rounded-xl border border-slate-200 p-4">
            <p class="text-xs uppercase tracking-wide text-slate-500">Records Found</p>
            <p class="text-2xl font-bold text-slate-900">{{ summary.records_found || 0 }}</p>
          </div>
          <div class="bg-white rounded-xl border border-cyan-200 p-4">
            <p class="text-xs uppercase tracking-wide text-cyan-600">Filtered</p>
            <p class="text-2xl font-bold text-cyan-700">{{ summary.records_filtered || 0 }}</p>
          </div>
          <div class="bg-white rounded-xl border border-indigo-200 p-4">
            <p class="text-xs uppercase tracking-wide text-indigo-600">Returned</p>
            <p class="text-2xl font-bold text-indigo-700">{{ summary.records_returned || 0 }}</p>
          </div>
          <div class="bg-white rounded-xl border border-amber-200 p-4">
            <p class="text-xs uppercase tracking-wide text-amber-600">Session Warnings</p>
            <p class="text-2xl font-bold text-amber-700">{{ sessionWarnings.length }}</p>
            <p class="mt-1 text-xs text-amber-700">
              {{ summary.failed_sessions || 0 }} failed · {{ summary.degraded_sessions || 0 }} degraded
            </p>
          </div>
        </div>

        <div
          v-if="summary.incomplete_results"
          class="bg-rose-50 border border-rose-200 rounded-xl p-4"
        >
          <p class="text-sm font-semibold text-rose-800">Results are incomplete</p>
          <p class="mt-1 text-sm text-rose-700">
            Some sessions could not be fully loaded. Review session warnings below before making decisions.
          </p>
        </div>

        <div v-if="sessionWarnings.length" class="bg-amber-50 border border-amber-200 rounded-xl p-4">
          <p class="text-sm font-semibold text-amber-800">Session data warnings</p>
          <ul class="mt-2 text-xs text-amber-700 space-y-1">
            <li
              v-for="warning in sessionWarnings.slice(0, 8)"
              :key="`${warning.session_id}-${warning.reason}`"
              :class="warning.severity === 'error' ? 'text-rose-700' : 'text-amber-700'"
            >
              Session {{ warning.session_id }}: {{ warning.reason }}
            </li>
          </ul>
        </div>

        <div v-if="records.length === 0" class="bg-white rounded-xl border border-slate-200 p-8 text-center text-slate-500">
          No records match the selected filters.
        </div>

        <div v-else class="bg-white rounded-xl border border-slate-200 overflow-hidden">
          <div class="overflow-x-auto">
            <table class="min-w-full divide-y divide-slate-200">
              <thead class="bg-slate-50">
                <tr>
                  <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Record</th>
                  <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Status</th>
                  <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Session</th>
                  <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Owner</th>
                  <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">DOI / ID</th>
                  <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Updated</th>
                  <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Actions</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100 bg-white">
                <tr v-for="record in records" :key="`${record.session_id}-${record.local_record_id}`" class="hover:bg-slate-50">
                  <td class="px-4 py-3 align-top">
                    <p class="text-sm font-medium text-slate-900">{{ record.record_title || 'Untitled record' }}</p>
                    <p class="text-xs text-slate-500">Local #{{ record.local_record_id }}</p>
                  </td>
                  <td class="px-4 py-3 align-top">
                    <span class="px-2 py-1 text-xs rounded-full border" :class="statusClass(record.record_status)">
                      {{ record.record_status || 'unknown' }}
                    </span>
                  </td>
                  <td class="px-4 py-3 align-top text-sm text-slate-700">
                    <p>#{{ record.session_id }}</p>
                    <p class="text-xs text-slate-500">{{ record.session_status || 'n/a' }}</p>
                  </td>
                  <td class="px-4 py-3 align-top text-sm text-slate-700">
                    <p>{{ record.owner_email || `User #${record.owner_user_id}` }}</p>
                  </td>
                  <td class="px-4 py-3 align-top text-sm text-slate-700">
                    <p class="break-all">{{ record.zenodo_doi || 'N/A' }}</p>
                    <p class="text-xs text-slate-500">Zenodo {{ record.zenodo_record_id || 'N/A' }}</p>
                  </td>
                  <td class="px-4 py-3 align-top text-sm text-slate-700">{{ formatDate(record.updated_at) }}</td>
                  <td class="px-4 py-3 align-top text-sm space-y-1">
                    <router-link
                      :to="`/sessions/${record.session_id}/records/${record.local_record_id}`"
                      class="block text-indigo-600 hover:text-indigo-800 font-medium"
                    >
                      Record Detail
                    </router-link>
                    <router-link
                      :to="`/sessions/${record.session_id}/records`"
                      class="block text-slate-600 hover:text-slate-800"
                    >
                      Session Records
                    </router-link>
                    <router-link
                      v-if="record.dataset_key"
                      :to="buildDatasetRoute(record.dataset_key, { environment: record.is_sandbox ? 'sandbox' : 'production' })"
                      class="block text-emerald-600 hover:text-emerald-800"
                    >
                      Dataset Workspace
                    </router-link>
                    <a
                      v-if="record.record_link"
                      :href="record.record_link"
                      target="_blank"
                      rel="noopener noreferrer"
                      class="block text-cyan-600 hover:text-cyan-800"
                    >
                      Open Zenodo
                    </a>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import submissionService from '@/services/submission.service.js'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import Alert from '@/components/ui/Alert.vue'
import { useToast } from '@/composables/useToast'
import { buildDatasetRoute } from '@/utils/datasetKey.js'

const loading = ref(true)
const payload = ref(null)
const error = ref('')
const showError = computed(() => !!error.value)
const toast = useToast()
const hdpcFile = ref(null)
const hdpcInput = ref(null)
const importing = ref(false)

const filters = ref({
  q: '',
  status: 'all',
  session_id: null,
  sort: 'updated_desc',
  limit_sessions: 25,
  max_records: 500,
})

const summary = computed(() => payload.value?.summary || {})
const records = computed(() => payload.value?.records || [])
const sessionWarnings = computed(() => payload.value?.session_warnings || [])

const formatDate = (dateString) => {
  if (!dateString) return 'N/A'
  const date = new Date(dateString)
  return Number.isNaN(date.getTime()) ? String(dateString) : date.toLocaleString()
}

const statusClass = (status) => {
  if (status === 'published') return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  if (status === 'draft') return 'bg-amber-50 text-amber-700 border-amber-200'
  return 'bg-slate-50 text-slate-700 border-slate-200'
}

const buildParams = () => {
  const params = {
    q: filters.value.q || undefined,
    status: filters.value.status,
    sort: filters.value.sort,
    limit_sessions: filters.value.limit_sessions,
    max_records: filters.value.max_records,
  }
  if (filters.value.session_id) {
    params.session_id = Number(filters.value.session_id)
  }
  return params
}

const loadRecords = async () => {
  loading.value = true
  error.value = ''

  try {
    const response = await submissionService.exploreRecords(buildParams())
    payload.value = response.data
  } catch (err) {
    console.error('Failed to load cross-session explorer:', err)
    error.value = err.error?.message || err.error || err.message || 'Failed to load records explorer.'
  } finally {
    loading.value = false
  }
}

const onHdpcFileChange = (event) => {
  hdpcFile.value = event.target.files?.[0] || null
}

const resetHdpcFile = () => {
  hdpcFile.value = null
  if (hdpcInput.value) {
    hdpcInput.value.value = ''
  }
}

const handleImportHdpc = async () => {
  if (!hdpcFile.value) {
    toast.error('Select a .hdpc file first')
    return
  }

  importing.value = true
  try {
    const response = await submissionService.importHdpc(hdpcFile.value)
    const sessionId = response?.data?.session?.id
    const recordCount = response?.data?.import_summary?.record_count
    const artifactKind = response?.data?.import_summary?.artifact_kind

    if (sessionId) {
      filters.value.session_id = Number(sessionId)
    }

    await loadRecords()
    const importModeNote = artifactKind === 'sanitized_shared' ? ' as explorer-only shared export' : ''
    toast.success(
      `Imported .hdpc${importModeNote} into session #${sessionId || 'N/A'}${recordCount !== undefined ? ` (${recordCount} records)` : ''}`
    )
    resetHdpcFile()
  } catch (err) {
    console.error('Failed to import .hdpc:', err)
    toast.error(err.error?.message || err.error || err.message || 'Failed to import .hdpc file')
  } finally {
    importing.value = false
  }
}

const resetFilters = () => {
  filters.value = {
    q: '',
    status: 'all',
    session_id: null,
    sort: 'updated_desc',
    limit_sessions: 25,
    max_records: 500,
  }
  loadRecords()
}

const downloadJson = () => {
  if (!payload.value) return
  const blob = new Blob([JSON.stringify(payload.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'cross_session_records_explorer.json'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

onMounted(() => {
  loadRecords()
})
</script>
