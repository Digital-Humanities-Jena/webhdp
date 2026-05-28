<template>
  <div class="min-h-screen bg-gray-50 py-8">
    <div class="max-w-4xl mx-auto px-4">
      <div class="mb-8">
        <h1 class="text-3xl font-bold text-gray-900">Select Pipeline</h1>
        <p class="mt-2 text-gray-600">Step 6 of 7: Choose a processing pipeline</p>
      </div>

      <StepIndicator :current-step="6" />

      <div class="bg-white shadow rounded-lg p-6">

        <div v-if="loadingPipelines" class="text-center py-12">
          <LoadingSpinner size="lg" text="Loading pipelines..." />
        </div>

        <div v-else-if="pipelineError" class="text-center py-12">
          <Alert v-model="pipelineError" variant="error" :message="pipelineError" :dismissible="false" />
        </div>

        <div v-else>
          <h2 class="text-xl font-semibold text-gray-900 mb-6">Available Pipelines</h2>

          <div v-if="availablePipelines.length === 0" class="text-center text-gray-500 py-8">
            <p>No pipelines are currently available.</p>
          </div>

          <div v-else class="space-y-4">
            <div
              v-for="pipeline in availablePipelines"
              :key="pipeline.identifier"
              @click="selectedPipeline = pipeline.identifier"
              :class="[
                'border-2 rounded-lg p-5 cursor-pointer transition-all',
                selectedPipeline === pipeline.identifier
                  ? 'border-indigo-600 bg-indigo-50 shadow-sm'
                  : 'border-gray-200 hover:border-gray-300'
              ]"
            >
              <div class="flex items-start">
                <input
                  type="radio"
                  :id="pipeline.identifier"
                  :value="pipeline.identifier"
                  v-model="selectedPipeline"
                  class="mt-1.5 h-4 w-4 text-indigo-600 border-gray-300 focus:ring-indigo-500"
                />
                <div class="ml-4 flex-1">
                  <div class="flex items-center justify-between">
                    <label :for="pipeline.identifier" class="text-lg font-bold text-gray-900 cursor-pointer">{{ pipeline.name }}</label>
                    <div class="ml-4 flex flex-wrap justify-end gap-2 text-[11px]">
                      <span class="rounded-full border border-gray-200 bg-white px-2.5 py-1 font-medium text-gray-700">
                        v{{ pipeline.version || 'n/a' }}
                      </span>
                      <span class="rounded-full border border-gray-200 bg-white px-2.5 py-1 font-medium text-gray-700">
                        {{ pipeline.modality || 'generic' }}
                      </span>
                      <span class="rounded-full border border-gray-200 bg-white px-2.5 py-1 font-medium text-gray-700">
                        {{ pipeline.processingMode || 'root' }}
                      </span>
                    </div>
                  </div>
                  <p class="mt-1 text-sm text-gray-600 leading-relaxed">{{ pipeline.description }}</p>

                  <div class="mt-3 flex flex-wrap gap-2">
                    <span
                      class="inline-flex items-center rounded border border-gray-200 bg-white px-2 py-0.5 text-[10px] font-medium uppercase tracking-tighter text-gray-700"
                    >
                      {{ pipeline.status || 'active' }}
                    </span>
                    <span
                      v-if="Array.isArray(pipeline.tags) && pipeline.tags.length"
                      class="inline-flex items-center rounded border border-gray-200 bg-white px-2 py-0.5 text-[10px] font-medium text-gray-700"
                    >
                      {{ pipeline.tags.join(', ') }}
                    </span>
                  </div>

                  <div v-if="pipeline.config?.steps?.length" class="mt-4 flex flex-wrap gap-2">
                    <template v-for="step in pipeline.config.steps" :key="step.id">
                      <span
                        v-if="step.enabled !== false"
                        class="inline-flex items-center rounded border border-indigo-200 bg-white px-2 py-0.5 text-[10px] font-medium uppercase tracking-tighter text-indigo-700"
                      >
                        <svg class="mr-1 h-2 w-2 text-indigo-400" fill="currentColor" viewBox="0 0 8 8">
                          <circle cx="4" cy="4" r="3" />
                        </svg>
                        {{ step.name }}
                      </span>
                      <span
                        v-else
                        class="inline-flex items-center rounded border border-gray-200 bg-gray-50 px-2 py-0.5 text-[10px] font-medium uppercase tracking-tighter text-gray-400 line-through"
                        title="Disabled in active config"
                      >
                        {{ step.name }}
                      </span>
                    </template>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="mt-8 flex justify-between">
            <button
              @click="handleBack"
              class="px-6 py-2 border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50 transition-colors"
            >
              ← Back
            </button>
            <button
              @click="handleSubmit"
              :disabled="!selectedPipeline || submitting"
              data-testid="pipeline-continue"
              class="px-8 py-2 bg-indigo-600 text-white rounded-md font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors shadow-sm"
            >
              {{ submitting ? 'Submitting...' : 'Continue to Summary →' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWorkflowStore } from '@/stores/workflow'
import { useToast } from '@/composables/useToast'
import pipelineService from '@/services/pipeline.service'
import StepIndicator from '@/components/workflow/StepIndicator.vue'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import Alert from '@/components/ui/Alert.vue'
import { persistWorkflowState, restoreWorkflowContext, shouldRestoreWorkflowContext } from '@/utils/workflowState'

const route = useRoute()
const router = useRouter()
const workflowStore = useWorkflowStore()
const toast = useToast()

const selectedPipeline = ref(null)
const submitting = ref(false)
const availablePipelines = ref([])
const loadingPipelines = ref(true)
const pipelineError = ref('')

onMounted(async () => {
  loadingPipelines.value = true
  pipelineError.value = ''
  try {
    const resumeSessionId = Number.parseInt(route.query.sessionId, 10)
    if (shouldRestoreWorkflowContext(workflowStore, resumeSessionId, {
      force: route.query.resume === 'workflow',
      requireUploadedFiles: true,
      requireSelectedFiles: true,
      requireBatchMetadata: true
    })) {
      await restoreWorkflowContext(workflowStore, resumeSessionId)
    }

    if (!workflowStore.sessionId) {
      toast.error('Your workflow session is missing. Please start again from upload.')
      router.replace('/workflow/upload')
      return
    }

    if (!Array.isArray(workflowStore.selectedFiles) || workflowStore.selectedFiles.length === 0) {
      toast.error('Select at least one file before choosing a pipeline.')
      workflowStore.goToStep(3)
      router.replace('/workflow/files')
      return
    }

    const response = await pipelineService.listPipelines()
    availablePipelines.value = response.data?.pipelines || []

    if (availablePipelines.value.length > 0) {
      selectedPipeline.value = workflowStore.selectedPipeline?.identifier || availablePipelines.value[0].identifier
    }
    if (workflowStore.sessionId) {
      await persistWorkflowState(workflowStore, 'pipeline')
    }
  } catch (err) {
    console.error('Failed to load pipelines:', err)
    pipelineError.value = 'Failed to load available pipelines. Please try refreshing the page.'
    toast.error('Failed to load pipelines')
  } finally {
    loadingPipelines.value = false
  }
})

const handleBack = () => {
  workflowStore.prevStep()
  persistWorkflowState(workflowStore, 'edm_selection').catch((err) => {
    console.warn('Failed to persist EDM workflow state:', err)
  })
  router.push('/workflow/edm-selection')
}

const handleSubmit = async () => {
  if (!selectedPipeline.value) return

  submitting.value = true

  try {
    // Save the selected pipeline to the store
    const chosenPipeline = availablePipelines.value.find((p) => p.identifier === selectedPipeline.value)
    workflowStore.setPipeline(chosenPipeline)

    // Advance to the final step
    workflowStore.nextStep()
    await persistWorkflowState(workflowStore, 'submit', { selectedPipeline: chosenPipeline })
    router.push('/workflow/submit')

  } catch (err) {
    console.error('Submission failed:', err)
    toast.error('An error occurred during submission.')
    submitting.value = false
  }
}
</script>
