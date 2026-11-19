<template>
  <div class="min-h-screen bg-gray-50 py-8">
    <div class="max-w-4xl mx-auto px-4">
      <div class="mb-8">
        <h1 class="text-3xl font-bold text-gray-900">Select Pipeline</h1>
        <p class="mt-2 text-gray-600">Choose how to process your selected files. Each pipeline lists its outputs and requirements.</p>
      </div>

      <StepIndicator :batch-mode="workflowStore.isBatchMode" :current-step="6" />

      <div class="bg-white shadow rounded-lg p-6">

        <div v-if="loadingPipelines" class="text-center py-12">
          <LoadingSpinner size="lg" text="Loading pipelines..." />
        </div>

        <div v-else-if="pipelineError" class="text-center py-12">
          <Alert :model-value="Boolean(pipelineError)" variant="error" :message="pipelineError" :dismissible="false" />
          <button type="button" @click="loadPipelines" class="mt-4 rounded-md bg-indigo-600 px-4 py-2 text-white hover:bg-indigo-700">Try again</button>
        </div>

        <div v-else>
          <h2 class="text-xl font-semibold text-gray-900 mb-6">Available Pipelines</h2>

          <div v-if="availablePipelines.length === 0" class="text-center text-gray-500 py-8">
            <p>No pipelines are currently available. Your file selection is saved.</p>
            <p class="mt-2 text-sm">Ask an administrator to enable a pipeline, then check again.</p>
            <button type="button" @click="loadPipelines" class="mt-4 rounded-md border border-gray-300 px-4 py-2 text-gray-700 hover:bg-gray-50">Check again</button>
          </div>

          <fieldset v-else class="space-y-4" :disabled="submitting">
            <legend class="sr-only">Available Pipelines</legend>
            <div
              v-for="pipeline in availablePipelines"
              :key="pipeline.identifier"
              @click="!submitting && !pipelineInputError(pipeline, workflowStore.selectedFiles) && (selectedPipeline = pipeline.identifier)"
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
                  name="processing-pipeline"
                  :id="pipeline.identifier"
                  :value="pipeline.identifier"
                  v-model="selectedPipeline"
                  :disabled="Boolean(pipelineInputError(pipeline, workflowStore.selectedFiles))"
                  :aria-describedby="`${pipeline.identifier}-outcome${pipelineGpuCount(pipeline) ? ` ${pipeline.identifier}-gpu` : ''}${pipelineInputError(pipeline, workflowStore.selectedFiles) ? ` ${pipeline.identifier}-input-error` : ''}`"
                  class="mt-1.5 h-4 w-4 text-indigo-600 border-gray-300 focus:ring-indigo-500"
                />
                <div class="ml-4 min-w-0 flex-1">
                  <div class="flex flex-wrap items-center justify-between gap-2">
                    <label :for="pipeline.identifier" class="text-lg font-bold text-gray-900 cursor-pointer">{{ pipelineTaskLabel(pipeline) }}</label>
                    <span v-if="recommendedPipeline?.identifier === pipeline.identifier" class="text-xs font-medium text-indigo-700" title="Compatible with your selection; favors fewer resources and a workflow without publication.">Recommended</span>
                  </div>
                  <p class="mt-1 text-sm text-gray-600 leading-relaxed">{{ pipeline.description }}</p>
                  <p v-if="pipelineGpuCount(pipeline)" :id="`${pipeline.identifier}-gpu`" class="mt-2 text-sm font-semibold text-indigo-900">
                    Requires {{ pipelineGpuCount(pipeline) === 1 ? 'a GPU' : `${pipelineGpuCount(pipeline)} GPUs` }}
                  </p>
                  <PipelineGpuStatus
                    v-if="selectedPipeline === pipeline.identifier && pipelineGpuCount(pipeline)"
                    class="mt-2"
                    :session-id="workflowStore.sessionId"
                    :gpu-count="pipelineGpuCount(pipeline)"
                    :component-keys="pipelineGuidance(pipeline).hpc_component_keys"
                  />

                  <p :id="`${pipeline.identifier}-outcome`" class="mt-2 text-sm font-medium text-slate-800">{{ pipelineGuidance(pipeline).outcome }}</p>
                  <p v-if="pipelineInputError(pipeline, workflowStore.selectedFiles)" :id="`${pipeline.identifier}-input-error`" class="mt-1 text-sm text-amber-800">{{ pipelineInputError(pipeline, workflowStore.selectedFiles) }}</p>
                  <details class="mt-3 text-sm text-gray-600" @click.stop>
                    <summary class="cursor-pointer font-medium text-indigo-700">Outputs and requirements</summary>
                    <p v-if="pipelineGuidance(pipeline).outputs?.length" class="mt-2">Outputs: {{ pipelineGuidance(pipeline).outputs.join(', ') }}.</p>
                    <p class="mt-2">Requires: {{ pipelineGuidance(pipeline).requirements.join('; ') || 'No HPC allocation required' }}.</p>
                    <p v-if="pipelineGuidance(pipeline).source_extensions?.length" class="mt-2">Source formats: {{ pipelineGuidance(pipeline).source_extensions.join(', ') }}.</p>
                    <p v-if="pipeline.identifier === 'mesh_optimization'" class="mt-2">Static GLB with embedded textures only. Detail budgets apply per material group; geometry is retained when reduction exceeds the error limit. Small files may grow after export.</p>
                    <p class="mt-2">Version {{ pipeline.version || 'not specified' }} · {{ pipeline.modality || 'generic' }}</p>
                    <p v-if="pipeline.identifier === 'model_georeferencing'" class="mt-2">
                      Use a batch with one upright, textured GLB and one 8-bit reference GeoTIFF per bundle.
                      The reference must cover the site and use a projected coordinate system in metres.
                      Give each pair the same filename stem (for example, church.glb and church.tif),
                      list each GLB in the metadata spreadsheet, and review the bundles in Files.
                      Check the alignment overlay before reusing the result; image matching does not establish survey accuracy.
                    </p>
                    <ol v-if="pipeline.config?.steps?.length" class="mt-2 list-decimal space-y-1 pl-5">
                      <li v-for="step in pipeline.config.steps.filter(step => step.enabled !== false)" :key="step.id">{{ step.name }}</li>
                    </ol>
                  </details>
                </div>
              </div>
            </div>
          </fieldset>

          <p v-if="saveError" role="alert" class="mt-4 text-sm text-red-700">{{ saveError }}</p>
          <p v-if="inputCompatibilityError" role="alert" class="mt-4 text-sm text-amber-800">{{ inputCompatibilityError }}</p>
          <div class="mt-8 flex flex-col-reverse gap-3 sm:flex-row sm:justify-between">
            <button
              @click="handleBack"
              :disabled="submitting"
              class="px-6 py-2 border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50 transition-colors"
            >
              ← Back
            </button>
            <button
              @click="handleSubmit"
              :disabled="!selectedPipeline || submitting || Boolean(inputCompatibilityError)"
              data-testid="pipeline-continue"
              class="px-8 py-2 bg-indigo-600 text-white rounded-md font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors shadow-sm"
            >
              {{ submitting ? 'Saving...' : 'Continue to Summary →' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWorkflowStore } from '@/stores/workflow'
import { useToast } from '@/composables/useToast'
import pipelineService from '@/services/pipeline.service'
import PipelineGpuStatus from '@/components/hpc/PipelineGpuStatus.vue'
import StepIndicator from '@/components/workflow/StepIndicator.vue'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import Alert from '@/components/ui/Alert.vue'
import { persistWorkflowState, restoreWorkflowContext, shouldRestoreWorkflowContext } from '@/utils/workflowState'
import { pipelineGpuCount, pipelineGuidance, pipelineInputError, recommendPipeline, pipelineTaskLabel } from '@/utils/pipelineGuidance'

const route = useRoute()
const router = useRouter()
const workflowStore = useWorkflowStore()
const toast = useToast()

const selectedPipeline = ref(null)
const submitting = ref(false)
const availablePipelines = ref([])
const loadingPipelines = ref(true)
const pipelineError = ref('')
const saveError = ref('')
const recommendedPipeline = computed(() => recommendPipeline(availablePipelines.value, workflowStore.selectedFiles))
const inputCompatibilityError = computed(() => {
  const pipeline = availablePipelines.value.find(item => item.identifier === selectedPipeline.value)
  return pipeline ? pipelineInputError(pipeline, workflowStore.selectedFiles) : ''
})

const loadPipelines = async () => {
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
      const savedIdentifier = selectedPipeline.value || workflowStore.selectedPipeline?.identifier
      selectedPipeline.value = availablePipelines.value.some(pipeline => pipeline.identifier === savedIdentifier)
        ? savedIdentifier : recommendedPipeline.value?.identifier || null
    } else {
      selectedPipeline.value = null
    }
    if (workflowStore.sessionId) {
      await persistWorkflowState(workflowStore, 'pipeline')
    }
  } catch (err) {
    console.error('Failed to load pipelines:', err)
    pipelineError.value = 'Could not load pipelines. Check your connection and try again. Your files are still saved.'
  } finally {
    loadingPipelines.value = false
  }
}

onMounted(loadPipelines)

const handleBack = () => {
  workflowStore.prevStep()
  persistWorkflowState(workflowStore, 'edm_selection').catch((err) => {
    console.warn('Failed to persist EDM workflow state:', err)
  })
  router.push('/workflow/edm-selection')
}

const handleSubmit = async () => {
  if (!selectedPipeline.value || submitting.value || inputCompatibilityError.value) return
  saveError.value = ''

  submitting.value = true

  try {
    // Save the selected pipeline to the store
    const chosenPipeline = availablePipelines.value.find((p) => p.identifier === selectedPipeline.value)
    workflowStore.setPipeline(chosenPipeline)

    await persistWorkflowState(workflowStore, 'submit', { selectedPipeline: chosenPipeline })
    workflowStore.nextStep()
    router.push('/workflow/submit')

  } catch (err) {
    console.error('Submission failed:', err)
    saveError.value = 'Could not save your pipeline choice. Try continuing again; processing has not started.'
    submitting.value = false
  }
}
</script>
