<template>
  <div class="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
    <div class="px-4 py-6 sm:px-0">
      <div class="flex items-center justify-between mb-6">
        <h1 class="text-2xl font-semibold text-gray-900">EDM Configuration</h1>
        <div class="flex items-center space-x-3">
          <span v-if="saving" class="text-sm text-gray-500">Saving...</span>
          <span v-if="successMessage" class="text-sm text-green-600">{{ successMessage }}</span>
        </div>
      </div>

      <div v-if="loading" class="bg-white shadow overflow-hidden sm:rounded-lg p-6 text-center">
        <p class="text-gray-500 text-sm">Loading configuration...</p>
      </div>

      <div v-else-if="error" class="bg-red-50 border-l-4 border-red-400 p-4 mb-6">
        <div class="flex">
          <div class="ml-3">
            <p class="text-sm text-red-700">{{ error }}</p>
          </div>
        </div>
      </div>

      <div v-else class="space-y-8">
        <div class="bg-white shadow overflow-hidden sm:rounded-lg">
          <div class="px-4 py-5 sm:px-6 flex items-start justify-between gap-4">
            <div>
              <h3 class="text-lg leading-6 font-medium text-gray-900">Local EDM Validator</h3>
              <p class="mt-1 max-w-2xl text-sm text-gray-500">
                Service used for EDM validation during template checks and LOD generation.
              </p>
            </div>
            <button
              @click="loadValidatorStatus"
              :disabled="statusLoading"
              class="inline-flex items-center px-3 py-2 border border-gray-300 shadow-sm text-sm leading-4 font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50"
            >
              {{ statusLoading ? 'Checking...' : 'Refresh' }}
            </button>
          </div>
          <div class="border-t border-gray-200 px-4 py-5 sm:px-6">
            <div v-if="validatorStatusError" class="rounded-md bg-red-50 p-4 text-sm text-red-700">
              {{ validatorStatusError }}
            </div>
            <dl v-else class="grid grid-cols-1 gap-4 sm:grid-cols-4">
              <div class="rounded-md bg-gray-50 p-4">
                <dt class="text-xs font-semibold uppercase tracking-wide text-gray-500">Feature</dt>
                <dd :class="['mt-1 text-sm font-semibold', validatorStatus?.enabled ? 'text-green-700' : 'text-gray-600']">
                  {{ validatorStatus?.enabled ? 'Enabled' : 'Disabled' }}
                </dd>
              </div>
              <div class="rounded-md bg-gray-50 p-4 sm:col-span-2">
                <dt class="text-xs font-semibold uppercase tracking-wide text-gray-500">Endpoint</dt>
                <dd class="mt-1 break-all text-sm text-gray-900">{{ validatorStatus?.url || 'Not configured' }}</dd>
              </div>
              <div class="rounded-md bg-gray-50 p-4">
                <dt class="text-xs font-semibold uppercase tracking-wide text-gray-500">Health</dt>
                <dd :class="['mt-1 text-sm font-semibold', validatorStatus?.health?.ok ? 'text-green-700' : 'text-red-700']">
                  {{ validatorStatus?.health?.ok ? 'Reachable' : 'Unavailable' }}
                </dd>
                <p v-if="validatorStatus?.health?.response_time_millis !== undefined" class="mt-1 text-xs text-gray-500">
                  {{ validatorStatus.health.response_time_millis }} ms
                </p>
              </div>
            </dl>
            <dl v-if="validatorInfoSummary" class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-4">
              <div class="rounded-md bg-gray-50 p-4">
                <dt class="text-xs font-semibold uppercase text-gray-500">Version</dt>
                <dd class="mt-1 break-all text-sm text-gray-900">
                  {{ validatorInfoSummary.version || 'Unknown' }}
                </dd>
              </div>
              <div class="rounded-md bg-gray-50 p-4">
                <dt class="text-xs font-semibold uppercase text-gray-500">Commit</dt>
                <dd class="mt-1 break-all text-sm text-gray-900">
                  {{ validatorInfoSummary.git_commit_short || validatorInfoSummary.source_ref || 'Unknown' }}
                </dd>
              </div>
              <div class="rounded-md bg-gray-50 p-4">
                <dt class="text-xs font-semibold uppercase text-gray-500">Build</dt>
                <dd class="mt-1 break-all text-sm text-gray-900">
                  {{ validatorInfoSummary.build_time || validatorInfoSummary.git_commit_time || 'Unknown' }}
                </dd>
              </div>
              <div class="rounded-md bg-gray-50 p-4">
                <dt class="text-xs font-semibold uppercase text-gray-500">Image</dt>
                <dd class="mt-1 break-all text-sm text-gray-900">
                  {{ validatorInfoSummary.image_tag || 'Unknown' }}
                </dd>
              </div>
            </dl>
            <p v-if="validatorStatus?.health?.message" class="mt-3 text-sm text-red-600">
              {{ validatorStatus.health.message }}
            </p>
            <p v-if="validatorStatus?.info?.message" class="mt-3 text-sm text-amber-700">
              Version metadata unavailable: {{ validatorStatus.info.message }}
            </p>
          </div>
        </div>

        <!-- Type Mappings Form -->
        <div class="bg-white shadow overflow-hidden sm:rounded-lg">
          <div class="px-4 py-5 sm:px-6">
            <h3 class="text-lg leading-6 font-medium text-gray-900">Type Mappings</h3>
            <p class="mt-1 max-w-2xl text-sm text-gray-500">
              Map Zenodo upload types to EDM object types.
            </p>
          </div>

          <div class="border-t border-gray-200">
            <div class="bg-gray-50 px-4 py-2 text-sm font-semibold text-gray-700">Object Type Definitions</div>

            <div class="divide-y divide-gray-200">
              <div v-for="(edmType, zenodoType) in config.types" :key="zenodoType" class="py-4 sm:py-5 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                <label class="text-sm font-medium text-gray-500 capitalize">{{ zenodoType }}</label>
                <div class="mt-1 sm:mt-0 sm:col-span-2">
                  <select v-model="config.types[zenodoType]" class="max-w-lg block focus:ring-indigo-500 focus:border-indigo-500 w-full shadow-sm sm:max-w-xs sm:text-sm border-gray-300 rounded-md">
                    <option value="TEXT">TEXT</option>
                    <option value="VIDEO">VIDEO</option>
                    <option value="SOUND">SOUND</option>
                    <option value="IMAGE">IMAGE</option>
                    <option value="3D">3D</option>
                  </select>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- License Mappings Form -->
        <div class="bg-white shadow overflow-hidden sm:rounded-lg">
          <div class="px-4 py-5 sm:px-6">
            <h3 class="text-lg leading-6 font-medium text-gray-900">License URIs</h3>
            <p class="mt-1 max-w-2xl text-sm text-gray-500">
              Map Zenodo license IDs to legal URI statements.
            </p>
          </div>

          <div class="border-t border-gray-200">
            <div class="bg-gray-50 px-4 py-2 text-sm font-semibold text-gray-700">License Definitions</div>

            <div class="divide-y divide-gray-200">
              <div v-for="(uri, licenseId) in config.licenses" :key="licenseId" class="py-4 sm:py-5 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
                <label class="text-sm font-medium text-gray-500 capitalize">{{ licenseId }}</label>
                <div class="mt-1 sm:mt-0 sm:col-span-2">
                  <input
                    type="text"
                    v-model="config.licenses[licenseId]"
                    class="max-w-lg block w-full shadow-sm focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm border-gray-300 rounded-md"
                  />
                </div>
              </div>

              <!-- Add New License Row -->
              <div class="py-4 sm:py-5 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6 bg-indigo-50/30">
                <div class="text-sm font-medium text-indigo-700">Add New License</div>
                <div class="mt-1 sm:mt-0 sm:col-span-2">
                  <div class="flex gap-4">
                    <input v-model="newLicenseKey" placeholder="License ID (e.g. cc-by-nc)" class="flex-1 shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md">
                    <input v-model="newLicenseUri" placeholder="URI" class="flex-[2] shadow-sm focus:ring-indigo-500 focus:border-indigo-500 block w-full sm:text-sm border-gray-300 rounded-md">
                    <button @click="addLicense" class="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500">
                      Add
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="px-4 py-3 bg-gray-50 text-right sm:px-6 border-t border-gray-200">
            <button
              @click="saveConfig"
              :disabled="saving"
              class="inline-flex justify-center py-2 px-4 border border-transparent shadow-sm text-sm font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50"
            >
              Save Configuration
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import api from '@/services/api'
import { useToast } from '@/composables/useToast'

const toast = useToast()

const loading = ref(true)
const saving = ref(false)
const error = ref(null)
const successMessage = ref('')
const config = ref({ types: {}, licenses: {} })
const newLicenseKey = ref('')
const newLicenseUri = ref('')
const validatorStatus = ref(null)
const validatorStatusError = ref('')
const statusLoading = ref(false)
const validatorInfoSummary = computed(() => {
  const summary = validatorStatus.value?.info?.summary
  return summary && Object.keys(summary).some((key) => summary[key]) ? summary : null
})

// Load existing config
async function loadConfig() {
  loading.value = true
  error.value = null
  try {
    const res = await api.get('/admin/edm-config')
    if (res.success) {
      config.value = res.data.config
    } else {
      error.value = res.message
    }
  } catch (err) {
    error.value = err.message || 'Failed to load configuration'
  } finally {
    loading.value = false
  }
}

async function loadValidatorStatus() {
  statusLoading.value = true
  validatorStatusError.value = ''
  try {
    const res = await api.get('/admin/edm-validator/status')
    if (res.success) {
      validatorStatus.value = res.data
    } else {
      validatorStatusError.value = res.message || 'Failed to load validator status'
    }
  } catch (err) {
    validatorStatusError.value = err.message || 'Failed to load validator status'
  } finally {
    statusLoading.value = false
  }
}

// Save config
async function saveConfig() {
  saving.value = true
  successMessage.value = ''
  try {
    const payload = {
        types: config.value.types,
        licenses: config.value.licenses
    }
    const res = await api.post('/admin/edm-config', payload)
    if (res.success) {
      toast.success('Configuration saved successfully!')
      successMessage.value = 'Saved!'
      setTimeout(() => successMessage.value = '', 3000)
    } else {
      toast.error('Failed to save: ' + res.message)
    }
  } catch (err) {
    toast.error('Error saving configuration: ' + err.message)
  } finally {
    saving.value = false
  }
}

function addLicense() {
    if (newLicenseKey.value && newLicenseUri.value) {
        config.value.licenses[newLicenseKey.value] = newLicenseUri.value
        newLicenseKey.value = ''
        newLicenseUri.value = ''
        toast.info('License mapping added. Remember to save.')
    }
}

onMounted(() => {
  loadConfig()
  loadValidatorStatus()
})
</script>
