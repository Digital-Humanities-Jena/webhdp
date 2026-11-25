<template>
  <div class="bg-white rounded-lg shadow p-6 space-y-5">
    <div class="flex items-start justify-between">
      <div>
        <h2 class="text-xl font-semibold text-gray-900">Output Preview QA</h2>
        <p class="mt-1 text-sm text-gray-600">Generate EDM, IIIF, and METS previews from a selected MSF row before running the pipeline.</p>
      </div>
      <span class="px-3 py-1 text-xs font-semibold rounded-full" :class="isEnabled ? 'bg-green-100 text-green-800' : 'bg-amber-100 text-amber-800'">
        {{ isEnabled ? 'Enabled' : 'Disabled' }}
      </span>
    </div>

    <div v-if="!isEnabled" class="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
      Requires Admin role and local storage mode.
    </div>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
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
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-2">Row index</label>
        <input v-model.number="rowIndex" :disabled="!isEnabled" type="number" min="0" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm disabled:bg-gray-100" />
      </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-2">Mapping Config (JSON object, optional)</label>
        <textarea v-model="mappingConfig" :disabled="!isEnabled" rows="8" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 text-xs disabled:bg-gray-100"></textarea>
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-2">Zenodo Record (JSON object, optional)</label>
        <textarea v-model="zenodoRecord" :disabled="!isEnabled" rows="8" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 text-xs disabled:bg-gray-100"></textarea>
      </div>
    </div>

    <div class="flex items-center justify-between">
      <div class="space-x-4 text-sm text-gray-700">
        <label class="inline-flex items-center space-x-2"><input v-model="targets.edm" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" /><span>EDM</span></label>
        <label class="inline-flex items-center space-x-2"><input v-model="targets.iiif" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" /><span>{{ IIIF_PRESENTATION_LABEL }}</span></label>
        <label class="inline-flex items-center space-x-2"><input v-model="targets.mets" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" /><span>METS</span></label>
      </div>
      <button @click="run" :disabled="!canRun || running" class="px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50">
        {{ running ? 'Generating…' : 'Generate Preview' }}
      </button>
    </div>

    <div v-if="result" class="space-y-4">
      <div class="rounded border p-4 text-xs text-gray-700">
        <p>Row index used: <span class="font-semibold">{{ result.row_index_used }}</span></p>
        <p>Main file key: <span class="font-semibold">{{ result.main_file_key || 'n/a' }}</span></p>
      </div>

      <div v-for="target in previewTargets" :key="target" class="rounded border p-4">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-semibold text-gray-900 uppercase">{{ target }}</h3>
          <span
            class="text-xs font-semibold"
            :class="badgeClass(result.outputs[target])"
          >
            {{ badgeLabel(result.outputs[target], target) }}
          </span>
        </div>
        <p v-if="!result.outputs[target].ok" class="mt-2 text-xs text-red-700">{{ result.outputs[target].error }}</p>
        <div v-else class="mt-2 space-y-3">
          <div class="flex flex-wrap gap-2 text-[11px]">
            <span class="rounded-full bg-slate-100 px-2 py-1 text-slate-700">
              {{ validationScopeLabel(result.outputs[target]) }}
            </span>
            <span
              class="rounded-full px-2 py-1"
              :class="result.outputs[target].minimum_viable_applied ? 'bg-amber-100 text-amber-800' : 'bg-emerald-100 text-emerald-800'"
            >
              {{ result.outputs[target].minimum_viable_applied ? 'Minimum viable applied' : 'Template output unchanged' }}
            </span>
          </div>

          <div class="grid grid-cols-3 gap-2 text-[11px]">
            <div class="rounded border bg-gray-50 p-2 text-gray-700">
              <div class="font-semibold text-gray-900">Errors</div>
              <div>{{ validationSummary(result.outputs[target]).errorCount }}</div>
            </div>
            <div class="rounded border bg-gray-50 p-2 text-gray-700">
              <div class="font-semibold text-gray-900">Warnings</div>
              <div>{{ validationSummary(result.outputs[target]).warningCount }}</div>
            </div>
            <div class="rounded border bg-gray-50 p-2 text-gray-700">
              <div class="font-semibold text-gray-900">Checks</div>
              <div>{{ validationSections(result.outputs[target]).length }}</div>
            </div>
          </div>

          <div v-if="validationSections(result.outputs[target]).length" class="space-y-2">
            <div
              v-for="section in validationSections(result.outputs[target])"
              :key="section.id"
              class="rounded border bg-white p-3"
            >
              <div class="flex items-center justify-between gap-4">
                <h4 class="text-xs font-semibold text-gray-900">{{ section.label }}</h4>
                <span class="text-[11px] font-semibold" :class="sectionStatusClass(section)">
                  {{ sectionStatusLabel(section) }}
                </span>
              </div>
              <p v-if="section.message" class="mt-2 text-[11px] text-gray-600">{{ section.message }}</p>
              <ul v-if="section.errors?.length" class="mt-2 space-y-1 text-[11px] text-red-700">
                <li v-for="(item, index) in section.errors" :key="`${section.id}-error-${index}`">{{ item }}</li>
              </ul>
              <ul v-if="section.warnings?.length" class="mt-2 space-y-1 text-[11px] text-amber-700">
                <li v-for="(item, index) in section.warnings" :key="`${section.id}-warning-${index}`">{{ item }}</li>
              </ul>
            </div>
          </div>

          <IiifManifestPreview v-if="target === 'iiif'" :content="result.outputs[target].content" />
          <details class="rounded border bg-gray-50">
            <summary class="cursor-pointer px-3 py-2 text-[11px] font-semibold text-gray-700">Rendered Output</summary>
            <pre class="max-h-72 overflow-auto border-t p-2 text-[11px] text-gray-700">{{ (target === 'iiif' && result.outputs[target].content) || result.outputs[target].preview?.text || '' }}</pre>
          </details>

          <details class="rounded border bg-white">
            <summary class="cursor-pointer px-3 py-2 text-[11px] font-semibold text-gray-700">Raw Validation JSON</summary>
            <pre class="max-h-40 overflow-auto border-t p-2 text-[11px] text-gray-700">{{ JSON.stringify(result.outputs[target].validation || {}, null, 2) }}</pre>
          </details>
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
import IiifManifestPreview from '@/components/workflow/IiifManifestPreview.vue'
import { IIIF_PRESENTATION_LABEL } from '@/utils/iiifPresentation'

const { success, error: showError } = useToast()

const isEnabled = ref(false)
const msfFiles = ref([])
const selectedMsfPath = ref('')
const directoryPath = ref('')
const rowIndex = ref(0)

const mappingConfig = ref('{}')
const zenodoRecord = ref('{}')
const targets = ref({ edm: true, iiif: true, mets: true })

const running = ref(false)
const result = ref(null)
const previewTargets = computed(() => Object.keys(targets.value).filter(target => result.value?.outputs?.[target]))

const canRun = computed(() => {
  const selectedTargets = Object.values(targets.value).filter(Boolean).length
  return isEnabled.value && !!selectedMsfPath.value && selectedTargets > 0
})

const badgeLabel = (output, target) => {
  if (!output?.ok) return 'error'
  if (output?.validation?.valid === false) return 'invalid'
  if (output?.validation?.valid === true) return target === 'iiif' ? 'checks passed' : 'valid'
  return 'ok'
}

const badgeClass = (output) => {
  if (!output?.ok) return 'text-red-700'
  if (output?.validation?.valid === false) return 'text-amber-700'
  return 'text-green-700'
}

const validationSummary = (output) => {
  const summary = output?.validation?.summary || {}
  return {
    errorCount: Number(summary.error_count || 0),
    warningCount: Number(summary.warning_count || 0)
  }
}

const validationSections = (output) => {
  return Array.isArray(output?.validation?.sections) ? output.validation.sections : []
}

const sectionStatusLabel = (section) => {
  if (section?.skipped) return 'skipped'
  if (section?.valid === false) return 'issues'
  return 'ok'
}

const sectionStatusClass = (section) => {
  if (section?.skipped) return 'text-slate-600'
  if (section?.valid === false) return 'text-red-700'
  return 'text-green-700'
}

const validationScopeLabel = (output) => {
  const scope = output?.validation?.summary?.validation_scope
  return scope === 'local+remote' ? 'Local + remote validation' : 'Local validation'
}

const loadContext = async () => {
  try {
    const [toolsContext, localContext] = await Promise.all([
      toolsService.getContext(),
      msfService.getLocalValidatorContext()
    ])
    isEnabled.value = !!toolsContext.data?.features?.output_preview_qa?.enabled
    msfFiles.value = localContext.data?.msf_files || []
  } catch (e) {
    isEnabled.value = false
    msfFiles.value = []
  }
}

const run = async () => {
  if (!canRun.value) return
  running.value = true
  try {
    const selectedTargets = Object.entries(targets.value)
      .filter(([, enabled]) => enabled)
      .map(([name]) => name)

    const response = await toolsService.runOutputPreviewLocal({
      msf_path: selectedMsfPath.value,
      directory_path: directoryPath.value.trim(),
      row_index: rowIndex.value,
      mapping_config: mappingConfig.value,
      zenodo_record: zenodoRecord.value,
      targets: selectedTargets
    })
    result.value = response.data || null
    success('Output preview generated.')
  } catch (e) {
    showError(e?.message || 'Output preview failed.')
  } finally {
    running.value = false
  }
}

onMounted(loadContext)
</script>
