<!-- src/components/workflow/LodMapper.vue -->
<template>
  <div class="lod-mapper-container glass-morphism rounded-2xl overflow-hidden shadow-2xl border border-white/20 flex flex-col min-h-[600px]">
    <!-- Header -->
    <div class="bg-gradient-to-r from-sky-700/95 via-cyan-700/95 to-teal-700/95 p-4 flex flex-wrap gap-4 items-center justify-between text-white">
      <div class="flex items-center gap-3">
        <div class="p-2 bg-white/20 rounded-lg backdrop-blur-md">
          <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
          </svg>
        </div>
        <div>
          <h2 class="text-xl font-bold tracking-tight">LOD-Mapper</h2>
          <p class="text-xs text-cyan-100 opacity-90">Map MSF & Zenodo metadata to Linked Open Data standards</p>
        </div>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <input
          type="file"
          ref="fileInput"
          class="hidden"
          accept=".yaml,.yml,.json"
          @change="importMapping"
        />

        <button
          @click="triggerImport"
          :disabled="importing"
          class="flex items-center gap-2 px-3 py-2 bg-cyan-500/20 hover:bg-cyan-500/35 rounded-lg transition-all text-xs font-semibold border border-cyan-300/40 text-cyan-50 disabled:opacity-50"
        >
          <svg v-if="importing" class="animate-spin h-3 w-3" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
          <svg v-else class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
          </svg>
          Import
        </button>

        <button
          @click="exportMapping"
          :disabled="exporting"
          class="flex items-center gap-2 px-3 py-2 bg-cyan-500/20 hover:bg-cyan-500/35 rounded-lg transition-all text-xs font-semibold border border-cyan-300/40 text-cyan-50 disabled:opacity-50"
        >
           <svg v-if="exporting" class="animate-spin h-3 w-3" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
          <svg v-else class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
          </svg>
          Export
        </button>

        <div class="w-px h-6 bg-white/20 mx-1"></div>

        <div class="flex min-w-0 flex-wrap items-center gap-2">
          <label for="lod-sample-row" class="text-sm text-cyan-100">Preview record</label>
          <select id="lod-sample-row" v-model.number="selectedRowIndex" class="max-w-full min-h-[44px] rounded border border-white/30 bg-white px-2 py-2 text-sm text-slate-800">
            <option v-for="sample in sampleRecords" :key="sample.row_index" :value="sample.row_index">{{ sample.label }}</option>
            <option v-if="!sampleRecords.length" :value="suggestedRowIndex">Suggested record {{ suggestedRowIndex + 1 }}</option>
          </select>
        </div>

        <button
          @click="testMapping"
          :disabled="testing"
          class="flex items-center gap-2 px-4 py-2 bg-white/20 hover:bg-white/30 rounded-full transition-all text-sm font-semibold backdrop-blur-md border border-white/10 disabled:opacity-50"
        >
          <svg v-if="testing" class="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          <svg v-else class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          Test Mapping
        </button>
      </div>
    </div>

    <div class="flex flex-col sm:flex-row flex-1 overflow-hidden bg-white/5 backdrop-blur-sm">
      <!-- Sidebar: LOD Standards -->
      <div class="w-full sm:w-20 shrink-0 bg-black/5 border-r border-white/10 flex flex-row sm:flex-col items-center overflow-x-auto px-2 py-2 sm:py-6 gap-2 sm:gap-6">
        <button
          type="button"
          :aria-pressed="activeStandard === std.id"
          v-for="std in lodStandards"
          :key="std.id"
          class="group relative shrink-0 min-w-[60px] flex flex-col items-center gap-1 cursor-pointer"
          @click="activeStandard = std.id"
        >
          <div :class="['p-3 rounded-2xl transition-all duration-300', activeStandard === std.id ? 'bg-cyan-700 text-white shadow-lg shadow-cyan-500/40 scale-110' : 'bg-white/70 text-slate-700 hover:bg-white opacity-80 hover:opacity-100']">
             <component :is="std.icon" class="h-6 w-6" />
          </div>
          <span :class="['text-[10px] font-bold tracking-tight uppercase px-1.5 py-0.5 rounded', activeStandard === std.id ? 'text-slate-900 bg-white/80' : 'text-slate-700 bg-white/65']">{{ std.name }}</span>
          <!-- Status Indicator -->
        </button>
      </div>

      <!-- Main Content -->
      <div class="min-w-0 flex-1 flex flex-col overflow-hidden">
        <!-- Modality Tabs -->
        <div class="flex overflow-x-auto border-b border-white/10 bg-black/5 px-2 sm:px-6">
          <button
            v-for="mod in modalities"
            :key="mod.id"
            :aria-pressed="activeModality === mod.id"
            @click="activeModality = mod.id"
            :class="['px-3 sm:px-5 py-3 text-xs font-bold uppercase tracking-widest transition-all relative', activeModality === mod.id ? 'text-cyan-700' : 'text-gray-500 hover:text-gray-700']"
          >
            {{ mod.name }}
            <div v-if="activeModality === mod.id" class="absolute bottom-0 left-0 right-0 h-0.5 bg-cyan-700 rounded-full transition-all"></div>
          </button>
        </div>

        <!-- Scrollable Mapping Area -->
        <div class="flex-1 overflow-y-auto p-3 sm:p-6">
          <div v-if="loadingColumns" class="flex flex-col items-center justify-center h-full opacity-50">
             <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-cyan-700 mb-2"></div>
             <p class="text-xs font-medium uppercase tracking-widest">Loading Fields...</p>
          </div>

          <div v-else-if="columnsError" role="alert" class="p-4 text-sm text-rose-800">{{ columnsError }} <button type="button" class="underline" @click="fetchColumns">Retry loading fields</button></div>
          <div v-else class="space-y-4">
            <div v-if="activeStandard === 'iiif'" class="text-sm text-slate-700">
              <p class="font-medium">{{ IIIF_PRESENTATION_LABEL }}</p>
              <p v-if="activeModality === '3d'" class="mt-1 text-xs">Scene placement uses local X, Y and Z coordinates.</p>
              <p v-if="activeModality === 'sound'" class="mt-1 text-xs">Supply a duration to play audio on a Timeline. Audio without a duration is offered as a download.</p>
            </div>
            <div
              v-if="activeStandard === 'zenodo' && communityOverride.enabled"
              class="p-3 rounded-lg border border-amber-200 bg-amber-50 text-amber-800 text-xs"
            >
              Zenodo community is hardcoded by admin to <strong>{{ communityOverride.community }}</strong>.
              Community mapping is overridden while this setting is enabled.
            </div>
            <div v-for="tag in currentTags" :key="tag.id" class="mapping-row group flex flex-col lg:flex-row items-stretch lg:items-center gap-3 p-4 rounded-xl border border-white/40 bg-white/50 hover:bg-white/80 hover:shadow-md transition-all">
              <!-- Target Tag -->
              <div class="min-w-0 lg:w-1/3">
                <div class="flex items-center gap-2 mb-1">
                  <label :for="controlId(tag, 'value')" class="text-sm font-semibold text-slate-800">{{ tag.name }}</label>
                  <span v-if="tag.required" class="text-red-500 text-[10px] font-bold">*</span>
                </div>
                <p class="text-xs text-gray-500 leading-relaxed">{{ tag.description }}</p>
              </div>

              <!-- Connector -->
              <div class="hidden lg:block flex-shrink-0 text-gray-300">
                <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 8l4 4m0 0l-4 4m4-4H3" />
                </svg>
              </div>

              <!-- Source Selector -->
              <div class="min-w-0 flex-1 flex flex-col sm:flex-row gap-2">
                <label :for="controlId(tag, 'source')" class="sr-only">{{ tag.name }} source · {{ activeStandardLabel }} {{ activeModality }}</label>
                <select
                  :id="controlId(tag, 'source')"
                  v-model="mapping[activeStandard][activeModality][tag.id].source"
                  :disabled="isCommunityOverrideLocked(tag.id)"
                  class="w-full sm:w-40 shrink-0 min-h-[44px] bg-white border border-gray-200 rounded-lg px-2 py-2 text-sm font-medium focus:ring-2 focus:ring-cyan-600 focus:border-cyan-600 transition-all outline-none"
                >
                  <option value="msf">MSF Column</option>
                  <option value="zenodo">Zenodo Metadata</option>
                  <option value="static">Static Value</option>
                  <option v-if="tag.options" value="options">Select Option</option>
                  <option value="skip">Skip / Default</option>
                </select>

                <div class="min-w-0 flex-1 relative">
                  <div
                    v-if="isCommunityOverrideLocked(tag.id)"
                    class="h-full min-h-[34px] flex items-center px-3 rounded-lg border border-amber-200 bg-amber-50 text-xs text-amber-800"
                  >
                    Forced community: {{ communityOverride.community }}
                  </div>
                  <!-- MSF Dropdown -->
                  <select
                    v-else-if="mapping[activeStandard][activeModality][tag.id].source === 'msf'"
                    :id="controlId(tag, 'value')"
                    v-model="mapping[activeStandard][activeModality][tag.id].field"
                    class="w-full min-w-0 min-h-[44px] bg-white border border-gray-200 rounded-lg px-3 py-2 text-sm font-medium focus:ring-2 focus:ring-cyan-600 outline-none"
                  >
                    <option v-for="col in msfColumns" :key="col" :value="col">{{ col }}</option>
                  </select>

                  <!-- Zenodo Dropdown -->
                  <select
                    v-else-if="mapping[activeStandard][activeModality][tag.id].source === 'zenodo'"
                    :id="controlId(tag, 'value')"
                    v-model="mapping[activeStandard][activeModality][tag.id].field"
                    class="w-full min-w-0 min-h-[44px] bg-white border border-gray-200 rounded-lg px-3 py-2 text-sm font-medium focus:ring-2 focus:ring-cyan-600 outline-none"
                  >
                    <option v-for="opt in zenodoOptions" :key="opt.id" :value="opt.id">{{ opt.name }}</option>
                  </select>

                  <!-- Static Input -->
                  <input
                    v-else-if="mapping[activeStandard][activeModality][tag.id].source === 'static'"
                    :id="controlId(tag, 'value')"
                    v-model="mapping[activeStandard][activeModality][tag.id].value"
                    type="text"
                    placeholder="Enter value..."
                    class="w-full min-w-0 min-h-[44px] bg-white border border-gray-200 rounded-lg px-3 py-2 text-sm font-medium focus:ring-2 focus:ring-cyan-600 outline-none"
                  />

                  <!-- Options Selector -->
                  <select
                    v-else-if="mapping[activeStandard][activeModality][tag.id].source === 'options'"
                    :id="controlId(tag, 'value')"
                    v-model="mapping[activeStandard][activeModality][tag.id].value"
                    class="w-full min-w-0 min-h-[44px] bg-white border border-gray-200 rounded-lg px-3 py-2 text-sm font-medium focus:ring-2 focus:ring-cyan-600 outline-none"
                  >
                    <option v-for="opt in tag.options" :key="opt" :value="opt">{{ opt }}</option>
                  </select>

                   <div v-else-if="mapping[activeStandard][activeModality][tag.id].source === 'skip'" class="h-full flex items-center px-3 italic text-gray-400 text-xs">
                     Will use default logic
                   </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <details v-if="qualitySummary" class="px-4 py-3 text-sm text-slate-700">
      <summary class="cursor-pointer">Spreadsheet checks · {{ qualitySummary.row_count }} rows</summary>
      <p class="mt-2">Missing: {{ qualitySummary.missing.filename }} filenames, {{ qualitySummary.missing.title }} titles, {{ qualitySummary.missing.description }} descriptions, {{ qualitySummary.missing.creators }} creator entries. {{ qualitySummary.duplicate_source_count }} repeated source paths.</p>
      <p class="mt-1 text-xs">{{ qualitySummary.scope }}</p>
    </details>
    <p v-if="testError" role="alert" class="p-4 text-sm text-red-700">{{ testError }} Use Test Mapping to retry.</p>
    <p v-if="['cidoc_crm', 'jsonld'].includes(activeStandard)" class="px-4 py-2 text-sm text-slate-700">CIDOC-CRM and JSON-LD describe the same digital dataset. Both use the CIDOC-CRM mappings.</p>
    <!-- Test results -->
    <div v-if="testResult" class="bg-white border-t border-gray-200 flex flex-col max-h-[600px] overflow-auto">
      <div class="flex flex-wrap gap-3 items-center justify-between p-4 bg-gray-50 border-b">
        <div class="flex items-center gap-3">
          <span :class="['px-2 py-1 rounded text-[10px] font-bold uppercase tracking-wider', testResult.validation.valid ? 'bg-green-100 text-green-700' : validationUnavailable ? 'bg-amber-100 text-amber-800' : 'bg-red-100 text-red-700']">
            {{ testResult.validation.valid ? (activeStandard === 'iiif' ? 'IIIF checks passed' : `Valid ${activeStandardLabel}`) : validationUnavailable ? 'Unverified · validator unavailable' : 'Validation Failed' }}
          </span>
          <h3 class="text-sm font-bold text-gray-900">Preview · {{ sampleLabel }} - {{ activeStandard.toUpperCase() }}</h3>
        </div>
        <button aria-label="Close preview" @click="testResult = null" class="text-gray-400 hover:text-gray-600 transition-colors">
          <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
      <div class="flex flex-col lg:flex-row flex-1 overflow-auto">
        <div class="w-full lg:w-1/3 min-w-0 border-r p-4 overflow-y-auto bg-gray-50/50">
          <MetadataReview :metadata="testResult.metadata" :provenance="testResult.provenance" :source-name="testResult.source_filename || sampleRecords.find(sample => sample.row_index === selectedRowIndex)?.filename || ''" />
          <details v-if="testResult.adjustments?.length" class="mt-3 text-xs text-slate-700">
            <summary class="cursor-pointer">{{ testResult.adjustments.length }} generated additions or corrections</summary>
            <ul class="mt-2 space-y-2 break-words"><li v-for="(item, index) in testResult.adjustments" :key="index">{{ item.field }} · {{ item.action }}<span v-if="item.value != null">: {{ item.value }}</span></li></ul>
          </details>

          <div v-if="testResult.validation.errors?.length || testResult.validation.warnings?.length" class="mt-4">
            <h4 v-if="testResult.validation.errors?.length" class="text-xs uppercase font-semibold text-red-700 mb-2">Errors</h4>
            <ul v-if="testResult.validation.errors?.length" class="space-y-1 mb-4">
              <li v-for="(err, i) in testResult.validation.errors" :key="i" class="text-xs text-red-600 bg-red-50 p-1.5 rounded border border-red-100"><button v-if="correctionTag(err)" type="button" class="text-left underline" @click="focusCorrection(err)">{{ err }}</button><span v-else>{{ err }}</span></li>
            </ul>

            <h4 v-if="testResult.validation.warnings?.length" class="text-xs uppercase font-semibold text-amber-800 mb-2">Warnings</h4>
            <ul v-if="testResult.validation.warnings?.length" class="space-y-1">
              <li v-for="(warn, i) in testResult.validation.warnings" :key="i" class="text-xs text-amber-700 bg-amber-50 p-1.5 rounded border border-amber-100">{{ warn }}</li>
            </ul>
          </div>
          <p class="mt-4 text-xs text-gray-500">This check covers the selected record. {{ testResult.validation.details?.scope || 'Review generated defaults and warnings before processing the batch.' }}</p>
        </div>
        <div class="min-w-0 flex-1 space-y-3 overflow-auto p-4">
          <IiifManifestPreview v-if="activeStandard === 'iiif'" :content="testResult.json" />
          <details>
            <summary class="cursor-pointer text-sm text-indigo-700">Generated document</summary>
            <pre class="p-4 bg-gray-900 text-green-300 overflow-x-auto rounded-md font-mono text-xs leading-relaxed">{{ testPreviewOutput }}</pre>
          </details>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, reactive, computed, watch } from 'vue'
import api from '@/services/api'
import { useToast } from '@/composables/useToast'
import { useWorkflowStore } from '@/stores/workflow'
import MetadataReview from '@/components/workflow/MetadataReview.vue'
import IiifManifestPreview from '@/components/workflow/IiifManifestPreview.vue'
import { IIIF_PRESENTATION_LABEL } from '@/utils/iiifPresentation'

const toast = useToast()
const workflowStore = useWorkflowStore()

const props = defineProps({
  msfPath: { type: String, required: true },
  templateId: { type: Number, required: true },
  initialMapping: { type: Object, default: null },
  provider: { type: String, default: "WebHDP" }
})

const emit = defineEmits(['update:mapping'])

const activeStandard = ref('zenodo')
const activeModality = ref('3d')
const loadingColumns = ref(true)
const testing = ref(false)
const exporting = ref(false)
const importing = ref(false)
const fileInput = ref(null)
const testResult = ref(null)
const testError = ref('')
let testEpoch = 0
let columnsEpoch = 0
const msfColumns = ref([])
const selectedRowIndex = ref(0)
const sampleRecords = ref([])
const qualitySummary = ref(null)
const columnsError = ref('')
function controlId(tag, role) { return `lod-${activeStandard.value}-${activeModality.value}-${tag.id.replace(/[^a-z0-9]/gi, '-')}-${role}` }
const sampleLabel = computed(() => sampleRecords.value.find(sample => sample.row_index === (testResult.value?.row_index_used ?? selectedRowIndex.value))?.label || `Record ${(testResult.value?.row_index_used ?? selectedRowIndex.value) + 1}`)
const validationUnavailable = computed(() => {
  if (testResult.value?.validation?.status === 'invalid') return false
  if (testResult.value?.validation?.status === 'unverified') return true
  const remote = testResult.value?.validation?.details?.remote
  return remote && ['error', 'unavailable', 'disabled', 'unknown'].includes(String(remote.status).toLowerCase()) && remote.valid !== true
})
const suggestedRowIndex = ref(0)
const communityOverride = ref({
  enabled: true,
  community: '3d-big-data-space'
})

const lodStandards = [
  {
    id: 'zenodo',
    name: 'Zenodo',
    mapped: true,
    icon: {
      template: `
        <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      `
    }
  },
  {
    id: 'edm',
    name: 'EDM-XML',
    mapped: true,
    icon: {
      template: `
        <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      `
    }
  },
  {
    id: 'iiif',
    name: 'IIIF',
    mapped: true,
    icon: {
      template: `
        <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 10l-2 1m0 0l-2-1m2 1v2.5M20 7l-2 1m2-1l-2-1m2 1v2.5M14 4l-2-1-2 1M4 7l2-1M4 7l2 1M4 7v2.5M12 21l-2-1m2 1l2-1m-2 1v-2.5M6 18l-2-1v-2.5M18 18l2-1v-2.5" />
        </svg>
      `
    }
  },
  {
    id: 'mets',
    name: 'METS',
    mapped: true,
     icon: {
      template: `
        <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
        </svg>
      `
    }
  }
]

lodStandards.push({ id: 'cidoc_crm', name: 'CIDOC-CRM', icon: lodStandards[1].icon }, { id: 'jsonld', name: 'JSON-LD', icon: lodStandards[1].icon })

const modalities = [
  { id: '3d', name: '3D' },
  { id: 'image', name: 'Image' },
  { id: 'sound', name: 'Sound' },
  { id: 'text', name: 'Text' },
  { id: 'video', name: 'Video' }
]

const zenodoOptions = [
  { id: 'metadata.upload_type', name: 'Zenodo Upload Type' },
  { id: 'metadata.title', name: 'Zenodo Title' },
  { id: 'metadata.description', name: 'Zenodo Description' },
  { id: 'metadata.publication_date', name: 'Zenodo Pub. Date' },
  { id: 'metadata.creators', name: 'Zenodo Creators' },
  { id: 'metadata.access_right', name: 'Zenodo Access Right' },
  { id: 'metadata.license', name: 'Zenodo License' },
  { id: 'metadata.keywords', name: 'Zenodo Keywords' },
  { id: 'links.html', name: 'Zenodo URL' },
  { id: 'id', name: 'Zenodo ID' }
]

const zenodoTags = [
  { id: 'zenodo:title', name: 'Title', required: true, description: 'Zenodo record title.' },
  { id: 'zenodo:description', name: 'Description', required: true, description: 'Zenodo record description.' },
  { id: 'zenodo:upload_type', name: 'Upload Type', required: true, description: 'Zenodo upload type.', options: ['dataset', 'publication', 'image', 'video', 'software', 'poster', 'presentation', 'lesson', 'physicalobject', 'other'] },
  { id: 'zenodo:publication_date', name: 'Publication Date', required: true, description: 'Publication date in YYYY-MM-DD.' },
  { id: 'zenodo:creators', name: 'Creators', required: true, description: 'Creators (comma-separated for MSF/static).' },
  { id: 'zenodo:access_right', name: 'Access Right', required: true, description: 'Access right for the Zenodo record.', options: ['open', 'embargoed', 'restricted', 'closed'] },
  { id: 'zenodo:license', name: 'License', required: false, description: 'License identifier (required for open/embargoed).' },
  { id: 'zenodo:communities', name: 'Communities', required: false, description: 'Zenodo communities (comma-separated identifiers).' },
  { id: 'zenodo:keywords', name: 'Keywords', required: false, description: 'Keywords (comma-separated).' },
  { id: 'zenodo:notes', name: 'Notes', required: false, description: 'Free-form notes for the record.' },
  { id: 'zenodo:version', name: 'Version', required: false, description: 'Version identifier.' },
  { id: 'zenodo:language', name: 'Language', required: false, description: 'Language code (e.g. eng).' }
]

const tagsByModality = {
  '3d': [
    { id: 'dc:title', name: 'Title', required: true, description: 'The title of the 3D model.' },
    { id: 'dc:description', name: 'Description', required: false, description: 'Narrative description of the object.' },
    { id: 'dc:creator', name: 'Creator', required: false, description: 'Person or organization that created the model.' },
    { id: 'dcterms:created', name: 'Date Created', required: false, description: 'Date of creation (YYYY-MM-DD).' },
    { id: 'edm:type', name: 'EDM Type', required: true, description: 'Must be 3D.' },
    { id: 'edm:country', name: 'Country', required: true, description: 'Origin country.', options: ['Netherlands', 'France', 'Germany', 'Italy', 'Spain', 'Europe'] },
    { id: 'edm:language', name: 'Language', required: true, description: 'Primary language.', options: ['en', 'it', 'nl', 'fr', 'de', 'es', 'mul'] },
    { id: 'dcterms:medium', name: 'Medium', required: false, description: 'Material of the original object.' },
    { id: 'schema:digitalSourceType', name: 'Digital Source Type', required: false, description: 'How the model was produced (e.g. Reality Captured).' },
    { id: 'edm:intendedUsage', name: 'Intended Usage', required: false, description: 'Purpose of the digitization (e.g. Research, Education).' },
    { id: 'dcterms:extent', name: 'Extent/Size', required: false, description: 'Size of the resource (e.g. file size).' },
    { id: 'edm:vertexCount', name: 'Vertex Count', required: false, description: 'Number of vertices in the 3D model.' },
    { id: 'edm:polygonCount', name: 'Polygon Count', required: false, description: 'Number of polygons in the 3D model.' },
    { id: 'lod:thumbnailMode', name: 'Rendered Thumbnail Mode', required: false, description: 'How rendered thumbnails are selected (render pipeline only).', options: ['auto', 'any', 'all', 'pattern', 'list'] },
    { id: 'lod:thumbnailPattern', name: 'Rendered Thumbnail Pattern', required: false, description: 'Wildcard for rendered thumbnails (e.g. *_r0*.png).' },
    { id: 'lod:thumbnailFiles', name: 'Rendered Thumbnail Files', required: false, description: 'Comma-separated rendered thumbnail filenames for list mode.' }
  ],
  'image': [
    { id: 'dc:title', name: 'Title', required: true, description: 'Title of the image.' },
    { id: 'dc:description', name: 'Description', required: false, description: 'Description of the visual content.' },
    { id: 'dc:creator', name: 'Creator', required: false, description: 'Photographer or artist.' },
    { id: 'edm:type', name: 'EDM Type', required: true, description: 'Must be IMAGE.' },
    { id: 'edm:country', name: 'Country', required: true, description: 'Origin country.', options: ['Netherlands', 'France', 'Germany', 'Italy', 'Spain', 'Europe'] },
    { id: 'edm:language', name: 'Language', required: true, description: 'Primary language.', options: ['en', 'it', 'nl', 'fr', 'de', 'es', 'mul'] }
  ],
  'iiif': [
    { id: 'label', name: 'Label', required: true, description: 'The title of the Manifest.' },
    { id: 'summary', name: 'Summary', required: false, description: 'A brief description of the object.' },
    { id: 'iiif:manifestId', name: 'Manifest ID', required: false, description: 'Persistent IIIF Manifest ID URL.' },
    { id: 'iiif:sceneId', name: 'Scene ID', description: 'Persistent Scene identifier URL.', modalities: ['3d'] },
    { id: 'iiif:sceneLabel', name: 'Scene Label', description: 'Human-readable label for the 3D Scene.', modalities: ['3d'] },
    { id: 'iiif:timelineId', name: 'Timeline ID', description: 'Persistent identifier URL for timed audio.', modalities: ['sound'] },
    { id: 'iiif:timelineLabel', name: 'Timeline Label', description: 'Human-readable label for timed audio.', modalities: ['sound'] },
    { id: 'iiif:canvasId', name: 'Canvas ID', description: 'Persistent Canvas identifier URL. For audio, used when duration is unavailable.', modalities: ['image', 'video', 'sound', 'text'] },
    { id: 'iiif:canvasLabel', name: 'Canvas Label', description: 'Display label for the Canvas. For audio, used when duration is unavailable.', modalities: ['image', 'video', 'sound', 'text'] },
    { id: 'iiif:annotationPageId', name: 'Annotation Page ID', required: false, description: 'Annotation page identifier URI.' },
    { id: 'iiif:annotationId', name: 'Annotation ID', required: false, description: 'Annotation identifier URI.' },
    { id: 'iiif:contentId', name: 'Content URL', description: 'Direct URL of an alternative source asset of the same media type.' },
    { id: 'iiif:modelLabel', name: 'Model Label', description: 'Human-readable label for the referenced model.', modalities: ['3d'] },
    { id: 'iiif:modelFormat', name: 'Model Format', description: 'Media type of the referenced model.', modalities: ['3d'], options: ['model/gltf-binary', 'model/gltf+json', 'model/obj', 'application/octet-stream'] },
    { id: 'iiif:width', name: 'Canvas Width', description: 'Positive integer. Supply with height to set the presentation aspect ratio.', modalities: ['image', 'video', 'text'] },
    { id: 'iiif:height', name: 'Canvas Height', description: 'Positive integer. Without dimensions, a square virtual frame is used.', modalities: ['image', 'video', 'text'] },
    { id: 'iiif:duration', name: 'Duration (seconds)', description: 'Positive duration for audio or video playback. Without it, the source is offered as a download.', modalities: ['sound', 'video'] },
    { id: 'iiif:translateX', name: 'Translate X', description: 'X translation in Scene units.', modalities: ['3d'] },
    { id: 'iiif:translateY', name: 'Translate Y', description: 'Y translation in Scene units.', modalities: ['3d'] },
    { id: 'iiif:translateZ', name: 'Translate Z', description: 'Z translation in Scene units.', modalities: ['3d'] },
    { id: 'iiif:rotateX', name: 'Rotate X', description: 'Rotation in degrees around the Scene X axis.', modalities: ['3d'] },
    { id: 'iiif:rotateY', name: 'Rotate Y', description: 'Rotation in degrees around the Scene Y axis.', modalities: ['3d'] },
    { id: 'iiif:rotateZ', name: 'Rotate Z', description: 'Rotation in degrees around the Scene Z axis.', modalities: ['3d'] },
    { id: 'iiif:scaleX', name: 'Scale X', description: 'Nonzero scale factor along X.', modalities: ['3d'] },
    { id: 'iiif:scaleY', name: 'Scale Y', description: 'Nonzero scale factor along Y.', modalities: ['3d'] },
    { id: 'iiif:scaleZ', name: 'Scale Z', description: 'Nonzero scale factor along Z.', modalities: ['3d'] },
    { id: 'iiif:pointX', name: 'Point X', description: 'X coordinate of the target point in the Scene.', modalities: ['3d'] },
    { id: 'iiif:pointY', name: 'Point Y', description: 'Y coordinate of the target point in the Scene.', modalities: ['3d'] },
    { id: 'iiif:pointZ', name: 'Point Z', description: 'Z coordinate of the target point in the Scene.', modalities: ['3d'] },
    { id: 'iiif:latitude', name: 'Latitude', description: 'Latitude of the location to publish on a map, in decimal degrees. Supply with longitude.' },
    { id: 'iiif:longitude', name: 'Longitude', description: 'Longitude of the location to publish on a map, in decimal degrees. Supply with latitude.' },
    { id: 'iiif:altitude', name: 'Altitude', description: 'Optional height in metres above or below the WGS 84 ellipsoid.' },
    { id: 'lod:thumbnailMode', name: 'Rendered Thumbnail Mode', required: false, description: 'How rendered thumbnails are selected (render pipeline only).', options: ['auto', 'any', 'all', 'pattern', 'list'] },
    { id: 'lod:thumbnailPattern', name: 'Rendered Thumbnail Pattern', required: false, description: 'Wildcard for rendered thumbnails (e.g. *_r0*.png).' },
    { id: 'lod:thumbnailFiles', name: 'Rendered Thumbnail Files', required: false, description: 'Comma-separated rendered thumbnail filenames for list mode.' },
    { id: 'rights', name: 'Rights', required: false, description: 'The license or rights statement.' },
    { id: 'provider', name: 'Provider', required: false, description: 'Organization providing the manifest.' }
  ],
  'zenodo': zenodoTags
  // Fallback for other modalities
}

// Initialize mapping state
const mapping = reactive({
  zenodo: {}, edm: {}, iiif: {}, mets: {}
})

function getTagsForStandardAndModality(standardId, modalityId) {
  if (standardId === 'zenodo') return tagsByModality.zenodo
  if (['cidoc_crm', 'jsonld'].includes(standardId)) return tagsByModality['3d'].filter(tag => ['dc:title', 'dc:description', 'dc:creator'].includes(tag.id))
  if (standardId === 'iiif') return tagsByModality.iiif.filter(tag => !tag.modalities || tag.modalities.includes(modalityId))
  return tagsByModality[modalityId] || tagsByModality['3d']
}

function getDefaultMappingForTag(tagId) {
  if (tagId === 'dc:title' || tagId === 'label' || tagId === 'zenodo:title') {
    return { source: 'msf', field: 'title', value: '' }
  }
  if (tagId === 'dc:description' || tagId === 'summary' || tagId === 'zenodo:description') {
    return { source: 'msf', field: 'description', value: '' }
  }
  if (tagId === 'dc:creator' || tagId === 'zenodo:creators') {
    return { source: 'msf', field: 'creator', value: '' }
  }
  if (tagId === 'edm:country') {
    return { source: 'options', field: '', value: 'Europe' }
  }
  if (tagId === 'edm:language') {
    return { source: 'options', field: '', value: 'mul' }
  }
  if (tagId === 'iiif:modelFormat') {
    return { source: 'skip', field: '', value: '' }
  }
  if (tagId === 'iiif:sceneLabel') {
    return { source: 'static', field: '', value: 'A Scene' }
  }
  if (tagId === 'lod:thumbnailMode') {
    return { source: 'options', field: '', value: 'auto' }
  }
  if (tagId === 'rights') {
    return { source: 'zenodo', field: 'metadata.license', value: '' }
  }
  if (tagId === 'zenodo:upload_type') {
    return { source: 'options', field: '', value: 'dataset' }
  }
  if (tagId === 'zenodo:publication_date') {
    return { source: 'msf', field: 'dcterms:created', value: '' }
  }
  if (tagId === 'zenodo:access_right') {
    return { source: 'options', field: '', value: 'open' }
  }
  if (tagId === 'zenodo:license') {
    return { source: 'static', field: '', value: 'cc-by-4.0' }
  }
  if (tagId === 'zenodo:keywords') {
    return { source: 'msf', field: 'keywords', value: '' }
  }
  return { source: 'skip', field: '', value: '' }
}

function normalizeMappingItem(item) {
  return {
    source: item?.source || 'skip',
    field: item?.field || '',
    value: item?.value ?? ''
  }
}

function isCommunityOverrideLocked(tagId) {
  return (
    activeStandard.value === 'zenodo' &&
    communityOverride.value.enabled &&
    tagId === 'zenodo:communities'
  )
}

function initializeMappingDefaults() {
  lodStandards.forEach(std => {
    if (!mapping[std.id] || typeof mapping[std.id] !== 'object') {
      mapping[std.id] = {}
    }
    modalities.forEach(mod => {
      if (!mapping[std.id][mod.id] || typeof mapping[std.id][mod.id] !== 'object') {
        mapping[std.id][mod.id] = {}
      }
      const tags = getTagsForStandardAndModality(std.id, mod.id)
      tags.forEach(tag => {
        if (!mapping[std.id][mod.id][tag.id]) {
          mapping[std.id][mod.id][tag.id] = getDefaultMappingForTag(tag.id)
        }
      })
    })
  })
}

const modalityImportAliases = {
  '3d': ['3d', '3d_model', '3dmodel', 'model_3d'],
  'image': ['image', 'img'],
  'sound': ['sound', 'audio'],
  'text': ['text', 'document', 'doc'],
  'video': ['video']
}

const iiifImportAliases = {
  'iiif:contentId': ['iiif:modelId'],
  'iiif:sceneId': ['iiif:canvasId'],
  'iiif:sceneLabel': ['iiif:canvasLabel'],
  'iiif:canvasId': ['iiif:sceneId'],
  'iiif:canvasLabel': ['iiif:sceneLabel'],
  'iiif:timelineId': ['iiif:canvasId', 'iiif:sceneId'],
  'iiif:timelineLabel': ['iiif:canvasLabel', 'iiif:sceneLabel']
}

function isTagMappingNode(node) {
  if (!node || typeof node !== 'object' || Array.isArray(node)) return false
  return Object.values(node).some(v => v && typeof v === 'object' && !Array.isArray(v) && Object.prototype.hasOwnProperty.call(v, 'source'))
}

function resolveImportedModalityNode(importedStandard, modalityId) {
  if (!importedStandard || typeof importedStandard !== 'object') return null
  const aliases = modalityImportAliases[modalityId] || [modalityId]
  for (const alias of aliases) {
    const candidate = importedStandard[alias]
    if (candidate && typeof candidate === 'object' && !Array.isArray(candidate)) {
      return candidate
    }
  }
  // Legacy flat standard-level tag mapping: treat as 3D modality defaults.
  if (modalityId === '3d' && isTagMappingNode(importedStandard)) {
    return importedStandard
  }
  return null
}

function mergeImportedMapping(importedMapping) {
  if (!importedMapping || typeof importedMapping !== 'object') return
  importedMapping = { ...importedMapping, cidoc_crm: importedMapping.cidoc_crm || importedMapping.jsonld }
  let firstMapped = null
  lodStandards.filter(std => std.id !== 'jsonld').forEach(std => {
    const importedStandard = importedMapping[std.id]
    if (!importedStandard || typeof importedStandard !== 'object') return

    modalities.forEach(mod => {
      const importedModality = resolveImportedModalityNode(importedStandard, mod.id)
      if (!importedModality || typeof importedModality !== 'object') return

      const tags = getTagsForStandardAndModality(std.id, mod.id)
      tags.forEach(tag => {
        const sourceIds = [tag.id, ...(std.id === 'iiif' ? iiifImportAliases[tag.id] || [] : [])]
        const item = sourceIds.map(id => importedModality[id]).find(Boolean)
        if (item) {
          mapping[std.id][mod.id][tag.id] = normalizeMappingItem(item)
          if (!firstMapped) firstMapped = { standard: std.id, modality: mod.id }
        }
      })
    })
  })
  if (firstMapped) {
    activeStandard.value = firstMapped.standard
    activeModality.value = firstMapped.modality
  }
}

initializeMappingDefaults()
mapping.jsonld = mapping.cidoc_crm

const currentTags = computed(() => {
  return getTagsForStandardAndModality(activeStandard.value, activeModality.value)
})

function correctionTag(message) {
  const text = String(message).toLowerCase()
  return currentTags.value.find(tag => text.includes(tag.name.toLowerCase()) || new RegExp(`\\b${tag.id.split(':').pop().toLowerCase()}\\b`).test(text))
}
function focusCorrection(message) {
  const tag = correctionTag(message)
  if (tag) (document.getElementById(controlId(tag, 'value')) || document.getElementById(controlId(tag, 'source')))?.focus()
}
const activeStandardLabel = computed(() => {
  const match = lodStandards.find(std => std.id === activeStandard.value)
  return match?.name || activeStandard.value.toUpperCase()
})

const testPreviewOutput = computed(() => {
  if (!testResult.value) return ''
  if (['iiif', 'jsonld'].includes(activeStandard.value)) return testResult.value.json || ''
  if (activeStandard.value === 'zenodo') {
    return JSON.stringify(testResult.value.payload || { metadata: testResult.value.metadata || {} }, null, 2)
  }
  return testResult.value.xml || ''
})

const msfParseOptions = computed(() => {
  return workflowStore.msfParseOptions || workflowStore.msfProfile?.parse_options || {}
})

async function fetchCommunityOverride() {
  try {
    const res = await api.get('/metadata/zenodo-community-override', { suppressGlobalError: true })
    const cfg = res?.data?.config || {}
    communityOverride.value = {
      enabled: cfg.enabled !== false,
      community: cfg.community || '3d-big-data-space'
    }
  } catch (e) {
    communityOverride.value = {
      enabled: true,
      community: '3d-big-data-space'
    }
  }
}

async function fetchColumns() {
  const epoch = ++columnsEpoch
  loadingColumns.value = true
  columnsError.value = ''
  try {
    const payload = {
      msf_path: props.msfPath,
      session_id: workflowStore.sessionId
    }
    if (Object.keys(msfParseOptions.value || {}).length > 0) {
      payload.msf_parse_options = msfParseOptions.value
    }
    const res = await api.post('/edm/msf-columns', payload)
    if (epoch !== columnsEpoch) return
    if (res.success) {
      msfColumns.value = res.data.columns || []
      sampleRecords.value = res.data.sample_records || []
      qualitySummary.value = res.data.quality_summary || null
      const suggested = Number.isInteger(res.data.suggested_row_index) ? res.data.suggested_row_index : 0
      suggestedRowIndex.value = Math.max(0, suggested)
      selectedRowIndex.value = suggestedRowIndex.value
      if (res.data.msf_profile) {
        workflowStore.setMsfProfile(res.data.msf_profile)
        if (res.data.msf_profile.parse_options) {
          workflowStore.setMsfParseOptions(res.data.msf_profile.parse_options)
        }
      }
      lodStandards.forEach(std => {
        modalities.forEach(mod => {
          Object.keys(mapping[std.id][mod.id]).forEach(tagId => {
            const mapItem = mapping[std.id][mod.id][tagId]
            if (mapItem.source === 'msf' && mapItem.field && !msfColumns.value.includes(mapItem.field)) {
              const match = msfColumns.value.find(col => col.toLowerCase() === mapItem.field.toLowerCase())
              if (match) mapItem.field = match
            }
          })
        })
      })
    }
  } catch (e) {
    if (epoch !== columnsEpoch) return
    msfColumns.value = []
    columnsError.value = "Could not load spreadsheet fields. Check your connection and try again."
  } finally {
    if (epoch === columnsEpoch) loadingColumns.value = false
  }
}

async function testMapping() {
  const epoch = ++testEpoch
  const standard = activeStandard.value
  testError.value = ''
  testing.value = true
  testResult.value = null
  try {
    // Build backend-compatible mapping config for current modality
    const config = {}
    Object.keys(mapping[activeStandard.value][activeModality.value]).forEach(tagId => {
      const m = mapping[activeStandard.value][activeModality.value][tagId]
      if (m.source !== 'skip') {
        config[tagId] = { ...m }
      }
    })

    const endpointByStandard = {
      zenodo: '/metadata/test-mapping',
      edm: '/edm/test-mapping',
      iiif: '/iiif/test-mapping',
      mets: '/mets/test-mapping',
      cidoc_crm: '/edm/test-linked-mapping',
      jsonld: '/edm/test-linked-mapping'
    }
    const endpoint = endpointByStandard[activeStandard.value] || '/edm/test-mapping'

    const safeRowIndex = Math.max(0, Number(selectedRowIndex.value) || 0)
    const payload = {
      standard,
      msf_path: props.msfPath,
      session_id: workflowStore.sessionId,
      row_index: safeRowIndex,
      mapping_config: config,
      zenodo_mapping: mapping.zenodo?.[activeModality.value] || {},
      zenodo_record: {
        id: 12345,
        metadata: { ...workflowStore.submissionMetadata, edm_provider: props.provider },
        links: { html: "https://sandbox.zenodo.org/records/12345" },
        files: []
      }
    }
    if (Object.keys(msfParseOptions.value || {}).length > 0) {
      payload.msf_parse_options = msfParseOptions.value
    }
    if (standard === 'edm') {
      payload.template_id = props.templateId
    }

    const res = await api.post(endpoint, payload)

    if (epoch !== testEpoch) return
    if (!res.success || typeof res.data?.validation?.valid !== 'boolean') throw new Error("Validation is unavailable")
    if (res.success) {
      testResult.value = res.data

      if (res.data.validation.valid) toast.success("Mapping test passed!")
      else toast.warning("Mapping test failed validation.")
    }
  } catch (e) {
    if (epoch !== testEpoch) return
    testError.value = "Mapping test failed: " + (e.error?.message || e.message)
  } finally {
    if (epoch === testEpoch) testing.value = false
  }
}

async function exportMapping() {
  exporting.value = true
  try {
    const res = await api.post('/edm/mapping/export?format=json', mapping, { responseType: 'blob' })

    const blob = (res instanceof Blob) ? res : new Blob([res], { type: 'application/json' })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', `lod_mappings_${new Date().toISOString().slice(0,10)}.json`)
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)

    toast.success("Mapping exported successfully")
  } catch (e) {
    toast.error("Export failed: " + (e.message || "Unknown error"))
  } finally {
    exporting.value = false
  }
}

function triggerImport() {
  fileInput.value?.click()
}

async function importMapping(event) {
  const file = event.target.files[0]
  if (!file) return

  importing.value = true
  try {
    const formData = new FormData()
    formData.append('file', file)

    // Use direct axios post if api wrapper doesn't support FormData well,
    // or assume api.post handles it (usually does if data is FormData)
    // Checking api.js would be good, but assuming standard interface

    // Some api wrappers force JSON content type. Let's try standard way.
    const res = await api.post('/edm/mapping/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })

    if (res.success) {
      const importedPayload = res?.data?.mapping || res?.data || {}
      mergeImportedMapping(importedPayload)
      await fetchColumns()
      emit('update:mapping', JSON.parse(JSON.stringify(mapping)))

      toast.success("Mapping imported successfully")
    } else {
        toast.error("Import failed: " + res.message)
    }
  } catch (e) {
    toast.error("Import error: " + (e.error?.message || e.message))
  } finally {
    importing.value = false
    if (fileInput.value) fileInput.value.value = '' // reset
  }
}

watch([mapping, activeStandard, activeModality, selectedRowIndex, () => props.templateId, () => props.provider, () => workflowStore.submissionMetadata, () => props.msfPath, () => workflowStore.sessionId, msfParseOptions], () => {
  testEpoch++
  testing.value = false
  testResult.value = null
  testError.value = ''
}, { deep: true, flush: 'sync' })

// Watch for changes and emit
watch(mapping, (newMapping) => {
  emit('update:mapping', JSON.parse(JSON.stringify(newMapping)))
}, { deep: true })

watch(() => JSON.stringify([props.msfPath, workflowStore.sessionId, msfParseOptions.value]), () => {
  columnsEpoch++
  sampleRecords.value = []
  qualitySummary.value = null
  msfColumns.value = []
  fetchColumns()
})

onBeforeUnmount(() => { testEpoch++; columnsEpoch++ })

onMounted(() => {
  if (props.initialMapping) mergeImportedMapping(props.initialMapping)
  mapping.jsonld = mapping.cidoc_crm
  fetchColumns()
  fetchCommunityOverride()
})
</script>

<style scoped>
.glass-morphism {
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}

.lod-mapper-container {
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
}

.mapping-row {
  animation: slideIn 0.3s ease-out forwards;
  opacity: 0;
}

@keyframes slideIn {
  from { transform: translateX(20px); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}

.mapping-row:nth-child(n) {
  animation-delay: calc(n * 0.05s);
}

/* Custom scrollbar */
::-webkit-scrollbar {
  width: 6px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.1);
  border-radius: 10px;
}
::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.2);
}
</style>
