<template>
  <div class="min-h-screen bg-gray-50">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">

      <div class="bg-white shadow rounded-lg">
        <div class="px-6 py-4 border-b border-gray-200 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 class="text-lg font-medium text-gray-900">Your Sessions</h2>
            <p class="text-sm text-gray-500 mt-1">A session groups your uploaded files, descriptions and processing choices. Resume a session to continue where you left off.</p>
          </div>
          <div class="inline-flex rounded-lg border border-gray-200 bg-gray-50 p-1">
            <button
              v-for="scope in scopes"
              :key="scope.value"
              type="button"
              class="px-3 py-1.5 text-xs font-medium rounded-md transition-colors"
              :class="currentScope === scope.value ? 'bg-white text-indigo-700 shadow-sm' : 'text-gray-600 hover:text-gray-900'"
              @click="changeScope(scope.value)"
            >
              {{ scope.label }}
            </button>
          </div>
        </div>

        <div v-if="loading" class="p-6 text-center">
          <LoadingSpinner text="Loading sessions…" />
        </div>

        <div v-else-if="loadError" role="alert" class="p-6 text-center">
          <p class="text-red-700">{{ loadError }}</p>
          <button type="button" class="mt-3 rounded-md border border-indigo-200 px-4 py-2 text-sm font-medium text-indigo-700" @click="loadSessions">Try again</button>
        </div>

        <div v-else-if="sessions.length === 0" class="p-6 text-center">
          <h3 class="text-lg font-semibold text-gray-900">{{ currentScope === 'all' ? 'Start your first session' : 'No sessions in this workspace' }}</h3>
          <p class="mx-auto mt-2 max-w-xl text-sm text-gray-600">Upload a self-contained model to try the workflow, or a ZIP and metadata spreadsheet for a batch. You will review everything before processing starts.</p>
          <router-link to="/workflow/upload" class="mt-4 inline-flex rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700">Upload files</router-link>
          <button v-if="currentScope !== 'all'" type="button" class="ml-3 mt-4 text-sm font-medium text-indigo-700 underline" @click="changeScope('all')">Show all sessions</button>
        </div>

        <ul v-else class="divide-y divide-gray-200">
          <li v-for="session in sessions" :key="session.id" class="px-6 py-4 hover:bg-gray-50">
            <div class="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
              <div>
                <p class="text-sm font-medium text-gray-900">Session #{{ session.id }}</p>
                <p class="text-sm text-gray-500">{{ formatDate(session.created_at) }}</p>
                <p class="text-xs text-gray-400 mt-1">{{ session.file_count }} files</p>
                <div class="mt-2 flex flex-wrap gap-2">
                  <span class="px-2.5 py-1 text-[11px] font-medium rounded-full bg-gray-100 text-gray-700">
                    {{ session.workspace?.type === 'institution' ? 'Institution workspace' : 'Personal workspace' }}
                  </span>
                  <span
                    v-if="session.workspace?.institution?.name"
                    class="px-2.5 py-1 text-[11px] font-medium rounded-full bg-indigo-100 text-indigo-700"
                  >
                    {{ session.workspace.institution.name }}
                  </span>
                  <span class="px-2.5 py-1 text-[11px] font-medium rounded-full bg-amber-100 text-amber-700">
                    {{ formatCredentialSource(session.publishing_context?.effective_credential_source) }}
                  </span>
                  <span class="px-2.5 py-1 text-[11px] font-medium rounded-full bg-emerald-100 text-emerald-700">
                    {{ session.publishing_context?.default_zenodo_environment || 'sandbox' }}
                  </span>
                  <span
                    v-if="session.access_mode === 'explorer_only'"
                    class="px-2.5 py-1 text-[11px] font-medium rounded-full bg-rose-100 text-rose-700"
                  >
                    Explorer-only
                  </span>
                  <span
                    v-if="session.origin_type === 'hdpc_import'"
                    class="px-2.5 py-1 text-[11px] font-medium rounded-full bg-sky-100 text-sky-700"
                  >
                    Imported .hdpc
                  </span>
                </div>
                <p
                  v-if="session.access_mode === 'explorer_only'"
                  class="mt-2 text-xs font-medium text-rose-700"
                >
                  Shared export imports are read-only and cannot resume workflow or publishing actions.
                </p>
                <p
                  v-if="session.workflow_hint?.requires_msf_repair"
                  class="mt-2 text-xs font-medium text-amber-700"
                >
                  Guided MSF repair required before local scan can start.
                </p>
                <p
                  v-if="session.workflow_hint?.requires_msf_repair && session.workflow_hint?.target_directory"
                  class="mt-1 text-[11px] font-mono text-gray-500 break-all"
                >
                  {{ session.workflow_hint.target_directory }}
                </p>
              </div>
              <div class="flex flex-wrap items-center gap-3 xl:justify-end">
                <span
                  :class="[
                    'px-3 py-1 text-xs font-medium rounded-full',
                    statusClass(session.status)
                  ]"
                >
                  {{ session.status }}
                </span>

                <button
                  v-if="session.workflow_hint?.requires_msf_repair"
                  @click="resumeMsfRepair(session.id)"
                  class="px-3 py-1 text-xs font-medium rounded-full border text-amber-700 border-amber-200 hover:bg-amber-50"
                >
                  Resume MSF Repair
                </button>

                <button
                  v-else-if="session.workflow_hint?.can_resume_workflow"
                  @click="resumeWorkflow(session)"
                  class="px-3 py-1 text-xs font-medium rounded-full border text-indigo-700 border-indigo-200 hover:bg-indigo-50"
                >
                  {{ session.workflow_hint?.resume_label || 'Resume Workflow' }}
                </button>

                <button
                  v-if="session.permissions?.can_manage"
                  @click="openGovernanceDrawer(session)"
                  class="px-3 py-1 text-xs font-medium rounded-full border text-slate-700 border-slate-200 hover:bg-slate-50"
                >
                  Manage Session
                </button>

                <button
                  v-if="canDownloadSharedHdpc(session)"
                  @click="handleDownloadSharedHdpc(session.id)"
                  class="px-3 py-1 text-xs font-medium rounded-full
                         border text-emerald-700 border-emerald-200 hover:bg-emerald-50"
                  :title="session.shared_hdpc_download_policy?.message || 'Download sanitized shared export'"
                >
                  Download Shared Export
                </button>

                <button
                  @click="handleDownloadHdpc(session.id)"
                  :disabled="!canDownloadHdpc(session)"
                  class="px-3 py-1 text-xs font-medium rounded-full
                         border
                         disabled:opacity-50 disabled:cursor-not-allowed
                         disabled:text-gray-400 disabled:border-gray-200 disabled:bg-gray-50
                         text-indigo-600 border-indigo-200 hover:bg-indigo-50"
                  :title="canDownloadHdpc(session) ? 'Download .hdpc file' : 'Only the session owner can download the raw .hdpc file'"
                >
                  Download .hdpc
                </button>

                <button
                  @click="handleDownloadMetadata(session.id)"
                  :disabled="!isDownloadable(session.status)"
                  class="px-3 py-1 text-xs font-medium rounded-full
                         border
                         disabled:opacity-50 disabled:cursor-not-allowed
                         disabled:text-gray-400 disabled:border-gray-200 disabled:bg-gray-50
                         text-blue-600 border-blue-200 hover:bg-blue-50"
                  :title="isDownloadable(session.status) ? 'Download Zenodo metadata as JSON' : 'Metadata not available for download (session failed or is pending)'"
                >
                  Download JSON
                </button>

              </div>
            </div>
          </li>
        </ul>
      </div>
    </div>
    <SessionGovernanceDrawer
      :open="governanceOpen"
      :session="selectedGovernanceSession"
      @close="closeGovernanceDrawer"
      @updated="handleGovernanceUpdated"
    />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import SessionGovernanceDrawer from '@/components/dashboard/SessionGovernanceDrawer.vue'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import { useWorkflowStore } from '@/stores/workflow'
import fileService from '@/services/file.service'
import { useToast } from '@/composables/useToast'
import { buildWorkflowResumeLocation, isDownloadableSessionState, sessionStateClass } from '@/utils/workflowState'

const router = useRouter()
const workflowStore = useWorkflowStore()
const toast = useToast()

const sessions = ref([])
const loading = ref(true)
const loadError = ref('')
const currentScope = ref('all')
const governanceOpen = ref(false)
const selectedGovernanceSession = ref(null)
const scopes = [
  { label: 'All', value: 'all' },
  { label: 'Personal', value: 'personal' },
  { label: 'Institution', value: 'institution' },
]

const formatDate = (dateString) => {
  if (!dateString) return 'N/A'
  const date = new Date(dateString)
  return date.toLocaleString()
}

const isDownloadable = (status) => {
  return isDownloadableSessionState(status)
}

const canDownloadHdpc = (session) => {
  return Boolean(session?.permissions?.can_download_hdpc) && isDownloadable(session?.status)
}

const canDownloadSharedHdpc = (session) => {
  return Boolean(session?.permissions?.can_download_shared_hdpc) && isDownloadable(session?.status)
}

const statusClass = (status) => {
  return sessionStateClass(status)
}

const formatCredentialSource = (source) => {
  if (!source) return 'System credentials'
  return `${source.charAt(0).toUpperCase()}${source.slice(1)} credentials`
}

const loadSessions = async () => {
  loading.value = true
  loadError.value = ''
  try {
    const response = await fileService.listSessions({ scope: currentScope.value })
    sessions.value = response.data.sessions || []
  } catch (err) {
    console.error('Failed to load sessions:', err)
    loadError.value = 'Could not load your sessions. Check your connection and try again.'
  } finally {
    loading.value = false
  }
}

const changeScope = async (scope) => {
  currentScope.value = scope
  loading.value = true
  await loadSessions()
}

// Helper function for blob downloading
const downloadBlob = (blob, filename) => {
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.URL.revokeObjectURL(url)
}

const handleDownloadHdpc = async (sessionId) => {
  try {
    const blob = await fileService.downloadHdpc(sessionId)
    downloadBlob(blob, `session_${sessionId}.hdpc`)
    toast.success('Downloaded .hdpc file')
  } catch (err) {
    console.error('Failed to download .hdpc:', err)
    toast.error(err.error || 'Failed to download .hdpc file')
  }
}

const handleDownloadSharedHdpc = async (sessionId) => {
  try {
    const blob = await fileService.downloadSharedHdpc(sessionId)
    downloadBlob(blob, `session_${sessionId}_shared.hdpc`)
    toast.success('Downloaded shared export')
  } catch (err) {
    console.error('Failed to download shared .hdpc export:', err)
    toast.error(err.error || 'Failed to download shared export')
  }
}

const openGovernanceDrawer = (session) => {
  selectedGovernanceSession.value = session
  governanceOpen.value = true
}

const closeGovernanceDrawer = () => {
  governanceOpen.value = false
  selectedGovernanceSession.value = null
}

const handleGovernanceUpdated = async (updatedSession) => {
  if (!updatedSession) return
  selectedGovernanceSession.value = updatedSession
  governanceOpen.value = false
  await loadSessions()
}

const handleDownloadMetadata = async (sessionId) => {
  try {
    const blob = await fileService.downloadZenodoMetadata(sessionId)
    downloadBlob(blob, `session_${sessionId}_zenodo_metadata.json`)
    toast.success('Downloaded Zenodo metadata')
  } catch (err) {
    console.error('Failed to download Zenodo metadata:', err)
    toast.error(err.error || 'Failed to download metadata')
  }
}

const resumeMsfRepair = (sessionId) => {
  workflowStore.setSessionId(sessionId)
  workflowStore.setBatchMode(true)
  workflowStore.goToStep(2)
  router.push({ path: '/workflow/msf-analysis', query: { sessionId: String(sessionId), resume: 'repair' } })
}

const resumeWorkflow = (session) => {
  const hint = session?.workflow_hint || {}
  router.push(buildWorkflowResumeLocation(session?.id, hint))
}

onMounted(() => {
  loadSessions()
})
</script>
