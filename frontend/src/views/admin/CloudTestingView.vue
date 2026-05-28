<template>
  <div class="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
    <div class="px-4 py-6 sm:px-0">
      <h1 class="text-2xl font-semibold text-gray-900 mb-2">Cloud Storage Testing</h1>
      <p class="text-gray-500 mb-6">Verify connectivity to external cloud storage services.</p>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-6">

        <!-- Google Drive Test Card -->
        <div class="bg-white shadow overflow-hidden sm:rounded-lg">
          <div class="px-4 py-5 sm:px-6 border-b border-gray-200">
            <div class="flex items-center">
              <div class="flex-shrink-0">
                <svg class="h-8 w-8 text-blue-500" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M7.71 3.5l-5.71 10 2.74 4.75L10.45 8.5 7.71 3.5zm9.08 0h-5.58l5.71 10h5.58l-5.71-10zm-6.29 10l-2.74 4.75h10.58L21.08 13.5H10.5z"/>
                </svg>
              </div>
              <div class="ml-4">
                <h3 class="text-lg leading-6 font-medium text-gray-900">Google Drive</h3>
                <p class="text-sm text-gray-500">Service Account Authentication</p>
              </div>
            </div>
          </div>

          <div class="px-4 py-5 sm:px-6">
            <!-- Status Display -->
            <div v-if="gdrive.status === 'idle'" class="flex items-center text-gray-500 mb-4">
              <span class="h-3 w-3 bg-gray-300 rounded-full mr-2"></span>
              Not tested yet
            </div>
            <div v-else-if="gdrive.status === 'testing'" class="flex items-center text-blue-600 mb-4">
              <svg class="animate-spin h-4 w-4 mr-2" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              Testing connection...
            </div>
            <div v-else-if="gdrive.status === 'success'" class="flex items-center text-green-600 mb-4">
              <svg class="h-5 w-5 mr-2" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
              </svg>
              Connected successfully
            </div>
            <div v-else-if="gdrive.status === 'error'" class="flex items-center text-red-600 mb-4">
              <svg class="h-5 w-5 mr-2" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/>
              </svg>
              Connection failed
            </div>

            <!-- Result Details -->
            <div v-if="gdrive.result" class="bg-gray-50 rounded-md p-4 mb-4">
              <p class="text-sm text-gray-700 mb-2">{{ gdrive.result.message }}</p>
              <div v-if="gdrive.result.details && gdrive.result.success" class="text-xs text-gray-500 space-y-1">
                <p><span class="font-medium">Folder ID:</span> {{ gdrive.result.details.folder_id }}</p>
                <p><span class="font-medium">Files Found:</span> {{ gdrive.result.details.files_found }}</p>
                <div v-if="gdrive.result.details.sample_files?.length" class="mt-2">
                  <p class="font-medium mb-1">Sample Files:</p>
                  <ul class="list-disc list-inside">
                    <li v-for="file in gdrive.result.details.sample_files" :key="file.name" class="truncate">
                      {{ file.name }}
                    </li>
                  </ul>
                </div>
              </div>
            </div>

            <button
              @click="testGoogleDrive"
              :disabled="gdrive.status === 'testing'"
              class="w-full inline-flex justify-center items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <svg v-if="gdrive.status !== 'testing'" class="h-4 w-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
              </svg>
              {{ gdrive.status === 'testing' ? 'Testing...' : 'Test Connection' }}
            </button>
          </div>
        </div>

        <!-- Dropbox Test Card -->
        <div class="bg-white shadow overflow-hidden sm:rounded-lg">
          <div class="px-4 py-5 sm:px-6 border-b border-gray-200">
            <div class="flex items-center">
              <div class="flex-shrink-0">
                <svg class="h-8 w-8 text-blue-600" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M6 2l6 3.75L6 9.5 0 5.75 6 2zm12 0l6 3.75L18 9.5l-6-3.75L18 2zM0 13.25L6 9.5l6 3.75-6 3.75-6-3.75zm18-3.75l6 3.75-6 3.75-6-3.75 6-3.75zM6 17.5l6-3.75 6 3.75-6 3.75-6-3.75z"/>
                </svg>
              </div>
              <div class="ml-4">
                <h3 class="text-lg leading-6 font-medium text-gray-900">Dropbox</h3>
                <p class="text-sm text-gray-500">Refresh Token Authentication</p>
              </div>
            </div>
          </div>

          <div class="px-4 py-5 sm:px-6">
            <!-- Status Display -->
            <div v-if="dropbox.status === 'idle'" class="flex items-center text-gray-500 mb-4">
              <span class="h-3 w-3 bg-gray-300 rounded-full mr-2"></span>
              Not tested yet
            </div>
            <div v-else-if="dropbox.status === 'testing'" class="flex items-center text-blue-600 mb-4">
              <svg class="animate-spin h-4 w-4 mr-2" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              Testing connection...
            </div>
            <div v-else-if="dropbox.status === 'success'" class="flex items-center text-green-600 mb-4">
              <svg class="h-5 w-5 mr-2" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
              </svg>
              Connected successfully
            </div>
            <div v-else-if="dropbox.status === 'error'" class="flex items-center text-red-600 mb-4">
              <svg class="h-5 w-5 mr-2" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/>
              </svg>
              Connection failed
            </div>

            <!-- Result Details -->
            <div v-if="dropbox.result" class="bg-gray-50 rounded-md p-4 mb-4">
              <p class="text-sm text-gray-700 mb-2">{{ dropbox.result.message }}</p>
              <div v-if="dropbox.result.details && dropbox.result.success" class="text-xs text-gray-500 space-y-1">
                <p><span class="font-medium">Account:</span> {{ dropbox.result.details.account_name }}</p>
                <p><span class="font-medium">Email:</span> {{ dropbox.result.details.email }}</p>
                <div class="mt-2">
                  <p class="font-medium mb-1">Storage Usage:</p>
                  <div class="w-full bg-gray-200 rounded-full h-2">
                    <div
                      class="bg-blue-600 h-2 rounded-full"
                      :style="{ width: `${Math.min(dropbox.result.details.storage_percentage, 100)}%` }"
                    ></div>
                  </div>
                  <p class="mt-1">{{ dropbox.result.details.storage_used_gb }} GB / {{ dropbox.result.details.storage_allocated_gb }} GB ({{ dropbox.result.details.storage_percentage }}%)</p>
                </div>
              </div>
            </div>

            <button
              @click="testDropbox"
              :disabled="dropbox.status === 'testing'"
              class="w-full inline-flex justify-center items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <svg v-if="dropbox.status !== 'testing'" class="h-4 w-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
              </svg>
              {{ dropbox.status === 'testing' ? 'Testing...' : 'Test Connection' }}
            </button>
          </div>
        </div>
      </div>

      <!-- Test All Button -->
      <div class="mt-6">
        <button
          @click="testAll"
          :disabled="gdrive.status === 'testing' || dropbox.status === 'testing'"
          class="inline-flex items-center px-6 py-3 border border-transparent text-base font-medium rounded-md shadow-sm text-white bg-gray-800 hover:bg-gray-900 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-500 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <svg class="h-5 w-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          Test All Services
        </button>
      </div>

      <!-- Info Panel -->
      <div class="mt-8 bg-blue-50 border-l-4 border-blue-400 p-4 rounded-r">
        <div class="flex">
          <div class="flex-shrink-0">
            <svg class="h-5 w-5 text-blue-400" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"/>
            </svg>
          </div>
          <div class="ml-3">
            <h3 class="text-sm font-medium text-blue-800">About Cloud Storage Tests</h3>
            <div class="mt-2 text-sm text-blue-700">
              <ul class="list-disc list-inside space-y-1">
                <li><strong>Google Drive:</strong> Uses Service Account credentials to access shared folders.</li>
                <li><strong>Dropbox:</strong> Uses OAuth refresh token for persistent API access.</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive } from 'vue'
import api from '@/services/api'

const gdrive = reactive({
  status: 'idle', // idle, testing, success, error
  result: null
})

const dropbox = reactive({
  status: 'idle',
  result: null
})

const testGoogleDrive = async () => {
  gdrive.status = 'testing'
  gdrive.result = null

  try {
    const response = await api.get('/admin/cloud/test/gdrive')
    gdrive.result = response.data
    gdrive.status = response.data.success ? 'success' : 'error'
  } catch (error) {
    console.error('Google Drive test failed:', error)
    gdrive.result = {
      success: false,
      message: error.error?.message || error.message || 'Connection test failed',
      details: {}
    }
    gdrive.status = 'error'
  }
}

const testDropbox = async () => {
  dropbox.status = 'testing'
  dropbox.result = null

  try {
    const response = await api.get('/admin/cloud/test/dropbox')
    dropbox.result = response.data
    dropbox.status = response.data.success ? 'success' : 'error'
  } catch (error) {
    console.error('Dropbox test failed:', error)
    dropbox.result = {
      success: false,
      message: error.error?.message || error.message || 'Connection test failed',
      details: {}
    }
    dropbox.status = 'error'
  }
}

const testAll = () => {
  testGoogleDrive()
  testDropbox()
}
</script>
