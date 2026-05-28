<template>
  <div v-if="open" class="fixed inset-0 z-[110]">
    <div class="absolute inset-0 bg-slate-900/35" @click="emit('close')"></div>
    <aside class="absolute right-0 top-0 flex h-full w-full max-w-2xl flex-col overflow-hidden bg-white shadow-2xl">
      <header class="flex items-start justify-between gap-4 border-b border-slate-200 px-6 py-5">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.22em] text-indigo-700">Session Governance</p>
          <h2 class="mt-2 text-2xl font-semibold text-slate-900">Session #{{ sessionId }}</h2>
          <p class="mt-2 text-sm text-slate-500">
            Update workspace ownership and publishing defaults without leaving the current view.
          </p>
        </div>
        <button
          type="button"
          class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          @click="emit('close')"
        >
          Close
        </button>
      </header>

      <div class="flex-1 overflow-y-auto px-6 py-6">
        <div v-if="loading" class="text-sm text-slate-500">Loading session governance…</div>
        <div v-else-if="loadError" class="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
          {{ loadError }}
        </div>
        <div v-else-if="details" class="space-y-6">
          <section class="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div class="flex flex-wrap gap-2">
              <span class="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-700">
                {{ currentSession?.workspace?.type === 'institution' ? 'Institution workspace' : 'Personal workspace' }}
              </span>
              <span v-if="currentSession?.workspace?.institution?.name" class="rounded-full border border-indigo-200 bg-white px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-indigo-700">
                {{ currentSession.workspace.institution.name }}
              </span>
              <span class="rounded-full border border-amber-200 bg-white px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-amber-700">
                {{ currentSession?.publishing_context?.effective_credential_source || 'system' }}
              </span>
              <span
                v-if="currentSession?.access_mode === 'explorer_only'"
                class="rounded-full border border-rose-200 bg-white px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-rose-700"
              >
                Explorer-only
              </span>
              <span
                v-if="currentSession?.origin_type === 'hdpc_import'"
                class="rounded-full border border-sky-200 bg-white px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-sky-700"
              >
                Imported .hdpc
              </span>
            </div>
            <p class="mt-3 text-sm text-slate-600">
              {{ hdpcDownloadPolicy.message }}
            </p>
            <p class="mt-1 text-xs text-slate-500">
              {{ hdpcDownloadPolicy.can_download ? 'You can download the raw .hdpc for this session.' : 'Raw .hdpc download is not available for your role.' }}
            </p>
            <p class="mt-3 text-sm text-slate-600">
              {{ sharedHdpcDownloadPolicy.message }}
            </p>
            <p class="mt-1 text-xs text-slate-500">
              {{ sharedHdpcDownloadPolicy.can_download ? 'You can download the sanitized shared export for this session.' : 'Shared export download is not available for this session or your role.' }}
            </p>
            <p
              v-if="currentSession?.access_mode === 'explorer_only'"
              class="mt-3 text-xs font-medium text-rose-700"
            >
              Imported shared exports stay read-only. Governance settings remain visible, but workflow and publishing mutations are blocked.
            </p>
          </section>

          <section class="rounded-2xl border border-slate-200 p-5">
            <h3 class="text-sm font-semibold text-slate-900">Workspace Settings</h3>
            <div class="mt-4 inline-flex rounded-xl border border-slate-200 bg-slate-50 p-1">
              <button
                type="button"
                class="rounded-lg px-4 py-2 text-sm font-medium"
                :class="form.workspaceType === 'personal' ? 'bg-white text-indigo-700 shadow-sm' : 'text-slate-600 hover:text-slate-900'"
                @click="handleWorkspaceTypeChange('personal')"
              >
                Personal
              </button>
              <button
                type="button"
                class="rounded-lg px-4 py-2 text-sm font-medium"
                :class="form.workspaceType === 'institution' ? 'bg-white text-indigo-700 shadow-sm' : 'text-slate-600 hover:text-slate-900'"
                @click="handleWorkspaceTypeChange('institution')"
              >
                Institution
              </button>
            </div>

            <div class="mt-4 grid gap-4 md:grid-cols-2">
              <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Institution
                <select
                  :value="form.institutionId"
                  :disabled="form.workspaceType !== 'institution'"
                  class="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900 disabled:bg-slate-100"
                  @change="handleInstitutionChange($event.target.value)"
                >
                  <option value="">Select institution</option>
                  <option v-for="institution in institutionCandidates" :key="institution.id" :value="String(institution.id)">
                    {{ institution.name }}
                  </option>
                </select>
              </label>

              <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Sharing Scope
                <select
                  v-model="form.sharingScope"
                  :disabled="form.workspaceType !== 'institution'"
                  class="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900 disabled:bg-slate-100"
                >
                  <option v-for="item in sharingScopeOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
                </select>
              </label>

              <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Credential Preference
                <select
                  v-model="form.credentialPreference"
                  :disabled="form.workspaceType !== 'institution'"
                  class="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900 disabled:bg-slate-100"
                >
                  <option v-for="item in credentialPreferenceOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
                </select>
              </label>

              <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Default Environment
                <select
                  v-model="form.defaultZenodoEnvironment"
                  class="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900"
                >
                  <option v-for="item in environmentOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
                </select>
              </label>

              <label class="text-xs font-semibold uppercase tracking-wide text-slate-500 md:col-span-2">
                Publishing User
                <select
                  v-model="form.publishingUserId"
                  class="mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900"
                >
                  <option v-for="candidate in publishingUserCandidates" :key="candidate.id" :value="String(candidate.id)">
                    {{ candidate.full_name || candidate.display_name || candidate.email }}{{ candidate.institution_role ? ` (${candidate.institution_role})` : '' }}
                  </option>
                </select>
              </label>
            </div>

            <label class="mt-4 flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
              <input
                v-model="form.useInstitutionDefaultCommunities"
                :disabled="form.workspaceType !== 'institution'"
                type="checkbox"
                class="mt-0.5 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 disabled:opacity-50"
              />
              <span>Append the institution’s default communities when saving or generating Zenodo metadata.</span>
            </label>
          </section>

          <section v-if="currentSession?.permissions?.can_manage" class="rounded-2xl border border-slate-200 p-5">
            <div class="flex items-center justify-between gap-3">
              <h3 class="text-sm font-semibold text-slate-900">Recent Session Audit</h3>
              <button
                type="button"
                class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                :disabled="auditLoading"
                @click="loadAuditEvents"
              >
                {{ auditLoading ? 'Refreshing…' : 'Refresh' }}
              </button>
            </div>
            <div v-if="auditLoading" class="mt-4 text-sm text-slate-500">Loading audit history…</div>
            <div v-else-if="!auditEvents.length" class="mt-4 text-sm text-slate-500">No session audit events recorded yet.</div>
            <div v-else class="mt-4 space-y-3">
              <article
                v-for="event in auditEvents"
                :key="event.id"
                class="rounded-xl border border-slate-200 bg-slate-50 p-3"
              >
                <div class="flex items-center justify-between gap-2">
                  <p class="text-sm font-semibold text-slate-900">{{ event.event_type }}</p>
                  <p class="text-xs text-slate-500">{{ formatTimestamp(event.created_at) }}</p>
                </div>
                <p class="mt-1 text-xs text-slate-500">
                  {{ event.actor?.email || 'System' }} · {{ event.entity_type }}{{ event.entity_id ? ` #${event.entity_id}` : '' }}
                </p>
              </article>
            </div>
          </section>
        </div>
      </div>

      <footer class="flex items-center justify-end gap-3 border-t border-slate-200 px-6 py-4">
        <button
          type="button"
          class="rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          @click="emit('close')"
        >
          Cancel
        </button>
        <button
          type="button"
          class="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="saving || !currentSession?.permissions?.can_manage"
          @click="saveWorkspace"
        >
          {{ saving ? 'Saving…' : 'Save changes' }}
        </button>
      </footer>
    </aside>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'

import { useToast } from '@/composables/useToast'
import fileService from '@/services/file.service'

const props = defineProps({
  open: {
    type: Boolean,
    default: false,
  },
  session: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['close', 'updated'])

const toast = useToast()
const loading = ref(false)
const saving = ref(false)
const auditLoading = ref(false)
const loadError = ref('')
const details = ref(null)
const auditEvents = ref([])
const hydrating = ref(false)

const form = reactive({
  workspaceType: 'personal',
  institutionId: '',
  sharingScope: 'private',
  credentialPreference: 'user',
  publishingUserId: '',
  defaultZenodoEnvironment: 'sandbox',
  useInstitutionDefaultCommunities: false,
})

const sessionId = computed(() => Number(props.session?.id || 0))
const currentSession = computed(() => details.value?.session || props.session || null)
const institutionCandidates = computed(() => details.value?.target_institutions || [])
const sharingScopeOptions = computed(() => details.value?.options?.sharing_scopes || [])
const credentialPreferenceOptions = computed(() => details.value?.options?.credential_preferences || [])
const environmentOptions = computed(() => details.value?.options?.default_zenodo_environments || [])
const hdpcDownloadPolicy = computed(() => details.value?.hdpc_download_policy || {
  scope: 'owner_only',
  can_download: false,
  message: 'Only the session owner can download raw .hdpc files.',
})
const sharedHdpcDownloadPolicy = computed(() => details.value?.shared_hdpc_download_policy || {
  scope: 'institution_reader_plus',
  enabled: false,
  can_download: false,
  message: 'Institution readers and above can download the sanitized shared .hdpc export for institution-shared sessions.',
  artifact_kind: 'sanitized_shared',
})
const publishingUserCandidates = computed(() => {
  if (form.workspaceType !== 'institution') {
    const owner = details.value?.owner_user
    return owner ? [{ ...owner, is_current: String(owner.id) === String(form.publishingUserId) }] : []
  }
  return details.value?.publishing_user_candidates || []
})

function ensurePublishingUserSelection() {
  const candidates = publishingUserCandidates.value || []
  if (!candidates.length) {
    form.publishingUserId = ''
    return
  }

  if (candidates.some((candidate) => String(candidate.id) === String(form.publishingUserId) && candidate.eligible !== false)) {
    return
  }

  const preferredCandidate = candidates.find((candidate) => candidate.is_current && candidate.eligible !== false)
    || candidates.find((candidate) => candidate.eligible !== false)
    || candidates[0]
  form.publishingUserId = preferredCandidate ? String(preferredCandidate.id) : ''
}

function formatTimestamp(value) {
  if (!value) return 'Unknown'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString()
}

function syncFormFromDetails() {
  hydrating.value = true
  const currentWorkspace = details.value?.current_workspace || {}
  const previewInstitutionId = details.value?.preview_institution_id
  const effectiveInstitutionId = previewInstitutionId || currentWorkspace.institution_id
  form.workspaceType = effectiveInstitutionId ? 'institution' : 'personal'
  form.institutionId = effectiveInstitutionId ? String(effectiveInstitutionId) : ''
  form.sharingScope = currentWorkspace.sharing_scope || 'private'
  form.credentialPreference = currentWorkspace.credential_preference || (form.workspaceType === 'institution' ? 'institution' : 'user')
  form.defaultZenodoEnvironment = currentWorkspace.default_zenodo_environment || 'sandbox'
  form.useInstitutionDefaultCommunities = Boolean(currentWorkspace.use_institution_default_communities)
  form.publishingUserId = currentWorkspace.publishing_user_id ? String(currentWorkspace.publishing_user_id) : ''
  ensurePublishingUserSelection()
  hydrating.value = false
}

async function loadWorkspace(previewInstitutionId = null) {
  if (!sessionId.value) return
  loading.value = true
  loadError.value = ''
  try {
    const params = {}
    if (previewInstitutionId !== null && previewInstitutionId !== undefined && previewInstitutionId !== '') {
      params.institution_id = previewInstitutionId
    }
    const response = await fileService.getSessionWorkspace(sessionId.value, params)
    details.value = response.data
    syncFormFromDetails()
  } catch (error) {
    loadError.value = error?.error?.message || error?.message || 'Failed to load session governance.'
  } finally {
    loading.value = false
  }
}

async function loadAuditEvents() {
  if (!sessionId.value || !currentSession.value?.permissions?.can_manage) {
    auditEvents.value = []
    return
  }
  auditLoading.value = true
  try {
    const response = await fileService.getSessionAuditEvents(sessionId.value, { per_page: 10 })
    auditEvents.value = response.data?.audit_events || []
  } catch (error) {
    auditEvents.value = []
    toast.error(error?.error?.message || error?.message || 'Failed to load session audit history')
  } finally {
    auditLoading.value = false
  }
}

async function handleWorkspaceTypeChange(nextType) {
  form.workspaceType = nextType
  if (nextType === 'personal') {
    form.institutionId = ''
    form.sharingScope = 'private'
    form.credentialPreference = 'user'
    form.useInstitutionDefaultCommunities = false
    form.publishingUserId = details.value?.owner_user?.id ? String(details.value.owner_user.id) : form.publishingUserId
    return
  }

  const nextInstitutionId = form.institutionId || String(institutionCandidates.value.find((item) => item.eligible !== false)?.id || '')
  form.institutionId = nextInstitutionId
  if (nextInstitutionId) {
    await loadWorkspace(nextInstitutionId)
    form.workspaceType = 'institution'
  }
}

async function handleInstitutionChange(value) {
  form.institutionId = value
  if (hydrating.value || form.workspaceType !== 'institution') return
  if (!value) {
    form.publishingUserId = details.value?.owner_user?.id ? String(details.value.owner_user.id) : ''
    return
  }
  await loadWorkspace(value)
  form.workspaceType = 'institution'
  ensurePublishingUserSelection()
}

async function saveWorkspace() {
  if (!sessionId.value || !currentSession.value?.permissions?.can_manage) return
  saving.value = true
  try {
    const response = await fileService.updateSessionWorkspace(sessionId.value, {
      institution_id: form.workspaceType === 'institution' && form.institutionId ? Number(form.institutionId) : null,
      sharing_scope: form.workspaceType === 'institution' ? form.sharingScope : 'private',
      credential_preference: form.workspaceType === 'institution' ? form.credentialPreference : 'user',
      publishing_user_id: Number(form.publishingUserId || details.value?.owner_user?.id || currentSession.value?.owner_user_id || 0),
      default_zenodo_environment: form.defaultZenodoEnvironment,
      use_institution_default_communities: form.workspaceType === 'institution' ? form.useInstitutionDefaultCommunities : false,
    })
    emit('updated', response.data?.session || null)
    toast.success('Session workspace updated')
    await loadWorkspace()
    await loadAuditEvents()
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to update session workspace')
  } finally {
    saving.value = false
  }
}

watch(
  () => [props.open, sessionId.value],
  async ([isOpen, nextSessionId]) => {
    if (!isOpen || !nextSessionId) return
    await loadWorkspace()
    await loadAuditEvents()
  },
  { immediate: true },
)
</script>
