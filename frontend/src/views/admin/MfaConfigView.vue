<template>
  <div class="max-w-4xl mx-auto py-6 sm:px-6 lg:px-8">
    <div class="px-4 py-6 sm:px-0">
      <h1 class="text-2xl font-semibold text-gray-900 mb-2">Login MFA</h1>
      <p class="text-gray-500 mb-6">Configure provider-specific email MFA bypasses.</p>

      <div v-if="loading" class="flex justify-center py-12">
        <svg class="animate-spin h-8 w-8 text-indigo-600" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
      </div>

      <div v-else class="space-y-6">
        <div class="bg-white shadow overflow-hidden sm:rounded-lg">
          <div class="px-4 py-5 sm:px-6 border-b border-gray-200">
            <h3 class="text-lg leading-6 font-medium text-gray-900">Provider Bypass</h3>
            <p class="mt-1 text-sm text-gray-500">Skip email verification codes for configured mailbox providers.</p>
          </div>

          <div class="px-4 py-5 sm:px-6 space-y-6">
            <div class="flex items-center justify-between">
              <div>
                <label class="block text-sm font-medium text-gray-700">Enable Provider Bypass</label>
                <p class="text-xs text-gray-500">Password login succeeds immediately for addresses matching the list below.</p>
              </div>
              <button
                type="button"
                data-testid="mfa-bypass-toggle"
                @click="config.enabled = !config.enabled"
                :class="[
                  'relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2',
                  config.enabled ? 'bg-indigo-600' : 'bg-gray-200'
                ]"
              >
                <span
                  :class="[
                    'pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out',
                    config.enabled ? 'translate-x-5' : 'translate-x-0'
                  ]"
                ></span>
              </button>
            </div>

            <div>
              <label for="mfa-domains" class="block text-sm font-medium text-gray-700 mb-2">Bypassed Email Domains</label>
              <textarea
                id="mfa-domains"
                v-model="domainsText"
                data-testid="mfa-bypass-domains"
                rows="6"
                class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                placeholder="gmail.com&#10;googlemail.com"
              ></textarea>
              <p class="mt-2 text-xs text-gray-500">Enter one domain per line. Wildcards such as *.example.edu are supported for subdomains.</p>
            </div>

            <div class="rounded-md border border-amber-200 bg-amber-50 p-4">
              <p class="text-sm text-amber-800">
                This reduces login protection for matching providers. Use it for delivery-blocked providers and remove entries once mail authentication is fixed.
              </p>
            </div>

            <div class="flex justify-end space-x-3">
              <button
                type="button"
                @click="loadConfig"
                :disabled="saving"
                class="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
              >
                Reset
              </button>
              <button
                type="button"
                data-testid="mfa-bypass-save"
                @click="saveConfig"
                :disabled="saving"
                class="px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50"
              >
                {{ saving ? 'Saving...' : 'Save Configuration' }}
              </button>
            </div>
          </div>
        </div>

        <div v-if="message" :class="[
          'rounded-md p-4',
          messageType === 'success' ? 'bg-green-50' : 'bg-red-50'
        ]">
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
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import api from '@/services/api'

const loading = ref(true)
const saving = ref(false)
const message = ref('')
const messageType = ref('success')
const domainsText = ref('')

const config = reactive({
  enabled: false,
  domains: []
})

const setMessage = (text, type = 'success') => {
  message.value = text
  messageType.value = type
  setTimeout(() => {
    if (message.value === text) {
      message.value = ''
    }
  }, 4000)
}

const parseDomains = () => {
  return domainsText.value
    .split(/\n|,|;/)
    .map((domain) => domain.trim().toLowerCase())
    .filter(Boolean)
}

const syncConfig = (nextConfig) => {
  config.enabled = Boolean(nextConfig?.enabled)
  config.domains = Array.isArray(nextConfig?.domains) ? nextConfig.domains : []
  domainsText.value = config.domains.join('\n')
}

const loadConfig = async () => {
  loading.value = true
  try {
    const response = await api.get('/admin/mfa-config')
    syncConfig(response.data?.config)
  } catch (error) {
    console.error('Failed to load MFA configuration:', error)
    setMessage('Failed to load MFA configuration', 'error')
  } finally {
    loading.value = false
  }
}

const saveConfig = async () => {
  saving.value = true
  message.value = ''
  try {
    const response = await api.post('/admin/mfa-config', {
      enabled: config.enabled,
      domains: parseDomains()
    })
    syncConfig(response.data?.config)
    setMessage('MFA configuration saved successfully')
  } catch (error) {
    console.error('Failed to save MFA configuration:', error)
    setMessage(error?.error?.message || 'Failed to save MFA configuration', 'error')
  } finally {
    saving.value = false
  }
}

onMounted(loadConfig)
</script>
