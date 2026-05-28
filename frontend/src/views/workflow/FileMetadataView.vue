<template>
  <div class="min-h-screen bg-gray-50 py-8">
    <div class="max-w-4xl mx-auto px-4">
      <!-- Auto-Save Indicator -->
      <div v-if="autoSaving || lastSaved" class="mb-4 text-sm text-gray-500">
        <span v-if="autoSaving">Saving draft...</span>
        <span v-else-if="lastSaved">Last saved: {{ formatTime(lastSaved) }}</span>
      </div>

      <!-- Header -->
      <div class="mb-8">
        <h1 class="text-3xl font-bold text-gray-900">File Metadata</h1>
        <p class="mt-2 text-gray-600">Step 3 of 6: Add metadata for each file</p>
        <p v-if="loadError" class="mt-3 text-sm text-red-600">{{ loadError }}</p>
      </div>

      <!-- Progress Indicator -->
      <StepIndicator :current-step="workflowStore.currentStep" />

      <!-- Metadata Forms -->
      <div class="space-y-6">
        <div
          v-for="(file, index) in workflowStore.selectedFiles"
          :key="index"
          class="bg-white shadow rounded-lg p-6"
        >
          <h3 class="text-lg font-semibold text-gray-900 mb-4">
            {{ file.filename || file }}
          </h3>

          <div class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">
                Title
              </label>
              <input
                v-model="fileMetadata[index].title"
                type="text"
                :disabled="loadingMetadata"
                class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
                placeholder="Enter file title"
              />
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">
                Description
              </label>
              <textarea
                v-model="fileMetadata[index].description"
                rows="3"
                :disabled="loadingMetadata"
                class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
                placeholder="Enter file description"
              ></textarea>
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">
                Keywords (comma-separated)
              </label>
              <input
                v-model="fileMetadata[index].keywords"
                type="text"
                :disabled="loadingMetadata"
                class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
                placeholder="keyword1, keyword2, keyword3"
              />
            </div>
          </div>
        </div>
      </div>

      <!-- Success Message -->
      <div v-if="success" class="mt-4 bg-green-50 border border-green-400 text-green-700 px-4 py-3 rounded">
        {{ success }}
      </div>

      <!-- Navigation -->
      <div class="mt-8 flex justify-between">
        <button
          @click="handleBack"
          class="px-6 py-2 border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50 transition-colors"
        >
          ← Back
        </button>
        <button
          @click="handleNext"
          :disabled="saving || loadingMetadata"
          class="px-6 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50 transition-colors"
        >
          {{ saving ? 'Saving...' : loadingMetadata ? 'Loading...' : 'Save & Continue →' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useAutoSave } from '@/composables/useAutoSave'
import { useRouter } from 'vue-router'
import { useWorkflowStore } from '@/stores/workflow'
import api from '@/services/api'
import StepIndicator from '@/components/workflow/StepIndicator.vue'

const router = useRouter()
const workflowStore = useWorkflowStore()

const saving = ref(false)
const loadingMetadata = ref(false)
const success = ref('')
const loadError = ref('')

const emptyMetadata = () => ({
  title: '',
  description: '',
  keywords: ''
})

const getFileId = (file) => file?.file_id || file?.id || null

const normalizeMetadata = (metadata = {}) => ({
  title: metadata.title || '',
  description: metadata.description || '',
  keywords: metadata.keywords || ''
})

const fileMetadata = ref(
  workflowStore.selectedFiles.map((file) => (
    normalizeMetadata(workflowStore.fileMetadata[getFileId(file)] || emptyMetadata())
  ))
)

// Auto-save functionality
const saveMetadataDraft = async (metadata) => {
  const fileIds = workflowStore.selectedFiles.map(getFileId)
  if (fileIds.length === 0 || fileIds.some((fileId) => !fileId)) return

  try {
    await Promise.all(
      metadata.map((item, index) => api.post(`/metadata/file/${fileIds[index]}`, { metadata: item }))
    )
  } catch (err) {
    console.error('Failed to auto-save metadata:', err)
  }
}

const { isSaving: autoSaving, lastSaved } = useAutoSave(
  saveMetadataDraft,
  fileMetadata,
  { interval: 30000, enabled: true }
)

onMounted(async () => {
  fileMetadata.value = workflowStore.selectedFiles.map((file) => (
    normalizeMetadata(workflowStore.fileMetadata[getFileId(file)] || emptyMetadata())
  ))

  const fileIds = workflowStore.selectedFiles.map(getFileId)
  if (fileIds.some((fileId) => !fileId)) {
    loadError.value = 'Some selected files cannot persist metadata because they do not have a backend file ID.'
    return
  }

  loadingMetadata.value = true
  loadError.value = ''
  try {
    const loaded = await Promise.all(
      fileIds.map((fileId) => api.get(`/metadata/file/${fileId}`))
    )
    fileMetadata.value = loaded.map((response, index) => {
      const metadata = normalizeMetadata(response?.data?.metadata || emptyMetadata())
      workflowStore.addFileMetadata(fileIds[index], metadata)
      return metadata
    })
  } catch (err) {
    loadError.value = err?.error?.message || err?.message || 'Failed to load existing file metadata.'
  } finally {
    loadingMetadata.value = false
  }
})

const handleBack = () => {
  workflowStore.prevStep()
  router.push('/workflow/files')
}

const handleNext = async () => {
  saving.value = true
  success.value = ''
  loadError.value = ''

  try {
    for (let i = 0; i < fileMetadata.value.length; i++) {
      const file = workflowStore.selectedFiles[i]
      const fileId = getFileId(file)
      if (!fileId) {
        throw new Error(`Cannot save metadata for ${file?.filename || file?.name || 'selected file'} without a backend file ID.`)
      }
      const metadata = fileMetadata.value[i]

      await api.post(`/metadata/file/${fileId}`, { metadata })
      workflowStore.addFileMetadata(fileId, metadata)
    }

    success.value = 'Metadata saved successfully!'

    setTimeout(() => {
      workflowStore.goToStep(4)
      router.push('/workflow/metadata')
    }, 800)

  } catch (err) {
    console.error('Failed to save metadata:', err)
    loadError.value = err?.error?.message || err?.message || 'Failed to save file metadata.'
  } finally {
    saving.value = false
  }
}

const formatTime = (date) => {
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit'
  })
}
</script>
