<template>
  <div class="min-h-screen bg-gray-50 py-8">
    <div class="max-w-6xl mx-auto px-4">
      <!-- Header -->
      <div class="mb-8">
        <h1 class="text-3xl font-bold text-gray-900">Review Files</h1>
        <p class="mt-2 text-gray-600">Review your uploaded files and select the models you want to process.</p>
      </div>

      <!-- Progress Indicator -->
      <StepIndicator :batch-mode="workflowStore.isBatchMode" :current-step="3" />

      <div class="bg-white shadow rounded-lg p-6">
        <div class="mb-5 rounded-xl border border-indigo-100 bg-indigo-50 px-4 py-4">
          <p class="text-sm font-semibold text-indigo-950">Record creation happens later</p>
          <p class="mt-1 text-sm text-indigo-900">
            Upload only registered the scanned bundles for this session. The files you choose here determine which bundles create or reuse local records when you confirm the submit step.
          </p>
        </div>

        <div
          v-if="workflowStore.sessionId"
          data-testid="cloud-downloads-panel"
          class="mb-5 rounded-xl border border-slate-200 bg-slate-50 px-4 py-4"
        >
          <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <p class="text-sm font-semibold text-slate-900">Cloud Storage downloads</p>
              <p v-if="cloudDownloadsLoading" class="mt-1 text-sm text-slate-600">Checking Cloud Storage mirrors...</p>
              <p v-else-if="cloudDownloadsError" class="mt-1 text-sm text-rose-700">{{ cloudDownloadsError }}</p>
              <p v-else-if="cloudDownloads?.reason" data-testid="cloud-downloads-reason" class="mt-1 text-sm text-slate-600">
                {{ cloudDownloads.reason }}
              </p>
              <p v-else class="mt-1 text-sm text-slate-600">
                {{ cloudDownloads?.available ? 'Mirrored upload artifacts are available from Cloud Storage.' : 'No mirrored upload artifacts are currently downloadable.' }}
              </p>
            </div>
            <button
              type="button"
              class="px-3 py-1.5 text-xs font-medium text-slate-700 border border-slate-300 rounded-md hover:bg-white disabled:opacity-50"
              :disabled="cloudDownloadsLoading"
              @click="fetchCloudDownloads"
            >
              Refresh
            </button>
          </div>

          <div v-if="cloudDownloads?.items?.length" class="mt-4 space-y-2">
            <div
              v-for="item in cloudDownloads.items"
              :key="item.id"
              data-testid="cloud-download-item"
              class="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white px-3 py-3 sm:flex-row sm:items-center sm:justify-between"
            >
              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-2">
                  <span class="text-sm font-medium text-slate-900">{{ item.original_filename }}</span>
                  <span class="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">{{ item.label }}</span>
                  <span
                    class="rounded-full px-2 py-0.5 text-xs font-semibold uppercase"
                    :class="item.can_download ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'"
                  >
                    {{ item.can_download ? 'Available' : 'Unavailable' }}
                  </span>
                </div>
                <p class="mt-1 text-xs text-slate-500">
                  {{ item.availability_message || item.storage_provider || 'Cloud mirror status checked.' }}
                </p>
              </div>
              <button
                type="button"
                data-testid="cloud-download-button"
                class="px-3 py-1.5 text-xs font-semibold text-indigo-700 border border-indigo-200 rounded-md hover:bg-indigo-50 disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="!item.can_download || downloadingMirrorId === item.id"
                @click="downloadCloudArtifact(item)"
              >
                {{ downloadingMirrorId === item.id ? 'Opening...' : 'Download' }}
              </button>
            </div>
          </div>
        </div>

        <div class="flex flex-col gap-3 mb-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 class="text-xl font-semibold text-gray-900">Found Files</h2>
            <p
              v-if="workflowStore.isBatchMode"
              class="mt-1 text-sm text-amber-700"
            >
              Select at least one model to continue. Expand a file group to check its textures and supporting files.
            </p>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <button
              v-if="!loading"
              type="button"
              @click="selectAllVisibleFiles"
              :disabled="visibleUploadedFiles.length === 0"
              class="text-sm font-medium text-indigo-700 border border-indigo-200 rounded-lg px-3 py-2 hover:bg-indigo-50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Select all scanned bundles
            </button>
            <button
              v-if="!loading"
              type="button"
              @click="clearSelection"
              :disabled="workflowStore.selectedFiles.length === 0"
              class="text-sm font-medium text-gray-700 border border-gray-300 rounded-lg px-3 py-2 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Clear selection
            </button>
            <button
              v-if="!loading"
              @click="fetchFiles"
              class="text-sm text-indigo-600 hover:text-indigo-800 flex items-center"
            >
              <svg class="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              Refresh
            </button>
          </div>
        </div>
        <p class="mb-4 text-xs text-gray-500">
          Validation tag (<strong>VALID</strong>) shows file integrity checks. Upload tag (<strong>UPLOADED</strong>) shows ingestion progress.
        </p>

        <!-- Loading State -->
        <div v-if="loading" class="text-center py-12">
          <div class="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600 mb-4"></div>
          <p class="text-gray-500">Retrieving session files...</p>
        </div>

        <div v-if="filesError && !loading" role="alert" class="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
          <p>{{ filesError }} {{ visibleUploadedFiles.length ? 'The previous list and your selection are retained.' : 'The file list is unavailable.' }}</p>
          <button type="button" class="mt-2 font-medium underline" @click="fetchFiles">Try loading files again</button>
        </div>

        <div v-if="!loading && !filesError && visibleUploadedFiles.length === 0" class="text-center py-12 text-gray-500 bg-gray-50 rounded-lg border-2 border-dashed border-gray-200">
          <svg class="mx-auto h-12 w-12 text-gray-400 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 13h6m-3-3v6m-9 1V7a2 2 0 012-2h6l2 2h6a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
          </svg>
          <p>No bundles found in the scanned directory.</p>
        </div>

        <div v-if="!loading && visibleUploadedFiles.length" class="space-y-6">
          <div
            v-for="rootFile in visibleUploadedFiles"
            :key="rootFile.file_id || rootFile.name"
            class="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden"
          >
            <!-- Bundle Header -->
            <div class="px-6 py-4 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
              <div class="flex items-center space-x-4">
                <input
                  type="checkbox"
                  :id="`check-${rootFile.file_id}`"
                  :checked="isSelected(rootFile)"
                  @change="toggleSelection(rootFile)"
                  class="h-5 w-5 text-indigo-600 rounded border-gray-300 focus:ring-indigo-500"
                />
                <div>
                  <h3 class="text-lg font-bold text-gray-900 flex items-center">
                    <span class="mr-2">📦</span>
                    {{ rootFile.name || rootFile.filename }}
                  </h3>
                  <p class="text-xs text-gray-500 truncate max-w-md">{{ rootFile.relative_path }}</p>
                </div>
              </div>

              <div class="flex items-center space-x-2">
                <span
                  v-if="rootFile.validation_status"
                  @click="handleShowDetails(rootFile, hasAssets(rootFile) ? 'assets' : 'overview')"
                  :class="[
                    'px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wider cursor-pointer hover:opacity-80',
                    statusClass(rootFile.validation_status)
                  ]"
                  title="Validation status"
                >
                  VALID: {{ rootFile.validation_status }}
                </span>
                <span
                  v-if="rootFile.upload_status"
                  :class="[
                    'px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wider',
                    uploadStatusClass(rootFile.upload_status)
                  ]"
                  title="Upload status"
                >
                  UPLOAD: {{ rootFile.upload_status }}
                </span>
                <span
                  v-if="!rootFile.validation_status && !rootFile.upload_status"
                  @click="handleShowDetails(rootFile, hasAssets(rootFile) ? 'assets' : 'overview')"
                  :class="[
                    'px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wider cursor-pointer hover:opacity-80',
                    statusClass(rootFile.status)
                  ]"
                >
                  {{ rootFile.status }}
                </span>

                <button
                  @click="handleShowDetails(rootFile, 'overview')"
                  class="p-2 hover:bg-gray-200 rounded-full transition-colors"
                  title="Investigate Bundle"
                >
                  <svg class="h-5 w-5 text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                </button>
              </div>
            </div>

            <!-- Bundle Contents Summary -->
            <div class="px-6 py-4">
              <div class="flex items-center space-x-6 text-sm">
                <button
                  @click="handleShowDetails(rootFile, hasAssets(rootFile) ? 'assets' : 'overview')"
                  class="flex items-center text-gray-600 hover:text-gray-900"
                  title="Show full bundle file list"
                >
                  <svg class="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                  </svg>
                  <span>{{ countFiles(rootFile) }} Files Total</span>
                </button>
                <button
                  v-if="hasAssets(rootFile)"
                  @click="handleShowDetails(rootFile, 'assets')"
                  class="flex items-center text-indigo-700 hover:text-indigo-900 font-medium"
                >
                  <svg class="h-4 w-4 mr-1 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4l2 2h4a2 2 0 012 2v12a4 4 0 01-4 4H7z" />
                  </svg>
                  <span>Assets Found ({{ countAssets(rootFile) }})</span>
                </button>
                <button
                  v-if="hasValidationIssues(rootFile)"
                  @click="handleShowDetails(rootFile, 'issues')"
                  class="flex items-center text-red-600 hover:text-red-700 font-medium"
                >
                  <svg class="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                  </svg>
                  <span>Action Required</span>
                </button>
              </div>
            </div>
          </div>
        </div>

        <div class="mt-8 flex justify-between items-center py-6 border-t border-gray-200">
          <div class="text-sm text-gray-600">
            Selected <span class="font-bold text-indigo-600 text-lg">{{ workflowStore.selectedFiles.length }}</span>
            of <span class="font-bold text-gray-900 text-lg">{{ visibleUploadedFiles.length }}</span> bundles
          </div>
          <div class="space-x-4">
            <button
              @click="handleBack"
              class="px-8 py-3 border border-gray-300 text-gray-700 font-medium rounded-lg hover:bg-gray-50 transition-all focus:ring-4 focus:ring-gray-100"
            >
              ← Back
            </button>
            <button
              @click="handleNext"
              :disabled="workflowStore.selectedFiles.length === 0"
              class="px-8 py-3 bg-indigo-600 text-white font-bold rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg hover:shadow-indigo-200 focus:ring-4 focus:ring-indigo-100"
            >
              Continue to Metadata →
            </button>
          </div>
        </div>
      </div>
    </div>

    <ValidationModal
      v-model:show="isModalOpen"
      :file-node="selectedFileForModal"
      :focus-section="modalFocusSection"
    />

  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWorkflowStore } from '@/stores/workflow'
import fileService from '@/services/file.service'
import StepIndicator from '@/components/workflow/StepIndicator.vue'
import ValidationModal from '@/components/workflow/ValidationModal.vue'
import {
  getNodeResumeKey,
  isWorkflowSourceNode,
  persistWorkflowState,
  restoreWorkflowContext,
  shouldRestoreWorkflowContext,
  normalizeSourceFileState,
  sourceFileStateClass
} from '@/utils/workflowState'

const router = useRouter()
const route = useRoute()
const workflowStore = useWorkflowStore()

const isModalOpen = ref(false)
const selectedFileForModal = ref(null)
const modalFocusSection = ref('overview')
const loading = ref(false)
const cloudDownloads = ref(null)
const cloudDownloadsLoading = ref(false)
const cloudDownloadsError = ref('')
const downloadingMirrorId = ref(null)
const filesError = ref('')
const excludedPathSegments = new Set(['__macosx', '__pycache__'])

const hasExcludedSegment = (value) => {
  if (!value || typeof value !== 'string') return false
  return value
    .replace(/\\/g, '/')
    .split('/')
    .some(segment => excludedPathSegments.has(segment.toLowerCase()))
}

const isExcludedNode = (node) => {
  if (!node) return false
  if (!isWorkflowSourceNode(node)) return true
  const candidates = [
    node.name,
    node.filename,
    node.relative_path,
    node.absolute_path,
    node.path
  ]
  return candidates.some(hasExcludedSegment)
}

const sanitizeNodes = (nodes = []) => {
  return nodes
    .filter(node => !isExcludedNode(node))
    .map(node => ({
      ...node,
      children: sanitizeNodes(node.children || [])
    }))
}

const visibleUploadedFiles = computed(() => sanitizeNodes(workflowStore.uploadedFiles || []))

const removeExcludedFromSelection = () => {
  workflowStore.selectedFiles = (workflowStore.selectedFiles || []).filter(file => !isExcludedNode(file))
}

const fetchFiles = async () => {
  if (!workflowStore.sessionId) return

  loading.value = true
  filesError.value = ''
  try {
    const response = await fileService.getNodes(workflowStore.sessionId, { suppressGlobalError: true })
    workflowStore.setUploadedFiles(sanitizeNodes(response.data.nodes || []))
    removeExcludedFromSelection()
  } catch (err) {
    filesError.value = 'Could not refresh your files. Check your connection and try again.'
    console.error('Failed to fetch session files:', err)
  } finally {
    loading.value = false
  }
}

const fetchCloudDownloads = async () => {
  if (!workflowStore.sessionId) return

  cloudDownloadsLoading.value = true
  cloudDownloadsError.value = ''
  try {
    const response = await fileService.listCloudDownloads(workflowStore.sessionId)
    cloudDownloads.value = response.data || null
  } catch (err) {
    console.error('Failed to fetch Cloud Storage downloads:', err)
    cloudDownloads.value = null
    cloudDownloadsError.value = err?.error?.message || err?.message || 'Could not check Cloud Storage downloads.'
  } finally {
    cloudDownloadsLoading.value = false
  }
}

const downloadCloudArtifact = async (item) => {
  if (!workflowStore.sessionId || !item?.id) return

  downloadingMirrorId.value = item.id
  try {
    const response = await fileService.getCloudDownloadUrl(workflowStore.sessionId, item.id)
    const downloadUrl = response.data?.download_url
    if (!downloadUrl) {
      throw new Error('Cloud download URL was not returned.')
    }
    window.location.assign(downloadUrl)
  } catch (err) {
    console.error('Failed to open Cloud Storage download:', err)
    cloudDownloadsError.value = err?.error?.message || err?.message || 'Could not open Cloud Storage download.'
    await fetchCloudDownloads()
  } finally {
    downloadingMirrorId.value = null
  }
}

onMounted(async () => {
  const resumeSessionId = Number.parseInt(route.query.sessionId, 10)
  if (shouldRestoreWorkflowContext(workflowStore, resumeSessionId, {
    force: route.query.resume === 'workflow',
    requireUploadedFiles: true
  })) {
    try {
      await restoreWorkflowContext(workflowStore, resumeSessionId, { includeDraft: false })
    } catch (err) {
      console.error('Failed to restore workflow context for the file review step:', err)
    }
  }

  if (!workflowStore.uploadedFiles || workflowStore.uploadedFiles.length === 0) {
    await fetchFiles()
  } else {
    workflowStore.setUploadedFiles(sanitizeNodes(workflowStore.uploadedFiles))
    removeExcludedFromSelection()
  }

  await fetchCloudDownloads()

  if (workflowStore.sessionId) {
    try {
      await persistWorkflowState(workflowStore, 'files')
    } catch (err) {
      console.warn('Failed to persist workflow state for file review:', err)
    }
  }
})

const countFiles = (node) => {
  let count = 1
  if (node.children) {
    node.children.forEach(child => {
      count += countFiles(child)
    })
  }
  return count
}

const hasAssets = (node) => {
  return Boolean(node?.children?.length)
}

const countAssets = (node) => {
  return Math.max(countFiles(node) - 1, 0)
}

const hasValidationIssues = (node) => {
  const status = normalizeSourceFileState(node.validation_status || node.status || '')
  if (['missing', 'failed'].includes(status)) {
    return true
  }
  const report = node.validation_report || {}
  if ((report.errors || []).length > 0 || (report.missing_textures || []).length > 0 || (report.conflicts || []).length > 0) {
    return true
  }
  if (node.children) {
    return node.children.some(child => hasValidationIssues(child))
  }
  return false
}

// Helper to get a unique identifier for a file
const getFileId = (file) => {
  return file.file_id || file.absolute_path || file.path || file.relative_path || file.name
}

// Check if a file with the same ID is in the store
const isSelected = (file) => {
  const targetId = getFileId(file)
  return workflowStore.selectedFiles.some(f => getFileId(f) === targetId)
}

const toggleSelection = (file) => {
  const targetId = getFileId(file)
  const index = workflowStore.selectedFiles.findIndex(f => getFileId(f) === targetId)

  if (index > -1) {
    // Found, so remove it
    workflowStore.selectedFiles.splice(index, 1)
  } else {
    // Not found, so add it
    workflowStore.selectedFiles.push(file)
  }
}

const selectAllVisibleFiles = () => {
  const selectedIds = new Set(workflowStore.selectedFiles.map(file => getFileId(file)))
  visibleUploadedFiles.value.forEach((file) => {
    const fileId = getFileId(file)
    if (!selectedIds.has(fileId)) {
      workflowStore.selectedFiles.push(file)
      selectedIds.add(fileId)
    }
  })
}

const clearSelection = () => {
  workflowStore.setSelectedFiles([])
}

watch(
  () => workflowStore.selectedFiles.map(file => getNodeResumeKey(file)),
  async () => {
    if (!workflowStore.sessionId) return
    try {
      await persistWorkflowState(workflowStore, 'files')
    } catch (err) {
      console.warn('Failed to persist selected files for workflow resume:', err)
    }
  },
  { deep: true }
)

const handleShowDetails = (fileNode, focusSection = 'overview') => {
  selectedFileForModal.value = fileNode
  modalFocusSection.value = focusSection
  isModalOpen.value = true
}

// ... (handleBack and handleNext are unchanged) ...
const handleBack = () => {
  if (workflowStore.isBatchMode) {
    workflowStore.goToStep(2)
    router.push('/workflow/msf-analysis')
    return
  }
  workflowStore.goToStep(1)
  router.push('/workflow/upload')
}

const handleNext = () => {
  if (workflowStore.selectedFiles.length > 0) {
    if (workflowStore.isBatchMode) {
      workflowStore.goToStep(4)
      persistWorkflowState(workflowStore, 'metadata').catch((err) => {
        console.warn('Failed to persist metadata workflow state:', err)
      })
      router.push({ name: 'SubmissionMetadata' })
    } else {
      workflowStore.nextStep()
      persistWorkflowState(workflowStore, 'metadata').catch((err) => {
        console.warn('Failed to persist metadata workflow state:', err)
      })
      router.push({ name: 'SubmissionMetadata' })
    }
  }
}

const statusClass = (status) => {
  return sourceFileStateClass(status)
}

const uploadStatusClass = (status) => {
  return sourceFileStateClass(status)
}
</script>
