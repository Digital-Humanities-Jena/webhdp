<template>
  <div class="min-h-screen bg-gray-50 py-8">
    <div class="max-w-4xl mx-auto px-4">
      <div class="mb-8">
        <h1 class="text-3xl font-bold text-gray-900">Submission Metadata</h1>
        <p class="mt-2 text-gray-600">Describe your records, or review the descriptions from your batch spreadsheet.</p>
      </div>

      <StepIndicator :batch-mode="workflowStore.isBatchMode" :current-step="4" />

      <div class="bg-white shadow rounded-lg p-6">

        <div v-if="loading" class="text-center py-12">
          <LoadingSpinner size="lg" text="Loading metadata form..." />
        </div>

        <div
          v-else-if="communityOverride.enabled"
          class="mb-6 bg-amber-50 border-l-4 border-amber-400 p-4 rounded"
        >
          <div class="flex">
            <div class="flex-shrink-0">
              <svg class="h-5 w-5 text-amber-500" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
              </svg>
            </div>
            <div class="ml-3">
              <h3 class="text-sm font-medium text-amber-800">Admin Override Active</h3>
              <p class="text-sm text-amber-700 mt-1">
                Zenodo community is hardcoded to <strong>{{ communityOverride.community }}</strong> for this submission.
                Any community values in metadata or mappings are overridden while this setting is enabled.
              </p>
            </div>
          </div>
        </div>

        <!-- NEW: Batch Mode Mapping Overview -->
        <div v-if="!loading && workflowStore.isBatchMode" class="space-y-8">
          <div class="bg-indigo-50 border-l-4 border-indigo-400 p-4 rounded">
            <div class="flex">
              <div class="flex-shrink-0">
                <svg class="h-5 w-5 text-indigo-400" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd" />
                </svg>
              </div>
              <div class="ml-3">
                <h3 class="text-sm font-medium text-indigo-800">Batch Mode Active</h3>
                <p class="text-sm text-indigo-700 mt-1">
                  Metadata for all matched files is being automatically extracted from your MSF file: <strong>{{ workflowStore.msfPath }}</strong>
                </p>
              </div>
            </div>
          </div>

          <!-- Column Mapping Table -->
          <div>
            <h3 class="text-lg font-semibold text-gray-900 mb-4">Metadata Column Mapping</h3>
            <div class="overflow-x-auto border border-gray-200 rounded-lg">
              <table class="min-w-full divide-y divide-gray-200">
                <thead class="bg-gray-50">
                  <tr>
                    <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">MSF Column</th>
                    <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Zenodo Field</th>
                  </tr>
                </thead>
                <tbody class="bg-white divide-y divide-gray-200">
                  <tr v-for="(field, column) in workflowStore.msfMapping" :key="column">
                    <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{{ column }}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      <span v-if="field.startsWith('_')" class="px-2 py-0.5 bg-gray-100 text-gray-600 rounded-full text-xs">
                        {{ field.substring(1) }} (Internal)
                      </span>
                      <span v-else class="px-2 py-0.5 bg-green-100 text-green-700 rounded-full text-xs font-bold">
                        {{ field }}
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Sample Extracted Metadata -->
          <div v-if="Object.keys(workflowStore.fileMetadataMap).length > 0">
            <h3 class="text-lg font-semibold text-gray-900 mb-4">Sample Extracted Metadata</h3>
            <div class="bg-gray-900 rounded-lg p-4 overflow-auto max-h-96">
              <div v-for="(metadata, filename) in Object.fromEntries(Object.entries(workflowStore.fileMetadataMap).slice(0, 1))" :key="filename">
                <h4 class="text-indigo-400 text-sm font-mono mb-2">// Sample for: {{ filename }}</h4>
                <pre class="text-green-400 text-xs font-mono">{{ JSON.stringify(metadata, null, 2) }}</pre>
              </div>
            </div>
            <p class="text-xs text-gray-500 mt-2">Showing metadata mapping for the first matched file. Similar mappings will be applied to all {{ Object.keys(workflowStore.fileMetadataMap).length }} matched files.</p>
          </div>
        </div>

        <div v-else-if="!loading && showSchemaError" class="text-center py-12">
          <Alert v-model="showSchemaError" variant="error" :message="schemaError" :dismissible="false" />
        </div>

        <form v-else-if="!loading" @submit.prevent="handleNext">
          <fieldset :disabled="saving" class="min-w-0">

          <div class="text-sm text-gray-500 mb-4 text-right">
            <span v-if="isSaving">Saving draft...</span>
            <span v-else-if="saveError" role="alert" class="text-rose-700">Draft save failed. Your edits are still on this page. <button type="button" class="underline" @click="save">Retry save</button></span>
            <span v-else-if="dirty">Unsaved changes</span>
            <span v-else-if="lastSaved">Draft saved at {{ lastSaved.toLocaleTimeString() }}</span>
          </div>

          <div class="space-y-6">
            <template v-for="field in schema.standard_fields" :key="field.key">
              <div v-if="isFieldVisible(field)" class="form-field-wrapper">
                <label :for="`field-${field.key}`" class="block text-sm font-medium text-gray-700">
                  {{ field.label }}
                  <span v-if="isFieldRequired(field)" class="text-red-500">*</span>
                </label>
                <p v-if="field.notes" class="text-xs text-gray-500 mb-1">{{ field.notes }}</p>

                <select
                  v-if="field.type === 'vocab'"
                  :id="`field-${field.key}`"
                  v-model="formData[field.key]"
                  class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
                >
                  <option value="">- Select {{ field.label }} -</option>
                  <option v-for="(label, value) in schema.vocabularies[field.vocabKey]" :key="value" :value="value">
                    {{ label }} ({{ value }})
                  </option>
                </select>

                <textarea
                  v-else-if="field.type === 'textarea'"
                  :id="`field-${field.key}`"
                  v-model="formData[field.key]"
                  rows="4"
                  class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
                ></textarea>

                <input
                  v-else-if="field.type === 'date'"
                  :id="`field-${field.key}`"
                  v-model="formData[field.key]"
                  type="date"
                  class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
                />

                <input
                  v-else-if="field.type === 'tags'"
                  :id="`field-${field.key}`"
                  v-model="formData[field.key]"
                  type="text"
                  class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
                  placeholder="keyword1, keyword2, keyword3"
                />

                <input
                  v-else
                  :id="`field-${field.key}`"
                  v-model="formData[field.key]"
                  type="text"
                  class="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
                />
              </div>
            </template>
          </div>

          <div class="space-y-8 mt-8 pt-6 border-t">
            <template v-for="(config, key) in schema.complex_fields" :key="key">
              <div v-if="isFieldVisible(config)" class="form-field-wrapper">
                <h3 class="text-lg font-medium text-gray-900">
                  {{ config.label }}
                  <span v-if="isFieldRequired(config)" class="text-red-500">*</span>
                </h3>
                <p v-if="config.notes" class="text-xs text-gray-500 mb-2">{{ config.notes }}</p>

                <div v-if="config.allow_multiple !== false">
                  <div class="space-y-4">

                    <div
                      v-for="(entry, index) in formData[key]"
                      :key="entry._uid"
                      class="p-4 border border-gray-200 rounded-lg relative"
                    >
                      <button
                        type="button"
                        @click="removeItem(key, index)"
                        class="absolute top-2 right-2 text-gray-400 hover:text-red-500"
                        title="Remove entry"
                      >
                        <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" /></svg>
                      </button>

                      <h4 class="text-sm font-semibold text-gray-600 mb-3">{{ config.item_label }} {{ index + 1 }}</h4>

                      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <template v-for="attr in config.attributes" :key="attr.key">
                          <div>
                            <label :for="`field-${key}-${index}-${attr.key}`" class="block text-xs font-medium text-gray-600">
                              {{ attr.label }}
                              <span v-if="attr.mandatory" class="text-red-500">*</span>
                            </label>
                            <p v-if="attr.notes" class="text-xs text-gray-500 mb-1">{{ attr.notes }}</p>

                            <!-- FIXED: Use v-if/v-else instead of <component :is> -->
                            <select
                              v-if="attr.type === 'vocab'"
                              :id="`field-${key}-${index}-${attr.key}`"
                              v-model="entry[attr.key]"
                              class="w-full px-2 py-1.5 text-sm border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
                            >
                              <option value="">- Select {{ attr.label }} -</option>
                              <option v-for="(label, value) in schema.vocabularies[attr.vocabKey]" :key="value" :value="value">
                                {{ label }} ({{ value }})
                              </option>
                            </select>

                            <input
                              v-else
                              :id="`field-${key}-${index}-${attr.key}`"
                              :type="attr.type === 'date' ? 'date' : attr.type === 'number' ? 'number' : 'text'"
                              v-model="entry[attr.key]"
                              class="w-full px-2 py-1.5 text-sm border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
                            />
                          </div>
                        </template>
                      </div>
                    </div>
                  </div>

                  <button
                    type="button"
                    @click="addItem(key, config.attributes)"
                    class="mt-4 px-4 py-2 border border-dashed border-gray-300 text-sm font-medium text-gray-700 rounded-md hover:bg-gray-50"
                  >
                    + Add {{ config.item_label }}
                  </button>
                </div>

                <div v-else>
                  <div class="p-4 border border-gray-200 rounded-lg">
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <template v-for="attr in config.attributes" :key="attr.key">
                        <div>
                          <label :for="`field-${key}-${attr.key}`" class="block text-xs font-medium text-gray-600">
                            {{ attr.label }}
                            <span v-if="attr.mandatory" class="text-red-500">*</span>
                          </label>
                          <p v-if="attr.notes" class="text-xs text-gray-500 mb-1">{{ attr.notes }}</p>

                          <!-- FIXED: Use v-if/v-else instead of <component :is> -->
                          <select
                            v-if="attr.type === 'vocab'"
                            :id="`field-${key}-${attr.key}`"
                            v-model="formData[key][attr.key]"
                            class="w-full px-2 py-1.5 text-sm border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
                          >
                            <option value="">- Select {{ attr.label }} -</option>
                            <option v-for="(label, value) in schema.vocabularies[attr.vocabKey]" :key="value" :value="value">
                              {{ label }} ({{ value }})
                            </option>
                          </select>

                          <input
                            v-else
                            :id="`field-${key}-${attr.key}`"
                            :type="attr.type === 'date' ? 'date' : attr.type === 'number' ? 'number' : 'text'"
                            v-model="formData[key][attr.key]"
                            class="w-full px-2 py-1.5 text-sm border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
                          />
                        </div>
                      </template>
                    </div>
                  </div>
                </div>
              </div>
            </template>
          </div>

          </fieldset>
        </form>

        <Alert v-model="showValidationErrors" variant="error" title="Validation Failed" class="mt-6">
          <ul class="list-disc pl-5 space-y-1">
            <li v-for="(err, index) in validationErrors" :key="index">
              {{ err }}
            </li>
          </ul>
        </Alert>

        <div class="mt-8 flex justify-between">
          <button
            @click="handleBack"
            :disabled="saving || loading"
            class="px-6 py-2 border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50 transition-colors"
          >
            ← Back
          </button>
          <button
            @click="handleNext"
            :disabled="loading || saving"
            class="px-6 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {{ saving ? 'Validating & Saving...' : 'Save & Continue →' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWorkflowStore } from '@/stores/workflow'
import api from '@/services/api'
import StepIndicator from '@/components/workflow/StepIndicator.vue'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import Alert from '@/components/ui/Alert.vue'
import { useAutoSave } from '@/composables/useAutoSave'
import { persistWorkflowState, restoreWorkflowContext, shouldRestoreWorkflowContext } from '@/utils/workflowState'

const route = useRoute()
const router = useRouter()
const workflowStore = useWorkflowStore()

const schema = ref(null)
const formData = reactive({})
const loading = ref(true)
const saving = ref(false)
const communityOverride = ref({
  enabled: false,
  community: '3d-big-data-space'
})

const schemaError = ref(null)
const showSchemaError = ref(false)
const validationErrors = ref([])
const showValidationErrors = computed({
  get: () => validationErrors.value.length > 0,
  set: (value) => {
    if (!value) {
      validationErrors.value = []
    }
  }
})



// --- Auto-save ---
const saveDraft = async (data) => {
  if (!workflowStore.sessionId) throw new Error('A session is required to save this draft.')
  await api.put(`/metadata/user/${workflowStore.sessionId}/draft`, preparePayloadForSubmission(data))
}


const { isSaving, lastSaved, saveError, dirty, save, stopAutoSave, startAutoSave, waitForSave } = useAutoSave(saveDraft, formData, {
  debounce: 3000,
  enabled: computed(() => !loading.value && !saving.value && !showSchemaError.value && !workflowStore.isBatchMode && Boolean(workflowStore.sessionId))
})

// --- Form Initialization ---
onMounted(async () => {
  loading.value = true
  schemaError.value = null
  showSchemaError.value = false

  const resumeSessionId = Number.parseInt(route.query.sessionId, 10)
  if (shouldRestoreWorkflowContext(workflowStore, resumeSessionId, {
    force: route.query.resume === 'workflow',
    requireSelectedFiles: true,
    requireUploadedFiles: true
  })) {
    try {
      await restoreWorkflowContext(workflowStore, resumeSessionId)
    } catch (err) {
      console.error('Failed to restore workflow context for metadata step:', err)
    }
  }

  if (!workflowStore.sessionId) {
    console.error("No session ID found in workflow store.")
    schemaError.value = "Your session has expired or was not found. Please start a new upload."
    showSchemaError.value = true
    loading.value = false
    return
  }

  try {
    try {
      const communityRes = await api.get('/metadata/zenodo-community-override', { suppressGlobalError: true })
      const cfg = communityRes?.data?.config || {}
      communityOverride.value = {
        enabled: cfg.enabled === true,
        community: cfg.community || '3d-big-data-space'
      }
    } catch (_e) {
      // keep default hidden state if the optional info endpoint is unavailable
    }

    const schemaResponse = await api.get('/metadata/schema')
    schema.value = schemaResponse.data

    const draftResponse = await api.get(`/metadata/user/${workflowStore.sessionId}`)

    // --- Correctly unwrap draft and handle malformed state ---
    let draft = draftResponse.data.metadata?.zenodo_metadata_draft

    // Handle legacy malformed drafts (if one exists)
    if (draft && draft.zenodo_metadata_draft) {
      draft = draft.zenodo_metadata_draft
    }

    if (draft && typeof draft === 'object' && !Array.isArray(draft)) {
      // Deep clone to avoid reference issues
      Object.assign(formData, JSON.parse(JSON.stringify(draft)))
    } else {
      initializeFromSchema()
    }
    // Initialize fields *after* loading or initializing
    initializeComplexFields(formData)

  } catch (err) {
    console.error('Failed to load metadata setup:', err)
    schemaError.value = 'Failed to load metadata form. Please try again.'
    showSchemaError.value = true
  } finally {
    loading.value = false
  }

  if (workflowStore.sessionId) {
    try {
      await persistWorkflowState(workflowStore, 'metadata')
    } catch (err) {
      console.warn('Failed to persist metadata workflow state:', err)
    }
  }
})

function initializeFromSchema() {
  const data = {}
  schema.value?.standard_fields.forEach(field => {
    if (field.default) {
      if (field.default === 'current_date') {
        data[field.key] = new Date().toISOString().split('T')[0]
      } else {
        data[field.key] = field.default
      }
    } else if (field.type === 'vocab') {
      data[field.key] = "" // Ensure empty string for dropdowns
    }
  })
  // Note: initializeComplexFields is now called *after* this in onMounted
  Object.assign(formData, data)
}

function initializeComplexFields(data) {
  if (!schema.value?.complex_fields) return
  for (const key in schema.value.complex_fields) {
    const config = schema.value.complex_fields[key];

    if (config.allow_multiple === false) {
      // Single-entry object (e.g., journal)
      if (!data[key] || typeof data[key] !== 'object' || Array.isArray(data[key])) {
        data[key] = {};
      }
    } else {
      // Multi-entry array (e.g., creators, communities)
      if (!Array.isArray(data[key])) {
        data[key] = [];
      }

      // *** ADD THIS: Regenerate _uid for all existing entries ***
      data[key] = data[key].map(entry => {
        if (!entry._uid) {
          return {
            ...entry,
            _uid: Date.now() + Math.random().toString(16).slice(2)
          };
        }
        return entry;
      });
    }
  }
}

// --- Dynamic Form Logic ---
function isFieldVisible(field) {
  if (!field.mandatory_rule) return true

  const [controllerKey, allowedValues] = field.mandatory_rule.split(':')
  const controllerValue = formData[controllerKey]

  return allowedValues.split(',').includes(controllerValue)
}

function isFieldRequired(field) {
  if (field.mandatory) return true
  // If a field with a mandatory_rule is visible, it's required
  return field.mandatory_rule && isFieldVisible(field)
}

function sanitizeFormData() {
  const sanitized = JSON.parse(JSON.stringify(formData))

  if (!schema.value?.complex_fields) return sanitized

  for (const key in schema.value.complex_fields) {
    const config = schema.value.complex_fields[key]

    if (config.allow_multiple === false) {
      if (!sanitized[key] || Array.isArray(sanitized[key])) {
        sanitized[key] = {}
      }
    } else {
      if (!Array.isArray(sanitized[key])) {
        sanitized[key] = []
      }

      // Only remove completely null/undefined entries, not partially filled ones
      sanitized[key] = sanitized[key].filter(entry => {
        return entry && typeof entry === 'object'
      })
    }
  }

  return sanitized
}

// This function is only for multi-entry fields
function addItem(key, attributes) {
  const newEntry = {}
  attributes.forEach(attr => {
    newEntry[attr.key] = attr.type === 'number' ? null : ''
  })

  // Give the entry a unique ID for Vue's key
  newEntry._uid = Date.now() + Math.random().toString(16).slice(2)

  // CHANGE: Remove .value (use reactive)
  if (!Array.isArray(formData[key])) {
    formData[key] = []
  }

  // CHANGE: Keep without .value (this was already correct)
  formData[key].push(newEntry)
}

// This function is only for multi-entry fields
function removeItem(key, index) {
  // CHANGE: Remove .value
  formData[key].splice(index, 1)
}

// --- Validation Logic ---
const orcidRegex = /^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/;
const dateRegex = /^\d{4}-\d{2}-\d{2}$/;

function validateForm() {
  const errors = [];
  // CHANGE: Remove .value - formData is already reactive
  const data = formData; // Direct reference to reactive object

  if (!schema.value) {
    errors.push("Schema is not loaded. Cannot validate.")
    return errors;
  }

  // 1. Standard Fields validation
  schema.value.standard_fields.forEach(field => {
    if (!isFieldVisible(field)) return;

    if (isFieldRequired(field) && !data[field.key]) {
      errors.push(`${field.label} is required.`);
    }

    if (field.type === 'date' && data[field.key] && !dateRegex.test(data[field.key])) {
      errors.push(`${field.label} must be in YYYY-MM-DD format.`);
    }

    if (field.key === 'embargo_date' && data[field.key]) {
      try {
        const embargo = new Date(data.embargo_date + 'T00:00:00Z');
        const today = new Date();
        today.setUTCHours(0, 0, 0, 0);
        if (embargo <= today) {
          errors.push("Embargo End Date must be in the future.");
        }
      } catch (e) {
        errors.push("Invalid Embargo End Date.");
      }
    }
  });

  // 2. Complex Fields validation
  for (const key in schema.value.complex_fields) {
    const config = schema.value.complex_fields[key];
    if (!isFieldVisible(config)) continue;

    if (config.allow_multiple !== false) {
      // Multi-entry array (e.g., creators)
      const entries = data[key] || [];

      // Filter out completely empty entries (all fields empty/null)
      const nonEmptyEntries = entries.filter(entry => {
        return Object.values(entry).some(val => val !== null && val !== '' && val !== undefined);
      });

      if (isFieldRequired(config) && nonEmptyEntries.length === 0) {
        errors.push(`At least one ${config.item_label} is required.`);
        continue; // Skip further validation if no entries exist
      }

      // Validate each non-empty entry
      nonEmptyEntries.forEach((entry, index) => {
        config.attributes.forEach(attr => {
          if (attr.mandatory && !entry[attr.key]) {
            errors.push(`${config.item_label} ${index + 1}: ${attr.label} is required.`);
          }
          if (attr.validation_regex && entry[attr.key] && !new RegExp(attr.validation_regex).test(entry[attr.key])) {
            errors.push(`${config.item_label} ${index + 1}: ${attr.validation_message || `Invalid format for ${attr.label}`}`);
          }
        });
      });
    } else {
      // Single-entry object (e.g., journal)
      const entry = data[key] || {};
      let hasData = Object.values(entry).some(val => val !== null && val !== '' && val !== undefined);

      if (isFieldRequired(config) && !hasData) {
        errors.push(`${config.label} is required.`);
        continue;
      }

      // If has data, validate mandatory fields
      if (hasData) {
        config.attributes.forEach(attr => {
          if (attr.mandatory && !entry[attr.key]) {
            errors.push(`${config.label}: ${attr.label} is required.`);
          }
          if (attr.validation_regex && entry[attr.key] && !new RegExp(attr.validation_regex).test(entry[attr.key])) {
            errors.push(`${config.label}: ${attr.validation_message || `Invalid format for ${attr.label}`}`);
          }
        });
      }
    }
  }

  return errors;
}

// --- Navigation ---
const handleBack = async () => {
  if (saving.value) return
  saving.value = true
  stopAutoSave()
  await waitForSave()
  if (!workflowStore.isBatchMode && dirty.value && !await save()) {
    startAutoSave()
    saving.value = false
    return
  }
  workflowStore.prevStep()
  persistWorkflowState(workflowStore, 'files').catch((err) => {
    console.warn('Failed to persist file-review workflow state:', err)
  })
  router.push('/workflow/files')
}

const handleNext = async () => {
  if (workflowStore.isBatchMode) {
    workflowStore.nextStep()
    persistWorkflowState(workflowStore, 'edm_selection').catch((err) => {
      console.warn('Failed to persist EDM workflow state:', err)
    })
    router.push('/workflow/edm-selection')
    return
  }

  saving.value = true
  validationErrors.value = []

  const errors = validateForm()
  if (errors.length > 0) {
    validationErrors.value = errors
    saving.value = false
    return
  }

  try {
    // Prepare clean payload with only visible/relevant fields
    stopAutoSave()
    await waitForSave()
    const cleanPayload = preparePayloadForSubmission()

    await api.put(`/metadata/user/${workflowStore.sessionId}`, cleanPayload)

    workflowStore.setSubmissionMetadata(cleanPayload)
    workflowStore.nextStep()
    persistWorkflowState(workflowStore, 'edm_selection').catch((err) => {
      console.warn('Failed to persist EDM workflow state:', err)
    })
    router.push('/workflow/edm-selection')

  } catch (err) {
    console.error('Failed to save metadata:', err)
    startAutoSave()
    if (err.error?.details?.errors || err.details?.errors) {
      validationErrors.value = err.error?.details?.errors || err.details.errors
    } else {
      validationErrors.value = [err.error?.message || err.message || 'Metadata could not be saved. Your edits remain on this page.']
    }
  } finally {
    saving.value = false
  }
}

// *** ADD THIS HELPER FUNCTION ***
function stripInternalProperties(data) {
  const cleaned = JSON.parse(JSON.stringify(data))

  if (!schema.value?.complex_fields) return cleaned

  for (const key in schema.value.complex_fields) {
    const config = schema.value.complex_fields[key]

    if (config.allow_multiple !== false && Array.isArray(cleaned[key])) {
      // Remove _uid from array entries
      cleaned[key] = cleaned[key].map(entry => {
        const { _uid, ...rest } = entry
        return rest
      })
    }
  }

  return cleaned
}

function preparePayloadForSubmission(data = formData) {
  const payload = {}

  // 1. Filter standard fields based on mandatory_rule visibility
  schema.value?.standard_fields.forEach(field => {
    if (isFieldVisible(field) && data[field.key] !== undefined && data[field.key] !== '') {
      let value = data[field.key]

      // If it's a tags field, split by comma and trim
      if (field.type === 'tags' && typeof value === 'string') {
        value = value.split(',').map(s => s.trim()).filter(s => s !== '')
      }

      payload[field.key] = value
    }
  })

  // 2. Filter complex fields based on mandatory_rule visibility
  if (schema.value?.complex_fields) {
    for (const key in schema.value.complex_fields) {
      const config = schema.value.complex_fields[key]

      // Only include if field is visible
      if (!isFieldVisible(config)) {
        continue
      }

      if (config.allow_multiple !== false) {
        // Multi-entry array (creators, communities, etc.)
        const entries = data[key] || []

        // Filter out completely empty entries and remove _uid
        const cleanedEntries = entries
          .filter(entry => {
            // Keep entry if any field has a value (excluding _uid)
            return Object.entries(entry).some(([k, v]) =>
              k !== '_uid' && v !== null && v !== '' && v !== undefined
            )
          })
          .map(entry => {
            // Remove _uid from each entry
            const { _uid, ...cleanEntry } = entry
            return cleanEntry
          })

        // Only include array if it has entries
        if (cleanedEntries.length > 0) {
          payload[key] = cleanedEntries
        }
      } else {
        // Single-entry object (journal, etc.)
        const entry = data[key] || {}

        // Check if object has any data
        const hasData = Object.values(entry).some(val =>
          val !== null && val !== '' && val !== undefined
        )

        // Only include if has data
        if (hasData) {
          payload[key] = entry
        }
      }
    }
  }

  return payload
}

</script>

<style scoped>
/* Add some spacing to form fields */
.form-field-wrapper {
  padding-bottom: 1rem;
}
</style>
