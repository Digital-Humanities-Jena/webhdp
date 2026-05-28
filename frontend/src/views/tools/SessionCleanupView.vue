<template>
  <div class="bg-white rounded-lg shadow p-6 space-y-5">
    <div class="flex items-start justify-between">
      <div>
        <h2 class="text-xl font-semibold text-gray-900">Session Cleanup</h2>
        <p class="mt-1 text-sm text-gray-600">Find stale sessions and remove selected records (and optionally directories).</p>
      </div>
      <div class="flex space-x-2">
        <button @click="analyze" :disabled="loading || !isEnabled" class="px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50">
          {{ loading ? 'Analyzing…' : 'Analyze' }}
        </button>
        <button @click="executeCleanup" :disabled="executing || selectedIds.length === 0 || !isEnabled" class="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 disabled:opacity-50">
          {{ executing ? 'Deleting…' : `Delete (${selectedIds.length})` }}
        </button>
      </div>
    </div>

    <div v-if="!isEnabled" class="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
      Requires Admin role.
    </div>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-2">Older than (hours)</label>
        <input v-model.number="olderThanHours" :disabled="!isEnabled" type="number" min="0" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm disabled:bg-gray-100" />
      </div>
      <label class="inline-flex items-center mt-8 space-x-2 text-sm text-gray-700">
        <input v-model="deleteDirectories" :disabled="!isEnabled" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
        <span>Delete session directories from disk</span>
      </label>
      <label class="inline-flex items-center mt-8 space-x-2 text-sm text-gray-700">
        <input v-model="selectAll" :disabled="!isEnabled || candidates.length === 0" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" @change="toggleSelectAll" />
        <span>Select all candidates</span>
      </label>
    </div>

    <div v-if="analysis" class="text-xs text-gray-600">
      Candidates found: <span class="font-semibold">{{ analysis.candidate_count || 0 }}</span>
    </div>

    <div v-if="candidates.length > 0" class="rounded border overflow-auto max-h-[480px]">
      <table class="min-w-full text-xs">
        <thead class="bg-gray-50">
          <tr>
            <th class="px-2 py-2 text-left">Select</th>
            <th class="px-2 py-2 text-left">Session</th>
            <th class="px-2 py-2 text-left">Status</th>
            <th class="px-2 py-2 text-left">Age (h)</th>
            <th class="px-2 py-2 text-left">Files</th>
            <th class="px-2 py-2 text-left">Submissions</th>
            <th class="px-2 py-2 text-left">Reasons</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in candidates" :key="item.session_id" class="border-t">
            <td class="px-2 py-2">
              <input :value="item.session_id" v-model="selectedIds" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
            </td>
            <td class="px-2 py-2 font-medium text-gray-900">{{ item.session_id }}</td>
            <td class="px-2 py-2">{{ item.status }}</td>
            <td class="px-2 py-2">{{ item.age_hours }}</td>
            <td class="px-2 py-2">{{ item.file_count }}</td>
            <td class="px-2 py-2">{{ item.submission_count }}</td>
            <td class="px-2 py-2">{{ (item.reasons || []).join(', ') }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="lastExecution" class="rounded border p-3 text-xs text-gray-700">
      Removed: <span class="font-semibold">{{ lastExecution.removed_count || 0 }}</span>
      <span v-if="(lastExecution.missing_session_ids || []).length > 0"> | Missing: {{ lastExecution.missing_session_ids.join(', ') }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useToast } from '@/composables/useToast'
import toolsService from '@/services/tools.service'

const { success, error: showError } = useToast()

const isEnabled = ref(false)
const loading = ref(false)
const executing = ref(false)
const olderThanHours = ref(72)
const deleteDirectories = ref(true)
const selectAll = ref(false)

const analysis = ref(null)
const candidates = ref([])
const selectedIds = ref([])
const lastExecution = ref(null)

const loadContext = async () => {
  try {
    const response = await toolsService.getContext()
    isEnabled.value = !!response.data?.features?.session_cleanup?.enabled
  } catch (e) {
    isEnabled.value = false
  }
}

const analyze = async () => {
  if (!isEnabled.value) return
  loading.value = true
  try {
    const response = await toolsService.analyzeSessionCleanup({ older_than_hours: olderThanHours.value })
    analysis.value = response.data || null
    candidates.value = response.data?.candidates || []
    selectedIds.value = []
    selectAll.value = false
    success('Session cleanup analysis completed.')
  } catch (e) {
    showError(e?.message || 'Failed to analyze sessions.')
  } finally {
    loading.value = false
  }
}

const toggleSelectAll = () => {
  if (selectAll.value) {
    selectedIds.value = candidates.value.map((item) => item.session_id)
  } else {
    selectedIds.value = []
  }
}

const executeCleanup = async () => {
  if (!isEnabled.value || selectedIds.value.length === 0) return
  executing.value = true
  try {
    const response = await toolsService.executeSessionCleanup({
      session_ids: selectedIds.value,
      delete_directories: deleteDirectories.value
    })
    lastExecution.value = response.data || null
    success('Session cleanup executed.')
    await analyze()
  } catch (e) {
    showError(e?.message || 'Failed to execute cleanup.')
  } finally {
    executing.value = false
  }
}

onMounted(loadContext)
</script>
