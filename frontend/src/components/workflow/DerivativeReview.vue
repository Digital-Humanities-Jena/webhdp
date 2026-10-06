<template>
  <details v-if="sets.length || error" class="rounded-xl border border-slate-200 bg-white p-5" aria-label="Geometric detail review">
    <summary class="cursor-pointer font-semibold text-slate-900">Compare source and geometric detail levels</summary>
    <p class="mt-2 text-sm text-slate-600">Check silhouette, thin features, textures and material boundaries before using a derivative. Lower triangle counts can still produce a larger file. The source shown here is the input supplied to this processing step.</p>
    <p v-if="error" role="alert" class="mt-2 text-sm text-rose-800">{{ error }}</p>
    <button v-if="error" type="button" class="min-h-11 text-sm text-indigo-700 underline" @click="loadSets">Refresh detail reports</button>
    <template v-if="selectedSet">
      <label v-if="sets.length > 1" class="mt-3 block text-sm">Processing run
        <select v-model="selectedSetId" class="ml-2 rounded border-slate-300"><option v-for="set in sets" :key="set.step_run_id" :value="set.step_run_id">{{ set.created_at || set.run_id }}</option></select>
      </label>
      <p v-if="selectedSet.error" class="mt-2 text-sm text-rose-800">{{ selectedSet.error }}</p>
      <template v-else>
        <div class="mt-3 overflow-x-auto"><table class="w-full text-left text-sm"><thead><tr><th class="py-2">Level</th><th>Triangles</th><th>Size</th><th>Retained meshes</th></tr></thead><tbody>
          <tr v-for="model in selectedSet.models" :key="model.level"><td class="py-2">{{ model.label }}</td><td>{{ model.triangles.toLocaleString() }}</td><td>{{ formatBytes(model.bytes) }}<span v-if="model.level !== 'source'" class="text-xs text-slate-500"> ({{ model.size_change_percent > 0 ? '+' : '' }}{{ model.size_change_percent.toFixed(1) }}%)</span></td><td>{{ model.retained_meshes ?? '—' }}</td></tr>
        </tbody></table></div>
        <div class="mt-3 flex flex-wrap items-center gap-3">
          <label class="text-sm">Detail level <select v-model="selectedLevel" class="ml-2 rounded border-slate-300"><option v-for="model in selectedSet.models" :key="model.level" :value="model.level">{{ model.label }}</option></select></label>
          <button type="button" :disabled="busy" class="min-h-11 text-sm font-semibold text-indigo-700 underline disabled:opacity-50" @click="loadModels">{{ busy ? 'Verifying and loading…' : 'Load comparison' }}</button>
          <button v-if="modelUrl" type="button" class="min-h-11 text-sm text-indigo-700 underline" @click="downloadModel">Download selected model</button>
        </div>
        <p v-if="modelUrl" class="mt-2 text-xs text-emerald-800">The loaded files match their recorded SHA-256 checksums.</p>
        <div v-if="modelUrl" class="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
          <div v-if="sourceUrl"><p class="mb-1 text-xs font-medium">Source supplied to this step</p><PlaygroundModelViewer :src="sourceUrl" alt="Source model for comparison" /></div>
          <div><p class="mb-1 text-xs font-medium">{{ selectedLevel }} detail</p><PlaygroundModelViewer :src="modelUrl" :alt="`${selectedLevel} detail model`" /></div>
        </div>
        <details class="mt-3 text-xs text-slate-600"><summary class="cursor-pointer">Geometry checks and limits</summary>
          <p class="mt-2">{{ selectedSet.quality_note }} Appearance requires visual review. Retained meshes met the accepted geometry limit or could not be reduced further.</p>
          <p v-if="selectedModel?.repaired_tangents" class="mt-2">{{ selectedModel.repaired_tangents }} exported tangent{{ selectedModel.repaired_tangents === 1 ? ' was' : 's were' }} normalized or repaired. Inspect normal-mapped surfaces in the comparison.</p>
          <ul class="mt-2 space-y-1"><li v-for="(check, index) in selectedModel?.geometry_checks || []" :key="index">{{ check.mesh }}: {{ check.status }} · {{ check.reason }} Sampled error {{ check.sampled_error }}; limit {{ check.error_limit }}.</li></ul>
        </details>
      </template>
    </template>
  </details>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { apiV2 } from '@/services/api'
import PlaygroundModelViewer from '@/components/tools/playground/PlaygroundModelViewer.vue'

const props = defineProps({ sessionId: { type: [Number, String], required: true }, recordId: { type: [Number, String], required: true } })
const sets = ref([])
const selectedSetId = ref(null)
const selectedLevel = ref('medium')
const selectedSet = computed(() => sets.value.find(set => set.step_run_id === selectedSetId.value))
const selectedModel = computed(() => selectedSet.value?.models.find(model => model.level === selectedLevel.value))
const error = ref('')
const busy = ref(false)
const modelUrl = ref('')
const sourceUrl = ref('')
let generation = 0
let controller
const base = () => `/sessions/${props.sessionId}/records/${props.recordId}/derivatives`
const formatBytes = value => value >= 1048576 ? `${(value / 1048576).toFixed(2)} MiB` : `${(value / 1024).toFixed(1)} KiB`

function clearModels() {
  generation++
  controller?.abort()
  for (const url of [modelUrl.value, sourceUrl.value]) if (url) URL.revokeObjectURL(url)
  modelUrl.value = sourceUrl.value = ''
  busy.value = false
}

async function loadSets() {
  clearModels()
  const current = generation
  error.value = ''
  try {
    const response = await apiV2.get(base(), { suppressGlobalError: true })
    if (current !== generation) return
    sets.value = response.data?.sets || []
    selectedSetId.value = sets.value[0]?.step_run_id ?? null
  } catch (err) { if (current === generation) error.value = err?.error?.message || err?.message || 'Detail reports could not be loaded.' }
}

async function loadModels() {
  clearModels()
  const current = generation
  controller = new AbortController()
  busy.value = true
  error.value = ''
  try {
    if (!globalThis.crypto?.subtle) throw new Error('Open WebHDP over HTTPS or localhost to verify and compare these files.')
    const levels = selectedLevel.value === 'source' ? ['source'] : [selectedLevel.value, 'source']
    const blobs = await Promise.all(levels.map(level => apiV2.get(`${base()}/${selectedSetId.value}/${level}`, { responseType: 'blob', signal: controller.signal, timeout: 600000, suppressGlobalError: true })))
    await Promise.all(blobs.map(async (blob, index) => {
      const digest = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer())
      const checksum = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
      const expected = selectedSet.value.models.find(model => model.level === levels[index])
      if (checksum !== expected.sha256 || blob.size !== expected.bytes) throw new Error('A transferred model does not match the report. Refresh the detail set before reviewing it.')
    }))
    if (current !== generation) return
    modelUrl.value = URL.createObjectURL(blobs[0])
    if (blobs[1]) sourceUrl.value = URL.createObjectURL(blobs[1])
  } catch (err) {
    if (current === generation) error.value = err?.error?.message || err?.message || 'The comparison could not be verified. Refresh the report or generate detail levels again.'
  } finally { if (current === generation) busy.value = false }
}

function downloadModel() {
  const link = document.createElement('a')
  link.href = modelUrl.value
  link.download = selectedModel.value.filename
  link.click()
}

watch([selectedSetId, selectedLevel], clearModels)
watch(() => [props.sessionId, props.recordId], loadSets)
onMounted(loadSets)
onBeforeUnmount(clearModels)
</script>
