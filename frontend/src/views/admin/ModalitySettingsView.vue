<template>
  <div class="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
    <div class="px-4 py-6 sm:px-0">
      <div class="flex items-center justify-between mb-6">
        <h1 class="text-2xl font-semibold text-gray-900">Modality Detection Rules</h1>
        <div class="flex items-center space-x-3">
          <span v-if="saving" class="text-sm text-gray-500 text-animate-pulse">Saving...</span>
          <span v-if="successMessage" class="text-sm text-green-600 font-medium">{{ successMessage }}</span>
        </div>
      </div>

      <div v-if="loading" class="bg-white/50 backdrop-blur-sm shadow overflow-hidden sm:rounded-2xl p-12 text-center border border-gray-100">
        <div class="animate-spin rounded-full h-10 w-10 border-b-2 border-indigo-600 mx-auto mb-4"></div>
        <p class="text-gray-500 text-sm font-medium">Loading configuration...</p>
      </div>

      <div v-else-if="error" class="bg-red-50 border-l-4 border-red-400 p-4 mb-6 rounded-r-xl">
        <div class="flex">
          <div class="ml-3">
            <p class="text-sm text-red-700 font-medium">{{ error }}</p>
          </div>
        </div>
      </div>

      <div v-else class="space-y-8">
        <!-- Extension Mappings -->
        <div class="bg-white shadow-xl shadow-gray-200/50 overflow-hidden sm:rounded-2xl border border-gray-100">
          <div class="px-6 py-5 border-b border-gray-100 bg-gray-50/50">
            <h3 class="text-lg leading-6 font-bold text-gray-900">File Extension Rules</h3>
            <p class="mt-1 max-w-2xl text-xs text-gray-500 font-medium">
              Map file extensions to internal modality categories.
            </p>
          </div>

          <div class="overflow-x-auto">
            <table class="min-w-full divide-y divide-gray-200">
              <thead class="bg-gray-50">
                <tr>
                  <th scope="col" class="px-6 py-3 text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider">Extension</th>
                  <th scope="col" class="px-6 py-3 text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider">Internal Category</th>
                  <th scope="col" class="relative px-6 py-3"><span class="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody class="bg-white divide-y divide-gray-100">
                <tr v-for="(category, ext) in configData.combined.extensions" :key="ext" :class="['hover:bg-gray-50/50 transition-colors', isOverride('extensions', ext) ? 'bg-indigo-50/30' : '']">
                  <td class="px-6 py-4 whitespace-nowrap flex items-center gap-2">
                    <span class="text-xs font-mono font-bold text-indigo-600">.{{ ext }}</span>
                    <span v-if="isOverride('extensions', ext)" class="inline-flex items-center px-1.5 py-0.5 rounded-full text-[8px] font-bold bg-indigo-100 text-indigo-700 uppercase tracking-tighter">Custom</span>
                  </td>
                  <td class="px-6 py-4 whitespace-nowrap">
                    <select v-model="configData.combined.extensions[ext]" @change="addExtensionOverride(ext, configData.combined.extensions[ext])" class="block w-full pl-3 pr-10 py-1.5 text-xs border-gray-200 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 rounded-lg transition-all">
                      <option v-for="cat in categories" :key="cat" :value="cat">{{ cat }}</option>
                    </select>
                  </td>
                  <td class="px-6 py-4 whitespace-nowrap text-right text-xs font-medium">
                    <button @click="removeExtension(ext)" class="text-red-400 hover:text-red-600 transition-colors">
                        <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                    </button>
                  </td>
                </tr>
                <!-- Add Row -->
                <tr class="bg-indigo-50/20">
                  <td class="px-6 py-3">
                    <input v-model="newExt" type="text" placeholder="e.g. obj" class="block w-full px-3 py-1.5 text-xs border-gray-200 focus:ring-indigo-500 focus:border-indigo-500 rounded-lg" />
                  </td>
                  <td class="px-6 py-3">
                    <select v-model="newExtCat" class="block w-full px-3 py-1.5 text-xs border-gray-200 focus:ring-indigo-500 focus:border-indigo-500 rounded-lg">
                      <option value="" disabled>Select Category...</option>
                      <option v-for="cat in categories" :key="cat" :value="cat">{{ cat }}</option>
                    </select>
                  </td>
                  <td class="px-6 py-3 text-right">
                    <button @click="addExtension" :disabled="!newExt || !newExtCat" class="inline-flex items-center px-3 py-1.5 border border-transparent text-[10px] font-bold uppercase tracking-wider rounded-lg text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 transition-all">
                      Add
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- Zenodo Type Mappings -->
        <div class="bg-white shadow-xl shadow-gray-200/50 overflow-hidden sm:rounded-2xl border border-gray-100">
          <div class="px-6 py-5 border-b border-gray-100 bg-gray-50/50">
            <h3 class="text-lg leading-6 font-bold text-gray-900">Zenodo Type Rules</h3>
            <p class="mt-1 max-w-2xl text-xs text-gray-500 font-medium">
              Map Zenodo record types to EDM modalities.
            </p>
          </div>

          <div class="overflow-x-auto">
            <table class="min-w-full divide-y divide-gray-200">
              <thead class="bg-gray-50">
                <tr>
                  <th scope="col" class="px-6 py-3 text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider">Zenodo Type</th>
                  <th scope="col" class="px-6 py-3 text-left text-[10px] font-bold text-gray-400 uppercase tracking-wider">EDM Modality</th>
                  <th scope="col" class="relative px-6 py-3"><span class="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody class="bg-white divide-y divide-gray-100">
                <tr v-for="(edmType, zType) in configData.combined.zenodo_types" :key="zType" :class="['hover:bg-gray-50/50 transition-colors', isOverride('zenodo_types', zType) ? 'bg-indigo-50/30' : '']">
                  <td class="px-6 py-4 whitespace-nowrap flex items-center gap-2">
                    <span class="text-xs font-semibold text-gray-700 capitalize">{{ zType }}</span>
                    <span v-if="isOverride('zenodo_types', zType)" class="inline-flex items-center px-1.5 py-0.5 rounded-full text-[8px] font-bold bg-indigo-100 text-indigo-700 uppercase tracking-tighter">Custom</span>
                  </td>
                  <td class="px-6 py-4 whitespace-nowrap">
                    <select v-model="configData.combined.zenodo_types[zType]" @change="addZenodoOverride(zType, configData.combined.zenodo_types[zType])" class="block w-full pl-3 pr-10 py-1.5 text-xs border-gray-200 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 rounded-lg transition-all">
                      <option v-for="mod in modalities" :key="mod" :value="mod">{{ mod }}</option>
                    </select>
                  </td>
                  <td class="px-6 py-4 whitespace-nowrap text-right text-xs font-medium">
                    <button @click="removeZenodoType(zType)" class="text-red-400 hover:text-red-600 transition-colors">
                        <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                    </button>
                  </td>
                </tr>
                <!-- Add Row -->
                <tr class="bg-indigo-50/20">
                  <td class="px-6 py-3">
                    <input v-model="newZType" type="text" placeholder="e.g. software" class="block w-full px-3 py-1.5 text-xs border-gray-200 focus:ring-indigo-500 focus:border-indigo-500 rounded-lg" />
                  </td>
                  <td class="px-6 py-3">
                    <select v-model="newZMod" class="block w-full px-3 py-1.5 text-xs border-gray-200 focus:ring-indigo-500 focus:border-indigo-500 rounded-lg">
                      <option value="" disabled>Select Modality...</option>
                      <option v-for="mod in modalities" :key="mod" :value="mod">{{ mod }}</option>
                    </select>
                  </td>
                  <td class="px-6 py-3 text-right">
                    <button @click="addZenodoType" :disabled="!newZType || !newZMod" class="inline-flex items-center px-3 py-1.5 border border-transparent text-[10px] font-bold uppercase tracking-wider rounded-lg text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 transition-all">
                      Add
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <!-- 3D Modality Complexity Tiers -->
        <div class="bg-indigo-900 shadow-xl shadow-indigo-900/20 overflow-hidden sm:rounded-2xl border border-indigo-700 p-6 text-white">
          <div class="flex items-start gap-4 mb-6">
             <div class="p-3 bg-indigo-500 rounded-xl">
                <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
                </svg>
             </div>
             <div>
                <h3 class="text-lg font-bold">3D Hierarchical Dependency Mapping</h3>
                <p class="text-xs text-indigo-200 font-medium">Current internal priority tiers for 3D modality detection.</p>
             </div>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div class="bg-white/5 backdrop-blur-md rounded-xl p-4 border border-white/10">
                <h4 class="text-[10px] font-bold uppercase tracking-widest text-indigo-300 mb-3">Tier 1: Robust / Self-Contained</h4>
                <div class="flex flex-wrap gap-2">
                    <span v-for="ext in configData.tiers.tier1" :key="ext" class="px-2 py-1 bg-green-500/20 text-green-300 text-[10px] font-bold rounded-md border border-green-500/30">.{{ ext }}</span>
                </div>
                <p class="mt-3 text-[10px] text-gray-400">These formats are prioritized as they carry all necessary data for visualization.</p>
            </div>

            <div class="bg-white/5 backdrop-blur-md rounded-xl p-4 border border-white/10">
                <h4 class="text-[10px] font-bold uppercase tracking-widest text-indigo-300 mb-3">Tier 2: Dependency-Heavy</h4>
                <div class="flex flex-wrap gap-2">
                    <span v-for="ext in configData.tiers.tier2" :key="ext" class="px-2 py-1 bg-yellow-500/20 text-yellow-300 text-[10px] font-bold rounded-md border border-yellow-500/30">.{{ ext }}</span>
                </div>
                <p class="mt-3 text-[10px] text-gray-400">These require sidecar files (e.g. .mtl, .bin) to be present to be considered high-quality candidates.</p>
            </div>
          </div>
        </div>

        <!-- Action Bar -->
        <div class="flex items-center justify-between p-6 bg-gray-900 rounded-2xl shadow-xl shadow-gray-900/20 text-white">
          <div class="flex items-center gap-4">
             <div class="p-2 bg-indigo-500 rounded-lg">
                <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
             </div>
             <div>
                <p class="text-xs font-bold uppercase tracking-widest text-indigo-300">Admin Controls</p>
                <p class="text-[10px] text-gray-400 font-medium">Changes affect all new LOD mapping operations.</p>
             </div>
          </div>
          <div class="flex gap-3">
            <button
                @click="resetConfig"
                :disabled="saving"
                class="px-4 py-2 text-xs font-bold uppercase tracking-wider rounded-full bg-white/10 hover:bg-white/20 transition-all border border-white/10 disabled:opacity-30"
            >
                Reset to Defaults
            </button>
            <button
              @click="saveConfig"
              :disabled="saving"
              class="flex items-center gap-2 px-6 py-2 bg-indigo-600 hover:bg-indigo-700 rounded-full transition-all text-sm font-bold shadow-lg shadow-indigo-500/50 disabled:opacity-50 group"
            >
              <svg v-if="saving" class="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <svg v-else class="h-4 w-4 group-hover:scale-110 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
              </svg>
              Save Configuration
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '@/services/api'
import { useToast } from '@/composables/useToast'

const toast = useToast()

const loading = ref(true)
const saving = ref(false)
const error = ref(null)
const successMessage = ref('')
const configData = ref({ defaults: {}, overrides: {}, combined: { extensions: {}, zenodo_types: {} }, tiers: {} })

const categories = ['3d_model', 'image', 'video', 'audio', 'document', 'data', 'other']
const modalities = ['3D', 'IMAGE', 'VIDEO', 'SOUND', 'TEXT']

const newExt = ref('')
const newExtCat = ref('')
const newZType = ref('')
const newZMod = ref('')

async function loadConfig() {
  loading.value = true
  error.value = null
  try {
    const res = await api.get('/admin/modality-config')
    if (res.success) {
      configData.value = res.data.config
    } else {
      error.value = res.error?.message || 'Failed to load configuration'
    }
  } catch (err) {
    error.value = err.message || 'Failed to load configuration'
  } finally {
    loading.value = false
  }
}

async function saveConfig() {
  saving.value = true
  successMessage.value = ''
  try {
    // Only save the overrides to the backend to keep it clean,
    // though the current edm_service.save_modality_configuration expects the whole dict.
    // We send back what we consider 'overrides'.
    const payload = configData.value.overrides
    const res = await api.post('/admin/modality-config', payload)
    if (res.success) {
      toast.success('Modality detection overrides saved!')
      successMessage.value = 'Overrides Saved!'
      setTimeout(() => successMessage.value = '', 3000)
      await loadConfig() // Refresh to get updated combined view
    } else {
      toast.error('Failed to save: ' + (res.error?.message || 'Unknown error'))
    }
  } catch (err) {
    toast.error('Error saving configuration: ' + err.message)
  } finally {
    saving.value = false
  }
}

async function resetConfig() {
  if (!confirm('Are you sure you want to reset all modality rules to system defaults? This will delete all custom overrides.')) return

  saving.value = true
  try {
    const res = await api.delete('/admin/modality-config')
    if (res.success) {
      toast.success('Reset to defaults successful')
      await loadConfig()
    } else {
      toast.error('Failed to reset: ' + (res.error?.message || 'Unknown error'))
    }
  } catch (err) {
    toast.error('Error resetting configuration: ' + err.message)
  } finally {
    saving.value = false
  }
}

function addExtension() {
  if (newExt.value && newExtCat.value) {
    const key = (newExt.value.startsWith('.') ? newExt.value.substring(1) : newExt.value).toLowerCase()
    if (!configData.value.overrides.extensions) configData.value.overrides.extensions = {}
    configData.value.overrides.extensions[key] = newExtCat.value
    // Update combined locally for immediate feedback
    configData.value.combined.extensions[key] = newExtCat.value
    newExt.value = ''
    newExtCat.value = ''
    toast.info('Extension rule added locally.')
  }
}

function removeExtension(ext) {
  if (configData.value.overrides.extensions && configData.value.overrides.extensions[ext]) {
    delete configData.value.overrides.extensions[ext]
  }
  // Revert combined to default if it exists, or delete
  if (configData.value.defaults.extensions[ext]) {
    configData.value.combined.extensions[ext] = configData.value.defaults.extensions[ext]
  } else {
    delete configData.value.combined.extensions[ext]
  }
}

function addZenodoType() {
  if (newZType.value && newZMod.value) {
    const key = newZType.value.toLowerCase()
    if (!configData.value.overrides.zenodo_types) configData.value.overrides.zenodo_types = {}
    configData.value.overrides.zenodo_types[key] = newZMod.value
    configData.value.combined.zenodo_types[key] = newZMod.value
    newZType.value = ''
    newZMod.value = ''
    toast.info('Zenodo type mapping added locally.')
  }
}

function removeZenodoType(zType) {
  if (configData.value.overrides.zenodo_types && configData.value.overrides.zenodo_types[zType]) {
    delete configData.value.overrides.zenodo_types[zType]
  }
  if (configData.value.defaults.zenodo_types[zType]) {
    configData.value.combined.zenodo_types[zType] = configData.value.defaults.zenodo_types[zType]
  } else {
    delete configData.value.combined.zenodo_types[zType]
  }
}

function addExtensionOverride(ext, cat) {
  if (!configData.value.overrides.extensions) configData.value.overrides.extensions = {}
  configData.value.overrides.extensions[ext] = cat
  toast.info(`Updated override for .${ext}`)
}

function addZenodoOverride(zType, mod) {
  if (!configData.value.overrides.zenodo_types) configData.value.overrides.zenodo_types = {}
  configData.value.overrides.zenodo_types[zType] = mod
  toast.info(`Updated override for Zenodo type: ${zType}`)
}

function isOverride(type, key) {
  return configData.value.overrides[type] && configData.value.overrides[type][key] !== undefined
}

onMounted(() => {
  loadConfig()
})
</script>

<style scoped>
.text-animate-pulse {
  animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: .5; }
}
</style>
