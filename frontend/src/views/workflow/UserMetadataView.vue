<template>
  <div class="min-h-screen bg-gray-50 py-8">
    <div class="max-w-4xl mx-auto px-4">
      <!-- Header -->
      <div class="mb-8">
        <h1 class="text-3xl font-bold text-gray-900">Your Information</h1>
        <p class="mt-2 text-gray-600">Step 4 of 6: Provide submission metadata</p>
      </div>

      <!-- Progress Indicator -->
      <StepIndicator :current-step="workflowStore.currentStep" />

      <!-- User Metadata Form -->
      <div class="bg-white shadow rounded-lg p-6">
        <div class="space-y-6">
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">
              Project Name *
            </label>
            <input
              v-model="userMetadata.projectName"
              type="text"
              required
              class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
              placeholder="Enter project name"
            />
          </div>

          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">
              Institution
            </label>
            <input
              v-model="userMetadata.institution"
              type="text"
              class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
              placeholder="Enter institution name"
            />
          </div>

          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">
              Project Description
            </label>
            <textarea
              v-model="userMetadata.description"
              rows="4"
              class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
              placeholder="Describe your project"
            ></textarea>
          </div>

          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">
              License
            </label>
            <select
              v-model="userMetadata.license"
              class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
            >
              <option value="">Select license</option>
              <option value="cc-by-4.0">CC BY 4.0</option>
              <option value="cc-by-sa-4.0">CC BY-SA 4.0</option>
              <option value="cc0-1.0">CC0 1.0</option>
              <option value="mit">MIT</option>
            </select>
          </div>

          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">
              Additional Notes
            </label>
            <textarea
              v-model="userMetadata.notes"
              rows="3"
              class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
              placeholder="Any additional information"
            ></textarea>
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
            :disabled="!userMetadata.projectName || saving"
            class="px-6 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {{ saving ? 'Saving...' : 'Save & Continue →' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useWorkflowStore } from '@/stores/workflow'
import StepIndicator from '@/components/workflow/StepIndicator.vue'

const router = useRouter()
const workflowStore = useWorkflowStore()

const userMetadata = ref({
  projectName: '',
  institution: '',
  description: '',
  license: '',
  notes: ''
})

const saving = ref(false)
const success = ref('')

const handleBack = () => {
  workflowStore.goToStep(4)
  router.push('/workflow/metadata')
}

const handleNext = async () => {
  if (!userMetadata.value.projectName) return

  saving.value = true
  success.value = ''

  try {
    // Store in workflow store
    workflowStore.setUserMetadata(userMetadata.value)

    success.value = 'Information saved successfully!'

    setTimeout(() => {
      workflowStore.goToStep(6)
      router.push('/workflow/pipeline')
    }, 800)

  } catch (err) {
    console.error('Failed to save metadata:', err)
  } finally {
    saving.value = false
  }
}
</script>
