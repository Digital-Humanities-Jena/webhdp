<template>
  <div class="bg-white rounded-lg shadow p-6 space-y-5">
    <div class="flex items-start justify-between">
      <div>
        <h2 class="text-xl font-semibold text-gray-900">Metadata Normalizer</h2>
        <p class="mt-1 text-sm text-gray-600">Normalize casing, whitespace, and delimited duplicates in selected MSF columns.</p>
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
        <label class="block text-sm font-medium text-gray-700 mb-2">Columns (comma-separated)</label>
        <input v-model="columnsText" :disabled="!isEnabled" type="text" placeholder="title,creator,keywords" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm disabled:bg-gray-100" />
      </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-2">Case mode</label>
        <select v-model="mode" :disabled="!isEnabled" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm disabled:bg-gray-100">
          <option value="none">None</option>
          <option value="lower">lowercase</option>
          <option value="upper">UPPERCASE</option>
          <option value="title">Title Case</option>
          <option value="sentence">Sentence case</option>
        </select>
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-2">Delimiter for dedupe</label>
        <input v-model="delimiter" :disabled="!isEnabled" type="text" placeholder=";" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm disabled:bg-gray-100" />
      </div>
      <div class="space-y-2 pt-6">
        <label class="inline-flex items-center space-x-2 text-sm text-gray-700">
          <input v-model="collapseWhitespace" :disabled="!isEnabled" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
          <span>Collapse whitespace</span>
        </label>
        <label class="inline-flex items-center space-x-2 text-sm text-gray-700">
          <input v-model="dedupeDelimited" :disabled="!isEnabled" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
          <span>Deduplicate delimiter-separated values</span>
        </label>
      </div>
    </div>

    <div class="flex justify-end space-x-2">
      <button @click="run" :disabled="!canRun || running" class="px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50">
        {{ running ? 'Running…' : 'Run Normalizer' }}
      </button>
      <button @click="download('csv')" :disabled="!result || downloading" class="px-4 py-2 bg-gray-100 text-gray-900 rounded-md hover:bg-gray-200 disabled:opacity-50">CSV</button>
      <button @click="download('xlsx')" :disabled="!result || downloading" class="px-4 py-2 bg-gray-100 text-gray-900 rounded-md hover:bg-gray-200 disabled:opacity-50">XLSX</button>
    </div>

    <div v-if="result" class="space-y-3">
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div class="rounded border p-3"><p class="text-xs text-gray-500">Rows original</p><p class="text-lg font-semibold text-gray-900">{{ result.summary?.rows_original || 0 }}</p></div>
        <div class="rounded border p-3"><p class="text-xs text-gray-500">Rows after</p><p class="text-lg font-semibold text-gray-900">{{ result.summary?.rows_after_operations || 0 }}</p></div>
        <div class="rounded border p-3"><p class="text-xs text-gray-500">Operations</p><p class="text-lg font-semibold text-gray-900">{{ result.summary?.operations_applied || 0 }}</p></div>
        <div class="rounded border p-3"><p class="text-xs text-gray-500">Warnings</p><p class="text-lg font-semibold text-gray-900">{{ result.warnings?.length || 0 }}</p></div>
      </div>

      <div v-if="normalizeReport" class="rounded border p-4 text-xs text-gray-700">
        <p>Changed cells: <span class="font-semibold">{{ normalizeReport.changed_cells || 0 }}</span></p>
        <p>Deduped cells: <span class="font-semibold">{{ normalizeReport.deduped_cells || 0 }}</span></p>
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
const columnsText = ref('title,creator,keywords')
const mode = ref('title')
const delimiter = ref(';')
const collapseWhitespace = ref(true)
const dedupeDelimited = ref(true)

const running = ref(false)
const downloading = ref(false)
const result = ref(null)

const canRun = computed(() => isEnabled.value && !!selectedMsfPath.value && columns.value.length > 0)
const columns = computed(() => columnsText.value.split(',').map((item) => item.trim()).filter(Boolean))
const normalizeReport = computed(() => {
  const operations = result.value?.operations || []
  return operations.find((item) => item.type === 'normalize_text_columns') || null
})

const loadContext = async () => {
  try {
    const [toolsContext, localContext] = await Promise.all([
      toolsService.getContext(),
      msfService.getLocalValidatorContext()
    ])
    isEnabled.value = !!toolsContext.data?.features?.metadata_normalizer?.enabled
    msfFiles.value = localContext.data?.msf_files || []
  } catch (e) {
    isEnabled.value = false
    msfFiles.value = []
  }
}

const buildNormalizerPayload = () => ({
  msf_path: selectedMsfPath.value,
  directory_path: '',
  columns: columns.value,
  mode: mode.value,
  collapse_whitespace: collapseWhitespace.value,
  dedupe_delimited: dedupeDelimited.value,
  delimiter: delimiter.value,
  auto_space: true,
  include_reference_check: false
})

const buildExportPayload = () => ({
  msf_path: selectedMsfPath.value,
  directory_path: '',
  include_reference_check: false,
  recursive: true,
  duplicate_scan_columns: columns.value,
  operations: [
    {
      type: 'normalize_text_columns',
      columns: columns.value,
      mode: mode.value,
      collapse_whitespace: collapseWhitespace.value,
      dedupe_delimited: dedupeDelimited.value,
      delimiter: delimiter.value,
      auto_space: true
    }
  ]
})

const run = async () => {
  if (!canRun.value) return
  running.value = true
  try {
    const response = await toolsService.runMetadataNormalizerLocal(buildNormalizerPayload())
    result.value = response.data || null
    success('Metadata normalization completed.')
  } catch (e) {
    showError(e?.message || 'Metadata normalizer failed.')
  } finally {
    running.value = false
  }
}

const download = async (format) => {
  if (!result.value) return
  downloading.value = true
  try {
    const { blob, filename } = await msfService.exportLocalMsf({
      ...buildExportPayload(),
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
