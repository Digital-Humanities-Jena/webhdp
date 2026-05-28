<template>
  <div class="bg-white rounded-lg shadow p-6 space-y-5">
    <div class="flex items-start justify-between">
      <div>
        <h2 class="text-xl font-semibold text-gray-900">MSF Reference Repair</h2>
        <p class="mt-1 text-sm text-gray-600">Auto-repair filename references by matching MSF values to scanned local files.</p>
      </div>
      <span class="px-3 py-1 text-xs font-semibold rounded-full" :class="isEnabled ? 'bg-green-100 text-green-800' : 'bg-amber-100 text-amber-800'">
        {{ isEnabled ? 'Enabled' : 'Disabled' }}
      </span>
    </div>

    <div v-if="!isEnabled" class="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
      Requires Admin role and local storage mode.
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-2">MSF File</label>
        <select v-model="selectedMsfPath" :disabled="!isEnabled" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm disabled:bg-gray-100">
          <option value="" disabled>-- Select an MSF file --</option>
          <option v-for="file in msfFiles" :key="file.full_path" :value="file.full_path">{{ file.path }}</option>
        </select>
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-2">Subdirectory (optional)</label>
        <input v-model="directoryPath" :disabled="!isEnabled" type="text" placeholder="rcin" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm disabled:bg-gray-100" />
      </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-2">Column to repair</label>
        <input v-model="columnName" :disabled="!isEnabled" type="text" placeholder="filename" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm disabled:bg-gray-100" />
      </div>
      <div class="space-y-2 pt-6">
        <label class="inline-flex items-center space-x-2 text-sm text-gray-700">
          <input v-model="matchByStem" :disabled="!isEnabled" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
          <span>Allow stem-only match fallback</span>
        </label>
        <label class="inline-flex items-center space-x-2 text-sm text-gray-700">
          <input v-model="keepUnresolved" :disabled="!isEnabled" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
          <span>Keep unresolved values unchanged</span>
        </label>
      </div>
    </div>

    <div class="flex justify-end space-x-2">
      <button @click="runRepair" :disabled="!canRun || running" class="px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50">
        {{ running ? 'Running…' : 'Run Repair' }}
      </button>
      <button @click="download('csv')" :disabled="!result || downloading" class="px-4 py-2 bg-gray-100 text-gray-900 rounded-md hover:bg-gray-200 disabled:opacity-50">CSV</button>
      <button @click="download('xlsx')" :disabled="!result || downloading" class="px-4 py-2 bg-gray-100 text-gray-900 rounded-md hover:bg-gray-200 disabled:opacity-50">XLSX</button>
    </div>

    <div v-if="result" class="space-y-4">
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div class="rounded border p-3">
          <p class="text-xs text-gray-500">Rows original</p>
          <p class="text-lg font-semibold text-gray-900">{{ result.summary?.rows_original || 0 }}</p>
        </div>
        <div class="rounded border p-3">
          <p class="text-xs text-gray-500">Rows after</p>
          <p class="text-lg font-semibold text-gray-900">{{ result.summary?.rows_after_operations || 0 }}</p>
        </div>
        <div class="rounded border p-3">
          <p class="text-xs text-gray-500">Operations</p>
          <p class="text-lg font-semibold text-gray-900">{{ result.summary?.operations_applied || 0 }}</p>
        </div>
        <div class="rounded border p-3">
          <p class="text-xs text-gray-500">Valid</p>
          <p class="text-lg font-semibold" :class="result.is_valid ? 'text-green-700' : 'text-red-700'">{{ result.is_valid ? 'yes' : 'no' }}</p>
        </div>
      </div>

      <div v-if="repairReport" class="rounded border p-4">
        <h3 class="text-sm font-semibold text-gray-900">Repair report</h3>
        <div class="mt-2 text-xs text-gray-700 space-y-1">
          <p>Changed cells: <span class="font-semibold">{{ repairReport.changed_cells || 0 }}</span></p>
          <p>Unresolved: <span class="font-semibold">{{ repairReport.unresolved_count || 0 }}</span></p>
        </div>
        <div v-if="(repairReport.unresolved_preview || []).length" class="mt-3 max-h-48 overflow-auto border rounded p-2 bg-gray-50 text-xs">
          <p v-for="item in repairReport.unresolved_preview" :key="`${item.row_index}-${item.value}`" class="text-gray-700">
            Row {{ item.row_index }}: {{ item.value }}
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useToast } from '@/composables/useToast'
import msfService from '@/services/msf.service'
import toolsService from '@/services/tools.service'

const { success, error: showError } = useToast()

const isEnabled = ref(false)
const msfFiles = ref([])
const selectedMsfPath = ref('')
const directoryPath = ref('')
const columnName = ref('filename')
const matchByStem = ref(true)
const keepUnresolved = ref(true)
const running = ref(false)
const downloading = ref(false)
const result = ref(null)

const canRun = computed(() => isEnabled.value && !!selectedMsfPath.value)
const repairReport = computed(() => {
  const operations = result.value?.operations || []
  return operations.find((item) => item.type === 'repair_references') || null
})

const buildPayload = () => ({
  msf_path: selectedMsfPath.value,
  directory_path: directoryPath.value.trim(),
  recursive: true,
  include_reference_check: true,
  duplicate_scan_columns: [columnName.value || 'filename'],
  operations: [
    {
      type: 'repair_references',
      column: columnName.value.trim() || undefined,
      match_by_stem: matchByStem.value,
      keep_unresolved: keepUnresolved.value
    }
  ]
})

const loadContext = async () => {
  try {
    const [toolsContext, localContext] = await Promise.all([
      toolsService.getContext(),
      msfService.getLocalValidatorContext()
    ])
    isEnabled.value = !!toolsContext.data?.features?.msf_reference_repair?.enabled
    msfFiles.value = localContext.data?.msf_files || []
  } catch (e) {
    isEnabled.value = false
    msfFiles.value = []
  }
}

const runRepair = async () => {
  if (!canRun.value) return
  running.value = true
  try {
    const response = await msfService.validateLocalMsf(buildPayload())
    result.value = response.data || null
    success('Reference repair completed.')
  } catch (e) {
    showError(e?.message || 'Reference repair failed.')
  } finally {
    running.value = false
  }
}

const download = async (format) => {
  if (!result.value) return
  downloading.value = true
  try {
    const { blob, filename } = await msfService.exportLocalMsf({
      ...buildPayload(),
      format,
      allow_export_with_blockers: true
    })
    const link = document.createElement('a')
    const objectUrl = URL.createObjectURL(blob)
    link.href = objectUrl
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(objectUrl)
    success(`Downloaded ${filename}`)
  } catch (e) {
    showError(e?.message || 'Download failed.')
  } finally {
    downloading.value = false
  }
}

onMounted(loadContext)
</script>
