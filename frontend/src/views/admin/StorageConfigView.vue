<template>
  <div class="max-w-4xl mx-auto py-6 sm:px-6 lg:px-8">
    <div class="px-4 py-6 sm:px-0">
      <h1 class="text-2xl font-semibold text-gray-900 mb-2">Storage Configuration</h1>
      <p class="text-gray-500 mb-6">Configure cloud storage priority for batch uploads.</p>

      <!-- Loading State -->
      <div v-if="loading" class="flex justify-center py-12">
        <svg class="animate-spin h-8 w-8 text-indigo-600" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
      </div>

      <!-- Main Content -->
      <div v-else class="space-y-6">
        <!-- Current Storage Status -->
        <div class="bg-white shadow overflow-hidden sm:rounded-lg">
          <div class="px-4 py-5 sm:px-6 border-b border-gray-200">
            <h3 class="text-lg leading-6 font-medium text-gray-900">Current Storage Status</h3>
            <p class="mt-1 text-sm text-gray-500">Active storage and service availability.</p>
          </div>
          <div class="px-4 py-5 sm:px-6 space-y-4">
            <!-- Active Storage -->
            <div class="flex items-center space-x-3">
              <span class="text-sm font-medium text-gray-700">Active Storage:</span>
              <span :class="[
                'px-2 py-1 text-xs font-semibold rounded-full',
                status.active_storage === 'dropbox' ? 'bg-blue-100 text-blue-800' :
                status.active_storage === 'gdrive' ? 'bg-green-100 text-green-800' :
                status.active_storage === 'server' ? 'bg-yellow-100 text-yellow-800' :
                'bg-red-100 text-red-800'
              ]">
                {{ formatStorageType(status.active_storage) }}
              </span>
              <span class="text-sm text-gray-500">{{ status.active_message }}</span>
            </div>

            <!-- Service Status -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <!-- Dropbox Status -->
              <div class="flex items-center space-x-3 p-3 rounded-lg" :class="status.services?.dropbox?.available ? 'bg-green-50' : 'bg-red-50'">
                <svg class="h-6 w-6 text-blue-600" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M6 2l6 3.75L6 9.5 0 5.75 6 2zm12 0l6 3.75L18 9.5l-6-3.75L18 2zM0 13.25L6 9.5l6 3.75-6 3.75-6-3.75zm18-3.75l6 3.75-6 3.75-6-3.75 6-3.75zM6 17.5l6-3.75 6 3.75-6 3.75-6-3.75z"/>
                </svg>
                <div>
                  <p class="text-sm font-medium" :class="status.services?.dropbox?.available ? 'text-green-800' : 'text-red-800'">
                    Dropbox: {{ status.services?.dropbox?.available ? 'Available' : 'Unavailable' }}
                  </p>
                  <p class="text-xs text-gray-600">{{ status.services?.dropbox?.message }}</p>
                </div>
              </div>

              <!-- Google Drive Status -->
              <div class="flex items-center space-x-3 p-3 rounded-lg" :class="status.services?.gdrive?.available ? 'bg-green-50' : 'bg-red-50'">
                <svg class="h-6 w-6 text-blue-500" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M7.71 3.5l-5.71 10 2.74 4.75L10.45 8.5 7.71 3.5zm9.08 0h-5.58l5.71 10h5.58l-5.71-10zm-6.29 10l-2.74 4.75h10.58L21.08 13.5H10.5z"/>
                </svg>
                <div>
                  <p class="text-sm font-medium" :class="status.services?.gdrive?.available ? 'text-green-800' : 'text-red-800'">
                    Google Drive: {{ status.services?.gdrive?.available ? 'Available' : 'Unavailable' }}
                  </p>
                  <p class="text-xs text-gray-600">{{ status.services?.gdrive?.message }}</p>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Configuration Form -->
        <div class="bg-white shadow overflow-hidden sm:rounded-lg">
          <div class="px-4 py-5 sm:px-6 border-b border-gray-200">
            <h3 class="text-lg leading-6 font-medium text-gray-900">Storage Priority</h3>
            <p class="mt-1 text-sm text-gray-500">Configure which storage to use for batch uploads.</p>
          </div>
          <div class="px-4 py-5 sm:px-6 space-y-6">
            <!-- Primary Storage -->
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">Primary Storage</label>
              <select
                v-model="config.primary_storage"
                class="mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm rounded-md"
              >
                <option value="dropbox">Dropbox</option>
                <option value="gdrive">Google Drive</option>
              </select>
              <p class="mt-1 text-xs text-gray-500">First choice for file storage.</p>
            </div>

            <!-- Secondary Storage -->
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-2">Secondary Storage</label>
              <select
                v-model="config.secondary_storage"
                class="mt-1 block w-full pl-3 pr-10 py-2 text-base border-gray-300 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm rounded-md"
              >
                <option value="dropbox">Dropbox</option>
                <option value="gdrive">Google Drive</option>
              </select>
              <p class="mt-1 text-xs text-gray-500">Used when primary is unavailable.</p>
            </div>

            <!-- Server Fallback Toggle -->
            <div class="flex items-center justify-between">
              <div>
                <label class="block text-sm font-medium text-gray-700">Allow Server Fallback</label>
                <p class="text-xs text-gray-500">Use server storage if no cloud storage is available.</p>
              </div>
              <button
                @click="config.allow_server_fallback = !config.allow_server_fallback"
                :class="[
                  'relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2',
                  config.allow_server_fallback ? 'bg-indigo-600' : 'bg-gray-200'
                ]"
              >
                <span
                  :class="[
                    'pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out',
                    config.allow_server_fallback ? 'translate-x-5' : 'translate-x-0'
                  ]"
                ></span>
              </button>
            </div>

            <!-- Storage Mode Selection -->
            <div class="border-t border-gray-200 pt-6">
              <label class="block text-sm font-medium text-gray-700 mb-3">Storage Mode</label>
              <div class="space-y-3">
                <!-- Pure Cloud Option -->
                <label class="flex items-start p-4 border rounded-lg cursor-pointer transition-colors"
                  :class="config.storage_mode === 'pure_cloud' ? 'border-indigo-500 bg-indigo-50' : 'border-gray-200 hover:border-gray-300'"
                >
                  <input type="radio" v-model="config.storage_mode" value="pure_cloud" class="mt-1 text-indigo-600 focus:ring-indigo-500">
                  <div class="ml-3">
                    <span class="block text-sm font-medium text-gray-900">Pure Cloud (Recommended)</span>
                    <span class="block text-xs text-gray-500 mt-1">
                      Files are uploaded directly to cloud storage. Minimal server storage used only during processing.
                      <strong class="text-green-600">Best for large files (up to 100GB).</strong>
                    </span>
                  </div>
                </label>

                <!-- Cloud Backup Option -->
                <label class="flex items-start p-4 border rounded-lg cursor-pointer transition-colors"
                  :class="config.storage_mode === 'cloud_backup' ? 'border-indigo-500 bg-indigo-50' : 'border-gray-200 hover:border-gray-300'"
                >
                  <input type="radio" v-model="config.storage_mode" value="cloud_backup" class="mt-1 text-indigo-600 focus:ring-indigo-500">
                  <div class="ml-3">
                    <span class="block text-sm font-medium text-gray-900">Cloud Backup</span>
                    <span class="block text-xs text-gray-500 mt-1">
                      Files are stored on server AND backed up to cloud storage. Uses more server disk space.
                    </span>
                  </div>
                </label>

                <!-- Server Only Option -->
                <label class="flex items-start p-4 border rounded-lg cursor-pointer transition-colors"
                  :class="config.storage_mode === 'server_only' ? 'border-indigo-500 bg-indigo-50' : 'border-gray-200 hover:border-gray-300'"
                >
                  <input type="radio" v-model="config.storage_mode" value="server_only" class="mt-1 text-indigo-600 focus:ring-indigo-500">
                  <div class="ml-3">
                    <span class="block text-sm font-medium text-gray-900">Server Only</span>
                    <span class="block text-xs text-gray-500 mt-1">
                      Files are stored only on the server. No cloud storage used.
                    </span>
                  </div>
                </label>

                <!-- Local Storage (HPC Mode) -->
                <label class="flex items-start p-4 border rounded-lg cursor-pointer transition-colors"
                  :class="config.storage_mode === 'local' ? 'border-indigo-500 bg-indigo-50' : 'border-gray-200 hover:border-gray-300'"
                >
                  <input type="radio" v-model="config.storage_mode" value="local" class="mt-1 text-indigo-600 focus:ring-indigo-500">
                  <div class="ml-3">
                    <span class="block text-sm font-medium text-gray-900">Local Storage (HPC Mode)</span>
                    <span class="block text-xs text-gray-500 mt-1">
                      Direct local path access for input and output. Bypasses cloud upload.
                      <strong class="text-indigo-600">Requires environment configuration.</strong>
                    </span>
                  </div>
                </label>
              </div>
            </div>

            <!-- Warning for Pure Cloud mode -->
            <div v-if="config.storage_mode === 'pure_cloud' && !status.services?.dropbox?.available && !status.services?.gdrive?.available" class="bg-red-50 border-l-4 border-red-400 p-4">
              <div class="flex">
                <div class="flex-shrink-0">
                  <svg class="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/>
                  </svg>
                </div>
                <div class="ml-3">
                  <p class="text-sm text-red-700">
                    <strong>Error:</strong> Pure Cloud mode requires cloud storage, but no cloud service is available. Configure Dropbox or Google Drive first.
                  </p>
                </div>
              </div>
            </div>

            <!-- Save Button -->
            <div class="flex justify-end space-x-3">
              <button
                @click="refreshStatus"
                :disabled="saving"
                class="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
              >
                Refresh Status
              </button>
              <button
                @click="saveConfig"
                :disabled="saving"
                class="px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50"
              >
                {{ saving ? 'Saving...' : 'Save Configuration' }}
              </button>
            </div>
          </div>
        </div>

        <!-- Success/Error Messages -->
        <div v-if="message" :class="[
          'rounded-md p-4',
          messageType === 'success' ? 'bg-green-50' : 'bg-red-50'
        ]">
          <div class="flex">
            <div class="flex-shrink-0">
              <svg v-if="messageType === 'success'" class="h-5 w-5 text-green-400" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
              </svg>
              <svg v-else class="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/>
              </svg>
            </div>
            <div class="ml-3">
              <p :class="[
                'text-sm font-medium',
                messageType === 'success' ? 'text-green-800' : 'text-red-800'
              ]">
                {{ message }}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import api from '@/services/api'

const loading = ref(true)
const saving = ref(false)
const message = ref('')
const messageType = ref('success')

const config = reactive({
  primary_storage: 'dropbox',
  secondary_storage: 'gdrive',
  allow_server_fallback: false,
  storage_mode: 'pure_cloud'
})

const status = reactive({
  active_storage: null,
  active_message: '',
  services: {
    dropbox: { available: false, message: '' },
    gdrive: { available: false, message: '' }
  }
})

const formatStorageType = (type) => {
  const types = {
    dropbox: 'Dropbox',
    gdrive: 'Google Drive',
    server: 'Server / Local'
  }
  return types[type] || type || 'None'
}

const loadData = async () => {
  loading.value = true
  try {
    // Load both config and status
    const [configRes, statusRes] = await Promise.all([
      api.get('/admin/storage-config'),
      api.get('/admin/storage-status')
    ])

    // Update config
    if (configRes.data?.config) {
      Object.assign(config, configRes.data.config)
    }

    // Update status
    if (statusRes.data) {
      status.active_storage = statusRes.data.active_storage
      status.active_message = statusRes.data.active_message
      if (statusRes.data.services) {
        status.services = statusRes.data.services
      }
    }
  } catch (error) {
    console.error('Failed to load storage data:', error)
    message.value = 'Failed to load storage configuration'
    messageType.value = 'error'
  } finally {
    loading.value = false
  }
}

const refreshStatus = async () => {
  try {
    const response = await api.get('/admin/storage-status')
    if (response.data) {
      status.active_storage = response.data.active_storage
      status.active_message = response.data.active_message
      if (response.data.services) {
        status.services = response.data.services
      }
    }
    message.value = 'Status refreshed'
    messageType.value = 'success'
  } catch (error) {
    console.error('Failed to refresh status:', error)
    message.value = 'Failed to refresh status'
    messageType.value = 'error'
  }

  // Clear message after 3 seconds
  setTimeout(() => { message.value = '' }, 3000)
}

const saveConfig = async () => {
  saving.value = true
  message.value = ''

  try {
    await api.post('/admin/storage-config', {
      primary_storage: config.primary_storage,
      secondary_storage: config.secondary_storage,
      allow_server_fallback: config.allow_server_fallback,
      storage_mode: config.storage_mode
    })

    message.value = 'Configuration saved successfully'
    messageType.value = 'success'

    // Refresh status after saving
    await refreshStatus()
  } catch (error) {
    console.error('Failed to save configuration:', error)
    message.value = error.response?.data?.error || 'Failed to save configuration'
    messageType.value = 'error'
  } finally {
    saving.value = false
  }
}

onMounted(loadData)
</script>
