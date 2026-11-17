<template>
  <Teleport to="body">
    <div
      v-if="show && component"
      class="fixed inset-0 z-[120] flex items-center justify-center bg-slate-950/70 px-4 py-6"
      @click.self="close"
    >
      <div
        ref="dialogRef"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        class="flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl"
      >
        <div class="border-b border-slate-200 px-6 py-5">
          <div class="flex items-start justify-between gap-4">
            <div class="min-w-0">
              <div class="flex flex-wrap items-center gap-2">
                <span class="rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-700">
                  Playground
                </span>
                <span class="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
                  {{ component.key }}
                </span>
                <span
                  v-if="schema.metadata?.category"
                  class="rounded-full bg-indigo-50 px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.18em] text-indigo-700"
                >
                  {{ schema.metadata.category }}
                </span>
              </div>
              <h2 :id="titleId" class="mt-3 text-2xl font-semibold text-slate-950">
                {{ componentTitle }}
              </h2>
              <p class="mt-2 max-w-3xl text-sm text-slate-600">
                {{ componentDescription || 'No component description available.' }}
              </p>
            </div>

            <button
              type="button"
              class="rounded-full border border-slate-200 p-2 text-slate-500 transition hover:border-slate-300 hover:bg-slate-100 hover:text-slate-700"
              @click="close"
            >
              <span class="sr-only">Close playground modal</span>
              <svg class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path fill-rule="evenodd" d="M4.22 4.22a.75.75 0 011.06 0L10 8.94l4.72-4.72a.75.75 0 111.06 1.06L11.06 10l4.72 4.72a.75.75 0 11-1.06 1.06L10 11.06l-4.72 4.72a.75.75 0 11-1.06-1.06L8.94 10 4.22 5.28a.75.75 0 010-1.06z" clip-rule="evenodd" />
              </svg>
            </button>
          </div>
        </div>

        <div class="grid min-h-0 flex-1 grid-cols-1 gap-0 lg:grid-cols-[minmax(0,1fr)_22rem]">
          <div class="min-h-0 overflow-y-auto px-6 py-5">
            <fieldset :disabled="running || persistentRun.submitting.value" class="min-w-0">
            <div class="grid grid-cols-1 gap-4 md:grid-cols-3">
              <div>
                <label class="mb-2 block text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Session</label>
                <select
                  v-model="form.sessionId"
                  class="block w-full rounded-xl border-slate-300 bg-white text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                >
                  <option value="">Select a session</option>
                  <option
                    v-for="session in sessions"
                    :key="session.id"
                    :value="String(session.id)"
                  >
                    Session #{{ session.id }} · {{ session.status }} · {{ formatDate(session.created_at) }}
                  </option>
                </select>
                <p v-if="fieldErrors.sessionId" class="mt-2 text-xs text-rose-600">{{ fieldErrors.sessionId }}</p>
              </div>

              <div>
                <label class="mb-2 block text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Profile</label>
                <select
                  v-model="form.profileId"
                  class="block w-full rounded-xl border-slate-300 bg-white text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                >
                  <option
                    v-for="profile in profileOptions"
                    :key="profile.profile_id"
                    :value="profile.profile_id"
                  >
                    {{ profile.profile_id }} · {{ profile.adapter }}
                  </option>
                </select>
              </div>

              <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                <label class="flex items-center justify-between gap-4 text-sm font-medium text-slate-700">
                  <span>Run in sandbox mode</span>
                  <input
                    v-model="form.isSandbox"
                    type="checkbox"
                    class="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                  >
                </label>
                <p class="mt-2 text-xs text-slate-500">Session-backed Playground runs use the native adapter contract.</p>
              </div>
            </div>

            <div v-if="loadingSessions" class="mt-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
              <LoadingSpinner size="sm" text="Loading sessions..." />
            </div>

            <div v-if="form.sessionId" class="mt-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
              <div class="flex items-center justify-between gap-4">
                <div>
                  <div class="text-sm font-medium text-slate-900">Session Context</div>
                  <div class="mt-1 text-xs text-slate-500">
                    {{ sessionFiles.length }} files and {{ sessionDirectories.length }} directories available for manifest-backed path fields.
                  </div>
                </div>
                <div class="flex shrink-0 items-center gap-3">
                  <button
                    type="button"
                    class="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
                    :disabled="loadingSessionPaths"
                    @click="refreshSessionResources"
                  >
                    {{ loadingSessionPaths ? 'Refreshing…' : 'Refresh Paths' }}
                  </button>
                  <LoadingSpinner v-if="loadingSessionPaths" size="sm" text="Loading session paths..." />
                </div>
              </div>
            </div>

            <div v-if="form.sessionId" class="mt-4 rounded-2xl border border-indigo-200 bg-indigo-50 px-4 py-4">
              <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <div class="text-sm font-medium text-slate-900">HPC-Link Playground Allocation</div>
                  <div class="mt-1 text-xs text-indigo-900">
                    {{ hpcPlaygroundMessage }}
                  </div>
                </div>
                <button
                  type="button"
                  class="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
                  :disabled="hpcPlaygroundLoading || !form.sessionId || Boolean(hpcPlaygroundAllocation?.reservation_id)"
                  @click="requestPlaygroundHpcAllocation"
                >
                  {{ hpcPlaygroundLoading ? 'Requesting...' : hpcPlaygroundAllocation?.reservation_id ? 'Reserved GPU selected' : 'Allocate HPC' }}
                </button>
              </div>
            </div>
            <ReservedGpuAccess
              v-if="form.sessionId"
              class="mt-3"
              purpose="playground"
              :session-id="form.sessionId"
              :disabled="running || hpcPlaygroundLoading"
              @session-allocation="setPlaygroundReservedGpu"
            />

            <div v-if="errorMessage" class="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {{ errorMessage }}
            </div>

            <section v-if="visibleInputFields.length > 0" class="mt-6">
              <div class="mb-4">
                <h3 class="text-lg font-semibold text-slate-950">Inputs</h3>
                <p class="mt-1 text-sm text-slate-500">Inputs come from the canonical Playground schema produced by the component manifest.</p>
              </div>

              <div class="space-y-5">
                <PlaygroundFieldRenderer
                  v-for="field in visibleInputFields"
                  :key="`input-${field.name}`"
                  :field="field"
                  :model-value="getFieldValue(field)"
                  :error="fieldError(field)"
                  :session-id="form.sessionId"
                  :suggested-files="sessionFiles"
                  :suggested-directories="sessionDirectories"
                  @update:model-value="updateField(field, $event)"
                />
              </div>
            </section>

            <section v-if="visibleParameterGroups.length > 0" class="mt-8">
              <div class="mb-4">
                <h3 class="text-lg font-semibold text-slate-950">Parameters</h3>
                <p class="mt-1 text-sm text-slate-500">Parameter groups and widget behavior are rendered from the backend-produced Playground schema.</p>
              </div>

              <div class="space-y-5">
                <article
                  v-for="group in visibleParameterGroups"
                  :key="group.title"
                  class="rounded-2xl border border-slate-200 bg-white px-4 py-4"
                >
                  <div>
                    <h4 class="text-sm font-semibold text-slate-900">{{ group.title }}</h4>
                    <p v-if="group.description" class="mt-1 text-sm text-slate-500">{{ group.description }}</p>
                  </div>

                  <div class="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
                    <PlaygroundFieldRenderer
                      v-for="field in group.fields"
                      :key="`parameter-${field.name}`"
                      compact
                      :field="field"
                      :model-value="getFieldValue(field)"
                      :error="fieldError(field)"
                      :session-id="form.sessionId"
                      :suggested-files="sessionFiles"
                      :suggested-directories="sessionDirectories"
                      @update:model-value="updateField(field, $event)"
                    />
                  </div>
                </article>
              </div>
            </section>
            </fieldset>
          </div>

          <aside class="min-h-0 border-t border-slate-200 bg-slate-50 px-6 py-5 lg:border-l lg:border-t-0">
            <div class="flex h-full min-h-0 flex-col">
              <div class="flex items-center justify-between gap-3">
                <div>
                  <h3 class="text-lg font-semibold text-slate-950">Run</h3>
                  <p class="mt-1 text-sm text-slate-500">Execute this component with the manifest-backed form.</p>
                </div>
                <button
                  type="button"
                  class="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
                  :disabled="running || persistentRun.submitting.value"
                  @click="runPlayground"
                >
                  {{ running ? 'Running…' : 'Run Playground' }}
                </button>
              </div>

              <div class="mt-5 grid grid-cols-1 gap-3">
                <div class="rounded-2xl border border-slate-200 bg-white px-4 py-3">
                  <div class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Component</div>
                  <div class="mt-2 text-sm font-medium text-slate-900">{{ component.key }}</div>
                </div>
                <div class="rounded-2xl border border-slate-200 bg-white px-4 py-3">
                  <div class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Profile</div>
                  <div class="mt-2 text-sm font-medium text-slate-900">{{ form.profileId || 'n/a' }}</div>
                </div>
                <div class="rounded-2xl border border-slate-200 bg-white px-4 py-3">
                  <div class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Session</div>
                  <div class="mt-2 text-sm font-medium text-slate-900">{{ form.sessionId || 'Not selected' }}</div>
                </div>
              </div>

              <div v-if="running" class="mt-5 rounded-2xl border border-slate-200 bg-white px-4 py-4">
                <p class="text-sm text-slate-700">{{ persistentRun.trackingUnavailable.value ? 'Run tracking needs attention.' : 'Processing continues when you close this dialog.' }} Run {{ persistentRun.pending.value?.runId }} · {{ persistentRun.elapsed.value }}s</p>
                <button type="button" class="mt-3 mr-3 text-sm font-semibold text-indigo-700 underline" @click="persistentRun.refresh">Reconnect</button>
                <button v-if="result?.status === 'pending'" type="button" class="text-sm font-semibold text-indigo-700 underline" @click="persistentRun.cancel">Cancel queued run</button>
                <button v-if="!result && persistentRun.pending.value?.request" type="button" class="text-sm font-semibold text-indigo-700 underline" :disabled="persistentRun.submitting.value" @click="persistentRun.retry">Retry same request</button>
                <button v-if="persistentRun.trackingUnavailable.value" type="button" class="ml-3 text-sm text-indigo-700 underline" @click="persistentRun.dismiss">Dismiss tracking</button>
              </div>

              <div v-if="result" class="mt-5 min-h-0 flex-1 overflow-y-auto space-y-4">
                <div class="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                  <div class="flex flex-wrap items-center gap-2">
                    <span class="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-700">
                      Run {{ result.run_id || 'n/a' }}
                    </span>
                    <span v-if="result.component_version" class="text-xs text-slate-500">Component v{{ result.component_version }}</span>
                    <span
                      class="rounded-full px-2.5 py-1 text-[11px] font-medium"
                      :class="result.status === 'completed' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'"
                    >
                      {{ result.status || 'unknown' }}
                    </span>
                  </div>
                </div>

                <section v-if="summaryEntries.length" aria-label="Run summary" class="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                  <h4 class="text-sm font-semibold text-slate-900">Run summary</h4>
                  <dl class="mt-3 space-y-2 text-xs">
                    <div v-for="[key, value] in summaryEntries" :key="key" class="flex flex-wrap justify-between gap-x-3 gap-y-1">
                      <dt class="text-slate-500">{{ key.replaceAll('_', ' ') }}</dt>
                      <dd class="break-all font-medium text-slate-900">{{ value }}</dd>
                    </div>
                  </dl>
                </section>

                <PlaygroundArtifactPanel
                  v-if="result.result"
                  :run-id="result.run_id"
                  :result="result.result"
                  :schema="schema"
                />

                <div v-if="resultSchema.show_result_json" class="rounded-2xl border border-slate-200 bg-slate-950 p-4">
                  <div class="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Result JSON</div>
                  <pre class="overflow-x-auto text-[11px] leading-5 text-slate-100">{{ prettyResult }}</pre>
                </div>

                <div v-if="resultSchema.show_logs && runLogs.stdout" class="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                  <div class="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Stdout</div>
                  <pre class="max-h-48 overflow-auto rounded-xl bg-slate-950 p-3 text-[11px] leading-5 text-slate-100">{{ runLogs.stdout }}</pre>
                </div>

                <div v-if="resultSchema.show_logs && runLogs.stderr" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-4">
                  <div class="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-rose-600">Stderr</div>
                  <pre class="max-h-48 overflow-auto rounded-xl bg-slate-950 p-3 text-[11px] leading-5 text-rose-100">{{ runLogs.stderr }}</pre>
                </div>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import fileService from '@/services/file.service'
import hpcLinkService from '@/services/hpcLink.service'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import ReservedGpuAccess from '@/components/hpc/ReservedGpuAccess.vue'
import PlaygroundFieldRenderer from '@/components/tools/playground/PlaygroundFieldRenderer.vue'
import { useToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'
import { usePersistentPlaygroundRun } from '@/composables/usePersistentPlaygroundRun'
import {
  buildPlaygroundFieldIndex,
  buildPlaygroundFormState,
  deriveDirectories,
  flattenFormValues,
  flattenSessionFilePaths,
  formatPlaygroundLogs,
  getPlaygroundInputFields,
  getPlaygroundParameterGroups,
  getPlaygroundResultSchema,
  getPlaygroundSchema,
  isPlaygroundFieldVisible,
  isPlaygroundValueMissing,
  serializePlaygroundFieldValue
} from '@/utils/playgroundManifest'

const PlaygroundArtifactPanel = defineAsyncComponent(() => import('@/components/tools/playground/PlaygroundArtifactPanel.vue'))

const props = defineProps({
  show: {
    type: Boolean,
    default: false
  },
  component: {
    type: Object,
    default: null
  },
  sessions: {
    type: Array,
    default: () => []
  },
  loadingSessions: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['close'])

const { success, error: showError } = useToast()
const SESSION_RESOURCE_CACHE_TTL_MS = 30_000

const titleId = 'playground-runner-modal-title'
const dialogRef = ref(null)
const authStore = useAuthStore()
const persistentRun = usePersistentPlaygroundRun(() => authStore.user?.id || 'current', () => props.component?.key || '')
const running = persistentRun.active
const result = persistentRun.run
const localError = ref('')
const errorMessage = computed(() => localError.value || persistentRun.error.value)
const loadingSessionPaths = ref(false)
const sessionFiles = ref([])
const sessionDirectories = ref([])
const hpcPlaygroundAllocation = ref(null)
const hpcPlaygroundLoading = ref(false)
const hpcPlaygroundMessage = ref('Allocate HPC resources before running HDP Components remotely.')
const fieldErrors = ref({
  sessionId: '',
  inputs: {},
  parameters: {}
})

const form = reactive({
  sessionId: '',
  profileId: '',
  isSandbox: true,
  inputs: {},
  parameters: {}
})

const sessionResourceCache = new Map()
let sessionResourcesAbortController = null
let activeSessionLoadToken = 0
let previouslyFocusedElement = null

const schema = computed(() => getPlaygroundSchema(props.component))
const allFields = computed(() => buildPlaygroundFieldIndex(schema.value))
const profileOptions = computed(() => props.component?.profiles || [])
const componentTitle = computed(() => schema.value?.title || props.component?.name || props.component?.key || 'Playground Component')
const componentDescription = computed(() => schema.value?.description || props.component?.description || '')
const resultSchema = computed(() => getPlaygroundResultSchema(schema.value))
const combinedFormValues = computed(() => flattenFormValues(form))
const visibleInputFields = computed(() => (
  getPlaygroundInputFields(schema.value).filter((field) => isPlaygroundFieldVisible(field, combinedFormValues.value))
))
const visibleParameterGroups = computed(() => (
  getPlaygroundParameterGroups(schema.value)
    .map((group) => ({
      ...group,
      fields: group.fields.filter((field) => isPlaygroundFieldVisible(field, combinedFormValues.value))
    }))
    .filter((group) => group.fields.length > 0)
))
const prettyResult = computed(() => JSON.stringify(result.value?.result ?? {}, null, 2))
const summaryEntries = computed(() => Object.entries(result.value?.result?.summary || result.value?.result?.response?.summary || {})
  .filter(([, value]) => value !== null && ['string', 'number', 'boolean'].includes(typeof value)))
const runLogs = computed(() => formatPlaygroundLogs(result.value))

function emptyValueForField(field) {
  if (field?.widget === 'checkbox' || field?.type === 'boolean') {
    return false
  }
  return ''
}

function resetState() {
  cancelSessionResourceLoad()
  const defaults = buildPlaygroundFormState(schema.value)
  form.sessionId = ''
  form.profileId = profileOptions.value[0]?.profile_id || ''
  form.isSandbox = true
  form.inputs = defaults.inputs
  form.parameters = defaults.parameters
  localError.value = ''
  hpcPlaygroundAllocation.value = null
  hpcPlaygroundMessage.value = 'Allocate HPC resources before running HDP Components remotely.'
  fieldErrors.value = {
    sessionId: '',
    inputs: {},
    parameters: {}
  }
  sessionFiles.value = []
  sessionDirectories.value = []
}

async function requestPlaygroundHpcAllocation() {
  if (!form.sessionId) {
    localError.value = 'Select a session before allocating HPC resources.'
    return
  }
  hpcPlaygroundLoading.value = true
  localError.value = ''
  hpcPlaygroundMessage.value = 'Requesting Playground allocation...'
  try {
    const response = await hpcLinkService.requestAllocation({
      purpose: 'playground',
      session_id: Number.parseInt(form.sessionId, 10)
    })
    hpcPlaygroundAllocation.value = response.data?.allocation || null
    const status = hpcPlaygroundAllocation.value?.status || 'queued'
    hpcPlaygroundMessage.value = status === 'running'
      ? 'HPC-Link is active for this Playground session.'
      : `Allocation ${status}. The component run will use HPC-Link when the allocation becomes active.`
    success('HPC-Link Playground allocation requested.')
  } catch (requestError) {
    hpcPlaygroundMessage.value = requestError?.error?.message || requestError?.message || 'HPC-Link Playground allocation failed.'
    localError.value = hpcPlaygroundMessage.value
  } finally {
    hpcPlaygroundLoading.value = false
  }
}

function setPlaygroundReservedGpu(allocation) {
  if (allocation) {
    hpcPlaygroundAllocation.value = allocation
    hpcPlaygroundMessage.value = allocation.status === 'running'
      ? 'A reserved GPU is ready for this Playground session.'
      : 'HPC-Link is confirming the reserved GPU for this Playground session.'
  } else if (hpcPlaygroundAllocation.value?.reservation_id) {
    hpcPlaygroundAllocation.value = null
    hpcPlaygroundMessage.value = 'Allocate HPC resources before running HDP Components remotely.'
  }
}

function close() {
  emit('close')
}

function getFieldContainer(field) {
  return field.kind === 'input' ? form.inputs : form.parameters
}

function getFieldErrorContainer(field) {
  return field.kind === 'input' ? fieldErrors.value.inputs : fieldErrors.value.parameters
}

function getFieldValue(field) {
  return getFieldContainer(field)[field.name]
}

function clearField(field) {
  getFieldContainer(field)[field.name] = emptyValueForField(field)
  delete getFieldErrorContainer(field)[field.name]
}

function shouldActivateMutex(rawValue) {
  if (typeof rawValue === 'boolean') {
    return rawValue === true
  }
  return !isPlaygroundValueMissing(rawValue)
}

function updateField(field, value) {
  getFieldContainer(field)[field.name] = value
  delete getFieldErrorContainer(field)[field.name]

  const mutexTargets = Array.isArray(field?.constraints?.mutex_with) ? field.constraints.mutex_with : []
  if (!shouldActivateMutex(value) || mutexTargets.length === 0) {
    return
  }
  mutexTargets.forEach((targetName) => {
    const targetField = allFields.value[targetName]
    if (targetField) {
      clearField(targetField)
    }
  })
}

function fieldError(field) {
  return getFieldErrorContainer(field)[field.name] || ''
}

function getFocusableElements() {
  if (!dialogRef.value) {
    return []
  }
  return Array.from(
    dialogRef.value.querySelectorAll(
      'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'
    )
  ).filter((element) => !element.matches(':disabled'))
}

function focusInitialElement() {
  const [firstElement] = getFocusableElements()
  firstElement?.focus()
}

function cancelSessionResourceLoad() {
  activeSessionLoadToken += 1
  if (sessionResourcesAbortController) {
    sessionResourcesAbortController.abort()
    sessionResourcesAbortController = null
  }
  loadingSessionPaths.value = false
}

function restorePreviousFocus() {
  if (previouslyFocusedElement && typeof previouslyFocusedElement.focus === 'function') {
    previouslyFocusedElement.focus()
  }
  previouslyFocusedElement = null
}

function handleDocumentKeydown(event) {
  if (!props.show) {
    return
  }

  if (event.key === 'Escape') {
    event.preventDefault()
    close()
    return
  }

  if (event.key !== 'Tab') {
    return
  }

  const focusable = getFocusableElements()
  if (focusable.length === 0) {
    event.preventDefault()
    return
  }

  const firstElement = focusable[0]
  const lastElement = focusable[focusable.length - 1]
  const activeElement = document.activeElement

  if (event.shiftKey && activeElement === firstElement) {
    event.preventDefault()
    lastElement.focus()
    return
  }

  if (!event.shiftKey && activeElement === lastElement) {
    event.preventDefault()
    firstElement.focus()
  }
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
    sessionFiles.value = []
    sessionDirectories.value = []
    return
  }

  const cached = force ? null : getCachedSessionResources(normalizedId)
  if (cached) {
    sessionFiles.value = cached.files
    sessionDirectories.value = cached.directories
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
      suppressGlobalError: true
    })
    if (requestToken !== activeSessionLoadToken) {
      return
    }
    const files = flattenSessionFilePaths(response.data?.nodes || [])
    const directories = deriveDirectories(files)
    sessionResourceCache.set(normalizedId, { files, directories, cachedAt: Date.now() })
    sessionFiles.value = files
    sessionDirectories.value = directories
  } catch (requestError) {
    if (controller.signal.aborted || requestError?.code === 'ERR_CANCELED' || requestError?.name === 'CanceledError') {
      return
    }
    if (requestToken !== activeSessionLoadToken) {
      return
    }
    sessionFiles.value = []
    sessionDirectories.value = []
    showError(requestError?.error?.message || requestError?.message || 'Failed to load session paths.')
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
  if (!form.sessionId) {
    return
  }
  invalidateSessionResourceCache(form.sessionId)
  await loadSessionResources(form.sessionId, { force: true })
}

function formatDate(value) {
  if (!value) {
    return 'unknown'
  }
  try {
    return new Date(value).toLocaleString()
  } catch {
    return String(value)
  }
}

function collectVisibleFields() {
  return [
    ...visibleInputFields.value,
    ...visibleParameterGroups.value.flatMap((group) => group.fields)
  ]
}

function buildExecutionPayload() {
  const nextErrors = {
    sessionId: '',
    inputs: {},
    parameters: {}
  }

  if (!form.sessionId) {
    nextErrors.sessionId = 'Select a session before running the component.'
  }

  const visibleFields = collectVisibleFields()
  const inputs = {}
  const parameters = {}

  visibleFields.forEach((field) => {
    try {
      const serializedValue = serializePlaygroundFieldValue(field, getFieldValue(field))
      if (field.required && isPlaygroundValueMissing(serializedValue)) {
        nextErrors[field.kind === 'input' ? 'inputs' : 'parameters'][field.name] = `${field.label || field.name} is required.`
        return
      }
      if (!isPlaygroundValueMissing(serializedValue)) {
        if (field.kind === 'input') {
          inputs[field.name] = serializedValue
        } else {
          parameters[field.name] = serializedValue
        }
      }
    } catch (validationError) {
      nextErrors[field.kind === 'input' ? 'inputs' : 'parameters'][field.name] = validationError.message
    }
  })

  fieldErrors.value = nextErrors
  const hasErrors = Boolean(nextErrors.sessionId)
    || Object.keys(nextErrors.inputs).length > 0
    || Object.keys(nextErrors.parameters).length > 0

  if (hasErrors) {
    return null
  }

  return {
    component_key: props.component.key,
    profile_id: form.profileId || undefined,
    session_id: Number.parseInt(form.sessionId, 10),
    is_sandbox: form.isSandbox,
    inputs,
    parameters
  }
}

async function runPlayground() {
  const payload = buildExecutionPayload()
  if (!payload) {
    return
  }

  localError.value = ''
  await persistentRun.start(payload)
}

watch(() => result.value?.status, async (status, previous) => {
  if (!['completed', 'failed'].includes(status) || status === previous || !props.show) return
  if (status === 'completed') success('Playground run completed.')
  else showError(result.value?.error || 'Playground run failed. Review its results and logs.')
  const sessionId = result.value?.request?.session_id
  if (sessionId) {
    invalidateSessionResourceCache(sessionId)
    await loadSessionResources(sessionId, { force: true })
  }
})

watch(
  () => [props.show, props.component?.key],
  async ([isOpen]) => {
    if (isOpen) {
      resetState()
      await persistentRun.resume()
      const savedRequest = persistentRun.pending.value?.request || result.value?.request
      if (savedRequest) {
        form.sessionId = String(savedRequest.session_id)
        form.profileId = savedRequest.profile_id || form.profileId
        const savedValues = buildPlaygroundFormState(schema.value, savedRequest)
        form.inputs = savedValues.inputs
        form.parameters = savedValues.parameters
      }
      previouslyFocusedElement = document.activeElement
      document.addEventListener('keydown', handleDocumentKeydown)
      await nextTick()
      focusInitialElement()
      return
    }

    cancelSessionResourceLoad()
    persistentRun.pause()
    document.removeEventListener('keydown', handleDocumentKeydown)
    restorePreviousFocus()
  },
  { immediate: true }
)

watch(
  () => form.sessionId,
  async (sessionId) => {
    if (!props.show) {
      return
    }
    await loadSessionResources(sessionId)
  }
)

watch(profileOptions, (profiles) => {
  if (!profiles.length) {
    form.profileId = ''
    return
  }
  if (!profiles.some((profile) => profile.profile_id === form.profileId)) {
    form.profileId = profiles[0].profile_id
  }
}, { immediate: true })

onBeforeUnmount(() => {
  cancelSessionResourceLoad()
  document.removeEventListener('keydown', handleDocumentKeydown)
})
</script>
