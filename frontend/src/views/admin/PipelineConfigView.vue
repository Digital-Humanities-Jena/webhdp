<template>
  <div class="mx-auto max-w-none px-3 py-4 sm:px-5 lg:px-6">
    <div class="space-y-5">
      <header class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
        <div class="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <h1 class="text-2xl font-semibold text-slate-900">Pipeline Constructor</h1>
          <p class="mt-2 max-w-3xl text-sm text-slate-600">
            Add components in execution order, connect their inputs, then validate and publish a version. Preflight checks sample files; running a pipeline performs real processing.
          </p>
        </div>

        <div class="grid w-full grid-cols-2 items-center gap-2 sm:flex sm:w-auto sm:flex-wrap sm:justify-end">
          <button
            type="button"
            class="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 xl:hidden"
            @click="catalogPanelOpen = !catalogPanelOpen"
          >
            Catalog
          </button>
          <button
            type="button"
            class="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 2xl:hidden"
            @click="diagnosticsPanelOpen = !diagnosticsPanelOpen"
          >
            Diagnostics
          </button>
          <select
            v-if="pipelines.length > 0"
            v-model="selectedPipelineId"
            aria-label="Select pipeline"
            :disabled="busy"
            class="col-span-2 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm sm:w-64"
            @change="handlePipelineSelection"
          >
            <option value="">New pipeline</option>
            <option v-for="pipeline in pipelines" :key="pipeline.identifier" :value="pipeline.identifier">
              {{ pipeline.name }} ({{ pipeline.identifier }})
            </option>
          </select>
          <button
            type="button"
            class="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 sm:px-4"
            :disabled="busy"
            @click="requestNewPipeline"
          >
            New Pipeline
          </button>
          <button
            type="button"
            class="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-50 sm:px-4"
            :disabled="busy"
            @click="validateConfig"
            data-testid="validate-pipeline"
          >
            {{ validating ? 'Validating...' : 'Validate' }}
          </button>
          <button
            type="button"
            class="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-50 sm:px-4"
            :disabled="busy"
            @click="runPreflight"
            data-testid="run-preflight"
          >
            {{ preflighting ? 'Preflighting...' : 'Preflight' }}
          </button>
          <button
            type="button"
            class="rounded-xl bg-indigo-600 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50 sm:px-4"
            :disabled="busy"
            @click="publishPipeline"
          >
            {{ saving ? 'Publishing...' : 'Publish Version' }}
          </button>
        </div>
        </div>
      </header>

      <div v-if="error" role="alert" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
        {{ error }}
      </div>
      <div v-if="successMessage" role="status" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
        {{ successMessage }}
      </div>

      <div class="flex flex-wrap items-center gap-3 text-sm" role="status">
        <span class="rounded-full bg-slate-100 px-3 py-1 font-medium text-slate-700">{{ isDirty ? 'Unpublished changes' : savedEditorSnapshot ? 'Saved version loaded' : 'New pipeline' }}</span>
        <span class="text-slate-600">{{ busy ? 'Working… Please wait before changing the configuration.' : '1. Configure → 2. Validate → 3. Publish version → 4. Preflight & run' }}</span>
        <button type="button" class="font-medium text-indigo-700 underline" :disabled="busy || !editor.identifier" @click="exportDefinition">Export definition</button>
      </div>
      <ProgressBar v-if="busy && !loading" :label="executingPipeline ? 'Running the saved pipeline…' : saving ? 'Validating and publishing version…' : preflighting ? 'Checking sample files…' : 'Checking component configuration…'" />
      <div v-if="loadFailed" class="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm">
        The workspace could not be loaded. <button type="button" class="font-semibold text-indigo-700 underline" :disabled="busy" @click="loadInitialData()">Retry loading</button>
      </div>
      <div v-if="loading" class="rounded-2xl border border-slate-200 bg-white px-6 py-16 shadow-sm">
        <LoadingSpinner size="lg" text="Loading constructor workspace..." />
      </div>

      <fieldset v-else :disabled="busy" class="min-w-0 grid gap-5 xl:grid-cols-[18rem,minmax(0,1fr)] 2xl:grid-cols-[19rem,minmax(0,1fr),22rem]">
        <div :class="[catalogPanelOpen ? 'block' : 'hidden', 'xl:block']">
          <PipelineConstructorCatalogSidebar
          :catalog-search="catalogSearch"
          :catalog-category="catalogCategory"
          :catalog-tag="catalogTag"
          :catalog-profile="catalogProfile"
          :component-categories="componentCategories"
          :component-tags="componentTags"
          :component-profiles="componentProfiles"
          :filtered-components="filteredComponents"
          :is-admin="isAdmin"
          :component-path="componentPath"
          :validating-component="validatingComponent"
          :importing-component="importingComponent"
          :component-validation-result="componentValidationResult"
          @update:catalog-search="catalogSearch = $event"
          @update:catalog-category="catalogCategory = $event"
          @update:catalog-tag="catalogTag = $event"
          @update:catalog-profile="catalogProfile = $event"
          @update:component-path="componentPath = $event"
          @clear-catalog-filters="clearCatalogFilters"
          @add-step-from-component="addStepFromComponent"
          @validate-component-path="validateComponentPath"
          @import-component-path="importComponentPath"
          />
        </div>

        <main class="min-w-0 space-y-5">
          <section class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
            <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h2 class="text-lg font-semibold text-slate-900">Pipeline Definition</h2>
                <p class="mt-1 text-sm text-slate-500">
                  The constructor writes native pipeline configs directly. Structured edits remain manifest-driven and advanced JSON extras are preserved.
                </p>
              </div>
              <div class="flex flex-wrap gap-2 text-xs">
                <span class="rounded-full bg-indigo-50 px-3 py-1 font-medium text-indigo-700">
                  Steps: {{ editor.steps.length }}
                </span>
                <span class="rounded-full bg-slate-100 px-3 py-1 font-medium text-slate-700">
                  Active selection: {{ editor.identifier || 'new' }}
                </span>
              </div>
            </div>

            <div class="mt-6 grid gap-4 md:grid-cols-2">
              <div>
                <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Identifier</label>
                <input aria-label="Identifier" v-model.trim="editor.identifier" type="text" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm" />
              </div>
              <div>
                <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Name</label>
                <input aria-label="Name" v-model.trim="editor.name" type="text" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm" />
              </div>
              <div>
                <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Version</label>
                <input aria-label="Version" v-model.trim="editor.version" type="text" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm" />
              </div>
              <div>
                <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Status</label>
                <select aria-label="Status" v-model="editor.status" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm">
                  <option value="active">active</option>
                  <option value="draft">draft</option>
                  <option value="archived">archived</option>
                </select>
              </div>
              <div>
                <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Modality</label>
                <input aria-label="Modality" v-model.trim="editor.modality" type="text" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm" />
              </div>
              <div>
                <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Processing Mode</label>
                <select aria-label="Processing Mode" v-model="editor.processingMode" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm">
                  <option value="root">root</option>
                  <option value="record">record</option>
                  <option value="batch">batch</option>
                </select>
              </div>
            </div>

            <div class="mt-4">
              <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Tags</label>
              <input
                aria-label="Tags"
                v-model.trim="editor.tagsText"
                type="text"
                class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
                placeholder="3d, zenodo, point-cloud"
              />
            </div>

            <div class="mt-4">
              <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Description</label>
              <textarea aria-label="Description" v-model="editor.description" rows="3" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm" />
            </div>
          </section>

          <section class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
            <div class="flex items-center justify-between">
              <div>
                <h2 class="text-lg font-semibold text-slate-900">Pipeline Steps</h2>
                <p class="mt-1 text-sm text-slate-500">
                  Each step is driven by the component manifest. Inputs, triggers, and output mappings are validated server-side.
                </p>
              </div>
            </div>

            <div v-if="dependencyIssues.length" role="alert" class="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              <p class="font-semibold">Connections need attention</p>
              <button v-for="(issue, index) in dependencyIssues" :key="index" type="button" class="mt-2 block text-left underline" @click="focusIssue(issue)">{{ issue.message }} Open connection</button>
            </div>
            <button v-if="undoSteps" type="button" class="mt-3 text-sm font-medium text-indigo-700 underline" @click="undoStepChange">Undo last step removal or move</button>
            <div v-if="editor.steps.length === 0" class="mt-6 rounded-2xl border border-dashed border-slate-300 px-6 py-14 text-center text-sm text-slate-500">
              Add components from the catalog to start constructing the pipeline.
            </div>

            <div v-else class="mt-6 space-y-6">
              <PipelineConstructorStepCard
                v-for="(step, index) in editor.steps"
                :key="step.localKey"
                :step="step"
                :index="index"
                :total-steps="editor.steps.length"
                :helpers="stepCardHelpers"
                :actions="stepCardActions"
                :preflight-session-id="preflightSessionId"
                :constructor-session-files="constructorSessionFiles"
                :constructor-session-directories="constructorSessionDirectories"
              />
            </div>
          </section>
        </main>

        <div :class="[diagnosticsPanelOpen ? 'block' : 'hidden', 'xl:col-span-2 2xl:col-span-1 2xl:block']">
          <PipelineConstructorSidePanel
          :execution-blocked-reason="executionBlockedReason"
          :sessions="sessions"
          :sessions-error="sessionsError"
          :loading-sessions="loadingSessions"
          :run-id="persistentRun.pending.value?.runId || ''"
          :run-elapsed="persistentRun.elapsed.value"
          :can-retry-request="Boolean(persistentRun.pending.value?.request)"
          @retry-sessions="loadSessions"
          @reconnect-run="persistentRun.refresh"
          @dismiss-run="persistentRun.dismiss"
          @retry-run-request="persistentRun.retry"
          @focus-diagnostic="focusDiagnostic"
          :validation-result="validationResult"
          :preflight-result="preflightResult"
          :preflight-session-id="preflightSessionId"
          :preflight-file-paths-text="preflightFilePathsText"
          :constructor-session-files="constructorSessionFiles"
          :constructor-session-directories="constructorSessionDirectories"
          :loading-session-paths="loadingSessionPaths"
          :executing-pipeline="executingPipeline"
          :pipeline-execution-result="pipelineExecutionResult"
          :pipeline-execution-run="pipelineExecutionRun"
          :pipeline-execution-error="pipelineExecutionError"
          @update:preflight-session-id="preflightSessionId = $event"
          @update:preflight-file-paths-text="preflightFilePathsText = $event"
          @refresh-session-resources="refreshSessionResources"
          @run-pipeline-execution="runPipelineExecution"
          @run-preflight="runPreflight"
          />
        </div>
      </fieldset>
    </div>

    <PipelineConstructorOutputMappingModal
      v-if="outputMappingStep"
      :step="outputMappingStep"
      :support-data="supportData"
      :get-json-outputs="getJsonOutputs"
      :is-drop-target="isOutputMappingDropTarget"
      @close="closeOutputMappingModal"
      @add-output-mapping="addOutputMapping"
      @move-output-mapping="moveOutputMapping"
      @remove-output-mapping="removeOutputMapping"
      @start-output-mapping-drag="startOutputMappingDrag"
      @set-output-mapping-drop-target="setOutputMappingDropTarget"
      @drop-output-mapping-on="dropOutputMappingOn"
      @end-output-mapping-drag="endOutputMappingDrag"
    />
  </div>
</template>

<script setup>
import { usePersistentPipelineRun } from '@/composables/usePersistentPipelineRun'
import { computed, onMounted, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRoute, onBeforeRouteLeave } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import ProgressBar from '@/components/ui/ProgressBar.vue'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import PipelineConstructorCatalogSidebar from '@/components/admin/pipeline/PipelineConstructorCatalogSidebar.vue'
import PipelineConstructorOutputMappingModal from '@/components/admin/pipeline/PipelineConstructorOutputMappingModal.vue'
import PipelineConstructorSidePanel from '@/components/admin/pipeline/PipelineConstructorSidePanel.vue'
import PipelineConstructorStepCard from '@/components/admin/pipeline/PipelineConstructorStepCard.vue'
import fileService from '@/services/file.service'
import pipelineService from '@/services/pipeline.service'
import {
  buildPlaygroundFormState,
  deriveDirectories,
  flattenSessionFilePaths,
  getPlaygroundParameterGroups,
  getPlaygroundSchema,
  serializePlaygroundFieldValue,
} from '@/utils/playgroundManifest'
import {
  buildAdvancedJsonPayload,
  buildDefaultBindingForField,
  buildOutputActionSourceKey,
  getCompatibleSourceOutputOptions as getCompatibleSourceOutputOptionsForField,
  normalizeTriggerRule as normalizeConstructorTriggerRule,
  serializeTriggerCondition,
  serializeTriggerRule,
} from '@/utils/pipelineConstructor'
import { useToast } from '@/composables/useToast'

const route = useRoute()
const authStore = useAuthStore()
const toast = useToast()

const loading = ref(true)
const validating = ref(false)
const preflighting = ref(false)
const saving = ref(false)
let publicationRequest = null
const persistentRun = usePersistentPipelineRun(() => authStore.user?.id || 'current')
const executingPipeline = persistentRun.active
const sessions = ref([])
const sessionsError = ref('')
const loadingSessions = ref(false)
const savedComponents = ref([])
const undoSteps = ref(null)
const validatingComponent = ref(false)
const importingComponent = ref(false)
const catalogPanelOpen = ref(false)
const diagnosticsPanelOpen = ref(false)
const error = ref('')
const successMessage = ref('')
const pipelines = ref([])
const components = ref([])
const selectedPipelineId = ref('')
const validationResult = ref(null)
const preflightResult = ref(null)
const pipelineExecutionResult = ref(null)
const pipelineExecutionRun = persistentRun.run
const pipelineExecutionError = persistentRun.error
const componentValidationResult = ref(null)
const supportData = reactive({
  trigger_operators: [],
  file_facts: [],
  transforms: [],
  overwrite_policies: [],
  zenodo_target_paths: [],
  edm_metadata_target_paths: [],
  metadata_target_paths: [],
})
const componentPath = ref('')
const catalogSearch = ref('')
const catalogCategory = ref('')
const catalogTag = ref('')
const catalogProfile = ref('')
const preflightSessionId = ref('')
const preflightFilePathsText = ref('')
const loadingSessionPaths = ref(false)
const constructorSessionFiles = ref([])
const constructorSessionDirectories = ref([])
const outputMappingStepKey = ref('')
const draggingStepKey = ref('')
const stepDropTargetKey = ref('')
const draggingTriggerStepKey = ref('')
const draggingTriggerRuleKey = ref('')
const triggerRuleDropTargetKey = ref('')
const draggingOutputMappingStepKey = ref('')
const draggingOutputMappingKey = ref('')
const outputMappingDropTargetKey = ref('')

let localStepCounter = 0
const SESSION_RESOURCE_CACHE_TTL_MS = 30_000
const sessionResourceCache = new Map()
let sessionResourcesAbortController = null
let activeSessionLoadToken = 0

function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

function nextLocalKey(prefix = 'step') {
  localStepCounter += 1
  return `${prefix}-${localStepCounter}`
}

function createEmptyEditor() {
  return {
    identifier: '',
    name: '',
    description: '',
    status: 'active',
    modality: '3D Model',
    processingMode: 'root',
    version: '1.0.0',
    tagsText: '',
    steps: [],
  }
}

const editor = reactive(createEmptyEditor())
const cleanEditorSnapshot = ref(JSON.stringify(editor))
const savedEditorSnapshot = ref('')
const loadedPipelineConfig = ref(null)
const loadedPipelineId = ref('')
const loadFailed = ref(false)
let pipelineLoadToken = 0
const busy = computed(() => loading.value || saving.value || validating.value || preflighting.value || persistentRun.submitting.value || importingComponent.value || validatingComponent.value)
const isDirty = computed(() => JSON.stringify(editor) !== cleanEditorSnapshot.value)
const executionBlockedReason = computed(() => {
  if (executingPipeline.value) return 'A run is active. Follow its progress below; you can leave and reconnect later.'
  if (busy.value) return 'Wait for the current operation to finish.'
  if (!savedEditorSnapshot.value || JSON.stringify(editor) !== savedEditorSnapshot.value) return 'Publish these changes before running. Runs use the saved version, not an editor draft.'
  if (!Number.isSafeInteger(Number(preflightSessionId.value)) || Number(preflightSessionId.value) <= 0) return 'Choose a valid session ID and its files in Preflight.'
  if (!preflightFilePathsText.value.trim()) return 'Choose at least one session file in Preflight.'
  if (preflightResult.value?.valid !== true) return 'Run Preflight for this version and these files before starting.'
  return ''
})
function confirmDiscard() {
  return !isDirty.value || window.confirm('Discard unpublished pipeline changes? Export the definition first if you want to keep a copy.')
}
function requestNewPipeline() {
  if (!busy.value && confirmDiscard()) resetEditor()
}
function exportDefinition() {
  try {
    const blob = new Blob([JSON.stringify(buildPipelinePayload(), null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'pipeline-definition.json'
    link.click()
    URL.revokeObjectURL(url)
  } catch (err) { error.value = err.message }
}
function warnBeforeUnload(event) {
  if (!isDirty.value && !busy.value) return
  event.preventDefault()
  event.returnValue = ''
}
onBeforeRouteLeave(() => busy.value ? false : confirmDiscard())
onBeforeUnmount(() => {
  pipelineLoadToken += 1
  cancelSessionResourceLoad()
  window.removeEventListener('beforeunload', warnBeforeUnload)
})
watch(componentPath, () => { componentValidationResult.value = null }, { flush: 'sync' })
watch(editor, () => {
  validationResult.value = null
  preflightResult.value = null
  successMessage.value = ''
}, { deep: true, flush: 'sync' })
watch([preflightSessionId, preflightFilePathsText], () => { preflightResult.value = null }, { flush: 'sync' })

const isAdmin = computed(() => authStore.user?.role === 'admin')
const componentMap = computed(() => {
  const map = {}
  components.value.forEach((component) => {
    map[component.key] = component
  })
  return map
})

function getConstructorProfileIds(component) {
  const profiles = component?.constructor_schema?.profiles || []
  if (!profiles.length) {
    return ['builtin_default']
  }
  return profiles.map((profile) => profile.id).filter(Boolean)
}

const componentCategories = computed(() => {
  const categories = new Set()
  components.value.forEach((component) => {
    const category = component.constructor_schema?.metadata?.category
    if (category) {
      categories.add(category)
    }
  })
  return Array.from(categories).sort((left, right) => left.localeCompare(right))
})
const componentTags = computed(() => {
  const tags = new Set()
  components.value.forEach((component) => {
    ;(component.constructor_schema?.metadata?.tags || []).forEach((tag) => {
      if (tag) {
        tags.add(tag)
      }
    })
  })
  return Array.from(tags).sort((left, right) => left.localeCompare(right))
})
const componentProfiles = computed(() => {
  const profiles = new Set()
  components.value.forEach((component) => {
    getConstructorProfileIds(component).forEach((profileId) => profiles.add(profileId))
  })
  return Array.from(profiles).sort((left, right) => left.localeCompare(right))
})
const filteredComponents = computed(() => {
  const search = catalogSearch.value.toLowerCase()
  return components.value.filter((component) => {
    const category = component.constructor_schema?.metadata?.category || ''
    if (catalogCategory.value && category !== catalogCategory.value) {
      return false
    }
    if (catalogTag.value && !(component.constructor_schema?.metadata?.tags || []).includes(catalogTag.value)) {
      return false
    }
    if (catalogProfile.value && !getConstructorProfileIds(component).includes(catalogProfile.value)) {
      return false
    }
    if (!search) {
      return true
    }
    const haystack = [
      component.key,
      component.name,
      component.description,
      ...(component.constructor_schema?.metadata?.tags || []),
      ...(component.constructor_schema?.metadata?.keywords || []),
    ]
      .join(' ')
      .toLowerCase()
    return haystack.includes(search)
  })
})
const outputMappingStep = computed(() => editor.steps.find((step) => step.localKey === outputMappingStepKey.value) || null)

function toFieldFormValue(field, value) {
  if (value === undefined || value === null) {
    return field?.type === 'boolean' ? false : ''
  }
  if (field?.type === 'json' || field?.widget === 'json_editor') {
    return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
  }
  if (field?.type === 'file_list' || field?.widget === 'file_list_picker') {
    return Array.isArray(value) ? value.join('\n') : String(value)
  }
  if (String(field?.type || '').startsWith('array[') || field?.widget === 'array_editor') {
    return Array.isArray(value) ? value.join('\n') : String(value)
  }
  if (field?.type === 'boolean' || field?.widget === 'checkbox') {
    return value === true
  }
  return value
}

function parseTags(text) {
  return String(text || '')
    .split(',')
    .map((entry) => entry.trim())
    .filter(Boolean)
}

function normalizeBinding(binding) {
  return {
    enabled: true,
    target: binding.target,
    type: binding.type || '',
    source_step: binding.source_step || '',
    source_output: binding.source_output || '',
    selector: binding.selector || '',
  }
}

function getComponentForStep(step) {
  if (!step) return null
  return savedComponents.value.find(item => item.key === step.component_ref && item.version === step.component_version) || componentMap.value[step.component_ref] || null
}

function getComponentProfiles(step) {
  return getComponentForStep(step)?.constructor_schema?.profiles || [{ id: 'builtin_default' }]
}

function getConstructorInputs(step) {
  return getComponentForStep(step)?.constructor_schema?.inputs || []
}

function getParameterGroups(step) {
  const component = getComponentForStep(step)
  return component ? getPlaygroundParameterGroups(getPlaygroundSchema(component)) : []
}

function getAllParameterFields(step) {
  return getParameterGroups(step).flatMap((group) => group.fields || [])
}

function getParameterField(step, fieldName) {
  return getAllParameterFields(step).find((field) => field.name === fieldName) || null
}

function getJsonOutputs(step) {
  return (getComponentForStep(step)?.constructor_schema?.outputs || []).filter((output) => ['json', 'file_path'].includes(output.type))
}

function getStepIndex(step) {
  return editor.steps.findIndex((candidate) => candidate.localKey === step.localKey)
}

function defaultScopeForComponent(componentKey) {
  return componentKey === 'fast_renderer' ? 'batch' : 'record'
}

function getEarlierStepDescriptors(currentIndex) {
  return editor.steps.slice(0, currentIndex).map((step) => ({
    id: step.id,
    outputs: getComponentForStep(step)?.constructor_schema?.outputs || [],
  }))
}

function defaultBindingForField(field, currentIndex, earlierStepDescriptors = null) {
  return buildDefaultBindingForField(field, earlierStepDescriptors || getEarlierStepDescriptors(currentIndex))
}

function initializeParameterForm(component, existingParameters = {}) {
  const schema = getPlaygroundSchema(component)
  const form = buildPlaygroundFormState(schema).parameters
  getPlaygroundParameterGroups(schema).forEach((group) => {
    group.fields.forEach((field) => {
      if (Object.prototype.hasOwnProperty.call(existingParameters, field.name)) {
        form[field.name] = toFieldFormValue(field, existingParameters[field.name])
      }
    })
  })
  return form
}

function buildStepState(component, rawStep = {}, stepIndex = 0, earlierStepDescriptors = null) {
  const constructorSchema = component?.constructor_schema || { inputs: [], outputs: [], profiles: [] }
  const profileId = rawStep.execution_profile_ref || constructorSchema.profiles?.[0]?.id || 'builtin_default'
  const componentInputs = constructorSchema.inputs || []
  const structuredBindings = {}
  const structuredBindingTargets = []
  const rawInputBindings = Array.isArray(rawStep.input_bindings) ? rawStep.input_bindings : []
  componentInputs.forEach((field) => {
    const existing = rawInputBindings.find((binding) => binding.target === field.name && (field.supported_source_kinds || []).includes(binding.type))
    structuredBindings[field.name] = existing ? normalizeBinding(existing) : defaultBindingForField(field, stepIndex, earlierStepDescriptors)
    if (existing) {
      structuredBindingTargets.push(field.name)
    }
  })

  const rawOutputActions = Array.isArray(rawStep.output_actions) ? rawStep.output_actions : []
  const structuredOutputMappings = rawOutputActions
    .filter((action) => ['zenodo_metadata_field', 'edm_metadata_field'].includes(action.action_type))
    .map((action) => ({
      localKey: nextLocalKey('mapping'),
      action_type: action.action_type || '',
      source_output: action.source_output || '',
      selector: action.selector || '',
      transform: action.transform || '',
      target_field: action.target_field || '',
      overwrite_policy: action.overwrite_policy || '',
      __sourceKey: buildOutputActionSourceKey(action),
    }))

  return {
    localKey: nextLocalKey('step'),
    id: rawStep.id || buildUniqueStepId(component?.key || 'step'),
    name: rawStep.name || component?.constructor_schema?.title || component?.name || 'Step',
    description: rawStep.description || component?.description || '',
    enabled: rawStep.enabled !== false,
    scope: rawStep.scope || defaultScopeForComponent(component?.key || rawStep.component_ref || rawStep.id),
    component_ref: rawStep.component_ref || component?.key,
    component_version: rawStep.component_version || component?.version,
    component_manifest_hash: rawStep.component_manifest_hash,
    execution_profile_ref: profileId,
    parameterForm: initializeParameterForm(component, rawStep.parameters || {}),
    structuredInputBindings: structuredBindings,
    outputMappings: structuredOutputMappings,
    triggers: {
      default_behavior: rawStep.triggers?.default_behavior || 'run',
      rules: (rawStep.triggers?.rules || []).map((rule) => normalizeConstructorTriggerRule(rule, nextLocalKey)),
    },
    advancedJson: buildAdvancedJsonPayload(rawStep, structuredBindingTargets, structuredOutputMappings),
  }
}

function buildUniqueStepId(baseId) {
  const cleanedBase = String(baseId || 'step')
    .replace(/[^a-zA-Z0-9_]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toLowerCase() || 'step'
  let candidate = cleanedBase
  let index = 2
  const used = new Set(editor.steps.map((step) => step.id))
  while (used.has(candidate)) {
    candidate = `${cleanedBase}_${index}`
    index += 1
  }
  return candidate
}

function hydrateEditor(config) {
  resetEditor()
  editor.identifier = config.identifier || ''
  editor.name = config.name || config.identifier || ''
  editor.description = config.description || ''
  editor.status = config.status || 'active'
  editor.modality = config.modality || '3D Model'
  editor.processingMode = config.processingMode || 'root'
  editor.version = config.version || '1.0.0'
  editor.tagsText = Array.isArray(config.tags) ? config.tags.join(', ') : ''
  const earlierStepDescriptors = []
  editor.steps = (config.steps || []).map((step, index) => {
    const component = getComponentForStep(step)
    const hydratedStep = buildStepState(component, step, index, earlierStepDescriptors)
    earlierStepDescriptors.push({
      id: hydratedStep.id,
      outputs: getComponentForStep(hydratedStep)?.constructor_schema?.outputs || [],
    })
    return hydratedStep
  })
  cleanEditorSnapshot.value = JSON.stringify(editor)
  savedEditorSnapshot.value = cleanEditorSnapshot.value
}

function resetEditor() {
  const next = createEmptyEditor()
  editor.identifier = next.identifier
  editor.name = next.name
  editor.description = next.description
  editor.status = next.status
  editor.modality = next.modality
  editor.processingMode = next.processingMode
  editor.version = next.version
  editor.tagsText = next.tagsText
  editor.steps = []
  selectedPipelineId.value = ''
  outputMappingStepKey.value = ''
  validationResult.value = null
  preflightResult.value = null
  endStepDrag()
  endTriggerRuleDrag()
  endOutputMappingDrag()
  cleanEditorSnapshot.value = JSON.stringify(editor)
  savedEditorSnapshot.value = ''
  loadedPipelineId.value = ''
  loadedPipelineConfig.value = null
  pipelineExecutionResult.value = null
  undoSteps.value = null
}

function cancelSessionResourceLoad() {
  activeSessionLoadToken += 1
  if (sessionResourcesAbortController) {
    sessionResourcesAbortController.abort()
    sessionResourcesAbortController = null
  }
  loadingSessionPaths.value = false
}

function getCachedSessionResources(sessionId) {
  const cached = sessionResourceCache.get(sessionId)
  if (!cached) {
    return null
  }
  if ((Date.now() - cached.cachedAt) > SESSION_RESOURCE_CACHE_TTL_MS) {
    sessionResourceCache.delete(sessionId)
    return null
  }
  return cached
}

function invalidateSessionResourceCache(sessionId = null) {
  const normalizedId = Number.parseInt(sessionId, 10)
  if (Number.isInteger(normalizedId) && normalizedId > 0) {
    sessionResourceCache.delete(normalizedId)
    return
  }
  sessionResourceCache.clear()
}

async function loadSessionResources(sessionId, options = {}) {
  const force = options.force === true
  const normalizedId = Number.parseInt(sessionId, 10)
  if (!Number.isInteger(normalizedId) || normalizedId <= 0) {
    cancelSessionResourceLoad()
    constructorSessionFiles.value = []
    constructorSessionDirectories.value = []
    return
  }

  const cached = force ? null : getCachedSessionResources(normalizedId)
  if (cached) {
    constructorSessionFiles.value = cached.files
    constructorSessionDirectories.value = cached.directories
    return
  }

  if (sessionResourcesAbortController) {
    sessionResourcesAbortController.abort()
  }

  const requestToken = ++activeSessionLoadToken
  const controller = new AbortController()
  sessionResourcesAbortController = controller
  loadingSessionPaths.value = true
  try {
    const response = await fileService.getNodes(normalizedId, {
      signal: controller.signal,
      suppressGlobalError: true,
    })
    if (requestToken !== activeSessionLoadToken) {
      return
    }
    const files = flattenSessionFilePaths(response.data?.nodes || [])
    const directories = deriveDirectories(files)
    sessionResourceCache.set(normalizedId, { files, directories, cachedAt: Date.now() })
    constructorSessionFiles.value = files
    constructorSessionDirectories.value = directories
  } catch (requestError) {
    if (controller.signal.aborted || requestError?.code === 'ERR_CANCELED' || requestError?.name === 'CanceledError') {
      return
    }
    if (requestToken !== activeSessionLoadToken) {
      return
    }
    constructorSessionFiles.value = []
    constructorSessionDirectories.value = []
    toast.error(requestError?.error?.message || requestError?.message || 'Failed to load session paths.')
  } finally {
    if (requestToken === activeSessionLoadToken) {
      loadingSessionPaths.value = false
    }
    if (sessionResourcesAbortController === controller) {
      sessionResourcesAbortController = null
    }
  }
}

async function refreshSessionResources() {
  if (!preflightSessionId.value) {
    return
  }
  invalidateSessionResourceCache(preflightSessionId.value)
  await loadSessionResources(preflightSessionId.value, { force: true })
}

async function loadPipeline(identifier) {
  const token = ++pipelineLoadToken
  const response = await pipelineService.getPipeline(identifier)
  if (token !== pipelineLoadToken) return
  const config = response.data.pipeline.config || response.data.pipeline
  savedComponents.value = response.data.pipeline.components || []
  hydrateEditor(config)
  loadedPipelineConfig.value = clone(config)
  loadedPipelineId.value = identifier
  selectedPipelineId.value = identifier
}

function clearCatalogFilters() {
  catalogSearch.value = ''
  catalogCategory.value = ''
  catalogTag.value = ''
  catalogProfile.value = ''
}

function reorderMutableList(list, fromIndex, toIndex) {
  if (!Array.isArray(list) || fromIndex === toIndex) {
    return false
  }
  if (fromIndex < 0 || toIndex < 0 || fromIndex >= list.length || toIndex >= list.length) {
    return false
  }
  const [entry] = list.splice(fromIndex, 1)
  list.splice(toIndex, 0, entry)
  return true
}

function addStepFromComponent(component) {
  const step = buildStepState(component, { component_ref: component.key }, editor.steps.length)
  if (!step.id || editor.steps.some((existing) => existing.id === step.id)) {
    step.id = buildUniqueStepId(component.key)
  }
  editor.steps.push(step)
}

function moveStep(index, direction) {
  undoSteps.value = clone(editor.steps)
  reorderMutableList(editor.steps, index, index + direction)
}

function startStepDrag(step) {
  draggingStepKey.value = step.localKey
}

function setStepDropTarget(step) {
  if (!draggingStepKey.value || draggingStepKey.value === step.localKey) {
    return
  }
  stepDropTargetKey.value = step.localKey
}

function dropStepOn(step) {
  const fromIndex = editor.steps.findIndex((entry) => entry.localKey === draggingStepKey.value)
  const toIndex = editor.steps.findIndex((entry) => entry.localKey === step.localKey)
  undoSteps.value = clone(editor.steps)
  reorderMutableList(editor.steps, fromIndex, toIndex)
  endStepDrag()
}

function endStepDrag() {
  draggingStepKey.value = ''
  stepDropTargetKey.value = ''
}

function isStepDropTarget(step) {
  return Boolean(stepDropTargetKey.value) && stepDropTargetKey.value === step.localKey
}

function duplicateStep(index) {
  const original = editor.steps[index]
  const duplicate = clone(original)
  duplicate.localKey = nextLocalKey('step')
  duplicate.id = buildUniqueStepId(original.id)
  duplicate.name = `${original.name} Copy`
  duplicate.outputMappings = (duplicate.outputMappings || []).map((mapping) => ({ ...mapping, localKey: nextLocalKey('mapping') }))
  duplicate.triggers.rules = (duplicate.triggers.rules || []).map((rule) => ({
    ...rule,
    localKey: nextLocalKey('rule'),
    conditions: (rule.conditions || []).map((condition) => ({ ...condition, localKey: nextLocalKey('condition') })),
    parameterOverrideRows: (rule.parameterOverrideRows || []).map((row) => ({ ...row, localKey: nextLocalKey('override') })),
  }))
  editor.steps.splice(index + 1, 0, duplicate)
}

function removeStep(index) {
  const step = editor.steps[index]
  const dependants = editor.steps.filter(item => stepSources(item).some(binding => binding.source_step === step.id))
  if (dependants.length && !window.confirm(`Remove ${step.name}? These steps depend on it: ${dependants.map(item => item.name).join(', ')}. Their connections will need updating. You can undo this removal.`)) return
  undoSteps.value = clone(editor.steps)
  editor.steps.splice(index, 1)
}

function updateParameterValue(step, fieldName, value) {
  step.parameterForm[fieldName] = value
}

function getStepBinding(step, fieldName) {
  if (!step.structuredInputBindings[fieldName]) {
    const field = getConstructorInputs(step).find((entry) => entry.name === fieldName)
    step.structuredInputBindings[fieldName] = field ? defaultBindingForField(field, getStepIndex(step)) : { enabled: false, target: fieldName, type: '', source_step: '', source_output: '', selector: '' }
  }
  return step.structuredInputBindings[fieldName]
}

function getBindingTypeOptions(field) {
  const labels = {
    pipeline_source_file: 'Pipeline Source File',
    pipeline_source_files: 'Pipeline Source Files',
    pipeline_source_directory: 'Pipeline Source Directory',
    artifact_file: 'Earlier Step File Output',
    artifact_directory: 'Earlier Step Directory Output',
    artifact_json_value: 'Earlier Step JSON Value',
  }
  return (field.supported_source_kinds || [])
    .filter((kind) => labels[kind])
    .map((kind) => ({ value: kind, label: labels[kind] }))
}

function bindingNeedsSourceStep(binding) {
  return ['artifact_file', 'artifact_directory', 'artifact_json_value'].includes(binding.type)
}

function bindingNeedsSourceOutput(binding) {
  return ['artifact_file', 'artifact_directory', 'artifact_json_value'].includes(binding.type)
}

function getCompatibleSourceStepOptions(step, field) {
  const currentIndex = getStepIndex(step)
  const options = []
  editor.steps.slice(0, currentIndex).forEach((candidate) => {
    const outputs = getCompatibleSourceOutputOptions(step, field, candidate.id)
    if (outputs.length > 0) {
      options.push({ value: candidate.id, label: `${candidate.name} (${candidate.id})` })
    }
  })
  return options
}

function getCompatibleSourceOutputOptions(step, field, sourceStepId) {
  const sourceStep = editor.steps.find((candidate) => candidate.id === sourceStepId)
  const outputs = getComponentForStep(sourceStep)?.constructor_schema?.outputs || []
  return getCompatibleSourceOutputOptionsForField(field, outputs)
}

function handleBindingTypeChange(step, fieldName) {
  const binding = getStepBinding(step, fieldName)
  binding.source_step = ''
  binding.source_output = ''
  binding.selector = ''
}

function handleBindingSourceStepChange(step, fieldName) {
  const binding = getStepBinding(step, fieldName)
  binding.source_output = ''
  binding.selector = ''
}

function getCompatibleSelectorExamples(step, field, binding) {
  if (binding.type !== 'artifact_json_value' || !binding.source_step || !binding.source_output) {
    return []
  }
  const sourceStep = editor.steps.find((candidate) => candidate.id === binding.source_step)
  const sourceOutput = (getComponentForStep(sourceStep)?.constructor_schema?.outputs || []).find((entry) => entry.name === binding.source_output)
  return sourceOutput?.selector_examples || []
}

function getEarlierClassifierStepOptions(step) {
  const currentIndex = getStepIndex(step)
  return editor.steps
    .slice(0, currentIndex)
    .filter((candidate) => candidate.component_ref === 'input_file_classification')
    .map((candidate) => ({ value: candidate.id, label: `${candidate.name} (${candidate.id})` }))
}

function getClassifierOutputOptions(sourceStepId) {
  const sourceStep = editor.steps.find((candidate) => candidate.id === sourceStepId)
  return (getComponentForStep(sourceStep)?.constructor_schema?.outputs || [])
    .filter((output) => (output.trigger_fields || []).length > 0)
    .map((output) => ({ value: output.name, label: output.label || output.name }))
}

function getTriggerFieldOptions(step, condition) {
  if (condition.source_type === 'file_fact') {
    return supportData.file_facts.map((entry) => ({ value: entry.field, label: entry.label }))
  }
  const sourceStep = editor.steps.find((candidate) => candidate.id === condition.source_step)
  const output = (getComponentForStep(sourceStep)?.constructor_schema?.outputs || []).find((entry) => entry.name === condition.source_output)
  return (output?.trigger_fields || []).map((entry) => ({ value: entry.path, label: entry.label }))
}

function getTriggerOperatorOptions(condition) {
  if (condition.source_type === 'file_fact') {
    const match = supportData.file_facts.find((entry) => entry.field === condition.field)
    const operators = match?.operators || supportData.trigger_operators.map((entry) => entry.id)
    return supportData.trigger_operators.filter((entry) => operators.includes(entry.id))
  }
  const sourceStep = editor.steps.find((candidate) => candidate.id === condition.source_step)
  const output = (getComponentForStep(sourceStep)?.constructor_schema?.outputs || []).find((entry) => entry.name === condition.source_output)
  const triggerField = (output?.trigger_fields || []).find((entry) => entry.path === condition.field)
  const operators = triggerField?.operators || supportData.trigger_operators.map((entry) => entry.id)
  return supportData.trigger_operators.filter((entry) => operators.includes(entry.id))
}

function handleTriggerSourceTypeChange(condition) {
  condition.source_step = ''
  condition.source_output = ''
  condition.field = ''
  condition.operator = 'eq'
  condition.value_text = ''
  condition.value_from = ''
  condition.value_to = ''
}

function handleTriggerSourceStepChange(step, condition) {
  condition.source_output = ''
  condition.field = ''
}

function addTriggerRule(step) {
  step.triggers.rules.push({
    localKey: nextLocalKey('rule'),
    id: buildUniqueStepId('rule'),
    label: '',
    action: 'run',
    conditions: [],
    parameterOverrideRows: [],
  })
}

function removeTriggerRule(step, index) {
  step.triggers.rules.splice(index, 1)
}

function moveTriggerRule(step, index, direction) {
  reorderMutableList(step.triggers.rules, index, index + direction)
}

function startTriggerRuleDrag(step, rule) {
  draggingTriggerStepKey.value = step.localKey
  draggingTriggerRuleKey.value = rule.localKey
}

function setTriggerRuleDropTarget(step, rule) {
  if (!draggingTriggerRuleKey.value || draggingTriggerStepKey.value !== step.localKey || draggingTriggerRuleKey.value === rule.localKey) {
    return
  }
  triggerRuleDropTargetKey.value = rule.localKey
}

function dropTriggerRuleOn(step, rule) {
  if (draggingTriggerStepKey.value !== step.localKey) {
    endTriggerRuleDrag()
    return
  }
  const fromIndex = step.triggers.rules.findIndex((entry) => entry.localKey === draggingTriggerRuleKey.value)
  const toIndex = step.triggers.rules.findIndex((entry) => entry.localKey === rule.localKey)
  reorderMutableList(step.triggers.rules, fromIndex, toIndex)
  endTriggerRuleDrag()
}

function endTriggerRuleDrag() {
  draggingTriggerStepKey.value = ''
  draggingTriggerRuleKey.value = ''
  triggerRuleDropTargetKey.value = ''
}

function isTriggerRuleDropTarget(step, rule) {
  return draggingTriggerStepKey.value === step.localKey && triggerRuleDropTargetKey.value === rule.localKey
}

function addTriggerCondition(step, rule) {
  rule.conditions.push({
    localKey: nextLocalKey('condition'),
    source_type: 'file_fact',
    source_step: '',
    source_output: '',
    field: '',
    operator: 'eq',
    value_text: '',
    value_from: '',
    value_to: '',
  })
}

function removeTriggerCondition(rule, index) {
  rule.conditions.splice(index, 1)
}

function addParameterOverride(rule) {
  rule.parameterOverrideRows.push({
    localKey: nextLocalKey('override'),
    name: '',
    value: '',
  })
}

function removeParameterOverride(rule, index) {
  rule.parameterOverrideRows.splice(index, 1)
}

function resetParameterOverrideValue(step, overrideRow) {
  const field = getParameterField(step, overrideRow.name)
  overrideRow.value = field ? toFieldFormValue(field, field.default) : ''
}

function openOutputMappingModal(step) {
  outputMappingStepKey.value = step.localKey
}

function closeOutputMappingModal() {
  outputMappingStepKey.value = ''
}

function addOutputMapping(step) {
  step.outputMappings.push({
    localKey: nextLocalKey('mapping'),
    action_type: '',
    source_output: getJsonOutputs(step)[0]?.name || '',
    selector: '',
    transform: '',
    target_field: '',
    overwrite_policy: '',
  })
}

function getMetadataTargetPaths() {
  return supportData.metadata_target_paths?.length ? supportData.metadata_target_paths : supportData.zenodo_target_paths
}

function actionTypeForMetadataTarget(targetPath) {
  const target = getMetadataTargetPaths().find((entry) => entry.path === targetPath)
  return target?.action_type || 'zenodo_metadata_field'
}

function removeOutputMapping(step, index) {
  step.outputMappings.splice(index, 1)
}

function moveOutputMapping(step, index, direction) {
  reorderMutableList(step.outputMappings, index, index + direction)
}

function startOutputMappingDrag(step, mapping) {
  draggingOutputMappingStepKey.value = step.localKey
  draggingOutputMappingKey.value = mapping.localKey
}

function setOutputMappingDropTarget(step, mapping) {
  if (!draggingOutputMappingKey.value || draggingOutputMappingStepKey.value !== step.localKey || draggingOutputMappingKey.value === mapping.localKey) {
    return
  }
  outputMappingDropTargetKey.value = mapping.localKey
}

function dropOutputMappingOn(step, mapping) {
  if (draggingOutputMappingStepKey.value !== step.localKey) {
    endOutputMappingDrag()
    return
  }
  const fromIndex = step.outputMappings.findIndex((entry) => entry.localKey === draggingOutputMappingKey.value)
  const toIndex = step.outputMappings.findIndex((entry) => entry.localKey === mapping.localKey)
  reorderMutableList(step.outputMappings, fromIndex, toIndex)
  endOutputMappingDrag()
}

function endOutputMappingDrag() {
  draggingOutputMappingStepKey.value = ''
  draggingOutputMappingKey.value = ''
  outputMappingDropTargetKey.value = ''
}

function isOutputMappingDropTarget(mapping) {
  return Boolean(outputMappingDropTargetKey.value) && outputMappingDropTargetKey.value === mapping.localKey
}

function coercePrimitiveValue(value, kind) {
  if (kind === 'number' || kind === 'integer') {
    const numeric = Number(value)
    return Number.isFinite(numeric) ? numeric : value
  }
  if (kind === 'boolean') {
    const normalized = String(value).trim().toLowerCase()
    if (['true', '1', 'yes', 'on'].includes(normalized)) return true
    if (['false', '0', 'no', 'off'].includes(normalized)) return false
  }
  return value
}

function normalizeTriggerConditionForSave(step, condition) {
  const payload = {
    source_type: condition.source_type,
    field: condition.field,
    operator: condition.operator,
  }
  if (condition.source_type === 'classifier_output') {
    payload.source_step = condition.source_step
    payload.source_output = condition.source_output
  }

  let valueType = 'string'
  if (condition.source_type === 'file_fact') {
    valueType = supportData.file_facts.find((entry) => entry.field === condition.field)?.value_type || 'string'
  } else {
    const sourceStep = editor.steps.find((candidate) => candidate.id === condition.source_step)
    const output = (getComponentForStep(sourceStep)?.constructor_schema?.outputs || []).find((entry) => entry.name === condition.source_output)
    valueType = (output?.trigger_fields || []).find((entry) => entry.path === condition.field)?.value_type || 'string'
  }

  if (condition.operator === 'between') {
    payload.values = [
      coercePrimitiveValue(condition.value_from, valueType),
      coercePrimitiveValue(condition.value_to, valueType),
    ]
    return payload
  }
  if (condition.operator === 'in' || condition.operator === 'not_in') {
    payload.values = String(condition.value_text || '')
      .split(',')
      .map((entry) => entry.trim())
      .filter(Boolean)
      .map((entry) => coercePrimitiveValue(entry, valueType))
    return payload
  }
  if (!['exists', 'truthy'].includes(condition.operator)) {
    payload.value = coercePrimitiveValue(condition.value_text, valueType)
  }
  return payload
}

function parseAdvancedJson(step) {
  const text = String(step.advancedJson || '').trim()
  if (!text) {
    return {}
  }
  const parsed = JSON.parse(text)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`Advanced JSON on step '${step.name}' must be an object.`)
  }
  return parsed
}

function serializeStep(step) {
  const component = getComponentForStep(step)
  if (!component) {
    throw new Error(`Component '${step.component_ref}' is not registered.`)
  }
  const advanced = parseAdvancedJson(step)
  const parameters = {}
  getParameterGroups(step).forEach((group) => {
    group.fields.forEach((field) => {
      const serialized = serializePlaygroundFieldValue(field, step.parameterForm[field.name])
      if (serialized !== undefined) {
        parameters[field.name] = serialized
      }
    })
  })

  const structuredInputBindings = getConstructorInputs(step)
    .map((field) => getStepBinding(step, field.name))
    .filter((binding) => binding.enabled && binding.type)
    .map((binding) => ({
      kind: 'input',
      target: binding.target,
      type: binding.type,
      source_step: binding.source_step || undefined,
      source_output: binding.source_output || undefined,
      selector: binding.selector || undefined,
    }))

  const outputActions = step.outputMappings.map((mapping) => ({
    action_type: mapping.action_type || actionTypeForMetadataTarget(mapping.target_field),
    source_output: mapping.source_output,
    selector: mapping.selector || undefined,
    target_field: mapping.target_field,
    transform: mapping.transform || undefined,
    overwrite_policy: mapping.overwrite_policy || undefined,
  }))

  const triggers = {
    default_behavior: step.triggers.default_behavior || 'run',
    rules: step.triggers.rules.map((rule) => {
      const parameter_overrides = {}
      ;(rule.parameterOverrideRows || []).forEach((row) => {
        if (!row.name) {
          return
        }
        const field = getParameterField(step, row.name)
        if (!field) {
          return
        }
        const serialized = serializePlaygroundFieldValue(field, row.value)
        if (serialized !== undefined) {
          parameter_overrides[row.name] = serialized
        }
      })
      return serializeTriggerRule(
        rule,
        (rule.conditions || []).map((condition) => serializeTriggerCondition(condition, normalizeTriggerConditionForSave(step, condition))),
        parameter_overrides
      )
    }),
  }

  return {
    id: step.id,
    name: step.name,
    description: step.description || '',
    enabled: step.enabled !== false,
    scope: step.scope || 'record',
    component_ref: step.component_ref,
    component_version: step.component_version,
    component_manifest_hash: step.component_manifest_hash,
    execution_profile_ref: step.execution_profile_ref || 'builtin_default',
    parameters,
    input_bindings: [...structuredInputBindings, ...(advanced.input_bindings || [])],
    parameter_bindings: advanced.parameter_bindings || [],
    output_actions: [...outputActions, ...(advanced.output_actions || [])],
    resources: advanced.resources || {},
    triggers: {
      ...(advanced.triggers || {}),
      ...triggers,
    },
  }
}

function buildPipelinePayload() {
  if (!editor.identifier) {
    throw new Error('Pipeline identifier is required.')
  }
  if (!editor.name) {
    throw new Error('Pipeline name is required.')
  }
  return {
    identifier: editor.identifier,
    name: editor.name,
    description: editor.description || '',
    status: editor.status || 'active',
    modality: editor.modality || '3D Model',
    processingMode: editor.processingMode || 'root',
    version: editor.version || '1.0.0',
    tags: parseTags(editor.tagsText),
    steps: editor.steps.map((step) => serializeStep(step)),
  }
}

async function validateConfig() {
  if (busy.value) return
  diagnosticsPanelOpen.value = true
  error.value = ''
  successMessage.value = ''
  validating.value = true
  validationResult.value = null
  try {
    const payload = buildPipelinePayload()
    const snapshot = JSON.stringify(editor)
    const response = await pipelineService.validatePipelineConfig(payload)
    if (snapshot !== JSON.stringify(editor)) return
    validationResult.value = response.data
    if (response.data.valid) {
      toast.success('Pipeline validation passed')
    } else {
      toast.warning('Pipeline validation returned errors')
    }
  } catch (err) {
    error.value = err.error?.message || err.message || 'Failed to validate pipeline.'
  } finally {
    validating.value = false
  }
}

async function runPreflight() {
  if (busy.value) return
  diagnosticsPanelOpen.value = true
  error.value = ''
  successMessage.value = ''
  pipelineExecutionError.value = ''
  preflighting.value = true
  preflightResult.value = null
  validationResult.value = null
  try {
    const payload = buildPipelinePayload()
    const localFilePaths = String(preflightFilePathsText.value || '')
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
    if (!Number.isSafeInteger(Number(preflightSessionId.value)) || Number(preflightSessionId.value) <= 0 || !localFilePaths.length) throw new Error('Choose a valid session ID and at least one file for preflight.')
    const snapshot = JSON.stringify(editor)
    const context = JSON.stringify([preflightSessionId.value, preflightFilePathsText.value])
    const response = await pipelineService.preflightPipelineConstructor({
      pipeline_definition: payload,
      session_id: Number(preflightSessionId.value),
      local_file_paths: localFilePaths,
    })
    if (snapshot !== JSON.stringify(editor) || context !== JSON.stringify([preflightSessionId.value, preflightFilePathsText.value])) return
    preflightResult.value = response.data
    validationResult.value = response.data.validation
    if (response.data.valid === true) toast.success('Pipeline preflight completed')
    else toast.warning('Preflight found problems. Review the diagnostics before running.')
  } catch (err) {
    error.value = err.error?.message || err.message || 'Failed to preflight pipeline.'
  } finally {
    preflighting.value = false
  }
}

async function runPipelineExecution() {
  if (executionBlockedReason.value) { pipelineExecutionError.value = executionBlockedReason.value; return }
  diagnosticsPanelOpen.value = true
  await persistentRun.start({
    sessionId: Number(preflightSessionId.value),
    paths: preflightFilePathsText.value.split('\n').map(path => path.trim()).filter(Boolean),
    identifier: editor.identifier,
    version: loadedPipelineConfig.value.version,
    preflightToken: preflightResult.value?.preflight_token,
  })
}

async function loadSessions() {
  loadingSessions.value = true
  sessionsError.value = ''
  try { sessions.value = (await fileService.listSessions()).data?.sessions || [] }
  catch (err) { sessionsError.value = err?.error?.message || err.message || 'Could not load sessions. Retry the session list.' }
  finally { loadingSessions.value = false }
}

function stepSources(step) {
  let advanced = {}
  try { advanced = JSON.parse(step.advancedJson || '{}') } catch { /* JSON validation reports malformed advanced settings. */ }
  const advancedBindings = [...(Array.isArray(advanced?.input_bindings) ? advanced.input_bindings : []), ...(Array.isArray(advanced?.parameter_bindings) ? advanced.parameter_bindings : [])].filter(Boolean).map(binding => ({ ...binding, advanced: true }))
  return [...Object.values(step.structuredInputBindings || {}).filter(binding => binding?.enabled), ...advancedBindings, ...(step.triggers?.rules || []).flatMap(rule => rule.conditions || [])].filter(item => item?.source_step)
}
const dependencyIssues = computed(() => editor.steps.flatMap((step, index) => stepSources(step).flatMap(binding => {
  const source = editor.steps.findIndex(item => item.id === binding.source_step)
  const problem = source < 0 ? 'is missing' : source >= index ? 'must appear earlier' : !editor.steps[source].enabled && step.enabled ? 'is disabled' : ''
  return problem ? [{ stepId: step.id, message: `${step.name}: source “${binding.source_step}” ${problem}.`, target: binding.target, advanced: binding.advanced, trigger: !binding.target }] : []
})))
function focusIssue(issue) {
  const card = document.querySelector(`[data-testid="step-card-${CSS.escape(issue.stepId)}"]`)
  if (!card) return
  card.open = true
  const tab = card.querySelector(`[data-tab="${issue.advanced ? 'advanced' : issue.trigger ? 'triggers' : 'inputs'}"]`)
  tab?.click()
  requestAnimationFrame(() => {
    const target = issue.advanced ? card.querySelector('textarea[data-testid]') : issue.target ? card.querySelector(`[data-testid="binding-source-step-${CSS.escape(issue.stepId)}-${CSS.escape(issue.target)}"]`) : tab
    ;(target || card.querySelector('input'))?.focus()
    card.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
}
function focusDiagnostic(message) {
  const step = editor.steps.find(item => String(message).includes(`'${item.id}'`))
  if (step) focusIssue({ stepId: step.id, trigger: String(message).includes('trigger') })
}
function undoStepChange() {
  if (!undoSteps.value) return
  editor.steps = undoSteps.value
  undoSteps.value = null
}

async function publishPipeline() {
  if (busy.value) return
  error.value = ''
  successMessage.value = ''
  saving.value = true
  try {
    const payload = buildPipelinePayload()
    const check = await pipelineService.validatePipelineConfig(payload)
    validationResult.value = check.data
    diagnosticsPanelOpen.value = true
    if (check.data?.valid !== true) throw new Error('Resolve the validation errors before publishing this version.')
    const fingerprint = JSON.stringify(payload)
    if (publicationRequest?.fingerprint !== fingerprint) publicationRequest = { fingerprint, id: crypto.randomUUID() }
    const response = await pipelineService.createPipelineVersion(payload.identifier, payload, { requestId: publicationRequest.id })
    await loadInitialData(payload.identifier)
    successMessage.value = `Published ${response.data.pipeline.identifier} (${response.data.pipeline.publication_version || response.data.pipeline.active_version || response.data.pipeline.version || 'new version'}).${loadFailed.value ? ' Reload the saved version before testing it.' : ''}`
  } catch (err) {
    error.value = err.error?.message || err.message || 'Failed to publish pipeline.'
  } finally {
    saving.value = false
  }
}

async function validateComponentPath() {
  if (busy.value) return
  if (!componentPath.value) {
    toast.error('Component path is required')
    return
  }
  validatingComponent.value = true
  try {
    const path = componentPath.value
    const response = await pipelineService.validateComponentManifest(path)
    if (path !== componentPath.value) return
    componentValidationResult.value = response.data
    toast.success('Component manifest validated')
  } catch (err) {
    toast.error(err.error?.message || err.message || 'Failed to validate component manifest')
  } finally {
    validatingComponent.value = false
  }
}

async function importComponentPath() {
  if (busy.value) return
  if (!componentPath.value) {
    toast.error('Component path is required')
    return
  }
  importingComponent.value = true
  try {
    await pipelineService.importComponent(componentPath.value)
    toast.success('Component imported')
    const response = await pipelineService.listComponents()
    components.value = response.data.components || []
    validationResult.value = null
    preflightResult.value = null
  } catch (err) {
    toast.error(err.error?.message || err.message || 'Failed to import component')
  } finally {
    importingComponent.value = false
  }
}

async function handlePipelineSelection() {
  if (busy.value || !confirmDiscard()) { selectedPipelineId.value = loadedPipelineId.value; return }
  if (!selectedPipelineId.value) { resetEditor(); return }
  loading.value = true
  try { await loadPipeline(selectedPipelineId.value) }
  catch (err) { selectedPipelineId.value = loadedPipelineId.value; error.value = err.error?.message || err.message || 'Could not load the selected pipeline. Your editor is unchanged.' }
  finally { loading.value = false }
}

async function loadInitialData(preferredPipelineId = '') {
  error.value = ''
  loading.value = true
  loadFailed.value = false
  try {
    const [pipelinesResponse, componentsResponse, supportResponse] = await Promise.all([
      pipelineService.listPipelines(),
      pipelineService.listComponents(),
      pipelineService.getPipelineConstructorSupport(),
    ])
    pipelines.value = pipelinesResponse.data.pipelines || []
    components.value = componentsResponse.data.components || []
    Object.assign(supportData, supportResponse.data || {})

    const initialIdentifier = preferredPipelineId || selectedPipelineId.value || pipelines.value[0]?.identifier || ''
    if (initialIdentifier) {
      selectedPipelineId.value = initialIdentifier
      await loadPipeline(initialIdentifier)
    } else {
      resetEditor()
    }
  } catch (err) {
    loadFailed.value = true
    error.value = err.error?.message || err.message || 'Failed to load pipeline constructor workspace.'
  } finally {
    loading.value = false
  }
}

const stepCardHelpers = {
  getComponentForStep,
  getComponentProfiles,
  getConstructorInputs,
  getStepBinding,
  getBindingTypeOptions,
  bindingNeedsSourceStep,
  bindingNeedsSourceOutput,
  getCompatibleSourceStepOptions,
  getCompatibleSourceOutputOptions,
  getCompatibleSelectorExamples,
  getParameterGroups,
  getAllParameterFields,
  getParameterField,
  getEarlierClassifierStepOptions,
  getClassifierOutputOptions,
  getTriggerFieldOptions,
  getTriggerOperatorOptions,
  getJsonOutputs,
}

const stepCardActions = {
  moveStep,
  startStepDrag,
  setStepDropTarget,
  dropStepOn,
  endStepDrag,
  isStepDropTarget,
  duplicateStep,
  removeStep,
  updateParameterValue,
  handleBindingTypeChange,
  handleBindingSourceStepChange,
  addTriggerRule,
  removeTriggerRule,
  moveTriggerRule,
  startTriggerRuleDrag,
  setTriggerRuleDropTarget,
  dropTriggerRuleOn,
  endTriggerRuleDrag,
  isTriggerRuleDropTarget,
  addTriggerCondition,
  removeTriggerCondition,
  handleTriggerSourceTypeChange,
  handleTriggerSourceStepChange,
  addParameterOverride,
  removeParameterOverride,
  resetParameterOverrideValue,
  openOutputMappingModal,
}

onMounted(async () => {
  window.addEventListener('beforeunload', warnBeforeUnload)
  if (!authStore.user) {
    await authStore.fetchCurrentUser()
  }
  await Promise.all([loadInitialData(), loadSessions()])
  await persistentRun.resume(new URLSearchParams(window.location.search).get('run'))
  if (persistentRun.pending.value) diagnosticsPanelOpen.value = true
  if (route.path.startsWith('/tools')) {
    successMessage.value = ''
  }
})

watch(
  () => preflightSessionId.value,
  async (sessionId) => {
    await loadSessionResources(sessionId)
  }
)
</script>
