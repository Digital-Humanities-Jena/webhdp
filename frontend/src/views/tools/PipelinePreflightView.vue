<template>
  <div class="bg-white rounded-lg shadow p-6 space-y-5">
    <div>
      <h2 class="text-xl font-semibold text-gray-900">Pipeline Preflight</h2>
      <p v-if="isEnabled" class="mt-1 text-sm text-gray-600">Check an MSF file, its source directory, and runtime services before execution.</p>
    </div>

    <div v-if="contextError" class="text-sm text-gray-700">
      <p role="alert">Could not load Pipeline Preflight availability.</p>
      <button type="button" class="mt-3 text-indigo-700 underline" @click="loadContext">Try again</button>
    </div>
    <p v-else-if="!context" role="status" class="text-sm text-gray-600">Loading preflight options…</p>
    <section v-else-if="!isEnabled" class="space-y-3 text-sm text-gray-700" aria-labelledby="readiness-guidance">
      <p v-if="context.storage_mode === 'local'">{{ context.features?.pipeline_preflight?.reason || 'Local preflight is unavailable.' }}</p>
      <p v-else>Standalone Pipeline Preflight checks an MSF and directory in local storage mode.</p>
      <h3 id="readiness-guidance" class="text-base font-semibold text-gray-900">Submission readiness</h3>
      <p>Open Uploads and resume your workflow. On the Submit step, use <strong>Check again</strong> under <strong>Submission readiness</strong> to check the selected files and saved settings before processing.</p>
      <router-link to="/uploads" class="inline-flex rounded-md bg-indigo-600 px-4 py-2 font-medium text-white hover:bg-indigo-700">Open Uploads</router-link>
    </section>

    <template v-else>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-2">MSF File</label>
        <select v-model="selectedMsfPath" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm">
          <option value="" disabled>-- Select an MSF file --</option>
          <option v-for="file in msfFiles" :key="file.full_path" :value="file.full_path">{{ file.path }}</option>
        </select>
      </div>
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-2">Subdirectory (optional)</label>
        <input v-model="directoryPath" type="text" placeholder="rcin" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
      </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-2">Duplicate columns (comma-separated)</label>
        <input v-model="duplicateColumnsText" type="text" placeholder="filename,title" class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
      </div>
      <label class="inline-flex items-center mt-7 space-x-2 text-sm text-gray-700">
        <input v-model="recursiveScan" type="checkbox" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
        <span>Recursive scan</span>
      </label>
      <div class="flex items-end justify-end">
        <button @click="runPreflight" :disabled="!canRun || running" class="px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50">
          {{ running ? 'Running…' : 'Run Preflight' }}
        </button>
      </div>
    </div>

    <div v-if="result" class="space-y-4">
      <div class="grid grid-cols-1 md:grid-cols-4 gap-3">
        <div class="rounded border p-3">
          <p class="text-xs text-gray-500">Status</p>
          <p class="text-lg font-semibold" :class="result.readiness?.can_run ? 'text-green-700' : 'text-red-700'">
            {{ result.readiness?.status || 'unknown' }}
          </p>
        </div>
        <div class="rounded border p-3">
          <p class="text-xs text-gray-500">Blockers</p>
          <p class="text-lg font-semibold text-gray-900">{{ result.readiness?.blockers?.length || 0 }}</p>
        </div>
        <div class="rounded border p-3">
          <p class="text-xs text-gray-500">Warnings</p>
          <p class="text-lg font-semibold text-gray-900">{{ result.validator?.warnings?.length || 0 }}</p>
        </div>
        <div class="rounded border p-3">
          <p class="text-xs text-gray-500">Scan files</p>
          <p class="text-lg font-semibold text-gray-900">{{ result.validator?.scan_file_count || 0 }}</p>
        </div>
      </div>

      <div v-if="(result.readiness?.blockers || []).length" class="rounded-md border border-red-200 bg-red-50 p-4">
        <p class="text-sm font-semibold text-red-700">Readiness blockers</p>
        <ul class="mt-2 list-disc pl-5 text-xs text-red-700 space-y-1">
          <li v-for="msg in result.readiness.blockers" :key="msg">{{ msg }}</li>
        </ul>
      </div>

      <div class="rounded border p-4">
        <h3 class="text-sm font-semibold text-gray-900 mb-2">Service health</h3>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
          <div v-for="(service, key) in result.services || {}" :key="key" class="rounded border p-2">
            <p class="font-semibold" :class="service.ok ? 'text-green-700' : 'text-red-700'">{{ key }}: {{ service.ok ? 'ok' : 'failed' }}</p>
            <p class="text-gray-600 break-all">{{ service.url || service.message || '' }}</p>
          </div>
        </div>
      </div>
    </div>
    </template>
  </div>
</template>

<script setup>
import { computed, inject, ref } from 'vue'
import { useToast } from '@/composables/useToast'
import toolsService from '@/services/tools.service'

const { success, error: showError } = useToast()

const { context, contextError, loadContext } = inject('tools-context')
const isEnabled = computed(() => !!context.value?.features?.pipeline_preflight?.enabled)
const msfFiles = computed(() => context.value?.msf_files || [])
const running = ref(false)

const selectedMsfPath = ref('')
const directoryPath = ref('')
const duplicateColumnsText = ref('filename,title')
const recursiveScan = ref(true)

const result = ref(null)

const canRun = computed(() => isEnabled.value && !!selectedMsfPath.value)

const runPreflight = async () => {
  if (!canRun.value) return
  running.value = true
  try {
    const duplicateColumns = duplicateColumnsText.value
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)

    const response = await toolsService.runPipelinePreflightLocal({
      msf_path: selectedMsfPath.value,
      directory_path: directoryPath.value.trim(),
      recursive: recursiveScan.value,
      duplicate_scan_columns: duplicateColumns
    })
    result.value = response.data || null
    success('Preflight completed.')
  } catch (e) {
    showError(e?.message || 'Preflight failed.')
  } finally {
    running.value = false
  }
}

</script>
